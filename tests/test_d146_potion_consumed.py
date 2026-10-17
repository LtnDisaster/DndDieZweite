"""D146: potions and scrolls are CONSUMED (SRD) — the last dose leaves the
pack instead of squatting there as an empty vial. qty>1 spends one dose and
re-arms the entry; the last entry disappears inside the SAME transaction as
the heal, so a crash can never heal without consuming (or the reverse). An
entry that carries a curse always remains (D106/D113), and rechargeable
charge-items (wands & co.) keep their old depleted-shell behaviour.
"""
import uuid

import pytest
from starlette.testclient import TestClient

from app import db, main
from tests.test_combat_turn import my_token_id
from tests.test_d106_curses import _db_items, _grant_item
from tests.test_movement_fog import base_room, recv_until, ws_connect


@pytest.fixture()
def client():
    return TestClient(main.app)


def _hp(cid):
    return db.q1("SELECT hp, max_hp FROM characters WHERE id=?", (cid,))


def _use(client, user, code, tok, item_id, op_id=None, expect_error=False):
    oid = op_id or "u" + uuid.uuid4().hex[:8]
    with ws_connect(client, user, code) as ws:
        ws.send_json({"type": "use_item", "token_id": tok, "item_id": item_id,
                      "op_id": oid})
        # use_item ends with a room snapshot; refusals answer with an error.
        return recv_until(ws, "error" if expect_error else "snapshot",
                          fail_on_error=not expect_error)


def _potion(name="Healing Draught"):
    return {"name": name, "kind": "potion",
            "props": {"heal_dice": "2d4+2", "charges": 1}}


def test_last_dose_is_consumed(client):
    dm, player, code, ch = base_room(client)
    tok = my_token_id(client, player, code)
    _grant_item(client, dm, code, ch["id"], _potion())
    items = _db_items(ch["id"])
    assert len(items) == 1 and items[0]["kind"] == "potion"
    _use(client, player, code, tok, items[0]["id"])
    assert _db_items(ch["id"]) == []            # gone, not an empty vial
    _use(client, player, code, tok, items[0]["id"], expect_error=True)
    assert _db_items(ch["id"]) == []


def test_stack_loses_one_dose_and_rearms(client):
    dm, player, code, ch = base_room(client)
    tok = my_token_id(client, player, code)
    _grant_item(client, dm, code, ch["id"], _potion("Bulk Draught"), qty=3)
    ent = next(i for i in _db_items(ch["id"]) if i["name"] == "Bulk Draught")
    before = _hp(ch["id"])["hp"]
    _use(client, player, code, tok, ent["id"])
    after = [i for i in _db_items(ch["id"]) if i["name"] == "Bulk Draught"][0]
    assert after["qty"] == 2 and after["charges"] == after["chargesMax"] == 1
    assert before <= _hp(ch["id"])["hp"] <= before + 10   # healed 2d4+2 once


def test_wand_keeps_its_depleted_shell(client):
    dm, player, code, ch = base_room(client)
    tok = my_token_id(client, player, code)
    _grant_item(client, dm, code, ch["id"],
                {"name": "Spark Wand", "kind": "wand",
                 "props": {"heal_dice": "1d4", "charges": 1}})
    ent = _db_items(ch["id"])[0]
    _use(client, player, code, tok, ent["id"])
    left = _db_items(ch["id"])
    assert len(left) == 1 and left[0]["charges"] == 0    # rechargeable, stays


def test_cursed_consumable_entry_always_stays(client):
    dm, player, code, ch = base_room(client)
    tok = my_token_id(client, player, code)
    _grant_item(client, dm, code, ch["id"], _potion("Wicked Cordial"))
    items = _db_items(ch["id"])
    items[0]["curse"] = {"active": False, "trigger": "use"}   # stored trace
    db.x("UPDATE characters SET items=? WHERE id=?",
         (db.json_dumps(items), ch["id"]))
    _use(client, player, code, tok, items[0]["id"])
    left = _db_items(ch["id"])
    assert len(left) == 1 and left[0]["curse"]["trigger"] == "use"
    assert not left[0]["curse"].get("active") and left[0]["charges"] == 0


def test_replayed_op_consumes_never_twice(client):
    dm, player, code, ch = base_room(client)
    tok = my_token_id(client, player, code)
    _grant_item(client, dm, code, ch["id"], _potion("Sip of Spring"), qty=3)
    ent = next(i for i in _db_items(ch["id"]) if i["name"] == "Sip of Spring")
    oid = "u" + uuid.uuid4().hex[:8]
    _use(client, player, code, tok, ent["id"], op_id=oid)
    # A replay is SILENT by D93 design (no snapshot, no error) — settle it
    # behind a marker chat the server answers on the same socket queue.
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "use_item", "token_id": tok, "item_id": ent["id"],
                      "op_id": oid})
        mark = "SYNC" + uuid.uuid4().hex[:6]
        ws.send_json({"type": "chat", "text": mark})
        for _ in range(60):
            ev = ws.receive_json()
            if ev.get("kind") == "chat" and mark in str(ev.get("payload")):
                break
    after = [i for i in _db_items(ch["id"]) if i["name"] == "Sip of Spring"][0]
    assert after["qty"] == 2                                   # once, proven
