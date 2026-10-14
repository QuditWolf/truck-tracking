"""Strict, deterministic parser for WhatsApp messages — the same grammar the bot writes (see wa.py).

    A,B LS KN4 @14:32        line 1: TRUCKS VERB [SITE] [@][DD Mon] [HH:MM]
    - wet paddy              optional remark lines
    ~Ravi                    optional signature (ignored; the sender is known)

Loose input is fine: any case, commas or spaces between trucks, aliases, time with or without @,
"14.32", "3:35", "5:08pm"; filler words ("at", "trolley", "loaded"); "reached" for ENTER;
"left for BG" (destination dropped). LS/LO without a site use the shift's default loading site. Every token must resolve through the
registry; anything else returns `Parsed(ok=False)` and the bot asks (phase 3: LLM).
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from .core import IST
from .registry import Registry

TIME_RE = re.compile(r"^@?([01]?\d|2[0-3])[:.]([0-5]\d)(am|pm)?$", re.I)
# Words people add that carry no information for the parser
FILLER = {"at", "trolley", "trolleys", "truck", "trucks", "tractor", "loaded", "the", "is", "has", "@"}
# Built-in plain-language forms of the cycle verbs (registry verbs themselves have no aliases)
VERB_WORDS = {"reached": "ENTER", "reach": "ENTER", "entered": "ENTER", "in": "ENTER",
              "leave": "LEFT", "out": "LEFT", "exit": "LEFT"}
DAY_RE = re.compile(r"^@?(\d{1,2})$")
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
DEFAULT_SITE_VERBS = ("LS", "LO")


@dataclass
class Parsed:
    ok: bool
    trucks: list[str] = field(default_factory=list)
    verb: Optional[str] = None
    site: Optional[str] = None
    time: Optional[datetime] = None
    remarks: str = ""
    missing: list[str] = field(default_factory=list)


def _tokens(text: str) -> list[str]:
    return [t for t in re.split(r"[\s,]+", text.strip()) if t]


def split_lines(text: str) -> tuple[str, list[str], list[str]]:
    """(content line, remark lines, unknown extra lines). Signature and warning lines are dropped."""
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    if not lines:
        return "", [], []
    remarks, extra = [], []
    for ln in lines[1:]:
        if ln.startswith("- "):
            remarks.append(ln[2:].strip())
        elif ln.startswith("~") or ln.startswith("! "):
            continue
        else:
            extra.append(ln)
    return lines[0], remarks, extra


def _clock(raw_hour: str, minute: int, ampm: Optional[str], sent: datetime) -> datetime:
    """HH:MM near the send time. '05:30' (leading zero) and '17:30' are 24-hour; '5:30' or '10:30' (no am/pm) are
    12-hour and takes the reading closest before the send time."""
    hour = int(raw_hour)
    if ampm:
        hour = hour % 12 + (12 if ampm.lower() == "pm" else 0)
        return sent.replace(hour=hour, minute=minute, second=0, microsecond=0)
    base = sent.replace(minute=minute, second=0, microsecond=0)
    if hour > 12 or hour == 0 or raw_hour.startswith("0"):
        return base.replace(hour=hour)
    options = [base.replace(hour=h % 24) for h in {hour % 12, hour % 12 + 12}]
    options += [o - timedelta(days=1) for o in options]
    past = [o for o in options if o <= sent + timedelta(minutes=5)]
    return max(past)


def take_time(toks: list[str], sent: datetime) -> tuple[list[str], Optional[datetime]]:
    """Strip a trailing [@][DD Mon] HH:MM [am|pm]. A time later than now means yesterday (unless dated)."""
    ampm = None
    if len(toks) >= 2 and toks[-1].lower() in ("am", "pm") and TIME_RE.match(toks[-2]):
        ampm, toks = toks[-1], toks[:-1]
    if not toks or not (m := TIME_RE.match(toks[-1])):
        return toks, None
    toks = toks[:-1]
    ampm = m.group(3) or ampm
    t = _clock(m.group(1), int(m.group(2)), ampm, sent)
    if len(toks) >= 2 and toks[-1].lower()[:3] in MONTHS and (d := DAY_RE.match(toks[-2])):
        try:
            t = t.replace(month=MONTHS[toks[-1].lower()[:3]], day=int(d.group(1)))
        except ValueError:
            return toks, None
        if t > sent + timedelta(days=1):
            t = t.replace(year=t.year - 1)
        return toks[:-2], t
    if toks and toks[-1] == "@":
        toks = toks[:-1]
    return toks, (t - timedelta(days=1) if t > sent + timedelta(minutes=5) else t)


def normalize(toks: list[str], reg: Registry) -> list[str]:
    """Drop filler words, map plain verbs (reached → ENTER), and cut 'for <destination>'."""
    out = []
    for t in toks:
        low = t.lower()
        if low == "for":  # "B left for BG": BG is where it's going, not where it left
            break
        if low in FILLER:
            continue
        out.append(VERB_WORDS[low] if low in VERB_WORDS and reg.find("verb", VERB_WORDS[low]) else t)
    return out


def parse(text: str, reg: Registry, sent: datetime, default_site: Optional[str] = None) -> Parsed:
    sent = sent.astimezone(IST)
    content, remark_lines, extra = split_lines(text)
    toks, when = take_time(_tokens(content), sent)
    toks = normalize(toks, reg)
    remarks = "; ".join(remark_lines)

    trucks: list[str] = []
    i = 0
    while i < len(toks) and (t := reg.find("truck", toks[i])):
        if t.code not in trucks:
            trucks.append(t.code)
        i += 1
    verb = reg.find("verb", toks[i]) if i < len(toks) else None
    rest = toks[i + 1:] if verb else []
    site = reg.find("site", " ".join(rest)) if rest else None

    missing = []
    if not trucks:
        missing.append("truck")
    if not verb:
        missing.append("event")
    if rest and not site:
        missing.append("site")
    uses_default = not rest and verb and verb.code in DEFAULT_SITE_VERBS and default_site
    if not rest and verb and not uses_default:
        missing.append("site")
    if extra:
        missing.append("format")
    site_code = site.code if site else (default_site if uses_default else None)
    if missing or (verb and i + 1 + len(rest) != len(toks)):
        return Parsed(False, trucks, verb.code if verb else None, site_code, when, remarks, missing or ["format"])
    return Parsed(True, trucks, verb.code, site_code, when or sent.replace(second=0, microsecond=0), remarks)


def looks_like_event(text: str, reg: Registry) -> bool:
    """A real reporting attempt: short first line that mentions a known truck or event."""
    toks = _tokens(split_lines(text)[0])
    if not toks or len(toks) > 8:
        return False
    return any(reg.find("truck", t) or reg.find("verb", t) for t in toks)
