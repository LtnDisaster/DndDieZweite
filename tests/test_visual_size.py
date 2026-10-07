"""D82: visual token size is NOT mechanical occupancy.

Pins: visual_span falls back to the EFFECTIVE collision span (legacy tokens
render unchanged); occupied_cells never sees vw/vh; the `token_visual`
operation persists/broadcasts without touching fw/fh/x/y; a visual resize
requires no clearance; a mechanical resize still owns the cells and still
rejects an ill-fitting rectangle unchanged; hidden NPC tokens leak no visual
silhouette; a fresh snapshot carries both; and the real client `tokenAt`
selects through the visual artwork while gameplay spans stay mechanical.
"""
import json
import pathlib
import shutil
import subprocess

import pytest
from starlette.testclient import TestClient

from app import db, footprint, main


@pytest.fixture()
def client():
    return TestClient(main.app)
from tests.test_footprint_rect import npc_token, px_cell, tok_row
from tests.test_movement_fog import base_room, recv_until, set_grid, state_of, ws_connect

ROOT = pathlib.Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


def _tok(x, y, fw=None, fh=None, vw=None, vh=None, size="Medium", tok_id=1, owner=None):
    cell = 50
    return {"id": tok_id, "x": (x + .5) * cell, "y": (y + .5) * cell,
            "size": size, "fw": fw, "fh": fh, "vw": vw, "vh": vh,
            "owner_user_id": owner}


def _mp(w=20, h=20):
    return {"w": w, "h": h, "cell": 50, "origin": [0, 0]}


# ---------- the ONE visual derivation (pure geometry) ----------

def test_visual_span_defaults_to_effective_mechanical_span():
    assert footprint.visual_span(_tok(4, 6)) == (1, 1)                  # legacy 1x1
    assert footprint.visual_span(_tok(4, 6, size="Large")) == (2, 2)    # category square
    assert footprint.visual_span(_tok(4, 6, fw=3, fh=7)) == (3, 7)      # mechanical 3x7
    assert footprint.visual_span(_tok(4, 6, fw=3, fh=7, vw=5, vh=2)) == (5, 2)


def test_visual_span_clamps_and_survives_garbage():
    assert footprint.visual_span(_tok(4, 6, vw=99, vh=0)) == (10, 1)
    assert footprint.visual_span(_tok(4, 6, vw="abc", vh=None)) == (1, 1)
    assert footprint.visual_span({}) == (1, 1)


def test_occupied_cells_never_see_visual_dimensions():
    mp = _mp()
    plain = _tok(4, 6)
    art = _tok(4, 6, vw=3, vh=7)
    wide = _tok(4, 6, fw=3, fh=3, vw=7, vh=1)
    assert footprint.occupied_cells(mp, art) == footprint.occupied_cells(mp, plain)
    assert footprint.occupied_cells(mp, wide) == {(4 + dx, 6 + dy)
                                                  for dy in range(3) for dx in range(3)}


def test_visual_cells_are_centered_on_the_mechanical_footprint():
    """1x1 collision at (5,5) wearing a 3x5 visual: the 3x5 rect is centered
    on the occupied cell (floor-rounding for odd offsets), never its corner."""
    mp = _mp()
    cells = footprint.visual_cells(mp, _tok(5, 5, vw=3, vh=5))
    assert (5, 5) in cells
    assert len(cells) == 15
    xs = {c[0] for c in cells}
    assert xs == {4, 5, 6}


# ---------- the authoritative token_visual operation ----------

def test_token_visual_persists_broadcasts_and_never_moves_or_resizes(client):
    dm, player, code, _ = base_room(client)
    st0 = state_of(client, player, code)
    mine = next(t["id"] for t in st0["tokens"] if t["owner_user_id"] == st0["me"])
    row0 = tok_row(mine)
    with ws_connect(client, dm, code) as dws:
        with ws_connect(client, player, code) as ws:
            ws.send_json({"type": "token_visual", "token_id": mine, "width": 3, "height": 7})
            ev = recv_until(ws, "token_visual")["payload"]
            assert (ev["vw"], ev["vh"]) == (3, 7)
            seen = None
            for _ in range(20):
                e = dws.receive_json()
                if e.get("kind") == "token_visual" and e["payload"]["token_id"] == mine:
                    seen = e["payload"]
                    break
            assert seen and (seen["vw"], seen["vh"]) == (3, 7)
    row1 = tok_row(mine)
    assert (row1["vw"], row1["vh"]) == (3, 7)
    assert (row1["fw"], row1["fh"]) == (row0["fw"], row0["fh"])      # footprint untouched
    assert (row1["x"], row1["y"]) == (row0["x"], row0["y"])          # never moved
    tok = next(t for t in state_of(client, player, code)["tokens"] if t["id"] == mine)
    assert (tok["vw"], tok["vh"]) == (3, 7)                          # fresh snapshot


def test_visual_resize_never_changes_collision(client):
    """With a 3x7 artwork on a 1x1 token, foreign tokens may STILL finish on
    the cells the artwork merely covers — only the mechanical cell collides."""
    dm, player, code, _ = base_room(client)
    st0 = state_of(client, player, code)
    mine = next(t["id"] for t in st0["tokens"] if t["owner_user_id"] == st0["me"])
    pc = next(t for t in st0["tokens"] if t["id"] == mine)
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "token_visual", "token_id": mine, "width": 3, "height": 7})
        recv_until(ws, "token_visual")
    mp = state_of(client, dm, code)["grid"]
    pc_row = tok_row(mine)
    origin, (w, h) = footprint.occupied_origin(mp, pc_row)
    assert footprint.occupied_cells(mp, pc_row) == set(footprint.origin_cells(mp, origin, (w, h)))
    assert (w, h) == (1, 1)                                # still MECHANICALLY 1x1
    probe = {**pc_row, "id": 99999, "owner_user_id": None}
    # only the MECHANICAL cell blocks: a foreign token may NOT finish on it…
    assert not footprint.valid_final_position(mp, probe, origin, [pc_row, probe])
    # …but the cells the 3x7 artwork merely COVERS (centered: ±1 x, ±3 y)
    # stay free — collision never grew with the art.
    assert footprint.valid_final_position(mp, probe, (origin[0] + 1, origin[1]),
                                          [pc_row, probe])
    assert footprint.valid_final_position(mp, probe, (origin[0], origin[1] + 3),
                                          [pc_row, probe])


def test_foreign_token_visual_resize_is_refused(client):
    dm, player, code, _ = base_room(client)
    with ws_connect(client, dm, code) as ws:
        npc = npc_token(client, dm, code, ws, "Goblin", 15, 12)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "token_visual", "token_id": npc, "width": 4, "height": 4})
        err = recv_until(ws, "error", fail_on_error=False)
        assert "your token" in err["payload"]["msg"].lower()
    assert tok_row(npc)["vw"] is None


def test_visual_illegal_values_are_handled_authoritatively(client):
    dm, player, code, _ = base_room(client)
    with ws_connect(client, dm, code) as ws:
        npc = npc_token(client, dm, code, ws, "Squad", 12, 12)
        ws.send_json({"type": "token_visual", "token_id": npc, "width": "abc", "height": 2})
        err = recv_until(ws, "error", fail_on_error=False)
        assert "required" in err["payload"]["msg"].lower()
        ws.send_json({"type": "token_visual", "token_id": npc, "width": 99, "height": 1})
        assert recv_until(ws, "token_visual")["payload"]["vw"] == footprint.SPAN_LIMIT


def test_mechanical_resize_still_owns_the_cells(client):
    """After a visual 5x5, a valid mechanical 3x3 resize DOES change the
    occupied cells; an ill-fitting one is still rejected unchanged."""
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
        ws.send_json({"type": "token_visual", "token_id": npc, "width": 5, "height": 5})
        recv_until(ws, "token_visual")
        mp = state_of(client, dm, code)["grid"]
        mp.setdefault("origin", [0, 0])
        row = tok_row(npc)
        assert len(footprint.occupied_cells(mp, row)) == 1
        ws.send_json({"type": "token_span", "token_id": npc, "width": 3, "height": 7})
        err = recv_until(ws, "error", fail_on_error=False)       # 3x7 into the 2-row slot
        assert "fit" in err["payload"]["msg"].lower()
        assert (tok_row(npc)["fw"], tok_row(npc)["fh"]) == (None, None)
        ws.send_json({"type": "token_span", "token_id": npc, "width": 1, "height": 2})
        assert recv_until(ws, "token_span")["payload"]["fh"] == 2
        row = tok_row(npc)
        assert len(footprint.occupied_cells(mp, row)) == 2       # mechanical owns the cells
        assert (row["vw"], row["vh"]) == (5, 5)                  # visual kept independently


def test_hidden_token_leaks_no_visual_silhouette(client):
    dm, player, code, _ = base_room(client)
    with ws_connect(client, dm, code) as ws:
        npc = npc_token(client, dm, code, ws, "Dragon", 10, 8)   # inside the player's LOS
        ws.send_json({"type": "token_visual", "token_id": npc, "width": 4, "height": 9})
        recv_until(ws, "token_visual")
    pst = state_of(client, player, code)
    tok = next(t for t in pst["tokens"] if t["id"] == npc)
    assert "vw" not in tok and "vh" not in tok       # D82: no silhouette leak
    assert "fw" not in tok and "fh" not in tok and "size" not in tok
    dtok = next(t for t in state_of(client, dm, code)["tokens"] if t["id"] == npc)
    assert (dtok["vw"], dtok["vh"]) == (4, 9)


def test_snapshot_row_columns_are_backwards_compatible():
    """Old-shaped rows (no vw/vh keys at all — pre-D82 dicts) must not break
    the visual derivation used server-side."""
    legacy = {"x": 250.0, "y": 250.0, "size": "Medium", "fw": None, "fh": None}
    assert footprint.visual_span(legacy) == (1, 1)


# ---------- the REAL client helpers (node) ----------

@pytest.mark.skipif(NODE is None, reason="node not available")
def _client_hit(points, tokens):
    core = (ROOT / "app/static/js/10_core.js").read_text()
    canvas = (ROOT / "app/static/js/50_canvas.js").read_text()
    vis = core[core.index("const SIZE_FOOTPRINT"):core.index("\n}", core.index("function visualSpan")) + 2]
    hit = canvas[canvas.index("function tokenAt"):canvas.index("function ownToken")]
    script = f"""
      function cellSize(){{ return 50; }}
      const state = {{ tokens: {json.dumps(tokens)} }};
      {vis}
      {hit}
      const out = {json.dumps(points)}.map(([x, y]) => {{
        const t = tokenAt(x, y); return t ? t.id : null;
      }});
      console.log(JSON.stringify(out));
    """
    r = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@pytest.mark.skipif(NODE is None, reason="node not available")
def test_selection_works_through_large_visual_artwork(client):
    dm, player, code, _ = base_room(client)
    with ws_connect(client, dm, code) as ws:
        npc = npc_token(client, dm, code, ws, "Wyrm", 12, 12)     # mechanical 1x1
        ws.send_json({"type": "token_visual", "token_id": npc, "width": 3, "height": 7})
        recv_until(ws, "token_visual")
    c = 50
    cx, cy = (12 + .5) * c, (12 + .5) * c      # footprint center = artwork center
    tokens = [{"id": npc, "x": cx, "y": cy, "size": "Medium",
               "fw": None, "fh": None, "vw": 3, "vh": 7}]
    legacy = [{"id": 4242, "x": cx, "y": cy, "size": "Large",
               "fw": None, "fh": None}]
    # deep inside the 3x7 artwork (3 cells below the 1x1 body) -> selectable
    hits = _client_hit([[cx, cy + 3.4 * c]], tokens)
    assert hits == [npc]
    # clearly outside the artwork -> NOT selectable by that token
    hits = _client_hit([[cx, cy + 5.4 * c]], tokens)
    assert hits == [None]
    # legacy token (visual == mechanical 2x2): the old footprint spot still hits
    hits = _client_hit([[cx + 0.9 * c, cy + 0.9 * c]], legacy)
    assert hits == [4242]
