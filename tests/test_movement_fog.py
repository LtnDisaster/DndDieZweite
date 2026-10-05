"""Sprint 4 movement, footprint visibility, fog, and path-preview regressions."""
import time
import uuid

import pytest
from starlette.testclient import TestClient

from app import main
from app.room import movement


@pytest.fixture()
def client():
    return TestClient(main.app)


def H(u):
    return {"cookie": u["cookie"]}


def reg(client, tag):
    name = f"{tag}{uuid.uuid4().hex[:8]}"
    r = client.post("/api/register", json={"username": name, "password": "secret123"})
    assert r.status_code == 200, r.text
    val = r.headers["set-cookie"].split("vtt_session=", 1)[1].split(";", 1)[0].strip('"')
    return {"name": name, "cookie": f"vtt_session={val}"}


def join_room(client, user, code):
    r = client.post("/api/rooms/join", json={"code": code}, headers=H(user))
    assert r.status_code == 200, r.text


def make_char(client, user, hp=30, max_hp=30):
    r = client.post("/api/characters", headers=H(user), json={
        "name": f"Char{user['name']}", "race": "Human", "char_class": "Fighter", "level": 5,
        "stats": {"str": 16, "dex": 14, "con": 16, "int": 10, "wis": 12, "cha": 10},
        "hp": hp, "max_hp": max_hp,
    })
    assert r.status_code == 200, r.text
    return r.json()


def state_of(client, user, code):
    r = client.get(f"/api/rooms/{code}/state", headers=H(user))
    assert r.status_code == 200, r.text
    return r.json()


def ws_connect(client, user, code):
    return client.websocket_connect(f"/ws/{code}", headers={"cookie": user["cookie"]})


def recv_until(ws, kind, tries=30, fail_on_error=True):
    # An unexpected server "error" means the awaited event will never arrive;
    # fail loudly with its message instead of blocking on receive_json forever.
    # Tests that deliberately provoke errors pass fail_on_error=False.
    seen = []
    for _ in range(tries):
        ev = ws.receive_json()
        seen.append(ev.get("kind"))
        if ev.get("kind") == kind:
            return ev
        if ev.get("kind") == "error" and fail_on_error and kind != "error":
            raise AssertionError(f"unexpected error while waiting for {kind!r}: "
                                 f"{ev.get('payload')} (saw {seen})")
    raise AssertionError(f"never saw {kind!r}; saw {seen}")


def recv_kinds_until(ws, kind, tries=30, fail_on_error=True):
    seen = []
    for _ in range(tries):
        ev = ws.receive_json()
        seen.append(ev.get("kind"))
        if ev.get("kind") == kind:
            return seen
        if ev.get("kind") == "error" and fail_on_error and kind != "error":
            raise AssertionError(f"unexpected error while waiting for {kind!r}: "
                                 f"{ev.get('payload')} (saw {seen})")
    raise AssertionError(f"never saw {kind!r}; saw {seen}")


def set_grid(client, dm, code, mutate):
    grid = state_of(client, dm, code)["grid"]
    mutate(grid)
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "map_edit", "map": grid})
        recv_until(ws, "map_changed")


def wall_column(grid, x, skip=None):
    for y in range(grid["h"]):
        if y != skip:
            grid["cells"][y * grid["w"] + x] = 1


def add_npc(ws, label="Hidden", cx=15, cy=13):
    cell = 50
    ws.send_json({"type": "add_token", "label": label, "x": (cx + .5) * cell,
                  "y": (cy + .5) * cell, "size": "Medium"})
    return recv_until(ws, "token_add")["payload"]["id"]


def base_room(client):
    dm, player = reg(client, "dm"), reg(client, "pl")
    code = client.post("/api/rooms", json={"name": "Sprint4"}, headers=H(dm)).json()["code"]
    join_room(client, player, code)
    ch = make_char(client, player)
    client.post(f"/api/rooms/{code}/assign", json={"character_id": ch["id"]}, headers=H(player))
    return dm, player, code, ch


def room_with_wall(client, wall_x=10):
    dm, player, code, ch = base_room(client)
    set_grid(client, dm, code, lambda g: wall_column(g, wall_x))
    return dm, player, code, ch


def move_token(ws, token_id, tx, ty, teleport=False):
    ws.send_json({"type": "move", "token_id": token_id, "tx": tx, "ty": ty, "teleport": teleport})


# ---------- footprint, collision, and path preview ----------

def test_path_preview_uses_server_footprint_and_does_not_move(client):
    dm, player, code, _ = base_room(client)
    with ws_connect(client, player, code) as ws:
        mine = next(t for t in state_of(client, player, code)["tokens"] if t.get("character_id"))
        ws.send_json({"type": "path_preview", "token_id": mine["id"], "tx": 9, "ty": 6,
                      "request_id": 7})
        ev = recv_until(ws, "path_preview")
        assert ev["payload"]["goal"] == {"cx": 9, "cy": 6}
        assert ev["payload"]["cells"]
        assert ev["payload"]["cost"] >= 1
    after = next(t for t in state_of(client, player, code)["tokens"] if t["id"] == mine["id"])
    assert after["x"] == mine["x"] and after["y"] == mine["y"]


def test_player_cannot_preview_another_players_token(client):
    dm, player, code, _ = base_room(client)
    with ws_connect(client, dm, code) as dws:
        npc = add_npc(dws)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "path_preview", "token_id": npc, "tx": 12, "ty": 13})
        assert recv_until(ws, "error")["payload"]["msg"]


def test_path_preview_cannot_reveal_unexplored_route(client):
    dm, player, code, _ = base_room(client)
    with ws_connect(client, player, code) as ws:
        mine = next(t for t in state_of(client, player, code)["tokens"] if t.get("character_id"))
        ws.send_json({"type": "path_preview", "token_id": mine["id"], "tx": 20, "ty": 6,
                      "request_id": 9})
        assert recv_until(ws, "error")["payload"]["msg"] == "No path there"


# ---------- occluded token payload security ----------

def test_hidden_npc_is_absent_from_player_state_and_live_updates(client):
    dm, player, code, _ = room_with_wall(client)
    with ws_connect(client, dm, code) as dws:
        npc = add_npc(dws, cx=15)
        move_token(dws, npc, 16, 13, teleport=True)
        recv_until(dws, "step")

    dm_state = state_of(client, dm, code)["tokens"]
    assert npc in [t["id"] for t in dm_state]
    player_state = state_of(client, player, code)["tokens"]
    assert npc not in [t["id"] for t in player_state]

    with ws_connect(client, player, code) as pws:
        with ws_connect(client, dm, code) as dws:
            move_token(dws, npc, 17, 13, teleport=True)
            recv_until(dws, "step")
        pws.send_json({"type": "chat", "text": "marker", "target": "party"})
        seen = recv_kinds_until(pws, "chat")
        assert "step" not in seen
        assert "token_add" not in seen


def test_npc_movement_does_not_reveal_player_fog(client):
    dm, player, code, _ = room_with_wall(client)
    before = state_of(client, player, code)["grid"]
    with ws_connect(client, dm, code) as ws:
        npc = add_npc(ws, cx=11)
        move_token(ws, npc, 12, 13, teleport=True)
        recv_until(ws, "step")
    after = state_of(client, player, code)["grid"]
    far_idx = 13 * before["w"] + 20
    assert after["explored"][far_idx] == before["explored"][far_idx]


# ---------- fog of war ----------

def test_dm_can_reveal_and_rehide_fog(client):
    dm, player, code, _ = base_room(client)
    grid = state_of(client, player, code)["grid"]
    idx = 13 * grid["w"] + 35
    assert grid["explored"][idx] == 0 and grid["cells"][idx] is None
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "fog_edit", "cells": [
            {"x": 35, "y": 13, "explored": 1}]})
        ev = recv_until(ws, "fog_changed")
        assert str(idx) in ev["payload"]["cells"]
    revealed = state_of(client, player, code)["grid"]
    assert revealed["explored"][idx] == 1 and revealed["cells"][idx] is not None

    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "fog_edit", "cells": [
            {"x": 35, "y": 13, "explored": 0}]})
        recv_until(ws, "fog_changed")
    hidden = state_of(client, player, code)["grid"]
    assert hidden["explored"][idx] == 0 and hidden["cells"][idx] is None


def test_player_cannot_reveal_fog(client):
    dm, player, code, _ = base_room(client)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "fog_edit", "cells": [{"x": 35, "y": 13, "explored": 1}]})
        assert recv_until(ws, "error")["payload"]["msg"] == "DM only"


def test_wall_blocks_exploration_and_door_open_reveals(client):
    dm, player, code, _ = room_with_wall(client)

    def mutate(grid):
        wall_column(grid, 10, skip=13)
        grid["cells"][13 * grid["w"] + 10] = 0
        grid["doors"] = [{"id": "door", "x": 10, "y": 13, "dir": "v",
                          "closed": True, "locked": False, "label": "Door"}]
    set_grid(client, dm, code, mutate)
    with ws_connect(client, dm, code) as ws:
        mine = next(t for t in state_of(client, player, code)["tokens"] if t.get("character_id"))
        move_token(ws, mine["id"], 10, 13, teleport=True)
        recv_until(ws, "step")
    grid = state_of(client, player, code)["grid"]
    behind_idx = 13 * grid["w"] + 11
    assert grid["explored"][behind_idx] == 0 and grid["cells"][behind_idx] is None

    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "door", "x": 10, "y": 13, "dir": "v", "action": "toggle"})
        assert recv_until(ws, "explored")["payload"]["terrain"]
        assert recv_until(ws, "map_changed")
    opened = state_of(client, player, code)["grid"]
    assert opened["explored"][behind_idx] == 1 and opened["cells"][behind_idx] is not None


# ---------- movement cancellation and trap auto-stop ----------

def test_dm_can_stop_active_movement(client, monkeypatch):
    monkeypatch.setattr(movement, "STEP_DELAY", 2)
    dm, player, code, _ = base_room(client)
    with ws_connect(client, dm, code) as ws:
        npc = add_npc(ws, cx=8, cy=13)
        move_token(ws, npc, 14, 13)
        seen = recv_kinds_until(ws, "step")
        assert "move_state" in seen
        ws.send_json({"type": "stop_move", "token_id": npc})
        stopped = recv_until(ws, "move_state")["payload"]
        assert stopped["moving"] is False and stopped["reason"] == "manual"
        time.sleep(.05)
        stopped_tok = next(t for t in state_of(client, dm, code)["tokens"] if t["id"] == npc)
        cx = int(stopped_tok["x"] // 50)
        assert cx <= 9


def test_player_cannot_stop_movement(client):
    dm, player, code, _ = base_room(client)
    with ws_connect(client, dm, code) as dws:
        npc = add_npc(dws)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "stop_move", "token_id": npc})
        assert recv_until(ws, "error")["payload"]["msg"] == "DM only"


def test_movement_stops_when_trap_triggers(client, monkeypatch):
    monkeypatch.setattr(movement, "STEP_DELAY", .01)
    dm, player, code, _ = base_room(client)

    def mutate(grid):
        grid["traps"] = [{"id": "t1", "x": 10, "y": 13, "label": "Spike Trap",
                          "dc": 10, "dmg": "1d4", "discovered": False}]
    set_grid(client, dm, code, mutate)
    with ws_connect(client, dm, code) as ws:
        npc = add_npc(ws, cx=8, cy=13)
        move_token(ws, npc, 14, 13)
        seen_stop = False
        while not seen_stop:
            ev = ws.receive_json()
            if ev.get("kind") == "move_state" and ev["payload"].get("moving") is False:
                assert ev["payload"].get("reason") == "trap"
                seen_stop = True
        stopped = next(t for t in state_of(client, dm, code)["tokens"] if t["id"] == npc)
        assert int(stopped["x"] // 50) <= 10
