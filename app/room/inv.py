"""Inventory / equipment / container transports (Sprint 22, D92).

Thin handlers ONLY: authorisation here, mutation exclusively through
app/inventory.py (the SSOT). Sheet rights = character owner or the DM — a
D82 token CONTROLLER may act through a token but never edits the sheet (same
rule as attune). Containers are D82 world objects (editor, fog, dm_only,
reach); contents live in SQLite and are transmitted ONLY through an
authorised inspect — never via /state or broadcasts.
"""
from .. import db, events, floors as FLOOR, gear, inventory as INV
from . import authz, chat as CHAT
from .interact import _reach_cells
from .net import broadcast, dm_whisper, get_map, send_to, send_user, sys_msg

OPID = 40


def _op(msg):
    v = str(msg.get("op_id") or "")[:OPID].strip()
    return v or None


def _coins_to_cp(msg):
    """(integer amount, coin id) -> copper, via the SSOT converter. A client can
    only ever send a denomination + whole count — never a raw copper total."""
    from .. import gear
    try:
        return gear.to_cp(msg.get("amount"), msg.get("coin", "cp"))
    except ValueError as ex:
        raise INV.InvError(str(ex))


async def _sheet_char(ws, room_id, user, is_dm, msg):
    """Character of THIS room whose sheet the sender may manage, else None."""
    ch = db.q1("SELECT * FROM characters WHERE id=?", (msg.get("char_id", -1),))
    if ch is None:
        await send_to(ws, "error", {"msg": "No such character"})
        return None
    if db.q1("SELECT 1 AS hit FROM room_members WHERE room_id=? AND character_id=?",
             (room_id, ch["id"])) is None:
        await send_to(ws, "error", {"msg": "No such character"})
        return None
    if not is_dm and ch["user_id"] != user["id"]:
        await send_to(ws, "error", {"msg": "Not your character"})
        return None
    return ch


# ---------- item definitions (DM template library) ----------

async def handle_item_def(ws, room_id, user, is_dm, msg):
    if not is_dm:
        await send_to(ws, "error", {"msg": "DM only"})
        return
    action = str(msg.get("action", ""))
    if action in ("create", "update"):
        d = INV.clean_def(msg.get("defn") or {})
        if d is None:
            await send_to(ws, "error", {"msg": "Invalid item definition"})
            return
        did = d.pop("id") or "def" + _rand()
        # D100: item_defs.id is global. Never clobber another room's definition —
        # a same-room id updates in place, a foreign id is refused outright (a
        # per-room key would need a destructive rebuild, so the conflict is made
        # explicit instead of silently overwriting the other room's library row).
        owner = db.q1("SELECT room_id FROM item_defs WHERE id=?", (did,))
        if owner is not None and owner["room_id"] != room_id:
            await send_to(ws, "error", {"msg": "That definition id is already used by "
                                               "another room — choose a different id"})
            return
        db.x("INSERT INTO item_defs(id, room_id, name, desc, kind, weight, stackable,"
             " props, created_by, value) VALUES(?,?,?,?,?,?,?,?,?,?)"
             " ON CONFLICT(id) DO UPDATE SET name=excluded.name, desc=excluded.desc,"
             " kind=excluded.kind, weight=excluded.weight, stackable=excluded.stackable,"
             " props=excluded.props, value=excluded.value",
             (did, room_id, d["name"], d["desc"], d["kind"], d["weight"],
              d["stackable"], db.json_dumps(d["props"]), user["id"], d["value"]))
        await send_to(ws, "whisper", {"text": f"📚 Item definition “{d['name']}” saved."})
    elif action == "delete":
        did = str(msg.get("def_id", ""))[:24]
        db.x("DELETE FROM item_defs WHERE id=? AND room_id=?", (did, room_id))
    else:
        return
    await broadcast(room_id, "inv_changed", None)


def _rand():
    import uuid
    return uuid.uuid4().hex[:8]


# ---------- DM grant / remove ----------

async def handle_inv_grant(ws, room_id, user, is_dm, msg):
    if not is_dm:
        await send_to(ws, "error", {"msg": "DM only"})
        return
    ch = db.q1("SELECT * FROM characters WHERE id=?", (msg.get("char_id", -1),))
    if ch is None or db.q1("SELECT 1 AS hit FROM room_members WHERE room_id=? AND character_id=?",
                           (room_id, ch["id"])) is None:
        await send_to(ws, "error", {"msg": "No such character"})
        return
    try:
        qty = int(msg.get("qty", 1))
    except (TypeError, ValueError):
        qty = -1
    if qty < 1 or qty > 9999:
        await send_to(ws, "error", {"msg": "Quantity must be 1–9999"})
        return
    entries = []
    d = db.q1("SELECT * FROM item_defs WHERE id=? AND room_id=?",
              (str(msg.get("def_id", ""))[:24], room_id))
    if d is not None:
        entries.append(INV.entry_from_def(d, qty))
    else:                                   # ad-hoc item authored right here
        e = INV.clean_def(msg.get("item") or {})
        if e is None:
            await send_to(ws, "error", {"msg": "Define an item or pick a definition"})
            return
        e.pop("id")
        e["qty"] = qty
        entries.append(_ad_clean(e))
    try:
        res = INV.grant(room_id, ch["id"], entries, _op(msg))
    except INV.InvError as ex:
        await send_to(ws, "error", {"msg": str(ex)})
        return
    if res == "replay":
        await send_to(ws, "whisper", {"text": "⚠️ That grant was already applied."})
        return
    await broadcast(room_id, "inv_changed", None)
    names = ", ".join(f"{r['qty']} × {r['name']}" for r in res)
    sys_msg(room_id, f"🎒 The DM grants {ch['name']} {names}.")
    if ch["user_id"] != user["id"]:
        await send_user(room_id, ch["user_id"], "whisper",
                        {"text": f"🎒 The DM grants you {names}."})


def _ad_clean(e):
    """Run an ad-hoc definition payload through the item sanitizer."""
    from .. import gear
    return gear.clean_items([e])[0]


async def handle_inv_remove(ws, room_id, user, is_dm, msg):
    if not is_dm:
        await send_to(ws, "error", {"msg": "DM only"})
        return
    ch = db.q1("SELECT * FROM characters WHERE id=?", (msg.get("char_id", -1),))
    if ch is None or db.q1("SELECT 1 AS hit FROM room_members WHERE room_id=? AND character_id=?",
                           (room_id, ch["id"])) is None:
        await send_to(ws, "error", {"msg": "No such character"})
        return
    try:
        res = INV.remove(room_id, ch["id"], str(msg.get("item_id", ""))[:16],
                         msg.get("qty", 1), _op(msg))
    except INV.InvError as ex:
        await send_to(ws, "error", {"msg": str(ex)})
        return
    if res == "replay":
        await send_to(ws, "whisper", {"text": "⚠️ That action was already applied."})
        return
    await broadcast(room_id, "inv_changed", None)
    sys_msg(room_id, f"🎒 The DM takes {res['qty']} × {res['name']} from {ch['name']}.")


# ---------- player stack ops + transfer ----------

async def handle_inv_adjust(ws, room_id, user, is_dm, msg):
    ch = await _sheet_char(ws, room_id, user, is_dm, msg)
    if ch is None:
        return
    action = str(msg.get("action", ""))
    if action not in ("split", "combine"):
        return
    try:
        res = INV.adjust(room_id, ch["id"], action, str(msg.get("item_id", ""))[:16],
                         other_id=str(msg.get("other_id", ""))[:16] or None,
                         qty=msg.get("qty", 1), op_id=_op(msg))
    except INV.InvError as ex:
        await send_to(ws, "error", {"msg": str(ex)})
        return
    if res == "replay":
        await send_to(ws, "whisper", {"text": "⚠️ That action was already applied."})
        return
    await broadcast(room_id, "inv_changed", None)


async def _item_transfer_effects(room_id, to_char_id, item_name, op_id=""):
    """D113 on_transfer seam: after an OWNERSHIP change committed, the NEW owner's
    carried curse fires IF it is active AND armed on_transfer. Reuses the one
    effect core; the claim is keyed to the transfer op_id so a replay or a racing
    duplicate transfer cannot fire the curse twice. Curse fragments are DM-only.
    A plain read/sync never calls this — only the committed mutation handlers do."""
    from .. import effectops
    tok = db.q1("SELECT * FROM tokens WHERE character_id=? AND room_id=? "
                "ORDER BY id LIMIT 1", (to_char_id, room_id))
    fresh = db.q1("SELECT items FROM characters WHERE id=?", (to_char_id,))
    if tok is None or fresh is None:
        return
    items = gear.clean_items(db.j(fresh["items"], []), keep_curse=True)
    cands = [i for i in items if i["name"] == item_name
               and _curse_armed(i, "on_transfer")]
    if not cands:
        return
    fired = await effectops.fire(room_id, "on_transfer", token=tok, caster=None,
                                 items=cands, round_uid=str(op_id or "") + ":transfer")
    for ctx in fired:
        for frag in ctx["log"]:
            await dm_whisper(room_id, f"✨ {frag}")


def _curse_armed(item, event):
    cur = item.get("curse")
    return bool(isinstance(cur, dict) and cur.get("active")
                and str(cur.get("trigger", "")) == event and cur.get("effects"))


async def handle_inv_transfer(ws, room_id, user, is_dm, msg):
    """Player hands items to another room member's character. Sender must own
    the source sheet (or be DM); the receiver needs no action — but BOTH
    characters must belong to members of THIS room, and debit+credit share ONE
    transaction, so a half-transfer is impossible."""
    ch = await _sheet_char(ws, room_id, user, is_dm, msg)
    if ch is None:
        return
    to_id = msg.get("to_char_id", -1)
    to = db.q1("SELECT * FROM characters WHERE id=?", (to_id,))
    if to is None or to["id"] == ch["id"]:
        await send_to(ws, "error", {"msg": "Who is that?"})
        return
    if not is_dm and db.q1("SELECT 1 AS hit FROM room_members WHERE room_id=? AND character_id=?",
                           (room_id, to["id"])) is None:
        await send_to(ws, "error", {"msg": "Who is that?"})
        return
    try:
        res = INV.transfer(room_id, ch["id"], to["id"],
                           str(msg.get("item_id", ""))[:16], msg.get("qty", 1), _op(msg))
    except INV.InvError as ex:
        await send_to(ws, "error", {"msg": str(ex)})
        return
    if res == "replay":
        await send_to(ws, "whisper", {"text": "⚠️ That transfer was already applied."})
        return
    await broadcast(room_id, "inv_changed", None)
    await _item_transfer_effects(room_id, to["id"], res["name"], _op(msg) or "")
    line = f"🤝 {ch['name']} hands {res['qty']} × {res['name']} to {to['name']}."
    sys_msg(room_id, line)


# ---------- equipment ----------

async def _item_equip_effects(room_id, ch, res, op_id=""):
    """D111 equip/unequip seam — fired AFTER the authoritative swap. The worn
    set is re-read from the DB (never from the pre-move sheet copy); the op_id
    rides the claim so a retry cannot fire twice."""
    from .. import effectops
    if not isinstance(res, dict):
        return
    tok = db.q1("SELECT * FROM tokens WHERE character_id=? AND room_id=? "
                "ORDER BY id LIMIT 1", (ch["id"], room_id))
    fresh = db.q1("SELECT items, equipment FROM characters WHERE id=?", (ch["id"],))
    if tok is None or fresh is None:
        return
    items = gear.clean_items(db.j(fresh["items"], []), keep_curse=True)
    equip = db.j(fresh["equipment"], {}) or {}
    if res.get("item"):
        worn = {v for v in equip.values() if v}
        cands = [i for i in items if i["id"] in worn]
        event = "equip"
    else:
        prev = res.get("prev")
        cands = [i for i in items if i["id"] == prev]
        event = "unequip"
    if not cands:
        return
    fired = await effectops.fire(room_id, event, token=tok, caster=tok,
                                 items=cands, round_uid=str(op_id or ""))
    for ctx in fired:
        # An item's OWN effect is the wearer's; a CURSE's effect is not — an
        # un-revealed curse must not name itself to the owner (D113).
        curse_src = ctx.get("src") == "curse"
        for frag in ctx["log"]:
            if curse_src:
                await dm_whisper(room_id, f"✨ {frag}")
            else:
                await send_user(room_id, ch["user_id"], "whisper", {"text": f"✨ {frag}"})


async def handle_inv_equip(ws, room_id, user, is_dm, msg):
    ch = await _sheet_char(ws, room_id, user, is_dm, msg)
    if ch is None:
        return
    slot = str(msg.get("slot", ""))
    item_id = str(msg.get("item_id", "") or "")[:16] or None
    try:
        res = INV.equip_slot(room_id, ch["id"], slot, item_id, _op(msg))
    except INV.InvError as ex:
        await send_to(ws, "error", {"msg": str(ex)})
        return
    if res == "replay":
        await send_to(ws, "whisper", {"text": "⚠️ That action was already applied."})
        return
    await broadcast(room_id, "inv_changed", None)
    await _item_equip_effects(room_id, ch, res, _op(msg) or "")


async def handle_inv_grip(ws, room_id, user, is_dm, msg):
    """D98: choose one/two-handed grip for an equipped versatile weapon."""
    ch = await _sheet_char(ws, room_id, user, is_dm, msg)
    if ch is None:
        return
    item_id = str(msg.get("item_id", "") or "")[:16]
    try:
        res = INV.set_grip(room_id, ch["id"], item_id, msg.get("grip", "one"), _op(msg))
    except INV.InvError as ex:
        await send_to(ws, "error", {"msg": str(ex)})
        return
    if res == "replay":
        await send_to(ws, "whisper", {"text": "⚠️ That action was already applied."})
        return
    await broadcast(room_id, "inv_changed", None)


async def handle_inv_money(ws, room_id, user, is_dm, msg):
    """D99: grant/deduct (DM) or transfer (owner) coin. Amount is ALWAYS an
    integer + denomination converted through gear.to_cp — a client can never
    send a copper total that mints money. Debit/credit are atomic and guarded
    against negative balances inside app/inventory.py."""
    from .. import gear
    action = str(msg.get("action", ""))
    try:
        cp = gear.to_cp(msg.get("amount"), msg.get("coin", "cp"))
    except ValueError as ex:
        await send_to(ws, "error", {"msg": str(ex)})
        return
    if action in ("grant", "deduct"):
        if not is_dm:
            await send_to(ws, "error", {"msg": "DM only"})
            return
        ch = db.q1("SELECT * FROM characters WHERE id=?", (msg.get("char_id", -1),))
        if ch is None or db.q1("SELECT 1 AS hit FROM room_members WHERE room_id=? AND character_id=?",
                               (room_id, ch["id"])) is None:
            await send_to(ws, "error", {"msg": "No such character"})
            return
        fn = INV.grant_coins if action == "grant" else INV.remove_coins
        verb = "gives" if action == "grant" else "takes"
        try:
            res = fn(room_id, ch["id"], cp, _op(msg))
        except INV.InvError as ex:
            await send_to(ws, "error", {"msg": str(ex)})
            return
        if res == "replay":
            await send_to(ws, "whisper", {"text": "⚠️ That action was already applied."})
            return
        await broadcast(room_id, "inv_changed", None)
        line = f"🪙 The DM {verb} {ch['name']} {gear.cp_label(cp)}."
        sys_msg(room_id, line)
        if ch["user_id"] != user["id"]:
            await send_user(room_id, ch["user_id"], "whisper", {"text": line})
        return
    if action == "transfer":
        ch = await _sheet_char(ws, room_id, user, is_dm, msg)
        if ch is None:
            return
        to = db.q1("SELECT * FROM characters WHERE id=?", (msg.get("to_char_id", -1),))
        if to is None or to["id"] == ch["id"]:
            await send_to(ws, "error", {"msg": "Who is that?"})
            return
        if db.q1("SELECT 1 AS hit FROM room_members WHERE room_id=? AND character_id=?",
                 (room_id, to["id"])) is None:
            await send_to(ws, "error", {"msg": "Who is that?"})
            return
        try:
            res = INV.transfer_coins(room_id, ch["id"], to["id"], cp, _op(msg))
        except INV.InvError as ex:
            await send_to(ws, "error", {"msg": str(ex)})
            return
        if res == "replay":
            await send_to(ws, "whisper", {"text": "⚠️ That transfer was already applied."})
            return
        await broadcast(room_id, "inv_changed", None)
        sys_msg(room_id, f"🤝 {ch['name']} hands {gear.cp_label(cp)} to {to['name']}.")
        return
    await send_to(ws, "error", {"msg": "Unknown money action"})


async def handle_inv_container(ws, room_id, user, is_dm, msg):
    """inspect / move (put-or-take) / fill / remove against a container object.
    Authorisation mirrors the D82 interact path: same plane, controlled token
    adjacent, dm_only answered as if not present, unknown = silent no-op."""
    fl = str(msg.get("floor") or "")
    if not FLOOR.exists(room_id, fl):
        return
    oid = str(msg.get("object_id", ""))[:24]
    action = str(msg.get("action", "inspect"))
    mp = get_map(room_id, fl)
    obj = next((o for o in mp.get("objects", []) if o.get("id") == oid), None)
    if obj is not None:
        if ((obj.get("interact") or {}).get("op") or {}).get("kind") != "container":
            return                                         # unknown: silent no-op
    elif oid.startswith("loot:"):
        # D133 (AP-019): an editor LOOT object flagged `container` is a REAL
        # D92 container — contents live in SQLite under the one existing
        # (room_id, object_id) key, namespace "loot:<entry id>", mirrors the
        # D105 "tok:<token_id>" carcass key. Unflagged loot keeps the legacy
        # note-pickup untouched.
        obj = next((l for l in mp.get("loot", [])
                    if l.get("id") == oid[5:] and l.get("container")), None)
        if obj is None:
            return
    else:
        return                                             # unknown: silent no-op
    if not is_dm:
        planes = {(t.get("floor") or "") for t in authz.controlled_rows(room_id, user["id"])}
        if fl not in planes:
            return                                        # elsewhere: nothing here
        if obj.get("dm_only"):
            await send_to(ws, "error", {"msg": "It isn't here."})
            return
        x0, y0 = obj["x"], obj["y"]
        near = {(x0 + dx, y0 + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)}
        if not _reach_cells(room_id, user["id"], mp, fl) & near:
            await send_to(ws, "error", {"msg": "Walk up to it first"})
            return
    ch = None
    if action in ("move", "put", "take", "coins_take"):      # need a character
        ch = db.q1("SELECT * FROM characters WHERE id=?", (msg.get("char_id", -1),))
        if ch is None or (not is_dm and ch["user_id"] != user["id"]):
            await send_to(ws, "error", {"msg": "Not your character"})
            return
        if db.q1("SELECT 1 AS hit FROM room_members WHERE room_id=? AND character_id=?",
                 (room_id, ch["id"])) is None:
            await send_to(ws, "error", {"msg": "No such character"})
            return
    if action == "inspect":
        await send_to(ws, "inv_contents",
                      {"object_id": oid, "label": obj.get("label", ""),
                       "floor": fl, "items": INV.container_peek(room_id, oid, curse=is_dm),
                       "coins": INV.container_coins_peek(room_id, oid)})
        return
    if action in ("fill", "remove", "coins_fill") and not is_dm:
        await send_to(ws, "error", {"msg": "DM only"})
        return
    try:
        if action == "fill":
            qty = int(msg.get("qty", 1))
            if qty < 1 or qty > 9999:
                raise INV.InvError("Quantity must be 1–9999")
            d = db.q1("SELECT * FROM item_defs WHERE id=? AND room_id=?",
                      (str(msg.get("def_id", ""))[:24], room_id))
            if d is not None:
                entries = [INV.entry_from_def(d, qty)]
            else:
                e = INV.clean_def(msg.get("item") or {})
                if e is None:
                    raise INV.InvError("Define an item or pick a definition")
                e.pop("id")
                e["qty"] = qty
                from .. import gear
                entries = [gear.clean_items([e])[0]]
            res = INV.container_fill(room_id, oid, entries, _op(msg))
        elif action == "remove":
            res = INV.container_remove(room_id, oid, str(msg.get("item_id", ""))[:16],
                                       msg.get("qty", 1), _op(msg))
        elif action in ("move", "put", "take"):
            res = INV.container_move(room_id, oid, ch["id"],
                                     str(msg.get("item_id", ""))[:16],
                                     msg.get("qty", 1), _op(msg))
        elif action == "coins_fill":
            res = INV.container_fill_coins(room_id, oid, _coins_to_cp(msg), _op(msg))
        elif action == "coins_take":
            res = INV.container_take_coins(room_id, ch["id"], oid,
                                           _coins_to_cp(msg), _op(msg))
        else:
            return
    except INV.InvError as ex:
        await send_to(ws, "error", {"msg": str(ex)})
        return
    if res == "replay":
        await send_to(ws, "whisper", {"text": "⚠️ That action was already applied."})
        return
    if action in ("coins_fill", "coins_take"):
        from .. import gear
        await send_to(ws, "inv_contents",
                      {"object_id": oid, "label": obj.get("label", ""),
                       "floor": fl, "items": INV.container_peek(room_id, oid, curse=is_dm),
                       "coins": INV.container_coins_peek(room_id, oid)})
        await broadcast(room_id, "inv_changed", None)
        if action == "coins_take":
            sys_msg(room_id, f"🪙 {user['username']} takes {gear.cp_label(res['cp'])}"
                             f" from the {obj['label']}.")
        return
    if action == "fill":
        await send_to(ws, "inv_contents",
                      {"object_id": oid, "label": obj.get("label", ""),
                       "floor": fl, "items": INV.container_peek(room_id, oid, curse=is_dm)})
        await broadcast(room_id, "inv_changed", None)
        return
    if action == "remove":
        await broadcast(room_id, "inv_changed", None)
        return
    # move: fresh contents back to the actor + public chronicle
    await send_to(ws, "inv_contents",
                  {"object_id": oid, "label": obj.get("label", ""),
                   "floor": fl, "items": INV.container_peek(room_id, oid, curse=is_dm)})
    await broadcast(room_id, "inv_changed", None)
    if not is_dm:
        verb = "puts" if res["direction"] == "into" else "takes"
        sys_msg(room_id, f"📦 {user['username']} {verb} {res['qty']} × {res['name']}"
                         f" {res['direction']} the {obj['label']}.")
        events.emit(events.make("container_moved", room_id=room_id, actor_id=user["id"],
                                object_id=oid, label=obj["label"],
                                item=res["name"], qty=res["qty"],
                                direction=res["direction"]))


# ---------- D105: NPC inventories (carcass key tok:<token_id>) + looting ----------
# An NPC token's gear lives in the SAME containers table as world chests, under
# the synthetic key "tok:<token_id>". It never rides in a snapshot or token
# payload — the only way to see it is an authorised inspect on this channel.

def _tok_c(tok_id):
    return f"tok:{int(tok_id)}"


def _npc_dead(tok):
    """A token carries NPC gear only if it is an NPC block WITHOUT a bound
    character; loot is open exactly while its server-side hp is 0. Healing
    above 0 re-locks it immediately — this reads the live row, never a cache."""
    if tok is None or tok["character_id"] is not None:
        return None
    from .. import npc as NPC
    block = NPC.load(tok)
    if not isinstance(block, dict):
        return None
    try:
        hp = int(block.get("hp", 1))
    except (TypeError, ValueError):
        hp = 1
    return block if hp <= 0 else False      # False = NPC exists, alive


async def handle_npc_inv(ws, room_id, user, is_dm, msg):
    """DM manages an NPC token's inventory. inspect / fill / remove /
    coins_fill / coins_remove — mutations go through app/inventory.py only.
    Silent for non-DM (mirrors the dm_only world-container path)."""
    if not is_dm:
        return
    tok = db.q1("SELECT * FROM tokens WHERE id=? AND room_id=?",
                (msg.get("token_id", -1), room_id))
    if _npc_dead(tok) is None:
        return                                        # not an NPC: silent no-op
    oid = _tok_c(tok["id"])
    action = str(msg.get("action", "inspect"))

    async def reply():
        await send_to(ws, "inv_contents",
                      {"object_id": oid, "label": tok["label"] or "NPC",
                       "floor": tok["floor"] or "", "items": INV.container_peek(room_id, oid, curse=is_dm),
                       "coins": INV.container_coins_peek(room_id, oid), "npc_token": tok["id"]})

    if action == "inspect":
        await reply()
        return
    try:
        if action == "fill":
            qty = int(msg.get("qty", 1))
            if qty < 1 or qty > 9999:
                raise INV.InvError("Quantity must be 1–9999")
            d = db.q1("SELECT * FROM item_defs WHERE id=? AND room_id=?",
                      (str(msg.get("def_id", ""))[:24], room_id))
            if d is None:
                raise INV.InvError("Pick an item definition of this room")
            res = INV.container_fill(room_id, oid, [INV.entry_from_def(d, qty)], _op(msg))
        elif action == "remove":
            res = INV.container_remove(room_id, oid, str(msg.get("item_id", ""))[:16],
                                       msg.get("qty", 1), _op(msg))
        elif action == "coins_fill":
            res = INV.container_fill_coins(room_id, oid, _coins_to_cp(msg), _op(msg))
        elif action == "coins_remove":
            res = INV.container_remove_coins(room_id, oid, _coins_to_cp(msg), _op(msg))
        else:
            return
    except INV.InvError as ex:
        await send_to(ws, "error", {"msg": str(ex)})
        return
    if res == "replay":
        await send_to(ws, "whisper", {"text": "⚠️ That action was already applied."})
        return
    # No inv_changed broadcast: a living NPC's inventory is DM knowledge only;
    # the DM client re-renders from the inv_contents reply.
    await reply()


async def handle_loot(ws, room_id, user, is_dm, msg):
    """Loot a DOWNED npc token. Authorisation mirrors the D82/D92 container
    path: same room, controlled token on the npc's plane, standing adjacent,
    and the receiving character is yours (the DM may act for any seated
    character). The corpse keeps sitting on the map — only its gear moves,
    through one transaction per action, guarded by op_id."""
    tok = db.q1("SELECT * FROM tokens WHERE id=? AND room_id=?",
                (msg.get("token_id", -1), room_id))
    dead = _npc_dead(tok)
    if dead is None:
        return                                        # not an NPC: silent no-op
    action = str(msg.get("action", "inspect"))
    if dead is False:
        await send_to(ws, "error",
                      {"msg": "It isn't here." if not is_dm
                              else "That creature is still standing."})
        return
    fl = str(tok["floor"] or "")
    if not is_dm:
        planes = {(t.get("floor") or "") for t in authz.controlled_rows(room_id, user["id"])}
        if fl not in planes:
            return                                    # nowhere near: nothing here
        mp = get_map(room_id, fl)
        # token x/y are PIXELS on the map (map-object coords are cells) — the
        # reach comparison lives in cell space, so convert first.
        cs = mp.get("cell") or 50
        x0, y0 = int(tok["x"] // cs), int(tok["y"] // cs)
        near = {(x0 + dx, y0 + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)}
        if not _reach_cells(room_id, user["id"], mp, fl) & near:
            await send_to(ws, "error", {"msg": "Walk up to it first"})
            return
    oid = _tok_c(tok["id"])

    async def reply():
        await send_to(ws, "inv_contents",
                      {"object_id": oid, "label": tok["label"] or "fallen creature",
                       "floor": fl, "items": INV.container_peek(room_id, oid, curse=is_dm),
                       "coins": INV.container_coins_peek(room_id, oid), "npc_token": tok["id"]})

    if action == "inspect":
        await reply()
        return
    ch = await _sheet_char(ws, room_id, user, is_dm, msg)
    if ch is None:
        return
    try:
        if action == "take":
            res = INV.container_give(room_id, oid, ch["id"],
                                     str(msg.get("item_id", ""))[:16],
                                     msg.get("qty", 1), _op(msg))
        elif action == "coins_take":
            res = INV.container_take_coins(room_id, ch["id"], oid,
                                           _coins_to_cp(msg), _op(msg))
        else:
            return
    except INV.InvError as ex:
        await send_to(ws, "error", {"msg": str(ex)})
        return
    if res == "replay":
        await send_to(ws, "whisper", {"text": "⚠️ That action was already applied."})
        return
    await reply()
    await broadcast(room_id, "inv_changed", None)     # the TAKING sheet must refresh
    if action == "take":
        await _item_transfer_effects(room_id, ch["id"], res["name"], _op(msg) or "")
        sys_msg(room_id, f"💰 {user['username']} loots {res['qty']} × {res['name']}"
                         f" from the fallen {tok['label'] or 'creature'}.")
        events.emit(events.make("container_moved", room_id=room_id, actor_id=user["id"],
                                object_id=oid, label=tok["label"] or "carcass",
                                item=res["name"], qty=res["qty"], direction="from"))
    else:
        from .. import gear
        sys_msg(room_id, f"🪙 {user['username']} takes {gear.cp_label(res['cp'])}"
                         f" from the fallen {tok['label'] or 'creature'}.")


# ---------- D106: DM-authored secret curses on concrete item instances ----------
# One channel, five actions. Storage goes through app/inventory.py only; the
# disclosure rules live in gear.curse_view. The whisper RECIPIENT is always
# resolved server-side from the instance's current holder — the client cannot
# name one — and delivery rides the existing private whisper system (chat.
# post_chat), so other players see nothing on the wire and nothing in history.

CURSE_ACTIONS = ("set", "clear", "reveal", "conceal", "whisper",
                 "arm", "activate", "deactivate")


def _curse_fields(msg):
    """Sanitise the DM-authored metadata. Control chars are stripped with the
    SAME cleaner chat uses — whisper text becomes chat body, so both paths
    share one definition of a legal character."""
    return gear.clean_curse({
        "name": CHAT.clean_text(msg.get("name"), gear.CURSE_NAME),
        "desc": CHAT.clean_text(msg.get("desc"), gear.CURSE_DESC),
        "whisper": CHAT.clean_text(msg.get("whisper"), gear.CURSE_WHISPER)})


def _arm_fields(msg):
    """D113: validate a DM-authored curse ARM (which event + which effect cell).
    The effect cell is the SAME grammar a magic item carries — run through the
    one effectops validator, never a second engine. Returns (trigger, canon_cell)
    or (None, error_message)."""
    from .. import effectops
    trigger = str(msg.get("trigger", "")).strip().lower()
    if trigger not in effectops.CURSE_TRIGGERS:
        return None, f"Unknown curse trigger (use one of {', '.join(effectops.CURSE_TRIGGERS)})."
    raw = msg.get("effects")
    try:
        ops = effectops.validate(raw)
    except effectops.EffectError as ex:
        return None, f"Invalid effect: {ex}"
    return trigger, effectops.canon(ops)


def _curse_of_char(char_id, item_id):
    """Trusted read of (entry, curse) for owner-side actions (reveal/whisper)."""
    row = db.q1("SELECT items FROM characters WHERE id=?", (char_id,))
    if row is None:
        return None, None
    items = gear.clean_items(db.j(row["items"], []), keep_curse=True)
    it = INV.find(items, item_id)
    return it, (it.get("curse") if it else None)


async def handle_curse(ws, room_id, user, is_dm, msg):
    """DM-only: mark a concrete instance cursed (character-, world-chest- or
    NPC-carried), edit/clear the secret, reveal it to or whisper it to the
    CURRENT player owner. Room scope is enforced by construction: the character
    must be a member's character, the token/container must live in THIS room.
    No broadcast ever carries curse data — the DM client gets the fresh state
    on this socket only."""
    if not is_dm:
        await send_to(ws, "error", {"msg": "DM only"})
        return
    action = str(msg.get("action", ""))
    if action not in CURSE_ACTIONS:
        return
    item_id = str(msg.get("item_id", ""))[:16]
    if not item_id:
        await send_to(ws, "error", {"msg": "Which item?"})
        return

    # ---- resolve the scope of THIS room (foreign ids answer like nothing exists)
    char, oid = None, None
    if msg.get("char_id") not in (None, "", 0):
        char = db.q1("SELECT * FROM characters WHERE id=?", (msg.get("char_id", -1),))
        if char is None or db.q1("SELECT 1 AS hit FROM room_members WHERE room_id=? AND character_id=?",
                                 (room_id, char["id"])) is None:
            await send_to(ws, "error", {"msg": "No such character"})
            return
    elif msg.get("token_id") not in (None, "", 0):
        tok = db.q1("SELECT * FROM tokens WHERE id=? AND room_id=?",
                    (msg.get("token_id", -1), room_id))
        if _npc_dead(tok) is None:                       # not an NPC of this room
            await send_to(ws, "error", {"msg": "No such container here"})
            return
        oid = _tok_c(tok["id"])
    else:
        oid = str(msg.get("object_id", ""))[:16]
        fl = str(msg.get("floor") or "")
        obj = None
        if oid and FLOOR.exists(room_id, fl):
            mp = get_map(room_id, fl)
            obj = next((o for o in mp.get("objects", []) if o.get("id") == oid), None)
            if obj is not None and ((obj.get("interact") or {}).get("op") or {}).get("kind") != "container":
                obj = None
        if obj is None:
            await send_to(ws, "error", {"msg": "No such container here"})
            return

    async def fail(text):
        await send_to(ws, "error", {"msg": text})

    async def done(payload):
        await send_to(ws, "curse_updated", payload)     # DM socket only

    if action in ("reveal", "conceal", "whisper") and char is None:
        # Editing (set/clear) works anywhere the DM may reach; disclosing and
        # whispering require an unambiguous player owner for this instance.
        return await fail("That item needs a player owner first — move it onto a character.")

    try:
        if action == "set":
            curse = _curse_fields(msg)
            if curse is None:
                return await fail("Give the curse a name, a description or a whisper text.")
            res = (INV.curse_set(room_id, char["id"], item_id, curse, _op(msg))
                   if char else INV.container_curse_set(room_id, oid, item_id, curse, _op(msg)))
        elif action == "clear":
            res = (INV.curse_clear(room_id, char["id"], item_id, _op(msg))
                   if char else INV.container_curse_clear(room_id, oid, item_id, _op(msg)))
        elif action == "arm":
            trigger, cell = _arm_fields(msg)
            if trigger is None:
                return await fail(cell)                       # cell carries the message
            res = (INV.curse_arm(room_id, char["id"], item_id, trigger, cell, _op(msg))
                   if char else INV.container_curse_arm(room_id, oid, item_id, trigger, cell, _op(msg)))
        elif action in ("activate", "deactivate"):
            on = action == "activate"
            res = (INV.curse_active(room_id, char["id"], item_id, on, _op(msg))
                   if char else INV.container_curse_active(room_id, oid, item_id, on, _op(msg)))
        elif action in ("reveal", "conceal"):          # D110 fix: "whisper" must
            res = INV.curse_reveal(room_id, char["id"], item_id,   # NEVER reach here —
                                   action == "reveal", _op(msg))    # it only delivers text;
        else:                                                      # the old else-branch also
            res = None                                             # flipped revealed back off

    except INV.InvError as ex:
        return await fail(str(ex))
    if res == "replay":
        return await send_to(ws, "whisper", {"text": "⚠️ That action was already applied."})

    if action in ("set", "clear", "reveal", "conceal", "arm", "activate", "deactivate"):
        await done({"char_id": char["id"] if char else None,
                    "object_id": None if char else oid,
                    "item_id": res["item_id"], "curse": res.get("curse"), "action": action})
        if action == "set":
            await send_to(ws, "whisper", {"text": f"🪡 Curse “{res['curse']['name'] or 'unnamed'}” set on {res['name']}."})
        elif action == "clear":
            await send_to(ws, "whisper", {"text": f"🪡 Curse removed from {res['name']}."})
        elif action == "conceal":
            await send_to(ws, "whisper", {"text": f"🪡 Curse on {res['name']} is undisclosed again."})
        elif action == "arm":
            await send_to(ws, "whisper", {"text": f"⚙️ Curse on {res['name']} armed on “{res['curse']['trigger']}”."})
        elif action in ("activate", "deactivate"):
            await send_to(ws, "whisper", {"text": f"🔮 Curse on {res['name']} is now "
                                           + ("ACTIVE" if action == "activate" else "dormant")
                                           + "."})

    if action == "reveal":
        # Server-side disclosure: ONLY the owning user receives the released
        # fields (name + desc — the whisper text never rides a sheet), through
        # the private whisper channel; nobody else sees an event or a history row.
        curse = res["curse"]
        label = " — ".join(x for x in (curse["name"], curse["desc"]) if x)
        if not CHAT._rate_ok(room_id, user["id"], "curse"):
            return await fail("Curses are being sent too quickly.")
        await CHAT.post_chat(room_id, user,
                             text=f"☠️ {res['name']}: {label or 'a curse stirs.'}",
                             channel="whisper", visibility="whisper",
                             recipients=[char["user_id"]], meta={"source": "curse"})
        await send_to(ws, "whisper", {"text": f"🪡 The curse on {res['name']} is revealed to its owner."})
    elif action == "whisper":
        # The stored whisper text goes to the CURRENT owner exactly as the DM
        # authored it. The recipient is looked up from the item's holder —
        # any recipient field in this message is ignored by construction.
        if not CHAT._rate_ok(room_id, user["id"], "curse"):
            return await fail("Curses are being sent too quickly.")
        it, curse = _curse_of_char(char["id"], item_id)
        if it is None:
            return await fail("Item not found")
        if not curse:
            return await fail("That item carries no curse.")
        if not curse["whisper"]:
            return await fail("This curse has no whisper text stored.")
        mid = await CHAT.post_chat(room_id, user, text=curse["whisper"],
                                   channel="whisper", visibility="whisper",
                                   recipients=[char["user_id"]],
                                   meta={"source": "curse"})
        if mid is None:
            return await fail("The whisper text is empty.")
        await send_to(ws, "whisper", {"text": f"🪡 Whispered to {char['name']}'s player."})
