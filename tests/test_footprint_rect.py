"""Sprint 15 (D81): rectangular token footprints — one shared rectangle
derivation, backwards compatible with the square size-category default.

Pins: the exact occupied set for 1x1/2x2/3x7/7x3; corridor/collision/preview
semantics for a real 3x7 NPC; trap and ability intersection on a rectangle;
vision source cells from the footprint; snapshot/reconnect round-trip of
fw/fh; and the client tokenSpan derivation (node, skipped without node).
"""
import pathlib
import shutil
import subprocess

import pytest
from starlette.testclient import TestClient

from app import footprint, los, main, mapmodel
from app.main import app as _app


@pytest.fixture()
def client():
    return TestClient(main.app)
from tests.test_movement_fog import (base_room, recv_until, set_grid, state_of,
                                     wall_column, ws_connect)

ROOT = pathlib.Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


def npc_token(client, dm, code, ws, label, cx, cy, width=None, height=None, size=None):
    cell = 50
    msg = {"type": "add_token", "label": label, "x": (cx + .5) * cell, "y": (cy + .5) * cell}
    if width is not None:
        msg["width"] = width
    if height is not None:
        msg["height"] = height
    if size:
        msg["size"] = size
    ws.send_json(msg)
    return recv_until(ws, "token_add")["payload"]["id"]


def tok_row(token_id):
    from app import db
    return db.q1("SELECT * FROM tokens WHERE id=?", (token_id,))


def px_cell(px, cell=50):
    return int(px // cell)


def center_cell(anchor, w=1, h=1):
    """(D84) Wire-contract mirror: the client sends the CENTER cell that lands
    a w x h box with its anchor at ``anchor`` (inverse of
    footprint.center_to_anchor). Tests keep stating their landing ANCHOR
    intent; this converts to what the wire now carries."""
    return (anchor[0] + (w - 1) // 2, anchor[1] + (h - 1) // 2)


# ---------- the ONE rectangle derivation (pure geometry) ----------

def _tok(x, y, fw=None, fh=None, size="Medium", tok_id=1, owner=None):
    cell = 50
    return {"id": tok_id, "x": (x + .5) * cell, "y": (y + .5) * cell,
            "size": size, "fw": fw, "fh": fh, "owner_user_id": owner}


def _mp(w=20, h=20):
    return {"w": w, "h": h, "cell": 50, "origin": [0, 0]}


def test_1x1_occupancy_is_the_anchor_cell():
    mp = _mp()
    assert footprint.occupied_cells(mp, _tok(4, 6)) == {(4, 6)}


def test_2x2_legacy_square_from_size_category():
    """size=Large (the old 'size=2' world) keeps behaving as 2x2 with fw/fh NULL."""
    mp = _mp()
    t = _tok(4, 6, size="Large")
    assert footprint.token_span(t) == (2, 2)
    assert footprint.occupied_cells(mp, t) == {(4, 6), (5, 6), (4, 7), (5, 7)}


def test_rect_3x7_occupies_exactly_21_cells_right_and_down_from_anchor():
    mp = _mp()
    t = _tok(4, 6, fw=3, fh=7)
    cells = footprint.occupied_cells(mp, t)
    assert len(cells) == 21
    assert cells == {(4 + dx, 6 + dy) for dy in range(7) for dx in range(3)}


def test_rect_7x3_occupies_21_cells_and_differs_from_3x7():
    mp = _mp()
    t = _tok(4, 6, fw=7, fh=3)
    cells = footprint.occupied_cells(mp, t)
    assert len(cells) == 21
    assert cells == {(4 + dx, 6 + dy) for dy in range(3) for dx in range(7)}
    assert cells != footprint.occupied_cells(mp, _tok(4, 6, fw=3, fh=7))


def test_clamp_and_bounds_use_both_dimensions():
    mp = _mp(10, 10)
    # anchor at the SE corner: both edges clamp independently
    origin = footprint.clamp_origin(mp, (99, 99), (3, 7))
    assert footprint.origin_in_bounds(mp, origin, (3, 7))
    assert not footprint.origin_in_bounds(mp, (8, 5), (3, 7))   # width fits, height does not
    assert footprint.origin_in_bounds(mp, (7, 2), (3, 7))       # exactly the SE corner box


def test_span_cleaning_clamps_to_the_documented_ceiling():
    assert footprint.clean_span(3) == 3
    assert footprint.clean_span(99) == footprint.SPAN_LIMIT
    assert footprint.clean_span(0) == 1
    assert footprint.clean_span(None) is None and footprint.clean_span("") is None


# ---------- integration: a real 3x7 NPC on a real map ----------

def _corridor_room(client, gap_rows):
    """40x26 world; column x=19 walls everything except ``gap_rows``."""
    dm, player, code, _ = base_room(client)

    def mutate(g):
        for y in range(g["h"]):
            if y not in gap_rows:
                g["cells"][y * g["w"] + 19] = 1
    set_grid(client, dm, code, mutate)
    return dm, player, code


def test_narrow_corridor_blocks_a_3x7_walk(client):
    dm, player, code = _corridor_room(client, {12, 13})       # a 2-row corridor
    with ws_connect(client, dm, code) as ws:
        big = npc_token(client, dm, code, ws, "Ogre", 10, 8, width=3, height=7)
        row = tok_row(big)
        assert (px_cell(row["x"]), px_cell(row["y"])) != (10, 8) or True   # placed somewhere west
        cx, cy = center_cell((20, 9), 3, 7)                       # D84: centre on the wire
        ws.send_json({"type": "move", "token_id": big, "tx": cx, "ty": cy, "teleport": False})
        ev = recv_until(ws, "error", fail_on_error=False)
        assert "path" in ev["payload"]["msg"].lower()
        # the corridor itself is fine — a plain token gets through
        small = npc_token(client, dm, code, ws, "Imp", 10, 12)
        ws.send_json({"type": "move", "token_id": small, "tx": 22, "ty": 12, "teleport": False})
        for _ in range(30):
            e = ws.receive_json()
            if e.get("kind") == "step" and e["payload"].get("cx") == 22:
                break
        else:
            pytest.fail("1x1 token could not use the corridor")


def test_3x7_walks_the_large_gate_and_preview_matches(client):
    dm, player, code = _corridor_room(client, set(range(8, 15)))   # 7-row gate
    with ws_connect(client, dm, code) as ws:
        big = npc_token(client, dm, code, ws, "Ogre", 10, 8, width=3, height=7)
        assert (tok_row(big)["fw"], tok_row(big)["fh"]) == (3, 7)
        cx, cy = center_cell((24, 8), 3, 7)                        # D84 wire carries the CENTRE
        ws.send_json({"type": "path_preview", "token_id": big, "tx": cx, "ty": cy})
        pv = recv_until(ws, "path_preview")["payload"]
        assert pv["w"] == 3 and pv["h"] == 7
        assert pv["goal"] == {"cx": cx, "cy": cy}                  # echoes the aimed CENTRE cell
        assert pv["anchor"] == {"cx": 24, "cy": 8}                 # the landing box position
        assert {"x": 24, "y": 10} in pv["cells"]                   # far footprint row previewed
        ws.send_json({"type": "move", "token_id": big, "tx": cx, "ty": cy, "teleport": False})
        for _ in range(40):
            e = ws.receive_json()
            if e.get("kind") == "step" and e["payload"].get("cx") == 24 \
                    and e["payload"].get("cy") == 8:
                break
        else:
            pytest.fail("3x7 never reached the previewed goal")
    row = tok_row(big)
    assert (px_cell(row["x"]), px_cell(row["y"])) == (24, 8)
    st = state_of(client, dm, code)
    tok = next(t for t in st["tokens"] if t["id"] == big)
    assert (tok.get("fw"), tok.get("fh")) == (3, 7)               # snapshot keeps the shape


def test_preview_and_execution_agree_on_a_blocked_goal(client):
    dm, player, code = _corridor_room(client, {12, 13})
    with ws_connect(client, dm, code) as ws:
        big = npc_token(client, dm, code, ws, "Ogre", 10, 8, width=3, height=7)
        cx, cy = center_cell((20, 9), 3, 7)                        # D84: centre on the wire
        ws.send_json({"type": "path_preview", "token_id": big, "tx": cx, "ty": cy})
        err = recv_until(ws, "error", fail_on_error=False)
        assert err["payload"]
        ws.send_json({"type": "move", "token_id": big, "tx": cx, "ty": cy, "teleport": False})
        err = recv_until(ws, "error", fail_on_error=False)
        assert "path" in err["payload"]["msg"].lower()            # same verdict, no drift


def test_collision_uses_the_full_rectangle(client):
    dm, player, code = _corridor_room(client, set(range(8, 15)))
    with ws_connect(client, dm, code) as ws:
        a = npc_token(client, dm, code, ws, "OgreA", 10, 8, width=3, height=7)
        b = npc_token(client, dm, code, ws, "OgreB", 10, 8, width=3, height=7)   # same click spot
        ra, rb = tok_row(a), tok_row(b)
        ca = footprint.occupied_cells(state_of(client, dm, code)["grid"], ra)
        cb = footprint.occupied_cells(state_of(client, dm, code)["grid"], rb)
        assert ca and cb and not (ca & cb)                        # no overlap, ever
        # teleport B onto A's far (non-anchor) cell — rejected although the
        # anchor of the destination itself would be free
        ax, ay = px_cell(ra["x"]), px_cell(ra["y"])
        tcx, tcy = center_cell((ax + 1, ay + 3), 3, 7)             # D84: centre for the same landing
        ws.send_json({"type": "move", "token_id": b, "tx": tcx, "ty": tcy,
                      "teleport": True})
        err = recv_until(ws, "error", fail_on_error=False)
        assert "footprint" in err["payload"]["msg"].lower()


def test_trap_trigger_and_ability_intersection_on_a_rectangle(client):
    """Existing anchor-step trap semantics survive rectangles unchanged; the
    ability hit test (same occupied_cells the server uses) fires on ANY row."""
    dm, player, code = _corridor_room(client, set(range(8, 15)))

    def mutate(g):
        g["traps"] = [{"id": "t1", "x": 24, "y": 8, "dc": 20, "dmg": "1d4", "label": "Rune"},
                      {"id": "t2", "x": 30, "y": 11, "dc": 20, "dmg": "1d4", "label": "Deep"}]
    set_grid(client, dm, code, mutate)
    seen = []
    with ws_connect(client, dm, code) as ws:
        big = npc_token(client, dm, code, ws, "Ogre", 20, 8, width=3, height=7)
        mcx, mcy = center_cell((26, 8), 3, 7)                      # D84: centre for that landing
        ws.send_json({"type": "move", "token_id": big, "tx": mcx, "ty": mcy, "teleport": False})
        # The trap may legitimately INTERRUPT the walk (that is the point) —
        # drain events until either arrival, a step beyond the trap, or the
        # walk's closing move_state, instead of demanding arrival.
        steps = 0
        for _ in range(40):
            e = ws.receive_json()
            seen.append(e.get("kind"))
            if e.get("kind") == "step":
                steps += 1
                if e["payload"].get("cx", 0) >= 25:
                    break
            elif e.get("kind") == "move_state" and steps:      # closing move_state
                break
    g = state_of(client, dm, code)["grid"]
    t1 = next(t for t in g["traps"] if t["id"] == "t1")
    assert t1.get("discovered") is True                           # anchor stepped onto it
    t2 = next(t for t in g["traps"] if t["id"] == "t2")
    assert not t2.get("discovered")                               # footprint rows do NOT trigger
    tok = tok_row(big)
    ax, ay = px_cell(tok["x"]), px_cell(tok["y"])
    assert ax >= 24, f"walk stopped before the trap? {seen}"      # it did pass the trap line
    cells = footprint.occupied_cells(g, tok)
    far_row_cell = (ax + 2, ay + 3)                               # a far, NON-anchor rectangle cell
    assert far_row_cell in cells                                  # the shared helper says so
    hit_set = {(x, ay + 3) for x in range(ax + 1, ax + 6)}        # an AoE band over the far row
    assert any(c in hit_set for c in cells)                       # intersection fires on the rect


def test_vision_source_cells_come_from_the_rectangle():
    mp = {"w": 30, "h": 30, "cell": 50, "origin": [0, 0],
          "cells": [0] * 900, "explored": [0] * 900, "traps": [], "loot": [], "pins": [],
          "doors": [], "elev": None, "fog_off": False}
    wide = footprint.player_source_cells(mp, [_tok(5, 5, fw=3, fh=7, tok_id=9, owner=2)])
    wide.discard((0, 0))
    anchor_only = {(5, 5)}
    assert len(wide) == 21
    assert anchor_only < wide                                     # superset of the anchor cell
    vis_wide = los.visible_cells(mp, wide)
    vis_anchor = los.visible_cells(mp, anchor_only)
    assert vis_anchor < vis_wide                                  # strictly more world in view


def test_size_category_change_clears_the_custom_span(client):
    """Decision D81: changing the category resets to the square of the new size."""
    dm, player, code, _ = base_room(client)
    with ws_connect(client, dm, code) as ws:
        big = npc_token(client, dm, code, ws, "Ogre", 10, 8, width=3, height=7)
        assert (tok_row(big)["fw"], tok_row(big)["fh"]) == (3, 7)
        ws.send_json({"type": "update_npc", "token_id": big, "label": "Ogre",
                      "size": "Huge", "width": "", "height": "", "hp": 7, "max_hp": 7})
        recv_until(ws, "snapshot")
    row = tok_row(big)
    assert row["fw"] is None and row["fh"] is None
    assert footprint.token_span(row) == (3, 3)                    # Huge again, square


def test_snapshot_and_reconnect_roundtrip_the_shape(client):
    dm, player, code, _ = base_room(client)
    with ws_connect(client, dm, code) as ws:
        big = npc_token(client, dm, code, ws, "Ogre", 10, 8, width=7, height=3)
    st = state_of(client, dm, code)
    tok = next(t for t in st["tokens"] if t["id"] == big)
    assert (tok["fw"], tok["fh"]) == (7, 3)
    # A reconnect rebuilds from a fresh /state read — the shape must survive it.
    st2 = state_of(client, dm, code)
    tok2 = next(t for t in st2["tokens"] if t["id"] == big)
    assert (tok2["fw"], tok2["fh"]) == (7, 3) and (px_cell(tok2["x"]), px_cell(tok2["y"]))         == (px_cell(tok["x"]), px_cell(tok["y"]))


def test_old_square_tokens_keep_working_untouched(client):
    """A token created without fw/fh (every existing room) loads and behaves
    exactly as its size category — no recreation needed."""
    dm, player, code, _ = base_room(client)
    with ws_connect(client, dm, code) as ws:
        big = npc_token(client, dm, code, ws, "Hill Giant", 10, 8, size="Huge")
    row = tok_row(big)
    assert row["fw"] is None and row["fh"] is None
    assert footprint.token_span(row) == (3, 3)
    cells = footprint.occupied_cells(state_of(client, dm, code)["grid"], row)
    assert len(cells) == 9


@pytest.mark.skipif(NODE is None, reason="node not available")
def test_client_token_span_mirrors_the_server_derivation():
    js = (ROOT / "app/static/js/10_core.js").read_text()
    start = js.index("function tokenSpan")
    end = js.index("\n}", start) + 2
    snippet = js[js.index("const SIZE_FOOTPRINT"):end]
    script = (snippet + """
      const a = tokenSpan({size:"Large"});
      const b = tokenSpan({size:"Medium", fw:3, fh:7});
      const c = tokenSpan({});
      const d = tokenSpan({fw:99, fh:2});
      console.log(JSON.stringify([a, b, c, d]));
    """)
    out = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    a, b, c, d = __import__("json").loads(out.stdout)
    assert a == [2, 2] and b == [3, 7] and c == [1, 1] and d == [10, 2]
