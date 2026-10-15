"""D113 (Sprint 42) Phase 5: data-driven traps.

A trap is a MAP ENTITY, not a CSV row (no traps.csv). Its resolution runs on the
ONE effect grammar (save/check/damage/condition), never a second dice/save
engine; discovery (Wisdom/Perception vs search_dc) and disarming (a server
Dexterity CHECK vs disarm_dc — labelled honestly, the engine has NO tool
proficiency so it is never called a "Thieves' tools" check) reuse opposed's
participant/check_roll. A legacy trap's save d20 also rolls through app.room.dice
(D114), so every outcome is deterministic and no path carries a private RNG. The
surface is leak-safe: a search against an absent cell and a missed search against
a HIDDEN trap answer byte-identically, so the endpoint is never a trap oracle. A
legacy trap (dc/dmg, no effects) keeps the byte-identical one-shot path and never
gains a stray key.
"""
import uuid

import pytest
from starlette.testclient import TestClient

from app import db, main
from tests.test_movement_fog import (base_room, park, recv_until, set_grid,
                                     state_of, ws_connect)
from tests.test_d109_mastery import always, conds_of, drain


@pytest.fixture()
def client():
    return TestClient(main.app)


# effect cell: a DEX save or you are knocked prone (no damage dice → deterministic)
EFFECTS = {"ops": [{"op": "save", "ability": "dex", "dc": 15, "success": [],
                    "failure": [{"op": "condition", "key": "prone", "until": "end",
                                 "target": "target"}]}]}


def ptoken(client, player, code):
    st = state_of(client, player, code)
    return next(t["id"] for t in st["tokens"] if t.get("owner_user_id") == st["me"])


def put_trap(client, dm, code, x, y, **fields):
    tid = "t" + uuid.uuid4().hex[:10]

    def mut(g):
        g["traps"] = [dict({"id": tid, "x": x, "y": y, "label": "Glyph of Warding"},
                           **fields)]
    set_grid(client, dm, code, mut)
    return tid


def dm_grid(client, dm, code):
    return state_of(client, dm, code)["grid"]["traps"]


def trap_reply(client, user, code, payload, kind="whisper"):
    with ws_connect(client, user, code) as ws:
        ws.send_json({"type": "trap", **payload})
        return recv_until(ws, kind, fail_on_error=(kind == "whisper"))["payload"]["text"]


# --------------------------------------------------------------------------- #
# 1-2. schema round-trips: legacy byte-identical, modern additive
# --------------------------------------------------------------------------- #

def test_legacy_trap_roundtrips_without_stray_keys(client):
    dm, player, code, ch = base_room(client)
    tid = put_trap(client, dm, code, 20, 12, dc=18, dmg="1d4")
    trap = next(t for t in dm_grid(client, dm, code) if t["id"] == tid)
    assert trap["dc"] == 18 and trap["dmg"] == "1d4"
    for absent in ("effects", "search_dc", "disarm_dc", "repeat", "trigger", "disarmed"):
        assert absent not in trap, f"legacy trap gained a stray {absent!r} key"


def test_effects_trap_stored_and_legacy_untouched(client):
    dm, player, code, ch = base_room(client)
    tid = put_trap(client, dm, code, 20, 12, effects=EFFECTS, search_dc=12, disarm_dc=15)
    trap = next(t for t in dm_grid(client, dm, code) if t["id"] == tid)
    assert "effects" in trap and "dc" not in trap            # modern driver, no legacy dc
    assert trap["search_dc"] == 12 and trap["disarm_dc"] == 15


def test_invalid_effect_cell_is_dropped(client):
    dm, player, code, ch = base_room(client)
    tid = put_trap(client, dm, code, 20, 12, dc=12, dmg="1d4",
                   effects={"ops": [{"op": "not_a_real_op"}]})
    trap = next(t for t in dm_grid(client, dm, code) if t["id"] == tid)
    assert "effects" not in trap                             # fail-closed: bad cell dropped
    assert trap["dc"] == 12                                  # the trap is still a trap


# --------------------------------------------------------------------------- #
# 3-4. the grammar springs the trap (through the effect engine) + re-arm flags
# --------------------------------------------------------------------------- #

def test_effects_trap_springs_grammar_on_trigger(client, monkeypatch):
    dm, player, code, ch = base_room(client)
    tok = ptoken(client, player, code)
    park(client, dm, code, tok, 16, 12)
    tok = ptoken(client, player, code)
    put_trap(client, dm, code, 16, 12, effects=EFFECTS)
    always(client, monkeypatch, 1)                           # d20=1 → dex save fails
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "trap", "action": "trigger", "token_id": tok,
                      "x": 16, "y": 12, "target_id": tok})
        recv_until(ws, "map_changed")
    assert "prone" in [c["k"] for c in conds_of(tok)]        # grammar failure branch applied
    assert db.q1("SELECT hp FROM characters WHERE id=?", (ch["id"],))["hp"] == 30  # no damage in this cell


def test_repeat_keeps_armed_vs_one_shot(client, monkeypatch):
    dm, player, code, ch = base_room(client)
    tok = ptoken(client, player, code)
    park(client, dm, code, tok, 16, 12); tok = ptoken(client, player, code)
    one = put_trap(client, dm, code, 16, 12, effects=EFFECTS)
    always(client, monkeypatch, 1)
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "trap", "action": "trigger", "token_id": tok,
                      "x": 16, "y": 12, "target_id": tok})
        recv_until(ws, "map_changed")
    assert next(t for t in dm_grid(client, dm, code) if t["id"] == one)["triggered"] is True

    rep = put_trap(client, dm, code, 16, 12, effects=EFFECTS, repeat=True)
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "trap", "action": "trigger", "token_id": tok,
                      "x": 16, "y": 12, "target_id": tok})
        recv_until(ws, "map_changed")
    assert next(t for t in dm_grid(client, dm, code) if t["id"] == rep)["triggered"] is False


# --------------------------------------------------------------------------- #
# 5-6. leak-safe discovery
# --------------------------------------------------------------------------- #

def test_search_discovers_and_never_leaks(client, monkeypatch):
    dm, player, code, ch = base_room(client)
    tok = ptoken(client, player, code)
    park(client, dm, code, tok, 16, 12); tok = ptoken(client, player, code)

    # a player CANNOT see a hidden trap on the wire before discovering it
    put_trap(client, dm, code, 17, 12, effects=EFFECTS, search_dc=12)
    assert [t for t in state_of(client, player, code)["grid"]["traps"]] == []

    # MISSED search vs a hidden trap == search of an empty cell (identical reply)
    always(client, monkeypatch, 1)                           # d20=1 → fail DC12
    miss_hidden = trap_reply(client, player, code, {"action": "search", "token_id": tok, "x": 17, "y": 12})
    miss_empty = trap_reply(client, player, code, {"action": "search", "token_id": tok, "x": 15, "y": 12})
    assert miss_hidden == miss_empty                         # no oracle: byte-identical

    # SUCCESSFUL search reveals it to everyone (grid now carries the trap)
    always(client, monkeypatch, 20)
    found = trap_reply(client, player, code, {"action": "search", "token_id": tok, "x": 17, "y": 12})
    assert "found" in found
    assert [t["id"] for t in state_of(client, player, code)["grid"]["traps"]]  # discovered → visible


def test_trap_without_search_dc_is_indistinguishable(client, monkeypatch):
    dm, player, code, ch = base_room(client)
    tok = ptoken(client, player, code)
    park(client, dm, code, tok, 16, 12); tok = ptoken(client, player, code)
    put_trap(client, dm, code, 17, 12, effects=EFFECTS)      # no search_dc → not findable
    always(client, monkeypatch, 20)
    miss = trap_reply(client, player, code, {"action": "search", "token_id": tok, "x": 17, "y": 12})
    empty = trap_reply(client, player, code, {"action": "search", "token_id": tok, "x": 15, "y": 12})
    assert miss == empty and "found" not in miss


# --------------------------------------------------------------------------- #
# 7-8. disarming (Dexterity check vs disarm_dc)
# --------------------------------------------------------------------------- #

def test_disarm_success_and_fail(client, monkeypatch):
    dm, player, code, ch = base_room(client)
    tok = ptoken(client, player, code)
    park(client, dm, code, tok, 16, 12); tok = ptoken(client, player, code)
    tid = put_trap(client, dm, code, 16, 12, effects=EFFECTS, disarm_dc=15, discovered=True)

    always(client, monkeypatch, 1)                           # fail
    fail = trap_reply(client, player, code, {"action": "disarm", "token_id": tok, "x": 16, "y": 12})
    assert "fail" in fail
    assert next(t for t in dm_grid(client, dm, code) if t["id"] == tid).get("disarmed") is not True

    always(client, monkeypatch, 20)                          # succeed
    ok = trap_reply(client, player, code, {"action": "disarm", "token_id": tok, "x": 16, "y": 12})
    assert "disarmed" in ok
    t = next(t for t in dm_grid(client, dm, code) if t["id"] == tid)
    assert t["disarmed"] is True and t["triggered"] is True   # disarmed → never springs


def test_disarm_requires_a_discovered_trap(client, monkeypatch):
    dm, player, code, ch = base_room(client)
    tok = ptoken(client, player, code)
    park(client, dm, code, tok, 16, 12); tok = ptoken(client, player, code)
    put_trap(client, dm, code, 16, 12, effects=EFFECTS, disarm_dc=15)   # hidden
    always(client, monkeypatch, 20)
    r = trap_reply(client, player, code, {"action": "disarm", "token_id": tok, "x": 16, "y": 12})
    assert r == "There is nothing here to disarm."           # never acknowledges a hidden trap


def test_player_cannot_force_spring(client):
    dm, player, code, ch = base_room(client)
    tok = ptoken(client, player, code)
    park(client, dm, code, tok, 16, 12); tok = ptoken(client, player, code)
    put_trap(client, dm, code, 16, 12, effects=EFFECTS)
    with pytest.raises(AssertionError):                       # recv_until surfaces the error
        trap_reply(client, player, code, {"action": "trigger", "token_id": tok,
                                          "x": 16, "y": 12, "target_id": tok})


# --------------------------------------------------------------------------- #
# D114 Phase 2: the legacy save uses the ONE dice engine; disarm is honestly
# labelled a Dexterity check (the engine models no tool proficiency).
# --------------------------------------------------------------------------- #

def test_legacy_trap_save_rolls_through_the_dice_engine(client, monkeypatch):
    # A legacy trap (dc/dmg, no effects) used to roll its save d20 with a local
    # random.randint. D114 routes it through dice.do_roll, so forcing the d20 via
    # the one engine is deterministic — proof the legacy path has no private RNG.
    dm, player, code, ch = base_room(client)
    tok = ptoken(client, player, code)
    park(client, dm, code, tok, 16, 12); tok = ptoken(client, player, code)
    db.x("UPDATE characters SET hp=30 WHERE id=?", (ch["id"],))
    put_trap(client, dm, code, 16, 12, dc=12, dmg="1d4")        # legacy trap (no effects)
    always(client, monkeypatch, 20)                            # d20=20 (+dex) → save succeeds
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "trap", "action": "trigger", "token_id": tok,
                      "x": 16, "y": 12, "target_id": tok})
        recv_until(ws, "map_changed")
    assert db.q1("SELECT hp FROM characters WHERE id=?", (ch["id"],))["hp"] == 30  # saved

    put_trap(client, dm, code, 16, 12, dc=12, dmg="1d4")        # re-place (one-shot re-arms)
    always(client, monkeypatch, 1)                             # d20=1 → save fails; dmg die=1
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "trap", "action": "trigger", "token_id": tok,
                      "x": 16, "y": 12, "target_id": tok})
        recv_until(ws, "map_changed")
    assert db.q1("SELECT hp FROM characters WHERE id=?", (ch["id"],))["hp"] == 29  # 1d4 → 1


def test_disarm_is_labelled_a_dexterity_check(client, monkeypatch):
    dm, player, code, ch = base_room(client)
    tok = ptoken(client, player, code)
    park(client, dm, code, tok, 16, 12); tok = ptoken(client, player, code)
    put_trap(client, dm, code, 16, 12, effects=EFFECTS, disarm_dc=15, discovered=True)
    always(client, monkeypatch, 20)
    ok = trap_reply(client, player, code, {"action": "disarm", "token_id": tok, "x": 16, "y": 12})
    assert "Dexterity" in ok and "Thieves" not in ok          # honest label, no false tool claim
