"""Compara o content stream (por operador) entre dois PDFs de mesmo layout.

Uso:
  python scripts/diag_conteudo.py A.pdf B.pdf
  python scripts/diag_conteudo.py A.pdf B.pdf paginas:0,50,120

A coluna "delta" e' A - B: positivo = temos mais aquele operador que a
referencia (candidato a corte).
"""
import collections
import sys

import pikepdf


def conta(caminho, paginas):
    pdf = pikepdf.open(caminho)
    total = collections.Counter()
    dec = 0
    for i, pg in enumerate(pdf.pages):
        c = pg.obj.get("/Contents")
        vals = list(c) if c is not None and c._type_name == "array" else [c]
        dados = b"\n".join(s.read_bytes() for s in vals if s is not None)
        dec += len(dados)
        if paginas and i not in paginas:
            continue
        try:
            for _ops, op in pikepdf.parse_content_stream(pg):
                total[str(op)] += 1
        except Exception:
            continue
    pdf.close()
    return total, dec


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    paginas = set()
    if len(argv) > 2 and ":" in argv[2]:
        paginas = {int(x) for x in argv[2].split(":", 1)[1].split(",") if x}
    ca, da = conta(argv[0], paginas)
    cb, db = conta(argv[1], paginas)
    print("%-14s %10s %10s %8s" % ("operador", "A", "B", "delta"))
    for op in sorted(set(ca) | set(cb), key=lambda o: -(ca[o] - cb[o])):
        if ca[op] == cb[op]:
            continue
        print("%-14s %10d %10d %+8d" % (op, ca[op], cb[op], ca[op] - cb[op]))
    print("\ndescomprimido: %d x %d (%+.1f%%)"
          % (da, db, 100.0 * (da - db) / db if db else 0.0))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
