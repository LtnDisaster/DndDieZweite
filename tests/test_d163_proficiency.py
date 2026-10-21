"""D163-4 — weapon/armor proficiency is derived from CSV, not claimed by DM.

Two axes landed on the character sheet: weapon_profs (groups from class rows
weapon_prof) and armor_profs (armor_prof). The engines that used to trust a
hand-ticked item flag now consult the axes: an armor the wearer is not trained
with gives NO armour benefit (SRD 5.2.1), a weapon outside the axis rolls with
disadvantage and its mastery properties are inert. Items that carry no
prof_group at all (every pre-D163 pack) keep the old flag semantics
byte-identically — the axes only ever ADD rules where the data speaks.
"""
import pytest
from starlette.testclient import TestClient

from app import db, gear, main
from tests.test_movement_fog import H, base_room


@pytest.fixture()
def client():
    return TestClient(main.app)


def sheet(**over):
    ch = {"stats": {"str": 10, "dex": 16, "con": 10, "int": 10, "wis": 10,
                    "cha": 10}, "level": 5, "items": [], "equipment": {}}
    ch.update(over)
    return ch


def weapon(pid="w1", group="martial", flag=None, dice="1d8"):
    props = {"damage_dice": dice, "finesse": True}
    if group is not None:
        props["prof_group"] = group
    if flag is not None:
        props["proficient"] = flag
    return {"id": pid, "name": "Blade", "kind": "weapon", "qty": 1,
            "props": props}


def armor(pid="a1", group="medium", ac=14):
    props = {"ac_base": ac, "ac_max_dex": 2}
    if group is not None:
        props["prof_group"] = group
    return {"id": pid, "name": "Breastplate", "kind": "armor", "qty": 1,
            "props": props}


# --------------------------------------------------------------- weapon axis

def test_weapon_axis_decides_proficiency_and_to_hit():
    trained = sheet(items=[weapon()], equipment={"main_hand": "w1"},
                    weapon_profs=["martial"])
    p = gear.weapon_profiles(trained)[0]
    assert p["proficient"] and not p["untrained"]
    assert p["to_hit"] == 6                          # dex +3 + prof +3 (level 5)

    bare = sheet(items=[weapon()], equipment={"main_hand": "w1"},
                 weapon_profs=[])
    p = gear.weapon_profiles(bare)[0]
    assert not p["proficient"] and p["untrained"]
    assert p["to_hit"] == 3                          # no proficiency; dice.py adds dis


def test_legacy_flag_and_no_group_unchanged():
    legacy = sheet(items=[weapon(group=None, flag=True)],
                   equipment={"main_hand": "w1"})
    p = gear.weapon_profiles(legacy)[0]
    assert p["proficient"] and not p["untrained"]    # pre-D163 flag semantics
    assert p["to_hit"] == 6
    off = sheet(items=[weapon(group=None, flag=False)],
                equipment={"main_hand": "w1"})
    assert gear.weapon_profiles(off)[0]["to_hit"] == 3


# ---------------------------------------------------------------- armor axis

def test_armor_without_training_gives_no_ac():
    items = [armor()]
    untrained = sheet(items=items, equipment={"armor": "a1"}, armor_profs=[])
    trained = sheet(items=items, equipment={"armor": "a1"},
                    armor_profs=["medium"])
    assert gear.compute_ac(untrained) == 10          # no armor benefit at all (engine unarmored base)
    assert gear.compute_ac(trained) == 16            # 14 + dex capped +2


def test_armor_without_group_data_unchanged():
    ch = sheet(items=[armor(group=None)], equipment={"armor": "a1"})
    assert gear.compute_ac(ch) == 16                 # legacy: worn-safe as before


# ----------------------------------------------------- axes come from CSV rows

def test_class_rows_fill_both_axes(client):
    dm, player, code, ch = base_room(client)
    from app import content as CT
    rid = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
    CT.store("class", rid, {"id": "tpro", "level": "1", "name": "Prof tester",
                            "hit_die": "10", "hp_base": "10",
                            "hp_per_level": "5", "weapon_prof": "simple",
                            "armor_prof": "light"})
    r = client.post(f"/api/build/{code}/{ch['id']}/apply",
                    json={"class_id": "tpro", "to": 1, "choices": {}},
                    headers=H(player))
    assert r.status_code == 200 and r.json()["ok"], r.text
    row = db.q1("SELECT weapon_profs, armor_profs FROM characters WHERE id=?",
                (ch["id"],))
    assert db.j(row["weapon_profs"], []) == ["simple"]
    assert db.j(row["armor_profs"], []) == ["light"]
