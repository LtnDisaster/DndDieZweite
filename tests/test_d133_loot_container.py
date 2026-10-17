"""D133 (AP-019): editor loot objects flagged `container` are REAL containers.

A loot entry with `container` rides the ONE D92 container channel under the
synthetic key "loot:<entry id>" (mirroring the D105 "tok:<id>" carcass key):
contents live in SQLite, exchange only through authorised inv_container, and
walking over the object never writes the legacy note again (a one-time hint
whisper points at the open action instead). Unflagged loot keeps the D79-era
note-pickup untouched.
"""
import uuid

import pytest
from starlette.testclient import TestClient

from app import db, main
from tests.test_movement_fog import (H, base_room, recv_until, set_grid,
                                     state_of, ws_connect)

CELL = 50


@pytest.fixture
def client():
    app = main.app
    with TestClient(app) as c:
        yield c


def player_cell(client, user, code):
    st = state_of(client, user, code)
    tok = next(t for t in st["tokens"] if t.get("owner_user_id") == st["me"])
    return tok, int(tok["x"] // CELL), int(tok["y"] // CELL)


def put_loot(client, dm, code, x, y, cid="purse", container=1):
    def mut(g):
        g["loot"].append({"id": cid, "x": x, "y": y, "label": "Coin Purse",
                          "taken_by": None, "container": container})
    set_grid(client, dm, code, mut)


def notes_of(ch_id):
    return db.q1("SELECT notes FROM characters WHERE id=?", (ch_id,))["notes"] or ""


def primary_map(code):
    rid = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
    # the PRIMARY plane lives in room_state.map_json; floor_maps holds only
    # additional floors.
    return db.j(db.q1("SELECT map_json FROM room_state WHERE room_id=?",
                      (rid,))["map_json"], {})


def loot_entry(code, cid="purse"):
    return next((l for l in primary_map(code).get("loot", [])
                 if l.get("id") == cid), None)


def test_container_loot_is_never_a_note_pickup(client):
    dm, player, code, ch = base_room(client)
    tok, px, py = player_cell(client, player, code)
    put_loot(client, dm, code, px + 1, py)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "move", "token_id": tok["id"], "tx": px + 1, "ty": py})
        ws.send_json({"type": "chat", "text": "@@walkdone@@"})
        while True:
            ev = ws.receive_json()
            if ev.get("kind") == "chat" and "@@walkdone@@" in str(ev.get("payload", {}).get("text", "")):
                break
    assert "[loot]" not in notes_of(ch["id"])
    assert loot_entry(code)["taken_by"] is None
    assert loot_entry(code).get("hinted") is True


def test_round_trip_coins_and_items_on_the_loot_key(client):
    dm, player, code, ch = base_room(client)
    tok, px, py = player_cell(client, player, code)
    put_loot(client, dm, code, px + 1, py)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "move", "token_id": tok["id"], "tx": px + 1, "ty": py})
    with ws_connect(client, dm, code) as dws:
        dws.send_json({"type": "inv_container", "action": "coins_fill",
                       "object_id": "loot:purse", "floor": "", "amount": 25, "coin": "gp"})
        p = recv_until(dws, "inv_contents")
    assert p["payload"]["coins"] == 2500
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "inv_container", "action": "coins_take",
                      "object_id": "loot:purse", "floor": "", "char_id": ch["id"],
                      "amount": 10, "coin": "gp", "op_id": "lt" + uuid.uuid4().hex[:8]})
        p = recv_until(ws, "inv_contents")
    assert p["payload"]["coins"] == 1500
    st = state_of(client, player, code)
    me = next(m for m in st["members"] if m["user_id"] == st["me"])
    assert me["char"]["wallet"] == 1000
    assert loot_entry(code)["taken_by"] is None      # container semantics, not taken


def test_out_of_reach_answers_explicitly(client):
    dm, player, code, ch = base_room(client)
    tok, px, py = player_cell(client, player, code)
    put_loot(client, dm, code, px + 8, py)           # far away, no walk
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "inv_container", "action": "inspect",
                      "object_id": "loot:purse", "floor": ""})
        ev = recv_until(ws, "error")
    assert "Walk up to it first" in ev["payload"]["msg"]


def test_unflagged_loot_keeps_the_legacy_note(client):
    dm, player, code, ch = base_room(client)
    tok, px, py = player_cell(client, player, code)
    put_loot(client, dm, code, px + 1, py, cid="old", container=0)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "move", "token_id": tok["id"], "tx": px + 1, "ty": py})
        recv_until(ws, "map_changed")
    assert "[loot] Coin Purse" in notes_of(ch["id"])
    entry = next(l for l in primary_map(code).get("loot", []) if l["id"] == "old")
    assert entry["taken_by"] == db.q1("SELECT user_id FROM room_members "
                                      "WHERE character_id=?", (ch["id"],))["user_id"]


def test_unknown_or_unflagged_key_stays_silent(client):
    dm, player, code, ch = base_room(client)
    put_loot(client, dm, code, 3, 3, cid="plain", container=0)
    with ws_connect(client, player, code) as ws:
        for oid in ("loot:nope", "loot:plain"):      # unknown id / unflagged
            ws.send_json({"type": "chat", "text": "@@probe@@"})
            ws.send_json({"type": "inv_container", "action": "inspect",
                          "object_id": oid, "floor": ""})
            while True:
                ev = ws.receive_json()
                if ev.get("kind") == "chat" and "@@probe@@" in str(ev.get("payload", {}).get("text", "")):
                    break
                assert ev.get("kind") != "inv_contents", oid
                assert ev.get("kind") != "error", oid
