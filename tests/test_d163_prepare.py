"""D163-7 — the daily prepared list is a player decision, not a frozen CSV flag.

D138 made preparation GATE castable spells, but the prepared state itself was
baked into the content row forever. D163 adds the missing action:
"spell_prepare" sets the daily list from the character's own prep-gated
known spells (validated server-side, persisted in characters.prepared_spells
so a build recompute rebuilds the same sheet) and the sheet re-renders through
the existing snapshot. Non-preparing characters can't call it; foreign or
cantrip ids are refused before anything is written.
"""
import pytest
from starlette.testclient import TestClient

from app import db, main
from tests.test_movement_fog import base_room, ws_connect
from tests.test_sprint23_combat import set_progression


@pytest.fixture
def client():
    return TestClient(main.app)


def prep_room(client):
    dm, player, code, ch = base_room(client)
    set_progression(ch["id"],
                    spells=[{"id": "u1", "name": "Unprepped", "level": 1,
                             "cast": "none", "prep": True, "prepared": False},
                            {"id": "p2", "name": "Prepped", "level": 1,
                             "cast": "none", "prep": True, "prepared": True},
                            {"id": "c0", "name": "Free", "level": 0, "cast": "none"}],
                    spell_slots={"1": {"max": 2, "used": 0}})
    return dm, player, code, ch


def spells_json(cid):
    return {x["id"]: x for x in db.j(
        db.q1("SELECT spells FROM characters WHERE id=?", (cid,))["spells"], [])}


def test_prepare_swaps_the_daily_list(client):
    dm, player, code, ch = prep_room(client)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "spell_prepare", "spell_ids": ["u1"]})
        # confirmation rides the snapshot broadcast
        for _ in range(40):
            ev = ws.receive_json()
            if ev.get("kind") == "snapshot":
                break
    picks = db.j(db.q1("SELECT prepared_spells FROM characters WHERE id=?",
                       (ch["id"],))["prepared_spells"], [])
    assert picks == ["u1"]
    sp = spells_json(ch["id"])
    assert sp["u1"]["prepared"] is True and sp["p2"]["prepared"] is False


def test_prepare_refuses_bad_input(client):
    dm, player, code, ch = prep_room(client)
    with ws_connect(client, player, code) as ws:
        for bad in (["nope"], ["u1", "u1"], ["c0"]):
            ws.send_json({"type": "spell_prepare", "spell_ids": bad})
            got_error = False
            for _ in range(40):
                ev = ws.receive_json()
                if ev.get("kind") == "error":
                    assert "preparable" in ev["payload"]["msg"]
                    got_error = True
                    break
                if ev.get("kind") == "snapshot":
                    break
            assert got_error, bad
    assert db.j(db.q1("SELECT prepared_spells FROM characters WHERE id=?",
                      (ch["id"],))["prepared_spells"], []) == []
    assert spells_json(ch["id"])["p2"]["prepared"] is True   # nothing touched


def test_non_preparer_cannot_prepare(client):
    dm, player, code, ch = base_room(client)
    set_progression(ch["id"],
                    spells=[{"id": "k1", "name": "Known", "level": 1,
                             "cast": "none"}])
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "spell_prepare", "spell_ids": ["k1"]})
        for _ in range(40):
            ev = ws.receive_json()
            if ev.get("kind") == "error":
                assert "does not prepare" in ev["payload"]["msg"]
                return
    raise AssertionError("no refusal for a non-preparing caster")


def test_ability_pipeline_cast_respects_the_daily_list(client):
    """D163: charbuild collects EVERY known class spell into
    characters.abilities, so the sheet button a built caster actually clicks
    is an ability_cast — the legacy type:"cast" path never renders for them.
    The preparation gate therefore has to ride the ability pipeline too
    (app.abilities._consume_cost), or the daily list would be decorative for
    exactly the CSV-driven casters it was built for. The E2E browser run
    found this hole; this test pins the fix."""
    from app import abilities
    dm, player, code, ch = prep_room(client)
    set_progression(ch["id"], abilities=["u1", "p2"])   # the real build puts
    # every known spell id on the abilities axis — the ownership check below
    # (execute: "This caster does not have that ability") is exactly that gate.
    rid = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
    for sid, nm in (("u1", "Unprepped"), ("p2", "Prepped")):
        assert abilities.register({"id": sid, "name": nm, "ability": "int",
                                   "range_ft": 30, "targeting": "single",
                                   "resolution": "auto", "damage": "1d4",
                                   "damage_type": "force",
                                   "cost": {"type": "spell_slot", "level": 1}}, rid)
    tok = db.q1("SELECT id FROM tokens WHERE room_id=? AND character_id=?",
                (rid, ch["id"]))
    with ws_connect(client, player, code) as ws:
        # prep-gated and NOT prepared: refused — and refused BEFORE any slot
        # is touched (the gate reads inside the same tx as the increment)
        ws.send_json({"type": "ability_cast", "token_id": tok["id"],
                      "ability_id": "u1"})
        for _ in range(40):
            ev = ws.receive_json()
            if ev.get("kind") == "error":
                assert "is not prepared" in ev["payload"]["msg"]
                break
        else:
            raise AssertionError("ability pipeline ignored the daily list")
        slots = db.j(db.q1("SELECT spell_slots FROM characters WHERE id=?",
                           (ch["id"],))["spell_slots"], {})
        assert slots["1"]["used"] == 0        # gate fires before any slot burn
        # the PREPARED entry rides the same button without that refusal — a
        # follow-on table verdict ("No target token") proves it passed the gate
        ws.send_json({"type": "ability_cast", "token_id": tok["id"],
                      "ability_id": "p2"})
        for _ in range(40):
            ev = ws.receive_json()
            if ev.get("kind") == "error":
                assert "is not prepared" not in ev["payload"]["msg"]
                return
    raise AssertionError("prepared spell never reached the table checks")
