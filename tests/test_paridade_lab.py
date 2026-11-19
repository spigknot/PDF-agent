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
# nomes aceitos para o baseline do motor (o lab ja foi reorganizado algumas
# vezes): usa o primeiro que existir
_CANDIDATOS = {
    "recommended": ("processo-compressed.pdf", "processo-recommended.pdf"),
    "extreme": ("processo-compressed-extreme.pdf", "processo-extreme.pdf"),
    "low": ("processo-compressed-low.pdf", "processo-low.pdf"),
}


def _ref(nivel):
    for nome in _CANDIDATOS[nivel]:
        caminho = os.path.join(LAB, nome)
        if os.path.exists(caminho):
            return caminho
    return os.path.join(LAB, _CANDIDATOS[nivel][0])


REFS = {nivel: _ref(nivel) for nivel in _CANDIDATOS}
# teto de tamanho relativo a referencia. Apertado em 14/11 com o ganho medido
# (0,990 / 1,004 / 0,950): qualquer regressao acima disso reprova.
LIMITE = {"recommended": 1.000, "extreme": 1.015, "low": 0.990}
# paginas com texto divergente ACEITAS (bug conhecido, documentado em
# docs/METODO.md §5). Medido em 22/11 com a fusao de fontes DESLIGADA: as mesmas
# 3 paginas divergem do mesmo jeito, entao NAO e' regressao da fusao — e' o
# extrator do MuPDF (o original tambem extrai U+FFFD no "i" acentuado do
# Calibri, GID 304) e o NBSP virando espaco. A lista e' explicita: qualquer
# pagina NOVA divergindo reprova, mesmo dentro do teto.
TEXTO_MAX = {"recommended": 0, "extreme": 3, "low": 0}
TEXTO_CONHECIDO = {"recommended": set(), "extreme": {180, 210, 222}, "low": set()}
# Render: compara com o ORIGINAL, nao com a referencia do motor. Medido em
# 22/11: nas 22 paginas onde nos afastamos >0,5% do motor, somos MAIS fieis ao
# original em TODAS (pg44: 0,05% nosso x 5,23% dele; pg218: 9,60% x 12,76%) —
# comparar com o motor punia a nossa fidelidade. E as 10 paginas fixas que
# existiam aqui escondiam a pg218: agora sao as 376.
# Tetos por nivel (medidos em 22/11, com margem ~10%). O extreme comprime
# imagem mais forte e a pg218 (imagem de fundo) re-renderiza inteira: 16,5%.
RENDER_MEDIA_MAX = {"recommended": 0.0037, "extreme": 0.0080, "low": 0.0045}
RENDER_PIOR_MAX = {"recommended": 0.105, "extreme": 0.180, "low": 0.020}
PAGINAS = None                 # None = todas as paginas


def _texto(caminho):
    import fitz
    d = fitz.open(caminho)
    try:
        return [p.get_text() for p in d]
    finally:
        d.close()


def _render_stats(a, b, paginas=PAGINAS):
    """(media, pior, pagina_do_pior) da fracao de pixels diferentes."""
    import fitz
    import numpy as np
    da, db = fitz.open(a), fitz.open(b)
    pior = 0.0
    pior_pg = 0
    soma = 0.0
    n = 0
    try:
        alvo = range(min(len(da), len(db))) if paginas is None else paginas
        for i in alvo:
            if i >= len(da) or i >= len(db):
                continue
            pa, pb = da[i].get_pixmap(dpi=80), db[i].get_pixmap(dpi=80)
            na = np.frombuffer(pa.samples, dtype=np.uint8).reshape(
                pa.height, pa.width, pa.n)
            nb = np.frombuffer(pb.samples, dtype=np.uint8).reshape(
                pb.height, pb.width, pb.n)
            if na.shape != nb.shape:
                return 1.0, 1.0, i + 1
            dif = np.abs(na.astype("int16") - nb.astype("int16")).max(axis=2)
            frac = float((dif > 24).sum()) / (na.shape[0] * na.shape[1])
            soma += frac
            n += 1
            if frac > pior:
                pior, pior_pg = frac, i + 1
    finally:
        da.close()
        db.close()
    return (soma / n if n else 0.0), pior, pior_pg


def _processa_nivel(arg):
    """Roda UM nivel e devolve (nivel, linhas_de_saida, falhou).

    Funcao de modulo para poder rodar em ProcessPoolExecutor: os tres niveis
    do documento de estresse sao independentes.
    """
    nivel, tmp, texto_orig, calibrar = arg
    import os
    # cada nivel tem o proprio pool de processos; dividir evita 72 processos
    # (3 x 24) disputando 36 CPUs
    os.environ.setdefault("PDFAGENT_PROC_WORKERS",
                          str(max(2, (os.cpu_count() or 4) // 3)))
    ref = REFS[nivel]
    saida = os.path.join(tmp, "processo_%s.pdf" % nivel)
    r = compress.comprimir(ORIG, saida, nivel, log=lambda m: None)
    tam_ref = os.path.getsize(ref)
    razao = r["depois"] / tam_ref
    texto = _texto(saida)
    pag_texto = [i for i in range(min(len(texto), len(texto_orig)))
                 if texto[i] != texto_orig[i]]
    media, pior, pior_pg = _render_stats(saida, ORIG, PAGINAS)
    problemas = []
    if razao > LIMITE[nivel]:
        problemas.append("tamanho %.4f > %.3f" % (razao, LIMITE[nivel]))
    if len(texto) != len(texto_orig):
        problemas.append("paginas %d != %d" % (len(texto), len(texto_orig)))
    if len(pag_texto) > TEXTO_MAX[nivel]:
        problemas.append("texto: %d pagina(s) > teto %d (%s)"
                         % (len(pag_texto), TEXTO_MAX[nivel], pag_texto[:6]))
    novas = set(i + 1 for i in pag_texto) - TEXTO_CONHECIDO[nivel]
    if novas:
        problemas.append("texto divergiu em pagina(s) nova(s): %s"
                         % sorted(novas)[:6])
    if media > RENDER_MEDIA_MAX[nivel]:
        problemas.append("render medio %.4f > %.4f"
                         % (media, RENDER_MEDIA_MAX[nivel]))
    if pior > RENDER_PIOR_MAX[nivel]:
        problemas.append("render pior %.4f > %.3f (pg %d)"
                         % (pior, RENDER_PIOR_MAX[nivel], pior_pg))
    if calibrar:
        return nivel, ["  %-12s %d B (%.4f da ref) | texto!=orig %d | "
                       "render medio %.3f%% pior %.2f%% (pg %d)"
                       % (nivel, r["depois"], razao, len(pag_texto),
                          100 * media, 100 * pior, pior_pg)], False
    if problemas:
        return nivel, ["  %-12s FALHA: %s" % (nivel, "; ".join(problemas))], True
    return nivel, ["  %-12s ok  (%d B, %.2f%% da ref, texto!=orig %d, "
                   "render %.3f%%)"
                   % (nivel, r["depois"], 100 * razao, len(pag_texto),
                      100 * pior)], False


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
    tarefas = [(n, tmp, texto_orig, calibrar) for n in niveis]
    resultados = None
    if len(niveis) > 1 and "--sequencial" not in argv:
        try:
            # Niveis sao independentes: rodar os 3 em paralelo corta o gate de
            # ~10 min para ~4 min. Cada compress ja' usa processos proprios,
            # entao o worker divide as CPUs entre os niveis.
            from concurrent.futures import ProcessPoolExecutor
            with ProcessPoolExecutor(max_workers=len(niveis)) as pool:
                resultados = list(pool.map(_processa_nivel, tarefas))
        except Exception as ex:
            print("  paralelo indisponivel (%s); em serie" % ex)
            resultados = None
    if resultados is None:
        resultados = [_processa_nivel(t) for t in tarefas]
    falhas = total = 0
    for nivel, linhas, falhou in resultados:
        for linha in linhas:
            print(linha)
        total += 1
        falhas += 1 if falhou else 0
    if calibrar:
        return 0
    print("\n%d/%d combinacoes do documento de estresse com problema" % (falhas, total))
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
