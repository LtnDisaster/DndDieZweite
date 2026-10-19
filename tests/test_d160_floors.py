"""D160 — floor removal must not silently renumber the stack.

Signed levels are POSITIONAL (floors.level_map). Deleting a MIDDLE storey would
pull every plane beyond it one level toward the primary and could newly-JOIN
planes a removed slab used to keep apart. D160 refuses it: a floor is removable
only when it is the outermost on its side, so survivors keep their level, their
standing tokens and their stored plane maps byte-for-byte.

These drive the REAL production path (DELETE /rooms/{code}/floors/{name} ->
FLOOR.remove) and assert stored state, not UI.
"""
import pytest
from starlette.testclient import TestClient

from app import db, floors
from app import main
from tests.test_movement_fog import H, base_room, recv_until, state_of, ws_connect


@pytest.fixture()
def client():
    return TestClient(main.app)


def _rid(code):
    return db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]


def _add(client, dm, code, name, below=False, ground=True):
    r = client.post(f"/api/rooms/{code}/floors",
                    json={"name": name, "below": below}, headers=H(dm))
    assert r.status_code == 200, r.text
    if ground:                                     # D159: air default -> lay a slab
        grid = client.get(f"/api/rooms/{code}/state?floor={name}",
                          headers=H(dm)).json()["grid"]
        grid["cells"] = [0] * len(grid["cells"])
        with ws_connect(client, dm, code) as ws:
            ws.send_json({"type": "map_edit", "map": grid, "floor": name})
            recv_until(ws, "map_changed")
    return r.json()


def _marker(client, dm, code, floor, idx, val):
    """Bake a distinctive terrain value into a plane so a later removal cannot
    quietly rewrite the stored map without the diff being caught."""
    grid = client.get(f"/api/rooms/{code}/state?floor={floor}", headers=H(dm)).json()["grid"]
    grid["cells"][idx] = val
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "map_edit", "map": grid, "floor": floor})
        recv_until(ws, "map_changed")


def _stored_map(code, floor):
    row = db.q1("SELECT map_json FROM floor_maps WHERE room_id=? AND floor=?",
                (_rid(code), floor))
    return row["map_json"] if row else None


def _add_token(client, dm, code, floor, x, y, label):
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "add_token", "label": label, "x": x, "y": y, "floor": floor})
        tid = recv_until(ws, "token_add")["payload"]["id"]
    return tid


def _token(tid):
    t = db.q1("SELECT floor, x, y, label FROM tokens WHERE id=?", (tid,))
    return (t["floor"], t["x"], t["y"], t["label"]) if t else None


def test_middle_floor_removal_refused_state_unchanged(client):
    dm, _player, code, _ch = base_room(client)
    _add(client, dm, code, "Attic")
    _add(client, dm, code, "Roof")
    _add(client, dm, code, "Cellar", below=True)

    # distinctive stored maps; the token stands on the UPPER floor 'Roof' while
    # the MIDDLE 'Attic' is empty — deleting Attic would renumber Roof (+2 -> +1)
    # under a standing token and could newly-join it to the ground.
    _marker(client, dm, code, "Attic", 5, 1)
    _marker(client, dm, code, "Roof", 7, 1)
    tok_r = _add_token(client, dm, code, "Roof", 5.5 * 50, 6.5 * 50, "R")

    lm0 = state_of(client, dm, code)["floor_levels"]
    assert lm0 == {"": 0, "Attic": 1, "Roof": 2, "Cellar": -1}
    map_a0, map_r0 = _stored_map(code, "Attic"), _stored_map(code, "Roof")
    tok_r0 = _token(tok_r)
    assert map_a0 and map_r0 and map_a0 != map_r0
    assert tok_r0[0] == "Roof"

    # deleting the empty MIDDLE above-floor 'Attic' (Roof is above it) is refused,
    # with an understandable reason — not a silent no-op.
    r = client.delete(f"/api/rooms/{code}/floors/Attic", headers=H(dm))
    assert r.status_code == 400
    reason = r.json()["detail"]
    assert "Roof" in reason and "above" in reason

    # nothing moved, nothing renumbered, no stored map touched.
    assert state_of(client, dm, code)["floor_levels"] == lm0
    assert _stored_map(code, "Attic") == map_a0
    assert _stored_map(code, "Roof") == map_r0
    assert _token(tok_r) == tok_r0

    # the DM can still tear the stack down OUTSIDE-IN; each removal is legal and
    # leaves the survivors' levels correct.
    _move_off(client, dm, code, tok_r, "")
    assert client.delete(f"/api/rooms/{code}/floors/Roof", headers=H(dm)).status_code == 200
    assert _stored_map(code, "Attic") == map_a0          # untouched by Roof's removal
    assert client.delete(f"/api/rooms/{code}/floors/Attic", headers=H(dm)).status_code == 200
    after = state_of(client, dm, code)["floor_levels"]
    assert after == {"": 0, "Cellar": -1}                 # below-plane level kept
    assert db.q1("SELECT 1 AS h FROM floor_maps WHERE room_id=? AND floor='Cellar'",
                 (_rid(code),)) is not None               # cellar map survived


def _move_off(client, dm, code, tok, dest):
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "token_floor", "token_id": tok, "floor": dest})
        recv_until(ws, "token_floor")


def test_below_middle_removal_refused(client):
    dm, _player, code, _ch = base_room(client)
    _add(client, dm, code, "Cellar", below=True)
    _add(client, dm, code, "Tomb", below=True)          # deeper cellar, level -2

    lm0 = state_of(client, dm, code)["floor_levels"]
    assert lm0 == {"": 0, "Cellar": -1, "Tomb": -2}

    # 'Cellar' is not the bottommost floor ('Tomb' is deeper) -> refused.
    r = client.delete(f"/api/rooms/{code}/floors/Cellar", headers=H(dm))
    assert r.status_code == 400
    reason = r.json()["detail"]
    assert "Tomb" in reason and "below" in reason
    assert state_of(client, dm, code)["floor_levels"] == lm0

    # bottom-up teardown works.
    assert client.delete(f"/api/rooms/{code}/floors/Tomb", headers=H(dm)).status_code == 200
    assert client.delete(f"/api/rooms/{code}/floors/Cellar", headers=H(dm)).status_code == 200
    assert state_of(client, dm, code)["floor_levels"] == {"": 0}


def test_removal_rule_at_unit_level():
    # The positional level model the guard protects (storage mutation is proven
    # end-to-end through the REST route in the tests above).
    import json
    room = {"floors": json.dumps({"below": ["Cellar", "Tomb"], "above": ["Attic", "Roof"]})}
    assert floors.level_map(room) == {"": 0, "Cellar": -1, "Tomb": -2, "Attic": 1, "Roof": 2}
    assert floors.order(room) == ["Tomb", "Cellar", "", "Attic", "Roof"]
