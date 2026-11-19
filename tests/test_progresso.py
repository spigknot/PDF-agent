"""Janela única do --avisar: pergunta (limite + comprimir), progresso e console.

Três defeitos reais que estes testes travam:

1. `.exe` é `--windowed`; vindo do Explorer (sem console pai) CADA worker de
   multiprocessing abria uma janela `conhost` — 22 janelinhas piscando numa
   compressão. `_console_oculta()` aloca UMA console escondida e os filhos a
   herdam.
2. o `--avisar` só mostrava um MessageBox no fim; agora é UMA janela com fase,
   barra e cronômetro congelado no fim, em comprimir E dividir.
3. o dividir comprimia sozinho e não perguntava nada. Agora pergunta o limite
   (1 casa, 1,7 MB, piso de 1 MB) e a caixa "Comprimir" vem DESMARCADA;
   marcada, aparecem low/recommended/extreme.
"""
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)


def _fonte(nome):
    with open(os.path.join(RAIZ, nome), encoding="utf-8") as fh:
        return fh.read()


# -- console oculta ---------------------------------------------------------

def test_console_oculta_existe_e_e_chamada_no_entrypoint():
    assert "_console_oculta" in _fonte("compress.py")
    assert "compress._console_oculta()" in _fonte("app.py"), \
        "app.py precisa chamar _console_oculta() antes de criar pools"


def test_console_oculta_nao_faz_nada_fora_do_executavel():
    import compress
    compress._console_oculta()          # sem frozen: no-op, não pode explodir


# -- formatação / fases -----------------------------------------------------

def test_fracao_por_fase():
    import progresso
    assert progresso._fracao("[3] recomprimindo imagens") == 0.55
    assert progresso._fracao("[6] finalizando") == 1.0
    assert progresso._fracao("[1] lendo") == 0.04
    assert progresso._fracao("linha qualquer") is None


def test_fmt_do_cronometro():
    import progresso
    assert progresso._fmt(3.94) == "3.9 s"
    assert progresso._fmt(63.25) == "1:03.2"
    assert progresso._fmt(3725.0) == "1:02:05"


# -- ligações nos comandos --------------------------------------------------

def test_comprimir_usa_a_janela_e_nao_messagebox():
    fonte = _fonte("compress.py")
    assert "progresso.executar(" in fonte
    # o aviso antigo (MessageBox no fim do --in-place) não pode voltar
    assert '_aviso("PDFagent", msg' not in fonte


def test_dividir_pergunta_limite_e_nao_comprime_sozinho():
    fonte = _fonte("commands/split.py")
    assert "progresso.executar(" in fonte
    assert "pedir_limite=" in fonte
    assert "comprimir_inicial=False" in fonte, \
        "a caixa Comprimir precisa vir desmarcada no app"
    # a compressão (quando marcada) alimenta a mesma janela: fase/barra
    assert "compress.comprimir(entrada, tmp, nivel, log=log)" in fonte


# -- diálogo do dividir -----------------------------------------------------

def test_dialogo_pergunta_com_padroes_certos():
    import progresso
    janela = progresso.Janela(subtitulo="x.pdf", pedir_limite=1.7)
    try:
        assert janela.var_limite.get() == "1.7"
        assert janela.var_comprimir.get() is False
        assert janela.var_nivel.get() == "recommended"
        assert janela.frame_niveis.winfo_manager() == "", \
            "os níveis só aparecem depois de marcar Comprimir"
        janela.chk.invoke()
        assert janela.frame_niveis.winfo_manager() == "pack"
        janela._confirma()
        assert janela.pedido == {"limite_mb": 1.7, "comprimir": True,
                                 "nivel": "recommended"}
    finally:
        janela.raiz.destroy()


def test_dialogo_recusa_limite_absurdo():
    import progresso
    janela = progresso.Janela(subtitulo="x.pdf", pedir_limite=1.7)
    try:
        for valor in ("0.5", "0,2", "abc", "99999"):
            janela.var_limite.set(valor)
            janela._confirma()
            assert janela.pedido is None, "aceitou limite inválido: %s" % valor
            assert "inválido" in janela.lbl_msg.cget("text")
        janela.var_limite.set("1,0")       # vírgula pt-BR no piso: vale
        janela._confirma()
        assert janela.pedido["limite_mb"] == 1.0
    finally:
        janela.raiz.destroy()


def test_janela_executa_congela_e_devolve_codigo():
    """Abre a janela de verdade, roda um trabalho curto e fecha sozinha."""
    import progresso

    janela = progresso.Janela(subtitulo="x.pdf")
    janela.raiz.after(400, janela._fechar)      # já não está ocupada: fecha

    def trabalho(log):
        log("[3] recomprimindo imagens")
        return True, "1 -> 2 bytes"

    assert janela.executa(trabalho) == 0
    assert janela.tempo_total is not None, "o cronômetro precisa congelar no fim"


def main():
    falhas = 0
    for nome, funcao in sorted(globals().items()):
        if nome.startswith("test_") and callable(funcao):
            try:
                funcao()
                print("  ok    %s" % nome)
            except AssertionError as ex:
                falhas += 1
                print("  FALHA %s: %s" % (nome, ex))
    print("TUDO OK" if not falhas else "%d falha(s)" % falhas)
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
