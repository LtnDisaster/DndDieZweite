"""D163-3 — tool proficiency is a real engine axis, fed by CSV, read by rules.

Before D163 the CSV columns tool_prof existed only as ledger text: doors read
ONE background row, trap disarms rolled a bare DEX check on purpose (documented
D114 gap), items with a tool prop were "isn't usable". D163 lands the axis:
characters carry `tool_profs` (written from background/class/feat rows at
apply), gear exposes tool_key/tool_trained/tool_available, and three real rules
read it — lockpicking (legacy background fallback preserved), trap disarms
(true Thieves' tools check) and USING a tool item (one check, honest label).
"""
import uuid

import pytest
from starlette.testclient import TestClient

from app import charbuild, db, gear, main
from tests.test_movement_fog import (H, base_room, recv_until, state_of,
                                     ws_connect)


@pytest.fixture()
def client():
    return TestClient(main.app)


def my_token(client, player, code):
    pst = state_of(client, player, code)
    tok = next(t for t in pst["tokens"] if t.get("character_id"))
    return tok["id"], tok["character_id"]


def fixed_roll(monkeypatch, value):
    seen = []

    def fake(expr, adv=None):
        seen.append(adv)
        return {"kept": value, "adv": adv}
    monkeypatch.setattr("app.room.opposed.do_roll", fake)
    return seen


def whisper(ws, needle):
    ev = recv_until(ws, "whisper", fail_on_error=False)
    assert ev["kind"] == "whisper", ev
    assert needle in ev["payload"]["text"], ev
    return ev["payload"]["text"]


def set_axes(char_id, **axes):
    for col, val in axes.items():
        db.x(f"UPDATE characters SET {col}=? WHERE id=?",
             (db.json_dumps(val), char_id))


# ------------------------------------------------------------- the axis itself

def test_tool_key_canonicalises_sources():
    assert gear.tool_key("Thieves' tools") == gear.tool_key("thieves_tools") \
        == gear.tool_key("  THIEVES  TOOLS ") == "thieves tools"


def test_class_apply_persists_axes(client):
    """weapon_prof / armor_prof / tool_prof on a CLASS row are no longer text."""
    dm, player, code, ch = base_room(client)
    rid = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
    from app import content as CT
    CT.store("class", rid, {"id": "taxis", "level": "1", "name": "Axis tester",
                            "hit_die": "8", "hp_base": "8", "hp_per_level": "4",
                            "weapon_prof": "simple", "armor_prof": "light",
                            "tool_prof": "thieves tools, poisoner's kit"})
    r = client.post(f"/api/build/{code}/{ch['id']}/apply",
                    json={"class_id": "taxis", "to": 1, "choices": {}},
                    headers=H(player))
    assert r.status_code == 200 and r.json()["ok"], r.text
    row = db.q1("SELECT tool_profs, weapon_profs, armor_profs FROM characters "
                "WHERE id=?", (ch["id"],))
    assert db.j(row["tool_profs"], []) == ["poisoner s kit", "thieves tools"]
    assert db.j(row["weapon_profs"], []) == ["simple"]
    assert db.j(row["armor_profs"], []) == ["light"]


def test_gear_axis_helpers():
    sheet = {"tool_profs": ["thieves tools"], "items": [
        {"id": "t", "name": "Kit", "qty": 1,
         "props": {"tool": "Thieves' tools"}}]}
    assert gear.tool_trained(sheet, "thieves' tools")
    assert gear.tool_available(sheet, "thieves tools")
    assert not gear.tool_trained(sheet, "Forgery Kit")
    assert not gear.tool_available({"items": sheet["items"]}, "land")  # no axis needed


# ------------------------------------------------- doors: axis + legacy path

def test_door_pick_works_from_axis_without_background(client, monkeypatch):
    """D163: training may arrive on the axis alone (class/feat rows) — the
    pre-D163 background-row read stays only as the documented fallback."""
    dm, player, code, _ = base_room(client)
    from tests.test_d162_lockpick import place_door
    place_door(client, dm, code, lock_dc=24)
    tok_id, char_id = my_token(client, player, code)
    set_axes(char_id, tool_profs=["thieves tools"])
    db.x("UPDATE characters SET items=? WHERE id=?",
         ('[{"def_id":"tkt","name":"Thieves\' tools","qty":1,'
          '"props":{"tool":"thieves tools"}}]', char_id))
    fixed_roll(monkeypatch, 20)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "door", "x": 8, "y": 6, "dir": "h", "action": "pick"})
        text = whisper(ws, "the lock clicks open")
        assert "20+5 = 25" in text                    # dex +2 + prof +3 (base char is level 5)


def test_door_pick_axis_without_tools_gets_disadvantage(client, monkeypatch):
    dm, player, code, _ = base_room(client)
    from tests.test_d162_lockpick import place_door
    place_door(client, dm, code, lock_dc=25)
    tok_id, char_id = my_token(client, player, code)
    set_axes(char_id, tool_profs=["thieves tools"])   # trained but toolless
    seen = fixed_roll(monkeypatch, 20)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "door", "x": 8, "y": 6, "dir": "h", "action": "pick"})
        text = whisper(ws, "no tools")
        assert "disadvantage" in text
    assert seen == ["dis"]


# ------------------------------------------------------- using a tool at all

def test_use_tool_rolls_and_labels(client, monkeypatch):
    dm, player, code, _ = base_room(client)
    tok_id, char_id = my_token(client, player, code)
    db.x("UPDATE characters SET items=? WHERE id=?",
         ('[{"id":"kit1","def_id":"forge","name":"Smith\'s tools","qty":1,'
          '"props":{"tool":"smith\'s tools","tool_ability":"wis"}}]', char_id))
    fixed_roll(monkeypatch, 13)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "use_item", "token_id": tok_id, "item_id": "kit1"})
        text = whisper(ws, "Smith's tools")
        assert "untrained" in text
    # trained + at hand -> proficiency rides the roll
    set_axes(char_id, tool_profs=["smith's tools"])
    seen = fixed_roll(monkeypatch, 13)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "use_item", "token_id": tok_id, "item_id": "kit1"})
        text = whisper(ws, "Smith's tools")
        assert "with proficiency" in text
    assert seen == [None]                             # a tool check has no disadvantage
