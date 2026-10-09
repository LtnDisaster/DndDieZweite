"""Server-authoritative inventory, equipment and containers (Sprint 22, D92).

OWNERSHIP MODEL: items live on CHARACTERS — the one existing item system
(``characters.items``; tokens act through their linked character). Sheet
authority = character owner or the room DM; token CONTROLLERS (D82) hold
operational authority only and get NO inventory rights. Handlers in
app/room/inv.py authorise; THIS module is the only mutation site for
quantities, transfers, equipment and container contents.

ATOMICITY: every mutation re-reads its rows INSIDE db.tx() (BEGIN IMMEDIATE)
and writes all touched rows before COMMIT. Concurrent operations serialise on
the database, so quantities can never duplicate, go negative or half-apply —
including a container↔character transfer (both sides live in SQLite).

REPLAY DEFENCE: mutating operations carry a client-generated ``op_id``; the
first INSERT into inv_ops wins, a replayed claim answers as a no-op ("replay").
"""
import sqlite3
import uuid

from . import db, gear


class InvError(Exception):
    """Rejected mutation — the transaction rolls back, nothing is written."""


def _claim(c, op_id, room_id, kind, ns=None):
    """Claim an op_id inside the caller's transaction. False = already claimed.
    D94: client-chosen op_ids are claimed under a server-side namespace
    (the character/object the op acts on) — one player cannot pre-claim a
    guessable op_id to silently swallow ANOTHER player's operation.
    Legacy (pre-D94) rows carry the raw op_id and keep working."""
    if not op_id:
        return True
    if ns is not None:
        op_id = f"{ns}|{op_id}"
    c.execute("DELETE FROM inv_ops WHERE created_at < datetime('now','-1 day')")
    try:
        c.execute("INSERT INTO inv_ops(op_id, room_id, kind) VALUES (?,?,?)",
                  (op_id, room_id, kind))
    except sqlite3.IntegrityError:
        return False
    return True


def new_item_id(items):
    ids = {i.get("id") for i in items}
    while True:
        nid = "it" + uuid.uuid4().hex[:10]
        if nid not in ids:
            return nid


def entry_from_def(d, qty):
    """Instantiate one inventory entry from an item_defs row (denormalised
    snapshot; def edits never mutate granted items — documented in D92)."""
    return gear.clean_items([{
        "name": d["name"], "kind": d.get("kind", "other"),
        "desc": d.get("desc", ""), "weight": d.get("weight", 0),
        "stackable": bool(d.get("stackable")), "def_id": d["id"],
        "props": db.j(d.get("props"), {}) or {}, "qty": qty,
    }])[0]


def clean_def(d):
    """Validate one item-definition payload (generic, catalogue-free: the DM
    authors name/desc themselves). None = invalid."""
    name = str(d.get("name", "")).strip()[:48]
    if not name:
        return None
    kind = d.get("kind", "other")
    if kind not in gear.KINDS:
        kind = "other"
    try:
        weight = max(0.0, min(9999.0, round(float(d.get("weight", 0)), 1)))
    except (TypeError, ValueError):
        weight = 0.0
    did = str(d.get("id", "")).strip()[:24]
    if did and not did.replace("_", "").isalnum():
        return None
    return {"id": did, "name": name, "desc": str(d.get("desc", ""))[:200],
            "kind": kind, "weight": weight, "stackable": 1 if d.get("stackable") else 0,
            "props": gear.clean_props(d.get("props"))}


# ---------- stack rules ----------

def _stack_key(it):
    """Two entries may share a stack iff: the SAME DM definition, both
    stackable, and instance truth matches (charges, identified). Attunable
    items never stack — attunement is instance truth."""
    if not it.get("stackable") or not it.get("def_id"):
        return None
    if it.get("attunable") or it.get("attuned"):
        return None
    return (it["def_id"], it.get("charges", -1), bool(it.get("identified", True)),
            it.get("heal", ""))


def stack_add(items, entry):
    """Merge into a matching stack or append a new entry. Full inventory =
    InvError (never silently dropped)."""
    key = _stack_key(entry)
    if key:
        for it in items:
            if _stack_key(it) == key:
                it["qty"] = min(9999, int(it["qty"]) + int(entry["qty"]))
                return it, True
    if len(items) >= 40:                       # gear.clean_items entry cap
        raise InvError("Inventory is full")
    entry = dict(entry)
    entry["id"] = new_item_id(items)
    items.append(entry)
    return entry, False


def find(items, item_id):
    return next((i for i in items if i.get("id") == item_id), None)


def _take(items, item_id, qty):
    """Debit qty from an entry (deleting it at zero). Returns the entry."""
    it = find(items, item_id)
    if it is None:
        raise InvError("Item not found")
    try:
        qty = int(qty)
    except (TypeError, ValueError):
        raise InvError("Quantity must be a whole number")
    if qty <= 0:
        raise InvError("Quantity must be positive")
    if int(it["qty"]) < qty:
        raise InvError(f"Only {it['qty']} × {it['name']} there")
    it["qty"] = int(it["qty"]) - qty
    if it["qty"] == 0:
        items.remove(it)
    return it, qty


def strip_slots(equip, items):
    """Drop equipment references to items that no longer exist (consistency
    SSOT — applied after EVERY mutation and on every read via clean_equipment)."""
    ids = {i.get("id") for i in items}
    for s in list(equip):
        if equip[s] and equip[s] not in ids:
            equip[s] = None
    return equip


# ---------- character mutations (each one tx, replay-guarded) ----------

def _char(c, char_id):
    r = c.execute("SELECT * FROM characters WHERE id=?", (char_id,)).fetchone()
    if r is None:
        raise InvError("No such character")
    return dict(r)


def _load(c, row):
    items = gear.clean_items(db.j(row.get("items"), []))
    equip = gear.clean_equipment(db.j(row.get("equipment"), {}), items)
    return items, equip


def _store(c, char_id, items, equip):
    c.execute("UPDATE characters SET items=?, equipment=? WHERE id=?",
              (db.json_dumps(items), db.json_dumps(equip), char_id))


def mutate_char(room_id, char_id, fn, op_id=None, kind="modify"):
    """fn(items, equip) -> result. Fresh read INSIDE the transaction."""
    with db.tx() as c:
        if not _claim(c, op_id, room_id, kind, char_id):
            return "replay"
        row = _char(c, char_id)
        items, equip = _load(c, row)
        res = fn(items, equip)
        strip_slots(equip, items)               # in-place slot hygiene
        _store(c, char_id, items, equip)
    return res


def grant(room_id, char_id, entries, op_id=None):
    """Add already-validated entry list(s) to a character (DM workflow)."""
    def fn(items, equip):
        added = []
        for e in entries:
            e = gear.clean_items([e])[0]
            it, merged = stack_add(items, e)
            added.append({"item_id": it["id"], "name": it["name"],
                          "qty": e["qty"], "merged": merged})
        return added
    return mutate_char(room_id, char_id, fn, op_id, "grant")


def remove(room_id, char_id, item_id, qty, op_id=None):
    def fn(items, equip):
        it, q = _take(items, item_id, qty)
        if it["qty"] == 0:
            strip_slots(equip, items)
        return {"name": it["name"], "qty": q}
    return mutate_char(room_id, char_id, fn, op_id, "remove")


def adjust(room_id, char_id, action, item_id, other_id=None, qty=1, op_id=None):
    """Player-side stack management: split (new stack) / combine (merge two)."""
    def fn(items, equip):
        it = find(items, item_id)
        if it is None:
            raise InvError("Item not found")
        if action == "split":
            if not it.get("stackable"):
                raise InvError("Not stackable")
            try:
                q = int(qty)
            except (TypeError, ValueError):
                raise InvError("Quantity must be a whole number")
            if q <= 0 or q >= int(it["qty"]):
                raise InvError("Split must leave at least one of each")
            if len(items) >= 40:
                raise InvError("Inventory is full")
            it["qty"] = int(it["qty"]) - q
            new = dict(it)
            new["id"] = new_item_id(items)
            new["qty"] = q
            items.append(new)
            return {"split": q, "name": it["name"]}
        if action == "combine":
            other = find(items, other_id)
            ka, kb = _stack_key(it), _stack_key(other) if other else None
            if other is None or ka is None or ka != kb:
                raise InvError("Those are different items")
            it["qty"] = min(9999, int(it["qty"]) + int(other["qty"]))
            items.remove(other)
            for s, v in equip.items():          # slots on the vanished stack
                if v == other["id"]:
                    equip[s] = it["id"]
            return {"name": it["name"], "qty": it["qty"]}
        raise InvError("Unknown action")
    return mutate_char(room_id, char_id, fn, op_id, f"adjust:{action}")


def equip_slot(room_id, char_id, slot, item_id, op_id=None):
    """(Un)equip into a named slot; item_id None = clear the slot. The slot's
    previous occupant simply returns to the pack — never destroyed."""
    if slot not in gear.SLOTS:
        raise InvError("No such slot")

    def fn(items, equip):
        if item_id is None:
            equip[slot] = None
            return {"slot": slot, "item": None}
        it = find(items, item_id)
        if it is None:
            raise InvError("Item not found")
        if not gear.can_equip(it, slot, equip, items):
            raise InvError(f"{it['name']} does not fit the {slot.replace('_', ' ')}")
        if (it.get("props") or {}).get("two_handed") and slot == "main_hand":
            equip["off_hand"] = None            # two-handed: the off hand is free
        if slot == "off_hand":
            held = find(items, equip.get("main_hand"))
            if held and (held.get("props") or {}).get("two_handed"):
                raise InvError(f"{it['name']} does not fit the off hand")
        equip[slot] = it["id"]
        return {"slot": slot, "item": it["name"]}
    return mutate_char(room_id, char_id, fn, op_id, "equip")


# ---------- transfers (both sides in ONE transaction) ----------

def _validate_parties(room_id, from_char, to_char):
    """Both characters must exist and both must be characters of MEMBERS of
    THIS room — transfers across rooms are refused by construction."""
    for cid in (from_char, to_char):
        if db.q1("SELECT 1 AS hit FROM room_members WHERE room_id=? AND character_id=?",
                 (room_id, cid)) is None:
            raise InvError("Not a character of this room")


def transfer(room_id, from_char, to_char, item_id, qty, op_id=None):
    _validate_parties(room_id, from_char, to_char)
    with db.tx() as c:
        if not _claim(c, op_id, room_id, "transfer", from_char):
            return "replay"
        src, dst = _char(c, from_char), _char(c, to_char)
        items_s, equip_s = _load(c, src)
        items_d, equip_d = _load(c, dst)
        it, q = _take(items_s, item_id, qty)
        copy = dict(it)
        copy["qty"] = q
        got, _ = stack_add(items_d, copy)       # full target → InvError → ROLLBACK
        strip_slots(equip_s, items_s)
        _store(c, from_char, items_s, equip_s)
        _store(c, to_char, items_d, equip_d)
    return {"name": it["name"], "qty": q, "to": dst["name"]}


# ---------- containers (world objects, D82 framework; contents in SQLite) ----------

def container_load(c, room_id, object_id):
    row = c.execute("SELECT items FROM containers WHERE room_id=? AND object_id=?",
                    (room_id, object_id)).fetchone()
    return gear.clean_items(db.j(row["items"], []) if row else [])


def container_peek(room_id, object_id):
    """Read-only view (inspect answers from this — never a /state payload)."""
    row = db.q1("SELECT items FROM containers WHERE room_id=? AND object_id=?",
                (room_id, object_id))
    return gear.clean_items(db.j(row["items"], []) if row else [])


def _container_store(c, room_id, object_id, items):
    c.execute("INSERT INTO containers(room_id, object_id, items, updated_at) "
              "VALUES(?,?,?,datetime('now')) ON CONFLICT(room_id,object_id) "
              "DO UPDATE SET items=excluded.items, updated_at=excluded.updated_at",
              (room_id, object_id, db.json_dumps(items)))


def container_fill(room_id, object_id, entries, op_id=None):
    """DM (or a player putting items down): add entries to the container."""
    def fn(items):
        added = []
        for e in entries:
            e = gear.clean_items([e])[0]
            it, merged = stack_add(items, e)
            added.append({"name": it["name"], "qty": e["qty"], "merged": merged})
        return added
    with db.tx() as c:
        if not _claim(c, op_id, room_id, "container_fill", object_id):
            return "replay"
        items = container_load(c, room_id, object_id)
        res = fn(items)
        _container_store(c, room_id, object_id, items)
    return res


def container_remove(room_id, object_id, item_id, qty, op_id=None):
    def fn(items):
        it, q = _take(items, item_id, qty)
        return {"name": it["name"], "qty": q}
    with db.tx() as c:
        if not _claim(c, op_id, room_id, "container_remove", object_id):
            return "replay"
        items = container_load(c, room_id, object_id)
        res = fn(items)
        _container_store(c, room_id, object_id, items)
    return res


def container_move(room_id, object_id, char_id, item_id, qty, op_id=None):
    """Atomic character↔container move. Direction is decided by WHERE THE ITEM
    IS: char→container (put) or container→char (take) — the caller cannot ask
    for more than exists; the recheck runs inside the serialised transaction."""
    try:
        qty = int(qty)
    except (TypeError, ValueError):
        raise InvError("Quantity must be a whole number")
    if qty <= 0:
        raise InvError("Quantity must be positive")
    if db.q1("SELECT 1 AS hit FROM room_members WHERE room_id=? AND character_id=?",
             (room_id, char_id)) is None:
        raise InvError("Not a character of this room")
    with db.tx() as c:
        if not _claim(c, op_id, room_id, "container_move", char_id):
            return "replay"
        src = _char(c, char_id)
        items_s, equip_s = _load(c, src)
        cont = container_load(c, room_id, object_id)
        it = find(items_s, item_id)
        if it is not None:                        # put: character → container
            it, q = _take(items_s, item_id, qty)
            copy = dict(it)
            copy["qty"] = q
            got, _ = stack_add(cont, copy)
            direction, name = "into", it["name"]
        else:                                     # take: container → character
            cit, q = _take(cont, item_id, qty)
            copy = dict(cit)
            copy["qty"] = q
            got, _ = stack_add(items_s, copy)     # full inventory → ROLLBACK
            direction, name = "from", cit["name"]
        _container_store(c, room_id, object_id, cont)
        strip_slots(equip_s, items_s)
        _store(c, char_id, items_s, equip_s)
    return {"name": name, "qty": q, "direction": direction, "item_id": got["id"]}
