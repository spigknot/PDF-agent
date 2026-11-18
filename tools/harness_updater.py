"""E2E do updater sem R2: transacao real com start injetado e rollback.

Uso: py -3.11 tools/harness_updater.py
"""
import functools
import http.server
import os
import sys
import tempfile
import threading
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from updater import apply, protocol  # noqa: E402


def _pkg(base: Path, marca: bytes) -> None:
    (base / "_internal").mkdir(parents=True)
    for rel, dados in {
        "PDFagent.exe": marca + b"-exe",
        "PDFagentUpdater.exe": b"upd",
        "pdfcompress.cmd": b"@echo",
        "pdfsplit.cmd": b"@echo",
        "_internal/base_library.zip": b"bl",
        "_internal/python311.dll": b"dll",
        "_internal/VCRUNTIME140.dll": b"dll",
        "_internal/VCRUNTIME140_1.dll": b"dll",
    }.items():
        (base / rel).write_bytes(dados)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="harness-upd-"))
    os.environ["LOCALAPPDATA"] = str(tmp / "la")
    inst = tmp / "inst"
    novo = tmp / "novo"
    _pkg(inst, b"velho")
    _pkg(novo, b"novo")
    (inst / "_internal" / "orfao.dll").write_bytes(b"x")

    handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                directory=str(tmp))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base_url = "http://127.0.0.1:%d" % srv.server_address[1]

    files = {}
    for path in sorted(novo.rglob("*")):
        if path.is_file():
            rel = path.relative_to(novo).as_posix()
            files[rel] = {"sha256": protocol.sha256_file(path),
                          "size": path.stat().st_size, "drive_id": "",
                          "github_url": "%s/novo/%s" % (base_url, rel)}

    plano = protocol.classify_files(inst, files)
    assert plano["download"] == ["PDFagent.exe"], plano["download"]
    assert plano["remove"] == ["_internal/orfao.dll"], plano["remove"]

    staged = tmp / "staged"
    for rel in plano["download"]:
        destino = staged / rel
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes((novo / rel).read_bytes())

    inicios = {"n": 0}
    apply.apply_sync_transaction(
        staged, inst, plano["remove"], 1, tmp / "updater.log",
        launch_verify=lambda *_a, **_k: inicios.__setitem__("n", inicios["n"] + 1))

    assert (inst / "PDFagent.exe").read_bytes() == b"novo-exe", "diff nao aplicado"
    assert not (inst / "_internal" / "orfao.dll").exists(), "orfao nao removido"
    assert inicios["n"] == 1, "start nao verificado"

    falha = tmp / "staged_falha"
    falha.mkdir()
    (falha / "PDFagent.exe").write_bytes(b"quebrado-exe")

    def nao_sobe(*_a, **_k):
        raise apply.UpdateError("nao subiu")

    try:
        apply.apply_sync_transaction(falha, inst, [], 1, tmp / "updater.log",
                                     launch_verify=nao_sobe)
    except apply.UpdateError:
        pass
    else:
        raise AssertionError("deveria ter falhado")

    assert (inst / "PDFagent.exe").read_bytes() == b"novo-exe", "rollback falhou"
    srv.shutdown()
    print("PASS: diff aplicado, orfao removido, start verificado, rollback ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
