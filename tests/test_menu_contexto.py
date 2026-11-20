"""O atalho do menu de contexto tem de chegar ao motor novo de divisão.

Cadeia: HKCU\...\shell\PDFagent\shell\dividir\command (gravada pelo .iss) →
`cli.main` → `commands.split.main` → `dividir` → `_partes` (busca
exponencial + binária em RAM, pikepdf lossless).

Se o atalho voltar a apontar para o compress ou o `dividir` voltar ao motor
antigo (peso por página), estes testes pegam antes do release.
"""
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)


def _fonte(nome):
    with open(os.path.join(RAIZ, nome), encoding="utf-8") as fh:
        return fh.read()


def test_registro_e_iss_apontam_para_split_com_avisar():
    iss = _fonte("instalador/PDFagent.iss")
    Linhas = [l.strip() for l in iss.splitlines() if "shell\\dividir\\command" in l]
    assert Linhas, "nenhuma chave de menu 'dividir' no .iss"
    linha = Linhas[0]
    assert '{app}\\{#Exe}' in linha
    assert '" split ""%1"" --avisar"' in linha, linha
    # o atalho de dividir NAO pode pedir compressao nem --in-place
    assert "--in-place" not in linha and "-n " not in linha


def test_cli_despacha_split_para_o_modulo_certo():
    import cli

    assert cli.COMMANDS["split"]["alvo"] == ("commands.split", "main")
    assert cli.SINONIMOS.get("dividir", "dividir") in ("split", "dividir") or \
        "dividir" in cli.COMMANDS


def test_dividir_chama_o_motor_novo():
    modulo = _fonte("commands/split.py")
    assert "r = dividir(args.entrada, limite," in modulo
    # motor novo: exponencial + binaria em RAM, write once
    assert "salto *= 2" in modulo and "baixo = melhor_fim + 1" in modulo
    assert "_pesos_por_pagina" not in modulo, "voltou ao motor de estimativa"
    assert "compress_streams=False" in modulo and "recompress_flate=False" in modulo
    assert "object_stream_mode=pikepdf.ObjectStreamMode.preserve" in modulo


def test_subpasta_e_padrao_1_6():
    modulo = _fonte("commands/split.py")
    assert 'pasta = os.path.join(raiz, base)' in modulo
    import progresso

    assert progresso.LIMITE_PADRAO_MB == 1.6


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
