"""D113 (Sprint 42): the 2024 concentration lifecycle, server-authoritative.

Concentration has ONE representation it has always had — the ``concentrating``
condition flag (D59) on a token's ``conds``. This module adds only the rules
2024 attaches to that flag and reuses every existing engine:

  * the saving throw runs through ``room.opposed.save_roll`` (``do_roll`` +
    ``gear.save_bonus`` + the ``my_saves_dis`` / ``auto_fail_saves`` hooks) — the
    SAME d20 channel a normal save uses; there is no second dice path;
  * ending a concentration clears the flag AND every condition LINKED to that
    concentrator (the additive ``conc`` token-id stamp, D113), so a spell's
    effects end with its concentration — across every token in the room;
  * delivery uses the existing visibility-gated condition bump + snapshot and
    the ``sys_msg`` / DM-whisper channels a PC line / an NPC line deserve.

Triggers and reactions NEVER chain out of here: losing concentration mutates
conditions only; it never rolls damage or fires an ``effectops`` trigger.
"""
from .. import db
from .. import conditions as C


def _room_tokens(room_id):
    return db.q("SELECT * FROM tokens WHERE room_id=?", (room_id,))


def _write(room_id, tok_id, conds):
    db.x("UPDATE tokens SET conds=? WHERE id=?", (db.json_dumps(conds), tok_id))


async def _clear(room_id, caster):
    """Remove the ``concentrating`` flag on the caster plus every condition in
    the room linked to it (``conc`` == caster token id). Visibility-correct
    bumps; returns the changed ``(token, conds)`` pairs. No flavour, no save."""
    cid = caster["id"]
    changed = []
    me = db.q1("SELECT * FROM tokens WHERE id=?", (cid,))
    if me is not None:
        old = C.load(me)
        new = C.strip_link(C.remove(old, "concentrating"), cid)
        if new != old:
            _write(room_id, cid, new)
            changed.append((me, new))
    for t in _room_tokens(room_id):
        if t["id"] == cid or not C.has_link(C.load(t), cid):
            continue
        old = C.load(t)
        new = C.strip_link(old, cid)
        if new != old:
            _write(room_id, t["id"], new)
            changed.append((t, new))
    from .visibility import send_cond_bump
    for t, conds in changed:
        await send_cond_bump(room_id, t, conds)
    return changed


async def end_previous(room_id, tok):
    """2024: casting a NEW concentration spell ends the previous one. Called the
    instant a concentration ability starts, BEFORE its own effects land, so the
    old concentration's linked conditions are already gone and the new ones
    survive. No flavour, no save."""
    me = db.q1("SELECT * FROM tokens WHERE id=?", (tok["id"],))
    if me is None or not C.is_concentrating(C.load(me)):
        return []
    return await _clear(room_id, me)


async def break_link(room_id, tok, reason="", announce=True):
    """End a concentration outright (failed save, going down, incapacitated,
    replaced): clear the flag + every linked condition, then announce + snapshot.
    ``announce=False`` keeps it silent (used mid-replacement)."""
    me = db.q1("SELECT * FROM tokens WHERE id=?", (tok["id"],))
    if me is None or not C.is_concentrating(C.load(me)):
        return []
    changed = await _clear(room_id, me)
    if announce and changed:
        from .net import broadcast, sys_msg
        sys_msg(room_id, f"✨ {me['label']} loses concentration"
                + (f" ({reason})" if reason else "") + ".")
        await broadcast(room_id, "snapshot", None)
    return changed


async def on_damage(room_id, tok, hp_lost, downed=False):
    """THE concentration response to damage (2024). A no-op when the creature is
    not concentrating or lost no HP. DC = max(10, floor(hp_lost/2)), uncapped,
    where ``hp_lost`` is the HP ACTUALLY lost (after resistance AND temp HP) —
    the damage reducer passes exactly that. Going to 0 HP breaks concentration
    outright (no save); otherwise a CON saving throw decides."""
    if tok is None or hp_lost is None or int(hp_lost) <= 0:
        return []
    me = db.q1("SELECT * FROM tokens WHERE id=?", (tok["id"],))
    if me is None or not C.is_concentrating(C.load(me)):
        return []
    if downed:
        return await break_link(room_id, me, "down")
    from . import opposed
    p = opposed.participant(room_id, me)
    if p is None:
        return await break_link(room_id, me, "incapacitated")
    sv = opposed.save_roll(p, "con")
    dc = max(10, int(int(hp_lost) // 2))
    ok = bool(sv) and not sv.get("auto_fail") and sv["total"] >= dc
    mod = (sv or {}).get("mod", 0)
    line = (f"🧠 {p['name']} concentration check — CON save "
            + (f"d20({sv['kept']}) {mod:+d} = {sv['total']} vs DC {dc}"
               if sv and not sv.get("auto_fail") else "AUTO-FAIL")
            + (" → holds" if ok else " → BROKEN"))
    await _announce_roll(room_id, me, line)
    return await break_link(room_id, me, "damage") if not ok else []


async def enforce_after_condition(room_id, tok):
    """Called after any condition write: a concentration-ending state (2024
    incapacitated family) landing on a concentrating creature ends it."""
    me = db.q1("SELECT * FROM tokens WHERE id=?", (tok["id"],))
    if me is None:
        return []
    conds = C.load(me)
    if C.is_concentrating(conds) and C.blocks_concentration(conds):
        return await break_link(room_id, me, "incapacitated")
    return []


async def _announce_roll(room_id, tok, line):
    """A PC concentration check is table knowledge → a public system line. An
    NPC's is DM-only, so it never names a creature the players cannot see."""
    from .net import send_user, sys_msg
    if tok.get("character_id"):
        sys_msg(room_id, line)
        return
    dm = db.q1("SELECT dm_id FROM rooms WHERE id=?", (room_id,))
    if dm is not None:
        await send_user(room_id, dm["dm_id"], "whisper", {"text": line})
