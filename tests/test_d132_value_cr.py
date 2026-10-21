"""D132 (AP-018): value_gp and cr finally have consumers.

The items.csv `value_gp` column rode a dead schema field; creatures.csv `cr`
was never projected. Both now travel the ONE existing data line:
value_gp -> item_defs.value (migration column) -> inventory entry value
(clean_items), and cr -> npc.clean_npc block -> token -> monster sheet payload.
No economy is invented: value is the DM-facing price/loot datum; cr is sheet
data the 2024 milestone engine deliberately does NOT turn into XP.
"""
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from app import content as C
from app import db, gear, inventory as INV, main, npc
from tests.test_movement_fog import (H, base_room, recv_until, ws_connect)

PACK = Path(__file__).resolve().parents[1] / "app" / "content_pack"


@pytest.fixture
def client():
    app = main.app
    with TestClient(app) as c:
        yield c


# ------------------------------------------------------------------- units

def test_cr_cleans_the_srd_band_only():
    assert npc._clean_cr("1/8") == "1/8"
    assert npc._clean_cr("3/4") == "3/4"
    assert npc._clean_cr("0") == "0"
    assert npc._clean_cr(7) == "7"
    assert npc._clean_cr(" 13 ") == "13"
    assert npc._clean_cr("31") == ""
    assert npc._clean_cr("legendary") == ""
    assert npc._clean_cr(None) == ""


def test_project_creature_keeps_cr_on_the_one_block_shape():
    block = npc.project_creature({
        "id": "owl", "name": "Owl", "cr": "0", "ac": 11, "hp": 5, "dex": 13,
    })
    assert block["cr"] == "0" and block["name"] == "Owl"
    bad = npc.project_creature({"id": "titan", "name": "Titan", "cr": "99", "hp": 5})
    assert bad["cr"] == ""            # out of band = unknown, never a forged 99


def test_def_value_clamps_and_entry_copies_it():
    d = INV.clean_def({"name": "Ring", "value": "1500000"})
    assert d["value"] == 999999.0
    d2 = INV.clean_def({"name": "Ring", "value": -5})
    assert d2["value"] == 0.0
    d3 = INV.clean_def({"name": "Ring", "value": 25})
    it = INV.entry_from_def({**d3, "props": "{}"}, 2)
    assert it["value"] == 25 and it["qty"] == 2
    # pre-D132 entries round-trip at 0 (additive field, no byte churn elsewhere):
    assert gear.clean_items([{"name": "Old"}])[0]["value"] == 0


# ------------------------------------------------------------- data lines

def test_pack_import_lands_value_gp_on_the_room_def(client):
    dm, player, code, ch = base_room(client)
    rid = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
    # fresh unique def id: item_defs.id is GLOBAL (D100), and other suites
    # legitimately own the shared pack ids already. The projection function
    # itself is the line under test.
    assert C._project_item(rid, {"id": "gem_d132", "name": "Test Gem",
                                 "kind": "other", "weight": 1,
                                 "value_gp": 42, "desc": ""}) == "ok"
    row = db.q1("SELECT value FROM item_defs WHERE id=? AND room_id=?",
                ("gem_d132", rid))
    assert row is not None and row["value"] == 42
    # and the real pack file still imports cleanly into a fresh-content room:
    files = {p.name: p.read_text(encoding="utf-8") for p in PACK.glob("*.csv")}
    rep = C.import_package(files, room_id=rid, mode="apply", apply=True)
    assert rep["ok"], rep


def test_dm_def_and_grant_carry_value_to_the_character(client):
    dm, player, code, ch = base_room(client)
    with ws_connect(client, dm, code) as dws:
        dws.send_json({"type": "item_def", "action": "create",
                       "defn": {"id": "goblet", "name": "Golden Goblet",
                                "kind": "other", "value": 750}})
        recv_until(dws, "whisper")
    st = client.get(f"/api/rooms/{code}/state", headers=H(dm)).json()
    gob = next(d for d in st["item_defs"] if d["id"] == "goblet")
    assert gob["value"] == 750.0                      # shipped to the table
    with ws_connect(client, dm, code) as dws:
        dws.send_json({"type": "inv_grant", "char_id": ch["id"],
                       "def_id": "goblet", "qty": 1})
        recv_until(dws, "inv_changed")
    mine = next(m for m in client.get(f"/api/rooms/{code}/state",
                                      headers=H(player)).json()["members"]
                if m.get("char") and m["char"]["id"] == ch["id"])
    entry = next(i for i in mine["char"]["items"] if i["def_id"] == "goblet")
    assert entry["value"] == 750.0                    # the loot entry knows


def test_npc_token_shares_cr_on_the_block(client):
    dm, player, code, ch = base_room(client)
    with ws_connect(client, dm, code) as dws:
        dws.send_json({"type": "add_token", "label": "Ogre", "x": 650, "y": 650,
                       "npc": {"name": "Ogre", "hp": 59, "cr": "2"}})
        nid = recv_until(dws, "token_add")["payload"]["id"]
    tok = db.q1("SELECT * FROM tokens WHERE id=?", (nid,))
    assert npc.load(tok)["cr"] == "2"
