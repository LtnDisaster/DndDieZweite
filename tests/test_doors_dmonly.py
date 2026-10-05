"""Sprint 9 (P6): dm_only and secret doors.

dm_only = operation restricted to the DM (server-enforced; "locked" stays a
physical game state and stays orthogonal). secret = the door is never
transmitted to players at all. Normal and locked door behaviour must not
regress. Tactical/Diorama share this handler and this map data, so client
views cannot diverge.
"""
import pytest
from starlette.testclient import TestClient

from app import db, mapmodel
from app.main import app
from test_movement_fog import (H, base_room, recv_until, set_grid, state_of,
                               ws_connect)

CELL = 50


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def room_id_of(code):
    return db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]


def with_doors(client, dm, code, doors):
    def mutate(g):
        g["doors"] = doors
    set_grid(client, dm, code, mutate)


def put_token_at(code, ch, cx, cy):
    db.x("UPDATE tokens SET x=?, y=? WHERE room_id=? AND character_id=?",
         (cx * CELL + CELL // 2, cy * CELL + CELL // 2, room_id_of(code), ch["id"]))


def door_at(client, who, code, **flags):
    d = {"id": "d1", "x": 1, "y": 1, "dir": "v", "closed": True, "label": "Door", **flags}
    with_doors(client, who, code, [d])


def sys_door_messages(code):
    return db.q("SELECT body FROM messages WHERE room_id=? AND type='system' "
                "AND body LIKE '%door%'", (room_id_of(code),))


# ---------- persistence / visibility ----------

def test_flags_survive_sanitize_and_state_roundtrip(client):
    dm, player, code, ch = base_room(client)
    door_at(client, dm, code, locked=True, dm_only=True, secret=False)
    grid = state_of(client, dm, code)["grid"]["doors"][0]
    assert grid["dm_only"] is True and grid["secret"] is False
    assert grid["locked"] is True and grid["closed"] is True


def test_secret_door_never_reaches_players(client):
    dm, player, code, ch = base_room(client)
    door_at(client, dm, code, secret=True)
    assert len(state_of(client, dm, code)["grid"]["doors"]) == 1
    pdata = state_of(client, player, code)
    assert pdata["grid"]["doors"] == []
    assert "d1" not in str(pdata["grid"]["doors"])  # not even the id leaks


def test_secret_door_still_blocks_movement_server_side(client):
    # mapmodel level: a closed secret door is a closed edge, flags irrelevant.
    base = {"w": 8, "h": 6, "cell": CELL, "cells": [0] * 48, "explored": [0] * 48}
    mp = mapmodel.sanitize({**base, "doors": [{"id": "s", "x": 1, "y": 1, "dir": "v",
                                               "closed": True, "secret": True}]})
    assert mapmodel.blocked_edges(mp)  # edge is impassable
    assert mp["doors"][0]["secret"] is True
    mp2 = mapmodel.sanitize({**base, "doors": [{"id": "s", "x": 1, "y": 1, "dir": "v",
                                                "closed": False, "secret": True}]})
    assert not mapmodel.blocked_edges(mp2)


# ---------- authorization ----------

def test_dm_can_operate_dm_only_and_secret_doors(client):
    dm, player, code, ch = base_room(client)
    door_at(client, dm, code, dm_only=True)
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "door", "x": 1, "y": 1, "dir": "v", "action": "toggle"})
        recv_until(ws, "map_changed")
    assert state_of(client, dm, code)["grid"]["doors"][0]["closed"] is False
    # and "set" for scripted state
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "door", "x": 1, "y": 1, "dir": "v", "action": "set",
                      "open": False, "locked": True})
        recv_until(ws, "map_changed")
    d = state_of(client, dm, code)["grid"]["doors"][0]
    assert d["closed"] is True and d["locked"] is True and d["dm_only"] is True


def test_player_cannot_toggle_visible_dm_only_door(client):
    dm, player, code, ch = base_room(client)
    door_at(client, dm, code, dm_only=True)
    put_token_at(code, ch, 1, 1)   # stand adjacent like a legit player would
    before = state_of(client, dm, code)["grid"]["doors"][0]["closed"]
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "door", "x": 1, "y": 1, "dir": "v", "action": "toggle"})
        ev = recv_until(ws, "error")
        assert "budge" in ev["payload"]["msg"]
    assert state_of(client, dm, code)["grid"]["doors"][0]["closed"] == before


def test_hostile_set_and_remove_from_player_are_refused(client):
    dm, player, code, ch = base_room(client)
    door_at(client, dm, code, dm_only=True)
    put_token_at(code, ch, 1, 1)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "door", "x": 1, "y": 1, "dir": "v", "action": "set",
                      "open": True})
        recv_until(ws, "error")
        ws.send_json({"type": "door", "x": 1, "y": 1, "dir": "v", "action": "remove"})
        recv_until(ws, "error")
    doors = state_of(client, dm, code)["grid"]["doors"]
    assert len(doors) == 1 and doors[0]["closed"] is True   # unchanged, still present


def test_secret_door_gives_no_signal_at_all_to_players(client):
    dm, player, code, ch = base_room(client)
    door_at(client, dm, code, secret=True)
    put_token_at(code, ch, 1, 1)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "door", "x": 1, "y": 1, "dir": "v", "action": "toggle"})
        ws.send_json({"type": "chat", "text": "probe"})
        got = []
        while True:
            ev = ws.receive_json()
            got.append(ev.get("kind"))
            if ev.get("kind") == "chat":
                break
        assert "error" not in got      # indistinguishable from "no door here"
    assert state_of(client, dm, code)["grid"]["doors"][0]["closed"] is True


# ---------- no information leaks / regressions ----------

def test_dm_only_moves_are_not_announced_in_the_chronicle(client):
    dm, player, code, ch = base_room(client)
    door_at(client, dm, code, dm_only=True)
    assert sys_door_messages(code) == []
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "door", "x": 1, "y": 1, "dir": "v", "action": "toggle"})
        recv_until(ws, "map_changed")
    assert sys_door_messages(code) == []
    # a normal door IS announced (regression anchor)
    door_at(client, dm, code)
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "door", "x": 1, "y": 1, "dir": "v", "action": "toggle"})
        recv_until(ws, "map_changed")
    assert sys_door_messages(code) != []


def test_normal_adjacent_player_toggle_still_works(client):
    dm, player, code, ch = base_room(client)
    door_at(client, dm, code)          # plain door: closed, not locked
    put_token_at(code, ch, 1, 1)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "door", "x": 1, "y": 1, "dir": "v", "action": "toggle"})
        recv_until(ws, "map_changed")
    assert state_of(client, dm, code)["grid"]["doors"][0]["closed"] is False


def test_locked_door_message_precedes_dm_only_neutralization(client):
    # locked + dm_only: the dm_only answer must win (no lock-state leak)
    dm, player, code, ch = base_room(client)
    door_at(client, dm, code, locked=True, dm_only=True)
    put_token_at(code, ch, 1, 1)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "door", "x": 1, "y": 1, "dir": "v", "action": "toggle"})
        ev = recv_until(ws, "error")
    assert "locked" not in ev["payload"]["msg"].lower()
    assert "budge" in ev["payload"]["msg"]
