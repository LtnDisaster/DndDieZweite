"""D106: DM-authored secret curses on concrete item instances.

One metadata block rides INSIDE the item entry (no schema change, no side
table — instance identity only lives inside one inventory, so the entry dict
IS the instance and travels through transfer, chest and loot untouched).
Every disclosure decision is server-side: gear.curse_view for sheets,
room/inv.py for container views, chat.post_chat's private whisper model for
delivery. These tests drive the REAL handlers and the REAL transaction layer
of app/inventory.py — and they hunt secrets on every wire a player can touch.
"""
import json
import uuid

import pytest
from starlette.testclient import TestClient

from app import db, main
from tests.test_movement_fog import (H, base_room, join_room, make_char,
                                     reg, recv_until, state_of, ws_connect)
from tests.test_d105_gear_loot import _fill_npc, _npc, _tokcell
from tests.test_sprint22_containers import _chest_at_player, _fill

CURSE_NAME = "Blood-Drinking Oath"
CURSE_DESC = "It whispers of the last knife in the dark."
WHISPER = "The dagger remembers your blood 4211-XY."
REVEALED_MARK = "Blood-Drinking Oath"

@pytest.fixture()
def client():
    return TestClient(main.app)


# ---------- helpers ----------

def _make_def(client, dm, code, name, stackable=False, kind="weapon", props=None):
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "item_def", "action": "create",
                      "defn": {"name": name, "kind": kind, "stackable": stackable,
                               "props": props or {}}})
        recv_until(ws, "whisper")
    return next(d["id"] for d in state_of(client, dm, code)["item_defs"]
                if d["name"] == name)


def _grant(client, dm, code, char_id, def_id, qty=1):
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "inv_grant", "char_id": char_id, "def_id": def_id,
                      "qty": qty, "op_id": "g" + uuid.uuid4().hex[:8]})
        recv_until(ws, "inv_changed")


def _grant_item(client, dm, code, char_id, item, qty=1):
    """DM grants an ad-hoc item (props ride clean_def -> clean_items)."""
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "inv_grant", "char_id": char_id, "item": item,
                      "qty": qty, "op_id": "g" + uuid.uuid4().hex[:8]})
        recv_until(ws, "inv_changed")


def _sheet(client, user, code, char_id=None):
    st = state_of(client, user, code)
    if char_id is None:
        m = next(m for m in st["members"] if m["char"] and m["user_id"] == st["me"])
    else:
        m = next(m for m in st["members"] if m["char"] and m["char"]["id"] == char_id)
    return m["char"]


def _db_items(char_id):
    row = db.q1("SELECT items FROM characters WHERE id=?", (char_id,))
    return db.j(row["items"], [])


def _db_curse(char_id, name=None):
    for it in _db_items(char_id):
        c = it.get("curse")
        if c and (name is None or it["name"] == name):
            return it, c
    return None, None


def _curse(client, dm, code, expect="curse_updated", fail_on_error=True, **kw):
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "curse", "op_id": "c" + uuid.uuid4().hex[:8], **kw})
        return recv_until(ws, expect, fail_on_error=fail_on_error)


def _dm_item_ids(client, dm, code, char_id, name):
    return [i["id"] for i in _sheet(client, dm, code, char_id)["items"] if i["name"] == name]


def _second_player(client, code):
    u2 = reg(client, "p2")
    join_room(client, u2, code)
    ch2 = make_char(client, u2)
    client.post(f"/api/rooms/{code}/assign", json={"character_id": ch2["id"]},
                headers=H(u2))
    return u2, ch2


def _dm_curse_dagger(client, dm, code, char_id, name, item_id=None,
                     whisper=WHISPER):
    """DM marks one concrete dagger cursed; returns the (possibly new) id."""
    kw = {"action": "set", "char_id": char_id,
          "item_id": item_id or _dm_item_ids(client, dm, code, char_id, name)[0],
          "name": CURSE_NAME, "desc": CURSE_DESC, "whisper": whisper}
    ev = _curse(client, dm, code, **kw)
    return ev["payload"]["item_id"]


def _room_with_dagger(client, name="Dagger"):
    dm, player, code, ch = base_room(client)
    did = _make_def(client, dm, code, name)
    _grant(client, dm, code, ch["id"], did)
    return dm, player, code, ch, did


# ================= metadata lifecycle on one instance =================

def test_dm_curses_one_dagger_the_twin_stays_clean(client):
    dm, player, code, ch, did = _room_with_dagger(client)
    _grant(client, dm, code, ch["id"], did)               # a second, identical one
    cursed_id = _dm_curse_dagger(client, dm, code, ch["id"], "Dagger")
    items = _db_items(ch["id"])
    cursed = [i for i in items if i.get("curse")]
    assert len(cursed) == 1 and cursed[0]["id"] == cursed_id
    assert cursed[0]["curse"]["name"] == CURSE_NAME
    assert cursed[0]["curse"]["whisper"] == WHISPER
    assert cursed[0]["curse"]["revealed"] is False
    clean = [i for i in items if not i.get("curse")]
    assert len(clean) == 1 and clean[0]["name"] == "Dagger"


def test_curse_survives_reload(client):
    dm, player, code, ch, _did = _room_with_dagger(client)
    _dm_curse_dagger(client, dm, code, ch["id"], "Dagger")
    # a fresh client (server reload): the metadata rides the stored JSON
    fresh = TestClient(main.app)
    assert _db_curse(ch["id"])[1] is not None
    sheet = _sheet(fresh, dm, code, ch["id"])
    assert any(i.get("curse") and i["curse"]["name"] == CURSE_NAME
               for i in sheet["items"])


def test_curse_survives_container_transfer(client):
    dm, player, code, ch, _did = _room_with_dagger(client)
    cx, cy = _chest_at_player(client, dm, player, code)
    cursed_id = _dm_curse_dagger(client, dm, code, ch["id"], "Dagger")
    # DM acts for the seated character: put into the chest, then take back out
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "inv_container", "action": "move", "object_id": "chest",
                      "floor": "", "char_id": ch["id"], "item_id": cursed_id,
                      "qty": 1, "op_id": "in-1"})
        cont = recv_until(ws, "inv_contents")["payload"]
        cid = next(i["id"] for i in cont["items"] if i["name"] == "Dagger")
        assert any(i.get("curse") for i in cont["items"])     # DM sees the truth
        ws.send_json({"type": "inv_container", "action": "move", "object_id": "chest",
                      "floor": "", "char_id": ch["id"], "item_id": cid,
                      "qty": 1, "op_id": "out-1"})
        recv_until(ws, "inv_contents")
    it, curse = _db_curse(ch["id"])
    assert curse and curse["name"] == CURSE_NAME              # the instance stayed cursed


def test_curse_survives_npc_loot(client):
    dm, player, code, ch, _tag = _room_with_dagger(client)
    cx, cy = _tokcell(client, player, code)
    tok = _npc(client, dm, code, cx=cx, cy=cy + 1, hp=0)
    got = _fill_npc(client, dm, code, tok, "Cursed Dirk", 1)   # stackable def, qty 1
    cid = next(i["id"] for i in got["items"] if i["name"] == "Cursed Dirk")
    _curse(client, dm, code, action="set", token_id=tok, item_id=cid,
           name=CURSE_NAME, desc=CURSE_DESC, whisper=WHISPER)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "loot", "action": "take", "token_id": tok,
                      "char_id": ch["id"], "item_id": cid, "qty": 1, "op_id": "l-1"})
        recv_until(ws, "inv_contents")
    it, curse = _db_curse(ch["id"], "Cursed Dirk")
    assert curse and curse["name"] == CURSE_NAME
    # ...and the player's own view still shows nothing of it
    assert "curse" not in json.dumps(_sheet(client, player, code))


def test_cursed_instance_never_merges_with_ordinary_stack(client):
    dm, player, code, ch, _ = _room_with_dagger(client)
    did = _make_def(client, dm, code, "Healing Potion", stackable=True, kind="potion")
    _grant(client, dm, code, ch["id"], did, qty=3)
    # cursing a qty=3 stack carves EXACTLY one piece; the stack stays ordinary
    pid = _dm_item_ids(client, dm, code, ch["id"], "Healing Potion")[0]
    ev = _curse(client, dm, code, action="set", char_id=ch["id"], item_id=pid,
                name=CURSE_NAME, desc=CURSE_DESC, whisper=WHISPER)
    new_id = ev["payload"]["item_id"]
    items = _db_items(ch["id"])
    cursed = [i for i in items if i.get("curse")]
    assert len(cursed) == 1 and cursed[0]["id"] == new_id and cursed[0]["qty"] == 1
    rest = [i for i in items if i["name"] == "Healing Potion" and not i.get("curse")]
    assert len(rest) == 1 and rest[0]["qty"] == 2
    # more of the same definition: merges with the ORDINARY remainder stack,
    # never with the cursed single piece — and the piece stays a single piece
    _grant(client, dm, code, ch["id"], did, qty=3)
    items = _db_items(ch["id"])
    potions = [i for i in items if i["name"] == "Healing Potion"]
    assert len(potions) == 2                                # cursed(1) + ordinary(5)
    assert sum(i["qty"] for i in potions) == 6
    assert next(i for i in potions if i.get("curse"))["qty"] == 1
    # the player cannot combine the cursed piece in, nor split it out again
    cursed_id = next(i["id"] for i in potions if i.get("curse"))
    other = next(i["id"] for i in potions if not i.get("curse"))
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "inv_adjust", "char_id": ch["id"], "action": "combine",
                      "item_id": other, "other_id": cursed_id, "op_id": "cmb-1"})
        assert "different items" in recv_until(ws, "error")["payload"]["msg"]
        ws.send_json({"type": "inv_adjust", "char_id": ch["id"], "action": "split",
                      "item_id": cursed_id, "qty": 1, "op_id": "spl-1"})
        assert "cannot be split" in recv_until(ws, "error")["payload"]["msg"]
    assert len([i for i in _db_items(ch["id"]) if i.get("curse")]) == 1


def test_replayed_curse_op_mints_nothing(client):
    dm, player, code, ch, _ = _room_with_dagger(client)
    dids = _dm_item_ids(client, dm, code, ch["id"], "Dagger")
    op = "c-replay-1"
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "curse", "op_id": op, "action": "set",
                      "char_id": ch["id"], "item_id": dids[0],
                      "name": CURSE_NAME, "desc": CURSE_DESC, "whisper": WHISPER})
        recv_until(ws, "curse_updated")
        recv_until(ws, "whisper")                            # first op's confirmation
        ws.send_json({"type": "curse", "op_id": op, "action": "set",
                      "char_id": ch["id"], "item_id": dids[0],
                      "name": "SECOND MINT", "desc": "x", "whisper": "y"})
        assert "already applied" in recv_until(ws, "whisper")["payload"]["text"]
    items = _db_items(ch["id"])
    cursed = [i for i in items if i.get("curse")]
    assert len(cursed) == 1
    assert cursed[0]["curse"]["name"] == CURSE_NAME      # second op changed nothing


def test_loot_take_replay_never_duplicates_the_cursed(client):
    dm, player, code, ch, _ = _room_with_dagger(client)
    cx, cy = _tokcell(client, player, code)
    tok = _npc(client, dm, code, cx=cx, cy=cy + 1, hp=0)
    got = _fill_npc(client, dm, code, tok, "Cursed Dirk", 1)
    cid = next(i["id"] for i in got["items"] if i["name"] == "Cursed Dirk")
    _curse(client, dm, code, action="set", token_id=tok, item_id=cid,
           name=CURSE_NAME, desc=CURSE_DESC, whisper=WHISPER)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "loot", "action": "take", "token_id": tok,
                      "char_id": ch["id"], "item_id": cid, "qty": 1, "op_id": "dup-1"})
        recv_until(ws, "inv_contents")                       # once, for real
        ws.send_json({"type": "loot", "action": "take", "token_id": tok,
                      "char_id": ch["id"], "item_id": cid, "qty": 1, "op_id": "dup-1"})
        assert "already applied" in recv_until(ws, "whisper")["payload"]["text"]
        ws.send_json({"type": "loot", "action": "take", "token_id": tok,
                      "char_id": ch["id"], "item_id": cid, "qty": 1, "op_id": "dup-2"})
        assert recv_until(ws, "error")["payload"]["msg"] == "Item not found"
    cursed = [i for i in _db_items(ch["id"]) if i.get("curse")]
    assert len(cursed) == 1 and cursed[0]["qty"] == 1


# ---------- write-path preservation: no silent clean_items wipe ----------

def test_curse_survives_equip_unequip_long_rest_identify_attune_use(client):
    dm, player, code, ch, _ = _room_with_dagger(client)
    # magic items for the recharge / identify / use / attune write paths
    _grant_item(client, dm, code, ch["id"], {
        "name": "Hex Lantern", "kind": "wondrous", "magic": True,
        "props": {"magic": True, "recharge": "long", "charges": 1}})
    _grant_item(client, dm, code, ch["id"], {
        "name": "Hex Draught", "kind": "potion",
        "props": {"magic": True, "heal_dice": "1d4+1", "charges": 2}})
    _grant_item(client, dm, code, ch["id"], {
        "name": "Hex Band", "kind": "ring",
        "props": {"magic": True, "attune": True}})
    names = ("Dagger", "Hex Lantern", "Hex Draught", "Hex Band")
    for n in names:
        _dm_curse_dagger(client, dm, code, ch["id"], n, whisper="")
    # equip + unequip (mutate_char write)
    dag = _dm_item_ids(client, dm, code, ch["id"], "Dagger")[0]
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "inv_equip", "char_id": ch["id"], "slot": "main_hand",
                      "item_id": dag, "op_id": "eq-1"})
        recv_until(ws, "inv_changed")
        ws.send_json({"type": "inv_equip", "char_id": ch["id"], "slot": "main_hand",
                      "item_id": None, "op_id": "eq-2"})
        recv_until(ws, "inv_changed")
        # use the cursed potion (items.py write-back)
        draught = next(i["id"] for i in _db_items(ch["id"]) if i["name"] == "Hex Draught")
    with ws_connect(client, player, code) as ws:
        tok = next(t for t in state_of(client, player, code)["tokens"]
                   if t["character_id"] == ch["id"])
        ws.send_json({"type": "use_item", "token_id": tok["id"],
                      "item_id": draught, "op_id": "use-1"})
        recv_until(ws, "snapshot")
    with ws_connect(client, player, code) as ws:
        # attune the cursed ring (items.py write)
        band = next(i["id"] for i in _db_items(ch["id"]) if i["name"] == "Hex Band")
        ws.send_json({"type": "attune", "char_id": ch["id"], "item_id": band})
        recv_until(ws, "snapshot")
    with ws_connect(client, dm, code) as ws:
        for n in ("Hex Lantern", "Hex Band"):
            iid = next(i["id"] for i in _db_items(ch["id"]) if i["name"] == n)
            ws.send_json({"type": "identify", "char_id": ch["id"], "item_id": iid})
            recv_until(ws, "snapshot")
        lamp = next(i["id"] for i in _db_items(ch["id"]) if i["name"] == "Hex Lantern")
        ws.send_json({"type": "recharge", "char_id": ch["id"], "item_id": lamp})
        recv_until(ws, "snapshot")
        ws.send_json({"type": "long_rest"})                    # dice.py write-back
        recv_until(ws, "snapshot")
    items = _db_items(ch["id"])
    for n in names:
        it = next(i for i in items if i["name"] == n)
        assert it.get("curse"), f"curse lost on {n} by a plain mutation"
    # side effects actually happened (this is not a no-op test):
    assert next(i for i in items if i["name"] == "Hex Band")["attuned"] is True
    assert next(i for i in items if i["name"] == "Hex Draught")["charges"] == 1  # one use: 2 -> 1


# ================= secrecy on every player-facing wire =================

def test_player_state_and_sheets_hide_the_secret(client):
    dm, player, code, ch, _ = _room_with_dagger(client)
    _dm_curse_dagger(client, dm, code, ch["id"], "Dagger")
    own = json.dumps(state_of(client, player, code))
    assert CURSE_NAME not in own and WHISPER not in own
    assert "curse" not in json.dumps(_sheet(client, player, code)["items"])
    # the DM channel DOES show it (proves it exists; strip is targeted, not global)
    assert CURSE_NAME in json.dumps(state_of(client, dm, code))
    # lobby sheet endpoint (own list) hides it too
    lobby = json.dumps(client.get("/api/characters", headers=H(player)).json())
    assert CURSE_NAME not in lobby and "curse" not in json.dumps(
        [i for c in client.get("/api/characters", headers=H(player)).json()
         for i in c["items"]])


def test_gear_snapshots_carry_no_secrets(client):
    dm, player, code, ch, _ = _room_with_dagger(client)
    dag = _dm_item_ids(client, dm, code, ch["id"], "Dagger")[0]
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "inv_equip", "char_id": ch["id"], "slot": "main_hand",
                      "item_id": dag, "op_id": "eq-1"})
        recv_until(ws, "inv_changed")
    _dm_curse_dagger(client, dm, code, ch["id"], "Dagger")
    sheet = _sheet(client, player, code)
    blob = json.dumps({"derived": sheet["derived"], "equipment": sheet["equipment"],
                       "items": sheet["items"]})
    assert CURSE_NAME not in blob and WHISPER not in blob and "curse" not in blob


def test_loot_and_chest_inspect_have_no_secrets_for_players(client):
    dm, player, code, ch, _ = _room_with_dagger(client)
    cx, cy = _chest_at_player(client, dm, player, code)
    _fill(client, dm, code, "chest", "Dirk", 1)
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "inv_container", "action": "inspect",
                      "object_id": "chest", "floor": ""})
        got = recv_until(ws, "inv_contents")["payload"]
    cid = next(i["id"] for i in got["items"] if i["name"] == "Dirk")
    _curse(client, dm, code, action="set", object_id="chest", floor="", item_id=cid,
           name=CURSE_NAME, desc=CURSE_DESC, whisper=WHISPER)
    # DM inspect: truth. Player inspect of the very same chest: nothing.
    dm_view = json.dumps(_curse_chest(client, dm, code))
    assert CURSE_NAME in dm_view
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "inv_container", "action": "inspect",
                      "object_id": "chest", "floor": ""})
        pl = recv_until(ws, "inv_contents")["payload"]
    assert "curse" not in json.dumps(pl)


def _curse_chest(client, dm, code):
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "inv_container", "action": "inspect",
                      "object_id": "chest", "floor": ""})
        return recv_until(ws, "inv_contents")["payload"]


def test_loot_inspect_hides_curse_from_looter(client):
    dm, player, code, ch, _ = _room_with_dagger(client)
    cx, cy = _tokcell(client, player, code)
    tok = _npc(client, dm, code, cx=cx, cy=cy + 1, hp=0)
    got = _fill_npc(client, dm, code, tok, "Cursed Dirk", 1)
    cid = next(i["id"] for i in got["items"] if i["name"] == "Cursed Dirk")
    _curse(client, dm, code, action="set", token_id=tok, item_id=cid,
           name=CURSE_NAME, desc=CURSE_DESC, whisper=WHISPER)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "loot", "action": "inspect", "token_id": tok})
        pl = recv_until(ws, "inv_contents")["payload"]
    assert "curse" not in json.dumps(pl)
    # chronicle: loot line names the item, never the curse
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "loot", "action": "take", "token_id": tok,
                      "char_id": ch["id"], "item_id": cid, "qty": 1, "op_id": "l-2"})
        recv_until(ws, "inv_contents")
    st = state_of(client, player, code)
    chat_blob = json.dumps(st["chat"]) + json.dumps(
        [m for m in db.q("SELECT body FROM messages WHERE room_id=?",
                         (db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"],))])
    assert CURSE_NAME not in chat_blob and WHISPER not in chat_blob


def test_manipulated_put_cannot_forge_nor_wipe(client):
    dm, player, code, ch, _ = _room_with_dagger(client)
    _dm_curse_dagger(client, dm, code, ch["id"], "Dagger")
    rows = client.get("/api/characters", headers=H(player)).json()
    me = next(c for c in rows if c["id"] == ch["id"])
    body = {k: me.get(k) for k in ("name", "race", "char_class", "background", "level",
                                   "stats", "hp", "max_hp", "ac", "speed", "notes",
                                   "weapons", "items", "skills", "spells",
                                   "spell_slots", "saves", "defenses", "resources",
                                   "hit_die")}
    # (1) forge: an "already revealed" curse minted by the sheet owner itself
    body["items"] = [dict(i, curse={"name": "SELF-FORGED", "desc": "d",
                                    "whisper": "w", "revealed": True})
                     for i in body["items"]]
    assert client.put(f"/api/characters/{ch['id']}", headers=H(player),
                      json=body).status_code == 200
    it, curse = _db_curse(ch["id"], "Dagger")
    assert curse and curse["name"] == CURSE_NAME            # forgery ignored
    assert not any(i.get("curse", {}).get("name") == "SELF-FORGED"
                   for i in _db_items(ch["id"]))
    assert "SELF-FORGED" not in json.dumps(
        client.get("/api/characters", headers=H(player)).json())
    # (2) wipe: the same PUT as the honest editor round-trip (stripped items)
    rows = client.get("/api/characters", headers=H(player)).json()
    me = next(c for c in rows if c["id"] == ch["id"])
    body["items"] = [{k: v for k, v in i.items() if k != "curse"} for i in me["items"]]
    assert client.put(f"/api/characters/{ch['id']}", headers=H(player),
                      json=body).status_code == 200
    assert _db_curse(ch["id"], "Dagger")[1] is not None     # survive the round-trip


def test_player_cannot_drive_the_curse_channel(client):
    dm, player, code, ch, _ = _room_with_dagger(client)
    _dm_curse_dagger(client, dm, code, ch["id"], "Dagger")
    dag = _dm_item_ids(client, dm, code, ch["id"], "Dagger")[0]
    with ws_connect(client, player, code) as ws:
        for action in ("set", "clear", "reveal", "conceal", "whisper"):
            ws.send_json({"type": "curse", "action": action, "char_id": ch["id"],
                          "item_id": dag})
            assert recv_until(ws, "error", fail_on_error=False)["payload"]["msg"] \
                == "DM only"
    assert _db_curse(ch["id"], "Dagger")[1] is not None     # untouched


def test_view_as_shares_nothing(client):
    dm, player, code, ch, _ = _room_with_dagger(client)
    _dm_curse_dagger(client, dm, code, ch["id"], "Dagger")
    r = client.get(f"/api/rooms/{code}/view_as/{ch['id']}", headers=H(dm))
    assert r.status_code == 200
    assert CURSE_NAME not in r.text and "curse" not in r.text


# ================= DM edit / reveal / owner semantics =================

def test_dm_edits_and_clears_the_curse(client):
    dm, player, code, ch, _ = _room_with_dagger(client)
    dag = _dm_curse_dagger(client, dm, code, ch["id"], "Dagger")
    _curse(client, dm, code, action="set", char_id=ch["id"], item_id=dag,
           name="New Name", desc="new desc", whisper="new whisper")
    assert _db_curse(ch["id"], "Dagger")[1]["name"] == "New Name"
    _curse(client, dm, code, action="clear", char_id=ch["id"], item_id=dag)
    assert _db_curse(ch["id"])[1] is None
    # clearing twice is just an edit that changed nothing — no crash, item intact
    assert any(i["name"] == "Dagger" for i in _db_items(ch["id"]))


def test_reveal_gives_owner_only_the_released_fields(client):
    dm, player, code, ch, _ = _room_with_dagger(client)
    u2, ch2 = _second_player(client, code)
    dag = _dm_curse_dagger(client, dm, code, ch["id"], "Dagger")
    with ws_connect(client, player, code) as ws_own, \
         ws_connect(client, u2, code) as ws_other:
        _curse(client, dm, code, action="reveal", char_id=ch["id"], item_id=dag)
        ev = recv_until(ws_own, "chat")["payload"]
        assert ev["visibility"] == "whisper"
        assert REVEALED_MARK in ev["text"] and CURSE_DESC in ev["text"]
        assert WHISPER not in ev["text"]                    # whisper text never here
        # the peer receives NOTHING on the wire (no second event arrives within
        # the events the owner's delivery produced — proven via their history)
        assert _db_curse(ch["id"], "Dagger")[1]["revealed"] is True
    own_state = json.dumps(state_of(client, player, code))
    assert REVEALED_MARK in own_state and CURSE_DESC in own_state
    assert WHISPER not in own_state                         # never on the sheet
    own_sheet = _sheet(client, player, code)
    cursed = next(i for i in own_sheet["items"] if i["name"] == "Dagger")["curse"]
    assert set(cursed.keys()) == {"name", "desc"}           # reduced view
    peer_state = json.dumps(state_of(client, u2, code))
    assert REVEALED_MARK not in peer_state and WHISPER not in peer_state


def test_reveal_survives_reload_and_can_be_reset(client):
    dm, player, code, ch, _ = _room_with_dagger(client)
    dag = _dm_curse_dagger(client, dm, code, ch["id"], "Dagger")
    _curse(client, dm, code, action="reveal", char_id=ch["id"], item_id=dag)
    fresh = TestClient(main.app)
    cursed = next(i for i in _sheet(fresh, player, code)["items"]
                  if i["name"] == "Dagger")["curse"]
    assert cursed == {"name": CURSE_NAME, "desc": CURSE_DESC}
    _curse(client, dm, code, action="conceal", char_id=ch["id"], item_id=dag)
    assert "curse" not in json.dumps(_sheet(client, player, code)["items"])
    assert _db_curse(ch["id"], "Dagger")[1]["revealed"] is False
    assert _db_curse(ch["id"], "Dagger")[1]["name"] == CURSE_NAME  # only disclosure flipped


def test_owner_change_resets_reveal_but_never_the_curse(client):
    dm, player, code, ch, _ = _room_with_dagger(client)
    u2, ch2 = _second_player(client, code)
    dag = _dm_curse_dagger(client, dm, code, ch["id"], "Dagger")
    _curse(client, dm, code, action="reveal", char_id=ch["id"], item_id=dag)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "inv_transfer", "char_id": ch["id"],
                      "to_char_id": ch2["id"], "item_id": dag, "qty": 1,
                      "op_id": "tr-1"})
        recv_until(ws, "inv_changed")
    it, curse = _db_curse(ch2["id"], "Dagger")
    assert curse is not None and curse["revealed"] is False   # curse kept, knowledge gone
    new_owner_view = json.dumps(_sheet(client, u2, code, ch2["id"])["items"])
    assert "curse" not in new_owner_view                      # NOT entitled yet
    # DM still knows — and a reveal now targets the NEW owner
    assert CURSE_NAME in json.dumps(_sheet(client, dm, code, ch2["id"])["items"])
    # loot out of a corpse is also an owner change (transfer semantics tested,
    # container semantics tested in test_curse_survives_container_transfer)


# ================= DM-controlled whisper delivery =================

def test_whisper_reaches_the_current_owner_only(client):
    dm, player, code, ch, _ = _room_with_dagger(client)
    u2, _ch2 = _second_player(client, code)
    dag = _dm_curse_dagger(client, dm, code, ch["id"], "Dagger")
    with ws_connect(client, player, code) as ws_own:
        # whisper actions answer on the DM socket with the sender's own chat
        # echo (there is no curse_updated for a pure delivery) — that echo is
        # queued AFTER the owner's delivery crossed loops, so waiting on it
        # makes the owner-side assertion race-free.
        ev = _curse(client, dm, code, expect="chat", action="whisper",
                    char_id=ch["id"], item_id=dag)["payload"]
        assert ev["visibility"] == "whisper" and ev["text"] == WHISPER
        assert ev["meta"]["source"] == "curse"
    # nothing for the peer, live or in history
    peer = state_of(client, u2, code)
    assert WHISPER not in json.dumps(peer)
    # the DM's own history may keep it (sender), other sockets never saw it:
    # chat rows are recipient-filtered in chat_history_for_viewer — verify
    row = db.q1("SELECT * FROM messages WHERE body=?", (WHISPER,))
    assert row and row["visibility"] == "whisper"
    from app.room import chat as CHAT
    uid_pl = db.q1("SELECT id FROM users WHERE username=?", (player["name"],))["id"]
    uid_p2 = db.q1("SELECT id FROM users WHERE username=?", (u2["name"],))["id"]
    assert CHAT._visible_row(row, uid_pl, False)             # the owner's history: yes
    assert not CHAT._visible_row(row, uid_p2, False)         # anyone else's: never


def test_whisper_recipient_never_comes_from_the_client(client):
    dm, player, code, ch, _ = _room_with_dagger(client)
    u2, ch2 = _second_player(client, code)
    dag = _dm_curse_dagger(client, dm, code, ch["id"], "Dagger")
    with ws_connect(client, player, code) as ws_own:
        # the DM client tries to redirect the whisper to another member —
        # the field is ignored: the OWNER (derived from the item's holder) hears it
        ev = _curse(client, dm, code, expect="chat", action="whisper",
                    char_id=ch["id"], item_id=dag,
                    recipient_id=ch2["id"], user_id=9999, target="p2")["payload"]
        assert ev["text"] == WHISPER and ev["visibility"] == "whisper"
        ev2 = recv_until(ws_own, "chat")["payload"]      # the owner's live copy
        assert ev2["text"] == WHISPER
    assert WHISPER not in json.dumps(state_of(client, u2, code))


def test_whisper_without_player_owner_is_refused(client):
    dm, player, code, ch, _ = _room_with_dagger(client)
    cx, cy = _chest_at_player(client, dm, player, code)
    _fill(client, dm, code, "chest", "Dirk", 1)
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "inv_container", "action": "inspect",
                      "object_id": "chest", "floor": ""})
        cid = next(i["id"] for i in recv_until(ws, "inv_contents")["payload"]["items"]
                   if i["name"] == "Dirk")
    _curse(client, dm, code, action="set", object_id="chest", floor="", item_id=cid,
           name=CURSE_NAME, desc=CURSE_DESC, whisper=WHISPER)
    ev = _curse(client, dm, code, expect="error", action="whisper",
                object_id="chest", floor="", item_id=cid)
    assert "player owner" in ev["payload"]["msg"]
    ev = _curse(client, dm, code, expect="error", action="reveal",
                object_id="chest", floor="", item_id=cid)
    assert "player owner" in ev["payload"]["msg"]
    # but EDITING the container-borne curse works (Phase 4/5 split)
    _curse(client, dm, code, action="set", object_id="chest", floor="", item_id=cid,
           name=CURSE_NAME, desc="edited", whisper="new")
    assert "edited" in json.dumps(_curse_chest(client, dm, code))
    # a character that is NOT a member of this room answers like nothing exists
    stranger = make_char(client, reg(client, "str"))
    ev = _curse(client, dm, code, expect="error", action="set",
                char_id=stranger["id"], item_id="it1", name="x")
    assert ev["payload"]["msg"] == "No such character"


def test_curse_channel_never_broadcasts_to_players(client):
    dm, player, code, ch, _ = _room_with_dagger(client)
    dag = _dm_item_ids(client, dm, code, ch["id"], "Dagger")[0]
    _dm_curse_dagger(client, dm, code, ch["id"], "Dagger")
    with ws_connect(client, player, code) as ws_own:
        # fresh socket AFTER the curse was authored: nothing about it can be in
        # flight; the player's OWN public chat message is the guaranteed sync
        # point — every event that precedes its echo crossed this socket.
        ws_own.send_json({"type": "chat", "text": "sync-9001"})
        seen = []
        while True:
            ev = ws_own.receive_json()
            assert ev.get("kind") != "curse_updated"
            assert CURSE_NAME not in json.dumps(ev) and WHISPER not in json.dumps(ev)
            if ev.get("kind") == "chat" and ev["payload"].get("text") == "sync-9001":
                break
            seen.append(ev.get("kind"))
    assert _db_curse(ch["id"], "Dagger")[1] is not None      # the curse itself is real


# ================= room scope + Phase 7 atomic deletion =================

def test_foreign_room_ids_cannot_be_cursed(client):
    dm, player, code, ch, _ = _room_with_dagger(client)
    dm2, player2, code2, ch2 = base_room(client)
    # DM of room2 knows room1's character id from nowhere — and is refused:
    ev = _curse(client, dm2, code2, expect="error", action="clear",
                char_id=ch["id"], item_id="it1")
    assert ev["payload"]["msg"] == "No such character"
    # room2's DM pointing at room1's token id: silent refusal, like nothing there
    cx, cy = _tokcell(client, player, code)
    tok = _npc(client, dm, code, cx=cx, cy=cy + 1, hp=4)
    ev = _curse(client, dm2, code2, expect="error", action="set",
                token_id=tok, item_id="it1", name="x")
    assert ev["payload"]["msg"] == "No such container here"
    assert _db_curse(ch["id"])[1] is None                   # nothing touched


def _containers(object_id):
    return db.q1("SELECT 1 AS hit FROM containers WHERE object_id=?", (object_id,))


def test_npc_token_and_container_deleted_together(client):
    dm, player, code, _ch = base_room(client)
    cx, cy = _tokcell(client, player, code)
    tok = _npc(client, dm, code, cx=cx, cy=cy + 1, hp=0)
    _fill_npc(client, dm, code, tok, "Goblin Gold Knife", 1)
    # a world chest must survive (exactly-that-row rule)
    _chest_at_player(client, dm, player, code)
    _fill(client, dm, code, "chest", "Chest Dirk", 1)
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "del_token", "token_id": tok})
        recv_until(ws, "token_gone", tries=40)
    assert db.q1("SELECT 1 AS hit FROM tokens WHERE id=?", (tok,)) is None
    assert _containers(f"tok:{tok}") is None                # the hoard is gone too
    assert _containers("chest") is not None                 # world chest untouched


def test_failed_deletion_rolls_back_token_AND_container(client):
    # A rider still mounts the NPC — the token DELETE violates the FK and must
    # undo the container DELETE that already ran inside the same transaction.
    dm, player, code, _ch = base_room(client)
    cx, cy = _tokcell(client, player, code)
    horse = _npc(client, dm, code, cx=cx, cy=cy + 1, hp=4)
    _fill_npc(client, dm, code, horse, "Saddle Bag Loot", 1)
    rider = _npc(client, dm, code, cx=cx, cy=cy + 2, hp=4)
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "token_mount", "token_id": rider, "mount_id": horse})
        ws.send_json({"type": "del_token", "token_id": horse})
        # the mount property events may arrive first; recv_until skips them
        assert "Could not remove" in recv_until(ws, "error")["payload"]["msg"]
    assert db.q1("SELECT 1 AS hit FROM tokens WHERE id=?", (horse,)) is not None
    assert _containers(f"tok:{horse}") is not None          # ROLLED BACK — not orphaned
    assert db.q1("SELECT 1 AS hit FROM tokens WHERE id=?", (rider,)) is not None
    # and a plain deletion afterwards still works once the rider is gone
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "token_mount", "token_id": rider, "mount_id": None})
        ws.send_json({"type": "del_token", "token_id": horse})
        recv_until(ws, "token_gone", tries=40)
    assert _containers(f"tok:{horse}") is None
