"""Strict, deterministic parser for WhatsApp messages — the same grammar the bot writes (see wa.py).

    A,B LS KN4 @14:32        line 1: TRUCKS VERB [SITE] [@][DD Mon] [HH:MM]
    - wet paddy              optional remark lines
    ~Ravi                    optional signature (ignored; the sender is known)

Loose input is fine: any case, commas or spaces between trucks, aliases, time with or without @,
"14.32". LS/LO without a site use the shift's default site. Every token must resolve through the
registry; anything else returns `Parsed(ok=False)` and the bot asks (phase 3: LLM).
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from .core import IST
from .registry import Registry

TIME_RE = re.compile(r"^@?([01]?\d|2[0-3])[:.]([0-5]\d)$")
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


def take_time(toks: list[str], sent: datetime) -> tuple[list[str], Optional[datetime]]:
    """Strip a trailing [@][DD Mon] HH:MM. A time later than now means yesterday (unless dated)."""
    if not toks or not (m := TIME_RE.match(toks[-1])):
        return toks, None
    toks = toks[:-1]
    t = sent.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
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


def parse(text: str, reg: Registry, sent: datetime, default_site: Optional[str] = None) -> Parsed:
    sent = sent.astimezone(IST)
    content, remark_lines, extra = split_lines(text)
    toks, when = take_time(_tokens(content), sent)
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
