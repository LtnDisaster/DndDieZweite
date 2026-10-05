"""Hidden traps and loot, triggered by stepping onto a cell."""
import random

from .. import db, events, npc
from . import health
from .dice import dex_mod, do_roll
from .net import broadcast, send_user, sys_msg


def at_cell(items, cx, cy):
    return next((e for e in items if e["x"] == cx and e["y"] == cy), None)


async def hit_trap(room_id, tok, trap):
    # One-shot lifecycle: the trap remains in the persistent map state marked
    # triggered+discovered; walk() will not spring it a second time, and map
    # edits preserve the flags (dispatch merge). Only a fresh trap entity
    # (delete + re-place in the editor) re-arms it.
    trap["triggered"] = True
    trap["triggered_by"] = tok.get("id")
    trap["discovered"] = True
    events.emit(events.make("trap_triggered", room_id=room_id, actor_id=tok.get("id"),
                            trap_label=trap.get("label"), dc=trap.get("dc"),
                            dmg=trap.get("dmg")))
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
            hp_res = await health.damage(room_id, tok, dmg, broadcast_change=False) or {}
            hp = hp_res.get("hp", max(0, ch["hp"] - dmg))
            max_hp = hp_res.get("max_hp", ch["max_hp"])
            note = hp_res.get("note", "")
            detail = (f"🕯 {trap['label']} DC{trap['dc']}: save {roll}+{mod} = {tot} → failed! "
                      f"{trap['dmg']} = {dmg} damage → {hp}/{max_hp} HP{note}")
            sys_msg(room_id, f"{ch['name']} takes {dmg} damage")
            await broadcast(room_id, "snapshot", None)
        for uid in {owner, dm["dm_id"]}:
            await send_user(room_id, uid, "whisper", {"text": detail})
        return True
    # NPC / enemy token: roll a DEX save from its stat block and apply damage there.
    block = npc.load(tok)
    if block is None:
        await send_user(room_id, dm["dm_id"], "whisper",
                        {"text": f"🕯 NPC '{tok['label']}' triggered {trap['label']} "
                                 f"(DC{trap['dc']}, {trap['dmg']} dmg) — no damage auto-applied"})
        return True
    mod = npc.dex_mod(block)
    roll = random.randint(1, 20)
    tot = roll + mod
    sys_msg(room_id, f"⚠ {tok['label']} triggered a trap!")
    if tot >= trap["dc"]:
        detail = (f"🕯 {trap['label']} DC{trap['dc']}: {tok['label']} save {roll}+{mod} "
                  f"= {tot} → succeeded!")
    else:
        res = do_roll(trap["dmg"], None)
        dmg = res["total"] if res else 1
        hp_res = await health.damage(room_id, tok, dmg, broadcast_change=False) or {}
        hp = hp_res.get("hp", max(0, block["hp"] - dmg))
        max_hp = hp_res.get("max_hp", block["max_hp"])
        block = hp_res.get("block", block)
        detail = (f"🕯 {trap['label']} DC{trap['dc']}: {tok['label']} save {roll}+{mod} "
                  f"= {tot} → failed! {trap['dmg']} = {dmg} damage → {hp}/{max_hp} HP")
        sys_msg(room_id, f"{tok['label']} takes {dmg} damage")
        await broadcast(room_id, "snapshot", None)
        await send_user(room_id, dm["dm_id"], "whisper", {"text": detail})
    return True


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
