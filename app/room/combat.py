"""Combat: initiative tracking and DM HP adjustments."""
import json
import random

from .. import db
from .dice import dex_mod
from .net import broadcast, sys_msg


def get_init(room_id):
    st = db.q1("SELECT initiative FROM room_state WHERE room_id=?", (room_id,))
    init = db.j((st or {}).get("initiative"), {"combat": False, "order": [], "active": -1, "round": 0}) \
        or {"combat": False, "order": [], "active": -1, "round": 0}
    if "round" not in init:                     # pre-round saves default sensibly
        init["round"] = 1 if init.get("combat") else 0
    return init


def set_init(room_id, init):
    db.x("UPDATE room_state SET initiative=? WHERE room_id=?", (json.dumps(init), room_id))


async def handle_init_start(ws, room_id, user, is_dm, msg):
    if not is_dm:
        return
    order = []
    for tok in db.q("SELECT * FROM tokens WHERE room_id=? ORDER BY id", (room_id,)):
        mod = dex_mod(tok["character_id"])
        roll = random.randint(1, 20)
        order.append({"token_id": tok["id"], "label": tok["label"], "color": tok["color"],
                      "mod": mod, "roll": roll, "total": roll + mod})
    order.sort(key=lambda o: o["total"], reverse=True)
    init = {"combat": True, "round": 1, "order": order, "active": 0}
    set_init(room_id, init)
    sys_msg(room_id, "Combat started! — Round 1")
    await broadcast(room_id, "initiative", init)


async def handle_init_next(ws, room_id, user, is_dm, msg):
    if not is_dm:
        return
    init = get_init(room_id)
    if init["combat"] and init["order"]:
        init["active"] = (init["active"] + 1) % len(init["order"])
        set_init(room_id, init)
        await broadcast(room_id, "initiative", init)


async def handle_init_end_round(ws, room_id, user, is_dm, msg):
    """DM ends the current round: increment the round counter and return to the
    top of the (still fixed) initiative order. Initiative is rolled once per
    combat (D22), not re-rolled here."""
    if not is_dm:
        return
    init = get_init(room_id)
    if not init["combat"] or not init["order"]:
        return
    init["round"] = int(init.get("round", 1)) + 1
    init["active"] = 0
    set_init(room_id, init)
    sys_msg(room_id, f"— Round {init['round']} —")
    await broadcast(room_id, "initiative", init)


async def handle_init_end(ws, room_id, user, is_dm, msg):
    if not is_dm:
        return
    init = {"combat": False, "order": [], "active": -1, "round": 0}
    set_init(room_id, init)
    sys_msg(room_id, "Combat ended.")
    await broadcast(room_id, "initiative", init)


async def handle_hp(ws, room_id, user, is_dm, msg):
    if not is_dm:
        return
    tok = db.q1("SELECT * FROM tokens WHERE id=? AND room_id=?", (msg.get("token_id", -1), room_id))
    if tok is None or tok["character_id"] is None:
        return
    ch = db.q1("SELECT * FROM characters WHERE id=?", (tok["character_id"],))
    try:
        delta = max(-999, min(999, int(msg.get("delta", 0))))
    except (TypeError, ValueError):
        return
    hp = max(0, min(ch["max_hp"], ch["hp"] + delta))
    db.x("UPDATE characters SET hp=? WHERE id=?", (hp, ch["id"]))
    verb = "takes" if delta < 0 else "heals"
    sys_msg(room_id, f"{ch['name']} {verb} {abs(delta)} → {hp}/{ch['max_hp']} HP")
    await broadcast(room_id, "snapshot", None)
