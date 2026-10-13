"""WhatsApp text formats. Compact, no emojis.

    A,B LS KN4 14:32 Ravi
    - wet paddy, slow

Edit (sent as a reply to the original):   A,B ~LS~ LO KN4 14:32 Ravi
Delete:                                   ~A,B LS KN4 14:32 Ravi~ deleted
"""

from .core import to_ist


def _hm(ts: str) -> str:
    return f"{to_ist(ts):%H:%M}"


def _fields(r: dict) -> list[str]:
    return [",".join(r["trucks"]), r["verb"], r["site"] or "", _hm(r["event_time"])]


def line(r: dict) -> str:
    head = " ".join(x for x in _fields(r) + [r["user"]] if x)
    return head + (f"\n- {r['remarks']}" if r.get("remarks") else "")


def edit_line(before: dict, after: dict) -> str:
    parts = []
    for old, new in zip(_fields(before), _fields(after)):
        if old == new:
            parts.append(new)
        else:
            parts.append(" ".join(x for x in (f"~{old}~" if old else "", new) if x))
    head = " ".join(x for x in parts + [after["user"]] if x)
    if before.get("remarks") != after.get("remarks"):
        old, new = before.get("remarks"), after.get("remarks")
        head += "\n- " + " ".join(x for x in (f"~{old}~" if old else "", new or "") if x)
    elif after.get("remarks"):
        head += f"\n- {after['remarks']}"
    return head


def delete_line(r: dict) -> str:
    return f"~{' '.join(x for x in _fields(r) + [r['user']] if x)}~ deleted"
