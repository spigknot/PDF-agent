"""Gera os ícones dos dois botões da tela única do menu de contexto.

- `btn_comprimir.png`: setas convergindo (compressão).
- `btn_dividir.png`: tesoura sobre linha tracejada (divisão).
Estilo: traço grosso índigo (#3445C8) sobre fundo transparente — legível a 48 px.

Uso: py -3.11 scripts/make_menu_icons.py
"""
import math
import os

from PIL import Image, ImageDraw

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PASTA = os.path.join(RAIZ, "assets")
os.makedirs(PASTA, exist_ok=True)

S = 192
INDIGO = (52, 69, 200, 255)


def seta(draw, ponta, direcao, tamanho=44, largura=26):
    """Triângulo + haste na direção (dx, dy) unitária terminando em `ponta`."""
    dx, dy = direcao
    px, py = ponta
    perp = (-dy, dx)
    base = (px - dx * tamanho, py - dy * tamanho)
    draw.polygon([
        ponta,
        (base[0] + perp[0] * tamanho * 0.45, base[1] + perp[1] * tamanho * 0.45),
        (base[0] - perp[0] * tamanho * 0.45, base[1] - perp[1] * tamanho * 0.45),
    ], fill=INDIGO)
    draw.line([base, (base[0] - dx * tamanho * 0.9, base[1] - dy * tamanho * 0.9)],
              fill=INDIGO, width=largura)


def comprimir():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    seta(d, (S // 2 - 8, S // 2), (1, 0))
    seta(d, (S // 2 + 8, S // 2), (-1, 0))
    return img


def dividir():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # linha tracejada do corte
    for y in range(14, S - 10, 26):
        d.rounded_rectangle((S // 2 - 4, y, S // 2 + 4, y + 15),
                            radius=4, fill=(140, 155, 220, 255))
    # tesoura: dois anéis + lâminas cruzadas até a linha de corte
    d.ellipse((26, 34, 66, 74), outline=INDIGO, width=11)
    d.ellipse((26, 118, 66, 158), outline=INDIGO, width=11)
    d.line([(62, 54), (S // 2 - 4, 96)], fill=INDIGO, width=13, joint="curve")
    d.line([(62, 138), (S // 2 - 4, 96)], fill=INDIGO, width=13, joint="curve")
    # rosca
    d.ellipse((82, 86, 102, 106), fill=INDIGO)
    return img


def main():
    for nome, img in (("btn_comprimir.png", comprimir()),
                      ("btn_dividir.png", dividir())):
        caminho = os.path.join(PASTA, nome)
        img.save(caminho)
        print("%-20s %8d B" % (nome, os.path.getsize(caminho)))


if __name__ == "__main__":
    main()
