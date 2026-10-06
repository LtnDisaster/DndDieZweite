"""D73 token lifecycle: delete -> transient token_gone -> ABSENT (never a
stored 'Gone' placeholder). Distinct from last-seen fog ghosts, which remain
legitimate for tokens that still exist."""
import pytest
from starlette.testclient import TestClient

from app import db, main
from app.room import visibility


@pytest.fixture()
def client():
    return TestClient(main.app)


from test_movement_fog import (base_room, park, recv_until, state_of,
                               ws_connect)


def test_delete_is_authoritative_everywhere_and_idempotent(client):
    dm, player, code, ch = base_room(client)
    ptok = state_of(client, player, code)["tokens"][0]
    park(client, dm, code, ptok["id"])
    with ws_connect(client, player, code) as pws, ws_connect(client, dm, code) as dws:
        dws.send_json({"type": "add_token", "label": "Goblin", "x": (18 + .5) * 50,
                       "y": (12 + .5) * 50})
        tid = recv_until(dws, "token_add")["payload"]["id"]
        recv_until(pws, "token_add")                      # player sees the live token

        dws.send_json({"type": "del_token", "token_id": tid})
        ev = recv_until(pws, "token_gone")
        assert ev["payload"]["token_id"] == tid
        recv_until(dws, "token_gone")

    # absent from BOTH authorities and views; reload cannot resurrect
    assert db.q1("SELECT id FROM tokens WHERE id=?", (tid,)) is None
    for user in (dm, player):
        ids = [t["id"] for t in state_of(client, user, code)["tokens"]]
        assert tid not in ids
    # reconnect path: a fresh socket sees nothing to resurrect (state IS the DB)
    with ws_connect(client, dm, code) as dws2:
        pass

    # deleting an already deleted token (and a bogus id) is a silent no-op
    with ws_connect(client, dm, code) as dws3:
        dws3.send_json({"type": "del_token", "token_id": tid})
        dws3.send_json({"type": "del_token", "token_id": 999999})
        dws3.send_json({"type": "add_token", "label": "Proof", "x": 900, "y": 600})
        recv_until(dws3, "token_add")                     # alive + no error event


def test_deleted_hidden_npc_goes_absent_living_creature_keeps_ghost_semantics(client):
    dm, player, code, ch = base_room(client)
    ptok = state_of(client, player, code)["tokens"][0]
    park(client, dm, code, ptok["id"])
    with ws_connect(client, player, code) as pws, ws_connect(client, dm, code) as dws:
        dws.send_json({"type": "add_token", "label": "Stalker", "x": (18 + .5) * 50,
                       "y": (12 + .5) * 50})
        tid = recv_until(dws, "token_add")["payload"]["id"]
        recv_until(pws, "token_add")

        # (a) a creature that merely LEFT view keeps ghost semantics: the token
        # still exists server-side, players get token_leave, not token_gone
        dws.send_json({"type": "move", "token_id": tid, "tx": 36, "ty": 12, "teleport": True})
        recv_until(pws, "token_leave")
        assert db.q1("SELECT id FROM tokens WHERE id=?", (tid,)) is not None

        # (b) deletion converges BOTH sides to absent — a leave/ghost is not
        # enough: the row must be gone and token_gone must reach every client
        dws.send_json({"type": "del_token", "token_id": tid})
        recv_until(pws, "token_gone")
    assert db.q1("SELECT id FROM tokens WHERE id=?", (tid,)) is None
    assert tid not in [t["id"] for t in state_of(client, dm, code)["tokens"]]
    assert tid not in [t["id"] for t in state_of(client, player, code)["tokens"]]
    # server ghost memory must not reference the deleted token either
    for viewers in visibility._last_seen.get(1, {}).values():
        assert tid not in viewers
