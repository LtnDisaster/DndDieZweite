"""D128: NPC attack reach uses the existing footprint/plane range engine."""
import uuid

import pytest
from starlette.testclient import TestClient

from app import main
from tests.test_movement_fog import H, reg, recv_until, ws_connect


@pytest.fixture()
def client():
    return TestClient(main.app)


def _token(ws, label, x, y, attacks=None, reach=5):
    atk = [{"id": "bite", "name": "Bite", "to_hit": 30, "dmg": "1d6", "reach": reach}]
    if attacks is not None:
        atk = attacks
    ws.send_json({"type": "add_token", "label": label, "x": x, "y": y, "ac": 10,
                  "attacks": atk})
    return recv_until(ws, "token_add")["payload"]["id"]


def test_npc_attack_default_reach_refuses_the_cell_beyond_adjacent(client):
    dm = reg(client, "reachdm" + uuid.uuid4().hex[:4])
    code = client.post("/api/rooms", json={"name": "Reach"}, headers=H(dm)).json()["code"]
    with ws_connect(client, dm, code) as ws:
        target = _token(ws, "Target", 500, 300)
        attacker = _token(ws, "Brute", 400, 300)
        ws.send_json({"type": "npc_attack", "token_id": attacker, "attack": "bite",
                      "mode": "attack", "target_id": target})
        ev = recv_until(ws, "error", fail_on_error=False)
    assert ev["kind"] == "error" and "reach" in ev["payload"]["msg"]


def test_npc_attack_declared_reach_reaches_the_farther_cell(client):
    dm = reg(client, "reachdm2" + uuid.uuid4().hex[:4])
    code = client.post("/api/rooms", json={"name": "Reach2"}, headers=H(dm)).json()["code"]
    with ws_connect(client, dm, code) as ws:
        target = _token(ws, "Target", 500, 300)
        attacker = _token(ws, "Long Brute", 400, 300, reach=10)
        ws.send_json({"type": "npc_attack", "token_id": attacker, "attack": "bite",
                      "mode": "attack", "target_id": target})
        ev = recv_until(ws, "dice")["payload"]["text"]
    assert "Long Brute" in ev and "Bite" in ev and "AC 10" in ev


def test_content_attack_reach_survives_npc_block(client):
    from app import npc

    block = npc.project_creature({
        "id": "long-attack", "name": "Long Attack", "str": 16, "dex": 10, "con": 10,
        "int": 10, "wis": 10, "cha": 10, "hp": 7, "ac": 12,
        "attacks": "Maul +5 to hit; 2d6+3 bludgeoning, reach 10 ft"
    })
    assert block["attacks"][0]["reach"] == 10
    assert npc.clean_npc(block)["attacks"][0]["reach"] == 10


def test_npc_attack_editor_exposes_reach():
    from pathlib import Path
    src = Path(__file__).resolve().parents[1].joinpath("app/static/js/30_room.js").read_text()
    assert 'class="na-reach"' in src
    assert "a.reach = Math.max(0, Math.min(999" in src