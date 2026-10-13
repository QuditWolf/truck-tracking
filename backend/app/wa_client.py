"""Talks to the Baileys bridge (wa/index.js) on localhost. Swappable in tests via `set_transport`."""

import hashlib

import httpx

from . import core

TOKEN = hashlib.sha256(f"{core.SECRET}:wa".encode()).hexdigest()


class BridgeError(Exception):
    pass


def _http(method: str, path: str, body: dict | None = None, timeout: float = 20) -> dict | list:
    try:
        r = httpx.request(method, core.WA_URL + path, json=body, timeout=timeout, headers={"x-wa-token": TOKEN})
    except httpx.HTTPError as e:
        raise BridgeError(f"bridge unreachable: {e}") from e
    data = r.json() if r.content else {}
    if r.status_code >= 400:
        raise BridgeError(data.get("error", f"HTTP {r.status_code}") if isinstance(data, dict) else str(data))
    return data


_transport = _http


def set_transport(fn) -> None:
    global _transport
    _transport = fn


def status() -> dict:
    try:
        return _transport("GET", "/status", timeout=5)
    except BridgeError as e:
        return {"state": "offline", "error": str(e), "qr": None, "me": None}


def groups() -> list:
    return _transport("GET", "/groups")


def send(jid: str, text: str, quote: dict | None = None) -> str | None:
    return _transport("POST", "/send", {"jid": jid, "text": text, "quote": quote}).get("id")


def logout() -> None:
    _transport("POST", "/logout", {})
