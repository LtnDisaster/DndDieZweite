"""Sprint 13 (D79): the completed combat turn & movement loop.

Pins the authoritative behavior:
  * outside combat, movement is NOT budget-limited (exploration stays free);
  * inside combat, movement spends the ACTIVE turn's budget, priced with the
    movecost SSOT (squares) — the same unit that validates and charges it;
  * over-budget walks stop early with a reason, never silently;
  * listed combatants move only on their own turn (DM exempt as before);
  * Dash spends the ACTION and grants one more turn-speed of movement, once;
  * End Turn advances initiative and the next combatant gets fresh resources;
  * slots/actions reset per turn.
"""
import pytest
from starlette.testclient import TestClient

from app import db, main
from app import movecost
from app.room import combat as CB
from test_movement_fog import (H, base_room, join_room, make_char, reg,
                               recv_until, state_of, ws_connect)


def reveal_all(client, dm, code):
    """Fog aside: preview tests route over long distances (economy, not LOS).
    Uses the DM's own fog channel (fog_edit, WORLD cells, 512 per message)."""
    g = state_of(client, dm, code)["grid"]
    cells = [{"x": x, "y": y, "explored": 1} for y in range(g["h"]) for x in range(g["w"])]
    with ws_connect(client, dm, code) as ws:
        n = 0
        for i in range(0, len(cells), 512):
            ws.send_json({"type": "fog_edit", "cells": cells[i:i + 512]})
            n += 1
        for _ in range(n):
            recv_until(ws, "fog_changed")         # drain before close (TestClient)


@pytest.fixture()
def client():
    return TestClient(main.app)


def my_token_id(client, user, code):
    return next(t for t in state_of(client, user, code)["tokens"]
                if t.get("character_id"))["id"]


def npc_token_id(client, dm, code):
    return next((t for t in state_of(client, dm, code)["tokens"]
                 if t.get("owner_user_id") is None), {}).get("id")


def start_combat(client, dm, code, extra_npc=True):
    """Start initiative with exactly two listed combatants (mine + an NPC).
    The NPC is parked far from spawn so routes/targets stay deterministic."""
    with ws_connect(client, dm, code) as ws:
        npc_id = npc_token_id(client, dm, code)
        if npc_id is None and extra_npc:
            ws.send_json({"type": "add_token", "label": "Goblin"})
            npc_id = recv_until(ws, "token_add")["payload"]["id"]
            ws.send_json({"type": "move", "token_id": npc_id, "tx": 30, "ty": 20,
                          "teleport": True})
            recv_until(ws, "step")
        ws.send_json({"type": "init_start"})
        ev = recv_until(ws, "initiative")
    assert ev["payload"]["combat"] is True
    return CB.get_init(db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"])


def pass_until_mine(client, dm, code, mine):
    """Advance (DM) until MY token is the active one — deterministic despite
    random initiative rolls."""
    st = db.q1("SELECT id FROM rooms WHERE code=?", (code,))
    init = CB.get_init(st["id"])
    order_ids = [o["token_id"] for o in init["order"]]
    for _ in range(len(order_ids) + 1):
        if init["turn"] and init["turn"]["token_id"] == mine:
            return init
        with ws_connect(client, dm, code) as ws:
            ws.send_json({"type": "init_next"})
            recv_until(ws, "initiative")
        init = CB.get_init(st["id"])
    raise AssertionError("never became active")


# ---------- exploration ----------

def test_exploration_movement_is_not_budget_limited(client):
    """No combat: a 30-ft token (6-square budget) may walk 12 squares —
    terrain/paths still apply, the combat economy does not."""
    dm, player, code, _ = base_room(client)
    mine = my_token_id(client, player, code)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "move", "token_id": mine, "tx": 20, "ty": 6,
                      "teleport": False})
        recv_until(ws, "move_state")            # moving=True
        recv_until(ws, "move_state")            # moving=False, no reason
    tok = db.q1("SELECT x, y FROM tokens WHERE id=?", (mine,))
    assert (int(tok["x"] // 50), int(tok["y"] // 50)) == (20, 6)


# ---------- combat budget ----------

def test_combat_move_consumes_budget_same_units(client):
    dm, player, code, _ = base_room(client)
    mine = my_token_id(client, player, code)
    start_combat(client, dm, code)
    init = pass_until_mine(client, dm, code, mine)
    assert init["turn"]["move_total"] == movecost.walk_budget(30)   # unit pin: 6 squares
    assert init["turn"]["move_spent"] == 0
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "move", "token_id": mine, "tx": 11, "ty": 6,
                      "teleport": False})
        recv_until(ws, "move_state")
        ev = recv_until(ws, "initiative")       # the charge broadcast
    t = ev["payload"]["turn"]
    assert t["token_id"] == mine and t["move_spent"] == 3           # 3 orthogonal steps
    tok = db.q1("SELECT x FROM tokens WHERE id=?", (mine,))
    assert int(tok["x"] // 50) == 11


def test_over_budget_walk_stops_early_with_reason(client):
    dm, player, code, _ = base_room(client)
    mine = my_token_id(client, player, code)
    start_combat(client, dm, code)
    pass_until_mine(client, dm, code, mine)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "move", "token_id": mine, "tx": 17, "ty": 6,   # 9 squares > 6
                      "teleport": False})
        recv_until(ws, "move_state")                                        # start
        recv_until(ws, "error", fail_on_error=False)                        # Out of movement
        ev = recv_until(ws, "move_state", fail_on_error=False)
    assert ev["payload"]["reason"] == "budget"
    tok = db.q1("SELECT x, y FROM tokens WHERE id=?", (mine,))
    assert (int(tok["x"] // 50), int(tok["y"] // 50)) == (14, 6)            # spent 6, stopped
    st = db.q1("SELECT id FROM rooms WHERE code=?", (code,))
    assert CB.get_init(st["id"])["turn"]["move_spent"] == 6


def test_inactive_combatant_cannot_move(client):
    dm, player, code, _ = base_room(client)
    mine = my_token_id(client, player, code)
    start_combat(client, dm, code)
    init = pass_until_mine(client, dm, code, mine)
    other = next(o for o in init["order"] if o["token_id"] != mine)["token_id"]
    with ws_connect(client, dm, code) as ws:                               # pass to the NPC
        ws.send_json({"type": "init_next"})
        recv_until(ws, "initiative")
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "move", "token_id": mine, "tx": 10, "ty": 6, "teleport": False})
        ev = recv_until(ws, "error", fail_on_error=False)
    assert "not your turn" in ev["payload"]["msg"]


def test_preview_reports_turn_budget_in_cost_units(client):
    dm, player, code, _ = base_room(client)
    mine = my_token_id(client, player, code)
    reveal_all(client, dm, code)
    start_combat(client, dm, code)
    pass_until_mine(client, dm, code, mine)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "path_preview", "token_id": mine, "tx": 17, "ty": 6,
                      "request_id": 1})
        p = recv_until(ws, "path_preview")["payload"]
    assert p["cost"] == 9 and p["move_remaining"] == 6 and p["within_budget"] is False
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "path_preview", "token_id": mine, "tx": 12, "ty": 6,
                      "request_id": 2})
        p = recv_until(ws, "path_preview")["payload"]
    assert p["cost"] == 4 and p["within_budget"] is True


# ---------- Dash ----------

def send_as(client, user, code, payload, want="initiative"):
    with ws_connect(client, user, code) as ws:
        ws.send_json(payload)
        return recv_until(ws, want, fail_on_error=False)


def test_dash_spends_action_and_grants_movement(client):
    dm, player, code, _ = base_room(client)
    mine = my_token_id(client, player, code)
    start_combat(client, dm, code)
    init = pass_until_mine(client, dm, code, mine)
    base = init["turn"]["move_total"]
    ev = send_as(client, player, code, {"type": "dash", "token_id": mine})
    t = ev["payload"]["turn"]
    assert t["action"] == "used"
    assert t["move_total"] == base + movecost.walk_budget(30)      # +6 squares this turn
    assert t["move_spent"] == 0                                    # nothing permanently changed
    from app import gear
    tok = db.q1("SELECT character_id FROM tokens WHERE id=?", (mine,))
    row = db.q1("SELECT speed FROM characters WHERE id=?", (tok["character_id"],))
    assert gear.clean_speeds(row["speed"])["walk"] == 30           # stored speed untouched


def test_dash_cannot_be_used_twice(client):
    dm, player, code, _ = base_room(client)
    mine = my_token_id(client, player, code)
    start_combat(client, dm, code)
    pass_until_mine(client, dm, code, mine)
    ev = send_as(client, player, code, {"type": "dash", "token_id": mine})
    assert ev["kind"] == "initiative" and ev["payload"]["turn"]["action"] == "used"
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "dash", "token_id": mine})
        err = recv_until(ws, "error", fail_on_error=False)
    assert "no action left" in err["payload"]["msg"].lower()


def test_dash_requires_own_turn(client):
    dm, player, code, _ = base_room(client)
    mine = my_token_id(client, player, code)
    start_combat(client, dm, code)
    pass_until_mine(client, dm, code, mine)
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "init_next"})
        recv_until(ws, "initiative")
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "dash", "token_id": mine})
        err = recv_until(ws, "error", fail_on_error=False)
    assert err["payload"]["msg"] == "It is not your turn"


# ---------- End Turn ----------

def test_end_turn_advances_and_next_gets_fresh_resources(client):
    dm, player, code, _ = base_room(client)
    mine = my_token_id(client, player, code)
    start_combat(client, dm, code)
    init = pass_until_mine(client, dm, code, mine)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "move", "token_id": mine, "tx": 10, "ty": 6, "teleport": False})
        recv_until(ws, "move_state")
        recv_until(ws, "initiative")                                 # charged 2 units
        ws.send_json({"type": "end_turn"})
        ev = recv_until(ws, "initiative")
    nxt = ev["payload"]
    assert nxt["turn"]["token_id"] != mine                            # order advanced
    assert nxt["turn"]["move_spent"] == 0
    assert nxt["turn"]["move_total"] == movecost.walk_budget(30)      # own fresh budget
    assert all(nxt["turn"][s] == "available" for s in ("action", "bonus", "reaction"))


def test_end_turn_permission(client):
    dm, player, code, _ = base_room(client)
    mine = my_token_id(client, player, code)
    stranger = reg(client, "str")
    join_room(client, stranger, code)
    start_combat(client, dm, code)
    pass_until_mine(client, dm, code, mine)
    with ws_connect(client, stranger, code) as ws:
        ws.send_json({"type": "end_turn"})
        err = recv_until(ws, "error", fail_on_error=False)
    assert "active token's owner" in err["payload"]["msg"]


# ---------- per-turn reset across a round ----------

def test_resources_reset_on_new_round(client):
    dm, player, code, _ = base_room(client)
    mine = my_token_id(client, player, code)
    start_combat(client, dm, code)
    pass_until_mine(client, dm, code, mine)
    ev = send_as(client, player, code, {"type": "dash", "token_id": mine})
    assert ev["payload"]["turn"]["action"] == "used"
    for _ in range(len(ev["payload"]["order"])):                      # full round back to me
        with ws_connect(client, dm, code) as ws:
            ws.send_json({"type": "init_next"})
            recv_until(ws, "initiative")
    st = db.q1("SELECT id FROM rooms WHERE code=?", (code,))
    init = CB.get_init(st["id"])
    assert init["turn"]["token_id"] == mine
    assert init["turn"]["action"] == "available"
    assert init["turn"]["move_spent"] == 0
