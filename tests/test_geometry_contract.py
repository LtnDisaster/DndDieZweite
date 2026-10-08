"""Sprint 18 (D84): THE pointer-to-grid coordinate contract.

The clicked/aimed cell on the wire names where the player wants the token
CENTER; the server converts it ONCE (footprint.center_to_anchor) to the
canonical integer footprint anchor. Pins:

* the pure conversion incl. the documented even-parity tie-break (shared with
  anchor_for_center) and the 1x1 / 2x2 / 3x7 / 7x3 / rotated cases;
* preview + executed move land the box so its centre sits on the aimed cell,
  and invalid finishes STILL fail — the fix is conversion, not weakened gates;
* the rotation-aware conversion (a 3x7 turned 90 converts as 7x3);
* controller-delivered tokens carry geometry (the companion 3x7-as-1x1 bug);
* a Node-vm harness runs the REAL client pointer code (evtPos -> toCell ->
  planMove/requestPathPreview) over a real snapshot and asserts the wire
  carries the CENTER cell — never a client-side pre-conversion;
* static pins on the selection overlay: outline, not translucent block;
  gated by selected/map-edit/?debug only.
"""
import json
import pathlib
import shutil
import subprocess

import pytest
from starlette.testclient import TestClient

from app import db, footprint, main
from tests.test_movement_fog import (base_room, recv_until, set_grid, state_of,
                                     ws_connect)

ROOT = pathlib.Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


@pytest.fixture()
def client():
    return TestClient(main.app)


def center_cell(anchor, w=1, h=1):
    """Mirror of the wire contract: the CENTER cell a client sends to land a
    w x h box with its anchor at ``anchor``."""
    return (anchor[0] + (w - 1) // 2, anchor[1] + (h - 1) // 2)


def px_cell(px, cell=50):
    return int(px // cell)


def tok_row(token_id):
    return db.q1("SELECT * FROM tokens WHERE id=?", (token_id,))


def npc_token(ws, label, cx, cy, width=None, height=None, rot=None):
    cell = 50
    msg = {"type": "add_token", "label": label, "x": (cx + .5) * cell, "y": (cy + .5) * cell}
    if width is not None:
        msg["width"] = width
    if height is not None:
        msg["height"] = height
    ws.send_json(msg)
    tid = recv_until(ws, "token_add")["payload"]["id"]
    if rot:
        ws.send_json({"type": "token_rotate", "token_id": tid, "degrees": rot})
        recv_until(ws, "token_rot")
    return tid


def reveal_all(client, dm, code):
    g = state_of(client, dm, code)["grid"]
    cells = [{"x": x, "y": y, "explored": 1}
             for y in range(g["h"]) for x in range(g["w"])]
    with ws_connect(client, dm, code) as ws:
        for i in range(0, len(cells), 512):
            ws.send_json({"type": "fog_edit", "cells": cells[i:i + 512]})
        for _ in range((len(cells) + 511) // 512):
            recv_until(ws, "fog_changed")


# ---------- the conversion itself (pure) ----------

def test_center_to_anchor_exact_for_odd_spans():
    for span in [(1, 1), (3, 7), (7, 3), (5, 9)]:
        a = footprint.center_to_anchor((20, 9), span)
        # projected box centre hits the clicked cell centre exactly ...
        assert a[0] + span[0] / 2 == 20.5 and a[1] + span[1] / 2 == 9.5, span
        # ... and the 1x1 at the box's centre cell (anchor_for_center) lands
        # on exactly the aimed cell — the two rules are ONE convention.
        assert footprint.anchor_for_center(a, span, (1, 1)) == (20, 9)


def test_center_to_anchor_even_parity_uses_the_documented_tiebreak():
    # even extents: centre lands on the lower-right corner of the clicked cell
    assert footprint.center_to_anchor((20, 9), (2, 2)) == (20, 9)
    assert footprint.center_to_anchor((20, 9), (4, 6)) == (19, 7)
    # the bias is the SAME rule as anchor_for_center placing a 1x1 in an even
    # outer box: inner anchor = outer anchor + (even-1)//2 (floor, down-right)
    assert footprint.anchor_for_center((19, 7), (4, 6), (1, 1)) == (20, 9)
    assert footprint.center_to_anchor((20, 9), (4, 6)) == (19, 7)


def test_center_to_anchor_inverse_of_occupied_projection():
    mp = {"w": 30, "h": 30, "cell": 50, "origin": [0, 0]}
    tok = {"id": 1, "x": 100.0, "y": 100.0, "size": "Medium", "fw": 3, "fh": 7}
    _, span = footprint.occupied_origin(mp, tok)
    for aim in [(10, 8), (15, 20), (2, 20), (24, 1)]:
        anchor = footprint.center_to_anchor(aim, span)
        # projecting the box back, the integer cell containing its centre is
        # the aimed cell for odd spans, and the aim's lower-right neighbour
        # for even ones (the documented half-cell bias):
        ccx, ccy = anchor[0] + span[0] / 2, anchor[1] + span[1] / 2
        assert int(ccx) == aim[0] + (0 if span[0] % 2 else 1)
        assert int(ccy) == aim[1] + (0 if span[1] % 2 else 1)


# ---------- the contract over the wire (real WS, real maps) ----------

def _open_room_with_west_gate(client):
    """Column x=19 walls everything except rows 8..14 (a 7-row gate)."""
    dm, player, code, ch = base_room(client)

    def mutate(g):
        for y in range(g["h"]):
            if y not in set(range(8, 15)):
                g["cells"][y * g["w"] + 19] = 1
    set_grid(client, dm, code, mutate)
    return dm, player, code, ch


def test_3x7_preview_and_move_land_centered_on_the_aimed_cell(client):
    dm, player, code, _ = _open_room_with_west_gate(client)
    with ws_connect(client, dm, code) as ws:
        big = npc_token(ws, "Serpent", 10, 8, width=3, height=7)
        aim_anchor = (24, 8)
        cx, cy = center_cell(aim_anchor, 3, 7)
        ws.send_json({"type": "path_preview", "token_id": big, "tx": cx, "ty": cy})
        pv = recv_until(ws, "path_preview")["payload"]
        assert pv["goal"] == {"cx": cx, "cy": cy}          # echoes the aimed centre
        assert pv["anchor"] == {"cx": 24, "cy": 8}         # the landing box
        ws.send_json({"type": "move", "token_id": big, "tx": cx, "ty": cy,
                      "path": pv["path"], "teleport": False})
        for _ in range(60):
            e = ws.receive_json()
            if e.get("kind") == "step" and (e["payload"].get("cx"),
                                            e["payload"].get("cy")) == (24, 8):
                break
        else:
            pytest.fail("3x7 never landed its anchor on the conversion of the aim")
    row = tok_row(big)
    assert (px_cell(row["x"]), px_cell(row["y"])) == (24, 8)
    # the stored pixel centre of the ORIENTED box equals the aimed cell centre
    # (row x/y is the ANCHOR CELL CENTRE px; box centre = anchor px - c/2 + span*c/2)
    centre_px = (row["x"] - 25 + 3 * 50 / 2, row["y"] - 25 + 7 * 50 / 2)
    assert abs(centre_px[0] - (cx + .5) * 50) < 1e-9
    assert abs(centre_px[1] - (cy + .5) * 50) < 1e-9


def test_2x2_and_1x1_roundtrip(client):
    dm, player, code, _ = _open_room_with_west_gate(client)
    with ws_connect(client, dm, code) as ws:
        huge = npc_token(ws, "Ogre", 10, 9, width=2, height=2)
        cx, cy = center_cell((22, 10), 2, 2)               # even span -> +0/+0 anchor
        ws.send_json({"type": "path_preview", "token_id": huge, "tx": cx, "ty": cy})
        pv = recv_until(ws, "path_preview")["payload"]
        assert pv["anchor"] == {"cx": 22, "cy": 10}
        imp = npc_token(ws, "Imp", 10, 12)
        ws.send_json({"type": "path_preview", "token_id": imp, "tx": 22, "ty": 12})
        pv = recv_until(ws, "path_preview")["payload"]
        assert pv["anchor"] == pv["goal"] == {"cx": 22, "cy": 12}   # 1x1 unchanged


def test_rotated_3x7_converts_as_the_oriented_7x3(client):
    dm, player, code, _ = _open_room_with_west_gate(client)
    with ws_connect(client, dm, code) as ws:
        big = npc_token(ws, "Serpent", 6, 9, width=3, height=7, rot=90)
        row = tok_row(big)
        mp = state_of(client, dm, code)["grid"]
        anchor, span = footprint.occupied_origin(mp, {**row, "rot": 90})
        assert span == (7, 3)                              # D83 orientation
        aim_anchor = (anchor[0] + 6, anchor[1])            # slide east inside the gate
        cx, cy = center_cell(aim_anchor, 7, 3)
        ws.send_json({"type": "path_preview", "token_id": big, "tx": cx, "ty": cy})
        pv = recv_until(ws, "path_preview")["payload"]
        assert pv["w"] == 7 and pv["h"] == 3
        assert pv["anchor"] == {"cx": aim_anchor[0], "cy": aim_anchor[1]}


def test_invalid_centre_still_fails_box_not_point_is_checked(client):
    """Clicking an open floor cell whose CENTRE conversion drives the 3x7 box
    INTO the wall must still be refused — the conversion was fixed, the
    collision gates were not weakened."""
    dm, player, code, _ = _open_room_with_west_gate(client)   # x=19 walled except rows 8..14
    with ws_connect(client, dm, code) as ws:
        big = npc_token(ws, "Serpent", 10, 8, width=3, height=7)
        # clicked cell (20,18) is open floor; its anchor (19,15) spans x19..21
        # y15..21 whose x=19 column is all wall -> the BOX is illegal:
        cx, cy = 20, 18
        assert footprint.center_to_anchor((cx, cy), (3, 7)) == (19, 15)
        ws.send_json({"type": "path_preview", "token_id": big, "tx": cx, "ty": cy})
        err = recv_until(ws, "error", fail_on_error=False)
        assert err["payload"]["msg"] == "No path there"
        # and the same goal refuses on execute — no drift between the two
        ws.send_json({"type": "move", "token_id": big, "tx": cx, "ty": cy, "teleport": False})
        err = recv_until(ws, "error", fail_on_error=False)
        low = err["payload"]["msg"].lower()
        assert "path" in low or "footprint" in low
        assert tok_row(big) is not None


def test_dm_drag_teleport_lands_where_the_token_was_dropped(client):
    dm, player, code, _ = _open_room_with_west_gate(client)
    with ws_connect(client, dm, code) as ws:
        big = npc_token(ws, "Serpent", 10, 8, width=3, height=7)
        # client computes the drop from the token's OWN centre cell:
        row = tok_row(big)
        ax, ay = px_cell(row["x"]), px_cell(row["y"])
        cx, cy = center_cell((ax, ay), 3, 7)
        ws.send_json({"type": "move", "token_id": big, "tx": cx, "ty": cy, "teleport": True})
        # dropping on its own centre is a no-op — row must be untouched.
        import time
        time.sleep(0.25)                                   # let any write land
        row2 = tok_row(big)
        assert (row2["x"], row2["y"]) == (row["x"], row["y"])
        # an off-centre drop lands the box, not the pointer:
        ws.send_json({"type": "move", "token_id": big, "tx": 15, "ty": 11, "teleport": True})
        for _ in range(30):
            e = ws.receive_json()
            if e.get("kind") == "step":
                break
        row3 = tok_row(big)
        assert (px_cell(row3["x"]), px_cell(row3["y"])) == footprint.center_to_anchor(
            (15, 11), (3, 7))


# ---------- controller geometry delivery (companion 3x7-as-1x1 bug) ----------

def test_snapshot_carries_geometry_for_the_controller_too():
    from app.room.visibility import _snapshot
    row = {"id": 5, "label": "Wolf", "color": "#fff", "x": 100.0, "y": 150.0,
           "owner_user_id": None, "character_id": None, "controller_user_id": 7,
           "mount_token_id": None, "size": "Medium", "fw": 3, "fh": 7,
           "vw": None, "vh": None, "rot": 90, "conds": "[]", "death": None}
    for snap_uid, has_geo in [(7, True), (8, False), (None, False)]:
        snap = _snapshot(row, snap_uid)
        if has_geo:
            assert (snap["fw"], snap["fh"], snap["rot"], snap["size"]) == (3, 7, 90, "Medium")
            assert snap["vw"] is None and snap["vh"] is None
        else:
            assert "fw" not in snap and "rot" not in snap and "size" not in snap


def test_controller_player_previews_the_companion_with_real_geometry(client):
    """End-to-end: player controls a 3x7 companion -> BOTH delivery channels
    carry the shape and the preview converts with the REAL oriented span
    (never the 1x1 fallback the delivery bug produced)."""
    dm, player, code, _ = base_room(client)
    reveal_all(client, dm, code)
    with ws_connect(client, dm, code) as ws:
        wolf = npc_token(ws, "Wolf", 25, 13, width=3, height=7)
        pid = [m["user_id"] for m in state_of(client, dm, code)["members"] if m["char"]][0]
        ws.send_json({"type": "token_controller", "token_id": wolf, "user_id": pid})
        recv_until(ws, "token_controller")
        # nudge it: the step channel must DELIVER the token to the controller
        # (first_time -> token_add) — with geometry.
        ws.send_json({"type": "move", "token_id": wolf, "tx": 26, "ty": 13, "teleport": True})
        recv_until(ws, "step")
    st = state_of(client, player, code)
    wt = next(t for t in st["tokens"] if t["id"] == wolf)
    assert (wt.get("fw"), wt.get("fh")) == (3, 7)          # /state keeps it for the controller
    with ws_connect(client, player, code) as ws:
        cx, cy = center_cell((30, 13), 3, 7)
        ws.send_json({"type": "path_preview", "token_id": wolf, "tx": cx, "ty": cy,
                      "request_id": 1})
        pv = recv_until(ws, "path_preview")["payload"]
        assert pv["anchor"] == {"cx": 30, "cy": 13}        # converted with the REAL span
        assert pv["w"] == 3 and pv["h"] == 7


# ---------- static pins on the overlay/deselect behaviour ----------

JS_CANVAS = (ROOT / "app/static/js/50_canvas.js").read_text()


def test_footprint_overlay_is_an_outline_not_a_block():
    start = JS_CANVAS.index("if ((tw > 1 || th > 1) && (t.id === state.sel")
    end = JS_CANVAS.index("ctx.restore(); }", start) + 15
    block = JS_CANVAS[start:end]
    assert "strokeRect" in block, "overlay must be an outline"
    assert "fillRect" not in block, "the old translucent block must not return"
    assert "state.editing || DEBUG" in block                # still gated


def test_escape_deselects():
    esc = JS_CANVAS[JS_CANVAS.index('e.key === "Escape"'):]
    esc = esc[:esc.index("state.keys.add")]
    assert "state.sel = null" in esc and "renderSheet(null)" in esc


# ---------- the REAL client pointer path (Node vm) ----------

_DIO_DOM = """
{
  window: { addEventListener: () => {}, devicePixelRatio: 1 },
  location: { search: '' },
  requestAnimationFrame: () => 0,
  setTimeout: () => 0, clearTimeout: () => 0,
  document: (() => {
    const cache = {};
    const fakeCtx = new Proxy({}, { get: () => () => {} });
    const mk = (id) => (cache[id] = cache[id] || {
      getContext: () => fakeCtx,
      addEventListener: () => {},
      getBoundingClientRect: () => ({ left: 0, top: 0, width: 800, height: 600 }),
      parentElement: { getBoundingClientRect: () => ({ width: 800, height: 600 }) },
      classList: { toggle(){}, add(){}, remove(){} },
      style: {}, value: '', checked: false, textContent: '' });
    return { getElementById: mk, querySelectorAll: () => [] };
  })()
}
"""


def _run_node(script):
    r = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, f"node failed: {r.stderr}"
    return r.stdout.strip()


def _node_vm(paths, extra, sandbox_js="{}"):
    script = (
        "const vm=require('vm'),fs=require('fs');"
        f"const files={json.dumps(paths)};"
        f"const sb=Object.assign({{console}}, {sandbox_js});"
        "vm.createContext(sb);"
        "for(const f of files) vm.runInContext(fs.readFileSync(f,'utf8'),sb,{filename:f});"
        f"vm.runInContext({json.dumps(extra)},sb);"
    )
    return _run_node(script)


@pytest.mark.skipif(NODE is None, reason="node not available")
def test_pointer_to_grid_conversion_sends_the_centre_cell():
    """Load 10_core + the REAL 50_canvas and click the visual centre of a
    rotated 3x7 (oriented 7x3) token: evtPos/toCell/planMove must put the
    CENTRE cell on the wire — the server owns the anchor conversion."""
    js = ROOT / "app/static/js"
    out = _node_vm([str(js / "10_core.js"), str(js / "50_canvas.js")], """
      var rec = { sent: [] };
      wsSend = (m) => rec.sent.push(m);
      toast = (m) => rec.toast = m;
      renderSheet = (t) => rec.sheet = (t && t.id) || null;
      wsSend = (m) => rec.sent.push(m);
      Object.assign(state, {
        me: { id: 1 },
        room: { role: 'player', members: [{ user_id: 1, char: { name: 'A', hp: 10, max_hp: 10 } }] },
        grid: { w: 40, h: 26, cell: 50, origin: [0, 0], cells: [0], explored: [0],
                doors: [], traps: [], loot: [], pins: [], objects: [] },
        cam: { ox: 0, oy: 0 }, plan: null, planRequest: null, sel: null,
        moving: new Set(), ghosts: [], pings: [], init: null, keys: new Set(),
        tokens: [ { id: 7, label: 'Serpent', color: '#3cf', owner_user_id: 1,
                    x: (10 + .5) * 50, y: (8 + .5) * 50,
                    size: 'Medium', fw: 3, fh: 7, rot: 90 } ]
      });
      const t = state.tokens[0];
      const span = tokenSpan(t);                     // oriented box
      const c = cellSize();
      // the token's VISUAL/mechanical centre in world px == screen px (cam 0):
      const cx_px = t.x + (span[0] - 1) * c / 2, cy_px = t.y + (span[1] - 1) * c / 2;
      const p = evtPos({ clientX: cx_px, clientY: cy_px });
      const aim = toCell(p.x, p.y);
      const hit = tokenAt(cx_px, cy_px);
      const hitFar = tokenAt(2500, 2500);
      const centre = tokenCenterCell(t);
      requestPathPreview(aim.cx, aim.cy, true);
      const wire = rec.sent[0];
      console.log(JSON.stringify({ span, aim, wire, hit: hit && hit.id,
                                   hitFar: !!hitFar, centre }));
    """, _DIO_DOM)
    got = json.loads(out)
    t = 7
    assert got["span"] == [7, 3]
    # visual centre of the oriented box at anchor (10,8) is 10+3=13, 8+1=9:
    assert got["aim"] == {"cx": 13, "cy": 9}
    assert got["centre"] == {"cx": 13, "cy": 9}
    assert got["wire"]["type"] == "path_preview"
    assert (got["wire"]["tx"], got["wire"]["ty"]) == (13, 9)   # the CENTRE, un-converted
    assert got["hit"] == t and got["hitFar"] is False
