"""Limitation de débit simple, partagée entre processus (table `hits`) : « au plus N événements par fenêtre »."""

from __future__ import annotations

from collections.abc import Callable

from .db import Database
from .protocol import LicenseError


class RateLimiter:
    def __init__(self, db: Database, clock: Callable[[], float]):
        self._db = db
        self._clock = clock

    def hit(self, bucket: str, limit: int, window_seconds: int, message: str = "Trop de tentatives. Réessaie dans quelques minutes.") -> None:
        """Enregistre un événement ; lève LicenseError("rate_limited") si la limite de la fenêtre est dépassée."""
        now = int(self._clock())
        with self._db.tx() as conn:
            count = conn.execute("SELECT COUNT(*) FROM hits WHERE bucket = ? AND ts > ?", (bucket, now - window_seconds)).fetchone()[0]
            if count >= limit:
                raise LicenseError("rate_limited", message)
            conn.execute("INSERT INTO hits(bucket, ts) VALUES (?, ?)", (bucket, now))

    def blocked(self, bucket: str, limit: int, window_seconds: int) -> bool:
        """Vrai si la limite est déjà atteinte (sans rien enregistrer) : pour ne compter que les ÉCHECS."""
        now = int(self._clock())
        with self._db.tx() as conn:
            count = conn.execute("SELECT COUNT(*) FROM hits WHERE bucket = ? AND ts > ?", (bucket, now - window_seconds)).fetchone()[0]
        return count >= limit

    def record(self, bucket: str) -> None:
        with self._db.tx() as conn:
            conn.execute("INSERT INTO hits(bucket, ts) VALUES (?, ?)", (bucket, int(self._clock())))

    def purge(self, older_than_seconds: int = 7 * 86400) -> None:
        with self._db.tx() as conn:
            conn.execute("DELETE FROM hits WHERE ts < ?", (int(self._clock()) - older_than_seconds,))
