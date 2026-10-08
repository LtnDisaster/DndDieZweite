"""Sprint 20 P2 — browser-flow regression harness (NO real browser).

Honesty clause: no browser runtime exists on this host (no Playwright,
no chromium — checked 2026-10-08). Installing one was out of the timebox
and would be a major dependency change. This is the documented fallback:
a REAL-JS integration harness — the genuine client code files (10_core,
50_canvas) execute in a Node vm (the established pattern of
test_geometry_contract/test_view_mode), while the server half runs the
genuine WS/REST stack. Pixels are faked by a canvas stub; the WIRE,
server authority, geometry math and persistence are all real.

The six requested browser steps, mapped to what actually runs here:
  1 open Tactical view   -> real draw() dispatcher with viewMode=tactical
  2 token visible        -> state from the live /state (server-filtered)
  3 select rectangular   -> real tokenAt() hit test on a 2x1 token
  4 movement preview     -> real requestPathPreview() -> live server ->
                            real applyPathPreview()
  5 confirm & position   -> real confirmPlan() wire -> live move handler
                            -> step events + DB truth
  6 refresh & persistence-> second /state fetch: identical position
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from app import db
from app.main import app
from tests.test_movement_fog import (H, base_room, recv_until, state_of,
                                     ws_connect)

NODE = shutil.which("node")
ROOT = Path(__file__).resolve().parents[1]

_DOM = """
{
  window: { addEventListener: () => {}, devicePixelRatio: 1 },
  location: { search: '' },
  requestAnimationFrame: () => 0,
  setTimeout: () => 0, clearTimeout: () => 0,
  localStorage: { getItem: () => null, setItem: () => {} },
  document: (() => {
    const cache = {};
    const fakeCtx = new Proxy({}, { get: () => (() => {}) });
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
    assert r.returncode == 0, f"node failed: {r.stderr[-4000:]}"
    return r.stdout.strip()


def _vm(init_js, probe_js):
    js = ROOT / "app/static/js"
    boot = ("var rec = { sent: [] };"
            "state.pings=[]; state.viewMode='tactical';"
            "wsSend = (m) => rec.sent.push(m);"
            "toast = () => {}; renderSheet = () => {}; refreshRoom = () => {};")
    script = (
        "const vm=require('vm'),fs=require('fs');"
        f"const files={[str(js / '10_core.js'), str(js / '50_canvas.js')]};"
        f"const sb=Object.assign({{console}}, {_DOM});"
        "vm.createContext(sb);"
        "for(const f of files) vm.runInContext(fs.readFileSync(f,'utf8'),sb,{filename:f});"
        f"vm.runInContext({json.dumps(boot)},sb);"
        f"vm.runInContext({json.dumps(init_js)},sb);"
        f"vm.runInContext({json.dumps(probe_js)},sb);"
    )
    return json.loads(_run_node(script))


def _client_state_js(st):
    """The sandbox boots from the LIVE server snapshot — server truth, not a
    fixture sketch: tokens, grid (already per-viewer filtered), role."""
    return "Object.assign(state, {\n" + "\n".join([
        f"me: {{ id: {st['me']} }},",
        f"room: {{ role: {json.dumps(st['role'])}, members: {json.dumps(st['members'])} }},",
        f"grid: {json.dumps(st['grid'])},",
        f"tokens: {json.dumps(st['tokens'])},",
        "cam: { ox: 0, oy: 0 }, plan: null, planRequest: null, sel: null,",
        "moving: new Set(), ghosts: [], init: null, keys: new Set(),",
        "aoe: null, ruler: null, rulerArmed: false, aoeArmed: false,",
        "pingArmed: false, editing: false, editMap: null, viewFloor: '',",
        "chars: [], members: [],",
        "});",
    ])


@pytest.mark.skipif(NODE is None, reason="node not available")
def test_tactical_selection_preview_confirm_refresh_flow():
    c = TestClient(app)
    dm, player, code, ch = base_room(c)
    ptok = db.q1("SELECT * FROM tokens WHERE character_id=?", (ch["id"],))
    rect_id = ptok["id"]
    with ws_connect(c, dm, code) as wsd:
        # a rectangular token: 2 x 1 (real mechanical span via token_span)
        wsd.send_json({"type": "token_span", "token_id": rect_id, "width": 2, "height": 1})
        recv_until(wsd, "token_span")
        wsd.send_json({"type": "move", "token_id": rect_id, "tx": 5, "ty": 5,
                       "teleport": True})
        recv_until(wsd, "step")

    st = state_of(c, player, code)                       # live, filtered /state
    init = _client_state_js(st)

    # steps 1-4a: tactical draw, real hit test, real preview request on the wire
    run1 = _vm(init, """
      draw();                                             // (1) tactical render
      const t = state.tokens.find(x => x.id === SELID);
      const [w, h] = tokenSpan(t), c = cellSize();
      const cx_px = t.x + (w - 1) * c / 2, cy_px = t.y + (h - 1) * c / 2;
      const hit = tokenAt(cx_px, cy_px);                  // (2)+(3) real hit test
      state.sel = hit ? hit.id : null;                    // (3) selection state
      const visible = !!hit;                              // (2)
      requestPathPreview(9, 7, true);                     // (4) real request path
      console.log(JSON.stringify({ drawn: true, visible,
        sel: state.sel === SELID, wire: rec.sent[0] || null,
        rect: [w, h] }));
    """.replace("SELID", json.dumps(rect_id)))
    assert run1["drawn"] and run1["visible"] and run1["sel"], run1
    assert run1["rect"] == [2, 1]                         # rectangular token
    wire = run1["wire"]
    assert wire["type"] == "path_preview" and (wire["tx"], wire["ty"]) == (9, 7)

    # (4) the LIVE server answers the client's real request:
    with ws_connect(c, player, code) as wsp:
        wsp.send_json(wire)
        plan = recv_until(wsp, "path_preview")["payload"]
        assert plan.get("within_budget") and plan.get("cells"), plan
        assert plan.get("anchor") is not None             # D84 contract on the wire

        # step 5: the REAL client applies the server preview, then confirms —
        # the confirm travels as the client's own wire message over the live WS
        run2 = _vm(init + f"\nstate.sel = {json.dumps(rect_id)};", """
          state.planRequest = { id: PLAN.request_id, token_id: PLAN.token_id,
                                goal: PLAN.goal, confirmAfter: false };
          applyPathPreview(PLAN);                         // real 40_ws case body
          const planned = !!(state.plan && state.plan.cells.length);
          confirmPlan();                                  // real confirm -> move
          console.log(JSON.stringify({ planned, move: rec.sent[0] || null }));
        """.replace("PLAN", json.dumps(plan)))
        assert run2["planned"] and run2["move"]["type"] == "move"
        assert (run2["move"]["tx"], run2["move"]["ty"]) == (9, 7)

        wsp.send_json(run2["move"])
        # drain the walk to its end: the last step carries the final position
        last = None
        for _ in range(80):
            e = wsp.receive_json()
            k = e.get("kind")
            if k == "step" and e["payload"]["token_id"] == rect_id:
                last = e["payload"]
            if k == "move_state" and e["payload"]["moving"] is False:
                break
        assert last, "walk never stepped"

    row = db.q1("SELECT x, y FROM tokens WHERE id=?", (rect_id,))
    gx, gy = int(row["x"] // 50), int(row["y"] // 50)
    assert (gx, gy) != (5, 5), "the confirmed move never happened"
    assert (int(last["x"]), int(last["y"])) == (int(row["x"]), int(row["y"])), \
        "the last delivered step must match the DB truth (no orphan position)"

    # (6) refresh: a fresh /state must show the same server truth
    st2 = state_of(c, player, code)
    t2 = [t for t in st2["tokens"] if t["id"] == rect_id][0]
    assert (int(t2["x"] // 50), int(t2["y"] // 50)) == (gx, gy)
    run3 = _vm(_client_state_js(st2), """
      draw();
      const t = state.tokens.find(x => x.id === SELID);
      const [w, h] = tokenSpan(t), c = cellSize();
      const hit = tokenAt(t.x + (w - 1) * c / 2, t.y + (h - 1) * c / 2);
      console.log(JSON.stringify({ ok: hit && hit.id === SELID }));
    """.replace("SELID", json.dumps(rect_id)))
    assert run3["ok"], "after refresh the rectangle is still selectable in place"
