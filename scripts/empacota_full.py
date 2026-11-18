"""Gera dist/PDFagent-onedir-<versao>.zip (pacote completo para reparo).

E' o asset que o updater aplica com `--zip`/`--full` quando o diff nao serve
(instalacao corrompida, maquina nova, versao muito antiga).
"""
import pathlib
import sys
import zipfile

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
import compress  # noqa: E402


def main() -> int:
    origem = RAIZ / "dist" / "PDFagent"
    if not origem.is_dir():
        print("ERRO: dist/PDFagent nao existe — rode scripts/build_exe.py antes")
        return 1
    destino = RAIZ / "dist" / ("PDFagent-onedir-%s.zip" % compress.VERSAO)
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for path in sorted(origem.rglob("*")):
            if path.is_file():
                z.write(path, path.relative_to(origem).as_posix())
    print("OK: %s (%.1f MB)" % (destino, destino.stat().st_size / 1e6))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
