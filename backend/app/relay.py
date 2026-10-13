"""Outbox → WhatsApp, plus periodic summaries and stale-shift warnings.

Routing:
    report / edit / delete   → fleet (relay_fleet) + control (relay_control)
    shift / summary / ack    → control; also fleet in "full" mode
Edits and deletes reply to the message that originally carried the report.
"""

import json
import logging
from datetime import timedelta

from . import core, summary, wa, wa_client
from .core import flag, setting, set_setting, to_ist

log = logging.getLogger("relay")
STALE_AFTER = timedelta(minutes=30)  # don't flood the group with old queue items after an outage
MAX_ATTEMPTS = 5


# ── routing ────────────────────────────────────────────────────────────────

def _uniq(jids: list[str]) -> list[str]:
    out = []
    for j in jids:
        if j and j not in out:
            out.append(j)
    return out


def relay_targets(conn) -> list[str]:
    return _uniq([setting(conn, "fleet_jid") if flag(conn, "relay_fleet") else "",
                  setting(conn, "control_jid") if flag(conn, "relay_control") else ""])


def notice_targets(conn) -> list[str]:
    """Confirmations, summaries, shift notices: control always, fleet only in full mode."""
    full = setting(conn, "fleet_mode") == "full"
    return _uniq([setting(conn, "control_jid"), setting(conn, "fleet_jid") if full else ""])


def send(conn, jid: str, text: str, kind: str, report_id=None, quote=None) -> str | None:
    wa_id = wa_client.send(jid, text, quote)
    conn.execute("INSERT INTO wa_log (at, direction, jid, wa_id, kind, report_id, text, from_me) "
                 "VALUES (?, 'out', ?, ?, ?, ?, ?, 1)", (core.stamp(), jid, wa_id, kind, report_id, text))
    return wa_id


def original(conn, report_id: int, jid: str) -> dict | None:
    """The message that carried this report in this group: our relay, or the operator's own message."""
    row = conn.execute(
        "SELECT * FROM wa_log WHERE report_id = ? AND jid = ? AND "
        "((direction = 'out' AND kind IN ('report', 'ack')) OR (direction = 'in' AND kind = 'event')) ORDER BY id LIMIT 1",
        (report_id, jid)).fetchone()
    if not row or not row["wa_id"]:
        return None
    return {"id": row["wa_id"], "from_me": bool(row["from_me"]),
            "participant": None if row["direction"] == "out" else row["sender"], "text": row["text"]}


def first_name(name: str) -> str:
    return (name or "").split(" ")[0]


def _short(r: dict) -> dict:
    return {**r, "user": first_name(r.get("user", ""))}


def shift_text(conn, payload: dict) -> str:
    sh, who = payload["shift"], first_name(payload.get("user", ""))
    if payload["action"] == "start":
        t = f"{to_ist(sh['started_at']):%H:%M}"
        return " ".join(x for x in ("Shift started", t, sh.get("default_site") or "", who) if x)
    return " ".join(x for x in ("Shift ended", f"{to_ist(sh['ended_at']):%H:%M}", who) if x)


def messages_for(conn, kind: str, payload: dict) -> list[tuple]:
    """(jid, text, kind, report_id, quote) for one outbox item."""
    if kind == "report":
        r = _short(payload["report"])
        return [(j, wa.line(r), "report", r["id"], None) for j in relay_targets(conn)]
    if kind in ("edit", "delete"):
        r = _short(payload["after"] if kind == "edit" else payload["report"])
        text = wa.edit_line(_short(payload["before"]), r) if kind == "edit" else wa.delete_line(r)
        jids = _uniq(relay_targets(conn) + [j for j in (setting(conn, "fleet_jid"), setting(conn, "control_jid"))
                                            if original(conn, r["id"], j)])
        return [(j, text, kind, r["id"], original(conn, r["id"], j)) for j in jids]
    if kind == "shift":
        out = [(j, shift_text(conn, payload), "shift", None, None) for j in notice_targets(conn)]
        if payload["action"] == "end" and flag(conn, "summary_on_shift_end"):
            s = summary.shift_summary(conn, payload["shift"]["id"])
            if s:
                out += [(j, s["text"], "summary", None, None) for j in notice_targets(conn)]
        return out
    if kind == "notice":
        return [(j, payload["text"], payload.get("as", "ack"), payload.get("report_id"), payload.get("quote"))
                for j in (payload["jids"] if payload.get("jids") else notice_targets(conn))]
    return []


# ── outbox ─────────────────────────────────────────────────────────────────

def _finish(conn, row_id: int, status: str, error: str | None = None) -> None:
    conn.execute("UPDATE outbox SET status = ?, sent_at = ?, error = ? WHERE id = ?",
                 (status, core.stamp() if status == "sent" else None, error, row_id))


def process_outbox(conn) -> int:
    rows = conn.execute("SELECT * FROM outbox WHERE status = 'pending' ORDER BY id LIMIT 50").fetchall()
    if not rows:
        return 0
    if not flag(conn, "wa_enabled"):
        for r in rows:
            _finish(conn, r["id"], "skipped", "WhatsApp off")
        return 0
    connected = wa_client.status().get("state") == "open"
    done = 0
    for r in rows:
        if core.now() - to_ist(r["at"]) > STALE_AFTER:
            _finish(conn, r["id"], "skipped", "stale")
            continue
        if not connected:
            continue
        msgs = messages_for(conn, r["kind"], json.loads(r["payload"]))
        if not msgs:
            _finish(conn, r["id"], "skipped", "no group configured")
            continue
        try:
            for jid, text, kind, report_id, quote in msgs:
                already = conn.execute("SELECT 1 FROM wa_log WHERE direction='out' AND jid=? AND kind=? AND "
                                       "text=? AND at >= ?", (jid, kind, text, r["at"])).fetchone()
                if not already:  # idempotent on retry after a partial send
                    send(conn, jid, text, kind, report_id, quote)
            _finish(conn, r["id"], "sent")
            done += 1
        except wa_client.BridgeError as e:
            attempts = r["attempts"] + 1
            conn.execute("UPDATE outbox SET attempts = ?, error = ? WHERE id = ?", (attempts, str(e), r["id"]))
            if attempts >= MAX_ATTEMPTS:
                _finish(conn, r["id"], "failed", str(e))
            log.warning("send failed (%s/%s): %s", attempts, MAX_ATTEMPTS, e)
            break
    return done


# ── periodic ───────────────────────────────────────────────────────────────

def tick(conn) -> None:
    """Periodic summary (only if it changed) and a one-time warning for shifts left open too long."""
    if not flag(conn, "wa_enabled"):
        return
    from .reports import open_shift

    sh = open_shift(conn)
    if not sh:
        return
    now = core.now()
    interval = int(setting(conn, "summary_interval_min") or 0)
    last_at = setting(conn, "_last_summary_at")
    last = max(to_ist(last_at), to_ist(sh["started_at"])) if last_at else to_ist(sh["started_at"])
    if interval > 0 and now - last >= timedelta(minutes=interval):
        s = summary.shift_summary(conn, sh["id"])
        set_setting(conn, "_last_summary_at", core.iso(now))
        if s and s["text"] != setting(conn, "_last_summary_text"):
            set_setting(conn, "_last_summary_text", s["text"])
            core.enqueue(conn, "notice", {"text": s["text"], "as": "summary"})

    stale = int(setting(conn, "shift_stale_hours") or 0)
    if stale and now - to_ist(sh["started_at"]) > timedelta(hours=stale) \
            and setting(conn, "_stale_warned") != str(sh["id"]):
        set_setting(conn, "_stale_warned", str(sh["id"]))
        core.enqueue(conn, "notice", {"text": f"Shift open since {to_ist(sh['started_at']):%d %b %H:%M}. "
                                              f"Send 'shift end' if it's over.",
                                      "jids": [setting(conn, "control_jid")]})


def run_once(conn) -> None:
    with core.tx(conn):
        tick(conn)
    process_outbox(conn)  # sends one by one; each wa_log insert autocommits
