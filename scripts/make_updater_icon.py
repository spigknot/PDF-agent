"""Gera o ícone do PDFagentUpdater (PNG + ICO multi-tamanho).

Família visual igual à do app (squircle, degradê índigo → ciano), mas com
motivo próprio: um anel circular de atualização envolvendo uma seta de
download — leitura即时 de "baixar e instalar versão nova", mesmo a 16 px.

Uso: py -3.11 scripts/make_updater_icon.py
"""
import os
from PIL import Image, ImageDraw, ImageChops, ImageFilter

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PASTA = os.path.join(RAIZ, "assets")
os.makedirs(PASTA, exist_ok=True)

S = 1024


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def base_gradiente():
    img = Image.new("RGBA", (S, S))
    px = img.load()
    topo, fundo = (91, 108, 255), (28, 205, 196)
    for y in range(S):
        for x in range(S):
            t = min(1.0, max(0.0, (y + x * 0.18) / (S * 1.15)))
            px[x, y] = lerp(topo, fundo, t) + (255,)
    brilho = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    db = ImageDraw.Draw(brilho)
    db.ellipse((-230, -300, 620, 330), fill=(255, 255, 255, 46))
    img = Image.alpha_composite(img, brilho.filter(ImageFilter.GaussianBlur(90)))
    mascara = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mascara).rounded_rectangle((16, 16, S - 16, S - 16),
                                              radius=232, fill=255)
    tile = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    tile.paste(img, (0, 0), mascara)
    return tile


def anel(draw, caixa, cor, largura, graus_inicio=-70, graus_fim=225):
    """Arco espesso com uma ponta de seta na extremidade final."""
    draw.arc(caixa, graus_inicio, graus_fim, fill=cor, width=largura)
    import math
    x0, y0, x1, y1 = caixa
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    rx, ry = (x1 - x0) / 2, (y1 - y0) / 2
    a = math.radians(graus_fim)
    px, py = cx + rx * math.cos(a), cy + ry * math.sin(a)
    # seta tangente ao arco
    t = math.radians(graus_fim + 90)
    size = largura * 2.1
    p1 = (px - size * math.cos(t) + size * 0.6 * math.cos(a),
          py - size * math.sin(t) + size * 0.6 * math.sin(a))
    p2 = (px - size * math.cos(t) - size * 0.6 * math.cos(a),
          py - size * math.sin(t) - size * 0.6 * math.sin(a))
    draw.polygon([(px, py), p1, p2], fill=cor)


def main():
    tile = base_gradiente()
    d = ImageDraw.Draw(tile)
    branco = (255, 255, 255, 255)

    # anel de atualização (aberto no topo, ponta de seta)
    anel(d, (222, 206, 802, 786), branco, 74)

    # seta de download no centro
    d.rounded_rectangle((488, 330, 536, 570), radius=22, fill=branco)
    d.polygon([(512, 622), (398, 508), (626, 508)], fill=branco)

    # "bandeja"/linha de destino
    d.rounded_rectangle((386, 660, 638, 718), radius=29, fill=branco)

    # dois pontinhos discretos reforçando "novo"
    d.ellipse((270, 288, 306, 324), fill=(220, 248, 255, 235))
    d.ellipse((306, 254, 330, 278), fill=(220, 248, 255, 200))

    tile.save(os.path.join(PASTA, "pdfagent-updater-master.png"))
    tile.resize((512, 512), Image.LANCZOS).save(
        os.path.join(PASTA, "pdfagent-updater-preview.png"))
    tile.save(os.path.join(PASTA, "pdfagent-updater.ico"), format="ICO",
              sizes=[(256, 256), (128, 128), (64, 64), (48, 48),
                     (32, 32), (24, 24), (16, 16)])
    for nome in ("pdfagent-updater.ico", "pdfagent-updater-preview.png"):
        p = os.path.join(PASTA, nome)
        print("%-30s %8d B" % (nome, os.path.getsize(p)))


if __name__ == "__main__":
    main()
