"""D163-8/-9 — loot tables and quests become CSV content.

Loot: a `loottables.csv` kind (label/weight/qty entries, validated on store)
plus the DM's "roll_loot" action — the server loads the ROOM's table, picks
one weighted entry and announces the resolved quantity in the table channel.
Quests: a `quest` content kind projects INTO the live quests table (src-keyed,
so re-imports refresh the book text but never overwrite the DM's progress).
"""
import pytest
from starlette.testclient import TestClient

from app import content as CT, db, main
from tests.test_movement_fog import base_room, recv_until, ws_connect


@pytest.fixture
def client():
    return TestClient(main.app)


def rid_of(code):
    return db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]


# ------------------------------------------------------------------ loot

ENTRIES = '[{"label":"Gold coins","weight":"2","qty":"2d6+5"},' \
          '{"label":"Gem","weight":"1","qty":"1"}]'


def test_loot_table_stores_and_rolls(client, monkeypatch):
    dm, player, code, _ = base_room(client)
    rid = rid_of(code)
    CT.store("loottable", rid, {"id": "hoard1", "name": "Goblin hoard",
                                "entries": ENTRIES})
    assert CT.load("loottable", rid)
    seen = []

    def fake(expr, adv):
        seen.append(expr)
        return {"kept": 7, "adv": None, "total": 20}
    monkeypatch.setattr("app.room.loot.do_roll", fake)
    # deterministic weighted pick: land on the FIRST entry (the dice-qty one),
    # so "20 ×" proves the qty dice really went through do_roll.
    monkeypatch.setattr("app.room.loot.random.randint", lambda lo, hi: lo)
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "roll_loot", "table_id": "hoard1"})
        ev = recv_until(ws, "chat", fail_on_error=False)
        assert "Goblin hoard" in str(ev["payload"])
        assert "20 ×" in str(ev["payload"])          # qty dice went through do_roll


def test_loot_rejects_bad_entries_and_players(client):
    dm, player, code, _ = base_room(client)
    rid = rid_of(code)
    CT.store("loottable", rid, {"id": "hoardx", "name": "X",
                                      "entries": '[{"weight":1}]'})
    assert not CT.load("loottable", rid) or all(
        r.get("id") != "hoardx" for r in CT.load("loottable", rid))
    CT.store("loottable", rid, {"id": "hoard1", "name": "Ok", "entries": ENTRIES})
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "roll_loot", "table_id": "hoard1"})
        ev = recv_until(ws, "error", fail_on_error=False)
        assert "DM" in ev["payload"]["msg"]
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "roll_loot", "table_id": "nope"})
        ev = recv_until(ws, "error", fail_on_error=False)
        assert "No loot table" in ev["payload"]["msg"]


# ---------------------------------------------------------------- quests

def test_loot_qty_dice_grammar_matches_the_engine():
    """Regression (D163): the validator used the narrow BONUS-dice regex, so
    the qty die '2d6+5' — exactly what do_roll speaks — was rejected at
    import while the store bypass accepted it. One grammar, validated."""
    rows, hdr = CT.parse('id,name,entries\nh,H,"[{""label"":""C"",""qty"":""2d6+5""}]"\n')
    clean, errs, _warn = CT.validate("loottable", rows, hdr, "loottables.csv")
    assert not errs, errs
    assert '"qty":"2d6+5"' in clean[0]["entries"]      # canonical JSON keeps it
    bad_rows, bad_hdr = CT.parse(
        'id,name,entries\nh,H,"[{""label"":""C"",""qty"":""2d6++5""}]"\n')
    _c, errs2, _w = CT.validate("loottable", bad_rows, bad_hdr, "loottables.csv")
    assert any("2d6++5" in e["msg"] for e in errs2)


def test_quest_csv_creates_live_quest(client):
    dm, player, code, _ = base_room(client)
    rid = rid_of(code)
    CT.store("quest", rid, {"id": "q_mill", "title": "The Mill",
                            "description": "Reclaim the mill",
                            "objectives": "Scout the mill, Free the miller",
                            "status": "active"})
    row = db.q1("SELECT * FROM quests WHERE room_id=? AND src='q_mill'", (rid,))
    assert row and row["title"] == "The Mill"
    assert db.j(row["objectives"], []) == ["Scout the mill", "Free the miller"]
    assert row["status"] == "active" and row["visibility"] == "party"


def test_quest_reimport_keeps_dm_progress(client):
    dm, player, code, _ = base_room(client)
    rid = rid_of(code)
    CT.store("quest", rid, {"id": "q_mill", "title": "The Mill",
                            "objectives": "Scout the mill"})
    db.x("UPDATE quests SET status='done' WHERE room_id=? AND src='q_mill'",
         (rid,))
    CT.store("quest", rid, {"id": "q_mill", "title": "The Old Mill v2",
                            "description": "Updated", "objectives": "Scout, Hold"})
    row = db.q1("SELECT * FROM quests WHERE room_id=? AND src='q_mill'", (rid,))
    assert row["status"] == "done"                    # DM progress wins
    assert row["title"] == "The Old Mill v2"          # book text refreshes
    # The no-duplicate property is per ROOM: a re-import must never append a
    # second live row for this src in THIS room. (Room-scoped on purpose —
    # another test owns a q_mill in another room, and exactly one row per
    # room is the cross-room isolation contract.)
    assert len(db.q("SELECT id FROM quests WHERE room_id=? AND src='q_mill'",
                    (rid,))) == 1
