"""Magic items, armor, potions: schema validation, AC computation, unidentified masking."""
import re

KINDS = ("armor", "shield", "potion", "scroll", "wand", "staff", "ring",
         "tool", "wondrous", "spellbook", "other")
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
        })
        if not out[-1]["id"]:
            out[-1]["id"] = f"it{len(out)}"
    return out


def dex_mod(char):
    stats = char.get("stats") if isinstance(char.get("stats"), dict) else {}
    try:
        return (int(stats.get("dex", 10)) - 10) // 2
    except (TypeError, ValueError):
        return 0


def compute_ac(char, items=None):
    items = items if items is not None else char.get("items", [])
    if not isinstance(items, list):
        items = []
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
                        "charges": -1, "recharge": None, "desc": "A mysterious item."})
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
    return (v - 10) // 2


def prof_bonus(char):
    try:
        lvl = max(1, int(char.get("level", 1)))
    except (TypeError, ValueError):
        lvl = 1
    return 2 + (lvl - 1) // 4


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


def spell_attack(char, ability):
    return prof_bonus(char) + _stat_mod(char, ability)


def spell_save_dc(char, ability):
    return 8 + prof_bonus(char) + _stat_mod(char, ability)


def has_spellbook(items):
    return any(i.get("kind") == "spellbook" for i in items or [])
