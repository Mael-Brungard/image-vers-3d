"""
_ed25519.py - vérification de signatures Ed25519 (RFC 8032) en Python pur.

Pourquoi ne pas utiliser « cryptography » : le logiciel n'a besoin que de VÉRIFIER des signatures (la clé privée ne
quitte jamais le serveur), et un module de 60 lignes sans dépendance native évite d'alourdir l'installation et le
fichier de versions verrouillées. La vérification ne manipule que des données publiques : l'absence de temps constant
n'a donc aucune conséquence. Elle est contrôlée dans tests/test_licensing.py contre les vecteurs de test de la RFC 8032
et contre la bibliothèque « cryptography » (signatures valides, altérées, tronquées, non canoniques).
"""

from __future__ import annotations

import hashlib

_P = 2**255 - 19
_L = 2**252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, _P - 2, _P) % _P
_SQRT_M1 = pow(2, (_P - 1) // 4, _P)


def _inv(x: int) -> int:
    return pow(x, _P - 2, _P)


def _recover_x(y: int, sign: int) -> int | None:
    if y >= _P:
        return None
    x2 = (y * y - 1) * _inv(_D * y * y + 1) % _P
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P != 0:
        x = x * _SQRT_M1 % _P
    if (x * x - x2) % _P != 0:
        return None
    if (x & 1) != sign:
        x = _P - x
    return x


_GY = 4 * _inv(5) % _P
_GX = _recover_x(_GY, 0)
_G = (_GX, _GY, 1, _GX * _GY % _P)
_ZERO = (0, 1, 1, 0)


def _add(p, q):
    a = (p[1] - p[0]) * (q[1] - q[0]) % _P
    b = (p[1] + p[0]) * (q[1] + q[0]) % _P
    c = 2 * p[3] * q[3] * _D % _P
    d = 2 * p[2] * q[2] % _P
    e, f, g, h = b - a, d - c, d + c, b + a
    return (e * f % _P, g * h % _P, f * g % _P, e * h % _P)


def _mul(scalar: int, point):
    result = _ZERO
    while scalar > 0:
        if scalar & 1:
            result = _add(result, point)
        point = _add(point, point)
        scalar >>= 1
    return result


def _same(p, q) -> bool:
    return (p[0] * q[2] - q[0] * p[2]) % _P == 0 and (p[1] * q[2] - q[1] * p[2]) % _P == 0


def _decode(raw: bytes):
    if len(raw) != 32:
        return None
    y = int.from_bytes(raw, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    return None if x is None else (x, y, 1, x * y % _P)


def verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
    """Vrai si `signature` est une signature Ed25519 valide de `message` par `public_key`. Ne lève jamais d'exception."""
    try:
        if len(public_key) != 32 or len(signature) != 64:
            return False
        a = _decode(public_key)
        r = _decode(signature[:32])
        if a is None or r is None:
            return False
        s = int.from_bytes(signature[32:], "little")
        if s >= _L:  # signature non canonique (malléable)
            return False
        h = int.from_bytes(hashlib.sha512(signature[:32] + public_key + message).digest(), "little") % _L
        return _same(_mul(s, _G), _add(r, _mul(h, a)))
    except Exception:  # noqa: BLE001 - une entrée mal formée est simplement « invalide »
        return False
