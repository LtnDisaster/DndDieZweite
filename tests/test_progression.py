"""Multiclass-ready class progression tests (D53).

Pure model (validation, derived totals) + the WS authorization boundary.
All fixtures use ORIGINAL generic class ids — no class content whatsoever.
"""
import pytest
from starlette.testclient import TestClient

from app import db, gear, progression
from app.main import app

from test_movement_fog import (base_room, reg, state_of,
                               ws_connect, recv_until)


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


# ---------- pure model ----------

def test_total_level_is_derived_from_entries():
    assert progression.total_character_level(
        {"class_levels": [{"class_id": "fighter", "level": 3},
                          {"class_id": "wizard", "level": 2}]}) == 5
    assert progression.total_character_level(
        {"class_levels": '[{"class_id":"warlord","level":7}]'}) == 7   # raw JSON str too
    assert progression.total_character_level({"class_levels": "", "level": 4}) == 4  # legacy


def test_invalid_entries_rejected_not_half_applied():
    for bad in ([], "x", [{"class_id": "fighter", "level": 0}],
                [{"class_id": "fighter", "level": -2}],
                [{"class_id": "fighter", "level": 3}, {"class_id": "fighter", "level": 1}],
                [{"class_id": "", "level": 1}], [{"class_id": "fighter"}],
                [{"class_id": "f" * 40, "level": 1}],
                [{"class_id": "fighter", "level": 3}] * 9,
                [{"class_id": "fighter", "level": 15}, {"class_id": "wizard", "level": 10}]):
        assert progression.clean_class_levels(bad) is None, bad


def test_valid_entries_normalize_lowercase_ids():
    out = progression.clean_class_levels([{"class_id": "Warlord", "level": "2"}])
    assert out == [{"class_id": "warlord", "level": 2}]
    assert progression.format_classes({"class_levels": out}) == "Warlord 2"


def test_proficiency_bonus_uses_derived_total():
    ch = {"class_levels": [{"class_id": "warrior", "level": 3},
                           {"class_id": "adept", "level": 2}], "level": 1}  # legacy field lies
    assert gear.prof_bonus(ch) == 3          # total 5 -> PB +3, from the DERIVED total
    ch2 = {"class_levels": [{"class_id": "warrior", "level": 9}]}
    assert gear.prof_bonus(ch2) == 4         # total 9 -> PB +4


# ---------- persistence + WS ----------

def test_set_class_levels_syncs_legacy_level_column(client):
    _, _, _, ch = base_room(client)          # base char is legacy level 5
    assert progression.set_class_levels(ch["id"], [{"class_id": "warrior", "level": 3},
                                                   {"class_id": "adept", "level": 1}])
    row = db.q1("SELECT level, class_levels FROM characters WHERE id=?", (ch["id"],))
    assert row["level"] == 4                                   # legacy consumers keep working
    assert progression.load(row) == [{"class_id": "warrior", "level": 3},
                                     {"class_id": "adept", "level": 1}]
    assert not progression.set_class_levels(ch["id"], [{"class_id": "warrior", "level": 0}])
    assert db.q1("SELECT level FROM characters WHERE id=?", (ch["id"],))["level"] == 4  # unchanged


def test_dm_can_advance_room_member_character(client):
    dm, player, code, ch = base_room(client)
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "class_levels", "character_id": ch["id"],
                      "class_levels": [{"class_id": "warrior", "level": 3},
                                       {"class_id": "adept", "level": 2}]})
        recv_until(ws, "snapshot")
    m = next(m for m in state_of(client, player, code)["members"]
             if m["character_id"] == ch["id"])
    assert m["char"]["total_level"] == 5
    assert m["char"]["class_levels"] == [{"class_id": "warrior", "level": 3},
                                         {"class_id": "adept", "level": 2}]


def test_stranger_cannot_alter_class_levels(client):
    dm, player, code, ch = base_room(client)
    stranger = reg(client, "str")
    join = client.post("/api/rooms/join", json={"code": code},
                       headers={"cookie": stranger["cookie"]})
    assert join.status_code == 200
    with ws_connect(client, stranger, code) as ws:
        ws.send_json({"type": "class_levels", "character_id": ch["id"],
                      "class_levels": [{"class_id": "warrior", "level": 20}]})
        ev = recv_until(ws, "error")
        assert "character" in ev["payload"]["msg"].lower()
    assert db.q1("SELECT level FROM characters WHERE id=?", (ch["id"],))["level"] == 5  # lie-proof


def test_owner_can_set_own_and_invalid_payload_refused(client):
    dm, player, code, ch = base_room(client)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "class_levels", "character_id": ch["id"],
                      "class_levels": [{"class_id": "warrior", "level": 0}]})   # invalid
        assert recv_until(ws, "error")["kind"] == "error"
        ws.send_json({"type": "class_levels", "character_id": ch["id"],
                      "class_levels": [{"class_id": "warden", "level": 4}]})    # valid
        recv_until(ws, "snapshot")
    mine = state_of(client, player, code)["characters"]
    assert [c for c in mine if c["id"] == ch["id"]][0]["total_level"] == 4
