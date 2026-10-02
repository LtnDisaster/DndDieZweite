"""Quest Log + game-event foundation integration tests (D51/D52).

Covers the security-critical pair: live delivery AND /state filter DM-only
quests server-side, plus notice visibility, reconnect reconstruction, the
DM-only mutation boundary, and the plain-data event facts emitted by quest
and door operations.
"""
import json

import pytest
from starlette.testclient import TestClient

from app import db, events
from app.main import app

from test_movement_fog import (H, base_room, state_of, ws_connect, recv_until)


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def room_id_of(code):
    return db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]


def _add(ws, title, **kw):
    msg = {"type": "quest_add", "title": title}
    msg.update(kw)
    ws.send_json(msg)
    recv_until(ws, "quests_changed")


def _quests(client, user, code):
    return state_of(client, user, code)["quests"]


def _qid(quests, title):
    return next(q["id"] for q in quests if q["title"] == title)


def test_party_quest_visible_and_reconstructable(client):
    dm, player, code, _ = base_room(client)
    with ws_connect(client, dm, code) as ws:
        _add(ws, "Find the Missing Scout",
             objectives=["Speak with the guard", "Search the old road"])
    qs = _quests(client, player, code)
    assert [q["title"] for q in qs] == ["Find the Missing Scout"]
    assert qs[0]["status"] == "active" and len(qs[0]["objectives"]) == 2
    assert qs[0]["objectives"][0]["text"] == "Speak with the guard"
    # Reconnect reconstruction: a fresh /state (what a reconnecting client does)
    assert _quests(client, player, code)[0]["objectives"][1]["done"] is False


def test_dm_only_quest_never_reaches_player(client):
    dm, player, code, _ = base_room(client)
    with ws_connect(client, dm, code) as ws:
        _add(ws, "SECRET Patron Deal", objectives=["Keep the pact"], visibility="dm")
    assert _quests(client, dm, code)[0]["visibility"] == "dm"
    assert all(q["title"] != "SECRET Patron Deal" for q in _quests(client, player, code))
    # The strongest form: the title never even appears in the player's payload.
    raw = client.get(f"/api/rooms/{code}/state", headers=H(player)).text
    assert "SECRET Patron Deal" not in raw


def test_player_cannot_create_or_mutate_quests(client):
    dm, player, code, _ = base_room(client)
    with ws_connect(client, dm, code) as ws:
        _add(ws, "Party Quest")
        qid = _qid(_quests(client, dm, code), "Party Quest")
    with ws_connect(client, player, code) as pws:
        pws.send_json({"type": "quest_add", "title": "Hijacked Quest"})
        pws.send_json({"type": "quest_complete", "quest_id": qid})
        pws.send_json({"type": "quest_delete", "quest_id": qid})
        kinds = []
        for _ in range(12):                                   # skip connect chatter (presence…)
            kinds.append(pws.receive_json().get("kind"))
            if kinds.count("error") >= 3:
                break
        assert kinds.count("error") == 3
        assert "quests_changed" not in kinds
    assert all(q["title"] != "Hijacked Quest" for q in _quests(client, dm, code))
    assert _quests(client, dm, code)[0]["status"] == "active"      # untouched


def test_objective_completion_and_outcome_persist(client):
    dm, player, code, _ = base_room(client)
    with ws_connect(client, dm, code) as ws:
        _add(ws, "Lantern for the Widow",
             objectives=["Buy lamp oil", "Deliver the lantern"])
        qid = _qid(_quests(client, dm, code), "Lantern for the Widow")
        ws.send_json({"type": "quest_obj_done", "quest_id": qid,
                      "objective_id": "o1", "done": True})
        recv_until(ws, "quests_changed")
        ws.send_json({"type": "quest_complete", "quest_id": qid})
        recv_until(ws, "quests_changed")
    q = _quests(client, player, code)[0]
    assert q["status"] == "completed"
    assert q["objectives"][0]["done"] is True and q["objectives"][1]["done"] is False


def test_hidden_quest_filtered_from_players(client):
    dm, player, code, _ = base_room(client)
    with ws_connect(client, dm, code) as ws:
        _add(ws, "Pending Reveal")
        qid = _qid(_quests(client, dm, code), "Pending Reveal")
        ws.send_json({"type": "quest_update", "quest_id": qid, "status": "hidden"})
        recv_until(ws, "quests_changed")
    assert all(q["title"] != "Pending Reveal" for q in _quests(client, player, code))
    assert any(q["title"] == "Pending Reveal" for q in _quests(client, dm, code))


def test_notices_follow_quest_visibility(client):
    dm, player, code, _ = base_room(client)
    with ws_connect(client, dm, code) as ws:
        _add(ws, "Public Errand")
        _add(ws, "Covert Pact", visibility="dm")
    p_msgs = " ".join(m["body"] for m in state_of(client, player, code)["messages"])
    d_msgs = " ".join(m["body"] for m in state_of(client, dm, code)["messages"])
    assert "QUEST ADDED: Public Errand" in p_msgs          # party notice reaches players
    assert "QUEST ADDED: Covert Pact" not in p_msgs        # DM-only notice does not
    assert "QUEST ADDED: Covert Pact" in d_msgs


def test_quest_and_door_ops_emit_plain_events(client):
    dm, player, code, _ = base_room(client)
    rid = room_id_of(code)
    with ws_connect(client, dm, code) as ws:
        _add(ws, "Event Watch")
        qid = _qid(_quests(client, dm, code), "Event Watch")
        ws.send_json({"type": "quest_complete", "quest_id": qid})
        recv_until(ws, "quests_changed")
        grid = state_of(client, dm, code)["grid"]
        grid["doors"] = [{"id": "ev", "x": 8, "y": 6, "dir": "v",
                          "closed": True, "locked": False}]
        ws.send_json({"type": "map_edit", "map": grid})
        recv_until(ws, "map_changed")
        ws.send_json({"type": "door", "x": 8, "y": 6, "dir": "v", "action": "toggle"})
        recv_until(ws, "map_changed")
    types = [e["type"] for e in events.recent]
    assert "quest_started" in types and "quest_completed" in types
    assert "door_opened" in types and "door_closed" not in types   # started closed, opened once
    for e in events.recent:
        json.dumps(e)                       # transport-free: events are plain data
    done = next(e for e in events.recent if e["type"] == "quest_completed")
    assert done["data"]["quest_id"] == qid and done["room_id"] == rid
    opened = next(e for e in events.recent if e["type"] == "door_opened")
    assert opened["data"] == {"x": 8, "y": 6, "dir": "v", "locked": False}
