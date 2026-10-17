"""Server-authoritative dice: expression parsing, sheet-aware checks/saves/attacks/damage."""
import random
import re

from .. import charbuild, conditions as CND, content, db, gear, inventory as INV, npc
from . import authz, gamelog
from .net import broadcast, dm_whisper, send_to, sys_msg

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
    """DEX mod for initiative/trap saves — canonical derivation via as_sheet (D56/D70)."""
    if not character_id:
        return 0
    ch = db.q1("SELECT * FROM characters WHERE id=?", (character_id,))
    return gear.dex_mod(gear.as_sheet(ch)) if ch else 0


def char_stats(ch):
    return db.j((ch or {}).get("stats"), {}) or {}


def stat_mod(stats, ability):
    """Compatibility wrapper — delegates to the canonical derivation (D56/D70)."""
    return gear.stat_mod({"stats": stats if isinstance(stats, dict) else {}}, ability)


def roller_char(room_id, user_id):
    m = db.q1("SELECT character_id FROM room_members WHERE room_id=? AND user_id=?",
              (room_id, user_id))
    if m and m["character_id"]:
        # ONE choke point: every game-math consumer below must see a SHEET
        # (parsed JSON columns). Raw rows carrying JSON strings are how the
        # "stat modifier silently 0" bug reached saves/skills/spells (D70).
        return gear.as_sheet(db.q1("SELECT * FROM characters WHERE id=?", (m["character_id"],)))
    return None


async def dice_post(room_id, user, text, total, *, visibility="public", meta=None, is_dm=None):
    return await gamelog.post_message(room_id, user, text, total=total, visibility=visibility,
                                      kind="dice", is_dm=is_dm, meta=meta)


SKILL_KINDS = ("check", "save", "attack", "damage", "skill",
               "spell_attack", "spell_damage", "spell_dc")


def _spell_cover(msg):
    """D137 (audit A5): cover is a property of the TARGET and rides EVERY
    attack roll — item attacks had it, spell attacks are closing up."""
    cover = str(msg.get("cover") or "").lower()
    if cover == "total":
        return None                                   # caller refuses targeting
    return cover


async def _total_cover_note(room_id, user, is_dm, vis, ch):
    await dice_post(room_id, user, f"🛡 {ch['name']} — target is behind total "
                    "cover and can't be targeted.", None, visibility=vis, is_dm=is_dm,
                    meta={"mode": "total-cover"})


def _spell_attack_text(ch, sp, adv, cover=""):
    # AP-015: exhaustion rides spell attack rolls too (Attack Rolls, audit F4).
    atk = gear.spell_attack(ch, sp["ability"]) + gear.exhaustion_roll_mod(ch)
    cover_mod = _cover_bonus(cover)
    res = do_roll("1d20", adv)
    nat = res["kept"]
    advtxt = {"adv": " adv", "dis": " dis"}.get(res["adv"] or "", "")
    covtxt = {"half": " vs half cover", "three_quarters": " vs 3/4 cover"}.get(cover, "")
    text = (f"✨ {ch['name']} — {sp['name']} attack{advtxt}{covtxt}: "
            f"d20({nat}) {atk:+d}" + (f" {-cover_mod:+d} cover" if cover_mod else "")
            + f" = {nat + atk - cover_mod}"
            + (" — CRITICAL!" if nat == 20 else ""))
    return text, nat + atk - cover_mod


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
    mod += gear.exhaustion_roll_mod(ch)              # AP-015 (audit F4: Damage Rolls)
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
        # D111: standing condition hooks apply to NPC rolls too.
        conds = CND.load(tok)
        if kind == "save" and CND.auto_fails_save(conds, room_id, ab):
            await dice_post(room_id, user, f"🎲 {label} — {ab.upper()} save: "
                            f"AUTO-FAIL (condition)", 0, is_dm=True,
                            meta={"mode": "auto_fail", "ability": ab})
            return
        if CND.hook_bool(conds, room_id, "my_saves_dis" if kind == "save"
                         else "my_checks_dis"):
            adv = _combine_adv(adv, "dis")
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
            cover = _spell_cover(msg)
            if cover is None:
                await _total_cover_note(room_id, user, is_dm, msg.get("visibility"), nchar)
                return
            adv = await _consume_markers(room_id, tok, adv, None)   # D109 markers
            out = _spell_attack_text(nchar, sp, adv, cover)
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
    if sp["cast"] == "attack" and _spell_cover(msg) is None:
        # D137: total cover refuses the target BEFORE any slot is touched.
        await _total_cover_note(room_id, user, is_dm, msg.get("visibility"), nchar)
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
        posts.append(_spell_attack_text(nchar, sp, msg.get("adv"),
                                            _spell_cover(msg) or ""))
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
        ch = gear.as_sheet(db.q1("SELECT * FROM characters WHERE id=?", (t["character_id"],)))
        if ch is None:
            return None, t["label"]
        return gear.compute_ac(ch), t["label"]
    blk = npc.load(t)
    return (blk.get("ac", 10) if blk else None), t["label"]


def _vertical_range_distance(room_id, source, target):
    """Distance in feet along every legitimate plane relationship (D114).

    Shared BODY planes are physical presence. Otherwise an open shaft may expose
    the target on one of the attacker's body planes, in which case vertical depth
    counts. ``None`` means no mechanical attack/reach relationship exists.
    """
    from .. import vertical
    from .net import get_map as _get_map
    from . import vertical3d
    maps = vertical3d.maps_for(room_id)
    level_map = vertical3d.level_map(room_id)
    source_body = vertical3d.body_planes(room_id, source, maps, level_map)
    target_body = vertical3d.body_planes(room_id, target, maps, level_map)
    shared = sorted(source_body & target_body)
    shaft = []
    for plane in source_body:
        observed = vertical3d.observable_cells(room_id, target, plane, maps, level_map)
        if observed and plane not in shared:
            shaft.append((plane, observed))
    candidates = []
    for plane in shared:
        if maps.get(plane) is None and _get_map(room_id, plane) is None:
            continue
        candidates.append((0, vertical3d.body_cells(room_id, source, plane, maps, level_map),
                           vertical3d.body_cells(room_id, target, plane, maps, level_map)))
    for plane, observed in shaft:
        if maps.get(plane) is None and _get_map(room_id, plane) is None:
            continue
        vertical_delta = min(abs(vertical.floor_to_ft(level_map.get(plane, 0))
                                - vertical.floor_to_ft(level_map.get(other, 0)))
                             for other in target_body)
        candidates.append((vertical_delta,
                           vertical3d.body_cells(room_id, source, plane, maps, level_map),
                           observed))
    distance = None
    for vertical_delta, source_cells, target_cells in candidates:
        cell_distance = [max(abs(a[0] - t[0]), abs(a[1] - t[1]))
                         for a in source_cells for t in target_cells]
        candidate = max((max(cell_distance) * 5 if cell_distance else 0), vertical_delta)
        if distance is None or candidate < distance:
            distance = candidate
    return distance


def _roll_dmg(expr, bonus, crit):
    parsed = parse_roll(expr)
    if parsed is None:
        return None
    n, sides, mod = parsed
    n = min(200, n * 2) if crit else n
    rolls = [random.randint(1, sides) for _ in range(n)]
    mod += bonus
    return rolls, mod, sum(rolls) + mod


def _visible_to_member(user_id, room_id, tok):
    """D94: may a member even TARGET this token? Mirrors the /state token
    filter (rooms.py D82/D86/D72): same plane, fog sight, own/controlled
    always. D114 additionally admits a body protruding into, or an open
    shaft down to, a target. A hidden target must be indistinguishable from
    no target."""
    from .. import mapmodel
    from .. import ws as _ws
    from . import net as room_net
    from . import vertical3d
    if tok["owner_user_id"] == user_id or tok["controller_user_id"] == user_id:
        return True
    vmaps = vertical3d.maps_for(room_id)
    vlm = vertical3d.level_map(room_id)
    planes = set()
    for t in db.q("SELECT * FROM tokens WHERE room_id=?", (room_id,)):
        if t["owner_user_id"] == user_id or t.get("controller_user_id") == user_id:
            planes.update(vertical3d.body_planes(room_id, t, vmaps, vlm))
    for fl in planes:
        obs = vertical3d.observable_cells(room_id, tok, fl, vmaps, vlm)
        if not obs:
            continue
        mp = vmaps.get(fl) or room_net.get_map(room_id, fl)
        if mp is None:
            continue
        vis = _ws.viewer_visible_cells(room_id, user_id, mp, floor=fl)
        if any((i := mapmodel.flat_idx(mp, x, y)) is not None and i in vis
               for (x, y) in obs):
            return True
    return False


# ---------------------------------------------------------------------------
# D109 — weapon mastery seam (SRD 5.2.1 "Mastery Properties"). NO second
# engine: rolls run through do_roll, damage through _roll_dmg, forced movement
# through room.moveforced.apply_forced_move, Prone through room.conditions.
# knock_prone, saves through the ability engine's gear helpers. A mastery
# intent is fully validated BEFORE any die is touched; an effect only fires
# for an attack that (a) uses the weapon carrying the property, (b) belongs to
# a character whose build ledger unlocks it, and (c) opt-in asked for it.
MASTERIES_MARKER = ("sap", "slow", "vex")           # attacker-anchored clocks


def _combine_adv(base, force):
    """Advantage and disadvantage cancel each other — the SAME engine rule
    the long-range attack path already applies."""
    if force == "dis":
        return None if base == "adv" else "dis"
    if force == "adv":
        return None if base == "dis" else "adv"
    return base


async def _consume_markers(room_id, tok, adv, target_id=None):
    """SRD Sap: Disadvantage on the NEXT attack roll. SRD Vex: Advantage on
    the next attack roll AGAINST the marked target. Both are consumed on use;
    markers expiring is the combat turn hook's job (D80 lifecycle).
    D111: the SAME single point also applies the STANDING condition hooks —
    the attacker's my_attacks_dis and the target's attacks_against_me_adv/dis
    (catalog-driven, no key names hardwired here any more)."""
    from .visibility import send_cond_bump
    conds = CND.load(tok)
    if conds:
        conds, sap = CND.consume(conds, "sapped")
        vexed = None
        if target_id is not None:
            conds, vexed = CND.consume(conds, "vexed", ref=int(target_id))
        if sap is not None or vexed is not None:
            if sap is not None:
                adv = _combine_adv(adv, "dis")
            if vexed is not None:
                adv = _combine_adv(adv, "adv")
            payload = db.json_dumps(conds)
            db.x("UPDATE tokens SET conds=? WHERE id=?", (payload, tok["id"]))
            await send_cond_bump(room_id, {**tok, "conds": payload}, conds)
    if CND.hook_bool(conds, room_id, "my_attacks_dis"):
        adv = _combine_adv(adv, "dis")
    if target_id is not None:
        ttok = db.q1("SELECT * FROM tokens WHERE id=?", (target_id,))
        if ttok is not None:
            tc = CND.load(ttok)
            if CND.hook_bool(tc, room_id, "attacks_against_me_adv"):
                adv = _combine_adv(adv, "adv")
            if CND.hook_bool(tc, room_id, "attacks_against_me_dis"):
                adv = _combine_adv(adv, "dis")
    return adv


async def _set_marker(room_id, tok, key, rounds=0, until="", src=None, ref=None):
    """Set/refresh one marker (SRD Slow never stacks beyond -10 ft: the speed
    hook reads the key, not the entry count)."""
    from .visibility import send_cond_bump
    conds = CND.add(CND.load(tok), key, rounds, until, src=src, ref=ref)
    payload = db.json_dumps(conds)
    db.x("UPDATE tokens SET conds=? WHERE id=?", (payload, tok["id"]))
    await send_cond_bump(room_id, {**tok, "conds": payload}, conds)


def _token_size_ok_for_push(t_tok):
    """SRD Push: 'Large or smaller'. Characters are Medium (the engine carries
    no character token size — documented). NPCs: huge/gargantuan refuse."""
    if t_tok["character_id"]:
        return True
    blk = npc.load(t_tok)
    return (blk or {}).get("size", "Medium") not in ("Huge", "Gargantuan")


async def _item_attack(room_id, ws, user, is_dm, ch, msg, kind, adv, vis):
    """D93: attack with an EQUIPPED item. The profile (bonus/dice/range) is
    derived from server-side equipment+props (gear.weapon_profiles); the
    client claims an item_id and nothing else. AC verdict mirrors the NPC/
    ability engines; damage is ROLLED here but APPLIED by the DM through the
    existing hp flow — same table flow as npc_attack today. During an active
    initiative the attack consumes the attacker's action/bonus slot."""
    from . import combat as C                      # late import: combat imports dice
    item_id = str(msg.get("item_id", ""))[:16]
    op_id = str(msg.get("op_id", ""))[:40]

    # D94: the profile and the attacking token are RE-READ inside the claim
    # transaction — an interleaved unequip/remove can never make this attack
    # roll with a stale profile (select-then-execute was Sprint 23's hole).
    with db.tx() as c:
        row = c.execute("SELECT * FROM characters WHERE id=?", (ch["id"],)).fetchone()
        fresh = gear.as_sheet(dict(row) if row else None)
        prof = next((p for p in gear.weapon_profiles(fresh or ch)
                     if p["item_id"] == item_id), None)
        if prof is None:
            await send_to(ws, "error", {"msg": "No equipped weapon with attack properties on this character"})
            return
        tok = None
        if msg.get("token_id") is not None:
            row = c.execute("SELECT * FROM tokens WHERE id=? AND room_id=?",
                            (msg["token_id"], room_id)).fetchone()
            tok = dict(row) if row else None
            if tok is None or not authz.controls(tok, user["id"], is_dm) \
                    or tok["character_id"] != ch["id"]:
                await send_to(ws, "error", {"msg": "That token is not yours to attack with"})
                return
        if op_id and not INV._claim(c, op_id, room_id, "attack", ch["id"]):
            return

    init = C.get_init(room_id)
    slot = ("bonus" if str(msg.get("slot", "")) == "bonus"
            else "nick" if str(msg.get("slot", "")) == "nick" else "action")

    # ---- D109: mastery intent — EVERYTHING is validated before any die is
    # touched: property on the weapon, entitlement in the build ledger, mode
    # legality, initiative anchors, weapon hands, reach later. An invalid
    # intent refuses the request; it never rolls a "free" attack.
    want = str(msg.get("mastery") or "").strip().lower()
    if want not in ("", *content.MASTERIES):
        await send_to(ws, "error", {"msg": "Unknown mastery"})
        return
    if want and kind == "damage":
        await send_to(ws, "error", {"msg": "Masteries apply to attack rolls"})
        return
    nick_mode = slot == "nick"
    if nick_mode and want not in ("", "nick"):
        await send_to(ws, "error", {"msg": "A nick attack carries only the Nick mastery"})
        return
    if want and want != prof["mastery"]:
        await send_to(ws, "error", {"msg": f"This weapon has no {want} mastery"})
        return
    allowed = charbuild.allowed_masteries(fresh or ch)
    if (want and want not in allowed) or (nick_mode and "nick" not in allowed):
        await send_to(ws, "error", {"msg": "This character has no such mastery"})
        return
    listed = init.get("combat") and tok is not None and \
        any(o.get("token_id") == tok["id"] for o in init.get("order", []))
    if want in MASTERIES_MARKER and not listed:
        await send_to(ws, "error", {"msg": f"{want.title()} needs active initiative "
                                          "and your token (turn-anchored duration)"})
        return
    if want == "push" and tok is None:
        await send_to(ws, "error", {"msg": "Push needs your token for the direction"})
        return
    if want == "cleave" and (prof["ranged"] or prof["range_ft"]):
        await send_to(ws, "error", {"msg": "Cleave is a melee mastery"})
        return
    if want == "cleave" and msg.get("target2_id") is None:
        await send_to(ws, "error", {"msg": "Cleave needs a second target (target2_id)"})
        return
    if want == "cleave" and listed and \
            (init.get("turn") or {}).get("token_id") == tok["id"] and \
            (init.get("turn") or {}).get("m_cleave") == "used":
        await send_to(ws, "error", {"msg": "Cleave is already used this turn"})
        return
    if nick_mode:
        if not init.get("combat"):
            await send_to(ws, "error", {"msg": "Nick needs initiative — outside "
                                               "combat there is no Attack action"})
            return
        if is_dm or not listed or \
                (init.get("turn") or {}).get("token_id") != tok["id"]:
            await send_to(ws, "error", {"msg": "Nick belongs to your own turn "
                                               "in initiative"})
            return
        if prof["ranged"] or not prof["light"]:
            await send_to(ws, "error", {"msg": "Nick attacks need a Light melee weapon"})
            return
        other = next((p for p in gear.weapon_profiles(fresh or ch)
                      if p["slot"] != prof["slot"]), None)
        if other is None or other["ranged"] or not other["light"]:
            await send_to(ws, "error", {"msg": "Nick needs a Light weapon in BOTH hands"})
            return

    target = None
    if msg.get("target_id") is not None:
        target = db.q1("SELECT * FROM tokens WHERE id=? AND room_id=?",
                       (msg["target_id"], room_id))
        if target is None or (not is_dm and not _visible_to_member(user["id"], room_id, target)):
            # D94: hidden targets answer EXACTLY like nonexistent ones —
            # an attack must not be a probe for invisible monsters' names/AC.
            await send_to(ws, "error", {"msg": "No target token"})
            return
        if tok is not None:                      # reach is plane+distance truth
            dist = _vertical_range_distance(room_id, tok, target)
            if dist is None:
                await send_to(ws, "error", {"msg": "Target is out of reach"})
                return
            normal_r = prof.get("range_ft", 0)
            long_r = prof.get("range_long_ft", 0)
            if normal_r > 0:                     # D98 ranged tiers: normal / long / beyond
                maxr = long_r or normal_r
                if dist > maxr:
                    await send_to(ws, "error", {"msg": "Target is beyond the weapon's maximum range"})
                    return
                if long_r and dist > normal_r:   # beyond normal range: disadvantage
                    adv = None if adv == "adv" else "dis"   # advantage cancels it
            elif dist > 5 + prof.get("reach_ft", 0):        # melee reach
                await send_to(ws, "error", {"msg": "Target is out of reach"})
                return
        if want == "push" and not _token_size_ok_for_push(target):
            await send_to(ws, "error", {"msg": "The target is too large to push"})
            return

    # D109 cleave: the SECOND target is as validated as the first — visible,
    # same plane, within 5 ft of the first target AND within the attacker's
    # reach. A hidden second target answers like a nonexistent one (D94).
    t2 = None
    if want == "cleave":
        if target is None:
            await send_to(ws, "error", {"msg": "Cleave needs a first target"})
            return
        t2 = db.q1("SELECT * FROM tokens WHERE id=? AND room_id=?",
                   (msg["target2_id"], room_id))
        if t2 is None or t2["id"] == target["id"] or \
                (not is_dm and not _visible_to_member(user["id"], room_id, t2)):
            await send_to(ws, "error", {"msg": "No target token"})
            return
        if (t2.get("floor") or "") != (target.get("floor") or "") or \
                (t2.get("floor") or "") != (tok.get("floor") or ""):
            await send_to(ws, "error", {"msg": "Cleave target is on another plane"})
            return
        from .. import footprint as _fp
        from .net import get_map as _gm
        _m2 = _gm(room_id, tok.get("floor") or "")
        _c1 = _fp.occupied_origin(_m2, target)[0]
        _c2 = _fp.occupied_origin(_m2, t2)[0]
        _ca = _fp.occupied_origin(_m2, tok)[0]
        if max(abs(_c2[0] - _c1[0]), abs(_c2[1] - _c1[1])) > 1:      # 1 cell = 5 ft
            await send_to(ws, "error", {"msg": "Cleave target is not within 5 feet of the first"})
            return
        if max(abs(_c2[0] - _ca[0]), abs(_c2[1] - _ca[1])) * 5 > 5 + prof.get("reach_ft", 0):
            await send_to(ws, "error", {"msg": "Cleave target is outside your reach"})
            return

    if init.get("combat") and not is_dm:
        if tok is None:
            await send_to(ws, "error", {"msg": "Pick your token during combat (token_id)"})
            return
        turn = init.get("turn") or {}
        if listed:
            if turn.get("token_id") != tok["id"]:
                await send_to(ws, "error", {"msg": "It is not your turn"})
                return
            if CND.hook_bool(CND.load(tok), room_id, "no_actions"):
                # D134 (audit F5): incapacitated — no actions, no reactions.
                await send_to(ws, "error", {"msg": "You can't take actions right now"})
                return
            if nick_mode:
                # SRD Nick: the extra attack of the Light property becomes
                # PART OF the Attack action — it spends no bonus slot, needs
                # the action already taken (the attack it belongs to) and is
                # limited to once per turn.
                if turn.get("action") != "used":
                    await send_to(ws, "error", {"msg": "Nick is the extra attack OF the "
                                                      "Attack action — attack first"})
                    return
                if turn.get("m_nick") == "used":
                    await send_to(ws, "error", {"msg": "The Nick extra attack is once per turn"})
                    return
                init["turn"]["m_nick"] = "used"
                C.set_init(room_id, init)
            elif turn.get(slot) == "used":
                await send_to(ws, "error", {"msg": f"No {slot} left this turn"})
                return
            else:
                new_init = C.spend_slot(room_id, tok["id"], slot)
                if new_init is None:
                    await send_to(ws, "error", {"msg": "It is not your turn"})
                    return
                await broadcast(room_id, "initiative", new_init)

    # D110: slot/Nick accounting moved BELOW all target validation — a
    # refused attack (hidden target, out of reach, oversized push, bad
    # cleave pair) must never burn the turn's action.
    # D109 Sap/Vex ride the token's own attack rolls: consumed exactly on the
    # next roll (adv+dis cancel — the engine's one combine rule).
    if tok is not None and kind == "attack":
        adv = await _consume_markers(room_id, tok, adv,
                                     target["id"] if target is not None else None)

    tlabel = target["label"] if target else None
    dtxt = f" {prof['dmg_type']}" if prof["dmg_type"] else ""

    def _dmg_line(crit):
        # AP-015: the same -2/level rides the damage roll (audit F4: Damage Rolls).
        d = _roll_dmg(prof["dmg"], prof["dmg_bonus"]
                      + gear.exhaustion_roll_mod(fresh or ch), crit)
        if d is None:
            return None
        rolls, mod, total = d
        parts = [f"[{', '.join(map(str, rolls))}] {mod:+d} = {total}"]
        grand = total
        ex = prof.get("extra_dmg")
        if ex:                                                 # D98: extra damage dice (e.g. flame tongue)
            e = _roll_dmg(ex, 0, crit)
            if e is not None:
                er, _em, et = e
                grand += et
                exdt = f" {prof.get('extra_dmg_type')}" if prof.get("extra_dmg_type") else ""
                parts.append(f"+[{', '.join(map(str, er))}]{exdt} = {et}")
        tail = f" → {grand} total" if ex and grand != total else ""
        return (f"💥 {ch['name']} — {prof['name']} damage{' (crit!)' if crit else ''}{dtxt}: "
                f"{' '.join(parts)}{tail}"), grand

    if kind == "damage":                         # manual damage die, no d20
        line = _dmg_line(bool(msg.get("crit")))
        if line is None:
            await send_to(ws, "error", {"msg": "Weapon damage dice invalid"})
            return
        await dice_post(room_id, user, line[0], line[1], visibility=vis, is_dm=is_dm,
                        meta={"mode": "crit" if msg.get("crit") else "normal", "item": item_id})
        return

    cover = str(msg.get("cover") or "").lower()
    if cover == "total":
        await dice_post(room_id, user, f"🛡 {ch['name']} — target is behind total cover and can't be targeted.",
                        None, visibility=vis, is_dm=is_dm, meta={"mode": "total-cover"})
        return
    cover_mod = _cover_bonus(cover)
    exh_mod = gear.exhaustion_roll_mod(fresh or ch)       # AP-015 (audit F4)
    res = do_roll("1d20", adv)
    nat = res["kept"]
    crit = nat == 20
    total = nat + prof["to_hit"] - cover_mod + exh_mod
    advtxt = {"adv": " adv", "dis": " dis"}.get(res["adv"] or "", "")
    covtxt = {"half": " vs half cover", "three_quarters": " vs 3/4 cover"}.get(cover, "")
    extxt = f" {exh_mod:+d} exhaustion" if exh_mod else ""

    if target is None:                           # no AC claim without a target
        text = (f"⚔️ {ch['name']} — {prof['name']} attack{advtxt}{covtxt}{extxt}: d20({nat}) "
                f"{prof['to_hit']:+d} = {total}" + (" — CRITICAL!" if crit else ""))
        await dice_post(room_id, user, text, total, visibility=vis, is_dm=is_dm,
                        meta={"mode": res["adv"] or "normal", "item": item_id})
        return

    ac, alabel = _target_ac(room_id, target["id"])
    ac = 10 if ac is None else ac
    hit = crit or (nat != 1 and total >= ac)
    verdict = "— HIT!" if hit else "— MISS"
    text = (f"⚔️ {ch['name']} — {prof['name']} attack{advtxt}{covtxt} vs {alabel} "
            f"(AC {ac}): d20({nat}) {prof['to_hit']:+d}"
            + (f" {-cover_mod:+d} cover" if cover_mod else "")
            + extxt + f" = {total} {verdict}" + (" — CRITICAL!" if crit else ""))
    await dice_post(room_id, user, text, total, visibility=vis, is_dm=is_dm,
                    meta={"mode": res["adv"] or "normal", "item": item_id,
                          "hit": bool(hit), "ac": ac})
    grand = 0
    if hit:
        line = _dmg_line(crit)
        if line:
            grand = line[1]
            await dice_post(room_id, user, line[0], line[1], visibility=vis, is_dm=is_dm,
                            meta={"mode": "crit" if crit else "normal", "item": item_id})
    if want:
        await _mastery_after_roll(room_id, ws, user, is_dm, ch, fresh, prof, tok,
                                  target, t2, tlabel, vis, want, hit, crit, grand)
    if hit:
        # D111: the on_hit seam — AFTER the authoritative hit was decided and
        # posted, the wielded item's trigger effects fire through the shared
        # effect core (guarded, budgeted, no trigger-in-trigger).
        await _effects_on_hit(room_id, user, is_dm, ch, fresh, prof, tok, target, msg)


async def _effects_on_hit(room_id, user, is_dm, ch, fresh, prof, tok, target, msg):
    """D111 on_hit seam: fire the wielded item's trigger effects, post-
    decision. The core's claim guard makes retries harmless; fragments ride
    the same filtered channel as the attack line."""
    from .. import effectops
    raw = (fresh or ch).get("items")
    items = gear.clean_items(raw if isinstance(raw, list) else db.j(raw, []),
                             keep_curse=True)
    it = next((i for i in items if i["id"] == prof.get("item_id")), None)
    if it is None:
        return
    cur = it.get("curse")
    armed = isinstance(cur, dict) and cur.get("active") \
        and str(cur.get("trigger", "")) == "on_hit" and cur.get("effects")
    if not (it.get("props") or {}).get("effects") and not armed:
        return
    fired = await effectops.fire(room_id, "on_hit", token=tok, caster=tok,
                                 items=[it], target=target,
                                 round_uid=str(msg.get("op_id") or ""))
    for ctx in fired:
        curse_src = ctx.get("src") == "curse"
        for frag in ctx["log"]:
            if curse_src:
                await dm_whisper(room_id, f"✨ {frag}")
                continue
            await dice_post(room_id, user, f"✨ {frag}", None,
                            visibility=msg.get("visibility"), is_dm=is_dm,
                            meta={"mode": "effect"})


async def _mastery_after_roll(room_id, ws, user, is_dm, ch, fresh, prof, tok,
                              target, t2, tlabel, vis, want, hit, crit, grand):
    """D109: the hit/miss-gated half of an opt-in mastery. Every gate was
    validated before the roll; what remains is the SRD outcome branch."""
    from .. import footprint
    from . import combat as CMB, moveforced
    from .conditions import knock_prone
    from .net import get_map
    name, wname = ch["name"], prof["name"]

    if want == "graze" and not hit:
        # SRD Graze: flat damage equal to the ability modifier used for the
        # attack; a negative modifier deals no damage (documented reading).
        mod = gear.stat_mod(fresh or ch, prof["ability"])
        dmg = max(0, mod)
        dt = f" {prof['dmg_type']}" if prof["dmg_type"] else ""
        await dice_post(room_id, user,
                        f"🥩 {name} — {wname} Graze on {tlabel}: "
                        + (f"{dmg}{dt}" if dmg else f"no damage (mod {mod:+d})"),
                        dmg, visibility=vis, is_dm=is_dm,
                        meta={"mode": "graze", "hit": False, "item": prof["item_id"]})
        return
    if not hit or target is None:
        return

    if want == "cleave":
        init = CMB.get_init(room_id)
        turn = init.get("turn") or {}
        if init.get("combat") and tok is not None and turn.get("token_id") == tok["id"] \
                and any(o.get("token_id") == tok["id"] for o in init.get("order", [])):
            if turn.get("m_cleave") == "used":
                return                       # opportunity lost to a concurrent attack
            turn["m_cleave"] = "used"
            CMB.set_init(room_id, init)
        ac2, l2 = _target_ac(room_id, t2["id"])
        ac2 = 10 if ac2 is None else ac2
        res2 = do_roll("1d20", None)
        nat2, total2 = res2["kept"], res2["kept"] + prof["to_hit"]
        crit2 = nat2 == 20
        hit2 = crit2 or (nat2 != 1 and total2 >= ac2)
        await dice_post(room_id, user,
                        f"⚔️ {name} — {wname} Cleave vs {l2} (AC {ac2}): d20({nat2}) "
                        f"{prof['to_hit']:+d} = {total2} "
                        + ("— HIT!" if hit2 else "— MISS")
                        + (" — CRITICAL!" if crit2 else ""), total2,
                        visibility=vis, is_dm=is_dm,
                        meta={"mode": "cleave", "hit": bool(hit2), "ac": ac2})
        if hit2:
            # SRD Cleave: no ability modifier on the second damage unless
            # negative; the weapon's own flat/magic bonus stays (it is not an
            # ability modifier) and the weapon's extra dice roll too.
            amod = gear.stat_mod(fresh or ch, prof["ability"])
            flat = prof["dmg_bonus"] - (amod if prof["mod_to_dmg"] else 0)
            d = _roll_dmg(prof["dmg"], flat + (amod if amod < 0 else 0), crit2)
            if d is not None:
                rolls, dmod, dtot = d
                parts = [f"[{', '.join(map(str, rolls))}] {dmod:+d} = {dtot}"]
                gtot = dtot
                ex = prof.get("extra_dmg")
                if ex:
                    e = _roll_dmg(ex, 0, crit2)
                    if e is not None:
                        gtot += e[2]
                        parts.append(f"+[{', '.join(map(str, e[0]))}] = {e[2]}")
                await dice_post(room_id, user,
                                f"💥 {name} — {wname} Cleave damage "
                                f"{'(crit!) ' if crit2 else ''}{' '.join(parts)}",
                                gtot, visibility=vis, is_dm=is_dm,
                                meta={"mode": "crit" if crit2 else "normal",
                                      "item": prof["item_id"], "cleave": True})
        return

    if want == "push":
        fl = tok.get("floor") or ""
        mp = get_map(room_id, fl)
        a0, _s = footprint.occupied_origin(mp, tok)
        t0, _s2 = footprint.occupied_origin(mp, target)
        dx, dy = t0[0] - a0[0], t0[1] - a0[1]
        sx, sy = (dx > 0) - (dx < 0), (dy > 0) - (dy < 0)
        if sx == 0 and sy == 0:
            sx = 1                                       # same cell: any straight way
        final = await moveforced.apply_forced_move(
            room_id, target, "push", (t0[0] + sx * 2, t0[1] + sy * 2),
            chronicle=f"🌬 {name} pushes {tlabel} straight away (Push, up to 10 ft).")
        if final is None:
            await dice_post(room_id, user,
                            f"🚧 {tlabel} cannot be pushed — the way is blocked.",
                            None, visibility=vis, is_dm=is_dm,
                            meta={"mode": "push", "moved": False})
        else:
            await dice_post(room_id, user,
                            f"🌬 {name} pushes {tlabel} straight away (Push, up to 10 ft).",
                            None, visibility=vis, is_dm=is_dm,
                            meta={"mode": "push", "moved": True})
        return

    if want == "topple":
        from .. import abilities as ABIL                 # late: ws import cycle
        sheet, saves = ABIL._sheet_and_saves(target)
        dc = 8 + gear.stat_mod(fresh or ch, prof["ability"]) + gear.prof_bonus(fresh or ch)
        roll = do_roll("1d20", None)
        mod = gear.save_bonus(sheet, saves, "con") if sheet is not None else 0
        total = roll["kept"] + mod
        ok = total >= dc
        await dice_post(room_id, user,
                        f"🪓 {name} — {wname} Topple: {tlabel} CON save "
                        f"d20({roll['kept']}) {mod:+d} = {total} vs DC {dc} → "
                        + ("resists" if ok else "PRONE"), total,
                        visibility=vis, is_dm=is_dm,
                        meta={"mode": "topple", "dc": dc, "success": bool(ok)})
        if not ok:
            await knock_prone(room_id, target, actor=name)
        return

    if want == "sap":
        await _set_marker(room_id, target, "sapped", 0, "start", src=tok["id"])
        await dice_post(room_id, user,
                        f"😨 {tlabel} is sapped — disadvantage on its next attack roll.",
                        None, visibility=vis, is_dm=is_dm,
                        meta={"mode": "mastery", "mastery": "sap"})
        return

    if want == "slow":
        if grand <= 0:
            return                                       # SRD: 'and deal damage'
        await _set_marker(room_id, target, "slowed", 0, "start", src=tok["id"])
        await dice_post(room_id, user,
                        f"🐌 {tlabel} is slowed — speed reduced by 10 ft until "
                        f"{name}'s next turn.", None, visibility=vis, is_dm=is_dm,
                        meta={"mode": "mastery", "mastery": "slow"})
        return

    if want == "vex":
        if grand <= 0:
            return                                       # SRD: 'and deal damage'
        await _set_marker(room_id, tok, "vexed", 1, "end", src=tok["id"], ref=target["id"])
        await dice_post(room_id, user,
                        f"🎯 {name} vexes {tlabel} — advantage on the next attack "
                        f"against it.", None, visibility=vis, is_dm=is_dm,
                        meta={"mode": "mastery", "mastery": "vex"})


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
    if msg.get("target_id") is not None:
        target = db.q1("SELECT * FROM tokens WHERE id=? AND room_id=?",
                       (msg["target_id"], room_id))
        if target is None:
            await send_to(ws, "error", {"msg": "No target token"})
            return
        dist = _vertical_range_distance(room_id, tok, target)
        if dist is None or dist > atk.get("reach", 5):
            await send_to(ws, "error", {"msg": "Target is out of reach"})
            return
    adv = await _consume_markers(room_id, tok, msg.get("adv"),
                                 msg.get("target_id"))          # D109 markers
    res = do_roll("1d20", adv)
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


async def _spend_insp(ws, room_id, ch, adv):
    """D135 (AP-021, audit F6): Heroic Inspiration rides an EXISTING d20
    path. 'insp' spends the marker and folds into the normal advantage
    derivation — the SRD 'choose either die' keeps high (documented
    simplification, same class as the frightened blanket in conditions.py).
    Only attack rolls, ability checks and saving throws reach this: the
    blind-roll branch refuses the word before any character is loaded."""
    if adv != "insp":
        return True, adv
    if ch is None or not int(bool(ch.get("inspiration"))):
        await send_to(ws, "error", {"msg": "You have no Heroic Inspiration to spend"})
        return False, adv
    db.x("UPDATE characters SET inspiration=0 WHERE id=?", (ch["id"],))
    sys_msg(room_id, f"{ch['name']} spends Heroic Inspiration.")
    await broadcast(room_id, "snapshot", None)
    return True, "adv"


async def handle_roll(ws, room_id, user, is_dm, msg):
    kind = msg.get("kind")
    adv = msg.get("adv")
    vis = msg.get("visibility")
    # D135: the marker belongs to a seated character — blind expressions
    # cannot carry it; NPC rolls are refused inside _npc_roll.
    if adv == "insp" and kind not in SKILL_KINDS:
        await send_to(ws, "error", {"msg": "Heroic Inspiration spends on your own "
                                          "attack roll, ability check or saving throw"})
        return
    if kind in SKILL_KINDS and msg.get("token_id") is not None:
        tok, block = _npc_target(room_id, user, is_dm, msg)
        if tok is not None:
            if adv == "insp":
                await send_to(ws, "error", {"msg": "Heroic Inspiration spends on "
                                                  "your own attack roll, ability "
                                                  "check or saving throw"})
                return
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
            mod = res["mod"] + gear.stat_mod(ch, ab) + (gear.prof_bonus(ch) if bool(msg.get("prof")) else 0)
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
    ok, adv = await _spend_insp(ws, room_id, ch, msg.get("adv"))
    if not ok:
        return
    stats = char_stats(ch)

    if kind in ("check", "save"):
        ab = str(msg.get("ability", "")).lower()
        if ab not in ABILITIES:
            await send_to(ws, "error", {"msg": "Unknown ability"})
            return
        # D111: standing condition hooks (catalog-driven, see conditions.py).
        tokc = db.q1("SELECT * FROM tokens WHERE character_id=? AND room_id=? "
                     "ORDER BY id LIMIT 1", (ch["id"], room_id))
        conds = CND.load(tokc) if tokc else []
        if kind == "save" and CND.auto_fails_save(conds, room_id, ab):
            await dice_post(room_id, user,
                            f"🎲 {ch['name']} — {ab.upper()} save: AUTO-FAIL "
                            f"(condition)", 0, visibility=vis, is_dm=is_dm,
                            meta={"mode": "auto_fail", "ability": ab})
            return
        if CND.hook_bool(conds, room_id, "my_saves_dis" if kind == "save"
                         else "my_checks_dis"):
            adv = _combine_adv(adv, "dis")
        if kind == "save":
            saves = gear.clean_saves(db.j(ch.get("saves"), {}))
            mod = gear.save_bonus(ch, saves, ab)
            prof = bool(saves.get(ab))
        else:
            mod = gear.stat_mod(ch, ab) + (gear.prof_bonus(ch) if bool(msg.get("prof")) else 0)
            prof = bool(msg.get("prof"))
        mod += gear.exhaustion_roll_mod(ch)          # AP-015 (audit F4)
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
        bonus += gear.exhaustion_roll_mod(ch)        # AP-015 (audit F4)
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
            cover = _spell_cover(msg)
            if cover is None:
                await _total_cover_note(room_id, user, is_dm, vis, ch)
                return
            # D109: Sap/Vex ride the CASTER's token too (optional token_id).
            if msg.get("token_id") is not None:
                tok = db.q1("SELECT * FROM tokens WHERE id=? AND room_id=?",
                            (msg["token_id"], room_id))
                if tok is not None and authz.controls(tok, user["id"], is_dm):
                    adv = await _consume_markers(room_id, tok, adv, None)
            res = _spell_attack_text(ch, sp, adv, cover)
        elif kind == "spell_dc":
            res = _spell_dc_text(ch, sp)
        else:
            res = _spell_damage_text(ch, sp, bool(msg.get("crit")))
        if res is None:
            await send_to(ws, "error", {"msg": "Spell has no valid damage dice"})
            return
        await dice_post(room_id, user, res[0], res[1], visibility=vis, is_dm=is_dm)
        return

    # ---- D93: item attack. Everything derives SERVER-side: the profile from
    # equipped props, the bonus from gear, the AC verdict from the target.
    # Client fields like to_hit/dmg are not read — item_id is the claim.
    if msg.get("item_id") and kind in ("attack", "damage"):
        await _item_attack(room_id, ws, user, is_dm, ch, msg, kind, adv, vis)
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
        to_hit = gear.stat_mod(ch, wab) + (gear.prof_bonus(ch) if w.get("proficient") else 0) + bonus
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
    if sp["level"] > 0 and any(x.get("prep") for x in spells) and not sp.get("prepared"):
        # D138 (audit C3): a preparation-gated list only casts what is prepared.
        await send_to(ws, "error", {"msg": f"{sp['name']} is not prepared"})
        return
    if sp["cast"] == "attack" and _spell_cover(msg) is None:
        # D137: total cover refuses the target BEFORE any slot is touched.
        await _total_cover_note(room_id, user, is_dm, vis, ch)
        return
    # D131 (AP-017): the spell's casting time decides WHICH slot of the
    # active turn this cast spends — action, bonus action or reaction —
    # through the ONE turn-slot economy attacks already use. Minute/hour/
    # ritual cast times are out of turn tempo and spend nothing. Validation
    # first, spending only once the slot claim below succeeds (D110).
    from . import combat as CB                    # late: combat imports dice
    cast_slot = gear.casting_slot(sp.get("casting_time"))
    ctok = None
    if msg.get("token_id") is not None:
        ctok = db.q1("SELECT * FROM tokens WHERE id=? AND room_id=?",
                     (msg["token_id"], room_id))
        if ctok is None or not authz.controls(ctok, user["id"], is_dm) \
                or ctok["character_id"] != ch["id"]:
            await send_to(ws, "error", {"msg": "That token is not yours to cast with"})
            return
    init = CB.get_init(room_id)
    op_probe = str(msg.get("op_id", ""))[:40]
    if op_probe and INV.claimed(op_probe, room_id, "cast", ch["id"]):
        return                                                    # replay — silent
    if init.get("combat") and not is_dm:
        if ctok is None:
            await send_to(ws, "error", {"msg": "Pick your token during combat (token_id)"})
            return
        turn = init.get("turn") or {}
        listed = any(o["token_id"] == ctok["id"] for o in init.get("order", []))
        if cast_slot and listed:
            if turn.get("token_id") != ctok["id"]:
                await send_to(ws, "error", {"msg": "It is not your turn"})
                return
            if CND.hook_bool(CND.load(ctok), room_id, "no_actions"):
                # D134: casting is an action — incapacitated forbids it.
                await send_to(ws, "error", {"msg": "You can't take actions right now"})
                return
            if turn.get(cast_slot) == "used":
                await send_to(ws, "error", {"msg": f"No {cast_slot} left this turn"})
                return

    lvl = int(sp.get("level", 0))
    if lvl > 0:
        # D93: replay guard and consumption share ONE transaction, and the
        # slot is re-read inside it — a racing double-send consumes exactly
        # one slot (or nothing), never two, never negative.
        op_id = str(msg.get("op_id", ""))[:40]
        err = None
        with db.tx() as c:
            if op_id and not INV._claim(c, op_id, room_id, "cast", ch["id"]):
                err = "replay"
            else:
                fresh = c.execute("SELECT spell_slots FROM characters WHERE id=?",
                                  (ch["id"],)).fetchone()
                slots = gear.clean_slots(db.j(fresh["spell_slots"], {}))
                s = slots.get(lvl, {"max": 0, "used": 0})
                if s["used"] >= s["max"]:
                    err = f"No {lvl}-level spell slots left"
                else:
                    s["used"] += 1
                    c.execute("UPDATE characters SET spell_slots=? WHERE id=?",
                              (db.json_dumps(slots), ch["id"]))
        if err == "replay":
            return
        if err:
            await send_to(ws, "error", {"msg": err})
            return
        await broadcast(room_id, "snapshot", None)
    if init.get("combat") and not is_dm and cast_slot and ctok is not None and \
            any(o["token_id"] == ctok["id"] for o in init.get("order", [])):
        spent = CB.spend_slot(room_id, ctok["id"], cast_slot)
        if spent is not None:
            await broadcast(room_id, "initiative", spent)
    crit = bool(msg.get("crit"))
    posts = []
    if sp["cast"] == "attack":
        posts.append(_spell_attack_text(ch, sp, msg.get("adv"), _spell_cover(msg) or ""))
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
        await send_to(ws, "error", {"msg": "DM only"})
        return
    clear_conditions = bool(msg.get("clear_conditions"))
    for m in db.q("SELECT user_id, character_id FROM room_members "
                  "WHERE room_id=? AND character_id IS NOT NULL", (room_id,)):
        ch = gear.as_sheet(db.q1("SELECT * FROM characters WHERE id=?", (m["character_id"],)))
        if ch is None:
            continue
        slots = gear.clean_slots(db.j(ch["spell_slots"], {}))
        items = gear.clean_items(db.j(ch["items"], []), keep_curse=True)  # D106: rest preserves curses
        resources = gear.clean_resources(db.j(ch.get("resources"), []))
        for lv in range(1, 10):
            slots[lv]["used"] = 0
        for it in items:
            if it["recharge"] == "long":
                it["charges"] = it["chargesMax"]
        for r in resources:
            # a long rest is strictly greater than a short one (5e), so it also
            # refills short-reset class resources (e.g. sorcery points — D97).
            if r["reset"] in ("long", "short"):
                r["current"] = r["max"]
        tok = db.q1("SELECT * FROM tokens WHERE room_id=? AND character_id=?",
                    (room_id, m["character_id"]))
        death = _load_death(tok) if tok else None
        with db.tx() as c:
            c.execute(
                "UPDATE characters SET hp=max_hp, temp_hp=0, spell_slots=?, items=?, resources=?, "
                "hit_dice_spent=0, exhaustion=MAX(0, COALESCE(exhaustion,0)-1) WHERE id=?",
                (db.json_dumps(slots), db.json_dumps(items), db.json_dumps(resources),
                 m["character_id"]))
            if death is not None:
                c.execute("UPDATE tokens SET death=NULL WHERE id=?", (tok["id"],))
    # Monster tokens refill too: per-slot used=0, resources back to max.
    # HP/conditions are deliberately NOT restored here — the DM decides when
    # a creature recovers (and clear_conditions already covers conditions).
    for tok in db.q("SELECT id, npc FROM tokens WHERE room_id=? AND character_id IS NULL "
                    "AND npc IS NOT NULL", (room_id,)):
        block = npc.load(tok)
        if not block:
            continue
        changed = False
        slots = gear.clean_slots(block.get("spell_slots"))
        if any(d["used"] for d in slots.values()):
            for lv in slots:
                slots[lv]["used"] = 0
            block["spell_slots"] = slots
            changed = True
        resources = npc._clean_resources(block.get("resources"))
        if any(r["cur"] != r["max"] for r in resources):
            for r in resources:
                r["cur"] = r["max"]
            block["resources"] = resources
            changed = True
        if changed:
            db.x("UPDATE tokens SET npc=? WHERE id=?", (db.json_dumps(block), tok["id"]))
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
            await send_to(ws, "error", {"msg": "Not your character"})
            return
    ch = gear.as_sheet(db.q1("SELECT * FROM characters WHERE id=?", (tok["character_id"],)))
    if ch is None:
        return
    try:
        count = max(0, min(gear.hit_dice_max(ch), int(msg.get("hit_dice_count", 0) or 0)))
    except (TypeError, ValueError):
        count = 0
    hd = gear.clean_hit_die(ch.get("hit_die", 8))
    avail = max(0, gear.hit_dice_max(ch) - max(0, min(gear.hit_dice_max(ch), int(ch.get("hit_dice_spent") or 0))))
    spend = min(count, avail)
    con_mod = gear.stat_mod(ch, "con")
    healed = 0
    rolltxt = ""
    if spend:
        res = do_roll(f"{spend}d{hd}", None)
        if res:
            gear_bonus = int(gear.effective_gear(ch).get("hit_dice_bonus") or 0) * spend
            healed = max(0, res["total"] + con_mod + gear_bonus)
            rolltxt = f" spent {spend}d{hd} (CON {con_mod:+d}"
            if gear_bonus:
                rolltxt += f", gear {gear_bonus:+d}"
            rolltxt += f"): {healed} HP"
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
    ch = gear.as_sheet(db.q1("SELECT * FROM characters WHERE id=?", (tok["character_id"],)))
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
    # D93: op_id replay guard rides the write transaction (claim+store atomic).
    op_id = str(msg.get("op_id", ""))[:40]
    with db.tx() as c:
        if op_id and not INV._claim(c, op_id, room_id, "resource", ch["id"]):
            return
        c.execute("UPDATE characters SET resources=? WHERE id=?",
                  (db.json_dumps(resources), ch["id"]))
    await broadcast(room_id, "snapshot", None)
