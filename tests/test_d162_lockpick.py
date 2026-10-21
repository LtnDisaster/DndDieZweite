"""D162-4 — locked doors can be picked (2024 SRD thieves'-tools rule).

D161 P1-4: a locked door answered a player ONLY with "The door is locked" —
picking existed nowhere (no roll, no tool model, no field). D162 adds the ONE
server-side path: action "pick" on a locked door = Dexterity check through the
single check engine (opposed.check_roll), proficiency from the character's
background row (tool_prof), thieves'-tools possession from the real inventory
snapshot; WITHOUT tools the attempt runs at disadvantage (SRD wording) and
without proficiency; a failure means NO progress and NO alarm. The leak-safe
order (secret → silent, dm_only → "won't budge") is unchanged for pick too.
"""
import pytest
from starlette.testclient import TestClient

from app import db, main
from tests.test_movement_fog import (H, base_room, recv_until, set_grid,
                                     state_of, ws_connect)

DOOR_CELL = (8, 6)          # base_room: cell=50 px, token 425/325 → cell (8,6)


def place_door(client, dm, code, **kw):
    door = {"id": kw.pop("id", "dp1"), "x": DOOR_CELL[0], "y": DOOR_CELL[1],
            "dir": "h", "closed": True, "locked": True}
    door.update(kw)

    def mutate(g):
        g["doors"] = [d for d in (g.get("doors") or []) if d.get("id") != door["id"]] + [door]
    set_grid(client, dm, code, mutate)
    return door


def my_token(client, player, code):
    pst = state_of(client, player, code)
    tok = next(t for t in pst["tokens"] if t.get("character_id"))
    return tok["id"], tok["character_id"]


def fixed_roll(monkeypatch, value):
    seen = []

    def fake(expr, adv=None):
        seen.append(adv)
        return {"kept": value, "adv": adv}
    monkeypatch.setattr("app.room.opposed.do_roll", fake)
    return seen


def whisper(ws, needle):
    ev = recv_until(ws, "whisper", fail_on_error=False)
    assert ev["kind"] == "whisper", ev
    assert needle in ev["payload"]["text"], ev
    return ev["payload"]["text"]


@pytest.fixture()
def client():
    return TestClient(main.app)


def test_pick_without_tools_rolls_with_disadvantage_and_fails(client, monkeypatch):
    dm, player, code, _ = base_room(client)          # dex 14 → +2, no background
    place_door(client, dm, code, lock_dc=25)
    tok_id, char_id = my_token(client, player, code)
    seen = fixed_roll(monkeypatch, 20)               # even a nat 20 loses vs 25
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "door", "x": 8, "y": 6, "dir": "h", "action": "pick"})
        text = whisper(ws, "no tools")
        assert "disadvantage" in text and "no progress" in text
    assert seen == ["dis"]                            # SRD: no tools → dis
    st = next(d for d in state_of(client, dm, code)["grid"]["doors"]
              if d["id"] == "dp1")
    assert st["locked"] is True                       # failure changed nothing


def test_pick_with_tools_and_background_uses_proficiency(client, monkeypatch):
    dm, player, code, _ = base_room(client)
    place_door(client, dm, code, lock_dc=24)
    tok_id, char_id = my_token(client, player, code)
    room_id = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
    db.x("INSERT OR REPLACE INTO content(kind,room_id,id,name,data) "
         "VALUES('background',?,'bg_urchin','Urchin',?)",
         (room_id, db.json_dumps({"tool_prof": "thieves' tools"})))
    db.x("UPDATE characters SET background='bg_urchin', items=? WHERE id=?",
        ('[{"def_id":"thieves","name":"Thieves\' tools","qty":1}]', char_id))
    fixed_roll(monkeypatch, 20)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "door", "x": 8, "y": 6, "dir": "h", "action": "pick"})
        text = whisper(ws, "the lock clicks open")
        assert "thieves' tools + training" in text
        assert "20+5 = 25" in text                    # dex 14 (+2) + prof L5 (+3)
    st = next(d for d in state_of(client, dm, code)["grid"]["doors"] if d["id"] == "dp1")
    assert st["locked"] is False                      # unlocked — and still closed
    assert st["closed"] is True


def test_tools_without_background_no_proficiency(client, monkeypatch):
    dm, player, code, _ = base_room(client)
    place_door(client, dm, code, lock_dc=20)
    tok_id, char_id = my_token(client, player, code)
    db.x("UPDATE characters SET items=? WHERE id=?",
        ('[{"def_id":"thieves","name":"Thieves\' tools","qty":1}]', char_id))
    seen = fixed_roll(monkeypatch, 15)                # 15+2 = 17 < 20
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "door", "x": 8, "y": 6, "dir": "h", "action": "pick"})
        text = whisper(ws, "thieves' tools")
        assert "training" not in text and "no progress" in text
    assert seen == [None]                             # tools → no disadvantage


def test_reach_lock_still_applies_before_any_roll(client, monkeypatch):
    dm, player, code, _ = base_room(client)
    place_door(client, dm, code, id="far", x=15, y=15)
    seen = fixed_roll(monkeypatch, 20)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "door", "x": 15, "y": 15, "dir": "h", "action": "pick"})
        ev = recv_until(ws, "error", fail_on_error=False)
        assert "walk up" in ev["payload"]["msg"].lower()
    assert seen == []                                 # NO roll without reach


def test_secret_door_pick_stays_silent(client):
    dm, player, code, _ = base_room(client)
    place_door(client, dm, code, id="sec", secret=True, lock_dc=25)   # on the token's edge
    my_token(client, player, code)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "door", "x": 8, "y": 6, "dir": "h", "action": "pick"})
        # a frame that MUST answer (the DM-only far door is absent; use a
        # reachable NON-secret locked door? same edge — so instead: an own-frame
        # proof) — the connect greeting has already drained; the next event we
        # await is the room-wide response to a SECOND frame. If the secret pick
        # had answered, that answer would arrive FIRST.
        ws.send_json({"type": "door", "x": 15, "y": 15, "dir": "h", "action": "pick"})   # no door there: silent
        ws.send_json({"type": "init_end"})           # DM-only from a player: LOUD
        ev = recv_until(ws, "error", fail_on_error=False)
        assert "only" in ev["payload"]["msg"].lower()   # first answer = init_end, not a door


def test_dm_only_door_answers_the_pick(client):
    dm, player, code, _ = base_room(client)
    place_door(client, dm, code, id="dmO", x=2, y=2, dm_only=True, lock_dc=25)
    my_token(client, player, code)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "door", "x": 2, "y": 2, "dir": "h", "action": "pick"})
        ev = recv_until(ws, "error", fail_on_error=False)
        assert "won't budge" in ev["payload"]["msg"].lower()   # same answer as toggle


def test_dm_pick_does_nothing_the_hard_way(client):
    dm, player, code, _ = base_room(client)
    place_door(client, dm, code, lock_dc=5)
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "door", "x": 8, "y": 6, "dir": "h", "action": "pick"})
    # the DM branch must NOT flip the door closed state via an unknown action
    st = next(d for d in state_of(client, dm, code)["grid"]["doors"] if d["id"] == "dp1")
    assert st["locked"] is True and st["closed"] is True


def read(p):
    return open(p, encoding="utf-8").read()


def test_editor_authors_the_lock_dc():
    html = read("app/static/index.html")
    assert 'id="door-lockdc"' in html
    canvas = read("app/static/js/50_canvas.js")
    assert "lock_dc" in canvas and '"pick"' in canvas       # shift-click sends pick


def test_mapmodel_clamps_lock_dc():
    from app import mapmodel
    d = mapmodel.sanitize({"w": 10, "h": 10, "cell": 40, "cells": [0] * 100, "doors": [
        {"id": "a", "x": 2, "y": 2, "dir": "h", "locked": True, "lock_dc": 99},
        {"id": "b", "x": 4, "y": 4, "dir": "h", "locked": True, "lock_dc": "x"},
        {"id": "c", "x": 6, "y": 6, "dir": "h", "locked": False, "lock_dc": 8}]})
    by = {dd["id"]: dd for dd in d["doors"]}
    assert by["a"]["lock_dc"] == 25
    assert by["b"]["lock_dc"] == 15
    assert "lock_dc" not in by["c"]
