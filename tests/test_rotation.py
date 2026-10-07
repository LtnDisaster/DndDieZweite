"""D82: token rotation is a VISUAL facing — persisted, broadcast, never the
mechanical footprint.

Pins: 0/90/180/270 normalization server-side; persistence + reconnect; a 2x4
does NOT silently become 4x2 when the artwork turns; foreign/invalid requests
rejected with the old facing intact; the Tactical draw applies ctx.rotate to
the body but keeps text upright (static pin); and the real client tokenAt
swaps the visual hit rect on 90/270 (node).
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


def test_rotation_never_rotates_the_mechanical_footprint(client):
    """The explicit promise: a 2x4 collision rect stays 2x4 at the same cells
    while the artwork is facing 90 degrees."""
    dm, player, code, _ = base_room(client)
    with ws_connect(client, dm, code) as ws:
        npc = npc_token(client, dm, code, ws, "Grinder", 10, 10, width=2, height=4)
        mp = state_of(client, dm, code)["grid"]
        before = footprint.occupied_cells(mp, tok_row(npc))
        ws.send_json({"type": "token_rotate", "token_id": npc, "degrees": 90})
        recv_until(ws, "token_rot")
    row = tok_row(npc)
    assert (row["fw"], row["fh"]) == (2, 4)                 # NOT swapped to 4x2
    assert footprint.occupied_cells(mp, row) == before
    assert footprint.token_span(row) == (2, 4)


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
    assert "const [sw, sh]" not in loop           # rotation swap lives in tokenAt only
    at = src[src.index("function tokenAt"):src.index("function ownToken")]
    assert "rotDeg % 180 === 90 ? [vh, vw] : [vw, vh]" in at


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
