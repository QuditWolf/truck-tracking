"""Google sign-in → signed session cookie. Admin = email listed in ADMIN_EMAILS."""

from fastapi import Depends, HTTPException, Request, Response
from itsdangerous import BadSignature, URLSafeTimedSerializer

from . import core

COOKIE = "paddy_session"
MAX_AGE = 60 * 60 * 24 * 90  # 90 days — field users shouldn't have to log in every week
_signer = URLSafeTimedSerializer(core.SECRET, salt="session")


def verify_google(credential: str) -> dict:
    from google.auth.transport import requests as g_requests
    from google.oauth2 import id_token

    if not core.GOOGLE_CLIENT_ID:
        raise HTTPException(500, "GOOGLE_CLIENT_ID not configured")
    try:
        info = id_token.verify_oauth2_token(credential, g_requests.Request(), core.GOOGLE_CLIENT_ID)
    except ValueError as e:
        raise HTTPException(401, f"invalid Google credential: {e}")
    if not info.get("email_verified"):
        raise HTTPException(401, "email not verified")
    return {"sub": info["sub"], "email": info["email"].lower(), "name": info.get("name", "")}


def login(conn, response: Response, sub: str, email: str) -> dict:
    row = conn.execute("SELECT * FROM users WHERE google_sub = ?", (sub,)).fetchone()
    if not row:
        cur = conn.execute("INSERT INTO users (google_sub, email, created_at) VALUES (?,?,?)",
                           (sub, email, core.stamp()))
        core.audit(conn, cur.lastrowid, "signup", "user", cur.lastrowid, after={"email": email})
        row = conn.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()
    if row["disabled"]:
        raise HTTPException(403, "account disabled")
    response.set_cookie(COOKIE, _signer.dumps(row["id"]), max_age=MAX_AGE, httponly=True,
                        samesite="lax", secure=not core.DEV_LOGIN)
    return user_dict(row)


def user_dict(row) -> dict:
    return {"id": row["id"], "email": row["email"], "name": row["name"], "phone": row["phone"],
            "is_admin": row["email"].lower() in core.ADMIN_EMAILS, "onboarded": bool(row["name"] and row["phone"]),
            "disabled": bool(row["disabled"])}


def get_conn():
    """One SQLite connection per request: connections must not be shared across threads."""
    conn = core.connect()
    try:
        yield conn
    finally:
        conn.close()


def current_user(request: Request, conn=Depends(get_conn)) -> dict:
    token = request.cookies.get(COOKIE)
    try:
        uid = _signer.loads(token, max_age=MAX_AGE) if token else None
    except BadSignature:
        uid = None
    row = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone() if uid else None
    if not row or row["disabled"]:
        raise HTTPException(401, "not signed in")
    return user_dict(row)


def member(user=Depends(current_user)) -> dict:
    """Signed in and finished onboarding (name + phone)."""
    if not user["onboarded"]:
        raise HTTPException(403, "complete your profile first")
    return user


def admin(user=Depends(current_user)) -> dict:
    if not user["is_admin"]:
        raise HTTPException(403, "admin only")
    return user
