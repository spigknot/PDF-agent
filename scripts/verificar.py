"""Gate unico de verificacao do CompressPDF/PDF-agent.

Roda, em sequencia:
  1. testes unitarios de nivel           (tests/test_levels.py)
  2. paridade estrutural vs iLovePDF      (tests/test_paridade.py)  [se REA-lab existir]
  3. launcher .bat (sintaxe + caminho)    (simula sem abrir a GUI)
  4. exit code do CLI em falha            (precisa ser != 0)

Uso:  python scripts/verificar.py [--lab CAMINHO] [--max-difs N]
Saida: resumo PASS/FAIL; exit 1 se algum item falhar.
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
LAB_PADRAO = r"C:\Users\Gustavo\Desktop\REA-lab"
BAT = os.path.join(RAIZ, "CompressPDF.bat")


def roda(comando, cwd=None, timeout=1800):
    p = subprocess.run(comando, cwd=cwd or RAIZ, capture_output=True,
                       text=True, errors="replace", timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def item(nome, ok, detalhe=""):
    print("  [%s] %-42s %s" % ("OK" if ok else "FALHA", nome, detalhe))
    return ok


def teste_niveis():
    rc, saida = roda([PY, os.path.join(RAIZ, "tests", "test_levels.py")])
    ok = rc == 0 and "TUDO OK" in saida
    return item("testes de nivel (3 niveis)", ok,
                "" if ok else saida.strip().splitlines()[-1][:120])


def teste_paridade(lab, max_difs):
    if not os.path.isdir(os.path.join(lab, "originais")):
        print("  [pulado] paridade estrutural: corpus ausente em %s" % lab)
        return True, None
    rc, saida = roda([PY, os.path.join(RAIZ, "tests", "test_paridade.py"),
                      "--lab", lab])
    m = re.search(r"(\d+)/(\d+) combinacoes com diferenca estrutural", saida)
    n_difs = int(m.group(1)) if m else -1
    total = int(m.group(2)) if m else 0
    maior = "MAIOR" in saida
    ok = (rc in (0, 1)) and not maior and 0 <= n_difs <= max_difs
    det = "%d/%d com diferenca" % (n_difs, total) if n_difs >= 0 else "nao parseou"
    if maior:
        det += " | ARQUIVO MAIOR QUE O ILOVEPDF"
    return item("paridade estrutural vs iLovePDF", ok, det), n_difs


def teste_launcher():
    if not os.path.exists(BAT):
        return item("launcher .bat", False, "CompressPDF.bat ausente")
    with open(BAT, encoding="utf-8", errors="replace") as f:
        conteudo = f.read()
    if "cd /d \"%~dp0\"" not in conteudo:
        return item("launcher .bat", False, "sem cd /d \"%~dp0\"")
    # roda uma copia que nao abre a GUI: troca o start por echo
    tmp = os.path.join(RAIZ, "_verifica_launcher.bat")
    try:
        with open(tmp, "w", encoding="ascii", errors="replace", newline="\r\n") as f:
            f.write(conteudo.replace('start "" "%PYW%" app.py',
                                     "echo LAUNCH_OK cd=%~dp0"))
        rc, saida = roda(["cmd", "/c", "_verifica_launcher.bat"], timeout=120)
    finally:
        try:
            os.remove(tmp)
        except Exception:
            pass
    ok = rc == 0 and "LAUNCH_OK cd=%s" % RAIZ in saida
    return item("launcher .bat (sintaxe e caminho)", ok,
                "" if ok else saida.strip()[:120])


def teste_exit_code():
    rc, saida = roda([PY, os.path.join(RAIZ, "compress.py"),
                      "arquivo_que_nao_existe.pdf"], timeout=180)
    ok = rc != 0
    return item("CLI falha com exit code != 0", ok, "rc=%d" % rc)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lab", default=LAB_PADRAO)
    ap.add_argument("--max-difs", type=int, default=0,
                    help="teto de combinacoes com diferenca estrutural (0 = exige paridade total)")
    args = ap.parse_args()

    print("== verificacao do compressor ==  (%s)" % RAIZ)
    resultados = [teste_niveis(), teste_exit_code(), teste_launcher()]
    par_ok, _n_difs = teste_paridade(args.lab, args.max_difs)
    resultados.append(par_ok)

    ok = all(bool(r) for r in resultados)
    print("\n%s" % ("PASS — tudo dentro do esperado" if ok else "FAIL — ver itens acima"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
