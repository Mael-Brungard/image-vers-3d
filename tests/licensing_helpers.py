"""Outils de test du système de licence : une paire de clés jetable et un « faux serveur » qui signe comme le vrai."""

from __future__ import annotations

import time

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from imagevers3d import _licproto as proto


def make_keypair() -> tuple[Ed25519PrivateKey, bytes]:
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return private, public


def sign_token(
    private: Ed25519PrivateKey,
    did: str,
    *,
    kid: str = "k1",
    typ: str = "license",
    lid: str = "L-test",
    iat: int | None = None,
    exp: int | None | str = "default",
    plan: str = "personal",
    dev: int = 2,
    **extra,
) -> str:
    iat = int(time.time()) if iat is None else iat
    if exp == "default":
        exp = iat + proto.TRIAL_DAYS * 86400 if typ == "trial" else None
    payload = {"v": 1, "kid": kid, "typ": typ, "lid": lid, "did": did, "iat": iat, "exp": exp, "plan": plan, "dev": dev}
    payload.update(extra)
    payload_bytes = proto.canonical_json(payload)
    return proto.encode_token(payload_bytes, private.sign(proto.signing_message(payload_bytes)))


class FakeServer:
    """Remplace HttpClient : signe avec la clé de test et applique les mêmes règles simples que le vrai serveur."""

    def __init__(self, private: Ed25519PrivateKey, valid_key_body: str | None = None, kid: str = "k1"):
        self.private = private
        self.kid = kid
        self.valid_key_body = valid_key_body
        self.calls: list[tuple[str, dict]] = []
        self.trial_tokens: dict[str, str] = {}
        self.clock = time.time

    def post(self, path: str, body: dict) -> dict:
        self.calls.append((path, body))
        if path == "/v1/activate":
            if proto.normalize_key(body["key"]) != self.valid_key_body:
                raise proto.LicenseError("invalid_key", "Clé inconnue.")
            return {"token": sign_token(self.private, body["did"], kid=self.kid, iat=int(self.clock()))}
        if path == "/v1/trial":
            did = body["did"]
            if did not in self.trial_tokens:
                self.trial_tokens[did] = sign_token(self.private, did, kid=self.kid, typ="trial", lid="trial", iat=int(self.clock()))
            return {"token": self.trial_tokens[did]}
        if path == "/v1/deactivate":
            return {"ok": True}
        raise proto.LicenseError("not_found", "inconnu")
