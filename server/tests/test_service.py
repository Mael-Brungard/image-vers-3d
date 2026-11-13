"""Règles métier : licences, activations sur 2 appareils, essai unique, libérations, comptes par code e-mail."""

import re
from concurrent.futures import ThreadPoolExecutor

import pytest
from server_helpers import did

from licenseserver.protocol import LicenseError, proto

DAY = 86400


def new_license(service, email="client@example.test", **kwargs):
    lic, key, _ = service.create_license(email, source="admin", **kwargs)
    return lic, key


def activate(service, key, name, ip="198.51.100.1"):
    return service.activate(key, did(name), name, "0.1.0", ip)


def code_from_mail(mailer):
    return re.search(r"\b(\d{8})\b", mailer.sent[-1].text).group(1)


# ------------------------------------------------------------------ création de licences

def test_license_creation_sends_key_and_is_idempotent_per_source(service, mailer):
    lic, key, created = service.create_license("Client@Example.test ", source="stripe", source_ref="cs_1", payment_ref="pi_1")
    assert created and lic["email"] == "client@example.test" and lic["max_devices"] == 2
    assert proto.normalize_key(key) is not None
    assert len(mailer.sent) == 1 and key in mailer.sent[0].text and "https://example.test/download" in mailer.sent[0].text
    again, same_key, created = service.create_license("client@example.test", source="stripe", source_ref="cs_1")
    assert not created and again["id"] == lic["id"] and same_key == key
    assert len(mailer.sent) == 1  # pas de second e-mail


def test_two_purchases_give_two_distinct_keys(service):
    _, first = new_license(service)
    _, second = new_license(service)
    assert first != second


def test_database_never_stores_the_key_itself(service):
    lic, key = new_license(service)
    body = proto.normalize_key(key)
    with service.db.tx() as conn:
        dump = " ".join(str(tuple(row)) for table in ("licenses", "activations", "audit") for row in conn.execute(f"SELECT * FROM {table}"))
    assert body not in dump and key not in dump


def test_invalid_email_is_refused(service):
    for bad in ("", "pas-un-mail", "a@b", None, 12, "a b@c.fr"):
        with pytest.raises(LicenseError) as error:
            service.create_license(bad, source="admin")
        assert error.value.code == "invalid_email"


def test_mail_failure_does_not_lose_the_license(service, mailer):
    def broken(*args, **kwargs):
        raise OSError("smtp en panne")

    mailer.send_license = broken
    lic, key, created = service.create_license("client@example.test", source="admin")
    assert created and service.get_license(lic["id"]) is not None
    with service.db.tx() as conn:
        assert conn.execute("SELECT COUNT(*) FROM audit WHERE kind = 'mail_failed'").fetchone()[0] == 1


# ------------------------------------------------------------------ activation

def test_activation_returns_a_token_the_software_accepts(service):
    lic, key = new_license(service)
    token = activate(service, key, "pc1")
    payload = service.signer.verify_own(token)
    assert payload["typ"] == "license" and payload["lid"] == lic["id"] and payload["did"] == did("pc1")
    assert payload["exp"] is None and payload["dev"] == 2


def test_same_device_can_activate_again_without_using_a_second_slot(service):
    _, key = new_license(service)
    first = activate(service, key, "pc1")
    second = activate(service, key, "pc1")
    assert service.signer.verify_own(first)["did"] == service.signer.verify_own(second)["did"]
    activate(service, key, "pc2")  # la deuxième place est bien libre


def test_third_device_is_refused_with_a_clear_message(service):
    _, key = new_license(service)
    activate(service, key, "pc1")
    activate(service, key, "pc2")
    with pytest.raises(LicenseError) as error:
        activate(service, key, "pc3")
    assert error.value.code == "device_limit" and "2 ordinateurs" in error.value.message


def test_key_typed_loosely_still_activates(service):
    _, key = new_license(service)
    assert activate(service, "  " + key.lower().replace("-", " ") + "\n", "pc1")


def test_unknown_key_and_malformed_key(service):
    other = proto.display_key(proto.key_body_from_secret(b"z" * 32, "zzz"))
    with pytest.raises(LicenseError) as error:
        activate(service, other, "pc1")
    assert error.value.code == "invalid_key"
    with pytest.raises(LicenseError) as error:
        activate(service, "I3D-n-importe-quoi", "pc1")
    assert error.value.code == "invalid_key_format"
    with pytest.raises(LicenseError) as error:
        service.activate("x", "pas-un-did", "pc", "1", None)
    assert error.value.code == "bad_request"


def test_wrong_keys_are_rate_limited_per_connection(service):
    _, key = new_license(service)
    wrong = proto.display_key(proto.key_body_from_secret(b"z" * 32, "zzz"))
    for _ in range(10):
        with pytest.raises(LicenseError) as error:
            activate(service, wrong, "pc1", ip="198.51.100.9")
        assert error.value.code == "invalid_key"
    with pytest.raises(LicenseError) as error:
        activate(service, key, "pc1", ip="198.51.100.9")  # même la BONNE clé est refusée depuis cette connexion
    assert error.value.code == "rate_limited"
    assert activate(service, key, "pc1", ip="198.51.100.10")  # une autre connexion n'est pas touchée


def test_rate_limit_window_expires(service, clock):
    _, key = new_license(service)
    wrong = proto.display_key(proto.key_body_from_secret(b"z" * 32, "zzz"))
    for _ in range(10):
        with pytest.raises(LicenseError):
            activate(service, wrong, "pc1", ip="198.51.100.9")
    clock.advance(3601)
    assert activate(service, key, "pc1", ip="198.51.100.9")


def test_simultaneous_activations_never_exceed_the_limit(service):
    _, key = new_license(service)

    def attempt(number):
        try:
            activate(service, key, f"pc{number}", ip=f"198.51.100.{number}")
            return "ok"
        except LicenseError as exc:
            return exc.code

    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(attempt, range(8)))
    assert results.count("ok") == 2 and results.count("device_limit") == 6


def test_revoked_license_cannot_activate_new_devices(service):
    lic, key = new_license(service)
    activate(service, key, "pc1")
    assert service.revoke(lic["id"], "remboursement")
    with pytest.raises(LicenseError) as error:
        activate(service, key, "pc2")
    assert error.value.code == "revoked"
    with pytest.raises(LicenseError):
        activate(service, key, "pc1")  # même réactivation du premier poste
    assert service.restore(lic["id"])
    assert activate(service, key, "pc2")


def test_revoke_by_payment_targets_only_that_payment(service):
    first, _ = new_license(service, email="a@example.test")
    service.create_license("b@example.test", source="stripe", source_ref="cs_b", payment_ref="pi_b", send_mail=False)
    assert service.revoke_by_payment("pi_b", "remboursement") == 1
    assert service.get_license(first["id"])["status"] == "active"
    assert service.revoke_by_payment("pi_b", "remboursement") == 0  # déjà fait


# ------------------------------------------------------------------ libération d'une place

def test_release_from_the_software_frees_a_slot(service):
    _, key = new_license(service)
    token = activate(service, key, "pc1")
    activate(service, key, "pc2")
    assert service.deactivate_with_token(token) is True
    assert service.deactivate_with_token(token) is False  # déjà libéré : sans effet
    assert activate(service, key, "pc3")


def test_release_needs_a_token_signed_by_this_server(service):
    from licenseserver.signing import Signer, generate_seed

    foreign = Signer(generate_seed(), service.signer.kid).token(typ="license", license_id="L1", did=did("x"), issued_at=1, expires_at=None, max_devices=2)
    for bad in (foreign, "garbage", None, 12):
        with pytest.raises(LicenseError):
            service.deactivate_with_token(bad)


def test_trial_token_cannot_release_a_license(service):
    token = service.trial(did("pc1"), "0.1.0", None)
    with pytest.raises(LicenseError) as error:
        service.deactivate_with_token(token)
    assert error.value.code == "not_a_license"


def test_transfer_budget_is_limited_per_year(service, clock):
    _, key = new_license(service)
    for number in range(3):
        token = activate(service, key, f"pc{number}")
        assert service.deactivate_with_token(token)
    token = activate(service, key, "pc9")
    with pytest.raises(LicenseError) as error:
        service.deactivate_with_token(token)
    assert error.value.code == "transfer_limit"
    clock.advance(366 * DAY)
    assert service.deactivate_with_token(token)  # le quota se renouvelle


def test_admin_release_does_not_consume_the_quota(service):
    lic, key = new_license(service)
    for number in range(5):
        activate(service, key, f"pc{number % 2}")
        assert service.admin_release(lic["id"], did(f"pc{number % 2}"))
    assert service.account(lic["email"])[0]["transfers_left"] == 3


# ------------------------------------------------------------------ essai

def test_trial_is_seven_days_and_idempotent(service, clock):
    first = service.trial(did("pc1"), "0.1.0", "198.51.100.1")
    payload = service.signer.verify_own(first)
    assert payload["typ"] == "trial" and payload["exp"] - payload["iat"] == 7 * DAY and payload["dev"] == 1
    clock.advance(10 * DAY)
    assert service.trial(did("pc1"), "0.1.0", "198.51.100.1") == first  # redemander ne prolonge pas


def test_trial_per_connection_cap(service):
    for number in range(5):
        service.trial(did(f"pc{number}"), "0.1.0", "198.51.100.1")
    with pytest.raises(LicenseError) as error:
        service.trial(did("pc5"), "0.1.0", "198.51.100.1")
    assert error.value.code == "trial_refused"
    assert service.trial(did("pc5"), "0.1.0", "198.51.100.2")
    assert service.trial(did("pc0"), "0.1.0", "198.51.100.1")  # un poste déjà connu reste servi


def test_trial_cap_resets_after_a_month(service, clock):
    for number in range(5):
        service.trial(did(f"pc{number}"), "0.1.0", "198.51.100.1")
    clock.advance(31 * DAY)
    assert service.trial(did("pc5"), "0.1.0", "198.51.100.1")


def test_trial_rejects_bad_device_id(service):
    with pytest.raises(LicenseError):
        service.trial("n'importe quoi", "0.1.0", None)


# ------------------------------------------------------------------ espace client

def test_login_by_email_code(service, mailer):
    lic, key = new_license(service)
    mailer.sent.clear()
    assert service.request_code("Client@Example.test", "198.51.100.1") is True
    code = code_from_mail(mailer)
    cookie, csrf, email, _ = service.verify_code("client@example.test", code, "198.51.100.1")
    assert email == "client@example.test" and service.session(cookie)["csrf"] == csrf
    assert service.account(email)[0]["key"] == key
    service.logout(cookie)
    assert service.session(cookie) is None


def test_unknown_email_gets_no_mail_and_no_error(service, mailer):
    assert service.request_code("inconnu@example.test", "198.51.100.1") is False
    assert not mailer.sent


def test_code_is_single_use_expires_and_has_five_attempts(service, mailer, clock):
    new_license(service)
    mailer.sent.clear()
    service.request_code("client@example.test", None)
    code = code_from_mail(mailer)
    service.verify_code("client@example.test", code, None)
    with pytest.raises(LicenseError):  # déjà utilisé
        service.verify_code("client@example.test", code, None)

    service.request_code("client@example.test", None)
    good = code_from_mail(mailer)
    wrong = "00000000" if good != "00000000" else "11111111"
    for _ in range(5):
        with pytest.raises(LicenseError):
            service.verify_code("client@example.test", wrong, None)
    with pytest.raises(LicenseError):  # le bon code ne marche plus après 5 échecs
        service.verify_code("client@example.test", good, None)

    service.request_code("client@example.test", None)
    late = code_from_mail(mailer)
    clock.advance(601)
    with pytest.raises(LicenseError):
        service.verify_code("client@example.test", late, None)


def test_code_requests_are_rate_limited(service):
    new_license(service)
    for _ in range(5):
        service.request_code("client@example.test", None)
    with pytest.raises(LicenseError) as error:
        service.request_code("client@example.test", None)
    assert error.value.code == "rate_limited"


def test_session_expires(service, mailer, clock):
    new_license(service)
    service.request_code("client@example.test", None)
    cookie, *_ = service.verify_code("client@example.test", code_from_mail(mailer), None)
    clock.advance(15 * DAY)
    assert service.session(cookie) is None


def test_portal_release_requires_ownership(service):
    lic, key = new_license(service, email="a@example.test")
    activate(service, key, "pc1")
    with pytest.raises(LicenseError) as error:
        service.release_from_portal("autre@example.test", lic["id"], did("pc1"))
    assert error.value.code == "not_found"
    assert service.release_from_portal("a@example.test", lic["id"], did("pc1")) is True


def test_account_lists_only_own_licenses(service):
    new_license(service, email="a@example.test")
    new_license(service, email="b@example.test")
    assert len(service.account("a@example.test")) == 1 and service.account("c@example.test") == []
