"""SQLite storage.

Plain sqlite3 rather than an ORM: the schema is small, and a self-hosted box
benefits from having no migration machinery to get wrong. Connections are
short-lived (one per operation) so the poller loop and the HTTP API can share
the file safely; WAL mode keeps readers from blocking the writer.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS tgtg_credentials (
    id                      INTEGER PRIMARY KEY CHECK (id = 1),
    email                   TEXT,
    access_token            TEXT NOT NULL,
    refresh_token           TEXT NOT NULL,
    cookie                  TEXT NOT NULL,
    last_time_token_refreshed TEXT,
    -- Pinned at login so a poller restart never has to scrape Google Play for
    -- the current app version, which is slow and fails unpredictably.
    user_agent              TEXT,
    updated_at              TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS watches (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    label           TEXT NOT NULL DEFAULT '',
    store_pattern   TEXT,
    bag_pattern     TEXT,
    max_price_minor INTEGER,
    latitude        REAL NOT NULL,
    longitude       REAL NOT NULL,
    radius_km       INTEGER NOT NULL DEFAULT 10,
    enabled         INTEGER NOT NULL DEFAULT 1,
    -- Set after the first successful poll. Until then, observations are
    -- recorded silently so the initial survey does not alert on everything
    -- already in stock. Cleared by "re-baseline" to start fresh.
    baselined_at    TEXT,
    -- Opt-in: also ping when an already-available bag's count goes up.
    notify_on_increase INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS devices (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    expo_push_token TEXT NOT NULL UNIQUE,
    platform        TEXT,
    label           TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Per-watch, per-item state. This is the memory that makes 0 -> >0 detection
-- possible: without a remembered previous quantity every poll would look like
-- a fresh sighting and the user would be spammed.
CREATE TABLE IF NOT EXISTS observations (
    watch_id         INTEGER NOT NULL REFERENCES watches(id) ON DELETE CASCADE,
    item_id          TEXT NOT NULL,
    store_id         TEXT,
    store_name       TEXT,
    display_name     TEXT,
    last_quantity    INTEGER NOT NULL DEFAULT 0,
    last_price_minor INTEGER,
    first_seen_at    TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen_at     TEXT NOT NULL DEFAULT (datetime('now')),
    last_alerted_at  TEXT,
    PRIMARY KEY (watch_id, item_id)
);

CREATE INDEX IF NOT EXISTS idx_observations_item ON observations(item_id);

CREATE TABLE IF NOT EXISTS alerts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    watch_id    INTEGER,
    item_id     TEXT,
    title       TEXT NOT NULL,
    body        TEXT NOT NULL,
    devices_ok  INTEGER NOT NULL DEFAULT 0,
    devices_err INTEGER NOT NULL DEFAULT 0,
    error       TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_alerts_created ON alerts(created_at DESC);

-- Caches one get_items response per location bucket so N watches in the same
-- area cost one API call, not N. TGTG rate-limits per account, so this is the
-- difference between polite and banned.
CREATE TABLE IF NOT EXISTS page_cache (
    bucket_key  TEXT PRIMARY KEY,
    payload     TEXT NOT NULL,
    fetched_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- One row per poll pass. This is what lets the app answer "is this actually
-- working?" -- the failure mode we designed against is a tracker that looks
-- fine but has been silently blocked for six hours.
CREATE TABLE IF NOT EXISTS poll_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at TEXT,
    watches     INTEGER NOT NULL DEFAULT 0,
    buckets     INTEGER NOT NULL DEFAULT 0,
    items_seen  INTEGER NOT NULL DEFAULT 0,
    matched     INTEGER NOT NULL DEFAULT 0,
    alerts      INTEGER NOT NULL DEFAULT 0,
    errors      INTEGER NOT NULL DEFAULT 0,
    blocked     INTEGER NOT NULL DEFAULT 0,
    note        TEXT
);

CREATE INDEX IF NOT EXISTS idx_poll_runs_started ON poll_runs(started_at DESC);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing_connection(db_path) as conn:
        conn.executescript(SCHEMA)
        conn.commit()


@contextmanager
def closing_connection(db_path: Path) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def transaction(db_path: Path) -> Iterator[sqlite3.Connection]:
    """Connection wrapped in a transaction, committed on clean exit."""
    with closing_connection(db_path) as conn:
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
