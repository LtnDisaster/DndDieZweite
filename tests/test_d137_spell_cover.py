"""D137 (AP-023): cover rides SPELL attack rolls too — the SRD knows no
attack-kind exception. Item attacks already carried half/3/4/total; the
spell paths (PC roll, PC cast, NPC roll, NPC cast) close up, and total
cover refuses the target BEFORE a slot, marker or action is spent.
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


def attack_caster(client):
    dm, player, code, ch = base_room(client)
    set_progression(ch["id"],
                    spells=[{"id": "a1", "name": "Zap", "level": 1,
                             "cast": "attack", "ability": "int",
                             "casting_time": "1 action"}],
                    spell_slots={"1": {"max": 2, "used": 0}})
    tok = db.q1("SELECT id FROM tokens WHERE character_id=?", (ch["id"],))["id"]
    return dm, player, code, ch, tok


def drain(ws, cap=70):
    ws.send_json({"type": "chat", "text": "@@covflush@@"})
    out = []
    while len(out) < cap:
        ev = ws.receive_json()
        if ev.get("kind") == "chat" and "@@covflush@@" in str(ev.get("payload", {}).get("text", "")):
            return out
        out.append(ev)
    raise AssertionError("burst never ended")


def slots_used(ch_id):
    return db.j(db.q1("SELECT spell_slots FROM characters WHERE id=?",
                      (ch_id,))["spell_slots"], {})["1"]["used"]


def dice_text(evs):
    return " | ".join(e["payload"]["text"] for e in evs if e.get("kind") == "dice")


# --------------------------------------------------------------- PC paths

def test_spell_attack_roll_carries_half_and_three_quarter(client):
    dm, player, code, ch, tok = attack_caster(client)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "roll", "kind": "spell_attack", "spell_id": "a1",
                      "cover": "three_quarters", "visibility": "public",
                      "op_id": "c" + uuid.uuid4().hex[:8]})
        t1 = dice_text(drain(ws))
    assert "vs 3/4 cover" in t1 and "-5 cover" in t1
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "roll", "kind": "spell_attack", "spell_id": "a1",
                      "cover": "half", "visibility": "public",
                      "op_id": "c" + uuid.uuid4().hex[:8]})
        t2 = dice_text(drain(ws))
    assert "vs half cover" in t2 and "-2 cover" in t2


def test_total_cover_refuses_target_without_spending(client):
    dm, player, code, ch, tok = attack_caster(client)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "cast", "spell_id": "a1", "token_id": tok,
                      "cover": "total", "visibility": "public",
                      "op_id": "c" + uuid.uuid4().hex[:8]})
        t = dice_text(drain(ws))
    assert "can't be targeted" in t
    assert slots_used(ch["id"]) == 0


def test_cast_attack_spell_with_three_quarter_cover(client):
    dm, player, code, ch, tok = attack_caster(client)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "cast", "spell_id": "a1", "token_id": tok,
                      "cover": "three_quarters", "visibility": "public",
                      "op_id": "c" + uuid.uuid4().hex[:8]})
        t = dice_text(drain(ws))
    assert "vs 3/4 cover" in t
    assert slots_used(ch["id"]) == 1


def test_plain_spell_attack_text_unchanged(client):
    dm, player, code, ch, tok = attack_caster(client)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "roll", "kind": "spell_attack", "spell_id": "a1",
                      "visibility": "public", "op_id": "c" + uuid.uuid4().hex[:8]})
        t = dice_text(drain(ws))
    assert "cover" not in t and "Zap attack" in t
