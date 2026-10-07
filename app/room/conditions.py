"""Condition / status-effect WS handlers (DM manages all, players their own token)."""
from .. import conditions as C
from .. import db, movecost
from . import authz
from .net import broadcast, send_to, sys_msg


def _target(room_id, user, is_dm, msg):
    tok = db.q1("SELECT * FROM tokens WHERE id=? AND room_id=?", (msg.get("token_id", -1), room_id))
    if tok is None:
        return None
    if not authz.controls(tok, user["id"], is_dm):   # D82: owner or assigned controller
        return False          # visible-but-forbidden (distinct from "missing")
    return tok


async def handle_cond_add(ws, room_id, user, is_dm, msg):
    tok = _target(room_id, user, is_dm, msg)
    if tok is None:
        return
    if tok is False:
        await send_to(ws, "error", {"msg": "Not your token"})
        return
    conds = C.add(C.load(tok), msg.get("key"), msg.get("rounds", 0), msg.get("until", ""))
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


def stand_cost_units(tok):
    """Standing up costs half the creature's CURRENT TURN BASE movement (D80):
    ceil(walk_budget / 2) — the BASE, so a Dashed turn does not make standing
    up more expensive. The SSOT conversion stays in movecost; no second math."""
    from .movement import _walk_speed        # local: movement imports combat
    return -(-movecost.walk_budget(_walk_speed(tok)) // 2)


async def handle_stand(ws, room_id, user, is_dm, msg):
    """Stand Up (D80): the explicit, server-authoritative way to end prone.
    Never moves or teleports the token. In combat (token listed, own turn,
    owner or DM) it charges half the turn's BASE movement through the ONE turn
    budget (spend_move -> the same accounting Dash and walk use); outside
    combat it is free. Prone is removed only after every validation passed."""
    tok = _target(room_id, user, is_dm, msg)
    if tok is None:
        return
    if tok is False:
        await send_to(ws, "error", {"msg": "Not your token"})
        return
    conds = C.load(tok)
    if not any(c["k"].lower() == "prone" for c in conds):
        await send_to(ws, "error", {"msg": "Not prone"})
        return
    from .movement import _movement_block_reason
    blocked = _movement_block_reason(tok)
    if blocked:
        await send_to(ws, "error", {"msg": blocked})
        return
    from . import combat as CB               # local: avoid an import cycle
    init = CB.get_init(room_id)
    cost = 0
    if not is_dm and CB.is_listed(init, tok["id"]):
        if CB.turn_token(init) != tok["id"]:
            await send_to(ws, "error", {"msg": "It is not your turn"})
            return
        cost = stand_cost_units(tok)
        if CB.move_remaining(init, tok["id"]) < cost:
            await send_to(ws, "error", {"msg": "Not enough movement to stand up"})
            return
    new = C.remove(conds, "prone")
    db.x("UPDATE tokens SET conds=? WHERE id=?", (db.json_dumps(new), tok["id"]))
    if cost:
        CB.spend_move(room_id, tok["id"], cost)
    sys_msg(room_id, f"{tok['label']} stands up." + (f" ({cost} movement)" if cost else ""))
    await broadcast(room_id, "cond", {"token_id": tok["id"], "conds": new})
    if cost:
        await broadcast(room_id, "initiative", CB.get_init(room_id))
