"""Condition / status-effect WS handlers (DM manages all, players their own token)."""
from .. import conditions as C
from .. import db
from .net import broadcast, send_to, sys_msg


def _target(room_id, user, is_dm, msg):
    tok = db.q1("SELECT * FROM tokens WHERE id=? AND room_id=?", (msg.get("token_id", -1), room_id))
    if tok is None:
        return None
    if not (is_dm or tok["owner_user_id"] == user["id"]):
        return False          # visible-but-forbidden (distinct from "missing")
    return tok


async def handle_cond_add(ws, room_id, user, is_dm, msg):
    tok = _target(room_id, user, is_dm, msg)
    if tok is None:
        return
    if tok is False:
        await send_to(ws, "error", {"msg": "Not your token"})
        return
    conds = C.add(C.load(tok), msg.get("key"), msg.get("rounds", 0))
    db.x("UPDATE tokens SET conds=? WHERE id=?", (db.json_dumps(conds), tok["id"]))
    sys_msg(room_id, f"{tok['label']} is now {C.label(str(msg.get('key','')).strip())}.")
    await broadcast(room_id, "cond", {"token_id": tok["id"], "conds": conds})


async def handle_cond_remove(ws, room_id, user, is_dm, msg):
    tok = _target(room_id, user, is_dm, msg)
    if tok is None:
        return
    if tok is False:
        await send_to(ws, "error", {"msg": "Not your token"})
        return
    conds = C.remove(C.load(tok), msg.get("key"))
    db.x("UPDATE tokens SET conds=? WHERE id=?", (db.json_dumps(conds), tok["id"]))
    await broadcast(room_id, "cond", {"token_id": tok["id"], "conds": conds})
