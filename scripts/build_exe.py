"""Empacota o PDFagent.

Modos:
  python scripts/build_exe.py            # ambos (padrao)
  python scripts/build_exe.py --onedir   # so a pasta (instalador; start ~0,3 s)
  python scripts/build_exe.py --onefile  # so o .exe portatil (start ~2,6 s)

Saidas:
  dist/PDFagent/PDFagent.exe   pasta com _internal (o instalador leva esta)
  dist/PDFagent.exe            onefile portatil, sem instalacao
  dist/PDFagent/*.cmd          shims de cada subcomando (gerar_shims.py)
"""
import os
import subprocess
import sys
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(RAIZ, "app.py")
NOME = "PDFagent"


def _build(onedir=False, debug=False):
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--onedir" if onedir else "--onefile",
        "--name", NOME,
        "--distpath", os.path.join(RAIZ, "dist"),
        "--workpath", os.path.join(RAIZ, "build"),
        "--specpath", os.path.join(RAIZ, "build"),
        # binarios/dados das libs: pikepdf traz libqpdf; pymupdf traz o MuPDF.
        # NAO usar --collect-all pymupdf: ele puxa pymupdf/layout/resources/onnx
        # (~41 MB de modelos que o app nunca usa) + mupdf-devel (.lib/.h).
        # --collect-binaries leva so as DLLs (_mupdf, mupdfcpp64, _tgif...).
        "--collect-all", "pikepdf",
        "--collect-binaries", "pymupdf",
        "--collect-submodules", "pymupdf",
        "--exclude-module", "torch",
        "--exclude-module", "onnxruntime",
        "--exclude-module", "pymupdf.features",
        "--exclude-module", "pymupdf.layout",
        # nao usados pelo app; vinham arrastados pelo grafo de importacao
        "--exclude-module", "sympy",
        "--exclude-module", "mpmath",
        "--exclude-module", "pygments",
        "--exclude-module", "_pytest",
        "--exclude-module", "pytest",
        "--exclude-module", "IPython",
        # Pillow: nao decodificamos AVIF (4,2 MB de plugin)
        "--exclude-module", "PIL._avif",
        "--hidden-import", "fitz",
        # `app` e' carregado dinamicamente pelo cli.py (__import__) e, como o
        # entrypoint do PyInstaller vira __main__, sem isto o .exe instalado
        # responde "comando 'gui' indisponivel: No module named 'app'".
        "--hidden-import", "app",
        "--hidden-import", "progresso",
        "--collect-submodules", "fontTools",
        # comandos sao carregados dinamicamente pelo cli.py (__import__)
        "--collect-submodules", "commands",
        APP,
    ]
    cmd.insert(4, "--console" if debug else "--windowed")

    os.makedirs(os.path.join(RAIZ, "build"), exist_ok=True)
    print("PyInstaller: %s" % " ".join(cmd[2:6]))
    t0 = time.time()
    r = subprocess.run(cmd, cwd=RAIZ)
    if r.returncode != 0:
        print("FALHOU (rc=%d)" % r.returncode)
        return r.returncode

    exe = (os.path.join(RAIZ, "dist", NOME, NOME + ".exe") if onedir
           else os.path.join(RAIZ, "dist", NOME + (".exe" if os.name == "nt" else "")))
    if not os.path.exists(exe):
        print("FALHOU: %s nao foi gerado" % exe)
        return 1
    print("\nOK: %s (%.1f MB) em %.0fs"
          % (exe, os.path.getsize(exe) / 1048576, time.time() - t0))
    return 0


def _copia_updater():
    """Leva o PDFagentUpdater.exe para dentro do onedir (o instalador embarca
    a pasta inteira e o manifesto do R2 cobra esse arquivo) e escreve o
    build-info.json, que e' de onde o updater le a versao instalada."""
    import json
    import shutil
    import time

    exe = os.path.join(RAIZ, "dist", "PDFagentUpdater.exe")
    if not os.path.isfile(exe):
        print("ERRO: falta dist/PDFagentUpdater.exe — rode scripts/build_updater.py antes")
        return 1
    destino = os.path.join(RAIZ, "dist", "PDFagent", "PDFagentUpdater.exe")
    shutil.copy2(exe, destino)
    print("updater copiado para %s" % destino)
    # versao sem importar compress (o script roda de scripts/, sem o repo no path)
    import re

    with open(os.path.join(RAIZ, "compress.py"), encoding="utf-8") as f:
        m = re.search(r'^VERSAO = "([^"]+)"', f.read(), re.M)
    versao = m.group(1) if m else "0.0.0"

    info = os.path.join(RAIZ, "dist", "PDFagent", "build-info.json")
    with open(info, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"version": versao,
                   "built_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")},
                  f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("build-info.json: versao %s" % versao)
    return 0


def main(argv):
    so_onedir = "--onedir" in argv
    so_onefile = "--onefile" in argv
    quer_onedir = so_onedir or not so_onefile
    quer_onefile = so_onefile or not so_onedir
    debug = "--debug" in argv
    ok = True
    if quer_onedir:
        ok = (_build(True, debug) == 0) and ok
        if ok:
            ok = (_copia_updater() == 0) and ok
        if ok:
            subprocess.run([sys.executable,
                            os.path.join(RAIZ, "scripts", "gerar_shims.py")], cwd=RAIZ)
    if quer_onefile:
        ok = (_build(False, debug) == 0) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
