"""D85 — secure PNG token artwork: adversarial upload, authz, assignment.

Threat-model checks, fail-closed:
  * non-PNG and disguised content refused (MIME/filename are lies);
  * oversized body, oversized dimensions, truncated files refused;
  * metadata from the ORIGINAL file must not survive the re-encode;
  * a private asset is 404 for strangers (no existence oracle);
  * serving becomes allowed exactly when the asset rides a token in a room
    the requester belongs to;
  * the display name is never a path; ids are opaque and unguessable;
  * token_image stores only the server-canonical form; players attach only
    their own assets; hidden NPC tokens leak no artwork.
"""
import io
import re
import uuid

import pytest
from PIL import Image, PngImagePlugin
from starlette.testclient import TestClient

from app import db, main
from tests.test_movement_fog import (H, add_npc, base_room, recv_until,
                                     reg, room_with_wall, state_of, ws_connect)


@pytest.fixture()
def client():
    return TestClient(main.app)


def _png(w=48, h=64, pnginfo=None):
    b = io.BytesIO()
    Image.new("RGBA", (w, h), (200, 30, 30, 255)).save(b, "PNG", pnginfo=pnginfo)
    return b.getvalue()


def _put(client, user, blob, name="token", **kw):
    return client.put(f"/api/assets?name={name}", content=blob, headers=H(user), **kw)


# ---------- ingest gate ----------

def test_only_real_png_accepted(client):
    u = reg(client, "au")
    assert _put(client, u, b"GIF89a<h1>hi</h1>").status_code == 415
    assert _put(client, u, b"<html><script>alert(1)</script></html>").status_code == 415
    assert _put(client, u, b"\x89PNG\r\n\x1a\n" + b"junk" * 64).status_code == 415
    g = io.BytesIO(); Image.new("RGB", (8, 8)).save(g, "GIF")     # real GIF payload
    assert _put(client, u, g.getvalue()).status_code == 415
    assert _put(client, u, b"").status_code == 413
    r = _put(client, u, _png(48, 64), "ok")
    assert r.status_code == 200 and re.fullmatch(r"[0-9a-f]{16}", r.json()["id"])


def test_oversize_and_bomb_dims_refused(client):
    u = reg(client, "az")
    assert _put(client, u, b"\x89PNG\r\n\x1a\n" + b"x" * 1_600_000).status_code == 413
    assert _put(client, u, _png(4200, 1)).status_code == 413      # per-axis cap
    assert _put(client, u, _png(3000, 1500)).status_code == 413   # pixel-count cap


def test_truncated_png_refused(client):
    u = reg(client, "tr")
    good = _png(60, 60)
    assert _put(client, u, good[:len(good) // 2]).status_code == 415


def test_metadata_never_survives_reencode(client):
    u = reg(client, "me")
    meta = PngImagePlugin.PngInfo()
    meta.add_text("Comment", "LEAKME-marker" + "A" * 2000)
    aid = _put(client, u, _png(10, 10, meta), "meta").json()["id"]
    served = client.get(f"/api/assets/{aid}", headers=H(u))
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/png"
    assert served.headers["x-content-type-options"] == "nosniff"
    assert b"LEAKME" not in served.content
    assert Image.open(io.BytesIO(served.content)).size == (10, 10)


def test_dedupes_per_user(client):
    a, b = reg(client, "da"), reg(client, "db")
    blob = _png(9, 9)
    a1 = _put(client, a, blob, "same").json()["id"]
    a2 = _put(client, a, blob, "same").json()["id"]
    b1 = _put(client, b, blob, "same").json()["id"]
    assert a1 == a2 and b1 != a1                                  # rows per user


# ---------- authz / oracle ----------

def test_stranger_gets_404_not_403(client):
    owner, stranger = reg(client, "oa"), reg(client, "os")
    aid = _put(client, owner, _png(8, 8), "x").json()["id"]
    assert client.get(f"/api/assets/{aid}", headers=H(stranger)).status_code == 404
    assert client.get("/api/assets/..%2f..%2fdb", headers=H(stranger)).status_code == 404
    assert aid not in client.get("/api/assets", headers=H(stranger)).text
    assert aid in client.get("/api/assets", headers=H(owner)).text   # own: visible


def test_room_access_follows_the_token(client):
    """SPRINT-19 RE-SCOPED: serving follows what a viewer LEGITIMATELY SEES,
    not mere room membership. NPC artwork is stripped from player channels, so
    a plain room member gets the uniform 404 — the room was never a read grant
    for hidden or NPC art. Operators and the DM of a riding room keep access."""
    dm, player, code, _ = base_room(client)
    stranger = reg(client, "st")
    aid = _put(client, dm, _png(12, 12), "dmart").json()["id"]
    assert client.get(f"/api/assets/{aid}", headers=H(stranger)).status_code == 404
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "add_token", "label": "Guard", "x": 2.5 * 50, "y": 2.5 * 50})
        tok = recv_until(ws, "token_add")["payload"]["id"]
        ws.send_json({"type": "token_image", "token_id": tok, "asset_id": aid})
        assert recv_until(ws, "token_image")["payload"]["image"] == f"/assets/{aid}"
        assert db.q1("SELECT image FROM tokens WHERE id=?", (tok,))["image"] == f"/assets/{aid}"
        assert client.get(f"/api/assets/{aid}", headers=H(stranger)).status_code == 404
        # A plain room member may NOT read NPC artwork (the WS add strips it —
        # REST must not hand back what the game deliberately withholds).
        assert client.get(f"/api/assets/{aid}", headers=H(player)).status_code == 404
        # The DM reads art riding in their room.
        assert client.get(f"/api/assets/{aid}", headers=H(dm)).status_code == 200
        # Making the player the token's OPERATOR grants the read (and the live
        # token_add carries the image for them).
        pid = db.q1("SELECT id FROM users WHERE username=?", (player["name"],))["id"]
        ws.send_json({"type": "token_controller", "token_id": tok, "user_id": pid})
        assert recv_until(ws, "token_controller")["payload"]["controller_user_id"] == pid
        assert client.get(f"/api/assets/{aid}", headers=H(player)).status_code == 200
        assert client.delete(f"/api/assets/{aid}", headers=H(dm)).status_code == 409
        ws.send_json({"type": "token_image", "token_id": tok, "asset_id": None})
        recv_until(ws, "token_image")
    assert client.delete(f"/api/assets/{aid}", headers=H(dm)).status_code == 200


def test_name_is_display_only_never_a_path(client):
    u = reg(client, "np")
    nasty = "../../../../etc/passwd‮\x07"
    aid = client.put("/api/assets", content=_png(6, 6),
                     params={"name": nasty}, headers=H(u)).json()["id"]
    row = db.q1("SELECT * FROM assets WHERE id=?", (aid,))
    assert "/" not in row["file"] and ".." not in row["file"] and row["file"].endswith(".png")
    assert "\x07" not in row["name"] and "‮" not in row["name"]


# ---------- assignment (WS) ----------

def test_player_may_only_attach_own_asset(client):
    dm, player, code, _ = base_room(client)
    dm_art = _put(client, dm, _png(7, 7), "dm").json()["id"]
    pl_art = _put(client, player, _png(7, 8), "pl").json()["id"]
    mine = [t for t in state_of(client, player, code)["tokens"]
            if t.get("owner_user_id") is not None][0]["id"]
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "token_image", "token_id": mine, "asset_id": dm_art})
        assert recv_until(ws, "error", fail_on_error=False)["kind"] == "error"
        ws.send_json({"type": "token_image", "token_id": mine, "asset_id": "decafbaddeadbeef"})
        assert recv_until(ws, "error", fail_on_error=False)["kind"] == "error"
        ws.send_json({"type": "token_image", "token_id": mine,
                      "asset_id": "https://evil.test/x.png"})
        assert recv_until(ws, "error", fail_on_error=False)["kind"] == "error"
        ws.send_json({"type": "token_image", "token_id": mine, "asset_id": pl_art})
        assert recv_until(ws, "token_image")["payload"]["image"] == f"/assets/{pl_art}"
    st = client.get(f"/api/rooms/{code}/state", headers=H(player)).json()
    row = [t for t in st["tokens"] if t["id"] == mine][0]
    assert row["image"] == f"/assets/{pl_art}"


def test_hidden_npc_token_leaks_no_artwork(client):
    dm, player, code, ch = room_with_wall(client, wall_x=10)
    art = _put(client, dm, _png(9, 9), "dragon").json()["id"]
    with ws_connect(client, dm, code) as ws:
        hid = add_npc(ws, label="Hidden", cx=15, cy=13)     # behind the wall column
        ws.send_json({"type": "token_image", "token_id": hid, "asset_id": art})
        assert recv_until(ws, "token_image")["payload"]["image"] == f"/assets/{art}"
    st = client.get(f"/api/rooms/{code}/state", headers=H(player)).json()
    row = [t for t in st["tokens"] if t["id"] == hid]
    assert not row or row[0].get("image") in (None, "")
