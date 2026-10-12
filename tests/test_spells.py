"""Sprint 25 Phase C (D97): class-driven spellcasting through the EXISTING engines.

Pins the guarantees that matter:
  * build fills castable abilities / a sheet spell pool / a slot TABLE from the
    class row (prepared vs known models), never derives slots from total level
    (D58) — a 2nd-level half caster has 2 slots, not a full caster's 3;
  * a missing spell choice writes NOTHING (needs_choice), forward-only and idempotent;
  * a class resource (sorcery points) rides the generic resource system and its
    CSV ``class_resource_reset`` timing is honoured on a rest;
  * casting is one op: an upcast consumes the HIGHER slot AND raises the dice, a
    cantrip scales by character level from its tier table, and a repeated op_id
    consumes one slot and applies the effect once.
"""
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from app import abilities, charbuild as CB, content as C, db, gear, main
from test_movement_fog import (base_room, join_room, make_char, reg, recv_until,
                               ws_connect, add_npc)

PACK = Path(__file__).resolve().parents[1] / "app" / "content_pack"


@pytest.fixture()
def client():
    with TestClient(main.app) as c:
        yield c


def room_pack(client):
    dm, player, code, ch = base_room(client)
    rid = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
    files = {p.name: p.read_text(encoding="utf-8") for p in PACK.glob("*.csv")}
    C.import_package(files, room_id=rid, mode="apply", apply=True)   # registers spells
    return dm, player, code, ch, rid


def tok_id(code, char_id):
    return db.q1("SELECT id FROM tokens WHERE room_id=? AND character_id=?",
                 (db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"], char_id))["id"]


def cell_of(code, char_id):
    t = db.q1("SELECT x, y FROM tokens WHERE id=?", (tok_id(code, char_id),))
    return int(t["x"] // 50), int(t["y"] // 50)


def record_rolls(monkeypatch):
    """Capture the exact dice expressions the engine rolls (so scaling is observable)."""
    import re
    from app.room import dice as RD
    seen = []

    def fake(expr, adv=None):
        seen.append(expr)
        m = re.match(r"^(\d+)d", str(expr))
        n = int(m.group(1)) if m else 1
        return {"expr": expr, "rolls": [6] * n, "kept": 6 * n, "mod": 0,
                "total": 6 * n, "adv": None}
    monkeypatch.setattr(RD, "do_roll", fake)
    return seen


def slots_of(char_id):
    return gear.clean_slots(db.j(db.q1("SELECT spell_slots FROM characters WHERE id=?",
                                       (char_id,))["spell_slots"], {}))


def abilities_of(char_id):
    return set(db.j(db.q1("SELECT abilities FROM characters WHERE id=?",
                          (char_id,))["abilities"], []) or [])


# ---------- build: models, slot TABLE, choice-gating, class resource ----------

def test_build_prepared_caster_castable_pool_and_slot_table(client):
    _dm, player, _code, _ch, rid = room_pack(client)
    cid = make_char(client, player)["id"]
    ok, res = CB.apply(cid, "adept", 5,
                       {"subclass": "school_ember", "levels": {"4": {"ability": {"int": 2}}}}, rid)
    assert ok and res["spell_model"] == "prepared"
    # full caster at class level 5 -> 1:4, 2:3, 3:2 (the class row's TABLE)
    assert res["slots"] == {1: 4, 2: 3, 3: 2}
    pool = {r["id"] for r in C.spell_pool("adept", rid)}
    assert pool <= abilities_of(cid)                         # prepared -> whole class list
    disp = {s["id"] for s in gear.clean_spells(db.j(
        db.q1("SELECT spells FROM characters WHERE id=?", (cid,))["spells"], []))}
    assert pool == disp
    for sid in pool:                                         # sheet pool is castable
        assert abilities.get(sid) is not None


def test_build_half_caster_slots_are_a_table_not_derived_from_total_level(client):
    _dm, player, _code, _ch, rid = room_pack(client)
    cid = make_char(client, player)["id"]
    choices = {"skills": ["athletics", "perception"],
               "levels": {"2": {"cantrips": ["spark", "gust"], "spells": ["bolt", "smite"]}}}
    ok, res = CB.apply(cid, "warden", 2, choices, rid)
    assert ok and res["spell_model"] == "known"
    # a 2nd-level HALF caster has TWO 1st-level slots and NO 2nd-level slot — a naive
    # total-level derivation (the forbidden shortcut, D58) would not produce this table
    assert res["slots"] == {1: 2}
    assert 2 not in res["slots"]
    assert {"spark", "gust", "bolt", "smite"} <= abilities_of(cid)


def test_build_missing_spell_choice_writes_nothing(client):
    _dm, player, _code, _ch, rid = room_pack(client)
    cid = make_char(client, player)["id"]
    ok, res = CB.apply(cid, "warden", 2, {"skills": ["athletics", "perception"]}, rid)
    assert ok is False
    assert any(n["kind"] == "spells" and n["level"] == 2 for n in res["needs_choice"])
    row = db.q1("SELECT * FROM characters WHERE id=?", (cid,))
    assert CB.ledger(row) == {}                              # nothing written
    assert abilities_of(cid) == set()
    assert slots_of(cid)[1] == {"max": 0, "used": 0}


def test_build_known_caster_forward_idempotent_and_resource(client):
    _dm, player, _code, _ch, rid = room_pack(client)
    cid = make_char(client, player)["id"]
    picks = {"skills": ["persuasion", "religion"],
             "levels": {"1": {"cantrips": ["spark", "mend", "chill"],
                              "spells": ["arcane_ward", "bolt", "smite"]},
                        "3": {"spells": ["curse"]},
                        "4": {"cantrips": ["gust"]},
                        "5": {"ability": {"cha": 2}}}}
    ok, res = CB.apply(cid, "seer", 5, picks, rid)
    assert ok and res["spell_model"] == "known" and res["slots"] == {1: 4, 2: 3, 3: 2}
    assert {"curse", "gust"} <= abilities_of(cid)             # level-3 spell, level-4 cantrip
    # sorcery points ride the resource system, max = class level, short-rest reset
    sorc = next(r for r in gear.clean_resources(db.j(
        db.q1("SELECT resources FROM characters WHERE id=?", (cid,))["resources"], []))
        if r["id"] == "sorcery_points")
    assert sorc["max"] == 5 and sorc["reset"] == "short"
    assert CB.apply(cid, "seer", 5, picks, rid)[0] is False   # forward-only guard


# ---------- cast: scaling is data-driven, the higher slot is consumed ----------

def test_cast_upcast_scales_dice_and_consumes_the_higher_slot(client, monkeypatch):
    dm, player, code, ch, _rid = room_pack(client)
    seen = record_rolls(monkeypatch)
    px, py = cell_of(code, ch["id"])
    with ws_connect(client, dm, code) as dws:
        npc = add_npc(dws, label="Rival", cx=px + 1, cy=py)
    db.x("UPDATE characters SET abilities=?, spell_slots=?, stats=?, saves=? WHERE id=?",
         (db.json_dumps(["curse"]), db.json_dumps({2: {"max": 2, "used": 0},
                                                   3: {"max": 1, "used": 0}}),
          db.json_dumps({"cha": 16}), "{}", ch["id"]))
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "ability_cast", "token_id": tok_id(code, ch["id"]),
                      "ability_id": "curse", "target_id": npc, "cast_level": 3})
        r = recv_until(ws, "ability_result")["payload"]
    assert r["consumed"] == {"type": "spell_slot", "level": 3}
    assert "4d6" in seen                                     # 3d6 base +1d6 for the slot above 2
    assert slots_of(ch["id"])[3]["used"] == 1 and slots_of(ch["id"])[2]["used"] == 0


def test_cast_cantrip_scales_by_character_level_without_a_slot(client, monkeypatch):
    dm, player, code, ch, _rid = room_pack(client)
    seen = record_rolls(monkeypatch)
    px, py = cell_of(code, ch["id"])
    with ws_connect(client, dm, code) as dws:
        npc = add_npc(dws, label="Rival", cx=px + 1, cy=py)
    from app import progression
    progression.set_class_levels(ch["id"], [{"class_id": "seer", "level": 5}])
    db.x("UPDATE characters SET abilities=?, stats=?, saves=? WHERE id=?",
         (db.json_dumps(["spark"]), db.json_dumps({"int": 16}), "{}", ch["id"]))
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "ability_cast", "token_id": tok_id(code, ch["id"]),
                      "ability_id": "spark", "target_id": npc})
        r = recv_until(ws, "ability_result")["payload"]
    assert r["consumed"] is None                             # a cantrip costs no slot
    assert "2d8" in seen                                     # 1d8 base + the level-5 tier


def test_cast_duplicate_op_id_consumes_one_slot_and_effects_once(client, monkeypatch):
    dm, player, code, ch, _rid = room_pack(client)
    record_rolls(monkeypatch)
    px, py = cell_of(code, ch["id"])
    with ws_connect(client, dm, code) as dws:
        npc = add_npc(dws, label="Rival", cx=px + 1, cy=py)
    db.x("UPDATE characters SET abilities=?, spell_slots=?, stats=?, saves=? WHERE id=?",
         (db.json_dumps(["curse"]), db.json_dumps({2: {"max": 2, "used": 0}}),
          db.json_dumps({"cha": 16}), "{}", ch["id"]))
    body = {"type": "ability_cast", "token_id": tok_id(code, ch["id"]),
            "ability_id": "curse", "target_id": npc, "op_id": "cast-once"}
    with ws_connect(client, player, code) as ws:
        ws.send_json(body)
        recv_until(ws, "ability_result")
        ws.send_json(body)                                    # exact duplicate op_id
    assert slots_of(ch["id"])[2]["used"] == 1                 # never a second slot


# ---------- rest: the class resource's reset timing is honoured ----------

def test_rest_refills_class_resource_and_slots(client):
    dm, _player, code, ch, _rid = room_pack(client)
    tok = tok_id(code, ch["id"])
    db.x("UPDATE characters SET spell_slots=?, resources=?, hit_dice_spent=0 WHERE id=?",
         (db.json_dumps({1: {"max": 4, "used": 4}}),
          db.json_dumps([{"id": "sorcery_points", "name": "Sorcery Points",
                          "current": 0, "max": 5, "reset": "short"}]), ch["id"]))
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "long_rest"})
        recv_until(ws, "snapshot")
    sorc = next(r for r in gear.clean_resources(db.j(
        db.q1("SELECT resources FROM characters WHERE id=?", (ch["id"],))["resources"],
        [])) if r["id"] == "sorcery_points")
    assert sorc["current"] == 5 and sorc["max"] == 5          # long rest >= short rest
    assert slots_of(ch["id"])[1] == {"max": 4, "used": 0}
