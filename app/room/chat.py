"""Chat, whispers, DM personas and narrative delivery.

Delivery is always resolved server-side. A private message is inserted with
recipient metadata and sent only to the authorized sockets; it is never broadcast
and then hidden by the client.
"""
import re
import time
from collections import defaultdict, deque

from .. import db, npc
from .net import broadcast, send_to, send_user

MAX_TEXT = 4000
MAX_PERSONA = 64
CHANNELS = {"global", "dm", "whisper"}
STYLES = {"normal", "voice", "overlay", "whisper"}
_hits: dict[tuple, deque] = defaultdict(deque)
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _rate_ok(room_id, user_id, bucket="chat", limit=20, window=10.0):
    now = time.time()
    q = _hits[(room_id, user_id, bucket)]
    while q and q[0] < now - window:
        q.popleft()
    if len(q) >= limit:
        return False
    q.append(now)
    return True


def clear_rate_state():
    _hits.clear()


def clean_text(value, limit=MAX_TEXT):
    return _CONTROL.sub("", str(value or "")).strip()[:limit].strip()


def clean_persona(value):
    return _CONTROL.sub("", str(value or "")).strip()[:MAX_PERSONA].strip()


def clean_style(value):
    v = str(value or "").strip().lower()
    return v if v in STYLES else ""


def _recipients_from_msg(msg):
    raw = msg.get("recipient_ids", msg.get("recipients", msg.get("recipients_id")))
    if raw is None:
        raw = []
    if isinstance(raw, (list, tuple, set)):
        out = list(raw)
    else:
        out = [raw]
    one = msg.get("recipient_id", msg.get("target_id", msg.get("target")))
    if one is not None:
        out.append(one)
    return out


def _member_ids(room_id):
    return {m["user_id"] for m in db.q("SELECT user_id FROM room_members WHERE room_id=?", (room_id,))}


def _dm_ids(room_id):
    return {m["user_id"] for m in db.q(
        "SELECT user_id FROM room_members WHERE room_id=? AND role='dm'", (room_id,))}


def _valid_recipients(room_id, requested):
    members = _member_ids(room_id)
    out = set()
    for raw in list(requested or [])[:50]:
        try:
            uid = int(raw)
        except (TypeError, ValueError):
            continue
        if uid in members:
            out.add(uid)
    return sorted(out)


def _persona_clashes(room_id, persona):
    persona = clean_persona(persona).lower()
    if not persona:
        return False
    rows = db.q("SELECT u.username FROM room_members m JOIN users u ON u.id=m.user_id WHERE m.room_id=?",
                (room_id,))
    return any(str(r["username"] or "").strip().lower() == persona for r in rows)


def _resolve_npc(room_id, token_id):
    try:
        tid = int(token_id)
    except (TypeError, ValueError):
        return None
    tok = db.q1("SELECT * FROM tokens WHERE id=? AND room_id=?", (tid, room_id))
    if not tok or tok.get("owner_user_id") is not None or tok.get("character_id") is not None:
        return None
    if npc.load(tok) is None:
        return None
    return tok


async def _error(ws, message):
    await send_to(ws, "error", {"msg": message})


def _resolve_recipients(room_id, sender_id, is_dm, channel, requested):
    requested = _valid_recipients(room_id, requested)
    if channel == "global":
        return "public", []
    if channel == "dm":
        if is_dm:
            targets = [uid for uid in requested if uid != sender_id]
            if not targets:
                return "dm", []
            return "whisper", targets
        targets = [uid for uid in _dm_ids(room_id) if uid != sender_id]
        return ("whisper", targets) if targets else (None, [])
    targets = [uid for uid in requested if uid != sender_id]
    return ("whisper", targets) if targets else (None, [])


def _json_list(value):
    parsed = db.j(value, [])
    if not isinstance(parsed, list):
        return []
    out = []
    for x in parsed:
        try:
            out.append(int(x))
        except (TypeError, ValueError):
            continue
    return out


def _message_payload(mid, room_id=None):
    row = db.q1(
        "SELECT m.id, m.room_id, m.user_id, u.username, m.type, m.body, m.channel, m.persona, "
        "m.sender_kind, m.npc_token_id, m.visibility, m.recipient_ids, m.style, m.meta, m.created_at, "
        "t.label AS npc_label FROM messages m "
        "LEFT JOIN users u ON u.id=m.user_id "
        "LEFT JOIN tokens t ON t.id=m.npc_token_id "
        "WHERE m.id=?", (mid,))
    if not row or (room_id is not None and row.get("room_id") != int(room_id)):
        return None
    return _chat_row(row)


def _chat_row(row):
    meta = db.j(row.get("meta"), {})
    if not isinstance(meta, dict):
        meta = {}
    persona = clean_persona(row.get("persona"))
    sender_kind = str(row.get("sender_kind") or "user").lower()
    if sender_kind not in ("user", "persona", "npc"):
        sender_kind = "user"
    npc_label = clean_persona(row.get("npc_label")) or persona
    display = persona if (sender_kind == "npc" and npc_label) else persona if (sender_kind == "persona" and persona) else row.get("username")
    return {
        "id": row.get("id"),
        "type": row.get("type") or "chat",
        "channel": str(row.get("channel") or "").lower(),
        "user_id": row.get("user_id"),
        "username": row.get("username"),
        "display_name": display,
        "text": row.get("body") or "",
        "body": row.get("body") or "",
        "persona": persona,
        "sender_kind": sender_kind,
        "npc_token_id": row.get("npc_token_id"),
        "visibility": row.get("visibility") or "public",
        "recipient_ids": _json_list(row.get("recipient_ids")),
        "style": str(row.get("style") or ""),
        "meta": meta,
        "created_at": row.get("created_at"),
    }


def _visible_row(row, user_id, is_dm):
    visibility = row.get("visibility") or "public"
    if visibility == "public":
        return True
    if visibility == "dm":
        return bool(is_dm)
    if visibility == "whisper":
        return row.get("user_id") == user_id or user_id in _json_list(row.get("recipient_ids"))
    if visibility == "self":
        return row.get("user_id") == user_id or bool(is_dm)
    return False


async def post_chat(room_id, user, *, text, channel="global", visibility="public",
                    recipients=(), persona="", sender_kind="user", npc_token_id=None,
                    style="", kind="chat", meta=None, event=None, include_sender=True):
    text = clean_text(text)
    if not text:
        return None
    meta = meta if isinstance(meta, dict) else {}
    persona = clean_persona(persona) if sender_kind in ("persona", "npc") else ""
    sender_kind = sender_kind if sender_kind in ("user", "persona", "npc") else "user"
    recipients = _valid_recipients(room_id, recipients)
    if visibility == "public":
        recipients = []
    elif visibility != "dm":
        visibility = "whisper"
        if include_sender:
            recipients = sorted(set(recipients) | {user["id"]})
    else:
        recipients = []
    kind = "narrative" if kind == "narrative" else "chat"
    event = event or kind
    mid = db.x(
        "INSERT INTO messages (room_id,user_id,type,body,visibility,meta,channel,recipient_ids,"
        "persona,sender_kind,npc_token_id,style) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (room_id, user["id"], kind, text, visibility, db.json_dumps(meta), channel,
         db.json_dumps(recipients), persona, sender_kind, npc_token_id, style))
    payload = _message_payload(mid, room_id)
    if payload is None:
        return None
    if visibility == "public":
        await broadcast(room_id, event, payload)
    elif visibility == "dm":
        users = set(_dm_ids(room_id))
        if include_sender:
            users.add(user["id"])
        for uid in users:
            await send_user(room_id, uid, event, payload)
    else:
        users = set(recipients)
        if include_sender:
            users.add(user["id"])
        for uid in users:
            await send_user(room_id, uid, event, payload)
    return mid


def chat_history_for_viewer(room_id, user_id, is_dm, limit=200):
    rows = db.q(
        "SELECT m.id, m.room_id, m.user_id, u.username, m.type, m.body, m.channel, m.persona, "
        "m.sender_kind, m.npc_token_id, m.visibility, m.recipient_ids, m.style, m.meta, m.created_at, "
        "t.label AS npc_label FROM messages m "
        "LEFT JOIN users u ON u.id=m.user_id "
        "LEFT JOIN tokens t ON t.id=m.npc_token_id "
        "WHERE m.room_id=? AND m.type IN ('chat','narrative') ORDER BY m.id DESC LIMIT ?",
        (room_id, max(1, min(int(limit or 200), 500))))
    out = []
    for row in reversed(rows):
        if _visible_row(row, user_id, is_dm):
            out.append(_chat_row(row))
    return out[-int(limit or 200):]


async def _clean_sender(room_id, user, is_dm, msg):
    if not is_dm:
        return {"kind": "user", "persona": "", "npc_token_id": None, "error": None}
    kind = str(msg.get("sender_kind") or "user").strip().lower()
    if kind not in ("user", "persona", "npc"):
        kind = "user"
    persona = clean_persona(msg.get("persona"))
    if kind == "npc":
        tok = _resolve_npc(room_id, msg.get("npc_token_id"))
        if tok is None:
            return {"kind": kind, "persona": persona, "npc_token_id": None, "error": "Unknown NPC"}
        return {"kind": "npc", "persona": clean_persona(tok["label"]), "npc_token_id": tok["id"], "error": None}
    if kind == "persona":
        if not persona:
            persona = "Unknown Voice"
        if _persona_clashes(room_id, persona):
            return {"kind": kind, "persona": persona, "npc_token_id": None, "error": "Persona cannot match a room member name"}
        return {"kind": "persona", "persona": persona, "npc_token_id": None, "error": None}
    return {"kind": "user", "persona": "", "npc_token_id": None, "error": None}


async def handle_chat(ws, room_id, user, is_dm, msg):
    if not _rate_ok(room_id, user["id"], "chat"):
        await _error(ws, "Chat is being sent too quickly.")
        return
    text = clean_text(msg.get("text"))
    if not text:
        return
    channel = str(msg.get("channel") or "global").strip().lower()
    if channel not in CHANNELS:
        channel = "global"
    sender = await _clean_sender(room_id, user, is_dm, msg)
    if sender["error"]:
        await _error(ws, sender["error"])
        return
    visibility, recipients = _resolve_recipients(room_id, user["id"], is_dm, channel,
                                                 _recipients_from_msg(msg))
    if visibility is None:
        await _error(ws, "A whisper recipient is required.")
        return
    style = clean_style(msg.get("style")) if is_dm else ""
    await post_chat(room_id, user, text=text, channel=channel, visibility=visibility,
                    recipients=recipients, persona=sender["persona"], sender_kind=sender["kind"],
                    npc_token_id=sender["npc_token_id"], style=style)


def _resolve_narrative_target(room_id, target):
    raw = str(target if target is not None else "all").strip().lower()
    if raw in ("all", "everyone", "party", "public", "room", ""):
        return "public", []
    ids = _valid_recipients(room_id, [target])
    return ("whisper", ids) if ids else (None, [])


async def handle_narrative(ws, room_id, user, is_dm, msg):
    if not is_dm:
        await _error(ws, "DM only")
        return
    if not _rate_ok(room_id, user["id"], "narrative", limit=12, window=10.0):
        await _error(ws, "Narration is being sent too quickly.")
        return
    text = clean_text(msg.get("text"))
    if not text:
        return
    visibility, recipients = _resolve_narrative_target(room_id, msg.get("target", "all"))
    if visibility is None:
        await _error(ws, "Unknown narrative recipient.")
        return
    sender = await _clean_sender(room_id, user, is_dm, msg)
    if sender["error"]:
        await _error(ws, sender["error"])
        return
    style = clean_style(msg.get("style")) or "overlay"
    await post_chat(room_id, user, text=text, channel="narrative", visibility=visibility,
                    recipients=recipients, persona=sender["persona"], sender_kind=sender["kind"],
                    npc_token_id=sender["npc_token_id"], style=style, kind="narrative",
                    event="narrative",
                    meta={"overlay": style == "overlay", "private": visibility != "public"})
