"""Sprint 15B recovery: the two user-visible failures and their pins.

A) every Tactical token invisible — a loop-local `const [w, h]` shadowed the
   draw function's viewport `w/h` and the culling `continue` dropped every
   token outside the top-left corner. Pinned statically (regression class)
   and behaviorally (legacy tokens yield real, non-zero render geometry).
B) no discoverable footprint editor — a labelled Footprint row now lives in
   the normal sheet of every selectable token and drives the new server
   `token_span` operation, which validates the COMPLETE rectangle at the
   token's CURRENT position and rejects an ill-fitting resize unchanged.
"""
import json
import pathlib
import shutil
import subprocess

import pytest
from starlette.testclient import TestClient

from app import footprint, main


@pytest.fixture()
def client():
    return TestClient(main.app)
from tests.test_footprint_rect import npc_token, px_cell, tok_row
from tests.test_movement_fog import base_room, recv_until, set_grid, state_of, ws_connect

ROOT = pathlib.Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


def _canvas():
    return (ROOT / "app/static/js/50_canvas.js").read_text()


# ---------- A: the shadowing regression class can never return ----------

def test_render_loop_never_shadows_the_viewport_dimensions():
    src = _canvas()
    start = src.index("for (const t of state.tokens){")
    culled = src.index("continue;", start)
    loop_head = src[start:culled]
    assert "tokenSpan(t)" in loop_head                  # the fix is in place
    assert "const [w, h]" not in loop_head              # viewport w/h must not be shadowed
    assert "tx > w+80 || ty > h+80" in loop_head        # culling STILL uses viewport w/h


def test_tokenAt_and_plan_use_distinct_span_names():
    src = _canvas()
    at = src[src.index("function tokenAt"):src.index("function ownToken")]
    assert "const [w, h] = tokenSpan" in at             # tokenAt owns no viewport vars
    assert "state.plan.w" in src and "pw" in src        # plan marker uses pw/ph


@pytest.mark.skipif(NODE is None, reason="node not available")
def _span_geometry(tokens):
    """Evaluate the CLIENT's real tokenSpan over real server snapshot tokens."""
    js = (ROOT / "app/static/js/10_core.js").read_text()
    snippet = js[js.index("const SIZE_FOOTPRINT"):js.index("\n}", js.index("function tokenSpan")) + 2]
    script = snippet + f"""
      const out = {json.dumps(tokens)}.map(t => {{
        const [w, h] = tokenSpan(t), side = Math.max(w, h);
        const c = 50;
        return {{ w, h, rect: [w * c, h * c],
                  radius: (c / 50) * (side === 1 ? 16 : 20 + (side - 1) * 14) }};
      }});
      console.log(JSON.stringify(out));
    """
    r = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@pytest.mark.skipif(NODE is None, reason="node not available")
def test_legacy_and_custom_tokens_yield_visible_geometry(client):
    """The exact failure mode: legacy tokens (fw/fh absent) must produce
    non-zero, correct render geometry through the client's helper."""
    dm, player, code, _ = base_room(client)
    with ws_connect(client, dm, code) as ws:
        pst = state_of(client, player, code)
        pc = next(t for t in pst["tokens"] if t["owner_user_id"] == pst["me"])
        legacy2x2 = npc_token(client, dm, code, ws, "Legacy", 14, 12, size="Large")
        rect3x7 = npc_token(client, dm, code, ws, "Rect", 20, 10, width=3, height=7)
        rect7x3 = npc_token(client, dm, code, ws, "Flat", 26, 10, width=7, height=3)
    st = state_of(client, dm, code)
    by_id = {t["id"]: t for t in st["tokens"]}
    payload = [{"size": pc.get("size", "Medium"), "fw": pc.get("fw"), "fh": pc.get("fh")},
               {k: by_id[legacy2x2].get(k) for k in ("size", "fw", "fh")},
               {k: by_id[rect3x7].get(k) for k in ("size", "fw", "fh")},
               {k: by_id[rect7x3].get(k) for k in ("size", "fw", "fh")}]
    g = _span_geometry(payload)
    assert g[0]["w"] == 1 and g[0]["radius"] > 0 and g[0]["rect"] == [50, 50]     # legacy 1x1
    assert g[1]["w"] == 2 and g[1]["h"] == 2 and g[1]["rect"] == [100, 100]       # legacy 2x2
    assert g[2]["w"] == 3 and g[2]["h"] == 7 and g[2]["rect"] == [150, 350]       # custom 3x7
    assert g[3]["w"] == 7 and g[3]["h"] == 3 and g[3]["rect"] == [350, 150]       # custom 7x3
    assert all(x["radius"] > 0 for x in g)


# ---------- B: the server-authoritative resize operation ----------

def test_resize_flow(client):
    dm, player, code, _ = base_room(client)
    mine = next(t["id"] for t in state_of(client, player, code)["tokens"]
                if t["owner_user_id"] == state_of(client, player, code)["me"])
    with ws_connect(client, dm, code) as dws:                 # DM watches the room
        with ws_connect(client, player, code) as ws:
            ws.send_json({"type": "token_span", "token_id": mine, "width": 3, "height": 7})
            ev = recv_until(ws, "token_span")["payload"]
            assert (ev["fw"], ev["fh"]) == (3, 7)
            seen = None
            for _ in range(20):
                e = dws.receive_json()
                if e.get("kind") == "token_span" and e["payload"]["token_id"] == mine:
                    seen = e["payload"]
                    break
            assert seen and (seen["fw"], seen["fh"]) == (3, 7)
    st = state_of(client, player, code)                       # a FRESH snapshot keeps it
    tok = next(t for t in st["tokens"] if t["id"] == mine)
    assert (tok["fw"], tok["fh"]) == (3, 7)
    row = tok_row(mine)
    assert (px_cell(row["x"]), px_cell(row["y"])) == (8, 6)   # NEVER moved by a resize


def test_foreign_token_resize_is_refused(client):
    dm, player, code, _ = base_room(client)
    with ws_connect(client, dm, code) as ws:
        npc = npc_token(client, dm, code, ws, "Goblin", 15, 12)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "token_span", "token_id": npc, "width": 2, "height": 2})
        err = recv_until(ws, "error", fail_on_error=False)
        assert "your token" in err["payload"]["msg"].lower()
    assert tok_row(npc)["fw"] is None


def test_illegal_values_are_handled_authoritatively(client):
    dm, player, code, _ = base_room(client)
    with ws_connect(client, dm, code) as ws:
        npc = npc_token(client, dm, code, ws, "Squad", 12, 12)
        ws.send_json({"type": "token_span", "token_id": npc, "width": "abc", "height": 2})
        err = recv_until(ws, "error", fail_on_error=False)
        assert "required" in err["payload"]["msg"].lower()
        ws.send_json({"type": "token_span", "token_id": npc, "width": 99, "height": 1})
        assert recv_until(ws, "token_span")["payload"]["fw"] == footprint.SPAN_LIMIT


def test_resize_that_does_not_fit_is_rejected_and_everything_stays(client):
    dm, player, code, _ = base_room(client)

    def walls(g):                                     # a 2-row slot around (12,12)
        for y in range(g["h"]):
            if y not in (12, 13):
                g["cells"][y * g["w"] + 15] = 1
        for x in range(g["w"]):
            g["cells"][8 * g["w"] + x] = 1
            g["cells"][17 * g["w"] + x] = 1
    set_grid(client, dm, code, walls)
    with ws_connect(client, dm, code) as ws:
        npc = npc_token(client, dm, code, ws, "Snake", 12, 12)
        row0 = tok_row(npc)
        ws.send_json({"type": "token_span", "token_id": npc, "width": 3, "height": 7})
        err = recv_until(ws, "error", fail_on_error=False)
        assert "fit" in err["payload"]["msg"].lower()
        row1 = tok_row(npc)
        assert (row1["fw"], row1["fh"]) == (None, None)         # old dimensions kept
        assert (row1["x"], row1["y"]) == (row0["x"], row0["y"]) # and NOT relocated
        # a footprint that DOES fit the slot still works (1x2)
        ws.send_json({"type": "token_span", "token_id": npc, "width": 1, "height": 2})
        assert recv_until(ws, "token_span")["payload"]["fh"] == 2


def test_update_npc_span_change_in_place_only(client):
    dm, player, code, _ = base_room(client)

    def walls(g):
        for y in range(g["h"]):
            if y not in (12, 13):
                g["cells"][y * g["w"] + 15] = 1
    set_grid(client, dm, code, walls)
    with ws_connect(client, dm, code) as ws:
        npc = npc_token(client, dm, code, ws, "Tight", 13, 10)   # near the wall line x=15
        ws.send_json({"type": "update_npc", "token_id": npc, "label": "Tight",
                      "hp": 9, "max_hp": 9, "size": "Gargantuan"})   # 4x4 into the 2-row gap
        err = recv_until(ws, "error", fail_on_error=False)
        assert "fit" in err["payload"]["msg"].lower()
        assert tok_row(npc)["size"] == "Medium"                   # whole save rejected
        # unrelated edit (label only) keeps working
        ws.send_json({"type": "update_npc", "token_id": npc, "label": "Renamed"})
        recv_until(ws, "snapshot")
        assert tok_row(npc)["label"] == "Renamed"
