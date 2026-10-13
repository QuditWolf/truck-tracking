"""Strict, deterministic parser for typed WhatsApp messages.

Accepts only messages where every token resolves through the registry:

    A,B LS KN4          trucks, verb, site
    D LO                verb LS/LO with the shift's default site
    C US DAIRY 14:32    optional trailing HH:MM (IST, today)
    A ls kua no 4       multi-word site names / aliases are fine

Anything else returns `Parsed(ok=False)` — phase 3 hands those to the LLM.
`looks_like_event` tells real attempts apart from chat ("ok", "good morning").
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from .core import IST
from .registry import Registry

TIME_RE = re.compile(r"^([01]?\d|2[0-3])[:.]([0-5]\d)$")
DEFAULT_SITE_VERBS = ("LS", "LO")


@dataclass
class Parsed:
    ok: bool
    trucks: list[str] = field(default_factory=list)
    verb: Optional[str] = None
    site: Optional[str] = None
    time: Optional[datetime] = None
    missing: list[str] = field(default_factory=list)


def _tokens(text: str) -> list[str]:
    return [t for t in re.split(r"[\s,]+", text.strip()) if t]


def _event_time(hm: str, sent: datetime) -> datetime:
    m = TIME_RE.match(hm)
    t = sent.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
    return t - timedelta(days=1) if t > sent + timedelta(minutes=5) else t


def parse(text: str, reg: Registry, sent: datetime, default_site: Optional[str] = None) -> Parsed:
    toks = _tokens(text)
    sent = sent.astimezone(IST)
    when = None
    if toks and TIME_RE.match(toks[-1]):
        when = _event_time(toks.pop(), sent)

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
    if not rest and verb and not (verb.code in DEFAULT_SITE_VERBS and default_site):
        missing.append("site")
    site_code = site.code if site else (default_site if not rest and verb and verb.code in DEFAULT_SITE_VERBS else None)
    if missing or (verb and i + 1 + len(rest) != len(toks)):
        return Parsed(False, trucks, verb.code if verb else None, site_code, when, missing or ["format"])
    return Parsed(True, trucks, verb.code, site_code, when or sent.replace(second=0, microsecond=0))


def looks_like_event(text: str, reg: Registry) -> bool:
    """A real reporting attempt: short, and mentions a known truck or event."""
    toks = _tokens(text)
    if not toks or len(toks) > 8:
        return False
    return any(reg.find("truck", t) or reg.find("verb", t) for t in toks)
