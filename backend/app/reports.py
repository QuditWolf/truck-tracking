"""Reports (one submission, 1+ trucks), shifts, and the bridge to the trip engine."""

from datetime import datetime, timedelta
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
        "trucks": sorted({reg.canon(t).code for t in truck_ids}),  # merged trucks collapse into one
        "verb": verb.code,
        "site": site.code if site else None,
        "site_as_reported": raw_site.code if raw_site else None,
        "event_time": row["event_time"],
        "remarks": row["remarks"],
        "deleted": bool(row["deleted"]),
        "wa_msg_id": row["wa_msg_id"],
        "skip_fleet": bool(row["skip_fleet"]) if "skip_fleet" in row.keys() else False,
        "half": bool(row["half"]) if "half" in row.keys() else False,
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
                        site.site_type if site else None, to_ist(report["event_time"]), report.get("user", ""),
                        bool(report.get("half")))
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


def flag_details(a: trips.Analysis, report_id: int, truck_codes: list[str]) -> list[dict]:
    """Structured flags for the live form: code, text, truck and the earlier report it refers to."""
    out, seen = [], set()
    for t in truck_codes:
        for f in a.flags.get((report_id, t), []):
            if f.text in seen:
                continue
            seen.add(f.text)
            ref = {"verb": f.ref.verb, "site": f.ref.site, "time": iso(f.ref.time), "user": f.ref.user} if f.ref else None
            out.append({"code": f.code, "text": f.text, "truck": t, "ref": ref})
    return out


def flags_for(a: trips.Analysis, report_id: int, truck_codes: list[str]) -> list[str]:
    """Flag texts for a report, de-duplicated (multi-truck reports share e.g. 'outside any shift')."""
    return list(dict.fromkeys(f.text for t in truck_codes for f in a.flags.get((report_id, t), [])))


def site_usage(conn, reg: Registry, shift: trips.Shift) -> dict[str, int]:
    """Truck-events per canonical site inside a shift's window."""
    rows = conn.execute(
        "SELECT r.site_id, COUNT(*) AS n FROM reports r JOIN report_trucks rt ON rt.report_id = r.id "
        "WHERE r.deleted = 0 AND r.site_id IS NOT NULL AND r.event_time >= ? AND (? IS NULL OR r.event_time <= ?) "
        "GROUP BY r.site_id",
        (iso(shift.start), shift.end and iso(shift.end), shift.end and iso(shift.end))).fetchall()
    out: dict[str, int] = {}
    for r in rows:
        site = reg.canon(r["site_id"])
        if site:
            out[site.code] = out.get(site.code, 0) + r["n"]
    return out


def sites_by_usage(conn, reg: Registry) -> list[dict]:
    """Site order for the report form, fixed for the whole shift: by events in the previous shift, then the
    one before (ties keep registry order). Tiles never move while people are reporting."""
    sites = reg.listing("site")
    shifts = load_shifts(conn)
    if not shifts:
        return sites
    cur_i = next((i for i in range(len(shifts) - 1, -1, -1) if shifts[i].end is None), len(shifts))
    prev = site_usage(conn, reg, shifts[cur_i - 1]) if cur_i >= 1 else {}
    prev2 = site_usage(conn, reg, shifts[cur_i - 2]) if cur_i >= 2 else {}
    row = open_shift(conn)
    mine = shift_sites(conn, reg, row) if row else []
    first = {code: i for i, code in enumerate(mine)}
    return sorted(sites, key=lambda s: (first.get(s["code"], len(first)),
                                        -prev.get(s["code"], 0), -prev2.get(s["code"], 0)))  # stable sort


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
            "event_time": minute(t), "remarks": (data.get("remarks") or "").strip(), "half": bool(data.get("half"))}


def _write_trucks(conn, reg: Registry, report_id: int, trucks: list[str]) -> None:
    conn.execute("DELETE FROM report_trucks WHERE report_id = ?", (report_id,))
    for code in trucks:
        conn.execute("INSERT INTO report_trucks (report_id, truck_id) VALUES (?, ?)",
                     (report_id, reg.find("truck", code, active_only=False).id))


def create_reports(conn, data: dict, verbs: list[str], user_id: int, source: str = "web", wa_msg_id=None,
                   skip_fleet: bool = False) -> list[dict]:
    """Several events reported together (H LO LEFT): one report per event, same time, in cycle order,
    relayed as one message."""
    from .trips import cycle_sort, mixed_phases
    verbs = cycle_sort([v.strip().upper() for v in verbs if v and v.strip()])
    if not verbs:
        raise ValueError("event required")
    if mixed_phases(verbs):
        raise ValueError("loading and unloading events can't be reported together")
    out = [create_report(conn, {**data, "verb": v}, user_id, source, wa_msg_id, skip_fleet, relay=False) for v in verbs]
    if source == "web":
        enqueue(conn, "report", {"report": out[0], "also": out[1:]})
    return out


def create_report(conn, data: dict, user_id: int, source: str = "web", wa_msg_id=None,
                  skip_fleet: bool = False, relay: bool = True) -> dict:
    reg = Registry(conn)
    n = normalize(conn, reg, data, user_id)
    ts = stamp()
    cur = conn.execute(
        "INSERT INTO reports (user_id, source, verb_id, site_id, event_time, remarks, wa_msg_id, skip_fleet, half, "
        "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (user_id, source, n["verb_id"], n["site_id"], n["event_time"], n["remarks"], wa_msg_id, int(skip_fleet),
         int(n["half"]), ts, ts),
    )
    rid = cur.lastrowid
    _write_trucks(conn, reg, rid, n["trucks"])
    report = get_report(conn, rid)
    audit(conn, user_id, "create", "report", rid, after=report)
    if source == "web" and relay:
        enqueue(conn, "report", {"report": report})
    return report


def update_report(conn, report_id: int, data: dict, user_id: int) -> dict:
    before = get_report(conn, report_id)
    reg = Registry(conn)
    n = normalize(conn, reg, {**before, **{k: v for k, v in data.items() if v is not None}}, user_id)
    conn.execute(
        "UPDATE reports SET verb_id=?, site_id=?, event_time=?, remarks=?, half=?, updated_at=? WHERE id=?",
        (n["verb_id"], n["site_id"], n["event_time"], n["remarks"], int(n["half"]), stamp(), report_id),
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


def shift_sites(conn, reg: Registry, row) -> list[str]:
    """The shift's sites in order (canonical codes); falls back to the single default site of older shifts."""
    ids = [r["site_id"] for r in conn.execute("SELECT site_id FROM shift_sites WHERE shift_id = ? ORDER BY sort",
                                              (row["id"],))]
    if not ids and row["default_site_id"]:
        ids = [row["default_site_id"]]
    return list(dict.fromkeys(c.code for i in ids if (c := reg.canon(i))))


def _set_shift_sites(conn, reg: Registry, shift_id: int, sites: list[str], user_id) -> Optional[int]:
    ids = list(dict.fromkeys(resolve_or_create(conn, reg, "site", s, user_id).id for s in sites if s and s.strip()))
    conn.execute("DELETE FROM shift_sites WHERE shift_id = ?", (shift_id,))  # link rows only; sites themselves stay
    for i, site_id in enumerate(ids):
        conn.execute("INSERT INTO shift_sites (shift_id, site_id, sort) VALUES (?,?,?)", (shift_id, site_id, i))
    conn.execute("UPDATE shifts SET default_site_id = ? WHERE id = ?", (ids[0] if ids else None, shift_id))
    return ids[0] if ids else None


def shift_dict(conn, reg: Registry, row) -> dict:
    keys = row.keys()
    sites = shift_sites(conn, reg, row)
    return {"id": row["id"], "started_at": row["started_at"], "ended_at": row["ended_at"],
            "default_site": sites[0] if sites else None, "sites": sites, "open": row["ended_at"] is None,
            "started_by": _user_name(conn, row["started_by"]) if "started_by" in keys and row["started_by"] else "",
            "ended_by": _user_name(conn, row["ended_by"]) if "ended_by" in keys and row["ended_by"] else ""}


def open_shift(conn):
    return conn.execute(
        "SELECT * FROM shifts WHERE deleted = 0 AND ended_at IS NULL ORDER BY started_at DESC LIMIT 1"
    ).fetchone()


def _overlaps(conn, start: str, end: Optional[str], exclude: Optional[int] = None) -> bool:
    """Would this shift overlap another? Open shifts extend to +inf. Touching at one minute is allowed
    (that minute belongs to the earlier shift)."""
    far = "9999"
    for r in conn.execute("SELECT id, started_at, ended_at FROM shifts WHERE deleted = 0").fetchall():
        if r["id"] == exclude:
            continue
        if to_ist(start) < to_ist(r["ended_at"] or far + "-01-01") and to_ist(r["started_at"]) < to_ist(end or far + "-01-01"):
            return True
    return False


def start_shift(conn, user_id: int, site: Optional[str] = None, at: Optional[str] = None,
                sites: Optional[list[str]] = None) -> dict:
    reg = Registry(conn)
    start = minute(at or now())
    cur = open_shift(conn)
    if cur:  # one open shift at a time: starting a new one ends the old one
        if to_ist(start) <= to_ist(cur["started_at"]):
            raise ValueError("new shift must start after the open shift started")
        # previous shift ends the minute before, so reports in the new shift's first minute belong to it
        end_shift(conn, user_id, at=iso(to_ist(start) - timedelta(minutes=1)))
    if _overlaps(conn, start, None):
        raise ValueError("shift would overlap an existing shift")
    c = conn.execute("INSERT INTO shifts (started_at, started_by) VALUES (?,?)", (start, user_id))
    _set_shift_sites(conn, reg, c.lastrowid, sites if sites is not None else [site] if site else [], user_id)
    row = conn.execute("SELECT * FROM shifts WHERE id = ?", (c.lastrowid,)).fetchone()
    out = shift_dict(conn, reg, row)
    audit(conn, user_id, "start", "shift", c.lastrowid, after=out)
    enqueue(conn, "shift", {"action": "start", "shift": out, "user": _user_name(conn, user_id)})
    return out


def create_past_shift(conn, user_id: int, started_at: str, ended_at: str, sites: list[str]) -> dict:
    """Admin: record a shift that already happened (closed). Doesn't touch the running shift; no overlaps."""
    reg = Registry(conn)
    start, end = minute(started_at), minute(ended_at)
    if to_ist(end) < to_ist(start):
        raise ValueError("shift must end after it started")
    if to_ist(end) > now():
        raise ValueError("a recorded shift must have ended already")
    if _overlaps(conn, start, end):
        raise ValueError("shift would overlap an existing shift")
    c = conn.execute("INSERT INTO shifts (started_at, ended_at, started_by, ended_by) VALUES (?,?,?,?)",
                     (start, end, user_id, user_id))
    _set_shift_sites(conn, reg, c.lastrowid, sites, user_id)
    out = shift_dict(conn, reg, conn.execute("SELECT * FROM shifts WHERE id = ?", (c.lastrowid,)).fetchone())
    audit(conn, user_id, "create", "shift", c.lastrowid, after=out)
    return out


def split_shift(conn, shift_id: int, user_id: int, at: str) -> dict:
    """Admin: someone forgot to end a shift. It ends at `at` − 1 min and a new shift (same sites) starts at
    `at`, running to the old end (or still open). Reports fall into whichever shift their time is in;
    hand-added counts stay with the first shift."""
    reg = Registry(conn)
    row = conn.execute("SELECT * FROM shifts WHERE id = ? AND deleted = 0", (shift_id,)).fetchone()
    if not row:
        raise ValueError("shift not found")
    at = minute(at)
    if not to_ist(row["started_at"]) < to_ist(at) or (row["ended_at"] and to_ist(at) > to_ist(row["ended_at"])):
        raise ValueError("split time must be inside the shift")
    first_end = iso(to_ist(at) - timedelta(minutes=1))
    conn.execute("UPDATE shifts SET ended_at = ?, ended_by = ? WHERE id = ?", (first_end, user_id, shift_id))
    c = conn.execute("INSERT INTO shifts (started_at, ended_at, started_by, ended_by) VALUES (?,?,?,?)",
                     (at, row["ended_at"], user_id, row["ended_by"]))
    _set_shift_sites(conn, reg, c.lastrowid, shift_sites(conn, reg, row), user_id)
    out = shift_dict(conn, reg, conn.execute("SELECT * FROM shifts WHERE id = ?", (c.lastrowid,)).fetchone())
    audit(conn, user_id, "split", "shift", shift_id, before=dict(row), after={"ended_at": first_end, "new_shift": out})
    return out


def end_shift(conn, user_id: int, at: Optional[str] = None) -> dict:
    cur = open_shift(conn)
    if not cur:
        raise ValueError("no open shift")
    end = minute(at or now())
    if to_ist(end) < to_ist(cur["started_at"]):
        raise ValueError("shift must end after it started")
    conn.execute("UPDATE shifts SET ended_at = ?, ended_by = ? WHERE id = ?", (end, user_id, cur["id"]))
    row = conn.execute("SELECT * FROM shifts WHERE id = ?", (cur["id"],)).fetchone()
    out = shift_dict(conn, Registry(conn), row)
    audit(conn, user_id, "end", "shift", cur["id"], before=dict(cur), after=out)
    enqueue(conn, "shift", {"action": "end", "shift": out, "user": _user_name(conn, user_id)})
    return out


def edit_shift(conn, shift_id: int, user_id: int, started_at=None, ended_at=None, site=None,
               deleted=None, sites=None) -> dict:
    reg = Registry(conn)
    row = conn.execute("SELECT * FROM shifts WHERE id = ?", (shift_id,)).fetchone()
    if not row:
        raise ValueError("not found")
    start = minute(started_at) if started_at else row["started_at"]
    end = (minute(ended_at) if ended_at else None) if ended_at is not None else row["ended_at"]
    if end and to_ist(end) < to_ist(start):
        raise ValueError("shift must end after it started")
    if not deleted and _overlaps(conn, start, end, exclude=shift_id):
        raise ValueError("shift would overlap an existing shift")
    if end is None and open_shift(conn) and open_shift(conn)["id"] != shift_id:
        raise ValueError("another shift is already open")
    conn.execute("UPDATE shifts SET started_at=?, ended_at=?, deleted=? WHERE id=?",
                 (start, end, int(deleted if deleted is not None else row["deleted"]), shift_id))
    if sites is not None or site:
        _set_shift_sites(conn, reg, shift_id, sites if sites is not None else [site], user_id)
    new = conn.execute("SELECT * FROM shifts WHERE id = ?", (shift_id,)).fetchone()
    out = shift_dict(conn, reg, new)
    audit(conn, user_id, "update", "shift", shift_id, before=dict(row), after=out)
    return out
