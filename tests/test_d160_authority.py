"""D160 — server authority & multi-client isolation (real WebSocket clients).

Every assertion is on the MESSAGES the server sends (or refuses to send), not on
a canvas. Two independent sockets where isolation matters. Each attack targets a
specific production gate:
  handle_move authz.controls, the fly/DM teleport gate, _move3d/_teleport3d volume
  validation, token_floor DM-only + destination validation, and plane-scoped
  delivery that must never leak a hidden cross-plane token.
"""
import pytest
from starlette.testclient import TestClient

from app import db
from app.main import app
from tests.test_floor_maps import set_floor_grid
from tests.test_movement_fog import (H, add_npc, base_room, join_room,
                                     make_char, recv_until, reg, state_of,
                                     ws_connect)

CELL = 50


@pytest.fixture()
def client():
    return TestClient(app)


def rid(code):
    return db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]


def _add(client, dm, code, name, below=False):
    assert client.post(f"/api/rooms/{code}/floors",
                       json={"name": name, "below": below}, headers=H(dm)).status_code == 200


def _row(tid):
    return db.q1("SELECT * FROM tokens WHERE id=?", (tid,))


def _own_token(client, player, code):
    me = state_of(client, player, code)["me"]
    return db.q1("SELECT id FROM tokens WHERE room_id=? AND owner_user_id=?",
                 (rid(code), me))["id"]


def _activate(client, dm, code, tok):
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "init_start"})
        init = recv_until(ws, "initiative")["payload"]
        for _ in range(len(init["order"]) + 2):
            if (init.get("turn") or {}).get("token_id") == tok:
                return
            ws.send_json({"type": "init_next"})
            init = recv_until(ws, "initiative")["payload"]
    raise AssertionError("token never active")


def _as_flyer(client, dm, code, tok, pid):
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "token_controller", "token_id": tok, "controller_id": pid})
        recv_until(ws, "token_controller")
        ws.send_json({"type": "update_npc", "token_id": tok,
                      "npc": {"speed": 30, "fly": 30}})
        recv_until(ws, "snapshot")


# ---------- 1. foreign-token authority (gate: handle_move authz.controls) ----

def test_player_cannot_move_a_foreign_token(client):
    dm, player, code, _ = base_room(client)
    with ws_connect(client, dm, code) as wsd:
        npc = add_npc(wsd, "Guard", cx=8, cy=8)          # DM-owned, owner_user_id NULL
    with ws_connect(client, player, code) as wsp:
        wsp.send_json({"type": "move", "token_id": npc, "tx": 1, "ty": 1})
        err = recv_until(wsp, "error")
    assert "your own token" in err["payload"]["msg"]
    r = _row(npc)
    assert (int(r["x"] // CELL), int(r["y"] // CELL)) == (8, 8)   # not moved


# ---------- 2/3. cross-floor needs fly + DM ---------------------------------

def test_cross_floor_move_without_fly_is_refused(client):
    dm, player, code, _ = base_room(client)
    _add(client, dm, code, "crypt")
    mine = _own_token(client, player, code)
    with ws_connect(client, player, code) as wsp:
        wsp.send_json({"type": "move", "token_id": mine, "tx": 6, "ty": 6, "floor": "crypt"})
        err = recv_until(wsp, "error")
    assert "fly speed" in err["payload"]["msg"]
    assert _row(mine)["floor"] == ""                      # never left the ground


def test_player_cannot_change_floors(client):
    dm, player, code, _ = base_room(client)
    _add(client, dm, code, "crypt")
    mine = _own_token(client, player, code)
    with ws_connect(client, player, code) as wsp:
        wsp.send_json({"type": "token_floor", "token_id": mine, "floor": "crypt"})
        err = recv_until(wsp, "error")
    assert "Only the DM moves tokens between floors" in err["payload"]["msg"]
    assert _row(mine)["floor"] == ""


def test_dm_token_floor_rejects_unregistered_name(client):
    dm, _player, code, _ = base_room(client)
    with ws_connect(client, dm, code) as wsd:
        tok = add_npc(wsd, "T", cx=6, cy=6)
        wsd.send_json({"type": "token_floor", "token_id": tok, "floor": "__ghost__"})
        err = recv_until(wsd, "error")
    assert "No such floor" in err["payload"]["msg"]
    assert _row(tok)["floor"] == ""


# ---------- 4. flight route rejects an unregistered floor --------------------

def test_flight_to_unregistered_floor_refused(client):
    dm, player, code, _ = base_room(client)
    pid = state_of(client, player, code)["me"]
    with ws_connect(client, dm, code) as wsd:
        flyer = add_npc(wsd, "Sky", cx=16, cy=12)
    _as_flyer(client, dm, code, flyer, pid)
    with ws_connect(client, player, code) as wsp:
        wsp.send_json({"type": "move", "token_id": flyer, "tx": 16, "ty": 12,
                       "floor": "__ghost__", "mode": "fly"})
        err = recv_until(wsp, "error")
    assert "not registered" in err["payload"]["msg"]
    assert _row(flyer)["floor"] == ""


# ---------- 5. teleport cannot shove a body into a solid cell ----------------

def test_dm_teleport_cannot_enter_a_solid_cell(client):
    dm, _player, code, _ = base_room(client)
    _add(client, dm, code, "Upper")
    # wall the destination cell on the upper plane
    def wall(g):
        g["cells"][5 * g["w"] + 5] = 1
    set_floor_grid(client, dm, code, "Upper", wall)
    with ws_connect(client, dm, code) as wsd:
        tok = add_npc(wsd, "M", cx=5, cy=5)
        wsd.send_json({"type": "move", "token_id": tok, "tx": 5, "ty": 5,
                       "floor": "Upper", "teleport": True})
        err = recv_until(wsd, "error", fail_on_error=False)
    assert err["kind"] == "error" and "teleport destination" in err["payload"]["msg"]
    assert _row(tok)["floor"] == ""


# ---------- 6. hidden sealed upper-plane token is never delivered (R7) -------

def test_hidden_sealed_plane_token_not_delivered(client):
    """A token on a plane that is SOLIDLY sealed from the viewer's plane must not
    appear in that viewer's server-computed /state at all — and not via an
    explicit ?floor= request either. This is the delivery channel, not the canvas."""
    dm, player, code, _ = base_room(client)
    _add(client, dm, code, "crypt")
    set_floor_grid(client, dm, code, "crypt", lambda g: g.update(cells=[0] * len(g["cells"])))
    with ws_connect(client, dm, code) as wsd:
        wsd.send_json({"type": "add_token", "label": "Lurker", "floor": "crypt",
                       "x": 16.5 * CELL, "y": 12.5 * CELL, "size": "Medium"})
        hidden = recv_until(wsd, "token_add")["payload"]["id"]
        wsd.send_json({"type": "add_token", "label": "Marker",
                       "x": 8.5 * CELL, "y": 8.5 * CELL, "size": "Medium"})
        marker = recv_until(wsd, "token_add")["payload"]["id"]
    ids = {t["id"] for t in state_of(client, player, code)["tokens"]}
    assert marker in ids                      # ground marker reaches the player
    assert hidden not in ids                  # sealed upper-plane token: invisible
    r = client.get(f"/api/rooms/{code}/state?floor=crypt", headers=H(player))
    assert r.status_code in (200, 403)        # either way it must not leak
    if r.status_code == 200:
        assert hidden not in {t["id"] for t in r.json().get("tokens", [])}


# ---------- 7. flight can't keep going after the turn ends -------------------

def test_flyer_cannot_move_out_of_turn(client):
    dm, player, code, _ = base_room(client)
    _add(client, dm, code, "A")
    pid = state_of(client, player, code)["me"]
    with ws_connect(client, dm, code) as wsd:
        flyer = add_npc(wsd, "Sky", cx=16, cy=12)
    _as_flyer(client, dm, code, flyer, pid)
    _activate(client, dm, code, flyer)                    # flyer is on turn
    with ws_connect(client, player, code) as wsp:
        wsp.send_json({"type": "move", "token_id": flyer, "tx": 16, "ty": 12,
                       "floor": "A", "mode": "fly"})
        for _ in range(16):
            if recv_until(wsp, "move_state")["payload"].get("moving") is False:
                break
    with ws_connect(client, dm, code) as wsd:             # turn moves on
        wsd.send_json({"type": "init_next"})
        recv_until(wsd, "initiative")
    with ws_connect(client, player, code) as wsp:
        wsp.send_json({"type": "move", "token_id": flyer, "tx": 16, "ty": 12,
                       "floor": "", "mode": "fly"})
        err = recv_until(wsp, "error", fail_on_error=False)
    assert err["kind"] == "error" and "not your turn" in err["payload"]["msg"]
