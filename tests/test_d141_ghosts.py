"""D141 (AP-028): fog memory outlives the process.

TODO P2 closed: a viewer's ghost dict used to die with the server (or a
worker restart). It now goes to room_state.ghosts_json when the last socket
closes and comes back with the viewer's first sighted frame — no DB churn
per step, one write per disconnect, int keys restored on hydration.
"""
import pytest
from starlette.testclient import TestClient

from app import db, main
from app.room import visibility
from tests.test_movement_fog import (H, base_room, join_room, make_char, reg,
                                     state_of, ws_connect)


@pytest.fixture
def client():
    app = main.app
    with TestClient(app) as c:
        yield c


def rid(code):
    return db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]


def second_player(client, code, tag):
    u = reg(client, tag)
    join_room(client, u, code)
    ch = make_char(client, u)
    client.post(f"/api/rooms/{code}/assign",
                json={"character_id": ch["id"]}, headers=H(u))
    return u, ch


def tok_of(user_id, code):
    return next(t for t in db.q("SELECT * FROM tokens WHERE room_id=?", (rid(code),))
                if t.get("owner_user_id") == user_id)


def drain(ws, cap=90):
    ws.send_json({"type": "chat", "text": "@@ghflush@@"})
    out = []
    while len(out) < cap:
        ev = ws.receive_json()
        if ev.get("kind") == "chat" and "@@ghflush@@" in str(ev.get("payload", {}).get("text", "")):
            return out
        out.append(ev)
    raise AssertionError("burst never ended")


def test_ghosts_survive_the_process(client):
    from tests.test_movement_fog import room_with_wall
    from tests.test_sprint19_audit import add_named
    from tests.test_sprint21_privacy import _dm_act_then_drain, _sync
    dm, player, code, ch = room_with_wall(client, wall_x=10)
    me = state_of(client, player, code)["me"]
    with ws_connect(client, dm, code) as wsd, \
         ws_connect(client, player, code) as wsp:
        _sync(wsd, wsp)
        sent = add_named(wsd, "Sentry", 4, 4)
        _sync(wsd, wsp)
        wsd.send_json({"type": "move", "token_id": sent, "tx": 5, "ty": 4})
        _, p_seen = _dm_act_then_drain(wsd, wsp)
        assert any(e.get("kind") == "step" and e["payload"]["token_id"] == sent
                   for e in p_seen), "premise: the player SAW the token move"
        assert sent in visibility._last_seen.get(rid(code), {}).get(me, {})
    blob = db.j(db.q1("SELECT ghosts_json FROM room_state WHERE room_id=?",
                      (rid(code),))["ghosts_json"], {})
    assert str(sent) in (blob.get(str(me)) or {})      # written at disconnect
    visibility._last_seen.pop(rid(code), None)          # the process died
    visibility.hydrate_ghosts(rid(code), me)
    back = visibility._last_seen[rid(code)][me]
    assert sent in back and back[sent]["id"] == sent     # int keys restored


def test_empty_ghosts_write_nothing(client):
    dm, player, code, ch = base_room(client)
    me = state_of(client, player, code)["me"]
    with ws_connect(client, player, code) as wsa:
        drain(wsa)
    blob = db.j(db.q1("SELECT ghosts_json FROM room_state WHERE room_id=?",
                      (rid(code),))["ghosts_json"], {})
    assert blob.get(str(me)) is None          # never persisted, stays lean
