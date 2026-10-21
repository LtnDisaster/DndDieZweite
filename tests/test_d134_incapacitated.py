"""D134 (AP-020): the ONE 2024 Incapacitated finally rules actions, not movement.

Audit F5 closed the key list (D110); this closes the EFFECT:
`no_actions` is the new hook-grammar word. The parent condition Incapacitated
takes away actions and reactions but leaves MOVEMENT free and does NOT auto-
fail saves — the STR/DEX auto-fail belongs to paralyzed/petrified/stunned/
unconscious, which now also carry `no_actions`. Consumers: the attack path,
the casting gate (D131), the Attack/Escape choke (`_take_action`), Dash —
all validated BEFORE any slot or resource is spent. The grapple release
condition switched to the faithful proxy (`no_actions`) the SRD text names.
"""
import uuid

import pytest
from starlette.testclient import TestClient

from app import db, main
from app import conditions as C
from app.room import combat as CB
from test_d129_exhaustion import grant_equip, mk_def
from test_d131_casting_time import caster_room
from test_movement_fog import base_room, recv_until, state_of, ws_connect
from test_sprint23_combat import set_progression

CELL = 50


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


def cond_remove(client, dm, code, tok_id, key):
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "cond_remove", "token_id": tok_id, "key": key})
        recv_until(ws, "cond")


def pc_token(client, player, code):
    st = state_of(client, player, code)
    tok = next(t for t in st["tokens"] if t.get("owner_user_id") == st["me"])
    return tok


def error_of(evs):
    errs = [e for e in evs if e.get("kind") == "error"]
    return errs[0]["payload"]["msg"] if errs else None


def drain(ws, cap=80):
    ws.send_json({"type": "chat", "text": "@@incflush@@"})
    out = []
    while len(out) < cap:
        ev = ws.receive_json()
        if ev.get("kind") == "chat" and "@@incflush@@" in str(ev.get("payload", {}).get("text", "")):
            return out
        out.append(ev)
    raise AssertionError("burst never ended")


# ------------------------------------------------------------------ table

def test_the_2024_parent_condition_changed():
    assert "no_actions" in C.HOOKS
    p = C.BUILTIN_HOOKS["incapacitated"]
    assert p == {"no_actions": True}        # movement free, saves normal
    for k in ("paralyzed", "petrified", "stunned", "unconscious"):
        h = C.BUILTIN_HOOKS[k]
        assert h["no_actions"] and h["blocks_movement"] and h["auto_fail_saves"]


# ------------------------------------------------------------- consumers

def test_incapacitated_blocks_attack_and_dash_but_not_movement(client):
    from test_combat_turn import pass_until_mine, start_combat
    dm, player, code, ch = base_room(client)
    def_id = mk_def(client, dm, code, {"damage_dice": "1d8", "damage_type": "slashing",
                                       "ability": "str"}, "Blade")
    item_id = grant_equip(client, dm, player, code, ch["id"], def_id)
    tok = pc_token(client, player, code)
    start_combat(client, dm, code)
    pass_until_mine(client, dm, code, tok["id"])
    cond_add(client, dm, code, tok["id"], "incapacitated")
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "dash", "token_id": tok["id"]})
        ws.send_json({"type": "roll", "kind": "attack", "item_id": item_id,
                      "token_id": tok["id"], "visibility": "public",
                      "op_id": "x" + uuid.uuid4().hex[:8]})
        assert "can't take actions" in error_of(drain(ws))
    # movement stays free (the 2024 parent does not block it)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "move", "token_id": tok["id"],
                      "tx": int(tok["x"] // CELL) + 1, "ty": int(tok["y"] // CELL)})
        kinds = [e.get("kind") for e in drain(ws)]
    assert "step" in kinds or "snapshot" in kinds
    # the condition being gone reopens the action:
    cond_remove(client, dm, code, tok["id"], "incapacitated")
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "roll", "kind": "attack", "item_id": item_id,
                      "token_id": tok["id"], "visibility": "public",
                      "op_id": "y" + uuid.uuid4().hex[:8]})
        assert any(e.get("kind") == "dice" for e in drain(ws))


def test_incapacitated_blocks_casting_without_spending_anything(client):
    from test_combat_turn import pass_until_mine, start_combat
    dm, player, code, ch, tok = caster_room(client, "1 action")
    start_combat(client, dm, code)
    pass_until_mine(client, dm, code, tok)
    cond_add(client, dm, code, tok, "stunned")
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "cast", "spell_id": "s1", "token_id": tok,
                      "visibility": "public", "op_id": "z9"})
        assert "can't take actions" in error_of(drain(ws))
    slots = db.j(db.q1("SELECT spell_slots FROM characters WHERE id=?",
                       (ch["id"],))["spell_slots"], {})
    assert slots["1"]["used"] == 0


def test_escape_needs_an_action(client):
    from test_combat_turn import pass_until_mine, start_combat
    dm, player, code, ch = base_room(client)
    tok = pc_token(client, player, code)
    start_combat(client, dm, code)
    pass_until_mine(client, dm, code, tok["id"])
    cond_add(client, dm, code, tok["id"], "grappled", dc=15)
    cond_add(client, dm, code, tok["id"], "paralyzed")
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "escape", "token_id": tok["id"], "op_id": "e1"})
        assert "can't take actions" in error_of(drain(ws))
    conds = C.load(db.q1("SELECT * FROM tokens WHERE id=?", (tok["id"],)))
    assert any(c["k"] == "grappled" for c in conds)     # nothing freed, nothing spent
