"""Server-authoritative dice: expression parsing, sheet-aware checks/saves/attacks/damage."""
import random
import re

from .. import db, gear
from .net import broadcast, send_to, sys_msg

ROLL_RE = re.compile(r"^(\d*)d(\d+)([+-]\d+)?$")
ABILITIES = ("str", "dex", "con", "int", "wis", "cha")


def parse_roll(expr: str):
    m = ROLL_RE.match(expr.strip().lower().replace(" ", ""))
    if not m:
        return None
    n = min(int(m.group(1) or 1), 100)
    sides = min(int(m.group(2)), 1000)
    mod = max(-500, min(500, int(m.group(3) or 0)))
    return max(n, 1), sides, mod


def do_roll(expr: str, adv: str | None):
    parsed = parse_roll(expr)
    if not parsed:
        return None
    n, sides, mod = parsed
    if adv in ("adv", "dis") and n == 1 and sides == 20:
        rolls = [random.randint(1, 20), random.randint(1, 20)]
        keep = max if adv == "adv" else min
        total = keep(rolls) + mod
        return {"expr": expr, "rolls": rolls, "kept": keep(rolls), "mod": mod,
                "total": total, "adv": adv}
    rolls = [random.randint(1, sides) for _ in range(n)]
    return {"expr": expr, "rolls": rolls, "kept": sum(rolls), "mod": mod,
            "total": sum(rolls) + mod, "adv": None}


def dex_mod(character_id):
    if not character_id:
        return 0
    ch = db.q1("SELECT stats FROM characters WHERE id=?", (character_id,))
    dex = (db.j(ch["stats"], {}) or {}).get("dex", 10) if ch else 10
    try:
        return (int(dex) - 10) // 2
    except (TypeError, ValueError):
        return 0


def char_stats(ch):
    return (db.j(ch["stats"], {}) if ch else {}) or {}


def stat_mod(stats, ability):
    try:
        return (int(stats.get(ability, 10)) - 10) // 2
    except (TypeError, ValueError):
        return 0


def prof_bonus(level):
    return 2 + (max(1, int(level)) - 1) // 4


def roller_char(room_id, user_id):
    m = db.q1("SELECT character_id FROM room_members WHERE room_id=? AND user_id=?",
              (room_id, user_id))
    if m and m["character_id"]:
        return db.q1("SELECT * FROM characters WHERE id=?", (m["character_id"],))
    return None


async def dice_post(room_id, user, text, total):
    mid = db.x("INSERT INTO messages (room_id,user_id,type,body) VALUES (?,?,'dice',?)",
               (room_id, user["id"], text))
    await broadcast(room_id, "dice", {"id": mid, "username": user["username"],
                                      "text": text, "total": total})


SKILL_KINDS = ("check", "save", "attack", "damage", "skill",
               "spell_attack", "spell_damage", "spell_dc")


def _spell_attack_text(ch, sp, adv):
    atk = gear.spell_attack(ch, sp["ability"])
    res = do_roll("1d20", adv)
    nat = res["kept"]
    advtxt = {"adv": " adv", "dis": " dis"}.get(res["adv"] or "", "")
    text = (f"✨ {ch['name']} — {sp['name']} attack{advtxt}: d20({nat}) {atk:+d} = {nat + atk}"
            + (" — CRITICAL!" if nat == 20 else ""))
    return text, nat + atk


def _spell_dc_text(ch, sp):
    dc = gear.spell_save_dc(ch, sp["ability"])
    sv = (sp.get("save") or "?").upper()
    return f"✨ {ch['name']} — {sp['name']} save DC {dc} ({sp['ability'].upper()} vs {sv})", dc


def _spell_damage_text(ch, sp, crit):
    parsed = parse_roll(sp["dmg"])
    if parsed is None:
        return None
    n, sides, mod = parsed
    n = min(200, n * 2) if crit else n
    rolls = [random.randint(1, sides) for _ in range(n)]
    total = sum(rolls) + mod
    text = (f"💥 {ch['name']} — {sp['name']} damage{' (crit!)' if crit else ''}: "
            f"[{', '.join(map(str, rolls))}] {mod:+d} = {total}")
    return text, total


async def handle_roll(ws, room_id, user, is_dm, msg):
    kind = msg.get("kind")
    adv = msg.get("adv")
    if kind not in SKILL_KINDS:
        res = do_roll(str(msg.get("expr", "")), adv)
        if res is None:
            await send_to(ws, "error", {"msg": "Bad expression — try 1d20+5 or 2d6"})
            return
        label = {"adv": " (adv)", "dis": " (dis)"}.get(res["adv"] or "", "")
        ab = str(msg.get("ability", "")).lower()
        ch = roller_char(room_id, user["id"]) if ab in ABILITIES else None
        if ch is not None:
            mod = res["mod"] + stat_mod(char_stats(ch), ab) + (prof_bonus(ch["level"]) if bool(msg.get("prof")) else 0)
            total = res["kept"] + mod
            text = (f"🎲 {ch['name']} — {res['expr']} ({ab.upper()}"
                    f"{' prof' if msg.get('prof') else ''}){label}: "
                    f"[{', '.join(map(str, res['rolls']))}] {mod:+d} = {total}")
            await dice_post(room_id, user, text, total)
            return
        text = (f"{user['username']} rolled {res['expr']}{label}: "
                f"[{', '.join(map(str, res['rolls']))}] {res['mod']:+d} = {res['total']}")
        await dice_post(room_id, user, text, res["total"])
        return

    ch = roller_char(room_id, user["id"])
    if ch is None:
        await send_to(ws, "error", {"msg": "Bring a character to the table first"})
        return
    stats = char_stats(ch)

    if kind in ("check", "save"):
        ab = str(msg.get("ability", "")).lower()
        if ab not in ABILITIES:
            await send_to(ws, "error", {"msg": "Unknown ability"})
            return
        mod = stat_mod(stats, ab) + (prof_bonus(ch["level"]) if bool(msg.get("prof")) else 0)
        res = do_roll("1d20", adv)
        total = res["kept"] + mod
        word = "save" if kind == "save" else "check"
        advtxt = {"adv": " adv", "dis": " dis"}.get(res["adv"] or "", "")
        rolltxt = (f"[{','.join(map(str, res['rolls']))}]→{res['kept']}"
                   if res["adv"] else str(res["rolls"][0]))
        text = f"🎲 {ch['name']} — {ab.upper()} {word}{advtxt}: {rolltxt} {mod:+d} = {total}"
        await dice_post(room_id, user, text, total)
        return

    if kind == "skill":
        key = str(msg.get("skill", "")).lower()
        if key not in gear.SKILLS:
            await send_to(ws, "error", {"msg": "Unknown skill"})
            return
        bonus, prof = gear.skill_bonus(ch, db.j(ch["skills"], {}) or {}, key)
        res = do_roll("1d20", adv)
        total = res["kept"] + bonus
        advtxt = {"adv": " adv", "dis": " dis"}.get(res["adv"] or "", "")
        rolltxt = (f"[{','.join(map(str, res['rolls']))}]→{res['kept']}"
                   if res["adv"] else str(res["rolls"][0]))
        tag = " ★" if prof == 2 else (" ✓" if prof == 1 else "")
        text = (f"🎲 {ch['name']} — {gear.SKILLS[key][0]}{tag} check{advtxt}: "
                f"{rolltxt} {bonus:+d} = {total}")
        await dice_post(room_id, user, text, total)
        return

    if kind in ("spell_attack", "spell_damage", "spell_dc"):
        spells = db.j(ch["spells"], []) or []
        sp = next((x for x in spells if x.get("id") == msg.get("spell_id")), None)
        if sp is None:
            await send_to(ws, "error", {"msg": "Spell not found on this character"})
            return
        if kind == "spell_attack":
            res = _spell_attack_text(ch, sp, adv)
        elif kind == "spell_dc":
            res = _spell_dc_text(ch, sp)
        else:
            res = _spell_damage_text(ch, sp, bool(msg.get("crit")))
        if res is None:
            await send_to(ws, "error", {"msg": "Spell has no valid damage dice"})
            return
        await dice_post(room_id, user, res[0], res[1])
        return

    weapons = db.j(ch["weapons"], []) or []
    w = next((x for x in weapons if x.get("name") == msg.get("weapon")), None)
    if w is None:
        await send_to(ws, "error", {"msg": "Weapon not found on this character"})
        return
    bonus = int(w.get("dmgBonus", 0) or 0)
    ab = str(msg.get("ability", "")).lower()
    wab = ab if ab in ABILITIES else w["ability"]

    if kind == "attack":
        to_hit = stat_mod(stats, wab) + (prof_bonus(ch["level"]) if w.get("proficient") else 0) + bonus
        res = do_roll("1d20", adv)
        nat = res["kept"]
        crit = nat == 20
        total = nat + to_hit
        advtxt = {"adv": " adv", "dis": " dis"}.get(res["adv"] or "", "")
        ovr = "→" + wab.upper() if wab != w["ability"] else ""
        text = (f"⚔️ {ch['name']} — {w['name']} attack{ovr}{advtxt}: d20({nat}) {to_hit:+d} = {total}"
                + (" — CRITICAL!" if crit else ""))
        await dice_post(room_id, user, text, total)
        return

    parsed = parse_roll(w["dmg"])
    if parsed is None:
        await send_to(ws, "error", {"msg": "Weapon has no valid damage dice"})
        return
    crit = bool(msg.get("crit"))
    n, sides, mod = parsed
    n = min(200, n * 2) if crit else n
    rolls = [random.randint(1, sides) for _ in range(n)]
    mod += bonus
    total = sum(rolls) + mod
    text = (f"💥 {ch['name']} — {w['name']} damage{' (crit!)' if crit else ''}: "
            f"[{', '.join(map(str, rolls))}] {mod:+d} = {total}")
    await dice_post(room_id, user, text, total)


async def handle_cast(ws, room_id, user, is_dm, msg):
    """Cast a spell: consumes a slot (leveled spells), then rolls its effect(s)."""
    ch = roller_char(room_id, user["id"])
    if ch is None:
        await send_to(ws, "error", {"msg": "Bring a character to the table first"})
        return
    spells = db.j(ch["spells"], []) or []
    sp = next((x for x in spells if x.get("id") == msg.get("spell_id")), None)
    if sp is None:
        await send_to(ws, "error", {"msg": "Spell not found on this character"})
        return
    lvl = int(sp.get("level", 0))
    if lvl > 0:
        slots = gear.clean_slots(db.j(ch["spell_slots"], {}))
        s = slots.get(lvl, {"max": 0, "used": 0})
        if s["used"] >= s["max"]:
            await send_to(ws, "error", {"msg": f"No {lvl}-level spell slots left"})
            return
        s["used"] += 1
        db.x("UPDATE characters SET spell_slots=? WHERE id=?", (db.json_dumps(slots), ch["id"]))
        await broadcast(room_id, "snapshot", None)
    crit = bool(msg.get("crit"))
    posts = []
    if sp["cast"] == "attack":
        posts.append(_spell_attack_text(ch, sp, msg.get("adv")))
    elif sp["cast"] == "save":
        posts.append(_spell_dc_text(ch, sp))
    if sp["dmg"]:
        d = _spell_damage_text(ch, sp, crit)
        if d:
            posts.append(d)
    if not posts:
        posts.append((f"✨ {ch['name']} casts {sp['name']}.", 0))
    for text, total in posts:
        await dice_post(room_id, user, text, total)


async def handle_long_rest(ws, room_id, user, is_dm, msg):
    if not is_dm:
        return
    for m in db.q("SELECT character_id FROM room_members "
                  "WHERE room_id=? AND character_id IS NOT NULL", (room_id,)):
        ch = db.q1("SELECT spell_slots, items FROM characters WHERE id=?", (m["character_id"],))
        if ch is None:
            continue
        slots = gear.clean_slots(db.j(ch["spell_slots"], {}))
        items = gear.clean_items(db.j(ch["items"], []))
        changed = False
        for lv in range(1, 10):
            if slots[lv]["used"]:
                slots[lv]["used"] = 0
                changed = True
        for it in items:
            if it["recharge"] == "long" and it["charges"] < it["chargesMax"]:
                it["charges"] = it["chargesMax"]
                changed = True
        if changed:
            db.x("UPDATE characters SET spell_slots=?, items=? WHERE id=?",
                 (db.json_dumps(slots), db.json_dumps(items), m["character_id"]))
    sys_msg(room_id, "🛌 The party takes a long rest — spell slots and rechargeable items restored.")
    await broadcast(room_id, "snapshot", None)
