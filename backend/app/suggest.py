"""Suggest the next event and site for the trucks being reported, so most reports are 2 taps.

Next step: simply the next step of the cycle after the truck's last report —
ENTER loading → LS → LO → LEFT loading → ENTER unloading → US → UO → LEFT unloading → ENTER loading …
(predictable, and it nudges crews to report every step).
Site: mid-phase steps (LO, LEFT) stay at the truck's current site. A new phase (ENTER) picks its kind
from the cycle — after loading an unloading site, after unloading a loading site — preferring the
shift's default sites of that kind (the one this truck last used, else the first), then the truck's own
history, then the busiest site of that kind.
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
    return _site_how(conn, reg, history, slot, last_event)[0]


def _site_how(conn, reg: Registry, history: list[trips.Trip], slot: int, last_event) -> tuple[Optional[str], str]:
    """Site for the suggested step. The phase decides the kind: after loading (LO, LEFT loading) the
    next stop is an unloading site, after unloading (UO, LEFT unloading) a loading site."""
    kind = "loading" if slot <= 3 else "unloading"
    if last_event and last_event.site and last_event.site_type == kind and (slot <= 3) == (_phase_slot(last_event) <= 3):
        return last_event.site, "here"  # mid-phase (LS → LO → LEFT): still at the same site
    used = [e.site for t in reversed(history) for k in sorted(t.slots, reverse=True)
            if (e := t.slots[k]).site and e.site_type == kind]
    from .reports import shift_sites
    sh = open_shift(conn)
    defaults = []
    for code in (shift_sites(conn, reg, sh) if sh else []):
        item = reg.find("site", code, active_only=False)
        if item and item.site_type == kind:
            defaults.append(item.code)
    if defaults:  # the shift's default sites first; among them, where this truck last went
        pick = next((c for c in used if c in defaults), defaults[0])
        return pick, "only_default" if len(defaults) == 1 else "default"
    if used:
        return used[0], "history"
    shifts = load_shifts(conn)
    usage = site_usage(conn, reg, shifts[-1]) if shifts else {}
    typed = {s["code"]: s for s in reg.listing("site") if s["site_type"] == kind}
    busiest = sorted((n, code) for code, n in usage.items() if code in typed)
    return (busiest[-1][1], "busiest") if busiest else (None, "")


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
            per[code] = {"verb": verb, "site": None, "how": ""}
            continue
        site, how = _site_how(conn, reg, history, slot, last_event)
        per[code] = {"verb": verb or trips.SLOT_NAMES[slot], "site": site, "how": how,
                     "after": f"{last_event.verb} {last_event.site or ''}".strip() if last_event else None}
    verbs = {p["verb"] for p in per.values()}
    sites = {p["site"] for p in per.values()}
    common_verb = verbs.pop() if len(verbs) == 1 else None
    site = sites.pop() if common_verb and len(sites) == 1 else None
    # how sure the site is, weakest truck wins: here (truck is there now) > only_default > default > history > busiest
    hows = [p.get("how", "") for p in per.values()]
    how = min(hows, key=lambda h: HOW_RANK.index(h)) if site and hows else ""
    return {"verb": common_verb, "site": site, "how": how, "per_truck": per}


HOW_RANK = ["", "busiest", "history", "default", "only_default", "here"]
