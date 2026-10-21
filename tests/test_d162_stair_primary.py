"""D162-1 — stairs back to the PRIMARY plane are authorable and validated.

D161 P2-8: the primary floor's true name is "" and the editor demanded a
non-empty target ("Stairs need a target floor name"), so a stair DOWN to the
ground floor could never be created — the descent was one-way. The server
always accepted an op.floor of "" (floors.exists; mapmodel keeps the key); the
gap was the authoring UI plus the missing save-time validation for dangling
targets. Here: E-1 -> E0, E0 -> E-1, E+1 -> E0 all work through the real
connector; a NEW dangling stair target is refused at save time with an
understandable message; a pre-existing dangling stair keeps saving (legacy
maps stay compatible); a primary-target stair survives reload.
"""
import pytest
from starlette.testclient import TestClient

from app import db
from app.room import net as room_net
from tests.test_floor_maps import CELL, add_floor, set_floor_grid, state_floor
from tests.test_movement_fog import H, base_room, recv_until, state_of, ws_connect


@pytest.fixture()
def client():
    from app import main
    return TestClient(main.app)


def mine_of(client, player, code):
    return [t for t in state_of(client, player, code)["tokens"]
            if t.get("owner_user_id") is not None][0]


def hop(client, dm, code, tok_id, floor):
    """DM plane hop (token_floor) — the audit-proven DM-only channel."""
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "token_floor", "token_id": tok_id, "floor": floor})
        recv_until(ws, "token_floor")


def place_stair(client, dm, code, on_floor, obj_id, x, y, to_floor, tx, ty):
    def mutate(g):
        g["objects"] = (g.get("objects") or []) + [{
            "id": obj_id, "label": "Test stair", "x": x, "y": y,
            "interact": {"op": {"kind": "stair", "floor": to_floor,
                                "x": tx, "y": ty}}}]
    set_floor_grid(client, dm, code, on_floor, mutate)


def use_stair(client, player, code, obj_id, on_floor):
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "interact", "object_id": obj_id, "floor": on_floor})
        while True:
            ev = ws.receive_json()
            if ev.get("kind") in ("token_floor", "error"):
                return ev


def edit_expect(client, dm, code, grid):
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "map_edit", "map": grid})
        ev = ws.receive_json()
        while ev.get("kind") not in ("map_changed", "error"):
            ev = ws.receive_json()
        return ev


# ---------- the three directions through the primary plane ----------

def test_stair_from_cellar_back_to_primary(client):
    """E-1 -> E0: the descent that D161 could not author now works."""
    dm, player, code, _ = base_room(client)
    add_floor(client, dm, code, "Cellar")
    mine = mine_of(client, player, code)
    cx, cy = int(mine["x"] // CELL), int(mine["y"] // CELL)
    hop(client, dm, code, mine["id"], "Cellar")
    place_stair(client, dm, code, "Cellar", "stBack", cx + 1, cy, "", cx, cy)
    ev = use_stair(client, player, code, "stBack", "Cellar")
    assert ev["kind"] == "token_floor", ev
    assert ev["payload"]["floor"] == ""
    row = db.q1("SELECT floor, x, y FROM tokens WHERE id=?", (mine["id"],))
    assert row["floor"] == ""
    assert (int(row["x"] // CELL), int(row["y"] // CELL)) == (cx, cy)


def test_stair_from_above_to_primary(client):
    """E+1 -> E0."""
    dm, player, code, _ = base_room(client)
    add_floor(client, dm, code, "Attic")
    mine = mine_of(client, player, code)
    cx, cy = int(mine["x"] // CELL), int(mine["y"] // CELL)
    hop(client, dm, code, mine["id"], "Attic")
    place_stair(client, dm, code, "Attic", "stDown", cx + 1, cy, "", cx, cy)
    ev = use_stair(client, player, code, "stDown", "Attic")
    assert ev["kind"] == "token_floor", ev
    assert ev["payload"]["floor"] == ""
    assert db.q1("SELECT floor FROM tokens WHERE id=?", (mine["id"],))["floor"] == ""


def test_stair_from_primary_to_cellar(client):
    """E0 -> E-1 (negative levels stay supported)."""
    dm, player, code, _ = base_room(client)
    add_floor(client, dm, code, "Under")
    mine = mine_of(client, player, code)
    cx, cy = int(mine["x"] // CELL), int(mine["y"] // CELL)
    place_stair(client, dm, code, "", "stDown2", cx + 1, cy, "Under", cx + 4, cy)
    ev = use_stair(client, player, code, "stDown2", "")
    assert ev["kind"] == "token_floor", ev
    assert ev["payload"]["floor"] == "Under"
    assert db.q1("SELECT floor FROM tokens WHERE id=?", (mine["id"],))["floor"] == "Under"


# ---------- save-time validation ----------

def test_new_dangling_stair_is_refused_at_save(client):
    dm, player, code, _ = base_room(client)
    grid = state_of(client, dm, code)["grid"]
    grid["objects"] = (grid.get("objects") or []) + [{
        "id": "stBad", "label": "Nether stair", "x": 2, "y": 2,
        "interact": {"op": {"kind": "stair", "floor": "Nether", "x": 3, "y": 3}}}]
    ev = edit_expect(client, dm, code, grid)
    assert ev["kind"] == "error", ev
    msg = ev["payload"]["msg"].lower()
    assert "nether" in msg and "floor" in msg
    ids = [o.get("id") for o in state_of(client, dm, code)["grid"].get("objects", [])]
    assert "stBad" not in ids


def test_primary_stair_target_saves_and_validates(client):
    """The save gate must NOT refuse the empty target — "" is a real floor."""
    dm, player, code, _ = base_room(client)
    place_stair(client, dm, code, "", "stOK", 2, 2, "", 3, 3)
    ids = [o.get("id") for o in state_of(client, dm, code)["grid"].get("objects", [])]
    assert "stOK" in ids


def test_legacy_dangling_stair_keeps_saving(client):
    """Compatibility: a map that already carries a dangling stair (pre-D162
    authoring) must not become un-savable."""
    dm, player, code, _ = base_room(client)
    room_id = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
    mp = room_net.get_map(room_id, "")
    mp["objects"] = (mp.get("objects") or []) + [{
        "id": "stLegacy", "label": "Old dangling", "x": 1, "y": 1,
        "interact": {"op": {"kind": "stair", "floor": "Nether", "x": 2, "y": 2}}}]
    room_net.set_map(room_id, mp, "")          # seed bypassing the editor gate
    grid = state_of(client, dm, code)["grid"]  # server view carries stLegacy
    assert "stLegacy" in [o.get("id") for o in grid.get("objects", [])]
    ev = edit_expect(client, dm, code, grid)   # unchanged re-save of same map
    assert ev["kind"] == "map_changed", ev
    ids2 = [o.get("id") for o in state_of(client, dm, code)["grid"].get("objects", [])]
    assert "stLegacy" in ids2


def test_primary_target_stair_persists_across_reload(client):
    """op.floor == "" survives save + /state reload byte-true (key present)."""
    dm, player, code, _ = base_room(client)
    add_floor(client, dm, code, "Crypt2")
    place_stair(client, dm, code, "Crypt2", "stP", 3, 3, "", 4, 4)
    g3 = state_floor(client, dm, code, "Crypt2")["grid"]
    st3 = [o for o in g3.get("objects", []) if o.get("id") == "stP"]
    assert st3
    op = st3[0]["interact"]["op"]
    assert op["kind"] == "stair" and "floor" in op and op["floor"] == ""


# ---------- editor wiring (static pins, D161 test style) ----------

def read(p):
    return open(p, encoding="utf-8").read()


def test_editor_offers_primary_as_stair_target():
    html = read("app/static/index.html")
    assert '<select id="obj-tfl"' in html, "stair target must be a real select"
    js_main = read("app/static/js/60_main.js")
    assert "fillStairFloors()" in js_main, "op=stair must populate the floor list"
    js_room = read("app/static/js/30_room.js")
    assert "function fillStairFloors" in js_room
    assert "floorLabelOf" in js_room.split("function fillStairFloors")[1][:600], \
        "the primary must render under its shared label, not as an empty box"
    js_canvas = read("app/static/js/50_canvas.js")
    assert "Stairs need a target floor name" not in js_canvas, \
        "the D161 P2-8 blocker toast must be gone"


def test_server_validates_stair_targets_with_legacy_tolerance():
    py = read("app/room/dispatch.py")
    assert "legacy_dangling" in py
    assert "Stairs point at a floor that does not exist" in py
