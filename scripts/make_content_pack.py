"""Generate the shipped technical content pack (app/content_pack/*.csv).

A maintenance tool, not a runtime path. It writes each kind's CSV using the
canonical column order from ``app.content.SCHEMAS``. NOTE (D108): this data
block was RE-SYNCED from the shipped CSVs on 2026-10-14 — earlier packs had
been hand-extended after the last generator run (D97 casters, D105 kits), the
generator had gone stale, and a blind regeneration silently dropped them.
The generator is now byte-faithful: running it must NEVER change a shipped
file; if you hand-edit a CSV, update the block below in the same change
(verify: run it twice, no file may change). Rows use ORIGINAL names and
descriptions (ATTRIBUTION.md); demo backgrounds/feats carry 2024 origin
fields with house-rule notes. Run with:
  PYTHONPATH=. python scripts/make_content_pack.py
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


# ------------------------------------------------------------ speciess
emit("species", [
    {'id': 'kin_fey', 'name': 'Fey-kin', 'size': 'medium', 'speed_ft': '30', 'darkvision_ft': '60', 'ability_bonuses': 'dex+2', 'languages': 'Common, Sylvan', 'traits': 'Darkvision 60 ft; Fey ancestry'},
    {'id': 'kin_stoutheart', 'name': 'Stoutheart', 'size': 'medium', 'speed_ft': '25', 'darkvision_ft': '60', 'ability_bonuses': 'con+2', 'languages': 'Common, Understone', 'traits': 'Darkvision 60 ft; Sturdy', 'manual': 'Stonecunning is adjudicated by the DM'},
    {'id': 'kin_kit', 'name': 'Kit-kin', 'size': 'small', 'speed_ft': '30', 'ability_bonuses': 'dex+1, int+1', 'languages': 'Common, Kit', 'traits': 'Clever; Small size'},
])

# ------------------------------------------------------------ classs
emit("class", [
    {'id': 'scout', 'level': '1', 'name': 'Scout', 'hit_die': '8', 'hp_base': '14', 'hp_per_level': '5', 'saves': 'dex, int', 'skill_options': 'acrobatics, athletics, deception, insight, intimidation, investigation, perception, performance, persuasion, sleight_of_hand, stealth', 'skill_count': '4', 'weapon_prof': 'simple, martial', 'armor_prof': 'light', 'features': 'Expertise; Sly Strike', 'expertise': '1', 'subclass_family': 'scout_traditions', 'starting_items': 'dagger_surge, potion_heal x2', 'starting_choices': 'weapon=bow_long|sword_versatile; kit=gloves_thief|goggles_night'},
    {'id': 'scout', 'level': '2', 'features': 'Nimble Dodge'},
    {'id': 'scout', 'level': '3', 'features': 'Tradition feature', 'subclass_choice': '1'},
    {'id': 'scout', 'level': '4', 'ability_boost_or_feat': '1'},
    {'id': 'scout', 'level': '5', 'features': 'Deft Footwork'},
    {'id': 'scout', 'level': '6', 'features': 'Expertise', 'expertise': '1'},
    {'id': 'scout', 'level': '7', 'features': 'Keen Instinct'},
    {'id': 'scout', 'level': '8', 'ability_boost_or_feat': '1'},
    {'id': 'scout', 'level': '9', 'features': 'Tradition feature'},
    {'id': 'scout', 'level': '10', 'features': 'Iron Nerves'},
    {'id': 'scout', 'level': '11'},
    {'id': 'scout', 'level': '12', 'ability_boost_or_feat': '1'},
    {'id': 'scout', 'level': '13', 'features': 'Tradition feature'},
    {'id': 'scout', 'level': '14', 'features': 'Swift Escape'},
    {'id': 'scout', 'level': '15'},
    {'id': 'scout', 'level': '16', 'ability_boost_or_feat': '1'},
    {'id': 'scout', 'level': '17', 'features': 'Tradition feature'},
    {'id': 'scout', 'level': '18', 'features': 'Elusive'},
    {'id': 'scout', 'level': '19', 'ability_boost_or_feat': '1'},
    {'id': 'scout', 'level': '20', 'features': 'Fortune of the Scout'},
    {'id': 'adept', 'level': '1', 'name': 'Adept', 'hit_die': '6', 'hp_base': '8', 'hp_per_level': '4', 'saves': 'int, wis', 'features': 'Spellcasting; Arcane Recovery', 'subclass_family': 'arcane_traditions', 'spellcasting_ability': 'int', 'cantrips_known': '3', 'spells_known': '6', 'prepared': '1', 'slot_progression': '1:2', 'spell_first_level': '1'},
    {'id': 'adept', 'level': '2', 'features': 'Tradition feature', 'subclass_choice': '1', 'cantrips_known': '3', 'spells_known': '8', 'slot_progression': '1:3', 'spell_first_level': '1'},
    {'id': 'adept', 'level': '3', 'cantrips_known': '3', 'spells_known': '10', 'slot_progression': '1:4;2:2', 'spell_first_level': '1'},
    {'id': 'adept', 'level': '4', 'ability_boost_or_feat': '1', 'cantrips_known': '4', 'spells_known': '11', 'slot_progression': '1:4;2:3', 'spell_first_level': '1'},
    {'id': 'adept', 'level': '5', 'cantrips_known': '4', 'spells_known': '13', 'slot_progression': '1:4;2:3;3:2', 'spell_first_level': '1'},
    {'id': 'adept', 'level': '6', 'cantrips_known': '4', 'spells_known': '14', 'slot_progression': '1:4;2:3;3:3', 'spell_first_level': '1'},
    {'id': 'adept', 'level': '7', 'cantrips_known': '4', 'spells_known': '16', 'slot_progression': '1:4;2:3;3:3;4:1', 'spell_first_level': '1'},
    {'id': 'adept', 'level': '8', 'ability_boost_or_feat': '1', 'cantrips_known': '4', 'spells_known': '17', 'slot_progression': '1:4;2:3;3:3;4:2', 'spell_first_level': '1'},
    {'id': 'adept', 'level': '9', 'cantrips_known': '4', 'spells_known': '19', 'slot_progression': '1:4;2:3;3:3;4:3;5:1', 'spell_first_level': '1'},
    {'id': 'adept', 'level': '10', 'cantrips_known': '5', 'spells_known': '20', 'slot_progression': '1:4;2:3;3:3;4:3;5:2', 'spell_first_level': '1'},
    {'id': 'adept', 'level': '11', 'cantrips_known': '5', 'spells_known': '22', 'slot_progression': '1:4;2:3;3:3;4:3;5:3;6:1', 'spell_first_level': '1'},
    {'id': 'adept', 'level': '12', 'ability_boost_or_feat': '1', 'cantrips_known': '5', 'spells_known': '23', 'slot_progression': '1:4;2:3;3:3;4:3;5:3;6:1', 'spell_first_level': '1'},
    {'id': 'adept', 'level': '13', 'cantrips_known': '5', 'spells_known': '25', 'slot_progression': '1:4;2:3;3:3;4:3;5:3;6:1;7:1', 'spell_first_level': '1'},
    {'id': 'adept', 'level': '14', 'cantrips_known': '5', 'spells_known': '26', 'slot_progression': '1:4;2:3;3:3;4:3;5:3;6:1;7:1', 'spell_first_level': '1'},
    {'id': 'adept', 'level': '15', 'cantrips_known': '5', 'spells_known': '28', 'slot_progression': '1:4;2:3;3:3;4:3;5:3;6:1;7:1;8:1', 'spell_first_level': '1'},
    {'id': 'adept', 'level': '16', 'ability_boost_or_feat': '1', 'cantrips_known': '5', 'spells_known': '29', 'slot_progression': '1:4;2:3;3:3;4:3;5:3;6:1;7:1;8:1', 'spell_first_level': '1'},
    {'id': 'adept', 'level': '17', 'cantrips_known': '5', 'spells_known': '31', 'slot_progression': '1:4;2:3;3:3;4:3;5:3;6:1;7:1;8:1;9:1', 'spell_first_level': '1'},
    {'id': 'adept', 'level': '18', 'cantrips_known': '5', 'spells_known': '32', 'slot_progression': '1:4;2:3;3:3;4:3;5:3;6:2;7:1;8:1;9:1', 'spell_first_level': '1'},
    {'id': 'adept', 'level': '19', 'cantrips_known': '5', 'spells_known': '34', 'slot_progression': '1:4;2:3;3:3;4:3;5:3;6:2;7:1;8:1;9:1', 'spell_first_level': '1'},
    {'id': 'adept', 'level': '20', 'features': 'Arcane Mastery', 'cantrips_known': '5', 'spells_known': '36', 'slot_progression': '1:4;2:3;3:3;4:3;5:3;6:2;7:2;8:1;9:1', 'spell_first_level': '1'},
    {'id': 'warden', 'level': '1', 'name': 'Warden', 'hit_die': '10', 'hp_base': '12', 'hp_per_level': '5', 'saves': 'wis; cha', 'skill_options': 'animal_handling;athletics;insight;perception;survival', 'skill_count': '2', 'weapon_prof': 'simple; martial', 'armor_prof': 'all armor; shields', 'features': "Warden's Bond", 'starting_choices': 'focus=ring_warding|gloves_giant'},
    {'id': 'warden', 'level': '2', 'hit_die': '10', 'hp_base': '12', 'hp_per_level': '5', 'saves': 'wis; cha', 'spellcasting_ability': 'wis', 'cantrips_known': '2', 'spells_known': '2', 'slot_progression': '1:2', 'spell_first_level': '2'},
    {'id': 'warden', 'level': '3', 'hit_die': '10', 'hp_base': '12', 'hp_per_level': '5', 'saves': 'wis; cha', 'spellcasting_ability': 'wis', 'cantrips_known': '2', 'spells_known': '2', 'slot_progression': '1:3', 'spell_first_level': '2'},
    {'id': 'warden', 'level': '4', 'hit_die': '10', 'hp_base': '12', 'hp_per_level': '5', 'saves': 'wis; cha', 'ability_boost_or_feat': '1', 'spellcasting_ability': 'wis', 'cantrips_known': '2', 'spells_known': '2', 'slot_progression': '1:3', 'spell_first_level': '2'},
    {'id': 'warden', 'level': '5', 'hit_die': '10', 'hp_base': '12', 'hp_per_level': '5', 'saves': 'wis; cha', 'spellcasting_ability': 'wis', 'cantrips_known': '2', 'spells_known': '2', 'slot_progression': '1:4;2:2', 'spell_first_level': '2'},
    {'id': 'warden', 'level': '6', 'hit_die': '10', 'hp_base': '12', 'hp_per_level': '5', 'saves': 'wis; cha', 'spellcasting_ability': 'wis', 'cantrips_known': '2', 'spells_known': '2', 'slot_progression': '1:4;2:2', 'spell_first_level': '2'},
    {'id': 'warden', 'level': '7', 'hit_die': '10', 'hp_base': '12', 'hp_per_level': '5', 'saves': 'wis; cha', 'spellcasting_ability': 'wis', 'cantrips_known': '2', 'spells_known': '2', 'slot_progression': '1:4;2:3', 'spell_first_level': '2'},
    {'id': 'warden', 'level': '8', 'hit_die': '10', 'hp_base': '12', 'hp_per_level': '5', 'saves': 'wis; cha', 'ability_boost_or_feat': '1', 'spellcasting_ability': 'wis', 'cantrips_known': '2', 'spells_known': '2', 'slot_progression': '1:4;2:3', 'spell_first_level': '2'},
    {'id': 'warden', 'level': '9', 'hit_die': '10', 'hp_base': '12', 'hp_per_level': '5', 'saves': 'wis; cha', 'spellcasting_ability': 'wis', 'cantrips_known': '2', 'spells_known': '2', 'slot_progression': '1:4;2:3;3:2', 'spell_first_level': '2'},
    {'id': 'warden', 'level': '10', 'hit_die': '10', 'hp_base': '12', 'hp_per_level': '5', 'saves': 'wis; cha', 'spellcasting_ability': 'wis', 'cantrips_known': '2', 'spells_known': '2', 'slot_progression': '1:4;2:3;3:2', 'spell_first_level': '2'},
    {'id': 'warden', 'level': '11', 'hit_die': '10', 'hp_base': '12', 'hp_per_level': '5', 'saves': 'wis; cha', 'spellcasting_ability': 'wis', 'cantrips_known': '2', 'spells_known': '2', 'slot_progression': '1:4;2:3;3:3', 'spell_first_level': '2'},
    {'id': 'warden', 'level': '12', 'hit_die': '10', 'hp_base': '12', 'hp_per_level': '5', 'saves': 'wis; cha', 'ability_boost_or_feat': '1', 'spellcasting_ability': 'wis', 'cantrips_known': '2', 'spells_known': '2', 'slot_progression': '1:4;2:3;3:3', 'spell_first_level': '2'},
    {'id': 'warden', 'level': '13', 'hit_die': '10', 'hp_base': '12', 'hp_per_level': '5', 'saves': 'wis; cha', 'spellcasting_ability': 'wis', 'cantrips_known': '2', 'spells_known': '2', 'slot_progression': '1:4;2:3;3:3;4:1', 'spell_first_level': '2'},
    {'id': 'warden', 'level': '14', 'hit_die': '10', 'hp_base': '12', 'hp_per_level': '5', 'saves': 'wis; cha', 'spellcasting_ability': 'wis', 'cantrips_known': '2', 'spells_known': '2', 'slot_progression': '1:4;2:3;3:3;4:1', 'spell_first_level': '2'},
    {'id': 'warden', 'level': '15', 'hit_die': '10', 'hp_base': '12', 'hp_per_level': '5', 'saves': 'wis; cha', 'spellcasting_ability': 'wis', 'cantrips_known': '2', 'spells_known': '2', 'slot_progression': '1:4;2:3;3:3;4:2', 'spell_first_level': '2'},
    {'id': 'warden', 'level': '16', 'hit_die': '10', 'hp_base': '12', 'hp_per_level': '5', 'saves': 'wis; cha', 'ability_boost_or_feat': '1', 'spellcasting_ability': 'wis', 'cantrips_known': '2', 'spells_known': '2', 'slot_progression': '1:4;2:3;3:3;4:2', 'spell_first_level': '2'},
    {'id': 'warden', 'level': '17', 'hit_die': '10', 'hp_base': '12', 'hp_per_level': '5', 'saves': 'wis; cha', 'spellcasting_ability': 'wis', 'cantrips_known': '2', 'spells_known': '2', 'slot_progression': '1:4;2:3;3:3;4:3;5:1', 'spell_first_level': '2'},
    {'id': 'warden', 'level': '18', 'hit_die': '10', 'hp_base': '12', 'hp_per_level': '5', 'saves': 'wis; cha', 'spellcasting_ability': 'wis', 'cantrips_known': '2', 'spells_known': '2', 'slot_progression': '1:4;2:3;3:3;4:3;5:1', 'spell_first_level': '2'},
    {'id': 'warden', 'level': '19', 'hit_die': '10', 'hp_base': '12', 'hp_per_level': '5', 'saves': 'wis; cha', 'ability_boost_or_feat': '1', 'spellcasting_ability': 'wis', 'cantrips_known': '2', 'spells_known': '2', 'slot_progression': '1:4;2:3;3:3;4:3;5:2', 'spell_first_level': '2'},
    {'id': 'warden', 'level': '20', 'hit_die': '10', 'hp_base': '12', 'hp_per_level': '5', 'saves': 'wis; cha', 'spellcasting_ability': 'wis', 'cantrips_known': '2', 'spells_known': '2', 'slot_progression': '1:4;2:3;3:3;4:3;5:2', 'spell_first_level': '2'},
    {'id': 'seer', 'level': '1', 'name': 'Seer', 'hit_die': '6', 'hp_base': '6', 'hp_per_level': '4', 'saves': 'con; cha', 'skill_options': 'deception;insight;intimidation;persuasion;religion', 'skill_count': '2', 'weapon_prof': 'simple', 'features': 'Spellcasting; Sorcerous Origin', 'class_resource': 'sorcery_points:level', 'spellcasting_ability': 'cha', 'cantrips_known': '3', 'spells_known': '3', 'slot_progression': '1:2', 'spell_first_level': '1', 'class_resource_reset': 'short'},
    {'id': 'seer', 'level': '2', 'hit_die': '6', 'hp_base': '6', 'hp_per_level': '4', 'saves': 'con; cha', 'class_resource': 'sorcery_points:level', 'spellcasting_ability': 'cha', 'cantrips_known': '3', 'spells_known': '3', 'slot_progression': '1:3', 'spell_first_level': '1', 'class_resource_reset': 'short'},
    {'id': 'seer', 'level': '3', 'hit_die': '6', 'hp_base': '6', 'hp_per_level': '4', 'saves': 'con; cha', 'class_resource': 'sorcery_points:level', 'spellcasting_ability': 'cha', 'cantrips_known': '3', 'spells_known': '4', 'slot_progression': '1:4;2:2', 'spell_first_level': '1', 'class_resource_reset': 'short'},
    {'id': 'seer', 'level': '4', 'hit_die': '6', 'hp_base': '6', 'hp_per_level': '4', 'saves': 'con; cha', 'ability_boost_or_feat': '1', 'class_resource': 'sorcery_points:level', 'spellcasting_ability': 'cha', 'cantrips_known': '4', 'spells_known': '4', 'slot_progression': '1:4;2:3', 'spell_first_level': '1', 'class_resource_reset': 'short'},
    {'id': 'seer', 'level': '5', 'hit_die': '6', 'hp_base': '6', 'hp_per_level': '4', 'saves': 'con; cha', 'class_resource': 'sorcery_points:level', 'spellcasting_ability': 'cha', 'cantrips_known': '4', 'spells_known': '4', 'slot_progression': '1:4;2:3;3:2', 'spell_first_level': '1', 'class_resource_reset': 'short'},
    {'id': 'seer', 'level': '6', 'hit_die': '6', 'hp_base': '6', 'hp_per_level': '4', 'saves': 'con; cha', 'class_resource': 'sorcery_points:level', 'spellcasting_ability': 'cha', 'cantrips_known': '4', 'spells_known': '4', 'slot_progression': '1:4;2:3;3:3', 'spell_first_level': '1', 'class_resource_reset': 'short'},
    {'id': 'seer', 'level': '7', 'hit_die': '6', 'hp_base': '6', 'hp_per_level': '4', 'saves': 'con; cha', 'class_resource': 'sorcery_points:level', 'spellcasting_ability': 'cha', 'cantrips_known': '4', 'spells_known': '4', 'slot_progression': '1:4;2:3;3:3;4:1', 'spell_first_level': '1', 'class_resource_reset': 'short'},
    {'id': 'seer', 'level': '8', 'hit_die': '6', 'hp_base': '6', 'hp_per_level': '4', 'saves': 'con; cha', 'ability_boost_or_feat': '1', 'class_resource': 'sorcery_points:level', 'spellcasting_ability': 'cha', 'cantrips_known': '4', 'spells_known': '4', 'slot_progression': '1:4;2:3;3:3;4:2', 'spell_first_level': '1', 'class_resource_reset': 'short'},
    {'id': 'seer', 'level': '9', 'hit_die': '6', 'hp_base': '6', 'hp_per_level': '4', 'saves': 'con; cha', 'class_resource': 'sorcery_points:level', 'spellcasting_ability': 'cha', 'cantrips_known': '4', 'spells_known': '4', 'slot_progression': '1:4;2:3;3:3;4:3;5:1', 'spell_first_level': '1', 'class_resource_reset': 'short'},
    {'id': 'seer', 'level': '10', 'hit_die': '6', 'hp_base': '6', 'hp_per_level': '4', 'saves': 'con; cha', 'class_resource': 'sorcery_points:level', 'spellcasting_ability': 'cha', 'cantrips_known': '4', 'spells_known': '4', 'slot_progression': '1:4;2:3;3:3;4:3;5:2', 'spell_first_level': '1', 'class_resource_reset': 'short'},
    {'id': 'seer', 'level': '11', 'hit_die': '6', 'hp_base': '6', 'hp_per_level': '4', 'saves': 'con; cha', 'class_resource': 'sorcery_points:level', 'spellcasting_ability': 'cha', 'cantrips_known': '4', 'spells_known': '4', 'slot_progression': '1:4;2:3;3:3;4:3;5:3;6:1', 'spell_first_level': '1', 'class_resource_reset': 'short'},
    {'id': 'seer', 'level': '12', 'hit_die': '6', 'hp_base': '6', 'hp_per_level': '4', 'saves': 'con; cha', 'ability_boost_or_feat': '1', 'class_resource': 'sorcery_points:level', 'spellcasting_ability': 'cha', 'cantrips_known': '4', 'spells_known': '4', 'slot_progression': '1:4;2:3;3:3;4:3;5:3;6:1', 'spell_first_level': '1', 'class_resource_reset': 'short'},
    {'id': 'seer', 'level': '13', 'hit_die': '6', 'hp_base': '6', 'hp_per_level': '4', 'saves': 'con; cha', 'class_resource': 'sorcery_points:level', 'spellcasting_ability': 'cha', 'cantrips_known': '4', 'spells_known': '4', 'slot_progression': '1:4;2:3;3:3;4:3;5:3;6:1;7:1', 'spell_first_level': '1', 'class_resource_reset': 'short'},
    {'id': 'seer', 'level': '14', 'hit_die': '6', 'hp_base': '6', 'hp_per_level': '4', 'saves': 'con; cha', 'class_resource': 'sorcery_points:level', 'spellcasting_ability': 'cha', 'cantrips_known': '4', 'spells_known': '4', 'slot_progression': '1:4;2:3;3:3;4:3;5:3;6:1;7:1', 'spell_first_level': '1', 'class_resource_reset': 'short'},
    {'id': 'seer', 'level': '15', 'hit_die': '6', 'hp_base': '6', 'hp_per_level': '4', 'saves': 'con; cha', 'class_resource': 'sorcery_points:level', 'spellcasting_ability': 'cha', 'cantrips_known': '4', 'spells_known': '4', 'slot_progression': '1:4;2:3;3:3;4:3;5:3;6:1;7:1;8:1', 'spell_first_level': '1', 'class_resource_reset': 'short'},
    {'id': 'seer', 'level': '16', 'hit_die': '6', 'hp_base': '6', 'hp_per_level': '4', 'saves': 'con; cha', 'ability_boost_or_feat': '1', 'class_resource': 'sorcery_points:level', 'spellcasting_ability': 'cha', 'cantrips_known': '4', 'spells_known': '4', 'slot_progression': '1:4;2:3;3:3;4:3;5:3;6:1;7:1;8:1', 'spell_first_level': '1', 'class_resource_reset': 'short'},
    {'id': 'seer', 'level': '17', 'hit_die': '6', 'hp_base': '6', 'hp_per_level': '4', 'saves': 'con; cha', 'class_resource': 'sorcery_points:level', 'spellcasting_ability': 'cha', 'cantrips_known': '4', 'spells_known': '4', 'slot_progression': '1:4;2:3;3:3;4:3;5:3;6:1;7:1;8:1;9:1', 'spell_first_level': '1', 'class_resource_reset': 'short'},
    {'id': 'seer', 'level': '18', 'hit_die': '6', 'hp_base': '6', 'hp_per_level': '4', 'saves': 'con; cha', 'class_resource': 'sorcery_points:level', 'spellcasting_ability': 'cha', 'cantrips_known': '4', 'spells_known': '4', 'slot_progression': '1:4;2:3;3:3;4:3;5:3;6:2;7:1;8:1;9:1', 'spell_first_level': '1', 'class_resource_reset': 'short'},
    {'id': 'seer', 'level': '19', 'hit_die': '6', 'hp_base': '6', 'hp_per_level': '4', 'saves': 'con; cha', 'ability_boost_or_feat': '1', 'class_resource': 'sorcery_points:level', 'spellcasting_ability': 'cha', 'cantrips_known': '4', 'spells_known': '4', 'slot_progression': '1:4;2:3;3:3;4:3;5:3;6:2;7:1;8:1;9:1', 'spell_first_level': '1', 'class_resource_reset': 'short'},
    {'id': 'seer', 'level': '20', 'hit_die': '6', 'hp_base': '6', 'hp_per_level': '4', 'saves': 'con; cha', 'features': 'Sorcerous Restoration', 'class_resource': 'sorcery_points:level', 'spellcasting_ability': 'cha', 'cantrips_known': '4', 'spells_known': '4', 'slot_progression': '1:4;2:3;3:3;4:3;5:3;6:2;7:2;8:1;9:1', 'spell_first_level': '1', 'class_resource_reset': 'short'},
])

# ------------------------------------------------------------ subclasss
emit("subclass", [
    {'id': 'tradition_stalker', 'class_id': 'scout', 'level': '3', 'name': 'Stalker Tradition', 'features': 'Careful Step; climb speed equals walking speed'},
    {'id': 'tradition_stalker', 'class_id': 'scout', 'level': '9', 'name': 'Vanishing Step', 'features': 'Hide with a Bonus action'},
    {'id': 'tradition_stalker', 'class_id': 'scout', 'level': '13', 'name': 'Evasive Footwork', 'features': 'Take no damage when you move away'},
    {'id': 'tradition_stalker', 'class_id': 'scout', 'level': '17', 'name': 'Uncatchable', 'features': 'Only an opportunity attack can stop you'},
    {'id': 'school_ember', 'class_id': 'adept', 'level': '2', 'name': 'Ember School', 'features': 'Ember Affinity; learn a bonus fire spell', 'spells_grant': 'bolt, spark'},
    {'id': 'school_ember', 'class_id': 'adept', 'level': '6', 'name': 'Shielded Ember', 'features': 'Reactions resist fire damage'},
    {'id': 'school_ember', 'class_id': 'adept', 'level': '10', 'name': 'Burn Away', 'features': 'Once per rest, burn conditions'},
    {'id': 'school_ember', 'class_id': 'adept', 'level': '14', 'name': 'Ember Storm', 'features': 'Area feature', 'manual': 'area burst resolved by the DM'},
])

# ------------------------------------------------------------ backgrounds
emit("background", [
    {'id': 'bg_scholar', 'name': 'Scholar', 'skill_prof': 'arcana, history', 'languages': 'Common, Celestial', 'starting_items': 'potion_heal', 'feature': 'Lots of Research: you can find lore others cannot', 'asi_abilities': 'int, wis, cha', 'origin_feat': 'feat_quick_study', 'manual': 'demo background — the ASI pattern follows the 2024 SRD; the feat is house-rule'},
    {'id': 'bg_urchin', 'name': 'Urchin', 'skill_prof': 'sleight_of_hand, stealth', 'tool_prof': "thieves' tools", 'languages': 'Common', 'starting_items': 'sword_plus1, coin purse', 'feature': 'City Secrets: you know a hidden hideout', 'asi_abilities': 'dex, con, cha', 'origin_feat': 'feat_alley_cat', 'manual': 'demo background — the ASI pattern follows the 2024 SRD; the feat is house-rule'},
])

# ------------------------------------------------------------ feats
emit("feat", [
    {'id': 'feat_keen', 'name': 'Keen Mind', 'requires': 'Perception 5 ranks', 'ability_boost': 'wis+1', 'skill_prof': 'perception, investigation', 'effect': '+1 Wisdom; +1 to Perception and Investigation checks', 'category': 'general', 'manual': 'demo feat (house rule); the 2024 SRD has no such prerequisite'},
    {'id': 'feat_nimble', 'name': 'Nimble Steps', 'ability_boost': 'dex+1', 'effect': '+1 Dexterity (max 20)', 'category': 'general', 'manual': 'the 5 ft speed increase is not automated today'},
    {'id': 'feat_quick_study', 'name': 'Quick Study', 'skill_prof': 'investigation', 'effect': "Proficiency in Investigation; you can recall a book's exact wording", 'category': 'origin', 'manual': 'demo origin feat (house rule) for bg_scholar'},
    {'id': 'feat_alley_cat', 'name': 'Alley Cat', 'skill_prof': 'stealth', 'effect': 'Proficiency in Stealth; you always know the nearest way out of a building', 'category': 'origin', 'manual': 'demo origin feat (house rule) for bg_urchin'},
])

# ------------------------------------------------------------ items
emit("item", [
    {'id': 'sword_plus1', 'name': 'Sword +1', 'category': 'weapon', 'kind': 'weapon', 'weight': '3', 'value_gp': '25', 'damage_dice': '1d8', 'attack_bonus': '1', 'damage_bonus': '1', 'damage_type': 'slashing', 'magic': '1', 'desc': 'Adds +1 to attack and +1 to damage, but only when you attack with this sword.'},
    {'id': 'sword_versatile', 'name': 'Versatile Sword', 'category': 'weapon', 'kind': 'weapon', 'weight': '3', 'value_gp': '20', 'damage_dice': '1d8', 'damage_dice_two_handed': '1d10', 'versatile': '1', 'desc': 'One-handed 1d8. Two-handed 1d10. Choose the grip.'},
    {'id': 'axe_great', 'name': 'Great Axe', 'category': 'weapon', 'kind': 'weapon', 'weight': '7', 'value_gp': '30', 'damage_dice': '1d12', 'two_handed': '1', 'damage_type': 'slashing', 'desc': 'Requires two hands to wield.'},
    {'id': 'bow_long', 'name': 'Long Bow', 'category': 'weapon', 'kind': 'weapon', 'weight': '2', 'value_gp': '50', 'damage_dice': '1d8', 'two_handed': '1', 'range_normal_ft': '150', 'range_long_ft': '600', 'damage_type': 'piercing', 'desc': 'Normal range 150 ft, long range 600 ft.'},
    {'id': 'dagger_surge', 'name': 'Dagger of the Surge', 'category': 'weapon', 'kind': 'weapon', 'weight': '1', 'damage_dice': '1d4', 'finesse': '1', 'attack_bonus': '1', 'extra_damage_dice': '+1d8', 'extra_damage_type': 'lightning', 'magic': '1', 'desc': '+1 to attack. On a hit it deals an extra 1d8 lightning damage.'},
    {'id': 'ring_warding', 'name': 'Ring of Warding', 'category': 'wondrous', 'kind': 'ring', 'ac_bonus': '2', 'attune': '1', 'magic': '1', 'desc': 'While attuned this ring grants +2 to AC.'},
    {'id': 'leather_vest', 'name': 'Leather Vest', 'category': 'armor', 'kind': 'armor', 'weight': '5', 'value_gp': '10', 'ac_base': '11', 'ac_max_dex': '2', 'desc': 'Base AC 11 plus your Dexterity modifier up to +2.'},
    {'id': 'gloves_thief', 'name': 'Gloves of the Thief', 'category': 'other', 'kind': 'wondrous', 'skill_prof': 'stealth, sleight_of_hand', 'attune': '1', 'magic': '1', 'desc': 'While worn grants proficiency in Stealth and Sleight of Hand.'},
    {'id': 'goggles_night', 'name': 'Goggles of the Night', 'category': 'other', 'kind': 'wondrous', 'darkvision_ft': '60', 'attune': '1', 'magic': '1', 'desc': 'While worn you gain darkvision out to 60 feet.'},
    {'id': 'gloves_giant', 'name': 'Gloves of the Giant', 'category': 'other', 'kind': 'wondrous', 'attribute_set': 'str=15', 'attune': '1', 'magic': '1', 'desc': 'While worn your Strength equals 15 (it never lowers a higher score).'},
    {'id': 'potion_heal', 'name': 'Healing Draught', 'category': 'potion', 'kind': 'potion', 'value_gp': '25', 'heal_dice': '2d4+2', 'desc': 'Drink to regain 2d4+2 hit points.'},
    {'id': 'talisman_fate', 'name': 'Talisman of Fate', 'category': 'other', 'kind': 'wondrous', 'attune': '1', 'magic': '1', 'manual': 'Reroll one failed saving throw once per dawn. The DM resolves this manually.'},
])

# ------------------------------------------------------------ spells
emit("spell", [
    {'id': 'spark', 'name': 'Test Spark', 'level': '0', 'school': 'evocation', 'casting_ability': 'int', 'targeting': 'single', 'range_ft': '120', 'casting_time': '1 action', 'duration': 'instant', 'resolution': 'attack', 'damage_dice': '1d8', 'damage_type': 'fire', 'scale_tiers': '5:+1d8;11:+1d8;17:+1d8', 'class_list': 'adept; warden; seer'},
    {'id': 'mend', 'name': 'Mend', 'level': '0', 'school': 'transmutation', 'casting_ability': 'int', 'targeting': 'single', 'range_ft': '5', 'casting_time': '1 action', 'duration': 'instant', 'resolution': 'auto', 'heal_dice': '1d4+1', 'class_list': 'adept; warden; seer', 'manual': 'Touch-range mending; DM narrates'},
    {'id': 'chill', 'name': 'Chill', 'level': '0', 'school': 'evocation', 'casting_ability': 'cha', 'targeting': 'single', 'range_ft': '30', 'casting_time': '1 action', 'duration': 'instant', 'resolution': 'save', 'save': 'dex', 'on_save': 'half', 'damage_dice': '1d6', 'damage_type': 'cold', 'scale_tiers': '5:+1d6;11:+1d6;17:+1d6', 'class_list': 'seer'},
    {'id': 'gust', 'name': 'Gust', 'level': '0', 'school': 'evocation', 'casting_ability': 'wis', 'targeting': 'single', 'range_ft': '30', 'casting_time': '1 action', 'duration': 'instant', 'resolution': 'save', 'save': 'dex', 'on_save': 'half', 'damage_dice': '1d6', 'damage_type': 'thunder', 'scale_tiers': '5:+1d6;11:+1d6;17:+1d6', 'class_list': 'warden; seer'},
    {'id': 'arcane_ward', 'name': 'Arcane Ward', 'level': '1', 'school': 'abjuration', 'casting_ability': 'int', 'targeting': 'self', 'casting_time': '1 action', 'duration': '10 minutes', 'concentration': 'True', 'resolution': 'auto', 'class_list': 'adept; warden; seer', 'manual': 'Grants temporary hit points — DM tracks'},
    {'id': 'bolt', 'name': 'Test Bolt', 'level': '2', 'school': 'evocation', 'casting_ability': 'int', 'targeting': 'area', 'shape': 'circle', 'size_ft': '20', 'range_ft': '150', 'casting_time': '1 action', 'duration': 'instant', 'resolution': 'save', 'save': 'dex', 'on_save': 'half', 'damage_dice': '8d6', 'damage_type': 'fire', 'upcast_step': '+1d6', 'upcast_scaling': '1', 'class_list': 'adept; warden; seer'},
    {'id': 'smite', 'name': 'Smiting Touch', 'level': '1', 'school': 'evocation', 'casting_ability': 'cha', 'targeting': 'single', 'range_ft': '5', 'casting_time': '1 bonus action', 'duration': 'instant', 'resolution': 'attack', 'damage_dice': '2d8', 'damage_type': 'radiant', 'class_list': 'warden; seer'},
    {'id': 'restoration', 'name': 'Lesser Restoration', 'level': '1', 'school': 'necromancy', 'casting_ability': 'wis', 'targeting': 'single', 'range_ft': '5', 'casting_time': '1 action', 'duration': 'instant', 'resolution': 'auto', 'heal_dice': '2d4+2', 'class_list': 'warden; seer'},
    {'id': 'ward_ice', 'name': 'Guarded Frost', 'level': '3', 'school': 'evocation', 'casting_ability': 'int', 'targeting': 'area', 'shape': 'circle', 'size_ft': '20', 'range_ft': '120', 'casting_time': '1 action', 'duration': 'instant', 'resolution': 'save', 'save': 'dex', 'on_save': 'half', 'damage_dice': '6d6', 'damage_type': 'cold', 'upcast_step': '+1d6', 'upcast_scaling': '1', 'class_list': 'adept; warden; seer'},
    {'id': 'curse', 'name': 'Dread Curse', 'level': '2', 'school': 'necromancy', 'casting_ability': 'cha', 'targeting': 'single', 'range_ft': '90', 'casting_time': '1 action', 'duration': 'instant', 'concentration': 'True', 'resolution': 'save', 'save': 'wis', 'on_save': 'half', 'damage_dice': '3d6', 'damage_type': 'necrotic', 'upcast_step': '+1d6', 'upcast_scaling': '1', 'class_list': 'seer'},
])

# ------------------------------------------------------------ creatures
emit("creature", [
    {'id': 'wolfkin', 'name': 'Wolfkin', 'size': 'medium', 'type': 'beast', 'ac': '13', 'hp': '11', 'speed_ft': '40', 'str': '12', 'dex': '15', 'con': '12', 'int': '3', 'wis': '12', 'cha': '6', 'cr': '1/4', 'skills': 'perception, stealth', 'saves': 'dex, wis', 'attacks': 'Bite +4 to hit; 1d6+2 piercing', 'tags': 'companion, beast', 'companion': '1'},
    {'id': 'hawkkin', 'name': 'Hawk-kin', 'size': 'tiny', 'type': 'beast', 'ac': '14', 'hp': '7', 'speed_ft': '10', 'fly_ft': '60', 'str': '4', 'dex': '18', 'con': '11', 'int': '2', 'wis': '14', 'cha': '7', 'cr': '1/4', 'skills': 'perception', 'attacks': 'Talons +6 to hit; 1d4+4 piercing', 'darkvision_ft': '60', 'tags': 'companion, mount, flyer', 'companion': '1'},
])

print("done.")
