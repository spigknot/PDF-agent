"""Gate do documento de estresse (lab\\processo.pdf, 376 paginas).

Valida o que os bugs de 14/11 quebraram: tamanho, TEXTO EXTRAIDO e RENDER.
A paridade estrutural do corpus pequeno continua em tests/test_paridade.py.

Uso:
  python tests/test_paridade_lab.py              # valida as 3 referencias
  python tests/test_paridade_lab.py --calibrar   # so imprime os numeros
  python tests/test_paridade_lab.py --niveis recommended
"""
import os
import sys
import tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
import compress  # noqa: E402

LAB = r"C:\Users\Gustavo\Desktop\lab"
ORIG = os.path.join(LAB, "processo.pdf")
REFS = {
    "recommended": os.path.join(LAB, "processo-compressed.pdf"),
    "extreme": os.path.join(LAB, "processo-compressed-extreme.pdf"),
    "low": os.path.join(LAB, "processo-compressed-low.pdf"),
}
# teto de tamanho relativo a referencia (medido em 14/11; apertar sozinho)
LIMITE = {"recommended": 1.010, "extreme": 1.030, "low": 1.000}
# fracao maxima de pixels diferentes contra a referencia (medido: 0.00114)
RENDER_MAX = 0.005
# paginas comparadas no render (as que ja divergiram em 14/11 + amostra)
PAGINAS = (0, 21, 50, 120, 148, 209, 300, 337, 338, 375)


def _texto(caminho):
    import fitz
    d = fitz.open(caminho)
    try:
        return [p.get_text() for p in d]
    finally:
        d.close()


def _render_pior(a, b, paginas=PAGINAS):
    import fitz
    import numpy as np
    da, db = fitz.open(a), fitz.open(b)
    pior = 0.0
    try:
        for i in paginas:
            if i >= len(da) or i >= len(db):
                continue
            pa, pb = da[i].get_pixmap(dpi=80), db[i].get_pixmap(dpi=80)
            na = np.frombuffer(pa.samples, dtype=np.uint8).reshape(
                pa.height, pa.width, pa.n)
            nb = np.frombuffer(pb.samples, dtype=np.uint8).reshape(
                pb.height, pb.width, pb.n)
            if na.shape != nb.shape:
                return 1.0
            dif = np.abs(na.astype("int16") - nb.astype("int16")).max(axis=2)
            frac = float((dif > 24).sum()) / (na.shape[0] * na.shape[1])
            pior = max(pior, frac)
    finally:
        da.close()
        db.close()
    return pior


def main(argv):
    calibrar = "--calibrar" in argv
    niveis = ["recommended", "extreme", "low"]
    for i, a in enumerate(argv):
        if a == "--niveis" and i + 1 < len(argv):
            niveis = [x.strip() for x in argv[i + 1].split(",") if x.strip()]

    if not os.path.exists(ORIG) or not all(os.path.exists(REFS[n]) for n in niveis):
        print("lab ausente em %s — teste pulado" % LAB)
        return 0

    tmp = tempfile.mkdtemp(prefix="paridade_lab_")
    texto_orig = _texto(ORIG)
    falhas = total = 0
    for nivel in niveis:
        ref = REFS[nivel]
        saida = os.path.join(tmp, "processo_%s.pdf" % nivel)
        r = compress.comprimir(ORIG, saida, nivel, log=lambda m: None)
        total += 1

        tam_ref = os.path.getsize(ref)
        razao = r["depois"] / tam_ref
        texto = _texto(saida)
        pag_texto = [i for i in range(min(len(texto), len(texto_orig)))
                     if texto[i] != texto_orig[i]]
        pior = _render_pior(saida, ref)

        problemas = []
        if razao > LIMITE[nivel]:
            problemas.append("tamanho %.4f > %.3f" % (razao, LIMITE[nivel]))
        if len(texto) != len(texto_orig):
            problemas.append("paginas %d != %d" % (len(texto), len(texto_orig)))
        if pag_texto:
            problemas.append("texto difere em %d pagina(s): %s"
                             % (len(pag_texto), pag_texto[:6]))
        if pior > RENDER_MAX:
            problemas.append("render %.4f > %.3f" % (pior, RENDER_MAX))

        if calibrar:
            print("  %-12s %d B (%.4f da ref) | texto!=orig %d | render %.4f%%"
                  % (nivel, r["depois"], razao, len(pag_texto), 100 * pior))
            continue
        if problemas:
            falhas += 1
            print("  %-12s FALHA: %s" % (nivel, "; ".join(problemas)))
        else:
            print("  %-12s ok  (%d B, %.2f%% da ref, texto!=orig %d, render %.3f%%)"
                  % (nivel, r["depois"], 100 * razao, len(pag_texto), 100 * pior))

    if calibrar:
        return 0
    print("\n%d/%d combinacoes do documento de estresse com problema" % (falhas, total))
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
