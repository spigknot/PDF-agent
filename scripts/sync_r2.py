#!/usr/bin/env python3
"""Publica a pasta onedir no Cloudflare R2 (S3) e gera o sync_manifest.json.

Uso:
    py -3.11 scripts/sync_r2.py --package dist/PDFagent --version 1.1.0
    py -3.11 scripts/sync_r2.py --package dist/PDFagent --version 1.1.0 --dry-run
    py -3.11 scripts/sync_r2.py --package dist/PDFagent --version 1.1.0 --prune

Logica portada de `D:\\Projetos\\SIG Windows\\scripts\\sync_r2.py`:
  - snapshot do pacote (sha256 + tamanho por arquivo);
  - diferenca por ETag/MD5 contra o bucket (sobe SO' o que mudou);
  - manifesto schema 2 assinado (RSA PKCS#1 v1.5/SHA-256) na raiz do bucket.

Credenciais em release/r2_config.json (NUNCA commitar).
O `canonical_manifest` vem de `updater/protocol.py`: publicador e app assinam/
verificam exatamente os mesmos bytes.
"""
import argparse
import base64
import hashlib
import json
import pathlib
import sys
import time

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from updater.protocol import canonical_manifest  # noqa: E402

KEY_PATH = RAIZ / "release" / "update_private_key.pem"
CONFIG_PATH = RAIZ / "release" / "r2_config.json"

# Componentes que NAO entram no manifesto (mas podem estar no pacote).
SYNC_EXCLUDED_TOP_LEVEL: set[str] = set()


def snapshot(package: pathlib.Path) -> dict:
    """{caminho_relativo: {"sha256", "size"}} do pacote onedir."""
    files = {}
    for path in sorted(package.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if not path.is_file():
            continue
        relative = path.relative_to(package).as_posix()
        if relative.split("/", 1)[0] in SYNC_EXCLUDED_TOP_LEVEL:
            continue
        # Nunca publicar cache local: varia por maquina e, se sumir do pacote,
        # o diff geraria remocao de arquivo que o updater nao gerencia.
        if "__pycache__" in relative.split("/") or relative.endswith(".pyc"):
            continue
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        files[relative] = {"sha256": digest.hexdigest(),
                           "size": path.stat().st_size}
    return files


def sign_manifest(manifest: dict) -> None:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    if not KEY_PATH.is_file():
        raise SystemExit("chave privada de atualizacao nao encontrada: %s" % KEY_PATH)
    private_key = serialization.load_pem_private_key(KEY_PATH.read_bytes(), password=None)
    signature = private_key.sign(canonical_manifest(manifest), padding.PKCS1v15(),
                                 hashes.SHA256())
    manifest["signature"] = base64.b64encode(signature).decode("ascii")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--package", required=True, help="pasta onedir (ex.: dist/PDFagent)")
    ap.add_argument("--version", required=True, help="versao semver (ex.: 1.1.0)")
    ap.add_argument("--quiet", action="store_true", help="so' o resumo")
    ap.add_argument("--dry-run", action="store_true", help="nao sobe nada; lista o diff")
    ap.add_argument("--prune", action="store_true",
                    help="apaga do bucket o que nao esta no snapshot")
    args = ap.parse_args()

    if not CONFIG_PATH.is_file():
        raise SystemExit("release/r2_config.json nao encontrado (credenciais do R2)")
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    package = pathlib.Path(args.package)
    if not package.is_dir():
        raise SystemExit("pasta do pacote nao encontrada: %s" % package)

    files = snapshot(package)
    if not args.quiet:
        print("pacote: %d arquivos" % len(files))

    import boto3

    s3 = boto3.client(
        "s3",
        endpoint_url=cfg["endpoint"],
        aws_access_key_id=cfg["access_key_id"],
        aws_secret_access_key=cfg["secret_access_key"],
        region_name="auto",
    )
    bucket = cfg["bucket"]
    public_base = cfg["public_base"].rstrip("/")

    def _md5(path: pathlib.Path) -> str:
        digest = hashlib.md5()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    remote_etags = {}
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket):
        for obj in page.get("Contents", []):
            remote_etags[str(obj["Key"])] = str(obj.get("ETag") or "").strip('"')

    to_upload = {}
    for path, entry in files.items():
        if remote_etags.get(path) != _md5(package / path):
            to_upload[path] = entry
    orfaos = sorted(set(remote_etags) - set(files) - {"sync_manifest.json"})

    if not args.quiet:
        print("subir: %d | orfaos no bucket: %d" % (len(to_upload), len(orfaos)))
    if args.dry_run:
        for path in sorted(to_upload)[:20]:
            print("  +", path)
        for path in orfaos[:20]:
            print("  -", path)
        print("[dry-run] nada foi enviado")
        return 0

    for index, path in enumerate(sorted(to_upload), 1):
        with (package / path).open("rb") as handle:
            s3.put_object(Bucket=bucket, Key=path, Body=handle)
        if not args.quiet and (index % 25 == 0 or index == len(to_upload)):
            print("  upload %d/%d" % (index, len(to_upload)))
    if not args.quiet:
        print("upload concluido")

    if args.prune:
        for key in orfaos:
            s3.delete_object(Bucket=bucket, Key=key)
            if not args.quiet:
                print("  - removido", key)

    manifest = {
        "schema": 2,
        "version": args.version,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "files": [
            {
                "path": path,
                "sha256": entry["sha256"],
                "size": entry["size"],
                "drive_id": "",
                "github_url": "%s/%s" % (public_base, path),
            }
            for path, entry in sorted(files.items())
        ],
    }
    sign_manifest(manifest)
    body = json.dumps(manifest, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    s3.put_object(Bucket=bucket, Key="sync_manifest.json", Body=body,
                  ContentType="application/json")
    if args.quiet:
        print("PASS: sync-r2 version=%s uploaded=%d unchanged=%d manifest=sync_manifest.json"
              % (args.version, len(to_upload), len(files) - len(to_upload)))
    else:
        print("sync_manifest.json publicado no R2")
    return 0


if __name__ == "__main__":
    sys.exit(main())
