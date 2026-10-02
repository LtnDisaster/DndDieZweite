"""Sprint 7 — generic ability engine: derived stats, saves, damage pipeline, resources.

Fixtures use ONLY original mechanical names (Training Bolt etc.) — the engine is
tested without any copyrighted spell content (D55).
"""
import json
import uuid

import pytest
from starlette.testclient import TestClient

from app import abilities, db, gear
from app.main import app

from test_movement_fog import (H, add_npc, base_room, reg, recv_until,
                               set_grid, state_of, wall_column, ws_connect)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


DEFS = [
    {"id": "training_bolt", "name": "Training Bolt", "ability": "int", "range_ft": 120,
     "targeting": "single", "resolution": "save", "save": "dex", "on_save": "half",
     "damage": "3d6", "damage_type": "fire"},
    {"id": "training_burst", "name": "Training Burst", "ability": "int", "range_ft": 60,
     "targeting": "area", "shape": "circle", "size_ft": 5,
     "resolution": "save", "save": "dex", "on_save": "half",
     "damage": "3d6", "damage_type": "fire", "cost": {"type": "spell_slot", "level": 1}},
    {"id": "medic_pulse", "name": "Medic Pulse", "ability": "wis", "range_ft": 0,
     "targeting": "self", "resolution": "auto", "heal": "2d4+2"},
    {"id": "grapple_bind", "name": "Grapple Bind", "ability": "str", "range_ft": 30,
     "targeting": "point", "resolution": "auto",
     "condition": {"key": "restrained", "rounds": 2}},
    {"id": "focus_gaze", "name": "Focus Gaze", "ability": "wis", "range_ft": 0,
     "targeting": "self", "resolution": "auto", "concentration": True},
    {"id": "training_beam", "name": "Training Beam", "ability": "int", "range_ft": 60,
     "targeting": "single", "resolution": "attack",
     "damage": "1d8", "damage_type": "force"},
    {"id": "dart_prick", "name": "Dart Prick", "ability": "dex", "range_ft": 60,
     "targeting": "point", "resolution": "auto", "damage": "1d4",
     "damage_type": "piercing"},
]


@pytest.fixture(autouse=True)
def _registry():
    for d in DEFS:
        assert abilities.register(d) is not None
    yield


def room_id_of(code):
    return db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]


def token_of(code, character_id):
    return db.q1("SELECT * FROM tokens WHERE room_id=? AND character_id=?",
                 (room_id_of(code), character_id))


def fake_rolls(monkeypatch, script):
    """Deterministic do_roll: script maps expression → queued totals."""
    from app.room import dice as RD
    queues = {k: list(v) for k, v in script.items()}

    def fake(expr, adv=None):
        v = queues[expr].pop(0)
        return {"expr": expr, "rolls": [v], "kept": v, "mod": 0, "total": v, "adv": None}
    monkeypatch.setattr(RD, "do_roll", fake)


def make_caster_npc(client, dm, code, label="Rival", x=15, y=2, abilities_=None):
    """NPC token with a full stat block (INT 16, level 5 → PB +3, DC 14)."""
    with ws_connect(client, dm, code) as ws:
        tid = add_npc(ws, label=label, cx=x, cy=y)
        db.x("UPDATE tokens SET npc=? WHERE id=?", (db.json_dumps({
            "name": label, "level": 5, "ac": 12,
            "stats": {"str": 10, "dex": 10, "con": 10, "int": 16, "wis": 10, "cha": 10},
            "abilities": abilities_ or [d["id"] for d in DEFS],
        }), tid))
    return tid


def player_cell(code, ch):
    tok = token_of(code, ch["id"])
    return int(tok["x"] // 50), int(tok["y"] // 50)


# ---------- Part A: derived spellcasting stats ----------

def test_ability_modifier_save_dc_and_attack_are_one_derivation():
    ch = {"stats": {"int": 16}, "level": 5}                    # PB +3 at level 5
    assert gear.stat_mod(ch, "int") == 3
    assert gear.ability_save_dc(ch, "int") == 14
    assert gear.ability_attack_bonus(ch, "int") == 6
    assert gear.ability_save_dc(ch, "int", 2) == 16            # explicit bonus only
    assert gear.stat_mod(ch, "nonsense") == 0
    assert gear.stat_mod({"stats": {"int": 999}}, "int") == 10  # clamps to score 30
    # multiclass: total 6 from two classes → PB +3 regardless of legacy column
    mc = {"class_levels": json.dumps([{"class_id": "warrior", "level": 3},
                                      {"class_id": "adept", "level": 3}]),
          "stats": {"int": 16}, "level": 1}
    assert gear.ability_save_dc(mc, "int") == 14


def test_clean_definition_rejects_junk_whole():
    assert abilities.clean_definition({"id": "x y", "name": "Bad"}) is None
    assert abilities.clean_definition({"name": "No id"}) is None
    assert abilities.clean_definition(
        {"id": "a", "name": "A", "targeting": "area", "shape": "blob"}) is None
    assert abilities.clean_definition(
        {"id": "a", "name": "A", "damage": "3d6"}) is None      # damage needs a type
    assert abilities.clean_definition(
        {"id": "a", "name": "A", "resolution": "save"}) is None  # save needs an ability
    assert abilities.clean_definition(
        {"id": "a", "name": "A", "cost": {"type": "mana"}}) is None
    ok = abilities.clean_definition({"id": "a", "name": "A"})
    assert ok and ok["targeting"] == "single" and ok["los_required"] is True


# ---------- Part D: saving-throw resolution through the damage pipeline ----------

def test_training_bolt_save_fail_and_success_use_typed_damage(client, monkeypatch):
    dm, player, code, ch = base_room(client)
    ptok = token_of(code, ch["id"])
    npc_tok = make_caster_npc(client, dm, code)
    db.x("UPDATE characters SET stats=?, saves=?, hp=? WHERE id=?",
         (db.json_dumps({"int": 16, "dex": 10}), "{}", 30, ch["id"]))

    fake_rolls(monkeypatch, {"1d20": [3], "3d6": [21]})         # fails vs DC 14
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "ability_cast", "token_id": npc_tok,
                      "ability_id": "training_bolt", "target_id": ptok["id"]})
        r = recv_until(ws, "ability_result")["payload"]
    assert r["dc"] == 14 and r["entries"][0]["save"]["success"] is False
    assert r["entries"][0]["damage"] == 21
    assert db.q1("SELECT hp FROM characters WHERE id=?", (ch["id"],))["hp"] == 9

    db.x("UPDATE characters SET hp=30 WHERE id=?", (ch["id"],))
    fake_rolls(monkeypatch, {"1d20": [20], "3d6": [21]})        # saves → half (floor first)
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "ability_cast", "token_id": npc_tok,
                      "ability_id": "training_bolt", "target_id": ptok["id"]})
        r = recv_until(ws, "ability_result")["payload"]
    assert r["entries"][0]["save"]["success"] is True
    assert r["entries"][0]["damage"] == 10                      # 21 // 2
    assert db.q1("SELECT hp FROM characters WHERE id=?", (ch["id"],))["hp"] == 20


def test_resist_immune_flow_through_existing_defense_logic(client, monkeypatch):
    dm, player, code, ch = base_room(client)
    ptok = token_of(code, ch["id"])
    npc_tok = make_caster_npc(client, dm, code)
    db.x("UPDATE characters SET stats=?, saves=?, hp=?, defenses=? WHERE id=?",
         (db.json_dumps({"dex": 10}), "{}", 30,
          db.json_dumps({"resist": ["fire"]}), ch["id"]))
    fake_rolls(monkeypatch, {"1d20": [1], "3d6": [21]})
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "ability_cast", "token_id": npc_tok,
                      "ability_id": "training_bolt", "target_id": ptok["id"]})
        r = recv_until(ws, "ability_result")["payload"]
    assert r["entries"][0]["damage"] == 10                      # 21 fail-save → resist → 10
    assert db.q1("SELECT hp FROM characters WHERE id=?", (ch["id"],))["hp"] == 20

    db.x("UPDATE characters SET hp=30, defenses=? WHERE id=?",
         (db.json_dumps({"immune": ["fire"]}), ch["id"]))
    fake_rolls(monkeypatch, {"1d20": [1], "3d6": [21]})
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "ability_cast", "token_id": npc_tok,
                      "ability_id": "training_bolt", "target_id": ptok["id"]})
        r = recv_until(ws, "ability_result")["payload"]
    assert r["entries"][0]["damage"] == 0 and r["entries"][0]["immune"] is True
    assert db.q1("SELECT hp FROM characters WHERE id=?", (ch["id"],))["hp"] == 30


def test_ability_damage_enters_death_pipeline_not_bypassed(client, monkeypatch):
    dm, player, code, ch = base_room(client)
    ptok = token_of(code, ch["id"])
    npc_tok = make_caster_npc(client, dm, code)
    db.x("UPDATE characters SET hp=1, max_hp=10 WHERE id=?", (ch["id"],))
    fake_rolls(monkeypatch, {"1d20": [1], "3d6": [9]})
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "ability_cast", "token_id": npc_tok,
                      "ability_id": "training_bolt", "target_id": ptok["id"]})
        recv_until(ws, "ability_result")
    assert db.j(db.q1("SELECT death FROM tokens WHERE id=?", (ptok["id"],))["death"]) \
        .get("s") is not None                                   # dying-state machinery ran


# ---------- Part C: heal + condition effects reuse their systems ----------

def test_heal_uses_central_health_logic(client, monkeypatch):
    dm, player, code, ch = base_room(client)
    ptok = token_of(code, ch["id"])
    db.x("UPDATE characters SET hp=10 WHERE id=?", (ch["id"],))
    db.x("UPDATE characters SET abilities=? WHERE id=?",
         (db.json_dumps(["medic_pulse"]), ch["id"]))
    fake_rolls(monkeypatch, {"2d4+2": [9]})
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "ability_cast", "token_id": ptok["id"],
                      "ability_id": "medic_pulse"})
        r = recv_until(ws, "ability_result")["payload"]
    assert r["entries"][0]["heal"] == 9
    assert db.q1("SELECT hp FROM characters WHERE id=?", (ch["id"],))["hp"] == 19


def test_condition_effect_stores_on_existing_condition_system(client, monkeypatch):
    dm, player, code, ch = base_room(client)
    from app import conditions as C
    npc_tok = make_caster_npc(client, dm, code)
    px, py = player_cell(code, ch)
    fake_rolls(monkeypatch, {})
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "ability_cast", "token_id": npc_tok,
                      "ability_id": "grapple_bind", "x": px, "y": py})
        r = recv_until(ws, "ability_result")["payload"]
    assert r["entries"][0]["condition"] == "restrained"
    tok = db.q1("SELECT conds FROM tokens WHERE id=?", (token_of(code, ch["id"])["id"],))
    assert any(c["k"] == "restrained" and c["rounds"] == 2 for c in C.load(tok))


def test_concentration_uses_existing_flag(client):
    dm, player, code, ch = base_room(client)
    ptok = token_of(code, ch["id"])
    db.x("UPDATE characters SET abilities=? WHERE id=?",
         (db.json_dumps(["focus_gaze"]), ch["id"]))
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "ability_cast", "token_id": ptok["id"],
                      "ability_id": "focus_gaze"})
        recv_until(ws, "ability_result")
    from app import conditions as C
    assert C.is_concentrating(C.load(db.q1("SELECT conds FROM tokens WHERE id=?",
                                           (ptok["id"],))))


# ---------- Part F: slots + generic resources ----------

def test_slot_consumption_and_exhaustion(client, monkeypatch):
    dm, player, code, ch = base_room(client)
    ptok = token_of(code, ch["id"])
    db.x("UPDATE characters SET abilities=?, spell_slots=?, hp=?, stats=?, saves=? WHERE id=?",
         (db.json_dumps(["training_burst"]),
          db.json_dumps({1: {"max": 1, "used": 0}}), 30,
          db.json_dumps({"dex": 10}), "{}", ch["id"]))
    px, py = player_cell(code, ch)
    fake_rolls(monkeypatch, {"1d20": [1], "3d6": [10]})
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "ability_cast", "token_id": ptok["id"],
                      "ability_id": "training_burst", "x": px, "y": py})
        r = recv_until(ws, "ability_result")["payload"]
        assert r["consumed"] == {"type": "spell_slot", "level": 1}
        # exactly ONE slot existed — second cast must refuse and change nothing
        ws.send_json({"type": "ability_cast", "token_id": ptok["id"],
                      "ability_id": "training_burst", "x": px, "y": py})
        e = recv_until(ws, "error")
    assert "1-level spell slots" in e["payload"]["msg"]
    slots = gear.clean_slots(db.j(db.q1("SELECT spell_slots FROM characters WHERE id=?",
                                        (ch["id"],))["spell_slots"]))
    assert slots[1] == {"max": 1, "used": 1}                    # never went negative/second
    assert db.q1("SELECT hp FROM characters WHERE id=?", (ch["id"],))["hp"] == 20


def test_upcast_level_validated_not_applied_silently(client, monkeypatch):
    dm, player, code, ch = base_room(client)
    ptok = token_of(code, ch["id"])
    db.x("UPDATE characters SET abilities=?, spell_slots=?, stats=?, saves=? WHERE id=?",
         (db.json_dumps(["training_burst"]),
          db.json_dumps({1: {"max": 1, "used": 0}, 2: {"max": 1, "used": 0}}),
          db.json_dumps({"dex": 10}), "{}", ch["id"]))
    px, py = player_cell(code, ch)
    fake_rolls(monkeypatch, {"1d20": [1], "3d6": [2]})
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "ability_cast", "token_id": ptok["id"],
                      "ability_id": "training_burst", "x": px, "y": py,
                      "cast_level": 0})
        assert recv_until(ws, "error")["payload"]["msg"] == "Invalid cast level"
        ws.send_json({"type": "ability_cast", "token_id": ptok["id"],
                      "ability_id": "training_burst", "x": px, "y": py,
                      "cast_level": 2})
        r = recv_until(ws, "ability_result")["payload"]
    assert r["consumed"]["level"] == 2
    slots = gear.clean_slots(db.j(db.q1("SELECT spell_slots FROM characters WHERE id=?",
                                        (ch["id"],))["spell_slots"]))
    assert slots[2]["used"] == 1 and slots[1]["used"] == 0


def test_generic_resource_cost(client, monkeypatch):
    dm, player, code, ch = base_room(client)
    ptok = token_of(code, ch["id"])
    abilities.register({"id": "focus_prick", "name": "Focus Prick", "ability": "dex",
                        "range_ft": 30, "targeting": "point", "resolution": "auto",
                        "damage": "1d1", "damage_type": "piercing",
                        "cost": {"type": "resource", "id": "focus"}})
    db.x("UPDATE characters SET abilities=?, resources=?, hp=? WHERE id=?",
         (db.json_dumps(["focus_prick"]),
          db.json_dumps([{"id": "focus", "name": "Focus", "current": 1, "max": 2,
                          "reset": "manual"}]), 30, ch["id"]))
    px, py = player_cell(code, ch)
    fake_rolls(monkeypatch, {"1d1": [1]})
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "ability_cast", "token_id": ptok["id"],
                      "ability_id": "focus_prick", "x": px, "y": py})
        r = recv_until(ws, "ability_result")["payload"]
        assert r["consumed"] == {"type": "resource", "id": "focus"}
        ws.send_json({"type": "ability_cast", "token_id": ptok["id"],
                      "ability_id": "focus_prick", "x": px, "y": py})
        assert "exhausted" in recv_until(ws, "error")["payload"]["msg"]
    res = db.j(db.q1("SELECT resources FROM characters WHERE id=?", (ch["id"],))["resources"])
    assert next(r for r in res if r["id"] == "focus")["current"] == 0


# ---------- attack resolution ----------

def test_attack_resolution_against_existing_ac(client, monkeypatch):
    dm, player, code, ch = base_room(client)
    ptok = token_of(code, ch["id"])
    npc_tok = make_caster_npc(client, dm, code)
    # nat 20 crit lands — crit doubles the damage dice (expr 1d8 → 2d8)
    fake_rolls(monkeypatch, {"1d20": [20, 1], "2d8": [10]})
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "ability_cast", "token_id": npc_tok,
                      "ability_id": "training_beam", "target_id": ptok["id"]})
        r = recv_until(ws, "ability_result")["payload"]
    assert r["entries"][0]["attack"]["hit"] and r["entries"][0]["attack"]["crit"]
    assert db.q1("SELECT hp FROM characters WHERE id=?", (ch["id"],))["hp"] == 20

    with ws_connect(client, dm, code) as ws:                    # nat 1 fumbles
        ws.send_json({"type": "ability_cast", "token_id": npc_tok,
                      "ability_id": "training_beam", "target_id": ptok["id"]})
        r = recv_until(ws, "ability_result")["payload"]
    assert r["entries"][0]["attack"]["hit"] is False
    assert db.q1("SELECT hp FROM characters WHERE id=?", (ch["id"],))["hp"] == 20


# ---------- Part J: footprint-aware targeting ----------

def test_large_token_hit_on_non_origin_cell_only(client, monkeypatch):
    dm, player, code, ch = base_room(client)
    caster = make_caster_npc(client, dm, code, x=2, y=8)
    with ws_connect(client, dm, code) as ws:
        tid = add_npc(ws, label="BigOne", cx=14, cy=2)
        db.x("UPDATE tokens SET size='Large' WHERE id=?", (tid,))
    # Large at origin (14,2) occupies (14,2),(15,2),(14,3),(15,3); aim at its FOOT
    fake_rolls(monkeypatch, {"1d4": [2, 2]})
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "ability_cast", "token_id": caster,
                      "ability_id": "dart_prick", "x": 15, "y": 3})
        r = recv_until(ws, "ability_result")["payload"]
    assert any(e["label"] == "BigOne" for e in r["entries"])
    # the cell just OUTSIDE its footprint must NOT hit it
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "ability_cast", "token_id": caster,
                      "ability_id": "dart_prick", "x": 16, "y": 3})
        r = recv_until(ws, "ability_result")["payload"]
    assert r["entries"] == []


# ---------- LOS + range authority ----------

def test_los_required_rejects_wall_allows_open_door(client, monkeypatch):
    dm, player, code, ch = base_room(client)
    px, py = player_cell(code, ch)
    wall = px + 1
    set_grid(client, dm, code, lambda g: wall_column(g, wall))
    npc_tok = make_caster_npc(client, dm, code, x=wall + 3, y=py)
    fake_rolls(monkeypatch, {"1d20": [1], "3d6": [5]})
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "ability_cast", "token_id": npc_tok,
                      "ability_id": "training_bolt",
                      "target_id": token_of(code, ch["id"])["id"]})
        assert "Line of sight" in recv_until(ws, "error")["payload"]["msg"]
        # same geometry, door set open in the wall column → allowed
        g = state_of(client, dm, code)["grid"]
        g["doors"] = [{"x": wall, "y": py, "dir": "v", "closed": False, "locked": False}]
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "map_edit", "map": g})
        recv_until(ws, "map_changed")
        ws.send_json({"type": "ability_cast", "token_id": npc_tok,
                      "ability_id": "training_bolt",
                      "target_id": token_of(code, ch["id"])["id"]})
        recv_until(ws, "ability_result")


def test_range_authority(client, monkeypatch):
    dm, player, code, ch = base_room(client)
    px, py = player_cell(code, ch)
    npc_tok = make_caster_npc(client, dm, code, x=px + 13, y=py)   # 65 ft > 60 ft range
    fake_rolls(monkeypatch, {"1d20": [1], "3d6": [5]})
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "ability_cast", "token_id": npc_tok,
                      "ability_id": "training_bolt",
                      "target_id": token_of(code, ch["id"])["id"]})
        assert "out of range" in recv_until(ws, "error")["payload"]["msg"]
    assert db.q1("SELECT hp FROM characters WHERE id=?", (ch["id"],))["hp"] == 30


# ---------- Part I: security / authority ----------

def test_player_cannot_cast_through_others_malformed_and_dead_socket(client):
    dm, player, code, ch = base_room(client)
    other = reg(client, "pl2")
    ch2 = client.post("/api/characters", headers=H(other), json={
        "name": "Peer", "race": "Human", "char_class": "Fighter", "level": 5,
        "stats": {}, "hp": 30, "max_hp": 30}).json()["id"]
    client.post(f"/api/rooms/{code}/assign", json={"character_id": ch2}, headers=H(other))
    peer_tok = token_of(code, ch2)
    npc_tok = make_caster_npc(client, dm, code)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "ability_cast", "token_id": peer_tok["id"],
                      "ability_id": "focus_gaze"})                  # someone else's token
        assert "own character" in recv_until(ws, "error")["payload"]["msg"]
        ws.send_json({"type": "ability_cast", "token_id": npc_tok["id"],
                      "ability_id": "focus_gaze"})                  # DM's NPC
        assert "own character" in recv_until(ws, "error")["payload"]["msg"]
        ws.send_json({"type": "ability_cast", "token_id": token_of(code, ch["id"])["id"],
                      "ability_id": "not_registered"})              # unknown ability
        assert recv_until(ws, "error")["payload"]["msg"] == "Unknown ability"
        ws.send_json({"type": "ability_cast", "token_id": token_of(code, ch["id"])["id"],
                      "ability_id": "grapple_bind", "x": "spam", "y": "spam"})
        assert recv_until(ws, "error")                               # malformed geometry
        ws.send_json({"type": "ability_cast", "token_id": token_of(code, ch["id"])["id"],
                      "ability_id": "still_missing"})                # socket still alive
        assert recv_until(ws, "error")["payload"]["msg"] == "Unknown ability"


def test_granted_abilities_required_for_players(client):
    dm, player, code, ch = base_room(client)
    ptok = token_of(code, ch["id"])
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "ability_cast", "token_id": ptok["id"],
                      "ability_id": "focus_gaze"})                  # nothing granted
        assert recv_until(ws, "error")["payload"]["msg"] == \
            "This caster does not have that ability"


# ---------- Part J privacy ----------

def test_hidden_creature_affected_but_never_named_to_player(client, monkeypatch):
    dm, player, code, ch = base_room(client)
    px, py = player_cell(code, ch)
    assert px + 20 < 40
    npc_tok = make_caster_npc(client, dm, code, x=px + 20, y=py)  # far outside FOG_R=6
    db.x("UPDATE tokens SET npc=? WHERE id=?", (db.json_dumps({
        "name": "Skulker", "level": 5, "ac": 12, "hp": 30, "max_hp": 30,
        "stats": {"dex": 10}, "abilities": []}), npc_tok))
    ptok = token_of(code, ch["id"])
    # wide-range variant so range isn't the refusal reason; FOG_R=6 hides the Skulker
    abilities.register(dict(next(d for d in DEFS if d["id"] == "training_burst"),
                            range_ft=150))
    db.x("UPDATE characters SET abilities=?, spell_slots=?, stats=?, saves=? WHERE id=?",
         (db.json_dumps(["training_burst"]), db.json_dumps({1: {"max": 4, "used": 0}}),
          db.json_dumps({"int": 16}), "{}", ch["id"]))
    fake_rolls(monkeypatch, {"1d20": [1], "3d6": [6]})
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "ability_cast", "token_id": ptok["id"],
                      "ability_id": "training_burst", "x": px + 20, "y": py})
        r = recv_until(ws, "ability_result")["payload"]
    assert r["entries"] == [] and r["hidden_count"] == 1
    st = state_of(client, player, code)
    assert not any("Skulker" in str(m.get("text", "")) for m in st["messages"])
    sk = db.j(db.q1("SELECT npc FROM tokens WHERE id=?", (npc_tok,))["npc"])
    assert sk["hp"] == 24                                          # resolved server-side anyway
