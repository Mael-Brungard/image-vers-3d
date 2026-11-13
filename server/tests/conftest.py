"""Réglages communs des tests du serveur : base jetable, e-mails en mémoire, horloge pilotée, application FastAPI complète."""

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402
from server_helpers import Clock, make_env  # noqa: E402

from licenseserver import web  # noqa: E402
from licenseserver.config import Config  # noqa: E402
from licenseserver.mail import Mailer  # noqa: E402


@pytest.fixture()
def clock():
    return Clock()


@pytest.fixture()
def config(tmp_path):
    return Config.from_env(make_env(tmp_path))


@pytest.fixture()
def mailer(config):
    return Mailer(config)


@pytest.fixture()
def app(config, clock, mailer):
    return web.create_app(config, clock=clock, mailer=mailer)


@pytest.fixture()
def service(app):
    return app.state.service


@pytest.fixture()
def http(app):
    with TestClient(app, base_url="http://127.0.0.1:8000", client=("203.0.113.7", 50000)) as client:
        yield client


