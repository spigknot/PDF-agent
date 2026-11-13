"""Testes do comando split: limite respeitado, páginas inteiras, sem corte."""
import os
import random
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pikepdf  # noqa: E402
from PIL import Image  # noqa: E402
import fitz  # noqa: E402
from commands import split as comando  # noqa: E402

LIMITE = 220_000


def gera_fixture(caminho, paginas=6):
    random.seed(11)
    doc = fitz.open()
    for i in range(paginas):
        pg = doc.new_page(width=595, height=842)
        pg.insert_text((72, 72), "pagina %d" % (i + 1), fontsize=18)
        img = Image.new("RGB", (600, 800))
        px = img.load()
        for y in range(0, 800, 3):
            for x in range(0, 600, 3):
                v = (x * 7 + y * 13 + random.randint(0, 60)) % 256
                for dy in range(3):
                    for dx in range(3):
                        if y + dy < 800 and x + dx < 600:
                            px[x + dx, y + dy] = (v, (v * 3) % 256, (v * 7) % 256)
        png = caminho + ".png"
        img.save(png)
        pg.insert_image(fitz.Rect(40, 90, 555, 780), filename=png)
        os.remove(png)
    doc.save(caminho, deflate=True)
    doc.close()


def paginas_de(caminho):
    with pikepdf.open(caminho) as p:
        return len(p.pages)


def main():
    tmp = tempfile.mkdtemp(prefix="split_")
    origem = os.path.join(tmp, "doc.pdf")
    gera_fixture(origem)
    total_antes = os.path.getsize(origem)
    print("fixture: %d B, %d páginas" % (total_antes, paginas_de(origem)))

    # 1) divisão com limite: sem compressão para medir o split puro
    r = comando.dividir(origem, LIMITE, comprimir=False, destino=os.path.join(tmp, "a"),
                        log=lambda m: None)
    assert r["precisa_dividir"], "deveria dividir"
    somas = 0
    for caminho in r["partes"]:
        tam = os.path.getsize(caminho)
        assert tam <= LIMITE, "parte %s = %d > limite %d" % (caminho, tam, LIMITE)
        somas += paginas_de(caminho)
    assert somas == paginas_de(origem), "páginas perdidas: %d != %d" % (somas, paginas_de(origem))
    print("dividido em %d partes, todas <= %.2f MB, %d páginas preservadas"
          % (len(r["partes"]), LIMITE / 1048576, somas))

    # 2) limite maior que o arquivo: não divide
    r2 = comando.dividir(origem, total_antes * 2, comprimir=False,
                         destino=os.path.join(tmp, "b"), log=lambda m: None)
    assert not r2["precisa_dividir"], "não deveria dividir"
    print("sem divisão quando cabe no limite: ok")

    # 3) compressão prévia pode evitar a divisão
    r3 = comando.dividir(origem, total_antes, comprimir=True,
                         destino=os.path.join(tmp, "c"), log=lambda m: None)
    print("com compressão: precisa_dividir=%s partes=%d"
          % (r3["precisa_dividir"], len(r3["partes"])))
    for c in r3["partes"]:
        assert os.path.getsize(c) <= total_antes
    print("TUDO OK")


if __name__ == "__main__":
    main()
