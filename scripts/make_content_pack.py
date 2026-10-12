"""Generate the shipped technical content pack (app/content_pack/*.csv).

A maintenance tool, not a runtime path. It writes each kind's CSV using the
canonical column order from ``app.content.SCHEMAS`` so a hand edit and this
generator can never disagree on column alignment. Rows below use ORIGINAL
names and descriptions (ATTRIBUTION.md); the human authors supply real rule
packages later. Run with:  PYTHONPATH=. python scripts/make_content_pack.py
"""
import csv
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import content as C                                   # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "app", "content_pack")


def emit(kind, rows):
    cols = [c[0] for c in C.SCHEMAS[kind]]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow({c: r.get(c, "") for c in cols})
    with open(os.path.join(OUT, C.KIND_FILE[kind]), "w", encoding="utf-8") as f:
        f.write(buf.getvalue())
    print("wrote", C.KIND_FILE[kind], f"({len(rows)} rows)")


# ---------------------------------------------------------------- species
emit("species", [
    {"id": "kin_fey", "name": "Fey-kin", "size": "medium", "speed_ft": 30,
     "darkvision_ft": 60, "ability_bonuses": "dex+2",
     "languages": "Common, Sylvan", "traits": "Darkvision 60 ft; Fey ancestry"},
    {"id": "kin_stoutheart", "name": "Stoutheart", "size": "medium", "speed_ft": 25,
     "darkvision_ft": 60, "ability_bonuses": "con+2",
     "languages": "Common, Understone", "traits": "Darkvision 60 ft; Sturdy",
     "manual": "Stonecunning is adjudicated by the DM"},
    {"id": "kin_kit", "name": "Kit-kin", "size": "small", "speed_ft": 30,
     "ability_bonuses": "dex+1, int+1", "languages": "Common, Kit",
     "traits": "Clever; Small size"},
])

# ---------------------------------------------------------------- classes
SCOUT_BASE = {"name": "Scout", "hit_die": 8, "hp_base": 14, "hp_per_level": 5,
              "saves": "dex, int", "skill_count": 4,
              "skill_options": "acrobatics, athletics, deception, insight, intimidation, investigation, perception, performance, persuasion, sleight_of_hand, stealth",
              "weapon_prof": "simple, martial", "armor_prof": "light",
              "subclass_family": "scout_traditions"}


def scout_level(lvl, **extra):
    r = {"id": "scout", "level": lvl}
    if lvl == 1:
        r.update(SCOUT_BASE)
    r.update({k: v for k, v in extra.items() if v is not None})
    return r


SCOUT_LEVELS = [
    scout_level(1, features="Expertise; Sly Strike", expertise=1),
    scout_level(2, features="Nimble Dodge"),
    scout_level(3, features="Tradition feature", subclass_choice=1),
    scout_level(4, ability_boost_or_feat=1),
    scout_level(5, features="Deft Footwork"),
    scout_level(6, features="Expertise", expertise=1),
    scout_level(7, features="Keen Instinct"),
    scout_level(8, ability_boost_or_feat=1),
    scout_level(9, features="Tradition feature"),
    scout_level(10, features="Iron Nerves"),
    scout_level(11),
    scout_level(12, ability_boost_or_feat=1),
    scout_level(13, features="Tradition feature"),
    scout_level(14, features="Swift Escape"),
    scout_level(15),
    scout_level(16, ability_boost_or_feat=1),
    scout_level(17, features="Tradition feature"),
    scout_level(18, features="Elusive"),
    scout_level(19, ability_boost_or_feat=1),
    scout_level(20, features="Fortune of the Scout"),
]

ADEPT_BASE = {"name": "Adept", "hit_die": 6, "hp_base": 8, "hp_per_level": 4,
              "saves": "int, wis", "spellcasting_ability": "int",
              "subclass_family": "arcane_traditions", "prepared": 1,
              "slot_progression": "full"}


def adept_level(lvl, cantrips=0, known=0, **extra):
    r = {"id": "adept", "level": lvl, "cantrips_known": cantrips,
         "spells_known": known}
    if lvl == 1:
        r.update(ADEPT_BASE)
    r.update({k: v for k, v in extra.items() if v is not None})
    return r


# (cantrips, known, extra) per level 1..20
ADEPT_TABLE = [
    (3, 6, {"features": "Spellcasting; Arcane Recovery"}),
    (3, 8, {"subclass_choice": 1, "features": "Tradition feature"}),
    (3, 10, {}), (4, 11, {"ability_boost_or_feat": 1}),
    (4, 13, {}), (4, 14, {}), (4, 16, {}), (4, 17, {"ability_boost_or_feat": 1}),
    (4, 19, {}), (5, 20, {}), (5, 22, {}), (5, 23, {"ability_boost_or_feat": 1}),
    (5, 25, {}), (5, 26, {}), (5, 28, {}), (5, 29, {"ability_boost_or_feat": 1}),
    (5, 31, {}), (5, 32, {}), (5, 34, {}), (5, 36, {"features": "Arcane Mastery"}),
]
ADEPT_LEVELS = [adept_level(i + 1, c, k, **e) for i, (c, k, e) in enumerate(ADEPT_TABLE)]

emit("class", SCOUT_LEVELS + ADEPT_LEVELS)

# ---------------------------------------------------------------- subclasses
emit("subclass", [
    {"id": "tradition_stalker", "class_id": "scout", "level": 3, "name": "Stalker Tradition",
     "features": "Careful Step; climb speed equals walking speed"},
    {"id": "tradition_stalker", "class_id": "scout", "level": 9, "name": "Vanishing Step",
     "features": "Hide with a Bonus action"},
    {"id": "tradition_stalker", "class_id": "scout", "level": 13, "name": "Evasive Footwork",
     "features": "Take no damage when you move away"},
    {"id": "tradition_stalker", "class_id": "scout", "level": 17, "name": "Uncatchable",
     "features": "Only an opportunity attack can stop you"},
    {"id": "school_ember", "class_id": "adept", "level": 2, "name": "Ember School",
     "features": "Ember Affinity; learn a bonus fire spell", "spells_grant": "bolt, spark"},
    {"id": "school_ember", "class_id": "adept", "level": 6, "name": "Shielded Ember",
     "features": "Reactions resist fire damage"},
    {"id": "school_ember", "class_id": "adept", "level": 10, "name": "Burn Away",
     "features": "Once per rest, burn conditions"},
    {"id": "school_ember", "class_id": "adept", "level": 14, "name": "Ember Storm",
     "features": "Area feature", "manual": "area burst resolved by the DM"},
])

# ---------------------------------------------------------------- items
emit("item", [
    {"id": "sword_plus1", "name": "Sword +1", "kind": "weapon", "category": "weapon",
     "weight": 3, "value_gp": 25, "damage_dice": "1d8", "attack_bonus": 1,
     "damage_bonus": 1, "damage_type": "slashing", "magic": 1,
     "desc": "Adds +1 to attack and +1 to damage, but only when you attack with this sword."},
    {"id": "sword_versatile", "name": "Versatile Sword", "kind": "weapon", "category": "weapon",
     "weight": 3, "value_gp": 20, "damage_dice": "1d8", "damage_dice_two_handed": "1d10",
     "versatile": 1, "desc": "One-handed 1d8. Two-handed 1d10. Choose the grip."},
    {"id": "axe_great", "name": "Great Axe", "kind": "weapon", "category": "weapon",
     "weight": 7, "value_gp": 30, "damage_dice": "1d12", "two_handed": 1,
     "damage_type": "slashing", "desc": "Requires two hands to wield."},
    {"id": "bow_long", "name": "Long Bow", "kind": "weapon", "category": "weapon",
     "weight": 2, "value_gp": 50, "damage_dice": "1d8", "two_handed": 1,
     "range_normal_ft": 150, "range_long_ft": 600, "damage_type": "piercing",
     "desc": "Normal range 150 ft, long range 600 ft."},
    {"id": "dagger_surge", "name": "Dagger of the Surge", "kind": "weapon", "category": "weapon",
     "weight": 1, "damage_dice": "1d4", "finesse": 1, "attack_bonus": 1,
     "extra_damage_dice": "+1d8", "extra_damage_type": "lightning", "magic": 1,
     "desc": "+1 to attack. On a hit it deals an extra 1d8 lightning damage."},
    {"id": "ring_warding", "name": "Ring of Warding", "kind": "ring", "category": "wondrous",
     "ac_bonus": 2, "magic": 1, "attune": 1, "desc": "While attuned this ring grants +2 to AC."},
    {"id": "leather_vest", "name": "Leather Vest", "kind": "armor", "category": "armor",
     "weight": 5, "value_gp": 10, "ac_base": 11, "ac_max_dex": 2,
     "desc": "Base AC 11 plus your Dexterity modifier up to +2."},
    {"id": "gloves_thief", "name": "Gloves of the Thief", "kind": "wondrous", "category": "other",
     "skill_prof": "stealth, sleight_of_hand", "magic": 1, "attune": 1,
     "desc": "While worn grants proficiency in Stealth and Sleight of Hand."},
    {"id": "goggles_night", "name": "Goggles of the Night", "kind": "wondrous", "category": "other",
     "darkvision_ft": 60, "magic": 1, "attune": 1, "desc": "While worn you gain darkvision out to 60 feet."},
    {"id": "gloves_giant", "name": "Gloves of the Giant", "kind": "wondrous", "category": "other",
     "attribute_set": "str=15", "magic": 1, "attune": 1,
     "desc": "While worn your Strength equals 15 (it never lowers a higher score)."},
    {"id": "potion_heal", "name": "Healing Draught", "kind": "potion", "category": "potion",
     "value_gp": 25, "heal_dice": "2d4+2", "desc": "Drink to regain 2d4+2 hit points."},
    {"id": "talisman_fate", "name": "Talisman of Fate", "kind": "wondrous", "category": "other",
     "magic": 1, "attune": 1,
     "manual": "Reroll one failed saving throw once per dawn. The DM resolves this manually."},
])

# ---------------------------------------------------------------- spells
emit("spell", [
    {"id": "spark", "name": "Test Spark", "level": 0, "school": "evocation",
     "casting_ability": "int", "targeting": "single", "range_ft": 120,
     "casting_time": "1 action", "duration": "instant", "resolution": "attack",
     "damage_dice": "1d8", "damage_type": "fire", "class_list": "adept, warden",
     "scaling_note": "Damage grows with character level (manual today)"},
    {"id": "bolt", "name": "Test Bolt", "level": 2, "school": "evocation",
     "casting_ability": "int", "targeting": "area", "shape": "circle", "size_ft": 20,
     "range_ft": 150, "casting_time": "1 action", "duration": "instant",
     "resolution": "save", "save": "dex", "on_save": "half", "damage_dice": "8d6",
     "damage_type": "fire", "upcast_step": "+1d6", "upcast_scaling": 1, "class_list": "adept",
     "scaling_note": "+1d6 per slot level above 2",
     "manual": "upcast dice scaling is NOT auto-applied; DM rolls the extra dice"},
    {"id": "mend", "name": "Mend", "level": 0, "school": "transmutation",
     "casting_ability": "int", "targeting": "single", "casting_time": "1 action",
     "duration": "instant", "resolution": "auto", "heal_dice": "1d4+1",
     "class_list": "adept"},
    {"id": "arcane_ward", "name": "Arcane Ward", "level": 1, "school": "abjuration",
     "casting_ability": "int", "targeting": "self", "casting_time": "1 action",
     "duration": "10 minutes", "resolution": "auto", "class_list": "adept",
     "manual": "Temp hit points are tracked by the DM"},
])

# ---------------------------------------------------------------- backgrounds
emit("background", [
    {"id": "bg_scholar", "name": "Scholar", "skill_prof": "arcana, history",
     "languages": "Common, Celestial", "starting_items": "potion_heal",
     "feature": "Lots of Research: you can find lore others cannot"},
    {"id": "bg_urchin", "name": "Urchin", "skill_prof": "sleight_of_hand, stealth",
     "tool_prof": "thieves' tools", "languages": "Common",
     "starting_items": "sword_plus1, coin purse", "feature": "City Secrets: you know a hidden hideout"},
])

# ---------------------------------------------------------------- feats
emit("feat", [
    {"id": "feat_keen", "name": "Keen Mind", "requires": "Perception 5 ranks",
     "ability_boost": "wis+1", "skill_prof": "perception, investigation",
     "effect": "+1 Wisdom; +1 to Perception and Investigation checks"},
    {"id": "feat_nimble", "name": "Nimble Steps", "ability_boost": "dex+1",
     "effect": "+1 Dexterity (max 20)",
     "manual": "the 5 ft speed increase is not automated today"},
])

# ---------------------------------------------------------------- creatures
emit("creature", [
    {"id": "wolfkin", "name": "Wolfkin", "size": "medium", "type": "beast",
     "ac": 13, "hp": 11, "speed_ft": 40, "str": 12, "dex": 15, "con": 12,
     "int": 3, "wis": 12, "cha": 6, "cr": "1/4", "skills": "perception, stealth",
     "saves": "dex, wis", "attacks": "Bite +4 to hit; 1d6+2 piercing",
     "tags": "companion, beast", "companion": 1},
    {"id": "hawkkin", "name": "Hawk-kin", "size": "tiny", "type": "beast",
     "ac": 14, "hp": 7, "speed_ft": 10, "fly_ft": 60, "str": 4, "dex": 18,
     "con": 11, "int": 2, "wis": 14, "cha": 7, "cr": "1/4", "skills": "perception",
     "attacks": "Talons +6 to hit; 1d4+4 piercing", "darkvision_ft": 60,
     "tags": "companion, mount, flyer", "companion": 1},
])

print("done.")
