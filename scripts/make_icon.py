"""Gera o ícone do PDFagent (PNG alta resolução + ICO multi-tamanho).

Conceito: uma página sendo "dobráda" para dentro — as duas setas indicam
compressão e a linha tracejada indica a divisão; o canto dobrado dá o ar de
papel/origami. Fundo em degradê índigo → ciano, com brilho suave.

Uso: py -3.11 scripts/make_icon.py
"""
import os
from PIL import Image, ImageDraw, ImageFilter

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PASTA = os.path.join(RAIZ, "assets")
os.makedirs(PASTA, exist_ok=True)

S = 1024                      # master; redimensionado com Lanczos
C = S // 2


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def gradiente():
    img = Image.new("RGBA", (S, S))
    px = img.load()
    topo, fundo = (91, 108, 255), (28, 205, 196)
    for y in range(S):
        for x in range(S):
            t = min(1.0, max(0.0, (y + x * 0.18) / (S * 1.15)))
            r, g, b = lerp(topo, fundo, t)
            px[x, y] = (r, g, b, 255)
    return img


def main():
    base = gradiente()

    # brilho suave no canto superior esquerdo
    brilho = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(brilho)
    d.ellipse((-230, -300, 620, 330), fill=(255, 255, 255, 46))
    base = Image.alpha_composite(base, brilho.filter(ImageFilter.GaussianBlur(90)))

    # máscara do tile arredondado
    mascara = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mascara).rounded_rectangle((16, 16, S - 16, S - 16),
                                              radius=232, fill=255)
    tile = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    tile.paste(base, (0, 0), mascara)

    d = ImageDraw.Draw(tile)

    # folha branca com canto superior direito dobrado
    folha = (268, 190, 762, 836)
    d.rounded_rectangle(folha, radius=34, fill=(247, 250, 255, 255))
    d.polygon([(762, 190), (762, 330), (622, 190)], fill=(205, 219, 255, 255))
    d.line([(622, 190), (622, 330), (762, 330)],
           fill=(163, 185, 245, 255), width=8, joint="curve")

    # linhas de "texto" — grossas o bastante para sobreviver a 16 px
    cor_linha = (120, 142, 205, 255)
    for y, w in ((450, 330), (530, 280), (610, 240)):
        d.rounded_rectangle((330, y, 330 + w, y + 30), radius=15, fill=cor_linha)

    # linha tracejada vertical: a divisão
    for y in range(690, 816, 34):
        d.rounded_rectangle((C - 5, y, C + 5, y + 20), radius=5,
                            fill=(91, 108, 255, 255))

    # duas setas convergindo: a compressão (desenhadas com polígonos)
    azul = (52, 92, 220, 255)
    d.polygon([(338, 348), (420, 392), (338, 436), (338, 408), (300, 408),
               (300, 376), (338, 376)], fill=azul)
    d.polygon([(692, 348), (610, 392), (692, 436), (692, 408), (730, 408),
               (730, 376), (692, 376)], fill=azul)

    tile.save(os.path.join(PASTA, "pdfagent-512.png").replace("-512", "-master"))

    # versão de apresentação 512 px
    tile.resize((512, 512), Image.LANCZOS).save(
        os.path.join(PASTA, "pdfagent-preview.png"))

    # ICO com todos os tamanhos que o Windows usa
    tamanhos = [(256, 256), (128, 128), (64, 64), (48, 48),
                (32, 32), (24, 24), (16, 16)]
    tile.save(os.path.join(PASTA, "pdfagent.ico"),
              format="ICO", sizes=tamanhos)

    for nome in ("pdfagent.ico", "pdfagent-preview.png", "pdfagent-master.png"):
        p = os.path.join(PASTA, nome)
        print("%-24s %8d B" % (nome, os.path.getsize(p)))


if __name__ == "__main__":
    main()
