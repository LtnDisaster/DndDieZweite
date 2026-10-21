"""D163-2: monsters stay data — creatures.csv reaches the existing engine.

The NPC block always COULD carry defenses, swim/climb speeds and resources;
creatures.csv just had no columns for them (the D162 audit called this out:
resistances were only reachable through the DM's NPC editor). These tests pin
the full chain: CSV row -> project_creature -> clean_npc (survives the
add_token/update_npc rebuild) -> real combat adjudication (health.change_hp
halves a resisted hit, nullifies an immune one) -> condition immunity blocks
a cast at the ONE fixed-condition choke point. A column that merely displayed
would fail every behavioural test below.
"""
import asyncio
import json

import pytest
from starlette.testclient import TestClient

from app import abilities, content as C, db, gear, main, npc
from app.room import health
from tests.test_movement_fog import base_room

ROW = (
    "id,name,size,hp,ac,str,dex,resistances,immunities,vulnerabilities,"
    "condition_immunities,swim_ft,climb_ft,recharge,attacks\n"
    "d163_grell,Grell,Tiny,22,13,8,22,psychic,poison,bludgeoning,"
    "charmed;frightened,10,20,Breath 1,"
    "\"Tentacle +4 to hit, reach 5 ft, one creature: 1d4+6 plus grab\"\n"
)


@pytest.fixture()
def client():
    return TestClient(main.app)


def _row():
    rows, hdr = C.parse(ROW)
    clean, errs, _warn = C.validate("creature", rows, hdr, "creatures.csv")
    assert not errs, errs
    return clean[0]


def rid_of(code):
    return db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]


def test_new_columns_project_into_the_existing_npc_block():
    block = npc.project_creature(_row())
    assert block["defenses"] == {"resist": ["psychic"], "immune": ["poison"],
                                 "vulnerable": ["bludgeoning"]}
    assert block["cond_immune"] == ["charmed", "frightened"]
    assert block["swim"] == 10 and block["climb"] == 20
    assert block["resources"] == [{"name": "Breath", "max": 1, "cur": 1}]
    assert block["attacks"][0]["to_hit"] == 4          # multiattack line parses
    # the block must survive the add_token/update_npc clean_npc rebuild intact
    again = npc.clean_npc(json.loads(json.dumps(block)))
    assert again["defenses"] == block["defenses"]
    assert again["cond_immune"] == block["cond_immune"]
    assert again["resources"] == block["resources"]


def test_unknown_damage_type_fails_closed_at_import():
    rows, hdr = C.parse(ROW.replace("psychic", "psychic,lasercannon"))
    _clean, errs, _warn = C.validate("creature", rows, hdr, "creatures.csv")
    assert any("lasercannon" in e["msg"] for e in errs)


def _npc_token(code, block):
    rid = rid_of(code)
    tok_id = db.x("INSERT INTO tokens (room_id,label,x,y,npc) VALUES (?,?,?,?,?)",
                  (rid, "Grell", 5.0, 5.0, db.json_dumps(block)))
    return db.q1("SELECT * FROM tokens WHERE id=?", (tok_id,))


def test_resist_immune_vulnerable_hit_the_real_damage_path(client):
    dm, _p, code, _ch = base_room(client)
    tok = _npc_token(code, npc.project_creature(_row()))
    room_id = rid_of(code)

    async def hit(dtype, amount=-8):
        tok_row = db.q1("SELECT * FROM tokens WHERE id=?", (tok["id"],))
        return await health.change_hp(room_id, tok_row, amount, damage_type=dtype)

    r = asyncio.run(hit("psychic"))                  # resistant: 8 -> 4
    assert r and r["damage"] == 4
    r = asyncio.run(hit("bludgeoning"))              # vulnerable: 8 -> 16
    assert r and r["damage"] == 16
    r = asyncio.run(hit("poison"))                   # immune: 8 -> 0
    assert r and r["damage"] == 0 and r["immune"]


def test_condition_immunity_blocks_a_real_cast(client):
    dm, player, code, ch = base_room(client)
    abilities.register({"id": "d163_daze", "name": "Daze", "ability": "int",
                        "range_ft": 120, "targeting": "single",
                        "resolution": "auto",
                        "condition": {"key": "charmed", "rounds": 1}})
    db.x("UPDATE characters SET abilities=? WHERE id=?",
         (db.json_dumps(["d163_daze"]), ch["id"]))
    for t in db.q("SELECT * FROM tokens WHERE room_id=? AND character_id=?",
                  (rid_of(code), ch["id"])):
        caster = t
    grell = _npc_token(code, npc.project_creature(_row()))
    result = asyncio.run(abilities.execute(
        rid_of(code), actor_token_id=caster["id"], ability_id="d163_daze",
        is_dm=True, actor_user_id=None, target_id=grell["id"]))
    assert result["ok"]
    entry = result["entries"][0]
    assert entry.get("condition_immune") == "charmed"
    assert "condition" not in entry
    assert not db.j(db.q1("SELECT conds FROM tokens WHERE id=?", (grell["id"],))["conds"], [])
