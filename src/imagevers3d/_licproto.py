"""
_licproto.py - protocole de licence partagé par le logiciel et par le serveur (bibliothèque standard uniquement).

Ce fichier est la SOURCE UNIQUE du format : le serveur en reçoit une copie à la construction de son image
(server/Dockerfile) et les tests vérifient que les deux côtés se comprennent. Il ne contient aucun secret.

Trois objets :
  - la clé de licence  « I3D-XXXXX-XXXXX-XXXXX-XXXXX-XXXXX » : 24 caractères (120 bits) + 1 caractère de contrôle ;
  - l'identifiant d'appareil (« did ») : 32 caractères hexadécimaux, haché, jamais l'identifiant brut de la machine ;
  - le jeton « I3D1.<charge utile>.<signature> » : JSON signé Ed25519 par le serveur, vérifié hors ligne par le logiciel.

Le jeton ne prouve pas à lui seul qu'on a payé : il est lié à UN appareil (did), émis par le serveur uniquement après
un paiement (licence) ou une demande d'essai, et sa signature ne peut pas être fabriquée sans la clé privée du serveur.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
from collections.abc import Mapping

from . import _ed25519

SIGNATURE_DOMAIN = b"I3D-LICENSE-v1\0"  # préfixe de séparation : une signature de licence ne vaut rien ailleurs
TOKEN_PREFIX = "I3D1"
KEY_PREFIX = "I3D"
ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford : sans I, L, O, U
KEY_DATA_CHARS = 24
KEY_LENGTH = KEY_DATA_CHARS + 1  # + caractère de contrôle
TRIAL_DAYS = 7
MAX_DEVICES = 2
PLAN = "personal"
TOKEN_TYPES = ("license", "trial")

_DID_RE = re.compile(r"^[0-9a-f]{32}$")
_FIELD_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")


class LicenseError(RuntimeError):
    """Erreur de licence avec un code stable (pour le programme) et un message en français (pour la personne)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------- base64 sans remplissage

def b64u_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def b64u_decode(text: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (binascii.Error, ValueError) as exc:
        raise LicenseError("invalid_token", "Jeton de licence illisible.") from exc


# ---------------------------------------------------------------- appareil

def make_device_id(raw: str) -> str:
    """Identifiant d'appareil publiable : on ne transmet jamais l'identifiant brut de la machine."""
    return hashlib.sha256(b"I3D-DEVICE-v1|" + raw.strip().lower().encode("utf-8")).hexdigest()[:32]


def is_device_id(value: object) -> bool:
    return isinstance(value, str) and _DID_RE.match(value) is not None


# ---------------------------------------------------------------- clé de licence

def _check_char(data: str) -> str:
    total = sum(ALPHABET.index(c) * (2 * i + 1) for i, c in enumerate(data))  # poids impairs : toute faute isolée est vue
    return ALPHABET[total % 32]


def _crockford(raw: bytes, length: int) -> str:
    number = int.from_bytes(raw, "big")
    return "".join(ALPHABET[(number >> (5 * (length - 1 - i))) & 31] for i in range(length))


def key_body_from_data(data: str) -> str:
    return data + _check_char(data)


def key_body_from_secret(secret: bytes, license_id: str) -> str:
    """Clé de licence DÉRIVÉE de l'identifiant de licence : le serveur peut la réafficher dans l'espace client sans
    jamais la stocker en clair, et une fuite de la base seule ne donne aucune clé."""
    digest = hmac.new(secret, b"I3D-KEY-v1|" + license_id.encode("utf-8"), hashlib.sha256).digest()
    return key_body_from_data(_crockford(digest[:15], KEY_DATA_CHARS))


def display_key(body: str) -> str:
    groups = [body[i : i + 5] for i in range(0, KEY_LENGTH, 5)]
    return KEY_PREFIX + "-" + "-".join(groups)


def normalize_key(text: str) -> str | None:
    """Corps canonique (25 caractères) d'une clé saisie à la main, ou None si elle est mal formée.
    Tolère espaces, tirets, minuscules, l'absence du préfixe et les confusions O/0, I/L/1."""
    if not isinstance(text, str):
        return None
    compact = re.sub(r"[\s\-_]", "", text).upper()
    if len(compact) == len(KEY_PREFIX) + KEY_LENGTH and compact.startswith(KEY_PREFIX):
        compact = compact[len(KEY_PREFIX) :]
    compact = compact.translate(str.maketrans({"O": "0", "I": "1", "L": "1"}))
    if len(compact) != KEY_LENGTH or any(c not in ALPHABET for c in compact):
        return None
    data, check = compact[:-1], compact[-1]
    return compact if _check_char(data) == check else None


def key_lookup_hash(pepper: bytes, body: str) -> str:
    """Empreinte stockée par le serveur pour retrouver une licence à partir de la clé saisie."""
    return hmac.new(pepper, b"I3D-LOOKUP-v1|" + body.encode("ascii"), hashlib.sha256).hexdigest()


# ---------------------------------------------------------------- jeton

def canonical_json(payload: Mapping) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def encode_token(payload_bytes: bytes, signature: bytes) -> str:
    return f"{TOKEN_PREFIX}.{b64u_encode(payload_bytes)}.{b64u_encode(signature)}"


def signing_message(payload_bytes: bytes) -> bytes:
    return SIGNATURE_DOMAIN + payload_bytes


def split_token(token: str) -> tuple[bytes, bytes]:
    if not isinstance(token, str) or len(token) > 2048:
        raise LicenseError("invalid_token", "Jeton de licence illisible.")
    parts = token.strip().split(".")
    if len(parts) != 3 or parts[0] != TOKEN_PREFIX:
        raise LicenseError("invalid_token", "Jeton de licence illisible.")
    return b64u_decode(parts[1]), b64u_decode(parts[2])


def validate_payload(payload: object) -> dict:
    """Contrôle la forme de la charge utile (déjà authentifiée par la signature) ; renvoie un dict propre."""
    bad = LicenseError("invalid_token", "Jeton de licence incomplet.")
    if not isinstance(payload, dict):
        raise bad
    exp = payload.get("exp")
    checks = (
        payload.get("v") == 1,
        isinstance(payload.get("kid"), str) and _FIELD_ID_RE.match(payload["kid"]) is not None,
        payload.get("typ") in TOKEN_TYPES,
        isinstance(payload.get("lid"), str) and _FIELD_ID_RE.match(payload["lid"]) is not None,
        is_device_id(payload.get("did")),
        isinstance(payload.get("iat"), int) and not isinstance(payload.get("iat"), bool),
        exp is None or (isinstance(exp, int) and not isinstance(exp, bool)),
        isinstance(payload.get("plan"), str) and len(payload["plan"]) <= 32,
        isinstance(payload.get("dev"), int) and 1 <= payload["dev"] <= 100,
    )
    if not all(checks):
        raise bad
    if payload["typ"] == "trial" and exp is None:  # un essai a toujours une fin
        raise bad
    return {k: payload[k] for k in ("v", "kid", "typ", "lid", "did", "iat", "exp", "plan", "dev")}


def verify_token(token: str, public_keys: Mapping[str, bytes]) -> dict:
    """Vérifie la signature d'un jeton et renvoie sa charge utile. Lève LicenseError si quoi que ce soit cloche.
    Ne vérifie NI l'appareil NI les dates : c'est le rôle de l'appelant (license.LicenseManager)."""
    payload_bytes, signature = split_token(token)
    try:
        payload = json.loads(payload_bytes.decode("ascii"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise LicenseError("invalid_token", "Jeton de licence illisible.") from exc
    if not isinstance(payload, dict):
        raise LicenseError("invalid_token", "Jeton de licence illisible.")
    key = public_keys.get(payload.get("kid")) if isinstance(payload.get("kid"), str) else None
    if key is None:
        raise LicenseError("unknown_key", "Licence émise avec une clé inconnue de cette version : mets le logiciel à jour.")
    if not _ed25519.verify(key, signing_message(payload_bytes), signature):
        raise LicenseError("bad_signature", "Signature de licence invalide.")
    return validate_payload(payload)
