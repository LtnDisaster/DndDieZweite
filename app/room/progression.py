"""Class-progression WebSocket transport (thin, D53).

`class_levels` sets a character's multiclass entries. Authorization mirrors
the character-editing rules elsewhere: the DM may advance any character in the
room, and a user may always manage characters they own; anyone else is
refused server-side. The mutation itself is the pure operation
``progression.set_class_levels`` — future automation uses the same call.
"""
from .. import db, progression
from .net import broadcast, send_to


async def handle_class_levels(ws, room_id, user, is_dm, msg):
    try:
        cid = int(msg["character_id"])
    except (KeyError, ValueError, TypeError):
        return
    ch = db.q1("SELECT id, user_id, name FROM characters WHERE id=?", (cid,))
    if ch is None:
        await send_to(ws, "error", {"msg": "Unknown character"})
        return
    if ch["user_id"] == user["id"]:
        pass  # owners manage their own characters (same rule as character editing)
    elif is_dm and not db.q1("SELECT 1 AS ok FROM room_members WHERE room_id=? AND character_id=?",
                             (room_id, cid)):
        await send_to(ws, "error", {"msg": "That character is not in this room"})
        return
    elif not is_dm:
        await send_to(ws, "error", {"msg": "Not your character"})
        return
    if not progression.set_class_levels(cid, msg.get("class_levels")):
        await send_to(ws, "error", {"msg": "Invalid class levels (class_id + level 1..20)"})
        return
    await broadcast(room_id, "snapshot", None)
