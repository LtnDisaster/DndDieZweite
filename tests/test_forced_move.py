"""Phase 6 (D71): DM-only forced movement — push/pull/shove/knockback/throw/
teleport. Stops at the first illegal cell (wall, cliff, occupied), syncs z,
never a walk (no budget, no _walks entry, NO world growth even for players).
"""
import pytest
from starlette.testclient import TestClient

from app import db
from app.main import app
from app.room import movement
from test_movement_fog import (add_npc, base_room, recv_until, set_grid,
                               state_of, wall_column, ws_connect)


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def tok_pos(client, dm, code, tok_id):
    t = next(t for t in state_of(client, dm, code)["tokens"] if t["id"] == tok_id)
    return int(t["x"] // 50), int(t["y"] // 50), t.get("z", 0)


def test_push_moves_stops_at_wall_and_is_dm_only(client):
    dm, player, code, ch = base_room(client)
    with ws_connect(client, dm, code) as ws:
        tok = next(t["id"] for t in state_of(client, player, code)["tokens"]
                   if t.get("owner_user_id"))
        ws.send_json({"type": "move", "token_id": tok, "tx": 16, "ty": 12, "teleport": True})
        recv_until(ws, "step")
        ws.send_json({"type": "forced_move", "token_id": tok, "kind": "push", "tx": 20, "ty": 12})
        done = recv_until(ws, "forced_moved")["payload"]
        assert done["to"] == {"cx": 20, "cy": 12, "z": 0}
    assert tok_pos(client, dm, code, tok)[:2] == (20, 12)
    assert tok not in movement._walks                       # not a walk

    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "move", "token_id": tok, "tx": 16, "ty": 12, "teleport": True})
        recv_until(ws, "step")
    set_grid(client, dm, code, lambda g: wall_column(g, 19))
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "forced_move", "token_id": tok, "kind": "shove", "tx": 24, "ty": 12})
        recv_until(ws, "forced_moved")
    assert tok_pos(client, dm, code, tok)[:2] == (18, 12)   # stopped before the wall

    with ws_connect(client, player, code) as ws:            # player cannot force
        ws.send_json({"type": "forced_move", "token_id": tok, "kind": "push", "tx": 16, "ty": 12})
        ws.send_json({"type": "chat", "text": "ping", "channel": "global"})
        ev = recv_until(ws, "error", fail_on_error=False)
        assert "DM-only" in ev["payload"]["msg"]
    assert tok_pos(client, dm, code, tok)[:2] == (18, 12)


def test_cliff_and_occupied_stop_a_push_and_force_never_grows_the_world(client):
    dm, player, code, ch = base_room(client)
    with ws_connect(client, dm, code) as ws:
        tok = next(t["id"] for t in state_of(client, player, code)["tokens"]
                   if t.get("owner_user_id"))
        ws.send_json({"type": "move", "token_id": tok, "tx": 16, "ty": 12, "teleport": True})
        recv_until(ws, "step")
        npc = add_npc(ws, cx=22, cy=12)
        ws.send_json({"type": "forced_move", "token_id": tok, "kind": "throw", "tx": 26, "ty": 12})
        recv_until(ws, "forced_moved")
    assert tok_pos(client, dm, code, tok)[:2] == (21, 12)   # stopped before the NPC

    def cliff(g):
        for y in range(g["h"]):
            g["elev"][y * g["w"] + 17] = 3
    set_grid(client, dm, code, cliff)
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "move", "token_id": npc, "tx": 16, "ty": 20, "teleport": True})
        recv_until(ws, "step")
        ws.send_json({"type": "forced_move", "token_id": tok, "kind": "knockback",
                      "tx": 16, "ty": 12})
        recv_until(ws, "forced_moved")
    assert tok_pos(client, dm, code, tok)[:2] == (18, 12)   # stopped one cell before the cliff

    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "forced_move", "token_id": tok, "kind": "push", "tx": 39, "ty": 12})
        recv_until(ws, "forced_moved")
    assert tok_pos(client, dm, code, tok)[:2] == (39, 12)
    g = state_of(client, dm, code)["grid"]
    assert (g["w"], g["h"]) == (40, 26)                     # even at the edge: NO growth (D67/D71)


def test_forced_teleport_respects_legality_and_z(client):
    dm, player, code, ch = base_room(client)
    with ws_connect(client, dm, code) as ws:
        tok = next(t["id"] for t in state_of(client, player, code)["tokens"]
                   if t.get("owner_user_id"))
    set_grid(client, dm, code, lambda g: (
        g["cells"].__setitem__(14 * g["w"] + 24, 1),
        [g["elev"].__setitem__(y * g["w"] + 26, 2) for y in range(g["h"])]))
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "forced_move", "token_id": tok, "kind": "teleport",
                      "tx": 24, "ty": 14})
        ws.send_json({"type": "chat", "text": "marker", "channel": "global"})
        ev = recv_until(ws, "error", fail_on_error=False)
        assert "cannot be moved" in ev["payload"]["msg"]
        ws.send_json({"type": "forced_move", "token_id": tok, "kind": "teleport",
                      "tx": 26, "ty": 12})
        done = recv_until(ws, "forced_moved")["payload"]
        assert done["to"]["z"] == 2
    assert tok_pos(client, dm, code, tok) == (26, 12, 2)
