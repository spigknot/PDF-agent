"""Migração do menu de contexto: o diff do updater não toca no registro.

O updater troca só arquivos; o menu (HKCU) é escrito pelo instalador. Quem
atualiza pelo botão verde continuaria com o submenu antigo — o app conserta no
boot. Estes testes rodam numa chave temporária do HKCU (nunca na real).
"""
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

EXE = r"C:\Program Files\PDFagent\PDFagent.exe"


def _fonte(nome):
    with open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), nome), encoding="utf-8") as fh:
        return fh.read()


def _chave_teste():
    return r"Software\PDFagent-teste\menu-%s" % uuid.uuid4().hex[:8]


def _le(caminho, valor=None):
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, caminho) as k:
        if valor is None:
            return winreg.QueryValue(k, None)
        return winreg.QueryValueEx(k, valor)[0]


def _existe(caminho, valor=None):
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, caminho) as k:
            if valor is not None:
                winreg.QueryValueEx(k, valor)
            return True
    except OSError:
        return False


def _cria_formato_antigo(chave):
    import winreg

    hkcu = winreg.HKEY_CURRENT_USER
    with winreg.CreateKeyEx(hkcu, chave, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, "MUIVerb", 0, winreg.REG_SZ, "PDFagent")
        winreg.SetValueEx(k, "SubCommands", 0, winreg.REG_SZ, "x")
    for sub, cmd in (("comprimir", "--in-place -n recommended --avisar"),
                     ("dividir", "split")):
        with winreg.CreateKeyEx(hkcu, chave + "\\shell\\%s\\command" % sub, 0,
                                winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, None, 0, winreg.REG_SZ,
                              '"%s" %s "%%1"' % (EXE, cmd))


def _limpa(chave):
    import app as appmod
    import winreg

    appmod._apaga_arvore(winreg.HKEY_CURRENT_USER, chave)
    base = "\\".join(chave.split("\\")[:2])
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, base)
    except OSError:
        pass


def test_migra_submenu_para_item_unico():
    import app as appmod

    chave = _chave_teste()
    try:
        _cria_formato_antigo(chave)
        assert appmod.migra_menu_contexto(chave=chave, exe=EXE) == "migrado"
        # comando único -> menu "%1"
        assert _le(chave + r"\command") == '"%s" menu "%%1"' % EXE
        # submenus e SubCommands sumiram; o resto (rótulo/ícone) fica
        assert not _existe(chave + r"\shell\comprimir")
        assert not _existe(chave + r"\shell\dividir")
        assert not _existe(chave, "SubCommands")
        assert _le(chave, "MUIVerb") == "PDFagent"
        # idempotente: na segunda vez não há o que migrar
        assert appmod.migra_menu_contexto(chave=chave, exe=EXE) == "nada-a-fazer"
    finally:
        _limpa(chave)


def test_nao_cria_menu_quando_nao_existe():
    """Usuário desmarcou 'menu de contexto' na instalação: não inventa nada."""
    import app as appmod

    chave = _chave_teste()
    try:
        assert appmod.migra_menu_contexto(chave=chave, exe=EXE) == "nada-a-fazer"
        assert not _existe(chave)
    finally:
        _limpa(chave)


def test_so_limpa_shell_quando_fica_vazia():
    import app as appmod

    chave = _chave_teste()
    try:
        _cria_formato_antigo(chave)
        appmod.migra_menu_contexto(chave=chave, exe=EXE)
        assert not _existe(chave + r"\shell"), "shell vazia deveria sumir"
    finally:
        _limpa(chave)


def test_fonte_nao_mexe_no_registro():
    import app as appmod

    assert appmod.migra_menu_contexto(exe=None) == "fonte"


def test_instalador_e_app_escrevem_o_mesmo_comando():
    """O .iss e a migração do app precisam produzir a MESMA string de comando."""
    import re

    import app as appmod

    iss = _fonte("instalador/PDFagent.iss")
    m = re.search(r'shell\\PDFagent\\command";[^\n]*ValueData: "([^"]*(?:""[^"]*)*)"',
                  iss)
    assert m, "não achei o comando único no .iss"
    valor_iss = m.group(1).replace('""', '"')
    esperado = '"%s" menu "%%1"' % r"{app}\{#Exe}"
    assert valor_iss == esperado, valor_iss

    # o app gera exatamente o mesmo formato, só trocando o caminho do exe
    gerado = appmod.formato_comando_menu(r"C:\Program Files\PDFagent\PDFagent.exe")
    assert gerado == '"C:\\Program Files\\PDFagent\\PDFagent.exe" menu "%1"'
    assert gerado.replace(r"C:\Program Files\PDFagent\PDFagent.exe",
                          r"{app}\{#Exe}") == valor_iss


def test_instalador_nao_pergunta_nada():
    """PATH e menu de contexto entram sempre: sem [Tasks], sem caixinha."""
    iss = _fonte("instalador/PDFagent.iss")
    assert "[Tasks]" not in iss, "instalador não deve ter página de tarefas"
    assert "Tasks: contextmenu" not in iss
    assert "WizardIsTaskSelected" not in iss
    assert "AdicionaAoPath();" in iss
    # chamada incondicional logo após o ssPostInstall (sem if de task)
    linhas = [l.strip() for l in iss.splitlines()]
    i = next(i for i, l in enumerate(linhas) if "ssPostInstall" in l)
    corpo = [l for l in linhas[i + 1:i + 4]
             if l and not l.startswith("{")]
    assert corpo and corpo[0] == "AdicionaAoPath();", corpo
    # o item único do menu é escrito direto no [Registry]
    assert "shell\\PDFagent\\command" in iss


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
