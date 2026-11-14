"""Compara programas de fonte por tipo de letra entre dois PDFs.

Uso: python scripts/diag_fontes.py A.pdf B.pdf

Mostra, por BaseFont (sem tag de subset): quantos programas, tamanho total e
quantos CONJUNTOS DE NOMES de glifo distintos existem entre as copias. Se o
arquivo de referencia tiver 1 conjunto por tipo de letra, ele compartilha o
mesmo subset entre copias; se tiver varios, cada copia tem o seu.
"""
import io
import sys
import zlib

import pikepdf
from fontTools.ttLib import TTFont


def tn(o):
    try:
        return o._type_name
    except Exception:
        return ""


def base(b):
    b = str(b).lstrip("/")
    return b.split("+", 1)[1] if "+" in b else b


def coleta(cam):
    pdf = pikepdf.open(cam)
    out = {}
    for obj in pdf.objects:
        if tn(obj) != "dictionary" or str(obj.get("/Type", "")) != "/Font":
            continue
        fd = obj.get("/FontDescriptor")
        if fd is None or tn(fd) != "dictionary":
            continue
        for k in ("/FontFile", "/FontFile2", "/FontFile3"):
            s = fd.get(k)
            if s is None:
                continue
            og = s.objgen
            if og in out:
                break
            try:
                raw = s.read_bytes()
                tt = TTFont(io.BytesIO(raw))
                nomes = frozenset(tt.getGlyphOrder())
            except Exception:
                raw, nomes = b"", frozenset()
            out[og] = {"base": base(obj.get("/BaseFont", "?")),
                       "tam": len(raw), "nomes": nomes,
                       "crc": zlib.crc32(raw)}
            break
    pdf.close()
    return out


def relatorio(nome, dados):
    porbase = {}
    for d in dados.values():
        porbase.setdefault(d["base"], []).append(d)
    print("== %s: %d programas, %d tipos de letra"
          % (nome.split("/")[-1], len(dados), len(porbase)))
    for bf, lst in sorted(porbase.items(), key=lambda x: -len(x[1]))[:8]:
        conjuntos = {frozenset(x["nomes"]) for x in lst}
        crcs = {x["crc"] for x in lst}
        print("   %-28s %2d prog %7d B | glifos distintos: %d | bytes distintos: %d"
              % (bf[:28], len(lst), sum(x["tam"] for x in lst),
                 len(conjuntos), len(crcs)))


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    for cam in sys.argv[1:3]:
        relatorio(cam, coleta(cam))
