"""O item único do menu de contexto tem de abrir a tela única (comprimir|dividir).

Cadeia: HKCU\\...\\shell\\PDFagent\\command (gravada pelo .iss, SEM submenu) →
`cli.main` → `commands.menu.main` → telas (escolha/comprimir/dividir) →
`compress._in_place` / `commands.split.dividir` (motores inalterados).

Se o registro voltar a ter submenu, o `menu` sumir do cli ou a tela deixar
de delegar aos motores, estes testes pegam antes do release.
"""
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)


def _fonte(nome):
    with open(os.path.join(RAIZ, nome), encoding="utf-8") as fh:
        return fh.read()


def test_registro_e_item_unico_sem_submenu():
    iss = _fonte("instalador/PDFagent.iss")
    comandos = [l.strip() for l in iss.splitlines()
                if "shell\\PDFagent\\command" in l]
    assert comandos, "sem chave de comando único no .iss"
    linha = comandos[0]
    assert '{app}\\{#Exe}' in linha
    assert '" menu ""%1""' in linha, linha
    # item único: nenhum comando de submenu; a era com-submenu vira deletekey
    assert "shell\\comprimir\\command" not in iss
    assert "shell\\dividir\\command" not in iss
    assert "shell\\PDFagent\\shell\\comprimir" in iss  # migração deletekey
    assert "deletekey" in iss
    # o comando único não fixa nível nem modo: a tela pergunta
    assert "--in-place" not in linha and "--avisar" not in linha \
        and "-n " not in linha


def test_cli_despacha_menu_para_o_modulo_certo():
    import cli

    assert cli.COMMANDS["menu"]["alvo"] == ("commands.menu", "main")
    assert cli.COMMANDS["menu"]["shim"] is None


def test_tela_tem_as_tres_telas_e_os_dois_botoes():
    fonte = _fonte("commands/menu.py")
    for tela in ("_tela_escolha", "_tela_comprimir", "_tela_dividir",
                 "_tela_progresso", "_vai_comprimir", "_vai_dividir"):
        assert tela in fonte, "tela ausente: %s" % tela
    assert "Comprimir" in fonte and "Dividir" in fonte
    assert "btn_comprimir.png" in fonte and "btn_dividir.png" in fonte
    assert os.path.exists(os.path.join(RAIZ, "assets", "btn_comprimir.png"))
    assert os.path.exists(os.path.join(RAIZ, "assets", "btn_dividir.png"))


def test_limite_padrao_1_6_e_validacao():
    from commands import menu

    assert menu.valida_limite_mb("1,6") == 1.6
    assert menu.valida_limite_mb("1.6") == 1.6
    assert menu.valida_limite_mb("1,0") == 1.0
    for ruim in ("0.5", "0,2", "abc", "99999", ""):
        try:
            menu.valida_limite_mb(ruim)
        except ValueError:
            continue
        raise AssertionError("aceitou limite inválido: %r" % ruim)


def test_executar_delega_aos_motores():
    import compress
    from commands import menu
    from commands import split as splitmod

    chamadas = {}
    salva_in_place, salva_dividir = compress._in_place, splitmod.dividir
    try:
        compress._in_place = lambda entradas, args, log=None: chamadas.update(
            via="in_place", entradas=entradas, nivel=args.nivel) or (True, "ok")

        def falso_dividir(entrada, limite, comprimir=True, nivel="recommended",
                          destino=None, log=print):
            chamadas.update(via="dividir", limite=limite,
                            comprimir=comprimir, nivel=nivel)
            return {"partes": [], "comprimido": None, "precisa_dividir": False,
                    "total_antes": 1, "total_depois": 1}

        splitmod.dividir = falso_dividir
        ok, _ = menu.executar_compressao("a.pdf", "low", lambda m: None)
        assert ok and chamadas["via"] == "in_place" \
            and chamadas["nivel"] == "low"
        ok, msg = menu.executar_divisao("a.pdf", 1.6, False, "recommended",
                                        lambda m: None)
        assert ok and chamadas["via"] == "dividir" \
            and chamadas["limite"] == int(round(1.6 * 1048576)) \
            and chamadas["comprimir"] is False
        assert "1,6" in msg or "1.6" in msg
    finally:
        compress._in_place, splitmod.dividir = salva_in_place, salva_dividir


def test_janela_abre_na_escolha():
    """Abre a tela de verdade, confere os dois botões e fecha sem mainloop."""
    from commands import menu

    janela = menu.Janela.__new__(menu.Janela)
    import tkinter as tk

    janela.__init__("x.pdf")
    try:
        textos = set()
        pilha = list(janela.corpo.winfo_children())
        while pilha:
            w = pilha.pop()
            try:
                if w.winfo_class() == "Label" and w.cget("text") in (
                        "Comprimir", "Dividir"):
                    textos.add(w.cget("text"))
            except Exception:
                pass
            pilha.extend(w.winfo_children())
        assert textos == {"Comprimir", "Dividir"}, sorted(textos)
    finally:
        janela.raiz.destroy()


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
