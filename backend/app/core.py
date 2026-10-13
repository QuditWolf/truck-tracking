"""Config, IST time helpers, DB connection, audit."""

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

DB_PATH = os.environ.get("PADDY_DB", str(Path(__file__).parent.parent / "data" / "paddy.db"))
SECRET = os.environ.get("PADDY_SECRET", "dev-secret-change-me")
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
ADMIN_EMAILS = {e.strip().lower() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()}
DEV_LOGIN = os.environ.get("DEV_LOGIN", "") == "1"  # allow email-only login for local dev

DEFAULT_SETTINGS = {
    "fleet_mode": "silent",       # silent: fleet group gets relays only | full: also confirmations + summaries
    "summary_interval_min": "15",
    "shift_stale_hours": "14",
}


def now() -> datetime:
    """Current IST time at minute precision — all reported times are whole minutes."""
    return datetime.now(IST).replace(second=0, microsecond=0)


def stamp() -> str:
    """Precise IST timestamp for bookkeeping (audit, created_at)."""
    return datetime.now(IST).replace(microsecond=0).isoformat()


def to_ist(value: str | datetime) -> datetime:
    """Parse ISO string (naive = IST) and normalise to IST."""
    dt = datetime.fromisoformat(value) if isinstance(value, str) else value
    return dt.replace(tzinfo=IST) if dt.tzinfo is None else dt.astimezone(IST)


def iso(dt: datetime) -> str:
    return to_ist(dt).replace(microsecond=0).isoformat()


def minute(value: str | datetime) -> str:
    """ISO string for an event/shift time, truncated to the minute."""
    return iso(to_ist(value).replace(second=0, microsecond=0))


def connect(path: str | None = None) -> sqlite3.Connection:
    path = path or DB_PATH
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript((Path(__file__).parent / "schema.sql").read_text())
    for k, v in DEFAULT_SETTINGS.items():
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))


@contextmanager
def tx(conn: sqlite3.Connection):
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def audit(conn, user_id, action: str, entity: str, entity_id, before=None, after=None) -> None:
    conn.execute(
        "INSERT INTO audit (at, user_id, action, entity, entity_id, before, after) VALUES (?,?,?,?,?,?,?)",
        (stamp(), user_id, action, entity, entity_id,
         json.dumps(before, default=str) if before is not None else None,
         json.dumps(after, default=str) if after is not None else None),
    )


def enqueue(conn, kind: str, payload: dict) -> None:
    conn.execute("INSERT INTO outbox (at, kind, payload) VALUES (?, ?, ?)",
                 (stamp(), kind, json.dumps(payload, default=str)))


def setting(conn, key: str) -> str:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else DEFAULT_SETTINGS[key]
