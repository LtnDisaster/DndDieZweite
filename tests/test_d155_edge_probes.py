"""D155 (Night-shift 4.0): deterministic edge-case probes.

Areas the regression brief called out — resource spend on refusal/replay,
consumables, dying/heal boundaries, plane-crossing adjacency, transfer
races, slot double-send, dirty CSV values. Every probe is deterministic
(no luck-dependent asserts); where the engine is defensive, the probe
stays as a pinned invariant.
"""
import uuid

import pytest
from starlette.testclient import TestClient

from app import db, gear, main
from tests.test_d106_curses import _db_items, _grant_item
from tests.test_integration import _death_state, make_char, reg, state_of
from tests.test_movement_fog import (H, base_room, join_room, recv_until,
                                     ws_connect)


@pytest.fixture
def client():
    return TestClient(main.app)


def drain(ws, tag, cap=120):
    """Flush until our marker chat line comes back — everything before it
    belongs to the message under test."""
    ws.send_json({"type": "chat", "text": f"@@{tag}@@"})
    out = []
    while len(out) < cap:
        ev = ws.receive_json()
        if ev.get("kind") == "chat" and f"@@{tag}@@" in str(ev.get("payload", {}).get("text", "")):
            return out
        out.append(ev)
    raise AssertionError("flush marker never arrived")


def error_of(evs):
    errs = [e for e in evs if e.get("kind") == "error"]
    return errs[0]["payload"]["msg"] if errs else None


def rid(code):
    return db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]


def token_of(code, char_id):
    return next(t for t in db.q("SELECT * FROM tokens WHERE room_id=?", (rid(code),))
                if t["character_id"] == char_id)


# ---------- consumables (D152 edges) ----------

def _vial():
    return {"name": "Edge Draught", "kind": "potion", "props": {"heal_dice": "2d4+2"}}


def test_full_hp_use_still_spends_the_dose(client):
    # SRD: a drunk potion is gone even if it healed nothing.
    dm, player, code, ch = base_room(client)
    _grant_item(client, dm, code, ch["id"], _vial(), qty=2)
    tok = token_of(code, ch["id"])
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "use_item", "token_id": tok["id"],
                      "item_id": _db_items(ch["id"])[0]["id"],
                      "op_id": "u" + uuid.uuid4().hex[:8]})
        drain(ws, "usefull")
    items = _db_items(ch["id"])
    assert items and items[0]["qty"] == 1        # one dose burned at full HP


def test_uncounted_scroll_is_consumed_too(client):
    dm, player, code, ch = base_room(client)
    _grant_item(client, dm, code, ch["id"],
                {"name": "Edge Scroll", "kind": "scroll", "props": {"heal_dice": "1d4+1"}})
    tok = token_of(code, ch["id"])
    ent = _db_items(ch["id"])[0]
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "use_item", "token_id": tok["id"], "item_id": ent["id"],
                      "op_id": "u" + uuid.uuid4().hex[:8]})
        drain(ws, "scroll")
    assert _db_items(ch["id"]) == []


def test_heal_while_dying_ends_the_death_state(client):
    # engine invariant: real healing over 0 also clears death (items.py);
    # the dying hero who drinks comes back WITHOUT rolling saves.
    dm, player, code, ch = base_room(client)
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "hp", "token_id": token_of(code, ch["id"])["id"],
                      "delta": -db.q1("SELECT hp FROM characters WHERE id=?",
                                      (ch["id"],))["hp"]})
        drain(ws, "drop")
    assert _death_state(client, dm, code, ch["id"])["dead"] is False
    _grant_item(client, dm, code, ch["id"], _vial())
    ent = _db_items(ch["id"])[0]
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "use_item", "token_id": token_of(code, ch["id"])["id"],
                      "item_id": ent["id"], "op_id": "u" + uuid.uuid4().hex[:8]})
        drain(ws, "revive")
    assert _death_state(client, dm, code, ch["id"]) is None
    assert db.q1("SELECT hp FROM characters WHERE id=?", (ch["id"],))["hp"] > 0


# ---------- turn economy without combat ----------

def test_turn_mark_outside_combat_refused(client):
    dm, player, code, ch = base_room(client)
    tok = token_of(code, ch["id"])
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "turn_mark", "token_id": tok["id"],
                      "slot": "action", "value": "used"})
        assert "active turn" in error_of(drain(ws, "mark"))


# ---------- plane-crossing adjacency on the stabilize path ----------

def test_same_cell_other_floor_is_not_adjacent(client):
    dm, player, code, ch = base_room(client)
    mate = reg(client, "mate")
    join_room(client, mate, code)
    och = make_char(client, mate, name="Patient")
    client.post(f"/api/rooms/{code}/assign", json={"character_id": och["id"]},
                headers=H(mate))
    atok, otok = token_of(code, ch["id"]), token_of(code, och["id"])
    db.x("UPDATE tokens SET x=0, y=0 WHERE id=?", (atok["id"],))
    db.x("UPDATE tokens SET x=0, y=0 WHERE id=?", (otok["id"],))
    db.x("UPDATE characters SET hp=0 WHERE id=?", (och["id"],))
    db.x("UPDATE tokens SET death=? WHERE id=?",
         (db.json_dumps({"s": 0, "f": 0, "stable": False, "dead": False}), otok["id"]))
    assert client.post(f"/api/rooms/{code}/floors",
                       json={"name": "crypt"}, headers=H(dm)).status_code == 200
    db.x("UPDATE tokens SET floor='crypt' WHERE id=?", (otok["id"],))
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "stabilize", "token_id": atok["id"],
                      "target_token_id": otok["id"], "op_id": "s" + uuid.uuid4().hex[:8]})
        assert "next to the patient" in error_of(drain(ws, "stab"))


# ---------- transfers ----------

def test_transfer_to_foreign_room_character_refused(client):
    dm, player, code, ch = base_room(client)
    stranger = reg(client, "stranger")
    sch = make_char(client, stranger, name="Nobody")     # never joined this room
    _grant_item(client, dm, code, ch["id"], {"name": "Coin Purse", "kind": "gear",
                                             "props": {}})
    ent = _db_items(ch["id"])[0]
    tok = token_of(code, ch["id"])
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "inv_transfer", "char_id": ch["id"],
                      "to_char_id": sch["id"], "item_id": ent["id"], "qty": 1,
                      "op_id": "t" + uuid.uuid4().hex[:8]})
        assert "Who is that" in error_of(drain(ws, "who"))
    assert [i["id"] for i in _db_items(ch["id"])] == [ent["id"]]   # nothing left


def test_transfer_completes_exactly_once_when_sender_disconnects(client):
    # The write transaction is server-side: closing the socket right after
    # sending must neither lose the transfer nor allow a re-delivery.
    dm, player, code, ch = base_room(client)
    mate = reg(client, "mate")
    join_room(client, mate, code)
    och = make_char(client, mate, name="Getter")
    client.post(f"/api/rooms/{code}/assign", json={"character_id": och["id"]},
                headers=H(mate))
    oid = str(och["id"])
    _grant_item(client, dm, code, ch["id"],
                {"name": "Shared Rope", "kind": "gear", "props": {}}, qty=2)
    ent = _db_items(ch["id"])[0]
    op = "t" + uuid.uuid4().hex[:8]
    with ws_connect(client, player, code) as ws:      # NO recv — instant close
        ws.send_json({"type": "inv_transfer", "char_id": ch["id"],
                      "to_char_id": int(oid), "item_id": ent["id"], "qty": 1,
                      "op_id": op})
    src = next(i for i in _db_items(ch["id"]) if i["name"] == "Shared Rope")
    assert src["qty"] == 1


# ---------- slot spend: refusal and replay (double-send) ----------

def _caster(client, dm, code):
    ch = make_char(client, dm, name="Caster",
                   spells=[{"id": "sp-fire", "name": "Fire Bolt", "level": 1,
                            "cast": "save", "prepared": True, "prep": True,
                            "dc": 13}],
                   spell_slots={"1": {"max": 2, "used": 0}})
    client.post(f"/api/rooms/{code}/assign", json={"character_id": ch["id"]},
                headers=H(dm))
    return ch


def _slots(client, dm, code, cid):
    import json as _json
    return db.j(db.q1("SELECT spell_slots FROM characters WHERE id=?", (cid,))["spell_slots"], {})


def test_cast_replay_consumes_slot_exactly_once(client):
    dm, player, code, _ = base_room(client)
    ch = _caster(client, dm, code)   # the caster rides the DM's own sheet
    tok = token_of(code, ch["id"])
    op = "c" + uuid.uuid4().hex[:8]
    with ws_connect(client, dm, code) as ws:
        for _ in range(2):
            ws.send_json({"type": "cast", "spell_id": "sp-fire", "token_id": tok["id"],
                          "op_id": op})
        drain(ws, "cast2")
    assert _slots(client, dm, code, ch["id"])["1"]["used"] == 1


def test_cast_without_slots_refuses_without_writing(client):
    dm, player, code, _ = base_room(client)
    ch = _caster(client, dm, code)
    tok = token_of(code, ch["id"])
    with ws_connect(client, dm, code) as ws:
        for _ in range(3):
            ws.send_json({"type": "cast", "spell_id": "sp-fire", "token_id": tok["id"],
                          "op_id": "c" + uuid.uuid4().hex[:8]})
        evs = drain(ws, "dry")
    assert "No 1-level spell slots left" in str(evs)
    assert _slots(client, dm, code, ch["id"])["1"]["used"] == 2   # 2 of 2 spent, not 3


# ---------- dirty CSV / item data ----------

def test_clean_items_survives_garbage_values():
    items = gear.clean_items([
        {"id": "a", "name": "Bad Qty", "qty": -5, "weight": "abc"},
        {"id": "b", "name": "Huge Charges", "kind": "wand", "charges": 99999,
         "recharge": "long", "heal_dice": "not-a-dice"},
        {"id": "c", "name": "Null Entry"},
    ])
    by_id = {i["id"]: i for i in items}
    assert by_id["a"]["qty"] >= 1                       # never negative/zero
    assert isinstance(by_id["a"]["weight"], (int, float))
    assert 0 <= by_id["b"]["charges"] <= 999            # clamped
    assert not by_id["b"]["heal"]                        # bad dice -> no heal
    assert by_id["c"]["name"] == "Null Entry"


# ---------- NPC authority ----------

def test_player_cannot_drive_an_npc_attack(client):
    dm, player, code, ch = base_room(client)
    db.x("UPDATE tokens SET x=0, y=0 WHERE room_id=? AND character_id=?",
         (rid(code), ch["id"]))
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "add_token", "label": "Brute", "x": 50, "y": 0,
                      "max_hp": 20, "hp": 20,
                      "attacks": [{"id": "bite", "name": "Bite", "to_hit": 5,
                                   "dmg": "1d6"}]})
        npc_id = recv_until(ws, "token_add")["payload"]["id"]
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "npc_attack", "token_id": npc_id, "attack": "bite",
                      "target_id": token_of(code, ch["id"])["id"]})
        evs = drain(ws, "npc")
    assert not [e for e in evs if e.get("kind") == "dice"]      # silent authz refusal
    # the DM still can
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "npc_attack", "token_id": npc_id, "attack": "bite",
                      "target_id": token_of(code, ch["id"])["id"]})
        evs = drain(ws, "npc2")
    assert [e for e in evs if e.get("kind") == "dice"]


# ---------- documented deviation pin ----------

def test_dying_short_rest_revive_is_pinned_current_design(client):
    # CURRENT engine design (DECISIONS: "short rest is owner-or-DM and is
    # hit-dice based"; pinned since D-era in test_integration): a dying hero
    # CAN self-revive with hit dice. 2014 RAW would demand consciousness.
    # Flagged in docs/REGRESSION_AUDIT_2026-10-18.md as a rule the operator
    # may want to call — this test keeps any future change VISIBLE.
    dm, player, code, ch = base_room(client)
    tok = token_of(code, ch["id"])
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "hp", "token_id": tok["id"],
                      "delta": -db.q1("SELECT hp FROM characters WHERE id=?",
                                      (ch["id"],))["hp"]})
        drain(ws, "drop2")
    assert _death_state(client, dm, code, ch["id"])["dead"] is False
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "short_rest", "token_id": tok["id"], "hit_dice_count": 3})
        drain(ws, "rest")
    assert _death_state(client, dm, code, ch["id"]) is None
    assert db.q1("SELECT hp FROM characters WHERE id=?", (ch["id"],))["hp"] > 0
