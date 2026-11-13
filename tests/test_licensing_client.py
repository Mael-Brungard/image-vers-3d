"""Côté logiciel : état de licence, essai de 7 jours, activation unique, recul d'horloge, appareil, contrôle `require`,
réglages de développement (refusés dans une version compilée) et appels HTTP."""

import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from licensing_helpers import FakeServer, make_keypair, sign_token

from imagevers3d import _licproto as proto
from imagevers3d import license as lic

DAY = 86400
T0 = 1_800_000_000
KEY_BODY = proto.key_body_from_secret(b"s" * 32, "lic-1")
KEY_TEXT = proto.display_key(KEY_BODY)


class Clock:
    def __init__(self, now=T0):
        self.now = now

    def __call__(self):
        return self.now


@pytest.fixture()
def env(tmp_path):
    private, public = make_keypair()
    clock = Clock()
    did = proto.make_device_id("test-machine")
    server = FakeServer(private, KEY_BODY)
    server.clock = clock
    manager = lic.LicenseManager(tmp_path, clock=clock, device_id=did, client=server, keys={"k1": public})
    return type("Env", (), {"private": private, "public": public, "clock": clock, "did": did, "server": server, "manager": manager, "dir": tmp_path})


def write_state(env, **data):
    (env.dir / lic.STATE_FILE_NAME).write_text(json.dumps(data), encoding="utf-8")


# ------------------------------------------------------------------ état initial

def test_no_licence_by_default(env):
    status = env.manager.status()
    assert status.state == "none" and not status.allowed
    with pytest.raises(lic.LicenseError) as error:
        env.manager.require()
    assert error.value.code == "license_required"


def test_unreadable_state_file_is_treated_as_empty(env):
    (env.dir / lic.STATE_FILE_NAME).write_text("{ pas du json", encoding="utf-8")
    assert env.manager.status().state == "none"
    (env.dir / lic.STATE_FILE_NAME).write_text("[1, 2]", encoding="utf-8")
    assert env.manager.status().state == "none"


# ------------------------------------------------------------------ essai

def test_trial_lasts_seven_days_then_stops(env):
    status = env.manager.start_trial()
    assert status.state == "trial" and status.allowed and status.days_left == 7
    env.clock.now += 3 * DAY + 100
    assert env.manager.status().days_left == 4
    env.clock.now = T0 + 7 * DAY - 1
    assert env.manager.status().state == "trial"
    env.clock.now = T0 + 7 * DAY
    status = env.manager.status()
    assert status.state == "trial_expired" and not status.allowed
    with pytest.raises(lic.LicenseError) as error:
        env.manager.require()
    assert error.value.code == "trial_expired"


def test_trial_cannot_be_restarted_by_deleting_the_state_file(env):
    env.manager.start_trial()
    env.clock.now = T0 + 9 * DAY
    (env.dir / lic.STATE_FILE_NAME).unlink()
    status = env.manager.start_trial()  # le serveur renvoie le MÊME jeton, donc déjà expiré
    assert status.state == "trial_expired"
    assert len({call[1]["did"] for call in env.server.calls}) == 1


def test_trial_is_not_restarted_while_running_or_expired(env):
    env.manager.start_trial()
    env.manager.start_trial()
    assert [c[0] for c in env.server.calls].count("/v1/trial") == 1


def test_clock_rollback_blocks_the_trial(env):
    env.manager.start_trial()
    env.clock.now = T0 + 5 * DAY
    assert env.manager.status().state == "trial"
    env.clock.now = T0 + 1 * DAY  # on remonte l'horloge de 4 jours pour « gagner » du temps
    status = env.manager.status()
    assert status.state == "clock" and not status.allowed
    assert env.manager.require.__self__ is env.manager
    with pytest.raises(lic.LicenseError) as error:
        env.manager.require()
    assert error.value.code == "clock_tampered"
    env.clock.now = T0 + 5 * DAY + 10  # heure remise correctement : l'essai reprend
    assert env.manager.status().state == "trial"


def test_small_clock_correction_is_tolerated(env):
    env.manager.start_trial()
    env.clock.now = T0 + 2 * DAY
    env.manager.status()
    env.clock.now = T0 + 2 * DAY - 3600
    assert env.manager.status().state == "trial"


def test_editing_the_last_seen_time_is_detected(env):
    env.manager.start_trial()
    env.clock.now = T0 + 3 * DAY
    env.manager.status()
    data = json.loads((env.dir / lic.STATE_FILE_NAME).read_text(encoding="utf-8"))
    data["seen"] = T0  # l'utilisateur « rajeunit » l'horodatage à la main
    (env.dir / lic.STATE_FILE_NAME).write_text(json.dumps(data), encoding="utf-8")
    assert env.manager.status().state == "clock"


def test_clock_state_cannot_be_reset_by_asking_for_a_new_trial(env):
    env.manager.start_trial()
    env.clock.now = T0 + 5 * DAY
    env.manager.status()
    env.clock.now = T0 + 1 * DAY
    assert env.manager.start_trial().state == "clock"
    assert env.manager.status().state == "clock"


# ------------------------------------------------------------------ licence

def test_activation_stores_a_perpetual_licence_usable_offline(env):
    status = env.manager.activate(KEY_TEXT.lower())  # saisie tolérante
    assert status.state == "licensed" and status.days_left is None and status.allowed
    activate_calls = [c for c in env.server.calls if c[0] == "/v1/activate"]
    assert len(activate_calls) == 1 and activate_calls[0][1]["key"] == KEY_TEXT and activate_calls[0][1]["did"] == env.did
    # Plus aucun appel réseau ensuite, même dix ans plus tard ou après un redémarrage.
    env.clock.now = T0 + 3650 * DAY
    fresh = lic.LicenseManager(env.dir, clock=env.clock, device_id=env.did, client=None, keys={"k1": env.public})
    fresh._client = None  # tout appel réseau planterait
    assert fresh.status().state == "licensed" and fresh.require().allowed


def test_licence_replaces_a_running_trial(env):
    env.manager.start_trial()
    assert env.manager.activate(KEY_TEXT).state == "licensed"
    env.clock.now += 30 * DAY
    assert env.manager.status().state == "licensed"


def test_licence_ignores_clock_games(env):
    env.manager.activate(KEY_TEXT)
    env.clock.now = T0 - 400 * DAY
    assert env.manager.status().state == "licensed"


def test_wrong_key_and_bad_format_are_reported(env):
    with pytest.raises(lic.LicenseError) as error:
        env.manager.activate("n'importe quoi")
    assert error.value.code == "invalid_key_format"
    assert not env.server.calls
    other = proto.display_key(proto.key_body_from_secret(b"z" * 32, "autre"))
    with pytest.raises(lic.LicenseError) as error:
        env.manager.activate(other)
    assert error.value.code == "invalid_key"
    assert env.manager.status().state == "none"


def test_token_copied_from_another_computer_is_refused(env, tmp_path):
    env.manager.activate(KEY_TEXT)
    other_dir = tmp_path / "autre"
    other_dir.mkdir()
    (other_dir / lic.STATE_FILE_NAME).write_bytes((env.dir / lic.STATE_FILE_NAME).read_bytes())
    other = lic.LicenseManager(other_dir, clock=env.clock, device_id=proto.make_device_id("autre-machine"), client=env.server, keys={"k1": env.public})
    status = other.status()
    assert status.state == "invalid" and not status.allowed


def test_forged_token_is_refused(env):
    intruder, _ = make_keypair()
    write_state(env, token=sign_token(intruder, env.did))
    status = env.manager.status()
    assert status.state == "invalid" and "invalide" in status.message.lower()


def test_edited_token_is_refused(env):
    env.manager.activate(KEY_TEXT)
    data = json.loads((env.dir / lic.STATE_FILE_NAME).read_text(encoding="utf-8"))
    head, payload, signature = data["token"].split(".")
    forged = proto.b64u_decode(payload).replace(b'"typ":"license"', b'"typ":"license"').replace(b'"dev":2', b'"dev":9')
    data["token"] = ".".join((head, proto.b64u_encode(forged), signature))
    (env.dir / lic.STATE_FILE_NAME).write_text(json.dumps(data), encoding="utf-8")
    fresh = lic.LicenseManager(env.dir, clock=env.clock, device_id=env.did, client=env.server, keys={"k1": env.public})
    assert fresh.status().state == "invalid"


def test_server_answer_for_another_device_or_type_is_rejected(env):
    class Liar:
        def post(self, path, body):
            return {"token": sign_token(env.private, proto.make_device_id("quelqu-un-d-autre"))}

    manager = lic.LicenseManager(env.dir, clock=env.clock, device_id=env.did, client=Liar(), keys={"k1": env.public})
    with pytest.raises(lic.LicenseError) as error:
        manager.activate(KEY_TEXT)
    assert error.value.code == "bad_response"

    class WrongType:
        def post(self, path, body):
            return {"token": sign_token(env.private, env.did)}  # licence renvoyée à une demande d'essai

    manager = lic.LicenseManager(env.dir, clock=env.clock, device_id=env.did, client=WrongType(), keys={"k1": env.public})
    with pytest.raises(lic.LicenseError):
        manager.start_trial()
    assert manager.status().state == "none"


def test_deactivate_frees_the_slot_and_removes_the_licence(env):
    env.manager.activate(KEY_TEXT)
    assert env.manager.deactivate().state == "none"
    sent = [c for c in env.server.calls if c[0] == "/v1/deactivate"]
    assert len(sent) == 1 and sent[0][1]["token"].startswith("I3D1.")
    assert env.manager.activate(KEY_TEXT).state == "licensed"  # on peut réactiver


def test_trial_cannot_be_deactivated_as_a_licence(env):
    env.manager.start_trial()
    with pytest.raises(lic.LicenseError) as error:
        env.manager.deactivate()
    assert error.value.code == "not_a_license"


def test_failed_deactivation_keeps_the_licence(env):
    env.manager.activate(KEY_TEXT)

    class Offline:
        def post(self, path, body):
            raise lic.LicenseError("network", "hors ligne")

    env.manager._client = Offline()
    with pytest.raises(lic.LicenseError):
        env.manager.deactivate()
    assert env.manager.status().state == "licensed"


# ------------------------------------------------------------------ module : instance du processus

def test_module_require_uses_the_installed_manager(env):
    lic.set_manager(env.manager)
    try:
        with pytest.raises(lic.LicenseError):
            lic.require()
        env.manager.activate(KEY_TEXT)
        assert lic.require().state == "licensed"
    finally:
        lic.set_manager(None)


# ------------------------------------------------------------------ réglages de développement

def test_dev_public_key_is_only_honoured_in_source_form(monkeypatch):
    _, public = make_keypair()
    monkeypatch.setenv("IMAGEVERS3D_DEV_LICENSE_PUBKEY", base64.b64encode(public).decode())
    monkeypatch.setattr(lic, "is_compiled", lambda: False)
    assert lic.public_keys().get("dev") == public
    monkeypatch.setattr(lic, "is_compiled", lambda: True)
    assert "dev" not in lic.public_keys()


def test_dev_server_url_is_ignored_in_a_compiled_build(monkeypatch):
    monkeypatch.setenv("IMAGEVERS3D_LICENSE_URL", "http://127.0.0.1:1/")
    monkeypatch.setattr(lic, "is_compiled", lambda: False)
    assert lic.server_url() == "http://127.0.0.1:1"
    monkeypatch.setattr(lic, "is_compiled", lambda: True)
    assert lic.server_url() == lic._license_keys.SERVER_URL.rstrip("/")


def test_source_form_is_detected_as_not_compiled():
    assert lic.is_compiled() is False


def test_bad_dev_key_values_are_ignored(monkeypatch):
    monkeypatch.setattr(lic, "is_compiled", lambda: False)
    for value in ("***", base64.b64encode(b"court").decode()):
        monkeypatch.setenv("IMAGEVERS3D_DEV_LICENSE_PUBKEY", value)
        assert "dev" not in lic.public_keys()


def test_embedded_keys_are_decoded(monkeypatch):
    monkeypatch.delenv("IMAGEVERS3D_DEV_LICENSE_PUBKEY", raising=False)
    _, public = make_keypair()
    monkeypatch.setattr(lic._license_keys, "KEYS", {"k1": base64.b64encode(public).decode(), "bad": "!!", "short": "AAAA"})
    assert lic.public_keys() == {"k1": public}


# ------------------------------------------------------------------ appareil

def test_machine_id_fallback_is_created_once(tmp_path, monkeypatch):
    monkeypatch.setattr(lic.sys, "platform", "darwin")
    monkeypatch.setattr(lic, "_UNIX_MACHINE_ID_FILES", ())
    first = lic.read_machine_id(tmp_path)
    assert first.startswith("local:") and lic.read_machine_id(tmp_path) == first
    assert (tmp_path / "device.id").read_text(encoding="ascii") == first[len("local:") :]


def test_device_id_of_the_manager_is_hashed(tmp_path):
    manager = lic.LicenseManager(tmp_path)
    assert proto.is_device_id(manager.device_id) and manager.device_id == lic.LicenseManager(tmp_path).device_id


# ------------------------------------------------------------------ HTTP

class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        if self.path == "/v1/ok":
            status, payload = 200, {"echo": body, "agent": self.headers.get("User-Agent")}
        elif self.path == "/v1/refuse":
            status, payload = 403, {"error": "revoked", "message": "Cette licence a été remboursée."}
        elif self.path == "/v1/html":
            status, payload = 502, None
        else:
            status, payload = 200, ["pas", "un", "objet"]
        raw = b"<html>bad gateway</html>" if payload is None else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


@pytest.fixture()
def http_url():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def test_http_client_success_and_user_agent(http_url):
    data = lic.HttpClient(http_url).post("/v1/ok", {"a": 1})
    assert data["echo"] == {"a": 1} and data["agent"].startswith("ImageVers3D/")


def test_http_client_maps_server_errors(http_url):
    with pytest.raises(lic.LicenseError) as error:
        lic.HttpClient(http_url).post("/v1/refuse", {})
    assert error.value.code == "revoked" and "remboursée" in error.value.message
    with pytest.raises(lic.LicenseError) as error:
        lic.HttpClient(http_url).post("/v1/html", {})
    assert error.value.code == "http_502"
    with pytest.raises(lic.LicenseError) as error:
        lic.HttpClient(http_url).post("/v1/list", {})
    assert error.value.code == "bad_response"


def test_http_client_reports_network_failure_and_missing_server():
    with pytest.raises(lic.LicenseError) as error:
        lic.HttpClient("http://127.0.0.1:9", timeout=2).post("/v1/ok", {})
    assert error.value.code == "network"
    with pytest.raises(lic.LicenseError) as error:
        lic.HttpClient("").post("/v1/ok", {})
    assert error.value.code == "no_server"
