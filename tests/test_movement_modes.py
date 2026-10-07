"""D83: movement modes (walk/fly/swim/climb) as a FOUNDATION.

Budgets come ONLY from gear.clean_speeds + movecost.walk_budget (SSOT, no
second feet->squares formula). One active mode per movement operation; each
mode keeps its own per-turn ledger, so switching can never farm movement.
Fly ignores difficult terrain and elevation cliffs — walls, closed doors and
map bounds stay in force. Swim/climb are data-only (no water terrain exists;
inventing fake terrain rules is explicitly out of scope).
"""
import pytest
from starlette.testclient import TestClient

from app import main, mapmodel, movecost, path as P
from app.room import combat as CB


@pytest.fixture()
def client():
    return TestClient(main.app)
from tests.test_footprint_rect import npc_token, tok_row
from tests.test_movement_fog import add_npc, base_room, recv_until, state_of, ws_connect


# ---------- SSOT unit layer ---------------------------------------------------

def test_fly_route_cost_uses_the_same_ssot_conversion():
    assert movecost.walk_budget(60) == 12                       # the ONE formula
    assert movecost.walk_budget(30) == 6


def test_fly_ignores_difficult_terrain_in_route_cost(monkeypatch):
    DIFF = 2                                                    # TERRAIN id: difficult
    monkeypatch.setattr(mapmodel, "terrain_at", lambda mp, x, y: DIFF)
    route = [(0, 0), (1, 0), (2, 0), (3, 0)]
    assert movecost.route_cost({}, route, 1, mode="walk") == 6  # doubled every step
    assert movecost.route_cost({}, route, 1, mode="fly") == 3   # terrain never slows flight
    assert movecost.route_cost({}, route, 1) == 6               # default stays walk


def test_fly_crosses_elevation_cliff_walk_does_not(monkeypatch):
    mp = {"w": 10, "h": 10, "cell": 50, "origin": [0, 0], "elev": [1]}
    monkeypatch.setattr(mapmodel, "terrain_at", lambda mp, x, y: 0)
    monkeypatch.setattr(mapmodel, "elev_at",
                        lambda mp, x, y: 0 if x < 3 else 5)
    assert not P.step_legal(mp, (2, 0), (3, 0))                  # a wall of drop: no
    assert P.step_legal(mp, (2, 0), (3, 0), mode="fly")          # flight goes over it


def test_mode_ledgers_cannot_farm_movement():
    """The exploit guard: per-mode ledgers only ever go UP in `spent`; the
    per-turn ceiling is sum(mode budgets) — a walk->fly->walk switch can use
    each mode's own budget once, never refill anything."""
    init = {"combat": True, "round": 1, "active": 0,
            "order": [{"token_id": 1}],
            "turn": {"token_id": 1, "move_mode": "walk",
                     "move_by": {"walk": {"total": 6, "spent": 0},
                                 "fly": {"total": 10, "spent": 0}},
                     "move_total": 6, "move_spent": 0}}
    assert CB.move_remaining(init, 1) == 6 and CB.move_remaining(init, 1, "fly") == 10
    by = init["turn"]["move_by"]
    by["walk"]["spent"] = 6                                     # walk it all out
    assert CB.move_remaining(init, 1, "walk") == 0
    assert CB.move_remaining(init, 1, "fly") == 10              # fly untouched
    by["fly"]["spent"] = 10                                     # fly it all out
    assert CB.move_remaining(init, 1, "fly") == 0
    assert CB.move_remaining(init, 1, "walk") == 0              # NOT refilled by switching
    assert CB.move_remaining(init, 1, "swim") == 0              # creature has no swim
    assert CB.move_remaining(init, 2) is None                   # economy: unlisted


def test_legacy_turn_object_still_reads_walk():
    init = {"combat": True, "round": 1, "active": 0, "order": [{"token_id": 7}],
            "turn": {"token_id": 7, "move_total": 6, "move_spent": 2}}   # pre-D83
    assert CB.move_remaining(init, 7) == 4
    assert CB.move_remaining(init, 7, "fly") == 4               # legacy: single meter


# ---------- server-authoritative mode gate (WS) --------------------------------

def _make_flyer(ws, tok_id, fly=50):
    ws.send_json({"type": "update_npc", "token_id": tok_id,
                  "npc": {"speed": 30, "fly": fly}})
    recv_until(ws, "snapshot")


def test_mode_requires_an_actual_speed(client):
    dm, player, code, _ = base_room(client)
    with ws_connect(client, dm, code) as ws:
        walker = add_npc(ws, "Walker", cx=10, cy=10)
        ws.send_json({"type": "move", "token_id": walker, "tx": 12, "ty": 10,
                      "mode": "fly"})
        err = recv_until(ws, "error", fail_on_error=False)
        assert "no fly speed" in err["payload"]["msg"]
        _make_flyer(ws, walker)
        ws.send_json({"type": "move", "token_id": walker, "tx": 12, "ty": 10,
                      "teleport": True, "mode": "fly"})         # now it may ask
        recv_until(ws, "step")
        assert tok_row(walker)["x"] == (12 + .5) * 50


def test_garbage_mode_word_falls_back_to_walk(client):
    dm, player, code, _ = base_room(client)
    with ws_connect(client, dm, code) as ws:
        tok = add_npc(ws, "Plod", cx=10, cy=10)
        ws.send_json({"type": "path_preview", "token_id": tok, "tx": 12, "ty": 10,
                      "request_id": 1, "mode": "levitate"})
        pv = recv_until(ws, "path_preview")["payload"]
        assert pv["mode"] == "walk" and pv["speed_ft"] == 30


def test_preview_prices_the_requested_mode(client):
    dm, player, code, _ = base_room(client)
    with ws_connect(client, dm, code) as ws:
        tok = add_npc(ws, "Hippogriff", cx=10, cy=10)
        _make_flyer(ws, tok, fly=60)
        ws.send_json({"type": "path_preview", "token_id": tok, "tx": 13, "ty": 10,
                      "request_id": 2, "mode": "fly"})
        pv = recv_until(ws, "path_preview")["payload"]
        assert pv["mode"] == "fly"
        assert pv["speed_ft"] == 60 and pv["budget"] == 12      # THE SSOT conversion
        ws.send_json({"type": "path_preview", "token_id": tok, "tx": 13, "ty": 10,
                      "request_id": 3})
        pv2 = recv_until(ws, "path_preview")["payload"]
        assert pv2["mode"] == "walk" and pv2["speed_ft"] == 30


def test_combat_per_mode_ledger_over_the_wire(client):
    """Full stack: an NPC led by a player (authz.controls) spends per mode."""
    dm, player, code, _ = base_room(client)
    st = state_of(client, dm, code)
    pid = next(m["user_id"] for m in st["members"] if m["user_id"] != st["me"])
    with ws_connect(client, dm, code) as ws:
        mount_kid = add_npc(ws, "Companion", cx=5, cy=5)
        ws.send_json({"type": "token_controller", "token_id": mount_kid,
                      "controller_id": pid})
        recv_until(ws, "token_controller")
        _make_flyer(ws, mount_kid, fly=50)
        ws.send_json({"type": "init_start"})
        init = recv_until(ws, "initiative")["payload"]
        # advance until the companion owns the active turn (bounded)
        for _ in range(len(init["order"]) + 1):
            if (init.get("turn") or {}).get("token_id") == mount_kid:
                break
            ws.send_json({"type": "init_next"})
            init = recv_until(ws, "initiative")["payload"]
        assert (init.get("turn") or {}).get("token_id") == mount_kid
        by = init["turn"]["move_by"]
        assert by["walk"]["total"] == 6 and by["fly"]["total"] == 10
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "move", "token_id": mount_kid, "tx": 8, "ty": 5,
                      "mode": "fly"})
        for _ in range(8):                                       # drain the walk
            m = recv_until(ws, "move_state")
            if m["payload"].get("moving") is False:
                break
    room_id = tok_row(mount_kid)["room_id"]
    init = CB.get_init(room_id)
    assert CB.move_remaining(init, mount_kid, "walk") == 6       # walk ledger untouched
    assert CB.move_remaining(init, mount_kid, "fly") == 10 - 3   # fly paid the 3 steps
