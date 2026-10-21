"""D147: attuning to an unidentified magic item is not a gate — it is the
SRD/DMG ANSWER. Attunement is a short rest spent with the item, and the rule
says the attuning creature learns the item's properties when the bond
settles. handle_attune therefore flips `identified` exactly when it flips
`attuned` on (magic items only); refusing or toggling off never reveals
anything. The DM's own identify path is untouched.
"""
import uuid

import pytest
from starlette.testclient import TestClient

from app import db, main
from tests.test_movement_fog import H, base_room, recv_until, ws_connect


@pytest.fixture()
def client():
    return TestClient(main.app)


def _ring(tag):
    return {"id": "r" + tag, "name": f"Ring {tag}", "kind": "ring",
            "magic": True, "attunable": True, "identified": False,
            "desc": f"whispers of {tag}"}


def _char_with(client, player, code, n=1):
    ch = {"name": "Att-" + uuid.uuid4().hex[:6], "race": "", "char_class": "",
          "background": "", "level": 1,
          "stats": {"str": 10, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10},
          "hp": 10, "max_hp": 10,
          "items": [_ring(f"{i}{uuid.uuid4().hex[:4]}") for i in range(n)]}
    cid = client.post("/api/characters", headers=H(player), json=ch).json()["id"]
    client.post(f"/api/rooms/{code}/assign", json={"character_id": cid},
                headers=H(player))
    return cid


def _items(cid):
    row = db.q1("SELECT items FROM characters WHERE id=?", (cid,))
    return db.j(row["items"], [])


def _attune(ws, char_id, item_id):
    ws.send_json({"type": "attune", "char_id": char_id, "item_id": item_id})


def test_attuning_reveals_the_item(client):
    dm, player, code, _ = base_room(client)
    cid = _char_with(client, player, code)
    it = _items(cid)[0]
    assert it["identified"] is False
    with ws_connect(client, player, code) as ws:
        _attune(ws, cid, it["id"])
        ev = recv_until(ws, "whisper")
        assert "learn" in ev["payload"]["text"] and it["name"] in ev["payload"]["text"]
        recv_until(ws, "snapshot")
    after = _items(cid)[0]
    assert after["attuned"] is True and after["identified"] is True


def test_refused_attune_reveals_nothing(client):
    dm, player, code, _ = base_room(client)
    cid = _char_with(client, player, code, n=4)
    items = _items(cid)
    with ws_connect(client, player, code) as ws:
        for i in range(3):                     # the legal three
            _attune(ws, cid, items[i]["id"])
            recv_until(ws, "snapshot")
        _attune(ws, cid, items[3]["id"])       # the fourth is refused
        ev = recv_until(ws, "whisper")
        assert "at most" in ev["payload"]["text"]
    fourth = next(i for i in _items(cid) if i["id"] == items[3]["id"])
    assert fourth["attuned"] is False and fourth["identified"] is False


def test_toggle_off_keeps_the_knowledge(client):
    dm, player, code, _ = base_room(client)
    cid = _char_with(client, player, code)
    it = _items(cid)[0]
    with ws_connect(client, player, code) as ws:
        _attune(ws, cid, it["id"])
        recv_until(ws, "snapshot")
        _attune(ws, cid, it["id"])             # toggle OFF
        recv_until(ws, "snapshot")
    after = _items(cid)[0]
    assert after["attuned"] is False and after["identified"] is True
