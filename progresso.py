"""Uma ÚNICA janela para o modo --avisar (menu de contexto).

Por que existe: o `.exe` é `--windowed`, então (a) sem console os workers de
`multiprocessing` abriam uma janelinha `conhost` cada um e (b) o usuário só
via um MessageBox no fim. Aqui há uma janela só, com fase, barra e cronômetro
(congelado no fim).

No dividir ela abre PERGUNTANDO: limite em MB (1 casa, já em 1,7) e a caixa
"Comprimir" — DESMARCADA por padrão; marcada, aparecem low/recommended/
extreme. O mesmo diálogo vira a tela de progresso depois do clique em Dividir.

Uso:
    codigo = progresso.executar(lambda log: trabalho(log), subtitulo="x.pdf")
    codigo = progresso.executar(lambda log, escolha: trabalho(log, escolha),
                                subtitulo="x.pdf", pedir_limite=1.7)
    # escolha = {"limite_mb": 1.7, "comprimir": False, "nivel": "recommended"}
"""
import queue
import threading
import time

TITULO = "PDFagent"

# fase do log (as linhas do `comprimir` começam com "[n]") -> fração concluída
_FASES = ((b"[1]", 0.04), (b"[2]", 0.12), (b"[3]", 0.55),
          (b"[4]", 0.63), (b"[5]", 0.94), (b"[6]", 1.0))

#: limite que a pergunta do dividir já traz preenchido (MB, uma casa decimal)
LIMITE_PADRAO_MB = 1.7

#: piso aceito: abaixo disso nenhuma parte cabe uma página com imagem
LIMITE_MINIMO_MB = 1.0

#: teto aceito (parte maior que isso não é "dividir", é copiar)
LIMITE_MAXIMO_MB = 2000.0

#: níveis de compressão oferecidos quando a caixa "Comprimir" é marcada
NIVEIS = ("low", "recommended", "extreme")


def _fmt(segundos):
    """12,3 s  |  1:02,3  |  1:02:03"""
    if segundos < 60:
        return "%.1f s" % segundos
    minutos, resto = divmod(segundos, 60)
    if minutos < 60:
        return "%d:%04.1f" % (minutos, resto)
    horas, minutos = divmod(int(minutos), 60)
    return "%d:%02d:%02d" % (horas, minutos, int(resto))


def _fracao(msg):
    """Fração da barra para a linha de log (None quando não é marco de fase)."""
    dado = msg.encode("utf-8", "replace")[:3]
    for marca, fracao in _FASES:
        if dado.startswith(marca):
            return fracao
    return None


class Janela:
    def __init__(self, titulo=TITULO, subtitulo="", pedir_limite=None,
                 comprimir_inicial=False, nivel_inicial="recommended"):
        import tkinter as tk
        from tkinter import ttk

        self.fila = queue.Queue()
        self.ocupado = True           # trava o fechamento durante o trabalho
        self.iniciado = False
        self.resultado = 1
        self.t0 = None
        self.tempo_total = None
        self.pedido = None            # {"limite_mb", "comprimir", "nivel"}
        self.trabalho = None
        self._tk = tk
        self._ttk = ttk

        self.raiz = tk.Tk()
        self.raiz.title(titulo)
        self.raiz.geometry("620x330")
        self.raiz.resizable(False, False)
        self.raiz.attributes("-topmost", True)
        self.raiz.protocol("WM_DELETE_WINDOW", self._fechar)

        self.quadro = ttk.Frame(self.raiz, padding=16)
        self.quadro.pack(fill="both", expand=True)

        topo = ttk.Frame(self.quadro)
        topo.pack(fill="x")
        ttk.Label(topo, text=titulo,
                  font=("Segoe UI Semibold", 14)).pack(side="left")
        self.lbl_tempo = ttk.Label(topo, text="0,0 s", font=("Consolas", 12))
        self.lbl_tempo.pack(side="right")

        ttk.Label(self.quadro, text=subtitulo or " ",
                  foreground="#444").pack(anchor="w", pady=(2, 10))

        self.barra = ttk.Progressbar(self.quadro, mode="determinate", maximum=100)
        self.lbl_msg = ttk.Label(self.quadro, text="preparando…", wraplength=560)
        self.txt_fim = tk.Text(self.quadro, height=5, wrap="word", relief="flat",
                               background=self.raiz.cget("background"),
                               font=("Segoe UI", 9))
        self.txt_fim.configure(state="disabled")
        self.btn = ttk.Button(self.quadro, text="Fechar", command=self._fechar,
                              state="disabled")

        self.frame_prompt = None
        if pedir_limite is not None:
            self._monta_pergunta(pedir_limite, comprimir_inicial, nivel_inicial)
        else:
            self._mostra_progresso()

    # -- pergunta -----------------------------------------------------------
    def _monta_pergunta(self, limite_inicial, comprimir_inicial, nivel_inicial):
        import tkinter as tk
        from tkinter import ttk

        self.frame_prompt = ttk.Frame(self.quadro)
        self.frame_prompt.pack(fill="x", pady=(4, 0))

        linha = ttk.Frame(self.frame_prompt)
        linha.pack(fill="x")
        ttk.Label(linha, text="Dividir em partes de").pack(side="left")
        self.var_limite = tk.StringVar(value="%.1f" % limite_inicial)
        self.spin = ttk.Spinbox(linha, from_=LIMITE_MINIMO_MB,
                                to=LIMITE_MAXIMO_MB, increment=0.1,
                                format="%.1f", width=7,
                                textvariable=self.var_limite)
        self.spin.pack(side="left", padx=(8, 4))
        ttk.Label(linha, text="MB").pack(side="left")

        self.var_comprimir = tk.BooleanVar(value=bool(comprimir_inicial))
        self.chk = ttk.Checkbutton(self.frame_prompt, text="Comprimir",
                                   variable=self.var_comprimir,
                                   command=self._alterna_niveis)
        self.chk.pack(anchor="w", pady=(10, 0))

        self.frame_niveis = ttk.Frame(self.frame_prompt)
        self.var_nivel = tk.StringVar(value=nivel_inicial)
        for nivel in NIVEIS:
            ttk.Radiobutton(self.frame_niveis, text=nivel, value=nivel,
                            variable=self.var_nivel).pack(side="left", padx=(0, 12))

        acoes = ttk.Frame(self.frame_prompt)
        acoes.pack(fill="x", pady=(14, 0))
        ttk.Button(acoes, text="Cancelar", command=self._cancela).pack(side="right")
        self.btn_dividir = ttk.Button(acoes, text="Dividir",
                                      command=self._confirma)
        self.btn_dividir.pack(side="right", padx=(0, 8))

        self._alterna_niveis()
        self.spin.focus_set()
        self.raiz.bind("<Return>", lambda _e: self._confirma())

    def _alterna_niveis(self):
        if self.var_comprimir.get():
            if not self.frame_niveis.winfo_manager():
                self.frame_niveis.pack(anchor="w", pady=(4, 0))
        else:
            self.frame_niveis.pack_forget()

    def _confirma(self):
        try:
            valor = float(self.var_limite.get().replace(",", "."))
        except ValueError:
            valor = None
        if valor is None or valor < LIMITE_MINIMO_MB or valor > LIMITE_MAXIMO_MB:
            self.lbl_msg.configure(
                text="limite inválido: use de %.1f a %.0f MB (uma página com "
                     "imagem costuma passar de 1 MB)" % (LIMITE_MINIMO_MB,
                                                         LIMITE_MAXIMO_MB))
            self.lbl_msg.pack(anchor="w", pady=(8, 0))
            self.barra.pack_forget()
            self.spin.focus_set()
            return
        self.pedido = {"limite_mb": valor,
                       "comprimir": bool(self.var_comprimir.get()),
                       "nivel": self.var_nivel.get()}
        self._mostra_progresso()
        self._inicia()

    def _cancela(self):
        self.ocupado = False
        self.resultado = 2
        self.raiz.destroy()

    # -- layout -------------------------------------------------------------
    def _mostra_progresso(self):
        if self.frame_prompt is not None:
            self.frame_prompt.destroy()
            self.frame_prompt = None
        self.barra.pack(fill="x")
        self.lbl_msg.pack(anchor="w", pady=(8, 0))
        self.txt_fim.pack(fill="both", expand=True, pady=(8, 0))
        self.btn.pack(anchor="e", pady=(10, 0))

    # -- execução -----------------------------------------------------------
    def _inicia(self):
        if self.iniciado:
            return
        self.iniciado = True
        self.t0 = time.monotonic()
        threading.Thread(target=self._roda, daemon=True).start()

    def _roda(self):
        try:
            if self.pedido is None:
                ok, mensagem = self.trabalho(self.log)
            else:                       # modo pergunta: trabalho(log, escolha)
                ok, mensagem = self.trabalho(self.log, self.pedido)
        except SystemExit as ex:
            ok = not ex.code
            mensagem = "concluído" if ok else "falhou (código %s)" % ex.code
        except Exception as ex:                       # noqa: BLE001
            ok, mensagem = False, "erro: %s" % ex
        self.fila.put(("fim", (ok, mensagem, not ok)))

    # -- thread de UI -------------------------------------------------------
    def _fechar(self):
        if self.ocupado:
            return                      # não deixa fechar no meio da compressão
        self.raiz.destroy()

    def log(self, msg):
        """Callable passado ao `comprimir` (só enfileira; nunca toca em widget)."""
        self.fila.put(("log", str(msg)))

    def _drena(self):
        try:
            while True:
                tipo, dado = self.fila.get_nowait()
                if tipo == "log":
                    fracao = _fracao(dado)
                    if fracao is not None:
                        self.barra["value"] = fracao * 100
                    self.lbl_msg.configure(text=dado[:160])
                elif tipo == "fim":
                    ok, mensagem, erro = dado
                    self.ocupado = False
                    self.tempo_total = time.monotonic() - self.t0
                    self.lbl_tempo.configure(
                        text="tempo total: " + _fmt(self.tempo_total))
                    self.barra["value"] = 100 if ok else self.barra["value"]
                    self.lbl_msg.configure(text="concluído" if ok else "falhou")
                    self.txt_fim.configure(state="normal")
                    self.txt_fim.delete("1.0", "end")
                    self.txt_fim.insert(
                        "end", "%s\n\ntempo: %s" % (mensagem, _fmt(self.tempo_total)))
                    self.txt_fim.configure(
                        state="disabled",
                        foreground="#a11" if erro else "#13753b")
                    self.btn.configure(state="normal", text="Fechar",
                                       command=self._fechar)
                    self.resultado = 0 if ok else 1
        except queue.Empty:
            pass
        if self.iniciado and self.ocupado and self.t0 is not None:
            self.lbl_tempo.configure(text=_fmt(time.monotonic() - self.t0))
        if self.raiz.winfo_exists():
            self.raiz.after(80, self._drena)

    def executa(self, trabalho):
        """`trabalho(log)`; no modo pergunta, `trabalho(log, escolha)`."""
        self.trabalho = trabalho
        if self.frame_prompt is None:
            self._inicia()
        self.raiz.after(80, self._drena)
        self.raiz.mainloop()
        return self.resultado


def executar(trabalho, titulo=TITULO, subtitulo="", pedir_limite=None,
             comprimir_inicial=False, nivel_inicial="recommended"):
    """Abre a janela, roda `trabalho(log[, escolha])` e devolve o código (0/1/2)."""
    janela = Janela(titulo, subtitulo, pedir_limite=pedir_limite,
                    comprimir_inicial=comprimir_inicial,
                    nivel_inicial=nivel_inicial)
    return janela.executa(trabalho)
