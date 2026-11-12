"""Paridade estrutural: nossa saida vs a do iLovePDF, nas 21 combinacoes.

Compara a ESTRUTURA do PDF (imagens, fontes, anotacoes, chaves do catalogo,
docinfo), nao so tamanho/render. Diferencas esperadas (marca do produtor,
datas, /ID, bytes do XMP) sao normalizadas antes da comparacao.

Uso:  python tests/test_paridade.py [--lab CAMINHO] [--niveis rec,ext]
"""
import os
import sys
import tempfile
import collections

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import compress  # noqa: E402

import pikepdf  # noqa: E402

LAB_PADRAO = r"C:\Users\Gustavo\Desktop\REA-lab"
PASTAS_REF = {
    "recommended": "ilovepdf - recommended",
    "extreme": "ilovepdf - extreme",
    "low": "ilovepdf - low",
}
# chaves de catalogo que fazem parte do contrato de compressao
CHAVES_CATALOGO = ("/Metadata", "/StructTreeRoot", "/PieceInfo", "/Threads",
                   "/AcroForm", "/Outlines", "/Names", "/OCProperties",
                   "/MarkInfo", "/PageLabels")
# chaves de docinfo que nao valem comparacao (mudam por execucao)
DOCINFO_IGNORAR = {"/Producer", "/Creator", "/ModDate", "/CreationDate"}


def _filtro(obj):
    f = obj.get("/Filter")
    if f is None:
        return ()
    if isinstance(f, pikepdf.Array):
        return tuple(str(x) for x in f)
    return (str(f),)


def _cs(obj):
    cs = obj.get("/ColorSpace")
    if isinstance(cs, pikepdf.Array):
        return "[" + " ".join(str(x) for x in cs) + "]"
    return str(cs) if cs is not None else "?"


def impressao_digital(caminho):
    """Extrai a estrutura comparavel de um PDF."""
    d = {"paginas": 0, "imagens": [], "fontes": [], "annots": [],
         "catalogo": {}, "docinfo": {}, "xobjects_form": 0, "objetos": 0}
    with pikepdf.open(caminho) as pdf:
        d["objetos"] = len(pdf.objects)
        d["paginas"] = len(pdf.pages)
        raiz = pdf.Root
        for k in CHAVES_CATALOGO:
            d["catalogo"][k] = k in raiz
        di = pdf.docinfo or {}
        for k, v in di.items():
            if str(k) in DOCINFO_IGNORAR:
                continue
            d["docinfo"][str(k)] = str(v)[:60]
        for pg in pdf.pages:
            ann = pg.get("/Annots")
            if ann:
                for a in ann:
                    d["annots"].append(str(a.get("/Subtype", "?")))
            res = pg.get("/Resources")
            if res is None:
                continue
            fontes = res.get("/Font")
            if fontes is not None:
                for _, f in fontes.items():
                    base = str(f.get("/BaseFont", "?"))
                    if "+" in base:          # tira o tag de subset
                        base = base.split("+", 1)[1]
                    emb = any(k in f for k in ("/FontFile", "/FontFile2",
                                               "/FontFile3"))
                    d["fontes"].append((str(f.get("/Subtype", "?")), base, emb))
            xo = res.get("/XObject")
            if xo is None:
                continue
            for _, o in xo.items():
                sub = str(o.get("/Subtype", ""))
                if sub == "/Image":
                    d["imagens"].append((_filtro(o), _cs(o),
                                         int(o.get("/BitsPerComponent", 8)),
                                         int(o.get("/Width", 0)),
                                         int(o.get("/Height", 0))))
                elif sub == "/Form":
                    d["xobjects_form"] += 1
    for k in ("imagens", "fontes", "annots"):
        d[k] = sorted(d[k])
    return d


def compara(nosso, ref):
    difs = []
    if nosso["paginas"] != ref["paginas"]:
        difs.append("paginas: %d != %d" % (nosso["paginas"], ref["paginas"]))
    for k in CHAVES_CATALOGO:
        if nosso["catalogo"][k] != ref["catalogo"][k]:
            difs.append("catalogo %s: %s != %s"
                        % (k, nosso["catalogo"][k], ref["catalogo"][k]))
    for campo in ("imagens", "fontes", "annots"):
        a, b = collections.Counter(nosso[campo]), collections.Counter(ref[campo])
        if a != b:
            so_nos = list((a - b).elements())[:3]
            so_ref = list((b - a).elements())[:3]
            difs.append("%s: so_nosso=%s so_ref=%s (n=%d/%d)"
                        % (campo, so_nos, so_ref, sum(a.values()), sum(b.values())))
    if nosso["docinfo"] != ref["docinfo"]:
        difs.append("docinfo: %s != %s" % (nosso["docinfo"], ref["docinfo"]))
    if nosso["xobjects_form"] != ref["xobjects_form"]:
        difs.append("form xobjects: %d != %d"
                    % (nosso["xobjects_form"], ref["xobjects_form"]))
    return difs


def main(argv):
    lab = LAB_PADRAO
    niveis = ["extreme", "recommended", "low"]
    for i, a in enumerate(argv):
        if a == "--lab" and i + 1 < len(argv):
            lab = argv[i + 1]
        if a == "--niveis" and i + 1 < len(argv):
            niveis = [n.strip() for n in argv[i + 1].split(",") if n.strip()]
    orig = os.path.join(lab, "originais")
    if not os.path.isdir(orig):
        print("corpus ausente em %s — teste pulado" % orig)
        return 0

    tmp = tempfile.mkdtemp(prefix="paridade_")
    total = falhas = 0
    for nivel in niveis:
        pasta_ref = os.path.join(lab, PASTAS_REF[nivel])
        if not os.path.isdir(pasta_ref):
            print("sem referencia para %s (%s)" % (nivel, pasta_ref))
            continue
        print("\n=== nivel %s ===" % nivel)
        for nome in sorted(os.listdir(orig)):
            if not nome.lower().endswith(".pdf"):
                continue
            base = os.path.splitext(nome)[0]
            ref = os.path.join(pasta_ref, base + "-compressed.pdf")
            if not os.path.exists(ref):
                print("  %-46s sem referencia" % nome[:46])
                continue
            saida = os.path.join(tmp, "%s_%s.pdf" % (base[:40], nivel))
            try:
                r = compress.comprimir(os.path.join(orig, nome), saida, nivel,
                                       log=lambda m: None)
            except Exception as ex:
                print("  %-46s ERRO %s" % (nome[:46], ex))
                falhas += 1
                total += 1
                continue
            total += 1
            difs = compara(impressao_digital(saida), impressao_digital(ref))
            maior = r["depois"] > os.path.getsize(ref)
            if maior:
                difs.append("MAIOR: %d > %d" % (r["depois"], os.path.getsize(ref)))
            if difs:
                falhas += 1
                print("  %-46s DIF (%d): %s" % (nome[:46], len(difs), "; ".join(difs[:4])))
            else:
                print("  %-46s identico  (%d B vs %d B)"
                      % (nome[:46], r["depois"], os.path.getsize(ref)))
    print("\n%d/%d combinacoes com diferenca estrutural" % (falhas, total))
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
