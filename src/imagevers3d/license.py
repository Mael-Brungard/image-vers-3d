"""
license.py - licence, essai gratuit et activation (côté logiciel).

Principe (détails et limites : docs/LICENSING.md) :
  - on active UNE fois, en ligne : le serveur vérifie la clé, compte les appareils (2 au maximum) et renvoie un jeton
    signé, lié à cet ordinateur ; ensuite tout fonctionne HORS LIGNE : le logiciel vérifie la signature avec la clé
    publique qu'il embarque (aucune clé privée n'est jamais distribuée) ;
  - l'essai gratuit de 7 jours est un jeton du même type (type « trial »), délivré une seule fois par ordinateur ;
  - rien n'est comparé « en clair » : sans la clé privée du serveur, on ne peut pas fabriquer de jeton valide.

Ce que ce module ne peut PAS faire : empêcher quelqu'un qui contrôle son propre ordinateur de modifier le programme
lui-même. Le but est de rendre cela plus long et plus pénible qu'un achat (modules compilés, contrôles répétés à
plusieurs endroits, pas de variable d'environnement de contournement dans la version livrée).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import os
import platform
import ssl
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from . import __version__, _license_keys, paths
from ._licproto import (
    LicenseError,
    display_key,
    is_device_id,
    make_device_id,
    normalize_key,
    verify_token,
)

STATE_FILE_NAME = "license.json"
CLOCK_TOLERANCE_SECONDS = 24 * 3600  # une horloge corrigée de quelques heures n'est pas une fraude
SEEN_WRITE_INTERVAL_SECONDS = 600
HTTP_TIMEOUT_SECONDS = 20


def is_compiled() -> bool:
    """Vrai quand ce module a été compilé (version livrée). Les réglages de développement ne sont alors plus lus."""
    return not str(globals().get("__file__", "")).endswith(".py")


def public_keys() -> dict[str, bytes]:
    """Clés publiques de vérification : celles de la version livrée, plus une clé de développement (IMAGEVERS3D_DEV_LICENSE_PUBKEY)
    acceptée UNIQUEMENT quand le module n'est pas compilé, pour que les tests et l'intégration continue fonctionnent."""
    keys: dict[str, bytes] = {}
    for kid, encoded in _license_keys.KEYS.items():
        try:
            raw = base64.b64decode(encoded)
        except ValueError:
            continue
        if len(raw) == 32:
            keys[kid] = raw
    dev = os.environ.get("IMAGEVERS3D_DEV_LICENSE_PUBKEY", "")
    if dev and not is_compiled():
        try:
            raw = base64.b64decode(dev)
        except ValueError:
            raw = b""
        if len(raw) == 32:
            keys["dev"] = raw
    return keys


def server_url() -> str:
    override = os.environ.get("IMAGEVERS3D_LICENSE_URL", "") if not is_compiled() else ""
    return (override or _license_keys.SERVER_URL).rstrip("/")


def buy_url() -> str:
    return _license_keys.BUY_URL.strip()


# ---------------------------------------------------------------- identifiant d'appareil

_UNIX_MACHINE_ID_FILES = ("/etc/machine-id", "/var/lib/dbus/machine-id")


def read_machine_id(data_dir: Path) -> str:
    """Identifiant brut de la machine : MachineGuid (Windows), machine-id (Linux), sinon un nombre aléatoire conservé
    dans le dossier de données. Il n'est jamais transmis tel quel : voir make_device_id."""
    try:
        if sys.platform == "win32":
            import winreg

            flags = winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0)
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0, flags) as key:
                value = str(winreg.QueryValueEx(key, "MachineGuid")[0]).strip()
            if value:
                return "win:" + value
        else:
            for candidate in _UNIX_MACHINE_ID_FILES:
                try:
                    value = Path(candidate).read_text(encoding="ascii").strip()
                except OSError:
                    continue
                if value:
                    return "unix:" + value
    except Exception:  # noqa: BLE001 - pas d'identifiant système : on se rabat sur un identifiant local
        pass
    fallback = data_dir / "device.id"
    try:
        value = fallback.read_text(encoding="ascii").strip()
        if len(value) >= 16:
            return "local:" + value
    except OSError:
        pass
    value = base64.b16encode(os.urandom(16)).decode("ascii").lower()
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        fallback.write_text(value, encoding="ascii")
    except OSError:
        pass
    return "local:" + value


# ---------------------------------------------------------------- état

@dataclass(frozen=True)
class LicenseStatus:
    state: str  # licensed | trial | trial_expired | none | invalid | clock
    message: str
    days_left: int | None = None
    license_id: str | None = None
    expires_at: int | None = None

    @property
    def allowed(self) -> bool:
        return self.state in ("licensed", "trial")


_REQUIRE_CODES = {
    "none": "license_required",
    "trial_expired": "trial_expired",
    "invalid": "license_invalid",
    "clock": "clock_tampered",
}


# ---------------------------------------------------------------- réseau

class HttpClient:
    """Appels JSON vers le serveur de licence (bibliothèque standard, TLS vérifié par défaut)."""

    def __init__(self, base_url: str | None = None, timeout: float = HTTP_TIMEOUT_SECONDS):
        self._base_url = base_url
        self._timeout = timeout

    def post(self, path: str, body: Mapping) -> dict:
        base = (self._base_url if self._base_url is not None else server_url()).rstrip("/")
        if not base:
            raise LicenseError("no_server", "Cette version n'est pas configurée pour l'activation (adresse du serveur absente).")
        request = urllib.request.Request(
            base + path,
            data=json.dumps(dict(body)).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": f"ImageVers3D/{__version__}", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout, context=ssl.create_default_context()) as response:
                return _read_json(response.read())
        except urllib.error.HTTPError as exc:
            try:
                data = _read_json(exc.read())
            except LicenseError:
                data = {}
            code = str(data.get("error") or f"http_{exc.code}")
            raise LicenseError(code, str(data.get("message") or f"Le serveur de licence a répondu une erreur ({exc.code}).")) from exc
        except (urllib.error.URLError, TimeoutError, ssl.SSLError, OSError) as exc:
            raise LicenseError(
                "network", "Impossible de joindre le serveur de licence. Vérifie ta connexion Internet puis réessaie."
            ) from exc


def _read_json(raw: bytes) -> dict:
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise LicenseError("bad_response", "Réponse inattendue du serveur de licence.") from exc
    if not isinstance(data, dict):
        raise LicenseError("bad_response", "Réponse inattendue du serveur de licence.")
    return data


# ---------------------------------------------------------------- gestionnaire

class LicenseManager:
    """Lit, vérifie et met à jour l'état de licence de CET ordinateur. Aucune interface graphique ici."""

    def __init__(
        self,
        data_dir: Path | str | None = None,
        *,
        clock: Callable[[], float] = time.time,
        device_id: str | None = None,
        client=None,
        keys: Mapping[str, bytes] | None = None,
    ):
        self._dir = Path(data_dir) if data_dir is not None else Path(paths.DATA_DIR)
        self._clock = clock
        self._device_id = device_id
        self._client = client if client is not None else HttpClient()
        self._keys = keys
        self._lock = threading.RLock()
        self._verified: dict[str, dict] = {}

    # -- identité
    @property
    def device_id(self) -> str:
        if self._device_id is None:
            self._device_id = make_device_id(read_machine_id(self._dir))
        return self._device_id

    @property
    def state_path(self) -> Path:
        return self._dir / STATE_FILE_NAME

    # -- stockage
    def _load(self) -> dict:
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self, data: dict) -> None:
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            handle, temporary = tempfile.mkstemp(prefix="license-", suffix=".tmp", dir=self._dir)
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(data, stream, sort_keys=True)
            os.replace(temporary, self.state_path)
        except OSError:
            pass  # disque en lecture seule : on continue, la licence reste valable pour cette session

    def _seen_mac(self, seen: int) -> str:
        key = hashlib.sha256(b"I3D-SEEN-v1|" + self.device_id.encode("ascii")).digest()
        return hmac.new(key, str(seen).encode("ascii"), hashlib.sha256).hexdigest()[:32]

    # -- vérification
    def _payload(self, token: str) -> dict:
        cached = self._verified.get(token)
        if cached is not None:
            return cached
        keys = self._keys if self._keys is not None else public_keys()
        payload = verify_token(token, keys)
        if payload["did"] != self.device_id:
            raise LicenseError("other_device", "Cette licence est liée à un autre ordinateur.")
        self._verified[token] = payload
        return payload

    def status(self) -> LicenseStatus:
        with self._lock:
            data = self._load()
            token = data.get("token")
            if not isinstance(token, str) or not token:
                return LicenseStatus("none", "Pas encore de licence : démarre l'essai gratuit ou active ta clé.")
            try:
                payload = self._payload(token)
            except LicenseError as exc:
                return LicenseStatus("invalid", exc.message)
            now = int(self._clock())
            expires = payload["exp"]
            if payload["typ"] == "license" and expires is None:
                return LicenseStatus("licensed", "Licence active.", None, payload["lid"], None)

            # Jeton qui expire (essai, ou licence à durée limitée) : on surveille le recul d'horloge.
            seen = data.get("seen")
            if seen is not None:
                valid = isinstance(seen, int) and hmac.compare_digest(str(data.get("seen_mac", "")), self._seen_mac(seen))
                if not valid or now + CLOCK_TOLERANCE_SECONDS < seen:
                    return LicenseStatus(
                        "clock",
                        "L'horloge de l'ordinateur semble avoir été reculée. Remets l'heure exacte pour continuer, ou active ta licence.",
                        None,
                        payload["lid"],
                        expires,
                    )
            if seen is None or now - seen >= SEEN_WRITE_INTERVAL_SECONDS:
                data["seen"] = now
                data["seen_mac"] = self._seen_mac(now)
                self._save(data)
            if now >= expires:
                if payload["typ"] == "trial":
                    return LicenseStatus("trial_expired", "L'essai gratuit est terminé. Achète une licence pour continuer.", 0, payload["lid"], expires)
                return LicenseStatus("invalid", "Cette licence a expiré.", 0, payload["lid"], expires)
            days = max(1, math.ceil((expires - now) / 86400))
            if payload["typ"] == "trial":
                plural = "s" if days > 1 else ""
                return LicenseStatus("trial", f"Essai gratuit : {days} jour{plural} restant{plural}.", days, payload["lid"], expires)
            return LicenseStatus("licensed", "Licence active.", days, payload["lid"], expires)

    def require(self) -> LicenseStatus:
        status = self.status()
        if not status.allowed:
            raise LicenseError(_REQUIRE_CODES.get(status.state, "license_required"), status.message)
        return status

    # -- actions en ligne (une fois)
    def _store_token(self, response: dict, expected_type: str) -> LicenseStatus:
        token = response.get("token")
        if not isinstance(token, str):
            raise LicenseError("bad_response", "Réponse inattendue du serveur de licence.")
        keys = self._keys if self._keys is not None else public_keys()
        payload = verify_token(token, keys)
        if payload["did"] != self.device_id or payload["typ"] != expected_type:
            raise LicenseError("bad_response", "Le serveur a renvoyé une licence qui ne correspond pas à cet ordinateur.")
        with self._lock:
            data = self._load()
            data["token"] = token  # « seen » est conservé : effacer l'horodatage ne doit pas relancer l'essai
            self._verified[token] = payload
            self._save(data)
        return self.status()

    def activate(self, key_text: str) -> LicenseStatus:
        body = normalize_key(key_text)
        if body is None:
            raise LicenseError("invalid_key_format", "Cette clé n'a pas le bon format. Elle ressemble à I3D-XXXXX-XXXXX-XXXXX-XXXXX-XXXXX.")
        response = self._client.post(
            "/v1/activate",
            {"key": display_key(body), "did": self.device_id, "name": _device_label(), "app": __version__},
        )
        return self._store_token(response, "license")

    def start_trial(self) -> LicenseStatus:
        current = self.status()
        if current.state in ("licensed", "trial", "trial_expired", "clock"):
            return current  # un seul essai par ordinateur ; une licence active passe avant
        response = self._client.post("/v1/trial", {"did": self.device_id, "app": __version__})
        return self._store_token(response, "trial")

    def deactivate(self) -> LicenseStatus:
        """Libère la place de cet ordinateur sur le serveur (pour activer un autre poste), puis retire la licence ici."""
        with self._lock:
            data = self._load()
        token = data.get("token")
        if not isinstance(token, str):
            return self.status()
        payload = self._payload(token)
        if payload["typ"] != "license":
            raise LicenseError("not_a_license", "Seule une licence achetée peut être transférée.")
        self._client.post("/v1/deactivate", {"token": token})
        with self._lock:
            data.pop("token", None)
            self._verified.clear()
            self._save(data)
        return self.status()


def _device_label() -> str:
    try:
        return (platform.node() or "ordinateur")[:40]
    except Exception:  # noqa: BLE001
        return "ordinateur"


# ---------------------------------------------------------------- instance du processus

_MANAGER: LicenseManager | None = None
_MANAGER_LOCK = threading.Lock()


def get_manager() -> LicenseManager:
    global _MANAGER
    with _MANAGER_LOCK:
        if _MANAGER is None:
            _MANAGER = LicenseManager()
        return _MANAGER


def set_manager(manager: LicenseManager | None) -> None:
    """Remplace l'instance du processus (tests, scénarios d'interface)."""
    global _MANAGER
    with _MANAGER_LOCK:
        _MANAGER = manager


def require() -> LicenseStatus:
    """Contrôle appelé avant tout travail de calcul : lève LicenseError sans licence ni essai valable."""
    return get_manager().require()


__all__ = [
    "HttpClient",
    "LicenseError",
    "LicenseManager",
    "LicenseStatus",
    "get_manager",
    "buy_url",
    "is_compiled",
    "is_device_id",
    "public_keys",
    "read_machine_id",
    "require",
    "server_url",
    "set_manager",
]
