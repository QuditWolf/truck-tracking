"""Read-only access without a login: API keys (scripts, downstream apps) and the supervisor link."""

import hashlib
import hmac
import secrets

from fastapi import Depends, HTTPException, Request

from . import core
from .auth import COOKIE, current_user, get_conn


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def create_key(conn, name: str, user_id: int) -> dict:
    key = "tt_" + secrets.token_urlsafe(32)
    cur = conn.execute("INSERT INTO api_keys (name, prefix, hash, created_by, created_at) VALUES (?,?,?,?,?)",
                       (name.strip() or "key", key[:10], _hash(key), user_id, core.stamp()))
    core.audit(conn, user_id, "create", "api_key", cur.lastrowid, after={"name": name, "prefix": key[:10]})
    return {"id": cur.lastrowid, "name": name, "key": key}  # the full key is shown once, never stored


def check_key(conn, key: str) -> dict | None:
    row = conn.execute("SELECT * FROM api_keys WHERE hash = ? AND revoked = 0", (_hash(key),)).fetchone()
    if row:
        conn.execute("UPDATE api_keys SET last_used_at = ? WHERE id = ?", (core.stamp(), row["id"]))
    return dict(row) if row else None


def reader(request: Request, conn=Depends(get_conn)) -> dict:
    """Signed-in member, or a valid API key (Authorization: Bearer tt_... or X-API-Key)."""
    auth = request.headers.get("authorization", "")
    key = auth[7:].strip() if auth.lower().startswith("bearer ") else request.headers.get("x-api-key", "")
    if key:
        k = check_key(conn, key)
        if not k:
            raise HTTPException(401, "invalid or revoked API key")
        return {"api_key": k["name"]}
    if request.cookies.get(COOKIE):
        user = current_user(request, conn)
        if user["onboarded"]:
            return user
    raise HTTPException(401, "API key or sign-in required")


# ── supervisor link ─────────────────────────────────────────────────────────

def supervisor_token(conn) -> str:
    return core.setting(conn, "_supervisor_token")


def new_supervisor_token(conn, user_id: int) -> str:
    token = secrets.token_urlsafe(18)
    core.set_setting(conn, "_supervisor_token", token)
    core.audit(conn, user_id, "rotate", "supervisor_link", None)
    return token


def disable_supervisor(conn, user_id: int) -> None:
    core.set_setting(conn, "_supervisor_token", "")
    core.audit(conn, user_id, "disable", "supervisor_link", None)


def supervisor(token: str, conn=Depends(get_conn)) -> bool:
    current = supervisor_token(conn)
    if not current or not hmac.compare_digest(token, current):
        raise HTTPException(404, "link not valid")
    return True
