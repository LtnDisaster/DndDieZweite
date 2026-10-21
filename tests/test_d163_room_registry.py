"""D163-1: room-scoped ability registry.

The content DB was always room-scoped (PK kind,room_id,id) but the ability
registry collapsed every room's ids into one bare key: importing a spell with
an existing id in room B silently re-defined room A's LIVE definition (last
writer won globally). These tests pin the fix: a non-zero room context resolves
the room's own definition first; the bare key keeps its legacy last-writer
meaning for manual/global definitions; a room neither owns nor imports gets
nothing; a "restart" reload repopulates each room independently.
"""
import pytest
from starlette.testclient import TestClient

from app import abilities, content as C, db, main
from tests.test_movement_fog import base_room
from tests.test_content import _post


@pytest.fixture()
def client():
    return TestClient(main.app)


def _spell(name_a, dice):
    return ("id,name,level,casting_ability,targeting,resolution,save,on_save,"
            "damage_dice,damage_type\n"
            f"d163_bolt,{name_a},2,int,single,save,dex,half,{dice},fire\n").encode()


def _rid(code):
    return db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]


def test_same_id_two_rooms_resolve_independently(client):
    dm_a, _p, code_a, _ch = base_room(client)
    dm_b, _p, code_b, _ch = base_room(client)
    rid_a, rid_b = _rid(code_a), _rid(code_b)
    assert _post(client, dm_a, code_a, _spell("Bolt of A", "1d6"),
                 name="spells.csv").json()["ok"]
    assert _post(client, dm_b, code_b, _spell("Bolt of B", "8d6"),
                 name="spells.csv").json()["ok"]
    a = abilities.get("d163_bolt", rid_a)
    b = abilities.get("d163_bolt", rid_b)
    assert a is not None and b is not None
    assert a["damage"] == "1d6" and a["name"] == "Bolt of A"
    # before D163-1 this was A's 1d6 too — the exact cross-room clobber:
    assert b["damage"] == "8d6" and b["name"] == "Bolt of B"


def test_room_without_the_row_resolves_none(client):
    dm, _p, code, _ch = base_room(client)
    other, _p2, code2, _ch2 = base_room(client)
    assert _post(client, dm, code, _spell("Only Here", "2d6"),
                 name="spells.csv").json()["ok"]
    assert abilities.get("d163_bolt", _rid(code2)) is None


def test_upsert_updates_only_its_own_room(client):
    dm_a, _p, code_a, _ch = base_room(client)
    dm_b, _p, code_b, _ch = base_room(client)
    rid_a, rid_b = _rid(code_a), _rid(code_b)
    _post(client, dm_a, code_a, _spell("Bolt of A", "1d6"), name="spells.csv")
    _post(client, dm_b, code_b, _spell("Bolt of B", "8d6"), name="spells.csv")
    rep = _post(client, dm_a, code_a, _spell("Bolt of A", "3d6"),
                name="spells.csv", mode="upsert")
    assert rep.json()["ok"]
    assert abilities.get("d163_bolt", rid_a)["damage"] == "3d6"
    assert abilities.get("d163_bolt", rid_b)["damage"] == "8d6"


def test_manual_registration_stays_global_fallback(client):
    dm, _p, code, _ch = base_room(client)
    abilities.register({"id": "d163_manual", "name": "Manual", "ability": "int",
                        "range_ft": 30, "targeting": "single",
                        "resolution": "auto", "damage": "1d4",
                        "damage_type": "radiant"})
    # room-less definitions remain reachable as fallback from any room (D163-1
    # documents this as the global/manual lane — room rows always win)
    assert abilities.get("d163_manual", _rid(code)) is not None
    abilities.unregister("d163_manual")


def test_restart_reload_keeps_rooms_independent(client):
    dm_a, _p, code_a, _ch = base_room(client)
    dm_b, _p, code_b, _ch = base_room(client)
    rid_a, rid_b = _rid(code_a), _rid(code_b)
    _post(client, dm_a, code_a, _spell("Bolt of A", "1d6"), name="spells.csv")
    _post(client, dm_b, code_b, _spell("Bolt of B", "8d6"), name="spells.csv")
    abilities.clear_registry()                     # simulate restart
    assert C.load_registered_abilities() >= 2
    assert abilities.get("d163_bolt", rid_a)["damage"] == "1d6"
    assert abilities.get("d163_bolt", rid_b)["damage"] == "8d6"
