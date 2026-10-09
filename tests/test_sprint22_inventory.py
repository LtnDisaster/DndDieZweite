"""Sprint 22 (D92): persistent inventory, definitions, stacks, transfers, equipment.

Adversarial pins: unauthorised sheet access is refused (second player, forged
char ids from other rooms, players driving DM-only ops); quantities are whole
and positive end to end; op_id replays change nothing; stacks split/combine
without duplication; transfers are atomic across two characters and clear the
source's equipment slots; equipment validates slot admission (generic table +
props override + two-handed rule); AC switches to equipped mode ONLY once a
slot is occupied (legacy sheets keep byte-identical math); everything persists
in the database, not in hub memory.
"""
import pytest
from starlette.testclient import TestClient

from app import db, gear, inventory as INV, main
from tests.test_movement_fog import (H, base_room, join_room, make_char,
                                     recv_until, reg, ws_connect)


@pytest.fixture()
def client():
    return TestClient(main.app)


def items_of(client, user, code):
    st = client.get(f"/api/rooms/{code}/state", headers=H(user)).json()
    return st["characters"][0]["items"], st["characters"][0]["equipment"]


def db_items(char_id):
    row = db.q1("SELECT items, equipment FROM characters WHERE id=?", (char_id,))
    return db.j(row["items"], []), db.j(row["equipment"], {})


def make_def(ws, name="Healing Draught", **kw):
    d = {"name": name, "kind": kw.get("kind", "potion"),
         "desc": kw.get("desc", ""), "stackable": kw.get("stackable", True),
         "weight": kw.get("weight", 0.5)}
    if kw.get("props"):
        d["props"] = kw["props"]
    ws.send_json({"type": "item_def", "action": "create", "defn": d})
    recv_until(ws, "whisper")


def _grant(dm_ws, code, char_id, def_id=None, item=None, qty=1, op_id=None):
    msg = {"type": "inv_grant", "char_id": char_id, "qty": qty}
    if def_id:
        msg["def_id"] = def_id
    if item:
        msg["item"] = item
    if op_id:
        msg["op_id"] = op_id
    dm_ws.send_json(msg)


# ---------- definitions + grants ----------

def test_def_library_grant_and_persist(client):
    dm, player, code, ch = base_room(client)
    with ws_connect(client, dm, code) as ws:
        make_def(ws)
    defs = client.get(f"/api/rooms/{code}/state", headers=H(dm)).json()["item_defs"]
    assert defs and defs[0]["name"] == "Healing Draught"
    # players never receive the DM's future-loot templates
    assert client.get(f"/api/rooms/{code}/state",
                      headers=H(player)).json()["item_defs"] == []
    with ws_connect(client, dm, code) as ws:
        _grant(ws, code, ch["id"], def_id=defs[0]["id"], qty=5)
        recv_until(ws, "inv_changed")
    items, _ = items_of(client, player, code)
    draughts = [i for i in items if i["name"] == "Healing Draught"]
    assert len(draughts) == 1 and draughts[0]["qty"] == 5      # ONE stack
    assert draughts[0]["stackable"] and draughts[0]["weight"] == 0.5
    assert draughts[0]["def_id"] == defs[0]["id"]
    # persistence: a fresh refetch (reconnect stand-in) shows the same truth
    again, _ = items_of(client, player, code)
    assert again == items


def test_adhoc_grant_replay_changes_nothing(client):
    dm, player, code, ch = base_room(client)
    with ws_connect(client, dm, code) as ws:
        _grant(ws, code, ch["id"], item={"name": "Tinderbox", "kind": "tool"},
               qty=2, op_id="op-unique-1")
        recv_until(ws, "inv_changed")
        _grant(ws, code, ch["id"], item={"name": "Tinderbox", "kind": "tool"},
               qty=2, op_id="op-unique-1")                              # replay
        recv_until(ws, "whisper")
    items, _ = db_items(ch["id"])
    tb = [i for i in items if i["name"] == "Tinderbox"]
    assert len(tb) == 1 and tb[0]["qty"] == 2       # never 4


@pytest.mark.parametrize("qty", [0, -3, "3.5", 100000, "x", None])
def test_grant_rejects_any_invalid_quantity(client, qty):
    dm, player, code, ch = base_room(client)
    with ws_connect(client, dm, code) as ws:
        _grant(ws, code, ch["id"], item={"name": "Coin", "kind": "other"}, qty=qty)
        recv_until(ws, "error")
    assert db_items(ch["id"])[0] == []


def test_players_cannot_drive_dm_ops(client):
    dm, player, code, ch = base_room(client)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "inv_grant", "char_id": ch["id"], "qty": 1,
                      "item": {"name": "Stolen", "kind": "other"}})
        assert "DM only" in recv_until(ws, "error")["payload"]["msg"]
        ws.send_json({"type": "inv_remove", "char_id": ch["id"], "item_id": "it0", "qty": 1})
        assert "DM only" in recv_until(ws, "error")["payload"]["msg"]
        ws.send_json({"type": "item_def", "action": "create",
                      "defn": {"name": "Sneaky", "kind": "ring"}})
        assert "DM only" in recv_until(ws, "error")["payload"]["msg"]


# ---------- sheet authority ----------

def test_foreign_sheet_and_transfer_refused(client):
    dm, a, code, ch_a = base_room(client)
    b = reg(client, "pl")
    join_room(client, b, code)
    ch_b = make_char(client, b)
    client.post(f"/api/rooms/{code}/assign", json={"character_id": ch_b["id"]}, headers=H(b))
    with ws_connect(client, dm, code) as ws:
        _grant(ws, code, ch_a["id"], item={"name": "Gem", "kind": "other"}, qty=3)
        recv_until(ws, "inv_changed")
        _grant(ws, code, ch_b["id"], item={"name": "Gem", "kind": "other"}, qty=1)
        recv_until(ws, "inv_changed")
    gem_b = next(i for i in items_of(client, b, code)[0] if i["name"] == "Gem")
    with ws_connect(client, b, code) as ws:
        for mtype, extra in (("inv_adjust", {"action": "split", "qty": 1}),
                             ("inv_equip", {"slot": "armor", "item_id": None}),
                             ("inv_transfer", {"to_char_id": ch_b["id"], "qty": 1})):
            ws.send_json({"type": mtype, "char_id": ch_a["id"], "item_id": "x", **extra})
            assert "Not your character" in recv_until(ws, "error")["payload"]["msg"]
        # B legitimately transferring his OWN single gem away and back works,
        # but forging a bigger quantity than owned is refused atomically:
        ws.send_json({"type": "inv_transfer", "char_id": ch_b["id"],
                      "to_char_id": ch_a["id"], "item_id": gem_b["id"], "qty": 99})
        assert "Only" in recv_until(ws, "error")["payload"]["msg"]
    assert next(i for i in items_of(client, b, code)[0]
                if i["name"] == "Gem")["qty"] == 1            # unchanged


def test_forged_char_from_other_room(client):
    dm1, p1, code1, _ = base_room(client)
    _, p2, code2, ch2 = base_room(client)
    with ws_connect(client, dm1, code1) as ws:
        _grant(ws, code1, ch2["id"], item={"name": "CrossRoom", "kind": "other"})
        assert "No such character" in recv_until(ws, "error")["payload"]["msg"]


# ---------- stacks ----------

def test_split_combine_roundtrip(client):
    dm, player, code, ch = base_room(client)
    with ws_connect(client, dm, code) as ws:
        make_def(ws, name="Ration")
    defs = client.get(f"/api/rooms/{code}/state", headers=H(dm)).json()["item_defs"]
    with ws_connect(client, dm, code) as ws:
        _grant(ws, code, ch["id"], def_id=defs[0]["id"], qty=5)
        recv_until(ws, "inv_changed")
    with ws_connect(client, player, code) as ws:
        rid = next(i["id"] for i in items_of(client, player, code)[0]
                   if i["name"] == "Ration")
        ws.send_json({"type": "inv_adjust", "char_id": ch["id"], "action": "split",
                      "item_id": rid, "qty": 2})
        recv_until(ws, "inv_changed")
        items = items_of(client, player, code)[0]
        rations = [i for i in items if i["name"] == "Ration"]
        assert sorted(r["qty"] for r in rations) == [2, 3] and len(rations) == 2
        keep, split = sorted(rations, key=lambda r: r["qty"], reverse=True)
        ws.send_json({"type": "inv_adjust", "char_id": ch["id"], "action": "combine",
                      "item_id": keep["id"], "other_id": split["id"]})
        recv_until(ws, "inv_changed")
    items = items_of(client, player, code)[0]
    assert [i["qty"] for i in items if i["name"] == "Ration"] == [5]


def test_nonstackable_and_garbage_splits_refused(client):
    dm, player, code, ch = base_room(client)
    with ws_connect(client, dm, code) as ws:
        _grant(ws, code, ch["id"], item={"name": "Longsword", "kind": "other"}, qty=1)
        recv_until(ws, "inv_changed")
    sid = next(i["id"] for i in items_of(client, player, code)[0]
               if i["name"] == "Longsword")
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "inv_adjust", "char_id": ch["id"], "action": "split",
                      "item_id": sid, "qty": 1})
        assert "Not stackable" in recv_until(ws, "error")["payload"]["msg"]
        ws.send_json({"type": "inv_adjust", "char_id": ch["id"], "action": "split",
                      "item_id": sid, "qty": 0})
        assert "error" == recv_until(ws, "error")["kind"]
        ws.send_json({"type": "inv_adjust", "char_id": ch["id"], "action": "combine",
                      "item_id": sid, "other_id": sid})
        assert "different items" in recv_until(ws, "error")["payload"]["msg"]


# ---------- transfer ----------

def test_partial_transfer_moves_exactly_qty(client):
    dm, a, code, ch_a = base_room(client)
    b = reg(client, "pl")
    join_room(client, b, code)
    ch_b = make_char(client, b)
    client.post(f"/api/rooms/{code}/assign", json={"character_id": ch_b["id"]}, headers=H(b))
    with ws_connect(client, dm, code) as ws:
        make_def(ws, name="Arrow")
    defs = client.get(f"/api/rooms/{code}/state", headers=H(dm)).json()["item_defs"]
    with ws_connect(client, dm, code) as ws:
        _grant(ws, code, ch_a["id"], def_id=defs[0]["id"], qty=10)
        recv_until(ws, "inv_changed")
    aid = next(i["id"] for i in items_of(client, a, code)[0] if i["name"] == "Arrow")
    with ws_connect(client, a, code) as ws:
        ws.send_json({"type": "inv_transfer", "char_id": ch_a["id"],
                      "to_char_id": ch_b["id"], "item_id": aid, "qty": 4})
        recv_until(ws, "inv_changed")
    qa = next(i for i in items_of(client, a, code)[0] if i["name"] == "Arrow")["qty"]
    qb = next(i for i in items_of(client, b, code)[0] if i["name"] == "Arrow")["qty"]
    assert (qa, qb) == (6, 4)


# ---------- equipment ----------

def test_equip_slot_validation_and_two_handed(client):
    dm, player, code, ch = base_room(client)
    with ws_connect(client, dm, code) as ws:
        _grant(ws, code, ch["id"], item={"name": "Plate", "kind": "armor", "ac": 15})
        recv_until(ws, "inv_changed")
        _grant(ws, code, ch["id"], item={"name": "Kite Shield", "kind": "shield", "ac": 2})
        recv_until(ws, "inv_changed")
        _grant(ws, code, ch["id"], item={"name": "Ring", "kind": "ring"})
        recv_until(ws, "inv_changed")
        _grant(ws, code, ch["id"], item={"name": "Greatsword", "kind": "other",
                                         "props": {"two_handed": True, "slot": "main_hand"}})
        recv_until(ws, "inv_changed")
    items = {i["name"]: i["id"] for i in items_of(client, player, code)[0]}
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "inv_equip", "char_id": ch["id"],
                      "slot": "armor", "item_id": items["Ring"]})
        assert "does not fit" in recv_until(ws, "error")["payload"]["msg"]
        ws.send_json({"type": "inv_equip", "char_id": ch["id"],
                      "slot": "bogus", "item_id": items["Plate"]})
        assert "No such slot" in recv_until(ws, "error")["payload"]["msg"]
        for slot, name in (("armor", "Plate"), ("off_hand", "Kite Shield"),
                           ("acc1", "Ring")):
            ws.send_json({"type": "inv_equip", "char_id": ch["id"],
                          "slot": slot, "item_id": items[name]})
            recv_until(ws, "inv_changed")
        _, equip = items_of(client, player, code)
        assert equip["armor"] and equip["off_hand"] and equip["acc1"]
        # two-handed in main: the off hand must be CLEARED by the equip rule
        ws.send_json({"type": "inv_equip", "char_id": ch["id"],
                      "slot": "main_hand", "item_id": items["Greatsword"]})
        recv_until(ws, "inv_changed")
        _, equip = items_of(client, player, code)
        assert equip["main_hand"] and equip["off_hand"] is None
        # ...and while a two-hander is held, the off hand refuses anything
        ws.send_json({"type": "inv_equip", "char_id": ch["id"],
                      "slot": "off_hand", "item_id": items["Kite Shield"]})
        assert "does not fit" in recv_until(ws, "error")["payload"]["msg"]
        _, equip = items_of(client, player, code)
        assert equip["off_hand"] is None


def test_ac_equipped_mode_and_legacy_untouched():
    items = gear.clean_items([{"name": "Mail", "kind": "armor", "ac": 14, "id": "a1"},
                              {"name": "Board", "kind": "armor", "ac": 18, "id": "a2"}])
    base = {"ac": 10, "stats": {"dex": 12}, "items": items}
    assert gear.compute_ac(dict(base, equipment={})) == 14          # legacy: FIRST armor
    assert gear.compute_ac(dict(base, equipment={"armor": "a2"})) == 18
    # unequipped but owned armor no longer counts once ANY slot is worn:
    assert gear.compute_ac(dict(base, equipment={"acc1": None, "main_hand": "a2"})) == 18


def test_removing_equipped_item_clears_slot(client):
    dm, player, code, ch = base_room(client)
    with ws_connect(client, dm, code) as ws:
        _grant(ws, code, ch["id"], item={"name": "Breastplate", "kind": "armor", "ac": 14})
        recv_until(ws, "inv_changed")
    aid = next(i["id"] for i in items_of(client, player, code)[0]
               if i["name"] == "Breastplate")
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "inv_equip", "char_id": ch["id"],
                      "slot": "armor", "item_id": aid})
        recv_until(ws, "inv_changed")
    assert items_of(client, player, code)[1]["armor"] == aid
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "inv_remove", "char_id": ch["id"], "item_id": aid, "qty": 1})
        recv_until(ws, "inv_changed")
    items, equip = db_items(ch["id"])
    assert items == [] and equip["armor"] is None


def test_persistence_is_db_truth(client):
    dm, player, code, ch = base_room(client)
    with ws_connect(client, dm, code) as ws:
        _grant(ws, code, ch["id"], item={"name": "Charm", "kind": "trinket-not-a-kind"},
               qty=2)      # invalid kind falls back to "other" — never rejected
        recv_until(ws, "inv_changed")
    items, _ = db_items(ch["id"])
    assert len(items) == 1 and items[0]["kind"] == "other" and items[0]["qty"] == 2
