"""Server-authoritative dice: expression parsing, sheet-aware checks/saves/attacks/damage."""
import random
import re

from .. import db, gear, npc
from . import gamelog
from .net import broadcast, send_to, sys_msg

ROLL_RE = re.compile(r"^(\d*)d(\d+)([+-]\d+)?(?:(kh|kl)(\d+))?$", re.I)
ROLL_RE_KEEP_FIRST = re.compile(r"^(\d*)d(\d+)(?:(kh|kl)(\d+))?([+-]\d+)?$", re.I)
ABILITIES = ("str", "dex", "con", "int", "wis", "cha")


def _parse_dice(expr: str):
    if not expr or len(expr) > 24:
        return None
    s = str(expr).strip().lower().replace(" ", "")
    m = ROLL_RE.match(s)
    if m:
        n_s, sides_s, mod_s, keep, keep_s = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
    else:
        m = ROLL_RE_KEEP_FIRST.match(s)
        if not m:
            return None
        n_s, sides_s, keep, keep_s, mod_s = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
    n = max(1, min(100, int(n_s or 1)))
    sides = max(1, min(1000, int(sides_s)))
    mod = max(-500, min(500, int(mod_s or 0)))
    keep_n = max(1, min(n, int(keep_s))) if keep else 0
    return {"n": n, "sides": sides, "mod": mod, "keep": keep, "keep_n": keep_n}


def parse_roll(expr: str):
    p = _parse_dice(expr)
    if not p:
        return None
    return p["n"], p["sides"], p["mod"]


def do_roll(expr: str, adv: str | None):
    p = _parse_dice(expr)
    if not p:
        return None
    n, sides, mod = p["n"], p["sides"], p["mod"]
    keep, keep_n = p["keep"], p["keep_n"]
    if keep:
        rolls = [random.randint(1, sides) for _ in range(n)]
        kept_rolls = sorted(rolls, reverse=(keep == "kh"))[:keep_n]
        kept = sum(kept_rolls)
        return {"expr": expr.strip().lower().replace(" ", ""), "rolls": rolls,
                "kept": kept, "kept_rolls": kept_rolls, "mod": mod, "total": kept + mod,
                "adv": adv if adv in ("adv", "dis") else None, "keep": keep}
    if adv in ("adv", "dis") and n == 1 and sides == 20:
        rolls = [random.randint(1, 20), random.randint(1, 20)]
        keep = max if adv == "adv" else min
        total = keep(rolls) + mod
        return {"expr": expr, "rolls": rolls, "kept": keep(rolls), "mod": mod,
                "total": total, "adv": adv}
    rolls = [random.randint(1, sides) for _ in range(n)]
    return {"expr": expr, "rolls": rolls, "kept": sum(rolls), "mod": mod,
            "total": sum(rolls) + mod, "adv": None}


def _load_death(tok):
    d = db.j(tok.get("death"), None) if tok else None
    return d if isinstance(d, dict) else None


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


async def dice_post(room_id, user, text, total, *, visibility="public", meta=None, is_dm=None):
    return await gamelog.post_message(room_id, user, text, total=total, visibility=visibility,
                                      kind="dice", is_dm=is_dm, meta=meta)


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


# ---------- NPC / enemy rolls (DM-authorized, token-keyed) ----------

def _npc_target(room_id, user, is_dm, msg):
    """Return (tok, block) when msg references a DM-owned monster token, else (None, None)."""
    if not is_dm or msg.get("token_id") is None:
        return None, None
    tok = db.q1("SELECT * FROM tokens WHERE id=? AND room_id=?", (msg["token_id"], room_id))
    if tok is None or tok["owner_user_id"] is not None or tok["character_id"] is not None:
        return None, None
    block = npc.load(tok)
    return (tok, block) if block else (None, None)


async def _npc_roll(ws, room_id, user, tok, block, kind, msg):
    adv = msg.get("adv")
    label = tok["label"]
    nchar = npc.to_char(block, label)
    if kind in ("check", "save"):
        ab = str(msg.get("ability", "")).lower()
        if ab not in ABILITIES:
            await send_to(ws, "error", {"msg": "Unknown ability"})
            return
        saves = gear.clean_saves(block.get("saves"))
        if kind == "save":
            mod = gear.save_bonus(nchar, saves, ab)
        else:
            mod = npc.stat_mod(block, ab) + (gear.prof_bonus(nchar) if bool(msg.get("prof")) else 0)
        res = do_roll("1d20", adv)
        total = res["kept"] + mod
        word = "save" if kind == "save" else "check"
        advtxt = {"adv": " adv", "dis": " dis"}.get(res["adv"] or "", "")
        rolltxt = (f"[{','.join(map(str, res['rolls']))}]→{res['kept']}"
                   if res["adv"] else str(res["rolls"][0]))
        text = f"🎲 {label} — {ab.upper()} {word}{advtxt}: {rolltxt} {mod:+d} = {total}"
        await dice_post(room_id, user, text, total, is_dm=True)
        return
    if kind in ("spell_attack", "spell_dc", "spell_damage"):
        sp = next((x for x in block["spells"] if x.get("id") == msg.get("spell_id")), None)
        if sp is None:
            await send_to(ws, "error", {"msg": "Spell not found on this NPC"})
            return
        if kind == "spell_attack":
            out = _spell_attack_text(nchar, sp, adv)
        elif kind == "spell_dc":
            out = _spell_dc_text(nchar, sp)
        else:
            out = _spell_damage_text(nchar, sp, bool(msg.get("crit")))
        if out is None:
            await send_to(ws, "error", {"msg": "Spell has no valid damage dice"})
            return
        await dice_post(room_id, user, out[0], out[1])
        return
    await send_to(ws, "error", {"msg": "This action isn't available for an NPC"})


async def _npc_cast(ws, room_id, user, tok, block, msg):
    nchar = npc.to_char(block, tok["label"])
    sp = next((x for x in block["spells"] if x.get("id") == msg.get("spell_id")), None)
    if sp is None:
        await send_to(ws, "error", {"msg": "Spell not found on this NPC"})
        return
    lvl = int(sp.get("level", 0))
    if lvl > 0:
        slots = gear.clean_slots(block.get("spell_slots", {}))
        s = slots.get(lvl, {"max": 0, "used": 0})
        if s["used"] >= s["max"]:
            await send_to(ws, "error", {"msg": f"No {lvl}-level spell slots left"})
            return
        s["used"] += 1
        block["spell_slots"] = slots
        db.x("UPDATE tokens SET npc=? WHERE id=?", (db.json_dumps(block), tok["id"]))
        await broadcast(room_id, "snapshot", None)
    crit = bool(msg.get("crit"))
    posts = []
    if sp["cast"] == "attack":
        posts.append(_spell_attack_text(nchar, sp, msg.get("adv")))
    elif sp["cast"] == "save":
        posts.append(_spell_dc_text(nchar, sp))
    if sp["dmg"]:
        d = _spell_damage_text(nchar, sp, crit)
        if d:
            posts.append(d)
    if not posts:
        posts.append((f"✨ {tok['label']} casts {sp['name']}.", 0))
    for text, total in posts:
        await dice_post(room_id, user, text, total)


# ---------- NPC / monster attacks (DM-authorized, token-keyed) ----------

def _attack_by_id(block, msg):
    atks = block.get("attacks", []) or []
    aid = msg.get("attack")
    for a in atks:
        if a.get("id") == aid:
            return a
    try:
        i = int(aid)
    except (TypeError, ValueError):
        i = -1
    return atks[i] if 0 <= i < len(atks) else (atks[0] if atks else None)


COVER_BONUS = {"half": 2, "three_quarters": 5}


def _cover_bonus(value):
    return COVER_BONUS.get(str(value or "").lower(), 0)


def _target_ac(room_id, target_id):
    """Effective AC of a target token: a character's computed AC, else an NPC's AC."""
    t = db.q1("SELECT * FROM tokens WHERE id=? AND room_id=?", (target_id, room_id))
    if t is None:
        return None, None
    if t["character_id"]:
        ch = db.q1("SELECT * FROM characters WHERE id=?", (t["character_id"],))
        if ch is None:
            return None, t["label"]
        ch["items"] = db.j(ch.get("items"), []) or []
        ch["stats"] = db.j(ch.get("stats"), {}) or {}
        return gear.compute_ac(ch), t["label"]
    blk = npc.load(t)
    return (blk.get("ac", 10) if blk else None), t["label"]


async def _roll_npc_damage(room_id, user, label, atk):
    res = do_roll(atk["dmg"], None) if atk.get("dmg") else None
    if res is None:
        return
    await dice_post(room_id, user,
                    f"💥 {label} — {atk['name']} damage: [{', '.join(map(str, res['rolls']))}]"
                    f"{res['mod']:+d} = {res['total']}", res["total"])


async def handle_npc_attack(ws, room_id, user, is_dm, msg):
    tok, block = _npc_target(room_id, user, is_dm, msg)
    if tok is None:
        return
    atk = _attack_by_id(block, msg)
    if atk is None:
        await send_to(ws, "error", {"msg": "This NPC has no attacks"})
        return
    label, mode = tok["label"], msg.get("mode", "attack")
    if mode == "dc":
        if atk.get("dc"):
            await dice_post(room_id, user, f"🗡 {label} — {atk['name']}: DC {atk['dc']} "
                                           f"({(atk.get('save') or '?').upper()} save)", atk["dc"])
        return
    if mode == "damage":
        await _roll_npc_damage(room_id, user, label, atk)
        return
    res = do_roll("1d20", msg.get("adv"))
    nat, to_hit, total = res["kept"], atk["to_hit"], res["kept"] + atk["to_hit"]
    advtxt = {"adv": " adv", "dis": " dis"}.get(res["adv"] or "", "")
    ac = tl = None
    if msg.get("target_id") is not None:
        ac, tl = _target_ac(room_id, msg.get("target_id"))
    crit, fumble = nat == 20, nat == 1
    if ac is not None:
        hit = crit or (not fumble and total >= ac)
        await dice_post(room_id, user, f"🗡 {label} — {atk['name']}{advtxt}: d20({nat}) "
                        f"{to_hit:+d} = {total} vs {tl} AC {ac} → "
                        + ("HIT" if hit else "MISS")
                        + (" — CRITICAL!" if crit else (" — fumble" if fumble else "")), total)
        if hit:
            await _roll_npc_damage(room_id, user, label, atk)
    else:
        await dice_post(room_id, user, f"🗡 {label} — {atk['name']}{advtxt}: "
                        f"d20({nat}) {to_hit:+d} = {total}", total)


async def handle_roll(ws, room_id, user, is_dm, msg):
    kind = msg.get("kind")
    adv = msg.get("adv")
    vis = msg.get("visibility")
    if kind in SKILL_KINDS and msg.get("token_id") is not None:
        tok, block = _npc_target(room_id, user, is_dm, msg)
        if tok is not None:
            await _npc_roll(ws, room_id, user, tok, block, kind, msg)
            return
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
            await dice_post(room_id, user, text, total, visibility=vis, is_dm=is_dm,
                            meta={"mode": res["adv"] or "normal", "expr": res["expr"],
                                  "request": f"🎲 {user['username']} requested a blind roll ({res['expr']})."})
            return
        text = (f"{user['username']} rolled {res['expr']}{label}: "
                f"[{', '.join(map(str, res['rolls']))}] {res['mod']:+d} = {res['total']}")
        await dice_post(room_id, user, text, res["total"], visibility=vis, is_dm=is_dm,
                        meta={"mode": res["adv"] or "normal", "expr": res["expr"],
                              "request": f"🎲 {user['username']} requested a blind roll ({res['expr']})."})
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
        if kind == "save":
            saves = gear.clean_saves(db.j(ch.get("saves"), {}))
            mod = gear.save_bonus(ch, saves, ab)
            prof = bool(saves.get(ab))
        else:
            mod = stat_mod(stats, ab) + (prof_bonus(ch["level"]) if bool(msg.get("prof")) else 0)
            prof = bool(msg.get("prof"))
        res = do_roll("1d20", adv)
        total = res["kept"] + mod
        word = "save" if kind == "save" else "check"
        advtxt = {"adv": " adv", "dis": " dis"}.get(res["adv"] or "", "")
        rolltxt = (f"[{','.join(map(str, res['rolls']))}]→{res['kept']}"
                   if res["adv"] else str(res["rolls"][0]))
        text = f"🎲 {ch['name']} — {ab.upper()} {word}{advtxt}: {rolltxt} {mod:+d} = {total}"
        await dice_post(room_id, user, text, total, visibility=vis, is_dm=is_dm,
                        meta={"mode": res["adv"] or "normal", "prof": prof})
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
        await dice_post(room_id, user, text, total, visibility=vis, is_dm=is_dm,
                        meta={"mode": res["adv"] or "normal"})
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
        await dice_post(room_id, user, res[0], res[1], visibility=vis, is_dm=is_dm)
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
        cover = str(msg.get("cover") or "").lower()
        if cover == "total":
            await dice_post(room_id, user, f"🛡 {ch['name']} — target is behind total cover and can't be targeted.",
                            None, visibility=vis, is_dm=is_dm, meta={"mode": "total-cover"})
            return
        cover_mod = _cover_bonus(cover)
        to_hit = stat_mod(stats, wab) + (prof_bonus(ch["level"]) if w.get("proficient") else 0) + bonus
        res = do_roll("1d20", adv)
        nat = res["kept"]
        crit = nat == 20
        total = nat + to_hit - cover_mod
        advtxt = {"adv": " adv", "dis": " dis"}.get(res["adv"] or "", "")
        covtxt = {"half": " vs half cover", "three_quarters": " vs 3/4 cover"}.get(cover, "")
        ovr = "→" + wab.upper() if wab != w["ability"] else ""
        text = (f"⚔️ {ch['name']} — {w['name']} attack{ovr}{advtxt}{covtxt}: d20({nat}) {to_hit:+d}"
                + (f" {-cover_mod:+d} cover" if cover_mod else "") + f" = {total}"
                + (" — CRITICAL!" if crit else ""))
        await dice_post(room_id, user, text, total, visibility=vis, is_dm=is_dm,
                        meta={"mode": res["adv"] or "normal", "cover": cover or "none"})
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
    await dice_post(room_id, user, text, total, visibility=vis, is_dm=is_dm,
                    meta={"mode": "crit" if crit else "normal"})


async def handle_cast(ws, room_id, user, is_dm, msg):
    """Cast a spell: consumes a slot (leveled spells), then rolls its effect(s)."""
    vis = msg.get("visibility")
    tok, block = _npc_target(room_id, user, is_dm, msg)
    if tok is not None:
        await _npc_cast(ws, room_id, user, tok, block, msg)
        return
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
        await dice_post(room_id, user, text, total, visibility=vis, is_dm=is_dm)


async def handle_long_rest(ws, room_id, user, is_dm, msg):
    if not is_dm:
        return
    clear_conditions = bool(msg.get("clear_conditions"))
    for m in db.q("SELECT user_id, character_id FROM room_members "
                  "WHERE room_id=? AND character_id IS NOT NULL", (room_id,)):
        ch = db.q1("SELECT * FROM characters WHERE id=?", (m["character_id"],))
        if ch is None:
            continue
        slots = gear.clean_slots(db.j(ch["spell_slots"], {}))
        items = gear.clean_items(db.j(ch["items"], []))
        resources = gear.clean_resources(db.j(ch.get("resources"), []))
        for lv in range(1, 10):
            slots[lv]["used"] = 0
        for it in items:
            if it["recharge"] == "long":
                it["charges"] = it["chargesMax"]
        for r in resources:
            if r["reset"] == "long":
                r["current"] = r["max"]
        tok = db.q1("SELECT * FROM tokens WHERE room_id=? AND character_id=?",
                    (room_id, m["character_id"]))
        death = _load_death(tok) if tok else None
        with db.tx() as c:
            c.execute(
                "UPDATE characters SET hp=max_hp, temp_hp=0, spell_slots=?, items=?, resources=?, "
                "hit_dice_spent=0 WHERE id=?",
                (db.json_dumps(slots), db.json_dumps(items), db.json_dumps(resources),
                 m["character_id"]))
            if death is not None:
                c.execute("UPDATE tokens SET death=NULL WHERE id=?", (tok["id"],))
    if clear_conditions:
        db.x("UPDATE tokens SET conds='[]' WHERE room_id=?", (room_id,))
    sys_msg(room_id, "🛌 The party takes a long rest — HP, spell slots, hit dice, long-rest "
                     "resources and rechargeable items restored."
                     + (" Conditions cleared." if clear_conditions else ""))
    await dice_post(room_id, user, "🛌 Long rest.", 0, is_dm=True)
    await broadcast(room_id, "snapshot", None)


async def handle_short_rest(ws, room_id, user, is_dm, msg):
    tok = db.q1("SELECT * FROM tokens WHERE id=? AND room_id=?", (msg.get("token_id", -1), room_id))
    if tok is None or tok["character_id"] is None:
        return
    if not is_dm:
        owner = roller_char(room_id, user["id"])
        if owner is None or owner["id"] != tok["character_id"]:
            return
    ch = db.q1("SELECT * FROM characters WHERE id=?", (tok["character_id"],))
    if ch is None:
        return
    try:
        count = max(0, min(gear.hit_dice_max(ch), int(msg.get("hit_dice_count", 0) or 0)))
    except (TypeError, ValueError):
        count = 0
    hd = gear.clean_hit_die(ch.get("hit_die", 8))
    avail = max(0, gear.hit_dice_max(ch) - max(0, min(gear.hit_dice_max(ch), int(ch.get("hit_dice_spent") or 0))))
    spend = min(count, avail)
    con_mod = (max(1, min(30, int((db.j(ch.get("stats"), {}) or {}).get("con", 10)))) - 10) // 2
    healed = 0
    rolltxt = ""
    if spend:
        res = do_roll(f"{spend}d{hd}", None)
        if res:
            healed = max(0, res["total"] + con_mod)
            rolltxt = f" spent {spend}d{hd} (CON {con_mod:+d}): {healed} HP"
    new_hp = min(ch["max_hp"], ch["hp"] + healed)
    resources = gear.clean_resources(db.j(ch.get("resources"), []))
    for r in resources:
        if r["reset"] == "short":
            r["current"] = r["max"]
    db.x("UPDATE characters SET hp=?, temp_hp=?, hit_dice_spent=?, resources=? WHERE id=?",
         (new_hp, ch.get("temp_hp") or 0,
          max(0, min(gear.hit_dice_max(ch), int(ch.get("hit_dice_spent") or 0))) + spend,
          db.json_dumps(resources), ch["id"]))
    if new_hp > 0 and _load_death(tok) is not None:
        db.x("UPDATE tokens SET death=NULL WHERE id=?", (tok["id"],))
    await dice_post(room_id, user, f"🛌 {ch['name']} short rest{rolltxt}.", healed,
                    visibility=msg.get("visibility"), is_dm=is_dm)
    await broadcast(room_id, "snapshot", None)


async def handle_resource(ws, room_id, user, is_dm, msg):
    tok = db.q1("SELECT * FROM tokens WHERE id=? AND room_id=?", (msg.get("token_id", -1), room_id))
    if tok is None or tok["character_id"] is None:
        return
    if not is_dm:
        owner = roller_char(room_id, user["id"])
        if owner is None or owner["id"] != tok["character_id"]:
            return
    ch = db.q1("SELECT * FROM characters WHERE id=?", (tok["character_id"],))
    if ch is None:
        return
    resources = gear.clean_resources(db.j(ch.get("resources"), []))
    rid = str(msg.get("resource_id", ""))
    target = next((r for r in resources if r["id"] == rid), None)
    if target is None:
        await send_to(ws, "error", {"msg": "Resource not found"})
        return
    action = str(msg.get("action", "inc")).lower()
    try:
        current = int(target["current"])
    except (TypeError, ValueError):
        current = target["max"]
    if action == "inc":
        target["current"] = min(target["max"], current + 1)
    elif action == "dec":
        target["current"] = max(0, current - 1)
    elif action == "set":
        try:
            target["current"] = max(0, min(target["max"], int(msg.get("value", current))))
        except (TypeError, ValueError):
            return
    else:
        return
    db.x("UPDATE characters SET resources=? WHERE id=?", (db.json_dumps(resources), ch["id"]))
    await broadcast(room_id, "snapshot", None)
