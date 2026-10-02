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
const SIZE_FOOTPRINT = { Medium:1, Large:2 };
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
        [str(JS / "55_diorama.js")],
        _CANVAS_STUB + """
        let visibleHere = (i) => i !== 0;      // cell 0 unknown to this viewer
        const state = { room:{ role:"player", members:[] }, viewMode:"diorama",
                        grid:null, tokens:[], ghosts:[], cam:{ox:0,oy:0},
                        sel:null, plan:null, init:null };
        // 1) no map at all -> must not throw and must paint nothing
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
        [str(JS / "55_diorama.js")],
        _CANVAS_STUB + """
        let visibleHere = () => true;
        const wsSend = (o) => rec.sends.push(o.type || "msg");
        const renderSheet = () => {};
        const ownToken = () => null;
        let segDist = () => 99;
        const state = { room:{ role:"player", members:[] }, viewMode:"diorama",
                        grid:{ w:2, h:1, cell:50, cells:[0,0], explored:[1,1],
                               doors:[{id:"d1", x:0, y:0, dir:"v", closed:true, locked:false}],
                               traps:[], loot:[], pins:[] },
                        tokens:[{ id:1, x:10, y:10, size:"Large", label:"Ogre",
                                  color:"#e74c3c", npc:true }],
                        ghosts:[{ id:9, x:60, y:10, color:"#9aa", label:"Old" }],
                        cam:{ox:0,oy:0}, sel:1, plan:null, init:null };
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
        [str(JS / "55_diorama.js")],
        _CANVAS_STUB + """
        let visibleHere = (i) => i !== 0;               // origin cell hidden
        const state = { room:{ role:"player", members:[] }, viewMode:"diorama",
                        grid:{ w:2, h:1, cell:50, cells:[0,0], explored:[1,1],
                               doors:[], traps:[], loot:[], pins:[] },
                        tokens:[{ id:1, x:10, y:10, size:"Large", label:"Ogre",
                                  color:"#e74c3c", npc:true }],
                        ghosts:[], cam:{ox:0,oy:0}, sel:null, plan:null, init:null };
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
