"""Integration regressions for gear and build columns reaching live engines.

The gear SSOT already derived equipment speed/darkvision, background skill
proficiencies and feat spell grants. These tests pin the remaining consumer
wiring: movement, darkvision LOS, the origin replay, and the one existing spell
chronology. They deliberately add no new engine or schema.
"""
import csv
import io
import uuid

import pytest
from starlette.testclient import TestClient

from app import charbuild, db, gear, main
from app.room import dice as room_dice, movement
from tests.test_d108_origin import (_apply as apply_origin, _char as origin_char,
                                    _report as origin_report, _room as origin_room)
from tests.test_lighting2 import add_named, make_dark
from tests.test_movement_fog import H, base_room, recv_until, state_of, ws_connect


@pytest.fixture()
def client():
    return TestClient(main.app)


def rid_of(code):
    return db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]


def token_of(client, user, code, ch):
    return next(t["id"] for t in state_of(client, user, code)["tokens"]
                if t["character_id"] == ch["id"])


def mk_def(client, dm, code, name, props, kind="ring"):
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "item_def", "action": "create",
                      "defn": {"name": name, "kind": kind, "props": props}})
        recv_until(ws, "inv_changed")
    return next(d["id"] for d in state_of(client, dm, code)["item_defs"] if d["name"] == name)


def grant_item(client, player, dm, code, ch_id, def_id):
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "inv_grant", "char_id": ch_id, "def_id": def_id, "qty": 1})
        recv_until(ws, "inv_changed")
    return next(i for i in state_of(client, player, code)["characters"]
                if i["id"] == ch_id)["items"][-1]["id"]


def equip(client, player, code, ch_id, item_id, slot="acc1"):
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "inv_equip", "char_id": ch_id, "slot": slot,
                      "item_id": item_id, "op_id": "e" + uuid.uuid4().hex[:10]})
        recv_until(ws, "inv_changed")


def _csv_load(text):
    rows = list(csv.DictReader(io.StringIO(text)))
    return rows, list(rows[0].keys())


def _csv_dump(rows, fields):
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


def _mutate_origin_caster(files):
    """Add a minimal one-level caster and make the existing scholar Origin feat
    use the already-existing ``spells_grant`` column."""
    classes, fields = _csv_load(files["classes.csv"])
    caster = {k: "" for k in fields}
    caster.update({
        "id": "testcaster", "level": "1", "name": "Test Caster",
        "hit_die": "8", "hp_base": "8", "hp_per_level": "5", "saves": "int",
        "skill_options": "arcana, history", "skill_count": "2",
        "weapon_prof": "simple", "features": "Test Feature",
        "spellcasting_ability": "int", "cantrips_known": "1",
        "spells_known": "0", "prepared": "0",
        "slot_progression": "1:2", "spell_first_level": "1",
        "manual": "test caster", "starting_items": "dagger_surge",
    })
    classes.append(caster)
    files["classes.csv"] = _csv_dump(classes, fields)

    spells, fields = _csv_load(files["spells.csv"])
    for row in spells:
        if row["id"] in {"spark", "mend"}:
            existing = row.get("class_list") or ""
            row["class_list"] = f"{existing};testcaster" if existing else "testcaster"
    grant = {k: "" for k in fields}
    grant.update({
        "id": "feat_gift", "name": "Feat Gift", "level": "0", "school": "evocation",
        "casting_ability": "int", "targeting": "single", "range_ft": "120",
        "casting_time": "1 action", "duration": "instant", "resolution": "auto",
        "class_list": "otherclass", "manual": "outside the testcaster pool",
    })
    spells.append(grant)
    files["spells.csv"] = _csv_dump(spells, fields)

    feats, fields = _csv_load(files["feats.csv"])
    next(r for r in feats if r["id"] == "feat_quick_study")["spells_grant"] = "feat_gift"
    files["feats.csv"] = _csv_dump(feats, fields)


def test_equipment_speed_bonus_reaches_movement_speeds(client):
    dm, player, code, ch = base_room(client)
    tok = token_of(client, player, code, ch)
    before = db.q1("SELECT * FROM tokens WHERE id=?", (tok,))
    assert movement._speeds(before)["walk"] == 30

    item_id = grant_item(client, player, dm, code, ch["id"],
                         mk_def(client, dm, code, "Boots", {"speed_bonus_ft": 10}))
    equip(client, player, code, ch["id"], item_id)
    after = db.q1("SELECT * FROM tokens WHERE id=?", (tok,))
    assert movement._speeds(after)["walk"] == 40


def test_equipment_darkvision_reaches_los(client):
    dm, player, code, _ = base_room(client)
    make_dark(client, dm, code)
    with ws_connect(client, dm, code) as wsd:
        npc = add_named(wsd, "Lurker", 12, 12)
        mine = next(t for t in state_of(client, player, code)["tokens"]
                    if t.get("owner_user_id") is not None)["id"]
        wsd.send_json({"type": "forced_move", "token_id": mine,
                       "kind": "teleport", "tx": 8, "ty": 8})
        recv_until(wsd, "forced_moved")
    assert npc not in {t["id"] for t in state_of(client, player, code)["tokens"]}

    ch = db.q1("SELECT id FROM characters WHERE id IN "
               "(SELECT character_id FROM tokens WHERE id=?)", (mine,))["id"]
    item_id = grant_item(client, player, dm, code, ch,
                         mk_def(client, dm, code, "Goggles", {"darkvision_ft": 60}))
    equip(client, player, code, ch, item_id)
    assert npc in {t["id"] for t in state_of(client, player, code)["tokens"]}


def test_equipment_hit_dice_bonus_reaches_short_rest(client, monkeypatch):
    dm, player, code, ch = base_room(client)
    tok = token_of(client, player, code, ch)
    db.x("UPDATE characters SET hp=0, max_hp=20, hit_die=8, hit_dice_spent=0, "
         "stats=? WHERE id=?",
         (db.json_dumps({"str": 10, "dex": 10, "con": 10,
                         "int": 10, "wis": 10, "cha": 10}), ch["id"]))
    item_id = grant_item(client, player, dm, code, ch["id"],
                         mk_def(client, dm, code, "Vital Ring", {"hit_dice_bonus": 3}))
    equip(client, player, code, ch["id"], item_id)
    monkeypatch.setattr(room_dice, "do_roll", lambda *args, **kwargs: {"total": 8})
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "short_rest", "token_id": tok, "hit_dice_count": 1})
        recv_until(ws, "dice")
    assert db.q1("SELECT hp FROM characters WHERE id=?", (ch["id"],))["hp"] == 11


def test_item_hand_count_participates_in_the_existing_two_hand_rule(client):
    assert gear.wields_two_handed({"props": {"hands": 2}}) is True
    assert gear.can_equip({"kind": "weapon", "props": {"hands": 2}}, "off_hand") is False
    assert gear.can_equip({"kind": "weapon", "light": True,
                           "props": {"hands": 1}}, "off_hand") is True
    assert gear.can_equip({"kind": "weapon", "light": True,
                           "props": {"hands": 2}}, "off_hand") is False


def test_origin_background_skill_proficiencies_apply(client):
    dm, player, code, _ = origin_room(client)
    ch = origin_char(client, player)
    r = apply_origin(client, player, code, ch["id"],
                     {"mode": "plus2_plus1", "plus2": "int", "plus1": "wis"})
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True, r.text
    skills = db.j(db.q1("SELECT skills FROM characters WHERE id=?", (ch["id"],))["skills"], {})
    assert skills["arcana"] == 1 and skills["history"] == 1
    assert skills["investigation"] == 1


def test_origin_report_and_apply_return_background_details(client):
    dm, player, code, _ = origin_room(client)
    ch = origin_char(client, player)
    rep = origin_report(client, player, code, ch["id"])
    assert rep["background_feature"].startswith("Lots of Research")
    assert "Common" in rep["background_languages"]

    result = apply_origin(client, player, code, ch["id"], {"mode": "three"}).json()["result"]
    assert result["background_feature"].startswith("Lots of Research")
    assert "Common" in result["background_languages"]


def test_class_expertise_uses_existing_skill_axis(client):
    dm, player, code, _ = origin_room(client)
    ch = origin_char(client, player)
    ok, res = charbuild.apply(ch["id"], "scout", 1, {
        "skills": ["acrobatics", "athletics", "insight", "stealth"],
        "levels": {"1": {"expertise": ["stealth"]}},
    }, rid_of(code))
    assert ok, res
    row = db.q1("SELECT skills, build FROM characters WHERE id=?", (ch["id"],))
    assert db.j(row["skills"], {})["stealth"] == 2
    history = {h["level"]: h for h in db.j(row["build"], {})["history"]}
    assert history[1]["expertise"] == ["stealth"]

    other = origin_char(client, player)
    ok, err = charbuild.apply(other["id"], "scout", 1, {
        "skills": ["acrobatics", "athletics", "insight", "stealth"],
        "levels": {"1": {"expertise": ["perception"]}},
    }, rid_of(code))
    assert ok is False
    assert "non-proficient" in err["error"]

    duplicate = origin_char(client, player)
    ok, err = charbuild.apply(duplicate["id"], "scout", 1, {
        "skills": ["acrobatics", "athletics", "insight", "stealth"],
        "levels": {"1": {"expertise": ["stealth", "stealth"]}},
    }, rid_of(code))
    assert ok is False, res
    assert err["needs_choice"][0]["kind"] == "expertise"


def test_class_spellcasting_ability_is_recorded_for_display(client):
    dm, player, code, _ = origin_room(client, mutate=_mutate_origin_caster)
    ch = origin_char(client, player)
    rid = rid_of(code)
    p = charbuild.plan("testcaster", 1, rid)
    assert p["ok"] and p["needs"]["spell"]["ability"] == "int"
    ok, res = charbuild.apply(ch["id"], "testcaster", 1, {
        "skills": ["arcana", "history"],
        "levels": {"1": {"cantrips": "spark"}},
    }, rid)
    assert ok, res
    assert res["casting_ability"] == "int"
    led = db.j(db.q1("SELECT build FROM characters WHERE id=?", (ch["id"],))["build"], {})
    assert led["casting"]["ability"] == "int" and led["casting"]["model"] == "known"


def test_class_proficiencies_are_recorded_on_the_build_ledger(client):
    dm, player, code, _ = origin_room(client)
    ch = origin_char(client, player)
    ok, res = charbuild.apply(ch["id"], "scout", 1, {
        "skills": ["acrobatics", "athletics", "deception", "insight"],
        "levels": {"1": {"expertise": "insight"}},
    }, rid_of(code))
    assert ok, res
    led = db.j(db.q1("SELECT build FROM characters WHERE id=?", (ch["id"],))["build"], {})
    assert led["class_proficiencies"]["weapons"] == ["martial", "simple"]
    assert led["class_proficiencies"]["armor"] == ["light"]


def test_subclass_features_are_recorded_in_the_build_history(client):
    dm, player, code, _ = origin_room(client)
    ch = origin_char(client, player)
    ok, res = charbuild.apply(ch["id"], "scout", 3, {
        "skills": ["acrobatics", "athletics", "deception", "insight"],
        "subclass": "tradition_stalker",
        "levels": {"1": {"expertise": "insight"}},
    }, rid_of(code))
    assert ok, res
    led = db.j(db.q1("SELECT build FROM characters WHERE id=?", (ch["id"],))["build"], {})
    history = {h["level"]: h for h in led["history"]}
    assert history[3]["subclass"] == "Stalker Tradition"
    assert "Careful Step" in history[3]["features"]


def test_species_projection_is_recorded_on_the_build_ledger(client):
    dm, player, code, _ = origin_room(client)
    ch = origin_char(client, player)
    assert apply_origin(client, player, code, ch["id"], {"mode": "three"}).json()["ok"] is True
    led = db.j(db.q1("SELECT build FROM characters WHERE id=?", (ch["id"],))["build"], {})
    species = led["species"]
    assert species["id"] == "kin_fey"
    assert species["speed_ft"] == 30 and species["darkvision_ft"] == 60
    assert "Darkvision 60 ft" in species["traits"]


def test_origin_feat_spell_grant_uses_existing_spell_state(client):
    dm, player, code, _ = origin_room(client, mutate=_mutate_origin_caster)
    ch = origin_char(client, player)
    origin = apply_origin(client, player, code, ch["id"],
                          {"mode": "plus2_plus1", "plus2": "int", "plus1": "wis"}).json()
    assert origin["ok"] is True, origin
    ok, res = charbuild.apply(ch["id"], "testcaster", 1, {
        "skills": ["arcana", "history"],
        "levels": {"1": {"cantrips": "spark"}},
    }, rid_of(code))
    assert ok, res
    row = db.q1("SELECT abilities, spells FROM characters WHERE id=?", (ch["id"],))
    abilities = db.j(row["abilities"], [])
    spells = db.j(row["spells"], [])
    assert "feat_gift" in abilities
    assert "feat_gift" in {s.get("id") for s in spells}
