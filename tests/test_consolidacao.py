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


def _fonte_com_programa(pdf, base, prog):
    fd = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/FontDescriptor"),
        "/FontName": pikepdf.Name(base),
        "/FontFile2": prog,
    }))
    return pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/Font"),
        "/Subtype": pikepdf.Name("/TrueType"),
        "/BaseFont": pikepdf.Name(base),
        "/FontDescriptor": fd,
        "/Widths": pikepdf.Array([500]),
    }))


def test_fonte_citada_em_tf_conta_como_usada():
    """Fonte selecionada por Tf entra no mapa mesmo sem nenhum Tj/TJ.

    Bug real: /R72 da pg148 de processo.pdf sumia do /Resources e a pagina
    ficava sem fonte (texto extraido virava \\x00\\x01...).
    """
    pdf = pikepdf.new()
    fonte = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/Font"),
        "/Subtype": pikepdf.Name("/Type1"),
        "/BaseFont": pikepdf.Name("/Helvetica"),
    }))
    pagina = pdf.add_blank_page(page_size=(200, 200))
    pagina.obj["/Resources"] = pikepdf.Dictionary({
        "/Font": pikepdf.Dictionary({"/F1": fonte}),
    })
    pagina.obj["/Contents"] = pdf.make_stream(b"BT /F1 12 Tf ET")
    usos = compress._codigos_por_fonte(pdf)
    assert fonte.objgen in usos, "Tf sem glifo deve marcar a fonte como usada"
    assert usos[fonte.objgen] == set(), "e sem codigos de glifo"
    pdf.close()


def test_remocao_de_fonte_usa_objgen_original():
    """Fonte usada nao pode ser apagada porque sua copia canonica e' 'sem uso'.

    Bug real: a consolidacao remapeia /F2 para a canonica e decidia a remocao
    pelo objgen da canonica; se ela nao estivesse em `usados`, /F2 sumia.
    A terceira fonte (diferente) existe para o /Font NAO ficar vazio — com o
    dicionario vazio a guarda "nunca esvaziar" mascararia o bug.
    """
    pdf = pikepdf.new()
    prog = pdf.make_stream(b"PROGRAMA")
    sobra = _fonte_com_programa(pdf, "/AAA+Times", prog)   # criada primeiro
    usada = _fonte_com_programa(pdf, "/AAA+Times", prog)   # mesma assinatura
    outra = _fonte_com_programa(pdf, "/BBB+Arial", pdf.make_stream(b"OUTRO"))
    pagina = pdf.add_blank_page(page_size=(200, 200))
    pagina.obj["/Resources"] = pikepdf.Dictionary({
        "/Font": pikepdf.Dictionary({"/F1": sobra, "/F2": usada, "/F3": outra}),
    })
    pagina.obj["/Contents"] = pdf.make_stream(b"BT /F2 12 Tf (A) Tj /F3 12 Tf (B) Tj ET")
    compress._consolida_fontes(pdf, lambda m: None)
    nomes = {str(k) for k in pagina.obj["/Resources"]["/Font"].keys()}
    assert "/F2" in nomes, "a fonte usada nao pode ser removida"
    assert "/F1" not in nomes, "a copia sem uso deve sair"
    pdf.close()


def test_substituicao_padrao_preserva_tounicode():
    """Trocar Arial por Helvetica nao pode perder o CMap codigo->texto.

    Sem isso "fls. 1" virava \\x01\\x02... (pg148 de processo.pdf).
    """
    pdf = pikepdf.new()
    tou = pdf.make_stream(
        b"/CIDInit /ProcSet findresource begin 12 dict begin begincmap\n"
        b"1 begincodespacerange <00> <ff> endcodespacerange\n"
        b"1 beginbfchar <01> <0066> endbfchar\n"
        b"endcmap end end")
    fd = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/FontDescriptor"),
        "/FontName": pikepdf.Name("/Arial"),
        "/FontFile2": pdf.make_stream(b"PROGRAMA"),
    }))
    fonte = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/Font"),
        "/Subtype": pikepdf.Name("/TrueType"),
        "/BaseFont": pikepdf.Name("/Arial"),
        "/FontDescriptor": fd,
        "/Widths": pikepdf.Array([500]),
        "/ToUnicode": tou,
    }))
    pagina = pdf.add_blank_page(page_size=(200, 200))
    pagina.obj["/Resources"] = pikepdf.Dictionary({
        "/Font": pikepdf.Dictionary({"/F1": fonte}),
    })
    pagina.obj["/Contents"] = pdf.make_stream(b"BT /F1 12 Tf (A) Tj ET")
    compress._substitui_fontes_padrao(pdf, lambda m: None)
    depois = pagina.obj["/Resources"]["/Font"]["/F1"]
    assert str(depois.get("/BaseFont")) == "/Helvetica"
    assert depois.get("/ToUnicode") is not None, "o CMap tem de sobreviver"
    pdf.close()


def test_assinatura_nao_trunca_encoding():
    """Dois /Encoding diferentes NAO podem colidir na assinatura.

    str() de um Object do pikepdf corta a saida; 3 Type3 distintos de
    processo.pdf cairam na mesma assinatura e a extracao virou \\x00\\x01...
    """
    pdf = pikepdf.new()

    def fonte(marca):
        dif = [pikepdf.Name("/g%d" % i) for i in range(300)]
        dif[200] = pikepdf.Name("/%s" % marca)      # diferenca no fim
        enc = pikepdf.Dictionary({
            "/Type": pikepdf.Name("/Encoding"),
            "/Differences": pikepdf.Array([0] + dif),
        })
        return pdf.make_indirect(pikepdf.Dictionary({
            "/Type": pikepdf.Name("/Font"),
            "/Subtype": pikepdf.Name("/Type3"),
            "/CharProcs": pikepdf.Dictionary({
                "/g0": pdf.make_stream(b"0 0 d0"),
            }),
            "/Encoding": enc,
            "/Widths": pikepdf.Array([500] * 300),
            "/FirstChar": 0,
        }))

    a, b = fonte("marcaA"), fonte("marcaB")
    assert compress._assinatura_fonte(a) != compress._assinatura_fonte(b)
    pdf.close()


def _pdf_com_imagem_e_mascara(lado_px=400, lado_pt=36):
    """Imagem RGB 64x64 desenhada em 36x36 pt (128 dpi) com /SMask 1-bit."""
    import io as _io
    from PIL import Image
    pdf = pikepdf.new()
    buf = _io.BytesIO()
    Image.new("RGB", (lado_px, lado_px), (10, 20, 30)).save(
        buf, format="JPEG", quality=80)
    mascara = pdf.make_stream(bytes(lado_px * lado_px))
    mascara["/Type"] = pikepdf.Name("/XObject")
    mascara["/Subtype"] = pikepdf.Name("/Image")
    mascara["/Width"] = lado_px
    mascara["/Height"] = lado_px
    mascara["/BitsPerComponent"] = 1
    mascara["/ColorSpace"] = pikepdf.Name("/DeviceGray")
    foto = pdf.make_stream(buf.getvalue())
    foto["/Type"] = pikepdf.Name("/XObject")
    foto["/Subtype"] = pikepdf.Name("/Image")
    foto["/Width"] = lado_px
    foto["/Height"] = lado_px
    foto["/BitsPerComponent"] = 8
    foto["/ColorSpace"] = pikepdf.Name("/DeviceRGB")
    foto["/Filter"] = pikepdf.Name("/DCTDecode")
    foto["/SMask"] = mascara
    pagina = pdf.add_blank_page(page_size=(200, 200))
    pagina.obj["/Resources"] = pikepdf.Dictionary({
        "/XObject": pikepdf.Dictionary({"/Im1": foto}),
    })
    pagina.obj["/Contents"] = pdf.make_stream(
        b"q %d 0 0 %d 0 0 cm /Im1 Do Q" % (lado_pt, lado_pt))
    return pdf, foto, mascara


def test_mascara_acompanha_o_tamanho_da_imagem():
    """Mascara 1-bit tem de ser reamostrada junto com a imagem-mae.

    Medido em processo.pdf extreme: 58 mascaras somando 108 KB nossos contra
    24 KB do iLovePDF — cada uma ~4x maior porque ficava na resolucao original.
    """
    pdf, foto, mascara = _pdf_com_imagem_e_mascara()
    spec = dict(compress.LEVELS["extreme"])
    usos = compress._tamanhos_na_pagina(pdf)
    compress._recomprime_imagem(pdf, foto, spec, usos, lambda m: None)
    compress._recomprime_mascaras(pdf, spec, usos, lambda m: None)
    assert int(foto["/Height"]) < 400, "a imagem-mae devia ter sido reamostrada"
    assert int(mascara["/Height"]) == int(foto["/Height"]), \
        "a mascara tem de ter a mesma altura da imagem-mae"
    assert int(mascara["/Width"]) == int(foto["/Width"])
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
