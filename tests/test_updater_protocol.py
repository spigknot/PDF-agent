"""Protocolo do manifesto de atualizacao (schema 2 assinado)."""
import base64
import hashlib
import json
import os
import sys

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
from updater import protocol  # noqa: E402


@pytest.fixture(scope="module")
def chave():
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub = priv.public_key().public_numbers()
    return priv, pub.n, pub.e


def _manifesto(priv, *, versao="1.2.0"):
    m = {
        "schema": 2,
        "version": versao,
        "created_at": "2026-11-18T12:00:00-0300",
        "files": [
            {"path": p, "sha256": hashlib.sha256(p.encode()).hexdigest(),
             "size": 10, "drive_id": "",
             "github_url": protocol.R2_PUBLIC_BASE + "/" + p}
            for p in protocol.SYNC_REQUIRED_FILES
        ],
    }
    m["signature"] = _assina(priv, m)
    return m


def _assina(priv, manifest):
    return base64.b64encode(
        priv.sign(protocol.canonical_manifest(manifest), padding.PKCS1v15(),
                  hashes.SHA256())).decode()


def test_canonical_e_estavel_e_ordena_por_path():
    a = {"schema": 2, "version": "1.0.0", "created_at": "x",
         "files": [{"path": "b", "sha256": "1" * 64, "size": 1},
                   {"path": "a", "sha256": "2" * 64, "size": 2}]}
    b = json.loads(json.dumps(a))
    b["files"] = list(reversed(b["files"]))
    assert protocol.canonical_manifest(a) == protocol.canonical_manifest(b)
    assert protocol.canonical_manifest(a) == (
        b'{"created_at":"x","files":[{"drive_id":"","github_url":"",'
        b'"path":"a","sha256":"' + b"2" * 64 + b'","size":2},'
        b'{"drive_id":"","github_url":"","path":"b","sha256":"'
        + b"1" * 64 + b'","size":1}],"schema":2,"version":"1.0.0"}')


def test_assinatura_valida_e_detecta_adulteracao(chave):
    priv, n, e = chave
    m = _manifesto(priv)
    assert protocol.verify_signature(m["signature"],
                                     protocol.canonical_manifest(m), n=n, e=e)
    m2 = json.loads(json.dumps(m))
    m2["version"] = "9.9.9"
    assert not protocol.verify_signature(m["signature"],
                                         protocol.canonical_manifest(m2), n=n, e=e)


def test_validate_rejeita_schema_versao_e_hash(chave):
    priv, n, e = chave
    bom = _manifesto(priv)
    assert protocol.validate_manifest(bom, n=n, e=e)["version"] == "1.2.0"
    for campo, valor in (("schema", 1), ("version", "1.2"), ("files", [])):
        ruim = json.loads(json.dumps(bom))
        ruim[campo] = valor
        with pytest.raises(protocol.SyncError):
            protocol.validate_manifest(ruim, n=n, e=e)


def test_validate_ignora_componente_desconhecido_e_exige_obrigatorios(chave):
    priv, n, e = chave
    m = _manifesto(priv)
    m["files"].append({"path": "futuro/arquivo.dll", "sha256": "0" * 64,
                       "size": 1, "drive_id": "",
                       "github_url": protocol.R2_PUBLIC_BASE + "/futuro/arquivo.dll"})
    m["signature"] = _assina(priv, {k: v for k, v in m.items() if k != "signature"})
    estado = protocol.validate_manifest(m, n=n, e=e)
    assert "futuro/arquivo.dll" not in estado["files"]

    faltando = json.loads(json.dumps(m))
    faltando["files"] = [f for f in faltando["files"]
                         if f["path"] != protocol.SYNC_REQUIRED_FILES[0]]
    faltando["signature"] = _assina(
        priv, {k: v for k, v in faltando.items() if k != "signature"})
    with pytest.raises(protocol.SyncError):
        protocol.validate_manifest(faltando, n=n, e=e)


def test_classify_baixa_so_o_que_mudou(tmp_path):
    alvo = tmp_path / "inst"
    (alvo / "_internal").mkdir(parents=True)
    (alvo / "PDFagent.exe").write_bytes(b"igual")
    (alvo / "PDFagentUpdater.exe").write_bytes(b"velho")
    # orfao DENTRO de um top-level gerenciado (_internal) e' removivel
    (alvo / "_internal" / "orfao.dll").write_bytes(b"x")
    (alvo / "meu_arquivo.txt").write_bytes(b"nao gerenciado")
    arquivos = {
        "PDFagent.exe": {"sha256": hashlib.sha256(b"igual").hexdigest(),
                         "size": 5, "drive_id": "", "github_url": "https://x"},
        "PDFagentUpdater.exe": {"sha256": hashlib.sha256(b"novo").hexdigest(),
                                "size": 4, "drive_id": "", "github_url": "https://x"},
        "pdfsplit.cmd": {"sha256": hashlib.sha256(b"shim").hexdigest(),
                         "size": 4, "drive_id": "", "github_url": "https://x"},
    }
    r = protocol.classify_files(alvo, arquivos)
    assert r["download"] == ["PDFagentUpdater.exe", "pdfsplit.cmd"]
    assert r["unchanged"] == 1
    assert r["remove"] == ["_internal/orfao.dll"], \
        "so' top-levels gerenciados entram na remocao"


def test_version_key_ordena_semver():
    assert protocol.version_key("1.10.0") > protocol.version_key("1.9.9")
    assert protocol.version_key("2.0.0") > protocol.version_key("1.99.99")
    with pytest.raises(protocol.SyncError):
        protocol.version_key("1.2")


def test_chave_publica_embutida_e_4096():
    assert len(str(protocol.UPDATE_PUBLIC_KEY_N)) == 1233
    assert protocol.UPDATE_PUBLIC_KEY_E == 65537
