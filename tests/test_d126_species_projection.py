"""D126: species data drives existing movement, sight, and footprint paths."""
import uuid

import pytest
from starlette.testclient import TestClient

from app import charbuild, db, gear, main
from app import content as C
from app.room import movement, visibility
from tests.test_movement_fog import H, join_room, reg


@pytest.fixture()
def client():
    return TestClient(main.app)


def _room(client, n_players=1):
    users = [reg(client, f"d126dm-{uuid.uuid4().hex[:4]}")]
    for i in range(n_players):
        users.append(reg(client, f"d126p{i}-{uuid.uuid4().hex[:4]}"))
    code = client.post("/api/rooms", json={"name": "D126"},
                       headers=H(users[0])).json()["code"]
    rid = _rid(code)
    C.import_package({"species.csv": open("app/content_pack/species.csv",
                                          encoding="utf-8").read()},
                     rid, mode="apply", apply=True)
    for user in users[1:]:
        join_room(client, user, code)
    return users, code


def _character(client, user, race):
    return client.post("/api/characters", headers=H(user), json={
        "name": f"D126{uuid.uuid4().hex[:3]}", "race": race, "char_class": "scout",
        "background": "bg_urchin", "level": 1, "hp": 20, "max_hp": 20,
        "stats": {k: 12 for k in ("str", "dex", "con", "int", "wis", "cha")},
    }).json()


def _rid(code):
    return db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]


def _project(ch, room_id):
    spec = charbuild.species_projection(dict(ch), room_id)
    assert spec
    db.x("UPDATE characters SET build=? WHERE id=?",
         (db.json_dumps({"species": spec}), ch["id"]))
    return spec


def test_species_speed_and_darkvision_use_existing_engines(client):
    users, code = _room(client)
    player = users[1]
    ch = _character(client, player, "kin_stoutheart")
    rid = _rid(code)
    _project(ch, rid)
    client.post(f"/api/rooms/{code}/assign", json={"character_id": ch["id"]},
                headers=H(player))
    tok = db.q1("SELECT * FROM tokens WHERE room_id=? AND character_id=?",
                (rid, ch["id"]))
    ch = db.q1("SELECT * FROM characters WHERE id=?", (ch["id"],))
    sheet = gear.as_sheet(dict(ch))
    assert sheet["build"]["species"]["speed_ft"] == 25
    assert movement._speeds(tok)["walk"] == 25
    assert visibility._token_darkvision_cells(tok) == 12


def test_species_size_reaches_the_one_existing_token_footprint(client):
    users, code = _room(client)
    player = users[1]
    ch = _character(client, player, "kin_kit")
    rid = _rid(code)
    _project(ch, rid)
    client.post(f"/api/rooms/{code}/assign", json={"character_id": ch["id"]},
                headers=H(player))
    tok = db.q1("SELECT size FROM tokens WHERE room_id=? AND character_id=?",
                (rid, ch["id"]))
    assert tok["size"].lower() == "small"
