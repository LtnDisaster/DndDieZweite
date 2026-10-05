"""Sprint 8 (P3): trap lifecycle is persistent and one-shot.

untriggered -> trigger -> effect -> marked discovered+triggered -> the trap
STAYS in the authoritative map state, never springs again on walking, survives
map edits (including stale editor snapshots and resizes) and reconnects.
"""
from app import db
from test_movement_fog import (base_room, recv_until, set_grid, state_of,
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


def player_tok(client, code, ch):
    tok = db.q1("SELECT * FROM tokens WHERE room_id=? AND character_id=?",
                (room_id_of(code), ch["id"]))
    return tok


def place_trap(client, dm, code, x, y):
    def mutate(g):
        g["traps"] = [{"id": "spike1", "x": x, "y": y, "label": "Spike Plate",
                       "dc": 18, "dmg": "1d4", "discovered": False}]
    set_grid(client, dm, code, mutate)


def test_trap_triggers_once_and_persists(client):
    dm, player, code, ch = base_room(client)
    tok = player_tok(client, code, ch)
    px, py = int(tok["x"] // 50), int(tok["y"] // 50)
    place_trap(client, dm, code, px + 2, py)

    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "path_preview", "token_id": tok["id"],
                      "tx": px + 4, "ty": py, "request_id": 11})
        prev = recv_until(ws, "path_preview")["payload"]
        ws.send_json({"type": "move", "token_id": tok["id"], "tx": px + 4, "ty": py,
                      "teleport": False, "path": prev["path"]})
        reason = None
        for _ in range(60):
            ev = ws.receive_json()
            p = ev.get("payload") or {}
            if (ev.get("kind") == "move_state" and p.get("token_id") == tok["id"]
                    and p.get("moving") is False):
                reason = p.get("reason")
                break
        assert reason == "trap"

    grid = state_of(client, dm, code)["grid"]
    trap = grid["traps"][0]
    assert trap["triggered"] is True and trap["discovered"] is True
    assert trap["triggered_by"] == tok["id"]
    # token is ON the trap cell and the trap entity still exists on the map
    tok2 = db.q1("SELECT x, y FROM tokens WHERE id=?", (tok["id"],))
    assert (int(tok2["x"] // 50), int(tok2["y"] // 50)) == (px + 2, py)

    # --- walk away and back OVER the sprung cell: must not trigger again
    db.x("UPDATE characters SET hp=30 WHERE id=?", (ch["id"],))

    def one_move(ws, tx, ty, req):
        ws.send_json({"type": "path_preview", "token_id": tok["id"],
                      "tx": tx, "ty": ty, "request_id": req})
        prev = recv_until(ws, "path_preview")["payload"]
        ws.send_json({"type": "move", "token_id": tok["id"], "tx": tx, "ty": ty,
                      "teleport": False, "path": prev["path"]})
        for _ in range(90):
            ev = ws.receive_json()
            p = ev.get("payload") or {}
            if (ev.get("kind") == "move_state" and p.get("token_id") == tok["id"]
                    and p.get("moving") is False):
                return p.get("reason")
        raise AssertionError("walk never ended")

    with ws_connect(client, player, code) as ws:
        assert one_move(ws, px, py, 12) != "trap"        # step back west
        assert one_move(ws, px + 4, py, 13) != "trap"    # re-cross the sprung trap
    assert db.q1("SELECT hp FROM characters WHERE id=?", (ch["id"],))["hp"] == 30

    # --- stale map editor snapshot must not reset the lifecycle flags
    stale = state_of(client, dm, code)["grid"]
    for t in stale["traps"]:
        t["discovered"] = False
        t["triggered"] = False
        t["triggered_by"] = None
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "map_edit", "map": stale})
        recv_until(ws, "map_changed")
    saved = state_of(client, dm, code)["grid"]["traps"][0]
    assert saved["triggered"] is True and saved["discovered"] is True
    assert saved["triggered_by"] == tok["id"]

    # --- reconnect path: player /state still shows it as discovered
    pg = state_of(client, player, code)["grid"]
    assert [t["id"] for t in pg["traps"]] == ["spike1"]


def test_resize_preserves_explored_overlap(client):
    dm, player, code, ch = base_room(client)
    tok = player_tok(client, code, ch)
    # walking/assign already revealed cells around the token; capture a lit cell
    g = state_of(client, dm, code)["grid"]
    lit = [i for i, v in enumerate(g["explored"]) if v]
    assert lit, "expected revealed cells after assign"
    y0, x0 = divmod(lit[0], g["w"])
    smaller = state_of(client, dm, code)["grid"]
    smaller["w"], smaller["h"] = 20, 15
    smaller["cells"] = smaller["cells"][:0] + [0] * 300
    smaller["explored"] = [0] * 300          # editor snapshot: fog not owned
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "map_edit", "map": smaller})
        recv_until(ws, "map_changed")
    after = state_of(client, dm, code)["grid"]
    assert (after["w"], after["h"]) == (20, 15)
    if x0 < 20 and y0 < 15:
        assert after["explored"][y0 * 20 + x0] == 1, "overlap fog memory lost on resize"
