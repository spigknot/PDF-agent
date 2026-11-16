"""DPI efetivo: pacote picklable tem de dar o MESMO mapa (e os mesmos numeros).

Vacina da rodada 19. `_tamanhos_na_pagina` passou a montar pacotes de
`/XObject` (imagem -> objgen; Form -> bytes + /Matrix + /Resources) e rastrear a
CTM em processo. O mapa decide REAMOSTRAGEM: um (sx, sy) errado muda bytes e
render, e o gate estrutural so' acusa no fim.

Casos que ja' custaram tempo e ficam travados aqui:
  - Form com `/Matrix` (a matriz entra na CTM);
  - Form SEM `/Resources` e Form com `/Resources` VAZIO (o serial faz
    `recursos_de(xo) or cur`, ou seja, cai no do pai);
  - imagem desenhada duas vezes com escalas diferentes (duas ocorrencias);
  - `prof > 8` nao entra (limite de recursao do serial).
"""
import os
import sys

import pikepdf

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
import compress  # noqa: E402

Name = pikepdf.Name


def _imagem(pdf, tom=128, lado=4):
    st = pikepdf.Stream(pdf, bytes([tom]) * (lado * lado))
    st["/Type"] = Name("/XObject")
    st["/Subtype"] = Name("/Image")
    st["/Width"] = lado
    st["/Height"] = lado
    st["/ColorSpace"] = Name("/DeviceGray")
    st["/BitsPerComponent"] = 8
    return pdf.make_indirect(st)


def _form(pdf, conteudo, recursos=None, matriz=None):
    st = pikepdf.Stream(pdf, conteudo)
    st["/Type"] = Name("/XObject")
    st["/Subtype"] = Name("/Form")
    st["/BBox"] = pikepdf.Array([0, 0, 100, 100])
    if recursos is not None:
        st["/Resources"] = recursos
    if matriz is not None:
        st["/Matrix"] = pikepdf.Array(matriz)
    return pdf.make_indirect(st)


def _pdf(recursos_vazios=False):
    """10 paginas (para o pool ligar); so' a primeira desenha.

    Pg0: q 200 0 0 100 cm /Im1 Do Q   -> Im1 em (200, 100)
         q /Fm1 Do Q                  -> Fm1 (sem /Resources) desenha Im1 a 5
         /Fm2 Do                     -> Fm2 (/Matrix 2x) desenha Im2 a 20
    """
    pdf = pikepdf.new()
    im1 = _imagem(pdf, 100, 200)
    im2 = _imagem(pdf, 200, 200)
    if recursos_vazios:
        rec_fm = pikepdf.Dictionary()          # vazio: tem de cair no pai
    else:
        rec_fm = None                          # ausente: idem
    fm_pai = _form(pdf, b"q 5 0 0 5 0 0 cm /Im1 Do Q", recursos=rec_fm)
    fm_filho = _form(pdf, b"q 10 0 0 10 0 0 cm /Im2 Do Q",
                     recursos=pikepdf.Dictionary({
                         "/XObject": pikepdf.Dictionary({"/Im2": im2})}),
                     matriz=[2, 0, 0, 2, 0, 0])
    recursos = pikepdf.Dictionary({
        "/XObject": pikepdf.Dictionary(
            {"/Im1": im1, "/Fm1": fm_pai, "/Fm2": fm_filho})})
    conteudo = b"q 200 0 0 100 0 0 cm /Im1 Do Q q /Fm1 Do Q /Fm2 Do"
    for i in range(10):
        pag = pdf.add_blank_page(page_size=(300, 300))
        if i == 0:
            pag.obj["/Contents"] = pdf.make_stream(conteudo)
            pag.obj["/Resources"] = recursos
        else:
            pag.obj["/Contents"] = pdf.make_stream(b"q Q")
    return pdf, im1, im2


def _mapa(pdf, serial):
    if serial:
        os.environ["PDFAGENT_DPI_SERIAL"] = "1"
    else:
        os.environ.pop("PDFAGENT_DPI_SERIAL", None)
    try:
        return compress._tamanhos_na_pagina(pdf)
    finally:
        os.environ.pop("PDFAGENT_DPI_SERIAL", None)


def test_geometria_do_mapa():
    pdf, im1, im2 = _pdf()
    usos = _mapa(pdf, serial=True)
    assert usos[im1.objgen] == [(200.0, 100.0), (5.0, 5.0)], \
        "Im1: escala da pagina (200,100) e a do Form sem /Resources (5,5)"
    assert usos[im2.objgen] == [(20.0, 20.0)], \
        "Im2: /Matrix 2x do Form multiplica o cm 10x -> 20"
    pdf.close()


def test_form_com_resources_vazio_usa_o_pai():
    pdf, im1, _im2 = _pdf(recursos_vazios=True)
    usos = _mapa(pdf, serial=True)
    assert usos[im1.objgen] == [(200.0, 100.0), (5.0, 5.0)], \
        "dicionario vazio e' falsy no serial: tem de cair no /Resources do pai"
    pdf.close()


def test_pool_e_serial_dao_o_mesmo_mapa():
    pdf, _im1, _im2 = _pdf()
    serial = _mapa(pdf, serial=True)
    pool = _mapa(pdf, serial=False)
    assert {k: list(v) for k, v in serial.items()} == \
        {k: list(v) for k, v in pool.items()}
    pdf.close()


def test_clip_devolve_o_mesmo_dpi():
    """A passada do clip (rodada 20) devolve o MESMO mapa do caminho isolado.

    Sem nada recortado, o DPI do clip tem de ser igual ao calculado sobre o
    mesmo pdf (que ainda nao foi mexido).
    """
    pdf, _im1, _im2 = _pdf()
    draws, dpi_paginas, _pacotes = compress._coleta_draws(pdf)
    do_clip = compress._tamanhos_na_pagina(pdf, dpi_paginas)
    isolado = compress._tamanhos_na_pagina(pdf)
    assert draws, "a passada do clip tem de achar os draws das imagens"
    assert {k: list(v) for k, v in do_clip.items()} == \
        {k: list(v) for k, v in isolado.items()}, \
        "DPI do clip x isolado tem de ser identico"
    pdf.close()


def test_dpi_e_recalculado_depois_do_clip():
    """O clip muda `cm` e recorta pixels: o DPI tem de ser o POS-clip.

    Bug real da rodada 20 (2/21 no gate): o DPI coletado antes do clip dizia
    que a imagem era desenhada a 200x100 pt; depois do recorte ela e' 50x50.
    O otimizador so' ve' o estado pos-clip — usar o mapa antigo reamostrava
    errado (NS8002: 787 px de altura contra 655 da referencia).
    """
    pdf, im1, _im2 = _pdf()
    compress._CLIPADOS.clear()
    pagina = pdf.pages[0]
    # recorte de 50x50 sobre a imagem desenhada a 200x100
    pagina.obj["/Contents"] = pdf.make_stream(
        b"q 0 0 50 50 re W n q 200 0 0 100 0 0 cm /Im1 Do Q Q")
    usos_clip = compress._tamanhos_na_pagina(pdf, compress._aplica_clip_imagens(
        pdf, lambda m: None))
    assert compress._CLIPADOS, "o clip tinha de ter recortado a imagem"
    assert usos_clip[im1.objgen] == [(50.0, 50.0)], \
        "depois do recorte o desenho e' 50x50 pt, nao 200x100"
    pos = compress._tamanhos_na_pagina(pdf)
    assert {k: list(v) for k, v in usos_clip.items()} == \
        {k: list(v) for k, v in pos.items()}, \
        "o mapa do clip tem de bater com o pos-clip medido do zero"
    compress._CLIPADOS.clear()
    pdf.close()


def test_indices_dos_draws_apontam_para_cm_e_do():
    """`cm_idx`/`do_idx` caem em `cm`/`Do` no parse SEM filtro da pagina.

    E' a invariante que a rodada 16 pagou caro para aprender (2/21 no gate): o
    clip reparseia a pagina e edita aquelas POSICOES.
    """
    pdf, _im1, _im2 = _pdf()
    draws, _dpi, _pacotes = compress._coleta_draws(pdf)
    assert draws
    for d in draws:
        instrucoes = list(pikepdf.parse_content_stream(pdf.pages[d["pagina"]]))
        assert str(instrucoes[d["do_idx"]][1]) == "Do", "do_idx nao aponta um Do"
        if d["cm_idx"] is not None:
            assert str(instrucoes[d["cm_idx"]][1]) == "cm", "cm_idx nao aponta um cm"
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
