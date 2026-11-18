"""Empacota o PDFagentUpdater.exe (onefile, sem console) em dist/."""
import pathlib
import subprocess
import sys

RAIZ = pathlib.Path(__file__).resolve().parent.parent


def main() -> int:
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--onefile", "--windowed", "--noupx",
        "--name", "PDFagentUpdater",
        "--distpath", str(RAIZ / "dist"),
        "--workpath", str(RAIZ / "build" / "updater"),
        "--specpath", str(RAIZ / "build"),
        "--paths", str(RAIZ),
        str(RAIZ / "updater" / "__main__.py"),
    ]
    print(" ".join(cmd))
    rc = subprocess.call(cmd, cwd=str(RAIZ))
    if rc == 0:
        exe = RAIZ / "dist" / "PDFagentUpdater.exe"
        print("OK: %s (%.1f MB)" % (exe, exe.stat().st_size / 1e6))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
