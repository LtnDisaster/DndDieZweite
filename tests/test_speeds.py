"""Phase 3: gear.clean_speeds is the SSOT for movement modes; NPC blobs carry
authorable fly/swim/climb; walk stays the budget currency (foundation only).
"""
import pytest
from starlette.testclient import TestClient

from app import gear
from app.main import app
from test_movement_fog import (add_npc, base_room, recv_until, state_of,
                               ws_connect)


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


# ---------- clean_speeds ----------

def test_pc_row_int_and_garbage_all_normalise():
    assert gear.clean_speeds({"speed": 40})["walk"] == 40
    assert gear.clean_speeds({"speed": None})["walk"] == 30
    assert gear.clean_speeds(35)["walk"] == 35
    assert gear.clean_speeds(None) == {"walk": 30, "fly": 0, "swim": 0, "climb": 0}
    assert gear.clean_speeds({"speed": "lots"})["walk"] == 30


def test_extra_modes_only_when_authored():
    blob = {"speed": 30, "fly": 60, "swim": "bad", "climb": 30}
    s = gear.clean_speeds(blob)
    assert s == {"walk": 30, "fly": 60, "swim": 0, "climb": 30}
    assert gear.clean_speeds({"speed": 9999})["walk"] == 999         # bounded


# ---------- NPC authoring round trip ----------

def test_npc_fly_swim_climb_survive_clean_and_ws(client):
    dm, player, code, ch = base_room(client)
    with ws_connect(client, dm, code) as ws:
        npc = add_npc(ws, label="Bat", cx=16, cy=12)
        ws.send_json({"type": "update_npc", "token_id": npc, "speed": 5,
                      "fly": 30, "swim": 0, "climb": 0})
        recv_until(ws, "snapshot")
    tok = next(t for t in state_of(client, dm, code)["tokens"] if t["id"] == npc)
    blob = tok["npc"]
    assert blob["speeds"] == {"walk": 5, "fly": 30, "swim": 0, "climb": 0}
    assert blob["fly"] == 30 and blob["speed"] == 5
