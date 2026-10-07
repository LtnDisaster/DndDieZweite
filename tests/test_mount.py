"""D82: generic MOUNT relationship (rider -> mount), DM-managed and ACYCLIC.

The relationship layer ships fully: assign/unassign, same-room, self-cycle
and multi-hop cycle rejection, persistence and snapshot round-trip, clear
separation from the controller relationship. Carrying movement is
deliberately NOT silently half-implemented (see docs).
"""
import pytest
from starlette.testclient import TestClient

from app import main


@pytest.fixture()
def client():
    return TestClient(main.app)
from tests.test_movement_fog import H, add_npc, base_room, recv_until, state_of, ws_connect


def tok_row(token_id):
    from app import db
    return db.q1("SELECT * FROM tokens WHERE id=?", (token_id,))


def test_assign_persist_revoke(client):
    dm, player, code, _ = base_room(client)
    with ws_connect(client, dm, code) as ws:
        rider = add_npc(ws, "Knight", cx=10, cy=10)
        horse = add_npc(ws, "Horse", cx=11, cy=10)
        ws.send_json({"type": "token_mount", "token_id": rider, "mount_id": horse})
        ev = recv_until(ws, "token_mount")["payload"]
        assert ev == {"token_id": rider, "mount_token_id": horse}
    st = state_of(client, dm, code)
    assert next(t for t in st["tokens"] if t["id"] == rider)["mount_token_id"] == horse
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "token_mount", "token_id": rider, "mount_id": None})
        assert recv_until(ws, "token_mount")["payload"]["mount_token_id"] is None
    assert tok_row(rider)["mount_token_id"] is None


def test_self_and_cycle_rejected(client):
    dm, player, code, _ = base_room(client)
    with ws_connect(client, dm, code) as ws:
        a = add_npc(ws, "A", cx=10, cy=10)
        b = add_npc(ws, "B", cx=11, cy=10)
        c = add_npc(ws, "C", cx=12, cy=10)
        ws.send_json({"type": "token_mount", "token_id": a, "mount_id": a})
        err = recv_until(ws, "error", fail_on_error=False)
        assert "itself" in err["payload"]["msg"].lower()
        ws.send_json({"type": "token_mount", "token_id": b, "mount_id": a})
        recv_until(ws, "token_mount")
        ws.send_json({"type": "token_mount", "token_id": a, "mount_id": b})   # A->B->A
        err = recv_until(ws, "error", fail_on_error=False)
        assert "cycle" in err["payload"]["msg"].lower()
        # build a 3-chain C->B->A, then try A->C
        ws.send_json({"type": "token_mount", "token_id": c, "mount_id": b})
        recv_until(ws, "token_mount")
        ws.send_json({"type": "token_mount", "token_id": a, "mount_id": c})   # A->C->B->A
        err = recv_until(ws, "error", fail_on_error=False)
        assert "cycle" in err["payload"]["msg"].lower()
        assert tok_row(a)["mount_token_id"] is None                  # never mutated
        assert tok_row(b)["mount_token_id"] == a and tok_row(c)["mount_token_id"] == b


def test_mount_must_be_same_room(client):
    dm, player, code, _ = base_room(client)
    with ws_connect(client, dm, code) as ws:
        rider = add_npc(ws, "Centaur")
        ws.send_json({"type": "token_mount", "token_id": rider, "mount_id": 999999})
        err = recv_until(ws, "error", fail_on_error=False)
        assert "room" in err["payload"]["msg"].lower()


def test_mount_is_dm_only_and_mount_never_controller(client):
    dm, player, code, _ = base_room(client)
    with ws_connect(client, dm, code) as ws:
        rider = add_npc(ws, "Knight", cx=10, cy=10)
        horse = add_npc(ws, "Horse", cx=11, cy=10)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "token_mount", "token_id": rider, "mount_id": horse})
        err = recv_until(ws, "error", fail_on_error=False)
        assert "dm only" in err["payload"]["msg"].lower()
    assert tok_row(rider)["mount_token_id"] is None
