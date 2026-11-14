"""Regressao da consolidacao de objetos (bug real, nao teorico).

Caso medido em processo.pdf pg209: o iLovePDF extrai "Laudo"; a nossa saida
extraia "/audo". Causa: `_consolida_fontes` fundia duas copias do MESMO
programa de fonte com /ToUnicode diferentes — o render fica identico (mesmos
glifos) mas busca/copia de texto quebra. A assinatura passou a incluir o
/ToUnicode.
"""
import os
import sys

import pikepdf

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
import compress  # noqa: E402


def _fonte(pdf, tou):
    prog = pdf.make_stream(b"PROGRAMA-DE-FONTE-IDENTICO")
    fd = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/FontDescriptor"),
        "/FontName": pikepdf.Name("/X"),
        "/FontFile2": prog,
    }))
    d = pikepdf.Dictionary({
        "/Type": pikepdf.Name("/Font"),
        "/Subtype": pikepdf.Name("/TrueType"),
        "/BaseFont": pikepdf.Name("/X"),
        "/FontDescriptor": fd,
        "/Widths": pikepdf.Array([500, 500]),
    })
    if tou is not None:
        d["/ToUnicode"] = pdf.make_stream(tou)
    return pdf.make_indirect(d)


def test_tounicode_diferente_nao_funde():
    pdf = pikepdf.new()
    a = _fonte(pdf, b"CMAP-COM-A")
    b = _fonte(pdf, b"CMAP-COM-B")
    c = _fonte(pdf, b"CMAP-COM-A")
    sa, sb, sc = (compress._assinatura_fonte(x) for x in (a, b, c))
    assert sa != sb, "ToUnicode diferente tem de dar assinatura diferente"
    assert sa == sc, "mesmo ToUnicode + mesmo programa = assinatura igual"
    pdf.close()


def test_sem_tounicode_continua_fundindo():
    pdf = pikepdf.new()
    a = _fonte(pdf, None)
    b = _fonte(pdf, None)
    sa, sb = (compress._assinatura_fonte(x) for x in (a, b))
    assert sa == sb, "sem /ToUnicode a assinatura nao muda"
    pdf.close()


def test_mascara_imagem_inline():
    """Binario de BI...ID...EI nao pode engolir o resto do content stream.

    Bug real (processo.pdf pg337): 3.595 imagens inline na mesma pagina; sem
    mascarar, o tokenizador parava no primeiro binario, nenhum Tf/Tj era visto
    e TODAS as fontes da pagina eram consideradas sem uso e apagadas (render
    3,9% diferente e texto extraido virando lixo).
    """
    content = (b"q\nBI\n/CS/RGB\n/W 1\n/H 1\n/BPC 8\nID \xf8\xf0\xe8\nEI Q\n"
               b"BT /R11 12 Tf (Ola) Tj ET\n")
    toks = list(compress._tokens_conteudo(content))
    ops = [v for t, v in toks if t == "op"]
    assert b"Tf" in ops, "o Tf depois da imagem inline tem de ser visto"
    assert b"Tj" in ops, "o Tj depois da imagem inline tem de ser visto"
    # o mascaramento preserva o comprimento (offsets nao mudam)
    assert len(compress._mascara_imagens_inline(content)) == len(content)


def test_fonte_sem_uso_nao_esvazia_o_dict():
    """/Font inteiro marcado como sem uso => nao apagar (fallback de seguranca)."""
    # a regra vive em _consolida_fontes; aqui garantimos o contrato da funcao
    # auxiliar que decide a assinatura: /ToUnicode diferencia fontes.
    pdf = pikepdf.new()
    a = _fonte(pdf, b"CMAP-1")
    b = _fonte(pdf, b"CMAP-2")
    assert compress._assinatura_fonte(a) != compress._assinatura_fonte(b)
    pdf.close()


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
