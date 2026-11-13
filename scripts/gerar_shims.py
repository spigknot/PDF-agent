"""Gera os shims .cmd de cada subcomando (para o PATH).

Lê cli.COMMANDS e escreve, em `dist/PDFagent/`, um `.cmd` por comando com
`shim` definido:

    pdfcompress.cmd  ->  "%~dp0PDFagent.exe" compress %*

Assim cada função tem um "executável" próprio no PATH gastando ~40 bytes, sem
duplicar dependências. Rodar depois do build onedir (scripts/build_exe.py).
"""
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
import cli  # noqa: E402

MODELO = """@echo off
rem gerado por scripts/gerar_shims.py - nao editar
"%~dp0PDFagent.exe" {comando} %*
"""


def main(argv=None):
    destino = os.path.join(RAIZ, "dist", "PDFagent")
    if not os.path.isdir(destino):
        print("build onedir ausente em %s — rode scripts/build_exe.py" % destino)
        return 1
    feitos = []
    for nome, meta in cli.COMMANDS.items():
        shim = meta.get("shim")
        if not shim:
            continue
        caminho = os.path.join(destino, shim + ".cmd")
        with open(caminho, "w", encoding="ascii", newline="\r\n") as f:
            f.write(MODELO.format(comando=nome))
        feitos.append(shim + ".cmd")
    print("shims: %s" % (", ".join(feitos) or "nenhum"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
