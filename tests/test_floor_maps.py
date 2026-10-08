"""D88 — independent floor maps (P1).

One room, one world frame, per-plane CONTENT: terrain, walls, doors, traps,
objects, fog memory and light all live in the PLANE'S OWN map. The primary
floor keeps reading the legacy room_state.map_json byte-for-byte. Transitions
run through validated connectors (the D82 allowlisted `stair` op) — viewing a
floor never teleports anyone, and an occupied or walled destination is refused
outright.
"""
import pytest
from starlette.testclient import TestClient

from app import db, mapmodel
from app.room import net as room_net
from tests.test_movement_fog import (H, base_room, join_room, recv_until, reg,
                                     state_of, ws_connect)

CELL = 50


@pytest.fixture()
def client():
    return TestClient(main_app())


def main_app():
    from app import main
    return main.app


def state_floor(client, user, code, floor=""):
    url = f"/api/rooms/{code}/state" + (f"?floor={floor}" if floor else "")
    r = client.get(url, headers=H(user))
    assert r.status_code == 200, r.text
    return r.json()


def add_floor(client, dm, code, name):
    r = client.post(f"/api/rooms/{code}/floors", json={"name": name}, headers=H(dm))
    assert r.status_code == 200, r.text


def set_floor_grid(client, dm, code, floor, mutate):
    grid = state_floor(client, dm, code, floor)["grid"]
    mutate(grid)
    with ws_connect(client, dm, code) as ws:
        msg = {"type": "map_edit", "map": grid}
        if floor:
            msg["floor"] = floor
        ws.send_json(msg)
        recv_until(ws, "map_changed")


def wall_row(grid, y):
    for x in range(grid["w"]):
        grid["cells"][y * grid["w"] + x] = 1


def cell_idx(grid, x, y):
    ox, oy = grid.get("origin") or [0, 0]
    return (y - oy) * grid["w"] + (x - ox)


# ---------- isolation & persistence ----------

def test_edits_are_plane_local_and_persist(client):
    dm, player, code, _ = base_room(client)
    add_floor(client, dm, code, "crypt")
    set_floor_grid(client, dm, code, "crypt", lambda g: wall_row(g, 6))
    # the crypt wall exists ONLY on crypt ...
    g_crypt = state_floor(client, dm, code, "crypt")["grid"]
    assert g_crypt["cells"][cell_idx(g_crypt, 4, 6)] == 1
    g_base = state_of(client, dm, code)["grid"]
    assert g_base["cells"][cell_idx(g_base, 4, 6)] == 0
    # ... and a player's snapshot NEVER carries it: their grid is their plane
    g_pl = state_of(client, player, code)["grid"]
    assert g_pl["cells"][cell_idx(g_pl, 4, 6)] == 0
    # primary edits cannot touch the crypt wall (separate rows in the DB)
    set_floor_grid(client, dm, code, "", lambda g: wall_row(g, 6))
    g_crypt = state_floor(client, dm, code, "crypt")["grid"]
    assert g_crypt["cells"][cell_idx(g_crypt, 4, 3)] == 0     # untouched row 3
    g_base = state_of(client, dm, code)["grid"]
    assert g_base["cells"][cell_idx(g_base, 4, 6)] == 1
    # persistence is the floor_maps table (not the legacy blob)
    rid = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
    assert db.q1("SELECT map_json FROM floor_maps WHERE room_id=? AND floor='crypt'",
                 (rid,)) is not None
    assert db.q1("SELECT map_json FROM room_state WHERE room_id=?", (rid,))["map_json"]


# ---------- collision & pathfinding on the right plane ----------

def test_walls_and_stairs_obey_the_plane_map(client):
    dm, player, code, _ = base_room(client)
    add_floor(client, dm, code, "crypt")
    mine = [t for t in state_of(client, player, code)["tokens"]
            if t.get("owner_user_id") is not None][0]
    cx, cy = int(mine["x"] // CELL), int(mine["y"] // CELL)
    # The crypt is SEALED along the very row the token stands on: the same
    # cell that is free air on primary is solid rock one plane down.
    set_floor_grid(client, dm, code, "crypt", lambda g: wall_row(g, cy))
    with ws_connect(client, player, code) as wsp:
        # walkable on primary (the wall exists only crypt-side) ...
        wsp.send_json({"type": "path_preview", "token_id": mine["id"],
                       "tx": cx, "ty": cy + 3})
        prev = recv_until(wsp, "path_preview")["payload"]
        assert prev.get("path"), "open primary must yield a route"
        # ... stepping DOWN into rock is refused by the target plane's terrain
        wsp.send_json({"type": "token_floor", "token_id": mine["id"], "floor": "crypt"})
        err = recv_until(wsp, "error", fail_on_error=False)
        assert err["kind"] == "error" and "room" in err["payload"]["msg"].lower()
    assert db.q1("SELECT floor FROM tokens WHERE id=?", (mine["id"],))["floor"] == ""
    # DM opens the seam (plane-local edit only), and the same step now works
    set_floor_grid(client, dm, code, "crypt",
                   lambda g: [g["cells"].__setitem__(cell_idx(g, x, cy), 0)
                              for x in range(g["w"])])
    with ws_connect(client, player, code) as wsp:
        wsp.send_json({"type": "token_floor", "token_id": mine["id"], "floor": "crypt"})
        ev = wsp.receive_json()
        while ev.get("kind") not in ("token_floor", "error"):
            ev = wsp.receive_json()
        assert ev["kind"] == "token_floor", ev
    assert db.q1("SELECT floor FROM tokens WHERE id=?", (mine["id"],))["floor"] == "crypt"
    # primary is UNTOUCHED by every crypt edit above
    g_base = state_of(client, dm, code)["grid"]
    assert all(g_base["cells"][cell_idx(g_base, x, cy)] == 0 for x in range(6))


# ---------- fog memory is per-plane ----------

def test_explored_memory_is_per_plane(client):
    dm, player, code, _ = base_room(client)
    add_floor(client, dm, code, "crypt")
    # far corner: outside the spawn's line of sight on BOTH planes
    X, Y = 36, 22
    g_base = state_of(client, dm, code)["grid"]
    assert g_base["explored"][cell_idx(g_base, X, Y)] == 0   # untouched plane
    with ws_connect(client, dm, code) as wsd:
        wsd.send_json({"type": "fog_edit", "floor": "crypt", "cells": [
            {"x": X, "y": Y, "explored": 1}]})
    g_crypt = state_floor(client, dm, code, "crypt")["grid"]
    g_base = state_of(client, dm, code)["grid"]
    assert g_crypt["explored"][cell_idx(g_crypt, X, Y)] == 1
    assert g_base["explored"][cell_idx(g_base, X, Y)] == 0   # STILL untouched


# ---------- the stair connector ----------

def _place_stairs(client, dm, code, on_floor, obj_id, x, y, to_floor, tx, ty):
    def mutate(g):
        g["objects"] = (g.get("objects") or []) + [{
            "id": obj_id, "label": "Cellar stair", "x": x, "y": y,
            "interact": {"op": {"kind": "stair", "floor": to_floor, "x": tx, "y": ty}}}]
    set_floor_grid(client, dm, code, on_floor, mutate)


def test_stair_moves_to_a_validated_destination(client):
    dm, player, code, _ = base_room(client)
    add_floor(client, dm, code, "crypt")
    mine = [t for t in state_of(client, player, code)["tokens"]
            if t.get("owner_user_id") is not None][0]
    cx, cy = int(mine["x"] // CELL), int(mine["y"] // CELL)
    _place_stairs(client, dm, code, "", "st1", cx + 1, cy, "crypt", cx + 4, cy)
    with ws_connect(client, player, code) as wsp:
        wsp.send_json({"type": "interact", "object_id": "st1", "floor": ""})
        # arrives on the crypt at the connector's destination
        ev = wsp.receive_json()
        while ev.get("kind") not in ("token_floor", "error"):
            ev = wsp.receive_json()
        assert ev["kind"] == "token_floor", ev
        assert ev["payload"]["floor"] == "crypt"
    row = db.q1("SELECT floor, x, y FROM tokens WHERE id=?", (mine["id"],))
    assert row["floor"] == "crypt"
    assert (int(row["x"] // CELL), int(row["y"] // CELL)) == (cx + 4, cy)
    # the DM saw the whole story on the right planes
    with ws_connect(client, dm, code) as wsd:
        wsd.send_json({"type": "interact", "object_id": "st1", "floor": "crypt",
                       "token_id": mine["id"]})       # and back via crypt stair?
        # (no stair on crypt — dangling nothing-happens path below covers it)


def test_stair_refuses_occupied_and_foreign_planes(client):
    dm, player, code, _ = base_room(client)
    add_floor(client, dm, code, "crypt")
    add_floor(client, dm, code, "attic")
    mine = [t for t in state_of(client, player, code)["tokens"]
            if t.get("owner_user_id") is not None][0]
    cx, cy = int(mine["x"] // CELL), int(mine["y"] // CELL)
    _place_stairs(client, dm, code, "", "st2", cx + 1, cy, "crypt", cx + 4, cy)
    # stage an occupant on the crypt destination (plane-local placement)
    with ws_connect(client, dm, code) as wsd:
        wsd.send_json({"type": "add_token", "label": "Ghoul",
                       "x": (cx + 4.5) * CELL, "y": (cy + .5) * CELL,
                       "size": "Medium", "floor": "crypt"})
        while True:
            e = wsd.receive_json()
            if e.get("kind") == "token_add" and (e.get("payload") or {}).get("label") == "Ghoul":
                ghoul = e["payload"]["id"]
                break
    with ws_connect(client, player, code) as wsp:
        wsp.send_json({"type": "interact", "object_id": "st2", "floor": ""})
        err = recv_until(wsp, "error", fail_on_error=False)
        assert err["kind"] == "error" and "no room" in err["payload"]["msg"].lower()
        assert db.q1("SELECT floor FROM tokens WHERE id=?", (mine["id"],))["floor"] == ""
        # a wrong-plane claim answers like nothing being there (no leak, no move)
        wsp.send_json({"type": "interact", "object_id": "st2", "floor": "attic"})
        wsp.send_json({"type": "roll", "expr": "1d4"})
        kinds = []
        while (e := wsp.receive_json()).get("kind") != "dice":
            kinds.append(e.get("kind"))
        assert "token_floor" not in kinds and "error" not in kinds
    # the crypt ghoul never appears in a primary-plane snapshot
    ids = {t["id"] for t in state_of(client, player, code)["tokens"]}
    assert ghoul not in ids


# ---------- authorization & view semantics ----------

def test_players_cannot_edit_or_read_foreign_planes(client):
    dm, player, code, _ = base_room(client)
    add_floor(client, dm, code, "crypt")
    grid = state_of(client, dm, code)["grid"]
    with ws_connect(client, player, code) as wsp:
        wsp.send_json({"type": "map_edit", "map": grid, "floor": "crypt"})
        assert recv_until(wsp, "error", fail_on_error=False)["payload"]["msg"] == "DM only"
        wsp.send_json({"type": "fog_edit", "floor": "crypt",
                       "cells": [{"x": 2, "y": 2, "explored": 1}]})
    # a player's ?floor= parameter is NOT honoured (no error, just their plane)
    st = client.get(f"/api/rooms/{code}/state?floor=crypt", headers=H(player)).json()
    assert st["view_floor"] == ""
    # DM browsing a plane does not move anything
    before = {t["id"]: (t["x"], t["y"], t.get("floor") or "")
              for t in state_of(client, dm, code)["tokens"]}
    st2 = client.get(f"/api/rooms/{code}/state?floor=crypt", headers=H(dm)).json()
    assert st2["view_floor"] == "crypt"
    after = {t["id"]: (t["x"], t["y"], t.get("floor") or "")
             for t in state_of(client, dm, code)["tokens"]}
    assert before == after
    # unknown floor: never an oracle, primary answers
    st3 = client.get(f"/api/rooms/{code}/state?floor=nowhere", headers=H(dm)).json()
    assert st3["view_floor"] == ""
    with ws_connect(client, dm, code) as wsd:
        wsd.send_json({"type": "map_edit", "map": grid, "floor": "nowhere"})
        assert "No such floor" in recv_until(wsd, "error")["payload"]["msg"]
