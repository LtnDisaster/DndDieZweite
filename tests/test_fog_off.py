"""Sprint 8 (P4): room-wide fog-off flag — terrain to everyone, foes still LOS.

fog_off lives in the persisted map, is owned solely by fog_toggle (editor
snapshots must not reset it), hides nothing that moves: NPC live positions
stay filtered per recipient by the LOS pipeline.
"""
import pytest
from starlette.testclient import TestClient

from app.main import app
from test_movement_fog import add_npc, base_room, recv_until, state_of, ws_connect


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def toggle(client, user, code, on):
    with ws_connect(client, user, code) as ws:
        ws.send_json({"type": "fog_toggle", "on": on})
        recv_until(ws, "map_changed")


def test_fog_off_reveals_terrain_but_not_hidden_foes(client):
    dm, player, code, ch = base_room(client)
    with ws_connect(client, dm, code) as ws:
        npc_id = add_npc(ws)  # far corner (15,13), hidden from the party
    pg = state_of(client, player, code)["grid"]
    assert pg["fog_off"] is False
    assert None in pg["cells"], "expected fog on a fresh room"
    assert npc_id not in [t["id"] for t in state_of(client, player, code)["tokens"]]

    toggle(client, dm, code, True)
    pg = state_of(client, player, code)["grid"]
    assert pg["fog_off"] is True
    assert None not in pg["cells"], "fog-off must transmit full terrain"
    # persistent-memory flag still readable by the DM view untouched:
    dg = state_of(client, dm, code)["grid"]
    assert dg["fog_off"] is True
    # ... but a foe across the map is STILL hidden from the player:
    assert npc_id not in [t["id"] for t in state_of(client, player, code)["tokens"]]

    # editor snapshot (no fog_off key) must not silently re-enable fog
    stale = state_of(client, dm, code)["grid"]
    stale.pop("fog_off", None)
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "map_edit", "map": stale})
        recv_until(ws, "map_changed")
    assert state_of(client, dm, code)["grid"]["fog_off"] is True

    # toggle back restores the fog memory
    toggle(client, dm, code, False)
    pg = state_of(client, player, code)["grid"]
    assert pg["fog_off"] is False
    assert None in pg["cells"]


def test_fog_off_persists_across_reconnect_and_player_cannot_toggle(client):
    dm, player, code, ch = base_room(client)
    toggle(client, dm, code, True)
    # fresh player state read = already revealed (server-side, not client fx)
    assert None not in state_of(client, player, code)["grid"]["cells"]
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "fog_toggle", "on": False})
        err = recv_until(ws, "error")
        assert err["payload"]["msg"] == "DM only"
    assert state_of(client, dm, code)["grid"]["fog_off"] is True


def test_reset_fog_and_toggle_are_independent(client):
    dm, player, code, ch = base_room(client)
    assert state_of(client, player, code)["grid"]["explored"].count(1) > 0
    toggle(client, dm, code, True)
    with ws_connect(client, dm, code) as ws:
        grid = state_of(client, dm, code)["grid"]
        ws.send_json({"type": "map_edit", "map": grid, "reset_fog": True})
        recv_until(ws, "map_changed")
    dg = state_of(client, dm, code)["grid"]
    assert dg["explored"].count(1) == 0
    assert dg["fog_off"] is True, "reset_fog must not clear the fog-off flag"
