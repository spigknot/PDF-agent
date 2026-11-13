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

#: limite usado pelo menu de contexto (pode ser trocado por PDFAGENT_LIMITE)
LIMITE_PADRAO_MB = 10.0

#: chaves que levariam a outras páginas / ao topo da árvore
_PULAR = {"/Parent", "/P", "/Prev", "/Next", "/First", "/Last"}


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


def _pesos_por_pagina(pdf):
    """Bytes (streams crus + dicts) que cada página traz de novo."""
    import pikepdf

    vistos = set()
    pesos = []
    for pagina in pdf.pages:
        total = 0
        pilha = [pagina.obj]
        while pilha:
            obj = pilha.pop()
            try:
                og = obj.objgen
            except Exception:
                og = None
            if og:
                if og in vistos:
                    continue
                vistos.add(og)
            if isinstance(obj, pikepdf.Stream):
                try:
                    total += len(obj.read_raw_bytes())
                except Exception:
                    pass
            if isinstance(obj, pikepdf.Dictionary):
                try:
                    total += len(str(obj)) // 2
                except Exception:
                    pass
                for chave in obj.keys():
                    if str(chave) in _PULAR:
                        continue
                    try:
                        pilha.append(obj[chave])
                    except Exception:
                        pass
            elif isinstance(obj, pikepdf.Array):
                for item in obj:
                    pilha.append(item)
        pesos.append(total)
    return pesos


def _monta_parte(pdf, ini, fim):
    """Serializa as páginas [ini, fim) num PDF novo e devolve os bytes."""
    import pikepdf

    destino = pikepdf.Pdf.new()
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
    for pagina in pdf.pages[ini:fim]:
        copiada = destino.copy_foreign(pagina.obj)
        destino.pages.append(pikepdf.Page(copiada))
    buf = io.BytesIO()
    destino.save(buf)
    destino.close()
    return buf.getvalue()


def _partes(pdf, limite):
    """Lista de (ini, fim, bytes) respeitando o limite. Serializa uma vez por parte."""
    pesos = _pesos_por_pagina(pdf)
    n = len(pesos)
    partes = []
    ini = 0
    while ini < n:
        estimado = 0
        fim = ini
        while fim < n:
            if fim > ini and estimado + pesos[fim] > limite:
                break
            estimado += pesos[fim]
            fim += 1
        fim = max(fim, ini + 1)          # sempre pelo menos 1 página
        dados = _monta_parte(pdf, ini, fim)
        # ajuste fino: só quando a estimativa errou para cima
        while fim - ini > 1 and len(dados) > limite:
            fim -= 1
            dados = _monta_parte(pdf, ini, fim)
        partes.append((ini, fim, dados))
        ini = fim
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
            r = compress.comprimir(entrada, tmp, nivel, log=lambda m: None)
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

    pasta = destino or os.path.dirname(origem) or "."
    os.makedirs(pasta, exist_ok=True)
    base = os.path.splitext(os.path.basename(entrada))[0]

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

    pdf = pikepdf.open(origem)
    try:
        total = len(pdf.pages)
        partes = _partes(pdf, limite)
    finally:
        pdf.close()

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
    print("dividindo %s (limite %.2f MB, compressão %s)"
          % (os.path.basename(args.entrada), limite / 1048576,
             "off" if args.sem_comprimir else args.nivel))
    try:
        r = dividir(args.entrada, limite,
                    comprimir=not args.sem_comprimir, nivel=args.nivel,
                    destino=args.saida_dir)
    except Exception as ex:
        msg = "falha ao dividir: %s" % ex
        print(msg, file=sys.stderr)
        if args.avisar:
            import compress
            compress._aviso("PDFagent", msg, erro=True)
        return 1

    if r["precisa_dividir"]:
        msg = "%d arquivo(s) gerado(s) com limite de %.2f MB" % (
            len(r["partes"]), limite / 1048576)
    elif r["partes"]:
        msg = "não precisou dividir; comprimido salvo em %s" % os.path.basename(r["partes"][0])
    else:
        msg = "não precisou dividir (já cabe em %.2f MB)" % (limite / 1048576)
    print(msg)
    if args.avisar:
        import compress
        compress._aviso("PDFagent", msg + "\n\n" + "\n".join(
            "• " + os.path.basename(c) for c in r["partes"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
