"""Magic items, armor, potions: schema validation, AC computation, unidentified masking."""
import re

from . import db

KINDS = ("armor", "shield", "potion", "scroll", "wand", "staff", "ring",
         "tool", "wondrous", "spellbook", "weapon", "other")
RECHARGES = (None, "long")
HEAL_RE = re.compile(r"^\d{0,3}d\d+([+-]\d+)?$", re.I)
ATUNE_MAX = 3

ABILITIES = ("str", "dex", "con", "int", "wis", "cha")
CASTS = ("attack", "save", "none")
# 5e skills → (label, governing ability)
SKILLS = {
    "acrobatics": ("Acrobatics", "dex"), "animal_handling": ("Animal Handling", "wis"),
    "arcana": ("Arcana", "int"), "athletics": ("Athletics", "str"),
    "deception": ("Deception", "cha"), "history": ("History", "int"),
    "insight": ("Insight", "wis"), "intimidation": ("Intimidation", "cha"),
    "investigation": ("Investigation", "int"), "medicine": ("Medicine", "wis"),
    "nature": ("Nature", "int"), "perception": ("Perception", "wis"),
    "performance": ("Performance", "cha"), "persuasion": ("Persuasion", "cha"),
    "religion": ("Religion", "int"), "sleight_of_hand": ("Sleight of Hand", "dex"),
    "stealth": ("Stealth", "dex"), "survival": ("Survival", "wis"),
}
ITEM_ICONS = {"armor": "🛡", "shield": "🔰", "potion": "🧪", "scroll": "📜", "wand": "🪄",
              "staff": "🪵", "ring": "💍", "tool": "🧰", "wondrous": "✨",
              "spellbook": "📖", "other": "🎒"}


def _clampi(v, lo, hi, dflt=0):
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return dflt


def clean_items(items):
    out = []
    if not isinstance(items, list):
        return out
    for it in items[:40]:
        if not isinstance(it, dict):
            continue
        name = str(it.get("name", "")).strip()[:48]
        if not name:
            continue
        kind = it.get("kind", "other")
        if kind not in KINDS:
            kind = "other"
        heal = str(it.get("heal", ""))[:16]
        if heal and not HEAL_RE.match(heal):
            heal = ""
        recharge = it.get("recharge")
        if recharge not in RECHARGES:
            recharge = None
        charges = _clampi(it.get("charges", -1), -1, 999, -1)
        charges_max = charges if charges >= 0 else 1
        if recharge and charges < 0:
            charges = charges_max
        weight = it.get("weight", 0)
        try:
            weight = max(0.0, min(9999.0, round(float(weight), 1)))
        except (TypeError, ValueError):
            weight = 0.0
        try:
            qty = max(1, min(9999, int(it.get("qty", 1))))
        except (TypeError, ValueError):
            qty = 1
        out.append({
            "id": str(it.get("id", ""))[:16],
            "name": name,
            "kind": kind,
            "ac": _clampi(it.get("ac", 0), 0, 40),
            "light": bool(it.get("light")),
            "acBonus": _clampi(it.get("acBonus", 0), -5, 10),
            "heal": heal,
            "charges": charges,
            "chargesMax": charges_max,
            "recharge": recharge,
            "magic": bool(it.get("magic")),
            "attunable": bool(it.get("attunable")),
            "attuned": bool(it.get("attunable")) and bool(it.get("attuned")),
            "identified": bool(it.get("identified", True)) or not bool(it.get("magic")),
            "desc": str(it.get("desc", ""))[:200],
            # D92: inventory fields. qty defaults to 1 → every pre-sprint entry
            # IS a one-item stack; behaviour byte-identical for old rows.
            "qty": qty,
            "weight": weight,
            "stackable": bool(it.get("stackable")),
            "def_id": str(it.get("def_id", ""))[:24],
            "props": clean_props(it.get("props")),
        })
        if not out[-1]["id"]:
            out[-1]["id"] = f"it{len(out)}"
    return out


# D93: the named keys combat integration (gear.weapon_profiles, the attack
# path) reads. Typed validation ONLY for these — every other key keeps D92's
# generic scalar semantics. A wrongly-typed combat key is DROPPED, never
# coerced: a corrupted prop must not manufacture an attack bonus.
_DMG_DICE_RE = re.compile(r"^\d{1,3}d\d+([+-]\d{1,3})?$", re.I)
_PROP_BOOLS = ("proficient", "mod_to_damage")          # two_handed also bool, used by D92 rules
_PROP_INTS = {"attack_bonus": 10, "damage_bonus": 10, "range_ft": 600, "reach_ft": 60}


def clean_props(props):
    """D92: generic mechanical properties — DATA, never rules. Keys map to
    scalars (bool / number / short string); the named combat keys (D93) are
    type-validated. Anything structured, oversized or wrongly typed is dropped."""
    out = {}
    if not isinstance(props, dict):
        return out
    for k, v in list(props.items())[:20]:
        k = str(k).strip()[:24]
        if not k:
            continue
        if k == "damage_dice":
            d = str(v).strip().lower()[:16]
            if _DMG_DICE_RE.match(d):
                out[k] = d
            continue
        if k == "damage_type":
            if isinstance(v, str) and v.lower() in DAMAGE_TYPES:
                out[k] = v.lower()
            continue
        if k == "ability":
            if isinstance(v, str) and v.lower() in ABILITIES:
                out[k] = v.lower()
            continue
        if k == "two_handed" or (k in _PROP_BOOLS and isinstance(v, bool)):
            out[k] = bool(v)
            continue
        if k in _PROP_INTS:
            if isinstance(v, bool):
                continue
            if isinstance(v, (int, float)):
                out[k] = _clampi(v, -_PROP_INTS[k] if k.endswith("bonus") else 0,
                                 _PROP_INTS[k])
            continue
        if isinstance(v, bool):
            out[k] = v
        elif isinstance(v, (int, float)):
            out[k] = max(-10000, min(10000, v))
        elif isinstance(v, str):
            out[k] = v[:48]
    return out


def weapon_profiles(ch):
    """D93: SERVER-derived attack profiles — equipped items (main/off hand)
    carrying a valid props.damage_dice. THE single source for sheet display
    AND the attack path; clients render these numbers and attack by item_id,
    they never carry a bonus of their own. to_hit adds each modifier exactly
    once: ability mod + proficiency (if props.proficient) + props.attack_bonus."""
    equip = clean_equipment(ch.get("equipment"), ch.get("items"))
    by_id = {i.get("id"): i for i in ch.get("items") or [] if isinstance(i, dict)}
    out = []
    for slot in ("main_hand", "off_hand"):
        it = by_id.get(equip.get(slot))
        if not it:
            continue
        p = it.get("props") or {}
        dice = str(p.get("damage_dice") or "")
        if not _DMG_DICE_RE.match(dice):
            continue
        ability = p.get("ability") if p.get("ability") in ABILITIES else "str"
        to_hit = (stat_mod(ch, ability)
                  + (prof_bonus(ch) if p.get("proficient") else 0)
                  + _clampi(p.get("attack_bonus", 0), -10, 10))
        dmg_bonus = _clampi(p.get("damage_bonus", 0), -10, 10)
        if p.get("mod_to_damage"):
            dmg_bonus += stat_mod(ch, ability)
        out.append({"slot": slot, "item_id": it.get("id"),
                    "name": str(it.get("name", "Weapon"))[:48],
                    "ability": ability, "proficient": bool(p.get("proficient")),
                    "to_hit": to_hit, "dmg": dice.lower(), "dmg_bonus": dmg_bonus,
                    "dmg_type": p.get("damage_type") or "",
                    "range_ft": _clampi(p.get("range_ft", 0), 0, 600),
                    "reach_ft": _clampi(p.get("reach_ft", 0), 0, 60),
                    "two_handed": bool(p.get("two_handed"))})
    return out


# ---------- equipment (D92) ----------

SLOTS = ("main_hand", "off_hand", "armor", "acc1", "acc2", "acc3")
# Generic kind→slot admission — a DELIBERATELY coarse table; props.slot is the
# per-item override so no complex D&D slotting rules are hardcoded here.
SLOT_KINDS = {
    "main_hand": ("weapon", "wand", "staff", "tool", "wondrous", "other"),
    "off_hand": ("shield", "wand", "staff", "tool", "wondrous", "other"),
    "armor": ("armor",),
    "acc1": ("ring", "wondrous", "other"),
    "acc2": ("ring", "wondrous", "other"),
    "acc3": ("ring", "wondrous", "other"),
}
SLOT_LABELS = {"main_hand": "Main hand", "off_hand": "Off hand", "armor": "Armor",
               "acc1": "Accessory 1", "acc2": "Accessory 2", "acc3": "Accessory 3"}


def clean_equipment(equip, items):
    """Normalise {slot: item_id} to exactly SLOTS; references to items the
    character does not (or no longer) own are dropped. THE consistency filter —
    every read and every mutation of equipment runs it."""
    ids = {i.get("id") for i in items if isinstance(i, dict)}
    src = equip if isinstance(equip, dict) else {}
    out = {}
    for s in SLOTS:
        v = src.get(s)
        out[s] = v if isinstance(v, str) and v in ids else None
    return out


def can_equip(item, slot, equipment=None, items=None):
    """May THIS item occupy THIS slot? props.slot overrides the generic table
    (a string must match; false/empty bans equipping entirely). props.two_handed
    is the only cross-slot rule: a two-hander leaves the off hand empty."""
    if slot not in SLOTS or not isinstance(item, dict):
        return False
    ps = (item.get("props") or {}).get("slot")
    if ps is not None:
        if ps is True:
            return True                          # explicit: fits any slot
        if ps is False or ps in ("", 0):
            return False                         # explicit: never equippable
        return str(ps) == slot                   # explicit: exactly this slot
    if item.get("kind") not in SLOT_KINDS.get(slot, ()):
        return False
    if (item.get("props") or {}).get("two_handed") and slot == "off_hand":
        for s, iid in (equipment or {}).items():
            other = next((i for i in (items or []) if i.get("id") == iid), None)
            if s == "main_hand" and other and (other.get("props") or {}).get("two_handed"):
                return False
    return True


def dex_mod(char):
    return _stat_mod(char, "dex")


def compute_ac(char, items=None):
    items = items if items is not None else char.get("items", [])
    if not isinstance(items, list):
        items = []
    # D92 EQUIPPED MODE: once a character occupies any slot, ONLY equipped items
    # count. No slot filled (every pre-sprint sheet) → the legacy auto-derivation
    # below runs byte-identical — existing sheets and tests are untouched.
    equip = char.get("equipment") if isinstance(char.get("equipment"), dict) else {}
    worn = [v for v in equip.values() if v]
    if worn:
        by_id, active, seen = {i.get("id"): i for i in items if isinstance(i, dict)}, [], set()
        for v in worn:
            i = by_id.get(v)
            if i is not None and v not in seen:
                seen.add(v)
                active.append(i)
        return _ac_from_set(char, active)
    armor = next((i for i in items if i.get("kind") == "armor" and i.get("ac")), None)
    if armor:
        total = armor["ac"] + (max(0, dex_mod(char)) if armor.get("light") else 0)
    else:
        total = _clampi(char.get("ac", 10), 1, 40, 10)
    for i in items:
        if not i.get("identified", True):
            continue
        if i.get("kind") == "shield" and i.get("ac"):
            total += _clampi(i["ac"], 0, 10)
        elif i.get("acBonus"):
            total += i["acBonus"]
    return max(1, min(40, total))


def _ac_from_set(char, active):
    """AC from ONE authoritative item set (equipped mode). Same arithmetic as
    the legacy path — one formula, two admission rules."""
    armor = next((i for i in active if i.get("kind") == "armor" and i.get("ac")), None)
    if armor:
        total = armor["ac"] + (max(0, dex_mod(char)) if armor.get("light") else 0)
    else:
        total = _clampi(char.get("ac", 10), 1, 40, 10)
    for i in active:
        if not i.get("identified", True):
            continue
        if i.get("kind") == "shield" and i.get("ac"):
            total += _clampi(i["ac"], 0, 10)
        elif i.get("acBonus"):
            total += i["acBonus"]
    return max(1, min(40, total))


def attuned_count(items):
    return sum(1 for i in items if i.get("attunable") and i.get("attuned"))


def mask_items(items, mask):
    """Return a copy of items with unidentified magic hidden when mask=True."""
    out = []
    for i in items:
        if mask and i.get("magic") and not i.get("identified"):
            out.append({"id": i["id"], "name": "Unidentified item", "kind": i["kind"],
                        "magic": True, "identified": False, "unidentified": True,
                        "attunable": i.get("attunable", False), "attuned": False,
                        "ac": 0, "light": False, "acBonus": 0, "heal": "",
                        "charges": -1, "recharge": None, "desc": "A mysterious item.",
                        "qty": i.get("qty", 1), "weight": i.get("weight", 0),
                        "stackable": False, "def_id": "", "props": {}})
        else:
            out.append(dict(i))
    return out


# ---------- skills ----------

def _stat_mod(char, ability):
    stats = char.get("stats") if isinstance(char.get("stats"), dict) else {}
    try:
        v = int(stats.get(ability, 10))
    except (TypeError, ValueError):
        v = 10
    v = max(1, min(30, v))                                 # sane-score range, then classic math
    return (v - 10) // 2


def stat_mod(char, ability):
    """THE canonical ability-score modifier: floor((score-10)/2) (D56).
    Anything that needs a modifier calls this — no re-derived copies."""
    ability = str(ability or "").lower()
    if ability not in ABILITIES:
        return 0
    return _stat_mod(char, ability)


# JSON-backed character columns. as_sheet/as_row are the ONLY row↔sheet
# converters: game math (this module, room/dice, abilities) always sees a
# sheet with PARSED columns — a raw DB row carries stats/saves/skills as JSON
# strings, and _stat_mod correctly treats a non-dict as missing, which is how
# "ability modifier is silently 0" production bugs are born (2026-10 sprint).
_JSON_COLUMNS = ("stats", "skills", "saves", "items", "spells", "spell_slots",
                 "defenses", "resources", "abilities", "class_levels", "equipment")
_JSON_LIST_DEFAULTS = ("items", "spells", "resources", "abilities")


def as_sheet(char):
    """THE canonical DB row -> game-calculation sheet (D70). Idempotent: a
    sheet already holds parsed columns. Keeps the caller's dict (mutating the
    parsed columns on a q1() result is safe — rows are throwaway dicts)."""
    if not isinstance(char, dict):
        return char
    for col in _JSON_COLUMNS:
        if col not in char:
            continue
        dflt = [] if col in _JSON_LIST_DEFAULTS else {}
        parsed = db.j(char.get(col), dflt)
        char[col] = parsed if isinstance(parsed, type(dflt)) else dflt
    return char


def as_row(char):
    """THE canonical sheet -> DB row (inverse of as_sheet): JSON columns back to
    strings for persistence. Idempotent for already-stringified columns."""
    if not isinstance(char, dict):
        return char
    for col in _JSON_COLUMNS:
        if col in char and not isinstance(char[col], str):
            char[col] = db.json_dumps(char[col])
    return char


def clean_speeds(char):
    """Canonical movement modes (5e): {"walk","fly","swim","climb"} in feet.
    Accepts a PC row/sheet (speed column), an NPC blob (speed + optional
    fly/swim/climb fields), a plain int (legacy walk speed) or None.
    walk defaults to 30 ft — the other modes default to 0 = not available.
    Foundation for mode-dependent movement rules; the movement budget currently
    spends walk only (app/room/movement._walk_speed)."""
    if isinstance(char, (int, float)) and not isinstance(char, bool):
        src = {"speed": int(char)}
    elif isinstance(char, dict):
        src = char
    else:
        src = {}

    def ft(key, dflt=0):
        try:
            return max(0, min(int(src.get(key) or dflt), 999))
        except (TypeError, ValueError):
            return dflt
    walk = ft("speed") or ft("walk") or 30
    return {"walk": walk, "fly": ft("fly"), "swim": ft("swim"), "climb": ft("climb")}


def prof_bonus(char):
    # Single derivation for total level (multiclass-aware; D53) — same project
    # formula as before, fed by the canonical total_character_level().
    from . import progression
    return 2 + (progression.total_character_level(char) - 1) // 4


def clean_skills(skills):
    """Normalise to {skill_key: 0|1|2} (0 none, 1 proficient, 2 expertise)."""
    out = {}
    if isinstance(skills, dict):
        src = list(skills.items())
    elif isinstance(skills, (list, tuple)):
        src = [(k, 1) for k in skills]
    else:
        src = []
    for k, v in src:
        if k not in SKILLS:
            continue
        try:
            n = int(v)
        except (TypeError, ValueError):
            n = 1 if v else 0
        out[k] = max(0, min(2, n))
    return out


def skill_bonus(char, skills, key):
    """Return (total_bonus, is_proficient) for a skill on this character."""
    if key not in SKILLS:
        return 0, False
    lvl = skills.get(key, 0) if isinstance(skills, dict) else 0
    return _stat_mod(char, SKILLS[key][1]) + prof_bonus(char) * lvl, lvl > 0


def clean_saves(saves):
    """Normalise to {ability: bool}. Accepts dict/list/0-1 values."""
    out = {a: False for a in ABILITIES}
    if isinstance(saves, dict):
        for k, v in saves.items():
            k = str(k).lower()
            if k in out:
                out[k] = bool(v) and str(v).lower() not in ("0", "false", "off", "none")
    elif isinstance(saves, (list, tuple)):
        for k in saves:
            k = str(k).lower()
            if k in out:
                out[k] = True
    return out


def save_bonus(char, saves, ability):
    ability = str(ability or "").lower()
    if ability not in ABILITIES:
        return 0
    return _stat_mod(char, ability) + (prof_bonus(char) if clean_saves(saves).get(ability) else 0)


def hit_dice_max(char):
    try:
        return max(1, min(20, int(char.get("level", 1))))
    except (TypeError, ValueError):
        return 1


def clean_hit_die(value):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 8
    return min((4, 6, 8, 10, 12), key=lambda d: abs(d - n))


def clean_resources(resources):
    out = []
    seen = set()
    for i, r in enumerate(resources if isinstance(resources, list) else []):
        if not isinstance(r, dict):
            continue
        name = str(r.get("name", "")).strip()[:40]
        if not name:
            continue
        rid = str(r.get("id", ""))[:24] or f"res{i}"
        while rid in seen:
            rid = rid + "x"
        seen.add(rid)
        mx = _clampi(r.get("max", 1), 1, 99, 1)
        cur = _clampi(r.get("current", mx), 0, mx, mx)
        reset = str(r.get("reset", "manual")).lower()
        if reset not in ("manual", "short", "long"):
            reset = "manual"
        out.append({"id": rid, "name": name, "current": cur, "max": mx, "reset": reset})
    return out[:20]


# ---------- damage types and defenses ----------

DAMAGE_TYPES = ("acid", "bludgeoning", "cold", "fire", "force", "lightning",
                "necrotic", "piercing", "poison", "psychic", "radiant",
                "slashing", "thunder")


def clean_defenses(defenses):
    raw = defenses if isinstance(defenses, dict) else {}
    keys = ("resist", "immune", "vulnerable")
    if any(k in raw for k in keys):
        src = raw
    else:
        src = {}
        for kind, vals in raw.items():
            if kind in keys and isinstance(vals, (list, tuple)):
                src[kind] = vals
    out = {}
    for k in keys:
        vals = []
        for v in (src.get(k) or []):
            v = str(v).strip().lower()[:16]
            if v in DAMAGE_TYPES and v not in vals:
                vals.append(v)
        out[k] = vals[:12]
    return out


def apply_defense(amount, damage_type, defenses):
    try:
        amount = int(amount)
    except (TypeError, ValueError):
        amount = 0
    dtype = str(damage_type or "").strip().lower()
    if not dtype or dtype not in DAMAGE_TYPES:
        return max(0, min(99999, amount))
    d = clean_defenses(defenses)
    if dtype in d["immune"]:
        return 0
    if dtype in d["vulnerable"]:
        amount *= 2
    if dtype in d["resist"]:
        amount //= 2
    return max(0, min(99999, amount))


# ---------- spells & slots ----------

def clean_spells(spells):
    out = []
    if not isinstance(spells, list):
        return out
    for s in spells[:60]:
        if not isinstance(s, dict):
            continue
        name = str(s.get("name", "")).strip()[:48]
        if not name:
            continue
        cast = s.get("cast", "none")
        if cast not in CASTS:
            cast = "none"
        ability = str(s.get("ability", "int")).lower()
        if ability not in ABILITIES:
            ability = "int"
        save = str(s.get("save", "")).lower()
        if save not in ABILITIES:
            save = ""
        dmg = str(s.get("dmg", ""))[:16]
        if dmg and not HEAL_RE.match(dmg):
            dmg = ""
        sid = str(s.get("id", ""))[:16] or f"sp{len(out)}"
        out.append({
            "id": sid, "name": name, "level": _clampi(s.get("level", 1), 0, 9, 0),
            "school": str(s.get("school", ""))[:24], "cast": cast, "ability": ability,
            "dmg": dmg, "save": save,
            "range": str(s.get("range", ""))[:24], "duration": str(s.get("duration", ""))[:24],
        })
    seen = set()
    for it in out:
        while it["id"] in seen:
            it["id"] = it["id"] + "x"
        seen.add(it["id"])
    return out


def clean_slots(slots):
    """Normalise to {1..9: {max, used}} with used<=max. Accepts str or int keys."""
    out = {lv: {"max": 0, "used": 0} for lv in range(1, 10)}
    if isinstance(slots, dict):
        for lv in range(1, 10):
            d = slots.get(str(lv), slots.get(lv))
            if isinstance(d, dict):
                mx = _clampi(d.get("max", 0), 0, 9, 0)
                used = _clampi(d.get("used", 0), 0, 9, 0)
                out[lv] = {"max": mx, "used": min(used, mx)}
    return out


def ability_save_dc(char, ability, bonus=0):
    """Generic effect save DC: 8 + proficiency + casting-ability modifier + optional
    explicit bonus. The casting ability is CONFIGURATION (D57) — never hard-coded
    by class here. All save DCs derive from this one function."""
    return 8 + prof_bonus(char) + stat_mod(char, ability) + _clampi(bonus, -20, 20, 0)


def ability_attack_bonus(char, ability, bonus=0):
    """Generic spell/ability attack bonus: proficiency + ability modifier + optional
    explicit bonus. Works for magical or any other ability attack (D57)."""
    return prof_bonus(char) + stat_mod(char, ability) + _clampi(bonus, -20, 20, 0)


def spell_attack(char, ability, bonus=0):
    return ability_attack_bonus(char, ability, bonus)


def spell_save_dc(char, ability, bonus=0):
    return ability_save_dc(char, ability, bonus)


def has_spellbook(items):
    return any(i.get("kind") == "spellbook" for i in items or [])
