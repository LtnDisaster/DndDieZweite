"""D138 (AP-025): preparation is data, gated by the engine.

Audit C3: instead of hardcoding wizard ritual flows, a spell list becomes
PREP-GATED the moment it carries any spell with prep=true — casting a
prepared gate is list-wide, cantrips exempt, and refusal happens before any
slot, action or marker is touched. The CSV projects prep/prepared through
the same sheet pipeline as casting_time (D131).
"""
import uuid

import pytest
from starlette.testclient import TestClient

from app import db, main
from tests.test_movement_fog import base_room, ws_connect
from tests.test_sprint23_combat import set_progression


@pytest.fixture
def client():
    app = main.app
    with TestClient(app) as c:
        yield c


def prep_room(client, gated):
    dm, player, code, ch = base_room(client)
    flag = gated
    set_progression(ch["id"],
                    spells=[{"id": "u1", "name": "Unprepped", "level": 1, "cast": "none",
                             "prep": flag, "prepared": False},
                            {"id": "p2", "name": "Prepped", "level": 1, "cast": "none",
                             "prep": flag, "prepared": True},
                            {"id": "c0", "name": "Free", "level": 0, "cast": "none",
                             "prep": flag}],
                    spell_slots={"1": {"max": 2, "used": 0}})
    tok = db.q1("SELECT id FROM tokens WHERE character_id=?", (ch["id"],))["id"]
    return dm, player, code, ch, tok


def drain(ws, cap=70):
    ws.send_json({"type": "chat", "text": "@@prflush@@"})
    out = []
    while len(out) < cap:
        ev = ws.receive_json()
        if ev.get("kind") == "chat" and "@@prflush@@" in str(ev.get("payload", {}).get("text", "")):
            return out
        out.append(ev)
    raise AssertionError("burst never ended")


def error_of(evs):
    errs = [e for e in evs if e.get("kind") == "error"]
    return errs[0]["payload"]["msg"] if errs else None


def slots_used(ch_id):
    return db.j(db.q1("SELECT spell_slots FROM characters WHERE id=?",
                      (ch_id,))["spell_slots"], {})["1"]["used"]


def test_prep_gated_list_refuses_unprepared_without_spending(client):
    dm, player, code, ch, tok = prep_room(client, True)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "cast", "spell_id": "u1", "token_id": tok,
                      "visibility": "public", "op_id": "q" + uuid.uuid4().hex[:8]})
        assert "not prepared" in error_of(drain(ws))
    assert slots_used(ch["id"]) == 0


def test_prepared_spell_casts(client):
    dm, player, code, ch, tok = prep_room(client, True)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "cast", "spell_id": "p2", "token_id": tok,
                      "visibility": "public", "op_id": "q" + uuid.uuid4().hex[:8]})
        drain(ws)
    assert slots_used(ch["id"]) == 1


def test_cantrips_are_exempt_and_ungated_lists_free(client):
    dm, player, code, ch, tok = prep_room(client, True)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "cast", "spell_id": "c0", "token_id": tok,
                      "visibility": "public", "op_id": "q" + uuid.uuid4().hex[:8]})
        drain(ws)
    dm2, player2, code2, ch2, tok2 = prep_room(client, False)
    with ws_connect(client, player2, code2) as ws:
        ws.send_json({"type": "cast", "spell_id": "u1", "token_id": tok2,
                      "visibility": "public", "op_id": "q" + uuid.uuid4().hex[:8]})
        drain(ws)
    assert slots_used(ch2["id"]) == 1
