"""Base de datos SQLite (solo biblioteca estándar)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .config import SCHEMA_VERSION

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL, finished_at TEXT,
    roots TEXT NOT NULL,
    files INTEGER DEFAULT 0, bytes INTEGER DEFAULT 0, dirs INTEGER DEFAULT 0,
    errors INTEGER DEFAULT 0, seconds REAL DEFAULT 0,
    status TEXT NOT NULL            -- running | ok | interrupted
);

CREATE TABLE IF NOT EXISTS files (
    path TEXT PRIMARY KEY, root TEXT NOT NULL, parent TEXT NOT NULL,
    name TEXT NOT NULL, ext TEXT NOT NULL, size INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL, created_ns INTEGER NOT NULL,
    category TEXT NOT NULL,
    hint TEXT,                      -- whatsapp | captura | camara | copia
    cloud_only INTEGER NOT NULL DEFAULT 0,
    hash_quick TEXT, hash_full TEXT,
    last_seen_scan INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_files_size ON files(size);
CREATE INDEX IF NOT EXISTS idx_files_hash ON files(hash_full);
CREATE INDEX IF NOT EXISTS idx_files_cat ON files(category);
CREATE INDEX IF NOT EXISTS idx_files_root ON files(root);

CREATE TABLE IF NOT EXISTS dirs (
    path TEXT PRIMARY KEY, root TEXT NOT NULL, parent TEXT,
    depth INTEGER NOT NULL,
    kind TEXT NOT NULL DEFAULT 'normal',   -- normal | protected | project
    reason TEXT,
    measured INTEGER NOT NULL DEFAULT 1,
    direct_size INTEGER NOT NULL DEFAULT 0, direct_files INTEGER NOT NULL DEFAULT 0,
    total_size INTEGER NOT NULL DEFAULT 0, total_files INTEGER NOT NULL DEFAULT 0,
    last_seen_scan INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dirs_root ON dirs(root);

CREATE TABLE IF NOT EXISTS scan_errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT, scan_id INTEGER NOT NULL,
    path TEXT, error TEXT
);

CREATE TABLE IF NOT EXISTS programs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT,                    -- registro | winget | tienda
    name TEXT, version TEXT, publisher TEXT, install_date TEXT,
    install_location TEXT, size_kb INTEGER, identifier TEXT, collected_at TEXT
);

CREATE TABLE IF NOT EXISTS batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL,
    kind TEXT NOT NULL,             -- manual | watch | undo
    note TEXT
);

CREATE TABLE IF NOT EXISTS moves (   -- diario de cambios: de dónde salió y a dónde fue
    id INTEGER PRIMARY KEY AUTOINCREMENT, batch_id INTEGER NOT NULL, ts TEXT NOT NULL,
    src TEXT NOT NULL, dst TEXT NOT NULL,
    action TEXT NOT NULL,           -- move | quarantine | undo
    size INTEGER, reason TEXT, confidence REAL,
    status TEXT NOT NULL,           -- done | undone | missing
    undone_ts TEXT
);
CREATE INDEX IF NOT EXISTS idx_moves_batch ON moves(batch_id);

CREATE TABLE IF NOT EXISTS rules (      -- reglas tuyas o aprendidas de tus correcciones
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ext TEXT NOT NULL, hint TEXT NOT NULL DEFAULT '',
    dest_dir TEXT NOT NULL,
    source TEXT NOT NULL,           -- manual | learned
    created TEXT NOT NULL,
    UNIQUE(ext, hint)
);

CREATE TABLE IF NOT EXISTS suggestions (  -- sugerencias de la IA: esperan tu aprobación
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    src TEXT NOT NULL, dst_dir TEXT NOT NULL, label TEXT,
    confidence REAL, reason TEXT, size INTEGER, mtime_ns INTEGER,
    status TEXT NOT NULL DEFAULT 'pending',   -- pending | accepted | rejected
    created TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS steam_games (
    appid TEXT, name TEXT, install_dir TEXT, size_bytes INTEGER, library TEXT,
    collected_at TEXT
);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA_SQL)
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()
    return conn


def last_scan(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM scans ORDER BY id DESC LIMIT 1").fetchone()
