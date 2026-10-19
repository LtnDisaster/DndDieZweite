"""D159 — open-volume floors, signed levels, free 3D flight.

D159 changed the *meaning* of the vertical geometry without touching stored
data: the primary floor stays the default standable plane, every other
never-edited plane is now genuine open AIR (terrain 6) instead of an invisible
copy of the primary floor, and levels became signed (a cellar can sit *below*
the primary at -1/-2/…). A laid floor is a solid slab that caps its column and
blocks sight + vertical movement through the surface; only a real opening
(`openv` punched in the plane below, or an air/void cell above) lets a body or a
line of sight through.

These tests are the additive proof of that new truth: defaults, signed/below
levels, massive-slab occlusion, openv openings, a whole-volume multi-storey
flight route and its server-authoritative execution, and byte-compatibility of
explicitly stored maps. Existing D114 vertical suites were updated to lay real
slabs where they assumed a solid ceiling; nothing here re-weakens them.
"""
import pytest
from starlette.testclient import TestClient

from app import db, mapmodel, path as P
from app.main import app
from app.room import vertical3d
from app.room import net
from tests.test_floor_maps import cell_idx, set_floor_grid
from tests.test_movement_fog import (H, add_npc, base_room, recv_until,
                                     state_of, ws_connect)

CELL = 50


@pytest.fixture()
def client():
    return TestClient(app)


def rid(client, code):
    return db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]


def token_at(r, floor, cx, cy, **extra):
    mp = net.get_map(r, floor)
    return {"id": extra.pop("id", 1), "room_id": r, "floor": floor,
            "size": "Medium", "x": (cx + .5) * mp["cell"],
            "y": (cy + .5) * mp["cell"], "z": 0, "height_ft": None,
            "elevation_ft": 0, **extra}


def paint(map_name, cx, cy, *, cells=None, openv=None):
    if cells is not None:
        map_name["cells"][cell_idx(map_name, cx, cy)] = cells
    if openv is not None:
        map_name.setdefault("openv", [0] * map_name["w"] * map_name["h"])[
            cell_idx(map_name, cx, cy)] = openv


# ---------- A — the new defaults -------------------------------------------

def test_named_plane_defaults_to_open_air(client):
    """A never-edited named plane is open AIR, NOT a copy of the primary."""
    dm, _, code, _ = base_room(client)
    r = rid(client, code)
    assert client.post(f"/api/rooms/{code}/floors", json={"name": "crypt"},
                       headers=H(dm)).status_code == 200
    crypt = net.get_map(r, "crypt")
    primary = net.get_map(r, "")
    assert set(crypt["cells"]) == {mapmodel.AIR}, "a fresh plane must be all air"
    assert set(primary["cells"]) <= {0, 1}, "the primary keeps its floor/wall map"


def test_air_is_not_walkable_but_is_open_volume(client):
    """air(6) never blocks movement/vision and is not a slab, yet you cannot
    stand on it — a walker needs a floor, a flyer only needs open volume."""
    assert mapmodel.TERRAIN[mapmodel.AIR]["name"] == "air"
    assert mapmodel.walkable(mapmodel.AIR) is False
    assert mapmodel.blocks_movement(mapmodel.AIR) is False
    assert mapmodel.blocks_vision(mapmodel.AIR) is False
    assert mapmodel.body_open(mapmodel.AIR) is True
    assert mapmodel.is_open_volume(mapmodel.AIR) is True
    assert mapmodel.slab(mapmodel.AIR) is False


# ---------- B — signed levels and below-floors ------------------------------

def test_signed_levels_and_below_floors(client):
    dm, _, code, _ = base_room(client)
    r = rid(client, code)
    a = client.post(f"/api/rooms/{code}/floors", json={"name": "Attic"},
                    headers=H(dm)).json()
    client.post(f"/api/rooms/{code}/floors", json={"name": "Roof"}, headers=H(dm))
    c1 = client.post(f"/api/rooms/{code}/floors", json={"name": "Cellar", "below": True},
                     headers=H(dm))
    assert c1.status_code == 200, c1.text
    c2 = client.post(f"/api/rooms/{code}/floors", json={"name": "Tomb", "below": True},
                     headers=H(dm))
    assert c2.status_code == 200, c2.text

    lm = vertical3d.level_map(r)
    assert lm == {"": 0, "Attic": 1, "Roof": 2, "Cellar": -1, "Tomb": -2}
    # bottom -> top, primary in the middle
    assert vertical3d.floor_list(r) == ["Tomb", "Cellar", "", "Attic", "Roof"]
    assert c2.json()["floors"] == ["Tomb", "Cellar", "", "Attic", "Roof"]
    assert c2.json()["floor_levels"] == lm

    # storage went to the object form once a below-floor exists
    room = db.q1("SELECT floors FROM rooms WHERE id=?", (r,))
    assert isinstance(__import__("json").loads(room["floors"]), dict)
    assert set(lm.values()) == {-2, -1, 0, 1, 2}


# ---------- C — massive slab vs. a real opening -----------------------------

def test_laid_floor_caps_the_column_air_opens_it(client):
    dm, _, code, _ = base_room(client)
    client.post(f"/api/rooms/{code}/floors", json={"name": "crypt"}, headers=H(dm))
    r = rid(client, code)
    maps = vertical3d.maps_for(r)
    cell = (16, 16)
    # primary floor below, crypt open AIR above -> the boundary is open
    assert mapmodel.slab(mapmodel.terrain_at(maps[""], *cell)) is True
    assert vertical3d.boundary_open(maps, "", "crypt", cell) is True
    # author a real crypt slab -> the column is capped (massive floor)
    paint(maps["crypt"], 16, 16, cells=0)
    paint(maps["crypt"], 17, 16, cells=0)
    assert vertical3d.boundary_open(maps, "", "crypt", cell) is False
    # an opening punched in the plane BELOW reopens exactly that column
    paint(maps[""], 16, 16, openv=1)
    assert vertical3d.boundary_open(maps, "", "crypt", cell) is True
    # ... and only that column: the neighbouring slab stays capped
    assert vertical3d.boundary_open(maps, "", "crypt", (17, 16)) is False


def test_solid_slab_blocks_sight_and_vertical_travel(client):
    dm, _, code, _ = base_room(client)
    client.post(f"/api/rooms/{code}/floors", json={"name": "crypt"}, headers=H(dm))
    r = rid(client, code)
    maps = vertical3d.maps_for(r)
    lm = vertical3d.level_map(r)
    cell = (16, 16)
    paint(maps["crypt"], 16, 16, cells=0)                 # solid slab ceiling
    assert vertical3d.cross_plane_sight(maps, lm, "", "crypt", cell) is False
    flyer = token_at(r, "", 16, 16)
    assert vertical3d.vertical_path_clear(r, flyer, "", "crypt", maps, lm) is False
    # punch an opening -> sight and vertical travel go through the very cell
    paint(maps[""], 16, 16, openv=1)
    assert vertical3d.cross_plane_sight(maps, lm, "", "crypt", cell) is True
    assert vertical3d.vertical_path_clear(r, flyer, "", "crypt", maps, lm) is True


def test_air_stack_is_one_continuous_open_volume(client):
    """Two stacked AIR planes are freely joined — no slab anywhere in between."""
    dm, _, code, _ = base_room(client)
    for nm in ("A", "B"):
        client.post(f"/api/rooms/{code}/floors", json={"name": nm}, headers=H(dm))
    r = rid(client, code)
    maps = vertical3d.maps_for(r)
    lm = vertical3d.level_map(r)
    cell = (10, 10)
    assert vertical3d.column_open(maps, lm, "", "B", cell) is True
    tok = token_at(r, "", 10, 10, height_ft=30)           # tall flyer reaches 2 up
    assert vertical3d.body_planes(r, tok, maps, lm) == {"", "A", "B"}


# ---------- D — free 3D flight through the open volume ----------------------

def test_multi_storey_flight_route_exists_through_default_air(client):
    """The D114 A* chained through adjacent open boundaries flies straight up
    THREE storeys with no openings punched — because the planes are air."""
    dm, _, code, _ = base_room(client)
    for nm in ("Upper1", "Upper2"):
        client.post(f"/api/rooms/{code}/floors", json={"name": nm}, headers=H(dm))
    r = rid(client, code)
    maps = vertical3d.maps_for(r)
    lm = vertical3d.level_map(r)
    start, goal = ("", (16, 12)), ("Upper2", (16, 12))

    def state_ok(state):
        return vertical3d.volume_final_valid(
            r, token_at(r, state[0], *state[1]), [], maps, lm)

    def vertical_ok(prev, nxt, cells):
        return vertical3d.vertical_path_clear(
            r, token_at(r, prev[0], *prev[1]), prev[0], nxt[0], maps, lm)

    route = P.find_path_3d(start, goal, maps, lm, (1, 1),
                           vertical_ok=vertical_ok, state_ok=state_ok)
    assert route == [("Upper1", (16, 12)), ("Upper2", (16, 12))]


def test_diagonal_flight_composes_horizontal_and_vertical(client):
    """A diagonal flight (change plane AND position) is legal: the A* composes
    a vertical step with horizontal steps through open air."""
    dm, _, code, _ = base_room(client)
    client.post(f"/api/rooms/{code}/floors", json={"name": "Upper"}, headers=H(dm))
    r = rid(client, code)
    maps = vertical3d.maps_for(r)
    lm = vertical3d.level_map(r)
    start, goal = ("", (10, 10)), ("Upper", (12, 12))

    def state_ok(state):
        return vertical3d.volume_final_valid(
            r, token_at(r, state[0], *state[1]), [], maps, lm)

    def vertical_ok(prev, nxt, cells):
        return vertical3d.vertical_path_clear(
            r, token_at(r, prev[0], *prev[1]), prev[0], nxt[0], maps, lm)

    route = P.find_path_3d(start, goal, maps, lm, (1, 1), mode="fly",
                           vertical_ok=vertical_ok, state_ok=state_ok)
    assert route and route[-1] == goal
    # a genuine diagonal path changes BOTH plane and xy -> needs >1 move
    planes = {s[0] for s in route if s[0] != ""}
    positions = {s[1] for s in route}
    assert "Upper" in planes and len(positions) > 1


def _activate(client, dm, code, tok):
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "init_start"})
        init = recv_until(ws, "initiative")["payload"]
        for _ in range(len(init["order"]) + 2):
            if (init.get("turn") or {}).get("token_id") == tok:
                return init
            ws.send_json({"type": "init_next"})
            init = recv_until(ws, "initiative")["payload"]
    raise AssertionError(f"token {tok} never became active: {init}")


def _make_flyer(ws, tok_id, fly=50):
    ws.send_json({"type": "update_npc", "token_id": tok_id,
                  "npc": {"speed": 30, "fly": fly}})
    recv_until(ws, "snapshot")


def test_integration_flyer_ascends_into_default_air_without_openv(client):
    """Server-authoritative: a flyer hops onto a never-edited (air) plane with
    NO opening punched — the D159 default is open volume, not a hidden slab."""
    dm, player, code, _ = base_room(client)
    pid = state_of(client, player, code)["me"]
    client.post(f"/api/rooms/{code}/floors", json={"name": "Upper"}, headers=H(dm))
    with ws_connect(client, dm, code) as ws:
        flyer = add_npc(ws, "Dragon", cx=16, cy=12)
        ws.send_json({"type": "token_controller", "token_id": flyer,
                      "controller_id": pid})
        recv_until(ws, "token_controller")
        _make_flyer(ws, flyer)
    _activate(client, dm, code, flyer)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "move", "token_id": flyer, "tx": 16, "ty": 12,
                      "floor": "Upper", "mode": "fly"})
        for _ in range(12):
            ev = recv_until(ws, "move_state")
            if ev["payload"].get("moving") is False:
                break
    row = db.q1("SELECT * FROM tokens WHERE id=?", (flyer,))
    assert row["floor"] == "Upper"
    assert (int(row["x"] // CELL), int(row["y"] // CELL)) == (16, 12)


def test_integration_solid_ceiling_still_blocks_the_default_air(client):
    """The mirror proof: once the DM authors a real floor slab on the upper
    plane, the same hop is refused — the openness was the AIR, not a loophole."""
    dm, player, code, _ = base_room(client)
    pid = state_of(client, player, code)["me"]
    client.post(f"/api/rooms/{code}/floors", json={"name": "Upper"}, headers=H(dm))
    set_floor_grid(client, dm, code, "Upper",
                   lambda g: g.update(cells=[0] * len(g["cells"])))
    with ws_connect(client, dm, code) as ws:
        flyer = add_npc(ws, "Dragon", cx=16, cy=12)
        ws.send_json({"type": "token_controller", "token_id": flyer,
                      "controller_id": pid})
        recv_until(ws, "token_controller")
        _make_flyer(ws, flyer)
    _activate(client, dm, code, flyer)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "move", "token_id": flyer, "tx": 16, "ty": 12,
                      "floor": "Upper", "mode": "fly"})
        err = recv_until(ws, "error", fail_on_error=False)
    assert err["kind"] == "error"
    assert "No vertical flight path" in err["payload"]["msg"]
    assert db.q1("SELECT floor FROM tokens WHERE id=?", (flyer,))["floor"] == ""


# ---------- E — stored data stays byte-identical ----------------------------

def test_explicit_map_cells_survive_roundtrip(client):
    """Only never-edited planes default to air; every explicitly stored cell —
    floor, wall, void, and even stored air — is preserved verbatim."""
    dm, _, code, _ = base_room(client)
    r = rid(client, code)
    pattern = [mapmodel.VOID if i % 7 == 0 else (1 if i % 11 == 0 else 0)
               for i in range(80)]
    pattern[0] = mapmodel.AIR
    client.post(f"/api/rooms/{code}/floors", json={"name": "crypt"}, headers=H(dm))
    stored = net.get_map(r, "crypt")
    w = stored["w"] * stored["h"]
    stored["cells"] = (pattern[:w] + [0] * w)[:w]
    net.set_map(r, stored, "crypt")
    assert net.get_map(r, "crypt")["cells"] == stored["cells"]
