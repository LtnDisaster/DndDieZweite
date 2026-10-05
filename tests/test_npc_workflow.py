"""Sprint 8 (P5): NPC sheet workflow end to end.

Server-side contract behind the sheet: stat-block fields round-trip through
add_token/update_npc/bestiary/spawn (incl. abilities/resources/notes),
long rest refills monster slots+resources, players never receive stat blocks,
and same-name spawns stay distinct tokens. The renderSheet crash guard is a
JS-side fix pinned textually (no DOM harness available for 30_room.js).
"""
import json

import pytest
from starlette.testclient import TestClient

from app import db
from app.main import app
from test_movement_fog import base_room, recv_until, state_of, ws_connect

NPC_BLOB = {"level": 3, "stats": {"str": 16, "dex": 12, "con": 14, "int": 6,
                                  "wis": 11, "cha": 8},
            "hp": 26, "max_hp": 26, "ac": 13, "speed": 30,
            "attacks": [{"name": "Bite", "to_hit": 5, "dmg": "1d6+3"}],
            "spell_slots": {1: {"max": 2, "used": 0}},
            "saves": {"str": 1},
            "abilities": [{"name": "Breath Weapon", "desc": "15ft cone, DC13, 2d6 fire"}],
            "resources": [{"name": "Breath Weapon", "max": 1, "cur": 1}],
            "notes": "Prefers to ambush at dusk."}


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def dm_tokens(client, dm, code):
    return {t["id"]: t for t in state_of(client, dm, code)["tokens"]}


def test_npc_blob_roundtrips_and_is_dm_only(client):
    dm, player, code, ch = base_room(client)
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "add_token", "label": "Goblin Boss", "x": 225, "y": 325,
                      "size": "Medium", "disposition": "hostile", **NPC_BLOB})
        tok_id = recv_until(ws, "token_add")["payload"]["id"]
    tok = dm_tokens(client, dm, code)[tok_id]
    blk = tok["npc"]
    assert blk["abilities"][0]["name"] == "Breath Weapon"
    assert blk["resources"] == [{"name": "Breath Weapon", "max": 1, "cur": 1}]
    assert blk["notes"] == "Prefers to ambush at dusk."
    # player (in LOS of a Medium token placed 2 cells away): token yes, block no
    ptoks = {t["id"]: t for t in state_of(client, player, code)["tokens"]}
    if tok_id in ptoks:                      # visibility is LOS-gated; either way:
        assert ptoks[tok_id]["npc"] is None
        assert "disposition" not in ptoks[tok_id]
    # update_npc consumes a used slot + a spent resource:
    with ws_connect(client, dm, code) as ws:
        upd = dict(NPC_BLOB)
        upd["spell_slots"] = {1: {"max": 2, "used": 2}}
        upd["resources"] = [{"name": "Breath Weapon", "max": 1, "cur": 0}]
        ws.send_json({"type": "update_npc", "token_id": tok_id,
                      "label": "Goblin Boss", "npc": upd})
        recv_until(ws, "snapshot")
    blk = dm_tokens(client, dm, code)[tok_id]["npc"]
    assert blk["spell_slots"]["1"]["used"] == 2
    assert blk["resources"][0]["cur"] == 0

    # long rest refills BOTH, without touching HP or the block otherwise:
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "long_rest"})
        recv_until(ws, "snapshot")
    tok = dm_tokens(client, dm, code)[tok_id]
    blk = tok["npc"]
    assert blk["spell_slots"]["1"]["used"] == 0
    assert blk["resources"][0]["cur"] == 1
    assert blk["hp"] == 26


def test_bestiary_same_name_spawn_and_blob_fields(client):
    dm, player, code, ch = base_room(client)
    payload = {"name": "Shadow", "level": 4, "stats": {"str": 8, "dex": 18, "con": 10,
               "int": 6, "wis": 11, "cha": 10}, "hp": 16, "max_hp": 16, "ac": 12,
               "speed": 40, "attacks": [], "spells": [], "spell_slots": {},
               "saves": {}, "defenses": {"immune": ["poison"]},
               "abilities": [{"name": "Strength Drain", "desc": "melee, fail = -1d4 str"}],
               "resources": [{"name": "Amorphous", "max": 1, "cur": 1}],
               "notes": "Hates bright light.", "size": "Medium", "disposition": "hostile"}
    r = client.post("/api/creatures", json=payload, headers={"cookie": dm["cookie"]})
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    assert r.json()["block"]["abilities"][0]["name"] == "Strength Drain"
    # duplicate name is fine and must be a NEW id
    r2 = client.post("/api/creatures", json=payload, headers={"cookie": dm["cookie"]})
    assert r2.status_code == 200 and r2.json()["id"] != cid

    enc = client.post("/api/encounters",
                      json={"name": "Duo", "entries": [{"creature_id": cid, "quantity": 2,
                                                        "name": "Shadow"}]},
                      headers={"cookie": dm["cookie"]})
    assert enc.status_code == 200, enc.text
    eid = enc.json()["id"]
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "spawn_encounter", "encounter_id": eid})
        ids = [recv_until(ws, "token_add")["payload"]["id"] for _ in range(2)]
    toks = dm_tokens(client, dm, code)
    assert len(set(ids)) == 2
    assert sorted(toks[i]["label"] for i in ids) == ["Shadow 1", "Shadow 2"]
    for i in ids:
        blk = toks[i]["npc"]
        assert blk["abilities"][0]["desc"].startswith("melee")
        assert blk["defenses"]["immune"] == ["poison"]


def test_rendersheet_crash_guard_pinned():
    src = open("app/static/js/30_room.js").read()
    # class_levels must never be dereferenced on a possibly-undefined character:
    assert "const clsTxt = ch && ch.class_levels" in src
    assert "(ch.class_levels" not in src.replace("ch && ch.class_levels", "")
