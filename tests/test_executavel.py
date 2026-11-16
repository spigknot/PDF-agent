"""Executavel: quando o pool de PROCESSOS pode rodar.

O .exe (PyInstaller) rodava TUDO em serie porque `freeze_support()` nunca era
chamado e todos os pools tinham `not getattr(sys, "frozen", False)` — 111,8 s
contra 62,1 s do CLI. Agora o entrypoint chama `freeze_support()` e a decisao
ficou em `_pode_processo()`, com o PORTATIL (onefile) fora: nele cada worker
reextrai o bundle (~2,6 s por processo).
"""
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
import compress  # noqa: E402


def test_fora_do_executavel_pode_processo():
    assert compress._portatil_onefile() is False
    os.environ.pop("PDFAGENT_PROC_OFF", None)
    assert compress._pode_processo() is True


def test_knob_desliga_tudo():
    os.environ["PDFAGENT_PROC_OFF"] = "1"
    try:
        assert compress._pode_processo() is False
    finally:
        os.environ.pop("PDFAGENT_PROC_OFF", None)
    assert compress._pode_processo() is True


def test_entrypoint_chama_freeze_support():
    """Sem isso, cada worker do .exe abriria a GUI em vez de rodar a tarefa."""
    with open(os.path.join(RAIZ, "app.py"), encoding="utf-8", errors="replace") as f:
        fonte = f.read()
    assert "freeze_support()" in fonte, "app.py tem de chamar freeze_support()"


def main():
    falhas = 0
    for nome in sorted(n for n in globals() if n.startswith("test_")):
        try:
            globals()[nome]()
            print("  ok    %s" % nome)
        except AssertionError as ex:
            falhas += 1
            print("  FALHA %s: %s" % (nome, ex))
    print("TUDO OK" if not falhas else "%d falha(s)" % falhas)
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
