"""Guard tests for the client-local view mode (Tactical / Diorama).

The frontend has no JS test framework, so these tests verify the invariants
that matter most: view mode is presentation-only, client-local, never reaches
the server, and the Diorama renderer behaves on degenerate input. Behavioural
renderer checks run the real script bodies in a Node `vm` sandbox (skipped if
node is unavailable).
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "app" / "static" / "js"
NODE = shutil.which("node")

needs_node = pytest.mark.skipif(NODE is None, reason="node not available")


def _run_node(script: str) -> str:
    r = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, f"node failed: {r.stderr}"
    return r.stdout.strip()


def _func_body(source: str, name: str) -> str:
    m = re.search(rf"function {name}\([^)]*\)\s*\{{[\s\S]*?\n\}}", source)
    assert m, f"function {name} not found"
    return m.group(0)


def test_server_has_no_view_mode_plumbing():
    """The server must not know or care which renderer a client uses."""
    for py in (ROOT / "app").rglob("*.py"):
        text = py.read_text(encoding="utf-8", errors="replace")
        assert "view_mode" not in text, f"server view-mode plumbing in {py}"
    from app.room import dispatch
    for kind in ("view", "view_mode", "set_view", "viewmode"):
        assert kind not in dispatch.HANDLERS


def test_no_js_broadcasts_view_mode():
    """Switching views must not touch the network."""
    core = (JS / "10_core.js").read_text()
    body = _func_body(core, "setViewMode")
    for forbidden in ("wsSend", "fetch(", "api("):
        assert forbidden not in body, f"setViewMode must not use {forbidden}"
    for jsf in JS.glob("*.js"):
        assert "view_mode" not in jsf.read_text(), "view_mode must not exist anywhere"


def test_view_dispatch_and_loading():
    canvas = (JS / "50_canvas.js").read_text()
    dispatcher = _func_body(canvas, "draw")
    assert "drawDiorama()" in dispatcher and "drawTactical()" in dispatcher
    assert "function drawTactical()" in canvas
    html = (ROOT / "app" / "static" / "index.html").read_text()
    order = [html.index(p) for p in ("js/50_", "js/55_", "js/60_")]
    assert order == sorted(order), "55_diorama.js must load between 50 and 60"
    assert 'id="view-tactical"' in html and 'id="view-diorama"' in html


def _node_vm(paths, extra, sandbox_js="{}"):
    """Run `extra` inside a vm context that has loaded the given script files."""
    script = (
        "const vm=require('vm'),fs=require('fs');"
        f"const files={json.dumps(paths)};"
        f"const sb=Object.assign({{console}}, {sandbox_js});"
        "vm.createContext(sb);"
        "for(const f of files) vm.runInContext(fs.readFileSync(f,'utf8'),sb,{filename:f});"
        f"vm.runInContext({json.dumps(extra)},sb);"
    )
    return _run_node(script)


_CANVAS_STUB = """
const rec = { fills: 0, sends: [] };
const ctx = new Proxy({}, { get(t,p){ if(p==="fill") return ()=>{rec.fills++;};
                            return typeof t[p]==="function"?t[p]:()=>{}; },
                       set(t,p,v){ t[p]=v; return true; } });
const view = () => ({ w: 800, h: 600 });
const cellSize = () => 50;
"""
# 10_core.js is loaded FIRST in these harnesses (like in the browser) so the
# D72 helpers (gridOrigin/wIdx/inWorld) are the real ones; state/SIZE_FOOTPRINT
# come from core and must be assigned, never redeclared.
_CORE_STATE = """
Object.assign(state, { room:{ role:"player", members:[] }, viewMode:"diorama",
                       tokens:[], ghosts:[], cam:{ox:0,oy:0},
                       sel:null, plan:null, init:null });
"""




@needs_node
def test_view_mode_fallback_and_persistence():
    out = _node_vm(
        [str(JS / "10_core.js")],
        """
        const a = normalizeViewMode("bogus");
        const b = normalizeViewMode("diorama");
        const c = normalizeViewMode(null);
        localStorage.setItem("dndtable-view-mode","diorama");
        loadViewMode(); const d = state.viewMode;
        localStorage.setItem("dndtable-view-mode","nonsense");
        loadViewMode(); const e = state.viewMode;
        console.log([a,b,c,d,e].join(","));
        """,
        sandbox_js="""{ localStorage: (() => { const s = {};
            return { getItem: k => (k in s ? s[k] : null),
                     setItem: (k,v) => { s[k] = String(v); } }; })() }""",
    )
    assert out.split(",") == ["tactical", "diorama", "tactical", "diorama", "tactical"]


@needs_node
def test_diorama_empty_and_hidden_safe():
    """Empty map renders without error; unknown cells are never drawn."""
    out = _node_vm(
        [str(JS / "10_core.js"), str(JS / "55_diorama.js")],
        _CANVAS_STUB + _CORE_STATE + """
        let visibleHere = (i) => i !== 0;      // cell 0 unknown to this viewer
        // 1) no map at all -> must not throw and must paint nothing
        state.grid = null;
        drawDiorama(); const emptyFills = rec.fills;
        // 2) 1x2 map, cell 0 hidden -> exactly one floor quad painted
        state.grid = { w:2, h:1, cell:50, cells:[0,0], explored:[1,1],
                       doors:[], traps:[], loot:[], pins:[] };
        rec.fills = 0; drawDiorama(); const oneFill = rec.fills;
        // 3) token only on the hidden cell -> adds no extra paint, sends nothing
        state.tokens = [{ id:1, x:10, y:10, size:"Medium", label:"Goblin",
                          color:"#e74c3c", npc:true }];
        rec.fills = 0; drawDiorama(); const afterHiddenToken = rec.fills;
        console.log([emptyFills===0, oneFill===1, afterHiddenToken===oneFill, rec.sends.length===0].join(","));
        """,
    )
    assert out.split(",") == ["true", "true", "true", "true"]


@needs_node
def test_diorama_token_and_door_paths_execute():
    out = _node_vm(
        [str(JS / "10_core.js"), str(JS / "55_diorama.js")],
        _CANVAS_STUB + _CORE_STATE + """
        let visibleHere = () => true;
        const wsSend = (o) => rec.sends.push(o.type || "msg");
        const renderSheet = () => {};
        const ownToken = () => null;
        let segDist = () => 99;
        state.grid = { w:2, h:1, cell:50, cells:[0,0], explored:[1,1],
                       doors:[{id:"d1", x:0, y:0, dir:"v", closed:true, locked:false}],
                       traps:[], loot:[], pins:[] };
        state.tokens = [{ id:1, x:10, y:10, size:"Large", label:"Ogre",
                          color:"#e74c3c", npc:true }];
        state.ghosts = [{ id:9, x:60, y:10, color:"#9aa", label:"Old" }];
        state.sel = 1;
        drawDiorama(); const rendered = rec.fills > 0;
        // clicking the door edge reuses the authoritative door toggle only
        state.tokens = [];                       // click location is the door, not the card
        segDist = () => 0;                       // "on" the door segment
        dioramaDown({ x: 25, y: 15 });
        console.log([rendered, rec.sends.length===1, rec.sends[0]==="door"].join(","));
        """,
    )
    assert out.split(",") == ["true", "true", "true"]


@needs_node
def test_diorama_footprint_reveal_parity():
    """A Large token whose ORIGIN cell is hidden but another footprint cell is
    visible must render — matching the server's any-cell reveal semantics."""
    out = _node_vm(
        [str(JS / "10_core.js"), str(JS / "55_diorama.js")],
        _CANVAS_STUB + _CORE_STATE + """
        let visibleHere = (i) => i !== 0;               // origin cell hidden
        state.grid = { w:2, h:1, cell:50, cells:[0,0], explored:[1,1],
                       doors:[], traps:[], loot:[], pins:[] };
        state.tokens = [{ id:1, x:10, y:10, size:"Large", label:"Ogre",
                          color:"#e74c3c", npc:true }];
        drawDiorama();
        // expected paints: 1 visible floor quad + 1 billboard shadow fill
        console.log([rec.fills === 2].join(","));
        """,
    )
    assert out == "true"


def test_diorama_reads_only_filtered_client_state():
    """No second visibility authority, no extra data requests in the renderer."""
    dio = (JS / "55_diorama.js").read_text()
    assert "visibleHere(" in dio, "diorama must reuse the tactical visibility mask"
    for forbidden in ("fetch(", "api(", "XMLHttpRequest"):
        assert forbidden not in dio, f"diorama must not request data via {forbidden}"


# ---------- view framing regressions (D75, manual black-screen findings) ----------
# A player who opens a room must LAND on their own token, and the diorama must
# frame the KNOWN world — otherwise both renderers paint almost nothing and the
# manual tester sees "everything is black" plus a "stuck" diorama. These tests
# run the REAL renderers in a Node vm against a player-shaped payload.

_DOM_STUB = """
(() => {
  const rec = { rects: [], polys: [] };
  const ctx = { canvas:{width:800,height:600},
    fillRect:(x,y)=>{rec.rects.push([x,y]);}, clearRect(){}, strokeRect(){},
    beginPath(){ ctx._c=[]; }, moveTo(x,y){ ctx._c.push([x,y]); }, lineTo(x,y){ ctx._c.push([x,y]); },
    closePath(){}, arc(){}, fill(){ if (ctx._c) rec.polys.push(ctx._c); }, ellipse(){},
    stroke(){}, setLineDash(){}, save(){}, restore(){}, drawImage(){}, fillText(){},
    measureText:()=>({width:10}) };
  const mk = () => ({ style:{}, dataset:{}, value:"", textContent:"", innerHTML:"", checked:false,
    classList:{add(){},remove(){},toggle(){},contains:()=>false}, addEventListener(){},
    setAttribute(){}, appendChild(){}, onclick:null, width:800, height:600,
    getBoundingClientRect:()=>({width:800,height:600,left:0,top:0}),
    getContext:()=>ctx, parentElement:{getBoundingClientRect:()=>({width:800,height:600})},
    naturalWidth:0, complete:false });
  const els = {};
  return { rec, document: { getElementById: id => els[id] || (els[id] = mk()),
    createElement: () => mk(), querySelectorAll: () => [], addEventListener(){}, body: mk() },
    window: { devicePixelRatio:1, addEventListener(){} }, navigator:{},
    localStorage: (() => { const s={}; return { getItem:k=>(k in s?s[k]:null),
      setItem:(k,v)=>{s[k]=String(v);} }; })(),
    setTimeout, clearTimeout, requestAnimationFrame:()=>0,
    Image: function(){ return { naturalWidth:0 }; } };
})()
"""

_PLAYER_SCENE = """
Object.assign(state, {
  room: { role: "player", members: [] }, me: { id: 2, username: "pl" },
  grid: (() => { const w=40,h=26,cells=new Array(w*h).fill(null);
    for(let y=17;y<=23;y++)for(let x=33;x<=39;x++) cells[y*w+x]=0;   // ring deep in the world
    return { w,h,cell:50,origin:[0,0],cells,elev:[],explored:new Array(w*h).fill(0),
             traps:[],loot:[],doors:[],pins:[],fog_off:false }; })(),
  tokens: [{ id:1, owner_user_id:2, x:1825, y:1025, label:"Hero", color:"#4ae",
             size:"Medium", conds:[], death:{} }],
  ghosts: [], plan:null, aoe:null, pings:[], ruler:null, editing:false, editMap:null,
  cam:{ox:0,oy:0}, camT:{ox:0,oy:0}, camD:{ox:0,oy:0},
  sel:null, init:{combat:false,order:[],active:-1}, viewMode:"tactical",
  moving:new Set(), keys:new Set(), tickOn:false, online:new Set(["pl"]),
});
const snap = () => JSON.stringify(state.grid.cells) + "|" +
                   JSON.stringify(state.tokens.map(t=>[t.id,t.x,t.y]));
const inView = () => {
  const rects = rec.rects.filter(([x,y]) => x>-50 && x<850 && y>-50 && y<650).length;
  const polys = rec.polys.filter(p => p.some(([x,y]) => x>-50 && x<850 && y>-50 && y<650)).length;
  return [rects, polys];
};
"""


def _run_renderers(extra: str) -> str:
    out = _node_vm([str(JS / "10_core.js"), str(JS / "50_canvas.js"), str(JS / "55_diorama.js")],
                   extra, sandbox_js=_DOM_STUB)
    return out


@needs_node
def test_player_lands_on_own_token_not_on_black_space():
    out = _run_renderers(_PLAYER_SCENE + """
        const before = snap();
        rec.rects = []; drawTactical();                 // old entry state: cam (0,0)
        const blackBefore = inView()[0];                // the manual regression: ~nothing
        initViewCam();                                  // openRoom now frames my token
        rec.rects = []; drawTactical();
        const after = inView()[0];
        console.log([blackBefore <= 1, after >= 30, snap() === before].join(","));
        """)
    assert out == "true,true,true"


@needs_node
def test_diorama_frames_the_known_world_and_switching_back_restores():
    out = _run_renderers(_PLAYER_SCENE + """
        const before = snap();
        initViewCam();                                  // tactical framing (camT)
        const camT = JSON.stringify(state.cam);
        setViewMode("diorama");
        rec.polys = []; drawDiorama();
        const seen = inView()[1] >= 30;                 // fit put the KNOWN ring on screen
        setViewMode("tactical");
        const restored = JSON.stringify(state.cam) === camT;   // own view came back
        rec.rects = []; drawTactical();
        const back = inView()[0] >= 30;
        console.log([seen, restored, back, snap() === before,
                     state.viewMode === "tactical"].join(","));
        """)
    assert out == "true,true,true,true,true"


def test_view_switch_controls_live_in_stable_chrome():
    """D75/P5: the escape hatch must sit OUTSIDE the canvas/mapwrap layer, in
    the room header — no renderer can ever cover or swallow it."""
    html = (ROOT / "app" / "static" / "index.html").read_text()
    header = html[html.index('<section id="view-room"'):html.index('<main class="room-grid"')]
    for elem in ('id="btn-back"', 'id="view-tactical"', 'id="view-diorama"'):
        assert elem in header, f"{elem} must live in the room header chrome"
    assert 'id="viewtoggle"' in header
