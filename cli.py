"""Despachante de subcomandos do PDFagent.

REGRA PARA NOVAS FUNÇÕES (ver docs/COMANDOS.md):
 1. crie `comandos/<nome>.py` com `main(argv) -> int|None` (None = sucesso);
 2. registre em COMMANDS com `help`, `alvo` e `shim`;
 3. o shim `.cmd` (ex.: pdfsplit.cmd) é gerado por scripts/gerar_shims.py.
"""
import os
import sys

#: nome do comando -> metadados. `alvo` = (módulo, função).
COMMANDS = {
    "compress": {
        "help": "comprime PDFs nos 3 níveis (extreme | recommended | low)",
        "alvo": ("compress", "main"),
        "shim": "pdfcompress",
    },
    "split": {
        "help": "divide um PDF em partes por limite de tamanho (comprime antes)",
        "alvo": ("commands.split", "main"),
        "shim": "pdfsplit",
    },
    "gui": {
        "help": "abre a interface gráfica (padrão quando não há argumentos)",
        "alvo": ("app", "run_gui"),
        "shim": None,
    },
}

SINONIMOS = {"comprimir": "compress", "compress": "compress"}


def _ajuda(arquivo=None):
    arquivo = arquivo or sys.stdout
    arquivo.write("PDFagent — compressor/utilitários de PDF\n\n")
    arquivo.write("uso: PDFagent <comando> [opções]   |   PDFagent <arquivo.pdf> [opções]\n\n")
    arquivo.write("comandos:\n")
    for nome, meta in COMMANDS.items():
        arquivo.write("  %-10s %s\n" % (nome, meta["help"]))
    arquivo.write("\nOutros: --version, --help\n")
    arquivo.write("Sem argumentos abre a GUI. Para o menu de contexto, "
                  "`PDFagent --in-place -n recommended --avisar arquivo.pdf` "
                  "continua funcionando (vai para compress).\n")
    return 0


def _executa(nome, args):
    modulo, funcao = COMMANDS[nome]["alvo"]
    try:
        importar = __import__(modulo, fromlist=[funcao])
        alvo = getattr(importar, funcao)
    except Exception as ex:  # pragma: no cover
        print("comando %r indisponível: %s" % (nome, ex), file=sys.stderr)
        return 3
    resultado = alvo(args)
    return 0 if resultado is None else int(resultado)


def _parece_entrada(texto):
    """Heurística de retrocompatibilidade: primeiro argumento é um caminho/flag."""
    if texto.startswith("-"):
        return True          # -n/--nivel/--in-place/--avisar/--saida-dir...
    if texto.lower().endswith(".pdf"):
        return True
    return os.path.exists(texto)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        return _executa("gui", [])
    primeiro = argv[0]
    if primeiro in ("-h", "--help", "help", "/?"):
        return _ajuda()
    if primeiro in ("-V", "--version"):
        import compress
        print("PDFagent %s" % compress.VERSAO)
        return 0
    comando = SINONIMOS.get(primeiro, primeiro)
    if comando in COMMANDS:
        return _executa(comando, argv[1:])
    # retrocompatibilidade: `PDFagent entrada.pdf -n low` e o menu de contexto
    if _parece_entrada(primeiro):
        return _executa("compress", argv)
    print("comando desconhecido: %s" % primeiro, file=sys.stderr)
    return _ajuda(sys.stderr) or 2


if __name__ == "__main__":
    sys.exit(main())
