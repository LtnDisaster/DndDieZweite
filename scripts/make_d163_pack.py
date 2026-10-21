#!/usr/bin/env python3
"""Build scripts/d163_pack — the D163 CSV-only acceptance pack.

Every header is taken BYTE-IDENTICAL from the shipped content_pack (the same
schema the server validates against), every row carries brand-new D163 ids.
Regenerate with:  python scripts/make_d163_pack.py
"""
import csv
import io
import pathlib

SRC = pathlib.Path(__file__).resolve().parents[1] / "app" / "content_pack"
OUT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "d163_pack"
OUT.mkdir(exist_ok=True)


def write(filename, rows):
    header = (SRC / filename).read_text(encoding="utf-8").splitlines()[0]
    cols = next(csv.reader([header]))
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, lineterminator="\n",
                       quoting=csv.QUOTE_MINIMAL)
    w.writeheader()
    for r in rows:
        w.writerow({c: r.get(c, "") for c in cols})
    (OUT / filename).write_text(buf.getvalue(), encoding="utf-8")
    print(f"{filename}: {len(rows)} rows")


write("species.csv", [dict(
    id="sp_gremlin", name="Gremlin", size="tiny", speed_ft=30, darkvision_ft=60,
    ability_bonuses="dex+2", languages="Common; Deep Speech",
    traits="Darkvision 60 ft; Small and untrustworthy",
    manual="D163 acceptance species — house-rule build on the 2024 pattern")])

write("backgrounds.csv", [dict(
    id="bg_tinker", name="Tinker", skill_prof="arcana, history",
    tool_prof="tinker's tools", languages="Common",
    starting_items="tool_hexkit",
    feature="Spotlock: you know how things come apart",
    asi_abilities="int, wis, dex", origin_feat="feat_hexcat",
    manual="D163 acceptance background — grants the tool axis from CSV")])

write("feats.csv", [
    dict(id="feat_hexcat", name="Hexcat's Instinct", ability_boost="dex+1",
         tool_prof="tinker's tools", effect="+1 Dexterity; trained with tinker's tools",
         category="origin",
         manual="D163 origin feat — the tool grant is machine-readable"),
    dict(id="feat_brightspark", name="Brightspark", requires="Skill Proficiency — Investigation",
         ability_boost="int+1", skill_prof="investigation", effect="+1 Intelligence",
         category="general", manual="D163 general feat with a machine-readable prerequisite"),
])

write("items.csv", [
    dict(id="tool_hexkit", name="Hexing Kit", category="gear", kind="tool",
         weight=1, value_gp=25, tool="tinker's tools", tool_ability="int",
         desc="Picks, lenses and one suspiciously humming chip.",
         manual="D163 tool item — usable without any code (use_item)"),
    dict(id="dagger_misery", name="Dagger of Misery", category="weapon", kind="weapon",
         weight=1, value_gp=50, damage_dice="1d4", damage_type="piercing",
         finesse=1, attack_bonus=1, damage_bonus=1, attune=1, magic=1,
         prof_group="simple", desc="It hums when blood is near.",
         manual="D163 magic weapon — +1/+1, attuned, finesse"),
])

CL = ["id", "level"]
write("classes.csv", [
    dict(id="hedgehex", level=1, name="Hedgehex", hit_die=8, hp_base=8,
         hp_per_level=4, saves="wis",
         skill_options="arcana; history; investigation; nature; religion",
         skill_count=2, weapon_prof="simple", armor_prof="light",
         tool_prof="tinker's tools", features="Hexing Touch",
         subclass_family="hedge_paths", spellcasting_ability="wis",
         cantrips_known=1, spells_known=2, prepared=1, slot_progression="1:2",
         spell_first_level=1, starting_items="dagger_misery",
         manual="D163 acceptance class — prepared caster, ASI at 4"),
    dict(id="hedgehex", level=2, features="Hexen Bark", slot_progression="1:2"),
    dict(id="hedgehex", level=3, subclass_choice=1, slot_progression="1:2"),
    dict(id="hedgehex", level=4, ability_boost_or_feat=1, slot_progression="1:2"),
])

write("subclasses.csv", [dict(
    id="path_hex", class_id="hedgehex", level=3, name="Hexhand Path",
    features="Hexen Sight: you see the hum of old magic",
    manual="D163 acceptance subclass")])

write("spells.csv", [
    dict(id="hex_spark", name="Hex Spark", level=0, school="evocation",
         casting_ability="wis", targeting="single", range_ft=60,
         casting_time="1 action", duration="instant", resolution="attack",
         damage_dice="1d8", damage_type="radiant",
         class_list="hedgehex", manual="D163 cantrip"),
    dict(id="hex_blight", name="Hex Blight", level=1, school="necromancy",
         casting_ability="wis", targeting="single", range_ft=30,
         casting_time="1 action", duration="instant", resolution="auto",
         prep=1, prepared=1,
         effects='[{"op":"damage","expr":"2d6","type":"necrotic"},'
                 '{"op":"save","ability":"dex","dc":"auto","success":[],'
                 '"failure":[{"op":"condition","key":"cursed_glint","rounds":2}]}]',
         class_list="hedgehex",
         manual="D163 multi-effect spell: damage + Dex save + custom condition"),
])

write("conditions.csv", [dict(
    id="cursed_glint", name="Cursed Glint", glyph="✨", color="#9b59b6",
    group="condition", my_attacks_dis=1,
    effects='{"on_round":[{"op":"damage","expr":"1d4","target":"self","type":"radiant"}]}',
    manual="D163 custom condition — recurring on_round effect from CSV")])

write("creatures.csv", [dict(
    id="grick_guard", name="Grick Guard", size="medium", type="plant", ac=17,
    hp=33, speed_ft=30, str=12, dex=14, con=14, cr="1/2",
    attacks="Tendril +4 to hit, reach 5 ft, one creature: 1d6+2 piercing",
    darkvision_ft=30, tags="plant; guard",
    resistances="psychic, poison", vulnerabilities="necrotic",
    condition_immunities="charmed", climb_ft=20, recharge="Spore Burst 1",
    manual="D163 acceptance monster — defenses and resources from CSV columns")])

write("loottables.csv", [dict(
    id="d163_hoard", name="Grick cache",
    entries='[{"label":"Coin purse","weight":3,"qty":"2d6+5"},'
            '{"label":"Hexed token","weight":1,"qty":"1"}]',
    manual="D163 acceptance loot table")])

write("quests.csv", [dict(
    id="d163_q_garden", title="The Blighted Garden",
    description="Something nests under the garden. The plants know.",
    objectives="Scout the garden, Burn the vines, Route the guard",
    status="active", visibility="party",
    manual="D163 acceptance quest — projects into the live quest log")])

print("pack built at", OUT)
