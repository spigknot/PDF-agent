"""Gera o par RSA-4096 do manifesto de atualizacao (uma vez so).

- privada: release/update_private_key.pem  (NUNCA commitar)
- publica: imprime N e E para colar em updater/protocol.py
"""
import pathlib
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

RAIZ = pathlib.Path(__file__).resolve().parent.parent
DESTINO = RAIZ / "release" / "update_private_key.pem"


def main() -> int:
    if DESTINO.exists():
        print("ja existe: %s (apague para gerar outra)" % DESTINO)
        return 1
    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    chave = rsa.generate_private_key(public_exponent=65537, key_size=4096)
    DESTINO.write_bytes(chave.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ))
    pub = chave.public_key().public_numbers()
    print("UPDATE_PUBLIC_KEY_E =", pub.e)
    print("UPDATE_PUBLIC_KEY_N =", pub.n)
    print("chave privada em", DESTINO)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
