"""Le VRAI module de licence du logiciel face au VRAI serveur : essai, achat, activation, deuxième poste, remboursement."""

import re

import pytest
from server_helpers import checkout, stripe_event

from imagevers3d import license as lic
from licenseserver.protocol import LicenseError, proto

DAY = 86400


class Adapter:
    """Même interface que lic.HttpClient, mais sans réseau : les requêtes vont directement à l'application FastAPI."""

    def __init__(self, http):
        self.http = http

    def post(self, path, body):
        response = self.http.post(path, json=body)
        data = response.json()
        if response.status_code != 200:
            raise LicenseError(data["error"], data["message"])
        return data


def computer(http, service, clock, tmp_path, name):
    folder = tmp_path / name
    folder.mkdir()
    keys = {service.signer.kid: service.signer.public_key}
    return lic.LicenseManager(folder, clock=clock, device_id=proto.make_device_id(name), client=Adapter(http), keys=keys)


def purchase(http, clock, mailer):
    body, headers = stripe_event(clock, "checkout.session.completed", checkout())
    assert http.post("/stripe/webhook", content=body, headers=headers).status_code == 200
    return re.search(r"I3D(?:-[0-9A-Z]{5}){5}", mailer.sent[-1].text).group(0)


def test_whole_customer_journey(http, service, mailer, clock, tmp_path):
    pc1 = computer(http, service, clock, tmp_path, "pc1")

    # 1. Découverte : l'essai de 7 jours, puis il se termine.
    assert pc1.start_trial().state == "trial"
    clock.advance(8 * DAY)
    assert pc1.status().state == "trial_expired"

    # 2. Achat (Stripe -> serveur -> e-mail) puis activation avec la clé reçue.
    key = purchase(http, clock, mailer)
    assert pc1.activate(key).state == "licensed"

    # 3. Ensuite : plus aucun réseau nécessaire.
    pc1._client = None
    clock.advance(3000 * DAY)
    assert pc1.require().state == "licensed"

    # 4. Deuxième poste : accepté. Troisième : refusé avec un message clair.
    pc2 = computer(http, service, clock, tmp_path, "pc2")
    assert pc2.activate(key).allowed
    pc3 = computer(http, service, clock, tmp_path, "pc3")
    with pytest.raises(LicenseError) as error:
        pc3.activate(key)
    assert error.value.code == "device_limit"
    assert pc3.status().state == "none"

    # 5. Transfert depuis le logiciel du poste 2 : le poste 3 peut alors s'activer.
    pc2._client = Adapter(http)
    assert pc2.deactivate().state == "none"
    assert pc3.activate(key).state == "licensed"

    # 6. Remboursement : plus de nouvelle activation, mais le poste déjà activé continue (choix « activation unique »).
    body, headers = stripe_event(clock, "charge.refunded", {"payment_intent": "pi_1", "refunded": True}, event_id="evt_refund")
    http.post("/stripe/webhook", content=body, headers=headers)
    pc4 = computer(http, service, clock, tmp_path, "pc4")
    with pytest.raises(LicenseError) as error:
        pc4.activate(key)
    assert error.value.code == "revoked"
    assert pc1.require().state == "licensed"


def test_token_of_another_server_key_is_rejected_by_the_software(http, service, mailer, clock, tmp_path):
    key = purchase(http, clock, mailer)
    from licenseserver.signing import generate_seed
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    other_public = Ed25519PrivateKey.from_private_bytes(generate_seed()).public_key().public_bytes_raw()
    folder = tmp_path / "pc"
    folder.mkdir()
    manager = lic.LicenseManager(folder, clock=clock, device_id=proto.make_device_id("pc"), client=Adapter(http), keys={service.signer.kid: other_public})
    with pytest.raises(LicenseError) as error:  # un faux serveur qui répondrait avec sa propre clé serait refusé
        manager.activate(key)
    assert error.value.code == "bad_signature"
    assert manager.status().state == "none"


def test_trial_survives_reinstall_but_not_a_restart_of_the_clock(http, service, clock, tmp_path):
    first = computer(http, service, clock, tmp_path, "pc1")
    first.start_trial()
    clock.advance(6 * DAY)
    reinstall = tmp_path / "reinstall"
    reinstall.mkdir()
    again = lic.LicenseManager(
        reinstall, clock=clock, device_id=first.device_id, client=Adapter(http), keys={service.signer.kid: service.signer.public_key}
    )
    assert again.start_trial().days_left == 1  # même appareil : même essai, pas un nouvel essai de 7 jours
