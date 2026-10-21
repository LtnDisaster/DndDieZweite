"""Sprint 25 (D95): every documentation example is ACCEPTED by the real importer.

The documentation in docs/CSV_CONTENT_GUIDE.md lists 16 step-by-step examples.
These fixtures ARE those examples; each must import with zero errors through the
SAME code path the DM import uses. If a doc example ever stops being accepted,
this test fails — documentation and importer cannot drift apart.
"""
import pytest
from starlette.testclient import TestClient

from app import abilities, content as C, main


@pytest.fixture()
def client():
    return TestClient(main.app)


SCRATCH = 9_999_999        # a room id that need not exist; projections are guarded


def _csv(kind, *rows):
    """Build a header+rows CSV in the canonical schema column order (same helper
    shape as scripts/make_content_pack.py) so an example can never be misaligned
    against the real importer."""
    cols = [c[0] for c in C.SCHEMAS[kind]]
    lines = [",".join(cols)]
    for r in rows:
        lines.append(",".join(str(r.get(c, "")).replace(",", ";") for c in cols))
    return "\n".join(lines) + "\n"


# each example: (label, kind, [row dicts])  — these ARE the doc examples
EXAMPLES = [
    ("1 sword +1", "item", [
        {"id": "sword_p1", "name": "Sword +1", "kind": "weapon", "damage_dice": "1d8",
         "attack_bonus": 1, "damage_bonus": 1, "damage_type": "slashing", "magic": 1}]),
    ("2 versatile 1d8/1d10", "item", [
        {"id": "sv", "name": "Versatile Sword", "kind": "weapon", "damage_dice": "1d8",
         "damage_dice_two_handed": "1d10", "versatile": 1}]),
    ("3 two-handed axe", "item", [
        {"id": "gt", "name": "Great Axe", "kind": "weapon", "damage_dice": "1d12",
         "two_handed": 1, "damage_type": "slashing"}]),
    ("4 ring +2 AC", "item", [
        {"id": "rn", "name": "Ring of Warding", "kind": "ring", "ac_bonus": 2, "magic": 1, "attune": 1}]),
    ("5 +1 attack extra 1d8", "item", [
        {"id": "dg", "name": "Dagger of the Surge", "kind": "weapon", "damage_dice": "1d4",
         "attack_bonus": 1, "extra_damage_dice": "+1d8", "extra_damage_type": "lightning", "magic": 1}]),
    ("6 item grants skill proficiency", "item", [
        {"id": "gl", "name": "Gloves of the Thief", "kind": "wondrous",
         "skill_prof": "stealth; sleight_of_hand", "magic": 1, "attune": 1}]),
    ("7 item grants darkvision", "item", [
        {"id": "gn", "name": "Goggles of the Night", "kind": "wondrous", "darkvision_ft": 60,
         "magic": 1, "attune": 1}]),
    ("8 healing draught", "item", [
        {"id": "ph", "name": "Healing Draught", "kind": "potion", "heal_dice": "2d4+2"}]),

    ("8b ranged: normal + long range", "item", [
        {"id": "lb", "name": "Long Bow", "kind": "weapon", "damage_dice": "1d8",
         "range_normal_ft": 150, "range_long_ft": 600, "two_handed": 1,
         "damage_type": "piercing"}]),
    ("8c attribute bonus (general)", "item", [
        {"id": "hb", "name": "Headband of Intellect", "kind": "wondrous",
         "attribute_bonus": "int+2", "magic": 1, "attune": 1}]),
    ("8d sets an ability to a fixed score", "item", [
        {"id": "gg", "name": "Gloves of the Giant", "kind": "wondrous",
         "attribute_set": "str=15", "magic": 1, "attune": 1}]),
    ("8e multi-effect item", "item", [
        {"id": "ff", "name": "Flame Tongue", "kind": "weapon", "damage_dice": "2d6",
         "attack_bonus": 1, "extra_damage_dice": "+1d4", "extra_damage_type": "fire",
         "damage_type": "slashing", "magic": 1, "attune": 1}]),

    ("9 rogue-like class 1-20", "class",
     [{"id": "scout", "level": 1, "hit_die": 8, "hp_base": 14, "hp_per_level": 5,
       "saves": "dex; int", "skill_count": 4, "features": "Expertise; Sly Strike", "expertise": 1}]
     + [{"id": "scout", "level": n, "ability_boost_or_feat": 1 if n in (4, 8) else 0}
        for n in range(2, 21)]),

    ("10 subclass with features on levels", "subclass", [
        {"id": "trad_s", "class_id": "scout", "level": 3, "name": "Stalker", "features": "Careful Step"},
        {"id": "trad_s", "class_id": "scout", "level": 9, "name": "Vanishing", "features": "Hide as bonus"},
        {"id": "trad_s", "class_id": "scout", "level": 13, "name": "Evasive", "features": "No damage on move"}]),

    ("11 ability-boost-or-feat choice", "class", [
        {"id": "hero", "level": 4, "hit_die": 8, "ability_boost_or_feat": 1, "feat_choice": 1},
        {"id": "hero", "level": 8, "hit_die": 8, "ability_boost_or_feat": 1, "feat_choice": 1}]),
    ("11b feat row", "feat", [
        {"id": "feat_keen", "name": "Keen Mind", "ability_boost": "wis+1",
         "skill_prof": "perception; investigation", "effect": "+1 Wisdom"}]),

    ("12 a class's spell list", "spell", [
        {"id": "bolt", "name": "Bolt", "level": 2, "casting_ability": "int", "resolution": "save",
         "save": "dex", "on_save": "half", "damage_dice": "8d6", "damage_type": "fire",
         "class_list": "adept; warden"},
        {"id": "spark", "name": "Spark", "level": 0, "casting_ability": "int", "resolution": "attack",
         "damage_dice": "1d8", "damage_type": "fire", "class_list": "adept"}]),

    ("13 cantrip with scaling", "spell", [
        {"id": "spark", "name": "Spark", "level": 0, "casting_ability": "int",
         "targeting": "single", "resolution": "attack", "damage_dice": "1d8",
         "damage_type": "fire", "upcast_scaling": 1,
         "scaling_note": "grows with level; manual today"}]),

    ("14 spell with slots and upcasting", "spell", [
        {"id": "bolt", "name": "Bolt", "level": 2, "casting_ability": "int", "targeting": "area",
         "shape": "circle", "size_ft": 20, "resolution": "save", "save": "dex", "on_save": "half",
         "damage_dice": "8d6", "damage_type": "fire", "upcast_step": "+1d6", "upcast_scaling": 1}]),

    ("15 money + carrying (value and weight)", "item", [
        {"id": "gp", "name": "Gold Pouch", "kind": "other", "weight": 0.02, "value_gp": 50}]),

    ("15b carrying-capacity bonus (magical)", "item", [
        {"id": "bag_load", "name": "Bag of Loading", "kind": "wondrous", "weight": 0.5,
         "carry_bonus": 250, "magic": 1, "attune": 1}]),

    ("extra species", "species", [
        {"id": "kin_fey", "name": "Fey-kin", "size": "medium", "speed_ft": 30,
         "darkvision_ft": 60, "ability_bonuses": "dex+2", "traits": "Darkvision; Fey ancestry"}]),
]


@pytest.mark.parametrize("label,kind,rows", EXAMPLES,
                         ids=[e[0] for e in EXAMPLES])
def test_documentation_example_is_accepted(label, kind, rows):
    abilities.clear_registry()
    body = _csv(kind, *rows)
    rep = C.import_package({C.KIND_FILE[kind]: body}, room_id=SCRATCH, mode="apply", apply=True)
    assert rep["ok"], (label, rep["files"][0]["errors"])
    entry = rep["files"][0]
    assert entry["valid"] and entry["errors"] == []


def test_example_16_import_fix_export(client):
    """#16: import -> see a file/line/column error -> fix -> import clean -> export."""
    from tests.test_movement_fog import base_room, H
    dm, _p, code, _ch = base_room(client)
    bad = ("id,name,kind\nsword,Sword,weapon\nring,Ring,notakind\n").encode()
    rep = client.post(f"/api/content/{code}/import", content=bad, headers=H(dm),
                      params={"name": "items.csv", "mode": "preview"}).json()
    assert rep["ok"] is False
    err = rep["files"][0]["errors"][0]
    assert err["file"] == "items.csv" and err["line"] == 3 and err["column"] == "kind"
    # corrected and applied
    good = ("id,name,kind\nsword,Sword,weapon\nring,Ring,ring\n").encode()
    assert client.post(f"/api/content/{code}/import", content=good, headers=H(dm),
                       params={"name": "items.csv", "mode": "apply"}).json()["ok"]
    # export round-trips the two rows (full schema column order)
    txt = client.get(f"/api/content/{code}/export", params={"kind": "item"}, headers=H(dm)).text
    header = txt.splitlines()[0].split(",")
    assert header[:2] == ["id", "name"] and "kind" in header
    assert "sword" in txt and "ring" in txt
