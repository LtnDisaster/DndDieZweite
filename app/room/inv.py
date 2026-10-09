"""Inventory / equipment / container transports (Sprint 22, D92).

Thin handlers ONLY: authorisation here, mutation exclusively through
app/inventory.py (the SSOT). Sheet rights = character owner or the DM — a
D82 token CONTROLLER may act through a token but never edits the sheet (same
rule as attune). Containers are D82 world objects (editor, fog, dm_only,
reach); contents live in SQLite and are transmitted ONLY through an
authorised inspect — never via /state or broadcasts.
"""
from .. import db, events, floors as FLOOR, inventory as INV
from . import authz
from .interact import _reach_cells
from .net import broadcast, get_map, send_to, send_user, sys_msg

OPID = 40


def _op(msg):
    v = str(msg.get("op_id") or "")[:OPID].strip()
    return v or None


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
        db.x("INSERT INTO item_defs(id, room_id, name, desc, kind, weight, stackable,"
             " props, created_by) VALUES(?,?,?,?,?,?,?,?,?)"
             " ON CONFLICT(id) DO UPDATE SET name=excluded.name, desc=excluded.desc,"
             " kind=excluded.kind, weight=excluded.weight, stackable=excluded.stackable,"
             " props=excluded.props",
             (did, room_id, d["name"], d["desc"], d["kind"], d["weight"],
              d["stackable"], db.json_dumps(d["props"]), user["id"]))
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
    line = f"🤝 {ch['name']} hands {res['qty']} × {res['name']} to {to['name']}."
    sys_msg(room_id, line)


# ---------- equipment ----------

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


# ---------- world containers ----------

async def handle_inv_container(ws, room_id, user, is_dm, msg):
    """inspect / move (put-or-take) / fill / remove against a container object.
    Authorisation mirrors the D82 interact path: same plane, controlled token
    adjacent, dm_only answered as if not present, unknown = silent no-op."""
    fl = str(msg.get("floor") or "")
    if not FLOOR.exists(room_id, fl):
        return
    oid = str(msg.get("object_id", ""))[:16]
    action = str(msg.get("action", "inspect"))
    mp = get_map(room_id, fl)
    obj = next((o for o in mp.get("objects", []) if o.get("id") == oid), None)
    if obj is None or ((obj.get("interact") or {}).get("op") or {}).get("kind") != "container":
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
    if action in ("move", "put", "take"):                 # need a character
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
                       "floor": fl, "items": INV.container_peek(room_id, oid)})
        return
    if action in ("fill", "remove") and not is_dm:
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
        else:
            return
    except INV.InvError as ex:
        await send_to(ws, "error", {"msg": str(ex)})
        return
    if res == "replay":
        await send_to(ws, "whisper", {"text": "⚠️ That action was already applied."})
        return
    if action == "fill":
        await send_to(ws, "inv_contents",
                      {"object_id": oid, "label": obj.get("label", ""),
                       "floor": fl, "items": INV.container_peek(room_id, oid)})
        await broadcast(room_id, "inv_changed", None)
        return
    if action == "remove":
        await broadcast(room_id, "inv_changed", None)
        return
    # move: fresh contents back to the actor + public chronicle
    await send_to(ws, "inv_contents",
                  {"object_id": oid, "label": obj.get("label", ""),
                   "floor": fl, "items": INV.container_peek(room_id, oid)})
    await broadcast(room_id, "inv_changed", None)
    if not is_dm:
        verb = "puts" if res["direction"] == "into" else "takes"
        sys_msg(room_id, f"📦 {user['username']} {verb} {res['qty']} × {res['name']}"
                         f" {res['direction']} the {obj['label']}.")
        events.emit(events.make("container_moved", room_id=room_id, actor_id=user["id"],
                                object_id=oid, label=obj["label"],
                                item=res["name"], qty=res["qty"],
                                direction=res["direction"]))
