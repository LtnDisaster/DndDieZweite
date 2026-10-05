"""Sprint 8 (P1): confirmed routes equal the previewed route, and the
diorama projection resolves clicks independent of the camera.

Server tests lock the invariant: a confirmed preview path is executed EXACTLY
(cell for cell), and a route invalidated by a world change is REJECTED — the
server never silently walks a different route. The Node-vm tests pin the
isometric click→cell math (dioProj/dioUnproj single camera space) which used
to double-subtract the camera and made diorama confirmations diverge from the
previewed cell.
"""
import json
import re
import shutil
import subprocess
import uuid

import pytest
from starlette.testclient import TestClient

from app import db
from app.main import app

from test_movement_fog import (H, base_room, recv_until, set_grid, state_of,
                               wall_column, ws_connect)

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
JS = ROOT / "app" / "static" / "js"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node not available")


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def room_id_of(code):
    return db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]


def player_token_row(code, ch):
    return db.q1("SELECT * FROM tokens WHERE room_id=? AND character_id=?",
                 (room_id_of(code), ch["id"]))


def cell_of(tok):
    return int(tok["x"] // 50), int(tok["y"] // 50)


def await_walk_end(ws, token_id, tries=80):
    """Drain until move_state(moving=False) for token; return (reason, step_cells)."""
    steps = []
    for _ in range(tries):
        ev = ws.receive_json()
        k = ev.get("kind")
        p = ev.get("payload") or {}
        if k == "step" and p.get("token_id") == token_id:
            steps.append((p.get("cx"), p.get("cy")))
        if k == "move_state" and p.get("token_id") == token_id and p.get("moving") is False:
            return p.get("reason"), steps
    raise AssertionError("walk never ended")


# ---------- preview ≡ executed (server authority) ----------

def test_medium_preview_route_is_executed_exactly(client):
    dm, player, code, ch = base_room(client)
    tok = player_token_row(code, ch)
    px, py = cell_of(tok)
    # wall column two cells right of the token, gap at row py+1 → forces a turn
    def mutate(g):
        for y in range(0, py + 1):
            g["cells"][y * g["w"] + (px + 2)] = 1
    set_grid(client, dm, code, mutate)
    goal = (px + 4, py)

    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "path_preview", "token_id": tok["id"],
                      "tx": goal[0], "ty": goal[1], "request_id": 1})
        prev = recv_until(ws, "path_preview")["payload"]
    route = [(p["x"], p["y"]) for p in prev["path"]]
    assert (px + 2, py + 1) in route, "route must turn through the gap"
    assert route[-1] == goal and len(route) > 3

    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "move", "token_id": tok["id"], "tx": goal[0], "ty": goal[1],
                      "teleport": False, "path": prev["path"]})
        reason, steps = await_walk_end(ws, tok["id"])
    assert reason is None
    assert steps == route                      # executed EXACTLY the preview
    assert cell_of(player_token_row(code, ch)) == goal


def test_large_token_preview_route_is_executed_exactly(client):
    dm, player, code, ch = base_room(client)
    tok = player_token_row(code, ch)
    db.x("UPDATE tokens SET size='Large' WHERE id=?", (tok["id"],))
    px, py = cell_of(tok)                       # occupies (px,py)+(px+1,py)+row+1
    goal = (px + 5, py)

    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "path_preview", "token_id": tok["id"],
                      "tx": goal[0], "ty": goal[1], "request_id": 2})
        prev = recv_until(ws, "path_preview")["payload"]
    route = [(p["x"], p["y"]) for p in prev["path"]]

    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "move", "token_id": tok["id"], "tx": goal[0], "ty": goal[1],
                      "teleport": False, "path": prev["path"]})
        reason, steps = await_walk_end(ws, tok["id"])
    assert reason is None
    assert steps == route


def test_closed_door_after_preview_is_rejected_not_rerouted(client):
    dm, player, code, ch = base_room(client)
    tok = player_token_row(code, ch)
    px, py = cell_of(tok)
    gap = px + 2

    def mutate(g):                                   # wall with a door in the gap row
        for y in range(0, py + 1):
            if y != py:
                g["cells"][y * g["w"] + gap] = 1
        g["doors"] = [{"id": "d8", "x": gap - 1, "y": py, "dir": "v",
                       "closed": False, "locked": False}]
    set_grid(client, dm, code, mutate)
    goal = (px + 4, py)

    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "path_preview", "token_id": tok["id"],
                      "tx": goal[0], "ty": goal[1], "request_id": 3})
        prev = recv_until(ws, "path_preview")["payload"]
        assert prev["path"][-1] == {"x": goal[0], "y": goal[1]}

    gm = state_of(client, dm, code)["grid"]          # world change: door swings shut
    gm["doors"][0]["closed"] = True
    set_grid(client, dm, code, lambda g: g.update({"doors": gm["doors"]}))

    with ws_connect(client, player, code) as ws:     # confirm the stale route
        before = player_token_row(code, ch)
        ws.send_json({"type": "move", "token_id": tok["id"], "tx": goal[0], "ty": goal[1],
                      "teleport": False, "path": prev["path"]})
        # a rejected route answers with the error and nothing else; if a walk
        # had started, move_state(True) would arrive before/around the error.
        kinds, err = [], None
        for _ in range(15):
            ev = ws.receive_json()
            kinds.append(ev.get("kind"))
            if ev.get("kind") == "error":
                err = ev.get("payload")
                break
        assert err and err.get("code") == "route_invalid", f"saw {kinds}: {err}"
        assert "move_state" not in kinds, "rejected route must not start a walk"
        after = player_token_row(code, ch)
        assert (after["x"], after["y"]) == (before["x"], before["y"])


def test_nudged_token_invalidates_confirmed_route(client):
    dm, player, code, ch = base_room(client)
    tok = player_token_row(code, ch)
    px, py = cell_of(tok)
    goal = (px + 6, py)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "path_preview", "token_id": tok["id"],
                      "tx": goal[0], "ty": goal[1], "request_id": 4})
        prev = recv_until(ws, "path_preview")["payload"]
    db.x("UPDATE tokens SET x=?, y=? WHERE id=?", ((px + 1) * 50 + 25, py * 50 + 25, tok["id"]))
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "move", "token_id": tok["id"], "tx": goal[0], "ty": goal[1],
                      "teleport": False, "path": prev["path"]})
        err = recv_until(ws, "error")["payload"]
    assert err.get("code") == "route_invalid"
    tok2 = player_token_row(code, ch)
    assert (int(tok2["x"] // 50), int(tok2["y"] // 50)) == (px + 1, py)


# ---------- diorama projection (Node vm) ----------

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


@needs_node
def test_dio_unproj_is_exact_inverse_under_any_camera():
    out = _node_vm([str(JS / "55_diorama.js")],
                   """
                   var state = { cam: { ox: 0, oy: 0 } };
                   const bad = [];
                   for (const cam of [ [0,0], [137,-59], [-423, 78] ]){
                     state.cam.ox = cam[0]; state.cam.oy = cam[1];
                     for (const [lx, ly] of [[0,0],[3.7,8.2],[9.99,0.01],[5.5,5.5]]){
                       const [sx, sy] = dioProj(lx, ly, 50);
                       const { lx: rx, ly: ry } = dioUnproj(sx, sy, 50);
                       if (Math.abs(rx-lx) > 1e-9 || Math.abs(ry-ly) > 1e-9) bad.push([lx,ly,rx,ry]);
                     }
                   }
                   console.log(JSON.stringify(bad));
                   """)
    assert json.loads(out) == [], "dioUnproj must be the exact inverse of dioProj"


# Stubs MUST be defined inside the vm context: arrow functions written in the
# host script would close over the host scope, not the sandbox globals.
_DIO_STUBS = """
var rec = {};
var state = { cam: { ox: 137, oy: -59 },
              grid: { w: 10, h: 10, cells: [0], doors: [{ id: 'd', x: 5, y: 5, dir: 'v', closed: true }] },
              tokens: [{ id: 9, label: 'T', x: 125, y: 175, size: 'Medium', owner_user_id: 1 }],
              room: true, plan: null };
var cellSize = () => 50;
var SIZE_FOOTPRINT = { Medium: 1, Large: 2 };
var ownToken = () => state.tokens[0];
var planMove = (cx, cy) => { rec.moved = [cx, cy]; };
var confirmPlan = () => { rec.confirmed = (rec.confirmed || 0) + 1; };
var renderSheet = (t) => { rec.sheet = t ? t.id : null; };
var wsSend = (m) => { rec.sent = m; };
var visibleHere = () => true;
var segDist = (px, py, A, B) => {
  const [ax, ay] = A, [bx, by] = B;
  const dx = bx - ax, dy = by - ay;
  const t = Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy || 1)));
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
};
"""


@needs_node
def test_diorama_click_resolves_cell_independent_of_camera():
    """A click on the visual cell X must plan a move to X even while panned."""
    out = _node_vm([str(JS / "55_diorama.js")], _DIO_STUBS + """
                   // destination = visual centre of cell (4,6) with cam = (137,-59)
                   const [sx, sy] = dioProj(4.5, 6.5, 50);
                   dioramaDown({ x: sx, y: sy });
                   // a click at the token billboard must select it, not plan
                   const [tx, ty] = dioProj(2.5, 3.5, 50);
                   dioramaDown({ x: tx, y: ty });
                   // a click on the door segment must toggle the door
                   const A = dioProj(6, 5, 50), B = dioProj(6, 6, 50);
                   dioramaDown({ x: (A[0]+B[0])/2, y: (A[1]+B[1])/2 });
                   console.log(JSON.stringify(rec));
                   """)
    rec = json.loads(out)
    assert rec["moved"] == [4, 6], "panned-camera click must resolve to the visually clicked cell"
    assert rec["sheet"] == 9, "clicking the billboard must open the token"
    assert rec["sent"] and rec["sent"]["type"] == "door"


def test_onDbl_is_view_aware_and_no_double_camera_subtraction():
    """Pin the two client regressions textually: onDbl must resolve through
    clickCell (view-aware), and the diorama input path must not pre-subtract
    the camera before calling dioUnproj/dioTokenClick/dioDoorClick."""
    canvas = (JS / "50_canvas.js").read_text()
    m = re.search(r"function onDbl\(e\)\s*\{[\s\S]*?\n\}", canvas)
    assert m, "onDbl not found"
    body = m.group(0)
    assert "clickCell(p)" in body and "clickToken(p)" in body
    assert "toCell(p.x, p.y)" not in body, "onDbl must not use the ortho cell in diorama"
    dio = (JS / "55_diorama.js").read_text()
    m2 = re.search(r"function dioramaDown\(p\)\s*\{[\s\S]*?\n\}", dio)
    assert m2, "dioramaDown not found"
    body2 = m2.group(0)
    assert "state.cam.ox" not in body2, "dioramaDown must not pre-subtract the camera"
    assert "dioUnproj(p.x, p.y" in body2
