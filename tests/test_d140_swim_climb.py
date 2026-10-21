"""D140 (AP-027): swimming and climbing are allowed WITHOUT the matching
speed — the SRD prices them (+1 foot per foot, +2 in difficult terrain),
it does not forbid them. Only flight genuinely needs a fly speed.
"""
import pytest
from starlette.testclient import TestClient

from app import db, main, movecost
from tests.test_movecost import _mp, grid
from tests.test_movement_fog import base_room, recv_until, ws_connect


@pytest.fixture
def client():
    app = main.app
    with TestClient(app) as c:
        yield c


# ------------------------------------------------------------------ cost

def test_the_srd_surcharge_is_an_addition_not_a_multiplication():
    flat = _mp(10, 10, grid(10, 10))
    hard = _mp(10, 10, grid(10, 10, [(1, 0)]))
    assert movecost.route_cost(flat, [(0, 0), (1, 0)]) == 1                  # walk
    assert movecost.route_cost(flat, [(0, 0), (1, 0)], mode="swim", strained=True) == 2     # 1+1
    assert movecost.route_cost(flat, [(0, 0), (1, 0)], mode="climb", strained=True) == 2
    assert movecost.route_cost(hard, [(0, 0), (1, 0)]) == 2                  # difficult walk
    assert movecost.route_cost(hard, [(0, 0), (1, 0)], mode="swim", strained=True) == 3     # 1+2, literal
    assert movecost.route_cost(flat, [(0, 0), (1, 1)], mode="swim", strained=True) == 2     # 1st diag 1+1
    assert movecost.route_cost(flat, [(0, 0), (1, 0), (2, 1)], mode="swim", strained=True) == 2 + 2
    assert movecost.route_cost(flat, [(0, 0), (1, 1), (2, 2)], mode="swim", strained=True) == 2 + 3   # 2nd diag base 2+1
    assert movecost.route_cost(flat, [(0, 0), (1, 0)], mode="fly") == 1      # fly: no surcharge


def test_fly_without_speed_stays_refused_swim_without_speed_moves(client):
    dm, player, code, ch = base_room(client)
    rid = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
    tok = next(t for t in db.q("SELECT * FROM tokens WHERE room_id=?", (rid,))
               if t["character_id"] == ch["id"])
    assert tok["id"]
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "move", "token_id": tok["id"], "tx": 3, "ty": 0,
                      "mode": "fly"})
        ws.send_json({"type": "move", "token_id": tok["id"], "tx": 2, "ty": 0,
                      "mode": "swim"})
        ws.send_json({"type": "chat", "text": "@@swflush@@"})
        errs, steps = [], 0
        while True:
            ev = ws.receive_json()
            k = ev.get("kind")
            if k == "chat" and "@@swflush@@" in str(ev.get("payload", {}).get("text", "")):
                break
            if k == "error":
                errs.append(ev["payload"]["msg"])
            if k in ("step", "move", "snapshot"):
                steps += 1
    assert any("fly speed" in e for e in errs)
    assert not any("swim" in e for e in errs)
    assert steps >= 1


# ------------------------------------------------- D144: speed changes cost

def test_the_surcharge_follows_the_speed_not_the_mode(client):
    from app.room import movement as MOV
    pc_tok = db.q1("SELECT * FROM tokens LIMIT 1")   # any row: character branch
    npc = {"speed": 30, "swim": 30}
    npc_tok = {"character_id": None, "npc": db.json_dumps(npc)}
    assert MOV._strained(npc_tok, "walk") is False
    assert MOV._strained(npc_tok, "fly") is False         # fly: refused, never surcharged
    assert MOV._strained(npc_tok, "swim") is False        # HAS swim: no surcharge
    # the grid layer is creature-blind: it only ever sees the flag:
    flat = _mp(10, 10, grid(10, 10))
    assert movecost.route_cost(flat, [(0, 0), (1, 0)], mode="swim") == 1          # default
    assert movecost.route_cost(flat, [(0, 0), (1, 0)], mode="swim", strained=False) == 1
    assert movecost.route_cost(flat, [(0, 0), (1, 0)], mode="swim", strained=True) == 2


def test_strained_swim_draws_on_the_walk_pool(client):
    # D144: the turn budget follows the CREATURE. A walk-only creature that
    # swims pays its walk pool at the SRD rate — no phantom 0 budget, and
    # spend_move lands the surcharged units on the same walk ledger.
    from app.room import combat as CB
    dm, player, code, ch = base_room(client)
    rid = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
    tok = next(t for t in db.q("SELECT * FROM tokens WHERE room_id=?", (rid,))
               if t["character_id"] == ch["id"])
    init = {"combat": True, "order": [{"token_id": tok["id"]}], "active": 0, "round": 1}
    CB.begin_turn(init)
    assert CB.move_remaining(init, tok["id"], "walk") == 6      # speed 30
    assert CB.move_remaining(init, tok["id"], "swim") == 6      # D144 fallback
    assert CB.move_remaining(init, tok["id"], "fly") == 0       # no fly speed
    CB.set_init(rid, init)
    CB.spend_move(rid, tok["id"], 4, mode="swim")               # 2 surcharged steps
    after = CB.get_init(rid)
    assert CB.move_remaining(after, tok["id"], "swim") == 2     # walk pool drained
    assert after["turn"]["move_by"]["walk"]["spent"] == 4       # one honest ledger


def test_surcharged_walk_costs_double_units_in_the_ledger(client):
    # The full turn view: swim tx 7 squares on a 6-square pool = three
    # surcharged squares (2 units each), exactly at the budget edge.
    from app.room import combat as CB
    dm, player, code, ch = base_room(client)
    rid = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
    tok = next(t for t in db.q("SELECT * FROM tokens WHERE room_id=?", (rid,))
               if t["character_id"] == ch["id"])
    db.x("UPDATE tokens SET x=25, y=25 WHERE id=?", (tok["id"],))
    flat = _mp(10, 10, grid(10, 10))
    route = [(0, 0)] + [(i, 0) for i in range(1, 8)]
    total = movecost.route_cost(flat, route, mode="swim", strained=True)
    assert total == 14                                          # 7 squares, 2 each
    assert total // 2 > 6 and total > 6                         # a 6-square pool ends mid-route
