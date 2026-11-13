"""Règles métier : licences, activations (2 appareils), essais, transferts, comptes par code e-mail.

Tout ce qui touche à l'argent ou aux droits passe ici ; la couche web (web.py) ne fait que traduire HTTP <-> ces méthodes.
Chaque méthode qui écrit s'exécute dans UNE transaction : deux activations simultanées ne peuvent pas dépasser la limite."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time
from collections.abc import Callable

from .config import Config
from .db import Database
from .mail import Mailer
from .protocol import LicenseError, proto
from .ratelimit import RateLimiter
from .signing import Signer

DAY = 86400
OTP_TTL = 600
OTP_MAX_ATTEMPTS = 5
SESSION_TTL = 14 * DAY
_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s.]{2,}$")


def normalize_email(value: object) -> str:
    email = value.strip().lower() if isinstance(value, str) else ""
    if len(email) > 254 or not _EMAIL_RE.match(email):
        raise LicenseError("invalid_email", "Cette adresse e-mail n'est pas valide.")
    return email


class Service:
    def __init__(self, config: Config, db: Database, signer: Signer, mailer: Mailer, clock: Callable[[], float] = time.time):
        self.config = config
        self.db = db
        self.signer = signer
        self.mailer = mailer
        self.clock = clock
        self.limiter = RateLimiter(db, clock)
        self._key_secret = config.derive("license-key")
        self._pepper = config.derive("key-lookup")
        self._otp_secret = config.derive("otp")
        self._ip_secret = config.derive("ip")

    # ------------------------------------------------------------ outils
    def now(self) -> int:
        return int(self.clock())

    def ip_hash(self, ip: str | None) -> str | None:
        if not ip:
            return None
        return hmac.new(self._ip_secret, ip.encode("utf-8"), hashlib.sha256).hexdigest()[:24]

    def key_display(self, license_id: str) -> str:
        return proto.display_key(proto.key_body_from_secret(self._key_secret, license_id))

    def _audit(self, conn, kind: str, *, license_id=None, email=None, did=None, ip_hash=None, detail=None) -> None:
        conn.execute(
            "INSERT INTO audit(ts, kind, license_id, email, did, ip_hash, detail) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (self.now(), kind, license_id, email, did, ip_hash, detail),
        )

    # ------------------------------------------------------------ licences
    def create_license(
        self,
        email: str,
        *,
        source: str,
        source_ref: str | None = None,
        payment_ref: str | None = None,
        note: str | None = None,
        send_mail: bool = True,
    ) -> tuple[dict, str, bool]:
        """Crée une licence (idempotent si `source_ref` existe déjà). Renvoie (licence, clé affichable, créée_maintenant)."""
        email = normalize_email(email)
        created = False
        with self.db.tx() as conn:
            row = conn.execute("SELECT * FROM licenses WHERE source_ref = ?", (source_ref,)).fetchone() if source_ref else None
            if row is None:
                license_id = "L" + secrets.token_hex(8).upper()
                body = proto.key_body_from_secret(self._key_secret, license_id)
                conn.execute(
                    "INSERT INTO licenses(id, email, key_hash, source, source_ref, payment_ref, max_devices, created_at, note) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (license_id, email, proto.key_lookup_hash(self._pepper, body), source, source_ref, payment_ref,
                     self.config.max_devices, self.now(), note),
                )
                self._audit(conn, "license_created", license_id=license_id, email=email, detail=source)
                row = conn.execute("SELECT * FROM licenses WHERE id = ?", (license_id,)).fetchone()
                created = True
        key = self.key_display(row["id"])
        if created and send_mail:
            try:
                self.mailer.send_license(email, key)
            except Exception as exc:  # noqa: BLE001 - la licence existe : le client la retrouvera dans son espace client
                with self.db.tx() as conn:
                    self._audit(conn, "mail_failed", license_id=row["id"], email=email, detail=type(exc).__name__)
        return dict(row), key, created

    def get_license(self, license_id: str) -> dict | None:
        with self.db.tx() as conn:
            row = conn.execute("SELECT * FROM licenses WHERE id = ?", (license_id,)).fetchone()
        return dict(row) if row else None

    def revoke(self, license_id: str, reason: str) -> bool:
        """Bloque les NOUVELLES activations (les ordinateurs déjà activés restent valables : activation hors ligne)."""
        with self.db.tx() as conn:
            cursor = conn.execute(
                "UPDATE licenses SET status = 'revoked', revoked_reason = ? WHERE id = ? AND status = 'active'", (reason[:200], license_id)
            )
            if cursor.rowcount:
                self._audit(conn, "license_revoked", license_id=license_id, detail=reason[:200])
            return bool(cursor.rowcount)

    def revoke_by_payment(self, payment_ref: str, reason: str) -> int:
        with self.db.tx() as conn:
            ids = [r["id"] for r in conn.execute("SELECT id FROM licenses WHERE payment_ref = ? AND status = 'active'", (payment_ref,))]
        return sum(self.revoke(i, reason) for i in ids)

    def restore(self, license_id: str) -> bool:
        with self.db.tx() as conn:
            cursor = conn.execute("UPDATE licenses SET status = 'active', revoked_reason = NULL WHERE id = ? AND status = 'revoked'", (license_id,))
            if cursor.rowcount:
                self._audit(conn, "license_restored", license_id=license_id)
            return bool(cursor.rowcount)

    # ------------------------------------------------------------ activation (une fois, en ligne)
    def activate(self, key_text: object, did: object, name: object, app_version: object, ip: str | None) -> str:
        if not proto.is_device_id(did):
            raise LicenseError("bad_request", "Requête invalide.")
        body = proto.normalize_key(key_text) if isinstance(key_text, str) else None
        if body is None:
            raise LicenseError("invalid_key_format", "Cette clé n'a pas le bon format. Elle ressemble à I3D-XXXXX-XXXXX-XXXXX-XXXXX-XXXXX.")
        iph = self.ip_hash(ip)
        fail_bucket = f"activate-fail:{iph}"
        if iph and self.limiter.blocked(fail_bucket, 10, 3600):
            raise LicenseError("rate_limited", "Trop de clés incorrectes depuis cette connexion. Réessaie dans une heure.")
        label = str(name)[:40] if isinstance(name, str) else ""
        version = str(app_version)[:32] if isinstance(app_version, str) else ""
        now = self.now()
        with self.db.tx() as conn:
            lic = conn.execute("SELECT * FROM licenses WHERE key_hash = ?", (proto.key_lookup_hash(self._pepper, body),)).fetchone()
            if lic is not None:
                if lic["status"] != "active":
                    raise LicenseError("revoked", "Cette licence a été remboursée ou annulée : elle ne peut plus être activée.")
                act = conn.execute("SELECT * FROM activations WHERE license_id = ? AND did = ?", (lic["id"], did)).fetchone()
                if act is not None and act["released_at"] is None:
                    conn.execute("UPDATE activations SET last_seen_at = ?, name = ?, app_version = ? WHERE id = ?", (now, label, version, act["id"]))
                else:
                    used = conn.execute("SELECT COUNT(*) FROM activations WHERE license_id = ? AND released_at IS NULL", (lic["id"],)).fetchone()[0]
                    if used >= lic["max_devices"]:
                        raise LicenseError(
                            "device_limit",
                            f"Cette licence est déjà activée sur {lic['max_devices']} ordinateurs. Libère une place dans ton espace client "
                            "(ou depuis le logiciel, sur l'autre ordinateur), puis réessaie.",
                        )
                    if act is None:
                        conn.execute(
                            "INSERT INTO activations(license_id, did, name, app_version, created_at, last_seen_at) VALUES (?, ?, ?, ?, ?, ?)",
                            (lic["id"], did, label, version, now, now),
                        )
                    else:
                        conn.execute(
                            "UPDATE activations SET released_at = NULL, created_at = ?, last_seen_at = ?, name = ?, app_version = ? WHERE id = ?",
                            (now, now, label, version, act["id"]),
                        )
                    self._audit(conn, "activate", license_id=lic["id"], did=did, ip_hash=iph)
                return self.signer.token(typ="license", license_id=lic["id"], did=did, issued_at=now, expires_at=None, max_devices=lic["max_devices"])
        if iph:
            self.limiter.record(fail_bucket)
        raise LicenseError("invalid_key", "Cette clé de licence n'existe pas. Vérifie la saisie (ou copie-colle la clé reçue par e-mail).")

    # ------------------------------------------------------------ essai
    def trial(self, did: object, app_version: object, ip: str | None) -> str:
        if not proto.is_device_id(did):
            raise LicenseError("bad_request", "Requête invalide.")
        iph = self.ip_hash(ip)
        now = self.now()
        with self.db.tx() as conn:
            row = conn.execute("SELECT token FROM trials WHERE did = ?", (did,)).fetchone()
            if row is not None:
                return row["token"]  # idempotent : redemander ne prolonge jamais l'essai
            if iph:
                recent = conn.execute("SELECT COUNT(*) FROM trials WHERE ip_hash = ? AND created_at > ?", (iph, now - 30 * DAY)).fetchone()[0]
                if recent >= self.config.trial_per_ip_per_month:
                    raise LicenseError(
                        "trial_refused",
                        "Trop d'essais ont déjà été démarrés depuis cette connexion ce mois-ci. Achète une licence ou contacte le support.",
                    )
            token = self.signer.token(
                typ="trial", license_id="trial", did=did, issued_at=now, expires_at=now + proto.TRIAL_DAYS * DAY, max_devices=1
            )
            conn.execute("INSERT INTO trials(did, token, ip_hash, created_at) VALUES (?, ?, ?, ?)", (did, token, iph, now))
            self._audit(conn, "trial", did=did, ip_hash=iph)
            return token

    # ------------------------------------------------------------ libération d'une place
    def _release(self, conn, license_row, did: str, source: str) -> bool:
        act = conn.execute("SELECT * FROM activations WHERE license_id = ? AND did = ? AND released_at IS NULL", (license_row["id"], did)).fetchone()
        if act is None:
            return False
        now = self.now()
        used = conn.execute(
            "SELECT COUNT(*) FROM audit WHERE license_id = ? AND kind = 'release' AND ts > ?", (license_row["id"], now - 365 * DAY)
        ).fetchone()[0]
        if used >= self.config.transfers_per_year:
            raise LicenseError(
                "transfer_limit",
                f"Tu as déjà libéré {used} places cette année (maximum {self.config.transfers_per_year}). Écris au support pour un cas particulier.",
            )
        conn.execute("UPDATE activations SET released_at = ? WHERE id = ?", (now, act["id"]))
        self._audit(conn, "release", license_id=license_row["id"], did=did, detail=source)
        return True

    def deactivate_with_token(self, token: object) -> bool:
        """Depuis le logiciel : le jeton, signé par ce serveur, prouve que l'appareil est activé."""
        payload = self.signer.verify_own(token if isinstance(token, str) else "")
        if payload["typ"] != "license":
            raise LicenseError("not_a_license", "Seule une licence achetée peut être transférée.")
        with self.db.tx() as conn:
            lic = conn.execute("SELECT * FROM licenses WHERE id = ?", (payload["lid"],)).fetchone()
            if lic is None:
                raise LicenseError("invalid_token", "Licence inconnue.")
            return self._release(conn, lic, payload["did"], "app")

    def release_from_portal(self, email: str, license_id: str, did: str) -> bool:
        with self.db.tx() as conn:
            lic = conn.execute("SELECT * FROM licenses WHERE id = ? AND email = ?", (license_id, email)).fetchone()
            if lic is None:
                raise LicenseError("not_found", "Licence introuvable.")
            return self._release(conn, lic, did, "portal")

    def admin_release(self, license_id: str, did: str) -> bool:
        """Support : libère une place sans consommer le quota de transferts du client."""
        with self.db.tx() as conn:
            cursor = conn.execute("UPDATE activations SET released_at = ? WHERE license_id = ? AND did = ? AND released_at IS NULL", (self.now(), license_id, did))
            if cursor.rowcount:
                self._audit(conn, "admin_release", license_id=license_id, did=did)
            return bool(cursor.rowcount)

    # ------------------------------------------------------------ espace client
    def account(self, email: str) -> list[dict]:
        now = self.now()
        out = []
        with self.db.tx() as conn:
            for lic in conn.execute("SELECT * FROM licenses WHERE email = ? ORDER BY created_at", (email,)).fetchall():
                devices = [
                    dict(r)
                    for r in conn.execute(
                        "SELECT did, name, app_version, created_at, last_seen_at FROM activations WHERE license_id = ? AND released_at IS NULL ORDER BY created_at",
                        (lic["id"],),
                    )
                ]
                used = conn.execute(
                    "SELECT COUNT(*) FROM audit WHERE license_id = ? AND kind = 'release' AND ts > ?", (lic["id"], now - 365 * DAY)
                ).fetchone()[0]
                out.append(
                    {
                        "id": lic["id"],
                        "key": self.key_display(lic["id"]),
                        "status": lic["status"],
                        "created_at": lic["created_at"],
                        "max_devices": lic["max_devices"],
                        "devices": devices,
                        "transfers_left": max(0, self.config.transfers_per_year - used),
                    }
                )
        return out

    def request_code(self, email_raw: object, ip: str | None) -> bool:
        """Envoie un code à 8 chiffres si une licence existe pour cette adresse. Le résultat n'est PAS montré à l'utilisateur
        (même réponse dans tous les cas), pour qu'on ne puisse pas deviner qui est client."""
        email = normalize_email(email_raw)
        iph = self.ip_hash(ip)
        if iph:
            self.limiter.hit(f"code-ip:{iph}", 10, 3600)
        self.limiter.hit(f"code-email:{hashlib.sha256(email.encode()).hexdigest()[:24]}", 5, 3600)
        with self.db.tx() as conn:
            exists = conn.execute("SELECT 1 FROM licenses WHERE email = ? LIMIT 1", (email,)).fetchone() is not None
            if not exists:
                return False
            code = f"{secrets.randbelow(10**8):08d}"
            conn.execute(
                "INSERT INTO otp(email, code_hash, expires_at, attempts) VALUES (?, ?, ?, 0) "
                "ON CONFLICT(email) DO UPDATE SET code_hash = excluded.code_hash, expires_at = excluded.expires_at, attempts = 0",
                (email, self._code_hash(email, code), self.now() + OTP_TTL),
            )
        self.mailer.send_code(email, code)
        return True

    def _code_hash(self, email: str, code: str) -> str:
        return hmac.new(self._otp_secret, f"{email}|{code}".encode(), hashlib.sha256).hexdigest()

    def verify_code(self, email_raw: object, code_raw: object, ip: str | None) -> tuple[str, str, str, int]:
        """Vérifie le code ; renvoie (cookie_de_session, jeton_csrf, e-mail, expiration). Cinq essais, dix minutes."""
        email = normalize_email(email_raw)
        code = re.sub(r"\s", "", code_raw) if isinstance(code_raw, str) else ""
        iph = self.ip_hash(ip)
        if iph:
            self.limiter.hit(f"verify-ip:{iph}", 30, 3600)
        bad = LicenseError("invalid_code", "Code incorrect ou expiré. Demande un nouveau code.")
        now = self.now()
        with self.db.tx() as conn:
            row = conn.execute("SELECT * FROM otp WHERE email = ?", (email,)).fetchone()
            if row is None or row["expires_at"] < now or row["attempts"] >= OTP_MAX_ATTEMPTS:
                raise bad
            if not (code.isdigit() and len(code) == 8 and hmac.compare_digest(row["code_hash"], self._code_hash(email, code))):
                conn.execute("UPDATE otp SET attempts = attempts + 1 WHERE email = ?", (email,))
                failure = True
            else:
                conn.execute("DELETE FROM otp WHERE email = ?", (email,))
                cookie = secrets.token_urlsafe(32)
                csrf = secrets.token_urlsafe(24)
                conn.execute(
                    "INSERT INTO sessions(id, email, csrf, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
                    (hashlib.sha256(cookie.encode()).hexdigest(), email, csrf, now, now + SESSION_TTL),
                )
                self._audit(conn, "login", email=email, ip_hash=iph)
                failure = False
        if failure:  # l'incrément doit survivre : on lève après la validation de la transaction
            raise bad
        return cookie, csrf, email, now + SESSION_TTL

    def session(self, cookie: str | None) -> dict | None:
        if not cookie or len(cookie) > 100:
            return None
        with self.db.tx() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE id = ?", (hashlib.sha256(cookie.encode()).hexdigest(),)).fetchone()
        if row is None or row["expires_at"] < self.now():
            return None
        return dict(row)

    def logout(self, cookie: str | None) -> None:
        if cookie:
            with self.db.tx() as conn:
                conn.execute("DELETE FROM sessions WHERE id = ?", (hashlib.sha256(cookie.encode()).hexdigest(),))

    def purge(self) -> None:
        now = self.now()
        with self.db.tx() as conn:
            conn.execute("DELETE FROM otp WHERE expires_at < ?", (now,))
            conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
            conn.execute("DELETE FROM stripe_events WHERE ts < ?", (now - 90 * DAY,))
        self.limiter.purge()
