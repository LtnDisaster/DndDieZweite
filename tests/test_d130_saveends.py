"""D130 (AP-016): Save Ends.

A condition instance may carry `sa` (the save ability) plus `dc`; at the END of
the affected creature's OWN turn the engine repeats the save through the ONE
existing derivation (opposed.save_roll / beats_dc) and a success removes
exactly that entry. No second clock: this rides the existing end-of-turn
moment; entries without `sa` (incl. every pre-D130 entry and every grapple)
are untouched. Deterministic expectations: the fixture sheet has dex 14 / wis
12 (Fighter: saves proficient are str+con) — DC 1 on a dex save can never
fail, DC 30 on a wis save can never succeed. NPC blocks default every ability
to 10 (mod +0) — DC 1 still can never fail.
"""
import pytest
from starlette.testclient import TestClient

from app import db, main
from app import conditions as C
from app.room import combat as CB
from test_combat_turn import pass_until_mine, start_combat
from test_movement_fog import (H, base_room, make_char, reg, recv_until,
                               ws_connect)


@pytest.fixture
def client():
    app = main.app
    with TestClient(app) as c:
        yield c


def cond_add(client, dm, code, tok_id, key, **kw):
    msg = {"type": "cond_add", "token_id": tok_id, "key": key}
    msg.update(kw)
    with ws_connect(client, dm, code) as ws:
        ws.send_json(msg)
        recv_until(ws, "cond")


def conds_of(tok_id):
    return C.load(db.q1("SELECT * FROM tokens WHERE id=?", (tok_id,)))


def sys_has(code, needle):
    rid = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
    return db.q1("SELECT 1 AS ok FROM messages WHERE room_id=? AND type='system' "
                 "AND body LIKE ?", (rid, f"%{needle}%")) is not None


# ---------------------------------------------------------------- unit: data

def test_sa_field_round_trips_and_validates():
    lst = C.add([], "poisoned", dc=12, sa="con")
    assert lst[0]["sa"] == "con" and lst[0]["dc"] == 12
    assert C.add([], "poisoned", sa="xx") == C.add([], "poisoned")      # invalid sa = absent
    assert C.add([], "poisoned", sa="") == C.add([], "poisoned")
    # pre-D130 entries (no sa) round-trip byte-identically:
    assert C.clean_conds([{"k": "prone", "rounds": 0, "until": ""}]) == \
        [{"k": "prone", "rounds": 0, "until": ""}]
    # a refresh can add sa to an existing instance:
    refreshed = C.add(C.add([], "poisoned", dc=12), "poisoned", dc=12, sa="wis")
    assert refreshed[0]["sa"] == "wis" and len(refreshed) == 1


# ------------------------------------------------------- engine: end of turn

def test_save_at_end_of_own_turn_ends_the_condition(client):
    dm, player, code, ch = base_room(client)
    tok = db.q1("SELECT * FROM tokens WHERE room_id=? AND character_id=?",
                (db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"], ch["id"]))
    cond_add(client, dm, code, tok["id"], "poisoned", dc=1, sa="dex")
    assert any(c["k"] == "poisoned" for c in conds_of(tok["id"]))
    start_combat(client, dm, code)
    init = pass_until_mine(client, dm, code, tok["id"])
    assert init["turn"]["token_id"] == tok["id"]
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "end_turn"})
        recv_until(ws, "initiative")
    assert not any(c["k"] == "poisoned" for c in conds_of(tok["id"]))
    assert sys_has(code, "save at end of turn")
    assert sys_has(code, "the condition ends")


def test_failed_save_keeps_the_instance_with_its_dc(client):
    dm, player, code, ch = base_room(client)
    tok = db.q1("SELECT * FROM tokens WHERE room_id=? AND character_id=?",
                (db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"], ch["id"]))
    cond_add(client, dm, code, tok["id"], "stunned", dc=30, sa="wis")
    start_combat(client, dm, code)
    pass_until_mine(client, dm, code, tok["id"])
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "end_turn"})
        recv_until(ws, "initiative")
    entry = next(c for c in conds_of(tok["id"]) if c["k"] == "stunned")
    assert entry["dc"] == 30 and entry["sa"] == "wis"
    assert sys_has(code, "it stays")


def test_another_creatures_turn_does_not_roll_your_save(client):
    dm, player, code, ch = base_room(client)
    tok = db.q1("SELECT * FROM tokens WHERE room_id=? AND character_id=?",
                (db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"], ch["id"]))
    start_combat(client, dm, code)
    # park the condition on MY token BEFORE advancing toward my turn: every
    # intermediate end-of-turn belongs to a DIFFERENT creature.
    cond_add(client, dm, code, tok["id"], "poisoned", dc=1, sa="dex")
    init = CB.get_init(db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"])
    if init["turn"]["token_id"] != tok["id"]:
        with ws_connect(client, dm, code) as ws:
            ws.send_json({"type": "init_next"})
            recv_until(ws, "initiative")
    assert any(c["k"] == "poisoned" for c in conds_of(tok["id"]))


def test_dc_only_entries_are_never_auto_saved(client):
    dm, player, code, ch = base_room(client)
    tok = db.q1("SELECT * FROM tokens WHERE room_id=? AND character_id=?",
                (db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"], ch["id"]))
    cond_add(client, dm, code, tok["id"], "poisoned", dc=5)   # escape-style DC, no sa
    start_combat(client, dm, code)
    pass_until_mine(client, dm, code, tok["id"])
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "end_turn"})
        recv_until(ws, "initiative")
    entry = next(c for c in conds_of(tok["id"]) if c["k"] == "poisoned")
    assert entry.get("sa") is None and entry["dc"] == 5
    assert not sys_has(code, "save at end of turn")


def test_npc_saves_at_end_of_its_own_turn(client):
    dm, player, code, ch = base_room(client)
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "add_token", "label": "Goblin", "x": 700, "y": 700,
                      "npc": {"name": "Goblin", "hp": 7}})
        nid = recv_until(ws, "token_add")["payload"]["id"]
    cond_add(client, dm, code, nid, "restrained", dc=1, sa="dex")   # npc mod +0: dc 1 never fails
    start_combat(client, dm, code)
    pass_until_mine(client, dm, code, nid)
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "init_next"})
        recv_until(ws, "initiative")
    assert not any(c["k"] == "restrained" for c in conds_of(nid))
