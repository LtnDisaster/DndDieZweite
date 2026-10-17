"""D111 (Sprint 40): the generic effect grammar + data-driven conditions.

Unit tests cover the closed-world validator, the canonical byte-stability the
generator/export rely on, the merged condition catalog (SRD hooks + the room's
conditions.csv) and clean_props' refuse-don't-coerce rule. The integration
half rides the REAL WebSocket paths: an op-list spell, a feat as castable
ability, item use/equip/on_hit/on_damaged triggers, the on_start damage clock
of smouldering, catalog-driven movement block/speed, resource preflight (a
refused action costs nothing), replay idempotency, the trigger ping-pong
bound, cross-room op refusal and the /state cond_catalog.
"""
import asyncio
import json
import time
import uuid

import pytest
from starlette.testclient import TestClient

from app import abilities, conditions as CND, db, effectops, gear, main
from app import content as C
from app.room import combat as CMB, health, movement, dice as RD
from tests.test_movement_fog import (H, join_room, reg, recv_until, set_grid,
                                     state_of, ws_connect)
from tests.test_d109_mastery import (add_dummy, always, attack, char_items,
                                     conds_of, drain, dummy_near, equip,
                                     grant_item, mk_def, token_of)
from tests.test_sprint23_combat import _to_player_turn

CELL_OIL = effectops.canon([{"op": "condition", "key": "slicked", "rounds": 3}])
CELL_THORN = effectops.canon([{"op": "temp_hp", "expr": "1d4+1"}])
CELL_SHAKEN = effectops.canon([{"op": "condition", "key": "shaken",
                                "rounds": 1, "until": "end"}])


@pytest.fixture()
def client():
    return TestClient(main.app)


def rid_of(code):
    return db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]


def _room(client, n_players=1):
    """DM + N players on a default open map; conditions.csv imported as-is."""
    users = [reg(client, f"d111dm-{uuid.uuid4().hex[:4]}")]
    for i in range(n_players):
        users.append(reg(client, f"d111p{i}-{uuid.uuid4().hex[:4]}"))
    code = client.post("/api/rooms", json={"name": "D111"},
                       headers=H(users[0])).json()["code"]
    for u in users[1:]:
        join_room(client, u, code)
    C.import_package({"conditions.csv": open("app/content_pack/conditions.csv",
                                             encoding="utf-8").read()},
                     rid_of(code), mode="apply", apply=True)
    return users, code


def _player_char(client, user, code, hp=20):
    r = client.post("/api/characters", headers=H(user), json={
        "name": f"C{user['name'][:5]}{uuid.uuid4().hex[:3]}", "race": "kin_fey",
        "char_class": "scout", "background": "bg_urchin", "level": 1,
        "hp": hp, "max_hp": hp,
        "stats": {k: 12 for k in ("str", "dex", "con", "int", "wis", "cha")}})
    ch = r.json()
    client.post(f"/api/rooms/{code}/assign", json={"character_id": ch["id"]},
                headers=H(user))
    return ch


def _set_abilities(ch_id, ids):
    db.x("UPDATE characters SET abilities=? WHERE id=?", (db.json_dumps(ids), ch_id))


def _give_slots(tok_id, lvl=1, n=4):
    b = db.j(db.q1("SELECT npc FROM tokens WHERE id=?", (tok_id,))["npc"], {}) or {}
    b["spell_slots"] = {str(lvl): {"max": n, "used": 0}}
    db.x("UPDATE tokens SET npc=? WHERE id=?", (db.json_dumps(b), tok_id))


def _hp(char_id):
    return db.q1("SELECT hp, temp_hp FROM characters WHERE id=?", (char_id,))


def _mkdef(client, dm, code, props, name="Trinket", kind="ring"):
    """Like test_d109's mk_def but with a free KIND (acc slots need ring/…)."""
    with ws_connect(client, dm, code) as dws:
        dws.send_json({"type": "item_def", "action": "create",
                       "defn": {"name": name, "kind": kind, "props": dict(props)}})
        recv_until(dws, "whisper")
    defs = state_of(client, dm, code)["item_defs"]
    return next(d["id"] for d in defs if d["name"] == name)


def _recv(ws, kind, expect=None, tries=40):
    """recv_until + payload predicate (the fog helper has no expect)."""
    seen = []
    for _ in range(tries):
        ev = ws.receive_json()
        seen.append(ev.get("kind"))
        if ev.get("kind") == kind and (expect is None
                                       or expect(ev.get("payload") or {})):
            return ev
        if ev.get("kind") == "error" and kind != "error":
            raise AssertionError(f"unexpected error: {ev}")
    raise AssertionError(f"no {kind} event in {seen}")


# ============================ validator (unit) =============================

def test_validator_is_a_closed_world():
    bad = [
        {"v": 1, "ops": [{"op": "meteor"}]},                     # unknown op
        {"v": 1, "ops": [{"op": "damage", "expr": "1d4", "target": "everyone"}]},
        {"v": 1, "ops": [{"op": "damage", "expr": "pie"}]},      # bad dice
        {"v": 1, "ops": [{"op": "save", "ability": "xx",
                          "dc": 10, "success": [], "failure": []}]},
        {"v": 1, "ops": [{"op": "save", "ability": "str", "dc": 99,
                          "success": [], "failure": []}]},       # dc range
        {"v": 1, "ops": [{"op": "forced_move", "kind": "fling", "cells": 1}]},
        {"v": 1, "ops": [{"op": "forced_move", "kind": "push", "cells": 11}]},
        {"v": 1, "ops": [{"op": "condition", "key": "x" * 40}]},
        {"v": 3, "ops": [{"op": "heal", "expr": "1d4"}]},        # version too new
        {"ops": [{"op": "heal", "expr": "1d4"}]},                # no version
        {"v": 1, "ops": []},                                     # empty root
        {"v": 1, "ops": [{"op": "heal", "expr": "1d4", "side": "x"}]},  # surplus
        {"v": 1, "ops": [{"op": "resource", "id": "ki", "mode": "grant"}]},
        {"v": 1, "ops": [{"op": "heal", "expr": "1d4"}] * 9},    # > MAX_OPS
        {"v": 1, "ops": [{"op": "save", "ability": "str", "dc": 10,
                          "success": [{"op": "save", "ability": "str", "dc": 10,
                                       "success": [{"op": "heal", "expr": "1d4"}],
                                       "failure": []}],
                          "failure": []}]},                     # nesting too deep
        "[{\"op\": \"heal\", \"expr\": NaN}]",                  # not strict JSON
    ]
    for b in bad:
        with pytest.raises(effectops.EffectError):
            effectops.validate(b)
    good = effectops.validate({"v": 1, "ops": [
        {"op": "save", "ability": "str", "dc": "auto",
         "success": [{"op": "condition_remove", "key": "shaken"}],
         "failure": [{"op": "condition", "key": "shaken", "rounds": 1,
                      "until": "end"}]}]})
    assert good[0]["op"] == "save" and good[0]["target"] == "target"  # defaults
    resources = effectops.validate([{"op": "resource", "id": "ki"},
                                    {"op": "resource", "id": "ki",
                                     "mode": "restore"}])
    assert resources[0]["mode"] == "cost"           # back-compatible default
    assert resources[1]["mode"] == "restore"


def test_canon_is_byte_stable_and_export_safe():
    a = effectops.canon([{"op": "heal", "expr": "1D4+1", "target": "self"}])
    b = effectops.canon({"v": 1, "ops": [{"expr": "1d4+1", "op": "heal",
                                         "target": "self"}]})
    assert a == b and a == json.dumps(json.loads(a), separators=(",", ":"),
                                      sort_keys=True)


def test_condition_definition_hook_grammar():
    ops = effectops.validate({"on_start": [{"op": "damage", "expr": "1d4",
                                           "type": "fire", "target": "self"}]})
    assert list(ops) == ["on_start"]
    with pytest.raises(effectops.EffectError):
        effectops.validate({"on_munch": [{"op": "heal", "expr": "1d4"}]})


def test_builtin_hooks_are_srd_wired():
    CND.invalidate(None)
    assert CND.hook_bool([{"k": "poisoned", "rounds": 0, "until": ""}], 0,
                         "my_attacks_dis")
    assert CND.hook_bool([{"k": "blinded", "rounds": 0, "until": ""}], 0,
                         "attacks_against_me_adv")
    assert CND.auto_fails_save([{"k": "paralyzed", "rounds": 0, "until": ""}],
                               0, "dex")
    assert not CND.auto_fails_save([{"k": "paralyzed", "rounds": 0, "until": ""}],
                                   0, "wis")
    assert CND.hook_bool([{"k": "grappled", "rounds": 0, "until": ""}], 0,
                         "blocks_movement")
    assert CND.speed_delta([{"k": "slowed", "rounds": 0, "until": ""}], 0) == -10
    assert CND.expired_keys([{"k": "prone", "rounds": 1, "until": ""}],
                            [{"k": "prone", "rounds": 1, "until": "start"}]) == []
    assert CND.expired_keys([{"k": "prone", "rounds": 1, "until": ""}], []) == ["prone"]


def test_duration_can_seed_condition_rounds_without_a_second_clock():
    assert effectops.duration_rounds("Concentration, up to 1 minute") == 10
    assert effectops.duration_rounds("1 hour") == 60
    assert effectops.duration_rounds("Instantaneous") == 0
    assert effectops.duration_rounds("Permanent") == 0
    assert effectops.duration_rounds("not a duration") == 0

    resolved = effectops.validate(
        [{"op": "condition", "key": "slicked", "rounds": "duration", "until": "end"}],
        duration_rounds=10)
    assert resolved[0]["rounds"] == 10 and resolved[0]["until"] == "end"

    omitted = effectops.validate([{"op": "condition", "key": "slicked"}],
                                  duration_rounds=3)
    assert omitted[0]["rounds"] == 3

    carried = effectops.canon([{"op": "condition", "key": "slicked"}],
                              preserve_duration=True)
    assert json.loads(carried)["ops"][0]["rounds"] == "duration"
    assert effectops.validate(carried, duration_rounds=10)[0]["rounds"] == 10


def test_spell_duration_feeds_its_effect_condition():
    row = {
        "id": "test_slick", "name": "Test Slick", "level": 1, "school": "transmutation",
        "casting_ability": "int", "targeting": "single", "range_ft": 30,
        "casting_time": "1 action", "duration": "Concentration, up to 1 minute",
        "resolution": "auto", "class_list": "testcaster",
        "effects": '[{"op":"condition","key":"slicked","until":"end"}]',
    }
    defn = C.map_to_ability(row)
    assert defn is not None
    assert defn["ops"][0]["rounds"] == 10


def test_item_duration_seeds_condition_rounds(client):
    users, code = _room(client)
    dm, player = users[0], users[1]
    ch = _player_char(client, player, code)
    tok = token_of(client, player, code, ch)
    did = _mkdef(client, dm, code, {
        "effects": '[{"op":"condition","key":"slicked","until":"end"}]',
        "duration": "1 minute",
        "trigger": "use",
    }, name="Long Oil", kind="potion")
    grant_item(client, dm, code, ch["id"], did)
    it = next(i for i in char_items(client, player, code) if i["def_id"] == did)
    assert it["props"]["duration"] == "1 minute"
    assert json.loads(it["props"]["effects"])["ops"][0]["rounds"] == "duration"
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "use_item", "token_id": tok, "item_id": it["id"],
                      "op_id": "u" + uuid.uuid4().hex[:8]})
        _recv(ws, "whisper", expect=lambda p: "slicked" in str(p).lower())
    entry = next(c for c in conds_of(tok) if c["k"] == "slicked")
    assert entry["rounds"] == 10 and entry["until"] == "end"


def test_conditions_csv_merges_and_invalidates(client):
    users, code = _room(client)
    rid = rid_of(code)
    assert CND.definition("smouldering", rid)["glyph"] == "🔥"
    assert CND.effects_for("smouldering", rid, "on_start")   # parsed op list
    assert CND.definition("shaken", rid).get("my_attacks_dis") is True
    assert CND.speed_delta([{"k": "slicked", "rounds": 1, "until": ""}], rid) == -10
    # a re-import that edits the row must be seen (cache invalidation)
    C.import_package(
        {"conditions.csv": (
            "id,name,glyph,color,group,blocks_movement,speed_delta,"
            "my_attacks_dis,my_checks_dis,my_saves_dis,attacks_against_me_adv,"
            "attacks_against_me_dis,auto_fail_saves,effects,manual\n"
            "shaken,Rattled,😰,#f39c12,condition,0,0,1,1,0,0,0,,,\n")},
        rid, mode="replace", apply=True)
    assert CND.definition("shaken", rid)["name"] == "Rattled"


def test_clean_props_refuses_corrupt_effects_never_coerces():
    assert gear.clean_props({"effects": '{"v":1,"ops":[{"op":"meteor"}]}'}
                            ) == {}
    assert "effects" in gear.clean_props({"effects": CELL_OIL,
                                          "trigger": "on_hit"})
    assert "trigger" not in gear.clean_props({"effects": CELL_OIL,
                                              "trigger": "on_explode"})


def test_missing_token_cond_update_does_not_recurse():
    # D111 bugfix: this branch recursed forever on a deleted token row.
    asyncio.run(CMB._cond_update(1, 999999, []))


# ========================== integration (WebSocket) ========================

def _fake_rolls(monkeypatch, value=7):
    def fake(expr, adv=None):
        return {"expr": expr, "rolls": [value], "kept": value, "mod": 0,
                "total": value, "adv": adv}
    monkeypatch.setattr(RD, "do_roll", fake)


def test_spell_op_list_damage_and_push(client, monkeypatch):
    users, code = _room(client)
    dm = users[0]
    C.import_package({"spells.csv": open("app/content_pack/spells.csv",
                                         encoding="utf-8").read()},
                     rid_of(code), mode="apply", apply=True)
    caster = add_dummy(client, dm, code, 250, 250, "Caster")
    target = add_dummy(client, dm, code, 350, 250, "Target")
    _give_slots(caster)
    _fake_rolls(monkeypatch, 7)                    # damage AND the save roll = 7
    hp0 = (db.j(db.q1("SELECT npc FROM tokens WHERE id=?", (target,))["npc"], {})
           or {}).get("hp")
    with ws_connect(client, dm, code) as dws:
        dws.send_json({"type": "ability_cast", "token_id": caster,
                       "ability_id": "thunder_lure", "target_id": target})
        res = recv_until(dws, "ability_result")["payload"]
    assert res["entries"][0]["ops"], res
    hp1 = (db.j(db.q1("SELECT npc FROM tokens WHERE id=?", (target,))["npc"], {})
           or {}).get("hp")
    assert hp1 < hp0                               # 2d6 thunder applied
    row = db.q1("SELECT x FROM tokens WHERE id=?", (target,))
    assert int(row["x"]) // 50 == 7 + 2            # failed STR save -> pushed 2 cells


def test_spell_op_list_saved_target_is_not_pushed(client, monkeypatch):
    users, code = _room(client)
    dm = users[0]
    C.import_package({"spells.csv": open("app/content_pack/spells.csv",
                                         encoding="utf-8").read()},
                     rid_of(code), mode="apply", apply=True)
    caster = add_dummy(client, dm, code, 250, 250, "Caster")
    target = add_dummy(client, dm, code, 350, 250, "Target")
    _give_slots(caster)
    seq = iter([({"kept": 20, "total": 20}),                  # damage roll
                ({"kept": 20, "total": 20})])                 # save roll: success

    def fake(expr, adv=None):
        r = {"expr": expr, "rolls": [20], "mod": 0, "adv": adv}
        r.update(next(seq))
        return r
    monkeypatch.setattr(RD, "do_roll", fake)
    with ws_connect(client, dm, code) as dws:
        dws.send_json({"type": "ability_cast", "token_id": caster,
                       "ability_id": "thunder_lure", "target_id": target})
        recv_until(dws, "ability_result")
    assert int(db.q1("SELECT x FROM tokens WHERE id=?", (target,))["x"]) // 50 == 7


def test_feat_effects_register_and_respect_entitlement(client):
    users, code = _room(client)
    dm, player = users[0], users[1]
    C.import_package({"feats.csv": open("app/content_pack/feats.csv",
                                        encoding="utf-8").read()},
                     rid_of(code), mode="apply", apply=True)
    ch = _player_char(client, player, code)
    tok = token_of(client, player, code, ch)
    _set_abilities(ch["id"], [])                  # NOT taken yet
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "ability_cast", "token_id": tok,
                      "ability_id": "feat_martyr", "op_id": "f" + uuid.uuid4().hex[:8]})
        err = recv_until(ws, "error")["payload"]["msg"]
    assert "does not have that ability" in err
    _set_abilities(ch["id"], ["feat_martyr"])     # entitlement = feat was taken
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "ability_cast", "token_id": tok,
                      "ability_id": "feat_martyr", "op_id": "f" + uuid.uuid4().hex[:8]})
        res = recv_until(ws, "ability_result")["payload"]
    assert res["entries"][0]["applied"]
    assert _hp(ch["id"])["temp_hp"] >= 2          # 2d4+2 temp HP


def test_replayed_cast_applies_once(client):
    users, code = _room(client)
    player = users[1]
    C.import_package({"feats.csv": open("app/content_pack/feats.csv",
                                        encoding="utf-8").read()},
                     rid_of(code), mode="apply", apply=True)
    ch = _player_char(client, player, code)
    tok = token_of(client, player, code, ch)
    _set_abilities(ch["id"], ["feat_martyr"])
    op = "r" + uuid.uuid4().hex[:8]
    with ws_connect(client, player, code) as ws:
        for _ in range(2):
            ws.send_json({"type": "ability_cast", "token_id": tok,
                          "ability_id": "feat_martyr", "op_id": op})
    temp = _hp(ch["id"])["temp_hp"]
    assert 2 <= temp <= 10                        # ONE grant (2d4+2), never two
    # and a replay of a different cast still guards itself
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "ability_cast", "token_id": tok,
                      "ability_id": "feat_martyr", "op_id": op})
        drain(ws)
    assert _hp(ch["id"])["temp_hp"] == temp


def test_item_use_fires_effects(client):
    users, code = _room(client)
    dm, player = users[0], users[1]
    ch = _player_char(client, player, code)
    tok = token_of(client, player, code, ch)
    did = _mkdef(client, dm, code, {"effects": CELL_OIL, "trigger": "use"},
                 name="Slick Oil", kind="potion")
    grant_item(client, dm, code, ch["id"], did)
    it = next(i for i in char_items(client, player, code) if i["def_id"] == did)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "use_item", "token_id": tok, "item_id": it["id"],
                      "op_id": "u" + uuid.uuid4().hex[:8]})
        _recv(ws, "whisper", expect=lambda p: "slicked" in str(p).lower())
    assert any(c["k"] == "slicked" for c in conds_of(tok))


def test_equip_trigger_fires_once_per_op(client):
    # Deterministic by construction: no unbounded whisper waits — the chat
    # sentinel proves the equip handler FINISHED, the DB proves what it did.
    users, code = _room(client)
    dm, player = users[0], users[1]
    ch = _player_char(client, player, code)
    token_of(client, player, code, ch)
    did = _mkdef(client, dm, code, {"effects": CELL_THORN, "trigger": "equip"},
                 name="Thorn Band")
    grant_item(client, dm, code, ch["id"], did)
    it = next(i for i in char_items(client, player, code) if i["def_id"] == did)
    room_id = rid_of(code)
    op1 = "e" + uuid.uuid4().hex[:10]
    op2 = "e" + uuid.uuid4().hex[:10]

    def eq(op, ws):
        ws.send_json({"type": "inv_equip", "char_id": ch["id"], "slot": "acc1",
                      "item_id": it["id"], "op_id": op})
        drain(ws)                                   # handler finished, no error

    with ws_connect(client, player, code) as ws:
        eq(op1, ws)                                 # first equip: fires
        for _ in range(100):                        # effect landed (max 10 s)
            if _hp(ch["id"])["temp_hp"] >= 1:
                break
            time.sleep(0.1)
        eq(op1, ws)                                 # same op: equip replayed
        eq(op2, ws)                                 # fresh op: fires again
    assert _hp(ch["id"])["temp_hp"] >= 1
    claims = db.q("SELECT op_id FROM inv_ops WHERE kind='effect_trigger' "
                  "AND room_id=?", (room_id,))
    assert len(claims) == 2                         # one firing per fresh op


def test_on_hit_condition_marker(client, monkeypatch):
    always(client, monkeypatch, 20)               # every d20 = 20: the hit is forced
    users, code = _room(client)
    dm, player = users[0], users[1]
    ch = _player_char(client, player, code)
    tok = token_of(client, player, code, ch)
    did = mk_def(client, dm, code, {"damage_dice": "1d8", "effects": CELL_SHAKEN,
                                    "trigger": "on_hit"}, name="Quake Test")
    grant_item(client, dm, code, ch["id"], did)
    it = next(i for i in char_items(client, player, code) if i["def_id"] == did)
    equip(client, player, code, ch["id"], it["id"])
    dummy = dummy_near(client, dm, code, tok)
    _to_player_turn(client, dm, code, tok)
    with ws_connect(client, player, code) as ws:
        attack(ws, it["id"], tok, target=dummy, op="a" + uuid.uuid4().hex[:10])
        evs = drain(ws)
    from tests.test_d109_mastery import dice_bodies
    assert any("HIT" in b for b in dice_bodies(evs))
    shaken = [c for c in conds_of(dummy) if c["k"] == "shaken"]
    assert shaken and shaken[0]["until"] == "end"


def test_on_damaged_worn_item(client):
    users, code = _room(client)
    dm, player = users[0], users[1]
    ch = _player_char(client, player, code)
    tok = token_of(client, player, code, ch)
    did = _mkdef(client, dm, code, {"effects": CELL_THORN, "trigger": "on_damaged"},
                 name="Ember Test")
    grant_item(client, dm, code, ch["id"], did)
    it = next(i for i in char_items(client, player, code) if i["def_id"] == did)
    equip(client, player, code, ch["id"], it["id"], slot="acc1")
    tok_row = db.q1("SELECT * FROM tokens WHERE id=?", (tok,))
    room_id = rid_of(code)
    asyncio.run(health.change_hp(room_id, tok_row, -6))
    assert _hp(ch["id"])["hp"] == 14              # damage went through
    assert _hp(ch["id"])["temp_hp"] >= 1          # ... and the ring answered


def test_smouldering_burns_at_turn_start(client):
    users, code = _room(client)
    dm, player = users[0], users[1]
    ch = _player_char(client, player, code)
    tok = token_of(client, player, code, ch)
    with ws_connect(client, dm, code) as dws:
        dws.send_json({"type": "cond_add", "token_id": tok, "key": "smouldering",
                       "rounds": 3})
        recv_until(dws, "cond")
    hp0 = _hp(ch["id"])["hp"]
    _to_player_turn(client, dm, code, tok)        # the player's turn begins
    assert _hp(ch["id"])["hp"] < hp0              # on_start: 1d4 fire, self
    assert any(c["k"] == "smouldering" for c in conds_of(tok))


def test_grappled_blocks_and_slicked_slows_from_catalog(client):
    users, code = _room(client)
    dm, player = users[0], users[1]
    ch = _player_char(client, player, code)
    tok = token_of(client, player, code, ch)
    with ws_connect(client, dm, code) as dws:
        dws.send_json({"type": "cond_add", "token_id": tok, "key": "grappled"})
        recv_until(dws, "cond")
        dws.send_json({"type": "cond_add", "token_id": tok, "key": "slicked",
                       "rounds": 2})
        recv_until(dws, "cond")
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "move", "token_id": tok, "tx": 8, "ty": 5})
        err = recv_until(ws, "error")["payload"]["msg"]
    assert "grappled" in err.lower()              # blocks_movement via catalog
    tok_row = db.q1("SELECT * FROM tokens WHERE id=?", (tok,))
    assert movement._speeds(tok_row)["walk"] == 20   # 30 - slicked(10)


def test_resource_preflight_costs_nothing(client):
    users, code = _room(client)
    dm, player = users[0], users[1]
    cell = effectops.canon([{"op": "heal", "expr": "1d4+5"},
                            {"op": "resource", "id": "ki"}])
    csv = ("id,name,effects\n"
           f"ki_heal,\"Ki Heal\",\"{cell.replace(chr(34), chr(34) * 2)}\"\n")
    C.import_package({"spells.csv": csv}, rid_of(code), mode="apply", apply=True)
    ch = _player_char(client, player, code, hp=10)
    tok = token_of(client, player, code, ch)
    _set_abilities(ch["id"], ["ki_heal"])
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "ability_cast", "token_id": tok,
                      "ability_id": "ki_heal", "target_id": tok,
                      "op_id": "k" + uuid.uuid4().hex[:8]})
        err = recv_until(ws, "error")["payload"]["msg"]
    assert "ki" in err and "not available" in err
    assert _hp(ch["id"])["hp"] == 10              # the heal did NOT sneak through


def test_resource_restore_uses_the_existing_ledger(client):
    users, code = _room(client)
    player = users[1]
    cell = effectops.canon([{"op": "resource", "id": "ki", "mode": "restore"}])
    csv = ("id,name,effects\n"
           f"ki_restore,\"Ki Restore\",\"{cell.replace(chr(34), chr(34) * 2)}\"\n")
    C.import_package({"spells.csv": csv}, rid_of(code), mode="apply", apply=True)
    ch = _player_char(client, player, code)
    tok = token_of(client, player, code, ch)
    db.x("UPDATE characters SET resources=? WHERE id=?",
         (db.json_dumps([{"id": "ki", "name": "Ki", "current": 0, "max": 2,
                          "reset": "short"}]), ch["id"]))
    _set_abilities(ch["id"], ["ki_restore"])
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "ability_cast", "token_id": tok,
                      "ability_id": "ki_restore", "target_id": tok,
                      "op_id": "r" + uuid.uuid4().hex[:8]})
        res = recv_until(ws, "ability_result")["payload"]
    assert res["entries"][0]["applied"]
    resources = gear.clean_resources(db.j(
        db.q1("SELECT resources FROM characters WHERE id=?", (ch["id"],))["resources"], []))
    assert next(r for r in resources if r["id"] == "ki")["current"] == 1


def test_trigger_ping_pong_is_bounded(client):
    users, code = _room(client)
    dm, player = users[0], users[1]
    C.import_package({"conditions.csv": (
        "id,name,group,effects\n"
        "echo_a,Echo,condition,\"{\"\"on_expire\"\":["
        "{\"\"op\"\":\"\"condition\"\",\"\"key\"\":\"\"echo_b\"\",\"\"rounds\"\":1,"
        "\"\"until\"\":\"\"start\"\"}]}\"\n"
        "echo_b,Echo B,condition,\"{\"\"on_expire\"\":["
        "{\"\"op\"\":\"\"condition\"\",\"\"key\"\":\"\"echo_a\"\",\"\"rounds\"\":1,"
        "\"\"until\"\":\"\"start\"\"}]}\"\n")}, rid_of(code), mode="apply", apply=True)
    ch = _player_char(client, player, code)
    tok = token_of(client, player, code, ch)
    with ws_connect(client, dm, code) as dws:
        dws.send_json({"type": "cond_add", "token_id": tok, "key": "echo_a",
                       "rounds": 1, "until": "start"})
        recv_until(dws, "cond")
        dws.send_json({"type": "init_start"})
        recv_until(dws, "initiative")
        # every NEXT must terminate and hold AT MOST ONE of the pair live
        for _ in range(8):
            dws.send_json({"type": "init_next"})
            recv_until(dws, "initiative")
            live = [c["k"] for c in conds_of(tok) if c["k"].startswith("echo_")]
            assert len(live) <= 1, live           # never both at once: no ping-pong


def test_cross_room_target_is_never_touched(client):
    users, code = _room(client)
    dm = users[0]
    other = client.post("/api/rooms", json={"name": "D111B"},
                        headers=H(dm)).json()["code"]
    rid, rid_b = rid_of(code), rid_of(other)
    a = add_dummy(client, dm, code, 250, 250, "Here")
    b = add_dummy(client, dm, other, 250, 250, "Elsewhere")
    hp_b = (db.j(db.q1("SELECT npc FROM tokens WHERE id=?", (b,))["npc"], {})
            or {}).get("hp")
    ops = effectops.validate([{"op": "condition", "key": "shaken"}])
    ctx = effectops.make_ctx(rid, caster=db.q1("SELECT * FROM tokens WHERE id=?", (a,)),
                             target=db.q1("SELECT * FROM tokens WHERE id=?", (b,)))
    asyncio.run(effectops.run_ops(ops, ctx))
    assert conds_of(b) == []                      # the other room's token: skipped
    assert ctx["changed"] is False


def test_state_ships_cond_catalog(client):
    users, code = _room(client)
    st = state_of(client, users[1], code)
    cat = st["cond_catalog"]
    assert cat["smouldering"]["n"] == "Smouldering"
    assert cat["poisoned"]["c"] == "#27ae60"      # built-ins present as well
