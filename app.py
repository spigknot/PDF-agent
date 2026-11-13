# app.py — Interface grafica do CompressPDF (Tkinter, sem dependencias extras).
#
# Uso:  python app.py
import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import compress

NIVEIS = [
    ("extreme", "Extreme", "Menos qualidade, alta compressão"),
    ("recommended", "Recommended", "Boa qualidade, boa compressão"),
    ("low", "Low", "Alta qualidade, menos compressão"),
]


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PDFagent")
        self.geometry("640x520")
        self.arquivos = []
        self.fila = queue.Queue()
        self._monta()
        self.after(100, self._drena)

    def _monta(self):
        topo = ttk.Frame(self, padding=10)
        topo.pack(fill="both", expand=True)

        ttk.Label(topo, text="PDFs:").pack(anchor="w")
        self.lista = tk.Listbox(topo, height=6, selectmode="extended")
        self.lista.pack(fill="x", pady=4)
        linha = ttk.Frame(topo)
        linha.pack(fill="x")
        ttk.Button(linha, text="Adicionar…", command=self._add).pack(side="left")
        ttk.Button(linha, text="Remover", command=self._del).pack(side="left", padx=4)

        ttk.Label(topo, text="Nível de compressão:").pack(anchor="w", pady=(10, 0))
        self.nivel = tk.StringVar(value="recommended")
        for valor, rotulo, desc in NIVEIS:
            ttk.Radiobutton(topo, text=f"{rotulo} — {desc}",
                            value=valor, variable=self.nivel).pack(anchor="w")

        linha2 = ttk.Frame(topo)
        linha2.pack(fill="x", pady=(10, 0))
        ttk.Label(linha2, text="Saída:").pack(side="left")
        self.saida = tk.StringVar(value="")
        ttk.Entry(linha2, textvariable=self.saida).pack(side="left", fill="x",
                                                        expand=True, padx=4)
        ttk.Button(linha2, text="…", width=3,
                   command=self._escolhe_saida).pack(side="left")

        self.btn = ttk.Button(topo, text="Comprimir", command=self._go)
        self.btn.pack(pady=10)
        self.barra = ttk.Progressbar(topo, mode="indeterminate")
        self.barra.pack(fill="x")

        ttk.Label(topo, text="Registro:").pack(anchor="w")
        self.logw = tk.Text(topo, height=10, state="disabled")
        self.logw.pack(fill="both", expand=True)

    def _log(self, msg):
        self.logw.configure(state="normal")
        self.logw.insert("end", msg + "\n")
        self.logw.see("end")
        self.logw.configure(state="disabled")

    def _add(self):
        arqs = filedialog.askopenfilenames(title="Escolher PDFs",
                                           filetypes=[("PDF", "*.pdf")])
        for a in arqs:
            if a not in self.arquivos:
                self.arquivos.append(a)
                self.lista.insert("end", os.path.basename(a))

    def _del(self):
        for i in sorted(self.lista.curselection(), reverse=True):
            self.lista.delete(i)
            del self.arquivos[i]

    def _escolhe_saida(self):
        d = filedialog.askdirectory(title="Pasta de saída")
        if d:
            self.saida.set(d)

    def _go(self):
        if not self.arquivos:
            messagebox.showinfo("PDFagent", "Adicione pelo menos um PDF.")
            return
        # captura TUDO da UI aqui (thread da UI); a worker só recebe valores
        nivel = self.nivel.get()
        pasta = self.saida.get().strip()
        alvos = list(self.arquivos)
        self.btn.configure(state="disabled")
        self.barra.start(15)
        threading.Thread(target=self._trabalha,
                         args=(alvos, nivel, pasta),
                         daemon=True).start()

    def _trabalha(self, alvos, nivel, pasta):
        if pasta:
            os.makedirs(pasta, exist_ok=True)
        for entrada in alvos:
            if pasta:
                saida = os.path.join(pasta, os.path.basename(
                    compress._nome_saida(entrada, None, nivel)))
            else:
                saida = compress._nome_saida(entrada, None, nivel)
            try:
                r = compress.comprimir(entrada, saida, nivel,
                                       log=lambda m: self.fila.put(("log", m)))
                self.fila.put(("log",
                    f"OK: {os.path.basename(saida)} "
                    f"{r['antes']:,} -> {r['depois']:,} bytes (-{r['razao']:.1f}%)"))
            except Exception as ex:
                self.fila.put(("log", f"FALHA {os.path.basename(entrada)}: {ex}"))
        self.fila.put(("fim", None))

    def _drena(self):
        try:
            while True:
                tipo, msg = self.fila.get_nowait()
                if tipo == "fim":
                    self.barra.stop()
                    self.btn.configure(state="normal")
                else:
                    self._log(msg)
        except queue.Empty:
            pass
        self.after(100, self._drena)


def _anexa_console():
    """No .exe --windowed o stdout/stderr vem nulos: sem isso o modo linha de
    comando (PDFagent.exe entrada.pdf -n low) nao imprime nada. Anexa ao
    console do processo pai e reabre os fluxos."""
    if os.name != "nt" or sys.stdout is not None:
        return
    try:
        import ctypes
        if ctypes.windll.kernel32.AttachConsole(-1):
            sys.stdout = open("CONOUT$", "w", buffering=1,
                              encoding="utf-8", errors="replace")
            sys.stderr = open("CONOUT$", "w", buffering=1,
                              encoding="utf-8", errors="replace")
    except Exception:
        pass


def run_gui(argv=None):
    """Abre a interface gráfica (subcomando `gui` do cli.py)."""
    App().mainloop()
    return 0


if __name__ == "__main__":
    argv = sys.argv[1:]
    if argv:
        _anexa_console()
    import cli
    sys.exit(cli.main(argv) or 0)
