"""Inventory / items: use, attune, DM identify + recharge."""
import json

from .. import db, gear
from . import death as D
from .dice import do_roll
from .net import broadcast, send_to, send_user, sys_msg


async def handle_use_item(ws, room_id, user, is_dm, msg):
    tok = db.q1("SELECT * FROM tokens WHERE id=? AND room_id=?", (msg.get("token_id", -1), room_id))
    if tok is None or tok["character_id"] is None:
        return
    if not (is_dm or tok["owner_user_id"] == user["id"]):
        await send_to(ws, "error", {"msg": "Not your character"})
        return
    ch = gear.as_sheet(db.q1("SELECT * FROM characters WHERE id=?", (tok["character_id"],)))
    items = gear.clean_items(db.j(ch["items"], []))
    it = next((i for i in items if i["id"] == msg.get("item_id")), None)
    if it is None:
        await send_to(ws, "error", {"msg": "Item not found"})
        return
    if it["magic"] and not it["identified"] and not is_dm:
        await send_user(room_id, user["id"], "whisper", {"text": "✨ You don't know what this item does yet."})
        return
    if not it["heal"]:
        await send_to(ws, "error", {"msg": f"{it['name']} isn't usable"})
        return
    if it["charges"] == 0:
        await send_user(room_id, user["id"], "whisper", {"text": f"{it['name']} is depleted."})
        return
    res = do_roll(it["heal"], None)
    healed = res["total"] if res else 0
    hp = min(ch["max_hp"], ch["hp"] + healed)
    death = D.load(tok)
    if it["charges"] > 0:
        it["charges"] -= 1
        # Single UPDATE so HP and charge decrement are atomic (never one without the other).
        with db.tx() as c:
            c.execute("UPDATE characters SET hp=?, temp_hp=?, items=? WHERE id=?",
                      (hp, ch.get("temp_hp") or 0, json.dumps(items), ch["id"]))
            if hp > 0 and death is not None:
                c.execute("UPDATE tokens SET death=NULL WHERE id=?", (tok["id"],))
    else:
        with db.tx() as c:
            c.execute("UPDATE characters SET hp=?, temp_hp=? WHERE id=?",
                      (hp, ch.get("temp_hp") or 0, ch["id"]))
            if hp > 0 and death is not None:
                c.execute("UPDATE tokens SET death=NULL WHERE id=?", (tok["id"],))
    sys_msg(room_id, f"{ch['name']} uses {it['name']}.")
    extra = " (depleted)" if it["charges"] == 0 and it["chargesMax"] >= 0 else ""
    await send_user(room_id, ch["user_id"], "whisper",
                    {"text": f"🧪 {it['name']}: {it['heal']} = +{healed} → {hp}/{ch['max_hp']} HP{extra}"})
    await broadcast(room_id, "snapshot", None)


async def handle_attune(ws, room_id, user, is_dm, msg):
    ch = db.q1("SELECT * FROM characters WHERE id=?", (msg.get("char_id", -1),))
    if ch is None or not (is_dm or ch["user_id"] == user["id"]):
        return
    items = gear.clean_items(db.j(ch["items"], []))
    it = next((i for i in items if i["id"] == msg.get("item_id")), None)
    if it is None or not it["attunable"]:
        return
    if it["attuned"]:
        it["attuned"] = False
    elif gear.attuned_count(items) >= gear.ATUNE_MAX:
        await send_user(room_id, user["id"], "whisper",
                        {"text": f"⚠ You can be attuned to at most {gear.ATUNE_MAX} items."})
        return
    else:
        it["attuned"] = True
    db.x("UPDATE characters SET items=? WHERE id=?", (json.dumps(items), ch["id"]))
    await broadcast(room_id, "snapshot", None)


async def handle_identify(ws, room_id, user, is_dm, msg):
    if not is_dm:
        return
    ch = db.q1("SELECT * FROM characters WHERE id=?", (msg.get("char_id", -1),))
    if ch is None:
        return
    items = gear.clean_items(db.j(ch["items"], []))
    it = next((i for i in items if i["id"] == msg.get("item_id")), None)
    if it is None:
        return
    it["identified"] = True
    db.x("UPDATE characters SET items=? WHERE id=?", (json.dumps(items), ch["id"]))
    await send_user(room_id, ch["user_id"], "whisper",
                    {"text": f"🔍 The DM identifies {ch['name']}'s item as: {it['name']} — {it['desc'] or 'no known properties'}"})
    await broadcast(room_id, "snapshot", None)


async def handle_recharge(ws, room_id, user, is_dm, msg):
    if not is_dm:
        return
    ch = db.q1("SELECT * FROM characters WHERE id=?", (msg.get("char_id", -1),))
    if ch is None:
        return
    items = gear.clean_items(db.j(ch["items"], []))
    it = next((i for i in items if i["id"] == msg.get("item_id")), None)
    if it is None or not it["recharge"]:
        return
    it["charges"] = it["chargesMax"]
    db.x("UPDATE characters SET items=? WHERE id=?", (json.dumps(items), ch["id"]))
    sys_msg(room_id, f"{it['name']} recharges (long rest).")
    await broadcast(room_id, "snapshot", None)
