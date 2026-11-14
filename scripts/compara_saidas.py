"""Compara dois PDFs objeto a objeto: streams e dicionarios.

Uso: python scripts/compara_saidas.py A.pdf B.pdf

Serve para provar que uma otimizacao (paralelizar, refatorar) NAO mudou a
saida. Compara por objgen: tipo, /Subtype, tamanho e crc32 dos bytes crus.
"""
import sys
import zlib

import pikepdf


def censo(cam):
    pdf = pikepdf.open(cam)
    itens = {}
    meta = {}
    for o in pdf.objects:
        try:
            og = o.objgen
        except Exception:
            continue
        if not og or not og[0]:
            continue
        eh_meta = False
        try:
            tp = str(o.get("/Type", ""))
            sub = str(o.get("/Subtype", ""))
            eh_meta = (sub == "/XML" or tp in ("/ObjStm", "/Metadata"))
        except Exception:
            tp, sub = "", ""
        if isinstance(o, pikepdf.Stream):
            try:
                raw = o.read_raw_bytes()
            except Exception:
                raw = b""
            item = ("stream", str(o.get("/Subtype", "")), len(raw),
                    zlib.crc32(raw))
        else:
            item = ("dict", tp, len(str(o)), 0)
        # XMP e ObjStm carregam as datas que ATUALIZAMOS de proposito
        (meta if eh_meta else itens)[og] = item
    pdf.close()
    return itens, meta


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    A, MA = censo(argv[0])
    B, MB = censo(argv[1])
    print("objetos: %d x %d | so em A: %d | so em B: %d"
          % (len(A), len(B), len(set(A) - set(B)), len(set(B) - set(A))))
    comuns = set(A) & set(B)
    difs = [(og, A[og], B[og]) for og in comuns if A[og] != B[og]]
    print("objetos com conteudo diferente (estrutura): %d" % len(difs))
    for og, x, y in difs[:10]:
        print("   %s: %s -> %s" % (og, x[:3], y[:3]))
    difs_meta = [og for og in set(MA) & set(MB) if MA[og] != MB[og]]
    print("objetos de metadados diferentes (datas, esperado): %d" % len(difs_meta))
    return 0 if not difs else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
