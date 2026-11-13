"""Signature des jetons de licence (Ed25519). La clé privée ne sort jamais de ce processus ni du fichier d'environnement."""

from __future__ import annotations

import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .protocol import proto


class Signer:
    def __init__(self, seed: bytes, kid: str):
        self._private = Ed25519PrivateKey.from_private_bytes(seed)
        self.kid = kid
        self.public_key = self._private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)

    @property
    def public_key_b64(self) -> str:
        return base64.b64encode(self.public_key).decode("ascii")

    def token(self, *, typ: str, license_id: str, did: str, issued_at: int, expires_at: int | None, max_devices: int) -> str:
        payload = {
            "v": 1,
            "kid": self.kid,
            "typ": typ,
            "lid": license_id,
            "did": did,
            "iat": int(issued_at),
            "exp": None if expires_at is None else int(expires_at),
            "plan": proto.PLAN,
            "dev": int(max_devices),
        }
        payload_bytes = proto.canonical_json(payload)
        return proto.encode_token(payload_bytes, self._private.sign(proto.signing_message(payload_bytes)))

    def verify_own(self, token: str) -> dict:
        """Relit un jeton que CE serveur a émis (utilisé pour libérer une place : le jeton prouve l'activation)."""
        return proto.verify_token(token, {self.kid: self.public_key})


def generate_seed() -> bytes:
    return Ed25519PrivateKey.generate().private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
    )
