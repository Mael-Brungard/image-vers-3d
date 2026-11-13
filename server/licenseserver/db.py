"""Base SQLite (un seul fichier à sauvegarder). Une connexion par opération : sûr avec plusieurs threads et plusieurs processus."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS licenses (
    id            TEXT PRIMARY KEY,
    email         TEXT NOT NULL,
    key_hash      TEXT NOT NULL UNIQUE,
    status        TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'revoked')),
    revoked_reason TEXT,
    source        TEXT NOT NULL,
    source_ref    TEXT UNIQUE,
    payment_ref   TEXT,
    max_devices   INTEGER NOT NULL,
    created_at    INTEGER NOT NULL,
    note          TEXT
);
CREATE INDEX IF NOT EXISTS licenses_email ON licenses(email);
CREATE INDEX IF NOT EXISTS licenses_payment ON licenses(payment_ref);

CREATE TABLE IF NOT EXISTS activations (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    license_id   TEXT NOT NULL REFERENCES licenses(id),
    did          TEXT NOT NULL,
    name         TEXT,
    app_version  TEXT,
    created_at   INTEGER NOT NULL,
    last_seen_at INTEGER NOT NULL,
    released_at  INTEGER,
    UNIQUE (license_id, did)
);

CREATE TABLE IF NOT EXISTS trials (
    did        TEXT PRIMARY KEY,
    token      TEXT NOT NULL,
    ip_hash    TEXT,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS trials_ip ON trials(ip_hash, created_at);

CREATE TABLE IF NOT EXISTS otp (
    email      TEXT PRIMARY KEY,
    code_hash  TEXT NOT NULL,
    expires_at INTEGER NOT NULL,
    attempts   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS sessions (
    id         TEXT PRIMARY KEY,
    email      TEXT NOT NULL,
    csrf       TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS hits (
    bucket TEXT NOT NULL,
    ts     INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS hits_bucket ON hits(bucket, ts);

CREATE TABLE IF NOT EXISTS stripe_events (
    id TEXT PRIMARY KEY,
    ts INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS audit (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         INTEGER NOT NULL,
    kind       TEXT NOT NULL,
    license_id TEXT,
    email      TEXT,
    did        TEXT,
    ip_hash    TEXT,
    detail     TEXT
);
CREATE INDEX IF NOT EXISTS audit_license ON audit(license_id, kind, ts);
"""


class Database:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._connect()
        try:
            conn.executescript(SCHEMA)  # exécuté hors transaction : executescript valide tout ce qui est en cours
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=15000")
        return conn

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        """Transaction immédiate : les écritures concurrentes (deux activations simultanées) sont sérialisées."""
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            conn.close()
