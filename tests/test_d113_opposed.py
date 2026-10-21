"""D113 (Sprint 42) Phase 4: the effect grammar grows to v2 with an ``opposed``
op, while v1 cells keep working byte-identically.

Two halves: the closed-world validator now accepts v1 AND v2 (refuses anything
else, and refuses ``opposed`` under v1), and canon() PRESERVES a cell's own
version so adopting v2 never rewrites stored content. The op itself is decided
by ``room.opposed`` — the same primitive a grapple/shove/steal use — so there is
no second opposed engine and no new dice. Dice are forced through the ONE engine
(``room.dice``), so a 20-vs-1 check is deterministic whatever the modifiers are.
"""
import asyncio

import pytest
from starlette.testclient import TestClient

from app import db, effectops, main
from tests.test_movement_fog import add_npc, base_room, ws_connect
from tests.test_d109_mastery import conds_of, token_of
from app.room import dice as RD


@pytest.fixture()
def client():
    return TestClient(main.app)


OPPOSED = {"v": 2, "ops": [{"op": "opposed", "ability": "str", "tie": "defender",
                            "success": [{"op": "condition", "key": "prone",
                                         "rounds": 1, "until": "end", "target": "target"}],
                            "failure": [{"op": "condition", "key": "restrained",
                                         "rounds": 1, "until": "end", "target": "target"}]}]}


def _seq(monkeypatch, vals):
    it = iter(vals)
    monkeypatch.setattr(RD.random, "randint", lambda a, b: next(it))


# ------------------------------ validator (unit) ----------------------------

def test_v2_is_accepted_and_v1_still_is():
    assert effectops.validate(OPPOSED)                        # v2 opposed is legal
    assert effectops.validate({"v": 1, "ops": [{"op": "heal", "expr": "1d4"}]})


def test_v3_refused_and_opposed_needs_v2():
    with pytest.raises(effectops.EffectError):
        effectops.validate({"v": 3, "ops": [{"op": "heal", "expr": "1d4"}]})
    with pytest.raises(effectops.EffectError):
        effectops.validate(dict(OPPOSED, v=1))                 # opposed under v1 → refused


def test_opposed_needs_both_branches():
    with pytest.raises(effectops.EffectError):
        effectops.validate({"v": 2, "ops": [{"op": "opposed", "ability": "str",
                                             "success": []}]})


def test_canon_preserves_version():
    assert '"v":1' in effectops.canon([{"op": "heal", "expr": "1d4"}])   # bare list stays v1
    assert '"v":1' in effectops.canon({"v": 1, "ops": [{"op": "heal", "expr": "1d4"}]})
    assert '"v":2' in effectops.canon(OPPOSED)                 # only an explicit v2 → v2


# ------------------------------ execution (end-to-end) ----------------------

def _two_tokens(client):
    dm, player, code, ch = base_room(client)
    with ws_connect(client, dm, code) as ws:
        b = add_npc(ws, label="Foe", cx=8, cy=8)
    a = token_of(client, player, code, ch)
    room_id = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
    return room_id, db.q1("SELECT * FROM tokens WHERE id=?", (a,)), \
        db.q1("SELECT * FROM tokens WHERE id=?", (b,))


def test_opposed_success_branch(client, monkeypatch):
    room_id, A, B = _two_tokens(client)
    ctx = effectops.make_ctx(room_id, caster=A, target=B, trigger="manual")
    ctx["self"] = A
    _seq(monkeypatch, [20, 1])                                 # A rolls 20, B rolls 1
    asyncio.run(effectops.run_ops(effectops.validate(OPPOSED), ctx))
    assert "prone" in [c["k"] for c in conds_of(B["id"])]      # A won → success ran
    assert any("opposed" in l and "SUCCESS" in l for l in ctx["log"])


def test_opposed_failure_branch(client, monkeypatch):
    room_id, A, B = _two_tokens(client)
    ctx = effectops.make_ctx(room_id, caster=A, target=B, trigger="manual")
    ctx["self"] = A
    _seq(monkeypatch, [1, 20])                                 # A rolls 1, B rolls 20
    asyncio.run(effectops.run_ops(effectops.validate(OPPOSED), ctx))
    assert "restrained" in [c["k"] for c in conds_of(B["id"])]  # A lost → failure ran
    assert any("FAILURE" in l for l in ctx["log"])
