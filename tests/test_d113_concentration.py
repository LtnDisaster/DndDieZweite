"""D113 (Sprint 42) Phase 2: the 2024 concentration lifecycle.

Every save runs through the ONE dice engine (``app.room.dice`` via
``room.opposed.save_roll``) forced to a known face, so each outcome is
deterministic; HP is set through the real ``hp`` WS reducer so the CONCENTRATION
response fires on the exact HP ACTUALLY lost (post any resistance/temp path).
Pins: a save holds or breaks; breaking clears the flag AND every condition the
concentration OWNS (the additive ``conc`` link) across every token, while an
unrelated condition on that token survives; DC = max(10, floor(HP/2)) with the
floor (a total of 7 loses to DC 10, not 4) and NO cap at 30 (HP 70 lost → DC 35);
going down breaks outright with no save; an incapacitated state landing breaks
outright; and the lifecycle targets ONE concentrator's linked effects only.
"""
import asyncio

import pytest
from starlette.testclient import TestClient

from app import conditions as CND, db, effectops, main
from app.room import concentration as CONC, health
from tests.test_movement_fog import (H, add_npc, join_room, make_char, reg,
                                     state_of, ws_connect)
from tests.test_d109_mastery import always, conds_of, drain


@pytest.fixture()
def client():
    return TestClient(main.app)


def rid_of(code):
    return db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]


# ---------------------------------------------------------------------------
# builders
# ---------------------------------------------------------------------------

def _room(client, hp=30, max_hp=None):
    """A room with a DM, a PC token (a real character, so the CON save uses a
    real modifier) at the default slot, and one foe NPC. ``hp`` lets a test
    provoke a > 30 concentration DC without the hit being lethal."""
    dm, pl = reg(client, "dm"), reg(client, "pl")
    code = client.post("/api/rooms", json={"name": "D113"}, headers=H(dm)).json()["code"]
    join_room(client, pl, code)
    ch = make_char(client, pl, hp=hp, max_hp=max_hp or hp)
    client.post(f"/api/rooms/{code}/assign", json={"character_id": ch["id"]}, headers=H(pl))
    pc = next(t["id"] for t in state_of(client, dm, code)["tokens"] if t.get("character_id"))
    with ws_connect(client, dm, code) as ws:
        foe = add_npc(ws, label="Foe", cx=6, cy=6)
        drain(ws)
    return dm, pl, code, pc, foe


def _focus(pc, foe):
    """``pc`` concentrates; ``foe`` carries one condition that concentration
    OWNS (``conc`` = pc's token id) plus one UNRELATED condition that must
    survive a break — the additive link is surgical, not a wipe."""
    db.x("UPDATE tokens SET conds=? WHERE id=?",
         (db.json_dumps(CND.add([], "concentrating")), pc))
    linked = CND.add(CND.add([], "entangled", conc=pc), "blinded")
    db.x("UPDATE tokens SET conds=? WHERE id=?", (db.json_dumps(linked), foe))


def _sys(room_id):
    """The announced system lines a room accumulated (the CON-check line and the
    ``loses concentration`` line are written there; the live socket only gets a
    snapshot, exactly as for every other ``sys_msg``)."""
    return " ".join(m["body"] for m in db.q(
        "SELECT body FROM messages WHERE room_id=? AND type='system' ORDER BY id",
        (room_id,)))


# ---------------------------------------------------------------------------
# the save decides — driven through the real hp reducer (public sys line)
# ---------------------------------------------------------------------------

def test_concentration_save_hold_keeps_everything(client, monkeypatch):
    dm, _, code, pc, foe = _room(client)
    rid = rid_of(code)
    _focus(pc, foe)
    always(client, monkeypatch, 20)                       # native 20 → holds
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "hp", "token_id": pc, "delta": -10})   # 10 lost → DC 10
        drain(ws)
    txt = _sys(rid)
    assert "vs DC 10" in txt and "holds" in txt
    assert CND.is_concentrating(conds_of(pc))
    assert CND.has_link(conds_of(foe), pc) and any(c["k"] == "blinded" for c in conds_of(foe))


def test_concentration_save_fail_clears_linked_across_tokens(client, monkeypatch):
    dm, _, code, pc, foe = _room(client)
    rid = rid_of(code)
    _focus(pc, foe)
    always(client, monkeypatch, 1)                        # nat 1 → total < DC 20
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "hp", "token_id": pc, "delta": -20})   # 20 lost → DC 10
        drain(ws)
    txt = _sys(rid)
    assert "vs DC 10" in txt and "BROKEN" in txt
    assert not CND.is_concentrating(conds_of(pc))
    assert not CND.has_link(conds_of(foe), pc)            # the owned condition is gone
    assert any(c["k"] == "blinded" for c in conds_of(foe))  # ... but an unrelated one stays


# ---------------------------------------------------------------------------
# DC = max(10, floor(HP/2)), uncapped — pinned from the real announced check
# ---------------------------------------------------------------------------

def test_dc_uses_the_floor_not_half(client, monkeypatch):
    dm, _, code, pc, foe = _room(client)
    rid = rid_of(code)
    _focus(pc, foe)
    always(client, monkeypatch, 1)                        # total ~7
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "hp", "token_id": pc, "delta": -8})    # 8/2 = 4 → floor to 10
        drain(ws)
    txt = _sys(rid)
    assert "vs DC 10" in txt and "BROKEN" in txt          # 7 < 10 (would hold vs DC 4)


def test_dc_is_uncapped_past_thirty(client, monkeypatch):
    dm, _, code, pc, foe = _room(client, hp=100)          # room to lose > 60 HP
    rid = rid_of(code)
    _focus(pc, foe)
    always(client, monkeypatch, 1)
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "hp", "token_id": pc, "delta": -70})   # 70/2 = 35, no cap
        drain(ws)
    txt = _sys(rid)
    assert "vs DC 35" in txt and "BROKEN" in txt


# ---------------------------------------------------------------------------
# breakers that skip the save entirely
# ---------------------------------------------------------------------------

def test_going_down_breaks_without_a_save(client, monkeypatch):
    dm, _, code, pc, foe = _room(client)
    rid = rid_of(code)
    _focus(pc, foe)
    always(client, monkeypatch, 1)                        # would fail, but must NOT roll
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "hp", "token_id": pc, "delta": -30})   # HP 30 → 0
        drain(ws)
    txt = _sys(rid)
    assert not CND.is_concentrating(conds_of(pc))
    assert not CND.has_link(conds_of(foe), pc)
    assert "loses concentration" in txt and "concentration check" not in txt


def test_incapacitated_breaks_without_a_save(client):
    dm, _, code, pc, foe = _room(client)
    rid = rid_of(code)
    _focus(pc, foe)
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "cond_add", "token_id": pc, "key": "stunned"})
        drain(ws)
    txt = _sys(rid)
    assert "Stunned" in txt and "loses concentration" in txt
    assert not CND.is_concentrating(conds_of(pc))
    assert not CND.has_link(conds_of(foe), pc)
    assert any(c["k"] == "blinded" for c in conds_of(foe))


# ---------------------------------------------------------------------------
# the lifecycle targets ONE concentrator — the two NPC casters share one victim
# ---------------------------------------------------------------------------

def _two_casters(client):
    dm = reg(client, "dm")
    code = client.post("/api/rooms", json={"name": "D113b"}, headers=H(dm)).json()["code"]
    with ws_connect(client, dm, code) as ws:
        a = add_npc(ws, label="A", cx=4, cy=4)
        b = add_npc(ws, label="B", cx=5, cy=4)
        v = add_npc(ws, label="V", cx=6, cy=4)
        drain(ws)
    db.x("UPDATE tokens SET conds=? WHERE id=?",
         (db.json_dumps(CND.add([], "concentrating")), a))
    conds = CND.add(CND.add(CND.add([], "entangled", conc=a), "hexed", conc=b), "blinded")
    db.x("UPDATE tokens SET conds=? WHERE id=?", (db.json_dumps(conds), v))
    return rid_of(code), a, b, v


def test_end_previous_clears_only_that_caster(client):
    room_id, a, b, v = _two_casters(client)
    asyncio.run(CONC.end_previous(room_id, db.q1("SELECT * FROM tokens WHERE id=?", (a,))))
    victim = conds_of(v)
    assert not CND.is_concentrating(conds_of(a))
    assert not CND.has_link(victim, a)                     # A's owned condition ends
    assert CND.has_link(victim, b)                         # B's is untouched
    assert any(c["k"] == "blinded" for c in victim)         # and an unrelated one stays


def test_break_concentration_op_clears_linked(client):
    room_id, a, b, v = _two_casters(client)
    row = db.q1("SELECT * FROM tokens WHERE id=?", (a,))
    ctx = effectops.make_ctx(room_id, caster=row, target=row, trigger="cast", conc=a)
    asyncio.run(effectops.run_ops([{"op": "break_concentration", "target": "self"}], ctx))
    victim = conds_of(v)
    assert not CND.is_concentrating(conds_of(a))
    assert not CND.has_link(victim, a) and CND.has_link(victim, b)


# ---------------------------------------------------------------------------
# the trigger-depth kill-switch: a cursed "on_damaged hurts the wearer" ring
# fires EXACTLY once — the nested damage (from_trigger_depth > 0) must not
# re-open the on_damaged seam (the D111 claim uses a fresh uid per non-combat
# hit, so only the depth gate stops the bounce; without it the budget bounces).
# ---------------------------------------------------------------------------

def test_on_damaged_recursion_is_cut_by_depth(client):
    from tests.test_d111_effects import (_hp, _mkdef, _player_char, char_items,
                                         equip, grant_item, token_of)
    from tests.test_d111_effects import _room as _r111
    users, code = _r111(client)
    dm, player = users[0], users[1]
    ch = _player_char(client, player, code, hp=30)
    tok = token_of(client, player, code, ch)
    cell = effectops.canon([{"op": "damage", "expr": "1d1", "target": "self"}])
    did = _mkdef(client, dm, code, {"effects": cell, "trigger": "on_damaged"}, name="Pain")
    grant_item(client, dm, code, ch["id"], did)
    it = next(i for i in char_items(client, player, code) if i["def_id"] == did)
    equip(client, player, code, ch["id"], it["id"], slot="acc1")
    tok_row = db.q1("SELECT * FROM tokens WHERE id=?", (tok,))
    asyncio.run(health.change_hp(rid_of(code), tok_row, -6))
    assert _hp(ch["id"])["hp"] == 23               # -6 hit + ONE -1 tick, no bounce
