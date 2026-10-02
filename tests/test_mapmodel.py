"""Map model: sanitize/validate, fog reveal, and per-role (fog + hidden info) filtering.

Note: sanitize() enforces a MINIMUM grid size (MAX_W/MAX_H upper, 8x6 lower). Test
grids below 8x6 get clamped up, so cell-array length must match the clamped size.
"""
import json

from app import mapmodel as mm

_cw = lambda w: max(8, min(mm.MAX_W, w))
_ch = lambda h: max(6, min(mm.MAX_H, h))


def mk(w=10, h=8, **over):
    W, H = _cw(w), _ch(h)
    m = {"w": W, "h": H, "cell": 50, "cells": [0] * (W * H),
         "explored": [0] * (W * H), "traps": [], "loot": [], "doors": [], "pins": []}
    m.update(over)
    return m


# ---- sanitize / validation ----
def test_sanitize_accepts_clean_map():
    out = mm.sanitize(mk())
    assert out and out["w"] == 10 and out["h"] == 8 and len(out["cells"]) == 80


def test_sanitize_rejects_non_dict():
    assert mm.sanitize([1, 2, 3]) is None
    assert mm.sanitize(None) is None


def test_sanitize_rejects_bad_dimensions():
    assert mm.sanitize({"w": "x", "h": 8, "cells": [0] * (_cw(1) * 8)}) is None
    assert mm.sanitize({"h": 8, "cells": []}) is None  # missing w


def test_sanitize_rejects_wrong_cells_length():
    assert mm.sanitize({"w": 10, "h": 8, "cells": [0, 1, 2]}) is None


def test_sanitize_clamps_cells_to_0_1_2():
    cells = [5, -3, 9, 1, 0, 2] + [0] * (80 - 6)
    out = mm.sanitize(mk(cells=cells))
    assert out["cells"][:6] == [2, 0, 2, 1, 0, 2]


def test_sanitize_clamps_up_undersized_grid():
    out = mm.sanitize({"w": 4, "h": 3, "cell": 50,
                       "cells": [0] * 48, "explored": [0] * 48, "traps": [], "loot": []})
    assert out["w"] == 8 and out["h"] == 6 and len(out["cells"]) == 48


def test_sanitize_separates_traps_and_loot():
    m = mk(traps=[{"id": "t1", "x": 0, "y": 0, "dc": 13, "dmg": "2d6"}],
           loot=[{"id": "l1", "x": 1, "y": 1, "label": "gold"}])
    out = mm.sanitize(m)
    assert len(out["traps"]) == 1 and out["traps"][0]["dc"] == 13
    assert len(out["loot"]) == 1 and out["loot"][0]["taken_by"] is None


def test_sanitize_rejects_duplicate_entity_ids():
    m = mk(traps=[{"id": "same", "x": 0, "y": 0, "dc": 12, "dmg": "1d4"},
                  {"id": "same", "x": 1, "y": 0, "dc": 12, "dmg": "1d4"}])
    assert mm.sanitize(m) is None


def test_load_bad_json_returns_default():
    assert mm.load("{not json")["cells"] == [0] * (mm.DEFAULT_W * mm.DEFAULT_H)
    assert mm.load("")["w"] == mm.DEFAULT_W


# ---- fog reveal ----
def test_reveal_cells_marks_area_and_reports_only_new_cells():
    m = mm.default_map(20, 20)
    visible = {(x, y) for x in (9, 10, 11) for y in (9, 10, 11)}
    first = mm.reveal_cells(m, visible)
    assert len(first) == 9 and all(m["explored"][i] == 1 for i in first)
    assert mm.reveal_cells(m, visible) == []  # nothing new the second time


# ---- per-role visibility filtering ----
def test_player_view_nulls_unexplored_and_hides_undiscovered_secrets():
    m = mm.default_map(20, 20)
    m["traps"] = [{"id": "t1", "x": 19, "y": 19, "dc": 12, "dmg": "1d4", "discovered": False},
                  {"id": "t2", "x": 0, "y": 0, "dc": 12, "dmg": "1d4", "discovered": True}]
    m["loot"] = [{"id": "l1", "x": 1, "y": 1, "label": "mine", "taken_by": 7},
                 {"id": "l2", "x": 1, "y": 1, "label": "theirs", "taken_by": 99}]
    out = mm.visible_map(m, user_id=7, is_dm=False, visible_cells={(0, 0), (1, 1), (2, 2)})
    assert out["cells"][0] is not None      # near vision is revealed
    assert out["cells"][-1] is None          # far corner stays fogged (null)
    assert [t["id"] for t in out["traps"]] == ["t2"]   # undiscovered trap withheld
    assert [l["id"] for l in out["loot"]] == ["l1"]     # only this user's loot


def test_dm_view_is_unfiltered_truth():
    m = mk(traps=[{"id": "t1", "x": 9, "y": 7, "dc": 12, "dmg": "1d4", "discovered": False}])
    assert mm.visible_map(m, user_id=1, is_dm=True, visible_cells=()) is m


# ---- doors ----

def test_sanitize_normalises_doors_and_lock_forces_closed():
    m = mk(doors=[{"x": 3, "y": 2, "dir": "v", "closed": False},
                  {"x": 5, "y": 2, "dir": "l"},                       # "l" re-anchors left → dir v at x=4
                  {"x": 7, "y": 2, "dir": "h", "closed": False, "locked": True}])
    out = mm.sanitize(m)
    assert [(d["x"], d["y"], d["dir"], d["closed"], d["locked"]) for d in out["doors"]] == \
        [(3, 2, "v", False, False), (4, 2, "v", True, False), (7, 2, "h", True, True)]


def test_sanitize_dedupes_door_edges_and_drops_out_of_bounds():
    m = mk(doors=[{"x": 3, "y": 2, "dir": "v"}, {"x": 4, "y": 2, "dir": "l"},   # same edge twice
                  {"x": 9, "y": 7, "dir": "h"}])                                # h at bottom row → no neighbor
    out = mm.sanitize(m)
    assert len(out["doors"]) == 1 and out["doors"][0]["dir"] == "v"


def test_blocked_edges_covers_closed_and_locked_only():
    out = mm.sanitize(mk(doors=[{"x": 1, "y": 1, "dir": "v", "closed": False},
                                {"x": 3, "y": 3, "dir": "h", "closed": True}]))
    edges = mm.blocked_edges(out)
    assert frozenset({(1, 1), (2, 1)}) not in edges          # open door is passable
    assert frozenset({(3, 3), (3, 4)}) in edges              # closed door blocks


def test_find_door_matches_either_orientation():
    out = mm.sanitize(mk(doors=[{"x": 4, "y": 5, "dir": "h"}]))
    assert mm.find_door(out, 4, 5, 4, 6) is not None         # A→B
    assert mm.find_door(out, 4, 6, 4, 5) is not None         # B→A
    assert mm.find_door(out, 4, 5, 5, 5) is None


def test_player_view_hides_doors_in_unexplored_cells():
    m = mm.default_map(20, 20)
    m["explored"][0] = 1                                     # only the top-left corner explored
    m["doors"] = [{"id": "near", "x": 0, "y": 0, "dir": "v", "closed": True},
                  {"id": "far", "x": 15, "y": 15, "dir": "v", "closed": True}]
    out = mm.visible_map(m, user_id=7, is_dm=False, visible_cells=())
    assert [d["id"] for d in out["doors"]] == ["near"]


def test_sanitize_and_visible_map_filter_pins():
    out = mm.sanitize(mk(pins=[{"id": "p1", "x": 1, "y": 1, "title": "Safe",
                                "visibility": "players", "color": "#123456"},
                               {"id": "p2", "x": 2, "y": 1, "title": "Hidden",
                                "visibility": "dm"},
                               {"id": "p3", "x": 3, "y": 1, "title": "Later",
                                "visibility": "bogus"}]))
    assert [p["id"] for p in out["pins"]] == ["p1", "p2", "p3"]
    assert out["pins"][2]["visibility"] == "dm"

    player = mm.visible_map(out, user_id=7, is_dm=False,
                            visible_cells={(0, 0), (1, 1), (2, 1), (3, 1)})
    assert [p["id"] for p in player["pins"]] == ["p1"]
    dm = mm.visible_map(out, user_id=7, is_dm=True, visible_cells=())
    assert {p["id"] for p in dm["pins"]} == {"p1", "p2", "p3"}


def test_revealed_pin_requires_seen_cell():
    out = mm.sanitize(mk(pins=[{"id": "r", "x": 4, "y": 4, "visibility": "revealed"}]))
    assert mm.visible_map(out, 7, False, [])["pins"] == []
    m2 = mk(explored=[0] * 80, pins=[{"id": "r", "x": 4, "y": 4, "visibility": "revealed"}])
    m2["explored"][4 * m2["w"] + 4] = 1
    assert [p["id"] for p in mm.visible_map(m2, 7, False, [])["pins"]] == ["r"]
