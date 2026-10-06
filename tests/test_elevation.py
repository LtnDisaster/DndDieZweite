"""Phase 5 (D70): elevation as integer layer on the map + tokens.z column.
Stepping between cells one elevation unit apart is legal; two or more blocks the
step. Tokens always rest at their ground cell's elevation; players learn height
only through explored fog.
"""
import pytest
from starlette.testclient import TestClient

from app import db, mapmodel, path
from app.main import app
from test_movement_fog import (base_room, park, recv_until, set_grid,
                               state_of, ws_connect)


def _mp(w, h, cells=None, **kw):
    """D72: pure grid modules take the map object; cells stay WORLD space."""
    m = {"w": w, "h": h}
    if cells is not None:
        m["cells"] = cells
    m.update(kw)
    return m


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def mp(w=12, h=8):
    return mapmodel.sanitize({"w": w, "h": h, "cells": [0] * (w * h)})


# ---------- model ----------

def test_default_and_sanitize_elevation():
    m = mp()
    assert m["elev"] == [0] * 96
    m["elev"][7] = 2
    m2 = mapmodel.sanitize(m)
    assert m2["elev"][7] == 2
    m2["elev"][0] = 99
    assert mapmodel.sanitize(m2)["elev"][0] == 6          # clamped to -6..6
    bad = {"w": 12, "h": 8, "cells": [0] * 96, "elev": [1, 2]}   # wrong length
    assert mapmodel.sanitize(bad)["elev"] == [0] * 96


def test_grow_shifts_elevation_with_the_world():
    m = mp(w=20, h=8)
    for y in range(8):
        m["cells"][y * 20 + 5] = 0
        m["elev"][y * 20 + 5] = 2
    grown, (dx, dy) = mapmodel.grow_map(m, ["west"], 12)
    assert (dx, dy) == (12, 0)
    assert grown["elev"][7 * grown["w"] + 5 + 12] == 2
    assert grown["elev"][0] == 0                          # new land is flat ground


# ---------- movement rules ----------

def test_cliff_blocks_path_one_step_up_does_not():
    m = mp()
    for y in range(8):
        m["elev"][y * 12 + 6] = 3                          # two-unit jump from ground
    assert path.find_path(m, (3, 4), (9, 4)) is None
    for y in range(8):
        m["elev"][y * 12 + 6] = 1                          # one step -> climbable
    assert path.find_path(m, (3, 4), (9, 4)) is not None
    flat = {**m, "elev": None}                        # D72: the map carries the layer
    assert path.find_path(flat, (3, 4), (9, 4)) is not None   # elev None = flat


# ---------- wire level ----------

def _tok_id(code, ch):
    return db.q1("SELECT t.id FROM tokens t JOIN rooms r ON t.room_id=r.id "
                 "WHERE r.code=? AND t.character_id=?", (code, ch["id"]))["id"]


def test_token_rests_at_cell_elevation_and_player_sees_only_explored(client):
    dm, player, code, ch = base_room(client)
    tok = park(client, dm, code, _tok_id(code, ch))

    def plateau(g):
        for y in range(g["h"]):
            for x in range(17, 22):
                g["elev"][y * g["w"] + x] = 2
    set_grid(client, dm, code, plateau)

    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "move", "token_id": tok["id"], "tx": 18, "ty": 12, "teleport": True})
        recv_until(ws, "step")
    t = next(t for t in state_of(client, dm, code)["tokens"] if t["id"] == tok["id"])
    assert t["z"] == 2                                     # z follows the ground
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "move", "token_id": tok["id"], "tx": 16, "ty": 12, "teleport": True})
        recv_until(ws, "step")
    t = next(t for t in state_of(client, dm, code)["tokens"] if t["id"] == tok["id"])
    assert t["z"] == 0

    pg = state_of(client, player, code)["grid"]
    assert pg["elev"][12 * pg["w"] + 16] == 0              # explored near the token
    far = [v is None for v in pg["elev"]]
    assert any(far), "unexplored elevation must be hidden from players"


def test_cliff_blocks_the_real_preview(client):
    dm, player, code, ch = base_room(client)
    tok = park(client, dm, code, _tok_id(code, ch))

    def cliff(g):
        for y in range(g["h"]):
            g["elev"][y * g["w"] + 19] = 2
    set_grid(client, dm, code, cliff)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "path_preview", "token_id": tok["id"],
                      "tx": 21, "ty": 12, "request_id": 1})
        ev = recv_until(ws, "error")
        assert "No path" in ev["payload"]["msg"]
    def steps(g):
        for y in range(g["h"]):
            g["elev"][y * g["w"] + 19] = 1
    set_grid(client, dm, code, steps)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "path_preview", "token_id": tok["id"],
                      "tx": 21, "ty": 12, "request_id": 2})
        prev = recv_until(ws, "path_preview")["payload"]
        assert prev["path"][-1] == {"x": 21, "y": 12}
