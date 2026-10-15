"""D114 (Sprint 43) Phase 4: vertical openings vs solid ceilings (`openv`).

`openv` is a per-plane, per-cell bit: 1 = an opening in the ceiling ABOVE that
cell, joining this plane to the one declared one level higher. DEFAULT 0 = solid.
This is the gate that decides when a token's vertical body may reach another
plane and when a shaft lets sight through — never before it. Fail-closed: an
old map with no `openv` layer keeps planes fully independent. A wide body only
occupies a plane when its WHOLE footprint fits an open column there; a single
open cell never admits a massive creature.
"""
import pytest
from starlette.testclient import TestClient

from app import db, floors, footprint, mapmodel, vertical
from app import main
from app.room import vertical3d
from app.room.net import get_map
from tests.test_movement_fog import base_room, state_of, ws_connect, recv_until, set_grid, park, H


@pytest.fixture()
def client():
    return TestClient(main.app)


def rid(client, code):
    return db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]


def add_floor(client, dm, code, name):
    r = client.post(f"/api/rooms/{code}/floors", json={"name": name}, headers=H(dm))
    assert r.status_code == 200, r.text
    return r.json()


def ptoken(client, player, code):
    st = state_of(client, player, code)
    return next(t["id"] for t in st["tokens"] if t.get("owner_user_id") == st["me"])


def token_row(client, code, tok):
    return db.q1("SELECT * FROM tokens WHERE id=?", (tok,))


# --------------------------------------------------------------------------- #
# 1. sanitize round-trip and the default-solid invariant (pure mapmodel)
# --------------------------------------------------------------------------- #

def test_openv_defaults_solid_and_roundtrips():
    base = mapmodel.sanitize({"w": 8, "h": 6, "cell": 50, "cells": [0] * 48})
    assert base["openv"] == [0] * 48                          # a map without openv is solid everywhere
    painted = {**base, "openv": [1] * 48}
    assert mapmodel.sanitize(painted)["openv"] == [1] * 48     # a real layer round-trips
    # a wrong-length or junk layer can NEVER leave openings behind — fail-closed
    assert mapmodel.sanitize({**base, "openv": [1] * 5})["openv"] == [0] * 48
    assert mapmodel.sanitize({**base, "openv": "nope"})["openv"] == [0] * 48
    assert mapmodel.openv_at(base, 0, 0) == 0


# --------------------------------------------------------------------------- #
# 2. a tall body reaches an upper plane ONLY through a full-footprint opening
# --------------------------------------------------------------------------- #

def _owner_set_height(client, player, code, tok, **f):
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "token_height", "token_id": tok, **f})
        recv_until(ws, "token_height")


def _owner_set_span(client, player, code, tok, w, h):
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "token_span", "token_id": tok, "width": w, "height": h})
        recv_until(ws, "token_span")


def test_tall_body_protrudes_only_through_a_matching_opening(client):
    dm, player, code, ch = base_room(client)
    tok = ptoken(client, player, code)
    park(client, dm, code, tok, 16, 12)
    tok = ptoken(client, player, code)
    add_floor(client, dm, code, "Upper")
    _owner_set_span(client, player, code, tok, 2, 2)          # a 2x2 wide body
    _owner_set_height(client, player, code, tok, height_ft=30)  # reaches levels 0..2 by height
    tok = token_row(client, code, tok)
    r = rid(client, code)
    home = get_map(r, "")
    foot = sorted(footprint.occupied_cells(home, tok))         # 2x2 world cells

    maps = vertical3d.maps_for(r); lm = vertical3d.level_map(r)
    # (a) solid ceiling everywhere → the body NEVER reaches Upper (fail-closed)
    assert vertical3d.body_planes(r, tok, maps, lm) == {""}

    # (b) only ONE of the four cells open → still blocked (a hole must fit the whole body)
    def one_cell(grid):
        for k, (x, y) in enumerate(foot):
            grid["openv"][y * grid["w"] + x] = 1 if k == 0 else 0
    set_grid(client, dm, code, one_cell)
    maps = vertical3d.maps_for(r)
    assert "Upper" not in vertical3d.body_planes(r, tok, maps, lm)

    # (c) the whole footprint open → the body now reaches Upper
    def all_cells(grid):
        for (x, y) in foot:
            grid["openv"][y * grid["w"] + x] = 1
    set_grid(client, dm, code, all_cells)
    maps = vertical3d.maps_for(r)
    assert "Upper" in vertical3d.body_planes(r, tok, maps, lm)
    assert foot[0] in [(x, y) for (x, y) in
                       footprint.occupied_cells(maps["Upper"], {**tok, "floor": "Upper"})]


# --------------------------------------------------------------------------- #
# 3. straight-shaft sight only where the column is open; closed floor blocks it
# --------------------------------------------------------------------------- #

def test_cross_plane_sight_needs_an_open_column(client):
    dm, player, code, ch = base_room(client)
    r = rid(client, code)
    add_floor(client, dm, code, "Upper")
    maps = vertical3d.maps_for(r); lm = vertical3d.level_map(r)
    assert vertical3d.cross_plane_sight(maps, lm, "", "Upper", (5, 5)) is False   # solid floor blocks the view
    set_grid(client, dm, code, lambda g: g.__setitem__("openv",
              [1 if (i % g["w"], i // g["w"]) == (5, 5) else 0 for i in range(g["w"] * g["h"])]))
    maps = vertical3d.maps_for(r)
    assert vertical3d.cross_plane_sight(maps, lm, "", "Upper", (5, 5)) is True    # open shaft → you can look down
    assert vertical3d.cross_plane_sight(maps, lm, "", "Upper", (6, 6)) is False   # next tile is still solid
    assert vertical3d.cross_plane_sight(maps, lm, "", "", (5, 5)) is False        # same plane is 2D LOS, not this


# --------------------------------------------------------------------------- #
# 4. a hidden opening leaks nothing through fog (player grid masks openv)
# --------------------------------------------------------------------------- #

def test_openv_is_fog_masked_for_players(client):
    dm, player, code, ch = base_room(client)
    pg = state_of(client, player, code)["grid"]
    idx = next(i for i, e in enumerate(pg["explored"]) if not e)   # a cell behind fog
    set_grid(client, dm, code, lambda g: g["openv"].__setitem__(idx, 1))
    # the DM sees the opening they painted...
    assert state_of(client, dm, code)["grid"]["openv"][idx] == 1
    # ...but an unexplored player grid masks that opening to 0 (never reveals a shaft)
    assert state_of(client, player, code)["grid"]["openv"][idx] == 0
