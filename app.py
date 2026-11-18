# app.py — Interface grafica do CompressPDF (Tkinter, sem dependencias extras).
#
# Uso:  python app.py
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
import urllib.request
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import compress
from updater import protocol

NIVEIS = [
    ("extreme", "Extreme", "Menos qualidade, alta compressão"),
    ("recommended", "Recommended", "Boa qualidade, boa compressão"),
    ("low", "Low", "Alta qualidade, menos compressão"),
]


def _precisa_atualizar(versao_remota, versao_local=None):
    """True quando o manifesto publicado e' mais novo que o app (semver)."""
    local = versao_local if versao_local is not None else compress.VERSAO
    return protocol.version_key(versao_remota) > protocol.version_key(local)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PDFagent")
        self.geometry("640x560")
        self.arquivos = []
        self.fila = queue.Queue()
        self._ocupado = False          # compressao em andamento
        self._update_estado = None     # {"versao", "files", "download", "remove"}
        self._update_checando = False
        self._monta()
        self.after(100, self._drena)
        # Decisao do usuario: a checagem automatica acontece SO' no boot. Nao
        # ha' re-checagem periodica durante a sessao — para conferir depois, o
        # usuario usa o botao "Verificar atualizacoes".
        self.after(1500, lambda: self._checa_atualizacoes(manual=False))

    def _monta(self):
        topo = ttk.Frame(self, padding=10)
        topo.pack(fill="both", expand=True)

        barra_up = ttk.Frame(topo)
        barra_up.pack(fill="x", pady=(0, 6))
        self.btn_checar = ttk.Button(barra_up, text="Verificar atualizações",
                                     command=lambda: self._checa_atualizacoes(True))
        self.btn_checar.pack(side="left")
        self.lbl_update = ttk.Label(barra_up, text="")
        self.lbl_update.pack(side="right")
        # botao verde: so' aparece quando existe versao nova (pack em _oferece_update)
        self.btn_atualizar = tk.Button(
            barra_up, text="Atualizar", bg="#1e8e3e", fg="white",
            activebackground="#1b7a35", activeforeground="white",
            relief="flat", padx=10, cursor="hand2",
            command=self._instala_atualizacao)

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
        self._ocupado = True
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
                    self._ocupado = False
                elif tipo == "update":
                    self._oferece_update(msg)
                elif tipo == "update_fim":
                    self._update_checando = False
                elif tipo == "update_progress":
                    self.lbl_update.configure(text=msg)
                elif tipo == "update_ready":
                    self.lbl_update.configure(text="aplicando… o app vai reabrir")
                    self.after(400, self._fecha_para_atualizar)
                elif tipo == "update_erro":
                    self.btn_atualizar.configure(state="normal", text="Atualizar")
                    self.lbl_update.configure(text="")
                    messagebox.showerror("Atualização", msg)
                elif tipo == "aviso":
                    messagebox.showinfo("Atualizações", msg)
                else:
                    self._log(msg)
        except queue.Empty:
            pass
        self.after(100, self._drena)

    # ------------------------------------------------------------------ updater
    def _app_dir(self):
        """Pasta da instalacao (onedir) ou None quando roda do codigo-fonte."""
        if not getattr(sys, "frozen", False):
            return None
        return Path(sys.executable).parent

    def _checa_atualizacoes(self, manual):
        if self._update_checando:
            return
        self._update_checando = True
        if manual:
            self.lbl_update.configure(text="verificando…")
        threading.Thread(target=self._checa_worker, args=(manual,),
                         daemon=True).start()

    def _checa_worker(self, manual):
        try:
            estado = protocol.fetch_manifest()
            if _precisa_atualizar(estado["version"]):
                alvo = self._app_dir()
                plano = (protocol.classify_files(alvo, estado["files"])
                         if alvo else {"download": [], "remove": []})
                self.fila.put(("update", {"versao": estado["version"],
                                          "files": estado["files"],
                                          "download": plano["download"],
                                          "remove": plano["remove"]}))
            elif manual:
                self.fila.put(("aviso", "Você já está na versão mais nova "
                                        "(%s)." % compress.VERSAO))
        except Exception as ex:
            if manual:
                self.fila.put(("aviso", "Não foi possível verificar: %s" % ex))
        finally:
            self.fila.put(("update_fim", None))

    def _oferece_update(self, estado):
        self._update_estado = estado
        self.btn_atualizar.configure(text="Atualizar para %s" % estado["versao"])
        if not self.btn_atualizar.winfo_ismapped():
            self.btn_atualizar.pack(side="right", padx=6)
        self.lbl_update.configure(
            text="%d arquivo(s) a baixar" % len(estado["download"]))

    def _instala_atualizacao(self):
        if not self._update_estado or self._ocupado:
            return
        if self._app_dir() is None:
            self.lbl_update.configure(text="atualização só na versão instalada")
            return
        self.btn_atualizar.configure(state="disabled", text="Baixando…")
        threading.Thread(target=self._baixa_e_aplica,
                         args=(self._update_estado,), daemon=True).start()

    def _baixa_e_aplica(self, estado):
        versao = estado["versao"]
        raiz = Path(tempfile.gettempdir()) / "pdfagent_update" / versao
        staged = raiz / "staged"
        removals = raiz / "removals.txt"
        try:
            if staged.exists():
                shutil.rmtree(staged)
            staged.mkdir(parents=True)
            removals.write_text("\n".join(estado["remove"])
                                + ("\n" if estado["remove"] else ""),
                                encoding="utf-8")
            total = len(estado["download"])
            for indice, caminho in enumerate(estado["download"], 1):
                entry = estado["files"][caminho]
                destino = staged / caminho
                destino.parent.mkdir(parents=True, exist_ok=True)
                self.fila.put(("update_progress",
                               "%d/%d %s" % (indice, total, caminho)))
                req = urllib.request.Request(
                    entry["github_url"],
                    headers={"User-Agent": protocol.USER_AGENT})
                with urllib.request.urlopen(req, timeout=120) as resp, \
                        open(destino, "wb") as saida:
                    shutil.copyfileobj(resp, saida, 1024 * 1024)
                if protocol.sha256_file(destino) != entry["sha256"]:
                    raise RuntimeError("hash divergente: %s" % caminho)
            app_dir = self._app_dir()
            updater_tmp = (Path(tempfile.gettempdir())
                           / ("PDFagentUpdater-%d.exe" % os.getpid()))
            shutil.copy2(app_dir / "PDFagentUpdater.exe", updater_tmp)
            subprocess.Popen(
                [str(updater_tmp),
                 "--sync-staged", str(staged),
                 "--sync-removals", str(removals),
                 "--sync-version", versao,
                 "--target", str(app_dir),
                 "--pid", str(os.getpid()),
                 "--log", str(app_dir / "updater.log")],
                creationflags=0x00000008,   # DETACHED_PROCESS
                close_fds=True)
            self.fila.put(("update_ready", None))
        except Exception as ex:
            self.fila.put(("update_erro", str(ex)))

    def _fecha_para_atualizar(self):
        try:
            self.destroy()
        finally:
            os._exit(0)


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
    # OBRIGATORIO no executavel (PyInstaller): sem isto, cada worker de
    # ProcessPoolExecutor reabriria o app; com isto, o filho cai aqui, executa
    # a tarefa do pool e sai. Fora do .exe e' no-op.
    import multiprocessing
    multiprocessing.freeze_support()
    argv = sys.argv[1:]
    if argv:
        _anexa_console()
    import cli
    sys.exit(cli.main(argv) or 0)
