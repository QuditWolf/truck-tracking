"""Reports (one submission, 1+ trucks), shifts, and the bridge to the trip engine."""

from datetime import datetime
from typing import Optional

from . import trips
from .core import audit, enqueue, iso, minute, now, stamp, to_ist
from .registry import Registry, resolve_or_create

DRAFT_ID = -1


# ── reading ─────────────────────────────────────────────────────────────────

def report_dict(conn, reg: Registry, row) -> dict:
    truck_ids = [r["truck_id"] for r in conn.execute(
        "SELECT truck_id FROM report_trucks WHERE report_id = ? ORDER BY truck_id", (row["id"],))]
    user = conn.execute("SELECT name FROM users WHERE id = ?", (row["user_id"],)).fetchone()
    verb, site = reg.canon(row["verb_id"]), reg.canon(row["site_id"])
    raw_site = reg.by_id.get(row["site_id"])
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "user": user["name"] if user else "?",
        "source": row["source"],
        "trucks": sorted(reg.canon(t).code for t in truck_ids),
        "verb": verb.code,
        "site": site.code if site else None,
        "site_as_reported": raw_site.code if raw_site else None,
        "event_time": row["event_time"],
        "remarks": row["remarks"],
        "deleted": bool(row["deleted"]),
        "wa_msg_id": row["wa_msg_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def get_report(conn, report_id: int) -> Optional[dict]:
    row = conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
    return report_dict(conn, Registry(conn), row) if row else None


def load_shifts(conn) -> list[trips.Shift]:
    return [trips.Shift(r["id"], to_ist(r["started_at"]), to_ist(r["ended_at"]) if r["ended_at"] else None)
            for r in conn.execute("SELECT * FROM shifts WHERE deleted = 0 ORDER BY started_at")]


def to_events(reg: Registry, report: dict) -> list[trips.Event]:
    site = reg.find("site", report["site"], active_only=False) if report.get("site") else None
    return [trips.Event(report["id"], t, report["verb"], site.code if site else None,
                        site.site_type if site else None, to_ist(report["event_time"]), report.get("user", ""))
            for t in report["trucks"]]


def load_events(conn, reg: Registry, since: Optional[datetime] = None) -> list[trips.Event]:
    q = "SELECT * FROM reports WHERE deleted = 0"
    args: list = []
    if since:
        q += " AND event_time >= ?"
        args.append(iso(since))
    out = []
    for row in conn.execute(q, args).fetchall():
        out += to_events(reg, report_dict(conn, reg, row))
    return out


def analysis(conn, reg: Optional[Registry] = None, draft: Optional[dict] = None,
             exclude_id: Optional[int] = None) -> trips.Analysis:
    reg = reg or Registry(conn)
    events = [e for e in load_events(conn, reg) if e.report_id != exclude_id]
    if draft:
        events += to_events(reg, {**draft, "id": DRAFT_ID})
    return trips.analyze(events, load_shifts(conn))


def flags_for(a: trips.Analysis, report_id: int, truck_codes: list[str]) -> list[str]:
    """Flag texts for a report, de-duplicated (multi-truck reports share e.g. 'outside any shift')."""
    return list(dict.fromkeys(f.text for t in truck_codes for f in a.flags.get((report_id, t), [])))


# ── writing ─────────────────────────────────────────────────────────────────

def normalize(conn, reg: Registry, data: dict, user_id) -> dict:
    """Resolve free-text truck/site/verb to registry codes, creating unknown ones (web path)."""
    trucks = sorted({resolve_or_create(conn, reg, "truck", t, user_id).code
                     for t in data["trucks"] if t.strip()})
    if not trucks:
        raise ValueError("at least one truck")
    if not data.get("verb", "").strip():
        raise ValueError("verb required")
    verb = resolve_or_create(conn, reg, "verb", data["verb"], user_id)
    site = resolve_or_create(conn, reg, "site", data["site"], user_id) if data.get("site", "").strip() else None
    t = to_ist(data["event_time"]) if data.get("event_time") else now()
    return {"trucks": trucks, "verb": verb.code, "verb_id": verb.id,
            "site": site.code if site else None, "site_id": site.id if site else None,
            "event_time": minute(t), "remarks": (data.get("remarks") or "").strip()}


def _write_trucks(conn, reg: Registry, report_id: int, trucks: list[str]) -> None:
    conn.execute("DELETE FROM report_trucks WHERE report_id = ?", (report_id,))
    for code in trucks:
        conn.execute("INSERT INTO report_trucks (report_id, truck_id) VALUES (?, ?)",
                     (report_id, reg.find("truck", code, active_only=False).id))


def create_report(conn, data: dict, user_id: int, source: str = "web", wa_msg_id=None) -> dict:
    reg = Registry(conn)
    n = normalize(conn, reg, data, user_id)
    ts = stamp()
    cur = conn.execute(
        "INSERT INTO reports (user_id, source, verb_id, site_id, event_time, remarks, wa_msg_id, "
        "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (user_id, source, n["verb_id"], n["site_id"], n["event_time"], n["remarks"], wa_msg_id, ts, ts),
    )
    rid = cur.lastrowid
    _write_trucks(conn, reg, rid, n["trucks"])
    report = get_report(conn, rid)
    audit(conn, user_id, "create", "report", rid, after=report)
    if source == "web":
        enqueue(conn, "report", {"report": report})
    return report


def update_report(conn, report_id: int, data: dict, user_id: int) -> dict:
    before = get_report(conn, report_id)
    reg = Registry(conn)
    n = normalize(conn, reg, {**before, **{k: v for k, v in data.items() if v is not None}}, user_id)
    conn.execute(
        "UPDATE reports SET verb_id=?, site_id=?, event_time=?, remarks=?, updated_at=? WHERE id=?",
        (n["verb_id"], n["site_id"], n["event_time"], n["remarks"], stamp(), report_id),
    )
    _write_trucks(conn, reg, report_id, n["trucks"])
    after = get_report(conn, report_id)
    audit(conn, user_id, "update", "report", report_id, before=before, after=after)
    enqueue(conn, "edit", {"before": before, "after": after})
    return after


def delete_report(conn, report_id: int, user_id: int) -> None:
    before = get_report(conn, report_id)
    conn.execute("UPDATE reports SET deleted = 1, updated_at = ? WHERE id = ?", (stamp(), report_id))
    audit(conn, user_id, "delete", "report", report_id, before=before)
    enqueue(conn, "delete", {"report": before})


# ── shifts ──────────────────────────────────────────────────────────────────

def _user_name(conn, user_id) -> str:
    row = conn.execute("SELECT name FROM users WHERE id = ?", (user_id,)).fetchone()
    return row["name"] or "" if row else ""


def shift_dict(conn, reg: Registry, row) -> dict:
    site = reg.canon(row["default_site_id"])
    return {"id": row["id"], "started_at": row["started_at"], "ended_at": row["ended_at"],
            "default_site": site.code if site else None, "open": row["ended_at"] is None}


def open_shift(conn):
    return conn.execute(
        "SELECT * FROM shifts WHERE deleted = 0 AND ended_at IS NULL ORDER BY started_at DESC LIMIT 1"
    ).fetchone()


def _overlaps(conn, start: str, end: Optional[str], exclude: Optional[int] = None) -> bool:
    """Shift [start, end) overlaps any other non-deleted shift? Open shifts extend to +inf."""
    far = "9999"
    for r in conn.execute("SELECT id, started_at, ended_at FROM shifts WHERE deleted = 0").fetchall():
        if r["id"] == exclude:
            continue
        if to_ist(start) < to_ist(r["ended_at"] or far + "-01-01") and to_ist(r["started_at"]) < to_ist(end or far + "-01-01"):
            return True
    return False


def start_shift(conn, user_id: int, site: Optional[str] = None, at: Optional[str] = None) -> dict:
    reg = Registry(conn)
    start = minute(at or now())
    cur = open_shift(conn)
    if cur:  # one open shift at a time: starting a new one ends the old one
        if to_ist(start) <= to_ist(cur["started_at"]):
            raise ValueError("new shift must start after the open shift started")
        end_shift(conn, user_id, at=start)
    if _overlaps(conn, start, None):
        raise ValueError("shift would overlap an existing shift")
    site_id = resolve_or_create(conn, reg, "site", site, user_id).id if site else None
    c = conn.execute("INSERT INTO shifts (started_at, default_site_id, started_by) VALUES (?,?,?)",
                     (start, site_id, user_id))
    row = conn.execute("SELECT * FROM shifts WHERE id = ?", (c.lastrowid,)).fetchone()
    out = shift_dict(conn, reg, row)
    audit(conn, user_id, "start", "shift", c.lastrowid, after=out)
    enqueue(conn, "shift", {"action": "start", "shift": out, "user": _user_name(conn, user_id)})
    return out


def end_shift(conn, user_id: int, at: Optional[str] = None) -> dict:
    cur = open_shift(conn)
    if not cur:
        raise ValueError("no open shift")
    end = minute(at or now())
    if to_ist(end) <= to_ist(cur["started_at"]):
        raise ValueError("shift must end after it started")
    conn.execute("UPDATE shifts SET ended_at = ?, ended_by = ? WHERE id = ?", (end, user_id, cur["id"]))
    row = conn.execute("SELECT * FROM shifts WHERE id = ?", (cur["id"],)).fetchone()
    out = shift_dict(conn, Registry(conn), row)
    audit(conn, user_id, "end", "shift", cur["id"], before=dict(cur), after=out)
    enqueue(conn, "shift", {"action": "end", "shift": out, "user": _user_name(conn, user_id)})
    return out


def edit_shift(conn, shift_id: int, user_id: int, started_at=None, ended_at=None, site=None,
               deleted=None) -> dict:
    reg = Registry(conn)
    row = conn.execute("SELECT * FROM shifts WHERE id = ?", (shift_id,)).fetchone()
    if not row:
        raise ValueError("not found")
    start = minute(started_at) if started_at else row["started_at"]
    end = (minute(ended_at) if ended_at else None) if ended_at is not None else row["ended_at"]
    if end and to_ist(end) <= to_ist(start):
        raise ValueError("shift must end after it started")
    if not deleted and _overlaps(conn, start, end, exclude=shift_id):
        raise ValueError("shift would overlap an existing shift")
    if end is None and open_shift(conn) and open_shift(conn)["id"] != shift_id:
        raise ValueError("another shift is already open")
    site_id = resolve_or_create(conn, reg, "site", site, user_id).id if site else row["default_site_id"]
    conn.execute("UPDATE shifts SET started_at=?, ended_at=?, default_site_id=?, deleted=? WHERE id=?",
                 (start, end, site_id, int(deleted if deleted is not None else row["deleted"]), shift_id))
    new = conn.execute("SELECT * FROM shifts WHERE id = ?", (shift_id,)).fetchone()
    out = shift_dict(conn, reg, new)
    audit(conn, user_id, "update", "shift", shift_id, before=dict(row), after=out)
    return out
