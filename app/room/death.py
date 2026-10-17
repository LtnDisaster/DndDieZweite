"""Death saving throws for player characters (5e rules, token-scoped).

A character that drops to 0 HP enters the dying state; from then on each save is a
straight d20: 10+ succeeds, below 10 fails, a natural 20 lets the character regain
1 HP and become conscious, and a natural 1 counts as two failures. Three successes
stabilise (no more saves needed); three failures kill. Damage taken while at 0 adds a
failure (and instant-kills on damage that meets or exceeds the maximum HP). The state
lives on the **token** (``tokens.death``), because it is a play-time combat condition —
not part of the character library.
NPC/monster tokens never enter it: they just sit at 0 HP.
"""
from .. import conditions as CND
from .. import gear, db
from . import authz, combat as CMB
from .dice import dice_post, do_roll
from .grapple import _adjacent
from .net import broadcast, send_to, sys_msg


def clean_death(raw):
    d = db.j(raw, None) if isinstance(raw, str) else raw
    if not isinstance(d, dict):
        return None
    s = max(0, min(3, int(d.get("s", 0) or 0)))
    f = max(0, min(3, int(d.get("f", 0) or 0)))
    return {"s": s, "f": f, "stable": bool(d.get("stable")), "dead": bool(d.get("dead"))}


def load(tok):
    return clean_death(tok.get("death")) if tok else None


def new():
    return {"s": 0, "f": 0, "stable": False, "dead": False}


def apply_thresholds(d):
    if d["dead"]:
        return d
    if d["s"] >= 3:
        d["s"] = 3
        d["stable"] = True
    if d["f"] >= 3:
        d["f"] = 3
        d["dead"] = True
    return d


def _save(d, nat):
    """Apply one d20 death save; returns the human-readable verdict."""
    if nat == 1:
        d["f"] = min(3, d["f"] + 2)
        return "✗✗ natural 1 (two failures)"
    if nat >= 10:
        d["s"] = min(3, d["s"] + 1)
        return "✓ success"
    d["f"] = min(3, d["f"] + 1)
    return "✗ fail"


def _pc(room_id, user, is_dm, msg):
    tok = db.q1("SELECT * FROM tokens WHERE id=? AND room_id=?", (msg.get("token_id", -1), room_id))
    if tok is None or tok["character_id"] is None:
        return None                              # missing, or an NPC (no death saves)
    if not authz.controls(tok, user["id"], is_dm):   # D82: owner or assigned controller
        return False
    return tok


async def handle_death_save(ws, room_id, user, is_dm, msg):
    tok = _pc(room_id, user, is_dm, msg)
    if tok is None:
        return
    if tok is False:
        await send_to(ws, "error", {"msg": "Not your character"})
        return
    ch = gear.as_sheet(db.q1("SELECT * FROM characters WHERE id=?", (tok["character_id"],)))
    death = load(tok)
    if ch is None or ch["hp"] > 0 or death is None or death["stable"] or death["dead"]:
        await send_to(ws, "error", {"msg": "Not making death saves right now"})
        return
    nat = do_roll("1d20", msg.get("adv"))["kept"]
    if nat == 20:
        with db.tx() as c:
            c.execute("UPDATE characters SET hp=1 WHERE id=?", (ch["id"],))
            c.execute("UPDATE tokens SET death=NULL WHERE id=?", (tok["id"],))
        await dice_post(room_id, user, f"☠ {ch['name']} death save: d20({nat}) — "
                        "natural 20, regains 1 HP and becomes conscious", 20,
                        visibility=msg.get("visibility"), is_dm=is_dm)
        await broadcast(room_id, "death", {"token_id": tok["id"], "death": None})
        await broadcast(room_id, "snapshot", None)
        return
    verdict = _save(death, nat)
    apply_thresholds(death)
    db.x("UPDATE tokens SET death=? WHERE id=?", (db.json_dumps(death), tok["id"]))
    await dice_post(room_id, user, f"☠ {ch['name']} death save: d20({nat}) — {verdict}", nat,
                    visibility=msg.get("visibility"), is_dm=is_dm)
    if death["dead"]:
        sys_msg(room_id, f"☠ {ch['name']} has died.")
    elif death["stable"]:
        sys_msg(room_id, f"{ch['name']} is stable.")
    await broadcast(room_id, "death", {"token_id": tok["id"], "death": death})


async def handle_stabilize(ws, room_id, user, is_dm, msg):
    """D136 (AP-022, audit F8): 2024 Help-to-Stabilize is a DC 10 Wisdom
    (Medicine) CHECK, not an automatic pass. It costs the actor's Action in
    combat (incapacitation gates apply, D134), needs adjacency and touches
    no death-save counters on failure. Natural 20 on the check: the patient
    regains 1 HP."""
    tok = _pc(room_id, user, is_dm, msg)
    if tok is False:
        await send_to(ws, "error", {"msg": "Not your character"})
        return
    tgt = db.q1("SELECT * FROM tokens WHERE id=? AND room_id=?",
                (msg.get("target_token_id", -1), room_id))
    if tgt is None or tgt["character_id"] is None:
        await send_to(ws, "error", {"msg": "No patient token in this room"})
        return
    if tok is not None and tgt["id"] == tok["id"]:
        await send_to(ws, "error", {"msg": "You can't stabilize yourself"})
        return
    death = load(tgt)
    if death is None or death["stable"] or death["dead"]:
        await send_to(ws, "error", {"msg": "That creature does not need stabilizing"})
        return
    if tok is not None and CND.hook_bool(CND.load(tok), room_id, "no_actions"):
        await send_to(ws, "error", {"msg": "You can't take actions right now"})
        return
    if not is_dm:
        if tok is None:
            await send_to(ws, "error", {"msg": "Pick your token (token_id)"})
            return
        if not _adjacent(room_id, tok, tgt):
            await send_to(ws, "error", {"msg": "Stabilizing needs you next to the patient"})
            return
        init = CMB.get_init(room_id)
        if init.get("combat"):
            listed = any(o.get("token_id") == tok["id"] for o in init.get("order", []))
            if listed:
                turn = init.get("turn") or {}
                if turn.get("token_id") != tok["id"]:
                    await send_to(ws, "error", {"msg": "It is not your turn"})
                    return
                if turn.get("action") == "used":
                    await send_to(ws, "error", {"msg": "No action left this turn"})
                    return
                turn["action"] = "used"
                CMB.set_init(room_id, init)
    ch = gear.as_sheet(db.q1("SELECT * FROM characters WHERE id=?",
                             (tok["character_id"] if tok else tgt["character_id"],)))
    bonus, _ = gear.skill_bonus(ch, db.j(ch["skills"], {}) or {}, "medicine")
    res = do_roll("1d20", msg.get("adv"))
    nat, total = res["kept"], res["kept"] + bonus
    pch = gear.as_sheet(db.q1("SELECT * FROM characters WHERE id=?",
                              (tgt["character_id"],)))
    if nat == 20:
        with db.tx() as c:
            c.execute("UPDATE characters SET hp=1 WHERE id=?", (tgt["character_id"],))
            c.execute("UPDATE tokens SET death=NULL WHERE id=?", (tgt["id"],))
        await dice_post(room_id, user, f"🩺 {ch['name']} → {pch['name']}: "
                        f"d20({nat}) {bonus:+d} = {total} — natural 20, regains 1 HP",
                        total, visibility=msg.get("visibility"), is_dm=is_dm)
        await broadcast(room_id, "death", {"token_id": tgt["id"], "death": None})
    elif total >= 10:
        death["stable"] = True
        db.x("UPDATE tokens SET death=? WHERE id=?", (db.json_dumps(death), tgt["id"]))
        await dice_post(room_id, user, f"🩺 {ch['name']} → {pch['name']}: "
                        f"d20({nat}) {bonus:+d} = {total} (DC 10) — stable",
                        total, visibility=msg.get("visibility"), is_dm=is_dm)
        sys_msg(room_id, f"{pch['name']} is stable.")
        await broadcast(room_id, "death", {"token_id": tgt["id"], "death": death})
    else:
        await dice_post(room_id, user, f"🩺 {ch['name']} → {pch['name']}: "
                        f"d20({nat}) {bonus:+d} = {total} (DC 10) — the patient "
                        "stays dying", total, visibility=msg.get("visibility"),
                        is_dm=is_dm)
    await broadcast(room_id, "snapshot", None)


async def handle_death_clear(ws, room_id, user, is_dm, msg):
    """DM override: clear/reset the dying state on a token (revivify, story, etc.)."""
    if not is_dm:
        return
    tok = db.q1("SELECT * FROM tokens WHERE id=? AND room_id=?", (msg.get("token_id", -1), room_id))
    if tok is None or tok["character_id"] is None:
        return
    db.x("UPDATE tokens SET death=NULL WHERE id=?", (tok["id"],))
    await broadcast(room_id, "death", {"token_id": tok["id"], "death": None})
