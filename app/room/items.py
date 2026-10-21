"""Inventory / items: use, attune, DM identify + recharge."""
import json

from .. import db, gear, inventory as INV
from . import death as D
from .dice import do_roll
from .net import broadcast, dm_whisper, send_to, send_user, sys_msg


def _consume(it, items):
    """D146 (SRD): a potion or scroll is GONE when its last dose is drunk —
    the empty vial does not squat in the pack forever. qty>1 spends one dose
    and the entry re-arms with a fresh one; the last entry is removed from
    the very list the caller persists. An entry that carries a curse always
    stays (a curse's trace may never evaporate silently, D106/D113).
    Returns the whisper suffix."""
    if it["charges"] != 0 or it["kind"] not in ("potion", "scroll"):
        return ""
    if isinstance(it.get("curse"), dict):
        return ""
    qty = int(it.get("qty", 1) or 1)
    if qty > 1:
        it["qty"] = qty - 1
        it["charges"] = it["chargesMax"]
        return f" ({it['qty']} left)"
    try:
        items.remove(it)
    except ValueError:
        return ""
    return " (consumed)"


async def handle_use_item(ws, room_id, user, is_dm, msg):
    tok = db.q1("SELECT * FROM tokens WHERE id=? AND room_id=?", (msg.get("token_id", -1), room_id))
    if tok is None or tok["character_id"] is None:
        return
    if not (is_dm or tok["owner_user_id"] == user["id"]):
        await send_to(ws, "error", {"msg": "Not your character"})
        return
    ch = gear.as_sheet(db.q1("SELECT * FROM characters WHERE id=?", (tok["character_id"],)))
    items = gear.clean_items(db.j(ch["items"], []), keep_curse=True)
    it = next((i for i in items if i["id"] == msg.get("item_id")), None)
    if it is None:
        await send_to(ws, "error", {"msg": "Item not found"})
        return
    if it["magic"] and not it["identified"] and not is_dm:
        await send_user(room_id, user["id"], "whisper", {"text": "✨ You don't know what this item does yet."})
        return
    if not it["heal"] and not (it.get("props") or {}).get("effects"):
        await send_to(ws, "error", {"msg": f"{it['name']} isn't usable"})
        return
    # D153: a vial without a charge counter holds exactly one sip — without
    # this normalization a charges==-1 potion took the unlimited branch and
    # never emptied, so content-pack potions were infinite.
    if it["kind"] in ("potion", "scroll") and it["charges"] < 0:
        it["charges"] = 1
    if it["charges"] == 0:
        await send_user(room_id, user["id"], "whisper", {"text": f"{it['name']} is depleted."})
        return
    res = do_roll(it["heal"], None)
    healed = res["total"] if res else 0
    hp = min(ch["max_hp"], ch["hp"] + healed)
    death = D.load(tok)
    # D93: op_id replay guard rides the write transaction — a re-sent use
    # heals once, never twice (and never heals without its charge debit).
    op_id = str(msg.get("op_id", ""))[:40]
    if it["charges"] > 0:
        it["charges"] -= 1
        consumed = _consume(it, items)              # D146: last dose is gone
        # Single UPDATE so HP and charge decrement are atomic (never one without the other).
        with db.tx() as c:
            if op_id and not INV._claim(c, op_id, room_id, "use_item", ch["id"]):
                return
            c.execute("UPDATE characters SET hp=?, temp_hp=?, items=? WHERE id=?",
                      (hp, ch.get("temp_hp") or 0, json.dumps(items), ch["id"]))
            if hp > 0 and death is not None:
                c.execute("UPDATE tokens SET death=NULL WHERE id=?", (tok["id"],))
    else:
        consumed = ""
        with db.tx() as c:
            if op_id and not INV._claim(c, op_id, room_id, "use_item", ch["id"]):
                return
            c.execute("UPDATE characters SET hp=?, temp_hp=? WHERE id=?",
                      (hp, ch.get("temp_hp") or 0, ch["id"]))
            if hp > 0 and death is not None:
                c.execute("UPDATE tokens SET death=NULL WHERE id=?", (tok["id"],))
    sys_msg(room_id, f"{ch['name']} uses {it['name']}.")
    extra = ((" (depleted)" if it["charges"] == 0 and it["chargesMax"] >= 0
              and it in items else "") + consumed)
    if it["heal"]:
        await send_user(room_id, ch["user_id"], "whisper",
                        {"text": f"🧪 {it['name']}: {it['heal']} = +{healed} → {hp}/{ch['max_hp']} HP{extra}"})
    effect_cell = (it.get("props") or {}).get("effects")
    if effect_cell:
        # D111: the SAME effect core; its replay claim rides a distinct id so
        # a re-sent op can neither heal twice nor fire twice.
        from .. import effectops
        try:
            ops = effectops.validate(
                effect_cell,
                duration_rounds=effectops.duration_rounds((it.get("props") or {}).get("duration")))
            ctx = effectops.make_ctx(room_id, caster=tok, target=tok, trigger="use",
                                     op_id=(str(msg.get("op_id", "")) + ":fx")[:40]
                                     if op_id else "")
            ctx["self"] = tok
            await effectops.run_ops(ops, ctx)
            for frag in ctx["log"]:
                await send_user(room_id, ch["user_id"], "whisper", {"text": f"✨ {frag}"})
        except effectops.EffectError as ex:
            await send_user(room_id, ch["user_id"], "whisper",
                            {"text": f"⚠️ {it['name']}: effect refused ({ex})"})
    cur = it.get("curse")
    if isinstance(cur, dict) and cur.get("active") \
            and str(cur.get("trigger", "")) == "use" and cur.get("effects"):
        # D113: an ACTIVE use-armed curse answers the same "use", through the one
        # effect core; the owner is never told (its fragment goes to the DM only).
        from .. import effectops
        fired = await effectops.fire(
            room_id, "use", token=tok, caster=tok, items=[it],
            round_uid=(str(op_id) + ":curse") if op_id else "")
        for ctx in fired:
            for frag in ctx["log"]:
                await dm_whisper(room_id, f"✨ {frag}")
    await broadcast(room_id, "snapshot", None)


async def handle_attune(ws, room_id, user, is_dm, msg):
    ch = db.q1("SELECT * FROM characters WHERE id=?", (msg.get("char_id", -1),))
    if ch is None or not (is_dm or ch["user_id"] == user["id"]):
        return
    items = gear.clean_items(db.j(ch["items"], []), keep_curse=True)
    it = next((i for i in items if i["id"] == msg.get("item_id")), None)
    if it is None or not it["attunable"]:
        return
    learned = False
    if it["attuned"]:
        it["attuned"] = False
    elif gear.attuned_count(items) >= gear.ATUNE_MAX:
        await send_user(room_id, user["id"], "whisper",
                        {"text": f"⚠ You can be attuned to at most {gear.ATUNE_MAX} items."})
        return
    else:
        it["attuned"] = True
        # D147 (DMG/SRD): an attunement is a short rest with the item — the
        # attuning creature LEARNS its properties as the bond settles. No
        # gate is needed for unidentified items; the rule answers the why.
        learned = bool(it["magic"]) and not it["identified"]
        if learned:
            it["identified"] = True
    db.x("UPDATE characters SET items=? WHERE id=?", (json.dumps(items), ch["id"]))
    if learned:
        await send_user(room_id, ch["user_id"], "whisper",
                        {"text": f"✨ As the attunement settles, you learn what "
                                 f"{it['name']} is: {it['desc'] or 'no written properties'}"})
    await broadcast(room_id, "snapshot", None)


async def handle_identify(ws, room_id, user, is_dm, msg):
    if not is_dm:                                   # D162-11: loud, safe refusal
        await send_to(ws, "error", {"msg": "DM only"})
        return
    ch = db.q1("SELECT * FROM characters WHERE id=?", (msg.get("char_id", -1),))
    if ch is None:
        return
    items = gear.clean_items(db.j(ch["items"], []), keep_curse=True)
    it = next((i for i in items if i["id"] == msg.get("item_id")), None)
    if it is None:
        return
    it["identified"] = True
    db.x("UPDATE characters SET items=? WHERE id=?", (json.dumps(items), ch["id"]))
    await send_user(room_id, ch["user_id"], "whisper",
                    {"text": f"🔍 The DM identifies {ch['name']}'s item as: {it['name']} — {it['desc'] or 'no known properties'}"})
    await broadcast(room_id, "snapshot", None)


async def handle_recharge(ws, room_id, user, is_dm, msg):
    if not is_dm:                                   # D162-11: loud, safe refusal
        await send_to(ws, "error", {"msg": "DM only"})
        return
    ch = db.q1("SELECT * FROM characters WHERE id=?", (msg.get("char_id", -1),))
    if ch is None:
        return
    items = gear.clean_items(db.j(ch["items"], []), keep_curse=True)
    it = next((i for i in items if i["id"] == msg.get("item_id")), None)
    if it is None or not it["recharge"]:
        return
    it["charges"] = it["chargesMax"]
    db.x("UPDATE characters SET items=? WHERE id=?", (json.dumps(items), ch["id"]))
    sys_msg(room_id, f"{it['name']} recharges (long rest).")
    await broadcast(room_id, "snapshot", None)
