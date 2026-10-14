"""FastAPI app: JSON API under /api, built Svelte app served from / ."""

import asyncio
import hmac
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import auth, core, inbound, registry, relay, reports, summary, wa, wa_client
from .auth import admin, current_user, get_conn, member

STATIC = Path(__file__).parent.parent.parent / "web" / "dist"


log = logging.getLogger("app")


async def relay_worker():
    """Drains the outbox and runs periodic summaries. Own connection, own thread per tick."""
    conn = core.connect()
    while True:
        try:
            await asyncio.to_thread(relay.run_once, conn)
        except Exception:
            log.exception("relay tick failed")
        await asyncio.sleep(2)


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = core.connect()
    core.init_db(conn)
    registry.seed_verbs(conn)
    app.state.conn = conn  # startup/maintenance only; requests get their own (auth.get_conn)
    task = asyncio.create_task(relay_worker()) if os.environ.get("WA_WORKER", "1") == "1" else None
    yield
    if task:
        task.cancel()
    conn.close()


app = FastAPI(title="paddy2026", lifespan=lifespan)


def bad(e: Exception):
    raise HTTPException(400, str(e))


# ── auth / profile ──────────────────────────────────────────────────────────

class GoogleIn(BaseModel):
    credential: str


class DevIn(BaseModel):
    email: str


class ProfileIn(BaseModel):
    name: str
    phone: str


@app.get("/api/health")
def health(conn=Depends(get_conn)):
    conn.execute("SELECT 1")
    return {"ok": True}


@app.get("/api/config")
def config():
    return {"google_client_id": core.GOOGLE_CLIENT_ID, "dev_login": core.DEV_LOGIN}


@app.post("/api/auth/google")
def login_google(body: GoogleIn, response: Response, conn=Depends(get_conn)):
    info = auth.verify_google(body.credential)
    return auth.login(conn, response, info["sub"], info["email"])


@app.post("/api/auth/dev")
def login_dev(body: DevIn, response: Response, conn=Depends(get_conn)):
    if not core.DEV_LOGIN:
        raise HTTPException(404)
    email = body.email.strip().lower()
    return auth.login(conn, response, f"dev:{email}", email)


@app.post("/api/auth/logout")
def logout(response: Response):
    response.delete_cookie(auth.COOKIE)
    return {"ok": True}


@app.get("/api/me")
def me(user=Depends(current_user), conn=Depends(get_conn)):
    return {**user, "signature": relay.who(conn, user["name"] or "")}


@app.put("/api/me")
def update_me(body: ProfileIn, user=Depends(current_user), conn=Depends(get_conn)):
    name, phone = body.name.strip(), body.phone.strip()
    if not name or len(phone.replace("+", "").replace(" ", "")) < 10:
        bad(ValueError("name and a valid phone number are required"))
    with core.tx(conn):
        conn.execute("UPDATE users SET name = ?, phone = ? WHERE id = ?", (name, phone, user["id"]))
        core.audit(conn, user["id"], "update", "user", user["id"], before=user, after={"name": name, "phone": phone})
    return auth.user_dict(conn.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone())


# ── live updates ────────────────────────────────────────────────────────────

def data_version(conn) -> int:
    """Every change (reports, shifts, registry, users, settings — web or WhatsApp) writes an audit row."""
    return conn.execute("SELECT COALESCE(MAX(id), 0) FROM audit").fetchone()[0]


@app.get("/api/live")
async def live(request: Request, user=Depends(member)):
    """Server-sent events: pushes the data version whenever anything changes, so open pages refresh."""
    async def stream():
        conn = core.connect()
        last, idle = None, 0
        try:
            for _ in range(600):  # ~10 min, then the browser reconnects (and re-checks the session)
                if await request.is_disconnected():
                    break
                v = await asyncio.to_thread(data_version, conn)
                if v != last:
                    last, idle = v, 0
                    yield f"data: {v}\n\n"
                elif (idle := idle + 1) >= 15:
                    idle = 0
                    yield ": ping\n\n"  # keeps proxies from closing an idle stream
                await asyncio.sleep(1)
        finally:
            conn.close()

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── registry (dropdowns) ────────────────────────────────────────────────────

@app.get("/api/registry")
def get_registry(user=Depends(member), conn=Depends(get_conn)):
    reg = registry.Registry(conn)
    sh = reports.open_shift(conn)
    return {"truck": reg.listing("truck"), "site": reports.sites_by_usage(conn, reg), "verb": reg.listing("verb"),
            "shift": reports.shift_dict(conn, reg, sh) if sh else None}


# ── reports ─────────────────────────────────────────────────────────────────

class ReportIn(BaseModel):
    trucks: list[str]
    verb: str
    site: Optional[str] = None
    remarks: str = ""
    event_time: Optional[str] = None  # IST; default now
    start_shift: bool = False  # no open shift: start one at the event time (user confirmed)
    skip_fleet: bool = False  # admins only: don't relay this report to the fleet group


class ReportPatch(BaseModel):
    trucks: Optional[list[str]] = None
    verb: Optional[str] = None
    site: Optional[str] = None
    remarks: Optional[str] = None
    event_time: Optional[str] = None


def _with_flags(conn, items: list[dict]) -> list[dict]:
    a = reports.analysis(conn)
    return [{**r, "flags": [] if r["deleted"] else reports.flags_for(a, r["id"], r["trucks"])} for r in items]


@app.post("/api/reports/check")
def check_report(body: ReportIn, report_id: Optional[int] = None, user=Depends(member), conn=Depends(get_conn)):
    """Dry run: what would the engine say about this draft? Nothing is written."""
    reg = registry.Registry(conn)
    draft = {"trucks": [t.strip().upper() for t in body.trucks if t.strip()], "verb": body.verb.strip().upper(),
             "site": body.site, "event_time": body.event_time or core.iso(core.now()), "user": user["name"]}
    for kind, val in (("verb", draft["verb"]), ("site", body.site)):
        item = reg.find(kind, val) if val else None
        if item:
            draft[kind] = item.code
    draft["trucks"] = [(reg.find("truck", t) or registry.Item(0, "", t, t, None, "", "", None, True, 0)).code
                       for t in draft["trucks"]]
    a = reports.analysis(conn, reg, draft=draft, exclude_id=report_id)
    details = reports.flag_details(a, reports.DRAFT_ID, draft["trucks"])
    warnings = [d["text"] for d in details]
    new = [f"new {k}: {v}" for k, vals in (("truck", body.trucks), ("site", [body.site] if body.site else []),
                                           ("verb", [body.verb])) for v in vals if v and not reg.find(k, v)]
    return {"warnings": warnings, "details": details, "new_entries": new}


@app.post("/api/reports")
def create_report(body: ReportIn, user=Depends(member), conn=Depends(get_conn)):
    try:
        with core.tx(conn):
            if body.start_shift and not reports.open_shift(conn):
                reports.start_shift(conn, user["id"], body.site, body.event_time or core.iso(core.now()))
            r = reports.create_report(conn, body.model_dump(exclude={"start_shift", "skip_fleet"}), user["id"],
                                      skip_fleet=body.skip_fleet and user["is_admin"])
    except ValueError as e:
        bad(e)
    return _with_flags(conn, [r])[0]


@app.get("/api/reports")
def list_reports(mine: bool = True, limit: int = 100, include_deleted: bool = False,
                 user=Depends(member), conn=Depends(get_conn)):
    # everyone can read all reports; editing stays limited to the author or an admin (_own)
    q = "SELECT * FROM reports WHERE 1=1"
    args: list = []
    if mine:
        q += " AND user_id = ?"
        args.append(user["id"])
    if not include_deleted:
        q += " AND deleted = 0"
    q += " ORDER BY event_time DESC, id DESC LIMIT ?"
    args.append(min(limit, 1000))
    reg = registry.Registry(conn)
    return _with_flags(conn, [reports.report_dict(conn, reg, r) for r in conn.execute(q, args).fetchall()])


@app.get("/api/feed")
def feed(limit: int = 50, user=Depends(member), conn=Depends(get_conn)):
    """Everyone's latest reports — lets reporters see what others already posted."""
    reg = registry.Registry(conn)
    rows = conn.execute("SELECT * FROM reports WHERE deleted = 0 ORDER BY event_time DESC, id DESC LIMIT ?",
                        (min(limit, 200),)).fetchall()
    return _with_flags(conn, [reports.report_dict(conn, reg, r) for r in rows])


def _own(conn, report_id: int, user: dict) -> dict:
    r = reports.get_report(conn, report_id)
    if not r or r["deleted"]:
        raise HTTPException(404, "report not found")
    if r["user_id"] != user["id"] and not user["is_admin"]:
        raise HTTPException(403, "not your report")
    return r


@app.patch("/api/reports/{report_id}")
def edit_report(report_id: int, body: ReportPatch, user=Depends(member), conn=Depends(get_conn)):
    _own(conn, report_id, user)
    try:
        with core.tx(conn):
            r = reports.update_report(conn, report_id, body.model_dump(), user["id"])
    except ValueError as e:
        bad(e)
    return _with_flags(conn, [r])[0]


@app.delete("/api/reports/{report_id}")
def remove_report(report_id: int, user=Depends(member), conn=Depends(get_conn)):
    _own(conn, report_id, user)
    with core.tx(conn):
        reports.delete_report(conn, report_id, user["id"])
    return {"ok": True}


# ── shifts ──────────────────────────────────────────────────────────────────

class ShiftStart(BaseModel):
    site: Optional[str] = None
    at: Optional[str] = None


class ShiftEnd(BaseModel):
    at: Optional[str] = None


class ShiftPatch(BaseModel):
    started_at: Optional[str] = None
    ended_at: Optional[str] = None  # "" = reopen
    site: Optional[str] = None
    deleted: Optional[bool] = None


@app.get("/api/shifts")
def list_shifts(limit: int = 50, user=Depends(member), conn=Depends(get_conn)):
    reg = registry.Registry(conn)
    rows = conn.execute("SELECT * FROM shifts WHERE deleted = 0 ORDER BY started_at DESC LIMIT ?", (limit,))
    return [reports.shift_dict(conn, reg, r) for r in rows.fetchall()]


@app.post("/api/shifts/start")
def shift_start(body: ShiftStart, user=Depends(member), conn=Depends(get_conn)):
    try:
        with core.tx(conn):
            return reports.start_shift(conn, user["id"], body.site, body.at)
    except ValueError as e:
        bad(e)


@app.post("/api/shifts/end")
def shift_end(body: ShiftEnd, user=Depends(member), conn=Depends(get_conn)):
    try:
        with core.tx(conn):
            return reports.end_shift(conn, user["id"], body.at)
    except ValueError as e:
        bad(e)


@app.patch("/api/shifts/{shift_id}")
def shift_edit(shift_id: int, body: ShiftPatch, user=Depends(admin), conn=Depends(get_conn)):
    try:
        with core.tx(conn):
            return reports.edit_shift(conn, shift_id, user["id"], **body.model_dump())
    except ValueError as e:
        bad(e)


# ── summaries ───────────────────────────────────────────────────────────────

@app.get("/api/summary/shift")
def summary_shift(shift_id: Optional[int] = None, user=Depends(member), conn=Depends(get_conn)):
    return summary.shift_summary(conn, shift_id) or {"text": "No shifts yet."}


@app.get("/api/board")
def get_board(user=Depends(member), conn=Depends(get_conn)):
    return summary.board(conn)


class ManualIn(BaseModel):
    trucks: list[str] = []
    truck: str = ""  # single truck (older clients)
    kind: str  # load | unload
    count: int = 1
    site: Optional[str] = None
    note: str = ""
    post_fleet: bool = True  # control group always gets it; fleet group only if this is on
    shift_id: Optional[int] = None  # default: the open shift


@app.post("/api/manual")
def add_manual(body: ManualIn, user=Depends(member), conn=Depends(get_conn)):
    """Any member: count loads/unloads of a truck nobody reported (untracked trucks)."""
    reg = registry.Registry(conn)
    names = [t for t in (body.trucks or [body.truck]) if t and t.strip()]
    if body.kind not in ("load", "unload") or not 1 <= body.count <= 50 or not names:
        bad(ValueError("truck(s), kind (load/unload) and a count of 1-50 are required"))
    sh = conn.execute("SELECT id FROM shifts WHERE id = ? AND deleted = 0", (body.shift_id,)).fetchone() \
        if body.shift_id else reports.open_shift(conn)
    if not sh:
        bad(ValueError("no running shift — start one first"))
    trucks = list(dict.fromkeys((k.code if (k := reg.find("truck", t)) else t.strip().upper()) for t in names))
    site = None
    if body.site and body.site.strip():
        s_item = reg.find("site", body.site)
        if not s_item:
            bad(ValueError(f"unknown site {body.site}"))
        site = s_item.code
    entries = []
    with core.tx(conn):
        for truck in trucks:  # one entry per truck: each adds on top, each removable on its own
            cur = conn.execute("INSERT INTO manual_counts (shift_id, truck, kind, count, site, note, post_fleet, user_id, "
                               "created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                               (sh["id"], truck, body.kind, body.count, site, body.note.strip(),
                                int(body.post_fleet or not user["is_admin"]),  # only admins may skip fleet
                                user["id"], core.stamp()))
            entry = {**dict(conn.execute("SELECT * FROM manual_counts WHERE id = ?", (cur.lastrowid,)).fetchone()),
                     "user": user["name"]}
            core.audit(conn, user["id"], "create", "manual", cur.lastrowid, after=entry)
            core.enqueue(conn, "manual", {"action": "add", "entry": entry})
            entries.append(entry)
    return entries[0] if len(entries) == 1 and not body.trucks else entries


@app.delete("/api/manual/{entry_id}")
def delete_manual(entry_id: int, user=Depends(member), conn=Depends(get_conn)):
    row = conn.execute("SELECT * FROM manual_counts WHERE id = ? AND deleted = 0", (entry_id,)).fetchone()
    if not row:
        raise HTTPException(404, "not found")
    if row["user_id"] != user["id"] and not user["is_admin"]:
        raise HTTPException(403, "not your entry")
    with core.tx(conn):
        conn.execute("UPDATE manual_counts SET deleted = 1 WHERE id = ?", (entry_id,))
        core.audit(conn, user["id"], "delete", "manual", entry_id, before=dict(row))
        core.enqueue(conn, "manual", {"action": "delete", "entry": {**dict(row), "user": user["name"]}})
    return {"ok": True}


@app.get("/api/summary/range")
def summary_range(start: Optional[str] = None, end: Optional[str] = None,
                  user=Depends(member), conn=Depends(get_conn)):
    s = summary.to_date(start)
    return summary.range_summary(conn, s, summary.to_date(end) if end else s)


# ── admin ───────────────────────────────────────────────────────────────────

class RegistryIn(BaseModel):
    kind: str
    code: str
    label: str = ""
    site_type: Optional[str] = None
    plate: str = ""
    notes: str = ""


class RegistryPatch(BaseModel):
    code: Optional[str] = None
    label: Optional[str] = None
    site_type: Optional[str] = None
    plate: Optional[str] = None
    notes: Optional[str] = None
    active: Optional[bool] = None
    sort: Optional[int] = None


class AliasIn(BaseModel):
    code: str


class MergeIn(BaseModel):
    into: int


class UserPatch(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    disabled: Optional[bool] = None
    disabled_until: Optional[str] = None  # IST; with disabled=true → temporary


@app.get("/api/admin/registry")
def admin_registry(user=Depends(admin), conn=Depends(get_conn)):
    return registry.admin_listing(registry.Registry(conn))


def _admin_tx(conn, fn):
    try:
        with core.tx(conn):
            return fn()
    except ValueError as e:
        bad(e)
    except Exception as e:  # sqlite constraint (duplicate code etc.)
        if "UNIQUE" in str(e):
            bad(ValueError("code already exists"))
        raise


@app.post("/api/admin/registry")
def admin_registry_create(body: RegistryIn, user=Depends(admin), conn=Depends(get_conn)):
    return {"id": _admin_tx(conn, lambda: registry.create(conn, body.kind, body.code, body.label,
                                                           body.site_type, user["id"], plate=body.plate,
                                                           notes=body.notes))}


@app.patch("/api/admin/registry/{item_id}")
def admin_registry_edit(item_id: int, body: RegistryPatch, user=Depends(admin), conn=Depends(get_conn)):
    _admin_tx(conn, lambda: registry.edit(conn, item_id, user["id"], **body.model_dump()))
    return {"ok": True}


@app.delete("/api/admin/registry/{item_id}")
def admin_registry_delete(item_id: int, user=Depends(admin), conn=Depends(get_conn)):
    return {"result": _admin_tx(conn, lambda: registry.delete(conn, item_id, user["id"]))}


@app.post("/api/admin/registry/{item_id}/alias")
def admin_alias(item_id: int, body: AliasIn, user=Depends(admin), conn=Depends(get_conn)):
    return {"id": _admin_tx(conn, lambda: registry.add_alias(conn, item_id, body.code, user["id"]))}


@app.post("/api/admin/registry/{item_id}/merge")
def admin_merge(item_id: int, body: MergeIn, user=Depends(admin), conn=Depends(get_conn)):
    _admin_tx(conn, lambda: registry.merge(conn, item_id, body.into, user["id"]))
    return {"ok": True}


@app.post("/api/admin/registry/{item_id}/unmerge")
def admin_unmerge(item_id: int, user=Depends(admin), conn=Depends(get_conn)):
    _admin_tx(conn, lambda: registry.unmerge(conn, item_id, user["id"]))
    return {"ok": True}


@app.get("/api/admin/users")
def admin_users(user=Depends(admin), conn=Depends(get_conn)):
    rows = conn.execute("SELECT u.*, (SELECT COUNT(*) FROM reports r WHERE r.user_id = u.id AND r.deleted = 0) AS n "
                        "FROM users u ORDER BY u.created_at DESC").fetchall()
    return [{**auth.user_dict(r), "reports": r["n"], "created_at": r["created_at"],
             "whatsapp_only": r["google_sub"].startswith("wa:")} for r in rows]


def _valid_phone(phone: str) -> bool:
    return len("".join(ch for ch in phone if ch.isdigit())) >= 10


@app.patch("/api/admin/users/{user_id}")
def admin_user_edit(user_id: int, body: UserPatch, user=Depends(admin), conn=Depends(get_conn)):
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row:
        raise HTTPException(404, "user not found")
    before = {**auth.user_dict(row), "disabled_until": row["disabled_until"]}
    changes: dict = {}
    if body.name is not None:
        if not body.name.strip():
            bad(ValueError("name can't be empty"))
        changes["name"] = body.name.strip()
    if body.phone is not None:
        if body.phone.strip() and not _valid_phone(body.phone):
            bad(ValueError("phone needs at least 10 digits"))
        changes["phone"] = body.phone.strip() or None
    if body.disabled is not None:
        if body.disabled and row["email"].lower() in core.ADMIN_EMAILS:
            bad(ValueError("admins can't be disabled here"))
        until = core.minute(body.disabled_until) if body.disabled and body.disabled_until else None
        if until and core.to_ist(until) <= core.now():
            bad(ValueError("disable-until must be in the future"))
        changes["disabled"] = int(body.disabled)
        changes["disabled_until"] = until
    if changes:
        with core.tx(conn):
            conn.execute(f"UPDATE users SET {', '.join(f'{k} = ?' for k in changes)} WHERE id = ?",
                         (*changes.values(), user_id))
            action = "update" if body.disabled is None else ("disable" if body.disabled else "enable")
            core.audit(conn, user["id"], action, "user", user_id, before=before, after=changes)
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return auth.user_dict(row)


# ── WhatsApp ────────────────────────────────────────────────────────────────

class InboundIn(BaseModel):
    id: str
    jid: str
    text: str
    from_me: bool = False
    me: str = ""
    sender: str = ""
    sender_alt: str = ""
    push_name: str = ""
    ts: float = 0
    quoted_id: Optional[str] = None


@app.post("/api/wa/inbound", include_in_schema=False)
def wa_inbound(body: InboundIn, x_wa_token: str = Header(""), conn=Depends(get_conn)):
    if not hmac.compare_digest(x_wa_token, wa_client.TOKEN):
        raise HTTPException(401)
    try:
        with core.tx(conn):
            return {"result": inbound.handle(conn, body.model_dump())}
    except ValueError as e:
        return {"result": "error", "error": str(e)}


@app.get("/api/admin/wa")
def admin_wa(user=Depends(admin), conn=Depends(get_conn)):
    counts = {r["status"]: r["n"] for r in conn.execute(
        "SELECT status, COUNT(*) AS n FROM outbox GROUP BY status")}
    failed = [dict(r) for r in conn.execute(
        "SELECT id, at, kind, error FROM outbox WHERE status = 'failed' ORDER BY id DESC LIMIT 5")]
    activity = [dict(r) for r in conn.execute("SELECT * FROM wa_log ORDER BY id DESC LIMIT 60")]
    return {"status": wa_client.status(), "outbox": counts, "failed": failed, "activity": activity}


@app.get("/api/admin/wa/groups")
def admin_wa_groups(user=Depends(admin)):
    try:
        return wa_client.groups()
    except wa_client.BridgeError as e:
        raise HTTPException(503, str(e))


@app.post("/api/admin/wa/logout")
def admin_wa_logout(user=Depends(admin), conn=Depends(get_conn)):
    try:
        wa_client.logout()
    except wa_client.BridgeError as e:
        raise HTTPException(503, str(e))
    with core.tx(conn):
        core.audit(conn, user["id"], "logout", "whatsapp", None)
    return {"ok": True}


class WaTestIn(BaseModel):
    target: str  # fleet | control


@app.post("/api/admin/wa/test")
def admin_wa_test(body: WaTestIn, user=Depends(admin), conn=Depends(get_conn)):
    jid = core.setting(conn, f"{body.target}_jid")
    if not jid:
        bad(ValueError(f"no {body.target} group chosen"))
    try:
        relay.send(conn, jid, f"Dayalbagh Truck Tracking connected {wa.when(core.now())}", "test")
    except wa_client.BridgeError as e:
        raise HTTPException(503, str(e))
    return {"ok": True}


@app.post("/api/admin/wa/summary")
def admin_wa_summary(user=Depends(admin), conn=Depends(get_conn)):
    s = summary.shift_summary(conn)
    if not s:
        bad(ValueError("no shifts yet"))
    with core.tx(conn):
        core.enqueue(conn, "notice", {"text": s["text"], "as": "summary"})
    return {"ok": True}


@app.get("/api/admin/settings")
def admin_settings(user=Depends(admin), conn=Depends(get_conn)):
    return {k: core.setting(conn, k) for k in core.DEFAULT_SETTINGS}


@app.put("/api/admin/settings")
def admin_settings_put(body: dict[str, str], user=Depends(admin), conn=Depends(get_conn)):
    for k in ("wa_enabled", "send_fleet", "read_fleet", "summary_on_shift_end",
              *(f"{t}_{g}" for t in relay.TIERS for g in ("fleet", "control"))):
        if k in body and str(body[k]) not in ("0", "1"):
            bad(ValueError(f"{k} must be 0 or 1"))
    for k in ("fleet_jid", "control_jid"):
        if body.get(k) and not str(body[k]).endswith("@g.us"):
            bad(ValueError(f"{k} must be a group id ending in @g.us"))
    with core.tx(conn):
        for k, v in body.items():
            if k in core.DEFAULT_SETTINGS:
                before = core.setting(conn, k)
                conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (k, str(v)))
                core.audit(conn, user["id"], "update", "setting", None, before={k: before}, after={k: v})
    return admin_settings(user, conn)


@app.get("/api/admin/audit")
def admin_audit(limit: int = 200, entity: Optional[str] = None, entity_id: Optional[int] = None,
                user=Depends(admin), conn=Depends(get_conn)):
    q, args = "SELECT * FROM audit WHERE 1=1", []
    if entity:
        q += " AND entity = ?"
        args.append(entity)
    if entity_id is not None:
        q += " AND entity_id = ?"
        args.append(entity_id)
    q += " ORDER BY id DESC LIMIT ?"
    args.append(min(limit, 2000))
    return [dict(r) for r in conn.execute(q, args).fetchall()]


# ── static web app ──────────────────────────────────────────────────────────

if STATIC.exists():
    app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = STATIC / path
        return FileResponse(f if path and f.is_file() else STATIC / "index.html")
