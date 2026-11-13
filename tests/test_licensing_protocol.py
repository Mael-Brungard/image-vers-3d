"""Protocole de licence : signatures Ed25519 en Python pur (vecteurs RFC 8032 et recoupement avec « cryptography »),
clés de licence (format, tolérance de saisie, détection des fautes) et jetons (forme, signature, altérations)."""

import os
import random
import re

import pytest
from licensing_helpers import make_keypair, sign_token

from imagevers3d import _ed25519, _licproto as proto

RFC8032 = [
    (
        "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",
        "",
        "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b",
    ),
    (
        "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c",
        "72",
        "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00",
    ),
]
DID = "0123456789abcdef0123456789abcdef"


# ------------------------------------------------------------------ Ed25519

@pytest.mark.parametrize("public,message,signature", RFC8032)
def test_rfc8032_vectors(public, message, signature):
    assert _ed25519.verify(bytes.fromhex(public), bytes.fromhex(message), bytes.fromhex(signature))


def test_agrees_with_cryptography_on_random_signatures():
    private, public = make_keypair()
    for size in (0, 1, 31, 64, 300):
        message = os.urandom(size)
        assert _ed25519.verify(public, message, private.sign(message))


def test_rejects_every_single_bit_flip_of_signature_sample():
    private, public = make_keypair()
    message = b"licence"
    signature = bytearray(private.sign(message))
    rng = random.Random(1)
    for _ in range(80):
        corrupted = bytearray(signature)
        corrupted[rng.randrange(64)] ^= 1 << rng.randrange(8)
        assert not _ed25519.verify(public, message, bytes(corrupted))


def test_rejects_altered_message_and_wrong_key():
    private, public = make_keypair()
    _, other_public = make_keypair()
    signature = private.sign(b"abc")
    assert _ed25519.verify(public, b"abc", signature)
    assert not _ed25519.verify(public, b"abd", signature)
    assert not _ed25519.verify(other_public, b"abc", signature)


def test_rejects_malformed_inputs_without_raising():
    private, public = make_keypair()
    signature = private.sign(b"x")
    assert not _ed25519.verify(public[:31], b"x", signature)
    assert not _ed25519.verify(public, b"x", signature[:63])
    assert not _ed25519.verify(public, b"x", signature + b"\0")
    assert not _ed25519.verify(b"\xff" * 32, b"x", signature)  # point invalide
    assert not _ed25519.verify(public, b"x", b"\x00" * 64)


def test_rejects_non_canonical_s():
    private, public = make_keypair()
    signature = private.sign(b"x")
    s = int.from_bytes(signature[32:], "little") + _ed25519._L
    if s < 2**256:  # S + L tient sur 32 octets : signature malléable, doit être refusée
        assert not _ed25519.verify(public, b"x", signature[:32] + s.to_bytes(32, "little"))


# ------------------------------------------------------------------ clé de licence

KEY_RE = re.compile(r"^I3D(-[0-9A-HJKMNP-TV-Z]{5}){5}$")


def test_derived_key_is_stable_distinct_and_well_formed():
    secret = b"s" * 32
    first = proto.display_key(proto.key_body_from_secret(secret, "lic-1"))
    assert KEY_RE.match(first)
    assert first == proto.display_key(proto.key_body_from_secret(secret, "lic-1"))
    assert first != proto.display_key(proto.key_body_from_secret(secret, "lic-2"))
    assert first != proto.display_key(proto.key_body_from_secret(b"t" * 32, "lic-1"))


def test_normalize_accepts_common_typing_variants():
    body = proto.key_body_from_secret(b"s" * 32, "lic-1")
    shown = proto.display_key(body)
    assert proto.normalize_key(shown) == body
    assert proto.normalize_key(shown.lower()) == body
    assert proto.normalize_key(shown.replace("-", " ")) == body
    assert proto.normalize_key("  " + shown + "\n") == body
    assert proto.normalize_key(shown[4:]) == body  # sans le préfixe I3D


def test_normalize_tolerates_look_alike_letters():
    # 0/O et 1/I/L sont interchangeables à la saisie : on fabrique une clé qui contient ces chiffres.
    for number in range(2000):
        body = proto.key_body_from_secret(b"k" * 32, f"x{number}")
        if "0" in body and "1" in body:
            text = proto.display_key(body).replace("0", "O").replace("1", "l")
            assert proto.normalize_key(text) == body
            return
    pytest.fail("aucune clé d'essai ne contient à la fois 0 et 1")


def test_check_char_catches_every_single_character_error():
    body = proto.key_body_from_secret(b"s" * 32, "lic-1")
    for position in range(len(body) - 1):
        for letter in proto.ALPHABET:
            if letter == body[position]:
                continue
            altered = body[:position] + letter + body[position + 1 :]
            assert proto.normalize_key(altered) is None, (position, letter)


def test_check_char_catches_most_adjacent_swaps():
    """Une inversion de deux caractères voisins n'est manquée que si leurs valeurs diffèrent de 16 : environ 3 % des cas."""
    missed = total = 0
    for number in range(200):
        body = proto.key_body_from_secret(b"s" * 32, f"swap-{number}")
        for i in range(len(body) - 2):
            if body[i] == body[i + 1]:
                continue
            swapped = body[:i] + body[i + 1] + body[i] + body[i + 2 :]
            total += 1
            missed += proto.normalize_key(swapped) is not None
    assert missed / total < 0.06


@pytest.mark.parametrize("bad", ["", "I3D", "hello", "I3D-AAAAA-AAAAA-AAAAA-AAAAA", None, 12, "I3D-" + "U" * 25])
def test_normalize_rejects_garbage(bad):
    assert proto.normalize_key(bad) is None


def test_lookup_hash_depends_on_pepper():
    body = proto.key_body_from_secret(b"s" * 32, "lic-1")
    assert proto.key_lookup_hash(b"a" * 32, body) != proto.key_lookup_hash(b"b" * 32, body)
    assert len(proto.key_lookup_hash(b"a" * 32, body)) == 64


# ------------------------------------------------------------------ appareil

def test_device_id_is_hashed_stable_and_not_the_raw_value():
    did = proto.make_device_id("win:ABC-123")
    assert proto.is_device_id(did) and did == proto.make_device_id(" WIN:abc-123 ")
    assert len(did) == 32 and "abc-123" not in did
    assert did != proto.make_device_id("win:ABC-124")
    assert not proto.is_device_id("XYZ") and not proto.is_device_id(None) and not proto.is_device_id(did.upper())


# ------------------------------------------------------------------ jeton

def test_valid_token_round_trip():
    private, public = make_keypair()
    token = sign_token(private, DID, iat=1_700_000_000)
    payload = proto.verify_token(token, {"k1": public})
    assert payload["did"] == DID and payload["typ"] == "license" and payload["exp"] is None and payload["dev"] == 2


def test_trial_token_has_an_expiry():
    private, public = make_keypair()
    payload = proto.verify_token(sign_token(private, DID, typ="trial", lid="trial", iat=1000), {"k1": public})
    assert payload["exp"] == 1000 + 7 * 86400


def test_unknown_kid_is_refused_with_update_hint():
    private, public = make_keypair()
    with pytest.raises(proto.LicenseError) as error:
        proto.verify_token(sign_token(private, DID, kid="k9"), {"k1": public})
    assert error.value.code == "unknown_key"


def test_wrong_key_and_tampered_payload_are_refused():
    private, public = make_keypair()
    _, other_public = make_keypair()
    token = sign_token(private, DID)
    with pytest.raises(proto.LicenseError) as error:
        proto.verify_token(token, {"k1": other_public})
    assert error.value.code == "bad_signature"
    head, payload, signature = token.split(".")
    forged_payload = proto.b64u_encode(proto.b64u_decode(payload).replace(b'"license"', b'"trial__"'))
    with pytest.raises(proto.LicenseError):
        proto.verify_token(".".join((head, forged_payload, signature)), {"k1": public})


def test_signature_without_domain_prefix_is_refused():
    private, public = make_keypair()
    payload_bytes = proto.canonical_json({"v": 1, "kid": "k1", "typ": "license", "lid": "L", "did": DID, "iat": 1, "exp": None, "plan": "personal", "dev": 2})
    token = proto.encode_token(payload_bytes, private.sign(payload_bytes))  # signé SANS le préfixe de domaine
    with pytest.raises(proto.LicenseError) as error:
        proto.verify_token(token, {"k1": public})
    assert error.value.code == "bad_signature"


@pytest.mark.parametrize(
    "extra",
    [
        {"typ": "admin"},
        {"did": "not-a-device"},
        {"iat": True},
        {"iat": "1"},
        {"exp": "never"},
        {"dev": 0},
        {"dev": 1000},
        {"lid": ""},
        {"lid": "a b"},
        {"v": 2},
    ],
)
def test_authentic_but_malformed_payload_is_refused(extra):
    private, public = make_keypair()
    with pytest.raises(proto.LicenseError) as error:
        proto.verify_token(sign_token(private, **{"did": DID, **extra}), {"k1": public})
    assert error.value.code in ("invalid_token", "bad_signature")


def test_trial_without_expiry_is_refused():
    private, public = make_keypair()
    with pytest.raises(proto.LicenseError):
        proto.verify_token(sign_token(private, DID, typ="trial", exp=None), {"k1": public})


@pytest.mark.parametrize("token", ["", "garbage", "I3D1.a.b", "I3D2.aaa.bbb", "I3D1..", "I3D1." + "A" * 3000 + ".B", None, 42, "I3D1.%%%.%%%"])
def test_garbage_tokens_never_crash(token):
    _, public = make_keypair()
    with pytest.raises(proto.LicenseError):
        proto.verify_token(token, {"k1": public})
