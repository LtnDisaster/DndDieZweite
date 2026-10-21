"""D160 — adversarial vertical-geometry probes (real production primitives).

These do NOT assert source patterns; they call the exact functions the server
delivery path uses — ``vertical3d.observable_cells`` (sight), ``column_open`` /
``boundary_open`` (openness), ``vertical_path_clear`` (flight), ``body_planes``
(protrusion), ``path.find_path_3d`` (route), ``floors.absolute_height_ft``
(reach) — against the D159 open-volume world, and drive one integration move
through the WebSocket.

Where the D159 model deliberately provides LESS than a true 3D ray (no diagonal
cross-plane sight, no multi-opening zig-zag shaft, no cross-plane lighting), the
test asserts the REAL shaft behaviour and marks it as a documented limitation
(decision: the shaft+LOS model is intended; ray_clear_3d stays an unused
primitive). See docs/QUALITY_GATE_D160.md.
"""
import pytest
from starlette.testclient import TestClient

from app import floors, mapmodel, path as P
from app.main import app
from app.room import vertical3d
from app.room import net
from tests.test_d159_open_volumes import CELL, paint, rid, token_at
from tests.test_floor_maps import set_floor_grid
from tests.test_movement_fog import (H, add_npc, base_room, recv_until,
                                     state_of, ws_connect)


@pytest.fixture()
def client():
    return TestClient(app)


def _add(client, dm, code, name, below=False):
    r = client.post(f"/api/rooms/{code}/floors",
                    json={"name": name, "below": below}, headers=H(dm))
    assert r.status_code == 200, r.text
    return r.json()


def world(client, dm, code, names, below=()):
    """Declare planes (default air) and return (rid, maps, lm)."""
    for n in names:
        _add(client, dm, code, n)
    for n in below:
        _add(client, dm, code, n, below=True)
    r = rid(client, code)
    return r, vertical3d.maps_for(r), vertical3d.level_map(r)


# ---------- 1/2 — multi-storey sight through open air -----------------------

def test_sight_e0_to_eplus3_and_back(client):
    dm, _, code, _ = base_room(client)
    r, maps, lm = world(client, dm, code, ["A", "B", "C"])
    cell = (16, 16)
    assert vertical3d.column_open(maps, lm, "", "C", cell) is True
    high = token_at(r, "C", 16, 16)
    # a ground viewer sees the top-floor token straight down the open shaft
    assert cell in vertical3d.observable_cells(r, high, "", maps, lm)
    # ...and the reverse: the high viewer sees the ground token back up the shaft
    low = token_at(r, "", 16, 16)
    assert cell in vertical3d.observable_cells(r, low, "C", maps, lm)
    # a solid slab on ANY intermediate storey cuts the whole span
    paint(maps["B"], 16, 16, cells=0)
    assert cell not in vertical3d.observable_cells(r, high, "", maps, lm)


def test_sight_e_minus2_to_eplus2_needs_a_stair_through_the_ground(client):
    dm, _, code, _ = base_room(client)
    r, maps, lm = world(client, dm, code, ["Up1", "Up2"], below=["Dn1", "Dn2"])
    cell = (10, 10)
    # the SOLID primary ground seals the cellars from the upper storeys — a full
    # -2..+2 shaft does NOT exist by default (correct: the floor is a slab).
    assert vertical3d.column_open(maps, lm, "Dn2", "Up2", cell) is False
    # a stairwell punched through the ground boundary (openv on the plane BELOW
    # it) opens the whole stack; the air storeys above/below are already open.
    paint(maps["Dn1"], 10, 10, openv=1)
    assert vertical3d.column_open(maps, lm, "Dn2", "Up2", cell) is True
    assert cell in vertical3d.observable_cells(r, token_at(r, "Up2", 10, 10), "Dn2", maps, lm)


def test_level_gap_fails_closed(client):
    """#8 — a level gap cannot be constructed via the API; if raw storage ever
    yields one, adjacency fails closed (never joins across the missing storey)."""
    dm, _, code, _ = base_room(client)
    r = rid(client, code)
    maps = vertical3d.maps_for(r)
    lm = {"": 0, "up1": 1, "up3": 3}                 # synthetic gap at level 2
    assert vertical3d.column_open(maps, lm, "", "up3", (10, 10)) is False


def test_levels_are_always_contiguous(client):
    dm, _, code, _ = base_room(client)
    for n in ("a", "b", "c"):
        _add(client, dm, code, n)
    _add(client, dm, code, "x", below=True)
    vals = sorted(vertical3d.level_map(rid(client, code)).values())
    assert vals == [-1, 0, 1, 2, 3]                   # no gaps, ever


# ---------- 3/4 — massive slab vs a punched opening -------------------------

def test_solid_slab_occludes_a_punch_reopens(client):
    dm, _, code, _ = base_room(client)
    r, maps, lm = world(client, dm, code, ["Ceil"])
    cell = (16, 16)
    paint(maps["Ceil"], 16, 16, cells=0)              # massive ceiling
    assert vertical3d.observable_cells(r, token_at(r, "Ceil", 16, 16), "", maps, lm) == set()
    assert vertical3d.vertical_path_clear(r, token_at(r, "", 16, 16), "", "Ceil", maps, lm) is False
    paint(maps[""], 16, 16, openv=1)                  # trapdoor through the slab
    assert cell in vertical3d.observable_cells(r, token_at(r, "Ceil", 16, 16), "", maps, lm)
    assert vertical3d.vertical_path_clear(r, token_at(r, "", 16, 16), "", "Ceil", maps, lm) is True


# ---------- 5/6/7 — documented shaft limitations ----------------------------

def test_cross_plane_sight_is_vertical_projection_not_a_ray(client):
    """LIMITATION (intended): a token on another plane is observable only down its
    OWN open column (a vertical projection onto the viewer's plane). There is no
    angled/viewpoint 3D ray — the digital ray is not on the delivery path."""
    dm, _, code, _ = base_room(client)
    r, maps, lm = world(client, dm, code, ["A"])
    above = token_at(r, "A", 18, 16)
    obs = vertical3d.observable_cells(r, above, "", maps, lm)
    assert (18, 16) in obs          # seen straight down its own open column
    assert (16, 16) not in obs      # NOT smeared onto an unrelated cell (no diagonal)


def test_openings_must_align_across_solid_storeys(client):
    """LIMITATION (intended): a shaft is open at the SAME world cell across every
    boundary whose upper plane is solid. Openings offset per storey do not chain
    into sight."""
    dm, _, code, _ = base_room(client)
    r, maps, lm = world(client, dm, code, ["S1", "S2"])
    for nm in ("S1", "S2"):                           # two solid storeys
        for cx in (16, 17):
            paint(maps[nm], cx, 16, cells=0)
    paint(maps[""], 16, 16, openv=1)                  # hole in the ground at (16,16)
    paint(maps["S1"], 17, 16, openv=1)                # hole one cell over on S1
    assert vertical3d.column_open(maps, lm, "", "S2", (16, 16)) is False   # misaligned
    paint(maps["S1"], 16, 16, openv=1)                # align it
    assert vertical3d.column_open(maps, lm, "", "S2", (16, 16)) is True


def test_wall_on_intermediate_level_caps_column(client):
    dm, _, code, _ = base_room(client)
    r, maps, lm = world(client, dm, code, ["Mid", "Top"])
    paint(maps["Mid"], 12, 12, cells=1)               # a wall on the middle plane
    assert vertical3d.column_open(maps, lm, "", "Top", (12, 12)) is False


# ---------- 9 — insert below never renumbers existing floors ----------------

def test_insert_below_appends_without_renumbering(client):
    dm, _, code, _ = base_room(client)
    _add(client, dm, code, "Cellar", below=True)
    _add(client, dm, code, "Tomb", below=True)
    lm1 = vertical3d.level_map(rid(client, code))
    assert lm1 == {"": 0, "Cellar": -1, "Tomb": -2}
    _add(client, dm, code, "Deep", below=True)        # insertion at the deep end
    lm2 = vertical3d.level_map(rid(client, code))
    assert lm2 == {"": 0, "Cellar": -1, "Tomb": -2, "Deep": -3}


# ---------- 10 — edge / out-of-bounds fails closed --------------------------

def test_out_of_bounds_column_fails_closed(client):
    dm, _, code, _ = base_room(client)
    r, maps, lm = world(client, dm, code, ["A"])
    mp = maps["A"]
    oob = (mp["w"] + 5, mp["h"] + 5)
    try:
        res = vertical3d.column_open(maps, lm, "", "A", oob)
    except Exception:
        res = False                              # must fail closed, never leak
    assert not res
    # an out-of-world cell is never part of an observable footprint
    assert oob not in vertical3d.observable_cells(r, token_at(r, "A", 0, 0), "", maps, lm)


# ---------- 11 — a wide body cannot pass a one-cell opening -----------------

def test_large_token_needs_a_whole_open_column(client):
    dm, _, code, _ = base_room(client)
    r, maps, lm = world(client, dm, code, ["A"])
    tall = token_at(r, "", 16, 16, size="Large", height_ft=30)  # 2x2, reaches A
    foot = sorted(vertical3d.footprint.occupied_cells(maps[""], tall))
    assert len(foot) == 4, "Large should occupy a 2x2 box"
    for c in foot:
        paint(maps["A"], c[0], c[1], cells=0)         # slab the whole 2x2 cap
    paint(maps[""], foot[0][0], foot[0][1], openv=1)  # punch only ONE corner
    assert "A" not in vertical3d.body_planes(r, tall, maps, lm)
    for c in foot:                                     # open every corner -> joins
        paint(maps[""], c[0], c[1], openv=1)
    assert "A" in vertical3d.body_planes(r, tall, maps, lm)


# ---------- 12/16 — flight over >=3 storeys; blocked/occupied destinations --

def _route(r, maps, lm, start, goal, side=(1, 1)):
    def state_ok(s):
        return vertical3d.volume_final_valid(r, token_at(r, s[0], *s[1]), [], maps, lm)

    def vertical_ok(p, n, cells):
        return vertical3d.vertical_path_clear(r, token_at(r, p[0], *p[1]), p[0], n[0], maps, lm)
    return P.find_path_3d(start, goal, maps, lm, side, mode="fly",
                          vertical_ok=vertical_ok, state_ok=state_ok)


def test_flight_over_three_storeys_up_and_back_down(client):
    dm, _, code, _ = base_room(client)
    r, maps, lm = world(client, dm, code, ["A", "B", "C"])
    up = _route(r, maps, lm, ("", (16, 12)), ("C", (16, 12)))
    assert up and up[-1] == ("C", (16, 12))
    assert {s[0] for s in up} >= {"A", "B", "C"}       # really crossed three storeys
    down = _route(r, maps, lm, ("C", (16, 12)), ("", (16, 12)))
    assert down and down[-1] == ("", (16, 12))         # back down to the ground
    assert {"C"} | {s[0] for s in down} >= {"A", "B", "C"}   # crossed back down three


def test_flight_down_into_a_cellar_needs_an_opening(client):
    """The solid ground blocks a straight drop into a cellar; a trapdoor (openv on
    the cellar plane) opens exactly that column."""
    dm, _, code, _ = base_room(client)
    r, maps, lm = world(client, dm, code, [], below=["D"])
    assert _route(r, maps, lm, ("", (16, 12)), ("D", (16, 12))) is None
    paint(maps["D"], 16, 12, openv=1)
    down = _route(r, maps, lm, ("", (16, 12)), ("D", (16, 12)))
    assert down and down[-1] == ("D", (16, 12))


def test_blocked_destination_and_occupied_air(client):
    dm, _, code, _ = base_room(client)
    r, maps, lm = world(client, dm, code, ["A"])
    # (a) destination terrain is a wall -> not usable volume
    paint(maps["A"], 16, 12, cells=1)
    assert vertical3d.volume_final_valid(r, token_at(r, "A", 16, 12), [], maps, lm) is False
    # (b) an OPEN cell already held by another body -> collision, not terrain
    occupant = token_at(r, "A", 18, 12, id=99)
    assert vertical3d.volume_final_valid(
        r, token_at(r, "A", 18, 12, id=7), [occupant], maps, lm) is False


# ---------- 17 — vertical reach reporting -----------------------------------

def test_vertical_height_and_reach_math(client):
    dm, _, code, _ = base_room(client)
    _add(client, dm, code, "A")
    _add(client, dm, code, "B")
    _add(client, dm, code, "D", below=True)
    r = rid(client, code)
    assert floors.absolute_height_ft(r, "B") == 20
    assert floors.absolute_height_ft(r, "") == 0
    assert floors.absolute_height_ft(r, "D") == -10
    # the same-xy top-floor token is observable (visible) and 20 ft up (reach)
    maps, lm = vertical3d.maps_for(r), vertical3d.level_map(r)
    assert (16, 16) in vertical3d.observable_cells(r, token_at(r, "B", 16, 16), "", maps, lm)


# ---------- 18 — lamps are plane-local; the shaft gate is geometry ----------

def test_lamps_do_not_open_or_close_a_shaft(client):
    dm, _, code, _ = base_room(client)
    r, maps, lm = world(client, dm, code, ["Ceil"])
    paint(maps["Ceil"], 16, 16, cells=0)               # solid ceiling blocks sight
    before = vertical3d.observable_cells(r, token_at(r, "Ceil", 16, 16), "", maps, lm)
    maps["Ceil"].setdefault("objects", []).append(    # a lamp on the ceiling plane
        {"id": "l1", "type": "lamp", "x": 16, "y": 16, "state": {"on": True}})
    after = vertical3d.observable_cells(r, token_at(r, "Ceil", 16, 16), "", maps, lm)
    assert before == after == set()                    # lighting never opens a slab


# ---------- 19/20 — no stale sight cache + it reflects map edits ------------

def test_no_stale_sight_after_map_edit(client):
    """The delivery recomputes from the live map every time — there is no cached
    visibility to go stale. Flip a real slab and the very next read changes."""
    dm, _, code, _ = base_room(client)
    r = rid(client, code)
    _add(client, dm, code, "Ceil")
    tok = token_at(r, "Ceil", 16, 16)
    # open default air -> visible from the ground
    assert (16, 16) in vertical3d.observable_cells(r, tok, "")
    # author a slab on Ceil through the real storage path, then re-read WITHOUT
    # passing cached maps -> the new solidity must be seen immediately
    mp = net.get_map(r, "Ceil")
    mp["cells"][16 * mp["w"] + 16] = 0
    net.set_map(r, mp, "Ceil")
    assert (16, 16) not in vertical3d.observable_cells(r, tok, "")
    # and punching an opening clears it again on the next read
    mp = net.get_map(r, "")
    mp.setdefault("openv", [0] * mp["w"] * mp["h"])[16 * mp["w"] + 16] = 1
    net.set_map(r, mp, "")
    assert (16, 16) in vertical3d.observable_cells(r, tok, "")


# ---------- 14 (integration) + flight authority path ------------------------

def _activate(client, dm, code, tok):
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "init_start"})
        init = recv_until(ws, "initiative")["payload"]
        for _ in range(len(init["order"]) + 2):
            if (init.get("turn") or {}).get("token_id") == tok:
                return init
            ws.send_json({"type": "init_next"})
            init = recv_until(ws, "initiative")["payload"]
    raise AssertionError("token never active")


def _make_flyer(ws, tok_id, fly=50):
    ws.send_json({"type": "update_npc", "token_id": tok_id,
                  "npc": {"speed": 30, "fly": fly}})
    recv_until(ws, "snapshot")


def test_integration_flyer_crosses_two_storeys(client):
    dm, player, code, _ = base_room(client)
    pid = state_of(client, player, code)["me"]
    for n in ("A", "B"):
        _add(client, dm, code, n)
    with ws_connect(client, dm, code) as ws:
        flyer = add_npc(ws, "Sky", cx=16, cy=12)
        ws.send_json({"type": "token_controller", "token_id": flyer, "controller_id": pid})
        recv_until(ws, "token_controller")
        _make_flyer(ws, flyer)
    _activate(client, dm, code, flyer)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "move", "token_id": flyer, "tx": 16, "ty": 12,
                      "floor": "B", "mode": "fly"})
        for _ in range(14):
            if recv_until(ws, "move_state")["payload"].get("moving") is False:
                break
    row = db_row(flyer)
    assert row["floor"] == "B" and (int(row["x"] // CELL), int(row["y"] // CELL)) == (16, 12)


def db_row(tok_id):
    from app import db
    return db.q1("SELECT * FROM tokens WHERE id=?", (tok_id,))


# ---------- 14 — DOCUMENTED LIMITATION: no revalidation under a resting body --

def test_map_edit_under_resting_token_is_not_revalidated(client):
    """D160 known limitation (decision: report-only). A DM teleport can rest a
    token on an open-air plane. A LATER map edit that caps that column does not
    retroactively move or reject the resting token — the inconsistency persists
    until the token next moves. Not a live authority hole (DM-only, self-heals on
    the next move), recorded here so it is never mistaken for a guarantee."""
    dm, _player, code, _ = base_room(client)
    _add(client, dm, code, "A")
    with ws_connect(client, dm, code) as wsd:
        tok = add_npc(wsd, "Float", cx=16, cy=12)
        wsd.send_json({"type": "move", "token_id": tok, "tx": 16, "ty": 12,
                       "floor": "A", "teleport": True})
        recv_until(wsd, "token_floor")
    before = db_row(tok)
    assert before["floor"] == "A"                          # resting on the air plane
    cx, cy = int(before["x"] // CELL), int(before["y"] // CELL)

    def cap(g):                                            # a solid slab over the column
        g["cells"] = [0] * len(g["cells"])
        g["cells"][cy * g["w"] + cx] = 1
    set_floor_grid(client, dm, code, "A", cap)

    after = db_row(tok)                                    # NOT moved, NOT rejected
    assert (after["floor"], after["x"], after["y"]) == (before["floor"], before["x"], before["y"])
    # ...yet a fresh check now finds the body illegal (the latent inconsistency)
    maps, lm = vertical3d.maps_for(rid(client, code)), vertical3d.level_map(rid(client, code))
    assert vertical3d.volume_final_valid(rid(client, code), after, [after], maps, lm) is False


# ---------- 20b — reload / two-client convergence (Phase 5 divergence) --------

def test_reload_and_two_client_state_converge(client):
    """After authoring signed planes + a token resting on an upper plane, two
    independent /state reads (a fresh socket == a browser reload) must agree on
    the signed stack and the token's plane — no client diverges on reconnect."""
    dm, player, code, _ = base_room(client)
    _add(client, dm, code, "Attic")
    _add(client, dm, code, "Tomb", below=True)
    with ws_connect(client, dm, code) as wsd:
        flyer = add_npc(wsd, "Float", cx=16, cy=12)
        wsd.send_json({"type": "move", "token_id": flyer, "tx": 16, "ty": 12,
                       "floor": "Attic", "teleport": True})
        recv_until(wsd, "token_floor")
    sd = state_of(client, dm, code)
    sp = state_of(client, player, code)                 # a second, independent read
    assert sd["floors"] == sp["floors"] == ["Tomb", "", "Attic"]
    assert sd["floor_levels"] == sp["floor_levels"] == {"": 0, "Attic": 1, "Tomb": -1}
    assert any(t["id"] == flyer and t["floor"] == "Attic" for t in sd["tokens"])
