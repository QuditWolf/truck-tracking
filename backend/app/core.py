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
    "send_fleet": "1",            # hard switch: when off, nothing at all is posted in the fleet group
    # three routing tiers, each to fleet and/or control
    "relay_fleet": "1",           # web reports, edits, deletes
    "relay_control": "1",
    "summary_fleet": "0",         # periodic, end-of-shift and "send now" summaries
    "summary_control": "1",
    "notice_fleet": "0",          # confirmations, questions, shift start/end, stale-shift warning
    "notice_control": "1",
    "read_fleet": "1",            # parse typed messages in the fleet group into reports
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
    ("users", "disabled_until", "TEXT"),  # temporary disable: access returns after this IST time
    ("manual_counts", "post_fleet", "INTEGER NOT NULL DEFAULT 1"),
]


def backup(conn: sqlite3.Connection, reason: str) -> Path | None:
    """Consistent online copy (sqlite backup API) into <db dir>/backups/. Keeps the newest 20."""
    if not Path(DB_PATH).exists() or conn.execute("PRAGMA database_list").fetchone()["file"] != str(Path(DB_PATH).resolve()):
        return None
    folder = Path(DB_PATH).parent / "backups"
    folder.mkdir(exist_ok=True)
    dest = folder / f"paddy-{datetime.now(IST):%Y%m%d-%H%M%S}-{reason}.db"
    with sqlite3.connect(dest) as out:
        conn.backup(out)
    for old in sorted(folder.glob("paddy-*.db"))[:-20]:
        old.unlink()
    return dest


def init_db(conn: sqlite3.Connection) -> None:
    """Additive only: new tables/indexes (IF NOT EXISTS), new columns (MIGRATIONS), new settings
    (INSERT OR IGNORE). Never drops or rewrites data. Backs up first if anything will change."""
    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    pending = [(t, c, d) for t, c, d in MIGRATIONS
               if t in tables and c not in {r["name"] for r in conn.execute(f"PRAGMA table_info({t})")}]
    if tables and (pending or not {"users", "registry", "reports", "shifts", "wa_log"} <= tables):
        dest = backup(conn, "pre-migration")
        if dest:
            print(f"database backed up to {dest} before migrating", flush=True)
    conn.executescript((Path(__file__).parent / "schema.sql").read_text())
    for table, col, ddl in MIGRATIONS:
        if col not in {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
    # fleet_mode (silent|full) → per-tier switches, keeping behaviour identical
    old = conn.execute("SELECT value FROM settings WHERE key = 'fleet_mode'").fetchone()
    if old and not conn.execute("SELECT 1 FROM settings WHERE key = 'summary_fleet'").fetchone():
        full = "1" if old["value"] == "full" else "0"
        for k in ("summary_fleet", "notice_fleet"):
            conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, full))
    for k, v in DEFAULT_SETTINGS.items():
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
    data_fixes(conn)


def data_fixes(conn: sqlite3.Connection) -> None:
    """One-time, audited corrections to live data. Each runs once (marker in settings)."""
    done = lambda key: conn.execute("SELECT 1 FROM settings WHERE key = ?", (key,)).fetchone()
    # BG (Bhandara Ground) is an unloading site; the first seed wrongly made it a depot,
    # which made ENTER/LEFT at BG invisible to the trip engine.
    if not done("_fix_bg_unloading"):
        row = conn.execute("SELECT id FROM registry WHERE kind = 'site' AND code = 'BG' COLLATE NOCASE "
                           "AND site_type = 'depot'").fetchone()
        if row:
            conn.execute("UPDATE registry SET site_type = 'unloading' WHERE id = ?", (row["id"],))
            audit(conn, None, "update", "registry", row["id"], before={"site_type": "depot"},
                  after={"site_type": "unloading", "reason": "BG is an unloading site"})
        conn.execute("INSERT INTO settings (key, value) VALUES ('_fix_bg_unloading', '1')")


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
