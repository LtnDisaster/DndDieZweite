"""D87 — lighting: dark rooms where sight comes from carried light only.

The dark flag is DM-owned (map_edit), the radius is per token (token_light).
Proven here:
  * dark + light 0 = you see your own footprint and nothing else;
  * light opens an LOS-limited bubble — walls still cast shadows;
  * DMs are never restricted; non-dark rooms behave exactly as before;
  * light changes re-evaluate every viewer (add on gain, leave on loss);
  * a stale editor snapshot must not silently flip darkness;
  * hidden tokens leak neither radius nor plane.
"""
import pytest
from starlette.testclient import TestClient

from app import db, main
from tests.test_movement_fog import (H, add_npc, base_room, recv_until,
                                     room_with_wall, state_of, ws_connect)


@pytest.fixture()
def client():
    return TestClient(main.app)


def _set_dark(client, dm, code, dark):
    grid = state_of(client, dm, code)["grid"]
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "map_edit", "map": {**grid, "dark": dark}, "dark": dark})
        recv_until(ws, "map_changed")


def _player_token(client, player, code):
    return [t for t in state_of(client, player, code)["tokens"]
            if t.get("owner_user_id") is not None][0]["id"]


def test_dark_blinds_lightless_but_not_the_floor(client):
    dm, player, code, ch = base_room(client)
    far = None
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "add_token", "label": "Far", "x": 22.5 * 50, "y": 12.5 * 50})
        far = recv_until(ws, "token_add")["payload"]["id"]
    _set_dark(client, dm, code, True)
    st = state_of(client, player, code)
    assert st["grid"]["dark"] is True
    assert not [t for t in st["tokens"] if t["id"] == far]      # dark = blind
    mine = [t for t in st["tokens"] if t["id"] != far]
    assert mine                                                  # own token remains
    st_dm = state_of(client, dm, code)                           # DM unrestricted
    assert [t for t in st_dm["tokens"] if t["id"] == far]


def test_light_opens_the_world_walls_still_shadow(client):
    dm, player, code, ch = room_with_wall(client, wall_x=10)
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "add_token", "label": "Near", "x": 8.5 * 50, "y": 6.5 * 50})
        near = recv_until(ws, "token_add")["payload"]["id"]
        ws.send_json({"type": "add_token", "label": "Behind", "x": 12.5 * 50, "y": 6.5 * 50})
        behind = recv_until(ws, "token_add")["payload"]["id"]
    _set_dark(client, dm, code, True)
    mine = _player_token(client, player, code)
    with ws_connect(client, player, code) as wsp:
        wsp.send_json({"type": "token_light", "token_id": mine, "radius": 6})
        ev = None
        while ev is None or ev.get("kind") not in ("token_light", "error"):
            ev = wsp.receive_json()
        assert ev["kind"] == "token_light" and ev["payload"]["radius"] == 6
        st = state_of(client, player, code)
        ids = {t["id"] for t in st["tokens"]}
        assert near in ids                    # inside the lit, open bubble
        assert behind not in ids              # the wall casts its shadow
        assert db.q1("SELECT light FROM tokens WHERE id=?", (mine,))["light"] == 6


def test_light_loss_sends_token_leave(client):
    dm, player, code, ch = base_room(client)
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "add_token", "label": "Lantern-far", "x": 12.5 * 50, "y": 2.5 * 50})
        far = recv_until(ws, "token_add")["payload"]["id"]
    _set_dark(client, dm, code, True)
    mine = _player_token(client, player, code)
    with ws_connect(client, player, code) as wsp:
        wsp.send_json({"type": "token_light", "token_id": mine, "radius": 8})
        got = []
        while True:
            e = wsp.receive_json()
            got.append(e["kind"])
            if e["kind"] == "grid_reveal":
                break
        assert far in {t["id"] for t in state_of(client, player, code)["tokens"]}
        wsp.send_json({"type": "token_light", "token_id": mine, "radius": 0})
        got = []
        while True:
            e = wsp.receive_json()
            got.append(e["kind"])
            if e["kind"] == "token_leave" and e["payload"]["token_id"] == far:
                break
            if len(got) > 40:
                pytest.fail(f"never left; saw {got}")


def test_darkness_is_explicit_never_from_stale_snapshots(client):
    dm, player, code, _ = base_room(client)
    _set_dark(client, dm, code, True)
    grid = state_of(client, dm, code)["grid"]
    assert grid["dark"] is True
    with ws_connect(client, dm, code) as ws:
        # a stale editor snapshot WITHOUT the dark field must not flip it back
        stale = {k: v for k, v in grid.items() if k != "dark"}
        ws.send_json({"type": "map_edit", "map": stale})
        recv_until(ws, "map_changed")
    assert state_of(client, player, code)["grid"]["dark"] is True


def test_nondark_rooms_keep_classic_vision_and_hidden_tokens_stay_quiet(client):
    dm, player, code, _ = room_with_wall(client, wall_x=10)
    with ws_connect(client, dm, code) as ws:
        hid = add_npc(ws, label="Below", cx=15, cy=13)
        ws.send_json({"type": "token_light", "token_id": hid, "radius": 12})
        assert recv_until(ws, "token_light")["payload"]["radius"] == 12
    st = state_of(client, player, code)
    row = [t for t in st["tokens"] if t["id"] == hid]
    assert not row or (row[0].get("light") in (None,) and row[0].get("floor") in (None, ""))
    assert st["grid"].get("dark") is False          # default untouched
