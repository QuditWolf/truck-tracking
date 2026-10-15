"""Messages arriving from WhatsApp groups.

Control group:  shift start [SITE] | shift end | summary [last|today] | help
Fleet group:    strictly formatted events become reports (source 'wa'); attempts that
                don't parse get a short question. Plain chat is ignored.
Replies go where the mode says: silent → control group, full → reply in the fleet group.
"""

import re
from datetime import datetime

from . import core, parse, reports, summary, wa
from .core import IST, enqueue, flag, setting
from .registry import Registry
from .relay import who

HELP = ("Commands: shift start [SITE] [@HH:MM] | shift end [@HH:MM] | summary | summary last | summary today\n"
        "Fleet group: A,B LS KN4 @14:32 (time optional, - remark on next line)")


def _digits(jid: str) -> str:
    return re.sub(r"\D", "", (jid or "").split("@")[0].split(":")[0])


def sender_user(conn, msg: dict) -> int:
    """Match the sender to a signed-up user by phone; otherwise a WhatsApp-only user."""
    pn = next((j for j in (msg.get("sender_alt"), msg.get("sender"), msg.get("me") if msg.get("from_me") else "")
               if j and j.endswith("@s.whatsapp.net")), "")
    digits = _digits(pn)
    if digits:
        for u in conn.execute("SELECT id, phone FROM users WHERE phone IS NOT NULL").fetchall():
            if _digits(u["phone"])[-10:] == digits[-10:]:
                return u["id"]
    key = f"wa:{digits or msg.get('sender') or 'unknown'}"
    row = conn.execute("SELECT id FROM users WHERE google_sub = ?", (key,)).fetchone()
    if row:
        return row["id"]
    cur = conn.execute("INSERT INTO users (google_sub, email, name, phone, created_at) VALUES (?, '', ?, ?, ?)",
                       (key, msg.get("push_name") or digits or "WhatsApp", digits or None, core.stamp()))
    return cur.lastrowid


def _log(conn, msg: dict, kind: str, report_id=None) -> None:
    conn.execute("INSERT INTO wa_log (at, direction, jid, wa_id, kind, report_id, sender, text, from_me) "
                 "VALUES (?, 'in', ?, ?, ?, ?, ?, ?, ?)",
                 (core.stamp(), msg["jid"], msg["id"], kind, report_id, msg.get("sender") or "",
                  msg["text"], int(bool(msg.get("from_me")))))


def _quote(msg: dict) -> dict:
    return {"id": msg["id"], "from_me": bool(msg.get("from_me")), "participant": msg.get("sender") or None,
            "text": msg["text"]}


def _reply(conn, msg: dict, text: str, as_: str, report_id=None) -> None:
    """Answer a fleet message per the notice tier: a reply in the fleet group and/or a line in control."""
    if flag(conn, "notice_fleet"):
        enqueue(conn, "notice", {"text": text, "as": as_, "report_id": report_id,
                                 "jids": [msg["jid"]], "quote": _quote(msg)})
    if flag(conn, "notice_control") and setting(conn, "control_jid") != msg["jid"]:
        enqueue(conn, "notice", {"text": text, "as": as_, "report_id": report_id,
                                 "jids": [setting(conn, "control_jid")]})


def handle(conn, msg: dict) -> str:
    if not flag(conn, "wa_enabled"):
        return "off"
    # Our own sends echoed back (e.g. after a bridge restart lost its in-memory list): never act on them.
    if msg.get("id") and conn.execute("SELECT 1 FROM wa_log WHERE direction = 'out' AND wa_id = ?",
                                      (msg["id"],)).fetchone():
        return "own"
    # Same WhatsApp message delivered twice: handle once.
    if msg.get("id") and conn.execute("SELECT 1 FROM wa_log WHERE direction = 'in' AND wa_id = ? AND jid = ?",
                                      (msg["id"], msg["jid"])).fetchone():
        return "duplicate"
    if msg["jid"] == setting(conn, "control_jid") and msg["jid"]:
        return control(conn, msg)
    if msg["jid"] == setting(conn, "fleet_jid") and msg["jid"] and flag(conn, "read_fleet"):
        return fleet(conn, msg)
    return "ignored"


def control(conn, msg: dict) -> str:
    sent = datetime.fromtimestamp(msg.get("ts") or core.now().timestamp(), IST)
    toks, at = parse.take_time(parse._tokens(parse.split_lines(msg["text"])[0].lower()), sent)
    text = " ".join(toks)
    at = core.iso(at) if at else None
    quote = _quote(msg)
    m = re.match(r"^(?:shift start|start shift)\s*(.*)$", text)
    try:
        if m:
            _log(conn, msg, "command")
            reg = Registry(conn)
            words = m.group(1).strip()
            sites = [words] if words and reg.find("site", words) else [w for w in words.replace(",", " ").split() if w]
            reports.start_shift(conn, sender_user(conn, msg), None, at, [w.upper() for w in sites])
            return "shift_start"
        if text in ("shift end", "end shift"):
            _log(conn, msg, "command")
            reports.end_shift(conn, sender_user(conn, msg), at)
            return "shift_end"
    except ValueError as e:
        enqueue(conn, "notice", {"text": f"Not done: {e}", "as": "reply", "jids": [msg["jid"]], "quote": quote})
        return "error"
    if text.startswith("summary"):
        _log(conn, msg, "command")
        arg = text.removeprefix("summary").strip()
        if arg == "today":
            out = summary.range_summary(conn, summary.today(), summary.today())["text"]
        else:
            sid = None
            if arg == "last":
                row = conn.execute("SELECT id FROM shifts WHERE deleted = 0 AND ended_at IS NOT NULL "
                                   "ORDER BY started_at DESC LIMIT 1").fetchone()
                sid = row["id"] if row else None
            s = summary.shift_summary(conn, sid)
            out = s["text"] if s else "No shifts yet."
        enqueue(conn, "notice", {"text": out, "as": "summary", "jids": [msg["jid"]], "quote": quote})
        return "summary"
    if text in ("help", "?"):
        enqueue(conn, "notice", {"text": HELP, "as": "reply", "jids": [msg["jid"]], "quote": quote})
        return "help"
    _log(conn, msg, "chat")
    return "chat"


def fleet(conn, msg: dict) -> str:
    reg = Registry(conn)
    sent = datetime.fromtimestamp(msg.get("ts") or core.now().timestamp(), IST)
    sh = reports.open_shift(conn)
    loading = [c for c in (reports.shift_sites(conn, reg, sh) if sh else [])
               if (i := reg.find("site", c, active_only=False)) and i.site_type == "loading"]
    default_site = loading[0] if len(loading) == 1 else None  # one loading site → use it; several → ask
    p = parse.parse(msg["text"], reg, sent, default_site)

    if p.ok:
        user_id = sender_user(conn, msg)
        r = reports.create_report(conn, {"trucks": p.trucks, "verb": p.verb, "site": p.site, "remarks": p.remarks, "half": p.half,
                                         "event_time": core.iso(p.time)}, user_id, source="wa", wa_msg_id=msg["id"])
        _log(conn, msg, "event", r["id"])
        a = reports.analysis(conn)
        warnings = reports.flags_for(a, r["id"], r["trucks"])
        _reply(conn, msg, wa.line({**r, "user": who(conn, r["user"])}, warnings), "ack", r["id"])
        return "event"

    if parse.looks_like_event(msg["text"], reg):
        _log(conn, msg, "unparsed")
        sender = who(conn, msg.get("push_name") or "")
        need = ", ".join(p.missing)
        first = parse.split_lines(msg["text"])[0]
        _reply(conn, msg, wa.message(f"? {first}", sender, warnings=[f"{need} unclear, reply with e.g. A LS KN4"]), "ask")
        return "unparsed"
    _log(conn, msg, "chat")
    return "chat"

