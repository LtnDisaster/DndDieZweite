"""Behavioural tests for the A* pathfinder: straight lines, diagonals, wall
blocking, corner-cutting prevention, and difficult-terrain cost."""
from app.path import find_path


def grid(w, h, walls=(), rough=()):
    cells = [0] * (w * h)
    for (x, y) in walls:
        cells[y * w + x] = 1
    for (x, y) in rough:
        cells[y * w + x] = 2
    return cells


def test_straight_open_line():
    p = find_path(5, 1, grid(5, 1), (0, 0), (4, 0))
    assert p == [(1, 0), (2, 0), (3, 0), (4, 0)]


def test_start_equals_goal_is_empty_path():
    assert find_path(3, 3, grid(3, 3), (1, 1), (1, 1)) == []


def test_wall_blocks_in_a_one_tall_corridor():
    assert find_path(5, 1, grid(5, 1, walls=[(2, 0)]), (0, 0), (4, 0)) is None


def test_unreachable_behind_closed_wall():
    # full wall column x=1 separates the grid in a 2-row map
    p = find_path(3, 2, grid(3, 2, walls=[(1, 0), (1, 1)]), (0, 0), (2, 0))
    assert p is None


def test_diagonal_is_used_when_open():
    p = find_path(2, 2, grid(2, 2), (0, 0), (1, 1))
    assert p == [(1, 1)]  # single diagonal step


def test_corner_cutting_is_forbidden():
    # To step diagonally (0,0)->(1,1) both orthogonal neighbours must be walkable.
    # Wall at (1,0) forbids the diagonal; the only legal route is around via (0,1).
    p = find_path(2, 2, grid(2, 2, walls=[(1, 0)]), (0, 0), (1, 1))
    assert p == [(0, 1), (1, 1)]


def test_walls_along_path_are_never_visited():
    walls = [(1, 0), (1, 1)]
    p = find_path(3, 3, grid(3, 3, walls=walls), (0, 0), (2, 0))
    assert p is not None
    assert set(p) & set(walls) == set()


def test_difficult_terrain_is_avoided_when_a_floor_detour_is_cheaper():
    # Top row is a difficult corridor; a longer all-floor detour is cheaper
    # (fewer double-cost steps), so the pathfinder must route around the rough cells.
    rough = [(1, 0), (2, 0), (3, 0)]
    p = find_path(5, 2, grid(5, 2, rough=rough), (0, 0), (4, 0))
    assert p is not None
    assert p[-1] == (4, 0)
    assert not any((x, y) in rough for (x, y) in p)  # never walks on rough cells


def test_out_of_bounds_goal_rejected():
    assert find_path(3, 3, grid(3, 3), (0, 0), (9, 9)) is None


def test_goal_inside_wall_rejected():
    assert find_path(3, 3, grid(3, 3, walls=[(2, 2)]), (0, 0), (2, 2)) is None


def test_closed_door_edge_blocks_a_corridor():
    be = {frozenset({(1, 0), (2, 0)})}                     # a closed door between the two cells
    assert find_path(4, 1, grid(4, 1), (0, 0), (3, 0)) == [(1, 0), (2, 0), (3, 0)]
    assert find_path(4, 1, grid(4, 1), (0, 0), (3, 0), blocked_edges=be) is None


def test_open_door_edge_is_passable():
    # an open door contributes no blocked edge, so the route is unchanged
    assert find_path(4, 1, grid(4, 1), (0, 0), (3, 0), blocked_edges=set()) == \
        [(1, 0), (2, 0), (3, 0)]


def test_closed_door_forces_a_detour():
    # 3x2 open field, goal top-right; block the direct top edge → must loop via row 1
    be = {frozenset({(1, 0), (2, 0)})}
    p = find_path(3, 2, grid(3, 2), (0, 0), (2, 0), blocked_edges=be)
    assert p is not None and (1, 0) not in p and (1, 1) in p
