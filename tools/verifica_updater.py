"""Fecha as duas verificacoes pendentes do plano do updater.

1. botao verde: com um manifesto mais novo, o App mostra o botao e o texto certo
   (instancia Tk e drena a fila, sem abrir janela interativa);
2. --full: `fetch_full_releases()` acha o PDFagent-onedir-*.zip da release real
   e devolve url + sha256 + tamanho.

Uso: py -3.11 tools/verifica_updater.py
"""
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import app as app_mod  # noqa: E402
from updater import apply, protocol  # noqa: E402


def checa_botao_verde() -> None:
    janela = app_mod.App()
    janela.update()
    assert not janela.btn_atualizar.winfo_ismapped(), "botao verde nao pode nascer visivel"

    estado = {
        "version": "1.2.1",
        "files": {"PDFagent.exe": {"sha256": "f" * 64, "size": 10,
                                   "drive_id": "", "github_url": "https://x"}},
    }
    original = protocol.fetch_manifest
    protocol.fetch_manifest = lambda *a, **k: estado
    try:
        janela._checa_worker(manual=True)
        janela.update()
        # drena a fila manualmente (o after(100) nao roda sem mainloop)
        janela._drena()
        janela.update()
    finally:
        protocol.fetch_manifest = original

    visivel = bool(janela.btn_atualizar.winfo_ismapped())
    texto = janela.btn_atualizar.cget("text")
    label = janela.lbl_update.cget("text")
    cor = janela.btn_atualizar.cget("bg")
    janela.destroy()

    print("botao visivel:", visivel, "| cor:", cor)
    print("texto:", texto)
    print("label:", label)
    assert visivel, "botao verde devia aparecer com versao nova"
    assert "1.2.1" in texto, texto


def checa_full() -> None:
    descritores = apply.fetch_full_releases()
    primeiro = descritores[0]
    print("release:", primeiro["version"], "|", primeiro["zip_name"])
    print("sha256:", primeiro["sha256"][:16], "... | size:", primeiro["size"])
    print("url:", primeiro["url"][:72], "...")


if __name__ == "__main__":
    checa_full()
    checa_botao_verde()
