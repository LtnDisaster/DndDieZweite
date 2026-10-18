"""D151 (Nachtschicht 3.0, Phase 4): close the audit's test debt.

Phase 1 found four WS ops that the table uses every session but no test
ever exercised: turn_mark (slot bookkeeping), death_clear (DM revive
override), quest_fail and quest_obj_add (story panel). Each is pinned here
through its real transport, at the level the feature is actually felt.
"""
import uuid

import pytest
from starlette.testclient import TestClient

from app import db, main
from tests.test_movement_fog import H, base_room, join_room, make_char, reg, ws_connect


@pytest.fixture
def client():
    app = main.app
    with TestClient(app) as c:
        yield c


def drain(ws, marker, cap=90):
    """bounded read-until-marker — ws.receive_json() blocks forever otherwise"""
    ws.send_json({"type": "chat", "text": marker})
    out = []
    while len(out) < cap:
        ev = ws.receive_json()
        if ev.get("kind") == "chat" and marker in str(ev.get("payload", {}).get("text", "")):
            return out
        out.append(ev)
    raise AssertionError("burst never ended")


def rid(code):
    return db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]


def state_of(client, u, code):
    return client.get(f"/api/rooms/{code}/state", headers=H(u)).json()


def _add_member(client, code, tag):
    u = reg(client, tag)
    join_room(client, u, code)
    ch = make_char(client, u)
    client.post(f"/api/rooms/{code}/assign",
                json={"character_id": ch["id"]}, headers=H(u))
    tok = next(t for t in db.q("SELECT * FROM tokens WHERE room_id=?", (rid(code),))
               if t["character_id"] == ch["id"])
    return u, tok


# ---------------------------------------------------------------- turn_mark

def test_turn_marks_the_active_turn_only(client):
    dm, player, code, _ch = base_room(client)
    _mate, mtok = _add_member(client, code, "tm2")
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "init_start"})
        evs = drain(ws, "@@tm1@@")
        init = next(e for e in evs if e.get("kind") == "initiative")["payload"]
        active = init["turn"]["token_id"]
        idle = mtok["id"] if active != mtok["id"] else next(
            t["id"] for t in db.q("SELECT * FROM tokens WHERE room_id=?", (rid(code),))
            if t["id"] != mtok["id"])
        ws.send_json({"type": "turn_mark", "token_id": idle, "slot": "bonus",
                      "value": "used"})
        ws.send_json({"type": "turn_mark", "token_id": active, "slot": "bonus",
                      "value": "used"})
        evs = drain(ws, "@@tm2@@")
        assert any(e.get("kind") == "error" and "active turn" in e["payload"]["msg"]
                   for e in evs), "off-turn mark must be refused"
        marked = [e for e in evs if e.get("kind") == "initiative"
                  and (e["payload"].get("turn") or {}).get("bonus") == "used"]
        assert marked, "active-turn mark never broadcast"


def test_turn_mark_by_owner_on_own_active_turn(client):
    dm, player, code, _ch = base_room(client)      # single participant -> own turn active
    with ws_connect(client, player, code) as pws:
        with ws_connect(client, dm, code) as dws:
            dws.send_json({"type": "init_start"})
            evs = drain(dws, "@@own1@@")
            init = next(e for e in evs if e.get("kind") == "initiative")["payload"]
            tid = init["turn"]["token_id"]         # the owner sends their token, as the UI does
            pws.send_json({"type": "turn_mark", "token_id": tid,
                           "slot": "action", "value": "used"})
            evs = drain(pws, "@@own2@@")
            marked = [e for e in evs if e.get("kind") == "initiative"
                      and (e["payload"].get("turn") or {}).get("action") == "used"]
            errs = [e["payload"]["msg"] for e in evs if e.get("kind") == "error"]
            assert marked, f"errors={errs}"
            pws.send_json({"type": "turn_mark", "token_id": tid,
                           "slot": "action", "value": "available"})   # the chip toggles back
            evs = drain(pws, "@@own3@@")
            assert any(e.get("kind") == "initiative"
                       and (e["payload"].get("turn") or {}).get("action") == "available"
                       for e in evs)


# ---------------------------------------------------------------- death_clear

def test_death_clear_is_a_dm_override(client):
    dm, player, code, _ch = base_room(client)
    tok = db.q("SELECT * FROM tokens WHERE room_id=? AND character_id IS NOT NULL",
               (rid(code),))[0]
    db.x("UPDATE characters SET hp=0 WHERE id=?", (tok["character_id"],))
    db.x("UPDATE tokens SET death=? WHERE id=?",
         (db.json_dumps({"s": 1, "f": 2, "stable": False, "dead": False}), tok["id"]))
    with ws_connect(client, player, code) as pws:
        pws.send_json({"type": "death_clear", "token_id": tok["id"]})
        evs = drain(pws, "@@dc1@@")
        assert not [e for e in evs if e.get("kind") == "death"]
        assert db.q1("SELECT death FROM tokens WHERE id=?", (tok["id"],))["death"]
    with ws_connect(client, dm, code) as dws:
        dws.send_json({"type": "death_clear", "token_id": tok["id"]})
        evs = drain(dws, "@@dc2@@")
        gone = [e for e in evs if e.get("kind") == "death"
                and e["payload"]["token_id"] == tok["id"] and e["payload"]["death"] is None]
        assert gone, "DM clear never broadcast the reset"
        assert db.q1("SELECT death FROM tokens WHERE id=?", (tok["id"],))["death"] is None


# ------------------------------------------------------------ quest ops

def _dm_quest(client, dm, code, title):
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "quest_add", "title": title, "visibility": "party"})
        drain(ws, "@@q1@@")
    q = next(x for x in state_of(client, dm, code)["quests"] if x["title"] == title)
    return q["id"]


def test_quest_obj_add_and_fail_flow(client):
    dm, _player, code, _ch = base_room(client)
    qid = _dm_quest(client, dm, code, "Seal the gate")
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "quest_obj_add", "quest_id": qid, "text": "Find the keystone"})
        ws.send_json({"type": "quest_fail", "quest_id": qid})
        ws.send_json({"type": "quest_obj_add", "quest_id": qid + 9999, "text": "ghost"})
        evs = drain(ws, "@@q2@@")
        assert any(e.get("kind") == "error" and "No such quest" in e["payload"]["msg"]
                   for e in evs), "bogus quest id must answer"
    q = next(x for x in state_of(client, dm, code)["quests"] if x["id"] == qid)
    assert "Find the keystone" in [o["text"] for o in q["objectives"]]
    assert q["status"] == "failed"


def test_quest_ops_are_dm_only(client):
    dm, player, code, _ch = base_room(client)
    qid = _dm_quest(client, dm, code, "DM only quest")
    with ws_connect(client, player, code) as pws:
        pws.send_json({"type": "quest_obj_add", "quest_id": qid, "text": "sneaky"})
        pws.send_json({"type": "quest_fail", "quest_id": qid})
        evs = drain(pws, "@@q3@@")
        dm_only = [e for e in evs if e.get("kind") == "error"
                   and "Only the DM manages quests" in e["payload"]["msg"]]
        assert len(dm_only) >= 2, "player quest mutations must be refused"
    q = next(x for x in state_of(client, dm, code)["quests"] if x["id"] == qid)
    assert q["status"] != "failed" and not q["objectives"]
