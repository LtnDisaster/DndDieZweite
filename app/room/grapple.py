"""D112 (Sprint 41): Grapple / Shove / Escape per D&D 2024 / SRD 5.2.1 — NOT the
2014 Athletics-vs-Athletics contest.

The 2024 rules resolve a special melee attack (an Unarmed Strike made as part of
the Attack action) as an attacker CHECK that SETS a DC, against a target
SAVING THROW the target chooses between Strength and Dexterity. The engine
implements exactly that shape through the generic opposed primitive
(``room.opposed``) and applies the outcome with the sub-engines it already has:

  * Grapple  → the EXISTING ``grappled`` condition, tagged with the grappler's
    token id (``src``) and the escape DC (``dc``) so it can end properly;
  * Shove    → ``room.conditions.knock_prone`` OR ``room.moveforced``
    ``apply_forced_move(kind="shove")`` (the target's own move is untouched);
  * Escape   → a Strength (Athletics) / Dexterity (Acrobatics) check vs the
    stored escape DC — a fixed DC, not a re-contest.

Grapple ends when the grappled creature leaves the grappler's reach (any forced
movement, or a grappler that walks away) — ``end_grapples_out_of_reach``, wired
into ``moveforced`` and ``movement``.

Action economy mirrors the attack path exactly: every precondition (turn, slot,
reach, size, visibility) is validated BEFORE anything is spent, and the action
slot is consumed last so a refused attempt never burns a turn nor rolls a free
die. Out of initiative there is no action economy (DM-paced), matching Dash and
Stand Up. No cost is ever charged for a pre-invalid action.
"""
from .. import conditions as CND, db, footprint, gear
from . import authz, combat as CMB, opposed
from .conditions import knock_prone
from .dice import _visible_to_member, dice_post
from .net import broadcast, get_map, send_to, sys_msg
from .visibility import send_cond_bump


# ---------------------------------------------------------------------------
# geometry helpers (cell/footprint truth, exactly like room.dice measures reach)
# ---------------------------------------------------------------------------

def _origin_cells(mp, tok):
    origin, side = footprint.occupied_origin(mp, tok)
    return footprint.origin_cells(mp, origin, side)


def _adjacent(room_id, a, b):
    """Within 5 ft (Chebyshev ≤ 1 cell) using the CLOSEST footprint corners.
    D114: a shared plane includes the token's home plane, a body legitimately
    protruding into another plane, or a fully open vertical column. Plain
    different planes with no opening are still never adjacent."""
    from . import vertical3d
    maps = vertical3d.maps_for(room_id)
    lm = vertical3d.level_map(room_id)
    for fl in vertical3d.floor_list(room_id):
        ca = vertical3d.body_cells(room_id, a, fl, maps, lm)
        if not ca:
            continue
        cb = vertical3d.body_cells(room_id, b, fl, maps, lm)
        if any(max(abs(x1 - x2), abs(y1 - y2)) <= 1
               for x1, y1 in ca for x2, y2 in cb):
            return True
    return False


def _push_dest(room_id, attacker, target):
    """One cell beyond the target, straight away from the attacker (the shove's
    push destination; ``apply_forced_move`` still stops it at obstacles)."""
    if (attacker.get("floor") or "") != (target.get("floor") or ""):
        return None
    mp = get_map(room_id, attacker.get("floor") or "")
    if mp is None:
        return None
    ax, ay = footprint.occupied_origin(mp, attacker)[0]
    tx, ty = footprint.occupied_origin(mp, target)[0]
    sx = (tx > ax) - (tx < ax)
    sy = (ty > ay) - (ty < ay)
    if not sx and not sy:                       # same column (should not reach here)
        sx = 1
    return (tx + sx, ty + sy)


def _size_index(tok):
    from .. import npc
    size = (tok.get("size") or "").title()
    if size not in npc.SIZES:
        blk = npc.load(tok)
        size = npc.clean_size((blk or {}).get("size"))
    return npc.SIZES.index(size)


def _size_ok_grapple(att, tgt):
    """2024 Grapple: 'no more than one size larger than you'. Characters are
    Medium (the token size governs; mirrors room.dice._token_size_ok_for_push)."""
    return _size_index(tgt) <= _size_index(att) + 1


# ---------------------------------------------------------------------------
# shared validation / cost (mirrors room.dice._item_attack's discipline)
# ---------------------------------------------------------------------------

async def _melee_target(ws, room_id, user, is_dm, msg, *, size_check):
    tok = db.q1("SELECT * FROM tokens WHERE id=? AND room_id=?",
                (msg.get("token_id", -1), room_id))
    if tok is None or not authz.controls(tok, user["id"], is_dm):
        await send_to(ws, "error", {"msg": "You can only act through your own character"})
        return None, None
    target = db.q1("SELECT * FROM tokens WHERE id=? AND room_id=?",
                   (msg.get("target_id", -1), room_id))
    if target is None or target["id"] == tok["id"] or \
            (not is_dm and not _visible_to_member(user["id"], room_id, target)):
        await send_to(ws, "error", {"msg": "No target token"})   # hidden == absent (D94)
        return None, None
    if size_check and not _size_ok_grapple(tok, target):
        await send_to(ws, "error", {"msg": "The target is too large to grapple"})
        return None, None
    if not _adjacent(room_id, tok, target):
        await send_to(ws, "error", {"msg": "Target is out of reach"})
        return None, None
    return tok, target


async def _take_action(ws, room_id, user, is_dm, tok, slot="action"):
    """Validate the action slot BEFORE spending, then spend it (Attack / Escape
    action). Out of initiative: free. DM: free. Mirrors the attack path."""
    init = CMB.get_init(room_id)
    if init.get("combat") and not is_dm:
        listed = any(o.get("token_id") == tok["id"] for o in init.get("order", []))
        if listed:
            turn = init.get("turn") or {}
            if turn.get("token_id") != tok["id"]:
                await send_to(ws, "error", {"msg": "It is not your turn"})
                return False
            if turn.get(slot) == "used":
                await send_to(ws, "error", {"msg": f"No {slot} left this turn"})
                return False
            new = CMB.spend_slot(room_id, tok["id"], slot)
            if new is None:
                await send_to(ws, "error", {"msg": "It is not your turn"})
                return False
            await broadcast(room_id, "initiative", new)
    return True


def _claim(room_id, op_id, ns, kind):
    if not op_id:
        return True
    from .. import inventory as INV
    with db.tx() as c:
        return INV._claim(c, op_id, room_id, kind, ns)


# ---------------------------------------------------------------------------
# Grapple / Shove
# ---------------------------------------------------------------------------

async def _special_melee(ws, room_id, user, is_dm, msg, *, grapple):
    op = str(msg.get("op_id", ""))[:40] or None
    mode = str(msg.get("mode", "prone"))
    if grapple:
        mode = "grapple"
    elif mode not in ("prone", "push"):
        return await send_to(ws, "error", {"msg": "A shove knocks prone or pushes"})
    tok, target = await _melee_target(ws, room_id, user, is_dm, msg, size_check=grapple)
    if tok is None:
        return
    if not grapple and mode == "push" \
            and (tok.get("floor") or "") != (target.get("floor") or ""):
        # D114: a cross-plane body can be attacked/engaged, but a horizontal
        # push has no coherent destination on the attacker's plane.
        return await send_to(ws, "error", {
            "msg": "You cannot shove a creature across planes"})
    att = opposed.participant(room_id, tok)
    dfn = opposed.participant(room_id, target)
    if att is None or dfn is None:
        return await send_to(ws, "error", {"msg": "Cannot resolve this creature"})
    if not _claim(room_id, op, att["stats_id"], "special_melee"):
        return                                                    # replay — silent no-op
    if not await _take_action(ws, room_id, user, is_dm, tok):
        return

    bonus, _src = opposed.melee_attack_number(att)
    aroll = opposed.bonus_roll(att, bonus, adv=msg.get("adv"))
    dc = aroll["total"]
    adv_txt = {"adv": " adv", "dis": " dis"}.get(aroll["adv"] or "", "")
    verb = ("Grappling" if grapple else
            "Shoving to knock" if mode == "prone" else "Shoving to push")
    await dice_post(room_id, user,
                    f"🤼 {att['name']} — {verb} {target['label']}{adv_txt}: "
                    f"d20({aroll['kept']}) {bonus:+d} = {dc} (save DC {dc})",
                    dc, visibility="self", is_dm=is_dm,
                    meta={"mode": "opposed-attack", "dc": dc})

    force = str(msg.get("save", "")).lower() if is_dm else ""
    sav_ab = force if force in opposed.ABILITIES else opposed.better_save(dfn, ("str", "dex"))
    sv = opposed.save_roll(dfn, sav_ab)
    resisted = sv["total"] >= dc
    save_word = "auto-fail" if sv["auto_fail"] else f"d20({sv['kept']}) {sv['mod']:+d} = {sv['total']}"
    await dice_post(room_id, user,
                    f"🛡 {dfn['name']} — {sav_ab.upper()} save vs DC {dc}: {save_word} "
                    f"{'— RESISTED' if resisted else '— FAILED'}",
                    sv["total"], visibility="dm", is_dm=is_dm,
                    meta={"mode": "opposed-save", "dc": dc})

    if resisted:
        sys_msg(room_id, f"🤼 {dfn['name']} resists {att['name']}'s "
                         f"{'grapple' if grapple else 'shove'}.")
        return

    if grapple:
        conds = CND.add(CND.load(target), "grappled", 0, "", src=tok["id"], dc=dc)
        payload = db.json_dumps(conds)
        db.x("UPDATE tokens SET conds=? WHERE id=?", (payload, target["id"]))
        await send_cond_bump(room_id, {**target, "conds": payload}, conds)
        sys_msg(room_id, f"🤼 {att['name']} grapples {target['label']} (escape DC {dc}).")
        return

    if mode == "prone":
        await knock_prone(room_id, target, actor=att["name"])
        return
    dest = _push_dest(room_id, tok, target)
    if dest is not None:
        from .moveforced import apply_forced_move
        await apply_forced_move(room_id, target, "shove", dest,
                                chronicle=f"🤼 {att['name']} shoves {target['label']} 5 feet away.")


async def handle_grapple(ws, room_id, user, is_dm, msg):
    await _special_melee(ws, room_id, user, is_dm, msg, grapple=True)


async def handle_shove(ws, room_id, user, is_dm, msg):
    await _special_melee(ws, room_id, user, is_dm, msg, grapple=False)


# ---------------------------------------------------------------------------
# Escape — a fixed-DC check (Athletics or Acrobatics), not a re-contest.
# ---------------------------------------------------------------------------

async def handle_escape(ws, room_id, user, is_dm, msg):
    op = str(msg.get("op_id", ""))[:40] or None
    tok = db.q1("SELECT * FROM tokens WHERE id=? AND room_id=?",
                (msg.get("token_id", -1), room_id))
    if tok is None or not authz.controls(tok, user["id"], is_dm):
        return await send_to(ws, "error", {"msg": "Not your token"})
    entry = CND.has(CND.load(tok), "grappled")
    if entry is None:
        return await send_to(ws, "error", {"msg": "You are not grappled"})
    p = opposed.participant(room_id, tok)
    if p is None:
        return await send_to(ws, "error", {"msg": "Cannot resolve this creature"})
    if not _claim(room_id, op, p["stats_id"], "escape"):
        return                                                    # replay — silent no-op
    if not await _take_action(ws, room_id, user, is_dm, tok):
        return

    dc = entry.get("dc") or 0
    grappler = None
    if entry.get("src"):
        grappler = db.q1("SELECT * FROM tokens WHERE id=? AND room_id=?",
                         (entry["src"], room_id))
    # 2024: the grapple also ends if the grappler is incapacitated or gone.
    free = grappler is None or CND.hook_bool(CND.load(grappler), room_id, "blocks_movement")
    skill = "acrobatics" if str(msg.get("use", "")).lower() == "acrobatics" else "athletics"
    res = {"kept": 20, "mod": 0, "total": 99} if free else \
        opposed.check_roll(p, skill, kind="skill", adv=msg.get("adv"))
    escaped = free or opposed.beats_dc(res["total"], dc)
    if not free:
        word = gear.SKILLS[skill][0]
        await dice_post(room_id, user,
                        f"🤼 {p['name']} — {word} check to escape (DC {dc}): "
                        f"d20({res['kept']}) {res['mod']:+d} = {res['total']} "
                        f"{'— ESCAPED' if escaped else '— held'}",
                        res["total"], visibility="self",
                        is_dm=is_dm, meta={"mode": "opposed-escape", "dc": dc})
    if not escaped:
        return
    new = CND.remove(CND.load(tok), "grappled")
    payload = db.json_dumps(new)
    db.x("UPDATE tokens SET conds=? WHERE id=?", (payload, tok["id"]))
    await send_cond_bump(room_id, {**tok, "conds": payload}, new)
    sys_msg(room_id, f"🤼 {tok['label']} escapes the grapple.")


# ---------------------------------------------------------------------------
# Grapple ends when the grappled creature leaves the grappler's reach.
# ---------------------------------------------------------------------------

async def end_grapples_out_of_reach(room_id, moved_tok):
    """After a token moved: drop a grapple it BEARS whose grappler is gone/out of
    reach, and a grapple it CAUSES (as grappler) on any creature now out of its
    reach. Called from ``moveforced`` (any forced move, incl. a shove) and from
    ``movement`` (a grappler walking away). Returns True if anything changed."""
    changed = False
    pending = []

    def _drop(token):
        nonlocal changed
        payload = db.json_dumps(CND.remove(CND.load(token), "grappled"))
        db.x("UPDATE tokens SET conds=? WHERE id=?", (payload, token["id"]))
        changed = True
        pending.append((token, payload))

    # The moved token is itself grappled by someone (its ``src``).
    for c in CND.load(moved_tok):
        if c.get("k", "").lower() != "grappled" or c.get("src") is None:
            continue
        g = db.q1("SELECT * FROM tokens WHERE id=? AND room_id=?", (c["src"], room_id))
        if g is None or not _adjacent(room_id, g, moved_tok):
            _drop(moved_tok)
            break

    # The moved token is a GRAPPLER; recheck everyone it is holding.
    for t in db.q("SELECT * FROM tokens WHERE room_id=? AND id!=?",
                  (room_id, moved_tok["id"])):
        if any(c.get("k", "").lower() == "grappled" and c.get("src") == moved_tok["id"]
               and not _adjacent(room_id, moved_tok, t) for c in CND.load(t)):
            _drop(t)

    for token, payload in pending:
        await send_cond_bump(room_id, {**token, "conds": payload}, db.j(payload, []))
    return changed
