"""D112 (Sprint 41): Taschendiebstahl — server-authoritative pickpocketing.

A thief reaches an adjacent, visible creature and makes a Dexterity (Sleight of
Hand) check against that creature's Perception. Because D&D 2024 REMOVED passive
perception (``RULES_AUDIT_2024`` A7), "how hard was it to notice" is either a
DM-set fixed notice DC or a real Perception check the engine rolls for the
target — the caller picks; the engine never forces an opposed roll.

Two transfer models, both shipped:

  A. DM-mediated (always available): ``handle_pickpocket`` runs the concealed
     check and reports the result ONLY to the DM. Nothing is revealed to the
     thief and no item moves; the DM, who can see the victim's gear, moves the
     chosen item with the existing DM grant/hand-off tools. Zero leak.

  B. Auto-steal of a DM-authorised subset: a DM flags specific instances
     ``pick`` (``handle_pickable``). ``handle_pickpocket_take`` is fully
     self-contained — validate gate, verify the item IS pick-flagged, roll the
     check, and on a CLEAN steal atomically move that ONE item to the thief via
     the existing ``inventory.transfer`` (PC victim) / ``container_give``
     (NPC container). An unflagged or unknown item answers exactly like a failed
     check, so ``pick`` status is never an oracle; a thief only ever learns an
     item's name once the steal has actually succeeded.

The theft SUCCEEDING (item leaves the victim) and being DISCOVERED are reported
separately to the DM so discovery can be adjudicated apart from the outcome.
Replay/concurrency are guarded by the same ``inventory._claim`` op-id guard; the
action slot is validated before it is spent (no cost for a pre-invalid attempt).
"""
from .. import db, gear, npc
from .. import inventory as INV
from . import authz, opposed
from .dice import _visible_to_member, dice_post
from .grapple import _adjacent, _take_action
from .net import broadcast, send_to

NOTICE = ("sleight_of_hand",)


def _oid(tok):
    return f"tok:{int(tok['id'])}"


def _is_npc(tok):
    return tok["character_id"] is None and npc.load(tok) is not None


def _clean_notice_dc(msg):
    v = msg.get("notice_dc")
    if v in (None, "", 0):
        return None
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if 1 <= n <= 30 else None


async def _claim(room_id, op_id, ns, kind):
    if not op_id:
        return True
    with db.tx() as c:
        return INV._claim(c, op_id, room_id, kind, ns)


async def _steal_gate(ws, room_id, user, is_dm, msg):
    """Actor controls own character token; target exists, is visible, same plane,
    adjacent. Returns (actor_tok, target_tok, thief_char) or None (error sent)."""
    tok = db.q1("SELECT * FROM tokens WHERE id=? AND room_id=?",
                (msg.get("token_id", -1), room_id))
    if tok is None or not authz.controls(tok, user["id"], is_dm):
        await send_to(ws, "error", {"msg": "You can only act through your own character"})
        return None
    if tok["character_id"] is None:
        await send_to(ws, "error", {"msg": "Pickpocket through your own character"})
        return None
    thief = gear.as_sheet(db.q1("SELECT * FROM characters WHERE id=?", (tok["character_id"],)))
    if thief is None:
        await send_to(ws, "error", {"msg": "Bring a character to the table first"})
        return None
    target = db.q1("SELECT * FROM tokens WHERE id=? AND room_id=?",
                   (msg.get("target_id", -1), room_id))
    if target is None or target["id"] == tok["id"] or \
            (not is_dm and not _visible_to_member(user["id"], room_id, target)):
        await send_to(ws, "error", {"msg": "No target token"})   # hidden == absent (D94)
        return None
    if not _adjacent(room_id, tok, target):
        await send_to(ws, "error", {"msg": "You must be right next to them"})
        return None
    return tok, target, thief


def _roll_perception(room_id, target, adv):
    dfn = opposed.participant(room_id, target)
    if dfn is None:
        return None
    return opposed.check_roll(dfn, "perception", "skill", adv=adv)


async def _resolve_sleight(room_id, user, is_dm, tok, target, msg, tag):
    """Roll the Sleight-of-Hidden check and its Perception response. Returns
    ``(soh_total, unnoticed)`` after posting BOTH rolls to the DM only, or
    ``None`` if the check could not be resolved."""
    thief_p = opposed.participant(room_id, tok)
    soh = opposed.check_roll(thief_p, "sleight_of_hand", "skill", adv=msg.get("adv"))
    if soh is None:
        return None
    await dice_post(room_id, user,
                    f"🤝 {thief_p['name']} — {tag} Sleight of Hand "
                    f"(hidden): d20({soh['kept']}) {soh['mod']:+d} = {soh['total']}",
                    soh["total"], visibility="dm", is_dm=is_dm,
                    meta={"mode": "pickpocket", "who": "thief"})
    notice_dc = _clean_notice_dc(msg)
    if notice_dc is not None:
        unnoticed = opposed.beats_dc(soh["total"], notice_dc)
        await dice_post(room_id, user,
                        f"👁 {target['label']} — notice DC {notice_dc}: "
                        f"{'NOT noticed' if unnoticed else 'NOTICED'}",
                        notice_dc, visibility="dm", is_dm=is_dm,
                        meta={"mode": "pickpocket", "who": "notice"})
        return soh["total"], unnoticed
    per = _roll_perception(room_id, target, msg.get("adv"))
    if per is None:
        unnoticed = True
    else:
        unnoticed = opposed.opposed_wins(soh["total"], per["total"], tie="defender")
        await dice_post(room_id, user,
                        f"👁 {target['label']} — Perception check: "
                        f"d20({per['kept']}) {per['mod']:+d} = {per['total']} "
                        f"{'— did NOT notice' if unnoticed else '— NOTICED the theft'}",
                        per["total"], visibility="dm", is_dm=is_dm,
                        meta={"mode": "pickpocket", "who": "perception"})
    return soh["total"], unnoticed


# ---------------------------------------------------------------------------
# A. DM-mediated attempt (concealed check; no item moves)
# ---------------------------------------------------------------------------

async def handle_pickpocket(ws, room_id, user, is_dm, msg):
    op = str(msg.get("op_id", ""))[:40] or None
    res = await _steal_gate(ws, room_id, user, is_dm, msg)
    if res is None:
        return
    tok, target, thief = res
    if not await _claim(room_id, op, thief["id"], "pickpocket_try"):
        return                                                    # replay — silent
    if not await _take_action(ws, room_id, user, is_dm, tok):
        return
    out = await _resolve_sleight(room_id, user, is_dm, tok, target, msg, "attempts")
    if out is None:
        return await send_to(ws, "error", {"msg": "Cannot resolve this character"})
    _soh, unnoticed = out
    # The attempt is COVERT: the thief learns only that they tried, and the
    # outcome goes to the DM alone — never a room-wide chronicle (that would
    # tell the table a theft is happening).
    await send_to(ws, "whisper", {"text": "🤝 Your attempt is made covertly — the "
                                          "DM sees the result."})
    await dice_post(room_id, user,
                    f"🤝 {'Noticed' if unnoticed else 'Unnoticed'} attempt near "
                    f"{target['label']}.", None, visibility="dm", is_dm=is_dm,
                    meta={"mode": "pickpocket", "who": "outcome"})


# ---------------------------------------------------------------------------
# B. Auto-steal of a DM-authorised (``pick``) instance
# ---------------------------------------------------------------------------

def _pick_entry(room_id, target, item_id):
    """Return the target's item entry ONLY when the DM flagged it ``pick``;
    otherwise None (a non-flagged / unknown item is indistinguishable from a
    failed attempt — never an oracle for the victim's inventory)."""
    if _is_npc(target):
        items = INV.container_peek(room_id, _oid(target), curse=False)
    elif target["character_id"]:
        row = db.q1("SELECT items FROM characters WHERE id=?", (target["character_id"],))
        items = gear.clean_items(db.j((row or {}).get("items"), []))
    else:
        return None
    it = INV.find(items, item_id)
    return it if (it and it.get("pick")) else None


async def handle_pickpocket_take(ws, room_id, user, is_dm, msg):
    op = str(msg.get("op_id", ""))[:40] or None
    item_id = str(msg.get("item_id", ""))[:16]
    qty = msg.get("qty", 1)
    res = await _steal_gate(ws, room_id, user, is_dm, msg)
    if res is None:
        return
    tok, target, thief = res
    if not await _claim(room_id, op, thief["id"], "pickpocket"):
        return                                                    # replay — silent
    if not await _take_action(ws, room_id, user, is_dm, tok):
        return

    # Roll the check first; a detected attempt moves nothing.
    out = await _resolve_sleight(room_id, user, is_dm, tok, target, msg, "lifts from")
    if out is None:
        return await send_to(ws, "error", {"msg": "Cannot resolve this character"})
    _soh, unnoticed = out

    entry = _pick_entry(room_id, target, item_id)
    if not unnoticed or entry is None:
        # Either noticed, or the item was not an authorised steal — the thief
        # learns NOTHING either way (a failed probe cannot distinguish them).
        await send_to(ws, "whisper", {"text": "🤝 You fail to lift anything."})
        return

    try:
        if _is_npc(target):
            moved = INV.container_give(room_id, _oid(target), thief["id"], item_id, qty)
        else:
            moved = INV.transfer(room_id, target["character_id"], thief["id"], item_id, qty)
    except INV.InvError as ex:
        # Only a DM can see the real reason; a player sees the generic failure.
        await send_to(ws, "whisper", {"text": "🤝 You fail to lift anything."})
        await dice_post(room_id, user,
                        f"🤝 Steal failed after the check: {ex}", None,
                        visibility="dm", is_dm=is_dm, meta={"mode": "pickpocket"})
        return
    if moved == "replay":
        return

    await broadcast(room_id, "inv_changed", None)          # the thief's sheet refreshes
    # D113: a lifted item that changes hands fires an active on_transfer curse on
    # the THIEF now carrying it — DM-only announcement, keyed to this op (no
    # double-fire). Reads of the victim's purse earlier never reached this.
    from .inv import _item_transfer_effects
    await _item_transfer_effects(room_id, thief["id"], moved["name"], op or "")
    await send_to(ws, "whisper",
                  {"text": f"🤝 You lift {moved['qty']} × {moved['name']} from "
                           f"{target['label']} — unnoticed."})
    await dice_post(room_id, user,
                    f"🤝 {thief['name']} lifts {moved['qty']} × {moved['name']} from "
                    f"{target['label']} unnoticed.", None,
                    visibility="dm", is_dm=is_dm, meta={"mode": "pickpocket", "item": item_id})


# ---------------------------------------------------------------------------
# DM authoring of the ``pick`` flag (which instances a thief may attempt)
# ---------------------------------------------------------------------------

async def handle_pickable(ws, room_id, user, is_dm, msg):
    if not is_dm:
        return await send_to(ws, "error", {"msg": "DM only"})
    value = str(msg.get("action", "set")) != "clear"
    item_id = str(msg.get("item_id", ""))[:16]
    if not item_id:
        return await send_to(ws, "error", {"msg": "Which item?"})
    op = str(msg.get("op_id", ""))[:40] or None
    try:
        if msg.get("token_id") not in (None, "", 0):
            tok = db.q1("SELECT * FROM tokens WHERE id=? AND room_id=?",
                        (msg.get("token_id", -1), room_id))
            if not _is_npc(tok):
                return await send_to(ws, "error", {"msg": "No such NPC here"})
            res = INV.container_set_pick(room_id, _oid(tok), item_id, value, op)
            await send_to(ws, "inv_contents",
                          {"object_id": _oid(tok), "label": tok["label"] or "NPC",
                           "floor": tok["floor"] or "",
                           "items": INV.container_peek(room_id, _oid(tok), curse=is_dm),
                           "coins": INV.container_coins_peek(room_id, _oid(tok)),
                           "npc_token": tok["id"]})
        else:
            char = db.q1("SELECT * FROM characters WHERE id=?", (msg.get("char_id", -1),))
            if char is None or db.q1("SELECT 1 AS hit FROM room_members "
                                     "WHERE room_id=? AND character_id=?",
                                     (room_id, char["id"])) is None:
                return await send_to(ws, "error", {"msg": "No such character"})
            res = INV.set_pick_char(room_id, char["id"], item_id, value, op)
            await broadcast(room_id, "inv_changed", None)     # payload-less refresh
    except INV.InvError as ex:
        return await send_to(ws, "error", {"msg": str(ex)})
    if res == "replay":
        return await send_to(ws, "whisper", {"text": "⚠️ That was already applied."})
    flag = "authorised for a steal" if res["pick"] else "no longer stealable"
    await send_to(ws, "whisper", {"text": f"🤝 {res['name']} is {flag}."})
