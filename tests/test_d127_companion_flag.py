"""D127: the companion flag survives CSV → block → bestiary/DM UI."""
import uuid
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from app import content, db, main, npc
from tests.test_movement_fog import H, join_room, reg


ROOM_JS = Path("app/static/js/30_room.js")
CONTENT_JS = Path("app/static/js/70_content.js")


@pytest.fixture()
def client():
    return TestClient(main.app)


def _room(client):
    dm = reg(client, f"d127dm-{uuid.uuid4().hex[:4]}")
    player = reg(client, f"d127p-{uuid.uuid4().hex[:4]}")
    code = client.post("/api/rooms", json={"name": "D127"}, headers=H(dm)).json()["code"]
    join_room(client, player, code)
    rid = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
    content.import_package({"creatures.csv": open("app/content_pack/creatures.csv",
                                                  encoding="utf-8").read()},
                           rid, mode="apply", apply=True)
    return dm, code


def test_creature_companion_projects_and_round_trips_to_bestiary(client):
    assert npc.project_creature({
        "id": "pet", "name": "Pet", "companion": "1",
    })["companion"] is True
    assert npc.project_creature({
        "id": "pet", "name": "Pet",
    })["companion"] is False

    dm = reg(client, f"d127b-{uuid.uuid4().hex[:4]}")
    created = client.post("/api/creatures", headers=H(dm), json={
        "name": "Pet", "companion": True,
    }).json()
    assert created["block"]["companion"] is True
    updated = client.put(f"/api/creatures/{created['id']}", headers=H(dm), json={
        "name": "Pet", "companion": False,
    }).json()
    assert updated["block"]["companion"] is False


def test_creature_review_marks_csv_companion_and_block_path_is_pinned(client):
    dm, code = _room(client)
    rows = client.get(f"/api/content/{code}/creature-rows", headers=H(dm)).json()["creatures"]
    assert any(row["name"] == "Wolfkin" and row["companion"] is True for row in rows)
    assert any(row["name"] == "Hawk-kin" and row["companion"] is True for row in rows)

    assert 'id="npc-companion"' in ROOM_JS.read_text(encoding="utf-8")
    assert "c.companion" in CONTENT_JS.read_text(encoding="utf-8")
