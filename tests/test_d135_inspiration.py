"""D135 (AP-021): Heroic Inspiration is a spendable marker, not a light switch.

Audit F6: the 2024 rules make Inspiration a pool of ONE that rides an
attack roll, an ability check or a saving throw — spending is an engine
event, and gaining while full passes the marker on (or gains nothing).
Consumers: `adv:"insp"` on the character d20 paths (spend BEFORE rolling,
folds into the advantage derivation) and the `gain` action with
`pass_to_char`. Blind expressions and NPC rolls cannot carry the marker.
"""
import uuid

import pytest
from starlette.testclient import TestClient

from app import db, main
from tests.test_d129_exhaustion import grant_equip, mk_def
from tests.test_movement_fog import (H, base_room, join_room, make_char, reg,
                                     recv_until, state_of, ws_connect)
from tests.test_sprint23_combat import set_progression


@pytest.fixture
def client():
    app = main.app
    with TestClient(app) as c:
        yield c


def drain(ws, cap=80):
    ws.send_json({"type": "chat", "text": "@@insflush@@"})
    out = []
    while len(out) < cap:
        ev = ws.receive_json()
        if ev.get("kind") == "chat" and "@@insflush@@" in str(ev.get("payload", {}).get("text", "")):
            return out
        out.append(ev)
    raise AssertionError("burst never ended")


def error_of(evs):
    errs = [e for e in evs if e.get("kind") == "error"]
    return errs[0]["payload"]["msg"] if errs else None


def my_id(client, user, code):
    return state_of(client, user, code)["me"]


def tok_of(user_id, code):
    return next(t for t in db.q("SELECT * FROM tokens WHERE room_id=?",
                                (db.q1("SELECT id FROM rooms WHERE code=?",
                                       (code,))["id"],))
                if t.get("owner_user_id") == user_id)


def inspired(ch_id):
    return int(db.q1("SELECT inspiration FROM characters WHERE id=?",
                     (ch_id,))["inspiration"])


def second_player(client, code, tag):
    u = reg(client, tag)
    join_room(client, u, code)
    ch = make_char(client, u)
    assert client.post(f"/api/rooms/{code}/assign",
                       json={"character_id": ch["id"]}, headers=H(u)).status_code == 200
    return u, ch


# ------------------------------------------------------------- spending

def test_inspiration_spends_on_a_check(client):
    dm, player, code, ch = base_room(client)
    tk = tok_of(my_id(client, player, code), code)["id"]
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "inspiration", "action": "gain", "token_id": tk})
        drain(ws)
    assert inspired(ch["id"]) == 1
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "roll", "kind": "check", "ability": "dex",
                      "adv": "insp", "visibility": "public",
                      "op_id": "i" + uuid.uuid4().hex[:8]})
        evs = drain(ws)
    assert any(e.get("kind") == "dice" for e in evs)
    assert inspired(ch["id"]) == 0
    assert db.q1("SELECT 1 AS ok FROM messages WHERE room_id=? AND body LIKE ?",
                 (db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"],
                  "%spends Heroic Inspiration%")) is not None


def test_spending_without_the_marker_fails(client):
    dm, player, code, ch = base_room(client)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "roll", "kind": "save", "ability": "str",
                      "adv": "insp", "visibility": "public", "op_id": "j1"})
        assert "no Heroic Inspiration" in error_of(drain(ws))


def test_blind_and_npc_paths_cannot_carry_the_marker(client):
    dm, player, code, ch = base_room(client)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "roll", "kind": "misc", "expr": "1d20",
                      "adv": "insp", "visibility": "public", "op_id": "k1"})
        assert "attack roll, ability check or saving throw" in error_of(drain(ws))


def test_npc_rolls_cannot_carry_the_marker(client):
    dm = reg(client, "insdm2")
    code = client.post("/api/rooms", json={"name": "I2"}, headers=H(dm)).json()["code"]
    rid = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
    db.x("INSERT INTO tokens (room_id,label,x,y,npc) VALUES (?,?,?,?,?)",
         (rid, "Goblin", 0, 0, '{"name": "Goblin"}'))
    npc_tok = db.q1("SELECT id FROM tokens WHERE room_id=? AND label=?",
                    (rid, "Goblin"))["id"]
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "roll", "kind": "save", "ability": "dex",
                      "token_id": npc_tok, "adv": "insp", "op_id": "n1"})
        assert "attack roll, ability check or saving throw" in error_of(drain(ws))


def test_inspiration_spends_on_an_attack(client):
    from test_combat_turn import pass_until_mine, start_combat
    dm, player, code, ch = base_room(client)
    tk = None
    def_id = mk_def(client, dm, code, {"damage_dice": "1d8", "damage_type": "slashing",
                                       "ability": "str"}, "Insublade")
    item_id = grant_equip(client, dm, player, code, ch["id"], def_id)
    tok = tok_of(my_id(client, player, code), code)
    start_combat(client, dm, code)
    pass_until_mine(client, dm, code, tok["id"])
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "inspiration", "action": "gain", "token_id": tok["id"]})
        drain(ws)
        ws.send_json({"type": "roll", "kind": "attack", "item_id": item_id,
                      "token_id": tok["id"], "adv": "insp", "visibility": "public",
                      "op_id": "a" + uuid.uuid4().hex[:8]})
        evs = drain(ws)
    assert any(e.get("kind") == "dice" for e in evs)
    assert inspired(ch["id"]) == 0


# --------------------------------------------------------------- passing

def test_gaining_when_full_passes_on_or_gains_nothing(client):
    dm, player, code, ch = base_room(client)
    mate, och = second_player(client, code, "insmate")
    tk = tok_of(my_id(client, player, code), code)["id"]
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "inspiration", "action": "gain", "token_id": tk})
        drain(ws)
        ws.send_json({"type": "inspiration", "action": "gain", "token_id": tk})
        drain(ws)                                          # no pass_to_char
    assert inspired(ch["id"]) == 1 and inspired(och["id"]) == 0   # nothing gained
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "inspiration", "action": "gain", "token_id": tk,
                      "pass_to_char": och["id"]})
        drain(ws)
    assert inspired(ch["id"]) == 0 and inspired(och["id"]) == 1


def test_pass_needs_a_character_in_this_room(client):
    dm, player, code, ch = base_room(client)
    stranger = make_char(client, reg(client, "insfar"))            # not seated
    tk = tok_of(my_id(client, player, code), code)["id"]
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "inspiration", "action": "gain", "token_id": tk})
        drain(ws)
        ws.send_json({"type": "inspiration", "action": "gain", "token_id": tk,
                      "pass_to_char": stranger["id"]})
        drain(ws)
    assert inspired(ch["id"]) == 1 and inspired(stranger["id"]) == 0
