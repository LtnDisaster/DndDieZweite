"""D89 — lighting v2: static light sources (map lamps), token darkvision, and
the visibility rules that bind them: a lamp lights its PLANE for everyone
standing there; darkvision is a private sense of the OWNER (L5: controllers
reveal no fog, senses less so); light state is world DATA behind an
allowlisted op.
"""
import pytest
from starlette.testclient import TestClient

from app import db
from tests.test_movement_fog import (H, base_room, recv_until, state_of,
                                     ws_connect)

CELL = 50


@pytest.fixture()
def client():
    from app import main
    return TestClient(main.app)


def make_dark(client, dm, code):
    grid = state_of(client, dm, code)["grid"]
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "map_edit", "map": {**grid, "dark": True}, "dark": True})
        recv_until(ws, "map_changed")


def add_lamp(client, dm, code, x, y, bright=5):
    grid = state_of(client, dm, code)["grid"]
    grid["objects"] = (grid.get("objects") or []) + [{
        "id": "lamp1", "label": "Brazier", "x": x, "y": y,
        "interact": {"op": {"kind": "lamp", "bright": bright}}}]
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "map_edit", "map": grid})
        recv_until(ws, "map_changed")


def add_named(ws, label, cx, cy):
    ws.send_json({"type": "add_token", "label": label,
                  "x": (cx + .5) * CELL, "y": (cy + .5) * CELL, "size": "Medium"})
    while True:
        e = ws.receive_json()
        if e.get("kind") == "token_add" and (e.get("payload") or {}).get("label") == label:
            return e["payload"]["id"]


def test_lamp_lights_its_plane_for_everyone(client):
    dm, player, code, _ = base_room(client)
    make_dark(client, dm, code)
    with ws_connect(client, dm, code) as wsd:
        npc = add_named(wsd, "Thug", 20, 12)
    ids = {t["id"] for t in state_of(client, player, code)["tokens"]}
    assert npc not in ids, "dark room, no lights — the thug is nowhere"
    add_lamp(client, dm, code, 19, 12, bright=6)             # created LIT
    ids = {t["id"] for t in state_of(client, player, code)["tokens"]}
    assert npc in ids, "light reaches as far as sight does — for everyone on the plane"
    # the light belongs to the world, not the DM's private view
    assert npc in {t["id"] for t in state_of(client, dm, code)["tokens"]}
    # ... and it can be PUT OUT through the allowlisted op (world state flips,
    # persistence survives the sanitizer: {"on": false} is truth, not default)
    with ws_connect(client, dm, code) as wsd:
        wsd.send_json({"type": "interact", "object_id": "lamp1", "floor": ""})
        seen = False
        for _ in range(6):
            ev = wsd.receive_json()
            if ev.get("kind") == "object_state" and ev["payload"]["object_id"] == "lamp1":
                assert ev["payload"]["state"] == {"on": False}
                seen = True
                break
        assert seen
    ids = {t["id"] for t in state_of(client, player, code)["tokens"]}
    assert npc not in ids, "the plane went dark again — the thug is lost to sight"
    # off survives a fresh parse of the stored map (sanitizer regression)
    add_lamp(client, dm, code, 19, 12, bright=6)             # re-author resets to ON
    assert npc in {t["id"] for t in state_of(client, player, code)["tokens"]}


def test_darkvision_is_a_private_sense(client):
    dm, player, code, _ = base_room(client)
    make_dark(client, dm, code)
    with ws_connect(client, dm, code) as wsd:
        npc = add_named(wsd, "Lurker", 12, 12)
    ids = {t["id"] for t in state_of(client, player, code)["tokens"]}
    assert npc not in ids
    mine = [t for t in state_of(client, player, code)["tokens"]
            if t.get("owner_user_id") is not None][0]
    with ws_connect(client, dm, code) as wsd:
        wsd.send_json({"type": "forced_move", "token_id": mine["id"],
                       "kind": "teleport", "tx": 8, "ty": 8})
        recv_until(wsd, "forced_moved")
    assert npc not in {t["id"] for t in state_of(client, player, code)["tokens"]}, \
        "darkness keeps the lurker hidden from the unseeing"
    with ws_connect(client, player, code) as wsp:
        # strangers may not hand out senses
        wsp.send_json({"type": "token_darkvision", "token_id": npc, "radius": 10})
        assert recv_until(wsp, "error", fail_on_error=False)["payload"]["msg"] == "Not your token"
    with ws_connect(client, player, code) as wsp:
        wsp.send_json({"type": "token_darkvision", "token_id": mine["id"], "radius": 8})
        recv_until(wsp, "token_darkvision")
    assert npc in {t["id"] for t in state_of(client, player, code)["tokens"]}, \
        "eight feet of darkvision just bought a peek across the dark"
    for t in state_of(client, dm, code)["tokens"]:
        if t["id"] == mine["id"]:
            assert t.get("darkvision") == 8          # the DM keeps the truth
    # a hidden NPC's darkvision is invisible to every player payload
    with ws_connect(client, dm, code) as wsd:
        wsd.send_json({"type": "token_darkvision", "token_id": npc, "radius": 9})
    st = state_of(client, player, code)
    for t in st["tokens"]:
        assert not (t.get("character_id") is None and t.get("owner_user_id") is None
                    and "darkvision" in t)


def test_lamp_is_plane_data(client):
    dm, player, code, _ = base_room(client)
    client.post(f"/api/rooms/{code}/floors", json={"name": "crypt"}, headers=H(dm))
    grid = state_of(client, dm, code)["grid"]
    grid["objects"] = (grid.get("objects") or []) + [{
        "id": "lamp1", "label": "Brazier", "x": 6, "y": 4,
        "interact": {"op": {"kind": "lamp", "bright": 5}}}]
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "map_edit", "map": grid, "floor": "crypt"})
        recv_until(ws, "map_changed")
    g_base = state_of(client, dm, code)["grid"]
    assert not [o for o in (g_base.get("objects") or []) if o["id"] == "lamp1"]
    rid = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
    row = db.q1("SELECT map_json FROM floor_maps WHERE room_id=? AND floor='crypt'", (rid,))
    assert row is not None and "lamp1" in row["map_json"]
