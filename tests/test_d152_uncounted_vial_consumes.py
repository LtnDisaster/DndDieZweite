"""D152: a potion/scroll WITHOUT a charge counter (content-pack default,
charges==-1) held exactly one sip and was never consumed — it squatted in
the pack as an inexhaustible fountain. Such entries now normalize to one
dose through the tested D146 path. Charge-free items of other kinds (a
healing staff's unlimited feature) keep their unlimited behaviour.
"""
import pytest
from starlette.testclient import TestClient

from app import main
from tests.test_combat_turn import my_token_id
from tests.test_d106_curses import _db_items, _grant_item
from tests.test_d146_potion_consumed import _use
from tests.test_movement_fog import base_room


@pytest.fixture()
def client():
    return TestClient(main.app)


def _vial(name):
    return {"name": name, "kind": "potion", "props": {"heal_dice": "2d4+2"}}


def test_uncounted_potion_is_gone_after_one_drink(client):
    dm, player, code, ch = base_room(client)
    tok = my_token_id(client, player, code)
    _grant_item(client, dm, code, ch["id"], _vial("Field Draught"))
    items = _db_items(ch["id"])
    assert len(items) == 1 and items[0]["charges"] < 0   # content-pack shape
    _use(client, player, code, tok, items[0]["id"])
    assert _db_items(ch["id"]) == []                     # one sip, then gone


def test_uncounted_stack_spends_one_dose(client):
    dm, player, code, ch = base_room(client)
    tok = my_token_id(client, player, code)
    _grant_item(client, dm, code, ch["id"], _vial("Chest Case"), qty=2)
    ent = next(i for i in _db_items(ch["id"]) if i["name"] == "Chest Case")
    _use(client, player, code, tok, ent["id"])
    left = [i for i in _db_items(ch["id"]) if i["name"] == "Chest Case"]
    assert len(left) == 1 and left[0]["qty"] == 1
    _use(client, player, code, tok, left[0]["id"])
    assert [i for i in _db_items(ch["id"]) if i["name"] == "Chest Case"] == []


def test_chargeless_healer_of_other_kind_stays_unlimited(client):
    dm, player, code, ch = base_room(client)
    tok = my_token_id(client, player, code)
    _grant_item(client, dm, code, ch["id"],
                {"name": "Mercy Staff", "kind": "wand",
                 "props": {"heal_dice": "1d4"}})
    ent = next(i for i in _db_items(ch["id"]) if i["name"] == "Mercy Staff")
    _use(client, player, code, tok, ent["id"])
    _use(client, player, code, tok, ent["id"])
    left = [i for i in _db_items(ch["id"]) if i["name"] == "Mercy Staff"]
    assert len(left) == 1 and left[0]["charges"] < 0     # never normalized
