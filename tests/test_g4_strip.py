"""Vacina do G4: o TIFF tem de sair em UMA strip e com a polaridade declarada.

Bug real (processo.pdf pg116-179): o Pillow escrevia o TIFF em strips de ~8 KB
e `_g4_bytes` concatenava os bytes. Cada strip do T6 e' autocontido, mas o
leitor de PDF decodifica o stream como um fluxo unico — o resultado foi o topo
da imagem invertido e o corpo em branco (77% de pixels pretos contra 4,1% do
original). A 150 dpi, com a imagem de referencia: multi-strip dava 22,9%-95,9%
de preto, uma strip da' 4,12% (igual a referencia).

O teste trava as duas propriedades que importam:
  1. uma unica strip (tag 273/279 com um valor so');
  2. os bytes crus sao os mesmos do TIFF (nada de concatenacao).
"""
import io
import os
import struct
import sys

from PIL import Image, ImageDraw

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
import compress  # noqa: E402


def _imagem(lado, listras=60):
    """Padrao com texto e listras finas: sensivel a inversao e a corte."""
    img = Image.new("1", (lado, lado), 1)
    d = ImageDraw.Draw(img)
    for y in range(0, lado, max(4, lado // listras)):
        d.line((0, y, lado, y), fill=0)
    d.rectangle((lado // 4, lado // 4, lado // 2, lado // 2), fill=0)
    return img


def _tags_tiff(t):
    endian = "<" if t[:2] == b"II" else ">"
    ifd = struct.unpack(endian + "I", t[4:8])[0]
    n = struct.unpack(endian + "H", t[ifd:ifd + 2])[0]
    info = {}
    for i in range(n):
        e = t[ifd + 2 + i * 12: ifd + 2 + (i + 1) * 12]
        tag, tip, cnt, val = struct.unpack(endian + "HHI4s", e)
        info[tag] = (tip, cnt, val)

    def valores(tag):
        tip, cnt, val = info[tag]
        if tip == 3 and cnt == 1:
            return struct.unpack(endian + "H", val[:2])[0]
        if tip == 4 and cnt == 1:
            return struct.unpack(endian + "I", val)[0]
        off = struct.unpack(endian + "I", val)[0]
        return struct.unpack(endian + "%dI" % cnt, t[off:off + 4 * cnt])
    return info, valores


def test_g4_uma_strip_so():
    """Imagem grande o bastante para o Pillow querer varias strips."""
    img = _imagem(1400)
    tiff = compress._tiff_g4(img)
    _info, valores = _tags_tiff(tiff)
    offs = valores(273)
    n_strips = len(offs) if isinstance(offs, tuple) else 1
    assert n_strips == 1, ("TIFF G4 saiu com %d strips; concatenar strips "
                           "quebra a decodificacao no leitor de PDF" % n_strips)
    dados, w, h = compress._g4_bytes(img)
    assert (w, h) == img.size, (w, h)
    # os bytes devolvidos tem de ser exatamente a strip do TIFF
    tam = valores(279)
    tam = tam if isinstance(tam, tuple) else (tam,)
    assert len(dados) == sum(tam), (len(dados), tam)


def test_g4_ida_e_volta():
    """O que sai do _g4_bytes volta a ser a mesma imagem (via TIFF 1-strip)."""
    img = _imagem(600, listras=40)
    dados, w, h = compress._g4_bytes(img)
    # remonta um TIFF minimo com esses bytes e deixa o Pillow decodificar
    cab = bytearray()
    cab += b"II" + struct.pack("<HI", 42, 8)
    entradas = [(256, 4, 1, w), (257, 4, 1, h), (258, 3, 1, 1),
                (259, 3, 1, 4), (262, 3, 1, 1), (273, 4, 1, 0),
                (277, 3, 1, 1), (278, 4, 1, h), (279, 4, 1, len(dados))]
    n = len(entradas)
    inicio_dados = 8 + 2 + n * 12 + 4
    corpo = bytearray(struct.pack("<H", n))
    for tag, tip, cnt, val in entradas:
        if tag == 273:
            val = inicio_dados
        if tip == 3:
            corpo += struct.pack("<HHIHH", tag, tip, cnt, val, 0)
        else:
            corpo += struct.pack("<HHII", tag, tip, cnt, val)
    tiff = bytes(cab) + bytes(corpo) + b"\x00\x00\x00\x00" + dados
    back = Image.open(io.BytesIO(tiff)).convert("1")
    assert back.size == img.size, back.size
    assert back.tobytes() == img.tobytes(), "a imagem mudou no caminho G4"


def main():
    falhas = 0
    for nome in sorted(n for n in globals() if n.startswith("test_")):
        try:
            globals()[nome]()
            print("  ok    %s" % nome)
        except AssertionError as ex:
            falhas += 1
            print("  FALHA %s: %s" % (nome, ex))
    print("falhas: %d" % falhas)
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
