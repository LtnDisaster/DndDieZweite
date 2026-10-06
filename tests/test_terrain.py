"""Phase 4 (D69): terrain registry vocabulary — 3 barrier (blocks movement,
NOT vision, climbable) and 4 low_obstacle (passable, double cost, climbable).
path/los/footprint/movecost all consume mapmodel.TERRAIN via one registry.
"""
import pytest
from starlette.testclient import TestClient

from app import db, los, mapmodel, movecost, path, wall
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


def mp(w=12, h=8, mutate=None):
    m = mapmodel.sanitize({"w": w, "h": h, "cells": [0] * (w * h)})
    if mutate:
        mutate(m)
    return m


def column(m, x, v):
    for y in range(m["h"]):
        m["cells"][y * m["w"] + x] = v


# ---------- sanitize + registry ----------

def test_sanitize_accepts_the_extended_vocabulary_and_clamps():
    m = mapmodel.sanitize({"w": 8, "h": 6, "cells": [3, 4] + [0] * 46})
    assert m["cells"][:2] == [3, 4]
    m = mapmodel.sanitize({"w": 8, "h": 6, "cells": [9, -3, 5, 1] + [0] * 44})
    assert m["cells"][:4] == [4, 0, 4, 1]


def test_registry_semantics():
    assert mapmodel.walkable(4) and not mapmodel.walkable(3) and not mapmodel.walkable(1)
    assert mapmodel.blocks_movement(3) and not mapmodel.blocks_movement(4)
    assert mapmodel.blocks_vision(1) and not mapmodel.blocks_vision(3)
    assert mapmodel.difficult(2) and mapmodel.difficult(4) and not mapmodel.difficult(3)
    assert mapmodel.terrain(3)["climbable"] and mapmodel.terrain(4)["climbable"]


def test_wall_facade_agrees_with_registry():
    m = mp(mutate=lambda g: (column(g, 5, 1), column(g, 6, 3), g["cells"].__setitem__(0, 4)))
    assert wall.blocks_movement(m, 5, 2) and wall.blocks_vision(m, 5, 2)
    assert wall.blocks_movement(m, 6, 2) and not wall.blocks_vision(m, 6, 2)
    assert not wall.blocks_movement(m, 0, 0) and wall.height_units(m, 6, 2) == 1
    assert wall.climbable(m, 5, 2) and wall.name(m, 6, 2) == "barrier"


# ---------- path, LOS, cost ----------

def test_barrier_seals_a_corridor_but_low_obstacle_does_not():
    m = mp(mutate=lambda g: column(g, 5, 3))
    assert path.find_path(m, (2, 4), (9, 4)) is None
    m2 = mp(mutate=lambda g: column(g, 5, 4))
    assert path.find_path(m2, (2, 4), (9, 4)) is not None


def test_barrier_does_not_block_line_of_sight():
    m = mp(mutate=lambda g: column(g, 5, 3))
    assert los.line_of_sight(m, (3, 4), (8, 4))
    m2 = mp(mutate=lambda g: column(g, 5, 1))
    assert not los.line_of_sight(m2, (3, 4), (8, 4))


def test_low_obstacle_double_costs_in_movecost():
    m = mp(mutate=lambda g: [g["cells"].__setitem__(4 * 12 + x, 4) for x in (1, 2)])
    assert movecost.route_cost(_mp(m["w"], m["h"], m["cells"]), [(0, 4), (1, 4), (2, 4)]) == 4


def test_footprint_position_rejects_barrier_cells():
    from app import footprint
    m = mp(mutate=lambda g: column(g, 5, 3))
    assert footprint.valid_terrain_position(m, (5, 4), 1) is False
    m2 = mp(mutate=lambda g: column(g, 5, 4))
    assert footprint.valid_terrain_position(m2, (5, 4), 1) is True


# ---------- integration over the wire ----------

def test_barrier_blocks_and_low_obstacle_charges_preview(client):
    dm, player, code, ch = base_room(client)
    tok = park(client, dm, code, db.q1(
        "SELECT id FROM tokens WHERE room_id=? AND character_id=?",
        (db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"], ch["id"]))["id"])

    def barrier_wide(g):
        for y in range(g["h"]):
            g["cells"][y * g["w"] + 19] = 3
    set_grid(client, dm, code, barrier_wide)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "path_preview", "token_id": tok["id"],
                      "tx": 22, "ty": 12, "request_id": 1})
        ev = recv_until(ws, "error")
        assert "No path" in ev["payload"]["msg"]

    def low_bands(g):                                    # 2-column low band: not avoidable by A*
        for y in range(g["h"]):
            g["cells"][y * g["w"] + 19] = 0
            for x in (19, 20):
                g["cells"][y * g["w"] + x] = 4
    set_grid(client, dm, code, low_bands)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "path_preview", "token_id": tok["id"],
                      "tx": 21, "ty": 12, "request_id": 2})
        prev = recv_until(ws, "path_preview")["payload"]
        # 5 steps 16->21, exactly two cross low cells (19,20) -> each costs double
        assert prev["cost"] == 1 + 1 + 2 + 2 + 1 and prev["path"][0] == {"x": 17, "y": 12}
