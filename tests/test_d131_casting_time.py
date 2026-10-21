"""D131 (AP-017): casting time spends the turn slot it names.

`gear.casting_slot` maps the CASTING TIME text onto action/bonus/reaction
(None for minute/hour/ritual — out of turn tempo). During an active
initiative a player cast spends that slot of its OWN turn through the same
economy attacks use; validation precedes the spell-slot claim's spending and
an op-replay stays silent BEFORE the action check. Outside combat nothing is
spent. Deterministic fixtures: "1 action", "1 bonus action", "1 reaction",
"1 minute" — and spell-slot-free cantrips as the pure slot probe.
"""
import uuid

import pytest
from starlette.testclient import TestClient

from app import db, gear, main
from app.room import combat as CB
from test_combat_turn import pass_until_mine, start_combat
from test_movement_fog import (base_room, make_char, recv_until, ws_connect)
from test_sprint23_combat import set_progression


@pytest.fixture
def client():
    app = main.app
    with TestClient(app) as c:
        yield c


def token_id(code, ch_id):
    rid = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
    return db.q1("SELECT id FROM tokens WHERE room_id=? AND character_id=?",
                 (rid, ch_id))["id"]


def caster_room(client, casting_time):
    """base room whose PC knows a level-1 slot spender + a free cantrip, both
    carrying the SAME casting time under test."""
    dm, player, code, ch = base_room(client)
    set_progression(ch["id"],
                    spells=[{"id": "s1", "name": "Zap", "level": 1, "cast": "none",
                             "casting_time": casting_time},
                            {"id": "c0", "name": "Spark", "level": 0, "cast": "none",
                             "casting_time": casting_time}],
                    spell_slots={"1": {"max": 4, "used": 0}})
    return dm, player, code, ch, token_id(code, ch["id"])


def cast(client, player, code, tok, spell, op=None):
    msg = {"type": "cast", "spell_id": spell, "token_id": tok,
           "visibility": "public"}
    if op:
        msg["op_id"] = op
    with ws_connect(client, player, code) as ws:
        ws.send_json(msg)
        return drain_kind(ws)


def drain_kind(ws, cap=60):
    ws.send_json({"type": "chat", "text": "@@ctflush@@"})
    out = []
    while len(out) < cap:
        ev = ws.receive_json()
        if ev.get("kind") == "chat" and "@@ctflush@@" in str(ev.get("payload", {}).get("text", "")):
            return out
        out.append(ev)
    raise AssertionError("burst never ended")


def error_msg(evs):
    errs = [e for e in evs if e.get("kind") == "error"]
    return errs[0]["payload"]["msg"] if errs else None


# ---------------------------------------------------------------- unit: map

def test_casting_slot_maps_the_free_text():
    assert gear.casting_slot("1 action") == "action"
    assert gear.casting_slot("Action") == "action"
    assert gear.casting_slot("1 bonus action") == "bonus"
    assert gear.casting_slot("Bonus action") == "bonus"
    assert gear.casting_slot("1 reaction") == "reaction"
    assert gear.casting_slot("1 minute") is None
    assert gear.casting_slot("1 hour") is None
    assert gear.casting_slot("1 action, ritual 1 hour") is None
    assert gear.casting_slot("") == "action"          # SRD default, not "None"
    assert gear.casting_slot(None) == "action"


# ------------------------------------------------------------ gate: in combat

def test_action_cast_spends_the_action_and_blocks_the_second(client):
    dm, player, code, ch, tok = caster_room(client, "1 action")
    start_combat(client, dm, code)
    pass_until_mine(client, dm, code, tok)
    evs = cast(client, player, code, tok, "c0")            # free cantrip: slot economy only
    assert error_msg(evs) is None, evs
    init = CB.get_init(db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"])
    assert init["turn"]["action"] == "used" and init["turn"]["bonus"] == "available"
    evs = cast(client, player, code, tok, "c0")
    assert "No action left this turn" in error_msg(evs)


def test_bonus_cast_spends_the_bonus_not_the_action(client):
    dm, player, code, ch, tok = caster_room(client, "1 bonus action")
    start_combat(client, dm, code)
    pass_until_mine(client, dm, code, tok)
    evs = cast(client, player, code, tok, "c0")
    assert error_msg(evs) is None, evs
    init = CB.get_init(db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"])
    assert init["turn"]["bonus"] == "used" and init["turn"]["action"] == "available"


def test_long_casting_time_spends_no_turn_slot(client):
    dm, player, code, ch, tok = caster_room(client, "1 minute")
    start_combat(client, dm, code)
    pass_until_mine(client, dm, code, tok)
    evs = cast(client, player, code, tok, "s1")            # leveled: slot tx still runs
    assert error_msg(evs) is None, evs
    init = CB.get_init(db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"])
    assert init["turn"]["action"] == "available" and init["turn"]["bonus"] == "available"
    slots = db.j(db.q1("SELECT spell_slots FROM characters WHERE id=?", (ch["id"],))["spell_slots"], {})
    assert slots["1"]["used"] == 1                 # the spell slot itself is spent


def test_combat_cast_without_token_is_refused_before_any_spend(client):
    dm, player, code, ch, tok = caster_room(client, "1 action")
    start_combat(client, dm, code)
    pass_until_mine(client, dm, code, tok)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "cast", "spell_id": "s1", "op_id": "z" + uuid.uuid4().hex[:8]})
        ev = recv_until(ws, "error")
    assert "Pick your token during combat" in ev["payload"]["msg"]
    slots = db.j(db.q1("SELECT spell_slots FROM characters WHERE id=?", (ch["id"],))["spell_slots"], {})
    assert slots["1"]["used"] == 0                 # refused casts never spend


def test_op_replay_stays_silent_despite_used_action(client):
    dm, player, code, ch, tok = caster_room(client, "1 action")
    start_combat(client, dm, code)
    pass_until_mine(client, dm, code, tok)
    op = "r" + uuid.uuid4().hex[:8]
    evs = cast(client, player, code, tok, "s1", op=op)
    assert error_msg(evs) is None, evs
    evs = cast(client, player, code, tok, "s1", op=op)     # same op, action now used
    assert error_msg(evs) is None, evs             # silent replay, NOT "No action left"
    slots = db.j(db.q1("SELECT spell_slots FROM characters WHERE id=?", (ch["id"],))["spell_slots"], {})
    assert slots["1"]["used"] == 1


def test_spell_not_found_is_answered_before_the_token_gate(client):
    dm, player, code, ch, tok = caster_room(client, "1 action")
    start_combat(client, dm, code)
    pass_until_mine(client, dm, code, tok)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "cast", "spell_id": "nope"})   # no token_id either
        ev = recv_until(ws, "error")
    assert "Spell not found" in ev["payload"]["msg"]
