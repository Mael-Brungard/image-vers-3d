"""Configuration du serveur : uniquement des variables d'environnement (rien de secret dans le dépôt).

En production, le serveur REFUSE de démarrer si un secret manque ou est trop faible : mieux vaut un échec visible
qu'un serveur qui signerait avec une clé improvisée. Le mode développement (I3D_ENV=dev) est plus permissif."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from .protocol import proto


class ConfigError(Exception):
    pass


def _b64(value: str) -> bytes:
    return base64.b64decode(value.strip(), validate=True)


def _flag(value: str | None, default: bool = False) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "oui", "on")


@dataclass(frozen=True)
class Config:
    env: str = "production"
    db_path: Path = Path("/data/licenses.db")
    signing_seed: bytes = field(default=b"", repr=False)
    kid: str = "k1"
    master: bytes = field(default=b"", repr=False)
    base_url: str = ""
    stripe_webhook_secret: str = field(default="", repr=False)
    stripe_payment_link: str = ""
    mail_backend: str = "smtp"  # smtp | console | memory
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = field(default="", repr=False)
    smtp_security: str = "starttls"  # starttls | ssl | none
    mail_from: str = ""
    support_email: str = ""
    product_name: str = "Image vers 3D"
    download_url: str = ""
    buy_url: str = ""
    trust_proxy: bool = False
    max_devices: int = proto.MAX_DEVICES
    transfers_per_year: int = 3
    trial_per_ip_per_month: int = 5

    @property
    def is_dev(self) -> bool:
        return self.env == "dev"

    def derive(self, label: str) -> bytes:
        """Secrets dérivés du secret maître (un par usage) : une seule valeur à protéger et à sauvegarder."""
        return hmac.new(self.master, b"I3D-DERIVE-v1|" + label.encode("ascii"), hashlib.sha256).digest()

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Config:
        env_vars = os.environ if environ is None else environ
        get = lambda name, default="": (env_vars.get(name) or default).strip()  # noqa: E731
        env = get("I3D_ENV", "production").lower()
        problems: list[str] = []
        if env not in ("production", "dev"):
            problems.append("I3D_ENV doit valoir « production » ou « dev ».")
        dev = env == "dev"

        db_path = Path(get("I3D_DB_PATH", "./licenses.db" if dev else "/data/licenses.db"))

        seed = b""
        if get("I3D_SIGNING_KEY"):
            try:
                seed = _b64(get("I3D_SIGNING_KEY"))
            except ValueError:
                problems.append("I3D_SIGNING_KEY n'est pas du base64 valide.")
            else:
                if len(seed) != 32:
                    problems.append("I3D_SIGNING_KEY doit contenir 32 octets (générer avec : python tools/genkey.py, depuis le dépôt).")
        elif dev:
            seed = _dev_signing_seed(db_path)
        else:
            problems.append("I3D_SIGNING_KEY est obligatoire (python tools/genkey.py, depuis le dépôt).")

        master = get("I3D_MASTER_SECRET").encode("utf-8")
        if not master and dev:
            master = b"dev-master-secret-not-for-production-use-0123456789"
        if len(master) < 32:
            problems.append("I3D_MASTER_SECRET est obligatoire et doit faire au moins 32 caractères (aléatoires).")

        base_url = get("I3D_BASE_URL", "http://127.0.0.1:8000" if dev else "").rstrip("/")
        if not base_url:
            problems.append("I3D_BASE_URL est obligatoire (adresse publique du serveur, par exemple https://licence.exemple.fr).")
        elif not dev and not base_url.startswith("https://"):
            problems.append("I3D_BASE_URL doit commencer par https:// en production.")

        mail_backend = get("I3D_MAIL_BACKEND", "console" if dev else "smtp").lower()
        if mail_backend not in ("smtp", "console", "memory"):
            problems.append("I3D_MAIL_BACKEND doit valoir smtp, console ou memory.")
        if mail_backend in ("console", "memory") and not dev:
            problems.append("Les e-mails ne peuvent pas être « console » ou « memory » en production : configurer SMTP.")
        smtp_port = _int(get("SMTP_PORT", "587"), "SMTP_PORT", problems)
        smtp_security = get("SMTP_SECURITY", "starttls").lower()
        if smtp_security not in ("starttls", "ssl", "none"):
            problems.append("SMTP_SECURITY doit valoir starttls, ssl ou none.")
        if mail_backend == "smtp" and (not get("SMTP_HOST") or not get("MAIL_FROM")):
            problems.append("SMTP_HOST et MAIL_FROM sont obligatoires pour envoyer les e-mails (code de connexion, clé de licence).")

        max_devices = _int(get("I3D_MAX_DEVICES", str(proto.MAX_DEVICES)), "I3D_MAX_DEVICES", problems)
        if not 1 <= max_devices <= 20:
            problems.append("I3D_MAX_DEVICES doit être compris entre 1 et 20.")
        transfers = _int(get("I3D_TRANSFERS_PER_YEAR", "3"), "I3D_TRANSFERS_PER_YEAR", problems)
        trial_cap = _int(get("I3D_TRIAL_PER_IP_PER_MONTH", "5"), "I3D_TRIAL_PER_IP_PER_MONTH", problems)

        kid = get("I3D_SIGNING_KID", "k1")
        if not 1 <= len(kid) <= 32 or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for c in kid):
            problems.append("I3D_SIGNING_KID invalide (lettres, chiffres, . _ - ; 32 caractères au plus).")

        if problems:
            raise ConfigError("Configuration invalide :\n - " + "\n - ".join(problems))
        return cls(
            env=env,
            db_path=db_path,
            signing_seed=seed,
            kid=kid,
            master=master,
            base_url=base_url,
            stripe_webhook_secret=get("STRIPE_WEBHOOK_SECRET"),
            stripe_payment_link=get("I3D_STRIPE_PAYMENT_LINK_ID"),
            mail_backend=mail_backend,
            smtp_host=get("SMTP_HOST"),
            smtp_port=smtp_port,
            smtp_user=get("SMTP_USER"),
            smtp_password=get("SMTP_PASSWORD"),
            smtp_security=smtp_security,
            mail_from=get("MAIL_FROM"),
            support_email=get("I3D_SUPPORT_EMAIL"),
            product_name=get("I3D_PRODUCT_NAME", "Image vers 3D"),
            download_url=get("I3D_DOWNLOAD_URL"),
            buy_url=get("I3D_BUY_URL"),
            trust_proxy=_flag(get("I3D_TRUST_PROXY")),
            max_devices=max_devices,
            transfers_per_year=transfers,
            trial_per_ip_per_month=trial_cap,
        )


def _int(value: str, name: str, problems: list[str]) -> int:
    try:
        return int(value)
    except ValueError:
        problems.append(f"{name} doit être un nombre entier.")
        return 0


def _dev_signing_seed(db_path: Path) -> bytes:
    """Mode développement uniquement : clé de signature jetable conservée à côté de la base."""
    path = db_path.parent / "dev_signing.key"
    try:
        return _b64(path.read_text(encoding="ascii"))
    except (OSError, ValueError):
        seed = os.urandom(32)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(base64.b64encode(seed).decode("ascii"), encoding="ascii")
        except OSError:
            pass
        return seed
