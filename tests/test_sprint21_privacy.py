"""SPRINT-21 — final WebSocket privacy audit regressions (D91).

Sprint 20 left the MANUAL condition channels (cond_add / cond_remove / stand /
knock_prone), the initiative-driven condition ticks, walk move_state and
token_gone as room-wide id-broadcasts: an unseen NPC hit them all. Every one
now runs through the single presence gate (visibility.send_presence_event)
or the D82 property gate. These tests drive the LIVE WS dispatch paths.
Chat is room-wide, so every drain matches only its OWN unique marker text —
queue leftovers from other sockets can never truncate or fake a window.
Positive controls pin the other side: table-presence tokens keep their
classic room-wide channels, DM privileges are untouched.
"""
import pytest
from starlette.testclient import TestClient

from app import db
from app.main import app
from tests.test_movement_fog import (H, base_room, join_room, make_char,
                                     recv_until, reg, room_with_wall,
                                     ws_connect)
from tests.test_sprint19_audit import add_named


@pytest.fixture()
def client():
    return TestClient(app)


def _until(ws, marker, tries=150):
    """Drain until THIS socket's own marker echo. Every other event the
    server sent in the meantime is in the returned window."""
    evs = []
    for _ in range(tries):
        ev = ws.receive_json()
        evs.append(ev)
        if marker in str((ev.get("payload") or {}).get("text", "")):
            break
    return evs


def _drain_kind(ws, kind, tries=150):
    evs = []
    for _ in range(tries):
        ev = ws.receive_json()
        evs.append(ev)
        if ev.get("kind") == kind:
            break
    return evs


def _kinds(evs):
    return [e.get("kind") for e in evs]


def _conds_for(evs, tok_id):
    return [e for e in evs if e.get("kind") == "cond"
            and (e.get("payload") or {}).get("token_id") == tok_id]


_SEQ = [0]


def _sync(wsd, wsp):
    """Absorb join/hello/presence chatter deterministically before a window."""
    wsd.send_json({"type": "chat", "text": "sync-d"})
    _until(wsd, "sync-d")
    wsp.send_json({"type": "chat", "text": "sync-p"})
    _until(wsp, "sync-p")


def _dm_act_then_drain(wsd, wsp):
    """DM-side events are enqueued into the player's queue by the DM socket's
    connection task; seeing the DM's own unique echo proves the handler (and
    its awaited broadcast) completed — so every cross-loop event is already
    in the player's queue ahead of the player's own unique echo."""
    _SEQ[0] += 1
    n = _SEQ[0]
    wsd.send_json({"type": "chat", "text": f"fd{n}p"})      # unique per phase
    dm_seen = _until(wsd, f"fd{n}p")
    wsp.send_json({"type": "chat", "text": f"fp{n}s"})
    return dm_seen, _until(wsp, f"fp{n}s")


def test_manual_cond_channels_never_name_a_hidden_token(client):
    dm, player, code, ch = room_with_wall(client, wall_x=10)
    with ws_connect(client, dm, code) as wsd:
        hid = add_named(wsd, "Ghost", 15, 13)          # behind the wall: unseen
    with ws_connect(client, player, code) as wsp, \
         ws_connect(client, dm, code) as wsd:
        _sync(wsd, wsp)
        wsd.send_json({"type": "cond_add", "token_id": hid, "key": "restrained",
                       "rounds": 2})
        dm_seen, p_seen = _dm_act_then_drain(wsd, wsp)
        assert _conds_for(dm_seen, hid), "DM keeps table truth"
        assert not _conds_for(p_seen, hid), "manual cond_add named a hidden token"
        wsd.send_json({"type": "knock_prone", "token_id": hid})
        dm_seen, p_seen = _dm_act_then_drain(wsd, wsp)
        assert _conds_for(dm_seen, hid), "knock-prone still reaches the DM"
        assert not _conds_for(p_seen, hid), "knock_prone named a hidden token"
        wsd.send_json({"type": "cond_remove", "token_id": hid, "key": "restrained"})
        _, p_seen = _dm_act_then_drain(wsd, wsp)
        assert not _conds_for(p_seen, hid)
        wsd.send_json({"type": "del_token", "token_id": hid})
        _, p_seen = _dm_act_then_drain(wsd, wsp)
        gone = [e for e in p_seen if e.get("kind") == "token_gone"
                and e["payload"]["token_id"] == hid]
        assert not gone, "deleting an unseen NPC must not name it either"


def test_stand_on_hidden_npc_is_silent_but_room_channel_survives(client):
    """Presence control: a PLAYER's own token keeps the classic room-wide
    cond channel — the gate is presence, not sender."""
    dm, player, code, ch = base_room(client)
    pal = reg(client, "pal")
    join_room(client, pal, code)
    pch = make_char(client, pal)
    client.post(f"/api/rooms/{code}/assign", json={"character_id": pch["id"]},
                headers=H(pal))
    rid = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
    ptok = db.q1("SELECT * FROM tokens WHERE room_id=? AND character_id=?",
                 (rid, ch["id"]))
    with ws_connect(client, player, code) as wsa, \
         ws_connect(client, pal, code) as wsp:
        _sync(wsa, wsp)
        wsa.send_json({"type": "cond_add", "token_id": ptok["id"], "key": "prone",
                       "rounds": 0})
        wsa.send_json({"type": "chat", "text": "fa1x"})
        _until(wsa, "fa1x")
        wsp.send_json({"type": "chat", "text": "fp1y"})
        got = _until(wsp, "fp1y")
        assert _conds_for(got, ptok["id"]), "owned token cond must stay room-wide"
        wsa.send_json({"type": "stand", "token_id": ptok["id"]})
        wsa.send_json({"type": "chat", "text": "fa2x"})
        _until(wsa, "fa2x")
        wsp.send_json({"type": "chat", "text": "fp2y"})
        got = _until(wsp, "fp2y")
        assert _conds_for(got, ptok["id"]), "stand-up on an owned token stays public"


def test_hidden_npc_walk_is_silent_visible_walk_is_not(client):
    dm, player, code, ch = room_with_wall(client, wall_x=10)
    with ws_connect(client, dm, code) as wsd:
        hid = add_named(wsd, "Stalker", 15, 13)        # behind the wall
        vis = add_named(wsd, "Sentry", 4, 4)           # open ground, in sight
    with ws_connect(client, player, code) as wsp, \
         ws_connect(client, dm, code) as wsd:
        _sync(wsd, wsp)
        wsd.send_json({"type": "move", "token_id": hid, "tx": 14, "ty": 13})
        dm_seen, p_seen = _dm_act_then_drain(wsd, wsp)
        assert any(e.get("kind") == "move_state"
                   and e["payload"]["token_id"] == hid and e["payload"]["moving"]
                   for e in dm_seen), "premise: DM must see the walk start"
        leak = [e for e in p_seen if e.get("kind") == "move_state"
                and e["payload"]["token_id"] == hid]
        assert not leak, "walk ring of an unseen NPC announced its id"
        wsd.send_json({"type": "move", "token_id": vis, "tx": 5, "ty": 4})
        _, p_seen = _dm_act_then_drain(wsd, wsp)
        assert any(e.get("kind") == "move_state"
                   and e["payload"]["token_id"] == vis and e["payload"]["moving"]
                   for e in p_seen), \
            "visible-token walk rings must not be over-gated"


def test_controller_grant_window_tracks_condition_delivery(client):
    dm, player, code, ch = room_with_wall(client, wall_x=10)
    cid = db.q1("SELECT id FROM users WHERE username=?", (player["name"],))["id"]
    with ws_connect(client, dm, code) as wsd:
        hid = add_named(wsd, "Mount", 15, 13)          # unseen by the player
    with ws_connect(client, player, code) as wsp, \
         ws_connect(client, dm, code) as wsd:
        _sync(wsd, wsp)
        wsd.send_json({"type": "token_controller", "token_id": hid,
                       "controller_id": cid})
        _, p_seen = _dm_act_then_drain(wsd, wsp)
        assert "token_controller" in _kinds(p_seen)     # D82 grant is announced
        wsd.send_json({"type": "cond_add", "token_id": hid, "key": "prone",
                       "rounds": 1})
        _, p_seen = _dm_act_then_drain(wsd, wsp)
        # (15,13) is beyond the raw 6-cell LOS radius — the CONTROLLER branch
        # of the gate is the only reason this may arrive:
        assert _conds_for(p_seen, hid), \
            "the assigned controller must receive state for the token they operate"
        wsd.send_json({"type": "token_controller", "token_id": hid,
                       "controller_id": None})
        _dm_act_then_drain(wsd, wsp)
        wsd.send_json({"type": "cond_add", "token_id": hid, "key": "blinded",
                       "rounds": 1})
        _, p_seen = _dm_act_then_drain(wsd, wsp)
        assert not _conds_for(p_seen, hid), \
            "a REVOKED controller must go blind again"


def test_init_tick_player_side_silence(client):
    dm, player, code, ch = room_with_wall(client, wall_x=10)
    with ws_connect(client, dm, code) as wsd:
        hid = add_named(wsd, "Ticked", 15, 13)
        wsd.send_json({"type": "cond_add", "token_id": hid, "key": "prone",
                       "rounds": 1})
        recv_until(wsd, "cond")
        wsd.send_json({"type": "init_start"})
        recv_until(wsd, "initiative")
        wsd.send_json({"type": "chat", "text": "sync-d"})
        _until(wsd, "sync-d")
    with ws_connect(client, player, code) as wsp, \
         ws_connect(client, dm, code) as wsd:
        _sync(wsd, wsp)
        wsd.send_json({"type": "init_end_round"})           # ticks the active token
        dm_seen, p_seen = _dm_act_then_drain(wsd, wsp)
        assert not _conds_for(p_seen, hid), \
            "initiative-driven condition expiry named a hidden token"
        if not _conds_for(dm_seen, hid):
            pytest.skip("round-expiry semantics: no tick fired this advance")


def test_visible_token_deletion_still_reaches_the_viewer(client):
    """Ghost REMOVAL sync must stay correct — never-seen is pinned in test #1."""
    dm, player, code, ch = base_room(client)
    with ws_connect(client, dm, code) as wsd:
        vis = add_named(wsd, "Seen", 4, 4)
    with ws_connect(client, player, code) as wsp, \
         ws_connect(client, dm, code) as wsd:
        _sync(wsd, wsp)
        wsd.send_json({"type": "del_token", "token_id": vis})
        _, p_seen = _dm_act_then_drain(wsd, wsp)
        assert any(e.get("kind") == "token_gone" and e["payload"]["token_id"] == vis
                   for e in p_seen), "visible token deletion must reach the viewer"
