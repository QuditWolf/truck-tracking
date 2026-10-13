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
    # WhatsApp — all editable in Admin → WhatsApp
    "wa_enabled": "0",            # master switch: nothing is sent or read when off
    "fleet_jid": "",              # fleet group (operators post events here)
    "control_jid": "",            # control group (shifts, summaries, questions)
    "relay_fleet": "1",           # relay web reports into the fleet group
    "relay_control": "1",         # relay web reports into the control group
    "read_fleet": "1",            # parse typed messages in the fleet group into reports
    "fleet_mode": "silent",       # silent: fleet group gets relays only | full: also confirmations + summaries
    "summary_interval_min": "15", # periodic summary during an open shift; 0 = off
    "summary_on_shift_end": "1",
    "shift_stale_hours": "14",
}
WA_URL = os.environ.get("WA_URL", "http://127.0.0.1:3001")


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


# Columns added after first deploy: (table, column, DDL). CREATE TABLE IF NOT EXISTS won't add them.
MIGRATIONS = [
    ("registry", "plate", "TEXT NOT NULL DEFAULT ''"),
    ("registry", "notes", "TEXT NOT NULL DEFAULT ''"),
    ("outbox", "status", "TEXT NOT NULL DEFAULT 'pending'"),  # pending | sent | skipped | failed
]


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript((Path(__file__).parent / "schema.sql").read_text())
    for table, col, ddl in MIGRATIONS:
        if col not in {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
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
    return row["value"] if row else DEFAULT_SETTINGS.get(key, "")


def flag(conn, key: str) -> bool:
    return setting(conn, key) == "1"


def set_setting(conn, key: str, value: str) -> None:
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
