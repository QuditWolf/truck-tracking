"""Suggest the next event and site for the trucks being reported, so most reports are 2 taps.

Next step: simply the next step of the cycle after the truck's last report —
ENTER loading → LS → LO → LEFT loading → ENTER unloading → US → UO → LEFT unloading → ENTER loading …
(predictable, and it nudges crews to report every step).
Site: loading steps → where the truck last loaded (else the shift's default loading site, else the
busiest loading site); unloading steps → where it last unloaded (else the busiest unloading site).
Several trucks: suggest only what they all agree on. Nothing is ever sent automatically.
"""

from typing import Optional

from . import trips
from .reports import analysis, load_shifts, open_shift, site_usage
from .registry import Registry



def _timeline(a: trips.Analysis, truck: str) -> list[trips.Trip]:
    out = []
    for seg in a.segments:
        if seg.shift is not None:
            out += seg.trips.get(truck, [])
    return out


def _next_slot(last: int) -> int:
    return (last + 1) % 8  # -1 (no history) → 0 = ENTER loading site


def _slot_for_verb(verb: str, last: int) -> Optional[int]:
    if verb in trips.FIXED_SLOTS:
        return trips.FIXED_SLOTS[verb]
    if verb == "ENTER":
        return 4 if 1 <= last <= 3 else 0
    if verb == "LEFT":
        return 7 if last >= 4 else 3
    return None


def _site(conn, reg: Registry, history: list[trips.Trip], slot: int, last_event) -> Optional[str]:
    kind = "loading" if slot <= 3 else "unloading"
    if last_event and last_event.site_type == kind and (last_event.time is not None):
        same_phase = (slot <= 3) == (_phase_slot(last_event) <= 3)
        if same_phase:
            return last_event.site  # still at the same site
    for t in reversed(history):  # where this truck last was for this phase
        for k in sorted(t.slots, reverse=True):
            e = t.slots[k]
            if e.site and e.site_type == kind:
                return e.site
    if kind == "loading":
        from .reports import shift_sites
        sh = open_shift(conn)
        for code in (shift_sites(conn, reg, sh) if sh else []):
            item = reg.find("site", code, active_only=False)
            if item and item.site_type == "loading":
                return code
    shifts = load_shifts(conn)
    usage = site_usage(conn, reg, shifts[-1]) if shifts else {}
    typed = {s["code"]: s for s in reg.listing("site") if s["site_type"] == kind}
    busiest = sorted((n, code) for code, n in usage.items() if code in typed)
    return busiest[-1][1] if busiest else None


def _phase_slot(e) -> int:
    return trips.slot_of(e, None) if e.verb not in ("ENTER", "LEFT") else (0 if e.site_type == "loading" else 4)


def suggest(conn, truck_codes: list[str], verb: Optional[str] = None) -> dict:
    reg = Registry(conn)
    codes = [(reg.find("truck", t, active_only=False) or type("X", (), {"code": t})).code for t in truck_codes]
    a = analysis(conn, reg)
    per = {}
    for code in codes:
        history = _timeline(a, code)
        last_trip = history[-1] if history else None
        last = last_trip.last if last_trip else -1
        last_event = last_trip.slots[last] if last_trip else None
        slot = _slot_for_verb(verb, last) if verb else _next_slot(last)
        if slot is None:
            per[code] = {"verb": verb, "site": None}
            continue
        per[code] = {"verb": verb or trips.SLOT_NAMES[slot], "site": _site(conn, reg, history, slot, last_event),
                     "after": f"{last_event.verb} {last_event.site or ''}".strip() if last_event else None}
    verbs = {p["verb"] for p in per.values()}
    sites = {p["site"] for p in per.values()}
    common_verb = verbs.pop() if len(verbs) == 1 else None
    return {"verb": common_verb,
            "site": sites.pop() if common_verb and len(sites) == 1 else None,
            "per_truck": per}
