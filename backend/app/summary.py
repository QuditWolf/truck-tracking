"""Shift / day / season summaries — counts for WhatsApp, details for the web."""

from datetime import date
from statistics import mean
from typing import Optional

from . import trips
from .core import iso as core_iso, now, to_ist
from .reports import analysis, load_shifts


def time_range(sh: dict) -> str:
    """'15:38-19:04' (or '15:38-now') for a shift dict."""
    start = to_ist(sh["started_at"])
    return f"{start:%d %b %H:%M}-" + (f"{to_ist(sh['ended_at']):%H:%M}" if sh.get("ended_at") else "now")


def shift_label(shift: trips.Shift, all_shifts: list[trips.Shift]) -> str:
    same_day = [s for s in all_shifts if s.start.date() == shift.start.date()]
    n = sorted(same_day, key=lambda s: s.start).index(shift) + 1
    if not shift.end:
        end = "now"
    elif shift.end.date() != shift.start.date():
        end = f"{shift.end:%d %b %H:%M}"  # overnight: say which day it ended
    else:
        end = f"{shift.end:%H:%M}"
    return f"Shift {shift.start:%d %b} #{n} {shift.start:%H:%M}-{end}" + (" (ended)" if shift.end else "")


def _sites(d: dict) -> str:
    return ", ".join(f"{k} {v}" for k, v in sorted(d.items(), key=lambda kv: (-kv[1], kv[0])) if v > 0)


# Order of the per-truck lines. A truck can be in "Loading" now and also have loads counted.
# Only LS puts a truck in "Loading"; ENTER is "At loading site"; LO / LEFT loading site is "Hauling to unload"
# until the truck reaches an unloading site. The empty return trip isn't tracked.
POSITION_LINES = [("loading", "Loading"), ("en_route", "Hauling to unload"), ("loaded", "Loaded"), ("unloaded", "Unloaded"), ("unloading", "Unloading"),
                  ("at_loading", "At loading site"), ("at_unloading", "At unloading site")]


def counts_text(title: str, c: trips.Counts, notes: bool = True) -> str:
    """WhatsApp summary: title / totals (Loaded in *bold*, hauling, Unloaded) / per-truck detail.
    Final counts only; inferred/manual detail lives on the web page."""
    totals = [f"Loaded *{c.loaded}*" + (f": {_sites(c.loaded_by_site)}" if _sites(c.loaded_by_site) else "")]
    if hauling := c.position.get("en_route"):
        totals.append(f"Hauling to unload: {len(hauling)} ({','.join(hauling)})")
    totals.append(f"Unloaded {c.unloaded}" + (f": {_sites(c.unloaded_by_site)}" if _sites(c.unloaded_by_site) else ""))

    per = {k: " ".join(f"{t}*{p[k]}" for t, p in sorted(c.per_truck.items()) if p[k] > 0) for k in ("loads", "unloads")}
    detail = []
    for key, label in POSITION_LINES:
        if key == "en_route":
            continue  # shown with the totals
        if key in ("loaded", "unloaded"):
            if v := per["loads" if key == "loaded" else "unloads"]:
                detail.append(f"{label}: {v}")  # per truck, this shift
        elif v := c.position.get(key):
            detail.append(f"{label}: {','.join(v)}")
    return "\n\n".join("\n".join(block) for block in ([title], totals, detail) if block)


def _minutes(a, b) -> Optional[float]:
    return (b.time - a.time).total_seconds() / 60 if a and b else None


def _avg(xs) -> Optional[int]:
    xs = [x for x in xs if x is not None and x >= 0]
    return round(mean(xs)) if xs else None


def durations(seg: trips.Segment) -> dict:
    """Average minutes per phase, overall and per truck. Only from reported (not inferred) events."""
    rows = []
    for truck, ts in seg.trips.items():
        for i, t in enumerate(ts):
            s = t.slots
            nxt = ts[i + 1] if i + 1 < len(ts) else None
            rows.append({
                "truck": truck,
                "loading": _minutes(s.get(1), s.get(2)),
                "haul": _minutes(s.get(2) or s.get(3), s.get(4) or s.get(5)),
                "unloading": _minutes(s.get(5), s.get(6)),
                "cycle": _minutes(s.get(1), nxt.slots.get(1)) if nxt else None,
            })
    keys = ("loading", "haul", "unloading", "cycle")
    return {
        "overall": {k: _avg(r[k] for r in rows) for k in keys},
        "per_truck": {tr: {k: _avg(r[k] for r in rows if r["truck"] == tr) for k in keys}
                      for tr in sorted({r["truck"] for r in rows})},
    }


def _trip_view(t: trips.Trip) -> dict:
    return {
        "slots": {trips.SLOT_NAMES[k] + ("@U" if k in (4, 7) else ""): f"{e.time:%H:%M}"
                  for k, e in sorted(t.slots.items())},
        "load_site": t.load_site, "unload_site": t.unload_site,
        "loaded": t.loaded, "unloaded": t.unloaded, "closed": t.closed, "carry_in": t.carry_in,
        "duplicates": len(t.duplicates),
    }


def manual_entries(conn, shift_id: int) -> list[dict]:
    rows = conn.execute("SELECT m.*, u.name AS user FROM manual_counts m JOIN users u ON u.id = m.user_id "
                        "WHERE m.shift_id = ? AND m.deleted = 0 ORDER BY m.id", (shift_id,)).fetchall()
    return [dict(r) for r in rows]


def manual_text(m: dict) -> str:
    sign = "-" if m.get("negative") else "+"
    what = f"{sign}{m['count']} {m['kind']}{'s' if m['count'] > 1 else ''}"
    return " ".join(x for x in (m["truck"] or "Shift", what, m.get("site") or "", "(half)" if m.get("half") else "",
                                ) if x)


def apply_manual(conn, shift_id: int, c: trips.Counts) -> list[dict]:
    """Add hand-entered counts for untracked trucks into the shift's counts.
    Truck names resolve through the registry at read time, so later merges apply."""
    from .registry import Registry
    reg = Registry(conn)
    entries = manual_entries(conn, shift_id)
    for m in entries:
        known = reg.find("truck", m["truck"], active_only=False)
        if known:
            m["truck"] = known.code
        n, site = m["count"] * (-1 if m.get("negative") else 1), m["site"] or "?"
        size = n * (0.5 if m.get("half") else 1.0)
        # shift-level corrections (no truck) change totals only
        pt = c.per_truck.setdefault(m["truck"], {"trips": 0, "loads": 0, "unloads": 0}) if m["truck"] \
            else {"trips": 0, "loads": 0, "unloads": 0}
        if m["kind"] == "load":
            c.loaded += n
            c.loaded_manual += n
            c.loaded_abs += size
            if m["site"] or n > 0:  # a correction without a site changes the total only
                c.loaded_by_site[site] = c.loaded_by_site.get(site, 0) + n
            pt["loads"] += n
        else:
            c.unloaded += n
            c.unloaded_manual += n
            c.unloaded_abs += size
            if m["site"] or n > 0:
                c.unloaded_by_site[site] = c.unloaded_by_site.get(site, 0) + n
            pt["unloads"] += n
        from .relay import who
        name = who(conn, m["user"] or "")
        c.loaded, c.unloaded = max(c.loaded, 0), max(c.unloaded, 0)  # corrections never push a total below 0
        c.loaded_abs, c.unloaded_abs = max(c.loaded_abs, 0.0), max(c.unloaded_abs, 0.0)
        c.manual.append(manual_text(m) + (f": {m['note']}" if m["note"] else "") + (f" ~{name}" if name else ""))
    return entries


def shift_summary(conn, shift_id: Optional[int] = None) -> Optional[dict]:
    shifts = load_shifts(conn)
    if not shifts:
        return None
    sh = next((s for s in shifts if s.id == shift_id), None) if shift_id else \
        next((s for s in reversed(shifts) if s.end is None), shifts[-1])
    if not sh:
        return None
    a = analysis(conn)
    seg = a.segment(sh.id) or trips.Segment(sh)
    c = trips.count(seg, a.flags)
    manual = apply_manual(conn, sh.id, c)
    title = shift_label(sh, shifts)
    from .registry import Registry
    from .reports import report_dict
    reg = Registry(conn)
    remarks = []
    for row in conn.execute(
            "SELECT * FROM reports WHERE deleted = 0 AND remarks != '' AND event_time >= ? "
            "AND (? IS NULL OR event_time <= ?) ORDER BY event_time",
            (core_iso(sh.start), sh.end and core_iso(sh.end), sh.end and core_iso(sh.end))).fetchall():
        r = report_dict(conn, reg, row)  # canonical (post-merge) truck/site codes
        remarks.append({"id": r["id"], "event_time": r["event_time"], "remarks": r["remarks"], "user": r["user"],
                        "trucks": ",".join(r["trucks"]), "verb": r["verb"], "site": r["site"]})
    return {
        "shift_id": sh.id, "title": title, "open": sh.end is None, "manual": manual, "remarks": remarks,
        "counts": c.__dict__, "text": counts_text(title, c),
        "durations": durations(seg),
        "trips": {truck: [_trip_view(t) for t in ts] for truck, ts in sorted(seg.trips.items())},
        "flags": [f.text for (rid, tr), fs in a.flags.items() for f in fs
                  if any(e.report_id == rid for t in seg.trips.get(tr, []) for e in list(t.slots.values()) + t.duplicates)],
    }


def range_summary(conn, start: date, end: date) -> dict:
    """Totals over all shifts that started within [start, end] (IST dates)."""
    shifts = [s for s in load_shifts(conn) if start <= s.start.date() <= end]
    a = analysis(conn)
    total = trips.Counts()
    per_shift = []
    for sh in shifts:
        seg = a.segment(sh.id) or trips.Segment(sh)
        c = trips.count(seg, a.flags)
        apply_manual(conn, sh.id, c)
        per_shift.append({"shift_id": sh.id, "title": shift_label(sh, load_shifts(conn)),
                          "loaded": c.loaded, "unloaded": c.unloaded})
        for k in ("loaded", "loaded_inf", "loaded_manual", "loaded_abs", "reached", "unloaded", "unloaded_inf",
                  "unloaded_manual", "unloaded_abs", "flags"):
            setattr(total, k, getattr(total, k) + getattr(c, k))
        for attr in ("loaded_by_site", "unloaded_by_site"):
            for site, n in getattr(c, attr).items():
                getattr(total, attr)[site] = getattr(total, attr).get(site, 0) + n
        for truck, pt in c.per_truck.items():
            agg = total.per_truck.setdefault(truck, {"trips": 0, "loads": 0, "unloads": 0})
            for k in agg:
                agg[k] += pt[k]
        total.notes += c.notes
        total.manual += c.manual
    label = f"{start:%d %b}" if start == end else f"{start:%d %b}-{end:%d %b}"
    return {"title": label, "counts": total.__dict__, "per_shift": per_shift,
            "text": counts_text(f"Total {label}", total, notes=False)}


def today() -> date:
    return now().date()


def to_date(s: Optional[str]) -> date:
    return to_ist(s + "T00:00:00").date() if s else today()


def board(conn) -> dict:
    """Every active truck's position in the open (or latest) shift, with its last reported event."""
    from .registry import Registry

    shifts = load_shifts(conn)
    sh = next((s for s in reversed(shifts) if s.end is None), shifts[-1] if shifts else None)
    a = analysis(conn)
    seg = a.segment(sh.id) if sh else None
    out = []
    for t in Registry(conn).listing("truck"):
        ts = seg.trips.get(t["code"], []) if seg else []
        last_trip = ts[-1] if ts else None
        if last_trip:
            k = last_trip.last
            e = last_trip.slots[k]
            pos = trips.POSITION[k] if not last_trip.closed else "done"
            last = {"verb": e.verb, "site": e.site, "time": e.time.isoformat(), "user": e.user}
        else:
            pos, last = "idle", None
        out.append({"truck": t["code"], "position": pos, "last": last,
                    "trips": len(ts), "loads": sum(1 for x in ts if x.loaded)})
    return {"shift": shift_label(sh, shifts) if sh else None, "open": bool(sh and sh.end is None), "trucks": out}


def shift_list(conn, include_deleted: bool = False) -> list[dict]:
    """Every shift with its loaded/unloaded counts (incl. manual and corrections), newest first."""
    from .registry import Registry
    from .reports import shift_dict
    reg = Registry(conn)
    a = analysis(conn, reg)
    rows = conn.execute("SELECT * FROM shifts " + ("" if include_deleted else "WHERE deleted = 0 ") +
                        "ORDER BY started_at DESC").fetchall()
    live = load_shifts(conn)
    out = []
    for r in rows:
        d = shift_dict(conn, reg, r)
        d["deleted"] = bool(r["deleted"])
        sh = next((x for x in live if x.id == r["id"]), None)
        c = trips.count(a.segment(sh.id) or trips.Segment(sh), a.flags) if sh else trips.Counts()
        if sh:
            apply_manual(conn, sh.id, c)
            d["title"] = shift_label(sh, live)
        d.update(loaded=c.loaded, unloaded=c.unloaded, loaded_abs=c.loaded_abs, unloaded_abs=c.unloaded_abs,
                 manual=manual_entries(conn, r["id"]))
        out.append(d)
    return out
