"""Vacina do pipeline por imagem (prepare -> thread -> apply).

A janela deixa K imagens decodificadas ao mesmo tempo: enquanto as threads
codificam, a thread principal decodifica a proxima. O risco que isso introduz e'
o MESMO objeto aparecer em duas paginas e a segunda ocorrencia ser preparada
antes de a primeira ser aplicada (ela veria o original, nao o resultado) e o
caso de a /SMask ser escrita fora de ordem. O teste compara a saida com
janela=1 (serie) e janela=4 (pipeline): tem de ser a MESMA imagem no objeto.
"""
import io
import os
import sys

import pikepdf
from PIL import Image

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
import compress  # noqa: E402


def _imagem(lado_px, cor):
    buf = io.BytesIO()
    img = Image.new("RGB", (lado_px, lado_px), cor)
    for x in range(0, lado_px, 7):        # textura: sem ela o JPEG fica trivial
        for y in range(0, lado_px, 3):
            img.putpixel((x, y), (255 - cor[0], 255 - cor[1], 255 - cor[2]))
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def _pdf_com_objeto_repetido():
    """3 paginas; /Im1 aparece na 1a e na 3a, com SMask 1-bit."""
    pdf = pikepdf.new()
    mascara = pdf.make_stream(b"\x00" * (64 * 64))
    mascara["/Type"] = pikepdf.Name("/XObject")
    mascara["/Subtype"] = pikepdf.Name("/Image")
    mascara["/Width"] = 64
    mascara["/Height"] = 64
    mascara["/BitsPerComponent"] = 1
    mascara["/ColorSpace"] = pikepdf.Name("/DeviceGray")
    foto = pdf.make_stream(_imagem(1200, (200, 60, 60)))
    foto["/Type"] = pikepdf.Name("/XObject")
    foto["/Subtype"] = pikepdf.Name("/Image")
    foto["/Width"] = 1200
    foto["/Height"] = 1200
    foto["/BitsPerComponent"] = 8
    foto["/ColorSpace"] = pikepdf.Name("/DeviceRGB")
    foto["/Filter"] = pikepdf.Name("/DCTDecode")
    foto["/SMask"] = mascara
    outra = pdf.make_stream(_imagem(900, (60, 60, 200)))
    outra["/Type"] = pikepdf.Name("/XObject")
    outra["/Subtype"] = pikepdf.Name("/Image")
    outra["/Width"] = 900
    outra["/Height"] = 900
    outra["/BitsPerComponent"] = 8
    outra["/ColorSpace"] = pikepdf.Name("/DeviceRGB")
    outra["/Filter"] = pikepdf.Name("/DCTDecode")
    for xobj in ("/Im1", "/Im2", "/Im1"):
        pagina = pdf.add_blank_page(page_size=(300, 300))
        pagina.obj["/Resources"] = pikepdf.Dictionary({
            "/XObject": pikepdf.Dictionary({xobj: foto if xobj == "/Im1" else outra}),
        })
        pagina.obj["/Contents"] = pdf.make_stream(
            b"q 200 0 0 200 50 50 cm %s Do Q" % xobj.encode())
    return pdf


def _imagens(caminho):
    """(width, height, filter, bytes crus) de toda imagem, em ordem de objgen."""
    pdf = pikepdf.open(caminho)
    saida = []
    for o in pdf.objects:
        try:
            if not isinstance(o, pikepdf.Stream):
                continue
            if str(o.get("/Subtype", "")) != "/Image":
                continue
            saida.append((int(o.get("/Width", 0)), int(o.get("/Height", 0)),
                          str(o.get("/Filter", "")), o.read_raw_bytes()))
        except Exception:
            continue
    pdf.close()
    return sorted(saida, key=lambda t: (t[0], t[1], len(t[3])))


def _comprime(pdf, destino, threads, janela):
    origem = destino + ".in.pdf"
    pdf.save(origem)
    antes = dict(os.environ)
    try:
        os.environ["PDFAGENT_THREADS"] = str(threads)
        os.environ["PDFAGENT_JANELA"] = str(janela)
        compress._POOL = None
        compress.comprimir(origem, destino, "recommended", lambda m: None)
    finally:
        os.environ.clear()
        os.environ.update(antes)
        compress._POOL = None


def _temp(nome):
    import tempfile
    return os.path.join(tempfile.mkdtemp(prefix="cpdf_pipe_"), nome)


def test_pipeline_igual_a_serie():
    """janela=4 tem de escrever exatamente os mesmos bytes que janela=1."""
    pdf = _pdf_com_objeto_repetido()
    art = _temp("a.pdf")
    _comprime(pdf, art, threads=1, janela=1)
    pipe = _temp("b.pdf")
    _comprime(pdf, pipe, threads=4, janela=4)
    a, b = _imagens(art), _imagens(pipe)
    assert len(a) == len(b), "numero de imagens mudou (%d x %d)" % (len(a), len(b))
    for (wa, ha, fa, da), (wb, hb, fb, db) in zip(a, b):
        assert (wa, ha, fa) == (wb, hb, fb), \
            "metadados divergiram: %s x %s" % ((wa, ha, fa), (wb, hb, fb))
        assert da == db, "bytes da imagem %dx%d divergiram" % (wa, ha)
    pdf.close()


def test_mascara_acompanha_a_imagem_no_pipeline():
    """A /SMask tem de ser reamostrada na thread principal, junto com a mae.

    O resize da mascara virou dado (`res["smask"]`) e a escrita ficou para o
    `_aplica_job`. Se ela se perder no caminho, a mae encolhe e a mascara fica
    na resolucao original — o render continua "certo", mas o arquivo infla.
    """
    pdf = _pdf_com_objeto_repetido()
    destino = _temp("c.pdf")
    _comprime(pdf, destino, threads=4, janela=4)
    pdf2 = pikepdf.open(destino)
    vistos = 0
    for pagina in pdf2.pages:
        for _nome, obj in dict(pagina.get_images()).items():
            if str(obj.get("/ColorSpace", "")) != "/DeviceRGB":
                continue
            m = obj.get("/SMask")
            if m is None:
                continue
            vistos += 1
            assert int(obj.get("/Width")) < 1200, "imagem-mae nao reamostrada"
            assert int(m.get("/Width")) == int(obj.get("/Width")), \
                "mascara %s x mae %s" % (m.get("/Width"), obj.get("/Width"))
            assert int(m.get("/Height")) == int(obj.get("/Height"))
    assert vistos, "nenhuma imagem com mascara encontrada na saida"
    pdf2.close()
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
    print("falhas: %d" % falhas)
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
