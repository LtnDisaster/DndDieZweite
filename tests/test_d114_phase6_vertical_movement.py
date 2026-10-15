"""D114 (Sprint 43) Phase 6: vertical movement, flight through free air and
whole-volume collision.

Phase 4/5 established openings, body presence and sight. This phase makes the
vertical connection executable while deliberately reusing the ONE path,
movement-cost and footprint engines. Void is free air for a flying body; wall
and barrier remain obstruction. A creature may not turn a one-cell shaft into
an opening for a wide footprint, and vertical steps use the existing canonical
5-ft-square movement budget.
"""
import pytest
from starlette.testclient import TestClient

from app import db, footprint, mapmodel, path as P
from app.main import app
from app.room import combat as CB, vertical3d
from app.room.net import get_map
from tests.test_floor_maps import add_floor, cell_idx, set_floor_grid
from tests.test_movement_fog import (H, add_npc, base_room, recv_until,
                                     state_of, ws_connect)

CELL = 50


@pytest.fixture()
def client():
    return TestClient(app)


def rid(client, code):
    return db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]


def paint(map_name, cx, cy, *, cells=None, openv=None):
    if cells is not None:
        map_name["cells"][cell_idx(map_name, cx, cy)] = cells
    if openv is not None:
        map_name.setdefault("openv", [0] * map_name["w"] * map_name["h"])[
            cell_idx(map_name, cx, cy)] = openv


def token_at(r, floor, cx, cy, **extra):
    mp = get_map(r, floor)
    return {"id": 1, "room_id": r, "floor": floor, "size": "Medium",
            "x": (cx + .5) * mp["cell"], "y": (cy + .5) * mp["cell"],
            "z": 0, "height_ft": None, "elevation_ft": 0, **extra}


def test_void_is_open_volume_for_a_30ft_body_across_three_open_planes(client):
    dm, _, code, _ = base_room(client)
    add_floor(client, dm, code, "Upper1")
    add_floor(client, dm, code, "Upper2")
    r = rid(client, code)
    maps = vertical3d.maps_for(r)
    lm = vertical3d.level_map(r)
    cx = cy = 16

    tok = token_at(r, "", cx, cy, height_ft=30)
    foot = footprint.occupied_cells(maps[""], tok)
    for fl in ("", "Upper1", "Upper2"):
        for (x, y) in foot:
            paint(maps[fl], x, y, cells=5)                   # void = free air, not a wall
    for fl in ("", "Upper1"):
        for (x, y) in foot:
            paint(maps[fl], x, y, openv=1)

    assert footprint.valid_terrain_position(maps[""], (cx, cy), footprint.token_span(tok), mode="fly")
    assert footprint.valid_final_position(maps[""], tok, (cx, cy), tokens=[]) is False
    assert footprint.valid_final_position(maps[""], tok, (cx, cy), tokens=[], mode="fly") is True
    assert vertical3d.body_planes(r, tok, maps, lm) == {"", "Upper1", "Upper2"}


def test_solid_ceiling_still_blocks_cross_plane_body_projection(client):
    dm, _, code, _ = base_room(client)
    add_floor(client, dm, code, "Upper1")
    r = rid(client, code)
    maps = vertical3d.maps_for(r)
    lm = vertical3d.level_map(r)
    tok = token_at(r, "", 16, 16, height_ft=30)
    paint(maps["Upper1"], 16, 16, cells=5)
    assert vertical3d.body_planes(r, tok, maps, lm) == {""}


def test_wide_footprint_cannot_use_a_one_cell_opening(client):
    dm, _, code, _ = base_room(client)
    add_floor(client, dm, code, "Upper1")
    r = rid(client, code)
    maps = vertical3d.maps_for(r)
    lm = vertical3d.level_map(r)
    tok = token_at(r, "", 16, 16, size="Large", height_ft=30)
    foot = footprint.occupied_cells(maps[""], tok)

    for (x, y) in foot:
        paint(maps[""], x, y, openv=1)
    paint(maps[""], 16, 16, openv=0)
    start, goal = ("", (16, 16)), ("Upper1", (16, 16))

    def state_ok(state):
        return vertical3d.volume_final_valid(
            r, token_at(r, state[0], *state[1], size="Large", height_ft=30), [], maps, lm)

    def vertical_ok(prev, nxt, cells):
        return vertical3d.vertical_path_clear(
            r, token_at(r, prev[0], *prev[1], size="Large", height_ft=30), prev[0], nxt[0], maps, lm)

    assert P.find_path_3d(start, goal, maps, lm, (2, 2), vertical_ok=vertical_ok,
                          state_ok=state_ok) is None
    paint(maps[""], 16, 16, openv=1)
    assert P.find_path_3d(start, goal, maps, lm, (2, 2), vertical_ok=vertical_ok,
                          state_ok=state_ok) == [goal]


def test_flying_can_cross_void_where_walking_cannot():
    mp = mapmodel.default_map(8, 6)
    for y in range(6):
        if y != 3:
            for x in (1, 2, 3):
                mp["cells"][y * 8 + x] = 1                  # a true corridor
    mp["cells"][3 * 8 + 2] = mp["cells"][3 * 8 + 3] = 5     # void, free air but no floor

    assert P.step_legal(mp, (1, 3), (2, 3)) is False
    assert P.step_legal(mp, (1, 3), (2, 3), mode="fly") is True
    assert P.find_path(mp, (1, 3), (3, 3)) is None
    assert P.find_path(mp, (1, 3), (3, 3), mode="fly") == [(2, 3), (3, 3)]


def _make_flyer(ws, tok_id, fly=50):
    ws.send_json({"type": "update_npc", "token_id": tok_id,
                  "npc": {"speed": 30, "fly": fly}})
    recv_until(ws, "snapshot")


def _controller_id(client, player, code):
    return state_of(client, player, code)["me"]


def _activate(client, dm, code, tok):
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "init_start"})
        init = recv_until(ws, "initiative")["payload"]
        for _ in range(len(init["order"]) + 2):
            if (init.get("turn") or {}).get("token_id") == tok:
                return init
            ws.send_json({"type": "init_next"})
            init = recv_until(ws, "initiative")["payload"]
    raise AssertionError(f"token {tok} never became active: {init}")


def _add_token(client, dm, code, label, floor, cx, cy):
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "add_token", "label": label, "x": (cx + .5) * CELL,
                      "y": (cy + .5) * CELL, "size": "Medium", "floor": floor})
        return recv_until(ws, "token_add")["payload"]["id"]


def _open_column(client, dm, code, cx, cy):
    set_floor_grid(client, dm, code, "",
                   lambda g: g["openv"].__setitem__(cell_idx(g, cx, cy), 1))


def test_vertical_flight_costs_the_canonical_10ft_floor_step(client):
    dm, player, code, _ = base_room(client)
    pid = _controller_id(client, player, code)
    add_floor(client, dm, code, "Upper")
    with ws_connect(client, dm, code) as ws:
        flyer = add_npc(ws, "Dragon", cx=16, cy=12)
        ws.send_json({"type": "token_controller", "token_id": flyer, "controller_id": pid})
        recv_until(ws, "token_controller")
        _make_flyer(ws, flyer)
    _open_column(client, dm, code, 16, 12)
    _activate(client, dm, code, flyer)
    room_id = db.q1("SELECT room_id FROM tokens WHERE id=?", (flyer,))["room_id"]
    assert CB.move_remaining(CB.get_init(room_id), flyer, "fly") == 10

    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "move", "token_id": flyer, "tx": 16, "ty": 12,
                      "floor": "Upper", "mode": "fly"})
        for _ in range(12):
            ev = recv_until(ws, "move_state")
            if ev["payload"].get("moving") is False:
                break

    row = db.q1("SELECT * FROM tokens WHERE id=?", (flyer,))
    assert row["floor"] == "Upper"
    assert (int(row["x"] // CELL), int(row["y"] // CELL)) == (16, 12)
    assert CB.move_remaining(CB.get_init(room_id), flyer, "fly") == 8


def test_solid_ceiling_rejects_a_vertical_move(client):
    dm, player, code, _ = base_room(client)
    pid = _controller_id(client, player, code)
    add_floor(client, dm, code, "Upper")
    with ws_connect(client, dm, code) as ws:
        flyer = add_npc(ws, "Dragon", cx=16, cy=12)
        ws.send_json({"type": "token_controller", "token_id": flyer, "controller_id": pid})
        recv_until(ws, "token_controller")
        _make_flyer(ws, flyer)
    _activate(client, dm, code, flyer)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "move", "token_id": flyer, "tx": 16, "ty": 12,
                      "floor": "Upper", "mode": "fly"})
        err = recv_until(ws, "error", fail_on_error=False)
    assert err["kind"] == "error"
    assert "No vertical flight path" in err["payload"]["msg"]
    assert db.q1("SELECT floor FROM tokens WHERE id=?", (flyer,))["floor"] == ""


def test_body_volume_collision_blocks_the_target_plane(client):
    dm, player, code, _ = base_room(client)
    pid = _controller_id(client, player, code)
    add_floor(client, dm, code, "Upper")
    with ws_connect(client, dm, code) as ws:
        flyer = add_npc(ws, "Dragon", cx=16, cy=12)
        ws.send_json({"type": "token_controller", "token_id": flyer, "controller_id": pid})
        recv_until(ws, "token_controller")
        _make_flyer(ws, flyer)
    _add_token(client, dm, code, "Blocker", "Upper", 16, 12)
    _open_column(client, dm, code, 16, 12)
    _activate(client, dm, code, flyer)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "move", "token_id": flyer, "tx": 16, "ty": 12,
                      "floor": "Upper", "mode": "fly"})
        err = recv_until(ws, "error", fail_on_error=False)
    assert err["kind"] == "error"
    assert "No vertical flight path" in err["payload"]["msg"]
    assert db.q1("SELECT floor FROM tokens WHERE id=?", (flyer,))["floor"] == ""
