"""App: decisao de atualizar e download seletivo (sem abrir a GUI)."""
import hashlib
import importlib
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)


def _app_mod():
    """Importa app.py sem instanciar Tk (o modulo so' define classes no topo)."""
    return importlib.import_module("app")


def test_precisa_atualizar_por_semver():
    app = _app_mod()
    assert app._precisa_atualizar("1.2.0", "1.1.0") is True
    assert app._precisa_atualizar("1.1.1", "1.1.0") is True
    assert app._precisa_atualizar("1.1.0", "1.1.0") is False
    assert app._precisa_atualizar("1.0.9", "1.1.0") is False
    assert app._precisa_atualizar("2.0.0", "1.99.99") is True


def test_download_seletivo_so_do_exe(tmp_path):
    from updater import protocol

    alvo = tmp_path / "inst"
    (alvo / "_internal").mkdir(parents=True)
    arquivos_locais = {
        "PDFagent.exe": b"velho",
        "PDFagentUpdater.exe": b"upd",
        "pdfcompress.cmd": b"@echo",
        "pdfsplit.cmd": b"@echo",
        "_internal/base_library.zip": b"bl",
        "_internal/python311.dll": b"dll",
        "_internal/vcruntime140.dll": b"dll",
        "_internal/vcruntime140_1.dll": b"dll",
    }
    for rel, dados in arquivos_locais.items():
        (alvo / rel).write_bytes(dados)

    manifesto = {}
    for rel, dados in arquivos_locais.items():
        novo = b"novo" if rel == "PDFagent.exe" else dados
        manifesto[rel] = {
            "sha256": hashlib.sha256(novo).hexdigest(),
            "size": len(novo),
            "drive_id": "",
            "github_url": protocol.R2_PUBLIC_BASE + "/" + rel,
        }
    plano = protocol.classify_files(alvo, manifesto)
    assert plano["download"] == ["PDFagent.exe"], "so' o exe mudou"
    assert plano["unchanged"] == len(arquivos_locais) - 1
    assert plano["remove"] == [], "nada orfao numa instalacao limpa"
