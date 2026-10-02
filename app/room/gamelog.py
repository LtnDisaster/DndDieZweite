"""Game-log posting and per-viewer message delivery.

The message table is the durable feed. Delivery is role-scoped server-side; hidden
rolls are never broadcast-and-hidden in CSS.
"""
from .. import db
from .net import broadcast, send_user

VISIBILITIES = {"public", "self", "dm", "blind"}


def clean_visibility(value, is_dm=False):
    v = str(value or "public").strip().lower()
    if v in ("private", "self"):
        return "self"
    if v == "dm":
        return "dm" if is_dm else "self"
    if v == "blind":
        return "blind"
    return "public"


def _dm_users(room_id):
    return {m["user_id"] for m in db.q(
        "SELECT user_id FROM room_members WHERE room_id=? AND role='dm'", (room_id,))}


def _is_dm(room_id, user_id):
    return bool(db.q1("SELECT 1 AS ok FROM room_members WHERE room_id=? AND user_id=? AND role='dm'",
                      (room_id, user_id)))


async def post_message(room_id, user, text, *, total=None, visibility="public",
                       kind="dice", is_dm=None, meta=None, recipient_user_id=None):
    text = str(text or "").strip()[:4000]
    if not text:
        return None
    if is_dm is None:
        is_dm = _is_dm(room_id, user["id"])
    visibility = clean_visibility(visibility, is_dm)
    meta = meta if isinstance(meta, dict) else {}
    if visibility == "blind" and recipient_user_id is None:
        room = db.q1("SELECT dm_id FROM rooms WHERE id=?", (room_id,))
        recipient_user_id = int(room["dm_id"]) if room else user["id"]

    mid = db.x(
        "INSERT INTO messages (room_id,user_id,type,body,visibility,recipient_user_id,meta) "
        "VALUES (?,?,?,?,?,?,?)",
        (room_id, user["id"], kind, text, visibility, recipient_user_id, db.json_dumps(meta)))
    entry = {"id": mid, "username": user["username"], "text": text, "body": text,
             "total": total, "visibility": visibility, "meta": meta}
    event = "chat" if kind == "chat" else kind

    if visibility == "public":
        await broadcast(room_id, event, entry)
    elif visibility == "dm":
        for uid in _dm_users(room_id):
            await send_user(room_id, uid, event, entry)
    elif visibility == "blind":
        dm_users = _dm_users(room_id)
        if recipient_user_id:
            dm_users.add(int(recipient_user_id))
        for uid in dm_users:
            await send_user(room_id, uid, event, entry)
    else:  # self/private
        recipients = {int(user["id"])} | _dm_users(room_id)
        for uid in recipients:
            await send_user(room_id, uid, event, entry)

    if visibility == "blind" and not is_dm:
        await post_blind_request(room_id, user,
                                 meta.get("request") or "🎲 Blind roll requested.",
                                 is_dm=is_dm, meta={"expr": meta.get("expr", ""), "actor": user["username"]})
    return mid


async def post_blind_request(room_id, user, text, *, is_dm=None, meta=None):
    """Tell the requesting player that a blind roll was requested, without any result."""
    return await post_message(room_id, user, text, total=None, visibility="self",
                              kind="dice", is_dm=is_dm, meta={**(meta or {}), "blind_request": True})


def filter_messages_for_viewer(room_id, user_id, is_dm, limit=100):
    if is_dm:
        return db.q(
            "SELECT ms.id, ms.user_id, u.username, ms.type, ms.body, ms.created_at, "
            "ms.visibility, ms.recipient_user_id, ms.meta FROM messages ms "
            "LEFT JOIN users u ON u.id=ms.user_id WHERE ms.room_id=? AND ms.type IN ('dice','system') "
            "ORDER BY ms.id DESC LIMIT ?",
            (room_id, limit))
    return db.q(
        "SELECT ms.id, ms.user_id, u.username, ms.type, ms.body, ms.created_at, "
        "ms.visibility, ms.recipient_user_id, ms.meta FROM messages ms "
        "LEFT JOIN users u ON u.id=ms.user_id "
        "WHERE ms.room_id=? AND ms.type IN ('dice','system') AND ("
        "  ms.visibility='public' "
        "  OR (ms.visibility='self' AND (ms.user_id=? OR ms.recipient_user_id=?))"
        ") ORDER BY ms.id DESC LIMIT ?",
        (room_id, user_id, user_id, limit))
