"""WhatsApp text formats. Compact, no emojis, same grammar operators type, so it parses back.

    <content> @<time>        content: TRUCKS VERB [SITE] | Shift start [SITE] | Shift end
    - <remark>               optional
    ! <warning>              optional (confirmations)
    ~<name>                  who

    A,B LS KN4 @14:32        edit (reply to original):  A,B ~LS~ LO KN4 @14:32
    - wet paddy, slow                                   ~Ravi
    ~Ravi
                             delete (reply):            ~A,B LS KN4 @14:32~
                                                        deleted ~Ravi
Time carries the date only when it isn't today: @12 Oct 23:50.
"""

from .core import now, to_ist


def when(ts) -> str:
    t = to_ist(ts)
    return f"@{t:%H:%M}" if t.date() == now().date() else f"@{t:%d %b %H:%M}"


def _fields(r: dict) -> list[str]:
    return [",".join(r["trucks"]), r["verb"], r.get("site") or "", when(r["event_time"])]


def _join(parts) -> str:
    return " ".join(p for p in parts if p)


def message(content: str, user: str = "", remarks: str = "", warnings=()) -> str:
    lines = [content]
    if remarks:
        lines.append(f"- {remarks}")
    lines += [f"! {w}" for w in warnings]
    if user:
        lines.append(f"~{user}")
    return "\n".join(lines)


def line(r: dict, warnings=()) -> str:
    return message(_join(_fields(r)), r.get("user", ""), r.get("remarks", ""), warnings)


def edit_line(before: dict, after: dict) -> str:
    parts = [new if old == new else _join([f"~{old}~" if old else "", new])
             for old, new in zip(_fields(before), _fields(after))]
    old_r, new_r = before.get("remarks") or "", after.get("remarks") or ""
    remarks = new_r if old_r == new_r else _join([f"~{old_r}~" if old_r else "", new_r])
    return message(_join(parts), after.get("user", ""), remarks)


def delete_line(r: dict) -> str:
    user = r.get("user", "")
    return f"~{_join(_fields(r))}~\ndeleted" + (f" ~{user}" if user else "")


def shift_line(action: str, at, site: str = "", user: str = "") -> str:
    content = _join(["Shift start", site or ""]) if action == "start" else "Shift end"
    return message(f"{content} {when(at)}", user)
