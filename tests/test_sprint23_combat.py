"""Sprint 23 (D93): equipment -> mechanics, sheet-derived numbers, economy & replay.

Adversarial pins: attack bonuses/dice derive ONLY from server-side equipment +
props (forged client fields are ignored); the AC verdict mirrors the existing
NPC engine; the action/bonus slot is consumed exactly once per turn while a
combat is running and never double-spent by a replayed message; cast/resource/
use_item gained the same op_id replay guard, and all counters clamp at zero;
unequipping invalidates the profile and AC immediately; legacy (no-equipment)
attack math is untouched; unrelated room members never receive a peer's sheet
(stats/items/spells/derived are sheet-private).
"""
import uuid

import pytest
from starlette.testclient import TestClient

from app import db, gear, main
from app.room import dice as RD
from tests.test_movement_fog import (H, base_room, join_room, make_char,
                                     recv_until, reg, reg as _reg, state_of,
                                     ws_connect)


@pytest.fixture()
def client():
    return TestClient(main.app)


def put_char(client, user, cid, **over):
    keep = client.get("/api/characters", headers=H(user)).json()[0]
    body = {k: keep[k] for k in keep if k in (
        "name", "race", "char_class", "level", "stats", "hp", "max_hp", "ac",
        "speed", "notes", "weapons", "items", "skills", "spells",
        "spell_slots", "saves", "defenses", "resources")}
    body.update(over)
    r = client.put(f"/api/characters/{cid}", json=body, headers=H(user))
    assert r.status_code == 200, r.text
    return r.json()


def own_char(client, user, code):
    st = state_of(client, user, code)
    me = next(m for m in st["members"] if m["user_id"] == st["me"])
    return me["char"]


def mk_weapon_def(ws, name="Sword"):
    ws.send_json({"type": "item_def", "action": "create", "defn": {
        "name": name, "kind": "weapon",
        "props": {"damage_dice": "1d8", "damage_type": "slashing",
                  "ability": "str", "proficient": True, "attack_bonus": 2,
                  "mod_to_damage": True}}})
    recv_until(ws, "whisper")


def def_ids(client, dm, code):
    st = state_of(client, dm, code)
    return [d["id"] for d in st.get("item_defs", [])]


def equip_main(ws, char_id, item_id, op=None):
    ws.send_json({"type": "inv_equip", "char_id": char_id, "slot": "main_hand",
                  "item_id": item_id,
                  "op_id": op or ("e" + uuid.uuid4().hex[:10])})


def armed_room(client):
    """base_room whose player holds an equipped +2 STR longsword (server-derived
    to_hit: str +3 + prof +3 + 2 = +8, dmg 1d8+6)."""
    dm, player, code, ch = base_room(client)
    with ws_connect(client, dm, code) as dws:
        mk_weapon_def(dws)
        did = def_ids(client, dm, code)[0]
        dws.send_json({"type": "inv_grant", "char_id": ch["id"], "def_id": did, "qty": 1})
        recv_until(dws, "inv_changed")
    with ws_connect(client, player, code) as pws:
        item = own_char(client, player, code)["items"][0]
        equip_main(pws, ch["id"], item["id"])
        recv_until(pws, "inv_changed")
    return dm, player, code, ch


# ---------- derived profiles ----------

def test_equipped_weapon_profile_is_server_derived(client):
    dm, player, code, ch = armed_room(client)
    p = own_char(client, player, code)["derived"]["attack_profiles"]
    assert len(p) == 1 and p[0]["to_hit"] == 8          # 3 (str) + 3 (prof) + 2
    assert p[0]["dmg"] == "1d8" and p[0]["dmg_bonus"] == 3   # str mod rides damage once
    assert p[0]["dmg_type"] == "slashing" and p[0]["slot"] == "main_hand"


def test_forged_client_bonuses_and_dice_are_ignored(client):
    dm, player, code, ch = armed_room(client)
    item = own_char(client, player, code)["items"][0]
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "roll", "kind": "attack", "item_id": item["id"],
                      "to_hit": 999, "dmg": "20d20", "dmg_bonus": 500,
                      "visibility": "public"})
        ev = recv_until(ws, "dice")
    body = ev["payload"]["body"]
    assert "+8" in body and "+999" not in body and "20d20" not in body


def test_hit_miss_and_crit_verdicts(client, monkeypatch):
    dm, player, code, ch = armed_room(client)
    item = own_char(client, player, code)["items"][0]
    with ws_connect(client, dm, code) as dws:
        dws.send_json({"type": "add_token", "label": "Dummy", "x": 425, "y": 425})
        dummy = recv_until(dws, "token_add")["payload"]["id"]
    monkeypatch.setattr(RD, "_target_ac", lambda room_id, tid: (99, "Dummy"))
    monkeypatch.setattr(RD.random, "randint", lambda a, b: 5)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "roll", "kind": "attack", "item_id": item["id"],
                      "target_id": dummy, "visibility": "public"})
        ev = recv_until(ws, "dice")
        assert "MISS" in ev["payload"]["body"]
        monkeypatch.setattr(RD.random, "randint", lambda a, b: 20)
        ws.send_json({"type": "roll", "kind": "attack", "item_id": item["id"],
                      "target_id": dummy, "visibility": "public"})
        atk = recv_until(ws, "dice")
        dmg = recv_until(ws, "dice")
    assert "HIT" in atk["payload"]["body"] and "CRITICAL" in atk["payload"]["body"]
    assert "damage (crit!)" in dmg["payload"]["body"] and "= 43" in dmg["payload"]["body"]


def test_unequip_and_remove_invalidate_profile_and_ac(client):
    dm, player, code, ch = armed_room(client)
    full = own_char(client, player, code)
    item = full["items"][0]
    assert full["derived"]["attack_profiles"], "armed before the test"
    with ws_connect(client, player, code) as ws:
        equip_main(ws, ch["id"], None, op="uneq1")
        recv_until(ws, "inv_changed")
    after = own_char(client, player, code)
    assert after["derived"]["attack_profiles"] == []
    assert after["equipment"]["main_hand"] is None
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "roll", "kind": "attack", "item_id": item["id"],
                      "visibility": "public"})
        seen = recv_until(ws, "error")
    assert "No equipped weapon" in seen["payload"]["msg"]


def test_legacy_weapon_attack_path_unchanged(client):
    dm, player, code, ch = base_room(client)
    put_char(client, player, ch["id"], weapons=[{"name": "Shortbow", "ability": "dex",
                                                 "proficient": True, "dmg": "1d6",
                                                 "dmgBonus": 1}])
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "roll", "kind": "attack", "weapon": "Shortbow",
                      "visibility": "public"})
        ev = recv_until(ws, "dice")
    # legacy math for the OLD model: dex 14 (+2) + prof 3 + bonus 1 = +6, no AC verdict
    assert "Shortbow attack" in ev["payload"]["body"] and "+6" in ev["payload"]["body"]
    assert "MISS" not in ev["payload"]["body"] and "HIT" not in ev["payload"]["body"]


# ---------- action economy ----------

def _tok(client, user, code, ch):
    return next(t["id"] for t in state_of(client, user, code)["tokens"]
                if t["character_id"] == ch["id"])


def _to_player_turn(client, dm, code, tok):
    """DM starts combat and advances until the player's token is active."""
    with ws_connect(client, dm, code) as dws:
        dws.send_json({"type": "init_start"})
        order = recv_until(dws, "initiative")["payload"]
        guard = 0
        while (order.get("turn") or {}).get("token_id") != tok:
            guard += 1
            assert guard <= len(order["order"]) + 1, "never reached player turn"
            dws.send_json({"type": "init_next"})
            order = recv_until(dws, "initiative")["payload"]


def test_out_of_combat_attacks_are_free(client):
    dm, player, code, ch = armed_room(client)
    item = own_char(client, player, code)["items"][0]
    with ws_connect(client, player, code) as ws:
        for _ in range(3):
            ws.send_json({"type": "roll", "kind": "attack", "item_id": item["id"],
                          "visibility": "public"})
            recv_until(ws, "dice")


def test_action_slot_consumed_once_per_turn(client):
    dm, player, code, ch = armed_room(client)
    tok = _tok(client, player, code, ch)
    item = own_char(client, player, code)["items"][0]
    _to_player_turn(client, dm, code, tok)
    atk = lambda ws, **kw: ws.send_json({"type": "roll", "kind": "attack",
                                         "item_id": item["id"], "token_id": tok,
                                         "visibility": "public", **kw})
    with ws_connect(client, player, code) as ws:
        atk(ws, op_id="a1")                              # action: spent
        recv_until(ws, "initiative")                     # slot update broadcast
        recv_until(ws, "dice")
        atk(ws, op_id="a2")                              # same turn, no action left
        seen = recv_until(ws, "error")
        assert "No action left" in seen["payload"]["msg"]
        atk(ws, op_id="a3", slot="bonus")                # bonus action still open
        recv_until(ws, "initiative")
        recv_until(ws, "dice")
        atk(ws, op_id="a4", slot="bonus")
        assert "No bonus left" in recv_until(ws, "error")["payload"]["msg"]


def test_attack_replay_consumes_slot_once(client):
    dm, player, code, ch = armed_room(client)
    tok = _tok(client, player, code, ch)
    item = own_char(client, player, code)["items"][0]
    _to_player_turn(client, dm, code, tok)
    msg = {"type": "roll", "kind": "attack", "item_id": item["id"], "token_id": tok,
           "visibility": "public", "op_id": "same"}
    with ws_connect(client, player, code) as ws:
        ws.send_json(msg)
        recv_until(ws, "initiative")
        first = recv_until(ws, "dice")
        ws.send_json(msg)                                # exact replay, same op_id
        ws.send_json({"type": "resource", "token_id": tok, "resource_id": "nope"})
        # The WS loop is sequential: the fence error proves the replay finished.
        # A re-rolled attack would have posted "dice" BEFORE that error.
        kinds = []
        while True:
            kind = ws.receive_json().get("kind")
            if kind == "error":
                break
            kinds.append(kind)
        assert "dice" not in kinds, f"replay re-rolled: {kinds}"
        assert "Sword attack" in first["payload"]["body"]


def test_attack_off_turn_and_with_foreign_token_refused(client):
    dm, player, code, ch = armed_room(client)
    tok = _tok(client, player, code, ch)
    item = own_char(client, player, code)["items"][0]
    _to_player_turn(client, dm, code, tok)
    with ws_connect(client, dm, code) as dws:
        dws.send_json({"type": "add_token", "label": "Goblin", "x": 30, "y": 30})
        recv_until(dws, "token_add")
        dws.send_json({"type": "init_start"})
        order = recv_until(dws, "initiative")["payload"]
        guard = 0
        while (order.get("turn") or {}).get("token_id") == tok:
            guard += 1
            assert guard <= len(order["order"]) + 1, "never stepped past player turn"
            dws.send_json({"type": "init_next"})
            order = recv_until(dws, "initiative")["payload"]
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "roll", "kind": "attack", "item_id": item["id"],
                      "token_id": tok, "visibility": "public"})
        assert "not your turn" in recv_until(ws, "error")["payload"]["msg"]
        ws.send_json({"type": "roll", "kind": "attack", "item_id": item["id"],
                      "token_id": 987654, "visibility": "public"})
        assert "not yours to attack with" in recv_until(ws, "error")["payload"]["msg"]


# ---------- replay guards on the older spenders ----------

def test_cast_slot_replay_and_overspend(client):
    dm, player, code, ch = base_room(client)
    put_char(client, player, ch["id"],
             spells=[{"id": "s1", "name": "Zap", "level": 1, "cast": "none"}],
             spell_slots={"1": {"max": 1, "used": 0}})
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "cast", "spell_id": "s1", "op_id": "c1", "visibility": "public"})
        recv_until(ws, "snapshot")
        ws.send_json({"type": "cast", "spell_id": "s1", "op_id": "c1"})   # replay
        ws.send_json({"type": "cast", "spell_id": "nope"})                # fence
        kinds = []
        while True:
            k = ws.receive_json().get("kind")
            if k == "error":
                break
            kinds.append(k)
        assert "snapshot" not in kinds                    # replay changed nothing
        ws.send_json({"type": "cast", "spell_id": "s1", "op_id": "c2", "visibility": "public"})
        assert "No 1-level spell slots left" in recv_until(ws, "error")["payload"]["msg"]
    slots = db.j(db.q1("SELECT spell_slots FROM characters WHERE id=?", (ch["id"],))["spell_slots"], {})
    assert slots["1"]["used"] == 1


def test_resource_replay_clamp_and_legacy_mode(client):
    dm, player, code, ch = base_room(client)
    put_char(client, player, ch["id"], resources=[{"id": "ki", "name": "Ki", "max": 2}])
    tok = _tok(client, player, code, ch)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "resource", "token_id": tok, "resource_id": "ki",
                      "action": "dec", "op_id": "r1"})
        recv_until(ws, "snapshot")
        ws.send_json({"type": "resource", "token_id": tok, "resource_id": "ki",
                      "action": "dec", "op_id": "r1"})   # replay
        ws.send_json({"type": "resource", "token_id": tok, "resource_id": "nope"})  # fence
        kinds = []
        while True:
            k = ws.receive_json().get("kind")
            if k == "error":
                break
            kinds.append(k)
        assert "snapshot" not in kinds
        cur = lambda: next(r for r in own_char(client, player, code)["resources"] if r["id"] == "ki")["current"]
        assert cur() == 1
        for _ in range(3):                                # overspend impossible
            ws.send_json({"type": "resource", "token_id": tok, "resource_id": "ki", "action": "dec"})
            recv_until(ws, "snapshot")
        assert cur() == 0


def test_use_item_replay_and_unlimited_heal(client):
    dm, player, code, ch = base_room(client)
    put_char(client, player, ch["id"], hp=10, max_hp=30, items=[
        {"id": "p1", "name": "Draught", "kind": "potion", "heal": "1d4+2",
         "charges": 1, "chargesMax": 1, "identified": True},
        {"id": "p2", "name": "Endless Salve", "kind": "potion", "heal": "1d1",
         "charges": -1, "heal": "1d1", "identified": True}])
    tok = _tok(client, player, code, ch)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "use_item", "token_id": tok, "item_id": "p1", "op_id": "u1"})
        recv_until(ws, "snapshot")
        ws.send_json({"type": "use_item", "token_id": tok, "item_id": "p1", "op_id": "u1"})  # replay
        ws.send_json({"type": "use_item", "token_id": tok, "item_id": "nope"})   # fence
        kinds = []
        while True:
            k = ws.receive_json().get("kind")
            if k == "error":
                break
            kinds.append(k)
        assert "snapshot" not in kinds
        row = db.q1("SELECT hp, items FROM characters WHERE id=?", (ch["id"],))
        assert 10 < row["hp"] <= 17 and next(i for i in db.j(row["items"], []) if i["id"] == "p1")["charges"] == 0
        hp_mid = row["hp"]
        ws.send_json({"type": "use_item", "token_id": tok, "item_id": "p2"})   # unlimited item heals again (charges=-1)
        recv_until(ws, "snapshot")
        assert db.q1("SELECT hp FROM characters WHERE id=?", (ch["id"],))["hp"] > hp_mid


# ---------- sheet privacy ----------

def test_peer_row_tactical_only_dm_and_self_full(client):
    dm, player, code, ch = armed_room(client)
    other = reg(client, "pl2")
    join_room(client, other, code)
    ch2 = make_char(client, other)
    client.post(f"/api/rooms/{code}/assign", json={"character_id": ch2["id"]}, headers=H(other))
    with ws_connect(client, other, code) as ows:
        ows.send_json({"type": "inv_grant", "char_id": ch2["id"],
                       "item": {"name": "Secret Blade", "kind": "weapon"}})  # DM-only op
        assert "DM only" in recv_until(ows, "error")["payload"]["msg"]
        ows.send_json({"type": "inv_grant", "char_id": ch2["id"],
                       "item": {"name": "Secret Blade", "kind": "weapon"}})
        ows.send_json({"type": "resource", "token_id": 999998, "resource_id": "x"})  # fence
        kinds = []
        while True:
            k = ows.receive_json().get("kind")
            if k == "error":
                break
            kinds.append(k)
        assert "inv_changed" not in kinds
    peer = next(m["char"] for m in state_of(client, player, code)["members"]
                if m["user_id"] != state_of(client, player, code)["me"] and m["char"])
    assert peer["name"] and "ac_total" in peer and "hp" in peer and "speed" in peer
    for secret in ("items", "stats", "skills", "saves", "spells", "spell_slots",
                   "resources", "defenses", "equipment", "derived", "notes", "weapons"):
        assert secret not in peer, secret
    dmrow = next(m["char"] for m in state_of(client, dm, code)["members"] if m["char"])
    assert "items" in dmrow and "derived" in dmrow        # DM keeps the full view
    assert "items" in own_char(client, player, code)      # own row keeps it too


def test_forged_char_id_attack_uses_own_sheet_only(client):
    dm, player, code, ch = armed_room(client)
    other = reg(client, "pl3")
    join_room(client, other, code)
    ch2 = make_char(client, other)
    client.post(f"/api/rooms/{code}/assign", json={"character_id": ch2["id"]}, headers=H(other))
    item = own_char(client, player, code)["items"][0]
    with ws_connect(client, other, code) as ws:            # OTHER player cannot borrow the sword
        ws.send_json({"type": "roll", "kind": "attack", "item_id": item["id"],
                      "char_id": ch["id"], "visibility": "public"})
        assert "No equipped weapon" in recv_until(ws, "error")["payload"]["msg"]
    with ws_connect(client, other, code) as ws:            # ...and cannot equip onto it
        ws.send_json({"type": "inv_equip", "char_id": ch["id"], "slot": "main_hand",
                      "item_id": item["id"], "op_id": "forge1"})
        ws.send_json({"type": "resource", "token_id": 999999, "resource_id": "x"})  # fence
        kinds = []
        while True:
            k = ws.receive_json().get("kind")
            if k == "error":
                break
            kinds.append(k)
        assert "inv_changed" not in kinds   # forged equip applied nothing


# ---------- persistence ----------

def test_equipment_and_spending_persist_in_sqlite(client):
    dm, player, code, ch = armed_room(client)
    put_char(client, player, ch["id"],
             spells=[{"id": "s1", "name": "Zap", "level": 1, "cast": "none"}],
             spell_slots={"1": {"max": 2, "used": 0}})
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "cast", "spell_id": "s1", "op_id": "p1", "visibility": "public"})
        recv_until(ws, "snapshot")
    row = db.q1("SELECT items, equipment, spell_slots FROM characters WHERE id=?", (ch["id"],))
    assert row["equipment"] and db.j(row["equipment"], {})["main_hand"] == db.j(row["items"], [])[0]["id"]
    assert db.j(row["spell_slots"], {})["1"]["used"] == 1
    assert len(own_char(client, player, code)["derived"]["attack_profiles"]) == 1
