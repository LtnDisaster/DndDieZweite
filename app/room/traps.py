"""Hidden traps and loot, triggered by stepping onto a cell."""
from .. import gear, db, events, npc
from . import health
from .dice import dex_mod, do_roll
from .net import (broadcast, get_map, map_lock, send_to, send_user, set_map,
                  sys_msg)


def at_cell(items, cx, cy):
    return next((e for e in items if e["x"] == cx and e["y"] == cy), None)


def _d20():
    """(D114) A legacy trap's d20 now rolls through the ONE dice engine
    (`dice.do_roll`) instead of a local `random.randint`, so the save shares the
    same authoritative, testable roll the rest of the engine uses. The die value
    is returned UNMODIFIED and the caller adds the same raw DEX modifier and does
    the same `total >= dc` comparison — behaviour is byte-for-byte what the old
    `random.randint(1, 20)` produced (no advantage, no proficiency), only the RNG
    source moves. Damage dice already went through `do_roll`."""
    return do_roll("1d20", None)["kept"]


async def _fire_effects_trap(room_id, tok, trap):
    """D113 Phase 5: spring a data-driven trap. The trap's `effects` cell is run
    through the ONE effect grammar (save/check/damage/condition/forced_move), so
    there is no second dice/save engine. A sprung trap is no longer secret: the
    owner and DM see the resolution fragments. `repeat` re-arms the trap for the
    next creature to step on it; otherwise it springs once (triggered=True)."""
    from .. import effectops
    trap["discovered"] = True
    trap["triggered_by"] = tok.get("id")
    if not trap.get("repeat"):
        trap["triggered"] = True
    events.emit(events.make("trap_triggered", room_id=room_id, actor_id=tok.get("id"),
                            trap_label=trap.get("label")))
    dm = db.q1("SELECT dm_id FROM rooms WHERE id=?", (room_id,))
    try:
        ops = effectops.validate(trap["effects"])
    except effectops.EffectError as ex:
        # fail-closed: a stored-but-now-invalid cell never executes, only tells
        # the DM the trap could not resolve (a bad cell cannot hurt a player).
        await send_user(room_id, dm["dm_id"], "whisper",
                        {"text": f"⚠ {trap.get('label')}: invalid effect cell ({ex})"})
        return True
    ctx = effectops.make_ctx(room_id, caster=tok, target=tok, trigger="trap")
    ctx["self"] = tok
    ctx["depth"] = 1                     # a trap effect fires no further triggers
    await effectops.run_ops(ops, ctx)
    owner = tok.get("owner_user_id")
    detail = f"🕯 {trap.get('label')}: " + ("; ".join(ctx["log"]) if ctx["log"] else "triggered")
    for uid in {owner, dm["dm_id"]} - {None}:
        await send_user(room_id, uid, "whisper", {"text": detail})
    return True


async def hit_trap(room_id, tok, trap):
    # Data-driven trap (D113 Phase 5): fire the authored effect grammar. A legacy
    # trap (dc/dmg only, no effects) keeps the byte-identical path below.
    if trap.get("effects"):
        return await _fire_effects_trap(room_id, tok, trap)
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
    ch = (gear.as_sheet(db.q1("SELECT * FROM characters WHERE id=?", (tok["character_id"],)))
              if tok["character_id"] else None)
    if ch and owner:
        mod = dex_mod(ch["id"])
        roll = _d20()
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
    roll = _d20()
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
    ch = (gear.as_sheet(db.q1("SELECT * FROM characters WHERE id=?", (tok["character_id"],)))
              if tok["character_id"] else None)
    if not owner or ch is None:
        return False
    if loot.get("container"):
        # D133 (AP-019): flagged loot is a real container (inv_container on
        # the "loot:<id>" key) — stepping onto it never writes a note. The
        # hint is a one-liner; the True return only persists the marker.
        if not loot.get("hinted"):
            loot["hinted"] = True
            await send_user(room_id, owner, "whisper",
                            {"text": f"🎁 {loot['label']} is a container — "
                                     f"search it up close."})
        return True
    loot["taken_by"] = owner
    note = ("[loot] " + loot["label"])
    db.x("UPDATE characters SET notes=? WHERE id=?",
         ((ch["notes"] + "\n" + note) if ch["notes"] else note, ch["id"]))
    await send_user(room_id, owner, "whisper",
                    {"text": f"🎁 You found: {loot['label']} — added to {ch['name']}'s notes"})
    return True


# ---------------------------------------------------------------------------
# D113 Phase 5 / D114: data-driven traps — discovery, disarming and a DM
# force-spring, all through the SAME engines (opposed.participant/check_roll for
# the roll, the effect grammar in hit_trap for the resolution). No second engine.
# Disarm is a server Dexterity CHECK. IMPORTANT (documented open engine gap,
# D114): a real Thieves'-tools check would fold in a tool proficiency, but the
# engine models NO tool proficiency (characters carry skills+saves only, no tools
# column is read at roll time). So this is a plain DEX check and is LABELED as
# such — NOT a "Thieves' tools" check. DM-granted advantage is a stopgap, not a
# substitute for the missing proficiency; the proficiency model is deferred. The
# whole surface is leak-safe: a hidden trap is never named or acknowledged.
# ---------------------------------------------------------------------------

TRAP_ACTIONS = ("search", "disarm", "trigger")


def _cell_of(tok, mp):
    c = mp.get("cell") or 1
    return int(tok["x"] / c - 0.5), int(tok["y"] / c - 0.5)


def _adjacent(tok, mp, cx, cy):
    tx, ty = _cell_of(tok, mp)
    return abs(tx - cx) <= 1 and abs(ty - cy) <= 1


async def handle_trap(ws, room_id, user, is_dm, msg):
    """A player searches a cell (Wisdom/Perception vs search_dc) or disarms a
    discovered trap (Dexterity check vs disarm_dc); the DM may force-spring a
    trap on a chosen occupant. The actor names a CELL, never a trap id — an
    absent or hidden trap answers EXACTLY like a failed search, so this endpoint
    is never a trap oracle."""
    action = str(msg.get("action", ""))
    if action not in TRAP_ACTIONS:
        return
    tok = db.q1("SELECT * FROM tokens WHERE id=? AND room_id=?",
                (msg.get("token_id", -1), room_id))
    if tok is None:
        await send_to(ws, "error", {"msg": "No such token here"})
        return
    if not is_dm and tok["owner_user_id"] != user["id"]:
        await send_to(ws, "error", {"msg": "Not your token"})
        return
    if action == "trigger" and not is_dm:
        await send_to(ws, "error", {"msg": "DM only"})
        return
    try:
        cx, cy = int(msg.get("x")), int(msg.get("y"))
    except (TypeError, ValueError):
        await send_to(ws, "error", {"msg": "Which cell?"})
        return
    adv = str(msg.get("adv", "") or "").lower() or None
    if adv not in (None, "adv", "dis"):
        adv = None
    fl = str(tok.get("floor") or "")

    async def reply(text, kind="whisper"):
        await send_to(ws, kind, {"text": text} if kind == "whisper" else {"msg": text})

    async with map_lock(room_id):
        mp = get_map(room_id, fl)
        trap = at_cell(mp.get("traps", []), cx, cy)

        # A player may only act on a cell they stand next to; adjacency is the
        # player's OWN knowledge, never a trap oracle. The DM acts anywhere.
        if action in ("search", "disarm") and not is_dm and not _adjacent(tok, mp, cx, cy):
            await send_to(ws, "error", {"msg": "You must be next to that cell"})
            return

        from . import opposed
        _MISS = "You search the area but find nothing."

        if action == "search":
            # Leak-safe discovery: a hidden trap is never acknowledged. A search
            # against an absent cell and a MISSED search against a hidden trap
            # answer with the byte-identical _MISS line — never an oracle.
            if trap is not None and trap.get("discovered"):
                await reply(f"{trap.get('label')} has already been found.")
                return
            findable = trap is not None and trap.get("search_dc") and not trap.get("triggered")
            if not findable:
                await reply(_MISS)
                return
            p = opposed.participant(room_id, tok)
            if p is None:
                await send_to(ws, "error", {"msg": "This token cannot roll"})
                return
            dc = trap["search_dc"]
            r = opposed.check_roll(p, "perception", kind="skill", adv=adv)
            if r is None:
                await send_to(ws, "error", {"msg": "Cannot roll"})
                return
            if is_dm or opposed.beats_dc(r["total"], dc):
                trap["discovered"] = True
                set_map(room_id, mp, fl)
                await broadcast(room_id, "map_changed", None)
                await reply(f"🔍 Perception {r['kept']}+{r['mod']} = {r['total']} "
                            f"vs DC{dc} → you found: {trap.get('label')}.")
                sys_msg(room_id, f"{_label_name(tok)} discovered a trap: {trap.get('label')}")
            else:
                await reply(_MISS)
            return

        # ---- disarm / trigger require a trap the actor can actually see.
        if trap is None or (not is_dm and not trap.get("discovered")):
            await reply("There is nothing here to disarm." if action == "disarm" else _MISS)
            return

        if action == "trigger":
            target = db.q1("SELECT * FROM tokens WHERE id=? AND room_id=?",
                           (msg.get("target_id", -1), room_id))
            if target is None:
                await send_to(ws, "error", {"msg": "No such target"})
                return
            trap["discovered"] = True
            set_map(room_id, mp, fl)
            await hit_trap(room_id, target, trap)
            set_map(room_id, mp, fl)
            await broadcast(room_id, "map_changed", None)
            return

        # ---- disarm a discovered trap: a plain Dexterity CHECK (an honest
        # label — the engine models NO tool proficiency, so this is NOT a
        # "Thieves' tools" check; see the block comment above). DM may grant
        # advantage as a stopgap; the missing proficiency stays a known gap.
        dc = trap.get("disarm_dc")
        if not dc:
            await reply("There is no mechanism here to disarm.")
            return
        if trap.get("disarmed"):
            await reply(f"{trap.get('label')} is already disarmed.")
            return
        if trap.get("triggered") and not trap.get("repeat"):
            await reply(f"{trap.get('label')} has already sprung.")
            return
        p = opposed.participant(room_id, tok)
        if p is None:
            await send_to(ws, "error", {"msg": "This token cannot roll"})
            return
        r = opposed.check_roll(p, "dex", kind="check", adv=adv)
        if r is None:
            await send_to(ws, "error", {"msg": "Cannot roll"})
            return
        if opposed.beats_dc(r["total"], dc):
            trap["disarmed"] = True
            trap["triggered"] = True            # a disarmed trap never springs again
            set_map(room_id, mp, fl)
            await broadcast(room_id, "map_changed", None)
            await reply(f"🔧 Dexterity check {r['kept']}+{r['mod']} = {r['total']} "
                        f"vs DC{dc} → {trap.get('label')} disarmed.")
            sys_msg(room_id, f"{_label_name(tok)} disarmed a trap")
        else:
            await reply(f"🔧 Dexterity check {r['kept']}+{r['mod']} = {r['total']} "
                        f"vs DC{dc} → you fail to disarm {trap.get('label')}.")
        return


def _label_name(tok):
    if tok.get("character_id"):
        ch = db.q1("SELECT name FROM characters WHERE id=?", (tok["character_id"],))
        if ch:
            return ch["name"]
    return tok.get("label") or "Someone"
