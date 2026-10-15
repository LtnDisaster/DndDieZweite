"""D114 (Sprint 43) Phase 8: live integration of the vertical feature set.

Phase 4/5/6 prove the individual authorities in isolation. This file pins the
paths a table actually uses end to end:

  * a flying token reaches another plane through a real open column, including
    the horizontal approach, canonical budget and animated step contract;
  * walk mode cannot pretend to fly through the same opening;
  * `openv` survives the named-plane map-edit round trip;
  * a server-legitimated cross-plane token is present in the player snapshot
    and hit-testable by the real tactical canvas code (no browser required —
    the same Node-vm harness pattern as the existing geometry tests).
"""
import shutil

import pytest
from starlette.testclient import TestClient

from app import db
from app.main import app
from app.room import combat as CB
from tests.test_browser_flow import _client_state_js, _vm
from tests.test_d114_phase6_vertical_movement import (
    _activate, _add_token, _controller_id, _make_flyer, _open_column)
from tests.test_floor_maps import add_floor, cell_idx, set_floor_grid, state_floor
from tests.test_movement_fog import (base_room, recv_until, state_of,
                                     ws_connect)

CELL = 50
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node not available")


@pytest.fixture()
def client():
    return TestClient(app)


def room_id(client, code):
    return db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]


def own_token(client, player, code):
    st = state_of(client, player, code)
    return next(t for t in st["tokens"] if t.get("owner_user_id") == st["me"])


def token_cell(tok_id):
    row = db.q1("SELECT x, y, floor FROM tokens WHERE id=?", (tok_id,))
    return (int(row["x"] // CELL), int(row["y"] // CELL), row["floor"] or "")


def visible_ids(client, user, code):
    return {t["id"] for t in state_of(client, user, code)["tokens"]}


def _wait_idle(ws):
    seen = []
    for _ in range(60):
        ev = ws.receive_json()
        kind = ev.get("kind")
        seen.append(kind)
        if kind == "error":
            raise AssertionError(f"unexpected movement error: {ev.get('payload')} ({seen})")
        if kind == "move_state" and ev.get("payload", {}).get("moving") is False:
            return seen
    raise AssertionError(f"movement never finished; saw {seen}")


def test_phase8_live_vertical_flight_uses_horizontal_approach_and_open_column(client):
    dm, player, code, _ = base_room(client)
    add_floor(client, dm, code, "Upper")
    pid = _controller_id(client, player, code)

    flyer = _add_token(client, dm, code, "Sky", "", 16, 12)
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "token_controller", "token_id": flyer,
                      "controller_id": pid})
        recv_until(ws, "token_controller")
        _make_flyer(ws, flyer, fly=50)

    # The shaft is deliberately NOT under the flyer: a useful vertical route
    # needs real horizontal movement on both planes, not a direct hop.
    _open_column(client, dm, code, 17, 12)
    _activate(client, dm, code, flyer)
    rid = room_id(client, code)
    start_fly = CB.move_remaining(CB.get_init(rid), flyer, "fly")

    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "move", "token_id": flyer, "tx": 16, "ty": 12,
                      "floor": "Upper", "mode": "fly"})
        _wait_idle(ws)

    cx, cy, floor = token_cell(flyer)
    assert (cx, cy, floor) == (16, 12, "Upper")
    end_fly = CB.move_remaining(CB.get_init(rid), flyer, "fly")
    # horizontal to shaft (1) + vertical floor step (2) + horizontal to target (1)
    assert start_fly - end_fly == 4


def test_phase8_walk_mode_cannot_pretend_to_fly_through_an_open_column(client):
    dm, player, code, _ = base_room(client)
    add_floor(client, dm, code, "Upper")
    pid = _controller_id(client, player, code)

    flyer = _add_token(client, dm, code, "Grounded", "", 16, 12)
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "token_controller", "token_id": flyer,
                      "controller_id": pid})
        recv_until(ws, "token_controller")

    _open_column(client, dm, code, 16, 12)

    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "move", "token_id": flyer, "tx": 16, "ty": 12,
                      "floor": "Upper", "mode": "walk"})
        err = recv_until(ws, "error", fail_on_error=False)

    assert err["payload"]["msg"] == "Vertical movement requires a fly speed"
    _, _, floor = token_cell(flyer)
    assert floor == ""


def test_phase8_named_plane_openv_survives_map_edit_round_trip(client):
    dm, player, code, _ = base_room(client)
    add_floor(client, dm, code, "Attic")
    cx, cy = 17, 13

    set_floor_grid(client, dm, code, "Attic",
                   lambda g: g["openv"].__setitem__(cell_idx(g, cx, cy), 1))

    attic = state_floor(client, dm, code, "Attic")["grid"]
    assert attic["openv"][cell_idx(attic, cx, cy)] == 1

    primary = state_of(client, dm, code)["grid"]
    assert primary["openv"][cell_idx(primary, cx, cy)] == 0

    again = state_floor(client, dm, code, "Attic")["grid"]
    assert again["openv"][cell_idx(again, cx, cy)] == 1


@needs_node
def test_phase8_cross_plane_token_is_hit_testable_after_server_delivery(client):
    dm, player, code, ch = base_room(client)
    tok = own_token(client, player, code)
    cx, cy, _ = token_cell(tok["id"])
    add_floor(client, dm, code, "Upper")

    npc = _add_token(client, dm, code, "Sky", "Upper", cx, cy)
    assert npc not in visible_ids(client, player, code)

    # The open shaft itself is the legitimate sight connection. Height is then
    # changed as a live vertical-body update to prove the snapshot/canvas path
    # survives the re-evaluation, not because a shaft would otherwise hide.
    _open_column(client, dm, code, cx, cy)
    assert npc in visible_ids(client, player, code)

    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "token_height", "token_id": tok["id"],
                      "height_ft": 30})
        recv_until(ws, "token_height")

    assert npc in visible_ids(client, player, code)

    init = _client_state_js(state_of(client, player, code))
    probe = """
      draw();
      const t = state.tokens.find(x => x.id === NPCID);
      if (!t) { console.log(JSON.stringify({ visible:false, hit:null })); }
      else {
        const [w,h] = tokenSpan(t);
        const c = cellSize();
        const hit = tokenAt(t.x + (w - 1) * c / 2, t.y + (h - 1) * c / 2);
        console.log(JSON.stringify({ visible:true, hit: hit && hit.id }));
      }
    """.replace("NPCID", repr(npc))
    out = _vm(init, probe)
    assert out == {"visible": True, "hit": npc}
