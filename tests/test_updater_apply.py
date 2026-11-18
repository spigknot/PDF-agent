"""Motor transacional do updater: diff, remocao de orfao e rollback."""
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
from updater import apply  # noqa: E402


def _instala(dst, marca: bytes) -> None:
    (dst / "_internal").mkdir(parents=True, exist_ok=True)
    (dst / "PDFagent.exe").write_bytes(marca + b"-exe")
    (dst / "PDFagentUpdater.exe").write_bytes(b"upd")
    (dst / "pdfcompress.cmd").write_bytes(b"@echo")
    (dst / "pdfsplit.cmd").write_bytes(b"@echo")
    (dst / "_internal" / "base_library.zip").write_bytes(b"bl")
    (dst / "_internal" / "python311.dll").write_bytes(b"dll")
    (dst / "_internal" / "vcruntime140.dll").write_bytes(b"dll")
    (dst / "_internal" / "vcruntime140_1.dll").write_bytes(b"dll")


def test_aplica_diff_remove_orfao_e_pede_start(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "la"))
    alvo = tmp_path / "inst"
    _instala(alvo, b"velho")
    (alvo / "_internal" / "orfao.dll").write_bytes(b"x")
    staging = tmp_path / "staged"
    staging.mkdir()
    (staging / "PDFagent.exe").write_bytes(b"novo-exe")
    log = tmp_path / "updater.log"
    chamadas = []

    apply.apply_sync_transaction(
        staging, alvo, ["_internal/orfao.dll"], 1, log,
        launch_verify=lambda *_a, **_k: chamadas.append("start"))

    assert (alvo / "PDFagent.exe").read_bytes() == b"novo-exe"
    assert not (alvo / "_internal" / "orfao.dll").exists(), "orfao nao removido"
    assert chamadas == ["start"], "start nao verificado"
    assert "validando" in log.read_text(encoding="utf-8").lower()


def test_rollback_restaura_a_instalacao(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "la"))
    alvo = tmp_path / "inst"
    _instala(alvo, b"velho")
    staging = tmp_path / "staged"
    staging.mkdir()
    (staging / "PDFagent.exe").write_bytes(b"novo-exe")

    def nao_sobe(*_a, **_k):
        raise apply.UpdateError("nao subiu")

    try:
        apply.apply_sync_transaction(staging, alvo, [], 1,
                                     tmp_path / "updater.log",
                                     launch_verify=nao_sobe)
    except apply.UpdateError as exc:
        assert "nao subiu" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("deveria ter falhado")

    assert (alvo / "PDFagent.exe").read_bytes() == b"velho-exe", \
        "rollback devia ter restaurado a versao anterior"


def test_staging_vazio_e_rejeitado(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "la"))
    alvo = tmp_path / "inst"
    _instala(alvo, b"velho")
    staging = tmp_path / "vazio"
    staging.mkdir()
    try:
        apply.apply_sync_transaction(staging, alvo, [], 1,
                                     tmp_path / "updater.log",
                                     launch_verify=lambda *_a, **_k: None)
    except apply.UpdateError:
        pass
    else:  # pragma: no cover
        raise AssertionError("staging vazio devia falhar")
