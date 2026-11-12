"""Teste dos 3 niveis: gera fixture, comprime, valida estrutura e ordem."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import compress  # noqa: E402


def gera_fixture(caminho):
    import random
    from PIL import Image, ImageDraw
    import fitz
    random.seed(7)
    # foto com ruido (foto realista: JPEG eh o caminho natural)
    foto = Image.new("RGB", (900, 1350))
    px = foto.load()
    for y in range(0, 1350, 4):
        for x in range(0, 900, 4):
            r = (x * 255 // 900 + random.randint(-25, 25)) % 256
            gg = (y * 255 // 1350 + random.randint(-25, 25)) % 256
            b = ((x + y) * 255 // 2250 + random.randint(-25, 25)) % 256
            for dy in range(min(4, 1350 - y)):
                for dx in range(min(4, 900 - x)):
                    px[x + dx, y + dy] = (r, gg, b)
    d = ImageDraw.Draw(foto)
    d.rectangle([100, 100, 800, 1250], outline=(0, 255, 0), width=9)
    fp = caminho + ".foto.png"
    foto.save(fp)
    bw = Image.new("1", (850, 1100), 1)
    d2 = ImageDraw.Draw(bw)
    for i in range(30):
        d2.rectangle([50, 40 + i * 34, 700, 40 + i * 34 + 10], fill=0)
    sp = caminho + ".scan.png"
    bw.save(sp)
    doc = fitz.open()
    pg = doc.new_page(width=595, height=842)
    pg.insert_text((72, 60), "Fixture CompressPDF", fontsize=14)
    pg.insert_image(fitz.Rect(72, 90, 450, 500), filename=fp)
    pg.insert_image(fitz.Rect(72, 520, 450, 800), filename=sp)
    doc.set_metadata({"title": "T", "author": "A"})
    doc.save(caminho)
    os.remove(fp)
    os.remove(sp)


def main():
    tmp = tempfile.mkdtemp(prefix="cpd_test_")
    entrada = os.path.join(tmp, "in.pdf")
    gera_fixture(entrada)
    tam0 = os.path.getsize(entrada)
    res = {}
    for nv in ("extreme", "recommended", "low"):
        out = os.path.join(tmp, f"{nv}.pdf")
        r = compress.comprimir(entrada, out, nv, log=lambda m: None)
        res[nv] = r
        print(f"{nv}: {r['antes']:,} -> {r['depois']:,} (-{r['razao']:.1f}%)")
        assert r["depois"] < r["antes"], nv
    assert res["extreme"]["depois"] < res["recommended"]["depois"], "extreme<rec"
    assert res["recommended"]["depois"] < res["low"]["depois"], "rec<low"

    import pikepdf
    esperados = {"extreme": 72.0, "recommended": 150.0, "low": 200.0}
    for nv in ("extreme", "recommended", "low"):
        pdf = pikepdf.open(os.path.join(tmp, f"{nv}.pdf"))
        foto = None
        for page in pdf.pages:
            for _n, o in dict(page.get_images()).items():
                if int(o.get("/Width", 0)) > 200 and int(o.get("/BitsPerComponent", 0)) == 8:
                    foto = o
                    break
            if foto is not None:
                break
        assert foto is not None, f"foto {nv}"
        assert [str(x) for x in foto.get("/Filter")] == ["/FlateDecode", "/DCTDecode"], \
            f"cadeia flate+dct {nv}: {foto.get('/Filter')}"
        dp = foto.get("/DecodeParms")
        assert int(dp[1].get("/Quality")) == compress.LEVELS[nv]["qualidade"], nv
        larg = int(foto.get("/Width"))
        # foto 900x1350 desenhada em 273x410pt (aspect preservado) ->
        # px = 273/72*alvo; low nao re-amostra (171 DPI < limiar 400)
        if nv == "low":
            assert larg == 900, (nv, larg)
        else:
            alvo = esperados[nv]
            assert abs(larg - round(273 / 72 * alvo)) <= 2, (nv, larg)
        # metadados: extreme remove tudo e deixa so o carimbo;
        # docinfo e' PRESERVADO nos 3 niveis (provado nas 21 saidas reais do
        # iLovePDF: Author/Creator/Title ficam; so datas e Producer mudam).
        # O que o strip "Metadata" remove e' o fluxo XMP do catalogo.
        chaves = {str(k) for k in pdf.docinfo.keys()}
        assert "/Title" in chaves and "/Producer" in chaves, (nv, chaves)
        if nv == "extreme":
            # o motor tambem re-carimba o XMP (3-Heights XMP Library): o
            # original sai e entra um fluxo proprio — nao fica sem /Metadata
            assert "/Metadata" in pdf.Root, (nv, "XMP proprio deveria existir")
            assert b"CompressPDF" in pdf.Root["/Metadata"].read_bytes(), nv
        pdf.close()
    print("TUDO OK")


if __name__ == "__main__":
    main()
