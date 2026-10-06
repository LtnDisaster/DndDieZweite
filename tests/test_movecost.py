"""Phase 2 (D68): canonical 5e movement cost — diagonals 1, 2, 1, 2... from the
route start; difficult terrain doubles the unit of the entering step; budget =
speed//5 squares surfaced on the preview. Search weights (10/14) are untouched.
"""
import pytest

from app import db, movecost
from starlette.testclient import TestClient

from app.main import app
from test_movement_fog import (base_room, park, recv_until, state_of,
                               ws_connect)


def _mp(w, h, cells=None, **kw):
    """D72: pure grid modules take the map object; cells stay WORLD space."""
    m = {"w": w, "h": h}
    if cells is not None:
        m["cells"] = cells
    m.update(kw)
    return m


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def flat(w, h):
    return [0] * (w * h)


def grid(w, h, difficult=()):
    cells = flat(w, h)
    for (x, y) in difficult:
        cells[y * w + x] = 2
    return cells


# ---------- unit rules ----------

def test_orthogonal_line_costs_one_per_square():
    cells = flat(10, 10)
    route = [(0, 0)] + [(i, 0) for i in range(1, 6)]
    assert movecost.route_cost(_mp(10, 10, cells), route) == 5


def test_diagonals_alternate_one_two():
    cells = flat(10, 10)
    route = [(0, 0)] + [(i, i) for i in range(1, 5)]
    assert movecost.route_cost(_mp(10, 10, cells), route) == 1 + 2 + 1 + 2


def test_diagonal_counting_spans_the_whole_route_not_each_run():
    cells = flat(10, 10)
    # N, NE, E, NE -> second diagonal still counts 2 although an orthogonal step sits between
    route = [(0, 0), (0, 1), (1, 2), (2, 2), (3, 3)]
    assert movecost.route_cost(_mp(10, 10, cells), route) == 1 + 1 + 1 + 2


def test_difficult_doubles_the_entering_step():
    cells = grid(10, 10, [(1, 0), (2, 1)])
    orth = movecost.route_cost(_mp(10, 10, cells), [(0, 0), (1, 0)])
    assert orth == 2
    # (1,0)->(2,1) is the FIRST diagonal (unit 1) entering difficult -> doubled to 2
    diag = movecost.route_cost(_mp(10, 10, cells), [(0, 0), (1, 0), (2, 1)])
    assert diag == 2 + 2
    hard = grid(10, 10, [(1, 1), (2, 2)])
    # 1st diagonal into difficult: 1*2, 2nd diagonal into difficult: 2*2
    assert movecost.route_cost(_mp(10, 10, hard), [(0, 0), (1, 1), (2, 2)]) == 2 + 4


def test_large_footprint_counts_only_newly_entered_cells():
    cells = grid(10, 10, [(3, 0)])
    # slides (0,0)->(1,0): new cells (2,0),(2,1) are plain -> 1
    # then (1,0)->(2,0): new cells (3,0),(3,1) touch difficult -> unit doubled
    whole = movecost.route_cost(_mp(10, 10, cells), [(0, 0), (1, 0), (2, 0)], footprint=2)
    assert whole == 1 + 2
    into_it = movecost.route_cost(_mp(10, 10, cells), [(1, 0), (2, 0)], footprint=2)
    assert into_it == 2                                        # (3,0) newly covered -> unit doubled


def test_non_adjacent_route_step_is_rejected():
    with pytest.raises(ValueError):
        movecost.route_cost(_mp(10, 10, flat(10, 10)), [(0, 0), (2, 0)])


def test_walk_budget_is_speed_over_five():
    assert movecost.walk_budget(30) == 6
    assert movecost.walk_budget(0) == 0
    assert movecost.walk_budget(None) == 6                     # sane default, never a crash


# ---------- preview integration ----------

def test_preview_surfaces_speed_budget(client):
    dm, player, code, ch = base_room(client)
    tok = park(client, dm, code, db.q1(
        "SELECT id FROM tokens WHERE room_id=? AND character_id=?",
        (db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"], ch["id"]))["id"])
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "path_preview", "token_id": tok["id"],
                      "tx": 20, "ty": 12, "request_id": 1})
        prev = recv_until(ws, "path_preview")["payload"]
        assert prev["cost"] == 4 and prev["budget"] == 6 and prev["within_budget"] is True
        db.x("UPDATE characters SET speed=10 WHERE id=?", (ch["id"],))   # 2 squares
        ws.send_json({"type": "path_preview", "token_id": tok["id"],
                      "tx": 20, "ty": 12, "request_id": 2})
        prev = recv_until(ws, "path_preview")["payload"]
        assert prev["budget"] == 2 and prev["within_budget"] is False
        assert prev["cost"] == 4                                      # cost rule unchanged by speed
