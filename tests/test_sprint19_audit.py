"""Sprint 19 P0 — audit regressions for the Sprint 18 integration.

Five findings, one test family each (L-numbers match the final report):
  L1  property broadcasts (span/visual/rot/controller/image/floor/light) were
      room-wide: a hidden NPC's artwork/plane/light/controller leaked to every
      player socket — and from the leaked URL over REST too.
  L2  the step-first token_add and the ghost memory shipped the UNSTRIPPED
      snapshot — first-sight bypassed every add-path strip.
  L3  REST asset list/serve treated ROOM MEMBERSHIP as a read grant for
      artwork the game itself withholds (NPC/hidden/other-plane), and the DM
      listing exposed every user's global upload catalogue.
  L4  token_floor committed without checking the target plane for room.
  L5  dark-room light vision used OPERATED tokens — a controller saw the world
      through an NPC's lantern, which D82 forbids ("a controller reveals no
      fog") and the classic channel never allowed.

Helpers are the established movement/fog suite ones; recv semantics: drain_*
collects the kinds seen up to the awaited marker — forbidden kinds in that
window ARE the failure.
"""
import pytest
from starlette.testclient import TestClient

from app import db, main
from tests.test_assets import _png, _put
from tests.test_movement_fog import (H, add_npc, base_room, join_room,
                                     recv_until, reg, room_with_wall,
                                     state_of, ws_connect)


@pytest.fixture()
def client():
    return TestClient(main.app)

FORBIDDEN = {"token_image", "token_floor", "token_light", "token_controller",
             "token_span", "token_visual", "token_rot"}


def drain_events(ws, kind, tries=80):
    """Collect every event until the awaited kind arrives (markers are
    player-triggered rolls, so the window is bounded and deterministic)."""
    evs = []
    for _ in range(tries):
        ev = ws.receive_json()
        evs.append(ev)
        if (ev.get("kind") or ev.get("type")) == kind:
            return evs
    return evs


def uid_of(user):
    return db.q1("SELECT id FROM users WHERE username=?", (user["name"],))["id"]


def add_named(wsd, label, cx, cy):
    """A fresh viewer socket gets first-sight token_adds for every existing
    token on the next reevaluation (legitimate server behaviour) — the plain
    add_npc helper would capture one of those. Match by label."""
    cell = 50
    wsd.send_json({"type": "add_token", "label": label, "x": (cx + .5) * cell,
                   "y": (cy + .5) * cell, "size": "Medium"})
    for _ in range(40):
        ev = wsd.receive_json()
        if ev.get("kind") == "token_add" and (ev.get("payload") or {}).get("label") == label:
            return ev["payload"]["id"]
    raise AssertionError("NPC never added")


# ---------- L1 ----------

def test_property_broadcasts_reach_only_interested_viewers(client):
    dm, player, code, _ = room_with_wall(client)
    bystander = reg(client, "bs")
    join_room(client, bystander, code)
    bid = uid_of(bystander)
    art = _put(client, dm, _png(11, 11), "guardart").json()["id"]

    with ws_connect(client, player, code) as wsp, \
         ws_connect(client, bystander, code) as wsb:
        with ws_connect(client, dm, code) as wsd:
            hid = add_named(wsd, "Secret", 15, 13)
            for msg in ({"type": "token_image", "token_id": hid, "asset_id": art},
                        {"type": "token_light", "token_id": hid, "radius": 5},
                        {"type": "token_rot", "token_id": hid, "degrees": 90},
                        {"type": "token_span", "token_id": hid, "width": 2, "height": 2},
                        {"type": "token_visual", "token_id": hid, "vw": 3, "vh": 3},
                        {"type": "token_controller", "token_id": hid, "user_id": bid}):
                wsd.send_json(msg)
            wsd.send_json({"type": "forced_move", "token_id": hid, "kind": "teleport",
                           "tx": 15, "ty": 13})          # no-op marker, stays unseen
            # DETERMINISTIC FLUSH: a DM chat is broadcast from the acting
            # socket AFTER every property op was scheduled — on each target
            # loop the FIFO order guarantees all earlier deliveries precede
            # it (private roll replies CAN jump that order; broadcast chat
            # cannot). Draining up to it proves a live observation window.
            wsd.send_json({"type": "chat", "text": "flush-1"})
            seen = drain_events(wsp, "chat")
            got = {(e.get("kind") or e.get("type")) for e in seen}
            assert not (got & FORBIDDEN), f"player socket leaked {got & FORBIDDEN}"
            # the ACTUAL stakeholder learns its token: controller event AND the
            # token itself arrived — the flush window really was live.
            seen_b = drain_events(wsb, "chat")
            gb = {(e.get("kind") or e.get("type")) for e in seen_b}
            assert "token_controller" in gb
            adds = [e for e in seen_b if e.get("kind") == "token_add"
                    and (e.get("payload") or {}).get("id") == hid]
            assert adds, "the new controller is delivered its token"
        assert client.get(f"/api/assets/{art}", headers=H(bystander)).status_code == 200
        # serving follows legitimate sight, not membership
        assert client.get(f"/api/assets/{art}", headers=H(player)).status_code == 404
        assert client.get(f"/api/assets/{art}", headers=H(dm)).status_code == 200


# ---------- L2 ----------

def test_first_sight_token_add_and_ghost_carry_no_hidden_properties(client):
    dm, player, code, _ = room_with_wall(client)
    art = _put(client, dm, _png(9, 9), "secretface").json()["id"]
    with ws_connect(client, dm, code) as wsd:
        hid = add_named(wsd, "Patrol", 15, 13)
        wsd.send_json({"type": "token_image", "token_id": hid, "asset_id": art})
        wsd.send_json({"type": "token_light", "token_id": hid, "radius": 4})
        # player connects AFTER placement: the NPC is virgin territory (no ghost)
        with ws_connect(client, player, code) as wsp:
            wsd.send_json({"type": "forced_move", "token_id": hid,
                           "kind": "teleport", "tx": 7, "ty": 3})
            # deterministic flush: chat is processed on the DM loop AFTER the
            # move handler queued its events; the player loop is FIFO, so a
            # later stop-at-first-step could race the synthesized add.
            wsd.send_json({"type": "chat", "text": "flush-marker-9"})
            seen = drain_events(wsp, "chat")
            adds = [e for e in seen if e.get("kind") == "token_add"]
            mine = [a for a in adds if a["payload"].get("id") == hid]
            assert mine, "stepping NPC should reach its viewer as token_add"
            pl = mine[0]["payload"]
            for k in ("image", "floor", "light", "controller_user_id", "size", "fw"):
                assert pl.get(k) in (None, ""), f"first-sight leak: {k}={pl.get(k)}"
            assert pl.get("label") == "Patrol"           # honest data survives
            wsd.send_json({"type": "forced_move", "token_id": hid,
                           "kind": "teleport", "tx": 15, "ty": 13})
            drain_events(wsp, "token_leave")
            st = state_of(client, player, code)          # before disconnect
    ghosts = [g for g in st.get("ghosts", []) if g.get("id") == hid]
    assert ghosts, "the lost patrol remains a memory"
    for k in ("image", "floor", "light", "controller_user_id"):
        assert ghosts[0].get(k) in (None, ""), f"ghost leak: {k}"


# ---------- L4 (+ mount plane guard) ----------

def test_floor_change_rejects_occupied_destination_and_cross_plane_mount(client):
    dm, player, code, _ = base_room(client)
    r = client.post(f"/api/rooms/{code}/floors", json={"name": "crypt"}, headers=H(dm))
    assert r.status_code == 200, r.text
    mine = [t for t in state_of(client, player, code)["tokens"]
            if t.get("owner_user_id") is not None][0]
    cx, cy = int(mine["x"] // 50), int(mine["y"] // 50)
    with ws_connect(client, dm, code) as wsd:
        blocker = add_named(wsd, "Occupier", cx, cy)
        # add_token's placement spiral legally nudges overlapping NPCs aside —
        # stage the REAL overlap directly (a legacy row sitting on the same
        # cell), which is exactly the situation stairs must refuse.
        db.x("UPDATE tokens SET x=?, y=? WHERE id=?", (mine["x"], mine["y"], blocker))
        wsd.send_json({"type": "token_floor", "token_id": blocker, "floor": "crypt"})
        while (e := wsd.receive_json()).get("kind") != "token_floor":
            pass
        rider = add_named(wsd, "Rider", cx + 3, cy)   # stays PRIMARY
        # cross-plane ride refused (mount on crypt, rider on primary)
        wsd.send_json({"type": "token_mount", "token_id": rider, "mount_token_id": blocker})
        assert recv_until(wsd, "error", fail_on_error=False)["payload"]["msg"] \
            == "Mount and rider must share a floor"
    with ws_connect(client, player, code) as wsp:
        wsp.send_json({"type": "token_floor", "token_id": mine["id"], "floor": "crypt"})
        err = recv_until(wsp, "error", fail_on_error=False)
        assert err["kind"] == "error" and "room" in err["payload"]["msg"].lower()
        st = state_of(client, player, code)
        row = [t for t in st["tokens"] if t["id"] == mine["id"]][0]
        assert (row.get("floor") or "") == ""          # refused = unchanged
        # free the destination, then the same stairs are legal
        with ws_connect(client, dm, code) as wsd:
            wsd.send_json({"type": "forced_move", "token_id": blocker,
                           "kind": "teleport", "tx": cx + 6, "ty": cy + 6})
        wsp.send_json({"type": "token_floor", "token_id": mine["id"], "floor": "crypt"})
        assert recv_until(wsp, "token_floor")["payload"]["floor"] == "crypt"
        assert (state_of(client, player, code)["tokens"] and
                [t for t in state_of(client, player, code)["tokens"]
                 if t["id"] == mine["id"]][0]["floor"] == "crypt")


# ---------- L5 ----------

def test_controller_permission_never_grants_light_vision(client):
    dm, player, code, _ = room_with_wall(client)
    grid = state_of(client, dm, code)["grid"]
    with ws_connect(client, dm, code) as wsd:
        wsd.send_json({"type": "map_edit", "map": {**grid, "dark": True}, "dark": True})
        recv_until(wsd, "map_changed")
        lantern = add_named(wsd, "Lantern", 12, 5)
        squire = add_named(wsd, "Squire", 12, 8)
        wsd.send_json({"type": "token_light", "token_id": lantern, "radius": 10})
        recv_until(wsd, "token_light")
    pid = uid_of(player)
    ids = {t["id"] for t in state_of(client, player, code)["tokens"]}
    assert squire not in ids and lantern not in ids, \
        f"ids={ids} lantern={lantern} squire={squire} " \
        f"rows={db.q('SELECT id,label,owner_user_id FROM tokens')[:]} allusers={db.q('SELECT id FROM users')[:]}"
    with ws_connect(client, player, code) as wsp, \
         ws_connect(client, dm, code) as wsd:
        wsd.send_json({"type": "token_controller", "token_id": lantern, "user_id": pid})
        seen = drain_events(wsp, "token_add")
        adds = [e for e in seen if e.get("kind") == "token_add"
                and e["payload"].get("id") == lantern]
        assert adds, "the operated token itself IS delivered to its controller"
        wsd.send_json({"type": "chat", "text": "flush-4"})   # barrier
        seen += drain_events(wsp, "chat")
        leaked = [e for e in seen if e.get("kind") == "token_add"
                  and e["payload"].get("id") == squire]
        assert not leaked, "the lantern's light must not open the world for a controller"
    ids = {t["id"] for t in state_of(client, player, code)["tokens"]}
    assert squire not in ids


# ---------- L3 ----------

def test_asset_listing_mirrors_legitimate_sight(client):
    dm, player, code, _ = base_room(client)
    unrelated = reg(client, "un")
    secret = _put(client, unrelated, _png(5, 5), "someone-elses-life").json()["id"]
    roomart = _put(client, dm, _png(8, 8), "npc-face").json()["id"]
    ownart = _put(client, player, _png(6, 6), "my-face").json()["id"]
    mine = [t for t in state_of(client, player, code)["tokens"]
            if t.get("owner_user_id") is not None][0]["id"]
    with ws_connect(client, dm, code) as wsd:
        hid = add_named(wsd, "Warden", 4, 4)
        wsd.send_json({"type": "token_image", "token_id": hid, "asset_id": roomart})
        recv_until(wsd, "token_image")
    with ws_connect(client, player, code) as wsp:
        wsp.send_json({"type": "token_image", "token_id": mine, "asset_id": ownart})
        assert recv_until(wsp, "token_image")["payload"]["image"] == f"/assets/{ownart}"
    lst = client.get(f"/api/assets?room={code}", headers=H(player)).json()["assets"]
    listed = {a["id"] for a in lst}
    assert ownart in listed                          # own: always
    assert roomart not in listed                     # NPC art: not yours to browse
    assert secret not in listed                      # stranger: never
    assert client.get(f"/api/assets/{secret}", headers=H(player)).status_code == 404
    dl = client.get(f"/api/assets?room={code}", headers=H(dm)).json()["assets"]
    dlist = {a["id"] for a in dl}
    assert roomart in dlist                          # riding in their room
    assert secret not in dlist                       # no more global catalogue
