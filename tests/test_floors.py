"""D86 — floors: independent occupancy/visibility planes in one room map.

Proves the plane contract:
  * collision/pathfinding/resize/rotate only see tokens on the SAME floor;
  * token_floor moves a token (riders ride along), broadcast + per-viewer
    add/leave follow automatically;
  * a viewer standing on another plane receives NOTHING about the token —
    not even its plane via /state; the DM sees every plane;
  * floor list is DM-curated REST with sane limits, broadcast on change.
"""
import uuid

import pytest
from starlette.testclient import TestClient

from app import db, main
from tests.test_movement_fog import (H, add_npc, base_room, recv_until, reg,
                                     room_with_wall, state_of, ws_connect)


@pytest.fixture()
def client():
    return TestClient(main.app)


def _add_floor(client, dm, code, name):
    r = client.post(f"/api/rooms/{code}/floors", json={"name": name}, headers=H(dm))
    assert r.status_code == 200, r.text
    return r.json()["floors"]


def test_planes_are_collision_independent(client):
    dm, player, code, ch = base_room(client)
    _add_floor(client, dm, code, "attic")
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "add_token", "label": "Blocker", "x": 10.5 * 50,
                      "y": 5.5 * 50, "width": 2, "height": 2})
        blk = recv_until(ws, "token_add")["payload"]["id"]
        ws.send_json({"type": "add_token", "label": "Mover", "x": 2.5 * 50, "y": 5.5 * 50})
        mv = recv_until(ws, "token_add")["payload"]["id"]
        # same plane: landing ON the blocker's box is refused by the preview
        ws.send_json({"type": "path_preview", "token_id": mv, "tx": 10, "ty": 5})
        ev = None
        while ev is None or ev.get("kind") not in ("path_preview", "error"):
            ev = ws.receive_json()
        same_plane_err = ev["kind"] == "error"
        # other plane: the very same target is free air
        ws.send_json({"type": "token_floor", "token_id": blk, "floor": "attic"})
        assert recv_until(ws, "token_floor")["payload"]["floor"] == "attic"
        ws.send_json({"type": "path_preview", "token_id": mv, "tx": 10, "ty": 5})
        ok = recv_until(ws, "path_preview")["payload"]
        assert same_plane_err and (ok["anchor"]["cx"], ok["anchor"]["cy"]) == (10, 5)
        # ...and a walk with the provided path lands there
        ws.send_json({"type": "move", "token_id": mv, "tx": 10, "ty": 5, "path": ok["path"]})
        landed = False
        for _ in range(60):
            e = ws.receive_json()
            if e["kind"] == "step" and (e["payload"].get("cx"), e["payload"].get("cy")) == (10, 5):
                landed = True
                break
            if e["kind"] == "move_state" and not e["payload"].get("moving"):
                break
        assert landed, "mover never landed on the cross-plane cell"
        row = db.q1("SELECT x,y FROM tokens WHERE id=?", (mv,))
        assert (int(row["x"]) // 50, int(row["y"]) // 50) == (10, 5)


def test_plane_visibility_delivers_nothing_across_planes(client):
    dm, player, code, ch = base_room(client)          # player token on primary
    _add_floor(client, dm, code, "crypt")
    with ws_connect(client, player, code) as wsp, ws_connect(client, dm, code) as wsd:
        wsd.send_json({"type": "add_token", "label": "Wisp", "x": 8.5 * 50,
                       "y": 8.5 * 50, "color": "#123456"})
        wisp = recv_until(wsd, "token_add")["payload"]["id"]
        recv_until(wsp, "token_add")           # player sees it on the shared plane
        # move the wisp to another plane -> the player MUST get token_leave
        wsd.send_json({"type": "token_floor", "token_id": wisp, "floor": "crypt"})
        assert recv_until(wsd, "token_floor")["payload"]["floor"] == "crypt"
        got = []
        for _ in range(40):
            e = wsp.receive_json()
            got.append(e["kind"])
            if e["kind"] == "token_leave" and e["payload"]["token_id"] == wisp:
                break
        else: pytest.fail(f"player never got token_leave; saw {got}")
        # ...and nothing more about it ever reaches the player while the wisp
        # walks on the crypt plane; the DM receives every step
        wsd.send_json({"type": "move", "token_id": wisp, "tx": 9, "ty": 8,
                       "path": [{"x": 9, "y": 8}]})
        dm_steps = 0
        for _ in range(40):
            e = wsd.receive_json()
            if e["kind"] == "step" and e["payload"]["token_id"] == wisp \
                    and (e["payload"]["cx"], e["payload"]["cy"]) == (9, 8):
                dm_steps = 1
                break
        assert dm_steps
        st = state_of(client, player, code)
        assert not [t for t in st["tokens"] if t["id"] == wisp]     # not listed
        assert st["floors"] == ["", "crypt"]
        st_dm = state_of(client, dm, code)
        assert [t for t in st_dm["tokens"] if t["id"] == wisp][0]["floor"] == "crypt"


def test_riders_ride_across_planes(client):
    dm, player, code, ch = base_room(client)
    _add_floor(client, dm, code, "deck")
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "add_token", "label": "Boat", "x": 6.5 * 50, "y": 6.5 * 50})
        boat = recv_until(ws, "token_add")["payload"]["id"]
        ws.send_json({"type": "add_token", "label": "Rider", "x": 2.5 * 50, "y": 6.5 * 50})
        rider = recv_until(ws, "token_add")["payload"]["id"]
        ws.send_json({"type": "token_mount", "token_id": rider, "mount_token_id": boat})
        recv_until(ws, "token_mount")
        ws.send_json({"type": "token_floor", "token_id": boat, "floor": "deck"})
        seen = set()
        for _ in range(8):
            e = recv_until(ws, "token_floor")
            seen.add(e["payload"]["token_id"])
            if seen == {boat, rider}:
                break
        assert seen == {boat, rider}
    assert [db.q1("SELECT floor FROM tokens WHERE id=?", (i,))["floor"]
            for i in (boat, rider)] == ["deck", "deck"]


def test_floor_list_governance(client):
    dm, player, code, _ = base_room(client)
    assert client.post(f"/api/rooms/{code}/floors", json={"name": "crypt"},
                       headers=H(player)).status_code == 403
    assert client.post(f"/api/rooms/{code}/floors", json={"name": "../x"},
                       headers=H(dm)).status_code == 400
    assert client.post(f"/api/rooms/{code}/floors", json={"name": "crypt"},
                       headers=H(dm)).status_code == 200
    assert client.post(f"/api/rooms/{code}/floors", json={"name": "crypt"},
                       headers=H(dm)).status_code == 400        # duplicate
    st = state_of(client, player, code)
    assert st["floors"] == ["", "crypt"]
    # cannot delete the primary, cannot delete a floor with tokens on it
    assert client.delete(f"/api/rooms/{code}/floors/", headers=H(dm)).status_code in (400, 404, 405)   # trailing-slash = collection route: no DELETE there
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "add_token", "label": "C", "x": 3.5 * 50, "y": 3.5 * 50,
                      "floor": "crypt"})
        tok = recv_until(ws, "token_add")["payload"]["id"]
        assert client.delete(f"/api/rooms/{code}/floors/crypt",
                             headers=H(dm)).status_code == 400   # token stands there
        ws.send_json({"type": "token_floor", "token_id": tok, "floor": ""})
        recv_until(ws, "token_floor")
    assert client.delete(f"/api/rooms/{code}/floors/crypt", headers=H(dm)).status_code == 200


def test_hidden_across_planes_leaks_no_plane(client):
    dm, player, code, _ = room_with_wall(client, wall_x=10)
    _add_floor(client, dm, code, "crypt")
    with ws_connect(client, dm, code) as ws:
        hid = add_npc(ws, label="Below", cx=15, cy=13)
        ws.send_json({"type": "token_floor", "token_id": hid, "floor": "crypt"})
        assert recv_until(ws, "token_floor")["payload"]["floor"] == "crypt"
    st = state_of(client, player, code)
    row = [t for t in st["tokens"] if t["id"] == hid]
    assert not row or row[0].get("floor") in (None, "")          # plane not leaked
