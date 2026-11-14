# compress.py — Núcleo do CompressPDF.
#
# Replica fiel dos 3 níveis do iLovePDF Desktop 2.3.4 (engine 3-Heights PDF
# Optimizer), com parâmetros extraídos por engenharia reversa do binário
# (ver docs/METODO.md). Usa apenas bibliotecas open-source (pikepdf+Pillow):
# o SDK comercial original exige licença e não é redistribuível.
#
# Uso CLI:
#   python compress.py entrada.pdf -n extreme|recommended|low [-o saida.pdf]
#   python compress.py pasta/ -n recommended --saida-dir out/
import argparse
import io
import math
import os
import re
import struct
import sys
import zlib
from collections import defaultdict

try:
    import pikepdf
    from pikepdf import Name
except ImportError:
    sys.exit("ERRO: instale as dependencias: pip install -r requirements.txt")
try:
    from PIL import Image
except ImportError:
    sys.exit("ERRO: instale as dependencias: pip install -r requirements.txt")

# ----------------------------------------------------------------------------
# Tabela de níveis — extraída de iLovePdfTools.dll
#   ExtremeCompressSettings    @ RVA 0x35990  (level == 2)
#   RecommendedCompressSettings@ RVA 0x35F30  (level == 1, default)
#   LowCompressSettings        @ RVA 0x35E90  (level == 0)
# Mapeamento de enums: manual oficial PdfOptimizeAPI 6.27 (3-Heights).
# ----------------------------------------------------------------------------
NIVEIS_VALIDOS = ("extreme", "recommended", "low")

# Subset de fontes CFF/CIDFontType0C ainda nao e' seguro (o subsetter do
# fontTools nao preserva o charset CID -> glifos trocados). Medido: 9,4% de
# divergencia de render. Mantido desligado; a rede de seguranca tambem
# reverte caso seja ligado.
_TENTA_CFF = False

# Desliga a escolha dupla de kernel (usada pela rede de seguranca)
_sem_risco_kernel = False
# objgens recortados pelo ClipImages nesta execucao (ver _alvo)
_CLIPADOS = set()

# Versao do aplicativo (mostrada por --version e usada no build do .exe)
VERSAO = "1.0.0"

LEVELS = {
    # Low (0): base = perfil Default (tudo desligado) + overrides abaixo.
    "low": {
        "rotulo": "Low",
        "descricao": "Alta qualidade, menos compressão",
        "resolucao": 200.0, "limiar": 400.0, "qualidade": 75,
        "conversao_cor": "none",          # SetColorConversion(0)
        "bitonal": ["g4"],                # SetBitonalCompressions(128=JBIG2*)
        "continuo": ["jpeg"],             # SetContinuousCompressions(2=JPEG)
        "indexado": [],                   # herda Default=None -> intocado
        "strip": set(),                   # nao chama SetStrip -> mantem tudo
        "achatar": False,
        "remove_fontes_padrao": True,     # SetRemoveStandardFonts(1)
        "reduz_cor": False,
        "otimiza_recursos": True, "remove_redundantes": True, "subset_fontes": True,
    },
    # Recommended (1): base = perfil Print(2) + overrides abaixo.
    "recommended": {
        "rotulo": "Recommended",
        "descricao": "Boa qualidade, boa compressão",
        "resolucao": 150.0, "limiar": 150.0, "qualidade": 60,
        "conversao_cor": "none",          # SetColorConversion(0)
        "bitonal": ["g4", "source"],      # herda Print = Group4+Source
        "continuo": ["jpeg", "flate", "source"],  # herda Print
        "indexado": ["flate", "source"],  # herda Print
        # SetStrip(1143 = 0x477). OBSERVADO em 8 saidas reais do iLovePDF:
        # metadados/docinfo/StructTree/links VISIVEIS sao MANTIDOS
        # (docinfo atualizado, XMP re-carimbado). Replica so o
        # comportamento observavel; ver docs/METODO.md.
        # O bit 10 (0x400) NAO remove anotacao invisivel: o REA localizou a
        # unica leitura da mascara em FUN_1800b00e0 (pre-save), onde ele
        # alimenta diagnostico (codigos 0x1401/0x1702/0x1712), nao conteudo.
        # Por isso "invisiveis" saiu do perfil (era fidelidade inventada).
        "strip": {"threads", "pieceinfo", "thumbs", "spider", "alternates",
                  "assinaturas"},
        "achatar": False,
        "remove_fontes_padrao": False,    # herda Print=False
        "reduz_cor": True,                # herda Print=True
        "clip": True,                     # herda Print=True (ver docs/METODO.md)
        "otimiza_recursos": True, "remove_redundantes": True, "subset_fontes": True,
    },
    # Extreme (2): base = perfil Print(2) + overrides abaixo.
    "extreme": {
        "rotulo": "Extreme",
        "descricao": "Menos qualidade, alta compressão",
        "resolucao": 72.0, "limiar": 110.0, "qualidade": 60,
        "conversao_cor": "rgb",           # SetColorConversion(1=eConvRGB)
        "bitonal": ["g4"],                # SetBitonalCompressions(128=JBIG2*)
        "continuo": ["jpeg"],             # SetContinuousCompressions(2=JPEG)
        "indexado": ["flate", "source"],  # herda Print
        "strip": {"threads", "metadata", "pieceinfo", "structtree", "thumbs",
                  "spider", "alternates", "assinaturas"},             # SetStrip(127 = 0x7F)
        "achatar": False,
        "remove_fontes_padrao": True,     # SetRemoveStandardFonts(1)
        "reduz_cor": True,                # SetReduceColorComplexity(1)
        "otimiza_recursos": True, "remove_redundantes": True, "subset_fontes": True,
        "clip": True,                     # SetClipImages(1) — ver limitacoes
    },
}
# * JBIG2 sem codificador open-source disponível: fallback Group4 (sem perda),
#   documentado em docs/METODO.md.

FONTES_PADRAO_14 = {
    "/Helvetica", "/Helvetica-Bold", "/Helvetica-Oblique", "/Helvetica-BoldOblique",
    "/Times-Roman", "/Times-Bold", "/Times-Italic", "/Times-BoldItalic",
    "/Courier", "/Courier-Bold", "/Courier-Oblique", "/Courier-BoldOblique",
    "/Symbol", "/ZapfDingbats",
}

# Equivalencia metrica comprovada pelo comportamento do iLovePDF (low/extreme):
# remove o programa da fonte e re-aponta para a padrao-14 correspondente.
# Nomes comparados apos tirar prefixo de subset e normalizar.
EQUIV_PADRAO = {
    "timesnewromanpsmt": "/Times-Roman",
    "timesnewroman": "/Times-Roman",
    "times": "/Times-Roman",
    "timesnewromanps-boldmt": "/Times-Bold",
    "timesnewroman-bold": "/Times-Bold",
    "times-bold": "/Times-Bold",
    "timesnewromanps-italicmt": "/Times-Italic",
    "timesnewroman-italic": "/Times-Italic",
    "times-italic": "/Times-Italic",
    "timesnewromanps-bolditalicmt": "/Times-BoldItalic",
    "timesnewroman-bolditalic": "/Times-BoldItalic",
    "times-bolditalic": "/Times-BoldItalic",
    "arialmt": "/Helvetica",
    "arial": "/Helvetica",
    "helvetica": "/Helvetica",
    "arial-boldmt": "/Helvetica-Bold",
    "arial-bold": "/Helvetica-Bold",
    "helvetica-bold": "/Helvetica-Bold",
    "arial-italicmt": "/Helvetica-Oblique",
    "arial-italic": "/Helvetica-Oblique",
    "helvetica-oblique": "/Helvetica-Oblique",
    "arial-bolditalicmt": "/Helvetica-BoldOblique",
    "arial-bolditalic": "/Helvetica-BoldOblique",
    "helvetica-boldoblique": "/Helvetica-BoldOblique",
    "couriernewpsmt": "/Courier",
    "couriernew": "/Courier",
    "courier": "/Courier",
    "couriernewps-boldmt": "/Courier-Bold",
    "couriernew-bold": "/Courier-Bold",
    "courier-bold": "/Courier-Bold",
    "couriernewps-italicmt": "/Courier-Oblique",
    "couriernew-italic": "/Courier-Oblique",
    "courier-oblique": "/Courier-Oblique",
    "couriernewps-bolditalicmt": "/Courier-BoldOblique",
    "couriernew-bolditalic": "/Courier-BoldOblique",
    "courier-boldoblique": "/Courier-BoldOblique",
    "symbol": "/Symbol",
    "symbolmt": "/Symbol",
    "zapfdingbats": "/ZapfDingbats",
    "zapfdingbatsitc": "/ZapfDingbats",
}


def _nome_base(base):
    """'BCDFEE+TimesNewRomanPSMT' -> 'timesnewromanpsmt' (normalizado)."""
    b = str(base).lstrip("/")
    if "+" in b:
        b = b.split("+", 1)[1]
    return b.replace(" ", "").replace(",", "").lower()


def _streams_fonte_vivos(pdf):
    """objgens dos streams de programa de fonte ainda referenciados."""
    vivos = set()
    for fo in _fontes_recursivas(pdf):
        try:
            candidatos = [fo]
            df = fo.get("/DescendantFonts")
            if df is not None:
                candidatos.extend(list(df))
            for f in candidatos:
                d = f.get("/FontDescriptor")
                if d is None:
                    continue
                for k in ("/FontFile", "/FontFile2", "/FontFile3"):
                    try:
                        st = d.get(k)
                        if st is not None:
                            vivos.add(st.objgen)
                    except Exception:
                        pass
        except Exception:
            pass
    return vivos


def _descritores_vivos(pdf):
    """objgens de todo FontDescriptor em uso (inclusive dentro de Type0)."""
    vivos = set()
    for fo in _fontes_recursivas(pdf):
        try:
            candidatos = [fo]
            df = fo.get("/DescendantFonts")
            if df is not None:
                candidatos.extend(list(df))
            for f in candidatos:
                d = f.get("/FontDescriptor")
                if d is not None:
                    vivos.add(d.objgen)
        except Exception:
            pass
    return vivos


def _usos_por_fonte(pdf):
    """[(objeto_fonte, set de codigos int, largura em bytes)] por uso real."""
    saida = []
    por_fonte = {}
    vistos_res = set()
    _refs = []

    def walk(dados, res, prof=0):
        if res is None or prof > 8:
            return
        _refs.append(res)
        try:
            chave = res.objgen if getattr(res, "is_indirect", False) else id(res)
        except Exception:
            chave = id(res)
        if chave in vistos_res:
            return
        vistos_res.add(chave)
        try:
            fontes = dict(res.get("/Font", {}))
        except Exception:
            fontes = {}
        largura = {}
        for nome, fo in fontes.items():
            try:
                largura[str(nome)] = 2 if str(fo.get("/Subtype")) == "/Type0" else 1
            except Exception:
                largura[str(nome)] = 1
        achados = defaultdict(list)
        cur = None
        pend = []  # (tipo, valor)
        for tipo, val in _tokens_conteudo(dados):
            if tipo in ("str", "hex", "name"):
                pend.append((tipo, val))
                continue
            if tipo in ("num", "arr", "dict"):
                continue
            if tipo == "op":
                if val == b"Tf":
                    cur = None
                    for tp, p in reversed(pend):
                        if tp == "name":
                            cur = p.decode("latin-1")
                            break
                    pend = []
                elif val in (b"Tj", b"TJ", b"'", b'"') and cur is not None:
                    for tp, p in pend:
                        if tp in ("str", "hex"):
                            achados[cur].append(p)
                    pend = []
                elif val == b"Do":
                    alvo = None
                    for tp, p in reversed(pend):
                        if tp == "name":
                            alvo = p
                            break
                    pend = []
                    if alvo is not None:
                        try:
                            xo = res.get("/XObject", {}).get(Name(alvo.decode("latin-1")))
                        except Exception:
                            xo = None
                        if xo is not None and str(xo.get("/Subtype")) == "/Form":
                            sub = _bytes_conteudo(xo)
                            if sub:
                                walk(sub, xo.get("/Resources", res), prof + 1)
                else:
                    pend = []
                continue
            pend = []
        for nome, blocos in achados.items():
            fo = fontes.get(Name(nome))
            if fo is None:
                continue
            try:
                og = fo.objgen
            except Exception:
                og = (0, 0)
            w = largura.get(nome, 1)
            codigos = set()
            for b in blocos:
                if w == 2:
                    for i in range(0, len(b) - 1, 2):
                        codigos.add((b[i] << 8) | b[i + 1])
                else:
                    codigos.update(b)
            if og == (0, 0):
                og = ("direto", id(fo))
            if og in por_fonte:
                por_fonte[og][1].update(codigos)   # soma, nao descarta
                continue
            por_fonte[og] = [fo, set(codigos), w]
            saida.append(por_fonte[og])

    for pagina in pdf.pages:
        try:
            res = pagina.Resources
            dados = _bytes_conteudo(pagina)
        except Exception:
            continue
        if dados:
            walk(dados, res)
    return saida


def _politica_subset(opts, retain=None):
    """Politica do subset de fontes.

    COMPRESSPDF_SUBSET=compacto (padrao): renumerа glifos e descarta hinting —
        menor arquivo, mesma renderizacao medida (MuPDF).
    COMPRESSPDF_SUBSET=motor: replica o conjunto de tabelas do 3-Heights
        (evidencia no x.pdf): mantem hinting (fpgm/prep/cvt), mantem os GIDs
        originais e NAO carrega GPOS/GSUB.

    `retain` sobrepoe o `retain_gids` do modo. Medido nas referencias reais de
    processo.pdf: fonte SIMPLES com 4 glifos no iLovePDF contra 3.874 nossos —
    ele renumera; CID mantem 221 nos dois. Por isso `_merge_subset_fontes`
    passa retain=False para grupos sem CID.
    """
    modo = os.environ.get("COMPRESSPDF_SUBSET", "motor").lower()
    if modo.startswith("mot"):
        opts.retain_gids = True
        opts.hinting = True
        opts.layout_features = []
        # o motor nao emite GPOS/GSUB/GDEF no subset (evidencia: as 6 fontes
        # do x_ilovepdf_* so tem glyf/fpgm/prep/cvt/hmtx/loca/name) e tambem
        # descarta as tabelas de metrica por tamanho/hinting de tela.
        opts.drop_tables = list(getattr(opts, "drop_tables", [])) + [
            "GPOS", "GSUB", "GDEF", "hdmx", "VDMX", "gasp", "kern", "LTSH",
            "PCLT", "DSIG", "meta"]
        # a tabela `name` do motor tem exatamente 7 registros: IDs 0-6,
        # plataforma Windows, idioma 0x409 (medido em processo.pdf: 378 B
        # contra 11.906 B nossos com todas as linguas).
        opts.name_IDs = [0, 1, 2, 3, 4, 5, 6]
        opts.name_languages = [0x409]
        opts.name_legacy = False
    elif modo.startswith("ilove"):
        opts.retain_gids = True
        opts.hinting = True
    else:
        opts.hinting = os.environ.get("COMPRESSPDF_HINT", "0") == "1"
    if retain is not None:
        opts.retain_gids = bool(retain)


def _normaliza_nome_programa(tt, basefont):
    """Reescreve os nomes internos (IDs 1/4/6) sem o tag de subset.

    Cada copia de fonte do arquivo de origem carrega um prefixo diferente
    (ABCDEE+, MZBNSZ+...). Sem normalizar, dois subsets IDENTICOS geram bytes
    diferentes e nunca sao fundidos por `_consolida_programas_fonte`.
    """
    nome = str(basefont).lstrip("/")
    if "+" in nome:
        nome = nome.split("+", 1)[1]
    try:
        nm = tt["name"]
        for r in list(nm.names):
            if r.nameID in (1, 4, 6):
                nm.setName(nome, r.nameID, r.platformID, r.platEncID, r.langID)
    except Exception:
        pass


def _tag_subset(pdf):
    """Prefixo de subset de 6 letras, estavel por documento.

    O motor usa 6 letras (ASJHEV+ArialMT). Aqui o valor e' DERIVADO do /ID do
    trailer em vez de sorteado: rodar duas vezes no mesmo PDF tem de produzir o
    mesmo arquivo (medicao, testes de regressao e diff entre versoes). Fontes
    de documentos diferentes recebem prefixos diferentes.
    """
    try:
        bruto = bytes(pdf.trailer.get("/ID")[0])
    except Exception:
        bruto = b"pdfagent"
    n = zlib.crc32(bruto) & 0x3FFFFFFF
    letras = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    out = []
    for _ in range(6):
        out.append(letras[n % 26])
        n //= 26
    return "".join(out)


def _subset_fontes_cff(pdf, log):
    """Encolhe fontes CFF/CIDFontType0C esvaziando os charstrings NAO usados.

    Por que assim: o subsetter do fontTools renumera os glifos e quebra o
    charset CID (medido: 8,5-9,4% de divergencia de render, mesmo com
    retain_gids). Esvaziar apenas o *programa* dos glifos nao usados preserva
    indices, charset e a numeracao de CID — nada muda para o leitor.
    Medido: fonte de 35.906 B -> 906 B mantendo 4 glifos.
    """
    try:
        from fontTools.ttLib import TTFont, newTable
    except ImportError:
        return
    usos = _usos_por_fonte(pdf)
    contagem = _conta_streams_fonte(pdf)
    n = 0
    vistos = set()
    for fo, codigos, _w in usos:
        try:
            if str(fo.get("/Subtype")) != "/Type0":
                continue
            try:
                og = fo.objgen
            except Exception:
                og = (0, 0)
            chave = og if og != (0, 0) else ("direto", id(fo))
            if chave in vistos:
                continue
            vistos.add(chave)
            if not codigos:
                continue
            d0 = fo.get("/DescendantFonts")
            if d0 is None:
                continue
            d0 = d0[0]
            if str(d0.get("/Subtype")) != "/CIDFontType0":
                continue
            fd = d0.get("/FontDescriptor")
            if fd is None:
                continue
            ff = fd.get("/FontFile3")
            if ff is None:
                continue
            _garante_stream_exclusivo(pdf, fd, "/FontFile3", contagem, log)
            ff = fd.get("/FontFile3")
            if str(ff.get("/Subtype")) not in ("/CIDFontType0C", "/Type1C"):
                continue
            raw = ff.read_bytes()
            tt = TTFont()
            tab = newTable("CFF ")
            tab.decompile(raw, tt)
            tt.tables["CFF "] = tab
            top = tt["CFF "].cff[0]
            nomes = list(top.CharStrings.charStrings.keys())
            # CIDs usados -> nomes de glifo (formato 'cidNNNNN')
            usados = {".notdef"}
            mapa = {}
            for nm in nomes:
                if nm.startswith("cid") and nm[3:].isdigit():
                    mapa[int(nm[3:])] = nm
            for cid in codigos:
                nm = mapa.get(cid)
                if nm:
                    usados.add(nm)
            if len(usados) >= len(nomes):
                continue
            # seguranca: se nao mapeamos nem metade dos CIDs usados, nao mexer
            if len(usados) - 1 < max(1, len(codigos) // 2):
                continue
            for nm in nomes:
                if nm not in usados:
                    try:
                        top.CharStrings[nm].program = []
                    except Exception:
                        pass
            import io
            buf = io.BytesIO()
            tt.tables["CFF "].compile(tt)
            buf.write(tt.tables["CFF "].compile(tt))
            novo = buf.getvalue()
            if len(novo) >= len(raw):
                continue
            ff.write(zlib.compress(novo, 9))
            ff[Name("/Filter")] = Name("/FlateDecode")
            for k in ("/Length1", "/Length2", "/Length3"):
                try:
                    del ff[Name(k)]
                except Exception:
                    pass
            n += 1
        except Exception as ex:
            log(f"    CFF {fo.get('/BaseFont')}: {ex}")
            continue
    if n:
        log(f"    fontes CFF encolhidas: {n}")


def _subset_fontes_cid(pdf, log):
    """Re-subseta fontes Type0/CIDFontType2 (Identity-H) mantendo CIDs.

    Mantem a numeracao de CID (logo /W e os codigos do conteudo seguem
    validos) e reconstroi o /CIDToGIDMap para os novos GIDs.
    """
    try:
        from fontTools import subset
        from fontTools.ttLib import TTFont
    except ImportError:
        return
    usos = _usos_por_fonte(pdf)
    contagem = _conta_streams_fonte(pdf)
    n = 0
    vistos = set()
    for fo, codigos, _w in usos:
        try:
            try:
                og = fo.objgen
            except Exception:
                og = (0, 0)
            chave = og if og != (0, 0) else ("direto", id(fo))
            if chave in vistos:
                continue
            vistos.add(chave)
            if str(fo.get("/Subtype")) != "/Type0":
                continue
            if str(fo.get("/Encoding")) != "/Identity-H":
                continue
            if not codigos:
                continue
            desc = fo.get("/DescendantFonts")
            if desc is None:
                continue
            d0 = desc[0]
            if str(d0.get("/Subtype")) != "/CIDFontType2":
                continue
            c2g = d0.get("/CIDToGIDMap")
            # /Identity (ou ausente) era pulado: CID == GID, entao da para
            # subsetar e reconstruir o mapa como stream depois. Era o caso das
            # fontes grandes do x.pdf (ArialMT 102 KB, Wingdings 15 KB).
            identidade = c2g is None or isinstance(c2g, Name)
            fd = d0.get("/FontDescriptor")
            if fd is None:
                continue
            ff = fd.get("/FontFile2")
            if ff is None:
                continue
            _garante_stream_exclusivo(pdf, fd, "/FontFile2", contagem, log)
            ff = fd.get("/FontFile2")
            mapa = None if identidade else c2g.read_bytes()
            raw = ff.read_bytes()
            tt = TTFont(io.BytesIO(raw))
            ordem = tt.getGlyphOrder()
            gids = set()
            for cid in codigos:
                if identidade:
                    g = cid
                elif 2 * cid + 1 < len(mapa):
                    g = (mapa[2 * cid] << 8) | mapa[2 * cid + 1]
                else:
                    continue
                if 0 < g < len(ordem):
                    gids.add(g)
            if not gids:
                continue
            nomes = [ordem[g] for g in sorted(gids)]
            opts = subset.Options()
            opts.layout_features = ["*"]
            _politica_subset(opts)
            ss = subset.Subsetter(opts)
            ss.populate(glyphs=nomes)
            ss.subset(tt)
            _normaliza_nome_programa(tt, fo.get("/BaseFont", ""))
            buf = io.BytesIO()
            tt.save(buf)
            novo = buf.getvalue()
            if len(novo) >= len(raw):
                continue
            nova_ordem = tt.getGlyphOrder()
            nome2gid = {nm: i for i, nm in enumerate(nova_ordem)}
            maxcid = max(codigos)
            novo_mapa = bytearray(2 * (maxcid + 1))
            for cid in range(maxcid + 1):
                if identidade:
                    g = cid
                elif mapa is not None and 2 * cid + 1 < len(mapa):
                    g = (mapa[2 * cid] << 8) | mapa[2 * cid + 1]
                else:
                    continue
                if g < len(ordem):
                    ng = nome2gid.get(ordem[g], 0)
                    novo_mapa[2 * cid] = (ng >> 8) & 0xFF
                    novo_mapa[2 * cid + 1] = ng & 0xFF
            ff.write(zlib.compress(novo, 9))
            ff[Name("/Filter")] = Name("/FlateDecode")
            ff[Name("/Length1")] = len(novo)
            dados_mapa = zlib.compress(bytes(novo_mapa), 9)
            if identidade and getattr(opts, "retain_gids", False):
                # GIDs preservados: /Identity continua valido e nao precisa
                # de stream (o motor tambem mantem Identity). Economiza objeto.
                pass
            elif identidade:
                # nao existia stream de mapa: cria um indireto com o novo
                novo_c2g = pdf.make_stream(dados_mapa)
                novo_c2g[Name("/Filter")] = Name("/FlateDecode")
                d0[Name("/CIDToGIDMap")] = novo_c2g
            else:
                c2g.write(dados_mapa)
                c2g[Name("/Filter")] = Name("/FlateDecode")
            # tag de subset de 6 letras, como o motor faz (ASJHEV+ArialMT)
            try:
                tag = _tag_subset(pdf)
                nome = str(fo.get("/BaseFont", "")).lstrip("/")
                if "+" in nome:
                    nome = nome.split("+", 1)[1]
                fo[Name("/BaseFont")] = Name("/%s+%s" % (tag, nome))
                d0[Name("/BaseFont")] = Name("/%s+%s" % (tag, nome))
            except Exception:
                pass
            n += 1
        except Exception as ex:
            log(f"    subset CID: {ex}")
            continue
    if n:
        log(f"    fontes CID re-subsetadas: {n}")


def _fontes_recursivas(pdf):
    """Todas as fontes alcancaveis: paginas + Form XObjects (recursivo).

    Retorna lista de (dict_fonte) sem duplicatas por objgen.
    """
    vistos_res = set()
    vistos_fonte = set()
    out = []
    _refs = []  # segura wrappers p/ id() nao ser reutilizado

    def walk_res(res, prof=0):
        if res is None or prof > 8:
            return
        _refs.append(res)
        try:
            chave = res.objgen if getattr(res, "is_indirect", False) else id(res)
        except Exception:
            chave = id(res)
        if chave in vistos_res:
            return
        vistos_res.add(chave)
        try:
            fontes = res.get("/Font", {})
        except Exception:
            fontes = {}
        for _n, fo in dict(fontes).items():
            try:
                og = fo.objgen
            except Exception:
                continue
            chave_f = og if og != (0, 0) else ("direto", id(fo))
            if chave_f in vistos_fonte:
                continue
            vistos_fonte.add(chave_f)
            out.append(fo)
        try:
            xobjs = res.get("/XObject", {})
        except Exception:
            xobjs = {}
        for _n, xo in dict(xobjs).items():
            try:
                if str(xo.get("/Subtype")) == "/Form":
                    walk_res(xo.get("/Resources"), prof + 1)
            except Exception:
                continue

    for pagina in pdf.pages:
        try:
            walk_res(pagina.Resources)
        except Exception:
            continue
    return out


def _substitui_fontes_padrao(pdf, log):
    """Remove fontes embutidas equivalentes a padrao-14 (RemoveStandardFonts=1).

    Replica o observado no iLovePDF (low/extreme): o dicionario da fonte vira
    {Type, Subtype=/Type1, Encoding, BaseFont=/Times-Roman}; /Widths,
    /FontDescriptor e /FirstChar sao descartados. As metricas das padrao-14 sao
    identicas as dos originais (Times<->TimesNewRoman, Helvetica<->Arial), entao
    o layout nao muda.
    """
    n = 0
    desanexados = []  # (descriptor, [streams]) que ficaram sem uso
    for fo in _fontes_recursivas(pdf):
            try:
                alvo = EQUIV_PADRAO.get(_nome_base(fo.get("/BaseFont", "")))
                if alvo is None:
                    continue
                # so fontes simples com encoding nomeado (sem Differences)
                try:
                    subtipo = str(fo.get("/Subtype"))
                except Exception:
                    subtipo = ""
                if subtipo not in ("/Type1", "/TrueType", "/MMType1"):
                    continue
                enc = fo.get("/Encoding")
                # Sem /Encoding a fonte padrao usa a encoding EMBUTIDA (o caso
                # do ZapfDingbats). Forcar /WinAnsiEncoding trocava o glifo e a
                # extracao: "G" virava "l" em 10-13 paginas de processo.pdf.
                enc_nome = None
                if isinstance(enc, Name):
                    enc_nome = str(enc)
                elif enc is not None:
                    try:
                        if "/Differences" in enc:
                            continue
                        base = enc.get("/BaseEncoding")
                        enc_nome = str(base) if base is not None else None
                    except Exception:
                        continue
                # troca o dicionario inteiro (como o original), mas preserva o
                # /ToUnicode: sem ele a extracao da pagina vira \x01\x02... (o
                # mapeamento codigo->texto vivia no CMap, nao na encoding).
                campos = {"Type": Name("/Font"), "Subtype": Name("/Type1"),
                          "BaseFont": Name(alvo)}
                if enc_nome:
                    campos["Encoding"] = Name(enc_nome)
                try:
                    tou = fo.get("/ToUnicode")
                    if tou is not None:
                        campos["ToUnicode"] = tou
                except Exception:
                    pass
                novo = pikepdf.Dictionary(**campos)
                desc = fo.get("/FontDescriptor")
                if desc is not None:
                    streams = []
                    for k in ("/FontFile", "/FontFile2", "/FontFile3"):
                        try:
                            st = desc.get(k)
                            if st is not None and isinstance(st, pikepdf.Stream):
                                streams.append(st)
                        except Exception:
                            pass
                    if streams:
                        desanexados.append((desc, streams))
                for k in list(fo.keys()):
                    try:
                        del fo[k]
                    except Exception:
                        pass
                for k, v in novo.items():
                    fo[k] = v
                n += 1
            except Exception as ex:
                log(f"    fonte padrao: {ex}")
                continue
    # Zera somente os programas de fonte que ficaram SEM uso (o qpdf grava
    # objetos inalcancaveis mesmo assim). Descritores ainda usados por outra
    # fonte viva sao preservados.
    vivos = _streams_fonte_vivos(pdf)
    zerados = 0
    for desc, streams in desanexados:
        for st in streams:
            try:
                if st.objgen in vivos:
                    continue
            except Exception:
                pass
            try:
                st.write(b"")
                for kk in ("/Filter", "/DecodeParms", "/Length1", "/Length2", "/Length3"):
                    try:
                        del st[kk]
                    except Exception:
                        pass
                zerados += 1
            except Exception:
                pass
    if n:
        log(f"    fontes trocadas por padrao-14: {n} (programas zerados: {zerados})")


def _mul(m1, m2):
    a, b, c, d, e, f = m1
    g, h, i, j, k, l = m2
    return (a*g+b*i, a*h+b*j, c*g+d*i, c*h+d*j, e*g+f*i+k, e*h+f*j+l)


def _tamanhos_na_pagina(pdf):
    """Mapeia objgen da imagem -> lista de (larg_pt, alt_pt) desenhados.

    Percorre os content streams rastreando a CTM (cm/q/Q/Do), inclusive
    dentro de Form XObjects. Equivale a base para o calculo de DPI efetivo
    usado pelo otimizador (re-amostra imagens acima do limiar).
    """
    usos = defaultdict(list)

    def recursos_de(obj):
        try:
            r = obj.get("/Resources")
        except Exception:
            return None
        return r

    def caminha(ops, res, ctm, prof):
        pilha = []
        cur = res if res is not None else {}
        for operandos, operador in ops:
            op = str(operador)
            if op == "q":
                pilha.append((list(ctm), cur))
            elif op == "Q":
                if pilha:
                    ctm, cur = pilha.pop()
            elif op == "cm":
                ctm = _mul(ctm, [float(x) for x in operandos])
            elif op == "Do":
                nome = Name(str(operandos[0]))
                try:
                    xo = cur.get(Name("/XObject"), {}).get(nome)
                except Exception:
                    xo = None
                if xo is None:
                    continue
                try:
                    subtipo = str(xo.get("/Subtype"))
                except Exception:
                    continue
                if subtipo == "/Image":
                    try:
                        og = xo.objgen
                    except Exception:
                        continue
                    sx = math.hypot(ctm[0], ctm[1])
                    sy = math.hypot(ctm[2], ctm[3])
                    if sx > 0 and sy > 0 and prof < 8:
                        usos[og].append((sx, sy))
                elif subtipo == "/Form" and prof < 8:
                    try:
                        m = [float(x) for x in xo.get("/Matrix", [1, 0, 0, 1, 0, 0])]
                    except Exception:
                        m = [1, 0, 0, 1, 0, 0]
                    sub_res = recursos_de(xo) or cur
                    try:
                        sub_ops = pikepdf.parse_content_stream(xo, "q Q cm Do")
                    except Exception:
                        continue
                    caminha(sub_ops, sub_res, _mul(ctm, m), prof + 1)

    for pagina in pdf.pages:
        try:
            ops = pikepdf.parse_content_stream(pagina, "q Q cm Do")
        except Exception:
            continue
        try:
            res = pagina.Resources
        except Exception:
            res = {}
        caminha(ops, res, (1, 0, 0, 1, 0, 0), 0)
    return usos


def _dpi_efetivo(w_px, h_px, usos):
    """Maior DPI efetivo entre as ocorrencias; (None se imagem nao desenhada)."""
    if not usos:
        return None, None
    melhor = 0
    melhor_tam = None
    for sx, sy in usos:
        dx = w_px / (sx / 72.0)
        dy = h_px / (sy / 72.0)
        m = max(dx, dy)
        if m > melhor:
            melhor = m
            melhor_tam = (sx, sy)
    return melhor, melhor_tam


def _pil_da_imagem(obj):
    return pikepdf.PdfImage(obj).as_pil_image()


def _jpeg_bytes(img, qualidade):
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=qualidade, optimize=True)
    return buf.getvalue()


def _flate_bytes(img):
    """Raw comprimido (zlib) + parametros p/ /FlateDecode (sem preditor)."""
    raw = img.tobytes()
    return zlib.compress(raw, 9)


def _png_idat(img):
    """IDAT de um PNG (com predicao) p/ /FlateDecode com /Predictor 12."""
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    png = buf.getvalue()
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    idat = b""
    pos = 8
    while pos < len(png):
        (comp,) = struct.unpack(">I", png[pos:pos+4])
        tipo = png[pos+4:pos+8]
        dados = png[pos+8:pos+8+comp]
        if tipo == b"IDAT":
            idat += dados
        pos += 12 + comp
    return idat


def _jbig2_bytes(img1, tmpdir=None):
    """Codifica imagem '1' em JBIG2 usando o jbig2enc, se estiver instalado.

    Retorna (globals, pagina) ou None. O binario nao vem no projeto: sem ele
    seguimos com Group 4 (sem perda). Instalacao: `jbig2enc` no PATH.
    """
    import shutil
    import subprocess
    import tempfile
    exe = shutil.which("jbig2") or shutil.which("jbig2enc")
    if not exe:
        return None
    try:
        d = tempfile.mkdtemp(prefix="cpdf_jbig2_")
        entrada = os.path.join(d, "in.png")
        img1.save(entrada)
        saida = os.path.join(d, "out")
        # -s: symbols file (.sym, usado como /JBIG2Globals) | -p: PDF mode
        subprocess.run([exe, "-s", "-p", "-b", saida, entrada],
                       check=True, capture_output=True, timeout=120)
        glob = saida + ".sym"
        pag = saida + ".0000"
        if not (os.path.exists(glob) and os.path.exists(pag)):
            return None
        with open(glob, "rb") as f:
            g = f.read()
        with open(pag, "rb") as f:
            p = f.read()
        for arq in (glob, pag, entrada):
            try:
                os.remove(arq)
            except Exception:
                pass
        try:
            os.rmdir(d)
        except Exception:
            pass
        if not p:
            return None
        return (g or None), p
    except Exception:
        return None


def _g4_bytes(img1):
    """Codifica imagem modo '1' em CCITT Group 4 via TIFF do Pillow."""
    buf = io.BytesIO()
    img1.save(buf, format="TIFF", compression="group4")
    t = buf.getvalue()
    if t[:2] == b"II":
        endian, u16, u32 = "<", "<H", "<I"
    else:
        endian, u16, u32 = ">", ">H", ">I"
    ifd = struct.unpack(endian + "I", t[4:8])[0]
    n = struct.unpack(endian + "H", t[ifd:ifd+2])[0]
    entradas = {}
    for i in range(n):
        e = t[ifd+2+i*12: ifd+2+(i+1)*12]
        tag, tip, cnt, val = struct.unpack(endian + "HHI4s", e)
        entradas[tag] = (tip, cnt, val)

    def campo(tag):
        tip, cnt, val = entradas[tag]
        if tip == 3 and cnt == 1:
            return struct.unpack(endian + "H", val[:2])[0]
        if tip == 4 and cnt == 1:
            return struct.unpack(endian + "I", val)[0]
        if tip == 4:
            off = struct.unpack(endian + "I", val)[0]
            return struct.unpack(endian + "%dI" % cnt, t[off:off+4*cnt])
        raise ValueError(("tiff", tag, tip, cnt))

    w, h = campo(256), campo(257)
    assert campo(259) == 4, "sem compressao group4"
    offs = campo(273)
    tamanhos = campo(279)
    if isinstance(offs, int):
        offs, tamanhos = (offs,), (tamanhos,)
    return b"".join(t[o:o+c] for o, c in zip(offs, tamanhos)), w, h


def _e_cinza(img):
    """Decide se a imagem e' realmente sem cor (ReduceColorComplexity).

    Amostragem NEAREST (nao media) e limite estrito: a versao anterior usava
    downsample BICUBIC 32x32 e a media mascarava cor — imagens com listras
    coloridas finas (sat 184) eram classificadas como cinza e perdiam a cor
    (PSNR 20,9 dB contra o original; o motor as mantem em RGB).
    """
    try:
        from PIL import ImageChops
        im = img.convert("RGB")
        if im.size[0] * im.size[1] > 65536:
            lado = 256
            im = im.resize((min(lado, im.size[0]), min(lado, im.size[1])),
                           Image.NEAREST)
        r, g, b = im.split()
        d1 = ImageChops.difference(r, g).getextrema()[1]
        d2 = ImageChops.difference(g, b).getextrema()[1]
        d3 = ImageChops.difference(r, b).getextrema()[1]
        return max(d1, d2, d3) <= 8
    except Exception:
        return False


def _flate_menor(img):
    """Menor representacao Flate: PNG+predictor12 vs zlib cru.

    Para imagens pequenas o predictor acrescenta 1 byte por linha e pode
    piorar; o motor original grava SMask sem predictor (819 B vs 2.088 B).
    Retorna (dados, usar_predictor).
    """
    try:
        com_pred = _png_idat(img)
    except Exception:
        com_pred = None
    try:
        sem_pred = zlib.compress(img.tobytes(), 9)
    except Exception:
        sem_pred = None
    opcoes = [(d, True) for d in [com_pred] if d] + [(d, False) for d in [sem_pred] if d]
    if not opcoes:
        return b"", True
    return min(opcoes, key=lambda x: len(x[0]))


def _kernel_para(img):
    """Escolhe o filtro de reamostragem pelo conteudo.

    Imagens de traco/bitonais (poucos niveis distintos) sofrem ringing com
    LANCZOS: o PNG/Flate resultante fica 8-10x maior (medido: 8593 B vs 913 B).
    Fotos continuam com LANCZOS (melhor detalhe).

    KERNEL_FOTOS permite trocar por "bilinear": medição mostra que o motor
    original usa um filtro triangular (BILINEAR venceu nos 3 casos onde a saida
    deles e' sem perda). Bilinear gera arquivos 0,2-5,6% menores, com leve
    perda de nitidez; o padrao mantem LANCZOS (mais nitido, ja menor que o
    original).
    """
    try:
        amostra = img.convert("L").resize((64, 64), Image.NEAREST)
        niveis = len(set(amostra.tobytes()))
    except Exception:
        return _kernel_foto()
    if niveis <= 8:
        return Image.NEAREST
    if niveis <= 48:
        return Image.BOX
    return _kernel_foto()


def _kernel_foto():
    """Filtro das fotos. Padrao BILINEAR = o do motor (3-Heights usa filtro
    triangular; ver docs/METODO.md §4b). LANCZOS era escolha nossa: mais
    nitido, mas o ringing encarece o caminho sem perda (AP5439 pg1: 2.574 B
    contra 775 B do iLovePDF). COMPRESSPDF_KERNEL=lanczos volta o antigo.
    """
    if os.environ.get("COMPRESSPDF_KERNEL", "").lower().startswith("lanc"):
        return Image.LANCZOS
    return Image.BILINEAR


def _recomprime_imagem(pdf, obj, spec, usos, log):
    """Aplica downsampling + tenta as compressoes da mascara.

    Regra do original (ForceRecompression=False): so troca se ficar menor.
    Retorna (trocou, filtro_final, dpi_final).
    """
    try:
        if obj.get("/ImageMask") is True:
            return False, "mask", None
        if obj.get("/SMask") is not None and int(obj.get("/BitsPerComponent", 8)) == 1:
            return False, "smask", None
    except Exception:
        return False, "?", None
    try:
        w = int(obj["/Width"])
        h = int(obj["/Height"])
        bpc = int(obj.get("/BitsPerComponent", 8))
    except Exception:
        return False, "?", None
    try:
        cs = obj.get("/ColorSpace")
        cs_nome = str(cs[0]) if isinstance(cs, pikepdf.Array) else str(cs)
    except Exception:
        cs_nome = ""
    indexada = cs_nome == "/Indexed"
    bitonal = (bpc == 1 and not indexada)

    try:
        img = _pil_da_imagem(obj)
    except Exception as ex:
        log(f"    imagem {w}x{h}: decode falhou ({ex}); mantida")
        return False, "decode-falha", None

    # --- conversao de cor (Extreme: tudo vira RGB) ---
    if spec["conversao_cor"] == "rgb" and img.mode == "CMYK":
        img = img.convert("RGB")
    # A reducao de complexidade de cor roda DEPOIS da reamostragem: o motor
    # decide sobre a imagem ja reduzida (REA/Ghidra, FUN_1800a6720). Testar
    # antes fazia divergir nos dois sentidos (EM3120 pg3 e DO3877 pg19).

    # --- downsampling (desligado p/ indexadas, como no original) ---
    tem_smask = obj.get("/SMask") is not None
    alvo_w, alvo_h = w, h
    dpi_final = None
    if not indexada:
        dpi, tam = _dpi_efetivo(w, h, usos.get(obj.objgen, []))
        if dpi is not None:
            dpi_final = dpi
            drawn_w, drawn_h = tam if tam else (0.0, 0.0)
            # Imagem degenerada (lado desenhado < 1 pt): nos perfis de limiar
            # baixo (recommended/extreme) o motor grava 1x1 cru; no low (400)
            # ele mantem o original. Caso real: x.pdf /Image6 1x656 desenhada
            # em 0,12x276,6 pt.
            if (min(drawn_w, drawn_h) < 1.0 and spec["limiar"] <= 150.0
                    and (w, h) != (1, 1)):
                try:
                    obj.write(b"\x00")
                    for k in ("/Filter", "/DecodeParms", "/SMask", "/Mask"):
                        try:
                            del obj[k]
                        except Exception:
                            pass
                    obj[Name("/Width")] = 1
                    obj[Name("/Height")] = 1
                    obj[Name("/ColorSpace")] = Name("/DeviceGray")
                    obj[Name("/BitsPerComponent")] = 8
                    return True, "1x1", dpi
                except Exception as ex:
                    log(f"    1x1 falhou: {ex}")
            # Corte empirico ajustado nas amostras reais: o motor nao
            # reamostra imagem desenhada com menos de 60 pt no lado menor
            # QUANDO o dpi efetivo e' moderado (<150). NS8002 pg6: 150x55
            # (116 dpi) e 152x21 (123 dpi) ficaram intactas; o x.pdf tem
            # 48x45 pt mas a 199 dpi e E' reduzido para 48x45.
            pequena = min(drawn_w, drawn_h) < 60.0 and dpi < 150.0
            if dpi > spec["limiar"] and not pequena:
                # O motor guarda o dpi efetivo em float32 e calcula o alvo
                # como px*res/dpi (fórmula de FUN_1800a6720). Reproduzir o
                # float32 acerta os ±1 px que sobravam (GM9477 pg1: 241x160).
                def _alvo(px, pt):
                    if not pt:
                        return px
                    d = struct.unpack("<f", struct.pack("<f", px * 72.0 / pt))[0]
                    if not d:
                        return px
                    v = px * spec["resolucao"] / d
                    # imagem recortada pelo nosso ClipImages: o motor nao
                    # perde a ultima linha, entao arredonda para cima
                    # (NS8002 /Im40: 314.14 -> 315, como na referencia).
                    if getattr(obj, "objgen", None) in _CLIPADOS:
                        return max(1, int(math.ceil(v - 1e-9)))
                    return max(1, int(v + 0.5))
                alvo_w = min(_alvo(w, drawn_w), w)
                alvo_h = min(_alvo(h, drawn_h), h)
                # (tentamos derivar a altura da largura, preservando a
                #  proporcao: acertava o NS8002 mas quebrava DO3877 e tres
                #  imagens do NS8002 recommended — o motor usa o pt de cada
                #  eixo, como o decompilado indica. Ver METODO.md §4b.)
                if os.environ.get("COMPRESSPDF_DEBUG"):
                    log("    obj %s tipo=%s objwh=%sx%s usos=%s tam=%s -> %dx%d"
                        % (getattr(obj, "objgen", "?"), type(obj).__name__,
                           obj.get("/Width"), obj.get("/Height"),
                           usos.get(getattr(obj, "objgen", None), "SEM-CHAVE"),
                           tam, alvo_w, alvo_h))
    if (alvo_w, alvo_h) != (w, h):
        if bitonal:
            # 1-bit: NEAREST preserva bordas duras (LANCZOS gera franja
            # cinza que vira speckle no G4 — 12x maior)
            img = img.convert("1").resize((alvo_w, alvo_h), Image.NEAREST)
        else:
            if img.mode not in ("RGB", "L", "CMYK"):
                img = img.convert("RGB")
            k = _kernel_para(img)
            img = img.resize((alvo_w, alvo_h), k)
            # O motor original reamostra com filtro triangular (bilinear);
            # LANCZOS/NEAREST sao escolhas nossas por conteudo. Como o kernel
            # muda o custo dos DOIS caminhos (JPEG e Flate), a variante e
            # escolhida pelo menor stream final — nao so pelo JPEG.
            # (AP5439 pg1: NEAREST 754 B x BILINEAR 2.574 B no Flate;
            #  EM3120 pg3: BILINEAR suaviza o ruido e o JPEG fica menor.)
            if not _sem_risco_kernel:
                try:
                    base = _pil_da_imagem(obj)
                    if base.mode not in ("RGB", "L", "CMYK"):
                        base = base.convert("RGB")
                    alt = base.resize((alvo_w, alvo_h), Image.BILINEAR)
                    if alt.mode == img.mode:

                        def _custo_variante(im):
                            # so conta o que o PERFIL permite: em extreme/low
                            # o mascara e' apenas ["jpeg"]; incluir Flate aqui
                            # fazia o NEAREST ganhar e o JPEG final ficar
                            # grande (EM3120 pg3 mantinha o original).
                            permitidos = (spec["bitonal"] if bitonal else
                                          (spec["indexado"] if indexada
                                           else spec["continuo"]))
                            custos = []
                            if "jpeg" in permitidos and not bitonal:
                                custos.append(len(_jpeg_bytes(
                                    im, spec["qualidade"])))
                            if "flate" in permitidos:
                                custos.append(len(_flate_bytes(im)))
                            return min(custos) if custos else len(_flate_bytes(im))
                        if _custo_variante(alt) < _custo_variante(img):
                            img = alt
                except Exception:
                    pass
        # SMask acompanha o resize (preserva transparencia, como o original).
        # So achata no branco se a mascara nao puder ser reamostrada.
        if tem_smask and not bitonal:
            ok_mask = False
            try:
                m_obj = obj["/SMask"]
                m_img = pikepdf.PdfImage(m_obj).as_pil_image().convert("L")
                # mascara: media de area (BOX) — LANCZOS cria ringing no alfa
                # e infla o Flate (2.037 B vs 725 B medido)
                m_img = m_img.resize((alvo_w, alvo_h), Image.BOX)
                dados_m, usar_pred = _flate_menor(m_img)
                m_obj.write(dados_m)
                if usar_pred:
                    m_obj[Name("/Filter")] = Name("/FlateDecode")
                    m_obj[Name("/DecodeParms")] = pikepdf.Dictionary(
                        Predictor=12, Colors=1, BitsPerComponent=8, Columns=m_img.size[0])
                else:
                    m_obj[Name("/Filter")] = Name("/FlateDecode")
                    try:
                        del m_obj[Name("/DecodeParms")]
                    except Exception:
                        pass
                m_obj[Name("/Width")] = m_img.size[0]
                m_obj[Name("/Height")] = m_img.size[1]
                m_obj[Name("/ColorSpace")] = Name("/DeviceGray")
                m_obj[Name("/BitsPerComponent")] = 8
                ok_mask = True
            except Exception as ex:
                log(f"    smask nao reamostrada: {ex}")
            if not ok_mask:
                fundo = Image.new(img.mode, img.size, (255,) * len(img.getbands()))
                try:
                    fundo.paste(img, _pil_da_imagem(obj["/SMask"]).convert("L").resize(img.size, Image.LANCZOS))
                    img = fundo
                except Exception:
                    pass
                try:
                    del obj["/SMask"]
                except Exception:
                    pass
        reamostrada = True
    else:
        reamostrada = False

    # --- reduz complexidade de cor (Extreme) ---
    # Vale SEMPRE que a imagem vai ser re-codificada: o motor converte as
    # 456x260/461x292/474x270 do DO3877 (nao reamostradas) e so nao converte
    # a /Im150 porque nela o JPEG nao ficou menor e ele manteve o original.
    if (spec.get("reduz_cor") and img.mode == "RGB" and _e_cinza(img)):
        img = img.convert("L")

    try:
        orig_len = len(obj.read_raw_bytes())
    except Exception:
        orig_len = None

    mascara = spec["bitonal"] if bitonal else (spec["indexado"] if indexada else spec["continuo"])
    candidatos = []  # (nbytes, aplica_fn, rotulo)

    def tenta_jpeg():
        im = img
        if im.mode == "CMYK":
            cs_out, extra = "/DeviceCMYK", {"Decode": [1, 0, 1, 0, 1, 0, 1, 0]}
        elif im.mode == "L":
            cs_out, extra = "/DeviceGray", {}
        else:
            im = im.convert("RGB") if im.mode != "RGB" else im
            cs_out, extra = "/DeviceRGB", {}
        # Original: Filter=[/FlateDecode /DCTDecode], DecodeParms=[None {Quality}]
        # (camada Flate externa sobre o JPEG — evidenciado em saidas reais).
        jpeg = _jpeg_bytes(im, spec["qualidade"])
        dados = zlib.compress(jpeg, 9)

        def aplica(o, dados=dados, im=im, cs_out=cs_out, extra=extra):
            o.write(dados)
            o[Name("/Filter")] = pikepdf.Array(
                [Name("/FlateDecode"), Name("/DCTDecode")])
            o[Name("/DecodeParms")] = pikepdf.Array(
                [None, pikepdf.Dictionary(Quality=spec["qualidade"])])
            o[Name("/Width")] = im.size[0]
            o[Name("/Height")] = im.size[1]
            o[Name("/ColorSpace")] = Name(cs_out)
            o[Name("/BitsPerComponent")] = 8
            for k in ("/Intent",):
                try:
                    del o[k]
                except Exception:
                    pass
            if extra:
                o[Name("/Decode")] = extra["Decode"]
            elif "/Decode" in o:
                try:
                    del o["/Decode"]
                except Exception:
                    pass
        return len(dados), aplica, f"jpeg q{spec['qualidade']}"

    def tenta_flate():
        im = img
        if im.mode == "CMYK":
            im = im.convert("RGB")
        if im.mode == "P":
            im = im.convert("RGB")
        if im.mode == "1":
            cs_out, bpc = "/DeviceGray", 1
        elif im.mode == "L":
            cs_out, bpc = "/DeviceGray", 8
        else:
            im = im.convert("RGB") if im.mode != "RGB" else im
            cs_out, bpc = "/DeviceRGB", 8
        # menor entre PNG+predictor e zlib cru (o preditor pode piorar)
        dados, usar_pred = _flate_menor(im)
        cores = 1 if cs_out == "/DeviceGray" else 3

        def aplica(o, dados=dados, im=im, cs_out=cs_out, bpc=bpc,
                   cores=cores, usar_pred=usar_pred):
            o.write(dados)
            o[Name("/Filter")] = Name("/FlateDecode")
            if usar_pred:
                o[Name("/DecodeParms")] = pikepdf.Dictionary(
                    Predictor=12, Colors=cores, BitsPerComponent=bpc,
                    Columns=im.size[0])
            else:
                try:
                    del o[Name("/DecodeParms")]
                except Exception:
                    pass
            o[Name("/Width")] = im.size[0]
            o[Name("/Height")] = im.size[1]
            o[Name("/ColorSpace")] = Name(cs_out)
            o[Name("/BitsPerComponent")] = bpc
        return len(dados), aplica, "flate"

    def tenta_g4():
        im = img.convert("L").convert("1") if img.mode != "1" else img
        dados, gw, gh = _g4_bytes(im)

        def aplica(o, dados=dados, gw=gw, gh=gh):
            o.write(dados)
            o[Name("/Filter")] = Name("/CCITTFaxDecode")
            o[Name("/DecodeParms")] = pikepdf.Dictionary(K=-1, Columns=gw,
                                                         Rows=gh, BlackIs1=True)
            o[Name("/Width")] = gw
            o[Name("/Height")] = gh
            o[Name("/ColorSpace")] = Name("/DeviceGray")
            o[Name("/BitsPerComponent")] = 1
            for k in ("/SMask", "/Intent", "/Decode"):
                try:
                    del o[k]
                except Exception:
                    pass
        return len(dados), aplica, "group4"

    def tenta_jbig2():
        enc = _jbig2_bytes(img.convert("L").convert("1") if img.mode != "1" else img)
        if not enc:
            return None
        g, dados = enc

        def aplica(o, dados=dados, g=g):
            o.write(dados)
            o[Name("/Filter")] = Name("/JBIG2Decode")
            if g:
                o[Name("/DecodeParms")] = pikepdf.Dictionary(
                    JBIG2Globals=pdf.make_stream(g))
            o[Name("/Width")] = img.size[0]
            o[Name("/Height")] = img.size[1]
            o[Name("/ColorSpace")] = Name("/DeviceGray")
            o[Name("/BitsPerComponent")] = 1
            for k in ("/SMask", "/Intent", "/Decode"):
                try:
                    del o[k]
                except Exception:
                    pass
        return len(dados), aplica, "jbig2"

    for tipo in mascara:
        try:
            if tipo == "jpeg" and not bitonal:
                candidatos.append(tenta_jpeg())
            elif tipo == "flate":
                candidatos.append(tenta_flate())
            elif tipo == "g4" and bitonal:
                candidatos.append(tenta_g4())
                try:
                    jb = tenta_jbig2()
                    if jb:
                        candidatos.append(jb)
                except Exception as ex:
                    log(f"    jbig2 falhou: {ex}")
            elif tipo == "source":
                pass  # = manter bytes originais (candidato implicito)
        except Exception as ex:
            log(f"    candidato {tipo} falhou: {ex}")

    # (o antigo "Flate de resgate" foi removido: ele disparava justamente nos
    #  perfis que NAO listam flate — extreme e low usam so JPEG — e produzia
    #  Flate onde o motor devolve o original. Era a causa do DeviceGray Flate
    #  do DO3877 /Im150 em extreme.)

    # "source" so vale se nao reamostrou
    if not reamostrada and "source" in mascara and orig_len is not None:
        candidatos.append((orig_len, lambda o: None, "original"))
    if not candidatos:
        return False, "sem-candidatos", dpi_final
    candidatos.sort(key=lambda c: c[0])
    melhor_len, melhor_fn, rotulo = candidatos[0]
    if orig_len is not None and melhor_len >= orig_len:
        return False, f"mantida ({rotulo} maior)", dpi_final
    melhor_fn(obj)
    return True, rotulo, dpi_final


def _recomprime_mascaras(pdf, spec, usos, log):
    """Reamostra o /SMask 1-bit para o tamanho da imagem-mae e recodifica em G4.

    O motor trata a mascara como parte da imagem: se a mae cai para 928 px de
    largura, a mascara tambem. Medido em processo.pdf (extreme): 58 mascaras
    somando 24 KB do iLovePDF contra 108 KB nossos — cada uma ~4x maior porque
    a mascara nao e' desenhada por `Do`, nunca aparece em `_tamanhos_na_pagina`
    e ficava intocada.

    Nao mexe em /ImageMask (stencil) nem em mascara com /DecodeParms (preditor).
    """
    n = 0
    vistos = set()
    for obj in pdf.objects:
        try:
            if not isinstance(obj, pikepdf.Stream):
                continue
            if str(obj.get("/Subtype", "")) != "/Image":
                continue
            m = obj.get("/SMask")
            if m is None or not isinstance(m, pikepdf.Stream):
                continue
            if m.objgen in vistos:
                continue
            vistos.add(m.objgen)
            if int(m.get("/BitsPerComponent", 8)) != 1:
                continue
            if int(m.get("/ImageMask", 0)) == 1:
                continue
            if m.get("/DecodeParms") is not None:
                continue
        except Exception:
            continue
        try:
            alvo_w = int(obj["/Width"])
            alvo_h = int(obj["/Height"])
            if alvo_w < 8 or alvo_h < 8:
                continue
            img = _pil_da_imagem(m).convert("L").convert("1")
            if img.size == (alvo_w, alvo_h):
                continue
            novo_img = img.resize((alvo_w, alvo_h), Image.BOX)
            dados, gw, gh = _g4_bytes(novo_img)
            if len(dados) >= len(m.read_raw_bytes()):
                continue
            m.write(dados)
            m[Name("/Filter")] = Name("/CCITTFaxDecode")
            m[Name("/DecodeParms")] = pikepdf.Dictionary(
                K=-1, Columns=gw, Rows=gh, BlackIs1=True)
            m[Name("/Width")] = gw
            m[Name("/Height")] = gh
            m[Name("/ColorSpace")] = Name("/DeviceGray")
            m[Name("/BitsPerComponent")] = 1
            for k in ("/Decode", "/Intent"):
                try:
                    del m[k]
                except Exception:
                    pass
            n += 1
        except Exception as ex:
            log("    mascara %s: %s" % (obj.objgen, ex))
            continue
    if n:
        log("    mascaras 1-bit reamostradas: %d" % n)
    return n


def _remove_assinaturas(pdf, log):
    """Descarta campos de assinatura digital (o motor nao os preserva).

    Medido em processo.pdf contra a saida recommended do iLovePDF: saem os 214
    widgets /FT /Sig (com o carimbo /AP desenhado na pagina) e os 214
    dicionarios /Type /Sig; os 13 links ficam. Assinatura nao sobrevive a
    reescrita do arquivo, e o motor remove o campo em vez de deixa-lo invalido.
    """
    tirados = 0
    for pagina in pdf.pages:
        try:
            anots = pagina.obj.get("/Annots")
        except Exception:
            continue
        if anots is None or _tipo_obj(anots) != "array":
            continue
        try:
            n = len(anots)
        except Exception:
            continue
        manter = []
        for i in range(n):
            try:
                an = anots[i]
            except Exception:
                continue
            try:
                if str(an.get("/FT", "")) == "/Sig":
                    tirados += 1
                    continue
            except Exception:
                pass
            manter.append(an)
        if len(manter) != n:
            try:
                if manter:
                    pagina.obj["/Annots"] = pikepdf.Array(manter)
                else:
                    del pagina.obj["/Annots"]
            except Exception:
                pass
    # /AcroForm /Fields: fora do corpus do gate (nenhum original tem form),
    # mas o mesmo campo de assinatura pode viver so aqui.
    try:
        acro = pdf.Root.get("/AcroForm")
    except Exception:
        acro = None
    if acro is not None and _eh_dict(acro):
        try:
            campos = acro.get("/Fields")
        except Exception:
            campos = None
        if campos is not None and _tipo_obj(campos) == "array":
            manter = []
            try:
                n = len(campos)
            except Exception:
                n = 0
            for i in range(n):
                try:
                    c = campos[i]
                except Exception:
                    continue
                try:
                    if str(c.get("/FT", "")) == "/Sig":
                        tirados += 1
                        continue
                except Exception:
                    pass
                manter.append(c)
            if len(manter) != n:
                try:
                    if manter:
                        acro["/Fields"] = pikepdf.Array(manter)
                    else:
                        del pdf.Root["/AcroForm"]
                except Exception:
                    pass
    if tirados:
        log("    assinaturas: %d campo(s)/widget(s) removido(s)" % tirados)
    return tirados


def _aplica_strip(pdf, strip, log):
    # O motor descarta campos de assinatura em TODOS os niveis: medido nas tres
    # saidas de processo.pdf (recommended, extreme e low: 0 `/Type /Sig` e 0
    # widget `/FT /Sig`, com os 13 links preservados). Nao depende do Strip —
    # no low sobram 214 widgets + 214 /Sig (~1,4 MB) se pularmos.
    _remove_assinaturas(pdf, log)
    if not strip:
        return
    if "metadata" in strip:
        # O motor NAO apaga docinfo em nenhum nivel: nas 21 saidas reais o
        # docinfo mantem Author/Creator/Title (so datas e Producer mudam).
        # O "Metadata" do Strip e o fluxo XMP do catalogo — so ele sai.
        try:
            del pdf.Root["/Metadata"]
        except Exception:
            pass
        log("    strip: XMP removido (docinfo preservado)")
    for pagina in pdf.pages:
        for chave in (("threads", "/Threads"), ("thumbs", "/Thumb"),
                      ("alternates", "/Alternates"), ("pieceinfo", "/PieceInfo")):
            if chave[0] in strip:
                try:
                    del pagina[chave[1]]
                except Exception:
                    pass
    root = pdf.Root
    if "pieceinfo" in strip:
        try:
            del root["/PieceInfo"]
        except Exception:
            pass
    if "structtree" in strip:
        try:
            del root["/StructTreeRoot"]
        except Exception:
            pass
        try:
            # o motor REMOVE /MarkInfo junto com o StructTree: as saidas dele
            # nao tem a chave (antigo Marked=false deixava sobra e divergia
            # nas 7 combinacoes de extreme)
            del root["/MarkInfo"]
        except Exception:
            pass
    if "spider" in strip:
        try:
            del root["/SpiderInfo"]
        except Exception:
            pass
    # (bloco "invisiveis" removido: ver REA em docs/METODO.md §4b — o bit 10
    #  do Strip(1143) nao atua sobre conteudo; nenhuma amostra do corpus tem
    #  anotacao invisivel, entao o comportamento nunca foi validado)


def _xmp_tem_conteudo(xmp_bytes):
    """True se o XMP carrega titulo/autor/assunto/palavras nao vazios."""
    import re
    try:
        txt = xmp_bytes.decode("utf-8", "replace")
    except Exception:
        return False
    for campo in ("dc:title", "dc:creator", "dc:subject", "dc:description",
                  "pdf:Keywords"):
        m = re.search(rf"<{campo}[^>]*>(.*?)</{campo}>", txt, re.S)
        if not m:
            continue
        # remove tags internas e espacos
        interno = re.sub(r"<[^>]+>", " ", m.group(1))
        if interno.strip():
            return True
    return False


def _atualiza_datas_xmp(xmp_bytes):
    """Mantem o XMP original e atualiza apenas as datas, como o motor faz.

    Medido: o iLovePDF preserva o XMP byte a byte e so troca CreateDate,
    ModifyDate e MetadataDate (o resto — dc:creator, dc:title, dc:subject,
    pdf:PDFVersion, assinatura da ferramenta — fica intacto).
    """
    import datetime
    import re
    try:
        txt = xmp_bytes.decode("utf-8", "replace")
    except Exception:
        return None
    agora = datetime.datetime.now(datetime.timezone.utc)
    iso_z = agora.strftime("%Y-%m-%dT%H:%M:%SZ")
    local = datetime.datetime.now().astimezone()
    iso_tz = local.strftime("%Y-%m-%dT%H:%M:%S%z")
    if len(iso_tz) > 5:
        iso_tz = iso_tz[:-2] + ":" + iso_tz[-2:]
    achou = False
    for campo, valor in (("xmp:CreateDate", iso_z),
                         ("xmp:ModifyDate", iso_tz),
                         ("xmp:MetadataDate", iso_tz)):
        novo, n = re.subn(rf"(<{campo}>)[^<]*(</{campo}>)", rf"\g<1>{valor}\g<2>", txt)
        if n:
            txt = novo
            achou = True
    return txt.encode("utf-8") if achou else None


def _carimba(pdf, log, xmp_original=None):
    """Atualiza docinfo (Producer + datas, mantem o resto) e (re)escreve o
    XMP com carimbo minimo — replica o observado nas saidas do iLovePDF
    (Producer=iLovePDF; aqui identifica a replica com honestidade)."""
    import datetime
    agora_z = datetime.datetime.now(datetime.timezone.utc)
    data_z = agora_z.strftime("D:%Y%m%d%H%M%SZ")
    try:
        di = pdf.docinfo
        di["/Producer"] = "CompressPDF"
        di["/CreationDate"] = data_z
        di["/ModDate"] = data_z
    except Exception as ex:
        log(f"    carimbo docinfo: {ex}")
    try:
        ferramenta = "CompressPDF"
        try:
            for v in pdf.docinfo.values():
                pass
            ferramenta = str(pdf.docinfo.get("/Creator", ferramenta))[:80]
        except Exception:
            pass
        # O motor SEMPRE regenera o XMP (stamp 3-Heights ~1.414 B); nos 6
        # documentos policiais o XMP original ja tinha essa assinatura, o que
        # parecia preservacao — mas no teste.pdf (XMP do Word, 3.145 B) eles
        # regeraram para 1.414. Nosso carimbo minimo (857 B) faz o mesmo papel
        # e e menor, entao nao preservamos o XMP alheio.
        xmp_final = None
        xmp = xmp_final
        if xmp is None:
            xmp = (
            "<?xpacket begin='\ufeff' id='W5M0MpCehiHzreSzNTczkc9d'?>\n"
            '<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="CompressPDF">\n'
            '  <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">\n'
            '    <rdf:Description xmlns:xmp="http://ns.adobe.com/xap/1.0/" rdf:about="">\n'
            f"      <xmp:CreateDate>{agora_z.strftime('%Y-%m-%dT%H:%M:%SZ')}</xmp:CreateDate>\n"
            f"      <xmp:CreatorTool>{ferramenta}</xmp:CreatorTool>\n"
            f"      <xmp:ModifyDate>{agora_z.strftime('%Y-%m-%dT%H:%M:%SZ')}</xmp:ModifyDate>\n"
            f"      <xmp:MetadataDate>{agora_z.strftime('%Y-%m-%dT%H:%M:%SZ')}</xmp:MetadataDate>\n"
            "    </rdf:Description>\n"
            '    <rdf:Description xmlns:dc="http://purl.org/dc/elements/1.1/" rdf:about="">\n'
            "      <dc:format>application/pdf</dc:format>\n"
            "    </rdf:Description>\n"
            '    <rdf:Description xmlns:pdf="http://ns.adobe.com/pdf/1.3/" rdf:about="">\n'
            "      <pdf:Producer>CompressPDF</pdf:Producer>\n"
            "    </rdf:Description>\n"
            "  </rdf:RDF>\n"
            "</x:xmpmeta>\n"
            "<?xpacket end='w'?>\n"
            )
        _xmp_bytes = xmp if isinstance(xmp, bytes) else xmp.encode("utf-8")
        # comprime o XMP (XML comprime ~4:1); o motor grava cru, entao isso
        # deixa o mesmo metadado por uma fracao do custo
        try:
            meta = pdf.make_stream(zlib.compress(_xmp_bytes, 9))
            meta[Name("/Filter")] = Name("/FlateDecode")
        except Exception:
            meta = pdf.make_stream(_xmp_bytes)
        meta[Name("/Type")] = Name("/Metadata")
        meta[Name("/Subtype")] = Name("/XML")
        pdf.Root[Name("/Metadata")] = meta
    except Exception as ex:
        log(f"    carimbo XMP: {ex}")


def _parse_tounicode(dados, usados):
    """Extrai {codigo: unicode} do CMap ToUnicode, restrito aos usados."""
    import re
    texto = bytes(dados).decode("latin-1")
    mapa = {}

    def _u(h):
        b = bytes.fromhex(h)
        try:
            return b.decode("utf-16-be")
        except Exception:
            return ""

    for sec in re.findall(r"beginbfchar(.*?)endbfchar", texto, re.S):
        for src, dst in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", sec):
            if len(src) > 4:
                continue
            c = int(src, 16)
            if c in usados:
                for ch in _u(dst):
                    mapa.setdefault(c, ord(ch))
                    break
    for sec in re.findall(r"beginbfrange(.*?)endbfrange", texto, re.S):
        for lo, hi, base in re.findall(
                r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", sec):
            if len(lo) > 4:
                continue
            for c in range(int(lo, 16), int(hi, 16) + 1):
                if c in usados:
                    mapa.setdefault(c, int(base, 16) + (c - int(lo, 16)))
        for lo, hi, arr in re.findall(
                r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*\[([^\]]*)\]", sec):
            if len(lo) > 4:
                continue
            dsts = re.findall(r"<([0-9A-Fa-f]+)>", arr)
            for i, c in enumerate(range(int(lo, 16), int(hi, 16) + 1)):
                if c in usados and i < len(dsts):
                    for ch in _u(dsts[i]):
                        mapa.setdefault(c, ord(ch))
                        break
    return mapa


def _tabela_base(nome):
    if nome == "/WinAnsiEncoding":
        tab = {}
        for i in range(256):
            try:
                ch = bytes([i]).decode("cp1252")
                if len(ch) == 1 and ord(ch) not in (0x81, 0x8D, 0x8F, 0x90, 0x9D):
                    tab[i] = ord(ch)
            except Exception:
                pass
        return tab
    if nome == "/MacRomanEncoding":
        tab = {}
        for i in range(256):
            try:
                tab[i] = ord(bytes([i]).decode("mac_roman"))
            except Exception:
                pass
        return tab
    return None


def _conta_streams_fonte(pdf):
    """{objgen do stream: quantos descritores o referenciam}."""
    from collections import Counter
    c = Counter()
    for fo in _fontes_recursivas(pdf):
        try:
            candidatos = [fo]
            df = fo.get("/DescendantFonts")
            if df is not None:
                candidatos.extend(list(df))
            for f in candidatos:
                d = f.get("/FontDescriptor")
                if d is None:
                    continue
                for k in ("/FontFile", "/FontFile2", "/FontFile3"):
                    try:
                        st = d.get(k)
                        if st is not None:
                            c[st.objgen] += 1
                    except Exception:
                        pass
        except Exception:
            pass
    return c


def _garante_stream_exclusivo(pdf, desc, fkey, contagem, log=None):
    """Se o stream da fonte for compartilhado, clona p/ este descritor.

    Sem isso, subsetar para uma fonte corrompe a outra que usa o mesmo
    programa (caso real: TimesNewRomanPSMT simples + Type0 no mesmo PDF).
    """
    try:
        st = desc[fkey]
    except Exception:
        return None
    try:
        if contagem.get(st.objgen, 0) <= 1:
            return st
    except Exception:
        return st
    try:
        novo = pdf.make_stream(st.read_raw_bytes())
        for k in st.keys():
            if str(k) in ("/Length",):
                continue
            try:
                novo[k] = st[k]
            except Exception:
                pass
        desc[fkey] = novo
        if log:
            log("    stream de fonte compartilhado clonado")
        return novo
    except Exception:
        return st


def _glifo_do_codigo(c, diff_map, tab_base, tt):
    """Nome do glifo para um codigo, ou None se nao mapeavel."""
    nome = diff_map.get(c) if diff_map else None
    if nome:
        return nome
    u = (tab_base or {}).get(c)
    if u is None:
        return None
    try:
        return (tt.getBestCmap() or {}).get(u)
    except Exception:
        return None


def _nomes_glifos_usados(fo, codigos, tt):
    """Nomes de glifo correspondentes aos codigos usados (via Encoding do PDF).

    Mais seguro que mapear por Unicode: usa /Differences, a tabela base e,
    por fim, o cmap da propria fonte.
    """
    from fontTools.agl import AGL2UV
    nomes = set()
    diff_map = {}
    base = "/WinAnsiEncoding"
    try:
        enc = fo.get("/Encoding")
        if isinstance(enc, Name):
            base = str(enc)
        elif enc is not None:
            try:
                base = str(enc.get("/BaseEncoding", "/WinAnsiEncoding"))
            except Exception:
                pass
            try:
                diff = enc.get("/Differences")
                if diff is not None:
                    code = None
                    for el in diff:
                        if isinstance(el, int):
                            code = int(el)
                        else:
                            if code is not None:
                                diff_map[code] = str(el).lstrip("/")
                            code = (code or 0) + 1
            except Exception:
                pass
    except Exception:
        pass
    tab = _tabela_base(base) or {}
    try:
        cmap = tt.getBestCmap() or {}
    except Exception:
        cmap = {}
    ordem = set(tt.getGlyphOrder())
    # 1) pelo Encoding do PDF
    for c in codigos:
        nome = diff_map.get(c)
        if nome is None:
            u = tab.get(c)
            if u is not None:
                nome = cmap.get(u)
        if nome and nome in ordem:
            nomes.add(nome)
    # 2) pelo ToUnicode (caso o codigo nao siga o WinAnsi, ex.: export do Word)
    try:
        tou = fo.get("/ToUnicode")
        if tou is not None:
            for _c, u in _parse_tounicode(tou.read_bytes(), codigos).items():
                nome = cmap.get(u)
                if nome and nome in ordem:
                    nomes.add(nome)
    except Exception:
        pass
    return nomes, diff_map, tab


def _unicodes_da_fonte(fo, codigos):
    uni = set()
    try:
        tou = fo.get("/ToUnicode")
        if tou is not None:
            for c, u in _parse_tounicode(tou.read_bytes(), codigos).items():
                uni.add(u)
    except Exception:
        pass
    try:
        enc = fo.get("/Encoding")
        base, diff = "/WinAnsiEncoding", None
        if isinstance(enc, pikepdf.Name):
            base = str(enc)
        elif enc is not None:
            try:
                base = str(enc.get("/BaseEncoding", "/WinAnsiEncoding"))
            except Exception:
                pass
            try:
                diff = enc.get("/Differences", None)
            except Exception:
                pass
        tab = _tabela_base(base) or {}
        if diff is not None:
            from fontTools.agl import AGL2UV
            code = None
            for el in diff:
                if isinstance(el, int):
                    code = int(el)
                else:
                    if code is not None:
                        u = AGL2UV.get(str(el).lstrip("/"))
                        if u is not None:
                            tab[code] = u
                    code = (code or 0) + 1
        for c in codigos:
            if c in tab:
                uni.add(tab[c])
    except Exception:
        pass
    return {u for u in uni if 0 < u < 0x110000}


def _bytes_conteudo(obj):
    """Bytes decodificados do content stream (pagina ou Form XObject)."""
    try:
        return obj.read_bytes()
    except Exception:
        pass
    try:
        c = obj.get("/Contents")
    except Exception:
        return b""
    try:
        if isinstance(c, pikepdf.Array):
            return b" ".join(x.read_bytes() for x in c)
        return c.read_bytes()
    except Exception:
        return b""


_TOKENS_CACHE = {}


_TOK_NAME = re.compile(rb"/[^\s<>\[\]()/%]+")
_TOK_WORD = re.compile(rb"[^\s<>\[\]()/%]+")
_TOK_NUM = re.compile(rb"[+-]?(\d+\.?\d*|\.\d+)")


# brancos + delimitadores do PDF (a mascara de imagem inline precisa dos dois).
# NAO confundir com o `_DELIM` de outra funcao mais abaixo, que e' um set.
_DELIM_INLINE = b" \t\r\n\f\x00()<>[]{}/%"


def _mascara_imagens_inline(data):
    """Troca o binario de `BI ... ID <bytes> EI` por espacos (mesmo tamanho).

    O tokenizador nao conhece imagem inline: sem mascarar, os bytes da imagem
    viram "tokens" e o RESTO da pagina deixa de ser lido. Foi assim que as
    fontes da pg337 de processo.pdf foram consideradas sem uso e apagadas
    (render 3,9% diferente). O binario termina em `EI` isolado por brancos.
    """
    if b"BI" not in data:
        return data
    out = bytearray(data)
    i, n = 0, len(data)
    while True:
        j = data.find(b"BI", i)
        if j < 0:
            break
        ant = data[j - 1:j] if j else b" "
        pos = data[j + 2:j + 3]
        if ant not in _DELIM_INLINE or (pos and pos not in _DELIM_INLINE):
            i = j + 2
            continue
        k = data.find(b"ID", j + 2)
        if k < 0:
            break
        if data[k - 1:k] not in _DELIM_INLINE or data[k + 2:k + 3] not in _DELIM_INLINE:
            i = j + 2
            continue
        m = k + 3                 # depois de "ID" vem UM branco e o binario
        e = m
        while True:
            e = data.find(b"EI", e)
            if e < 0:
                e = n
                break
            antes = data[e - 1:e]
            depois = data[e + 2:e + 3]
            if antes in _DELIM_INLINE and (not depois or depois in _DELIM_INLINE):
                break
            e += 2
        for x in range(m, min(e, n)):
            out[x] = 0x20
        i = e + 2
    return bytes(out)


def _tokens_conteudo(data):
    """Tokeniza content stream cru em (tipo, valor).

    Tipos: 'str' (bytes literais, escapes resolvidos), 'hex' (bytes),
    'name', 'num', 'op', 'arr', 'dict'. Byte-exato: nao decodifica texto.

    Duas otimizacoes que nao mudam o resultado:
      - regexes compilados com .match(data, i): o codigo antigo fazia
        re.match(pat, data[i:]), copiando o resto do stream a cada token
        (O(n^2) de memoria/tempo em content streams grandes);
      - cache por conteudo: varias fases tokenizam o MESMO stream.
    """
    chave = (len(data), zlib.crc32(data))
    cache = _TOKENS_CACHE.get(chave)
    if cache is not None:
        return cache
    if len(_TOKENS_CACHE) > 4096:
        _TOKENS_CACHE.clear()
    data = _mascara_imagens_inline(data)
    toks = []
    i, n = 0, len(data)
    while i < n:
        c = data[i:i+1]
        if c in b" \t\r\n\f\x00":
            i += 1
            continue
        if c == b"%":
            j = data.find(b"\n", i)
            i = n if j < 0 else j + 1
            continue
        if c == b"(":
            depth = 1
            j = i + 1
            buf = bytearray()
            while j < n and depth:
                d = data[j:j+1]
                if d == b"\\":
                    esc = data[j+1:j+2]
                    mp = {b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"\b",
                          b"f": b"\f", b"(": b"(", b")": b")", b"\\": b"\\"}
                    if esc in mp:
                        buf += mp[esc]
                        j += 2
                    elif esc in b"01234567":
                        m = re.match(rb"[0-7]{1,3}", data[j+1:j+4])
                        buf.append(int(m.group(), 8) & 0xFF)
                        j += 1 + len(m.group())
                    elif esc in (b"\r", b"\n"):
                        j += 2
                        if data[j:j+1] == b"\n":
                            j += 1
                    else:
                        buf += esc
                        j += 2
                elif d == b"(":
                    depth += 1
                    buf += d
                    j += 1
                elif d == b")":
                    depth -= 1
                    if depth:
                        buf += d
                    j += 1
                else:
                    buf += d
                    j += 1
            toks.append(("str", bytes(buf)))
            i = j
            continue
        if c == b"<":
            if data[i+1:i+2] == b"<":
                toks.append(("dict", b"<<"))
                i += 2
                continue
            j = data.find(b">", i)
            if j < 0:
                break
            hx = re.sub(rb"\s+", b"", data[i+1:j])
            if len(hx) % 2:
                hx += b"0"
            try:
                toks.append(("hex", bytes.fromhex(hx.decode("ascii"))))
            except Exception:
                pass
            i = j + 1
            continue
        if c == b">":
            if data[i+1:i+2] == b">":
                toks.append(("dict", b">>"))
                i += 2
                continue
            i += 1
            continue
        if c in b"[]":
            toks.append(("arr", c))
            i += 1
            continue
        if c == b"/":
            m = _TOK_NAME.match(data, i)
            if m:
                toks.append(("name", m.group()))
                i = m.end()
                continue
        m = _TOK_WORD.match(data, i)
        if m:
            g = m.group()
            if _TOK_NUM.fullmatch(g):
                toks.append(("num", g))
            else:
                toks.append(("op", g))
            i = m.end()
            continue
        i += 1
    _TOKENS_CACHE[chave] = toks
    return toks


def _codigos_por_fonte(pdf):
    """objgen da fonte -> set(codigos de char usados nos contents).

    Usa tokenizer byte-exato sobre o stream decodificado (nao perde
    informacao como a decodificacao de strings do parser)."""

    por_obj = defaultdict(set)

    def walk(dados, res):
        nomes = defaultdict(set)
        cur = None
        pend = []  # (tipo, valor)
        for tipo, val in _tokens_conteudo(dados):
            if tipo in ("str", "hex", "name"):
                pend.append((tipo, val))
                continue
            if tipo in ("num", "arr", "dict"):
                continue
            if tipo == "op":
                if val == b"Tf":
                    cur = None
                    for tp, p in reversed(pend):
                        if tp == "name":
                            cur = p.decode("latin-1")
                            break
                    pend = []
                    # fonte SELECIONADA por Tf conta como usada mesmo que nao
                    # consigamos ler nenhum glifo dela: sem isso ela e' apagada
                    # do /Resources e a pagina fica sem fonte (processo.pdf
                    # pg148, /R72 -> extracao vira \x00\x01...).
                    if cur is not None:
                        try:
                            fo_tf = res.get("/Font", {}).get(Name(cur))
                            if fo_tf is not None:
                                por_obj[fo_tf.objgen]  # cria a entrada (set vazio)
                        except Exception:
                            pass
                elif val in (b"Tj", b"TJ", b"'", b'"') and cur is not None:
                    for tp, p in pend:
                        if tp in ("str", "hex"):
                            nomes[cur].update(p)
                    pend = []
                elif val == b"Do":
                    alvo = None
                    for tp, p in reversed(pend):
                        if tp == "name":
                            alvo = p
                            break
                    pend = []
                    if alvo is not None:
                        try:
                            xo = res.get("/XObject", {}).get(Name(alvo.decode("latin-1")))
                        except Exception:
                            xo = None
                        if xo is not None and str(xo.get("/Subtype")) == "/Form":
                            sub = _bytes_conteudo(xo)
                            if sub:
                                walk(sub, xo.get("/Resources", res))
                else:
                    pend = []
                continue
            pend = []
        try:
            fontes = res.get("/Font", {})
        except Exception:
            return
        for nome, codes in nomes.items():
            try:
                fo = fontes.get(Name(nome))
            except Exception:
                fo = None
            if fo is None:
                continue
            try:
                por_obj[fo.objgen].update(codes)
            except Exception:
                pass

    for pagina in pdf.pages:
        try:
            res = pagina.Resources
            dados = _bytes_conteudo(pagina)
        except Exception:
            continue
        if not dados:
            continue
        walk(dados, res)
    return por_obj


def _tipo_obj(obj):
    """Tipo real do Object do pikepdf: 'dictionary', 'array', 'stream', ...

    NAO use `hasattr(obj, "keys")` nem "keys() levanta em array": em pikepdf
    10.18 `keys()` de um array devolve [] SEM levantar excecao, entao o truque
    antigo tratava array como dicionario vazio e a varredura parava ali (era a
    causa de metade dos duplicados que sobravam em processo.pdf).
    """
    try:
        return obj._type_name
    except Exception:
        return ""


def _eh_dict(obj):
    return _tipo_obj(obj) in ("dictionary", "stream")


def _impressao_rapida(obj):
    """crc32 de uma representacao SEM truncamento.

    `str()` de um Object do pikepdf corta a saida (ex.: um /Encoding com 257
    /Differences aparece como `<pikepdf.Dictionary(...)({... "Differences": [ `),
    entao usar str() como identidade faz fontes DIFERENTES colidirem: 3 Type3
    distintos de processo.pdf cairam na mesma assinatura e a extracao de texto
    passou a sair como `\\x00\\x01...` nas paginas 148-151/179/209/221.
    """
    try:
        dados = _serializa_obj(obj)
    except Exception:
        try:
            dados = str(obj).encode("latin-1", "replace")
        except Exception:
            return 0
    return zlib.crc32(dados)


def _assinatura_fonte(fo):
    """Identidade da fonte: mesmo BaseFont + mesmo programa + mesmas larguras
    => os objetos sao intercambiaveis."""
    bf = str(fo.get("/BaseFont", ""))
    sub = str(fo.get("/Subtype", ""))
    enc = ""
    try:
        e = fo.get("/Encoding")
        if e is not None:
            # Name -> texto; dict (Differences!) -> impressao digital completa
            enc = str(e) if isinstance(e, Name) else "%d" % _impressao_rapida(e)
    except Exception:
        pass
    larg = ""
    try:
        if "/Widths" in fo:
            larg = "%d:%d" % (len(fo["/Widths"]), _impressao_rapida(fo["/Widths"]))
        elif "/W" in fo:
            larg = "%d:%d" % (len(fo["/W"]), _impressao_rapida(fo["/W"]))
    except Exception:
        pass
    # Type3 nao tem FontDescriptor: os charprocs sao parte da identidade
    procs = ""
    try:
        cp = fo.get("/CharProcs")
        if cp is not None and _eh_dict(cp):
            procs = "%d" % zlib.crc32(
                "|".join(sorted(str(k) for k in cp.keys())).encode("latin-1", "replace"))
    except Exception:
        pass
    prog = b""
    try:
        fd = fo.get("/FontDescriptor")
        if fd is not None:
            for k in ("/FontFile", "/FontFile2", "/FontFile3"):
                if k in fd:
                    bruto = fd[k].read_raw_bytes()
                    prog = ("%s:%d:%d" % (k, len(bruto), zlib.crc32(bruto))).encode()
                    break
    except Exception:
        pass
    # O /ToUnicode faz parte da identidade: duas copias do mesmo programa com
    # ToUnicode diferente desenham igual mas EXTRAEM texto diferente. Fundi-las
    # (era o caso de processo.pdf pg209: "Laudo" saia como "/audo") mantem o
    # render e quebra busca/copia.
    tou = b""
    try:
        tu = fo.get("/ToUnicode")
        if tu is not None:
            bruto = tu.read_raw_bytes()
            tou = ("%d:%d" % (len(bruto), zlib.crc32(bruto))).encode()
    except Exception:
        pass
    return (bf, sub, enc, larg, prog, tou, procs)


def _consolida_imagens(pdf, log):
    """Consolida imagens identicas num unico objeto (RemoveRedundantObjects).

    O motor grava uma vez o mesmo XObject re-embutido pagina a pagina. Medido
    em processo.pdf: 676 objetos de imagem nossos contra 266 do iLovePDF.
    Assinatura: bytes crus + filtro + dimensoes + espaco de cor.
    """
    vistos = {}
    mapa = {}
    for obj in pdf.objects:
        try:
            if not isinstance(obj, pikepdf.Stream):
                continue
            sub = str(obj.get("/Subtype", ""))
            if sub not in ("/Image", "/Form"):
                continue
            og = obj.objgen
            if not og or not og[0]:
                continue
            bruto = obj.read_raw_bytes()
            chave = (sub, len(bruto), zlib.crc32(bruto), str(obj.get("/Filter", "")),
                     int(obj.get("/Width", 0)), int(obj.get("/Height", 0)),
                     str(obj.get("/ColorSpace", "")), int(obj.get("/BitsPerComponent", 0)),
                     str(obj.get("/BBox", "")), str(obj.get("/Matrix", "")),
                     len(str(obj.get("/Resources", ""))))
        except Exception:
            continue
        if chave in vistos:
            mapa[og] = vistos[chave]
        else:
            vistos[chave] = og
    if not mapa:
        return 0
    trocas = 0
    pilha = []
    for pagina in pdf.pages:
        try:
            pilha.append(pagina.Resources)
        except Exception:
            pass
    # imagens tambem vivem nas aparencias de anotacao (/AP) e em Type3 charprocs
    try:
        for pagina in pdf.pages:
            try:
                anots = pagina.obj.get("/Annots")
            except Exception:
                continue
            if anots is None:
                continue
            for anot in anots:
                try:
                    ap = anot.get("/AP")
                    if ap is None:
                        continue
                    for chave in list(ap.keys()):
                        fluxo = ap[chave]
                        if isinstance(fluxo, pikepdf.Stream):
                            pilha.append(fluxo.get("/Resources"))
                except Exception:
                    pass
    except Exception:
        pass
    try:
        for pagina in pdf.pages:
            try:
                fontes = pagina.Resources.get("/Font")
            except Exception:
                continue
            if fontes is None:
                continue
            try:
                nomes_f = list(fontes.keys())
            except Exception:
                continue
            for nf in nomes_f:
                try:
                    fo = fontes[nf]
                    if str(fo.get("/Subtype", "")) != "/Type3":
                        continue
                    procs = fo.get("/CharProcs")
                    if procs is None:
                        continue
                    pilha.append(fo.get("/Resources"))
                    for pc in list(procs.keys()):
                        pilha.append(procs[pc].get("/Resources"))
                except Exception:
                    pass
    except Exception:
        pass
    vistos_res = set()
    manter = []
    while pilha:
        res = pilha.pop()
        if res is None:
            continue
        try:
            og = res.objgen
        except Exception:
            og = None
        marca = og if (og and og[0]) else ("d", id(res))
        if marca in vistos_res:
            continue
        vistos_res.add(marca)
        manter.append(res)
        if not _eh_dict(res):
            if _tipo_obj(res) == "array":
                try:
                    for item in res:
                        pilha.append(item)
                except Exception:
                    pass
            continue
        chaves = list(res.keys())
        for k in chaves:
            try:
                v = res[k]
            except Exception:
                continue
            if str(k) == "/XObject" and v is not None:
                try:
                    nomes = list(v.keys())
                except Exception:
                    nomes = []
                for nome in nomes:
                    try:
                        alvo = v[nome].objgen
                    except Exception:
                        continue
                    canonico = mapa.get(alvo)
                    if canonico is not None:
                        try:
                            v[nome] = pdf.get_object(canonico)
                            trocas += 1
                        except Exception:
                            pass
                # forms aninhados: o Form XObject tem /Resources proprio
                for nome in nomes:
                    try:
                        filho = v[nome]
                        if (isinstance(filho, pikepdf.Stream)
                                and str(filho.get("/Subtype", "")) == "/Form"):
                            pilha.append(filho.get("/Resources"))
                    except Exception:
                        pass
                continue
            pilha.append(v)
    log("    imagens consolidadas: %d duplicata(s) removida(s), %d objeto(s) mantido(s), "
        "%d referencia(s) reapontada(s)" % (len(mapa), len(vistos), trocas))
    return mapa


def _consolida_charprocs(pdf, log):
    """Consolida charprocs de fonte Type3 identicos.

    Type3 embute um stream por glifo; cada pagina traz a sua copia da fonte.
    Medido em processo.pdf: 2.519 charprocs nossos contra 967 do iLovePDF,
    com o mesmo glifo repetido 16x (deles 6-7x).
    """
    vistos = {}
    mapa = {}
    for obj in pdf.objects:
        if not _eh_dict(obj):
            continue
        if str(obj.get("/Subtype", "")) != "/Type3":
            continue
        procs = obj.get("/CharProcs")
        if procs is None or not _eh_dict(procs):
            continue
        try:
            nomes = [str(k) for k in procs.keys()]
        except Exception:
            continue
        for nome in nomes:
            try:
                s = procs[nome]
            except Exception:
                continue
            og = getattr(s, "objgen", None)
            if not og or not og[0]:
                continue
            try:
                bruto = s.read_raw_bytes()
            except Exception:
                continue
            chave = (len(bruto), zlib.crc32(bruto))
            if chave in vistos:
                if vistos[chave] != og:
                    mapa[og] = vistos[chave]
            else:
                vistos[chave] = og
    log("    charprocs Type3: %d copia(s) removida(s), %d glifo(s) distinto(s)"
        % (len(mapa), len(vistos)))
    return mapa


def _consolida_programas_fonte(pdf, log):
    """Consolida programas de fonte (FontFile*) byte a byte identicos.

    O motor compartilha um mesmo programa entre varios dicionarios de fonte
    (MergeEmbeddedFonts); medido em processo.pdf: 111 programas para 200 fontes
    no iLovePDF contra 176 nossos.
    """
    vistos = {}
    mapa = {}
    for obj in pdf.objects:
        if not _eh_dict(obj):
            continue
        if str(obj.get("/Type", "")) != "/FontDescriptor":
            continue
        for chave in ("/FontFile", "/FontFile2", "/FontFile3"):
            try:
                s = obj.get(chave)
            except Exception:
                continue
            if s is None:
                continue
            og = getattr(s, "objgen", None)
            if not og or not og[0]:
                continue
            try:
                bruto = s.read_raw_bytes()
            except Exception:
                continue
            k = (chave, len(bruto), zlib.crc32(bruto))
            if k in vistos:
                if vistos[k] != og:
                    mapa[og] = vistos[k]
            else:
                vistos[k] = og
    log("    programas de fonte: %d copia(s) removida(s), %d distinto(s)"
        % (len(mapa), len(vistos)))
    return mapa


def _reaponta_tudo(pdf, mapa, log):
    """Reaponta toda referencia indireta cujo objgen esteja no mapa.

    As varreduras de /Resources so alcancam o que esta em resources; imagem e
    fonte tambem aparecem em /SMask, /Alternates, /CharProcs, /AP de anotacao,
    /Resources de Pattern e afins. Aqui a varredura e' sobre `pdf.objects`
    inteiro, entao nenhuma copia sobrevive por falta de caminho.
    """
    if not mapa:
        return 0
    trocas = 0

    def desce(cont, prof=0):
        nonlocal trocas
        if prof > 64:
            return
        tipo = _tipo_obj(cont)
        if tipo in ("dictionary", "stream"):
            try:
                chaves = [str(k) for k in cont.keys()]
            except Exception:
                return
            for k in chaves:
                try:
                    v = cont[k]
                except Exception:
                    continue
                canonico = mapa.get(getattr(v, "objgen", None))
                if canonico is not None:
                    try:
                        cont[k] = pdf.get_object(canonico)
                        trocas += 1
                        continue
                    except Exception:
                        pass
                # so desce em container DIRETO: objeto indireto sera visitado
                # como raiz em pdf.objects (e o grafo tem ciclos: /Parent).
                if (not getattr(v, "is_indirect", False)
                        and _tipo_obj(v) in ("dictionary", "array")):
                    desce(v, prof + 1)
        elif tipo == "array":
            try:
                n = len(cont)
            except Exception:
                return
            for i in range(n):
                try:
                    v = cont[i]
                except Exception:
                    continue
                canonico = mapa.get(getattr(v, "objgen", None))
                if canonico is not None:
                    try:
                        cont[i] = pdf.get_object(canonico)
                        trocas += 1
                        continue
                    except Exception:
                        pass
                if (not getattr(v, "is_indirect", False)
                        and _tipo_obj(v) in ("dictionary", "array")):
                    desce(v, prof + 1)

    for obj in pdf.objects:
        desce(obj)
    log("    referencias reapontadas no documento inteiro: %d" % trocas)
    return trocas


def _consolida_fontes(pdf, log):
    """Consolida fontes identicas num unico objeto.

    O motor 3-Heights reusa o mesmo objeto quando o mesmo programa de fonte foi
    re-embutido pagina a pagina; sem isso o arquivo carrega centenas de copias.
    Medido em processo.pdf: 1.215 fontes, 937 duplicatas em 49 grupos, contra
    348 objetos na saida do iLovePDF.
    """
    vistos = {}
    mapa = {}
    for obj in pdf.objects:
        try:
            if not isinstance(obj, pikepdf.Dictionary):
                continue
            if str(obj.get("/Type", "")) != "/Font":
                continue
            og = obj.objgen
            if og is None:
                continue
            chave = _assinatura_fonte(obj)
        except Exception:
            continue
        if chave in vistos:
            mapa[og] = vistos[chave]
        else:
            vistos[chave] = og
    if not mapa:
        return 0
    trocas = 0
    dicts = 0
    entradas = 0
    removidos = 0
    # fontes com glifos realmente usados (paginas + Form XObjects)
    try:
        usados = set(_codigos_por_fonte(pdf).keys())
    except Exception:
        usados = set()

    def _remapea(fontes):
        nonlocal trocas, entradas, removidos
        apagar = []
        for nome in list(fontes.keys()):
            entradas += 1
            try:
                og = fontes[nome].objgen
            except Exception:
                continue
            canonico = mapa.get(og)
            og_orig = og
            if canonico is not None:
                try:
                    fontes[nome] = pdf.get_object(canonico)
                    trocas += 1
                    og = canonico
                except Exception:
                    pass
            # a decisao de remover usa a identidade ORIGINAL: o canonico pode
            # ser uma copia que nao aparece em `usados` (ex.: a primeira fonte
            # padrao da varredura) e apagar por causa dele derrubava fontes
            # realmente usadas (processo.pdf pg148 /R72 -> texto virava lixo).
            if og_orig and og_orig[0] and og_orig not in usados:
                apagar.append((nome, og_orig))
        # NUNCA esvaziar um /Font: se TODAS seriam removidas, o conteudo
        # daquela pagina provavelmente nao pode ser lido (imagem inline, CMap
        # quebrado) e apagar tudo deixa a pagina sem fonte — o texto continua
        # desenhado pelo leitor mas a extracao vira lixo (processo.pdf pg337).
        if len(apagar) == len(fontes):
            apagar = []
        for nome, og in apagar:
            try:
                del fontes[nome]
                removidos += 1
                if os.environ.get("COMPRESSPDF_DEBUG_FONTES"):
                    log("      remove /%s (objgen %s)" % (nome, og))
            except Exception:
                pass
        return 1

    vistos_res = set()
    manter = []
    pilha = []
    for pagina in pdf.pages:
        try:
            pilha.append(pagina.Resources)
        except Exception:
            pass
    # fontes tambem vivem no /DR do AcroForm e nas aparencias de anotacao
    try:
        acro = pdf.Root.get("/AcroForm")
        if acro is not None:
            pilha.append(acro.get("/DR"))
    except Exception:
        pass
    try:
        for pagina in pdf.pages:
            try:
                anots = pagina.obj.get("/Annots")
            except Exception:
                continue
            if anots is None:
                continue
            for anot in anots:
                try:
                    ap = anot.get("/AP")
                    if ap is None:
                        continue
                    for chave in list(ap.keys()):
                        fluxo = ap[chave]
                        if isinstance(fluxo, pikepdf.Stream):
                            pilha.append(fluxo.get("/Resources"))
                except Exception:
                    pass
    except Exception:
        pass
    while pilha:
        res = pilha.pop()
        if res is None:
            continue
        try:
            og = res.objgen
        except Exception:
            og = None
        # objgen de objeto direto e' (0, 0): NAO serve como identidade
        if og and og[0]:
            marca = og
        else:
            marca = ("direto", id(res))
        if marca in vistos_res:
            continue
        vistos_res.add(marca)
        manter.append(res)          # evita reuso de id() durante a varredura
        # NUNCA inferir dicionario por keys(): em pikepdf 10.18 keys() de um
        # array devolve [] sem levantar, e a varredura pararia no primeiro
        # array (/ProcSet, /Annots, /Kids...).
        if _eh_dict(res):
            try:
                fontes = res.get("/Font")
            except Exception:
                fontes = None
            if fontes is not None and _eh_dict(fontes):
                try:
                    dicts += _remapea(fontes)
                except Exception:
                    pass
            try:
                chaves = [str(k) for k in res.keys()]
            except Exception:
                chaves = []
            for k in chaves:
                try:
                    pilha.append(res[k])
                except Exception:
                    pass
        elif _tipo_obj(res) == "array":
            try:
                for item in res:
                    pilha.append(item)
            except Exception:
                pass
    log("    fontes consolidadas: %d duplicata(s) removida(s), %d objeto(s) mantido(s), "
        "%d referencia(s) reapontada(s), %d fonte(s) sem uso removida(s) "
        "[%d dict(s) /Font, %d entrada(s)]"
        % (len(mapa), len(vistos), trocas, removidos, dicts, entradas))
    return mapa


def _merge_subset_fontes(pdf, log):
    """Subseta UMA vez por fonte-fonte e compartilha o programa (MergeEmbeddedFonts).

    O motor grava um programa por fonte-fonte e aponta todos os dicionarios para
    ele. Medido em processo.pdf (extreme): 61 BaseFonts, 92 programas/911 KB no
    iLovePDF contra 163/1.612 KB nossos. Aqui os dicionarios que embutem os
    MESMOS bytes de programa sao agrupados, o subset usa a UNIAO dos glifos do
    grupo e todos passam a apontar para o stream canonico.

    Para Type0/CID o /CIDToGIDMap de cada fonte e' reconstruido contra a ordem
    de glifos resultante (que agora e' compartilhada).

    Devolve quantas fontes foram processadas (0 = nada feito, o chamador cai no
    caminho antigo).
    """
    if os.environ.get("COMPRESSPDF_MERGE", "1") == "0":
        return 0
    try:
        from fontTools import subset
        from fontTools.ttLib import TTFont
    except ImportError:
        return 0

    membros = []          # dicts com o necessario para subsetar/compartilhar
    vistos = set()

    def _fonte_simples(og, codes):
        try:
            fo = pdf.get_object(og)
            if str(fo.get("/Subtype", "")) == "/Type0":
                return None
            fd = fo.get("/FontDescriptor")
        except Exception:
            return None
        if fd is None or not _eh_dict(fd):
            return None
        fkey = next((k for k in ("/FontFile2", "/FontFile3", "/FontFile")
                     if k in fd), None)
        if fkey is None:
            return None
        return {"fo": fo, "fd": fd, "fkey": fkey, "codigos": set(codes),
                "tipo": "simple", "d0": None, "mapa": None, "identidade": True}

    def _fonte_cid(fo, codigos):
        try:
            if str(fo.get("/Subtype", "")) != "/Type0":
                return None
            if str(fo.get("/Encoding", "")) != "/Identity-H":
                return None
            desc = fo.get("/DescendantFonts")
            if desc is None or len(desc) == 0:
                return None
            d0 = desc[0]
            if str(d0.get("/Subtype", "")) != "/CIDFontType2":
                return None
            fd = d0.get("/FontDescriptor")
            if fd is None or not _eh_dict(fd):
                return None
            ff = fd.get("/FontFile2")
            if ff is None:
                return None
            c2g = d0.get("/CIDToGIDMap")
            identidade = c2g is None or isinstance(c2g, Name)
            mapa = None
            if not identidade:
                try:
                    mapa = c2g.read_bytes()
                except Exception:
                    return None
        except Exception:
            return None
        return {"fo": fo, "fd": fd, "fkey": "/FontFile2", "codigos": set(codigos),
                "tipo": "cid", "d0": d0, "mapa": mapa, "identidade": identidade}

    for og, codes in _codigos_por_fonte(pdf).items():
        if not codes:
            continue
        m = _fonte_simples(og, codes)
        if m is not None:
            membros.append(m)
    for fo, codigos, _w in _usos_por_fonte(pdf):
        if not codigos:
            continue
        try:
            chave = fo.objgen
        except Exception:
            continue
        if chave in vistos:
            continue
        vistos.add(chave)
        m = _fonte_cid(fo, codigos)
        if m is not None:
            membros.append(m)
    if not membros:
        return 0

    # agrupa por BYTES do programa (mesma fonte-fonte literal). Agrupar por
    # BaseFont e subsetar pela uniao de glifos foi medido e PIORA ~160 KB em
    # processo.pdf: o motor nao faz uniao, cada copia mantem o seu subset.
    grupos = {}
    for m in membros:
        try:
            raw = m["fd"][m["fkey"]].read_bytes()
        except Exception:
            continue
        m["raw"] = raw
        grupos.setdefault((len(raw), zlib.crc32(raw)), []).append(m)

    tag = _tag_subset(pdf)
    processados = 0
    programas_antes = len(grupos)
    for _chave, membros_g in grupos.items():
        if not membros_g:
            continue
        try:
            # o maior programa e' o canonico (tem o conjunto de glifos completo)
            canon = max(membros_g, key=lambda x: len(x["raw"]))
            tt = TTFont(io.BytesIO(canon["raw"]))
            ordem = tt.getGlyphOrder()
            ordem_set = set(ordem)
            nomes_uniao = set()
            por_codigo = []
            falhou = False
            for m in membros_g:
                if m["tipo"] == "simple":
                    nomes, diff_map, tab_base = _nomes_glifos_usados(
                        m["fo"], m["codigos"], tt)
                    if not nomes:
                        falhou = True
                        break
                    nomes = set(nomes)
                    # glifo que o canonico nao tem: nao arriscar a fusao
                    if not nomes <= ordem_set:
                        falhou = True
                        break
                    nomes_uniao |= nomes
                    por_codigo.append(None)
                else:
                    c2n = {}
                    for cid in m["codigos"]:
                        if m["identidade"]:
                            g = cid
                        else:
                            mp = m["mapa"] or b""
                            g = ((mp[2 * cid] << 8) | mp[2 * cid + 1]
                                 if 2 * cid + 1 < len(mp) else None)
                        if g is not None and 0 < g < len(ordem):
                            c2n[cid] = ordem[g]
                    if not c2n:
                        falhou = True
                        break
                    nomes_uniao |= set(c2n.values())
                    por_codigo.append(c2n)
            if falhou or not nomes_uniao:
                continue
            total_antes = sum(len(m["raw"]) for m in membros_g)
            # CID mantem os GIDs (o /CIDToGIDMap depende disso); fonte simples
            # renumera, como o motor (medido: Calibri 4 glifos deles x 3.874
            # nossos com retain_gids).
            tem_cid = any(m["tipo"] == "cid" for m in membros_g)
            opts = subset.Options()
            opts.layout_features = ["*"]
            _politica_subset(opts, retain=True if tem_cid else False)
            ss = subset.Subsetter(opts)
            ss.populate(glyphs=sorted(nomes_uniao))
            ss.subset(tt)
            _normaliza_nome_programa(tt, canon["fo"].get("/BaseFont", ""))
            buf = io.BytesIO()
            tt.save(buf)
            novo = buf.getvalue()
            if len(novo) >= total_antes:
                continue
            nome2gid = {nm: i for i, nm in enumerate(tt.getGlyphOrder())}
            # stream canonico do programa compartilhado
            canonico = pdf.make_stream(b"")
            canonico.write(zlib.compress(novo, 9), filter=Name("/FlateDecode"),
                           type_check=False)
            canonico[Name("/Length1")] = len(novo)
            for m, c2n in zip(membros_g, por_codigo):
                try:
                    m["fd"][m["fkey"]] = canonico
                    base = str(m["fo"].get("/BaseFont", "")).lstrip("/")
                    if "+" in base:
                        base = base.split("+", 1)[1]
                    m["fo"][Name("/BaseFont")] = Name("/%s+%s" % (tag, base))
                    if m["tipo"] == "cid" and m["d0"] is not None:
                        try:
                            m["d0"][Name("/BaseFont")] = Name("/%s+%s" % (tag, base))
                        except Exception:
                            pass
                        maxcid = max(c2n)
                        mapa_novo = bytearray(2 * (maxcid + 1))
                        for cid, nome in c2n.items():
                            g = nome2gid.get(nome, 0)
                            mapa_novo[2 * cid] = (g >> 8) & 0xFF
                            mapa_novo[2 * cid + 1] = g & 0xFF
                        if m["identidade"]:
                            # GIDs preservados: /Identity continua valido
                            pass
                        else:
                            try:
                                m["d0"][Name("/CIDToGIDMap")].write(
                                    zlib.compress(bytes(mapa_novo), 9))
                            except Exception:
                                novo_c2g = pdf.make_stream(zlib.compress(bytes(mapa_novo), 9))
                                novo_c2g[Name("/Filter")] = Name("/FlateDecode")
                                m["d0"][Name("/CIDToGIDMap")] = novo_c2g
                    processados += 1
                except Exception:
                    continue
        except Exception as ex:
            log("    merge fonte %s: %s" % (_crc, ex))
            continue
    if processados:
        log("    fontes: %d copia(s) -> %d programa(s), %d fonte(s) reapontada(s)"
            % (len(membros), len(grupos), processados))
    return processados


def _subset_fontes(pdf, log):
    """Re-subseta fontes embutidas p/ glifos usados (SubsetFonts=1 nos 3 niveis).

    Replica o observado: prefixo do BaseFont trocado, Widths/Encoding
    mantidos, troca so se ficar menor."""
    try:
        from fontTools import subset
        from fontTools.ttLib import TTFont
    except ImportError:
        log("    subset fontes: fontTools ausente (pip install fonttools)")
        return
    usos = _codigos_por_fonte(pdf)
    if not usos:
        return
    contagem = _conta_streams_fonte(pdf)
    tag = _tag_subset(pdf)
    n = 0
    vistos = set()
    # Itera TODAS as fontes com glifos usados — inclusive as que vivem so no
    # /Resources de um Form XObject ou de uma aparencia de anotacao. A versao
    # antiga olhava apenas page.Resources e deixava programas inteiros no
    # arquivo (medido em processo.pdf: Calibri de 79 KB nunca subsetada).
    pares = []
    for og, codes in usos.items():
        if not codes or og in vistos:
            continue
        vistos.add(og)
        try:
            fo = pdf.get_object(og)
        except Exception:
            continue
        pares.append((og, fo, codes))
    for og, fo, codes in pares:
        try:
            if str(fo.get("/Subtype", "")) == "/Type0":
                continue          # CID tem caminho proprio (_subset_fontes_cid)
            desc = fo.get("/FontDescriptor")
        except Exception:
            continue
        if desc is None:
            continue
        fkey = next((k for k in ("/FontFile2", "/FontFile3", "/FontFile")
                     if k in desc), None)
        if fkey is None:
            continue  # nao embutida: nada a fazer
        _garante_stream_exclusivo(pdf, desc, fkey, contagem, log)
        try:
            raw = desc[fkey].read_bytes()
            tt = TTFont(io.BytesIO(raw))
            nomes, diff_map, tab_base = _nomes_glifos_usados(fo, codes, tt)
            if not nomes:
                continue
            faltando = [c for c in codes
                        if _glifo_do_codigo(c, diff_map, tab_base, tt) is None]
            if faltando:
                continue  # nao sabemos mapear todos: nao arriscar
            opts = subset.Options()
            opts.layout_features = ["*"]
            _politica_subset(opts)
            ss = subset.Subsetter(opts)
            ss.populate(glyphs=sorted(nomes))
            ss.subset(tt)
            _normaliza_nome_programa(tt, fo.get("/BaseFont", ""))
            # verifica que todo codigo usado continua tendo glifo
            restantes = set(tt.getGlyphOrder())
            if any(_glifo_do_codigo(c, diff_map, tab_base, tt) not in restantes
                   for c in codes):
                continue
            buf = io.BytesIO()
            tt.save(buf)
            novo = buf.getvalue()
            if len(novo) >= len(raw):
                continue
            alvo = desc[fkey]
            cur_filter = alvo.get("/Filter", None)
            if cur_filter is None:
                alvo.write(novo)
            elif str(cur_filter) == "/FlateDecode":
                alvo.write(zlib.compress(novo, 9))
                alvo[Name("/Filter")] = Name("/FlateDecode")
            else:
                continue
            if fkey == "/FontFile2":
                alvo[Name("/Length1")] = len(novo)
            else:
                for k in ("/Length1", "/Length2", "/Length3"):
                    try:
                        del alvo[k]
                    except Exception:
                        pass
            try:
                base = str(fo.get("/BaseFont", ""))
                if "+" in base:
                    fo[Name("/BaseFont")] = Name(f"/{tag}+{base.split('+', 1)[1]}")
            except Exception:
                pass
            n += 1
        except Exception as ex:
            log(f"    fonte {og}: subset falhou ({ex})")
            continue
    if n:
        log(f"    fontes re-subsetadas: {n}")


def _remove_fontes_padrao(pdf, log):
    n = 0
    vistos = set()
    for pagina in pdf.pages:
        try:
            fontes = pagina.Resources.get("/Font", {})
        except Exception:
            continue
        for _nome, fonte in dict(fontes).items():
            try:
                if fonte.objgen in vistos:
                    continue
                vistos.add(fonte.objgen)
                base = str(fonte.get("/BaseFont", ""))
                if base not in FONTES_PADRAO_14:
                    continue
                enc = fonte.get("/Encoding")
                if enc is not None:
                    try:
                        if "/Differences" in enc:
                            continue
                    except Exception:
                        pass
                desc = fonte.get("/FontDescriptor")
                if desc is None:
                    continue
                tirou = False
                for k in ("/FontFile", "/FontFile2", "/FontFile3"):
                    try:
                        del desc[k]
                        tirou = True
                    except Exception:
                        pass
                n += tirou
            except Exception:
                continue
    if n:
        log(f"    fontes padrao desembutidas: {n}")


def _mat_mul(m1, m2):
    a, b, c, d, e, f = m1
    g, h, i, j, k, l = m2
    return (a*g+b*i, a*h+b*j, c*g+d*i, c*h+d*j, e*g+f*i+k, e*h+f*j+l)


def _bbox_de_path(instrucoes):
    """bbox (x0,y0,x1,y1) do path acumulado e se e' so retas/retangulos."""
    xs, ys = [], []
    retangular = True
    pts = []
    for operandos, operador in instrucoes:
        op = str(operador)
        try:
            vals = [float(x) for x in operandos]
        except Exception:
            continue
        if op == "re" and len(vals) >= 4:
            x, y, w, h = vals[:4]
            xs += [x, x + w]
            ys += [y, y + h]
        elif op in ("m", "l") and len(vals) >= 2:
            xs.append(vals[0])
            ys.append(vals[1])
        elif op in ("c",) and len(vals) >= 6:
            retangular = False
            xs += [vals[0], vals[2], vals[4]]
            ys += [vals[1], vals[3], vals[5]]
        elif op in ("v", "y") and len(vals) >= 4:
            retangular = False
            xs += [vals[0], vals[2]]
            ys += [vals[1], vals[3]]
        elif op == "h":
            pass
    if not xs or not ys:
        return None, retangular
    return (min(xs), min(ys), max(xs), max(ys)), retangular


def _intersecta(b1, b2):
    if b1 is None:
        return b2
    if b2 is None:
        return b1
    r = (max(b1[0], b2[0]), max(b1[1], b2[1]),
         min(b1[2], b2[2]), min(b1[3], b2[3]))
    if r[2] <= r[0] or r[3] <= r[1]:
        return None
    return r


def _coleta_draws(pdf):
    """Lista de draws de imagem com clip retangular e CTM."""
    draws = []
    for pi, pagina in enumerate(pdf.pages):
        try:
            try:
                media = [float(x) for x in pagina.MediaBox]
            except Exception:
                media = [0, 0, 595, 842]
            try:
                cb = [float(x) for x in pagina.CropBox]
            except Exception:
                cb = media
            pag_bbox = (min(cb[0], cb[2]), min(cb[1], cb[3]),
                        max(cb[0], cb[2]), max(cb[1], cb[3]))
        except Exception:
            pag_bbox = None
        try:
            instrucoes = list(pikepdf.parse_content_stream(pagina))
        except Exception:
            continue
        ctm = (1, 0, 0, 1, 0, 0)
        pilha_ctm = []
        clip = pag_bbox
        pilha_clip = []
        pts = []           # pontos do path JA em espaco de pagina
        retangular = True
        pendente = None
        ultimo_cm = None
        clip_ranges = []   # (ini, fim) de clips aplicados depois do ultimo cm
        path_ini = None

        def _pt(x, y):
            # le `ctm` do escopo corrente (nao captura o valor na definicao)
            return (ctm[0] * x + ctm[2] * y + ctm[4],
                    ctm[1] * x + ctm[3] * y + ctm[5])

        for idx, (operandos, operador) in enumerate(instrucoes):
            op = str(operador)
            if op == "q":
                pilha_ctm.append(ctm)
                pilha_clip.append(clip)
            elif op == "Q":
                if pilha_ctm:
                    ctm = pilha_ctm.pop()
                if pilha_clip:
                    clip = pilha_clip.pop()
            elif op == "cm":
                try:
                    m = [float(x) for x in operandos]
                    if len(m) == 6:
                        ctm = _mat_mul(ctm, m)
                        ultimo_cm = idx
                        clip_ranges = []   # novo escopo de imagem
                        path_ini = None
                except Exception:
                    pass
            elif op in ("m", "l"):
                try:
                    v = [float(x) for x in operandos]
                    if path_ini is None:
                        path_ini = idx
                    pts.append(_pt(v[0], v[1]))
                except Exception:
                    pass
            elif op == "re":
                try:
                    v = [float(x) for x in operandos]
                    if path_ini is None:
                        path_ini = idx
                    x, y, w, h = v[:4]
                    for (cx, cy) in ((x, y), (x + w, y), (x, y + h), (x + w, y + h)):
                        pts.append(_pt(cx, cy))
                except Exception:
                    pass
            elif op == "c":
                retangular = False
                try:
                    v = [float(x) for x in operandos]
                    for k in (0, 2, 4):
                        pts.append(_pt(v[k], v[k + 1]))
                except Exception:
                    pass
            elif op in ("v", "y"):
                retangular = False
                try:
                    v = [float(x) for x in operandos]
                    for k in range(0, min(4, len(v) - 1), 2):
                        pts.append(_pt(v[k], v[k + 1]))
                except Exception:
                    pass
            elif op in ("W", "W*"):
                if pts:
                    xs = [p[0] for p in pts]
                    ys = [p[1] for p in pts]
                    pendente = ((min(xs), min(ys), max(xs), max(ys)), retangular)
                else:
                    pendente = (None, retangular)
            elif op in ("n", "f", "F", "f*", "S", "s", "B", "B*", "b", "b*"):
                if pendente is not None:
                    if pendente[1]:
                        clip = _intersecta(clip, pendente[0])
                        if ultimo_cm is not None and path_ini is not None:
                            clip_ranges.append((path_ini, idx))
                    else:
                        pendente = (None, False)
                    pendente = None
                pts = []
                retangular = True
                path_ini = None
            elif op == "Do":
                nome = str(operandos[0]) if operandos else ""
                try:
                    xo = pagina.Resources.get("/XObject", {}).get(Name(nome))
                except Exception:
                    xo = None
                if xo is not None and str(xo.get("/Subtype")) == "/Image":
                    a, b, c, d, e, f = ctm
                    # o Do precisa ser o ultimo item do escopo p/ poder remover clip
                    fecha_escopo = (idx + 1 < len(instrucoes)
                                    and str(instrucoes[idx + 1][1]) == "Q")
                    draws.append({
                        "pagina": pi, "objgen": xo.objgen, "ctm": ctm,
                        "cm_idx": ultimo_cm, "clip": clip,
                        "clips_pos_cm": list(clip_ranges) if fecha_escopo else [],
                        "fecha_escopo": fecha_escopo,
                        "do_idx": idx,
                        "w": int(xo.get("/Width", 0)),
                        "h": int(xo.get("/Height", 0)),
                    })
    return draws


def _aplica_clip_imagens(pdf, log):
    """ClipImages: recorta a imagem a area visivel (clip x pagina).

    So age quando o desenho e' unico, sem rotacao e com clip retangular.
    Reescreve o `cm` que precede o `Do` e recorta os pixels.
    """
    draws = _coleta_draws(pdf)
    if not draws:
        return 0
    from collections import Counter
    contagem = Counter(d["objgen"] for d in draws)
    por_pagina = defaultdict(list)
    for d in draws:
        por_pagina[d["pagina"]].append(d)
    total = 0
    for pi, lista in por_pagina.items():
        pagina = pdf.pages[pi]
        try:
            instrucoes = list(pikepdf.parse_content_stream(pagina))
        except Exception:
            continue
        mexeu = False
        for d in lista:
            if contagem[d["objgen"]] != 1:
                continue
            a, b, c, dd, e, f = d["ctm"]
            if abs(b) > 1e-6 or abs(c) > 1e-6 or a <= 0 or dd <= 0:
                continue
            if d["clip"] is None or d["cm_idx"] is None:
                continue
            vis = _intersecta((e, f, e + a, f + dd), d["clip"])
            if vis is None:
                continue
            larg, alt = vis[2] - vis[0], vis[3] - vis[1]
            if larg < 2 or alt < 2:
                continue
            if larg >= a * 0.98 and alt >= dd * 0.98:
                continue  # nada a ganhar
            W, H = d["w"], d["h"]
            # linhas/colunas em pixels (y da imagem cresce de cima p/ baixo)
            px0 = int(round((vis[0] - e) / a * W))
            px1 = int(round((vis[2] - e) / a * W))
            py0 = int(round((1 - (vis[3] - f) / dd) * H))
            py1 = int(round((1 - (vis[1] - f) / dd) * H))
            px0 = max(0, min(W, px0)); px1 = max(0, min(W, px1))
            py0 = max(0, min(H, py0)); py1 = max(0, min(H, py1))
            if px1 - px0 < 2 or py1 - py0 < 2:
                continue
            try:
                xo = pagina.Resources.get("/XObject", {}).get(
                    Name(next(n for n, o in dict(pagina.Resources.get("/XObject", {})).items()
                              if o.objgen == d["objgen"])))
            except Exception:
                xo = None
            if xo is None:
                continue
            try:
                img = pikepdf.PdfImage(xo).as_pil_image()
                img = img.crop((px0, py0, px1, py1))
                buf = io.BytesIO()
                filt_orig = xo.get("/Filter")
                modo = img.mode
                novo_cm = [larg, 0, 0, alt, vis[0], vis[1]]
                # grava a imagem recortada em Flate (a recompressao decide depois)
                if modo in ("1", "L"):
                    dados = _png_idat(img)
                    xo.write(dados)
                    xo[Name("/Filter")] = Name("/FlateDecode")
                    xo[Name("/DecodeParms")] = pikepdf.Dictionary(
                        Predictor=12, Colors=1,
                        BitsPerComponent=(1 if modo == "1" else 8),
                        Columns=img.size[0])
                    xo[Name("/ColorSpace")] = Name("/DeviceGray")
                    xo[Name("/BitsPerComponent")] = (1 if modo == "1" else 8)
                else:
                    im = img if img.mode == "RGB" else img.convert("RGB")
                    dados = _png_idat(im)
                    xo.write(dados)
                    xo[Name("/Filter")] = Name("/FlateDecode")
                    xo[Name("/DecodeParms")] = pikepdf.Dictionary(
                        Predictor=12, Colors=3, BitsPerComponent=8,
                        Columns=im.size[0])
                    xo[Name("/ColorSpace")] = Name("/DeviceRGB")
                    xo[Name("/BitsPerComponent")] = 8
                xo[Name("/Width")] = img.size[0]
                xo[Name("/Height")] = img.size[1]
                _CLIPADOS.add(d["objgen"])
                for k in ("/SMask", "/Mask"):
                    try:
                        del xo[k]
                    except Exception:
                        pass
                ops, nome_op = instrucoes[d["cm_idx"]]
                instrucoes[d["cm_idx"]] = pikepdf.ContentStreamInstruction(
                    pikepdf.Array([float(v) for v in novo_cm]), nome_op)
                # remove clips em espaco de imagem (agora redundantes e
                # prejudiciais: recortariam o topo do novo recorte)
                apagar = set()
                for ini, fim in d.get("clips_pos_cm", []):
                    for k in range(ini, fim + 1):
                        apagar.add(k)
                if apagar:
                    instrucoes = [ins for k, ins in enumerate(instrucoes)
                                  if k not in apagar]
                mexeu = True
                total += 1
            except Exception as ex:
                log(f"    clip imagem: {ex}")
                continue
        if mexeu:
            try:
                novo = pikepdf.unparse_content_stream(instrucoes)
                pagina.Contents = pdf.make_stream(novo)
            except Exception as ex:
                log(f"    clip conteudo pag{pi}: {ex}")
    if total:
        log(f"    imagens recortadas (ClipImages): {total}")
    return total


def _recomprime_flate(pdf, log):
    """Re-deflaciona streams FlateDecode simples (sem preditor) no nivel maximo.

    O qpdf grava no nivel padrao; re-comprimir no 9 economiza ~2% por stream
    de conteudo (medido: 6.356 -> 6.245).
    """
    try:
        import zlib
    except ImportError:
        return
    n = 0
    ganho = 0
    for o in pdf.objects:
        try:
            if not isinstance(o, pikepdf.Stream):
                continue
            if str(o.get("/Filter")) != "/FlateDecode":
                continue
            if "/DecodeParms" in o:
                continue
            if str(o.get("/Subtype")) == "/Image":
                continue
            atual = o.read_raw_bytes()
            dados = o.read_bytes()
            novo = zlib.compress(dados, 9)
            if len(novo) < len(atual):
                o.write(novo)
                o[Name("/Filter")] = Name("/FlateDecode")
                ganho += len(atual) - len(novo)
                n += 1
        except Exception:
            continue
    if n:
        log(f"    streams re-deflacionados: {n} ({ganho:,} B)")


def _fmt_num(v):
    """Numero compacto: ate 6 decimais, sem zeros a direita, sem '-0'."""
    try:
        f = float(v)
    except Exception:
        return str(v)
    if f == int(f) and abs(f) < 1e16:
        s = str(int(f))
    else:
        s = f"{f:.6f}".rstrip("0").rstrip(".")
    if s in ("-0", ""):
        s = "0"
    return s


def _escapa_str(b):
    out = bytearray(b"(")
    for ch in b:
        c = bytes([ch])
        if c == b"(" or c == b")" or c == b"\\":
            out += b"\\" + c
        elif c == b"\n":
            out += b"\\n"
        elif c == b"\r":
            out += b"\\r"
        elif c == b"\t":
            out += b"\\t"
        elif ch < 32 or ch > 126:
            out += f"\\{ch:03o}".encode()
        else:
            out += c
    out += b")"
    return bytes(out)


_DELIM = set(b"()<>[]{}/%")
_ESPACO = frozenset(list(range(0, 33)) + [127])


def _regular(b):
    if not b:
        return False
    return b[0] not in _DELIM and b[0] not in _ESPACO


def _junta(partes):
    """Concatena tokens PDF inserindo espaco so quando necessario."""
    out = bytearray()
    for p in partes:
        if not p:
            continue
        if out and _regular(out[-1:]) and _regular(p[:1]):
            out += b" "
        out += p
    return bytes(out)


def _serializa_obj(o):
    """Serializa um operando de forma compacta."""
    try:
        if isinstance(o, pikepdf.Name):
            return str(o).encode("latin-1", "replace")
        if isinstance(o, pikepdf.Array):
            return b"[" + _junta([_serializa_obj(x) for x in o]) + b"]"
        if isinstance(o, pikepdf.Dictionary):
            partes = [b"<<"]
            for k in o.keys():
                partes.append(_serializa_obj(pikepdf.Name(str(k))))
                partes.append(_serializa_obj(o[k]))
            partes.append(b">>")
            return _junta(partes)
        if isinstance(o, bool):
            return b"true" if o else b"false"
        if o is None:
            return b"null"
        if isinstance(o, (int, float)):
            return _fmt_num(o).encode()
        if isinstance(o, pikepdf.String) or isinstance(o, (bytes, bytearray)):
            return _escapa_str(bytes(o))
        s = str(o)
        if s.startswith("/"):
            return s.encode("latin-1", "replace")
        # Decimal vindo do parser: preserva a grafia original
        tipo = type(o).__name__
        if tipo == "Decimal":
            return s.encode()
        try:
            float(s)
            return _fmt_num(s).encode()
        except Exception:
            return _escapa_str(s.encode("latin-1", "replace"))
    except Exception:
        return b"null"


def _serializa_instrucoes(instrucoes):
    """Serializa instrucoes de conteudo de forma compacta (1 instrucao/linha)."""
    linhas = []
    for operandos, operador in instrucoes:
        partes = [_serializa_obj(x) for x in operandos]
        partes.append(str(operador).encode("latin-1", "replace"))
        linhas.append(b" ".join(partes))
    return b"\n".join(linhas)


def _normaliza_conteudo(pdf, log):
    """Compacta content streams como o motor original.

    - separadores simples e '\\n' (o Word grava '\\r\\n' e espacos duplos)
    - '1 0 0 1 tx ty Tm' -> 'tx ty Td' quando a matriz de linha e' identidade
      (economia de ~7 bytes por bloco de texto; ver docs/METODO.md)
    Pula paginas com imagens inline (BI/ID/EI), onde o reparse e' arriscado.
    """
    n_pag = 0
    ganho = 0

    def normaliza(instrucoes):
        saida = []
        identidade = True
        # Estado que o operador so' re-escreve: re-setar o MESMO valor e' no-op
        # e sai do stream (o motor faz isso: medido em processo.pdf, `Tf` 6.451
        # deles contra 14.114 nossos, `M` 35 x 3.389, `j` 1.923 x 3.978).
        # `q` empilha uma copia e `Q` restaura — senao o corte fica errado.
        PADRAO = {"Tc": 0.0, "Tw": 0.0, "Tz": 100.0, "Ts": 0.0, "Tr": 0.0,
                  "w": 1.0, "J": 0.0, "j": 0.0, "M": 10.0, "Tf": None,
                  "d": None}
        estado = dict(PADRAO)
        pilha_estado = []
        cur = None          # ponto corrente do path (x, y) para c -> v/y
        ini = None          # inicio do subpath (para `h`)
        for operandos, operador in instrucoes:
            op = str(operador)
            if op == "q":
                pilha_estado.append(dict(estado))
            elif op == "Q":
                if pilha_estado:
                    estado = pilha_estado.pop()
            elif op == "gs":
                # ExtGState pode mexer em qualquer coisa: invalidar o rastreio
                for k in estado:
                    estado[k] = None

            # --- cortes de estado redundante ---
            if op in estado:
                chave = None
                try:
                    if op in ("Tf",) and len(operandos) == 2:
                        chave = (str(operandos[0]), float(operandos[1]))
                    elif op == "d" and len(operandos) == 2:
                        chave = (tuple(float(x) for x in operandos[0]),
                                 float(operandos[1]))
                    elif len(operandos) == 1:
                        chave = float(operandos[0])
                except Exception:
                    chave = None
                if chave is not None:
                    # None = desconhecido (comeco do stream ou apos `gs`):
                    # registra e emite; so corta quando o valor REPETE.
                    if estado[op] is not None and chave == estado[op]:
                        continue
                    estado[op] = chave

            # --- c -> v / y quando os pontos coincidem ---
            if op in ("m", "l") and len(operandos) == 2:
                try:
                    ini = cur = (float(operandos[0]), float(operandos[1]))
                except Exception:
                    cur = ini = None
            elif op in ("v", "y") and len(operandos) == 4:
                try:
                    cur = (float(operandos[2]), float(operandos[3]))
                except Exception:
                    cur = None
            elif op == "c" and len(operandos) == 6:
                try:
                    vals = [float(x) for x in operandos]
                except Exception:
                    vals = None
                if vals is not None and cur is not None:
                    x1, y1, x2, y2, x3, y3 = vals
                    if (x1, y1) == cur:
                        saida.append(pikepdf.ContentStreamInstruction(
                            pikepdf.Array([operandos[2], operandos[3],
                                           operandos[4], operandos[5]]),
                            pikepdf.Operator("v")))
                        cur = (x3, y3)
                        continue
                    if (x2, y2) == (x3, y3):
                        saida.append(pikepdf.ContentStreamInstruction(
                            pikepdf.Array([operandos[0], operandos[1],
                                           operandos[4], operandos[5]]),
                            pikepdf.Operator("y")))
                        cur = (x3, y3)
                        continue
                if vals is not None:
                    cur = (vals[4], vals[5])
            elif op == "h":
                cur = ini
            elif op == "re" and len(operandos) == 4:
                try:
                    cur = ini = (float(operandos[0]), float(operandos[1]))
                except Exception:
                    cur = ini = None
            elif op in ("f", "f*", "S", "s", "B", "B*", "n"):
                cur = ini = None      # path terminou

            if op == "BT":
                identidade = True
            elif op in ("Td", "TD", "T*", "'", '"'):
                identidade = False
            elif op == "Tm":
                vals = None
                try:
                    vals = [float(x) for x in operandos]
                except Exception:
                    vals = None
                if (identidade and vals and len(vals) == 6
                        and vals[0] == 1 and vals[1] == 0
                        and vals[2] == 0 and vals[3] == 1):
                    novo = pikepdf.Array([
                        pikepdf.Object.parse(_fmt_num(vals[4]).encode()),
                        pikepdf.Object.parse(_fmt_num(vals[5]).encode())])
                    saida.append(pikepdf.ContentStreamInstruction(
                        novo, pikepdf.Operator("Td")))
                    identidade = False
                    continue
                identidade = False
            saida.append(pikepdf.ContentStreamInstruction(operandos, operador))
        return saida

    for pi, pagina in enumerate(pdf.pages):
        try:
            instrucoes = list(pikepdf.parse_content_stream(pagina))
        except Exception:
            continue
        if any(str(o) in ("BI", "ID", "EI") for _op, o in instrucoes):
            continue  # imagem inline: nao mexer
        try:
            antes = 0
            try:
                c = pagina.get("/Contents")
                antes = (len(c.read_raw_bytes()) if not isinstance(c, pikepdf.Array)
                         else sum(len(x.read_raw_bytes()) for x in c))
            except Exception:
                antes = 0
            novo = _serializa_instrucoes(normaliza(instrucoes))
            comprimido = zlib.compress(novo, 9)
            # so troca se ficar menor que o stream atual
            try:
                atual_raw = (c.read_raw_bytes() if not isinstance(c, pikepdf.Array)
                             else b"".join(x.read_raw_bytes() for x in c))
            except Exception:
                atual_raw = None
            if atual_raw is not None and len(comprimido) >= len(atual_raw):
                continue
            stream = pdf.make_stream(comprimido)
            stream[Name("/Filter")] = Name("/FlateDecode")
            pagina.Contents = stream
            ganho += max(0, antes - len(stream.read_raw_bytes()))
            n_pag += 1
        except Exception as ex:
            log(f"    normaliza conteudo pag{pi}: {ex}")
    if n_pag:
        log(f"    content normalizado: {n_pag} pagina(s), {ganho:,} B")


def _unifica_conteudo(pdf, log):
    """Junta o /Contents de cada pagina num unico stream.

    O motor reescreve o conteudo e grava 1 stream por pagina (processo.pdf:
    376 no iLovePDF, 501 nossos e 1.380 no original). Cada stream extra custa
    o proprio dicionario e um flush do deflate. Nao reparseia nada: so
    concatena os bytes ja decodificados (os streams de uma pagina sao
    concatenados na mesma ordem pelo leitor).
    """
    n = 0
    ganho = 0
    for pagina in pdf.pages:
        try:
            cont = pagina.obj.get("/Contents")
        except Exception:
            continue
        if cont is None or _tipo_obj(cont) != "array" or len(cont) < 2:
            continue
        try:
            partes = []
            antes = 0
            for s in cont:
                partes.append(s.read_bytes())
                antes += len(s.read_raw_bytes())
        except Exception:
            continue
        if not partes:
            continue
        dados = b"\n".join(partes)
        try:
            novo = pdf.make_stream(b"")
            novo.write(zlib.compress(dados, 9), filter=Name("/FlateDecode"),
                       type_check=False)
            depois = len(novo.read_raw_bytes())
            if depois >= antes:
                continue
            pagina.obj["/Contents"] = novo
            n += 1
            ganho += antes - depois
        except Exception:
            continue
    if n:
        log("    conteudo unificado: %d pagina(s), %d bytes a menos" % (n, ganho))
    return ganho


def _remove_marcadores_mc(pdf, log):
    """Remove marcadores de conteudo (BMC/BDC/EMC) sem /OC.

    Depois de remover /StructTreeRoot eles nao servem para nada e custam ~12%
    do content stream. Marcadores com /OC (camadas) sao preservados.
    """
    n_pag = 0
    ganho = 0
    for pi, pagina in enumerate(pdf.pages):
        try:
            instrucoes = list(pikepdf.parse_content_stream(pagina))
        except Exception:
            continue
        novo = []
        prof_mc = 0
        removeu = False
        tem_inline = False
        for operandos, operador in instrucoes:
            op = str(operador)
            if op == "INLINE IMAGE" or any(
                    isinstance(x, pikepdf.PdfInlineImage) for x in operandos):
                # `unparse_content_stream` nao re-serializa imagem inline
                # ("don't know how to encode value <PdfInlineImage>"): reescrever
                # a pagina inteira quebraria. Pula a pagina (processo.pdf pg337).
                tem_inline = True
                break
            if op in ("BDC", "BMC"):
                txt = " ".join(str(x) for x in operandos)
                if "/OC" in txt:
                    novo.append(pikepdf.ContentStreamInstruction(operandos, operador))
                else:
                    prof_mc += 1
                    removeu = True
                continue
            if op == "EMC" and prof_mc > 0:
                prof_mc -= 1
                continue
            novo.append(pikepdf.ContentStreamInstruction(operandos, operador))
        if tem_inline or not removeu:
            continue
        try:
            try:
                antes = (len(pagina.Contents.read_raw_bytes())
                         if not isinstance(pagina.Contents, pikepdf.Array)
                         else sum(len(x.read_raw_bytes()) for x in pagina.Contents))
            except Exception:
                antes = 0
            dump = pikepdf.unparse_content_stream(novo)
            novo_stream = pdf.make_stream(zlib.compress(dump, 9))
            novo_stream[Name("/Filter")] = Name("/FlateDecode")
            pagina.Contents = novo_stream
            depois = len(novo_stream.read_raw_bytes())
            ganho += max(0, antes - depois)
            n_pag += 1
        except Exception as ex:
            log(f"    marcadores pag{pi}: {ex}")
    if n_pag:
        log(f"    marcadores MCID removidos: {n_pag} pagina(s), {ganho:,} B")


def _pior_diferenca_render(entrada, saida, dpi=80):
    """Pior fracao de pixels diferentes entre entrada e saida (por pagina)."""
    try:
        import fitz
        import numpy as np
        from PIL import Image
    except ImportError:
        return None
    try:
        d1 = fitz.open(entrada)
        d2 = fitz.open(saida)
    except Exception:
        return None
    pior = 0.0
    try:
        if len(d1) != len(d2):
            return 1.0
        for i in range(len(d1)):
            a = d1[i].get_pixmap(dpi=dpi)
            b = d2[i].get_pixmap(dpi=dpi)
            ia = np.asarray(Image.frombytes("RGB", (a.width, a.height), a.samples).convert("L"), float)
            ib = np.asarray(Image.frombytes("RGB", (b.width, b.height), b.samples).convert("L"), float)
            if ia.shape != ib.shape:
                return 1.0
            pior = max(pior, float((np.abs(ia - ib) > 40).mean()))
    except Exception:
        return None
    finally:
        try:
            d1.close(); d2.close()
        except Exception:
            pass
    return pior


#: Verificacao de render (rede de seguranca NOSSA, o motor 3-Heights nao faz).
#: Desligada por padrao para o algoritmo ficar identico ao do iLovePDF;
#: ligue com `--verificar` ou PDFAGENT_VERIFICAR=1.
VERIFICAR = bool(os.environ.get("PDFAGENT_VERIFICAR"))


def comprimir(entrada, saida, nivel="recommended", log=print, _guard=None,
              _sem_risco=False):
    """Comprime um PDF no nível dado. Retorna dict com estatisticas."""
    if nivel not in LEVELS:
        raise ValueError(f"nivel invalido: {nivel}")
    spec = LEVELS[nivel]
    log(f"[1] abrindo {os.path.basename(entrada)} (nivel {spec['rotulo']})")
    pdf = pikepdf.open(entrada)
    try:
        if pdf.is_encrypted:
            raise ValueError("PDF criptografado nao suportado")
        tam_antes = os.path.getsize(entrada)
        # guarda o XMP original antes de qualquer strip (vamos preserva-lo)
        xmp_original = None
        try:
            _m = pdf.Root.get("/Metadata")
            if _m is not None:
                xmp_original = _m.read_bytes()
        except Exception:
            pass

        log("[2] mapeando imagens e DPI efetivo")
        _CLIPADOS.clear()
        if spec.get("clip", False) and not _sem_risco:
            _aplica_clip_imagens(pdf, log)
        usos = _tamanhos_na_pagina(pdf)
        total = trocadas = 0
        for pagina in pdf.pages:
            try:
                imagens = dict(pagina.get_images())
            except Exception:
                continue
            for _nome, obj in imagens.items():
                try:
                    if obj.objgen is None:
                        continue
                except Exception:
                    continue
                total += 1
                try:
                    trocou, como, _dpi = _recomprime_imagem(
                        pdf, obj, spec, usos, log)
                    trocadas += bool(trocou)
                except Exception as ex:
                    log(f"    imagem ignorada: {ex}")
        log(f"[3] imagens: {trocadas}/{total} recomprimidas")
        try:
            _recomprime_mascaras(pdf, spec, usos, log)
        except Exception as ex:
            log("    mascaras: %s" % ex)

        log("[4] strip/otimizacoes de documento")
        _aplica_strip(pdf, spec["strip"], log)
        if "structtree" in spec["strip"]:
            _remove_marcadores_mc(pdf, log)
        _normaliza_conteudo(pdf, log)
        _unifica_conteudo(pdf, log)
        if spec.get("remove_fontes_padrao"):
            _substitui_fontes_padrao(pdf, log)
        if spec.get("subset_fontes", True):
            feitos = 0
            try:
                feitos = _merge_subset_fontes(pdf, log)
            except Exception as ex:
                log("    merge de fontes falhou: %s" % ex)
                feitos = 0
            if not feitos:
                # caminho antigo: subset por dicionario de fonte
                _subset_fontes(pdf, log)
                _subset_fontes_cid(pdf, log)
            if not _sem_risco and _TENTA_CFF:
                _subset_fontes_cff(pdf, log)
        # RemoveRedundantObjects/MergeEmbeddedFonts do motor: consolida fontes,
        # imagens, charprocs Type3 e programas de fonte identicos e depois
        # reaponta as referencias no documento INTEIRO (nao so em /Resources).
        mapa_dup = {}
        for _consolida in (_consolida_fontes, _consolida_imagens,
                           _consolida_programas_fonte, _consolida_charprocs):
            try:
                mapa_dup.update(_consolida(pdf, log))
            except Exception as ex:
                log("    consolidacao %s falhou: %s" % (_consolida.__name__, ex))
        _reaponta_tudo(pdf, mapa_dup, log)
        _carimba(pdf, log, xmp_original)
        if spec.get("otimiza_recursos"):
            try:
                pdf.remove_unreferenced_resources()
                log("    recursos nao referenciados removidos")
            except Exception as ex:
                log(f"    remove_unreferenced: {ex}")

        log("[5] salvando")
        _recomprime_flate_max(pdf, log)
        pdf.save(saida, object_stream_mode=pikepdf.ObjectStreamMode.generate,
                 recompress_flate=False)
    finally:
        pdf.close()
    tam_depois = os.path.getsize(saida)
    razao = 100.0 * (1.0 - tam_depois / tam_antes) if tam_antes else 0.0
    # GARANTIA: nunca entregar arquivo maior que o original. Em PDFs muito
    # pequenos o custo fixo (XMP + docinfo + tabela) supera o ganho; nesse
    # caso o original e' mantido byte a byte.
    if tam_depois >= tam_antes and tam_antes:
        try:
            import shutil
            shutil.copyfile(entrada, saida)
            tam_depois = os.path.getsize(saida)
            razao = 0.0
            log("[!] saida nao ficou menor; mantido o original (0%)")
        except Exception as ex:
            log(f"[!] nao foi possivel reverter para o original: {ex}")
    # Rede de seguranca: se o render mudou demais (clip errado, fonte quebrada),
    # refaz sem ClipImages. Nunca entregar arquivo visualmente divergente.
    if _guard is None:
        _guard = VERIFICAR
    if _guard:
        pior = _pior_diferenca_render(entrada, saida, dpi=110)
        limite = 0.04 if nivel == "extreme" else 0.02
        if pior is not None and pior > limite:
            if not _sem_risco:
                log(f"[!] render divergiu ({pior:.2%}); refazendo sem etapas arriscadas")
                return comprimir(entrada, saida, nivel, log=log, _guard=True,
                                 _sem_risco=True)
            log(f"[!] ATENCAO: render divergiu ({pior:.2%}) mesmo sem etapas arriscadas")
        if pior is not None:
            log(f"[7] verificacao de render: pior pagina {pior:.3%}")
    log(f"[6] {tam_antes:,} -> {tam_depois:,} bytes (-{razao:.1f}%)")
    return {"antes": tam_antes, "depois": tam_depois, "razao": razao,
            "nivel": nivel}


def _recomprime_flate_max(pdf, log):
    """Recomprime todo stream /FlateDecode em nivel 9 (o qpdf usa nivel 6).

    O `Object.write` do pikepdf, sem `filter=`, trata os bytes como NAO
    codificados e aplica o /Filter de novo — passar zlib aqui sem o argumento
    grava lixo (content stream ilegivel). Com `filter=/FlateDecode` os bytes
    entram como estao. Depois disso o save tem de usar recompress_flate=False,
    senao o qpdf desfaz o nivel 9.
    """
    n = 0
    ganho = 0
    for obj in pdf.objects:
        try:
            if not isinstance(obj, pikepdf.Stream):
                continue
            if str(obj.get("/Filter", "")) != "/FlateDecode":
                continue
            if obj.get("/DecodeParms") is not None:
                continue      # preditor: read_bytes() ja desfaz o preditor
            cru = obj.read_raw_bytes()
            if len(cru) < 64:
                continue
            dados = obj.read_bytes()
        except Exception:
            continue
        try:
            novo = zlib.compress(dados, 9)
        except Exception:
            continue
        if len(novo) + 2 >= len(cru):
            continue
        try:
            obj.write(novo, filter=Name("/FlateDecode"), type_check=False)
            n += 1
            ganho += len(cru) - len(novo)
        except Exception:
            continue
    if n:
        log("    flate nivel 9: %d stream(s), %d bytes a menos" % (n, ganho))
    return ganho


def _nome_saida(entrada, saida, nivel):
    if saida:
        return saida
    base, _ext = os.path.splitext(entrada)
    cand = f"{base}-compressed.pdf"
    i = 2
    while os.path.exists(cand):
        cand = f"{base}-compressed-{i}.pdf"
        i += 1
    return cand


def _nome_livre(caminho):
    """Devolve <nome>_old.pdf, ou _old_2, _old_3... se ja existir."""
    raiz, ext = os.path.splitext(caminho)
    if not os.path.exists(caminho):
        return caminho
    n = 2
    while os.path.exists("%s_%d%s" % (raiz, n, ext)):
        n += 1
    return "%s_%d%s" % (raiz, n, ext)


def _aviso(titulo, msg, erro=False):
    """Caixa de dialogo — o .exe e --windowed, entao print nao aparece."""
    try:
        import tkinter as tk
        from tkinter import messagebox
        raiz = tk.Tk()
        raiz.withdraw()
        (messagebox.showerror if erro else messagebox.showinfo)(titulo, msg)
        raiz.destroy()
    except Exception:
        try:
            print(msg)
        except Exception:
            pass


def _in_place(entradas, args):
    """Comprime no lugar: original vira <nome>_old.pdf, saida assume o nome."""
    linhas = []
    falhas = 0
    for entrada in entradas:
        pasta, arquivo = os.path.split(entrada)
        base = os.path.splitext(arquivo)[0]
        tmp = os.path.join(pasta, ".pdfagent_%s.tmp.pdf" % base)
        try:
            r = comprimir(entrada, tmp, args.nivel)
            if r["depois"] >= r["antes"]:
                raise RuntimeError("nao ficou menor (%d -> %d bytes)"
                                   % (r["antes"], r["depois"]))
            antigo = _nome_livre(os.path.join(pasta, base + "_old.pdf"))
            os.replace(entrada, antigo)
            os.replace(tmp, entrada)
            linhas.append("%s: %d -> %d bytes (-%.1f%%) | original: %s"
                          % (arquivo, r["antes"], r["depois"], r["razao"],
                             os.path.basename(antigo)))
        except Exception as ex:
            falhas += 1
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass
            linhas.append("%s: FALHOU (%s)" % (arquivo, ex))
    msg = "\n".join(linhas)
    if args.avisar:
        _aviso("PDFagent", msg, erro=bool(falhas))
    else:
        for linha in linhas:
            print(linha)
    if falhas:
        sys.exit(1)


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="PDFagent",
        description="Comprime PDFs nos 3 niveis do iLovePDF "
                    "(Extreme/Recommended/Low) — replica open-source.")
    ap.add_argument("-V", "--version", action="version",
                    version="PDFagent %s" % VERSAO)
    ap.add_argument("entrada", help="PDF de entrada ou pasta com PDFs")
    ap.add_argument("-n", "--nivel", default="recommended",
                    choices=["extreme", "recommended", "low"],
                    help="nivel de compressao (padrao: recommended)")
    ap.add_argument("-o", "--saida", default=None,
                    help="arquivo de saida (padrao: <nome>-compressed.pdf)")
    ap.add_argument("--saida-dir", default=None,
                    help="pasta de saida (modo lote)")
    ap.add_argument("--in-place", action="store_true",
                    help="comprime no lugar: original vira <nome>_old.pdf e a "
                         "saida assume o nome original (usado no menu de contexto)")
    ap.add_argument("--avisar", action="store_true",
                    help="mostra uma caixa de dialogo com o resultado (menu de contexto)")
    ap.add_argument("--verificar", action="store_true",
                    help="liga a verificacao de render (rede de seguranca nossa; "
                         "o motor do iLovePDF nao faz isso e custa minutos em PDF grande)")
    args = ap.parse_args(argv)
    if args.verificar:
        global VERIFICAR
        VERIFICAR = True

    entradas = []
    if os.path.isdir(args.entrada):
        entradas = [os.path.join(args.entrada, f) for f in sorted(os.listdir(args.entrada))
                    if f.lower().endswith(".pdf")]
    else:
        entradas = [args.entrada]
    if not entradas:
        sys.exit("nenhum PDF encontrado")
    if args.in_place:
        return _in_place(entradas, args)
    falhas = 0
    for entrada in entradas:
        if args.saida and len(entradas) == 1:
            saida = args.saida
        elif args.saida_dir:
            os.makedirs(args.saida_dir, exist_ok=True)
            saida = os.path.join(args.saida_dir,
                                 os.path.basename(_nome_saida(entrada, None, args.nivel)))
        else:
            saida = _nome_saida(entrada, None, args.nivel)
        try:
            r = comprimir(entrada, saida, args.nivel)
            print(f"OK: {os.path.basename(saida)} "
                  f"{r['antes']:,} -> {r['depois']:,} bytes (-{r['razao']:.1f}%)")
        except Exception as ex:
            falhas += 1
            print(f"FALHA {os.path.basename(entrada)}: {ex}")
    # exit code honesto: lote com falha precisa falhar para quem automatiza
    if falhas:
        sys.exit(1)


if __name__ == "__main__":
    main()
