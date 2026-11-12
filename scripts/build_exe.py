"""Gera dist/PDFagent.exe (onefile, GUI + modo linha de comando).

Uso:  python scripts/build_exe.py [--debug]
Sem --debug: janela (GUI) e sem console; com argumentos o proprio .exe
anexa o console do pai e funciona como CLI (PDFagent.exe in.pdf -n low).
"""
import os
import subprocess
import sys
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(RAIZ, "app.py")
NOME = "PDFagent"


def main(argv):
    debug = "--debug" in argv
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--onefile",
        "--name", NOME,
        "--distpath", os.path.join(RAIZ, "dist"),
        "--workpath", os.path.join(RAIZ, "build"),
        "--specpath", os.path.join(RAIZ, "build"),
        # binarios/dados das libs: pikepdf traz libqpdf; pymupdf traz o MuPDF.
        # O collect-all do pymupdf puxa os modulos de ML dele (features/layout),
        # que arrastam torch+onnxruntime — excluidos explicitamente.
        "--collect-all", "pikepdf",
        "--collect-all", "pymupdf",
        "--exclude-module", "torch",
        "--exclude-module", "onnxruntime",
        "--exclude-module", "pymupdf.features",
        "--exclude-module", "pymupdf.layout",
        "--hidden-import", "fitz",
        "--collect-submodules", "fontTools",
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

    exe = os.path.join(RAIZ, "dist", NOME + (".exe" if os.name == "nt" else ""))
    if not os.path.exists(exe):
        print("FALHOU: %s nao foi gerado" % exe)
        return 1
    print("\nOK: %s (%.1f MB) em %.0fs"
          % (exe, os.path.getsize(exe) / 1048576, time.time() - t0))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
