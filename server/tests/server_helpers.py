"""Outils communs aux tests du serveur (importés par conftest.py et par les tests)."""

import base64
import hashlib
import hmac
import json
import sys
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1]
SRC = SERVER.parent / "src"
for folder in (SERVER, SRC):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

from licenseserver.protocol import proto  # noqa: E402
from licenseserver.signing import generate_seed  # noqa: E402

T0 = 1_800_000_000
WEBHOOK_SECRET = "whsec_test_secret"
PAYMENT_LINK = "plink_test"


class Clock:
    def __init__(self, now=T0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def make_env(tmp_path, **overrides):
    env = {
        "I3D_ENV": "dev",
        "I3D_DB_PATH": str(tmp_path / "licenses.db"),
        "I3D_SIGNING_KEY": base64.b64encode(generate_seed()).decode(),
        "I3D_MASTER_SECRET": "m" * 40,
        "I3D_MAIL_BACKEND": "memory",
        "STRIPE_WEBHOOK_SECRET": WEBHOOK_SECRET,
        "I3D_STRIPE_PAYMENT_LINK_ID": PAYMENT_LINK,
        "I3D_SUPPORT_EMAIL": "support@example.test",
        "I3D_DOWNLOAD_URL": "https://example.test/download",
        "I3D_BUY_URL": "https://buy.example.test/x",
    }
    env.update(overrides)
    return env


def did(name: str) -> str:
    return proto.make_device_id(name)


def stripe_event(clock, kind, obj, event_id="evt_1", secret=WEBHOOK_SECRET, timestamp=None):
    """Corps + en-tête `Stripe-Signature` construits comme Stripe le fait."""
    body = json.dumps({"id": event_id, "type": kind, "data": {"object": obj}}).encode()
    stamp = int(clock.now if timestamp is None else timestamp)
    signature = hmac.new(secret.encode(), f"{stamp}.".encode() + body, hashlib.sha256).hexdigest()
    return body, {"Stripe-Signature": f"t={stamp},v1={signature}", "Content-Type": "application/json"}


def checkout(session_id="cs_1", email="client@example.test", payment="pi_1", status="paid", link=PAYMENT_LINK, mode="payment"):
    return {
        "id": session_id,
        "mode": mode,
        "payment_status": status,
        "payment_intent": payment,
        "payment_link": link,
        "customer_details": {"email": email},
    }
