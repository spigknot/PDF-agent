"""menu — tela única do botão direito: Comprimir ou Dividir.

O registro (instalador/PDFagent.iss) tem UM item "PDFagent" que chama
`PDFagent.exe menu "%1"`. Esta tela pergunta o mínimo, em telas separadas:

  1. escolha: dois botões grandes, [Comprimir] e [Dividir], sem texto extra;
  2a. comprimir → nível (low / recommended / extreme) → progresso;
  2b. dividir → limite em MB (1,6) + caixa "Comprimir antes" (+ nível) → progresso.

O motor é o mesmo de sempre: `compress._in_place` e `commands.split.dividir`.
`commands.split.main --avisar` continua existindo (CLI/shim); só o menu usa isto.
"""
import os
import queue
import sys
import threading
import time

# rodar `python commands/menu.py` direto poe commands/ no sys.path; a raiz
# do repo (onde vivem compress.py e progresso.py) precisa estar lá também
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RAIZ not in sys.path:
    sys.path.insert(0, _RAIZ)

#: o que cada tela devolve para quem chamou
NIVEIS = ("low", "recommended", "extreme")


def _progresso():
    import progresso

    return progresso


def valida_limite_mb(texto):
    """'1,6' | '1.6' -> 1.6. Rejeita absurdos (piso/teto de progresso.py)."""
    pg = _progresso()
    try:
        valor = float(str(texto).replace(",", "."))
    except (TypeError, ValueError):
        raise ValueError("informe o limite em MB (ex.: 1,6)")
    if not pg.LIMITE_MINIMO_MB <= valor <= pg.LIMITE_MAXIMO_MB:
        raise ValueError("use de %.1f a %.0f MB"
                         % (pg.LIMITE_MINIMO_MB, pg.LIMITE_MAXIMO_MB))
    return valor


def executar_compressao(entrada, nivel, log):
    """Comprime no lugar via o mesmo `_in_place` do menu antigo."""
    import compress
    from types import SimpleNamespace

    if nivel not in NIVEIS:
        raise ValueError("nível inválido: %s" % nivel)
    return compress._in_place([entrada], SimpleNamespace(nivel=nivel), log)


def executar_divisao(entrada, limite_mb, comprimir, nivel, log):
    """Divide via o mesmo `dividir` do motor pikepdf. Devolve (ok, mensagem)."""
    from commands import split as splitmod

    if nivel not in NIVEIS:
        raise ValueError("nível inválido: %s" % nivel)
    limite = int(round(limite_mb * 1048576))
    log("dividindo %s (limite %.1f MB, compressão %s)"
        % (os.path.basename(entrada), limite_mb,
           nivel if comprimir else "desligada"))
    try:
        r = splitmod.dividir(entrada, limite, comprimir=comprimir,
                             nivel=nivel, destino=None, log=log)
    except Exception as ex:
        return False, "falha ao dividir: %s" % ex
    if r["precisa_dividir"]:
        msg = "%d arquivo(s) gerado(s) com limite de %.1f MB" % (
            len(r["partes"]), limite_mb)
    elif r["partes"]:
        msg = ("não precisou dividir; comprimido salvo em %s"
               % os.path.basename(r["partes"][0]))
    else:
        msg = "não precisou dividir (já cabe em %.1f MB)" % limite_mb
    partes = "\n".join("• " + os.path.basename(c) for c in r["partes"])
    return True, msg + (("\n\n" + partes) if partes else "")


def _icone_app():
    pg = _progresso()
    return pg._icone()


def _png(nome):
    """PhotoImage de assets/<nome> (frozen ou fonte); None se ausente."""
    try:
        import tkinter as tk
    except Exception:
        return None
    candidatos = []
    if getattr(sys, "frozen", False):
        candidatos.append(os.path.join(getattr(sys, "_MEIPASS", ""), nome))
        candidatos.append(os.path.join(os.path.dirname(sys.executable), nome))
    candidatos.append(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "..", "assets", nome))
    for caminho in candidatos:
        if caminho and os.path.exists(caminho):
            try:
                return tk.PhotoImage(file=caminho)
            except Exception:
                return None
    return None


class Janela:
    COR_FUNDO = "#F4F5FA"
    COR_CARTAO = "#FFFFFF"
    COR_TEXTO = "#1F2430"
    COR_SUB = "#6B7280"
    COR_ACENTO = "#3445C8"
    COR_ACENTO_FG = "#FFFFFF"

    def __init__(self, entrada):
        import tkinter as tk
        from tkinter import ttk

        self.entrada = entrada
        self.fila = queue.Queue()
        self.ocupado = False
        self.trabalhando = False
        self.resultado = 2
        self.t0 = None
        self.tempo_total = None
        self.fracao_com_compressao = False

        self._tk = tk
        self.raiz = tk.Tk()
        self.raiz.title("PDFagent")
        icone = _icone_app()
        if icone:
            try:
                self.raiz.iconbitmap(icone)
            except Exception:
                pass
        self.raiz.geometry("560x440")
        self.raiz.resizable(False, False)
        self.raiz.configure(bg=self.COR_FUNDO)
        try:
            self.raiz.attributes("-topmost", True)
        except Exception:
            pass
        self.raiz.protocol("WM_DELETE_WINDOW", self._fechar)

        self.nivel_c = tk.StringVar(value="recommended")
        pg = _progresso()
        self.limite = tk.StringVar(value="%.1f" % pg.LIMITE_PADRAO_MB)
        self.chk_comprimir = tk.BooleanVar(value=False)
        self.nivel_d = tk.StringVar(value="recommended")

        estilo = ttk.Style(self.raiz)
        try:
            estilo.theme_use("clam")
        except Exception:
            pass
        estilo.configure("TFrame", background=self.COR_FUNDO)
        estilo.configure("TLabel", background=self.COR_FUNDO,
                         foreground=self.COR_TEXTO, font=("Segoe UI", 10))
        estilo.configure("Titulo.TLabel", font=("Segoe UI Semibold", 14))
        estilo.configure("Tempo.TLabel", foreground=self.COR_SUB,
                         font=("Consolas", 11))
        estilo.configure("Sub.TLabel", foreground=self.COR_SUB)
        estilo.configure("TRadiobutton", background=self.COR_FUNDO,
                         font=("Segoe UI", 10))
        estilo.configure("TCheckbutton", background=self.COR_FUNDO,
                         font=("Segoe UI", 10))
        estilo.configure("TSpinbox", font=("Segoe UI", 11))
        estilo.configure("TProgressbar", background=self.COR_ACENTO)

        topo = tk.Frame(self.raiz, bg=self.COR_FUNDO)
        topo.pack(fill="x", padx=20, pady=(16, 0))
        tk.Label(topo, text="PDFagent", bg=self.COR_FUNDO, fg=self.COR_TEXTO,
                 font=("Segoe UI Semibold", 14)).pack(side="left")
        self.lbl_tempo = tk.Label(topo, text="", bg=self.COR_FUNDO,
                                  fg=self.COR_SUB, font=("Consolas", 11))
        self.lbl_tempo.pack(side="right")
        try:
            tamanho = os.path.getsize(entrada) / 1048576.0
            sub = "%s  ·  %.1f MB" % (os.path.basename(entrada), tamanho)
        except OSError:
            sub = os.path.basename(entrada)
        tk.Label(self.raiz, text=sub, bg=self.COR_FUNDO, fg=self.COR_SUB,
                 font=("Segoe UI", 10)).pack(anchor="w", padx=20)

        self.corpo = tk.Frame(self.raiz, bg=self.COR_FUNDO)
        self.corpo.pack(fill="both", expand=True, padx=20, pady=12)

        self._img_comprimir = _png("btn_comprimir.png")
        self._img_dividir = _png("btn_dividir.png")

        self._mostra("escolha")

    # -- navegação ----------------------------------------------------------
    def _limpa_corpo(self):
        for filho in self.corpo.winfo_children():
            filho.destroy()

    GEOMETRIAS = {"escolha": "560x400", "comprimir": "440x300",
                  "dividir": "560x390"}

    def _mostra(self, tela):
        self._limpa_corpo()
        self.raiz.geometry(self.GEOMETRIAS[tela])
        {"escolha": self._tela_escolha,
         "comprimir": self._tela_comprimir,
         "dividir": self._tela_dividir}[tela]()

    def _fechar(self):
        if self.ocupado:
            return
        try:
            self.raiz.destroy()
        except Exception:
            pass

    # -- tela 1: escolha ----------------------------------------------------
    def _cartao(self, pai, imagem, texto, reserva, comando):
        tk = self._tk
        botao = tk.Button(pai, bg=self.COR_CARTAO,
                          activebackground="#E9EDFF", relief="flat", bd=0,
                          padx=12, pady=14, cursor="hand2", command=comando)
        if imagem is not None:
            tk.Label(botao, image=imagem, bg=self.COR_CARTAO).pack()
        else:
            tk.Label(botao, text=reserva, bg=self.COR_CARTAO,
                     fg=self.COR_ACENTO,
                     font=("Segoe UI Emoji", 40)).pack()
        tk.Label(botao, text=texto, bg=self.COR_CARTAO, fg=self.COR_TEXTO,
                 font=("Segoe UI Semibold", 12)).pack(pady=(8, 0))
        return botao

    def _tela_escolha(self):
        linha = self._tk.Frame(self.corpo, bg=self.COR_FUNDO)
        linha.pack(expand=True, fill="both")
        linha.columnconfigure((0, 1), weight=1, uniform="opcao")
        self._cartao(linha, self._img_comprimir, "Comprimir", "🗜",
                     lambda: self._mostra("comprimir")).grid(
                         row=0, column=0, sticky="nsew", padx=(0, 8))
        self._cartao(linha, self._img_dividir, "Dividir", "✂",
                     lambda: self._mostra("dividir")).grid(
                         row=0, column=1, sticky="nsew", padx=(8, 0))

    # -- tela 2a: comprimir -------------------------------------------------
    def _tela_comprimir(self):
        import tkinter as tk
        from tkinter import ttk

        for nivel in NIVEIS:
            ttk.Radiobutton(self.corpo, text=nivel, value=nivel,
                            variable=self.nivel_c).pack(anchor="w", pady=3)
        self._rodape(self.corpo,
                     [("Comprimir", self._vai_comprimir, True),
                      ("Voltar", lambda: self._mostra("escolha"), False)])

    # -- tela 2b: dividir ---------------------------------------------------
    def _tela_dividir(self):
        import tkinter as tk
        from tkinter import ttk

        linha = ttk.Frame(self.corpo)
        linha.pack(fill="x", pady=(2, 6))
        ttk.Label(linha, text="Tamanho máximo de cada parte").pack(side="left")
        ttk.Spinbox(linha, from_=1.0, to=2000.0, increment=0.1,
                    format="%.1f", width=6,
                    textvariable=self.limite).pack(side="left", padx=(8, 4))
        ttk.Label(linha, text="MB").pack(side="left")

        chk = ttk.Checkbutton(self.corpo, text="Comprimir antes de dividir",
                              variable=self.chk_comprimir,
                              command=self._alterna_niveis)
        chk.pack(anchor="w", pady=(8, 0))

        self.frame_niveis_d = ttk.Frame(self.corpo)
        for nivel in NIVEIS:
            ttk.Radiobutton(self.frame_niveis_d, text=nivel, value=nivel,
                            variable=self.nivel_d).pack(side="left",
                                                        padx=(0, 12))
        self._alterna_niveis()
        self._rodape(self.corpo,
                     [("Dividir", self._vai_dividir, True),
                      ("Voltar", lambda: self._mostra("escolha"), False)])

    def _alterna_niveis(self):
        if self.chk_comprimir.get():
            if not self.frame_niveis_d.winfo_manager():
                self.frame_niveis_d.pack(anchor="w", pady=(6, 0))
        else:
            self.frame_niveis_d.pack_forget()

    def _rodape(self, pai, botoes):
        import tkinter as tk

        barra = tk.Frame(pai, bg=self.COR_FUNDO)
        barra.pack(fill="x", pady=(16, 0))
        for texto, comando, primario in botoes:
            if primario:
                tk.Button(barra, text=texto, bg=self.COR_ACENTO,
                          fg=self.COR_ACENTO_FG, activebackground="#2B39A8",
                          activeforeground=self.COR_ACENTO_FG,
                          relief="flat", padx=18, pady=8,
                          font=("Segoe UI Semibold", 10), cursor="hand2",
                          command=comando).pack(side="right", padx=(8, 0))
            else:
                tk.Button(barra, text=texto, bg=self.COR_CARTAO,
                          fg=self.COR_TEXTO, activebackground="#E9EDFF",
                          relief="flat", padx=18, pady=8,
                          font=("Segoe UI", 10), cursor="hand2",
                          command=comando).pack(side="right")

    # -- progresso ----------------------------------------------------------
    def _vai_comprimir(self):
        nivel = self.nivel_c.get()
        self.fracao_com_compressao = False
        self._tela_progresso(
            lambda log: executar_compressao(self.entrada, nivel, log))

    def _vai_dividir(self):
        try:
            limite_mb = valida_limite_mb(self.limite.get())
        except ValueError as ex:
            self._aviso_linha(str(ex))
            return
        comprimir = bool(self.chk_comprimir.get())
        nivel = self.nivel_d.get()
        self.fracao_com_compressao = comprimir
        self._tela_progresso(
            lambda log: executar_divisao(self.entrada, limite_mb,
                                         comprimir, nivel, log))

    def _aviso_linha(self, msg):
        import tkinter as tk

        aviso = getattr(self, "_aviso", None)
        if aviso is None or not aviso.winfo_exists():
            aviso = tk.Label(self.corpo, text="", bg=self.COR_FUNDO,
                             fg="#B42318", font=("Segoe UI", 9),
                             wraplength=500)
            aviso.pack(anchor="w")
            self._aviso = aviso
        aviso.configure(text=msg)

    def _tela_progresso(self, trabalho):
        import tkinter as tk
        from tkinter import ttk

        self._limpa_corpo()
        self.raiz.geometry("620x380")
        self.barra = ttk.Progressbar(self.corpo, mode="determinate",
                                     maximum=100)
        self.barra.pack(fill="x")
        self.lbl_msg = tk.Label(self.corpo, text="preparando…",
                                bg=self.COR_FUNDO, fg=self.COR_TEXTO,
                                font=("Segoe UI", 10), wraplength=500,
                                justify="left")
        self.lbl_msg.pack(anchor="w", pady=(8, 0))
        self.txt_fim = tk.Text(self.corpo, height=6, wrap="word",
                               relief="flat", bg=self.COR_FUNDO,
                               font=("Segoe UI", 9))
        self.txt_fim.configure(state="disabled")
        self.txt_fim.pack(fill="both", expand=True, pady=(8, 0))
        self.btn_fechar = tk.Button(self.corpo, text="Fechar",
                                    bg=self.COR_CARTAO, fg=self.COR_TEXTO,
                                    relief="flat", padx=18, pady=8,
                                    font=("Segoe UI", 10), state="disabled",
                                    command=self._fechar)
        self.btn_fechar.pack(anchor="e", pady=(10, 0))

        self.ocupado = True
        self.trabalhando = True
        self.t0 = time.monotonic()
        self._trabalho = trabalho
        threading.Thread(target=self._roda, daemon=True).start()
        self.raiz.after(80, self._drena)

    def _roda(self):
        try:
            ok, mensagem = self._trabalho(self.log)
        except SystemExit as ex:
            ok = not ex.code
            mensagem = "concluído" if ok else "falhou (código %s)" % ex.code
        except Exception as ex:                       # noqa: BLE001
            ok, mensagem = False, "erro: %s" % ex
        self.fila.put(("fim", (ok, mensagem, not ok)))

    def log(self, msg):
        self.fila.put(("log", str(msg)))

    def _fracao_linha(self, msg):
        import re

        pg = _progresso()
        base = pg._fracao(msg)
        if base is not None:
            if self.fracao_com_compressao:
                return base * 0.4
            return base
        m = re.match(r"dividindo:\s*(\d+)\s*/\s*(\d+)", msg)
        if m:
            feito, total = int(m.group(1)), max(1, int(m.group(2)))
            piso = 0.4 if self.fracao_com_compressao else 0.0
            return piso + (1.0 - piso) * min(1.0, feito / total)
        return None

    def _drena(self):
        pg = _progresso()
        try:
            while True:
                tipo, dado = self.fila.get_nowait()
                if tipo == "log":
                    fracao = self._fracao_linha(dado)
                    if fracao is not None:
                        self.barra["value"] = fracao * 100
                    self.lbl_msg.configure(text=dado[:160])
                elif tipo == "fim":
                    ok, mensagem, erro = dado
                    self.ocupado = False
                    self.trabalhando = False
                    self.tempo_total = time.monotonic() - self.t0
                    self.lbl_tempo.configure(
                        text="tempo total: " + pg._fmt(self.tempo_total))
                    self.barra["value"] = 100 if ok else self.barra["value"]
                    self.lbl_msg.configure(text="concluído" if ok else "falhou")
                    self.txt_fim.configure(state="normal")
                    self.txt_fim.delete("1.0", "end")
                    self.txt_fim.insert(
                        "end", "%s\n\ntempo: %s" % (mensagem,
                                                   pg._fmt(self.tempo_total)))
                    self.txt_fim.configure(
                        state="disabled",
                        foreground="#B42318" if erro else "#13753b")
                    self.btn_fechar.configure(state="normal")
                    self.resultado = 0 if ok else 1
        except queue.Empty:
            pass
        if self.trabalhando and self.t0 is not None:
            self.lbl_tempo.configure(text=pg._fmt(time.monotonic() - self.t0))
        try:
            if self.raiz.winfo_exists():
                self.raiz.after(80, self._drena)
        except Exception:
            pass

    def executa(self):
        self.raiz.mainloop()
        return self.resultado


def main(argv=None):
    import argparse

    ap = argparse.ArgumentParser(prog="PDFagent menu")
    ap.add_argument("entrada", help="PDF de entrada")
    ap.add_argument("--avisar", action="store_true",
                    help="compatibilidade com o registro antigo (ignorado)")
    args = ap.parse_args(argv)

    if not os.path.exists(args.entrada):
        print("arquivo não encontrado: %s" % args.entrada, file=sys.stderr)
        return 1
    return Janela(args.entrada).executa()


if __name__ == "__main__":
    sys.exit(main())
