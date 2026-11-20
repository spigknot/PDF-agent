"""split — divide um PDF em partes que respeitam um limite de tamanho.

Nunca corta página: cada parte contém páginas inteiras, na ordem original.
Por padrão comprime antes (pode eliminar a necessidade de dividir);
`--sem-comprimir` desliga.

Lógica (a mais barata que encontrei):
 1. (opcional) comprime o arquivo inteiro, uma passada;
 2. UMA passada em memória somando os objetos de cada página (objetos
    compartilhados contam só na primeira parte que os usa) — sem escrever nada;
 3. monta as partes por essa estimativa e serializa cada uma em BytesIO;
    se passar do limite, devolve páginas do fim (raro) e re-serializa;
 4. grava exatamente os bytes já serializados (nenhuma gravação extra).
"""
import argparse
import io
import os
import sys

# rodar `python commands/split.py` direto poe commands/ no sys.path; a raiz
# do repo (onde vivem compress.py e progresso.py) precisa estar lá também
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RAIZ not in sys.path:
    sys.path.insert(0, _RAIZ)

#: limite usado pelo menu de contexto (pode ser trocado por PDFAGENT_LIMITE)
LIMITE_PADRAO_MB = 10.0


def _como_bytes(texto):
    """'10M' | '1.5 mb' | '500k' | '1048576' -> bytes."""
    t = str(texto).strip().lower().replace(" ", "")
    m = None
    import re
    m = re.match(r"^([0-9]+(?:\.[0-9]+)?)([kmg]?)b?$", t)
    if not m:
        raise argparse.ArgumentTypeError("limite inválido: %r (use 500k, 1M, 10MB…)" % texto)
    valor = float(m.group(1))
    mult = {"": 1, "k": 1024, "m": 1024 ** 2, "g": 1024 ** 3}[m.group(2)]
    return int(valor * mult)


def _limite_padrao():
    bruto = os.environ.get("PDFAGENT_LIMITE")
    if bruto:
        try:
            return _como_bytes(bruto)
        except Exception:
            pass
    return int(LIMITE_PADRAO_MB * 1024 * 1024)


def _monta_parte(pdf, ini, fim):
    """Serializa as páginas [ini, fim) em RAM (lossless) e devolve os bytes."""
    import pikepdf

    buf = io.BytesIO()
    with pikepdf.Pdf.new() as destino:
        try:
            info = pdf.docinfo
            if info is not None:
                for k, v in info.items():
                    try:
                        destino.docinfo[k] = v
                    except Exception:
                        pass
        except Exception:
            pass
        destino.pages.extend(pdf.pages[ini:fim])
        destino.save(
            buf,
            compress_streams=False,
            recompress_flate=False,
            object_stream_mode=pikepdf.ObjectStreamMode.preserve,
        )
    return buf.getvalue()


def _partes(pdf, limite, log=None):
    """Lista de (ini, fim, bytes) via Busca Exponencial + Busca Binária em RAM."""
    n = len(pdf.pages)
    partes = []
    ini = 0
    while ini < n:
        # 1. Busca Exponencial (1, 2, 4, 8...) para delimitar a janela
        salto = 1
        melhor_fim = ini + 1
        melhor_dados = None
        while (ini + salto) <= n:
            dados = _monta_parte(pdf, ini, ini + salto)
            if len(dados) <= limite:
                melhor_fim = ini + salto
                melhor_dados = dados
                salto *= 2
            else:
                if salto == 1:
                    melhor_dados = dados
                break

        # 2. Busca Binária na janela [melhor_fim + 1, min(n, ini + salto - 1)]
        baixo = melhor_fim + 1
        alto = min(n, ini + salto - 1)
        while baixo <= alto:
            meio = (baixo + alto) // 2
            dados = _monta_parte(pdf, ini, meio)
            if len(dados) <= limite:
                melhor_fim = meio
                melhor_dados = dados
                baixo = meio + 1
            else:
                alto = meio - 1

        if melhor_dados is None:
            melhor_dados = _monta_parte(pdf, ini, melhor_fim)

        partes.append((ini, melhor_fim, melhor_dados))
        ini = melhor_fim
        if log is not None:
            log("dividindo: %d/%d páginas…" % (ini, n))
    return partes


def dividir(entrada, limite, comprimir=True, nivel="recommended",
            destino=None, log=print):
    """Divide `entrada` em partes de no máximo `limite` bytes.

    Devolve dict: partes (lista de caminhos), comprimido (caminho|None),
    precisa_dividir (bool), total_antes/ total_depois.
    """
    import compress
    import pikepdf

    origem = entrada
    comprimido = None
    if comprimir:
        tmp = os.path.join(os.path.dirname(entrada) or ".",
                           ".pdfagent_split_%s.pdf" % os.path.splitext(
                               os.path.basename(entrada))[0])
        try:
            r = compress.comprimir(entrada, tmp, nivel, log=log)
            if r["depois"] < r["antes"]:
                origem, comprimido = tmp, tmp
                log("  comprimido: %d -> %d bytes (-%.1f%%)"
                    % (r["antes"], r["depois"], r["razao"]))
            else:
                os.remove(tmp)
                log("  compressão não reduziu; usando o original")
        except Exception as ex:
            log("  compressão falhou (%s); usando o original" % ex)
            try:
                os.path.exists(tmp) and os.remove(tmp)
            except Exception:
                pass

    base = os.path.splitext(os.path.basename(entrada))[0]
    # as partes vao SEMPRE para uma subpasta com o nome do arquivo de entrada
    # (sem extensao), dentro da pasta dele — ou dentro de `destino`, se o
    # chamador passou um destino explicito
    raiz = destino or os.path.dirname(origem) or "."
    pasta = os.path.join(raiz, base)
    os.makedirs(pasta, exist_ok=True)

    total_origem = os.path.getsize(origem)
    if total_origem <= limite:
        log("  cabe no limite (%d B <= %d B): não dividido" % (total_origem, limite))
        caminho = None
        if comprimido and os.path.abspath(origem) != os.path.abspath(entrada):
            caminho = os.path.join(pasta, base + "_comprimido.pdf")
            os.replace(origem, caminho)      # pdf ainda não foi aberto: sem lock
            comprimido = caminho
        return {"partes": [caminho] if caminho else [], "comprimido": comprimido,
                "precisa_dividir": False, "paginas": None,
                "total_antes": os.path.getsize(entrada),
                "total_depois": os.path.getsize(caminho) if caminho else total_origem}

    with pikepdf.open(origem) as pdf:
        total = len(pdf.pages)
        partes = _partes(pdf, limite, log=log)

    caminhos = []
    for i, (ini, fim, dados) in enumerate(partes, 1):
        nome = "%s_parte%d.pdf" % (base, i)
        caminho = os.path.join(pasta, nome)
        with open(caminho, "wb") as f:
            f.write(dados)
        caminhos.append(caminho)
        log("  %-32s páginas %d-%d  %.2f MB"
            % (nome, ini + 1, fim, len(dados) / 1048576))
        if fim - ini == 1 and len(dados) > limite:
            log("    aviso: a página %d sozinha já passa do limite" % (ini + 1))

    if comprimido and os.path.exists(comprimido):
        try:
            os.remove(comprimido)
        except Exception:
            pass
    return {"partes": caminhos, "comprimido": comprimido,
            "precisa_dividir": True, "paginas": total,
            "total_antes": os.path.getsize(entrada),
            "total_depois": sum(os.path.getsize(c) for c in caminhos)}


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="PDFagent split",
        description="Divide um PDF em partes inteiras (por página) respeitando "
                    "um limite de tamanho. Comprime antes por padrão.")
    ap.add_argument("entrada", help="PDF de entrada")
    ap.add_argument("-l", "--limite", type=_como_bytes, default=None,
                    help="limite por parte (1M, 500k, 10MB…); padrão %g MB"
                         % LIMITE_PADRAO_MB)
    ap.add_argument("-n", "--nivel", default="recommended",
                    choices=["extreme", "recommended", "low"],
                    help="nível da compressão prévia (padrão: recommended)")
    ap.add_argument("--sem-comprimir", action="store_true",
                    help="não comprime antes de dividir")
    ap.add_argument("-o", "--saida-dir", default=None, help="pasta de saída")
    ap.add_argument("--avisar", action="store_true",
                    help="mostra caixa de diálogo com o resultado (menu de contexto)")
    args = ap.parse_args(argv)

    limite = args.limite or _limite_padrao()
    if not os.path.exists(args.entrada):
        print("arquivo não encontrado: %s" % args.entrada, file=sys.stderr)
        return 1

    def trabalho(log, escolha):
        """`escolha` = {"limite_mb", "comprimir", "nivel"} (vem da janela)."""
        limite = int(round(escolha["limite_mb"] * 1048576))
        comprimir = bool(escolha["comprimir"])
        nivel = escolha["nivel"]
        log("dividindo %s (limite %.1f MB, compressão %s)"
            % (os.path.basename(args.entrada), escolha["limite_mb"],
               nivel if comprimir else "desligada"))
        try:
            r = dividir(args.entrada, limite,
                        comprimir=comprimir, nivel=nivel,
                        destino=args.saida_dir, log=log)
        except Exception as ex:
            return False, "falha ao dividir: %s" % ex
        if r["precisa_dividir"]:
            msg = "%d arquivo(s) gerado(s) com limite de %.1f MB" % (
                len(r["partes"]), escolha["limite_mb"])
        elif r["partes"]:
            msg = ("não precisou dividir; comprimido salvo em %s"
                   % os.path.basename(r["partes"][0]))
        else:
            msg = "não precisou dividir (já cabe em %.1f MB)" % escolha["limite_mb"]
        partes = "\n".join("• " + os.path.basename(c) for c in r["partes"])
        return True, msg + ("\n\n" + partes if partes else "")

    if args.avisar:
        import progresso

        try:
            sub = "%s  ·  %.1f MB" % (os.path.basename(args.entrada),
                                      os.path.getsize(args.entrada) / 1048576.0)
        except OSError:
            sub = os.path.basename(args.entrada)
        # a janela PERGUNTA: limite (1 casa, ja em 1,7 MB) + caixa "Comprimir"
        # DESMARCADA; o mesmo dialogo vira a tela de progresso no Dividir
        return progresso.executar(
            trabalho, subtitulo=sub,
            pedir_limite=(args.limite / 1048576.0 if args.limite
                          else progresso.LIMITE_PADRAO_MB),
            comprimir_inicial=False,
            nivel_inicial=args.nivel)
    ok, msg = trabalho(lambda m: None,
                       {"limite_mb": limite / 1048576.0,
                        "comprimir": not args.sem_comprimir,
                        "nivel": args.nivel})
    (print if ok else lambda m: print(m, file=sys.stderr))(msg)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
