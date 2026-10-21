"""D104 — light management (lamp channel) and the secure DM player-view preview.

Both features sit on the ONE existing light/visibility model (D87 darkness,
D89 lamps, per-viewer LOS gating): the new `lamp` message is a management
surface over the SAME objects list with the SAME canon, and `view_as` runs the
SAME `_viewer_token_view` the character's own /state runs. What these tests
pin: the radius and wall semantics come from the engine (no re-implementation
here), management is DM-only and plane-local, and the preview is the
character's real sight — read-only, leak-free, and byte-identical to what the
player themselves receive.
"""
import json

import pytest
from starlette.testclient import TestClient

from app import db, main
from tests.test_lighting2 import add_named, make_dark
from tests.test_movement_fog import (H, base_room, make_char, recv_until,
                                     reg, set_grid, state_of, wall_column,
                                     ws_connect)


@pytest.fixture()
def client():
    return TestClient(main.app)


def room_id(code):
    return db.q1("SELECT id FROM rooms WHERE id=(SELECT id FROM rooms WHERE code=?)",
                 (code.upper(),))["id"]


def primary_json(code) -> dict:
    return json.loads(db.q1("SELECT map_json FROM room_state WHERE room_id=?",
                            (room_id(code),))["map_json"])


def cell_idx(g, x, y):
    ox, oy = g.get("origin") or [0, 0]
    return (y - oy) * g["w"] + (x - ox)


def pc_token(code, ch):
    return db.q1("SELECT * FROM tokens WHERE room_id=? AND character_id=?",
                 (room_id(code), ch["id"]))


def add_floor(client, dm, code, name, ground=True):
    assert client.post(f"/api/rooms/{code}/floors", json={"name": name},
                       headers=H(dm)).status_code == 200
    # D159: a named plane is open AIR by default; a lamp-bearing plane the DM
    # stands a token on is authored as a real floor first.
    if ground:
        grid = client.get(f"/api/rooms/{code}/state?floor={name}",
                          headers=H(dm)).json()["grid"]
        grid["cells"] = [0] * len(grid["cells"])
        with ws_connect(client, dm, code) as ws:
            ws.send_json({"type": "map_edit", "map": grid, "floor": name})
            recv_until(ws, "map_changed")


def view_as(client, actor, code, cid):
    return client.get(f"/api/rooms/{code}/view_as/{cid}", headers=H(actor))


def lamps_of(g):
    return [o for o in (g.get("objects") or [])
            if ((o.get("interact") or {}).get("op") or {}).get("kind") == "lamp"]


def lamp(wsd, action, floor="", **kw):
    wsd.send_json({"type": "lamp", "action": action, "floor": floor, **kw})
    ev = recv_until(wsd, "lamp_ok")
    return ev["payload"]["id"]


def nonnull_mask(g):
    return [c is not None for c in g["cells"]]


# ---------- A: the lamp management channel drives the ONE light engine ----------

def test_lamp_manager_roundtrip_radius_and_off(client):
    dm, player, code, ch = base_room(client)
    make_dark(client, dm, code)                       # darkness: sight = light only
    with ws_connect(client, dm, code) as wsd:
        lid = lamp(wsd, "add", x=12, y=6, bright=5, label="Brazier")
    g = state_of(client, dm, code)["grid"]
    lm = next((o for o in lamps_of(g) if o["id"] == lid), None)
    assert lm and lm["label"] == "Brazier" and lm["interact"]["op"]["bright"] == 5
    p = state_of(client, player, code)
    assert p["grid"]["cells"][cell_idx(p["grid"], 15, 6)] is not None, \
        "within the bright radius the plane is visible to everyone on it"
    assert p["grid"]["cells"][cell_idx(p["grid"], 30, 6)] is None, \
        "outside the radius stays dark — light does not flood the map"
    with ws_connect(client, dm, code) as wsd:
        lamp(wsd, "update", id=lid, on=False)         # silent administration
    p = state_of(client, player, code)
    assert p["grid"]["cells"][cell_idx(p["grid"], 15, 6)] is None, \
        "an inactive lamp must not change sight at all"
    with ws_connect(client, dm, code) as wsd:
        lamp(wsd, "update", id=lid, on=True, bright=2, label="Dimple")
    g = state_of(client, dm, code)["grid"]
    lm = next(o for o in lamps_of(g) if o["id"] == lid)
    assert lm["label"] == "Dimple" and lm["interact"]["op"]["bright"] == 2
    assert not lm["interact"]["op"]["bright"] >= 5
    with ws_connect(client, dm, code) as wsd:
        lamp(wsd, "remove", id=lid)
    assert not lamps_of(state_of(client, dm, code)["grid"])


def test_walls_block_lamplight_exactly_like_sight(client):
    dm, player, code, ch = base_room(client)
    make_dark(client, dm, code)
    set_grid(client, dm, code, lambda g: wall_column(g, 10))
    with ws_connect(client, dm, code) as wsd:
        lamp(wsd, "add", x=8, y=13, bright=6)
    p = state_of(client, player, code)                # token still at spawn (8,6)
    assert p["grid"]["cells"][cell_idx(p["grid"], 6, 13)] is not None   # same side
    assert p["grid"]["cells"][cell_idx(p["grid"], 12, 13)] is None, \
        "light must not shine through the wall the sight engine already blocks"
    def unseal(g):
        for y in range(g["h"]):
            g["cells"][y * g["w"] + 10] = 0
    set_grid(client, dm, code, unseal)
    p = state_of(client, player, code)
    assert p["grid"]["cells"][cell_idx(p["grid"], 12, 13)] is not None, \
        "open the column and the SAME cell lights up — the engine, not a copy"


def test_darkness_without_light_keeps_only_memory_and_footstep(client):
    dm, player, code, ch = base_room(client)
    tok = pc_token(code, ch)
    tx, ty = int(tok["x"] // 50), int(tok["y"] // 50)
    pre = state_of(client, player, code)              # light-era explored memory
    known = {i for i, v in enumerate(pre["grid"]["cells"]) if v is not None}
    make_dark(client, dm, code)
    p = state_of(client, player, code)
    lit = {i for i, v in enumerate(p["grid"]["cells"]) if v is not None}
    own = cell_idx(p["grid"], tx, ty)
    assert own in lit, "you always feel the floor you stand on"
    assert lit == known | {own}, \
        "dark adds no new sight and erases no memory (the browser finding, as designed)"


def test_darkvision_remains_effective(client):
    dm, player, code, ch = base_room(client)
    make_dark(client, dm, code)
    tok = pc_token(code, ch)
    with ws_connect(client, dm, code) as wsd:
        wsd.send_json({"type": "token_darkvision", "token_id": tok["id"],
                       "radius": 4})
        recv_until(wsd, "token_darkvision")
    p = state_of(client, player, code)
    tx, ty = int(tok["x"] // 50), int(tok["y"] // 50)
    assert p["grid"]["cells"][cell_idx(p["grid"], tx + 3, ty)] is not None
    assert p["grid"]["cells"][cell_idx(p["grid"], tx + 9, ty)] is None


# ---------- B: plane isolation of the new channel ----------

def test_lamp_lives_and_lights_on_its_own_plane(client):
    dm, player, code, ch = base_room(client)
    add_floor(client, dm, code, "crypt")
    make_dark(client, dm, code)                       # primary goes dark
    before = nonnull_mask(state_of(client, player, code)["grid"])
    with ws_connect(client, dm, code) as wsd:
        lamp(wsd, "add", floor="crypt", x=9, y=7, bright=4)
    g_base = state_of(client, player, code)           # player stands on primary
    assert not lamps_of(g_base["grid"]), "the lamp must not be on the primary map"
    assert nonnull_mask(g_base["grid"]) == before, \
        "the crypt lamp may not light the primary plane"
    tok = pc_token(code, ch)
    with ws_connect(client, dm, code) as wsd:
        wsd.send_json({"type": "token_floor", "token_id": tok["id"], "floor": "crypt"})
        recv_until(wsd, "token_floor")
    p = state_of(client, player, code)                # player follows to the crypt
    assert p["view_floor"] == "crypt"
    assert p["grid"]["cells"][cell_idx(p["grid"], 10, 7)] is not None, \
        "the crypt lamp lights the crypt for the character standing on it"


# ---------- C: authority over the channel ----------

def test_players_cannot_manage_lamps(client):
    dm, player, code, _ = base_room(client)
    with ws_connect(client, player, code) as wsp:
        wsp.send_json({"type": "lamp", "action": "add", "floor": "", "x": 9, "y": 6})
        assert "DM only" in recv_until(wsp, "error")["payload"]["msg"]
    assert not lamps_of(state_of(client, dm, code)["grid"])   # refused = saved nothing
    with ws_connect(client, player, code) as wsp:
        wsp.send_json({"type": "lamp", "action": "remove", "floor": "", "id": "x"})
        assert "DM only" in recv_until(wsp, "error")["payload"]["msg"]


# ---------- D: view_as IS the character's server-side sight ----------

def test_view_as_equals_the_players_own_state(client):
    dm, player, code, ch = base_room(client)
    make_dark(client, dm, code)
    with ws_connect(client, dm, code) as wsd:
        lid = lamp(wsd, "add", x=12, y=6, bright=6)   # noqa: F841 (light, not id)
        npc = add_named(wsd, "Glowguard", 14, 6)
    mine = state_of(client, player, code)
    r = view_as(client, dm, code, ch["id"])
    assert r.status_code == 200, r.text
    pv = r.json()
    assert pv["view_floor"] == mine["view_floor"]
    assert nonnull_mask(pv["grid"]) == nonnull_mask(mine["grid"])
    assert {t["id"] for t in pv["tokens"]} == {t["id"] for t in mine["tokens"]}
    assert npc in {t["id"] for t in pv["tokens"]}, "what the light reveals, the preview reveals"
    assert {g["id"] for g in pv["ghosts"]} == {g["id"] for g in mine["ghosts"]}


def test_view_as_leaks_nothing_the_player_cannot_see(client):
    dm, player, code, ch = base_room(client)
    make_dark(client, dm, code)
    with ws_connect(client, dm, code) as wsd:
        far_npc = add_named(wsd, "Stalker", 30, 20)   # deep in the dark
    grid = state_of(client, dm, code)["grid"]
    grid["traps"] = [{"id": "t1", "x": 12, "y": 8, "label": "Plate",
                      "dc": 12, "dmg": "1d4", "discovered": False}]
    grid["objects"] = (grid.get("objects") or []) + [
        {"id": "dmsecret", "label": "Hidden Altar", "x": 11, "y": 8,
         "dm_only": True, "interact": {"label": "Pray", "op": {"kind": "toggle"}}}]
    grid["doors"] = [{"id": "sd", "x": 3, "y": 4, "dir": "v", "secret": True}]
    with ws_connect(client, dm, code) as wsd:
        wsd.send_json({"type": "map_edit", "map": grid})
        recv_until(wsd, "map_changed")
    pv = view_as(client, dm, code, ch["id"]).json()
    assert far_npc not in {t["id"] for t in pv["tokens"]}
    assert all(t["id"] != "t1" for t in pv["grid"]["traps"]), "undiscovered traps stay hidden"
    assert all(o["id"] != "dmsecret" for o in pv["grid"]["objects"])
    assert all(d["id"] != "sd" for d in pv["grid"]["doors"]), "secret doors stay secret"
    assert pv["dark"] is True
    # delivered lamp objects are the PLAYER furniture copy — op payload never travels
    for o in pv["grid"]["objects"]:
        if (o.get("interact") or {}).get("kind") == "lamp":
            assert "op" not in o["interact"]


def test_view_as_changes_nothing_for_anyone(client):
    dm, player, code, ch = base_room(client)
    make_dark(client, dm, code)
    with ws_connect(client, dm, code) as wsd:
        lamp(wsd, "add", x=12, y=6, bright=6)
    before_explored = primary_json(code)["explored"]
    mine_before = state_of(client, player, code)
    for _ in range(3):
        assert view_as(client, dm, code, ch["id"]).status_code == 200
    assert primary_json(code)["explored"] == before_explored, \
        "a preview must never mark anything explored"
    mine_after = state_of(client, player, code)
    assert nonnull_mask(mine_after["grid"]) == nonnull_mask(mine_before["grid"])
    assert {t["id"] for t in mine_after["tokens"]} == {t["id"] for t in mine_before["tokens"]}
    raw = db.q1("SELECT map_json FROM room_state WHERE room_id=?",
                (room_id(code),))["map_json"]
    assert json.loads(raw)["explored"] == before_explored   # raw DB truth untouched


def test_view_as_authorization_channel_is_dm_only_and_exact(client):
    dm, player, code, ch = base_room(client)
    assert view_as(client, player, code, ch["id"]).status_code == 404, \
        "a player cannot open the peek channel at all — not even their own"
    assert view_as(client, dm, code, 999999).status_code == 404
    outsider = reg(client, "out")
    assert view_as(client, outsider, code, ch["id"]).status_code == 403, \
        "non-members hit the classic room-membership gate (403, like /state)"
    other_dm, _p2, code2, _ch2 = base_room(client)      # a DIFFERENT room's DM
    assert view_as(client, other_dm, code, ch["id"]).status_code == 403, \
        "no cross-room peeking"
    # a character WITHOUT a token in this room answers like nothing being here
    stranger_ch = make_char(client, player)             # never assigned to the room
    assert view_as(client, dm, code, stranger_ch["id"]).status_code == 404


def test_reconnect_reveals_by_the_lit_plane_truth(client):
    dm, player, code, ch = base_room(client)
    make_dark(client, dm, code)
    with ws_connect(client, dm, code) as wsd:
        lamp(wsd, "add", x=20, y=6, bright=6)           # beyond the light-era memory
        npc = add_named(wsd, "Sentry", 23, 6)
    with ws_connect(client, player, code) as wsp:       # fresh connect = reveal
        recv_until(wsp, "explored")
    p = state_of(client, player, code)
    assert npc in {t["id"] for t in p["tokens"]}, \
        "reconnect reveals exactly what the LIGHT reveals — no more, no less"
    assert p["grid"]["explored"][cell_idx(p["grid"], 21, 6)] == 1, \
        "the lit cells beside the lamp become known at connect"
    assert p["grid"]["cells"][cell_idx(p["grid"], 17, 6)] is not None
    assert p["grid"]["cells"][cell_idx(p["grid"], 30, 6)] is None, \
        "beyond the glow nothing is revealed or remembered"
    assert any((o.get("interact") or {}).get("kind") == "lamp"
               for o in p["grid"]["objects"]), "the lamp itself is visible furniture"


def test_old_rooms_keep_the_classic_sight_and_peek_works_them(client):
    dm, player, code, ch = base_room(client)            # never dark, no lamps
    tok = pc_token(code, ch)
    tx, ty = int(tok["x"] // 50), int(tok["y"] // 50)
    p = state_of(client, player, code)
    assert p["grid"]["cells"][cell_idx(p["grid"], tx + 5, ty)] is not None
    assert p["grid"]["cells"][cell_idx(p["grid"], tx + 12, ty)] is None, \
        "the classic FOG_R=6 personal sight is untouched by D104"
    pv = view_as(client, dm, code, ch["id"]).json()
    assert nonnull_mask(pv["grid"]) == nonnull_mask(p["grid"])


def test_panel_toggled_off_state_survives_a_later_map_edit(client):
    # the D102/D82 state-merge precedent, now for the management channel:
    # a stale editor snapshot must not relight a lamp the DM just put out
    dm, player, code, ch = base_room(client)
    with ws_connect(client, dm, code) as wsd:
        lid = lamp(wsd, "add", x=10, y=10, bright=4)
        lamp(wsd, "update", id=lid, on=False)
    g = state_of(client, dm, code)["grid"]
    g["cells"][0] = 1                                    # a plain terrain edit
    with ws_connect(client, dm, code) as wsd:
        wsd.send_json({"type": "map_edit", "map": g})
        recv_until(wsd, "map_changed")
    lm = next(o for o in lamps_of(state_of(client, dm, code)["grid"]) if o["id"] == lid)
    assert lm["state"] == {"on": False}, "the edit resurrected the light"


# ---------- E: the client contract (source pins, no browser runner) ----------

def test_client_preview_wiring_is_not_cosmetic():
    def src(*parts):
        import os
        with open(os.path.join(main.STATIC_DIR, *parts), encoding="utf-8") as f:
            return f.read()
    canvas = src("js", "50_canvas.js")
    # the renderer must read the PREVIEW data, and input must be dead while it shows
    assert "function viewG()" in canvas and "function viewTokens()" in canvas \
        and "function viewGhosts()" in canvas
    assert "state.preview ? state.preview.grid" in canvas
    assert 'toast("Preview is view-only — exit it to interact")' in canvas
    assert "!state.preview && !onPlane(t)" in canvas      # no wrong-plane filter on previews
    assert "if (state.viewMode === \"diorama\" && !state.editing && !state.preview)" in canvas
    assert "Preview is tactical-view only" in src("js", "10_core.js")
    room = src("js", "30_room.js")
    assert "/view_as/" in room                              # real server endpoint, not local math
    assert "state.preview = p" in room and "renderPreviewBar" in room
    assert "wsSend({type:\"lamp\"" in room                  # management goes through the server
    html = src("index.html")
    assert 'id="previewbar"' in html and 'id="lightpanel"' in html and 'id="peekpanel"' in html
    assert 'id="lightpanel" data-tab="dm"' in html and 'id="peekpanel" data-tab="dm"' in html, \
        "the panels are DM-tab panels — players never receive the management surface"

