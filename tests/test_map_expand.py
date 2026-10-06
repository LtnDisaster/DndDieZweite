"""Automatic map growth (D67) under the world-coordinate invariant (D72):
chunked, deterministic, player-triggered — and NOTHING in world space moves.

Pure checks pin the geometry (terrain/fog/entities keep their WORLD coordinates
through every direction, corner and the cap); integration checks pin the
trigger semantics — a PLAYER token near an edge grows the world, hidden NPC
movement never does, players only see FOG in the new land, and the token's
stored pixel position is byte-identical across a west/north growth (the
reported teleport regression).
"""
import pytest
from starlette.testclient import TestClient

from app import mapmodel
from app.main import app

from tests.test_integration import H, join_room, make_char, recv_until, reg, state_of, ws_connect  # noqa: F401


@pytest.fixture(autouse=True)
def _reset_ratelimit():
    from app import ratelimit
    ratelimit._hits.clear()
    yield


@pytest.fixture(autouse=True)
def _enable_autogrow(monkeypatch):
    """The AUTO_GROW feature flag is OFF by default (D77) — these tests pin the
    growth MACHINERY itself, so they run with the flag explicitly enabled."""
    monkeypatch.setattr(mapmodel, "AUTO_GROW", True)
    yield


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def mark(mp):
    """Give every cell a detectable value so a mis-anchored re-layout is unmistakable."""
    mp["cells"] = [0] * (mp["w"] * mp["h"])
    mp["explored"] = [0] * (mp["w"] * mp["h"])
    for i in range(0, mp["w"] * mp["h"], 7):
        mp["cells"][i] = 1 if i % 3 == 0 else 2
    for i in range(1, mp["w"] * mp["h"], 11):
        mp["explored"][i] = 1


# ---------- pure geometry ----------

def test_growth_needed_per_edge_and_margin():
    mp = mapmodel.default_map(40, 26)
    m = mapmodel.FOG_R + mapmodel.GROW_MARGIN          # 11
    assert mapmodel.growth_needed(mp, (0, 13)) == ["west"]
    assert mapmodel.growth_needed(mp, (m, 13)) == ["west"]     # boundary counts
    assert mapmodel.growth_needed(mp, (m + 1, 13)) == []
    assert mapmodel.growth_needed(mp, (20, 0)) == ["north"]
    assert mapmodel.growth_needed(mp, (27, 13)) == []          # east fine for side 1
    assert mapmodel.growth_needed(mp, (27, 12)) == []          # fine north/south too
    assert mapmodel.growth_needed(mp, (38, 13)) == ["east"]
    assert mapmodel.growth_needed(mp, (20, 25)) == ["south"]


def test_growth_needed_is_world_space_after_origin_shift():
    """With a lowered origin the trigger follows WORLD cells, not array edges."""
    mp = mapmodel.default_map(40, 26)
    mp["origin"] = [-12, -12]                        # world spans [-12, 28) x [-12, 14)
    assert mapmodel.growth_needed(mp, (-12, 0)) == ["west"]
    assert mapmodel.growth_needed(mp, (-1, 0)) == ["west"]      # 1 cell from the edge
    assert mapmodel.growth_needed(mp, (0, 0)) == []             # local x=12 > margin 11
    assert mapmodel.growth_needed(mp, (27, 0)) == ["east"]      # x1 = -12+40 = 28
    assert mapmodel.growth_needed(mp, (0, 13)) == ["south"]     # y1 = -12+26 = 14


def test_growth_respects_token_footprint():
    mp = mapmodel.default_map(40, 26)
    # the footprint extends right/down: a wide token hits BOTH thresholds
    # where the same anchor as a Medium token hits neither
    assert mapmodel.growth_needed(mp, (27, 12), side=1) == []
    assert mapmodel.growth_needed(mp, (27, 12), side=3) == ["east", "south"]


def test_grow_map_keeps_every_world_coordinate_every_direction():
    """D72: growth moves the WINDOW (array + origin), never the world."""
    for dirs, expect in [(["west"], (12, 0)), (["north"], (0, 12)),
                         (["east"], (0, 0)), (["south"], (0, 0)),
                         (["west", "north"], (12, 12))]:
        mp = mapmodel.default_map(40, 26)
        mark(mp)
        mp["traps"] = [{"id": "t1", "x": 30, "y": 13, "dc": 12, "dmg": "1d4"}]
        mp["pins"] = [{"id": "p1", "x": 5, "y": 20}]
        old_cells, old_exp = list(mp["cells"]), list(mp["explored"])
        grown, (dx, dy) = mapmodel.grow_map(mp, dirs)
        assert (dx, dy) == expect, dirs
        w, h = grown["w"], grown["h"]
        assert len(grown["cells"]) == w * h == len(grown["explored"])
        assert grown["origin"] == [0 - dx, 0 - dy], dirs
        for oy in range(26):
            for ox in range(40):
                # THE invariant: terrain/fog at a WORLD cell never change
                assert mapmodel.terrain_at(grown, ox, oy) == old_cells[oy * 40 + ox], (dirs, ox, oy)
                assert mapmodel.explored_at(grown, ox, oy) == bool(old_exp[oy * 40 + ox]), (dirs, ox, oy)
        # entities keep their coordinates — they sit in the same WORLD cell
        assert grown["traps"][0]["x"] == 30 and grown["traps"][0]["y"] == 13
        assert grown["pins"][0]["x"] == 5 and grown["pins"][0]["y"] == 20
        # new land is fresh floor and unexplored — addressed in WORLD cells:
        if "west" in dirs or "north" in dirs:
            nx, ny = grown["origin"]
            assert mapmodel.terrain_at(grown, nx, ny) == 0
            assert not mapmodel.explored_at(grown, nx, ny)
        if "east" in dirs:
            assert mapmodel.terrain_at(grown, mp["w"], 5) == 0
        if "south" in dirs:
            assert mapmodel.terrain_at(grown, 5, mp["h"]) == 0


def test_repeated_growth_stays_consistent():
    mp = mapmodel.default_map(40, 26)
    mp["cells"][13 * 40 + 20] = 1
    for _ in range(3):
        mp, _ = mapmodel.grow_map(mp, ["west"])
    assert mp["w"] == 40 + 36 and mp["origin"][0] == -36
    assert mapmodel.terrain_at(mp, 20, 13) == 1                # wall still at (20,13)
    assert mapmodel.in_world(mp, -36, 0) and not mapmodel.in_world(mp, -37, 0)
    assert mapmodel.in_world(mp, 39, 25) and not mapmodel.in_world(mp, 40, 25)


def test_grow_map_clamps_at_documented_cap():
    mp = mapmodel.default_map(mapmodel.MAX_W, mapmodel.MAX_H)
    grown, shift = mapmodel.grow_map(mp, ["east", "south"])
    assert grown is None and shift == (0, 0)
    mp = mapmodel.default_map(mapmodel.MAX_W - 3, 26)
    grown, _ = mapmodel.grow_map(mp, ["east"])
    assert grown["w"] == mapmodel.MAX_W            # partial growth, capped
    grown2, _ = mapmodel.grow_map(grown, ["east"])
    assert grown2 is None                          # then stops for good


def test_grown_map_survives_sanitize():
    mp = mapmodel.default_map(40, 26)
    mark(mp)
    grown, _ = mapmodel.grow_map(mp, ["west", "north"])
    s = mapmodel.sanitize(grown)
    assert s is not None
    assert s["origin"] == [-12, -12]
    assert mapmodel.terrain_at(s, 20, 13) == mapmodel.terrain_at(mp, 20, 13)


# ---------- integration: trigger semantics ----------

def _dm_grid(client, dm, code):
    return state_of(client, dm, code)["grid"]


def _room_with_pc(client, tag):
    dm = reg(client, "dm")
    pl = reg(client, "pl")
    code = client.post("/api/rooms", json={"name": tag}, headers=H(dm)).json()["code"]
    join_room(client, pl, code)
    ch = make_char(client, pl)
    client.post(f"/api/rooms/{code}/assign", json={"character_id": ch["id"]}, headers=H(pl))
    st = state_of(client, pl, code)
    tok_id = next(t["id"] for t in st["tokens"] if t["owner_user_id"] == st["me"])
    return dm, pl, code, tok_id


def test_player_edge_move_grows_map_and_survives(client):
    from app import db
    dm, pl, code, tok_id = _room_with_pc(client, "Grow")

    # DM marks the world: wall + trap + pin + explored cell, all in WORLD cells
    with ws_connect(client, dm, code) as ws:
        mp = dict(_dm_grid(client, dm, code))
        mp["cells"][13 * mp["w"] + 30] = 1
        mp["traps"] = [{"id": "g1", "x": 30, "y": 13, "dc": 12, "dmg": "1d4", "label": "Rune"}]
        mp["pins"] = [{"id": "gp", "x": 33, "y": 13, "visibility": "players", "title": "X"}]
        ws.send_json({"type": "map_edit", "map": mp})
        recv_until(ws, "map_changed")
        ws.send_json({"type": "fog_edit", "cells": [{"x": 30, "y": 13, "explored": 1}]})
        recv_until(ws, "fog_changed")

        before = _dm_grid(client, dm, code)
        ws.send_json({"type": "move", "token_id": tok_id, "tx": 1, "ty": 13, "teleport": True})
        ev = recv_until(ws, "map_expanded")["payload"]
        assert ev["origin"] == [before["origin"][0] - 12, 0] and ev["w"] == before["w"] + 12

    after = _dm_grid(client, dm, code)
    assert after["w"] == before["w"] + 12 and after["h"] == before["h"]
    # THE regression pin: nothing in world space moved
    assert mapmodel.terrain_at(after, 30, 13) == 1             # wall still at (30,13)
    assert mapmodel.terrain_at(after, 1, 13) == 0              # new land = floor
    assert after["traps"][0]["x"] == 30 and after["traps"][0]["y"] == 13
    assert after["pins"][0]["x"] == 33
    assert mapmodel.explored_at(after, 30, 13)                 # fog memory holds WORLD cell
    # persisted: a fresh /state (fresh DB read) shows the grown map
    assert _dm_grid(client, dm, code)["w"] == before["w"] + 12

    # PLAYER view: new columns are FOG (None cells), never live geometry
    pst = state_of(client, pl, code)["grid"]
    ox = pst["origin"][0]
    assert pst["w"] == before["w"] + 12
    assert pst["origin"] == [ox, 0]
    assert all(pst["cells"][13 * pst["w"] + (wx - ox)] is None for wx in range(ox, ox + 6))

    # token DID NOT travel with the world — world coordinates never move
    tok = db.q1("SELECT x, y FROM tokens WHERE id=?", (tok_id,))
    assert tok["x"] == (1 + 0.5) * after["cell"]
    assert tok["y"] == (13 + 0.5) * after["cell"]


def test_all_four_edges_and_corner(client):
    for tx, ty, ew, eh in [(38, 13, 52, 26), (20, 2, 40, 38),
                           (20, 24, 40, 38), (1, 1, 52, 38)]:
        dm, pl, code, tok_id = _room_with_pc(client, "Edge")
        with ws_connect(client, dm, code) as ws:
            ws.send_json({"type": "move", "token_id": tok_id, "tx": tx, "ty": ty,
                          "teleport": True})
            recv_until(ws, "map_expanded")
        g = _dm_grid(client, dm, code)
        assert (g["w"], g["h"]) == (ew, eh), (tx, ty, g["w"], g["h"])


def test_npc_movement_never_grows_the_world(client):
    dm = reg(client, "dm")
    code = client.post("/api/rooms", json={"name": "NoGrow"}, headers=H(dm)).json()["code"]
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "add_token", "label": "Scout", "x": 500, "y": 500})
        npc_id = recv_until(ws, "token_add")["payload"]["id"]
        before = _dm_grid(client, dm, code)
        # Teleport the monster hard into the west edge — nothing may grow.
        # The ping proves the server finished processing the move; a growth
        # would already have streamed map_expanded before it.
        ws.send_json({"type": "move", "token_id": npc_id, "tx": 0, "ty": 5, "teleport": True})
        ws.send_json({"type": "ping", "x": 1, "y": 1})
        recv_until(ws, "ping")
    assert _dm_grid(client, dm, code)["w"] == before["w"]


def test_token_pixels_and_route_are_untouched_by_west_growth(client):
    """The user-visible bug class: walking WEST used to renumber the world
    underneath the token (teleport / double-shift). Now: after the growth the
    token's stored pixel is EXACTLY the walked destination, and the world cell
    under it is where the player asked."""
    from app import db
    dm, pl, code, tok_id = _room_with_pc(client, "WalkWest")
    with ws_connect(client, dm, code) as ws:
        # park safely, then WALK (not teleport) toward the west edge
        ws.send_json({"type": "move", "token_id": tok_id, "tx": 16, "ty": 12, "teleport": True})
        recv_until(ws, "step")
        ws.send_json({"type": "move", "token_id": tok_id, "tx": 5, "ty": 12})
        # map_expanded is the LAST event of the walk (announced after arrival),
        # so receiving it proves the whole route committed without a shift.
        recv_until(ws, "map_expanded", tries=80)
    tok = db.q1("SELECT x, y FROM tokens WHERE id=?", (tok_id,))
    assert (tok["x"], tok["y"]) == ((5 + .5) * 50, (12 + .5) * 50)   # exact, no drift
    g = _dm_grid(client, dm, code)
    assert g["origin"][0] == -12 and g["w"] == 52
    assert mapmodel.terrain_at(g, 5, 12) == 0                        # stands on fresh floor


def test_reconnect_after_growth_sees_the_same_world(client):
    """A client that reconnects AFTER a growth must not observe a second,
    shifted world: origin, token pixels and explored memory all speak WORLD."""
    from app import db
    dm, pl, code, tok_id = _room_with_pc(client, "Reconnect")
    with ws_connect(client, dm, code) as ws:
        mp = dict(_dm_grid(client, dm, code))
        mp["cells"][13 * mp["w"] + 39] = 1                       # wall near east edge
        ws.send_json({"type": "map_edit", "map": mp})
        recv_until(ws, "map_changed")
        ws.send_json({"type": "move", "token_id": tok_id, "tx": 38, "ty": 13, "teleport": True})
        recv_until(ws, "map_expanded")
    grown = _dm_grid(client, dm, code)
    assert mapmodel.terrain_at(grown, 39, 13) == 1               # wall stayed in the world
    tok_px = db.q1("SELECT x, y FROM tokens WHERE id=?", (tok_id,))
    # a reconnecting client refetches /state (what refreshRoom() does on join) —
    # that fresh read must show the SAME world, not a renumbered second one
    snap = state_of(client, pl, code)
    g = snap["grid"]
    assert g["w"] == grown["w"] and g["h"] == grown["h"]
    assert g["origin"] == grown["origin"]
    tok = next(t for t in snap["tokens"] if t["id"] == tok_id)
    assert (tok["x"], tok["y"]) == (tok_px["x"], tok_px["y"])    # no renumbering on join
    ox = g["origin"][0]
    # explored memory follows the WORLD cell the player already saw: the area
    # around the token is visible in the player grid after reconnecting
    assert g["cells"][13 * g["w"] + (38 - ox)] is not None

