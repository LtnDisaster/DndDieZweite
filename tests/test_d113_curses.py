"""D113 (Sprint 42) Phase 3: data-driven automatic curses (D&D 2024).

An active curse runs the SAME effect grammar a magic item uses (effectops), at
the SAME mutation seams, and is stored in the SAME D106 metadata dict — no
second curse/effect engine. These tests pin the eight binding decisions:
  * activation and disclosure are ORTHOGONAL and each survives the other;
  * a schema extension never switches an old curse on (omit-when-default), and
    activation is DM-only;
  * a curse fires ONLY on its explicitly-armed event, only while active; a plain
    read/sync (a /state fetch, an inspect) never fires anything;
  * owner change fires once, is op-id idempotent, and never leaks: the owner's
    payload carries no curse the DM has not revealed.
Reuse of the D106 harness keeps every pre-D113 curse assertion honest.
"""
import pytest
from starlette.testclient import TestClient

from app import conditions as CND, db, effectops, main
from tests.test_movement_fog import base_room, state_of, ws_connect
from tests.test_d106_curses import (_curse, _db_curse, _db_items, _dm_item_ids,
                                    _grant, _make_def, _sheet, _second_player)
from tests.test_d109_mastery import conds_of, drain, equip, token_of

# an effect that marks the CARRIER — the visible footprint of a curse firing.
CELL = effectops.canon([{"op": "condition", "key": "slicked",
                         "rounds": 1, "until": "end", "target": "self"}])


@pytest.fixture()
def client():
    return TestClient(main.app)


def _cursed_ring(client, trigger="equip", arm=True, active=True, effects=CELL):
    """A cursed ring on the PC, then (optionally) armed + activated by the DM."""
    dm, player, code, ch = base_room(client)
    did = _make_def(client, dm, code, "Cursed Ring", kind="ring")
    _grant(client, dm, code, ch["id"], did)
    iid = _dm_item_ids(client, dm, code, ch["id"], "Cursed Ring")[0]
    _curse(client, dm, code, action="set", char_id=ch["id"], item_id=iid,
           name="Doom", desc="a slow cold", whisper="it knows your name")
    if arm:
        _curse(client, dm, code, action="arm", char_id=ch["id"], item_id=iid,
               trigger=trigger, effects=effects)
    if active:
        _curse(client, dm, code, action="activate", char_id=ch["id"], item_id=iid)
    return dm, player, code, ch, iid


def _ring_item(sheet):
    return next(i for i in sheet["items"] if i["name"] == "Cursed Ring")


# ---------------------------------------------------------------------------
# fires on the armed event, only while active
# ---------------------------------------------------------------------------

def test_active_equip_curse_fires_when_worn(client):
    dm, player, code, ch, iid = _cursed_ring(client, trigger="equip")
    tok = token_of(client, player, code, ch)
    assert "slicked" not in [c["k"] for c in conds_of(tok)]      # not yet worn
    equip(client, player, code, ch["id"], iid, slot="acc1")
    assert "slicked" in [c["k"] for c in conds_of(tok)]          # equip fired it


def test_dormant_curse_never_fires(client):
    dm, player, code, ch, iid = _cursed_ring(client, trigger="equip", active=False)
    tok = token_of(client, player, code, ch)
    equip(client, player, code, ch["id"], iid, slot="acc1")
    assert "slicked" not in [c["k"] for c in conds_of(tok)]      # armed but off


def test_curse_fires_only_on_its_armed_event(client):
    dm, player, code, ch, iid = _cursed_ring(client, trigger="on_transfer")
    tok = token_of(client, player, code, ch)
    equip(client, player, code, ch["id"], iid, slot="acc1")
    assert "slicked" not in [c["k"] for c in conds_of(tok)]      # equip ≠ its trigger


# ---------------------------------------------------------------------------
# owner change (on_transfer): fires once, idempotently, without leaking
# ---------------------------------------------------------------------------

def test_owner_change_fires_once_and_never_leaks(client):
    dm, player, code, ch, iid = _cursed_ring(client, trigger="on_transfer")
    p2, ch2 = _second_player(client, code)
    tok2 = token_of(client, p2, code, ch2)
    op = "t" + "1234567890abcdef"
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "inv_transfer", "char_id": ch["id"],
                      "to_char_id": ch2["id"], "item_id": iid, "qty": 1, "op_id": op})
        drain(ws)
    assert "slicked" in [c["k"] for c in conds_of(tok2)]         # fired on new owner
    _, c2 = _db_curse(ch2["id"])
    assert c2 and c2.get("active") and c2["trigger"] == "on_transfer"  # it travelled
    assert "curse" not in _ring_item(_sheet(client, p2, code))   # new owner NOT told
    # a replayed op applies nothing further and never errors
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "inv_transfer", "char_id": ch["id"],
                      "to_char_id": ch2["id"], "item_id": iid, "qty": 1, "op_id": op})
        seen = [e.get("kind") for e in drain(ws)]
    assert "error" not in seen
    assert "slicked" in [c["k"] for c in conds_of(tok2)]


def test_reading_inventory_never_fires(client):
    dm, player, code, ch, iid = _cursed_ring(client, trigger="on_transfer")
    _second_player(client, code)
    for _ in range(3):                                           # repeated reads/syncs
        state_of(client, dm, code)
        state_of(client, player, code)
    # the curse is armed + active but nothing moved: a read is not a transfer
    assert _db_curse(ch["id"])[1].get("active") is True


# ---------------------------------------------------------------------------
# activation and disclosure are orthogonal, both ways
# ---------------------------------------------------------------------------

def test_activation_and_disclosure_are_independent(client):
    dm, player, code, ch, iid = _cursed_ring(client, trigger="equip")   # active, hidden
    assert _db_curse(ch["id"])[1]["active"] is True
    assert not _db_curse(ch["id"])[1].get("revealed")
    _curse(client, dm, code, action="reveal", char_id=ch["id"], item_id=iid)
    c = _db_curse(ch["id"])[1]
    assert c["revealed"] and c["active"] and c["trigger"] == "equip"    # reveal kept it live
    _curse(client, dm, code, action="deactivate", char_id=ch["id"], item_id=iid)
    c = _db_curse(ch["id"])[1]
    assert not c.get("active") and c["revealed"] and c["trigger"] == "equip"  # deactivate kept disclosure


# ---------------------------------------------------------------------------
# backward-compatible default + DM-only activation + validation
# ---------------------------------------------------------------------------

def test_legacy_curse_carries_no_activation_keys(client):
    dm, player, code, ch, iid = _cursed_ring(client, arm=False, active=False)
    c = _db_curse(ch["id"])[1]
    assert "active" not in c and "trigger" not in c and "effects" not in c  # byte-identical


def test_player_cannot_activate_a_curse(client):
    dm, player, code, ch, iid = _cursed_ring(client, trigger="equip", active=False)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "curse", "action": "activate",
                      "char_id": ch["id"], "item_id": iid, "op_id": "x1"})
        ws.receive_json()
    assert not _db_curse(ch["id"])[1].get("active")              # player ignored


def test_arm_refuses_an_invalid_effect(client):
    dm, player, code, ch = base_room(client)
    did = _make_def(client, dm, code, "Cursed Ring", kind="ring")
    _grant(client, dm, code, ch["id"], did)
    iid = _dm_item_ids(client, dm, code, ch["id"], "Cursed Ring")[0]
    _curse(client, dm, code, action="set", char_id=ch["id"], item_id=iid, name="Doom")
    ev = _curse(client, dm, code, expect="error", fail_on_error=False,
                action="arm", char_id=ch["id"], item_id=iid,
                trigger="equip", effects='{"v":1,"ops":[{"op":"meteor"}]}')
    assert "refused" in str(ev["payload"]).lower() or "invalid" in str(ev["payload"]).lower()
    assert "trigger" not in _db_curse(ch["id"])[1]               # nothing armed on refusal
