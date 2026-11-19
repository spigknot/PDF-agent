"""Rótulo do check de atualização: "verificando…" não pode ficar na tela.

Bug real (1.3.3): ao clicar em "Verificar atualizações", o `update_fim` só
religava o flag `_update_checando` — o texto "verificando…" ficava para sempre
quando o app já estava na versão nova (ou quando o check dava erro).
"""
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)


def _app(monkeypatch_aviso=None):
    import app as appmod
    from tkinter import messagebox

    if monkeypatch_aviso is not None:
        messagebox.showinfo = lambda *a, **k: monkeypatch_aviso.append(a)
        messagebox.showerror = lambda *a, **k: monkeypatch_aviso.append(a)
    ui = appmod.App()
    ui.withdraw()
    return ui


def test_aviso_limpa_o_verificando():
    avisos = []
    ui = _app(avisos)
    try:
        ui.lbl_update.configure(text="verificando…")
        ui.fila.put(("aviso", "Você já está na versão mais nova (1.3.4)."))
        ui._drena()
        assert ui.lbl_update.cget("text") == ""
        assert avisos, "o aviso ainda precisa aparecer"
    finally:
        ui.destroy()


def test_update_fim_limpa_o_verificando():
    ui = _app([])
    try:
        ui.lbl_update.configure(text="verificando…")
        ui.fila.put(("update_fim", None))
        ui._drena()
        assert ui.lbl_update.cget("text") == ""
        assert ui._update_checando is False
    finally:
        ui.destroy()


def test_update_fim_nao_apaga_a_oferta():
    """Se veio oferta, o rótulo é o "N arquivo(s) a baixar" — não pode zerar."""
    ui = _app([])
    try:
        ui.fila.put(("update", {"versao": "1.3.4",
                                "files": {"a": {"sha256": "x", "size": 1}},
                                "download": ["a"], "remove": []}))
        ui.fila.put(("update_fim", None))
        ui._drena()
        assert "arquivo(s) a baixar" in ui.lbl_update.cget("text")
    finally:
        ui.destroy()


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
