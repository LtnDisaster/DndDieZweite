"""Item math (SSOT in gear.py): AC, attunement cap, identification masking, charges."""
from app import gear


def char(ac=10, dex=10, items=None):
    return {"ac": ac, "stats": {"dex": dex}, "items": items or []}


def it(**kw):
    base = {"name": "x", "kind": "other", "ac": 0, "light": False, "acBonus": 0,
            "magic": False, "attunable": False, "attuned": False, "identified": True,
            "charges": -1, "heal": "", "recharge": None}
    base.update(kw)
    return gear.clean_items([base])[0]


# ---- AC ----
def test_no_armor_uses_sheet_ac_as_is():
    assert gear.compute_ac(char(ac=13, dex=20)) == 13  # dex does NOT add without armor


def test_light_armor_adds_full_dex_mod():
    armor = it(kind="armor", ac=12, light=True)
    assert gear.compute_ac(char(dex=20, items=[armor])) == 12 + 5


def test_medium_armor_does_not_add_dex():
    armor = it(kind="armor", ac=14, light=False)
    assert gear.compute_ac(char(dex=20, items=[armor])) == 14


def test_ac_bonus_counts_only_when_identified():
    ring_ident = it(name="Ring", magic=True, acBonus=1, identified=True)
    ring_unident = it(name="Ring", magic=True, acBonus=1, identified=False)
    assert gear.compute_ac(char(ac=10, items=[ring_ident])) == 11
    assert gear.compute_ac(char(ac=10, items=[ring_unident])) == 10


# ---- attunement ----
def test_attuned_count_and_cap():
    items = [it(name=f"a{i}", attunable=True, attuned=(i < 2)) for i in range(4)]
    assert gear.attuned_count(items) == 2
    assert gear.ATUNE_MAX == 3


def test_clean_drops_attuned_when_not_attunable():
    only = it(name="plain", attunable=False, attuned=True)
    assert only["attuned"] is False


# ---- masking ----
def test_mask_hides_unidentified_magic_only():
    items = [it(name="Secret", magic=True, identified=False, acBonus=2, desc="op"),
             it(name="Known", magic=True, identified=True, acBonus=2),
             it(name="Mundane", magic=False, ac=15)]
    masked = gear.mask_items(items, True)
    assert masked[0]["name"] == "Unidentified item"
    assert masked[0]["unidentified"] is True
    assert masked[0]["acBonus"] == 0 and masked[0]["desc"] != "op"
    assert masked[1]["name"] == "Known"        # identified -> untouched
    assert masked[2]["name"] == "Mundane"       # non-magic -> untouched


def test_mask_off_returns_real_names():
    items = [it(name="Secret", magic=True, identified=False)]
    assert gear.mask_items(items, False)[0]["name"] == "Secret"


# ---- charges / recharge ----
def test_clean_assigns_chargesmax_and_recharge_seeds_charges():
    w = gear.clean_items([{"name": "Wand", "magic": True, "charges": 3, "recharge": "long"}])[0]
    assert w["charges"] == 3 and w["chargesMax"] == 3
    auto = gear.clean_items([{"name": "Wand", "recharge": "long"}])[0]  # no charges given
    assert auto["charges"] == auto["chargesMax"] >= 1


def test_clean_gives_items_an_id():
    assert gear.clean_items([{"name": "NoId"}])[0]["id"] != ""


def test_clean_drops_empty_names_and_caps_list():
    assert gear.clean_items([{"name": "  "}]) == []
    assert len(gear.clean_items([{"name": f"i{i}"} for i in range(50)])) == 40


# ---- new item kinds ----
def test_new_kinds_preserved():
    for k in ("shield", "spellbook", "ring", "wand", "scroll", "wondrous"):
        assert gear.clean_items([{"name": "i", "kind": k}])[0]["kind"] == k


def test_shield_adds_ac_when_identified():
    sh = gear.clean_items([{"name": "Shield", "kind": "shield", "ac": 2,
                            "magic": True, "identified": True}])[0]
    assert gear.compute_ac({"ac": 12, "stats": {"dex": 10}, "items": [sh]}) == 14
    sh_un = gear.clean_items([{"name": "Shield", "kind": "shield", "ac": 2,
                               "magic": True, "identified": False}])[0]
    assert gear.compute_ac({"ac": 12, "stats": {"dex": 10}, "items": [sh_un]}) == 12


# ---- skills ----
def test_skill_bonus_includes_prof_and_expertise():
    ch = {"stats": {"wis": 20}, "level": 5}          # wis +5, PB 3
    assert gear.skill_bonus(ch, {}, "perception") == (5, False)
    assert gear.skill_bonus(ch, {"perception": 1}, "perception") == (8, True)
    assert gear.skill_bonus(ch, {"perception": 2}, "perception") == (11, True)


def test_skill_bonus_unknown_is_zero():
    assert gear.skill_bonus({"stats": {}, "level": 1}, {"bogus": 2}, "bogus") == (0, False)


def test_clean_skills_clamps_and_drops_unknown():
    s = gear.clean_skills({"perception": 2, "stealth": 1, "bogus": 2, "arcana": 9})
    assert s == {"perception": 2, "stealth": 1, "arcana": 2}


def test_skill_catalog_is_18():
    assert len(gear.SKILLS) == 18


# ---- spells & slots ----
def test_clean_spells_validates_fields():
    zap = gear.clean_spells([{"name": "Fire Bolt", "level": 0, "cast": "attack",
                              "ability": "dex", "dmg": "1d10"}])[0]
    assert zap["level"] == 0 and zap["cast"] == "attack" and zap["dmg"] == "1d10"
    bad = gear.clean_spells([{"name": "Bad", "dmg": "2d6*2", "cast": "teleport",
                              "ability": "xyz"}])[0]
    assert bad["dmg"] == "" and bad["cast"] == "none" and bad["ability"] == "int"
    assert gear.clean_spells([{"name": ""}]) == []


def test_clean_slots_normalizes_and_clamps_used():
    s = gear.clean_slots({"1": {"max": 4, "used": 9}, "2": {"max": 3}})
    assert s[1] == {"max": 4, "used": 4}
    assert s[2] == {"max": 3, "used": 0}
    assert s[9] == {"max": 0, "used": 0}


def test_spell_attack_and_save_dc():
    ch = {"stats": {"int": 20}, "level": 5}           # int +5, PB 3
    assert gear.spell_attack(ch, "int") == 8
    assert gear.spell_save_dc(ch, "int") == 16


def test_has_spellbook():
    assert gear.has_spellbook([{"kind": "spellbook"}]) is True
    assert gear.has_spellbook([{"kind": "ring"}, {"kind": "other"}]) is False
