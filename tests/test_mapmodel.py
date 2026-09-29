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
         "explored": [0] * (W * H), "traps": [], "loot": []}
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
def test_reveal_marks_area_and_reports_only_new_cells():
    m = mm.default_map(20, 20)
    first = mm.reveal(m, 10, 10, r=1)
    assert len(first) > 0 and all(m["explored"][i] == 1 for i in first)
    assert mm.reveal(m, 10, 10, r=1) == []  # nothing new the second time


# ---- per-role visibility filtering ----
def test_player_view_nulls_unexplored_and_hides_undiscovered_secrets():
    m = mm.default_map(20, 20)
    m["traps"] = [{"id": "t1", "x": 19, "y": 19, "dc": 12, "dmg": "1d4", "discovered": False},
                  {"id": "t2", "x": 0, "y": 0, "dc": 12, "dmg": "1d4", "discovered": True}]
    m["loot"] = [{"id": "l1", "x": 1, "y": 1, "label": "mine", "taken_by": 7},
                 {"id": "l2", "x": 1, "y": 1, "label": "theirs", "taken_by": 99}]
    out = mm.visible_map(m, user_id=7, is_dm=False, owned_cells=[(0, 0)])
    assert out["cells"][0] is not None      # near vision is revealed
    assert out["cells"][-1] is None          # far corner stays fogged (null)
    assert [t["id"] for t in out["traps"]] == ["t2"]   # undiscovered trap withheld
    assert [l["id"] for l in out["loot"]] == ["l1"]     # only this user's loot


def test_dm_view_is_unfiltered_truth():
    m = mk(traps=[{"id": "t1", "x": 9, "y": 7, "dc": 12, "dmg": "1d4", "discovered": False}])
    assert mm.visible_map(m, user_id=1, is_dm=True, owned_cells=[]) is m
