"""Login protection for running the app on a public address.

One shared team password (WFD_PASSWORD, server-side only) plus the reviewer's name. A successful login sets an
HttpOnly, signed session cookie. Failed attempts are slowed down and temporarily locked per IP address.
Mutating requests must be JSON (browsers cannot send cross-site JSON without a CORS preflight, which this
server never grants), which, together with SameSite=Lax cookies, blocks cross-site request forgery.

When WFD_PASSWORD is empty, login is off; the server then refuses to listen on anything but 127.0.0.1.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time

from .config import DATA_DIR, env

COOKIE = "wfd_session"
SESSION_DAYS = 14
_fail: dict[str, list[float]] = {}
_global_fail: list[float] = []
_lock = threading.Lock()
PER_IP_LIMIT = 8        # failed attempts per address per 15 minutes
GLOBAL_LIMIT = 40       # failed attempts from all addresses per 15 minutes (backstop if addresses are faked)
WINDOW = 900


def enabled() -> bool:
    return bool(env("WFD_PASSWORD"))


def _secret() -> bytes:
    s = env("WFD_SECRET")
    if s:
        return s.encode()
    p = DATA_DIR / ".session_secret"
    if not p.exists():
        p.write_text(secrets.token_hex(32))
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass
    # Changing WFD_PASSWORD invalidates existing sessions.
    return (p.read_text().strip() + "|" + hashlib.sha256(env("WFD_PASSWORD").encode()).hexdigest()).encode()


def make_token(name: str) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"n": name, "exp": time.time() + SESSION_DAYS * 86400}).encode()).decode()
    sig = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def read_token(token: str | None) -> str | None:
    if not token or "." not in token:
        return None
    payload, sig = token.rsplit(".", 1)
    good = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, good):
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(payload.encode()))
    except Exception:
        return None
    if data.get("exp", 0) < time.time():
        return None
    return data.get("n") or "reviewer"


def cookie_value(headers) -> str | None:
    raw = headers.get("Cookie") or ""
    for part in raw.split(";"):
        k, _, v = part.strip().partition("=")
        if k == COOKIE:
            return v
    return None


def current_user(headers) -> str | None:
    if not enabled():
        return "local"
    return read_token(cookie_value(headers))


def check_login(ip: str, name: str, password: str) -> tuple[bool, str]:
    now = time.time()
    with _lock:
        recent = [t for t in _fail.get(ip, []) if now - t < WINDOW]
        _fail[ip] = recent
        _global_fail[:] = [t for t in _global_fail if now - t < WINDOW]
        if len(recent) >= PER_IP_LIMIT:
            wait = int(WINDOW - (now - recent[0]))
            return False, f"Too many failed attempts. Try again in {max(1, wait // 60)} minute(s)."
        if len(_global_fail) >= GLOBAL_LIMIT:
            wait = int(WINDOW - (now - _global_fail[0]))
            return False, (f"Sign-in is paused for everyone after many failed attempts. Try again in {max(1, wait // 60)} "
                           f"minute(s). People already signed in are not affected.")
    ok = hmac.compare_digest(password.encode(), env("WFD_PASSWORD").encode())
    if not ok:
        time.sleep(min(3.0, 0.5 * (len(recent) + 1)))  # slow down guessing
        with _lock:
            _fail.setdefault(ip, []).append(now)
            _global_fail.append(now)
        return False, "Wrong password."
    if not name.strip():
        return False, "Enter your name so review history shows who made each change."
    with _lock:
        _fail.pop(ip, None)
    return True, ""


def set_cookie_header(token: str, secure: bool, clear: bool = False) -> str:
    attrs = [f"{COOKIE}={'' if clear else token}", "Path=/", "HttpOnly", "SameSite=Lax"]
    attrs.append("Max-Age=0" if clear else f"Max-Age={SESSION_DAYS * 86400}")
    if secure:
        attrs.append("Secure")
    return "; ".join(attrs)
