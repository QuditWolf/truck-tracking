"""
Trip reconstruction — the whole "what actually happened" engine.

A trip is one load→unload cycle of one truck. Every cycle verb maps to a slot:

    0 ENTER@loading  1 LS  2 LO  3 LEFT@loading  4 ENTER@unloading  5 US  6 UO  7 LEFT@unloading

Per truck, per shift, walk events in time order:
  - slot already filled in the current trip, within DUP_WINDOW  → duplicate (ignored)
  - slot <= last slot of the current trip                        → new trip (previous one closes)
  - otherwise                                                    → same trip; skipped slots are inferred

Trips never cross shift boundaries. A trip still open at shift end is closed there; if the truck
was loaded but not unloaded, the next shift's first trip is a carry-over (its load isn't recounted).

Pure functions, no DB. Everything is recomputed from the event list on every read, so edits,
deletes and backdated reports are handled for free.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

DUP_WINDOW = timedelta(minutes=20)

SLOT_NAMES = ["ENTER", "LS", "LO", "LEFT", "ENTER", "US", "UO", "LEFT"]
# Only LS/LO gaps are worth telling a human about. At unloading sites crews report ENTER + LEFT,
# so US/UO (like ENTER/LEFT at loading) are optional.
REQUIRED = (1, 2)
FIXED_SLOTS = {"LS": 1, "LO": 2, "US": 5, "UO": 6}


@dataclass(frozen=True)
class Event:
    report_id: int
    truck: str
    verb: str  # canonical verb code
    site: Optional[str]  # canonical site code
    site_type: Optional[str]  # loading | unloading | depot | None (unknown)
    time: datetime
    user: str = ""


@dataclass(frozen=True)
class Shift:
    id: int
    start: datetime
    end: Optional[datetime]  # None = open

    def contains(self, t: datetime) -> bool:
        return self.start <= t and (self.end is None or t < self.end)


@dataclass
class Flag:
    code: str  # duplicate | missing | unshifted | no_load
    text: str
    ref: Optional["Event"] = None  # the earlier report this is about (duplicate of / missing after)


@dataclass
class Trip:
    truck: str
    slots: dict[int, Event] = field(default_factory=dict)
    duplicates: list[Event] = field(default_factory=list)
    closed: Optional[str] = None  # None (open) | "next" | "shift_end"
    carry_in: bool = False  # started mid-cycle with a load carried from the previous shift

    @property
    def last(self) -> int:
        return max(self.slots)

    @property
    def loaded(self) -> Optional[str]:
        """'yes' (LO reported) | 'inf' (inferred) | None (not counted in this trip)."""
        s = self.slots
        if 2 in s:
            return "yes"
        if self.carry_in:
            return None
        # Only an LS implies a load (LS then later steps, or LS still open when the trip closed).
        # Unloading alone never implies a load — untracked loads are added by hand.
        if 1 in s and (self.closed or self.last > 1):
            return "inf"
        return None

    @property
    def unloaded(self) -> Optional[str]:
        s = self.slots
        if 6 in s or (4 in s and 7 in s):  # UO, or entered and left the unloading site
            return "yes"
        if 7 in s or (5 in s and self.closed):
            return "inf"
        if self.closed == "next" and (self.loaded or self.carry_in or self.last >= 4):
            return "inf"  # loaded (or reached the unloading site), then started a new trip: it unloaded
        return None

    def notes(self) -> list[str]:
        """Plain-language reasons for every inferred count, for summary remarks."""
        out, s, tr = [], self.slots, self.truck
        if self.carry_in:
            out.append(f"{tr} load carried from previous shift")
        if self.loaded == "inf":
            if 1 in s and self.last == 1:
                why = f"LS {_fmt(s[1])}, no LO" + (" by shift end" if self.closed == "shift_end" else "")
            else:
                why = f"LS {_fmt(s[1])}, LO missing"
            out.append(f"{tr} load {self.load_site or '?'} inferred: {why}")
        if self.unloaded == "inf":
            if 7 in s:
                why = f"left unloading {_fmt(s[7])}, UO missing"
            elif 5 in s:
                why = f"US {_fmt(s[5])}, no UO"
            else:
                why = "loaded again later"
            out.append(f"{tr} unload {self.unload_site or '?'} inferred: {why}")
        return out

    def _site(self, order) -> Optional[str]:
        for k in order:
            if k in self.slots and self.slots[k].site:
                return self.slots[k].site
        return None

    @property
    def load_site(self) -> Optional[str]:
        return self._site((2, 1, 0, 3))

    @property
    def unload_site(self) -> Optional[str]:
        return self._site((6, 5, 4, 7))

    @property
    def load_time(self) -> datetime:
        for k in (2, 1):
            if k in self.slots:
                return self.slots[k].time
        return min(e.time for e in self.slots.values())


@dataclass
class Segment:
    shift: Optional[Shift]  # None = events outside any shift
    trips: dict[str, list[Trip]] = field(default_factory=dict)


@dataclass
class Analysis:
    segments: list[Segment]
    flags: dict[tuple[int, str], list[Flag]]  # (report_id, truck) -> flags

    def segment(self, shift_id: Optional[int]) -> Optional[Segment]:
        for seg in self.segments:
            if (seg.shift.id if seg.shift else None) == shift_id:
                return seg
        return None


def slot_of(e: Event, cur: Optional[Trip]) -> Optional[int]:
    """Map an event to its cycle slot. None = not a cycle event (custom verb, depot)."""
    if e.verb in FIXED_SLOTS:
        return FIXED_SLOTS[e.verb]
    if e.verb not in ("ENTER", "LEFT") or e.site_type == "depot":
        return None
    last = cur.last if cur else -1
    if e.site_type == "loading":
        side = 0
    elif e.site_type == "unloading":
        side = 4
    else:  # unknown site type: guess from where the trip is
        side = 4 if (e.verb == "ENTER" and 1 <= last <= 3) or (e.verb == "LEFT" and last >= 4) else 0
    return side + (0 if e.verb == "ENTER" else 3)


def _fmt(e: Event) -> str:
    return f"@{e.time:%H:%M}"


def _ref(e: Event, who: bool = False) -> str:
    """'LS SOC @08:10' (+ ' ~Ravi') — same grammar as the WhatsApp lines."""
    return f"{e.verb}{' ' + e.site if e.site else ''} @{e.time:%H:%M}" + (f" ~{e.user}" if who and e.user else "")


def _missing(trip: Trip, upto: int, after: int) -> list[str]:
    return [SLOT_NAMES[k] for k in REQUIRED if after < k < upto and k not in trip.slots]


def _walk(truck: str, events: list[Event], carry: bool, flags) -> list[Trip]:
    trips: list[Trip] = []
    cur: Optional[Trip] = None

    def flag(e: Event, code: str, text: str, ref: Optional[Event] = None):
        flags.setdefault((e.report_id, truck), []).append(Flag(code, text, ref))

    for e in events:
        if (e.verb in ("LS", "LO") and e.site_type == "unloading") or (e.verb in ("US", "UO") and e.site_type == "loading"):
            flag(e, "site", f"{truck} {e.verb} at {e.site}, {'an unloading' if e.site_type == 'unloading' else 'a loading'} site")
        s = slot_of(e, cur)
        if s is None:
            continue
        if cur and s in cur.slots and abs(e.time - cur.slots[s].time) <= DUP_WINDOW:
            cur.duplicates.append(e)
            flag(e, "duplicate", f"{truck} {_ref(cur.slots[s], who=True).replace(' @', ' already reported @', 1)}",
                 cur.slots[s])
            continue
        if cur is None or s <= cur.last:
            if cur:
                cur.closed = "next"
                gap = _missing(cur, 7, cur.last)
                if gap:
                    flag(e, "missing", f"{truck} {', '.join(gap)} not reported after {_ref(cur.slots[cur.last])}",
                         cur.slots[cur.last])
            cur = Trip(truck, carry_in=(carry and not trips and s >= 4))
            trips.append(cur)
            gap = [] if cur.carry_in else _missing(cur, s, -1)
            if gap:
                flag(e, "missing", f"{truck} {', '.join(gap)} not reported before {_ref(e)}")
        elif s == 3 and 1 not in cur.slots and 2 not in cur.slots:
            flag(e, "no_load", f"{truck} {_ref(e)} without LS/LO")
        else:
            gap = _missing(cur, s, cur.last)
            if gap:
                flag(e, "missing", f"{truck} {', '.join(gap)} not reported "
                                   f"between {_ref(cur.slots[cur.last])} and {_ref(e)}", cur.slots[cur.last])
        cur.slots[s] = e

    return trips


def analyze(events: list[Event], shifts: list[Shift]) -> Analysis:
    shifts = sorted(shifts, key=lambda s: s.start)
    segments = {s.id: Segment(s) for s in shifts}
    unshifted = Segment(None)
    flags: dict[tuple[int, str], list[Flag]] = {}

    buckets: dict[tuple[Optional[int], str], list[Event]] = {}
    # same minute: order by report id, and a draft (negative id) is always the newest
    for e in sorted(events, key=lambda e: (e.time, e.report_id if e.report_id >= 0 else float("inf"))):
        sh = next((s for s in shifts if s.contains(e.time)), None)
        if sh is None:
            flags.setdefault((e.report_id, e.truck), []).append(Flag("unshifted", "outside any shift"))
        buckets.setdefault((sh.id if sh else None, e.truck), []).append(e)

    trucks = sorted({t for _, t in buckets})
    for truck in trucks:
        carry = False
        for sh in shifts:
            evs = buckets.get((sh.id, truck))
            if not evs:
                continue
            trips = _walk(truck, evs, carry, flags)
            if not trips:
                continue
            if sh.end is not None:
                last = trips[-1]
                last.closed = "shift_end"
                carry = bool(last.loaded or last.carry_in) and not last.unloaded
            else:
                carry = False
            segments[sh.id].trips[truck] = trips
        evs = buckets.get((None, truck))
        if evs:
            unshifted.trips[truck] = _walk(truck, evs, False, flags)

    out = list(segments.values())
    if unshifted.trips:
        out.append(unshifted)
    return Analysis(out, flags)


# ── summary over one segment ────────────────────────────────────────────────

# ENTER is "at the site", not loading/unloading yet
POSITION = {0: "at_loading", 1: "loading", 2: "en_route", 3: "en_route", 4: "at_unloading",
            5: "unloading", 6: "empty", 7: "empty"}


@dataclass
class Counts:
    loaded: int = 0
    loaded_inf: int = 0
    loaded_manual: int = 0
    reached: int = 0
    unloaded: int = 0
    unloaded_inf: int = 0
    unloaded_manual: int = 0
    loaded_by_site: dict[str, int] = field(default_factory=dict)
    unloaded_by_site: dict[str, int] = field(default_factory=dict)
    position: dict[str, list[str]] = field(default_factory=dict)  # see POSITION
    per_truck: dict[str, dict[str, int]] = field(default_factory=dict)
    flags: int = 0
    notes: list[str] = field(default_factory=list)  # why each inferred count was inferred
    manual: list[str] = field(default_factory=list)  # hand-added counts for untracked trucks


def count(seg: Segment, flags: dict[tuple[int, str], list[Flag]]) -> Counts:
    c = Counts()
    for truck, trips in sorted(seg.trips.items()):
        pt = c.per_truck.setdefault(truck, {"trips": len(trips), "loads": 0, "unloads": 0})
        for t in trips:
            if t.loaded:
                c.loaded += 1
                c.loaded_inf += t.loaded == "inf"
                site = t.load_site or "?"
                c.loaded_by_site[site] = c.loaded_by_site.get(site, 0) + 1
                pt["loads"] += 1
            c.notes += t.notes()
            if any(k >= 4 for k in t.slots):  # got to the unloading site (ENTER may be unreported)
                c.reached += 1
            if t.unloaded:
                c.unloaded += 1
                c.unloaded_inf += t.unloaded == "inf"
                site = t.unload_site or "?"
                c.unloaded_by_site[site] = c.unloaded_by_site.get(site, 0) + 1
                pt["unloads"] += 1
            for e in list(t.slots.values()) + t.duplicates:
                c.flags += len(flags.get((e.report_id, truck), []))
        last = trips[-1]
        if not last.closed:
            c.position.setdefault(POSITION[last.last], []).append(truck)
    return c
