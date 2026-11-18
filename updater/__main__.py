"""Entrypoint do PDFagentUpdater.exe (PyInstaller)."""
import sys

from updater.apply import main

if __name__ == "__main__":
    sys.exit(main())
