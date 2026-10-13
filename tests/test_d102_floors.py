"""D102 — floors: integrity, isolation and DM management (Stockwerke).

The floor system existed since D86/D88 but had three cracks this sprint closes:
* saves that silently wrote a NAMED plane's map into the PRIMARY blob
  (trap discovery, toggle objects) — cross-plane data corruption;
* fog reveals (WS connect, character seat) that landed on the primary map
  regardless of the token's plane — wrong-plane terrain and fog memory;
* the token_floor channel let players hop planes at will, skipping every
  destination check — D102 tightened it to DM + validated stair objects.
Plus the DM management surface the UI never had: rename (registry, plane map,
tokens and stair destinations move atomically), per-plane fog patches that
carry their plane so no client can mispaint them, and the player's snapshot
being delivered ON the plane their token stands on.
"""
import json

import pytest
from starlette.testclient import TestClient

from app import db
from app.room import movement
from tests.test_movement_fog import (H, add_npc, base_room, join_room,
                                     recv_until, reg, state_of, ws_connect)

CELL = 50


@pytest.fixture()
def client():
    return TestClient(main_app())


def main_app():
    from app import main
    return main.app


def room_id(code):
    return db.q1("SELECT id FROM rooms WHERE code=?", (code.upper(),))["id"]


def primary_json(code) -> dict:
    return json.loads(db.q1("SELECT map_json FROM room_state WHERE room_id=?",
                            (room_id(code),))["map_json"])


def floor_json(code, floor):
    row = db.q1("SELECT map_json FROM floor_maps WHERE room_id=? AND floor=?",
                (room_id(code), floor))
    return None if row is None else json.loads(row["map_json"])


def explored_count(mp) -> int:
    return sum(1 for e in (mp or {}).get("explored", []) if e)


def pc_token(code, ch):
    return db.q1("SELECT * FROM tokens WHERE room_id=? AND character_id=?",
                 (room_id(code), ch["id"]))


def add_floor(client, dm, code, name):
    r = client.post(f"/api/rooms/{code}/floors", json={"name": name}, headers=H(dm))
    assert r.status_code == 200, r.text


def rename_floor(client, dm, code, old, name):
    return client.patch(f"/api/rooms/{code}/floors/{old}",
                        json={"name": name}, headers=H(dm))


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


def dm_hop(client, dm, code, tok_id, floor):
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "token_floor", "token_id": tok_id, "floor": floor})
        recv_until(ws, "token_floor")


def cell_idx(grid, x, y):
    ox, oy = grid.get("origin") or [0, 0]
    return (y - oy) * grid["w"] + (x - ox)


def _drain(ws, kind, tries=60):
    evs = []
    for _ in range(tries):
        ev = ws.receive_json()
        evs.append(ev)
        if ev.get("kind") == kind:
            return evs
    return evs


# ---------- A: a plane's saves must stay on the plane ----------

def test_trap_on_named_plane_saves_the_plane_not_primary(client, monkeypatch):
    monkeypatch.setattr(movement, "STEP_DELAY", .01)
    dm, player, code, ch = base_room(client)
    add_floor(client, dm, code, "crypt")
    set_floor_grid(client, dm, code, "crypt", lambda g: g.update(
        traps=[{"id": "t1", "x": 10, "y": 7, "label": "Crypt glyph",
                "dc": 10, "dmg": "1d1", "discovered": False}]))
    tok = pc_token(code, ch)
    with ws_connect(client, dm, code) as wsd:
        wsd.send_json({"type": "token_floor", "token_id": tok["id"], "floor": "crypt"})
        recv_until(wsd, "token_floor")
        wsd.send_json({"type": "path_preview", "token_id": tok["id"], "tx": 10, "ty": 7})
        prev = recv_until(wsd, "path_preview")["payload"]
        wsd.send_json({"type": "move", "token_id": tok["id"], "tx": 10, "ty": 7,
                       "path": prev["path"]})
        while True:
            ev = wsd.receive_json()
            if ev.get("kind") == "move_state" and ev["payload"].get("moving") is False:
                assert ev["payload"].get("reason") == "trap"
                break
    assert not primary_json(code).get("traps"), \
        "the primary map learned a crypt trap (un-floored save)"
    fm = floor_json(code, "crypt")
    t = next(t for t in fm["traps"] if t["id"] == "t1")
    assert t["discovered"] and t.get("triggered")           # saved where it sprung


def test_toggle_on_named_plane_saves_the_plane_not_primary(client):
    dm, player, code, _ = base_room(client)
    add_floor(client, dm, code, "crypt")
    set_floor_grid(client, dm, code, "crypt", lambda g: g.update(
        objects=[{"id": "sw1", "label": "Wall switch", "x": 9, "y": 6,
                  "interact": {"op": {"kind": "toggle"}}}]))
    with ws_connect(client, dm, code) as wsd:
        wsd.send_json({"type": "interact", "object_id": "sw1", "floor": "crypt"})
        recv_until(wsd, "object_state")
    assert not primary_json(code).get("objects"), \
        "the primary map grew a crypt switch (un-floored save)"
    fm = floor_json(code, "crypt")
    assert next(o for o in fm["objects"] if o["id"] == "sw1")["state"] == {"on": True}


# ---------- B: fog reveals land on the plane the token stands on ----------

def test_ws_connect_reveals_only_the_standing_plane(client):
    dm, player, code, ch = base_room(client)
    add_floor(client, dm, code, "crypt")
    tok = pc_token(code, ch)
    dm_hop(client, dm, code, tok["id"], "crypt")
    before = explored_count(primary_json(code))
    with ws_connect(client, player, code) as wsp:
        ev = recv_until(wsp, "explored")
        assert ev["payload"].get("floor") == "crypt", \
            "the patch must name its plane (client plane guard)"
    assert explored_count(primary_json(code)) == before,  \
        "a crypt arrival must not poke holes into the primary fog"
    assert explored_count(floor_json(code, "crypt")) > 0  \
        # ... and the plane the token actually stands on does learn


def test_assign_reveals_on_the_token_plane(client):
    dm, player, code, ch = base_room(client)
    add_floor(client, dm, code, "crypt")
    tok = pc_token(code, ch)
    dm_hop(client, dm, code, tok["id"], "crypt")
    before = explored_count(primary_json(code))
    r = client.post(f"/api/rooms/{code}/assign",
                    json={"character_id": ch["id"]}, headers=H(player))
    assert r.status_code == 200, r.text
    assert explored_count(primary_json(code)) == before   # re-seat on crypt: primary untouched
    assert explored_count(floor_json(code, "crypt")) > 0


def test_walk_reveal_patch_is_plane_labelled_and_plane_scoped(client, monkeypatch):
    monkeypatch.setattr(movement, "STEP_DELAY", .01)
    dm, player, code, ch = base_room(client)
    obs = reg(client, "obs")
    join_room(client, obs, code)
    add_floor(client, dm, code, "crypt")
    tok = pc_token(code, ch)
    dm_hop(client, dm, code, tok["id"], "crypt")
    with ws_connect(client, player, code) as wsp, \
         ws_connect(client, obs, code) as wso, \
         ws_connect(client, dm, code) as wsd:
        wsp.send_json({"type": "path_preview", "token_id": tok["id"], "tx": 8, "ty": 9})
        prev = recv_until(wsp, "path_preview")["payload"]
        assert prev.get("path"), "the token previews on ITS OWN plane's map"
        wsp.send_json({"type": "move", "token_id": tok["id"], "tx": 8, "ty": 9,
                       "path": prev["path"]})
        ev = recv_until(wsp, "explored", tries=80)
        assert ev["payload"].get("floor") == "crypt"
        ev = recv_until(wsd, "explored", tries=80)
        assert ev["payload"].get("floor") == "crypt"      # the DM keeps world truth
        wsp.send_json({"type": "chat", "text": "flush-scoped"})
        seen = _drain(wso, "chat")
        kinds = {e.get("kind") for e in seen}
        assert "explored" not in kinds, \
            "a primary observer must not receive a crypt reveal (mis-paints its grid)"


def test_fog_edit_event_carries_its_plane(client):
    dm, player, code, ch = base_room(client)
    obs = reg(client, "obs")
    join_room(client, obs, code)
    add_floor(client, dm, code, "crypt")
    tok = pc_token(code, ch)
    dm_hop(client, dm, code, tok["id"], "crypt")
    with ws_connect(client, player, code) as wsp, \
         ws_connect(client, obs, code) as wso:
        with ws_connect(client, dm, code) as wsd:
            wsd.send_json({"type": "fog_edit", "floor": "crypt",
                           "cells": [{"x": 20, "y": 15, "explored": 1}]})
            wsd.send_json({"type": "chat", "text": "flush-fog"})
            recv_until(wsd, "chat")
        ev = recv_until(wsp, "fog_changed", tries=40)
        assert ev["payload"].get("floor") == "crypt"
        seen = _drain(wso, "chat")                        # chat reaches the observer
        kinds = {e.get("kind") for e in seen}
        assert "fog_changed" not in kinds


# ---------- C: plane changes are DM + validated stairs ----------

def test_player_cannot_self_hop_stairs_remain_the_route(client):
    dm, player, code, ch = base_room(client)
    add_floor(client, dm, code, "crypt")
    tok = pc_token(code, ch)
    with ws_connect(client, player, code) as wsp:
        wsp.send_json({"type": "token_floor", "token_id": tok["id"], "floor": "crypt"})
        assert "Only the DM" in recv_until(wsp, "error")["payload"]["msg"]
    assert (db.q1("SELECT floor FROM tokens WHERE id=?", (tok["id"],))["floor"] or "") == ""
    # the validated stair stays open: it sits ON the player's spawn cell, and
    # apply_forced_move checks terrain and occupants on the TARGET plane.
    set_floor_grid(client, dm, code, "", lambda g: g.update(
        objects=[{"id": "st1", "label": "Cellar stair", "x": 8, "y": 6,
                  "interact": {"op": {"kind": "stair", "floor": "crypt",
                                      "x": 12, "y": 9}}}]))
    with ws_connect(client, player, code) as wsp:
        wsp.send_json({"type": "interact", "object_id": "st1", "floor": ""})
        ev = wsp.receive_json()
        while ev.get("kind") not in ("token_floor", "error"):
            ev = wsp.receive_json()
        assert ev["kind"] == "token_floor", ev
        assert ev["payload"]["floor"] == "crypt"
    assert db.q1("SELECT floor FROM tokens WHERE id=?", (tok["id"],))["floor"] == "crypt"


# ---------- D: the floor manager (rename is the missing piece) ----------

def test_rename_moves_map_and_tokens_and_retargets_stairs(client):
    dm, player, code, ch = base_room(client)
    add_floor(client, dm, code, "crypt")
    add_floor(client, dm, code, "cellar")
    set_floor_grid(client, dm, code, "crypt",
                   lambda g: g["cells"].__setitem__(cell_idx(g, 5, 5), 1))   # recognisable wall
    tok = pc_token(code, ch)
    dm_hop(client, dm, code, tok["id"], "crypt")
    set_floor_grid(client, dm, code, "", lambda g: g.update(
        objects=[{"id": "st1", "label": "Cellar stair", "x": 8, "y": 6,
                  "interact": {"op": {"kind": "stair", "floor": "crypt",
                                      "x": 12, "y": 9}}}]))
    # refusals: same name, unknown floor, taken name, non-DM
    assert rename_floor(client, dm, code, "crypt", "crypt").status_code == 400
    assert rename_floor(client, dm, code, "ghost", "catacomb").status_code == 400
    assert rename_floor(client, dm, code, "crypt", "cellar").status_code == 400
    assert client.patch(f"/api/rooms/{code}/floors/crypt",
                        json={"name": "deep"}, headers=H(player)).status_code == 403
    r = rename_floor(client, dm, code, "crypt", "deep")
    assert r.status_code == 200, r.text
    assert r.json()["floors"] == ["", "deep", "cellar"]   # registry, order kept
    assert db.q1("SELECT 1 AS hit FROM floor_maps WHERE room_id=? AND floor='crypt'",
                 (room_id(code),)) is None                # plane map moved with it
    fm = floor_json(code, "deep")
    assert fm is not None and fm["cells"][cell_idx(fm, 5, 5)] == 1
    assert db.q1("SELECT floor FROM tokens WHERE id=?", (tok["id"],))["floor"] == "deep"
    st = next(o for o in primary_json(code)["objects"] if o["id"] == "st1")
    assert st["interact"]["op"]["floor"] == "deep",       \
        "stair destinations naming the old floor must be retargeted or they dangle"
    # the room still browses the renamed plane — and the old name is gone
    assert state_floor(client, dm, code, "deep")["view_floor"] == "deep"
    assert state_floor(client, dm, code, "crypt")["view_floor"] == ""


# ---------- E: the snapshot lands on the plane you stand on ----------

def test_player_state_is_delivered_on_the_token_plane(client):
    dm, player, code, ch = base_room(client)
    add_floor(client, dm, code, "crypt")
    tok = pc_token(code, ch)
    dm_hop(client, dm, code, tok["id"], "crypt")
    s = state_of(client, player, code)
    assert s["view_floor"] == "crypt"
    assert explored_count(s["grid"]) == 0,                \
        "the snapshot grid is the (untouched) crypt map — not the tavern's"
    assert [t for t in s["tokens"] if t["id"] == tok["id"]][0]["floor"] == "crypt"
