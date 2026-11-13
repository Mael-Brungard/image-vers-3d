"""Fichiers de déploiement : ils doivent rester d'accord avec le code (variables, copie du protocole, secrets absents)."""

import base64
import re
from pathlib import Path

import pytest
import yaml

from licenseserver.config import Config, ConfigError

SERVER = Path(__file__).resolve().parents[1]
REPO = SERVER.parent


def env_example() -> dict[str, str]:
    values = {}
    for line in (SERVER / ".env.example").read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            name, _, value = line.partition("=")
            values[name.strip()] = value.strip()
    return values


def test_env_example_only_uses_variables_the_server_reads():
    code = "\n".join(p.read_text(encoding="utf-8") for p in (SERVER / "licenseserver").glob("*.py"))
    compose = (SERVER / "docker-compose.yml").read_text(encoding="utf-8")
    caddy = (SERVER / "deploy" / "Caddyfile").read_text(encoding="utf-8")
    for name in env_example():
        assert name in code or name in compose or name in caddy, f"{name} est documentée mais lue nulle part"


def test_every_variable_the_server_reads_is_documented():
    code = (SERVER / "licenseserver" / "config.py").read_text(encoding="utf-8")
    read = set(re.findall(r'get\("([A-Z0-9_]+)"', code))
    compose = yaml.safe_load((SERVER / "docker-compose.yml").read_text(encoding="utf-8"))
    provided = set(compose["services"]["licences"]["environment"])  # réglées par le déploiement lui-même
    provided |= set(re.findall(r"^\s+(I3D_[A-Z_]+)=", (SERVER / "Dockerfile").read_text(encoding="utf-8"), re.M))
    provided.add("I3D_ENV")  # « dev » seulement pour travailler en local (docs/SERVER.md) ; la production est la valeur par défaut
    missing = read - set(env_example()) - provided
    assert not missing, f"variables non documentées dans .env.example : {sorted(missing)}"


def test_env_example_contains_no_secret_and_is_valid_once_filled():
    values = env_example()
    for secret in ("I3D_SIGNING_KEY", "I3D_MASTER_SECRET", "STRIPE_WEBHOOK_SECRET", "SMTP_PASSWORD"):
        assert values[secret] == "", f"{secret} doit rester vide dans le fichier d'exemple"
    with pytest.raises(ConfigError):
        Config.from_env(values)  # tel quel : refuse de démarrer (secrets absents), comme prévu
    filled = dict(values, I3D_SIGNING_KEY=base64.b64encode(bytes(32)).decode(), I3D_MASTER_SECRET="x" * 40, SMTP_HOST="smtp.exemple.fr")
    config = Config.from_env(filled)
    assert config.base_url == "https://licence.exemple.fr" and config.max_devices == 2 and config.mail_backend == "smtp"


def test_dockerfile_copies_the_shared_protocol_and_runs_unprivileged():
    text = (SERVER / "Dockerfile").read_text(encoding="utf-8")
    assert "src/imagevers3d/_licproto.py" in text and "src/imagevers3d/_ed25519.py" in text
    assert re.search(r"^USER licence$", text, re.M)
    assert "COPY server/licenseserver" in text
    copies = [line for line in text.splitlines() if line.startswith(("COPY", "ADD"))]
    assert all(".env" not in line and not line.startswith(("COPY . ", "ADD ")) for line in copies), "aucun secret dans l'image"


def test_compose_is_valid_and_hardened():
    compose = yaml.safe_load((SERVER / "docker-compose.yml").read_text(encoding="utf-8"))
    licences = compose["services"]["licences"]
    assert "ports" not in licences, "le serveur ne s'expose pas directement : seul Caddy est joignable"
    assert licences["read_only"] is True and licences["cap_drop"] == ["ALL"]
    assert licences["environment"]["I3D_TRUST_PROXY"] == "1"
    assert "ports" in compose["services"]["caddy"]


def test_gitignore_keeps_secrets_out_of_the_repository():
    text = (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()
    for entry in (".env", "server/.env", "*.db", "dev_signing.key"):
        assert entry in text
