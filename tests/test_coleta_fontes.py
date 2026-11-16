"""Coleta de fontes: pacote picklable + pool TEM de dar o MESMO resultado.

Vacina de um bug real (rodada 17): a primeira versao paralela devolvia o
`set` de codigos do worker. Conjunto igual, mas a ORDEM DE ITERACAO de um set
de ints depende do historico de insercao — e `_cod2glifo` numera os glifos
iterando esse set. Resultado: o programa subsetado saia 20 bytes diferente
(indistinguivel na imagem, arquivo diferente do baseline).

Por isso os bytes viajam crus e o set e' montado no processo principal, na
ordem dos bytes. Este teste compara o caminho paralelo com o serial em:
  1. chaves e CONTEUDO de `codigos_por_fonte`;
  2. a ORDEM de iteracao de cada set (a que muda a numeracao dos glifos);
  3. a ordem de `usos_por_fonte`;
  4. os casos de borda: Form com /Resources proprio, `Tf` sem `Tj` e Tipo0.
"""
import os
import sys

import pikepdf

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
import compress  # noqa: E402

Name = pikepdf.Name


def _fonte(pdf, base, tipo="/TrueType"):
    return pdf.make_indirect(pikepdf.Dictionary({
        "/Type": Name("/Font"),
        "/Subtype": Name(tipo),
        "/BaseFont": Name(base),
        "/Widths": pikepdf.Array([500, 500, 500]),
    }))


def _pdf(com_form=True):
    """12 paginas (passa do limiar do pool), um Form com /Resources proprio.

    Pagina: BT /F1 12 Tf (AB) Tj /F2 12 Tf (CD) Tj ET  e  q /Fm1 Do Q
    - F1 simples  -> codigos {65, 66}
    - F2 Tipo0    -> codigos {0x4344} (2 bytes por codigo)
    - Fm1: Form com /Resources PROPRIO (/F3) -> codigos {ord('Z')}
    - /FORA so' citada em Tf (sem Tj) -> entra com set vazio
    """
    pdf = pikepdf.new()
    f1 = _fonte(pdf, "/F1")
    f2 = _fonte(pdf, "/F2", "/Type0")
    f3 = _fonte(pdf, "/F3")
    fora = _fonte(pdf, "/FORA")

    conteudo = b"BT /F1 12 Tf (AB) Tj /F2 12 Tf (CD) Tj /FORA 12 Tf ET"
    if com_form:
        prog = pikepdf.Stream(pdf, b"BT /F3 9 Tf (Z) Tj ET")
        prog["/Type"] = Name("/XObject")
        prog["/Subtype"] = Name("/Form")
        prog["/BBox"] = pikepdf.Array([0, 0, 100, 100])
        prog["/Resources"] = pikepdf.Dictionary({"/Font": pikepdf.Dictionary({"/F3": f3})})
        form = pdf.make_indirect(prog)
        recursos = pikepdf.Dictionary({
            "/Font": pikepdf.Dictionary(
                {"/F1": f1, "/F2": f2, "/FORA": fora, "/Fm1": f1}),
            "/XObject": pikepdf.Dictionary({"/Fm1": form}),
        })
        conteudo += b" q /Fm1 Do Q"
    else:
        recursos = pikepdf.Dictionary({
            "/Font": pikepdf.Dictionary(
                {"/F1": f1, "/F2": f2, "/FORA": fora}),
        })

    for _ in range(12):
        pagina = pdf.add_blank_page(page_size=(300, 300))
        pagina.obj["/Contents"] = pdf.make_stream(conteudo)
        pagina.obj["/Resources"] = recursos
    return pdf, f1, f2, f3, fora


def _coleta(pdf, serial, limpar=True):
    """Roda a coleta; `limpar` zera o cache de eventos entre chamadas.

    Sem `limpar`, a 2a chamada no MESMO pdf reaproveita os eventos (assinatura
    igual) — e' o que os testes de cache exercitam; com `limpar`, cada caminho
    e' medido de verdade (pool x serial).
    """
    if limpar:
        compress._CACHE_COLETA = None
    if serial:
        os.environ["PDFAGENT_FONTES_SERIAL"] = "1"
    else:
        os.environ.pop("PDFAGENT_FONTES_SERIAL", None)
    os.environ.setdefault("PDFAGENT_PROC_WORKERS", "4")
    try:
        return compress._usos_e_codigos(pdf)
    finally:
        os.environ.pop("PDFAGENT_FONTES_SERIAL", None)


def _retrato(codigos, usos):
    """Conteudo E ordem de iteracao: e' a ordem que numera os glifos."""
    return ([(repr(k), list(v)) for k, v in codigos.items()],
            [(tuple(o.objgen), list(c), w) for o, c, w in usos])


def test_codigos_por_tipo_de_fonte():
    pdf, f1, f2, f3, fora = _pdf()
    codigos, usos = _coleta(pdf, serial=True)
    assert codigos[f1.objgen] == {65, 66}, "fonte simples conta os bytes do Tj"
    assert codigos[f2.objgen] == {0x4344}, "Tipo0 le 2 bytes por codigo"
    assert codigos[f3.objgen] == {ord("Z")}, "Form usa o /Resources dele, nao o do pai"
    assert codigos.get(fora.objgen) == set(), \
        "fonte citada em Tf entra com set vazio (senao some do /Resources)"
    largura = {o.objgen: w for o, _c, w in usos}
    assert largura[f1.objgen] == 1 and largura[f2.objgen] == 2
    pdf.close()


def test_pool_e_serial_dao_o_mesmo_retrato():
    pdf, _f1, _f2, _f3, _fora = _pdf()
    serial = _retrato(*_coleta(pdf, serial=True))
    pool = _retrato(*_coleta(pdf, serial=False))
    assert serial[0] == pool[0], "codigos (conteudo e ORDEM) tem de ser identicos"
    assert serial[1] == pool[1], "ordem de usos tem de ser identica"
    pdf.close()


def test_form_sem_resources_e_pulado_como_no_serial():
    """Form sem /Resources cai no /Resources do pai — que o walk JA visitou.

    O dedup por /Resources retorna antes de tokenizar o conteudo do Form (e' o
    comportamento do walk serial, replicado de proposito: a rodada 17 so'
    paralelizou, nao mudou semantica). Se isso mudasse, o conjunto de fontes
    "usadas" mudava junto — por isso o caso fica travado em teste.
    """
    pdf, f1, f2, _f3, fora = _pdf(com_form=False)
    prog = pikepdf.Stream(pdf, b"BT /F1 7 Tf (Q) Tj ET")
    prog["/Type"] = Name("/XObject")
    prog["/Subtype"] = Name("/Form")
    prog["/BBox"] = pikepdf.Array([0, 0, 10, 10])
    form = pdf.make_indirect(prog)
    pagina = pdf.pages[0]
    pagina.obj["/Resources"]["/XObject"] = pikepdf.Dictionary({"/Fm1": form})
    pagina.obj["/Contents"] = pdf.make_stream(
        b"BT /F1 12 Tf (AB) Tj /F2 12 Tf (CD) Tj ET q /Fm1 Do Q")
    pool = _retrato(*_coleta(pdf, serial=False))
    serial = _retrato(*_coleta(pdf, serial=True))
    assert pool == serial, "pacote e serial tem de concordar tambem neste caso"
    codigos, _usos = _coleta(pdf, serial=False)
    assert codigos[f1.objgen] == {65, 66}, \
        "o Form herda o /Resources do pai, ja visitado: o walk pula o conteudo"
    assert codigos.get(fora.objgen) == set()
    pdf.close()


def test_coleta_reaproveita_quando_nada_muda():
    """2a coleta no mesmo pdf usa os eventos da 1a (assinatura identica).

    E' o que faz a coleta do `_consolida_fontes` (pos-merge) custar 0,3 s em
    vez de 2,4 s. O teste olha a IDENTIDADE da lista de eventos: se o cache
    parar de acertar, os objetos mudam e ele falha.
    """
    pdf, _f1, _f2, _f3, _fora = _pdf()
    a = _retrato(*_coleta(pdf, serial=False, limpar=True))
    eventos_1 = compress._CACHE_COLETA[1]
    b = _retrato(*_coleta(pdf, serial=False, limpar=False))
    assert compress._CACHE_COLETA[1] is eventos_1, "a 2a coleta tem de vir do cache"
    assert a == b, "reaproveitar nao pode mudar o resultado"
    pdf.close()


def test_coleta_ve_conteudo_novo():
    """Conteudo diferente no MESMO pdf invalida o cache."""
    pdf, f1, _f2, _f3, _fora = _pdf()
    antes = _retrato(*_coleta(pdf, serial=False, limpar=True))
    eventos_1 = compress._CACHE_COLETA[1]
    pagina = pdf.pages[0]
    pagina.obj["/Contents"] = pdf.make_stream(b"BT /F1 12 Tf (ABQ) Tj ET")
    depois = _coleta(pdf, serial=False, limpar=False)[0]
    assert compress._CACHE_COLETA[1] is not eventos_1, "conteudo novo = cache novo"
    assert depois[f1.objgen] == {65, 66, ord("Q")}
    assert _retrato(*_coleta(pdf, serial=True, limpar=True))[0] != antes[0]
    pdf.close()


def test_coleta_ve_troca_de_objeto_de_fonte():
    """/Resources apontando para OUTRO objeto de fonte: a chave acompanha.

    E' o caso que impede o cache de devolver objgen morto: o evento guarda o
    rotulo + nome, e o replay resolve no pacote atual.
    """
    pdf, f1, _f2, _f3, _fora = _pdf()
    antes = _coleta(pdf, serial=False, limpar=True)[0]
    assert antes[f1.objgen] == {65, 66}
    novo = _fonte(pdf, "/F1")
    for pagina in pdf.pages:               # todas compartilham o mesmo /Resources
        pagina.obj["/Resources"]["/Font"]["/F1"] = novo
    depois = _coleta(pdf, serial=False, limpar=False)[0]
    assert depois[novo.objgen] == {65, 66}, "a coleta tem de ver o objeto NOVO"
    assert depois.get(f1.objgen) is None, "o objgen antigo nao pode sobreviver"
    pdf.close()


def test_campos_mutados_no_lugar_nao_invalidam():
    """Mutar /BaseFont no lugar (o que o merge faz) mantem a coleta valida.

    `_merge_subset_fontes` fase 3 grava /FontFile2, /BaseFont e /CIDToGIDMap no
    MESMO objeto — nada de /Resources nem conteudo. Se algum dia passar a
    trocar o objeto, `test_coleta_ve_troca_de_objeto_de_fonte` pega.
    """
    pdf, f1, _f2, _f3, _fora = _pdf()
    antes = _retrato(*_coleta(pdf, serial=False, limpar=True))
    eventos_1 = compress._CACHE_COLETA[1]
    f1["/BaseFont"] = Name("/ZZZ+Mutado")
    depois = _retrato(*_coleta(pdf, serial=False, limpar=False))
    assert compress._CACHE_COLETA[1] is eventos_1, "mutacao no lugar nao invalida"
    assert antes == depois
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
