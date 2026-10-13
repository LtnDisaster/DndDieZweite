"""D103 — editor floor/void integrity and the reliable PNG asset path.

Two shipped-but-broken surfaces, fixed at their real causes:

* PNG artwork: tokens.image canonically stores "/assets/<id>" and the canvas
  loads that url verbatim — but only /api/assets/<id> was ever routed, so every
  real browser 404'd the image (and blacklisted it in the client cache).
  D103 routes the canonical url to the SAME handler: same auth, same
  no-oracle 404, same PNG semantics.
* "no floor": the terrain registry had no impassable-but-visible state — the
  floor brush painted invisible 0, the eraser painted 0, and a floor-less
  cell simply did not exist. Registry entry 5 (void) is the minimal state:
  everything that already asks the registry (path, LOS, placement, collision)
  refuses it automatically; old maps never store a 5.
"""
import io
import json
import os

import pytest
from PIL import Image
from starlette.testclient import TestClient

from app import db, main, mapmodel
from tests.test_movement_fog import (H, add_npc, base_room, park, recv_until,
                                     reg, set_grid, state_of, ws_connect)

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


@pytest.fixture()
def client():
    return TestClient(main.app)


def room_id(code):
    return db.q1("SELECT id FROM rooms WHERE id=(SELECT id FROM rooms WHERE code=?)",
                 (code.upper(),))["id"]


def primary_json(code) -> dict:
    return json.loads(db.q1("SELECT map_json FROM room_state WHERE room_id=?",
                            (room_id(code),))["map_json"])


def pc_token(code, ch):
    return db.q1("SELECT * FROM tokens WHERE room_id=? AND character_id=?",
                 (room_id(code), ch["id"]))


def cell_idx(g, x, y):
    ox, oy = g.get("origin") or [0, 0]
    return (y - oy) * g["w"] + (x - ox)


def void_column(grid, x):
    for y in range(grid["h"]):
        grid["cells"][y * grid["w"] + x] = 5


def add_floor(client, dm, code, name):
    assert client.post(f"/api/rooms/{code}/floors", json={"name": name},
                       headers=H(dm)).status_code == 200


def state_floor(client, user, code, floor=""):
    url = f"/api/rooms/{code}/state" + (f"?floor={floor}" if floor else "")
    r = client.get(url, headers=H(user))
    assert r.status_code == 200, r.text
    return r.json()


def set_floor_grid(client, dm, code, floor, mutate):
    grid = state_floor(client, dm, code, floor)["grid"]
    mutate(grid)
    with ws_connect(client, dm, code) as ws:
        msg = {"type": "map_edit", "map": grid}
        if floor:
            msg["floor"] = floor
        ws.send_json(msg)
        recv_until(ws, "map_changed")


def _png(w=48, h=64):
    b = io.BytesIO()
    Image.new("RGBA", (w, h), (30, 200, 90, 255)).save(b, "PNG")
    return b.getvalue()


def _put(client, user, blob, name="token"):
    return client.put(f"/api/assets?name={name}", content=blob, headers=H(user))


def _static(*parts):
    with open(os.path.join(main.STATIC_DIR, *parts), encoding="utf-8") as f:
        return f.read()


def _mini_map(cells, **kw):
    w, h = kw.pop("w", 8), kw.pop("h", 6)
    d = {"w": w, "h": h, "cell": 50, "origin": [0, 0], "cells": cells}
    d.update(kw)
    return d


# ---------- A: the void state integrates with the ONE movement engine ----------

def test_void_blocks_movement_not_vision_and_refuses_occupancy(client):
    dm, player, code, ch = base_room(client)
    with ws_connect(client, dm, code) as wsd:
        npc = add_npc(wsd, "Watchspirit", cx=14, cy=13)          # placed BEFORE
    ptok = pc_token(code, ch)
    set_grid(client, dm, code, lambda g: void_column(g, 10))     # a pit, full column
    mp = primary_json(code)
    assert mp["cells"][cell_idx(mp, 10, 13)] == 5                # stored truth
    park(client, dm, code, ptok["id"], tx=9, ty=13)              # west of the pit
    s = state_of(client, player, code)
    # vision passes over the hole (the same geometry with a WALL keeps the NPC
    # hidden — the wall precedent lives in test_movement_fog/test_floors):
    assert any(t["id"] == npc for t in s["tokens"]), "void must not block sight"
    assert s["grid"]["explored"][cell_idx(s["grid"], 12, 13)] == 1, \
        "player light must reach THROUGH the void"
    # movement refuses it: a straight route across the pit has no path
    with ws_connect(client, dm, code) as wsd:
        wsd.send_json({"type": "path_preview", "token_id": npc, "tx": 5, "ty": 13})
        err = recv_until(wsd, "error", fail_on_error=False)
        assert err["kind"] == "error" and "path" in err["payload"]["msg"].lower()
        # teleport (forced destination) is refused by the same registry rule
        wsd.send_json({"type": "move", "token_id": npc, "tx": 10, "ty": 13,
                       "teleport": True})
        err = recv_until(wsd, "error", fail_on_error=False)
        assert err["kind"] == "error" and "teleport" in err["payload"]["msg"].lower()
    row = db.q1("SELECT x FROM tokens WHERE id=?", (npc,))
    assert int(row["x"] // 50) != 10                             # never inside
    # token placement spirals around the pit — it never lands on a void cell
    with ws_connect(client, dm, code) as wsd:
        wsd.send_json({"type": "add_token", "label": "Dropper", "x": 10.5 * 50,
                       "y": 13.5 * 50, "size": "Medium"})
        tok = recv_until(wsd, "token_add")["payload"]
    mp = primary_json(code)
    assert mp["cells"][cell_idx(mp, int(tok["x"] // 50), int(tok["y"] // 50))] != 5, \
        "valid_terrain_position must refuse void"


def test_walls_doors_traps_survive_floor_and_paint_edits(client):
    dm, player, code, _ = base_room(client)

    def stage(g):
        g["cells"][cell_idx(g, 20, 20)] = 1                      # a far wall
        g["doors"] = [{"id": "d1", "x": 4, "y": 6, "dir": "v"}]   # edge to (5,6)
        g["traps"] = [{"id": "t1", "x": 6, "y": 8, "label": "Plate",
                       "dc": 12, "dmg": "1d4", "discovered": False}]
    set_grid(client, dm, code, stage)
    # paint void on the door's cell, floor on the trap's cell — cells are cells;
    # the entities are separate data and MUST be untouched
    def paint(g):
        g["cells"][cell_idx(g, 4, 6)] = 5
        g["cells"][cell_idx(g, 6, 8)] = 0
    set_grid(client, dm, code, paint)
    g = state_of(client, dm, code)["grid"]
    assert g["cells"][cell_idx(g, 4, 6)] == 5
    assert g["cells"][cell_idx(g, 6, 8)] == 0
    assert g["cells"][cell_idx(g, 20, 20)] == 1, "a paint stroke touched a wall cell"
    assert any(d["id"] == "d1" for d in g["doors"]), "paint removed the door"
    assert any(t["id"] == "t1" for t in g["traps"]), "paint removed the trap"


# ---------- B: floors stay isolated — void lives on ITS plane only ----------

def test_void_and_floor_edits_are_plane_local(client):
    dm, player, code, ch = base_room(client)
    add_floor(client, dm, code, "crypt")
    set_floor_grid(client, dm, code, "crypt", lambda g: void_column(g, 10))
    g_crypt = state_floor(client, dm, code, "crypt")["grid"]
    assert g_crypt["cells"][cell_idx(g_crypt, 10, 6)] == 5
    g_base = state_of(client, dm, code)["grid"]
    assert all(g_base["cells"][cell_idx(g_base, 10, y)] == 0 for y in (6, 13)), \
        "the pit leaked from the crypt into the primary plane"
    tok = pc_token(code, ch)
    with ws_connect(client, dm, code) as wsd:
        wsd.send_json({"type": "token_floor", "token_id": tok["id"], "floor": "crypt"})
        recv_until(wsd, "token_floor")
        wsd.send_json({"type": "path_preview", "token_id": tok["id"],
                       "tx": 10, "ty": 6})
        err = recv_until(wsd, "error", fail_on_error=False)
        assert err["kind"] == "error", "walking into the crypt pit must have no route"
    # the SAME room, PRIMARY plane: nothing was ever painted there — even after
    # a reload-equivalent fresh /state the two planes differ in the raw DB truth:
    assert primary_json(code)["cells"][cell_idx(primary_json(code), 10, 6)] == 0
    fm = db.q1("SELECT map_json FROM floor_maps WHERE room_id=? AND floor='crypt'",
               (room_id(code),))["map_json"]
    assert json.loads(fm)["cells"][cell_idx(g_crypt, 10, 6)] == 5


# ---------- C: sanitize & legacy compatibility ----------

def test_registry_and_sanitize_semantics():
    assert mapmodel.TERRAIN_MAX == 5
    assert mapmodel.walkable(5) is False
    assert mapmodel.blocks_movement(5) is True
    assert mapmodel.blocks_vision(5) is False
    assert mapmodel.terrain(None)["name"] == "floor", "fog default unchanged"
    mp = mapmodel.sanitize(_mini_map([0] * 47 + [5]))
    assert mp is not None and mp["cells"][47] == 5
    mp = mapmodel.sanitize(_mini_map([6] * 48))                   # clamp, not reject
    assert mp["cells"] == [5] * 48
    assert mapmodel.sanitize(_mini_map([0] * 47 + [None])) is None, \
        "a map carrying fog nulls stays rejected (the editor must send numbers)"
    legacy = _mini_map([i % 5 for i in range(48)])                # all pre-D103 values
    mp = mapmodel.sanitize(legacy)
    assert mp["cells"] == legacy["cells"], "legacy terrain must survive untouched"
    assert mapmodel.load(json.dumps(mp))["cells"] == legacy["cells"]


# ---------- D: authority ----------

def test_players_cannot_paint_void_or_edit_any_map(client):
    dm, player, code, _ = base_room(client)
    grid = state_of(client, dm, code)["grid"]
    grid["cells"][0] = 5
    with ws_connect(client, player, code) as wsp:
        wsp.send_json({"type": "map_edit", "map": grid})
        assert "DM only" in recv_until(wsp, "error")["payload"]["msg"]
    assert primary_json(code)["cells"][0] == 0                    # refused = saved nothing


# ---------- E: PNG assets — the canonical url finally serves, auth intact ----------

def test_canonical_asset_url_serves_in_the_browser_path(client):
    # functional contract, not a route-table scan: FastAPI >=0.142 defers
    # include_router into opaque _IncludedRouter wrappers, so scanning
    # app.routes is version-dependent — what must hold is that BOTH urls
    # serve, identically and auth-gated, which the requests below prove.
    u = reg(client, "art")
    r = _put(client, u, _png(24, 24), "banner")
    assert r.status_code == 200
    aid = r.json()["id"]
    for url in (f"/assets/{aid}", f"/api/assets/{aid}"):
        got = client.get(url, headers=H(u))
        assert got.status_code == 200, url
        assert got.headers["content-type"].startswith("image/png")
        assert got.headers.get("x-content-type-options") == "nosniff"
        assert got.content[:8] == PNG_MAGIC                       # the CLEAN re-encode
    stranger = reg(client, "strg")
    for url in (f"/assets/{aid}", f"/api/assets/{aid}"):
        assert client.get(url, headers=H(stranger)).status_code == 404
    for junk in ("deadbeefDEADBEEF", "not-an-id", "aid.png", "de"):
        assert client.get(f"/assets/{junk}", headers=H(u)).status_code == 404


def test_assigned_artwork_roundtrips_over_the_canonical_url(client):
    dm, player, code, ch = base_room(client)
    r = _put(client, player, _png(32, 40), "hero")
    aid = r.json()["id"]
    tok = pc_token(code, ch)
    with ws_connect(client, player, code) as wsp:
        wsp.send_json({"type": "token_image", "token_id": tok["id"], "asset_id": aid})
        assert recv_until(wsp, "token_image")["payload"]["image"] == f"/assets/{aid}"
    t = next(t for t in state_of(client, player, code)["tokens"] if t["id"] == tok["id"])
    assert t["image"] == f"/assets/{aid}"                          # DB canon unchanged
    assert client.get(f"/assets/{aid}", headers=H(player)).status_code == 200
    assert client.get(f"/assets/{aid}", headers=H(dm)).status_code == 200, \
        "the DM of the room the art rides in may load it"
    stranger = reg(client, "nope")
    assert client.get(f"/assets/{aid}", headers=H(stranger)).status_code == 404


def test_client_draws_the_server_canonical_url(client):
    # the browser contract: the canvas loads tokens.image VERBATIM, so the
    # server must serve that url (the route tests above) — and the void brush
    # must exist, be paintable and be drag-paintable.
    src = _static("js", "50_canvas.js")
    assert "img.src = t.image" in src
    assert 'else if (b === "void") gm.cells[i] = 5;' in src
    assert '"wall","floor","void","rough","erase","reveal","refog"' in src
    html = _static("index.html")
    assert 'data-b="void"' in html
