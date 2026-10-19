"""D114 (Sprint 43) Phase 5: real cross-plane visibility, reach and interaction.

These tests go through the live REST/WS handlers, not the geometry helpers only.
They pin the three D114 outcomes at the integration boundary:

  * a body protruding through a full-footprint opening shares the upper plane;
  * an open shaft shares SIGHT, but not physical body presence;
  * a solid ceiling remains exactly the old fail-closed "elsewhere" case.
"""
import pytest
from starlette.testclient import TestClient

from app import db, main
from tests.test_floor_maps import cell_idx, set_floor_grid
from tests.test_movement_fog import H, recv_until, state_of, ws_connect
from tests.test_sprint23_combat import _tok, armed_room, own_char

CELL = 50


@pytest.fixture()
def client():
    return TestClient(main.app)


def add_floor(client, dm, code, name, ground=True):
    r = client.post(f"/api/rooms/{code}/floors", json={"name": name}, headers=H(dm))
    assert r.status_code == 200, r.text
    # D159: a named plane is open AIR by default; these tests gate a solid
    # ceiling on `openv`, so the DM lays the slab first (openv is the opening).
    if ground:
        set_floor_grid(client, dm, code, name,
                       lambda g: g.update(cells=[0] * len(g["cells"])))
    return r.json()


def ptoken(client, player, code):
    st = state_of(client, player, code)
    return next(t["id"] for t in st["tokens"] if t.get("owner_user_id") == st["me"])


def cell_of(tok_id):
    row = db.q1("SELECT x, y FROM tokens WHERE id=?", (tok_id,))
    return int(row["x"] // CELL), int(row["y"] // CELL)


def add_npc(client, dm, code, fl, cx, cy):
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "add_token", "label": "Foe", "x": (cx + .5) * CELL,
                      "y": (cy + .5) * CELL, "size": "Medium", "floor": fl})
        return recv_until(ws, "token_add")["payload"]["id"]


def set_open(client, dm, code, fl, cx, cy, value=1):
    def mutate(g):
        g["openv"][cell_idx(g, cx, cy)] = value
    set_floor_grid(client, dm, code, fl, mutate)


def set_height(client, player, code, tok, **body):
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "token_height", "token_id": tok, **body})
        recv_until(ws, "token_height")


def token_floor(client, dm, code, tok, fl):
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "token_floor", "token_id": tok, "floor": fl})
        recv_until(ws, "token_floor")


def token_ids(client, user, code):
    return {t["id"] for t in state_of(client, user, code)["tokens"]}


def recv_event(ws, kind, **payload):
    for _ in range(40):
        ev = ws.receive_json()
        if ev.get("kind") == kind and all(ev.get("payload", {}).get(k) == v
                                         for k, v in payload.items()):
            return ev
        if ev.get("kind") == "error":
            raise AssertionError(f"unexpected error waiting for {kind}: {ev}")
    raise AssertionError(f"never saw {kind} {payload}")


def attack(client, player, code, tok, item_id, target_id, expected="dice"):
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "roll", "kind": "attack", "item_id": item_id,
                      "token_id": tok, "target_id": target_id, "visibility": "public"})
        return recv_until(ws, expected, fail_on_error=False)


def test_protruding_body_shares_upper_plane_for_sight_and_attack(client):
    dm, player, code, ch = armed_room(client)
    tok = _tok(client, player, code, ch)
    add_floor(client, dm, code, "Upper")
    cx, cy = cell_of(tok)
    foe = add_npc(client, dm, code, "Upper", cx + 1, cy)
    assert foe not in token_ids(client, player, code)

    set_open(client, dm, code, "", cx, cy)
    set_height(client, player, code, tok, height_ft=30)
    assert foe in token_ids(client, player, code)

    item = own_char(client, player, code)["items"][0]
    ev = attack(client, player, code, tok, item["id"], foe)
    assert ev.get("kind") == "dice", ev


def test_live_recalc_protrudes_upper_token_when_body_grows(client):
    dm, player, code, ch = armed_room(client)
    tok = _tok(client, player, code, ch)
    add_floor(client, dm, code, "Upper")
    cx, cy = cell_of(tok)
    foe = add_npc(client, dm, code, "Upper", cx + 1, cy)
    assert foe not in token_ids(client, player, code)

    # Opening the ceiling first is not enough: the default Medium body is still
    # elsewhere. Growing it through the SAME player socket must make the server
    # re-run visibility and push the already-present foe as a token_add.
    set_open(client, dm, code, "", cx, cy)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "token_height", "token_id": tok, "height_ft": 30})
        recv_event(ws, "token_height", token_id=tok)
        recv_event(ws, "token_add", id=foe)


def test_solid_ceiling_keeps_planes_elsewhere_and_untargetable(client):
    dm, player, code, ch = armed_room(client)
    tok = _tok(client, player, code, ch)
    add_floor(client, dm, code, "Upper")
    cx, cy = cell_of(tok)
    foe = add_npc(client, dm, code, "Upper", cx + 1, cy)
    set_height(client, player, code, tok, height_ft=30)

    assert foe not in token_ids(client, player, code)
    item = own_char(client, player, code)["items"][0]
    ev = attack(client, player, code, tok, item["id"], foe, expected="error")
    assert ev.get("kind") == "error", ev
    assert "No target" in ev["payload"]["msg"]


def test_shaft_gives_sight_but_not_melee_presence(client):
    dm, player, code, ch = armed_room(client)
    tok = _tok(client, player, code, ch)
    add_floor(client, dm, code, "Upper")
    cx, cy = cell_of(tok)
    token_floor(client, dm, code, tok, "Upper")
    foe = add_npc(client, dm, code, "", cx, cy)
    set_open(client, dm, code, "", cx, cy)

    assert foe in token_ids(client, player, code)
    item = own_char(client, player, code)["items"][0]
    ev = attack(client, player, code, tok, item["id"], foe, expected="error")
    assert ev.get("kind") == "error", ev
    assert "out of reach" in ev["payload"]["msg"]

    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "grapple", "token_id": tok, "target_id": foe,
                      "op_id": "shaft-grapple"})
        ev = recv_until(ws, "error", fail_on_error=False)
    assert ev.get("kind") == "error", ev
    assert "out of reach" in ev["payload"]["msg"]


def test_protruding_body_reaches_a_plane_local_object(client):
    dm, player, code, ch = armed_room(client)
    tok = _tok(client, player, code, ch)
    add_floor(client, dm, code, "Upper")
    cx, cy = cell_of(tok)
    obj = {"id": "upper-lever", "x": cx + 1, "y": cy, "label": "Upper lever",
           "interact": {"label": "Pull", "op": {"kind": "toggle"}}}
    set_floor_grid(client, dm, code, "Upper",
                   lambda g: g.__setitem__("objects", (g.get("objects") or []) + [obj]))
    set_open(client, dm, code, "", cx, cy)
    set_height(client, player, code, tok, height_ft=30)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "interact", "object_id": "upper-lever", "floor": "Upper"})
        ev = recv_until(ws, "object_state")
    assert ev["payload"] == {"object_id": "upper-lever", "state": {"on": True}}
