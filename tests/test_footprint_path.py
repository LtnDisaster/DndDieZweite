"""Footprint-aware pathfinding and collision tests."""
from app.footprint import valid_final_position
from app.mapmodel import default_map, blocked_edges
from app.path import find_path


def _mp(w, h, cells=None, **kw):
    """D72: pure grid modules take the map object; cells stay WORLD space."""
    m = {"w": w, "h": h}
    if cells is not None:
        m["cells"] = cells
    m.update(kw)
    return m



def grid(w, h, walls=(), rough=()):
    cells = [0] * (w * h)
    for (x, y) in walls:
        cells[y * w + x] = 1
    for (x, y) in rough:
        cells[y * w + x] = 2
    return cells


def test_medium_one_cell_corridor_still_works():
    assert find_path(_mp(5, 1, grid(5, 1)), (0, 0), (4, 0), footprint=1) == [(1, 0), (2, 0), (3, 0), (4, 0)]


def test_large_cannot_enter_one_cell_corridor():
    assert find_path(_mp(5, 2, grid(5, 2, walls=[(0, 1), (1, 1), (2, 1), (3, 1), (4, 1)])), (0, 0), (4, 0), footprint=2) is None


def test_large_can_cross_two_cell_corridor():
    p = find_path(_mp(5, 2, grid(5, 2)), (0, 0), (3, 0), footprint=2)
    assert p is not None and p[-1] == (3, 0)


def test_huge_footprint_must_remain_inside_map():
    assert find_path(_mp(2, 10, grid(2, 10)), (0, 0), (0, 5), footprint=3) is None


def test_large_footprint_rejects_blocked_terrain():
    assert find_path(_mp(4, 4, grid(4, 4, walls=[(2, 1)])), (0, 0), (2, 0), footprint=2) is None


def test_large_closed_door_on_any_leading_edge_blocks():
    be = {frozenset({(2, 0), (3, 0)}), frozenset({(2, 1), (3, 1)})}
    assert find_path(_mp(6, 2, grid(6, 2)), (0, 0), (4, 0), blocked_edges=be, footprint=2) is None


def test_large_open_door_allows_sufficient_width():
    p = find_path(_mp(6, 2, grid(6, 2)), (0, 0), (4, 0), blocked_edges=set(), footprint=2)
    assert p is not None and p[-1] == (4, 0)


def test_large_diagonal_corner_is_conservative():
    # The 2x2 token starts at (0,0). The only diagonal exit requires both 2x2
    # intermediate positions; a wall below makes that diagonal illegal.
    assert find_path(_mp(3, 2, grid(3, 2, walls=[(1, 1)])), (0, 0), (2, 0), footprint=2) is None


def test_preview_allowed_cells_only_permit_known_area():
    allowed = {(x, y) for x in range(2) for y in range(1)}
    assert find_path(_mp(5, 1, grid(5, 1)), (0, 0), (2, 0), footprint=1, allowed_cells=allowed) is None
    assert find_path(_mp(2, 1, grid(2, 1)), (0, 0), (1, 0), footprint=1, allowed_cells=allowed) == [(1, 0)]


def test_final_collision_blocks_different_owner_footprints():
    mp = default_map(10, 10)
    moving = {"id": 1, "x": 4.5 * mp["cell"], "y": 5.5 * mp["cell"],
              "owner_user_id": 1, "size": "Large"}
    other = {"id": 2, "x": 5.5 * mp["cell"], "y": 6.5 * mp["cell"],
             "owner_user_id": 2, "size": "Medium"}
    assert not valid_final_position(mp, moving, (4, 5), [other])


def test_final_collision_allows_same_owner_overlap():
    mp = default_map(10, 10)
    moving = {"id": 1, "x": 4.5 * mp["cell"], "y": 5.5 * mp["cell"],
              "owner_user_id": 1, "size": "Large"}
    friendly = {"id": 2, "x": 5.5 * mp["cell"], "y": 6.5 * mp["cell"],
                "owner_user_id": 1, "size": "Medium"}
    assert valid_final_position(mp, moving, (4, 5), [friendly])


def test_final_collision_allows_ownerless_npc_pass_through_but_not_finish():
    mp = default_map(10, 10)
    moving = {"id": 1, "x": 4.5 * mp["cell"], "y": 5.5 * mp["cell"],
              "owner_user_id": None, "size": "Large"}
    npc = {"id": 2, "x": 5.5 * mp["cell"], "y": 6.5 * mp["cell"],
           "owner_user_id": None, "size": "Medium"}
    assert not valid_final_position(mp, moving, (4, 5), [npc])


def test_closed_door_helper_is_reused_by_footprint_movement():
    mp = default_map(5, 2)
    mp["doors"] = [{"id": "d", "x": 2, "y": 0, "dir": "v", "closed": True, "locked": False}]
    assert frozenset({(2, 0), (3, 0)}) in blocked_edges(mp)
