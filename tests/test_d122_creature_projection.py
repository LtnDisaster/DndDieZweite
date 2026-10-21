"""D122: room-scoped creature CSV content projects into the existing bestiary."""
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from app import content as C, db, main, npc
from tests.test_movement_fog import (H, base_room, recv_until, reg, ws_connect)

PACK = Path(__file__).resolve().parents[1] / "app" / "content_pack"


@pytest.fixture()
def client():
    return TestClient(main.app)


def _import(client, dm, code):
    rid = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
    files = {p.name: p.read_text(encoding="utf-8") for p in PACK.glob("*.csv")}
    report = C.import_package(files, room_id=rid, mode="apply", apply=True)
    assert report["ok"]
    return rid


def test_project_creature_uses_existing_npc_shape_and_attack_parser():
    block = npc.project_creature({
        "id": "wolfkin", "name": "Wolfkin", "size": "medium", "type": "beast",
        "ac": 13, "hp": 11, "speed_ft": 40, "str": 12, "dex": 15, "con": 12,
        "int": 3, "wis": 12, "cha": 6, "skills": "perception, stealth",
        "saves": "dex, wis", "attacks": "Bite +4 to hit; 1d6+2 piercing",
        "tags": "companion, beast", "manual": "demo",
    })
    assert block["stats"] == {"str": 12, "dex": 15, "con": 12, "int": 3,
                              "wis": 12, "cha": 6}
    assert block["ac"] == 13 and block["max_hp"] == 11 and block["speeds"]["walk"] == 40
    attack = block["attacks"][0]
    assert (attack["id"], attack["name"], attack["to_hit"], attack["dmg"]) == (
        "bite", "Bite", 4, "1d6+2")
    assert block["skills"] == {"perception": 1, "stealth": 1}
    assert all(block["saves"][a] for a in ("dex", "wis"))
    assert not any(block["saves"][a] for a in ("str", "con", "int", "cha"))
    assert block["unsupported"] == []
    assert "demo" in block["notes"]


def test_creature_csv_projects_to_room_dm_bestiary(client):
    dm, _player, code, _ch = base_room(client)
    _import(client, dm, code)
    r = client.get(f"/api/content/{code}/creature/wolfkin/projection", headers=H(dm))
    assert r.status_code == 200
    assert r.json()["projection"]["attacks"][0]["dmg"] == "1d6+2"

    r = client.post(f"/api/content/{code}/creature/wolfkin/to-bestiary", headers=H(dm))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] and body["creature"]["name"] == "Wolfkin"

    listed = client.get("/api/creatures", headers=H(dm)).json()
    assert any(c["id"] == body["creature_id"] and c["block"]["attacks"][0]["name"] == "Bite"
               for c in listed)
    assert client.post(f"/api/content/{code}/creature/wolfkin/to-bestiary",
                       headers=H(dm)).status_code == 409


def test_creature_projection_is_dm_room_scoped(client):
    dm, player, code, _ch = base_room(client)
    _import(client, dm, code)
    outsider = reg(client, "d122outsider")
    assert client.get(f"/api/content/{code}/creature/wolfkin/projection",
                      headers=H(player)).status_code == 403
    assert client.get(f"/api/content/{code}/creature/wolfkin/projection",
                      headers=H(outsider)).status_code == 403
    assert client.post(f"/api/content/{code}/creature/wolfkin/to-bestiary",
                       headers=H(player)).status_code == 403
    assert client.post(f"/api/content/{code}/creature/missing/to-bestiary",
                       headers=H(dm)).status_code == 404


def test_creature_projection_list_marks_unsupported_text(client):
    dm, _player, code, _ch = base_room(client)
    rid = _import(client, dm, code)
    C.import_package({"creatures.csv": (
        "id,name,attacks\nhowler,Howler,Howl and maybe a DM describes it\n")},
        room_id=rid, mode="replace", apply=True)
    rows = client.get(f"/api/content/{code}/creature-rows", headers=H(dm)).json()["creatures"]
    howler = next(row for row in rows if row["id"] == "howler")
    wolf = next(row for row in rows if row["id"] == "wolfkin")
    assert howler["ready"] is False and "attacks" in howler["projection"]["notes"]
    assert wolf["ready"] is True and wolf["projection"]["attacks"]


def test_content_darkvision_projects_and_add_token_uses_existing_sense_column(client):
    hawk = npc.project_creature({
        "id": "hawkkin", "name": "Hawk-kin", "size": "tiny", "type": "beast",
        "ac": 14, "hp": 7, "speed_ft": 10, "fly_ft": 60,
        "darkvision_ft": 60, "attacks": "Talons +6 to hit; 1d4+4 piercing",
    })
    assert hawk["darkvision_ft"] == 60

    dm, _player, code, _ch = base_room(client)
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "add_token", "label": "Hawk-kin", "x": 250, "y": 250,
                      "npc": hawk})
        recv_until(ws, "token_add")
    tok = db.q1("SELECT * FROM tokens WHERE room_id=? AND label=?", (
        db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"], "Hawk-kin"))
    assert tok["darkvision"] == 12
    assert npc.load(tok)["darkvision_ft"] == 60


def test_update_npc_preserves_unedited_darkvision_and_reapplies_changes(client):
    dm, _player, code, _ch = base_room(client)
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "add_token", "label": "Night", "x": 250, "y": 250,
                      "npc": {"name": "Night", "darkvision_ft": 90}})
        recv_until(ws, "token_add")
        rid = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
        tok = db.q1("SELECT id FROM tokens WHERE room_id=? AND label=?", (rid, "Night"))
        ws.send_json({"type": "update_npc", "token_id": tok["id"], "label": "Night",
                      "ac": 17})
        recv_until(ws, "snapshot")
        assert db.q1("SELECT darkvision FROM tokens WHERE id=?", (tok["id"],))["darkvision"] == 18
        ws.send_json({"type": "update_npc", "token_id": tok["id"], "label": "Night",
                      "darkvision_ft": 50})
        recv_until(ws, "snapshot")
        assert db.q1("SELECT darkvision FROM tokens WHERE id=?", (tok["id"],))["darkvision"] == 10
