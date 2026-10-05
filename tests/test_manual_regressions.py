"""Regressions found during the first real post-sprint browser smoke test."""
from app import db
from test_movement_fog import base_room, state_of, ws_connect, recv_until

import pytest
from starlette.testclient import TestClient
from app.main import app

@pytest.fixture()
def client():
    return TestClient(app)


def test_down_player_cannot_preview_or_move(client):
    dm, player, code, ch = base_room(client)
    tok = next(t for t in state_of(client, player, code)["tokens"] if t.get("character_id") == ch["id"])
    db.x("UPDATE characters SET hp=0 WHERE id=?", (ch["id"],))
    db.x("UPDATE tokens SET death=? WHERE id=?", (db.json_dumps({"s":0,"f":0,"stable":False,"dead":False}), tok["id"]))
    before = db.q1("SELECT x,y FROM tokens WHERE id=?", (tok["id"],))
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type":"path_preview", "token_id":tok["id"], "tx":9, "ty":6, "request_id":99})
        assert "downed" in recv_until(ws, "error")["payload"]["msg"].lower()
        ws.send_json({"type":"move", "token_id":tok["id"], "tx":9, "ty":6})
        assert "downed" in recv_until(ws, "error")["payload"]["msg"].lower()
    after = db.q1("SELECT x,y FROM tokens WHERE id=?", (tok["id"],))
    assert (after["x"], after["y"]) == (before["x"], before["y"])


def test_map_edit_preserves_runtime_trap_and_loot_state(client):
    dm, player, code, _ = base_room(client)
    grid = state_of(client, dm, code)["grid"]
    grid["traps"] = [{"id":"trap1", "x":3, "y":3, "label":"Pit", "dc":12, "dmg":"1d4", "discovered":False}]
    grid["loot"] = [{"id":"loot1", "x":4, "y":3, "label":"Chest", "taken_by":None}]
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type":"map_edit", "map":grid})
        recv_until(ws, "map_changed")

    # Runtime gameplay changes happen after the editor snapshot was taken.
    current = state_of(client, dm, code)["grid"]
    stale_editor = {**current, "cells": list(current["cells"]),
                    "explored": list(current["explored"]),
                    "traps": [dict(x) for x in current["traps"]],
                    "loot": [dict(x) for x in current["loot"]]}
    current["traps"][0]["discovered"] = True
    current["loot"][0]["taken_by"] = 12345
    from app.room.net import set_map
    set_map(db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"], current)

    stale_editor["cells"][0] = 1  # unrelated terrain edit
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type":"map_edit", "map":stale_editor})
        recv_until(ws, "map_changed")

    saved = state_of(client, dm, code)["grid"]
    assert saved["cells"][0] == 1
    assert saved["traps"][0]["discovered"] is True
    assert saved["loot"][0]["taken_by"] == 12345


def test_confirmed_preview_route_is_accepted_as_exact_server_route(client):
    """A confirmed preview may carry its server-produced path back to move()."""
    dm, player, code, _ = base_room(client)
    with ws_connect(client, player, code) as ws:
        tok = next(t for t in state_of(client, player, code)["tokens"] if t.get("owner_user_id"))
        ws.send_json({"type":"path_preview", "token_id":tok["id"], "tx":11, "ty":6, "request_id":321})
        prev = recv_until(ws, "path_preview")["payload"]
        ws.send_json({"type":"move", "token_id":tok["id"], "tx":11, "ty":6,
                      "teleport":False, "path":prev["path"]})
        first = recv_until(ws, "step", tries=20)["payload"]
        assert (first["cx"], first["cy"]) == (prev["path"][0]["x"], prev["path"][0]["y"])
