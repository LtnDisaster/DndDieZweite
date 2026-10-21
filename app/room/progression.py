"""Class-progression WebSocket transport (thin, D53).

`class_levels` sets a character's multiclass entries directly. Since D100 this raw
setter is DM-only: a DM may advance any character ASSIGNED to the room, and the
mutation is the pure ``progression.set_class_levels``. A player no longer changes
class levels here (that would bypass prerequisite/spell-grant validation) — the
validated, self-service path is the chronological build
(``/api/build/{code}/{cid}/apply`` → ``charbuild.apply``), which remains open to the
character's owner. Existing DM and server-side progression are unchanged.
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
    if not is_dm:
        # D100: owners advance through the validated build, not this raw setter.
        await send_to(ws, "error", {"msg": "DM only — advance your character with the Build"})
        return
    if not db.q1("SELECT 1 AS ok FROM room_members WHERE room_id=? AND character_id=?",
                 (room_id, cid)):
        await send_to(ws, "error", {"msg": "That character is not in this room"})
        return
    if not progression.set_class_levels(cid, msg.get("class_levels")):
        await send_to(ws, "error", {"msg": "Invalid class levels (class_id + level 1..20)"})
        return
    await broadcast(room_id, "snapshot", None)
