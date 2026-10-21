"""D158 — vertical sight for a stacked building (ground / upper / roof).

The occlusion authority is `vertical3d` (column_open / cross_plane_sight /
observable_cells) — the SINGLE server decision point the snapshot and the live
stream both consume. This adds the explicit ground-floor / upper / roof scenario
the manual abnahme asked for, WITHOUT touching the frozen diorama:

  * a solid ceiling (no `openv`) keeps every plane independent — a roof token is
    as "elsewhere" to the ground as it was before vertical geometry existed;
  * opening the WHOLE column (every intermediate plane at that cell) lets sight
    pass straight up/down it — symmetrically (the roof can look down too);
  * the canvas plane filter (`onPlane`) mirrors that: a DM standing on the roof
    neither sees nor paints the ground floor; a player renders exactly the rows
    the server already occlusion-filtered;
  * the DM changing the EDIT plane never moves the player's own perspective.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from app import db
from app.main import app
from app.room import net, vertical3d
from tests.test_movement_fog import base_room, state_of, H

NODE = shutil.which("node")
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def client():
    return TestClient(app)


def rid(code):
    return db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]


def add_floor(client, dm, code, name, ground=True):
    r = client.post(f"/api/rooms/{code}/floors", json={"name": name}, headers=H(dm))
    assert r.status_code == 200, r.text
    # D159: a named plane is open AIR by default; the solid-ceiling/open-shaft
    # occlusion this test verifies needs a real slab, so the DM lays a floor.
    if ground:
        r_ = rid(code)
        mp = net.get_map(r_, name)
        mp["cells"] = [0] * (mp["w"] * mp["h"])
        net.set_map(r_, mp, name)
    return r.json()


def openv(client_cell_open, room_id, floor, cell):
    """Open a vertical opening in the ceiling above `cell` on plane `floor`."""
    x, y = cell
    mp = net.get_map(room_id, floor)
    mp["openv"][y * mp["w"] + x] = 1
    net.set_map(room_id, mp, floor)


def test_stack_solid_ceilings_occlude_open_shaft_lets_sight_through(client):
    dm, player, code, ch = base_room(client)
    add_floor(client, dm, code, "Upper")          # level 1 (Erdgeschoss is primary, level 0)
    add_floor(client, dm, code, "Roof")           # level 2
    r = rid(code)

    maps = vertical3d.maps_for(r)
    lm = vertical3d.level_map(r)
    assert set(maps) == {"", "Upper", "Roof"}
    assert (lm[""], lm["Upper"], lm["Roof"]) == (0, 1, 2)   # real level numbers from the model

    # (a) FAIL-CLOSED: solid ceilings — no two planes see each other, either way.
    for a, b in [("", "Upper"), ("", "Roof"), ("Upper", "Roof"),
                 ("Upper", ""), ("Roof", ""), ("Roof", "Upper")]:
        assert vertical3d.cross_plane_sight(maps, lm, a, b, (5, 5)) is False, (a, b)
    assert vertical3d.column_open(maps, lm, "", "Roof", (5, 5)) is False

    # (b) open only the GROUND ceiling → the roof (two levels up) is still hidden:
    #     a partial column is not an opening all the way up.
    openv(client, r, "", (5, 5))
    maps = vertical3d.maps_for(r)
    assert vertical3d.column_open(maps, lm, "", "Roof", (5, 5)) is False
    assert vertical3d.cross_plane_sight(maps, lm, "", "Upper", (5, 5)) is True   # adjacent now open
    assert vertical3d.cross_plane_sight(maps, lm, "", "Roof", (5, 5)) is False

    # (c) open the Upper ceiling too → the FULL shaft joins ground and roof,
    #     symmetrically (the roof can look straight down onto the ground).
    openv(client, r, "Upper", (5, 5))
    maps = vertical3d.maps_for(r)
    assert vertical3d.column_open(maps, lm, "", "Roof", (5, 5)) is True
    assert vertical3d.cross_plane_sight(maps, lm, "", "Roof", (5, 5)) is True
    assert vertical3d.cross_plane_sight(maps, lm, "Roof", "", (5, 5)) is True
    # a neighbouring cell is still a solid ceiling — the hole is exactly one tile
    assert vertical3d.cross_plane_sight(maps, lm, "", "Roof", (6, 6)) is False


def test_dm_edit_plane_never_moves_the_player_perspective(client):
    dm, player, code, ch = base_room(client)
    add_floor(client, dm, code, "Roof")
    p_before = state_of(client, player, code)
    assert p_before["view_floor"] == ""           # the player stands on their home plane

    # the DM browses/edits the roof — that is the DM's view, nothing more.
    dm_roof = client.get(f"/api/rooms/{code}/state?floor=Roof", headers=H(dm))
    assert dm_roof.status_code == 200 and dm_roof.json()["view_floor"] == "Roof"

    p_after = state_of(client, player, code)
    assert [t["id"] for t in p_before["tokens"]] == [t["id"] for t in p_after["tokens"]]
    assert p_after["view_floor"] == "" and p_after["grid"] == p_before["grid"]

    # a player asking for a plane they are not standing on is silently kept on
    # their own — browsing the roof must never hand a player an x-ray.
    peek = client.get(f"/api/rooms/{code}/state?floor=Roof", headers=H(player)).json()
    assert peek["view_floor"] == ""
    assert peek["grid"] == p_after["grid"]


# --------------------------------------------------------------------------- #
# canvas representation — the real 50_canvas.js plane filter in a Node vm
# --------------------------------------------------------------------------- #
_CANVAS_DOM = r"""
{
  window: { addEventListener: () => {}, devicePixelRatio: 1 },
  location: { search: '' },
  requestAnimationFrame: () => 0,
  setTimeout: () => 0, clearTimeout: () => 0,
  localStorage: { getItem: () => null, setItem: () => {} },
  document: (() => {
    const fakeCtx = new Proxy({}, { get: () => (() => {}) });
    const cache = {};
    const mk = (id) => (cache[id] = cache[id] || {
      id, getContext: () => fakeCtx, addEventListener: () => {},
      getBoundingClientRect: () => ({ left: 0, top: 0, width: 800, height: 600 }),
      parentElement: { getBoundingClientRect: () => ({ width: 800, height: 600 }) },
      classList: { toggle(){}, add(){}, remove(){} }, style: {}, dataset: {},
      value: '', checked: false, textContent: '', innerHTML: '', querySelectorAll: () => [],
    });
    return { getElementById: mk, querySelectorAll: () => [], createElement: () => mk('__tmp' + Math.random()) };
  })()
}
"""


def _run_node(script):
    r = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, f"node failed: {r.stderr[-4000:]}"
    return r.stdout.strip()


@pytest.mark.skipif(NODE is None, reason="node not available")
def test_canvas_plane_filter_hides_other_floors_for_the_editor():
    js = ROOT / "app/static/js"
    files = [str(js / "10_core.js"), str(js / "50_canvas.js")]
    probe = ("Object.assign(state, {preview:null, editing:false, room:{role:'dm'}, viewFloor:'Roof'});"
             "console.log(JSON.stringify({"
             " roof: onPlane({id:'r', floor:'Roof'}),"
             " ground: onPlane({id:'g', floor:''}),"
             " upper: onPlane({id:'u', floor:'Upper'})}));")
    script = (
        "const vm=require('vm'),fs=require('fs');"
        f"const files={[str(f) for f in files]};"
        f"const sb=Object.assign({{console}}, {_CANVAS_DOM});"
        "vm.createContext(sb);"
        "for(const f of files) vm.runInContext(fs.readFileSync(f,'utf8'),sb,{filename:f});"
        f"vm.runInContext({json.dumps('wsSend=()=>{};toast=()=>{};refreshRoom=()=>{};draw=()=>{};')},sb);"
        f"vm.runInContext({json.dumps(probe)},sb);"
    )
    out = json.loads(_run_node(script))
    # a DM browsing the roof renders only roof tokens — the ground/upper floors
    # are neither drawn nor clickable, so no accidental paint lands on them.
    assert out["roof"] is True and out["ground"] is False and out["upper"] is False
