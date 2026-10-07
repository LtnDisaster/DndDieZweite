"""Combat: initiative tracking and DM HP adjustments."""
import json
import random

from .. import db, movecost, npc
from .. import conditions as C
from . import death as D, health
from .dice import dex_mod
from .net import broadcast, send_to, sys_msg


def step_conditions(room_id):
    """Advance timed conditions on every token by one round.

    Returns a list of ``(token_id, new_conds)`` for the tokens that changed, so the
    caller can stream the updates. Permanent (``rounds == 0``) conditions and the
    turn-anchored ones (``until`` = start/end — their clock is the turn hook below,
    never this one, D80) are kept untouched.
    """
    changed = []
    for tok in db.q("SELECT id, conds FROM tokens WHERE room_id=?", (room_id,)):
        new, dirty = C.step_rounds(C.load(tok))
        if dirty:
            db.x("UPDATE tokens SET conds=? WHERE id=?", (db.json_dumps(new), tok["id"]))
            changed.append((tok["id"], new))
    return changed


def _tick_turn_conditions(room_id, token_id, phase):
    """The ONE place a turn hook expires conditions (D80): advance the turn clock
    of ``token_id`` at its turn ``phase`` ("start"/"end"). Returns
    ``(token_id, new_conds)`` when something changed, else None."""
    if token_id is None:
        return None
    tok = db.q1("SELECT id, conds FROM tokens WHERE id=? AND room_id=?", (token_id, room_id))
    if tok is None:
        return None
    new, dirty = C.step_turn(C.load(tok), phase)
    if not dirty:
        return None
    db.x("UPDATE tokens SET conds=? WHERE id=?", (db.json_dumps(new), tok["id"]))
    return (tok["id"], new)


def token_dex_mod(tok):
    """DEX modifier for any token: an attached character, else an NPC stat block."""
    if tok["character_id"]:
        return dex_mod(tok["character_id"])
    block = npc.load(tok)
    return npc.dex_mod(block) if block else 0


def get_init(room_id):
    st = db.q1("SELECT initiative FROM room_state WHERE room_id=?", (room_id,))
    init = db.j((st or {}).get("initiative"), {"combat": False, "order": [], "active": -1, "round": 0}) \
        or {"combat": False, "order": [], "active": -1, "round": 0}
    if "round" not in init:                     # pre-round saves default sensibly
        init["round"] = 1 if init.get("combat") else 0
    return init


def set_init(room_id, init):
    db.x("UPDATE room_state SET initiative=? WHERE room_id=?", (json.dumps(init), room_id))


# ---------- turn state (D74: one turn = move + action + bonus + reaction) -----
# init["turn"] = {"token_id", "round", "move_total", "move_spent",
#                 "action", "bonus", "reaction"}  — slots are "available"/"used".
# Everything lives in the ONE initiative object; there is no second tracker.
# UNITS (D79): move_total/move_spent are in movecost UNITS (squares) — the very
# same unit in which route_cost/path_footprint_cost price routes and walk()
# charges steps. Storing feet here while charging squares made the budget 5x
# too generous; the SSOT conversion is movecost.walk_budget().

def token_speed_ft(tok):
    from .movement import _walk_speed          # local: movement imports this module
    return _walk_speed(tok)


def begin_turn(init):
    """(Re)set the per-turn resource state for the currently active token."""
    order = init.get("order") or []
    idx = int(init.get("active", -1))
    if not init.get("combat") or not (0 <= idx < len(order)):
        init["turn"] = None
        return init
    tid = order[idx]["token_id"]
    tok = db.q1("SELECT * FROM tokens WHERE id=?", (tid,))
    speed = token_speed_ft(tok) if tok else 30
    init["turn"] = {"token_id": tid, "round": int(init.get("round", 1)),
                    "move_total": movecost.walk_budget(speed), "move_spent": 0,
                    "action": "available", "bonus": "available", "reaction": "available"}
    return init


def advance(init):
    """Move to the next turn; wrapping the order starts a new round.
    Returns True when the round incremented."""
    wrapped = False
    init["active"] = (int(init["active"]) + 1) % len(init["order"])
    if init["active"] == 0:
        init["round"] = int(init.get("round", 1)) + 1
        wrapped = True
    return begin_turn(init), wrapped


def advance_turn(room_id, init):
    """The ONE turn lifecycle (D80) — every turn advance goes through here:

      1. TURN END hooks of the token whose turn just ends (its "end"-anchored
         conditions tick),
      2. initiative advance (existing order/round logic),
      3. round clock on wrap (round-only conditions, once per round),
      4. TURN START hooks of the newly active token ("start"-anchored tick;
         "until start of my turn" with rounds=1 is gone exactly there),
      5. fresh turn resources for the new active token (begin_turn).

    Returns ``(init, wrapped, cond_updates)`` with cond_updates a list of
    ``(token_id, conds)`` for the caller to broadcast."""
    updates = []
    upd = _tick_turn_conditions(room_id, turn_token(init), "end")
    if upd:
        updates.append(upd)
    init, wrapped = advance(init)
    if wrapped:
        updates.extend(step_conditions(room_id))
    upd = _tick_turn_conditions(room_id, turn_token(init), "start")
    if upd:
        updates.append(upd)
    return init, wrapped, updates


def first_turn_hooks(room_id, init):
    """TURN START hooks for the token that begins combat (round 1 has no
    previous turn to advance through advance_turn). Returns cond_updates."""
    upd = _tick_turn_conditions(room_id, turn_token(init), "start")
    return [upd] if upd else []


def is_listed(init, token_id):
    return init.get("combat") and any(o["token_id"] == token_id for o in init.get("order", []))


def turn_token(init):
    return (init.get("turn") or {}).get("token_id")


def move_remaining(init, token_id):
    """Movement units (squares) this token may still spend under the action
    economy, or None when the economy does not apply (no combat / token not in
    the order)."""
    if not is_listed(init, token_id):
        return None
    t = init.get("turn") or {}
    if t.get("token_id") != token_id:
        return 0
    return max(0, int(t["move_total"]) - int(t["move_spent"]))


def spend_move(room_id, token_id, units):
    """Charge walked movecost UNITS to the active turn (same unit walk()
    validated with). No-op when the turn has moved on (or DM walk)."""
    init = get_init(room_id)
    t = init.get("turn") or {}
    if t.get("token_id") != token_id:
        return None                      # turn moved on (or DM walk): nothing to charge
    t["move_spent"] = int(t["move_spent"]) + int(units)
    set_init(room_id, init)
    return init


def spend_slot(room_id, token_id, slot):
    """Mark action/bonus/reaction used. No-op outside that token's own turn."""
    init = get_init(room_id)
    t = init.get("turn") or {}
    if slot not in ("action", "bonus", "reaction") or t.get("token_id") != token_id:
        return None
    t[slot] = "used"
    set_init(room_id, init)
    return init


async def handle_init_start(ws, room_id, user, is_dm, msg):
    if not is_dm:
        return
    order = []
    for tok in db.q("SELECT * FROM tokens WHERE room_id=? ORDER BY id", (room_id,)):
        mod = token_dex_mod(tok)
        roll = random.randint(1, 20)
        order.append({"token_id": tok["id"], "label": tok["label"], "color": tok["color"],
                      "mod": mod, "roll": roll, "total": roll + mod})
    order.sort(key=lambda o: o["total"], reverse=True)
    init = {"combat": True, "round": 1, "order": order, "active": 0}
    begin_turn(init)
    for token_id, conds in first_turn_hooks(room_id, init):
        await broadcast(room_id, "cond", {"token_id": token_id, "conds": conds})
    set_init(room_id, init)
    sys_msg(room_id, "Combat started! — Round 1")
    await broadcast(room_id, "initiative", init)


async def handle_init_next(ws, room_id, user, is_dm, msg):
    if not is_dm:
        return
    init = get_init(room_id)
    if init["combat"] and init["order"]:
        init, wrapped, updates = advance_turn(room_id, init)
        for token_id, conds in updates:
            await broadcast(room_id, "cond", {"token_id": token_id, "conds": conds})
        if wrapped:
            sys_msg(room_id, f"— Round {init['round']} —")
        set_init(room_id, init)
        await broadcast(room_id, "initiative", init)


async def _end_turn_common(ws, room_id, user, is_dm):
    """Shared by init_next-style advance and the End Turn button."""
    init = get_init(room_id)
    if not init["combat"] or not init["order"]:
        await send_to(ws, "error", {"msg": "No combat running"})
        return
    turn = init.get("turn") or {}
    if not is_dm:
        tok = db.q1("SELECT owner_user_id FROM tokens WHERE id=? AND room_id=?",
                    (turn.get("token_id", -1), room_id))
        if tok is None or tok["owner_user_id"] != user["id"]:
            await send_to(ws, "error", {"msg": "Only the active token's owner (or the DM) can end the turn"})
            return
    init, wrapped, updates = advance_turn(room_id, init)
    for token_id, conds in updates:
        await broadcast(room_id, "cond", {"token_id": token_id, "conds": conds})
    if wrapped:
        sys_msg(room_id, f"— Round {init['round']} —")
    set_init(room_id, init)
    await broadcast(room_id, "initiative", init)


async def handle_end_turn(ws, room_id, user, is_dm, msg):
    await _end_turn_common(ws, room_id, user, is_dm)


async def handle_init_end_round(ws, room_id, user, is_dm, msg):
    """DM ends the current round: increment the round counter and return to the
    top of the (still fixed) initiative order. Initiative is rolled once per
    combat (D22), not re-rolled here."""
    if not is_dm:
        return
    init = get_init(room_id)
    if not init["combat"] or not init["order"]:
        return
    updates = []
    upd = _tick_turn_conditions(room_id, turn_token(init), "end")
    if upd:
        updates.append(upd)
    init["round"] = int(init.get("round", 1)) + 1
    init["active"] = 0
    begin_turn(init)
    updates.extend(step_conditions(room_id))
    updates.extend(first_turn_hooks(room_id, init))
    set_init(room_id, init)
    for token_id, conds in updates:
        await broadcast(room_id, "cond", {"token_id": token_id, "conds": conds})
    sys_msg(room_id, f"— Round {init['round']} —")
    await broadcast(room_id, "initiative", init)


async def handle_init_end(ws, room_id, user, is_dm, msg):
    if not is_dm:
        return
    init = {"combat": False, "order": [], "active": -1, "round": 0, "turn": None}
    set_init(room_id, init)
    sys_msg(room_id, "Combat ended.")
    await broadcast(room_id, "initiative", init)


async def handle_dash(ws, room_id, user, is_dm, msg):
    """Dash: spend the ACTION to gain this turn's speed again as movement
    (generic tabletop rule, D74/D79). Strict: only the token whose turn it is;
    a spent Action can never dash a second time. Never modifies the creature's
    stored speed — the bonus is this turn's move_total only."""
    tok = db.q1("SELECT * FROM tokens WHERE id=? AND room_id=?", (msg.get("token_id", -1), room_id))
    if tok is None:
        return
    if not (is_dm or tok["owner_user_id"] == user["id"]):
        await send_to(ws, "error", {"msg": "You can only dash with your own token"})
        return
    init = get_init(room_id)
    if not init["combat"]:
        await send_to(ws, "error", {"msg": "Dash needs combat (turn-based movement)"})
        return
    turn = init.get("turn") or {}
    if turn.get("token_id") != tok["id"]:
        await send_to(ws, "error", {"msg": "It is not your turn"})
        return
    if turn.get("action") == "used":
        await send_to(ws, "error", {"msg": "No action left this turn"})
        return
    turn["action"] = "used"
    turn["move_total"] = int(turn["move_total"]) + movecost.walk_budget(token_speed_ft(tok))
    init["turn"] = turn
    set_init(room_id, init)
    sys_msg(room_id, f"{tok['label']} dashes.")
    await broadcast(room_id, "initiative", init)


async def handle_turn_mark(ws, room_id, user, is_dm, msg):
    """Table bookkeeping: mark action/bonus/reaction available|used on the
    ACTIVE turn — by the DM or that token's owner."""
    try:
        tid = int(msg.get("token_id", -1))
    except (TypeError, ValueError):
        return
    slot = str(msg.get("slot", ""))
    value = str(msg.get("value", ""))
    if slot not in ("action", "bonus", "reaction") or value not in ("available", "used"):
        return
    init = get_init(room_id)
    turn = init.get("turn") or {}
    if turn.get("token_id") != tid:
        await send_to(ws, "error", {"msg": "Slots can only be marked on the active turn"})
        return
    if not is_dm:
        tok = db.q1("SELECT owner_user_id FROM tokens WHERE id=? AND room_id=?", (tid, room_id))
        if tok is None or tok["owner_user_id"] != user["id"]:
            await send_to(ws, "error", {"msg": "Not your token"})
            return
    turn[slot] = value
    init["turn"] = turn
    set_init(room_id, init)
    await broadcast(room_id, "initiative", init)


async def handle_hp(ws, room_id, user, is_dm, msg):
    if not is_dm:
        return
    tok = db.q1("SELECT * FROM tokens WHERE id=? AND room_id=?", (msg.get("token_id", -1), room_id))
    if tok is None:
        return
    try:
        delta = max(-9999, min(9999, int(msg.get("delta", 0))))
    except (TypeError, ValueError):
        return
    dtype = str(msg.get("damage_type", "")).strip().lower() or None
    res = await health.change_hp(room_id, tok, delta, crit=bool(msg.get("crit")),
                                 damage_type=dtype, broadcast_change=False)
    if res is None:
        return
    if delta < 0 and res.get("immune"):
        sys_msg(room_id, f"{res['name']} takes no {dtype or 'damage'} damage.")
        await broadcast(room_id, "snapshot", None)
        return
    if not res.get("changed"):
        return
    if delta < 0:
        verb, amount = "takes", res["damage"]
    else:
        verb, amount = "heals", res["healed"]
    sys_msg(room_id, f"{res['name']} {verb} {amount} → {res['hp']}/{res['max_hp']} HP{res.get('note', '')}")
    await broadcast(room_id, "snapshot", None)
