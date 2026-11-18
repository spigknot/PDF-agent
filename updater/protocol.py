"""Protocolo do manifesto de atualizacao do PDFagent (schema 2, assinado).

Fonte: `src/sync_common.py` do projeto SIG Windows, adaptado para:
  - versao SEMVER (o SIG usa YYYYMMDD_NNN);
  - repositorio `spigknot/PDF-agent` e bucket R2 `pdf-agent`;
  - chave publica PROPRIA do PDFagent (a do SIG e' de outro produto).

So' usa a stdlib: a verificacao RSA e' feita com `pow(sig, e, n)`.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path, PurePosixPath

R2_PUBLIC_HOST = "pub-61758a75c3ad4f2286db8345ca22115a.r2.dev"
R2_PUBLIC_BASE = "https://" + R2_PUBLIC_HOST
MANIFEST_URL = R2_PUBLIC_BASE + "/sync_manifest.json"
GITHUB_REPO = "spigknot/PDF-agent"
USER_AGENT = "PDFagentUpdater/1.0 (+https://github.com/spigknot/PDF-agent)"

SCHEMA = 2
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_FILES = 20_000
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")

# Chave publica de verificacao (a privada nunca sai de release/).
UPDATE_PUBLIC_KEY_E = 65537
UPDATE_PUBLIC_KEY_N = 882601081394008435445055860088755883792195964077874808258744852487018270949974083277325748738898741775012104050507593321705933876846606175135137076063703360993209750635070200137455264219414536314028052592753988386327065326549929417624365180776322053602876075185981098849398855350299019838700872288607092963395476802706127301261410464295053415386370209012263696823459848077323646312169259229576149673407453604080814172115766761319328966658309855352324715299202237548306684036438691862554937325501241193637012229982854894574934973837424337528499615487879377106295124541583794989594239683193472758952702698919468661031354955385633258688485637980615665515811165243321555848400866416635192121312096699462074430697746942935965366010285417203462160342114363915414155386904658857846613623270510209915436523823582195889399494540829503774820470776931517055680404810324956611899801222304229769648028361153235859572758091280698062606593970982529416165127746393759401124283927873301823578343049342014866479733380645858641636242872040138258949444967633223005943482999386996537419411429740738765180657500828028541378171171743059747247058523880905128805219066801814104507801872406858443746995665397515091362755534404466169790565136082437761348565797

# Arquivos que o manifesto e' OBRIGADO a cobrir (layout onedir do PDFagent).
SYNC_REQUIRED_FILES = (
    "PDFagent.exe",
    "PDFagentUpdater.exe",
    "_internal/base_library.zip",
    "_internal/python311.dll",
    "_internal/VCRUNTIME140.dll",
    "_internal/VCRUNTIME140_1.dll",
)
# Top-levels que o updater gerencia (baixa e remove orfaos).
SYNC_MANAGED_TOP_LEVELS = (
    "PDFagent.exe",
    "PDFagentUpdater.exe",
    "pdfcompress.cmd",
    "pdfsplit.cmd",
    "_internal",
)
SYNC_ALLOWED_TOP_LEVELS = set(SYNC_MANAGED_TOP_LEVELS) | {"removidos.txt",
                                                          "updater.log"}


class SyncError(RuntimeError):
    pass


def version_key(version: str) -> tuple:
    """(major, minor, patch) — comparacao numerica, nao lexicografica."""
    texto = str(version or "").strip()
    if not VERSION_RE.fullmatch(texto):
        raise SyncError("versao invalida: %r" % (version,))
    return tuple(int(parte) for parte in texto.split("."))


def canonical_manifest(manifest: dict) -> bytes:
    """Bytes assinados: chaves ordenadas, sem espacos, arquivos por path."""
    files = sorted(
        (
            {
                "path": str(entry.get("path") or ""),
                "sha256": str(entry.get("sha256") or "").lower(),
                "size": int(entry.get("size") or 0),
                "drive_id": str(entry.get("drive_id") or ""),
                "github_url": str(entry.get("github_url") or ""),
            }
            for entry in (manifest.get("files") or [])
        ),
        key=lambda item: item["path"],
    )
    payload = {
        "schema": int(manifest.get("schema") or 0),
        "version": str(manifest.get("version") or ""),
        "created_at": str(manifest.get("created_at") or ""),
        "files": files,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def verify_signature(signature_b64: str, payload: bytes, *,
                     n: int = 0, e: int = 0) -> bool:
    """RSA PKCS#1 v1.5 / SHA-256 com DigestInfo, sem `cryptography`."""
    n = int(n or UPDATE_PUBLIC_KEY_N)
    e = int(e or UPDATE_PUBLIC_KEY_E)
    if not n:
        return False
    try:
        signature = base64.b64decode(str(signature_b64), validate=True)
        if not signature:
            return False
        key_size = (n.bit_length() + 7) // 8
        if len(signature) != key_size:
            return False
        encoded = pow(int.from_bytes(signature, "big"), e, n)
        encoded_bytes = encoded.to_bytes(key_size, "big")
        digest_info = (bytes.fromhex("3031300d060960864801650304020105000420")
                       + hashlib.sha256(payload).digest())
        padding_size = key_size - len(digest_info) - 3
        if padding_size < 8:
            return False
        expected = b"\x00\x01" + (b"\xff" * padding_size) + b"\x00" + digest_info
        return encoded_bytes == expected
    except (TypeError, ValueError):
        return False


def validate_manifest(manifest: dict, *, n: int = 0, e: int = 0) -> dict:
    """Valida estrutura/assinatura: {"version": str, "files": {path: entry}}."""
    if not isinstance(manifest, dict):
        raise SyncError("o manifesto nao e' um objeto JSON")
    if int(manifest.get("schema") or 0) != SCHEMA:
        raise SyncError("o manifesto nao usa o schema esperado")
    if not verify_signature(str(manifest.get("signature") or ""),
                            canonical_manifest(manifest), n=n, e=e):
        raise SyncError("o manifesto nao possui assinatura digital valida")
    version = str(manifest.get("version") or "")
    version_key(version)          # valida o formato
    raw = manifest.get("files")
    if not isinstance(raw, list) or not raw:
        raise SyncError("o manifesto nao lista arquivos")
    if len(raw) > MAX_FILES:
        raise SyncError("o manifesto excede o limite de arquivos")
    files = {}
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise SyncError("entrada %d do manifesto e' invalida" % index)
        path = str(entry.get("path") or "")
        if not path or path.startswith("/") or ".." in path.split("/"):
            raise SyncError("caminho invalido no manifesto: %r" % (path,))
        if path.split("/", 1)[0] not in SYNC_ALLOWED_TOP_LEVELS:
            continue                  # componente novo: ignorar (forward-compat)
        if path in files:
            raise SyncError("caminho duplicado no manifesto: %s" % path)
        sha256 = str(entry.get("sha256") or "").lower()
        if len(sha256) != 64 or any(c not in "0123456789abcdef" for c in sha256):
            raise SyncError("hash invalido no manifesto para: %s" % path)
        size = int(entry.get("size") or 0)
        if size < 0:
            raise SyncError("tamanho invalido no manifesto para: %s" % path)
        url = str(entry.get("github_url") or "").strip()
        parsed = urllib.parse.urlparse(url)
        ok_github = (parsed.hostname == "github.com"
                     and parsed.path.startswith("/" + GITHUB_REPO + "/releases/download/"))
        ok_r2 = parsed.hostname == R2_PUBLIC_HOST and parsed.path.startswith("/")
        if parsed.scheme != "https" or not (ok_github or ok_r2):
            raise SyncError("URL de download invalida no manifesto para: %s" % path)
        files[path] = {"sha256": sha256, "size": size, "drive_id": "",
                       "github_url": url}
    missing = [rel for rel in SYNC_REQUIRED_FILES if rel not in files]
    if missing:
        raise SyncError("o manifesto nao cobre componentes obrigatorios: "
                        + ", ".join(missing))
    return {"version": version, "files": files}


def parse_manifest_bytes(payload: bytes) -> dict:
    if len(payload) > MAX_MANIFEST_BYTES:
        raise SyncError("o manifesto excede o tamanho maximo")
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SyncError("manifesto ilegivel: %s" % exc) from exc


def fetch_manifest(url: str = MANIFEST_URL, timeout: int = 30) -> dict:
    """Busca e valida o manifesto publicado no R2."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read(MAX_MANIFEST_BYTES + 1)
    return validate_manifest(parse_manifest_bytes(payload))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def classify_files(target: Path, files: dict) -> dict:
    """{download, remove, unchanged, total} da instalacao local vs manifesto."""
    target = Path(target).resolve()
    download = []
    unchanged = 0
    for path, entry in sorted(files.items()):
        local = target / Path(*PurePosixPath(path).parts)
        if not local.is_file():
            download.append(path)
            continue
        if local.stat().st_size != int(entry["size"]):
            download.append(path)
            continue
        if sha256_file(local) != entry["sha256"]:
            download.append(path)
            continue
        unchanged += 1
    managed = set()
    for top in SYNC_MANAGED_TOP_LEVELS:
        candidate = target / Path(*PurePosixPath(top).parts)
        if candidate.is_file():
            managed.add(top)
        elif candidate.is_dir():
            for local in candidate.rglob("*"):
                if local.is_file():
                    managed.add(local.relative_to(target).as_posix())
    remove = sorted(path for path in managed if path not in files)
    return {"download": download, "remove": remove,
            "unchanged": unchanged, "total": len(files)}
