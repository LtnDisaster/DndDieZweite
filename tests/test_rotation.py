"""D82/D83: token rotation ORIENTS THE ENTITY — its mechanical footprint turns
with it, re-anchored so the conceptual centre is preserved, and an illegal
turn is rejected with everything intact.

Pins: 0/90/180/270 normalization server-side; persistence + reconnect; a 2x4
at 90 degrees IS a 4x2 (footprint, not stored fw/fh — those stay the base);
the re-anchor preserves the doubled centre exactly and is reversible; a turn
into wall/overlap/bounds is refused and changes NOTHING; visual and mechanical
dimensions stay independent under rotation; foreign/invalid requests rejected
with the old facing intact; the Tactical draw rotates the body (BASE visual
dims inside the transform — no double rotation) but keeps text upright
(static pin); the real client tokenAt hit-tests the ORIENTED visual rect
(node).
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
from tests.test_footprint_rect import npc_token, tok_row
from tests.test_movement_fog import base_room, recv_until, state_of, ws_connect

ROOT = pathlib.Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


def _tok(x, y, fw=None, fh=None, rot=None, size="Medium", tok_id=1):
    cell = 50
    return {"id": tok_id, "x": (x + .5) * cell, "y": (y + .5) * cell,
            "size": size, "fw": fw, "fh": fh, "rot": rot}


def _mp(w=20, h=20):
    return {"w": w, "h": h, "cell": 50, "origin": [0, 0]}


def test_clean_rot_normalizes_and_rejects():
    assert footprint.clean_rot(-90) == 270
    assert footprint.clean_rot(450) == 90
    assert footprint.clean_rot(360) == 0
    assert footprint.clean_rot("90") == 90
    assert footprint.clean_rot(45) is None          # only the four cardinals
    assert footprint.clean_rot("abc") is None
    assert footprint.clean_rot(None) is None


def test_rotation_persists_broadcasts_and_survives_reconnect(client):
    dm, player, code, _ = base_room(client)
    st0 = state_of(client, player, code)
    mine = next(t["id"] for t in st0["tokens"] if t["owner_user_id"] == st0["me"])
    row0 = tok_row(mine)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "token_rotate", "token_id": mine, "degrees": 90})
        assert recv_until(ws, "token_rot")["payload"]["rot"] == 90
    row1 = tok_row(mine)
    assert row1["rot"] == 90
    assert (row1["x"], row1["y"]) == (row0["x"], row0["y"])          # never moved
    assert (row1["fw"], row1["fh"]) == (row0["fw"], row0["fh"])      # never resized
    tok = next(t for t in state_of(client, player, code)["tokens"] if t["id"] == mine)
    assert tok["rot"] == 90                                          # fresh snapshot


def test_rotation_normalization_is_server_side(client):
    dm, player, code, _ = base_room(client)
    with ws_connect(client, dm, code) as ws:
        npc = npc_token(client, dm, code, ws, "Weathervane", 12, 12)
        ws.send_json({"type": "token_rotate", "token_id": npc, "degrees": -90})
        assert recv_until(ws, "token_rot")["payload"]["rot"] == 270
        ws.send_json({"type": "token_rotate", "token_id": npc, "degrees": 45})
        err = recv_until(ws, "error", fail_on_error=False)
        assert "0, 90, 180 or 270" in err["payload"]["msg"]
        assert tok_row(npc)["rot"] == 270                            # invalid kept old


def test_rotation_orients_the_mechanical_footprint(client):
    """D83: the entity turns — a 2x4 base facing 90 OCCUPIES a 4x2, stored
    fw/fh stay the base 2x4, and the doubled centre is preserved exactly."""
    dm, player, code, _ = base_room(client)
    with ws_connect(client, dm, code) as ws:
        npc = npc_token(client, dm, code, ws, "Grinder", 10, 10, width=2, height=4)
        mp = state_of(client, dm, code)["grid"]
        row = tok_row(npc)
        old_ox, old_oy = footprint.occupied_origin(mp, row)[0]
        ws.send_json({"type": "token_rotate", "token_id": npc, "degrees": 90})
        recv_until(ws, "token_rot")
    row = tok_row(npc)
    assert (row["fw"], row["fh"]) == (2, 4)                 # base shape unchanged
    assert footprint.token_span(row) == (4, 2)              # EFFECTIVE is turned
    new_ox, new_oy = footprint.occupied_origin(mp, row)[0]
    assert (new_ox, new_oy) == (9, 11)                      # anchor_for_center
    assert 2 * new_ox + 4 == 2 * old_ox + 2                 # x-centre preserved
    assert 2 * new_oy + 2 == 2 * old_oy + 4                 # y-centre preserved
    assert footprint.occupied_cells(mp, row) == {(x, y) for x in range(9, 13)
                                                 for y in range(11, 13)}
    assert (row["x"], row["y"]) == ((9 + .5) * mp["cell"], (11 + .5) * mp["cell"])


def test_rotation_roundtrip_returns_to_the_exact_original(client):
    """90 then 180 back: the deterministic floor re-anchor walks the entity
    exactly home — no creep."""
    dm, player, code, _ = base_room(client)
    with ws_connect(client, dm, code) as ws:
        npc = npc_token(client, dm, code, ws, "Mangler", 10, 10, width=2, height=4)
        home = (tok_row(npc)["rot"] or 0, tok_row(npc)["x"], tok_row(npc)["y"])
        ws.send_json({"type": "token_rotate", "token_id": npc, "degrees": 90})
        recv_until(ws, "token_rot")
        mid = (tok_row(npc)["x"], tok_row(npc)["y"])
        ws.send_json({"type": "token_rotate", "token_id": npc, "degrees": 180})
        recv_until(ws, "token_rot")
    row = tok_row(npc)
    assert mid != (home[1], home[2])                        # it DID move (re-centre)
    assert (row["x"], row["y"]) == (home[1], home[2])       # and came home exactly


def test_anchor_for_center_is_deterministic_and_parity_documented():
    ac = footprint.anchor_for_center
    assert ac((10, 10), (2, 4), (4, 2)) == (9, 11)          # both even: centre exact
    assert ac((10, 10), (3, 7), (7, 3)) == (8, 12)          # both odd: centre exact
    assert ac((10, 10), (3, 3), (3, 3)) == (10, 10)         # no-op
    assert ac((10, 10), (1, 1), (3, 3)) == (9, 9)           # grow around centre
    assert ac((10, 10), (1, 2), (2, 1)) == (9, 10)          # mixed parity: floor
    assert abs((2 * 9 + 2) - (2 * 10 + 1)) <= 1            # centre shift <= half a cell


def test_rotation_into_obstruction_is_rejected_wholly(client):
    """A 2x4 flat against the world edge cannot turn upright sideways: the
    oriented box would leave the map — rot, x/y and occupancy untouched."""
    dm, player, code, _ = base_room(client)
    st = state_of(client, dm, code)
    with ws_connect(client, dm, code) as ws:
        npc = npc_token(client, dm, code, ws, "Wedge", 0, 0, width=4, height=2)
        mp = state_of(client, dm, code)["grid"]
        before = tok_row(npc)
        ws.send_json({"type": "token_rotate", "token_id": npc, "degrees": 90})
        err = recv_until(ws, "error", fail_on_error=False)
        assert "No room to turn" in err["payload"]["msg"]
    after = tok_row(npc)
    assert (after["rot"] or 0) == (before["rot"] or 0)
    assert (after["x"], after["y"]) == (before["x"], before["y"])
    assert footprint.occupied_cells(mp, after) == footprint.occupied_cells(mp, before)


def test_rotation_into_another_token_is_rejected(client):
    dm, player, code, _ = base_room(client)
    with ws_connect(client, dm, code) as ws:
        wide = npc_token(client, dm, code, ws, "Wide", 8, 10, width=4, height=2)
        npc_token(client, dm, code, ws, "Blocker", 10, 12, width=1, height=1)
        ws.send_json({"type": "token_rotate", "token_id": wide, "degrees": 90})
        err = recv_until(ws, "error", fail_on_error=False)
        assert "No room to turn" in err["payload"]["msg"]
    assert (tok_row(wide)["rot"] or 0) == 0


def test_visual_and_mechanical_stay_independent_under_rotation():
    tok = _tok(4, 6, fw=2, fh=2, rot=90, size="Medium")
    tok.update({"vw": 3, "vh": 7})
    assert footprint.token_span(tok) == (2, 2)              # mech: square turns into itself
    assert footprint.visual_span(tok) == (7, 3)             # visual: 3x7 turned 90
    big = dict(tok, fw=2, fh=4)
    assert footprint.token_span(big) == (4, 2)
    assert footprint.visual_span(big) == (7, 3)             # independence pin


def test_foreign_rotation_refused(client):
    dm, player, code, _ = base_room(client)
    with ws_connect(client, dm, code) as ws:
        npc = npc_token(client, dm, code, ws, "Statue", 14, 10)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "token_rotate", "token_id": npc, "degrees": 180})
        err = recv_until(ws, "error", fail_on_error=False)
        assert "your token" in err["payload"]["msg"].lower()
    assert tok_row(npc)["rot"] is None


def test_hidden_token_leaks_no_facing(client):
    dm, player, code, _ = base_room(client)
    with ws_connect(client, dm, code) as ws:
        npc = npc_token(client, dm, code, ws, "Dragon", 10, 8)   # inside LOS
        ws.send_json({"type": "token_rotate", "token_id": npc, "degrees": 90})
        recv_until(ws, "token_rot")
    tok = next(t for t in state_of(client, player, code)["tokens"] if t["id"] == npc)
    assert "rot" not in tok
    dtok = next(t for t in state_of(client, dm, code)["tokens"] if t["id"] == npc)
    assert dtok["rot"] == 90


def test_tactical_rotates_body_but_not_text():
    """Static pin: the draw loop enters a rotate transform for the body/rings
    and RESTORES it before the upright label/bar text (mirrors 15B-style
    loop-scope pins)."""
    src = (ROOT / "app/static/js/50_canvas.js").read_text()
    loop = src[src.index("for (const t of state.tokens){"):src.index("function evtPos")]
    rot_at = loop.index("ctx.rotate(")
    restore_at = loop.index("ctx.restore()", rot_at)
    label_at = loop.index("ctx.fillText(t.label,")
    assert restore_at < label_at                  # text drawn OUTSIDE the transform
    assert "rotDeg" in loop and "const rotDeg = (((t.rot | 0) % 360) + 360) % 360" in loop
    assert "const [sw, sh]" not in loop           # hit-testing lives in tokenAt only
    assert "baseVisualSpan(t)" in loop            # D83: transform-space uses BASE dims
    assert "visualSpan(" not in loop              # (oriented dims there = double rotation)
    at = src[src.index("function tokenAt"):src.index("function ownToken")]
    assert "const [sw, sh] = visualSpan(t);" in at    # D83: orientation lives in visualSpan
    assert "rotDeg" not in at


@pytest.mark.skipif(NODE is None, reason="node not available")
def test_hittest_follows_the_rotated_artwork():
    core = (ROOT / "app/static/js/10_core.js").read_text()
    canvas = (ROOT / "app/static/js/50_canvas.js").read_text()
    vis = core[core.index("const SIZE_FOOTPRINT"):core.index("\n}", core.index("function visualSpan")) + 2]
    hit = canvas[canvas.index("function tokenAt"):canvas.index("function ownToken")]
    c = 50
    tok = {"id": 7, "x": 12.5 * c, "y": 12.5 * c, "size": "Medium",
           "fw": None, "fh": None, "vw": 3, "vh": 7, "rot": 90}
    points = [[12.5 * c + 3.4 * c, 12.5 * c],     # now sideways: artwork reaches X
              [12.5 * c, 12.5 * c + 3.4 * c]]     # no longer reaches this far down
    script = f"""
      function cellSize(){{ return 50; }}
      const state = {{ tokens: {json.dumps([tok])} }};
      {vis}
      {hit}
      const out = {json.dumps(points)}.map(([x, y]) => {{ const t = tokenAt(x, y); return t ? t.id : null; }});
      console.log(JSON.stringify(out));
    """
    r = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == [7, None]
