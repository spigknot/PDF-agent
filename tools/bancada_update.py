"""Bancada: faz o MESMO caminho do app (manifesto -> diff -> updater real).

Uso: py -3.11 tools/bancada_update.py <target_instalado>
Nao abre a GUI: baixa os arquivos, valida sha256 e chama o PDFagentUpdater.exe.
"""
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from updater import protocol  # noqa: E402


def main() -> int:
    alvo = Path(sys.argv[1] if len(sys.argv) > 1
                else Path.home() / "AppData/Local/Programs/PDFagent")
    estado = protocol.fetch_manifest()
    plano = protocol.classify_files(alvo, estado["files"])
    print("manifesto %s | %d a baixar | %d iguais | %d orfaos"
          % (estado["version"], len(plano["download"]), plano["unchanged"],
             len(plano["remove"])))
    if not plano["download"]:
        print("nada a fazer")
        return 0
    raiz = Path(tempfile.mkdtemp(prefix="bancada-upd-"))
    staged = raiz / "staged"
    for caminho in plano["download"]:
        destino = staged / caminho
        destino.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(estado["files"][caminho]["github_url"],
                                     headers={"User-Agent": protocol.USER_AGENT})
        with urllib.request.urlopen(req, timeout=120) as resp, \
                open(destino, "wb") as saida:
            shutil.copyfileobj(resp, saida, 1024 * 1024)
        assert protocol.sha256_file(destino) == estado["files"][caminho]["sha256"]
        print("  baixado + sha256 ok:", caminho)
    removals = raiz / "removals.txt"
    removals.write_text("\n".join(plano["remove"]), encoding="utf-8")
    updater = alvo / "PDFagentUpdater.exe"
    rc = subprocess.call([str(updater), "--sync-staged", str(staged),
                          "--sync-removals", str(removals),
                          "--sync-version", estado["version"],
                          "--target", str(alvo), "--pid", "0",
                          "--log", str(alvo / "updater.log")])
    print("updater rc=%d" % rc)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
