"""Deterministic wall/door LOS and footprint-visible-cell tests."""
from app import los, mapmodel


def mp(w=12, h=12, walls=(), doors=()):
    m = mapmodel.default_map(w, h)
    for (x, y) in walls:
        m["cells"][y * w + x] = 1
    m["doors"] = [{"id": f"d{i}", "x": x, "y": y, "dir": d, "closed": c, "locked": locked,
                   "label": "Door"} for i, (x, y, d, c, locked) in enumerate(doors)]
    return m


def indices(mp_obj):
    return mp_obj


def test_straight_line_is_visible():
    assert los.line_of_sight(mp(), (1, 1), (5, 1)) is True


def test_wall_blocks_line():
    walls = [(3, 0), (3, 1), (3, 2)]
    assert los.line_of_sight(mp(walls=walls), (1, 1), (5, 1)) is False
    assert los.line_of_sight(mp(walls=walls), (1, 1), (3, 1)) is True  # the wall surface itself


def test_closed_door_blocks_and_open_door_does_not():
    closed = mp(doors=[(3, 1, "v", True, False)])
    open_door = mp(doors=[(3, 1, "v", False, False)])
    assert los.line_of_sight(closed, (1, 1), (5, 1), mapmodel.blocked_edges(closed)) is False
    assert los.line_of_sight(open_door, (1, 1), (5, 1), mapmodel.blocked_edges(open_door)) is True


def test_locked_closed_door_blocks():
    m = mp(doors=[(3, 1, "v", True, True)])
    assert los.line_of_sight(m, (1, 1), (5, 1), mapmodel.blocked_edges(m)) is False


def test_sealed_diagonal_corner_is_not_visible():
    walls = [(1, 0), (0, 1)]
    assert los.line_of_sight(mp(walls=walls), (0, 0), (1, 1)) is False


def test_open_diagonal_corner_is_visible():
    assert los.line_of_sight(mp(), (0, 0), (1, 1)) is True


def test_vision_radius_is_clipped():
    m = mp(w=30, h=30)
    seen = los.visible_cells(m, [(15, 15)], radius=1)
    assert 15 * 30 + 15 in seen
    assert 15 * 30 + 17 not in seen
    assert len(seen) == 9


def test_large_viewer_uses_every_footprint_cell():
    m = mp(w=12, h=10, walls=[(4, y) for y in range(0, 8)])
    small = los.visible_cells(m, [(2, 5)], radius=6)
    large = los.visible_cells(m, [(2, 7), (3, 7), (2, 8), (3, 8)], radius=6)
    assert 5 * m["w"] + 6 not in small        # wall at x=4 blocks the small source
    assert 8 * m["w"] + 6 in large            # its lower footprint cells see through the opening


def test_large_target_is_visible_when_one_footprint_cell_is_visible():
    m = mp(w=10, h=10)
    visible = los.visible_cells(m, [(0, 5)], radius=6)
    target_cells = {(5, 5), (6, 5), (5, 6), (6, 6)}
    assert bool(target_cells.intersection({(i % m["w"], i // m["w"]) for i in visible}))
