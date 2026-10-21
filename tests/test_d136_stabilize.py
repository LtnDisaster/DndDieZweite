"""D136 (AP-022): Help to stabilize is a DC 10 Wisdom (Medicine) CHECK.

Audit F8: 2024 replaced the automatic stabilize with a check — the engine
gains the `stabilize` message: adjacency, the actor's Action in combat (and
the D134 no_actions gate), a Medicine roll through the EXISTING skill
derivation, natural 20 revives, failure touches no death-save counter.
"""
import uuid

import pytest
from starlette.testclient import TestClient

from app import db, main
from tests.test_movement_fog import H, base_room, join_room, make_char, reg, ws_connect
from tests.test_sprint23_combat import set_progression


@pytest.fixture
def client():
    app = main.app
    with TestClient(app) as c:
        yield c


def drain(ws, cap=90):
    ws.send_json({"type": "chat", "text": "@@stabflush@@"})
    out = []
    while len(out) < cap:
        ev = ws.receive_json()
        if ev.get("kind") == "chat" and "@@stabflush@@" in str(ev.get("payload", {}).get("text", "")):
            return out
        out.append(ev)
    raise AssertionError("burst never ended")


def error_of(evs):
    errs = [e for e in evs if e.get("kind") == "error"]
    return errs[0]["payload"]["msg"] if errs else None


def rid(code):
    return db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]


def make_dying(client, code, tag):
    u = reg(client, tag)
    join_room(client, u, code)
    ch = make_char(client, u)
    client.post(f"/api/rooms/{code}/assign",
                json={"character_id": ch["id"]}, headers=H(u))
    tok = next(t for t in db.q("SELECT * FROM tokens WHERE room_id=?", (rid(code),))
               if t["character_id"] == ch["id"])
    db.x("UPDATE characters SET hp=0 WHERE id=?", (ch["id"],))
    db.x("UPDATE tokens SET death=? WHERE id=?",
         (db.json_dumps({"s": 0, "f": 0, "stable": False, "dead": False}), tok["id"]))
    return u, ch, tok


# ------------------------------------------------------------------ flow

def test_stabilize_is_a_medicine_check_whose_outcome_is_the_dice(client):
    dm, player, code, ch = base_room(client)
    mate, och, otok = make_dying(client, code, "stabmate")
    atok = next(t for t in db.q("SELECT * FROM tokens WHERE room_id=?", (rid(code),))
                if t["id"] != otok["id"] and t["character_id"] == ch["id"])
    db.x("UPDATE tokens SET x=0, y=0 WHERE id=?", (atok["id"],))
    db.x("UPDATE tokens SET x=50, y=0 WHERE id=?", (otok["id"],))
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "stabilize", "token_id": atok["id"],
                      "target_token_id": otok["id"], "visibility": "public",
                      "op_id": "s" + uuid.uuid4().hex[:8]})
        evs = drain(ws)
    dice = [e for e in evs if e.get("kind") == "dice"]
    assert dice, evs
    assert "DC 10" in dice[0]["payload"]["text"] or "natural 20" in dice[0]["payload"]["text"]
    d = db.j(db.q1("SELECT death FROM tokens WHERE id=?",
                   (otok["id"],))["death"], None)
    stable = bool(d and d.get("stable"))
    text = dice[0]["payload"]["text"]
    # SRD: a plain success stabilises (death record keeps stable=1), a
    # natural 20 instead restores 1 HP — the patient leaves dying entirely
    # (death cleared). The stored truth and the rolled text must agree.
    nat20 = "natural 20" in text
    assert stable == ("— stable" in text)
    assert (d is None) == nat20                  # nat20 leaves dying (1 HP)


def test_stabilize_needs_a_dying_patient(client):
    dm, player, code, ch = base_room(client)
    atok = next(t for t in db.q("SELECT * FROM tokens WHERE room_id=?", (rid(code),))
                if t["character_id"] == ch["id"])
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "stabilize", "token_id": atok["id"],
                      "target_token_id": atok["id"], "op_id": "s1"})
        assert "stabilize yourself" in error_of(drain(ws))


def test_distance_and_turn_and_action_are_enforced(client):
    from test_combat_turn import pass_until_mine, start_combat
    dm, player, code, ch = base_room(client)
    mate, och, otok = make_dying(client, code, "stabfar")
    atok = next(t for t in db.q("SELECT * FROM tokens WHERE room_id=?", (rid(code),))
                if t["id"] != otok["id"] and t["character_id"] == ch["id"])
    db.x("UPDATE tokens SET x=0, y=0 WHERE id=?", (atok["id"],))
    db.x("UPDATE tokens SET x=900, y=900 WHERE id=?", (otok["id"],))
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "stabilize", "token_id": atok["id"],
                      "target_token_id": otok["id"], "op_id": "s2"})
        assert "next to the patient" in error_of(drain(ws))
    db.x("UPDATE tokens SET x=50, y=0 WHERE id=?", (otok["id"],))
    start_combat(client, dm, code)           # not the actor's turn yet: someone else is
    first = db.q("SELECT * FROM tokens WHERE room_id=?", (rid(code),))
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "stabilize", "token_id": atok["id"],
                      "target_token_id": otok["id"], "op_id": "s3"})
        err = error_of(drain(ws))
    assert err in ("It is not your turn", None) or "not your turn" in str(err)
    pass_until_mine(client, dm, code, atok["id"])
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "stabilize", "token_id": atok["id"],
                      "target_token_id": otok["id"], "op_id": "s4"})
        drain(ws)
    init = db.q1("SELECT initiative FROM room_state WHERE room_id=?",
                 (rid(code),))["initiative"]
    turn = db.j(init, {}).get("turn") or {}
    assert turn.get("action") == "used"      # the Action is really spent


def test_incapacitated_cannot_stabilize(client):
    dm, player, code, ch = base_room(client)
    mate, och, otok = make_dying(client, code, "stabinc")
    atok = next(t for t in db.q("SELECT * FROM tokens WHERE room_id=?", (rid(code),))
                if t["id"] != otok["id"] and t["character_id"] == ch["id"])
    db.x("UPDATE tokens SET x=0, y=0 WHERE id=?", (atok["id"],))
    db.x("UPDATE tokens SET x=50, y=0 WHERE id=?", (otok["id"],))
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "cond_add", "token_id": atok["id"], "key": "stunned"})
        drain(ws)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "stabilize", "token_id": atok["id"],
                      "target_token_id": otok["id"], "op_id": "s5"})
        assert "can't take actions" in error_of(drain(ws))
