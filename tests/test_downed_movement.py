"""Sprint 8 (P2): downed (HP<=0) movement rejection is server-authoritative.

The gate lives in movement._movement_block_reason and runs BEFORE any route
work in handle_path_preview, handle_move (including DM teleport and a carried
preview path) and every step of walk(). Tactical and diorama are two renderers
over the same WS messages, so these server tests cover both views identically.
NPC/monster tokens (character_id NULL) intentionally keep DM control — a DM may
still drag a 0 HP monster token; that is by design, not a hole.
"""
from app import db
from test_movement_fog import (add_npc, base_room, recv_until, state_of,
                               ws_connect)

import pytest
from starlette.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def room_id_of(code):
    return db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]


def player_tok(code, ch):
    return db.q1("SELECT * FROM tokens WHERE room_id=? AND character_id=?",
                 (room_id_of(code), ch["id"]))


def drop_to_zero(ch):
    db.x("UPDATE characters SET hp=0 WHERE id=?", (ch["id"],))


def test_downed_move_rejected_even_with_a_carried_valid_path(client):
    """A route previewed while healthy must not smuggle a downed token out."""
    dm, player, code, ch = base_room(client)
    tok = player_tok(code, ch)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "path_preview", "token_id": tok["id"],
                      "tx": 12, "ty": 6, "request_id": 5})
        prev = recv_until(ws, "path_preview")["payload"]
    drop_to_zero(ch)
    before = db.q1("SELECT x, y FROM tokens WHERE id=?", (tok["id"],))
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "move", "token_id": tok["id"], "tx": 12, "ty": 6,
                      "teleport": False, "path": prev["path"]})
        err = recv_until(ws, "error")["payload"]
        assert "downed" in err["msg"].lower()
        # malformed payloads after the gate must error, not crash the socket
        ws.send_json({"type": "move", "token_id": tok["id"], "tx": 12, "ty": 6,
                      "path": "not-a-list"})
        assert "downed" in recv_until(ws, "error")["payload"]["msg"].lower()
    after = db.q1("SELECT x, y FROM tokens WHERE id=?", (tok["id"],))
    assert (after["x"], after["y"]) == (before["x"], before["y"])


def test_dm_cannot_teleport_a_downed_character(client):
    dm, player, code, ch = base_room(client)
    tok = player_tok(code, ch)
    drop_to_zero(ch)
    before = db.q1("SELECT x, y FROM tokens WHERE id=?", (tok["id"],))
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "move", "token_id": tok["id"], "tx": 14, "ty": 8,
                      "teleport": True})
        assert "downed" in recv_until(ws, "error")["payload"]["msg"].lower()
    after = db.q1("SELECT x, y FROM tokens WHERE id=?", (tok["id"],))
    assert (after["x"], after["y"]) == (before["x"], before["y"])


def test_walk_stops_when_token_drops_to_zero_mid_route(client):
    dm, player, code, ch = base_room(client)
    tok = player_tok(code, ch)
    goal = 14  # 6 cells: inside the fog preview allowance
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "path_preview", "token_id": tok["id"],
                      "tx": goal, "ty": 6, "request_id": 6})
        prev = recv_until(ws, "path_preview")["payload"]
        ws.send_json({"type": "move", "token_id": tok["id"], "tx": goal, "ty": 6,
                      "teleport": False, "path": prev["path"]})
        first = recv_until(ws, "step", tries=20)["payload"]
        assert first["token_id"] == tok["id"]
        drop_to_zero(ch)                       # damage lands mid-walk
        for _ in range(80):
            ev = ws.receive_json()
            p = ev.get("payload") or {}
            if (ev.get("kind") == "move_state" and p.get("token_id") == tok["id"]
                    and p.get("moving") is False):
                assert p.get("reason") == "downed"
                break
        else:
            raise AssertionError("walk never stopped")
    row = db.q1("SELECT x, y FROM tokens WHERE id=?", (tok["id"],))
    stopped_at = int(row["x"] // 50)
    assert int(row["y"] // 50) == 6
    assert first["cx"] <= stopped_at < goal, "token holds its last legal cell"


def test_npc_at_zero_hp_still_follows_dm_control_by_design(client):
    """Monsters have no death saves; the downed gate is a PC rule. A DM may
    still move a 0 HP NPC token (corpse dragging), and that must stay true."""
    dm, player, code, ch = base_room(client)
    with ws_connect(client, dm, code) as ws:
        npc_id = add_npc(ws, label="Goblin", cx=12, cy=10)
    db.x("UPDATE tokens SET npc=? WHERE id=?",
         (db.json_dumps({"name": "Goblin", "hp": 0, "max_hp": 4}), npc_id))
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "move", "token_id": npc_id, "tx": 13, "ty": 10,
                      "teleport": False})
        seen = []
        for _ in range(30):
            ev = ws.receive_json()
            p = ev.get("payload") or {}
            seen.append(ev.get("kind"))
            if ev.get("kind") == "move_state" and p.get("token_id") == npc_id and p.get("moving") is False:
                break
            if ev.get("kind") == "error":
                raise AssertionError(f"NPC move refused: {p}")
        assert "move_state" in seen
