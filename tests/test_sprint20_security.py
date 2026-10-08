"""Sprint 20 P1 — cross-floor AoE/ping correctness + adversarial security.

Every test exercises the REAL dispatch/serialization/delivery path (WS
handlers, REST, broadcasts) — not isolated helpers. Families:

  A  ability resolution is bound to the caster's plane (closes D88's note):
     area damage excludes other planes outright, cross-plane single targets
     are indistinguishable from unknown ids, and condition bumps for hidden
     tokens never ride the room-wide channel.
  B  aoe templates and pings are plane-scoped events (claim gating + delivery).
  C  property/asset/floor/mount/lamp/state sweeps around the same seams.

Drain semantics follow test_sprint19_audit: a DM chat is the deterministic
flush barrier — a forbidden kind inside the drained window IS the failure.
"""
import json
import shutil

import pytest
from starlette.testclient import TestClient

from app import abilities, db
from app.main import app
from tests.test_assets import _png, _put
from tests.test_movement_fog import (H, add_npc, base_room, join_room,
                                     recv_until, reg, room_with_wall,
                                     state_of, ws_connect)
from tests.test_sprint19_audit import add_named
from tests.test_lighting2 import add_lamp

CELL = 50

DEFS = [
    {"id": "s20_burst", "name": "Sprint Burst", "ability": "int", "range_ft": 60,
     "targeting": "area", "shape": "circle", "size_ft": 5,
     "resolution": "save", "save": "dex", "on_save": "half",
     "damage": "3d6", "damage_type": "fire"},
    {"id": "s20_lance", "name": "Sprint Lance", "ability": "int", "range_ft": 120,
     "targeting": "single", "resolution": "save", "save": "dex", "on_save": "none",
     "damage": "1d6", "damage_type": "force"},
    {"id": "s20_snare", "name": "Sprint Snare", "ability": "wis", "range_ft": 120,
     "targeting": "area", "shape": "circle", "size_ft": 5,
     "resolution": "auto", "condition": {"key": "restrained", "rounds": 1},
     "los_required": False},
]


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _registry():
    for d in DEFS:
        assert abilities.register(d) is not None
    yield


def _room_of(code):
    return db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]


def _add_floor(client, dm, code, name):
    assert client.post(f"/api/rooms/{code}/floors", json={"name": name},
                       headers=H(dm)).status_code == 200


def _pc_token(code, ch):
    return db.q1("SELECT * FROM tokens WHERE room_id=? AND character_id=?",
                 (_room_of(code), ch["id"]))


def _teleport(wsd, tok_id, tx, ty):
    wsd.send_json({"type": "move", "token_id": tok_id, "tx": tx, "ty": ty,
                   "teleport": True})
    recv_until(wsd, "step")


def _npc_hp(tok_id):
    row = db.q1("SELECT npc FROM tokens WHERE id=?", (tok_id,))
    return db.j(row["npc"], {}).get("hp")


def _set_npc_hp(tok_id, hp):
    row = db.q1("SELECT npc FROM tokens WHERE id=?", (tok_id,))
    block = db.j(row["npc"], {}) or {}
    block["hp"] = block["max_hp"] = hp        # the reducer clamps hp to max_hp
    db.x("UPDATE tokens SET npc=? WHERE id=?", (db.json_dumps(block), tok_id))


def _grant(ch, *ids):
    db.x("UPDATE characters SET abilities=? WHERE id=?",
         (db.json_dumps(list(ids)), ch["id"]))


def fake_rolls(monkeypatch, script):
    """Deterministic do_roll: expression → queued totals (empty queue = loud)."""
    from app.room import dice as RD
    queues = {k: list(v) for k, v in script.items()}

    def fake(expr, adv=None):
        v = queues[expr].pop(0)
        return {"expr": expr, "rolls": [v], "kept": v, "mod": 0, "total": v, "adv": None}
    monkeypatch.setattr(RD, "do_roll", fake)


def _drain(ws, kind, tries=80):
    evs = []
    for _ in range(tries):
        ev = ws.receive_json()
        evs.append(ev)
        if (ev.get("kind") or ev.get("type")) == kind:
            return evs
    return evs


def _kinds(evs):
    return {(e.get("kind") or e.get("type")) for e in evs}


# ---------- A — ability resolution bound to the caster's plane ----------

def test_area_damage_resolves_on_the_casters_plane_only(client, monkeypatch):
    dm, player, code, ch = base_room(client)
    _add_floor(client, dm, code, "crypt")
    with ws_connect(client, dm, code) as wsd:
        upper = add_npc(wsd, label="UpperPatrol", cx=14, cy=14)      # primary
        below = add_npc(wsd, label="CryptPatrol", cx=14, cy=14)      # primary …
        wsd.send_json({"type": "token_floor", "token_id": below, "floor": "crypt"})
        recv_until(wsd, "token_floor")                               # … then crypt
        ptok = _pc_token(code, ch)
        _teleport(wsd, ptok["id"], 10, 10)                           # within range
    _set_npc_hp(upper, 20)
    _set_npc_hp(below, 20)
    _grant(ch, "s20_burst")
    fake_rolls(monkeypatch, {"1d20": [1], "3d6": [10]})   # failed save, 10 dmg
    with ws_connect(client, player, code) as wsp:
        wsp.send_json({"type": "ability_cast", "token_id": ptok["id"],
                       "ability_id": "s20_burst", "x": 14, "y": 14})
        r = recv_until(wsp, "ability_result")["payload"]
    assert len(r["entries"]) == 1, "the crypt token is not a candidate at all"
    assert r["entries"][0]["label"] == "UpperPatrol"
    assert r["hidden_count"] == 0, "elsewhere is not hidden — it is ELSEWHERE"
    assert _npc_hp(upper) == 10
    assert _npc_hp(below) == 20, "same coordinates on another plane: untouched"


def test_cross_plane_single_target_is_indistinguishable_from_unknown(client,
                                                                     monkeypatch):
    dm, player, code, ch = base_room(client)
    _add_floor(client, dm, code, "crypt")
    with ws_connect(client, dm, code) as wsd:
        below = add_npc(wsd, label="CryptTarget", cx=14, cy=14)
        wsd.send_json({"type": "token_floor", "token_id": below, "floor": "crypt"})
        recv_until(wsd, "token_floor")
        _teleport(wsd, _pc_token(code, ch)["id"], 10, 10)   # in sight of the cell
    _set_npc_hp(below, 20)
    _grant(ch, "s20_lance")
    fake_rolls(monkeypatch, {"1d20": [1], "1d6": [4]})
    ptok = _pc_token(code, ch)
    with ws_connect(client, player, code) as wsp:
        wsp.send_json({"type": "ability_cast", "token_id": ptok["id"],
                       "ability_id": "s20_lance", "target_id": below})
        ghost = recv_until(wsp, "error", fail_on_error=False)["payload"]["msg"]
        wsp.send_json({"type": "ability_cast", "token_id": ptok["id"],
                       "ability_id": "s20_lance", "target_id": 999999})
        unknown = recv_until(wsp, "error", fail_on_error=False)["payload"]["msg"]
    assert ghost == unknown == "No target token"   # zero oracle for planes
    assert _npc_hp(below) == 20
    # the SAME token resolves the moment it stands on the caster's plane
    with ws_connect(client, dm, code) as wsd:
        wsd.send_json({"type": "token_floor", "token_id": below, "floor": ""})
        recv_until(wsd, "token_floor")
    with ws_connect(client, player, code) as wsp:
        wsp.send_json({"type": "ability_cast", "token_id": ptok["id"],
                       "ability_id": "s20_lance", "target_id": below})
        r = recv_until(wsp, "ability_result")["payload"]
    assert r["entries"] and _npc_hp(below) == 16


def test_condition_bump_for_hidden_token_never_names_it_roomwide(client):
    dm, player, code, ch = room_with_wall(client, wall_x=10)
    with ws_connect(client, dm, code) as wsd:
        hid = add_named(wsd, "Ghost", 15, 13)          # behind the wall: unseen
        ptok = _pc_token(code, ch)
    _grant(ch, "s20_snare")
    with ws_connect(client, player, code) as wsp, \
         ws_connect(client, dm, code) as wsd2:
        wsp.send_json({"type": "ability_cast", "token_id": ptok["id"],
                       "ability_id": "s20_snare", "x": 15, "y": 13})
        r = recv_until(wsp, "ability_result")["payload"]
        # flush from the SAME socket as the cast (one loop = FIFO; a marker
        # from the DM socket could legally overtake the cross-loop cond send)
        wsp.send_json({"type": "chat", "text": "flush-20"})
        seen = _drain(wsp, "chat")
        leaked = [e for e in seen if e.get("kind") == "cond"
                  and (e.get("payload") or {}).get("token_id") == hid]
        assert not leaked, "a hidden token's fresh condition must not " \
                           "broadcast to sockets that cannot see it"
        assert r["hidden_count"] == 1
        dm_seen = _drain(wsd2, "cond", tries=60)   # the DM DOES learn it
        cond = [e for e in dm_seen if e.get("kind") == "cond"
                and e["payload"]["token_id"] == hid]
        assert cond, "the DM keeps full table truth (privileges intact)"


# ---------- B — aoe templates and pings are plane-scoped ----------



def test_aoe_template_delivery_is_plane_scoped(client):
    dm, player, code, ch = base_room(client)
    _add_floor(client, dm, code, "deck")
    observer = reg(client, "obs")
    join_room(client, observer, code)
    with ws_connect(client, dm, code) as wsd:
        ptok = _pc_token(code, ch)
        wsd.send_json({"type": "token_floor", "token_id": ptok["id"], "floor": "deck"})
        recv_until(wsd, "token_floor")
    with ws_connect(client, player, code) as wsp, \
         ws_connect(client, observer, code) as wso, \
         ws_connect(client, dm, code) as wsd:
        wsd.send_json({"type": "aoe", "shape": "circle", "x": 5, "y": 6,
                       "size": 3, "floor": "deck"})
        wsd.send_json({"type": "chat", "text": "flush-A"})
        got_p = _drain(wsp, "chat")
        assert any(e.get("kind") == "aoe" and e["payload"]["floor"] == "deck"
                   for e in got_p), "deck's viewer sees the deck template"
        got_o = _drain(wso, "chat")
        assert "aoe" not in _kinds(got_o), "primary's viewer must not see it"
        wsd.send_json({"type": "aoe", "shape": "square", "x": 2, "y": 2, "size": 2})
        wsd.send_json({"type": "chat", "text": "flush-B"})
        got_o2 = _drain(wso, "chat")
        assert any(e.get("kind") == "aoe" for e in got_o2)
        got_p2 = _drain(wsp, "chat")
        assert "aoe" not in _kinds(got_p2)
        wsd.send_json({"type": "aoe", "shape": "circle", "x": 1, "y": 1,
                       "size": 2, "floor": "nowhere"})
        assert "No such floor" in recv_until(wsd, "error")["payload"]["msg"]
    with ws_connect(client, observer, code) as wso:
        wso.send_json({"type": "aoe", "shape": "circle", "x": 1, "y": 1, "size": 2})
        assert "Only the DM" in recv_until(wso, "error")["payload"]["msg"]


def test_ping_gating_bounds_and_plane_delivery(client):
    dm, player, code, ch = base_room(client)
    _add_floor(client, dm, code, "deck")
    observer = reg(client, "obs")
    join_room(client, observer, code)
    with ws_connect(client, dm, code) as wsd:
        ptok = _pc_token(code, ch)
        wsd.send_json({"type": "token_floor", "token_id": ptok["id"], "floor": "deck"})
        recv_until(wsd, "token_floor")
    with ws_connect(client, player, code) as wsp, \
         ws_connect(client, observer, code) as wso, \
         ws_connect(client, dm, code) as wsd:
        # 1. primary ping: observer receives, deck player must not
        wso.send_json({"type": "ping", "x": 2, "y": 2, "color": "#f1c40f"})
        wsd.send_json({"type": "chat", "text": "flush-1"})
        assert "ping" in _kinds(_drain(wsd, "chat"))          # DM sees everything
        assert "ping" not in _kinds(_drain(wsp, "chat"))      # elsewhere: silent
        _drain(wso, "chat")
        # 2. token-less observer CLAIMS another plane: dropped, even for the DM
        wso.send_json({"type": "ping", "x": 3, "y": 3, "floor": "deck"})
        wsd.send_json({"type": "chat", "text": "flush-2"})
        assert "ping" not in _kinds(_drain(wsd, "chat"))
        _drain(wso, "chat")
        # 3. deck's own player pings the deck: DM receives it, primary not
        wsp.send_json({"type": "ping", "x": 3, "y": 3, "floor": "deck"})
        wsd.send_json({"type": "chat", "text": "flush-3"})
        pings = [e for e in _drain(wsd, "chat") if e.get("kind") == "ping"]
        assert pings and pings[-1]["payload"]["floor"] == "deck"
        assert "ping" not in _kinds(_drain(wso, "chat"))
        _drain(wsp, "chat")
        # 4. bounds clamp to the TARGET plane's map (default primary 40x26)
        wso.send_json({"type": "ping", "x": 10 ** 6, "y": 10 ** 6})
        wsd.send_json({"type": "chat", "text": "flush-4"})
        pings = [e for e in _drain(wsd, "chat") if e.get("kind") == "ping"]
        assert (pings[-1]["payload"]["x"], pings[-1]["payload"]["y"]) == (39, 25)
        _drain(wso, "chat")
        # 5. a claimed-but-nonexistent floor: silently dropped
        wso.send_json({"type": "ping", "x": 4, "y": 4, "floor": "nowhere"})
        wsd.send_json({"type": "chat", "text": "flush-5"})
        assert "ping" not in _kinds(_drain(wsd, "chat"))


# ---------- C — properties, assets, floors, mounts, lamps, state ----------

def test_darkvision_property_reaches_only_interested(client):
    FORBIDDEN = {"token_darkvision", "token_light", "token_image", "token_floor"}
    dm, player, code, ch = room_with_wall(client, wall_x=10)
    with ws_connect(client, player, code) as wsp, \
         ws_connect(client, dm, code) as wsd:
        hid = add_named(wsd, "DarkThing", 15, 13)
        wsd.send_json({"type": "token_darkvision", "token_id": hid, "radius": 10})
        wsd.send_json({"type": "token_light", "token_id": hid, "radius": 3})
        wsd.send_json({"type": "chat", "text": "flush-D"})
        got = _drain(wsp, "chat")
        assert not _kinds(got) & FORBIDDEN


def test_asset_access_follows_controller_and_token_lifecycle(client):
    dm, player, code, ch = base_room(client)
    art = _put(client, dm, _png(9, 9), "guardface").json()["id"]
    with ws_connect(client, dm, code) as wsd:
        hid = add_named(wsd, "Warden", 4, 4)
        wsd.send_json({"type": "token_image", "token_id": hid, "asset_id": art})
        recv_until(wsd, "token_image")
    cid = db.q1("SELECT id FROM users WHERE username=?", (player["name"],))["id"]
    assert client.get(f"/api/assets/{art}", headers=H(player)).status_code == 404
    with ws_connect(client, dm, code) as wsd:
        wsd.send_json({"type": "token_controller", "token_id": hid, "controller_id": cid})
        recv_until(wsd, "token_controller")
        assert client.get(f"/api/assets/{art}", headers=H(player)).status_code == 200
        lst = {a["id"] for a in client.get(f"/api/assets?room={code}",
                                           headers=H(player)).json()["assets"]}
        assert art in lst, "riding a token I operate: listed"
        # 401-adjacent path: unrelated member still blind while riding persists
        stranger = reg(client, "str")
        assert client.get(f"/api/assets/{art}", headers=H(stranger)).status_code == 404
        wsd.send_json({"type": "token_controller", "token_id": hid,
                       "controller_id": None})
        recv_until(wsd, "token_controller")
        assert client.get(f"/api/assets/{art}", headers=H(player)).status_code == 404, \
            "revoked controller must not keep downloading the artwork"
        wsd.send_json({"type": "token_controller", "token_id": hid, "controller_id": cid})
        recv_until(wsd, "token_controller")
        assert client.get(f"/api/assets/{art}", headers=H(player)).status_code == 200
        # the riding token dies: the grant dies with it
        wsd.send_json({"type": "del_token", "token_id": hid})
        recv_until(wsd, "token_gone")
    assert client.get(f"/api/assets/{art}", headers=H(player)).status_code == 404


def test_foreign_and_missing_floor_transitions_refuse_in_place(client):
    dm, player, code, ch = base_room(client)
    _add_floor(client, dm, code, "crypt")
    with ws_connect(client, dm, code) as wsd:
        npc = add_named(wsd, "Keeper", 16, 14)
    ptok = _pc_token(code, ch)
    with ws_connect(client, player, code) as wsp:
        wsp.send_json({"type": "token_floor", "token_id": ptok["id"],
                       "floor": "nowhere"})
        assert "No such floor" in recv_until(wsp, "error",
                                             fail_on_error=False)["payload"]["msg"]
        wsp.send_json({"type": "token_floor", "token_id": npc, "floor": "crypt"})
        assert recv_until(wsp, "error", fail_on_error=False)["payload"]["msg"] \
            == "Not your token"
    assert db.q1("SELECT floor FROM tokens WHERE id=?", (ptok["id"],))["floor"] == ""
    assert db.q1("SELECT floor FROM tokens WHERE id=?", (npc,))["floor"] == ""
    # control: a legal own-token transition still works both directions
    with ws_connect(client, player, code) as wsp:
        wsp.send_json({"type": "token_floor", "token_id": ptok["id"], "floor": "crypt"})
        assert recv_until(wsp, "token_floor")["payload"]["floor"] == "crypt"
        wsp.send_json({"type": "token_floor", "token_id": ptok["id"], "floor": ""})
        assert recv_until(wsp, "token_floor")["payload"]["floor"] == ""


def test_rider_cannot_change_floors_alone_and_pair_lands_together(client):
    dm, player, code, ch = base_room(client)
    _add_floor(client, dm, code, "deck")
    with ws_connect(client, dm, code) as wsd:
        boat = add_named(wsd, "Boat", 6, 6)
        rider = add_named(wsd, "Sailor", 2, 6)
        wsd.send_json({"type": "token_mount", "token_id": rider, "mount_token_id": boat})
        recv_until(wsd, "token_mount")
        wsd.send_json({"type": "token_floor", "token_id": rider, "floor": "deck"})
        assert recv_until(wsd, "error", fail_on_error=False)["payload"]["msg"] \
            == "Dismount before changing floors"
        assert db.q1("SELECT floor FROM tokens WHERE id=?", (rider,))["floor"] == ""
        wsd.send_json({"type": "token_floor", "token_id": boat, "floor": "deck"})
        seen = set()
        for _ in range(8):
            e = recv_until(wsd, "token_floor")
            seen.add(e["payload"]["token_id"])
            if seen == {boat, rider}:
                break
        assert seen == {boat, rider}
        _teleport(wsd, boat, 12, 12)                 # same-plane walk of the mount
    pair = [db.q1("SELECT floor FROM tokens WHERE id=?", (i,))["floor"]
            for i in (boat, rider)]
    assert pair == ["deck", "deck"]                  # never split across planes


def test_lamp_state_survives_refresh_and_stale_editor_snapshot(client):
    dm, player, code, ch = base_room(client)
    add_lamp(client, dm, code, 5, 5, bright=5)
    with ws_connect(client, dm, code) as wsd:
        ptok = _pc_token(code, ch)
        _teleport(wsd, ptok["id"], 6, 5)             # stand beside the lamp
    with ws_connect(client, player, code) as wsp:
        wsp.send_json({"type": "interact", "object_id": "lamp1"})
        ev = recv_until(wsp, "object_state")["payload"]
        assert ev == {"object_id": "lamp1", "state": {"on": False}}
    st = state_of(client, dm, code)                  # a fresh /state after refresh
    lamp = [o for o in st["grid"]["objects"] if o["id"] == "lamp1"][0]
    assert lamp["state"] == {"on": False}
    # a stale editor snapshot that still says ON must not flip world truth
    stale = json.loads(json.dumps(st["grid"]))
    for o in stale["objects"]:
        if o["id"] == "lamp1":
            o["state"] = {"on": True}
    with ws_connect(client, dm, code) as wsd:
        wsd.send_json({"type": "map_edit", "map": stale})
        recv_until(wsd, "map_changed")
    st2 = state_of(client, dm, code)
    lamp2 = [o for o in st2["grid"]["objects"] if o["id"] == "lamp1"][0]
    assert lamp2["state"] == {"on": False}


def test_hidden_plane_token_absent_from_state_text_and_live_channel(client):
    dm, player, code, ch = room_with_wall(client, wall_x=10)
    _add_floor(client, dm, code, "crypt")
    with ws_connect(client, player, code) as wsp, \
         ws_connect(client, dm, code) as wsd:
        hid = add_named(wsd, "Below", 14, 13)
        wsd.send_json({"type": "token_floor", "token_id": hid, "floor": "crypt"})
        recv_until(wsd, "token_floor")
        st = state_of(client, player, code)
        # The token/ghost channels — the floor-data carriers — carry NOTHING
        # (the public chronicle names table figures by design; it is not a
        # plane-attribution channel and carries no id/floor/light data).
        raw = json.dumps([st["tokens"], st["ghosts"]])
        assert "Below" not in raw                      # not even a stripped row
        assert hid not in {t["id"] for t in st["tokens"]}
        assert hid not in {g["id"] for g in st["ghosts"]}
        # activity ON the crypt plane never touches the primary socket
        wsd.send_json({"type": "forced_move", "token_id": hid, "kind": "teleport",
                       "tx": 7, "ty": 3})
        wsd.send_json({"type": "chat", "text": "flush-C"})
        seen = _drain(wsp, "chat")
        tok_evs = [e for e in seen if (e.get("payload") or {}).get("token_id") == hid
                   or (e.get("payload") or {}).get("id") == hid]
        assert not tok_evs


# ---------- P3 — map-editor resize keeps pins and elevation ----------

def test_editor_resize_preserves_pins_and_elevation():
    """P3: edResize() used to rebuild the edit snapshot without pins or the
    elev layer — sanitize then legitimately emptied both, so every resize
    silently deleted all pins of that plane (pins belong to the plane's map;
    carrying them through preserves their floor association by construction).
    Real 50_canvas code in a Node vm, the established harness pattern."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    from tests.test_browser_flow import _vm
    init = """
      const cells = new Array(40*26).fill(0), elev = new Array(40*26).fill(0);
      cells[1*40+5] = 1; elev[1*40+2] = 4;
      state.editMap = { w: 40, h: 26, cell: 50, origin: [0, 0], cells, elev,
        explored: new Array(40*26).fill(0), traps: [{id:'t',x:1,y:1,dc:12,dmg:'1d4'}],
        loot: [], doors: [], objects: [],
        pins: [{id:'keep',x:1,y:1,type:'info',visibility:'dm',title:'K'},
               {id:'drop',x:38,y:24,type:'info',visibility:'dm',title:'D'}] };
      $("ed-w").value = 20; $("ed-h").value = 10;
    """
    probe = """
      edResize();
      const m = state.editMap;
      console.log(JSON.stringify({
        w: m.w, h: m.h, pins: m.pins.map(p => p.id),
        pinTitles: m.pins.map(p => p.title),
        elevAt: m.elev[1*20+2], cellsAt: m.cells[1*20+5],
        elevLen: m.elev.length, traps: m.traps.length }));
    """
    got = _vm(init, probe)
    assert got["w"] == 20 and got["h"] == 10
    assert got["pins"] == ["keep"], "in-bounds pin survives, out-of-bounds drops"
    assert got["pinTitles"] == ["K"]                          # full pin data kept
    assert got["elevAt"] == 4 and got["elevLen"] == 200       # row-wise elev carry
    assert got["cellsAt"] == 1 and got["traps"] == 1          # prior behaviour kept
