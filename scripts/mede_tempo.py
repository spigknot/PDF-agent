"""Mede o tempo de compressão em N rodadas e reporta as estatísticas.

Regra do projeto: TODA mudança importante tem o tempo medido — e uma rodada
só não serve, porque a variância medida na mesma máquina é de 1–5 s.

Uso:
  py -3.11 scripts/mede_tempo.py                    # recommended, 3 rodadas
  py -3.11 scripts/mede_tempo.py extreme 5
  py -3.11 scripts/mede_tempo.py low 1 --fases      # mostra o tempo por fase

Saída: uma linha por rodada (total e, opcionalmente, as fases) + resumo com
mínimo, mediana, média e máximo. Exit 0 mesmo com variação.
"""
import argparse
import os
import re
import statistics
import subprocess
import sys
import tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORIG = r"C:\Users\Gustavo\Desktop\lab\processo.pdf"
PY = sys.executable

RE_TOTAL = re.compile(r"^\[6\].*\(\+([\d.,]+)s\)", re.M)
RE_FASE = re.compile(r"^\[(\d)\] (.+?) \(\+([\d.,]+)s\)", re.M)


def _num(txt):
    # o tempo sai de `%.1f` do Python: ponto e' DECIMAL ("75.5"), nunca milhar
    return float(txt.replace(",", ""))


def roda(nivel, fases=False):
    tmp = tempfile.mkdtemp(prefix="mede_tempo_")
    saida = os.path.join(tmp, "out.pdf")
    env = dict(os.environ)
    if fases:
        env["PDFAGENT_DEBUG_TEMPO"] = "1"
    p = subprocess.run([PY, os.path.join(RAIZ, "compress.py"), ORIG,
                        "-n", nivel, "-o", saida],
                       cwd=RAIZ, capture_output=True, text=True,
                       errors="replace", env=env)
    out = (p.stdout or "") + (p.stderr or "")
    m = RE_TOTAL.search(out)
    total = _num(m.group(1)) if m else None
    marcas = [(int(n), _num(t)) for n, _rot, t in RE_FASE.findall(out)]
    return total, marcas, p.returncode


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("nivel", nargs="?", default="recommended")
    ap.add_argument("rodadas", nargs="?", type=int, default=3)
    ap.add_argument("--fases", action="store_true",
                    help="imprime o tempo de cada fase ([1]..[6])")
    args = ap.parse_args()

    if not os.path.exists(ORIG):
        print("lab ausente em %s" % ORIG)
        return 2

    tempos = []
    ultimas = []
    for i in range(args.rodadas):
        total, marcas, rc = roda(args.nivel, args.fases)
        if total is None:
            print("rodada %d: FALHOU (rc=%d, sem linha [6])" % (i + 1, rc))
            continue
        tempos.append(total)
        ultimas = marcas
        extra = ""
        if args.fases and marcas:
            extra = "  " + " ".join("[%d]=%.1fs" % (n, t) for n, t in marcas)
        print("rodada %d: %.1f s%s" % (i + 1, total, extra))

    if not tempos:
        return 1
    print("\n%s (%d rodada(s)): min %.1f | mediana %.1f | media %.1f | "
          "max %.1f  [espalhamento %.1f s]"
          % (args.nivel, len(tempos), min(tempos), statistics.median(tempos),
             statistics.mean(tempos), max(tempos),
             max(tempos) - min(tempos)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
