"""D148 (TODO 'Cross-tab / reconnect'): one user, MANY sockets. Closing one
tab must never prune what another open tab still holds — the ghost memory,
the online presence and the DB write all belong to the USER, not the socket.
And after the genuinely last socket closed (persisted, RAM pruned), the next
/state call re-seeds the ghosts from the database, so a reconnect sees the
same faded tokens it saw before the browser died.
"""
import pytest
from starlette.testclient import TestClient

from app import db, main
from app.room import visibility
from tests.test_d141_ghosts import rid
from tests.test_movement_fog import room_with_wall, state_of, ws_connect


@pytest.fixture
def client():
    with TestClient(main.app) as c:
        yield c


def test_second_tab_closing_prunes_nothing(client):
    from tests.test_sprint19_audit import add_named
    from tests.test_sprint21_privacy import _dm_act_then_drain, _sync
    dm, player, code, ch = room_with_wall(client, wall_x=10)
    me = state_of(client, player, code)["me"]
    with ws_connect(client, dm, code) as wsd, \
         ws_connect(client, player, code) as tab1, \
         ws_connect(client, player, code) as tab2:
        _sync(wsd, tab1)
        _sync(wsd, tab2)
        sent = add_named(wsd, "Sentry", 4, 4)
        _sync(wsd, tab1)
        wsd.send_json({"type": "move", "token_id": sent, "tx": 5, "ty": 4})
        _, p_seen = _dm_act_then_drain(wsd, tab1)
        assert any(e.get("kind") == "step" and e["payload"]["token_id"] == sent
                   for e in p_seen)
        assert sent in visibility._last_seen[rid(code)][me]
        tab2.__exit__(None, None, None)          # tab 2 closes; tab 1 is open
        wsd.send_json({"type": "chat", "text": "@@t2close@@"})
        _, p_after = _dm_act_then_drain(wsd, tab1)
        assert not any(e.get("kind") == "presence"
                       and e["payload"].get("online") is False
                       for e in p_after), "closing one tab logged the user off"
        assert sent in visibility._last_seen[rid(code)][me]
        blob = db.j(db.q1("SELECT ghosts_json FROM room_state WHERE room_id=?",
                          (rid(code),))["ghosts_json"], {})
        assert not (blob.get(str(me)) or {})     # nothing persisted yet


def test_reconnect_seeds_ghosts_from_the_database(client):
    from tests.test_sprint19_audit import add_named
    from tests.test_sprint21_privacy import _dm_act_then_drain, _sync
    dm, player, code, ch = room_with_wall(client, wall_x=10)
    me = state_of(client, player, code)["me"]
    with ws_connect(client, dm, code) as wsd, \
         ws_connect(client, player, code) as wsp:
        _sync(wsd, wsp)
        sent = add_named(wsd, "Sentry", 4, 4)
        _sync(wsd, wsp)
        wsd.send_json({"type": "move", "token_id": sent, "tx": 15, "ty": 4,
                              "teleport": True})   # wall blocks walking; DM drags through
        _dm_act_then_drain(wsd, wsp)
        wsd.send_json({"type": "chat", "text": "@@beforeclose@@"})
        _dm_act_then_drain(wsd, wsp)
    # last socket closed: memory pruned from RAM, persisted to the DB ...
    assert rid(code) not in visibility._last_seen
    blob = db.j(db.q1("SELECT ghosts_json FROM room_state WHERE room_id=?",
                      (rid(code),))["ghosts_json"], {})
    assert str(sent) in (blob.get(str(me)) or {})
    # ... and the reconnect (a fresh socket, then its state view) re-seeds
    # the faded tokens exactly as the browser saw them before it died.
    with ws_connect(client, player, code) as fresh:
        st = state_of(client, player, code)
        assert sent in visibility._last_seen[rid(code)][me]   # RAM refilled
    ghosts = [g for g in st["ghosts"] if g.get("ghost")]
    assert sent in {g["id"] for g in ghosts}
