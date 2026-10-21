"""D158 — every card-editing tool acts on ONE plane, and only that plane.

The floor rail reuses the existing state.viewFloor SSOT and the existing
per-plane maps (net.get_map/set_map + floor_maps). This is the server-side
proof that the isolation is real, independent of any browser:

  * editing a named floor persists to that floor's map and NEVER the primary;
  * a later edit on the primary never disturbs the named floor;
  * the change survives a reload (a fresh /state?floor= shows it), so the
    "active floor only" rule is persistence truth, not a client illusion.
"""
import copy
import json

import pytest
from starlette.testclient import TestClient

from app import db
from app.main import app
from app.room import net
from tests.test_movement_fog import H, recv_until, reg, ws_connect


@pytest.fixture()
def client():
    return TestClient(app)


def _make_room(client, tag):
    dm = reg(client, f"dm{tag}")
    code = client.post("/api/rooms", json={"name": f"Room {tag}"}, headers=H(dm)).json()["code"]
    room_id = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
    return dm, code, room_id


def _add_floor(client, dm, code, name):
    r = client.post(f"/api/rooms/{code}/floors", json={"name": name}, headers=H(dm))
    assert r.status_code == 200, r.text
    assert name in r.json()["floors"], r.text


def test_editing_a_named_floor_touches_only_that_floor(client):
    dm, code, room_id = _make_room(client, "Iso")
    _add_floor(client, dm, code, "crypt")

    primary = net.get_map(room_id, "")
    w, h = primary["w"], primary["h"]
    cells_before = list(primary["cells"])
    assert w * h > 4, "map too small to hold two distinct edit cells"
    idx_a = 1 * w + 1
    idx_b = 2 * w + 2

    crypt_edit = json.loads(json.dumps(primary))
    crypt_edit["cells"][idx_a] = 1                     # one wall on the crypt
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "map_edit", "map": crypt_edit, "floor": "crypt"})
        recv_until(ws, "map_changed")

    crypt = net.get_map(room_id, "crypt")
    assert crypt["cells"][idx_a] == 1, "the crypt edit never reached the named floor"
    # the primary plane is byte-identical to before — a floor edit cannot leak up
    assert list(net.get_map(room_id, "")["cells"]) == cells_before, "primary was disturbed"

    # persistence: a fresh snapshot of that floor shows the wall
    st = client.get(f"/api/rooms/{code}/state?floor=crypt", headers=H(dm))
    assert st.status_code == 200, st.text
    assert st.json()["grid"]["cells"][idx_a] == 1, "the named-floor edit did not survive reload"

    # a later edit on the primary must not disturb the crypt
    primary_edit = json.loads(json.dumps(net.get_map(room_id, "")))
    primary_edit["cells"][idx_b] = 1
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "map_edit", "map": primary_edit, "floor": ""})
        recv_until(ws, "map_changed")

    assert net.get_map(room_id, "")["cells"][idx_b] == 1, "primary edit did not land"
    after_crypt = net.get_map(room_id, "crypt")
    assert after_crypt["cells"][idx_a] == 1, "the crypt lost its own edit"
    assert after_crypt["cells"][idx_b] == cells_before[idx_b], "primary edit leaked into the crypt"


def test_edit_on_unknown_floor_is_refused(client):
    dm, code, room_id = _make_room(client, "NoFl")
    primary = net.get_map(room_id, "")
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "map_edit", "map": copy.deepcopy(primary), "floor": "ghost"})
        recv_until(ws, "error", fail_on_error=False)
    assert net.get_map(room_id, "")["cells"] == primary["cells"], "a refused edit changed the map"


def test_players_cannot_map_edit_any_floor(client):
    from app import mapmodel
    dm, code, room_id = _make_room(client, "PLedit")
    _add_floor(client, dm, code, "crypt")
    pl = reg(client, "plEdit")
    client.post("/api/rooms/join", json={"code": code}, headers=H(pl))
    crypt_before = net.get_map(room_id, "crypt")
    # D159: a never-edited named plane is open AIR, NOT a copy of the primary
    # floor — the old "blank plane == primary floor" premise is gone by design.
    assert crypt_before["cells"] == [mapmodel.AIR] * len(crypt_before["cells"])
    primary = net.get_map(room_id, "")
    with ws_connect(client, pl, code) as ws:
        ws.send_json({"type": "map_edit", "map": copy.deepcopy(primary), "floor": "crypt"})
        recv_until(ws, "error", fail_on_error=False)
    # nothing written to the named floor by a player: the plane is untouched
    assert net.get_map(room_id, "crypt")["cells"] == crypt_before["cells"]
