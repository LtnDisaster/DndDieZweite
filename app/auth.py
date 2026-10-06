"""Password hashing + signed session cookies (stdlib HMAC, bcrypt for hashes)."""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time

import bcrypt
from fastapi import Depends, HTTPException, Request

from . import db

SECRET_FILE = os.path.join(db.DATA_DIR, "secret.key")
SESSION_TTL = 30 * 24 * 3600  # 30 days
COOKIE = "vtt_session"


def cookie_secure(request: "Request") -> bool:
    """True under HTTPS. X-Forwarded-Proto is trusted ONLY when VTT_TRUST_PROXY=1
    declares that a trusted proxy in front normalises it — otherwise an internet
    client could spoof the header on a direct connection."""
    if os.environ.get("VTT_COOKIE_SECURE") == "1":
        return True
    if os.environ.get("VTT_TRUST_PROXY") == "1":
        proto = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip()
        if proto:
            return proto == "https"
    return request.url.scheme == "https"


def _secret() -> bytes:
    # Key is stored HEX-encoded: raw 32 random bytes can contain ASCII whitespace
    # (0x0a, 0x20, ...), and the read-back below strips it — a freshly generated
    # raw key would then differ between the generating call and every later
    # read, silently invalidating the first issued session (~1.6% of installs).
    # Legacy raw files (pre-hex) keep working via the ValueError fallback.
    if os.path.exists(SECRET_FILE):
        with open(SECRET_FILE, "rb") as f:
            raw = f.read().strip()
        try:
            return bytes.fromhex(raw.decode("ascii"))
        except ValueError:
            return raw
    s = secrets.token_bytes(32)
    os.makedirs(db.DATA_DIR, exist_ok=True)
    with open(SECRET_FILE, "wb") as f:
        f.write(s.hex().encode())
    os.chmod(SECRET_FILE, 0o600)
    return s


def hash_pw(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def verify_pw(pw: str, pw_hash: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), pw_hash.encode())
    except ValueError:
        return False


def _sign(payload_b64: str) -> str:
    return hmac.new(_secret(), payload_b64.encode(), hashlib.sha256).hexdigest()


def make_token(user_id: int) -> str:
    # Padding-free base64url: a "=" inside an unquoted cookie VALUE makes cookie
    # parsers drop the whole cookie (intermittent 401s — the payload length
    # decides, so it looked random). Old padded tokens still verify (read_token
    # re-adds padding before decoding).
    payload = base64.urlsafe_b64encode(
        json.dumps({"uid": user_id, "exp": time.time() + SESSION_TTL}).encode()
    ).decode().rstrip("=")
    return f"{payload}.{_sign(payload)}"


def read_token(token: str):
    if not token or "." not in token:
        return None
    payload, sig = token.rsplit(".", 1)
    if not hmac.compare_digest(sig, _sign(payload)):
        return None
    try:
        padded = payload + "=" * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode()))
    except Exception:
        return None
    if data.get("exp", 0) < time.time():
        return None
    return data.get("uid")


def current_user(request: Request):
    uid = read_token(request.cookies.get(COOKIE, ""))
    if uid is None:
        return None
    return db.q1("SELECT id, username FROM users WHERE id=?", (uid,))


def require_user(user=Depends(current_user)):
    if user is None:
        raise HTTPException(401, "Not logged in")
    return user


def room_of(request: Request, code: str):
    """Auth + room membership check, returns (user, room)."""
    user = current_user(request)
    if user is None:
        raise HTTPException(401, "Not logged in")
    room = db.q1("SELECT * FROM rooms WHERE code=?", (code,))
    if room is None:
        raise HTTPException(404, "Room not found")
    member = db.q1("SELECT * FROM room_members WHERE room_id=? AND user_id=?", (room["id"], user["id"]))
    if member is None:
        raise HTTPException(403, "Not a member of this room")
    room["_role"] = member["role"]
    return user, room
