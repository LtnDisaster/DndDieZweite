"""DM token management (add / remove NPC tokens)."""
import re

from .. import db
from .net import broadcast, send_to, sys_msg
from .visibility import broadcast_token_add, forget_token

WALL = "#95a5a6"


async def handle_add_token(ws, room_id, user, is_dm, msg):
    if not is_dm:
        return
    label = str(msg.get("label", "NPC"))[:32]
    color = str(msg.get("color", WALL))
    if not re.match(r"^#[0-9a-fA-F]{6}$", color):
        color = WALL
    try:
        x, y = float(msg.get("x", 500)), float(msg.get("y", 300))
    except (TypeError, ValueError):
        x, y = 500.0, 300.0
    tid = db.x("INSERT INTO tokens (room_id,label,color,x,y) VALUES (?,?,?,?,?)",
               (room_id, label, color, x, y))
    tok = db.q1("SELECT * FROM tokens WHERE id=?", (tid,))
    sys_msg(room_id, f"DM added token '{label}'.")
    await broadcast_token_add(room_id, tok)


async def handle_del_token(ws, room_id, user, is_dm, msg):
    if not is_dm:
        return
    tok = db.q1("SELECT * FROM tokens WHERE id=? AND room_id=?", (msg.get("token_id", -1), room_id))
    if tok and (tok["owner_user_id"] is None or is_dm):
        if tok["owner_user_id"] is not None:
            db.x("UPDATE room_members SET character_id=NULL WHERE user_id=? AND room_id=?",
                 (tok["owner_user_id"], room_id))
        db.x("UPDATE tokens SET owner_user_id=NULL, character_id=NULL, label='Gone', color='#555' WHERE id=?",
             (tok["id"],))
        sys_msg(room_id, f"DM removed token '{tok['label']}'.")
        await forget_token(room_id, tok["id"])
        await broadcast(room_id, "snapshot", None)
