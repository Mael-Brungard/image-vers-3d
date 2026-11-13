"""Outil d'administration et configuration de production (refus de démarrer avec des secrets manquants ou faibles)."""

import base64
import re

import pytest
from server_helpers import make_env

from licenseserver import admin
from licenseserver.config import Config, ConfigError
from licenseserver.protocol import proto
from licenseserver.signing import Signer


def run(args, monkeypatch, tmp_path, **env_overrides):
    for name, value in make_env(tmp_path, **env_overrides).items():
        monkeypatch.setenv(name, value)
    lines = []
    code = admin.main(args, out=lines.append)
    return code, "\n".join(lines)


def test_genkey_prints_a_matching_pair(monkeypatch, tmp_path):
    code, text = run(["genkey"], monkeypatch, tmp_path)
    private, public = re.findall(r"^  (\S+)$", text, re.M)
    assert code == 0 and Signer(base64.b64decode(private), "k1").public_key_b64 == public


def test_create_list_show_revoke_restore_release_resend_stats(monkeypatch, tmp_path):
    code, text = run(["create", "--email", "Client@Example.test", "--note", "presse"], monkeypatch, tmp_path)
    key = re.search(r"Clé : (\S+)", text).group(1)
    license_id = re.search(r"Licence (L\w+)", text).group(1)
    assert code == 0 and proto.normalize_key(key)
    assert "client@example.test" in run(["list"], monkeypatch, tmp_path)[1]
    assert "Aucune" not in run(["show", key], monkeypatch, tmp_path)[1] and run(["show", "inconnue"], monkeypatch, tmp_path)[0] == 1
    assert run(["revoke", license_id, "--reason", "test"], monkeypatch, tmp_path)[0] == 0
    assert run(["revoke", license_id], monkeypatch, tmp_path)[0] == 1  # déjà bloquée
    assert "Motif : test" in run(["show", license_id], monkeypatch, tmp_path)[1]
    assert run(["restore", license_id], monkeypatch, tmp_path)[0] == 0
    assert run(["release", license_id, "0" * 32], monkeypatch, tmp_path)[0] == 1
    assert run(["resend", license_id], monkeypatch, tmp_path)[0] == 0
    assert "licences actives : 1" in run(["stats"], monkeypatch, tmp_path)[1]
    assert run(["resend", "L000"], monkeypatch, tmp_path)[0] == 1


def test_create_without_mail(monkeypatch, tmp_path):
    code, text = run(["create", "--email", "a@example.test", "--no-mail"], monkeypatch, tmp_path)
    assert code == 0 and "Aucun e-mail envoyé" in text


# ------------------------------------------------------------------ configuration

def production_env(tmp_path, **overrides):
    env = make_env(
        tmp_path,
        I3D_ENV="production",
        I3D_BASE_URL="https://licence.example.test",
        I3D_MAIL_BACKEND="smtp",
        SMTP_HOST="smtp.example.test",
        MAIL_FROM="licence@example.test",
    )
    env.update(overrides)
    return env


def test_valid_production_config(tmp_path):
    config = Config.from_env(production_env(tmp_path))
    assert not config.is_dev and config.max_devices == 2 and config.base_url == "https://licence.example.test"


@pytest.mark.parametrize(
    "overrides,fragment",
    [
        ({"I3D_SIGNING_KEY": ""}, "I3D_SIGNING_KEY est obligatoire"),
        ({"I3D_SIGNING_KEY": "pas du base64 !!"}, "base64"),
        ({"I3D_SIGNING_KEY": base64.b64encode(b"court").decode()}, "32 octets"),
        ({"I3D_MASTER_SECRET": ""}, "I3D_MASTER_SECRET"),
        ({"I3D_MASTER_SECRET": "trop-court"}, "32 caractères"),
        ({"I3D_BASE_URL": ""}, "I3D_BASE_URL"),
        ({"I3D_BASE_URL": "http://licence.example.test"}, "https://"),
        ({"I3D_MAIL_BACKEND": "console"}, "SMTP"),
        ({"SMTP_HOST": ""}, "SMTP_HOST"),
        ({"MAIL_FROM": ""}, "MAIL_FROM"),
        ({"I3D_MAX_DEVICES": "0"}, "entre 1 et 20"),
        ({"I3D_MAX_DEVICES": "deux"}, "nombre entier"),
        ({"I3D_ENV": "staging"}, "I3D_ENV"),
        ({"I3D_SIGNING_KID": "k 1"}, "I3D_SIGNING_KID"),
    ],
)
def test_production_refuses_to_start_with_bad_secrets(tmp_path, overrides, fragment):
    with pytest.raises(ConfigError) as error:
        Config.from_env(production_env(tmp_path, **overrides))
    assert fragment in str(error.value)


def test_all_problems_are_reported_at_once(tmp_path):
    with pytest.raises(ConfigError) as error:
        Config.from_env({"I3D_ENV": "production"})
    text = str(error.value)
    assert "I3D_SIGNING_KEY" in text and "I3D_MASTER_SECRET" in text and "I3D_BASE_URL" in text


def test_secrets_never_appear_in_repr(tmp_path):
    config = Config.from_env(production_env(tmp_path, SMTP_PASSWORD="mot-de-passe-smtp"))
    text = repr(config)
    assert "mot-de-passe-smtp" not in text and "whsec_" not in text and ("m" * 40) not in text


def test_dev_mode_generates_a_throwaway_signing_key(tmp_path):
    env = {"I3D_ENV": "dev", "I3D_DB_PATH": str(tmp_path / "x" / "l.db")}
    first = Config.from_env(env)
    assert len(first.signing_seed) == 32 and Config.from_env(env).signing_seed == first.signing_seed


def test_derived_secrets_are_distinct_per_purpose(tmp_path):
    config = Config.from_env(production_env(tmp_path))
    assert len({config.derive(label) for label in ("license-key", "key-lookup", "otp", "ip")}) == 4
