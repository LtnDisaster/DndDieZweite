"""Sprint 5B hardening suite: cross-system regressions and adversarial input.

Covers interactions unit-level suites can't catch on their own:
door x LOS x persistent explored memory, stale path previews vs. authoritative
moves, walk lifecycle after DM cancellation, world invariants under hostile
coordinates, DM-only authorization over player sockets, and malformed payloads
that must never kill a socket or leak state.

Helpers are reused from tests/test_movement_fog.py (same import root dir).
"""
import time

import pytest
from starlette.testclient import TestClient

from app import db
from app.main import app
from app.room import movement

from test_movement_fog import (reg, join_room, make_char, state_of, ws_connect,
                               recv_until, recv_kinds_until, set_grid, wall_column,
                               add_npc, base_room, move_token)


@pytest.fixture()
def client():
    return TestClient(app)


def room_id_of(code):
    return db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]


# ---------- A. door x LOS x persistent explored memory ----------

def test_door_open_close_los_and_explored_cycle(client):
    dm, player, code, _ = base_room(client)
    set_grid(client, dm, code, lambda g: wall_column(g, 10))

    def add_door(g):                                   # carve a doorway at row 13
        g["cells"][13 * g["w"] + 10] = 0
        g["doors"] = [{"id": "d1", "x": 10, "y": 13, "dir": "v",
                       "closed": True, "locked": False}]
    set_grid(client, dm, code, add_door)

    with ws_connect(client, dm, code) as dws:
        mine = next(t for t in state_of(client, player, code)["tokens"] if t.get("character_id"))
        move_token(dws, mine["id"], 8, 13, teleport=True)          # bring the player to the door row
        recv_until(dws, "step")
        npc = add_npc(dws, label="Ambush", cx=12, cy=13)           # behind the closed door

    pst = state_of(client, player, code)
    assert npc not in [t["id"] for t in pst["tokens"]]              # never transmitted
    assert pst["grid"]["cells"][13 * 40 + 12] is None                # behind wall: unexplored

    with ws_connect(client, dm, code) as dws:                       # open the door
        dws.send_json({"type": "door", "x": 10, "y": 13, "dir": "v", "action": "toggle"})
        recv_until(dws, "map_changed")

    pst = state_of(client, player, code)
    assert npc in [t["id"] for t in pst["tokens"]]                  # visible through the gap
    assert pst["grid"]["cells"][13 * 40 + 12] is not None            # explored memory grew

    with ws_connect(client, dm, code) as dws:                       # close again + move NPC away
        dws.send_json({"type": "door", "x": 10, "y": 13, "dir": "v", "action": "toggle"})
        recv_until(dws, "map_changed")
        dws.send_json({"type": "move", "token_id": npc, "tx": 20, "ty": 13, "teleport": True})
        recv_until(dws, "step")

    pst = state_of(client, player, code)
    assert npc not in [t["id"] for t in pst["tokens"]]              # live state not leaked
    assert pst["grid"]["cells"][13 * 40 + 12] is not None            # persistent memory stays (D45)

    with ws_connect(client, player, code) as pws:                   # live: nothing crosses the door
        with ws_connect(client, dm, code) as dws:
            dws.send_json({"type": "move", "token_id": npc, "tx": 24, "ty": 13, "teleport": True})
            recv_until(dws, "step")
        pws.send_json({"type": "chat", "text": "marker", "channel": "global"})
        seen = recv_kinds_until(pws, "chat")
        assert "step" not in seen and "token_add" not in seen


# ---------- door adjacency with multiple owned tokens (legacy rows) ----------

def test_door_adjacency_counts_any_owned_token(client):
    dm, player, code, _ = base_room(client)                          # main token at (8,6)
    def mutate(g):
        g["doors"] = [{"id": "d2", "x": 29, "y": 20, "dir": "v",
                       "closed": False, "locked": False}]           # far from the main token
    set_grid(client, dm, code, mutate)
    rid = room_id_of(code)
    uid = next(m["user_id"] for m in state_of(client, dm, code)["members"]
               if m["username"] == player["name"])
    second = db.x("INSERT INTO tokens (room_id,owner_user_id,label,color,x,y) "
                  "VALUES (?,?, 'Second', '#fff', ?, ?)", (rid, uid, 30 * 50 + 25, 20 * 50 + 25))

    with ws_connect(client, player, code) as ws:                     # adjacent via the 2nd token
        ws.send_json({"type": "door", "x": 29, "y": 20, "dir": "v", "action": "toggle"})
        assert "map_changed" in recv_kinds_until(ws, "map_changed", tries=12)
    door = next(d for d in state_of(client, dm, code)["grid"]["doors"] if d["id"] == "d2")
    assert door["closed"] is True

    db.x("UPDATE tokens SET x=?, y=? WHERE id=?", (50, 50, second))  # move it away too
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "door", "x": 29, "y": 20, "dir": "v", "action": "toggle"})
        assert "Walk up" in recv_until(ws, "error")["payload"]["msg"]


# ---------- D. stale path previews are never authority ----------

def test_stale_preview_is_not_authority(client):
    dm, player, code, _ = base_room(client)                          # player token at (8,6)
    set_grid(client, dm, code, lambda g: wall_column(g, 10, skip=6))  # open gap at (10,6)
    with ws_connect(client, player, code) as ws:
        tok = next(t["id"] for t in state_of(client, player, code)["tokens"]
                   if t.get("owner_user_id"))
        ws.send_json({"type": "path_preview", "token_id": tok, "tx": 13, "ty": 6, "request_id": 7})
        prev = recv_until(ws, "path_preview")["payload"]
        assert len(prev["path"]) > 3                                 # route through the gap

    gm = state_of(client, dm, code)["grid"]                          # world changes: gap walls over
    gm["cells"][6 * gm["w"] + 10] = 1
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "map_edit", "map": gm})
        recv_until(ws, "map_changed")

    with ws_connect(client, player, code) as ws:                     # stale preview ≠ authority
        before = next(t for t in state_of(client, player, code)["tokens"] if t["id"] == tok)
        ws.send_json({"type": "move", "token_id": tok, "tx": 13, "ty": 6})
        assert "No path" in recv_until(ws, "error")["payload"]["msg"]
        time.sleep(0.2)
        after = next(t for t in state_of(client, player, code)["tokens"] if t["id"] == tok)
        assert (after["x"], after["y"]) == (before["x"], before["y"])


# ---------- C+. walk lifecycle: stop must leave no orphan task ----------

def test_stop_move_cancels_walk_with_no_orphan_task(client, monkeypatch):
    monkeypatch.setattr(movement, "STEP_DELAY", 2)
    dm, player, code, _ = base_room(client)
    with ws_connect(client, dm, code) as ws:
        npc = add_npc(ws, cx=4, cy=13)
        move_token(ws, npc, 18, 13)
        recv_until(ws, "step")
        assert npc in movement._walks
        ws.send_json({"type": "stop_move", "token_id": npc})
        stopped = recv_until(ws, "move_state")["payload"]
        assert stopped["moving"] is False and stopped["reason"] == "manual"
        assert npc not in movement._walks                            # no orphan registration
        pos = next(t for t in state_of(client, dm, code)["tokens"] if t["id"] == npc)
        frozen = (pos["x"], pos["y"])
        time.sleep(0.4)
        later = next(t for t in state_of(client, dm, code)["tokens"] if t["id"] == npc)
        assert (later["x"], later["y"]) == frozen                    # it really stopped


# ---------- invariants: hostile coordinates never put a token off-map ----------

def test_out_of_range_targets_clamp_inside_the_map(client, monkeypatch):
    monkeypatch.setattr(movement, "STEP_DELAY", .01)                 # walk to completion fast
    dm, player, code, _ = base_room(client)
    with ws_connect(client, dm, code) as ws:
        tok = next(t["id"] for t in state_of(client, dm, code)["tokens"]
                   if t.get("owner_user_id"))
        move_token(ws, tok, 9999, 9999, teleport=True)               # clamped to map corner
        move_token(ws, tok, -400, -400, teleport=True)               # clamped to origin
    t = next(t for t in state_of(client, dm, code)["tokens"] if t["id"] == tok)
    assert 0 <= t["x"] < 40 * 50 and 0 <= t["y"] < 26 * 50
    with ws_connect(client, player, code) as ws:                     # absurd walk: clamped, survives
        ws.send_json({"type": "move", "token_id": tok, "tx": 99999, "ty": 99999})
        done = {}
        for _ in range(400):                                         # first move_state is moving=True
            ev = ws.receive_json()
            if ev.get("kind") == "move_state" and ev["payload"].get("moving") is False:
                done = ev["payload"]
                break
        assert done.get("moving") is False
    t = next(t for t in state_of(client, dm, code)["tokens"] if t["id"] == tok)
    assert 0 <= t["x"] < 40 * 50 and 0 <= t["y"] < 26 * 50


# ---------- adversarial: DM-only operations refused over a player socket ----------

def test_player_sockets_cannot_reach_dm_operations(client):
    dm, player, code, _ = base_room(client)
    hostile = [
        {"type": "add_token", "label": "Hax", "x": 100, "y": 100},
        {"type": "del_token", "token_id": 1},
        {"type": "update_npc", "token_id": 1, "label": "hax"},
        {"type": "fog_edit", "cells": [{"x": 0, "y": 0, "explored": 1}]},
        {"type": "map_edit", "map": {"w": 8, "h": 8, "cells": [0] * 64}},
        {"type": "audio_add", "title": "x", "url": "http://evil.example/x.mp3"},
        {"type": "audio_play", "source_id": "1"},
        {"type": "audio_stop"},
        {"type": "audio_remove", "source_id": "1"},
        {"type": "sound_trigger", "sound_id": 1},
        {"type": "identify", "item_id": 1},
        {"type": "recharge", "item_id": 1},
        {"type": "narrative", "text": "the sky falls"},
        {"type": "spawn_encounter", "encounter_id": 999999},
    ]
    forbidden = {"token_add", "fog_changed", "ambience", "sound", "narrative", "initiative",
                 "map_changed"}
    with ws_connect(client, player, code) as ws:
        errors = 0
        for m in hostile:
            ws.send_json(m)
            ws.send_json({"type": "chat", "text": "marker", "channel": "global"})
            seen = recv_kinds_until(ws, "chat", tries=30)
            assert not (set(seen) & forbidden), f"DM-only effect {set(seen) & forbidden} for {m['type']}"
            errors += "error" in seen
        assert errors >= 8                                           # handlers answer, not hang
        ws.send_json({"type": "chat", "text": "still alive", "channel": "global"})
        assert recv_until(ws, "chat")["payload"]["text"] == "still alive"
    # nothing was mutated: no stray tokens/doors appeared
    assert state_of(client, dm, code)["grid"]["doors"] == []


def test_foreign_character_temp_hp_is_ignored(client):
    dm, p1, code, ch1 = base_room(client)
    p2 = reg(client, "p2")
    join_room(client, p2, code)
    make_char(client, p2)                                            # p2 seat-less char, no token
    tok1 = next(t["id"] for t in state_of(client, dm, code)["tokens"] if t.get("owner_user_id"))
    with ws_connect(client, p2, code) as ws:
        ws.send_json({"type": "temp_hp", "token_id": tok1, "amount": 99, "action": "set"})
        ws.send_json({"type": "chat", "text": "ping", "channel": "global"})
        seen = recv_kinds_until(ws, "chat")
        assert "snapshot" not in seen                                # no room-wide mutation event
    assert (db.q1("SELECT temp_hp FROM characters WHERE id=?", (ch1["id"],))["temp_hp"] or 0) == 0


# ---------- adversarial: malformed payloads never kill the socket ----------

def test_malformed_messages_are_survivable(client):
    dm, player, code, _ = base_room(client)
    with ws_connect(client, player, code) as ws:
        bad = [
            {"type": "move", "token_id": "abc", "tx": 1, "ty": 1},
            {"type": "move", "token_id": None, "tx": None},
            {"type": "path_preview", "token_id": 1},                          # missing tx/ty
            {"type": "path_preview", "token_id": 1, "tx": "x", "ty": "?"},
            {"type": "door", "x": "q", "y": None},
            {"type": "door", "x": -999, "y": -999, "dir": "z"},
            {"type": "fog_edit", "cells": "not-a-list"},
            {"type": "chat", "text": "hi", "channel": "whisper", "target": "999999"},
            {"type": "cond_add", "token_id": "nope", "k": "poisoned"},
            {"type": "hp", "token_id": 1, "amount": "lots"},
            {"nonsense": True},
        ]
        for m in bad:
            ws.send_json(m)
        ws.send_json({"type": "chat", "text": "alive", "channel": "global"})
        assert recv_until(ws, "chat", tries=60)["payload"]["text"] == "alive"


# ---------- mid-walk route invalidation ----------

def _await_walk_end(ws, tries=60):
    """Drain until move_state moving=False; return (payload, events_before_it)."""
    events = []
    for _ in range(tries):
        ev = ws.receive_json()
        if ev.get("kind") == "move_state" and ev["payload"].get("moving") is False:
            return ev["payload"], events
        events.append(ev)
    raise AssertionError(f"walk never ended; saw {[e.get('kind') for e in events]}")


def test_door_closed_midwalk_stops_token_before_the_door(client, monkeypatch):
    monkeypatch.setattr(movement, "STEP_DELAY", 0.25)
    dm, player, code, _ = base_room(client)                            # token at (8,6)

    def build(g):                                                      # doorway at row 6
        wall_column(g, 10, skip=6)
        g["doors"] = [{"id": "dw", "x": 10, "y": 6, "dir": "v",
                       "closed": False, "locked": False}]
    set_grid(client, dm, code, build)

    with ws_connect(client, player, code) as ws:
        tok = next(t for t in state_of(client, player, code)["tokens"] if t.get("owner_user_id"))
        move_token(ws, tok["id"], 14, 6)
        first = recv_until(ws, "step")["payload"]
        assert (first["cx"], first["cy"]) == (9, 6)                    # walking toward open door
        with ws_connect(client, dm, code) as dws:                      # DM slams it shut en route
            dws.send_json({"type": "door", "x": 10, "y": 6, "dir": "v", "action": "toggle"})
            recv_until(dws, "map_changed")
        payload, events = _await_walk_end(ws)
        kinds = [e.get("kind") for e in events]
        assert payload["reason"] == "path_blocked" and payload["token_id"] == tok["id"]
        assert kinds.count("step") == 1                                # only the legal step to (10,6)
        err = next(e for e in events if e.get("kind") == "error")
        assert "blocked" in err["payload"]["msg"]                      # private notice to mover
        ws.send_json({"type": "chat", "text": "marker", "channel": "global"})
        assert "step" not in recv_kinds_until(ws, "chat")              # nothing phases through later

    pst = state_of(client, dm, code)
    cur = next(t for t in pst["tokens"] if t["id"] == tok["id"])
    assert (int(cur["x"] // 50), int(cur["y"] // 50)) == (10, 6)       # last legal cell
    assert next(d for d in pst["grid"]["doors"] if d["id"] == "dw")["closed"] is True
    assert tok["id"] not in movement._walks                            # walk task cleaned up


def test_wall_painted_midwalk_stops_movement(client, monkeypatch):
    monkeypatch.setattr(movement, "STEP_DELAY", 0.25)
    dm, player, code, _ = base_room(client)
    set_grid(client, dm, code, lambda g: wall_column(g, 10, skip=6))   # open gap at (10,6)

    with ws_connect(client, player, code) as ws:
        tok = next(t["id"] for t in state_of(client, player, code)["tokens"]
                   if t.get("owner_user_id"))
        move_token(ws, tok, 14, 6)
        recv_until(ws, "step")

        def block(g):
            g["cells"][6 * g["w"] + 11] = 1          # wall closes in ahead of the token
        set_grid(client, dm, code, block)
        payload, events = _await_walk_end(ws)
        kinds = [e.get("kind") for e in events]
        assert payload["reason"] == "path_blocked"
        assert kinds.count("step") <= 1                                # never enters the new wall
        assert "map_changed" in kinds                                  # the edit that stopped it

    cur = next(t for t in state_of(client, dm, code)["tokens"] if t["id"] == tok)
    assert (int(cur["x"] // 50), int(cur["y"] // 50)) == (10, 6)       # stopped in the doorway
    assert tok not in movement._walks
