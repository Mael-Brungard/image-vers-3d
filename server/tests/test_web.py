"""Couche web : API du logiciel, webhook Stripe (signature, idempotence, remboursement), espace client, en-têtes de sécurité."""

import re
import time

import pytest
from server_helpers import WEBHOOK_SECRET, checkout, did, stripe_event
from fastapi.testclient import TestClient

from licenseserver import stripe_hooks
from licenseserver.protocol import LicenseError, proto


def buy(http, clock, session="cs_1", email="client@example.test", payment="pi_1", event_id=None):
    body, headers = stripe_event(clock, "checkout.session.completed", checkout(session, email, payment), event_id=event_id or f"evt_{session}")
    return http.post("/stripe/webhook", content=body, headers=headers)


def last_key(mailer):
    return re.search(r"I3D(?:-[0-9A-Z]{5}){5}", mailer.sent[-1].text).group(0)


# ------------------------------------------------------------------ API du logiciel

def test_activate_endpoint_returns_a_verifiable_token(http, service, mailer, clock):
    assert buy(http, clock).status_code == 200
    key = last_key(mailer)
    response = http.post("/v1/activate", json={"key": key, "did": did("pc1"), "name": "PC de Maël", "app": "0.1.0"})
    assert response.status_code == 200
    payload = proto.verify_token(response.json()["token"], {service.signer.kid: service.signer.public_key})
    assert payload["typ"] == "license" and payload["did"] == did("pc1")


def test_activate_errors_have_codes_status_and_french_messages(http, service, mailer, clock):
    buy(http, clock)
    key = last_key(mailer)
    wrong = proto.display_key(proto.key_body_from_secret(b"z" * 32, "zzz"))
    cases = [
        ({"key": wrong, "did": did("a")}, 403, "invalid_key"),
        ({"key": "I3D-nope", "did": did("a")}, 400, "invalid_key_format"),
        ({"key": key, "did": "nope"}, 400, "bad_request"),
        ({"did": did("a")}, 400, "invalid_key_format"),
    ]
    for body, status, code in cases:
        response = http.post("/v1/activate", json=body)
        assert (response.status_code, response.json()["error"]) == (status, code), body
        assert response.json()["message"]
    http.post("/v1/activate", json={"key": key, "did": did("a")})
    http.post("/v1/activate", json={"key": key, "did": did("b")})
    response = http.post("/v1/activate", json={"key": key, "did": did("c")})
    assert response.status_code == 409 and response.json()["error"] == "device_limit"


def test_api_rejects_non_json_and_oversized_bodies(http):
    assert http.post("/v1/activate", content=b"pas du json").status_code == 400
    assert http.post("/v1/activate", content=b"[1,2]").status_code == 400
    assert http.post("/v1/trial", content=b"x" * 20000).status_code == 400
    assert http.get("/v1/activate").status_code == 405


def test_trial_endpoint_is_idempotent(http):
    first = http.post("/v1/trial", json={"did": did("pc1"), "app": "0.1.0"})
    second = http.post("/v1/trial", json={"did": did("pc1"), "app": "0.1.0"})
    assert first.status_code == 200 and first.json() == second.json()


def test_deactivate_endpoint_frees_the_slot(http, service, mailer, clock):
    buy(http, clock)
    key = last_key(mailer)
    token = http.post("/v1/activate", json={"key": key, "did": did("a")}).json()["token"]
    http.post("/v1/activate", json={"key": key, "did": did("b")})
    assert http.post("/v1/deactivate", json={"token": token}).json() == {"ok": True, "released": True}
    assert http.post("/v1/activate", json={"key": key, "did": did("c")}).status_code == 200
    assert http.post("/v1/deactivate", json={"token": "bidon"}).status_code == 400


def test_unexpected_errors_are_hidden_from_the_client(app, service, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("secret interne : /etc/passwd")

    monkeypatch.setattr(service, "trial", boom)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/v1/trial", json={"did": did("a")})
    assert response.status_code == 500 and "passwd" not in response.text and response.json()["error"] == "server_error"


# ------------------------------------------------------------------ Stripe

def test_purchase_creates_a_license_and_emails_the_key(http, service, mailer, clock):
    response = buy(http, clock)
    assert response.status_code == 200 and response.json()["result"] == "licence créée"
    assert len(mailer.sent) == 1 and mailer.sent[0].to == "client@example.test"
    assert service.account("client@example.test")[0]["key"] == last_key(mailer)


def test_replayed_event_and_replayed_session_create_one_license(http, service, mailer, clock):
    buy(http, clock, event_id="evt_a")
    assert buy(http, clock, event_id="evt_a").json()["result"] == "doublon ignoré"
    assert buy(http, clock, event_id="evt_b").json()["result"] == "licence déjà créée"  # même session, autre événement
    assert len(service.account("client@example.test")) == 1 and len(mailer.sent) == 1


def test_forged_or_stale_webhooks_are_refused(http, service, clock):
    body, headers = stripe_event(clock, "checkout.session.completed", checkout(), secret="whsec_autre")
    assert http.post("/stripe/webhook", content=body, headers=headers).status_code == 400
    body, headers = stripe_event(clock, "checkout.session.completed", checkout(), timestamp=clock.now - 3600)
    assert http.post("/stripe/webhook", content=body, headers=headers).status_code == 400
    body, _ = stripe_event(clock, "checkout.session.completed", checkout())
    assert http.post("/stripe/webhook", content=body).status_code == 400  # pas d'en-tête
    body, headers = stripe_event(clock, "checkout.session.completed", checkout())
    assert http.post("/stripe/webhook", content=body + b" ", headers=headers).status_code == 400  # corps modifié
    assert service.account("client@example.test") == []


def test_unpaid_other_product_and_non_payment_sessions_create_nothing(http, service, clock):
    for index, session in enumerate((checkout(status="unpaid"), checkout(link="plink_autre"), checkout(mode="subscription"))):
        body, headers = stripe_event(clock, "checkout.session.completed", session, event_id=f"evt_{index}")
        assert http.post("/stripe/webhook", content=body, headers=headers).status_code == 200
    assert service.account("client@example.test") == []


def test_delayed_payment_creates_the_license_once_paid(http, service, clock):
    body, headers = stripe_event(clock, "checkout.session.completed", checkout(status="unpaid"), event_id="evt_1")
    http.post("/stripe/webhook", content=body, headers=headers)
    assert service.account("client@example.test") == []
    body, headers = stripe_event(clock, "checkout.session.async_payment_succeeded", checkout(status="paid"), event_id="evt_2")
    http.post("/stripe/webhook", content=body, headers=headers)
    assert len(service.account("client@example.test")) == 1


def test_checkout_without_email_fails_loudly_so_stripe_retries(http, clock):
    session = checkout()
    session["customer_details"] = {}
    body, headers = stripe_event(clock, "checkout.session.completed", session)
    assert http.post("/stripe/webhook", content=body, headers=headers).status_code == 400


def test_full_refund_and_dispute_block_new_activations(http, service, mailer, clock):
    buy(http, clock)
    key = last_key(mailer)
    http.post("/v1/activate", json={"key": key, "did": did("a")})
    body, headers = stripe_event(clock, "charge.refunded", {"payment_intent": "pi_1", "refunded": False}, event_id="evt_r1")
    assert "partiel" in http.post("/stripe/webhook", content=body, headers=headers).json()["result"]
    assert http.post("/v1/activate", json={"key": key, "did": did("b")}).status_code == 200
    body, headers = stripe_event(clock, "charge.refunded", {"payment_intent": "pi_1", "refunded": True}, event_id="evt_r2")
    assert http.post("/stripe/webhook", content=body, headers=headers).json()["result"].startswith("1 licence")
    refused = http.post("/v1/activate", json={"key": key, "did": did("c")})
    assert refused.status_code == 403 and refused.json()["error"] == "revoked"
    buy(http, clock, session="cs_2", payment="pi_2")
    body, headers = stripe_event(clock, "charge.dispute.created", {"payment_intent": "pi_2"}, event_id="evt_d")
    assert http.post("/stripe/webhook", content=body, headers=headers).json()["result"].startswith("1 licence")


def test_unknown_event_types_are_acknowledged(http, clock):
    body, headers = stripe_event(clock, "customer.created", {"id": "cus_1"})
    assert http.post("/stripe/webhook", content=body, headers=headers).json()["result"] == "événement ignoré"


def test_webhook_disabled_without_secret(tmp_path, clock, mailer):
    from server_helpers import make_env

    from licenseserver import web
    from licenseserver.config import Config

    app = web.create_app(Config.from_env(make_env(tmp_path, STRIPE_WEBHOOK_SECRET="")), clock=clock, mailer=mailer)
    with TestClient(app) as client:
        assert client.post("/stripe/webhook", content=b"{}").status_code == 503


def test_signature_check_matches_the_official_stripe_library():
    stripe = pytest.importorskip("stripe")
    payload = b'{"id":"evt_1","type":"x","data":{"object":{}}}'
    now = int(time.time())
    import hashlib
    import hmac

    signature = hmac.new(WEBHOOK_SECRET.encode(), f"{now}.".encode() + payload, hashlib.sha256).hexdigest()
    header = f"t={now},v1={signature}"
    stripe.Webhook.construct_event(payload, header, WEBHOOK_SECRET)  # la bibliothèque officielle accepte
    stripe_hooks.verify_signature(payload, header, WEBHOOK_SECRET, now)  # nous aussi
    for bad_header in (f"t={now},v1={'0' * 64}", f"t={now - 1000},v1={signature}"):
        with pytest.raises(Exception):
            stripe.Webhook.construct_event(payload, bad_header, WEBHOOK_SECRET)
        with pytest.raises(LicenseError):
            stripe_hooks.verify_signature(payload, bad_header, WEBHOOK_SECRET, now)


def test_signature_header_edge_cases():
    now = 1_800_000_000
    for header in (None, "", "garbage", "t=abc,v1=00", "v1=00", f"t={now}"):
        with pytest.raises(LicenseError):
            stripe_hooks.verify_signature(b"{}", header, WEBHOOK_SECRET, now)
    with pytest.raises(LicenseError):
        stripe_hooks.verify_signature(b"{}", f"t={now},v1=00", "", now)


# ------------------------------------------------------------------ espace client (pages)

def log_in(http, service, mailer, email="client@example.test"):
    response = http.post("/login", data={"email": email})
    assert response.status_code == 200
    code = re.search(r"\b(\d{8})\b", mailer.sent[-1].text).group(1)
    return http.post("/verify", data={"email": email, "code": code}, follow_redirects=False)


def test_home_shows_login_and_buy_link(http):
    page = http.get("/")
    assert page.status_code == 200 and "Recevoir un code" in page.text and "https://buy.example.test/x" in page.text
    assert 'lang="fr"' in page.text


def test_login_flow_shows_the_key_and_devices(http, service, mailer, clock):
    buy(http, clock)
    key = last_key(mailer)
    http.post("/v1/activate", json={"key": key, "did": did("pc1"), "name": "<script>alert(1)</script>"})
    response = log_in(http, service, mailer)
    assert response.status_code == 303 and response.headers["location"] == "/account"
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    page = http.get("/account")
    assert key in page.text and "1 / 2 ordinateurs" in page.text
    assert "<script>alert(1)</script>" not in page.text and "&lt;script&gt;" in page.text  # nom d'appareil échappé


def test_account_requires_a_session(http):
    response = http.get("/account", follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/"


def test_login_page_is_neutral_for_unknown_addresses(http, mailer):
    response = http.post("/login", data={"email": "inconnu@example.test"})
    assert response.status_code == 200 and "8 chiffres" in response.text and not mailer.sent


def test_login_rejects_invalid_email_and_wrong_code(http, service, mailer, clock):
    assert http.post("/login", data={"email": "pas-un-mail"}).status_code == 400
    buy(http, clock)
    http.post("/login", data={"email": "client@example.test"})
    response = http.post("/verify", data={"email": "client@example.test", "code": "12345678"})
    assert response.status_code == 400 and "incorrect" in response.text
    assert http.get("/account", follow_redirects=False).status_code == 303


def test_release_from_the_portal_needs_csrf_and_works(http, service, mailer, clock):
    buy(http, clock)
    key = last_key(mailer)
    http.post("/v1/activate", json={"key": key, "did": did("pc1"), "name": "Bureau"})
    log_in(http, service, mailer)
    page = http.get("/account").text
    csrf = re.search(r'name="csrf" value="([^"]+)"', page).group(1)
    license_id = re.search(r'name="license" value="([^"]+)"', page).group(1)
    form = {"license": license_id, "did": did("pc1")}
    assert http.post("/account/release", data={**form, "csrf": "faux"}).status_code == 400
    assert service.account("client@example.test")[0]["devices"]  # rien n'a bougé
    response = http.post("/account/release", data={**form, "csrf": csrf}, follow_redirects=False)
    assert response.status_code == 303 and "m=released" in response.headers["location"]
    assert "Place libérée" in http.get("/account?m=released").text
    assert service.account("client@example.test")[0]["devices"] == []


def test_cross_site_post_is_refused(http, service, mailer, clock):
    buy(http, clock)
    response = http.post("/login", data={"email": "client@example.test"}, headers={"Origin": "https://evil.example"})
    assert response.status_code == 400
    response = http.post("/login", data={"email": "client@example.test"}, headers={"Origin": "null"})
    assert response.status_code == 400
    assert http.post("/login", data={"email": "client@example.test"}, headers={"Origin": "http://127.0.0.1:8000"}).status_code == 200


def test_logout_needs_csrf_and_ends_the_session(http, service, mailer, clock):
    buy(http, clock)
    log_in(http, service, mailer)
    csrf = re.search(r'name="csrf" value="([^"]+)"', http.get("/account").text).group(1)
    http.post("/logout", data={"csrf": "faux"})
    assert http.get("/account", follow_redirects=False).status_code == 200
    http.post("/logout", data={"csrf": csrf})
    assert http.get("/account", follow_redirects=False).status_code == 303


def test_mail_outage_does_not_leak_whether_the_address_is_a_customer(http, service, mailer, clock):
    buy(http, clock)

    def broken(*args, **kwargs):
        raise OSError("smtp en panne")

    mailer.send_code = broken
    response = http.post("/login", data={"email": "client@example.test"})
    assert response.status_code == 200 and "8 chiffres" in response.text


# ------------------------------------------------------------------ en-têtes et divers

def test_security_headers_everywhere(http):
    for path in ("/", "/healthz", "/robots.txt"):
        headers = http.get(path).headers
        assert headers["cache-control"] == "no-store" and headers["x-content-type-options"] == "nosniff"
        assert headers["x-frame-options"] == "DENY" and "frame-ancestors 'none'" in headers["content-security-policy"]
        assert "script-src" not in headers["content-security-policy"] and "default-src 'none'" in headers["content-security-policy"]


def test_api_docs_are_not_exposed(http):
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert http.get(path).status_code == 404


def test_client_ip_uses_last_forwarded_hop_only_when_trusted(tmp_path, clock, mailer):
    from server_helpers import make_env

    from licenseserver import web
    from licenseserver.config import Config

    seen = []
    for trust in ("1", "0"):
        config = Config.from_env(make_env(tmp_path / trust, I3D_TRUST_PROXY=trust))
        app = web.create_app(config, clock=clock, mailer=mailer)
        app.state.service.trial = lambda did_, app_version, ip, seen=seen: seen.append(ip) or "token"
        with TestClient(app, client=("10.0.0.1", 1)) as client:
            client.post("/v1/trial", json={"did": did("a")}, headers={"X-Forwarded-For": "6.6.6.6, 203.0.113.50"})
    assert seen == ["203.0.113.50", "10.0.0.1"]
