"""Hidden traps and loot, triggered by stepping onto a cell."""
import random

from .. import db
from .dice import dex_mod, do_roll
from .net import broadcast, send_user, sys_msg


def at_cell(items, cx, cy):
    return next((e for e in items if e["x"] == cx and e["y"] == cy), None)


async def hit_trap(room_id, tok, trap):
    trap["discovered"] = True
    owner = tok["owner_user_id"]
    dm = db.q1("SELECT dm_id FROM rooms WHERE id=?", (room_id,))
    ch = db.q1("SELECT * FROM characters WHERE id=?", (tok["character_id"],)) if tok["character_id"] else None
    if ch and owner:
        mod = dex_mod(ch["id"])
        roll = random.randint(1, 20)
        tot = roll + mod
        sys_msg(room_id, f"⚠ {ch['name']} triggered a trap!")
        if tot >= trap["dc"]:
            detail = f"🕯 {trap['label']} DC{trap['dc']}: save {roll}+{mod} = {tot} → succeeded!"
        else:
            res = do_roll(trap["dmg"], None)
            dmg = res["total"] if res else 1
            hp = max(0, ch["hp"] - dmg)
            db.x("UPDATE characters SET hp=? WHERE id=?", (hp, ch["id"]))
            detail = (f"🕯 {trap['label']} DC{trap['dc']}: save {roll}+{mod} = {tot} → failed! "
                      f"{trap['dmg']} = {dmg} damage → {hp}/{ch['max_hp']} HP")
            sys_msg(room_id, f"{ch['name']} takes {dmg} damage")
            await broadcast(room_id, "snapshot", None)
        for uid in {owner, dm["dm_id"]}:
            await send_user(room_id, uid, "whisper", {"text": detail})
    else:
        await send_user(room_id, dm["dm_id"], "whisper",
                        {"text": f"🕯 NPC '{tok['label']}' triggered {trap['label']} "
                                 f"(DC{trap['dc']}, {trap['dmg']} dmg) — no damage auto-applied"})


async def take_loot(room_id, tok, loot) -> bool:
    owner = tok["owner_user_id"]
    ch = db.q1("SELECT * FROM characters WHERE id=?", (tok["character_id"],)) if tok["character_id"] else None
    if not owner or ch is None:
        return False
    loot["taken_by"] = owner
    note = ("[loot] " + loot["label"])
    db.x("UPDATE characters SET notes=? WHERE id=?",
         ((ch["notes"] + "\n" + note) if ch["notes"] else note, ch["id"]))
    await send_user(room_id, owner, "whisper",
                    {"text": f"🎁 You found: {loot['label']} — added to {ch['name']}'s notes"})
    return True
