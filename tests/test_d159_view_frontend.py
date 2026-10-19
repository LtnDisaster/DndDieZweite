"""D159 — the floor DISPLAY filter and signed labels, proven on the REAL client
code (10_core + 50_canvas) in a Node vm (the established harness pattern of
test_browser_flow / test_view_mode — no browser runtime on this host).

It checks the three things that must be true of a DISPLAY-only filter:
  * the plane the viewer stands on (viewerPlane) never changes because of it;
  * toggling "all floors" <-> "this floor only" only flips which DELIVERED rows
    the canvas is allowed to draw (onPlane), and never sends a wire message;
  * a cross-plane token carries an absolute floor tag with the delta to the
    viewed plane, while a same-plane token carries none.
"""
import json
import shutil

import pytest

from tests.test_browser_flow import NODE, _vm

pytestmark = pytest.mark.skipif(NODE is None, reason="node not available")

_INIT = """
Object.assign(state, {
  me: { id: 1 },
  room: { role: 'dm', members: [] },
  floors: ['Tomb', '', 'Attic'],
  floor_levels: { 'Tomb': -1, '': 0, 'Attic': 1 },
  viewFloor: '',
  preview: null, sel: null,
  tokens: [ { id: 1, floor: '',    label: 'Ground' },
            { id: 2, floor: 'Attic', label: 'Up' },
            { id: 3, floor: 'Tomb',  label: 'Down' } ],
});
state.viewFilter = 'all';
"""

_PROBE = """
const T = { primary: state.tokens[0], up: state.tokens[1], down: state.tokens[2] };
const R = {
  badge: [floorBadge(''), floorBadge('Attic'), floorBadge('Tomb')],
  level: [floorLevelOf(''), floorLevelOf('Attic'), floorLevelOf('Tomb')],
  // all-floors mode: every delivered plane is drawable
  all: [onPlane(T.primary), onPlane(T.up), onPlane(T.down)],
  // labels: cross-plane tagged with an absolute floor tag + delta, same-plane none
  labelUp: tokenPlaneLabel(T.up),
  labelPrimary: tokenPlaneLabel(T.primary),
  vpAll: viewerPlane(),
  sentAll: rec.sent.length,
};
state.viewFilter = 'current';
R.mode = viewFilterMode();
R.current = [onPlane(T.primary), onPlane(T.up), onPlane(T.down)];
R.vpCurrent = viewerPlane();
R.sentCurrent = rec.sent.length;
console.log(JSON.stringify(R));
"""


def test_floor_filter_and_labels_are_display_only():
    r = _vm(_INIT, _PROBE)
    MINUS = "\u2212"
    # signed floor tags: E0 / E+1 / E-1 (a true minus sign, not a hyphen)
    assert r["badge"] == ["E0", "E+1", "E" + MINUS + "1"], r["badge"]
    assert r["level"] == [0, 1, -1], r["level"]
    # ALL floors -> the DM browsing E0 can see/draw every plane the server sent
    assert r["all"] == [True, True, True], r["all"]
    # THIS floor only -> only the plane in view is drawable; the others are not
    assert r["mode"] == "current"
    assert r["current"] == [True, False, False], r["current"]
    # the viewed plane is identical in both modes — the filter never moves you
    assert r["vpAll"] == r["vpCurrent"] == "", (r["vpAll"], r["vpCurrent"])
    # a cross-plane token is badged with its floor + delta; same-plane is plain
    assert r["labelUp"] == "E+1 \u25B2+1", r["labelUp"]
    assert r["labelPrimary"] is None, r["labelPrimary"]
    # DISPLAY-ONLY: neither toggling nor badging ever put anything on the wire
    assert r["sentAll"] == 0 and r["sentCurrent"] == 0, r
