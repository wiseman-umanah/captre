"""
Lightweight SQLite index: attestation_id → content_hash

Survives server restarts. Written on every successful attest/revoke.
Read by GET /attestation/:id.

DB location (in priority order):
  1. INDEX_DB_PATH env var  — set this on Render to a persistent-disk path, e.g. /data/index.db
  2. <project_root>/data/index.db  — used in local dev
"""

import os
import sqlite3
from pathlib import Path

# Project root is 3 levels up from src/captre/index_db.py
_PROJECT_ROOT = Path(__file__).parent.parent.parent

_env_db = os.environ.get("INDEX_DB_PATH", "").strip()
_DB_PATH = Path(_env_db) if _env_db else _PROJECT_ROOT / "data" / "index.db"


def _conn() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(_DB_PATH))
    con.execute(
        "CREATE TABLE IF NOT EXISTS idx "
        "(attestation_id TEXT PRIMARY KEY, content_hash TEXT NOT NULL)"
    )
    con.commit()
    return con


def put(attestation_id: str, content_hash: str) -> None:
    with _conn() as con:
        con.execute(
            "INSERT OR REPLACE INTO idx (attestation_id, content_hash) VALUES (?, ?)",
            (attestation_id, content_hash),
        )


def get(attestation_id: str) -> str | None:
    con = _conn()
    row = con.execute(
        "SELECT content_hash FROM idx WHERE attestation_id = ?", (attestation_id,)
    ).fetchone()
    con.close()
    return row[0] if row else None
