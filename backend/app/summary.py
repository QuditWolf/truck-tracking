"""Shift / day / season summaries — counts for WhatsApp, details for the web."""

from datetime import date
from statistics import mean
from typing import Optional

from . import trips
from .core import now, to_ist
from .reports import analysis, load_shifts


def shift_label(shift: trips.Shift, all_shifts: list[trips.Shift]) -> str:
    same_day = [s for s in all_shifts if s.start.date() == shift.start.date()]
    n = sorted(same_day, key=lambda s: s.start).index(shift) + 1
    if not shift.end:
        end = "now"
    elif shift.end.date() != shift.start.date():
        end = f"{shift.end:%d %b %H:%M}"  # overnight: say which day it ended
    else:
        end = f"{shift.end:%H:%M}"
    return f"Shift {shift.start:%d %b} #{n} {shift.start:%H:%M}-{end}"


def _sites(d: dict) -> str:
    return ", ".join(f"{k} {v}" for k, v in sorted(d.items(), key=lambda kv: (-kv[1], kv[0])))


# Order of the per-truck lines. A truck can be in "Loading" now and also have loads counted.
POSITION_LINES = [("loading", "Loading"), ("loaded", "Loaded"), ("en_route", "En route"),
                  ("at_unloading", "At unloading"), ("unloading", "Unloading"),
                  ("at_loading", "At loading"), ("empty", "Empty")]


def counts_text(title: str, c: trips.Counts, notes: bool = True) -> str:
    inf = lambda n: f" ({n} inf)" if n else ""
    lines = [title,
             f"Loaded {c.loaded}{inf(c.loaded_inf)}" + (f": {_sites(c.loaded_by_site)}" if c.loaded_by_site else ""),
             f"Reached {c.reached}",
             f"Unloaded {c.unloaded}{inf(c.unloaded_inf)}" + (f": {_sites(c.unloaded_by_site)}" if c.unloaded_by_site else "")]
    loads = " ".join(f"{t}*{p['loads']}" for t, p in sorted(c.per_truck.items()) if p["loads"])
    for key, label in POSITION_LINES:
        if key == "loaded":
            if loads:
                lines.append(f"Loaded: {loads}")  # loads per truck this shift
        elif v := c.position.get(key):
            lines.append(f"{label}: {','.join(v)}")
    if notes and c.notes:
        lines.append("Inferred:")
        lines += c.notes
    return "\n".join(lines)


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
    title = shift_label(sh, shifts)
    return {
        "shift_id": sh.id, "title": title, "open": sh.end is None,
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
        seg = a.segment(sh.id)
        if not seg:
            continue
        c = trips.count(seg, a.flags)
        per_shift.append({"shift_id": sh.id, "title": shift_label(sh, load_shifts(conn)),
                          "loaded": c.loaded, "unloaded": c.unloaded})
        for k in ("loaded", "loaded_inf", "reached", "unloaded", "unloaded_inf", "flags"):
            setattr(total, k, getattr(total, k) + getattr(c, k))
        for attr in ("loaded_by_site", "unloaded_by_site"):
            for site, n in getattr(c, attr).items():
                getattr(total, attr)[site] = getattr(total, attr).get(site, 0) + n
        for truck, pt in c.per_truck.items():
            agg = total.per_truck.setdefault(truck, {"trips": 0, "loads": 0, "unloads": 0})
            for k in agg:
                agg[k] += pt[k]
        total.notes += c.notes
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
