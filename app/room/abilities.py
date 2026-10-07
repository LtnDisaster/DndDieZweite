"""WS transport for ability casting: parse → authorize → abilities.execute → filtered reply.

Everything mechanical lives in ``app.abilities.execute`` (D55); this module only maps
a client message to the operation and back. A player may act ONLY through a token
they control (their own character); the DM may act through any token in the room.
The reply is filtered: a player never learns WHICH hidden creature their AoE hit —
only how many (D62); the game-log chronicle applies the same filter inside the core.
"""
from .. import abilities, db
from . import authz
from .net import send_to


async def handle_ability_cast(ws, room_id, user, is_dm, msg):
    tok = db.q1("SELECT * FROM tokens WHERE id=? AND room_id=?",
                (msg.get("token_id", -1), room_id))
    if tok is None:
        await send_to(ws, "error", {"msg": "No such token in this room"})
        return
    if not is_dm and not authz.controls(tok, user["id"], False):
        # D82: own character OR a token the DM assigned to this player
        # (controller casting through a familiar uses the NPC block).
        await send_to(ws, "error", {"msg": "You can only cast through your own character"})
        return
    point = None
    if msg.get("x") is not None and msg.get("y") is not None:
        point = (msg.get("x"), msg.get("y"))
    result = await abilities.execute(
        room_id, actor_token_id=tok["id"], ability_id=str(msg.get("ability_id", "")),
        is_dm=is_dm, actor_user_id=user["id"], target_id=msg.get("target_id"),
        point=point, direction=str(msg.get("direction", "E")),
        cast_level=msg.get("cast_level"), adv=msg.get("adv"), user=user)
    if not result["ok"]:
        await send_to(ws, "error", {"msg": result["error"]})
        return
    visible_entries = [e for e in result["entries"] if e["visible"]]
    await send_to(ws, "ability_result", {
        "ability": result["ability"]["name"], "dc": result["dc"],
        "entries": [{k: v for k, v in e.items() if k != "visible"} for e in visible_entries],
        "hidden_count": result["hidden_count"], "consumed": result["consumed"]})
