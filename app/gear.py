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


# ---- D98: single canonical item-prop vocabulary (used by gear AND the content
# importer, which projects through inventory.clean_def -> gear.clean_props).
# No second validator elsewhere: one place decides what a prop may be.
_BONUS_DICE_RE = re.compile(r"^[+-]?\d{1,3}d\d+$", re.I)      # extra damage "+1d8"
_DICE_PROPS = ("damage_dice", "damage_dice_two_handed", "heal_dice")
_BOOL_PROPS = ("proficient", "mod_to_damage", "two_handed", "versatile",
               "finesse", "attune", "magic", "light")
_INT_PROPS = {
    "attack_bonus": (-10, 10), "damage_bonus": (-10, 10),
    "range_ft": (0, 600), "range_long_ft": (0, 600), "reach_ft": (0, 60),
    "ac_bonus": (-5, 10), "ac_base": (0, 40), "ac_max_dex": (-1, 99),
    "darkvision_ft": (0, 999), "speed_bonus_ft": (-99, 999),
    "hit_dice_bonus": (-10, 10), "charges": (-1, 999), "hands": (0, 2),
    "carry_bonus": (0, 9999),        # D99: extra carrying capacity, pounds
}


def _norm_list(v, allowed):
    """Normalise a comma/semicolon string OR a list into an ordered, de-duplicated
    list of allowed keys (skill / save / expertise grants). Tolerant of the legacy
    comma-string form already stored in DB rows."""
    if isinstance(v, str):
        parts = re.split(r"[,;]", v)
    elif isinstance(v, (list, tuple)):
        parts = list(v)
    else:
        return []
    out = []
    for p in parts:
        p = str(p).strip().lower()
        if p in allowed and p not in out:
            out.append(p)
    return out


def _norm_attr_set(v):
    """A 'set this score to a fixed value' grant (gloves/belt). Accepts
    {"ability","value"}, ["dex",15] or "dex,15"/"dex=15". -> {"ability","value"}."""
    if isinstance(v, dict):
        a, val = str(v.get("ability", "")).lower(), v.get("value")
    elif isinstance(v, (list, tuple)) and len(v) >= 2:
        a, val = str(v[0]).lower(), v[1]
    elif isinstance(v, str):
        m = re.split(r"[,=:]", v)
        if len(m) < 2:
            return None
        a, val = m[0].strip().lower(), m[1]
    else:
        return None
    if a not in ABILITIES:
        return None
    val = _clampi(val, 1, 30, 0)
    return {"ability": a, "value": val} if val >= 1 else None


def _norm_attr_bonus(v):
    """A '+/- delta to a score' grant (headband, toad cloak). Accepts dict
    {"wis":2}, "wis+2,cha+2" or [["wis",2]]. -> {ability: delta} (0 dropped)."""
    out = {}

    def add(a, d):
        a = str(a).lower()
        if a in ABILITIES:
            d = _clampi(d, -10, 10, 0)
            if d:
                out[a] = out.get(a, 0) + d
    if isinstance(v, dict):
        for a, d in v.items():
            add(a, d)
    elif isinstance(v, (list, tuple)):
        for tok in v:
            if isinstance(tok, (list, tuple)) and len(tok) >= 2:
                add(tok[0], tok[1])
    elif isinstance(v, str):
        for tok in re.split(r"[,;]", v):
            m = re.match(r"^\s*([a-z]+)\s*([+-]\d+)\s*$", tok, re.I)
            if m:
                add(m.group(1), int(m.group(2)))
    return out or None


# ---------- D106: secret per-instance curse metadata (DM-only by default) ----------
# A curse lives INSIDE the item entry (characters.items / containers.items JSON):
# instance identity only exists within one inventory — stack_add() re-issues
# entry ids on every transfer — so a side table could not follow the instance,
# while the entry dict rides along through transfer, container move and loot
# for free. clean_items() STRIPS this field by default (fail-closed: every
# read path, /state render and client PUT that predates D106 stays clean
# without knowing about curses); only server-internal mutation paths pass
# keep_curse=True, and only gear.curse_view() decides per viewer who sees what.

CURSE_NAME = 48
CURSE_DESC = 200
CURSE_WHISPER = 1000


def clean_curse(c):
    """Sanitise one stored curse dict. None = no curse (an all-empty dict is
    the same as no dict at all). Values are re-sanitised on EVERY trusted read,
    so a hand-edited DB row can never smuggle a control char or an overlong
    field into a DM view or a whisper. 'revealed' is the DM's disclosure flag
    for the CURRENT owner — gear.curse_view() gates it."""
    if not isinstance(c, dict):
        return None
    name = str(c.get("name", "")).strip()[:CURSE_NAME]
    desc = str(c.get("desc", "")).strip()[:CURSE_DESC]
    whisper = str(c.get("whisper", "")).strip()[:CURSE_WHISPER]
    if not (name or desc or whisper):
        return None
    return {"name": name, "desc": desc, "whisper": whisper,
            "revealed": bool(c.get("revealed"))}


def curse_view(items, mode="strip"):
    """THE single per-viewer disclosure filter for curse metadata.
    'dm'     — trusted passthrough (the caller already loaded with keep_curse).
    'owner'  — the owning character learns ONLY a revealed curse's name+desc;
               the whisper text never rides a sheet (it arrives via chat only).
    'strip'  — default, fail-closed: every hint of a curse vanishes."""
    out = []
    for it in items:
        curse = it.get("curse") if isinstance(it, dict) else None
        if curse is None or mode == "dm":
            out.append(it)
            continue
        it = dict(it)
        curse = clean_curse(curse)
        if mode == "owner" and curse and curse["revealed"]:
            it["curse"] = {"name": curse["name"], "desc": curse["desc"]}
        else:
            it.pop("curse", None)
        out.append(it)
    return out


def clean_items(items, keep_curse=False):
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
        props = clean_props(it.get("props"))          # canonical once; feeds the fields below
        heal = str(it.get("heal", ""))[:16]
        if heal and not HEAL_RE.match(heal):
            heal = ""
        if not heal and props.get("heal_dice"):       # D98: a content potion's heal_dice is usable
            heal = props["heal_dice"]
        recharge = it.get("recharge")
        if recharge not in RECHARGES:
            recharge = None
        if recharge is None and props.get("recharge") == "long":
            recharge = "long"
        charges = _clampi(it.get("charges", -1), -1, 999, -1)
        if charges < 0 and _clampi(props.get("charges", -1), -1, 999, -1) >= 0:
            charges = _clampi(props.get("charges"), -1, 999, -1)   # D98: content wand charges
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
        attunable = bool(it.get("attunable")) or bool(props.get("attune"))   # D98
        out.append({
            "id": str(it.get("id", ""))[:16],
            "name": name,
            "kind": kind,
            "ac": _clampi(it.get("ac", 0), 0, 40),
            "light": bool(it.get("light")) or bool(props.get("light")),
            "acBonus": _clampi(it.get("acBonus", 0), -5, 10),
            "heal": heal,
            "charges": charges,
            "chargesMax": charges_max,
            "recharge": recharge,
            "magic": bool(it.get("magic")) or bool(props.get("magic")),
            "attunable": attunable,
            "attuned": attunable and bool(it.get("attuned")),
            "identified": bool(it.get("identified", True)) or not bool(bool(it.get("magic")) or bool(props.get("magic"))),
            "desc": str(it.get("desc", ""))[:200],
            # D92: inventory fields. qty defaults to 1 → every pre-sprint entry
            # IS a one-item stack; behaviour byte-identical for old rows.
            "qty": qty,
            "weight": weight,
            "stackable": bool(it.get("stackable")),
            "def_id": str(it.get("def_id", ""))[:24],
            "grip": "two" if str(it.get("grip", "")).lower() in ("two", "2h", "two-handed") else "one",
            "props": props,
        })
        if not out[-1]["id"]:
            out[-1]["id"] = f"it{len(out)}"
        if keep_curse:                            # D106 trusted read only
            curse = clean_curse(it.get("curse"))
            if curse:
                out[-1]["curse"] = curse
    return out


# D93: the named keys combat integration (gear.weapon_profiles, the attack
# path) reads. Typed validation ONLY for these — every other key keeps D92's
# generic scalar semantics. A wrongly-typed combat key is DROPPED, never
# coerced: a corrupted prop must not manufacture an attack bonus.
_DMG_DICE_RE = re.compile(r"^\d{1,3}d\d+([+-]\d{1,3})?$", re.I)
_PROP_BOOLS = _BOOL_PROPS                                   # back-compat aliases


def clean_props(props):
    """D92/D98: THE single canonical item-prop validator — DATA, never rules. Used
    for DM definitions (inventory.clean_def) and content imports alike, so a prop
    means the same thing everywhere. Named keys are typed and range-clamped; a
    wrongly-typed value is DROPPED (never coerced — a corrupt prop must never
    manufacture a bonus). Unknown keys keep D92's generic scalar behaviour."""
    out = {}
    if not isinstance(props, dict):
        return out
    for k, v in list(props.items())[:24]:
        k = str(k).strip()[:24]
        if not k:
            continue
        if k in _DICE_PROPS:
            d = str(v).strip().lower()[:16]
            if _DMG_DICE_RE.match(d):
                out[k] = d
            continue
        if k == "extra_damage_dice":
            d = str(v).strip().lower()[:16]
            if _BONUS_DICE_RE.match(d):
                out[k] = d
            continue
        if k in ("damage_type", "extra_damage_type"):
            if isinstance(v, str) and v.lower() in DAMAGE_TYPES:
                out[k] = v.lower()
            continue
        if k == "ability":
            if isinstance(v, str) and v.lower() in ABILITIES:
                out[k] = v.lower()
            continue
        if k == "recharge":
            if str(v or "").lower() in ("long",):
                out[k] = "long"
            continue
        if k in _BOOL_PROPS:
            out[k] = v if isinstance(v, bool) else str(v).lower() in ("1", "true", "yes", "on")
            continue
        if k in _INT_PROPS:
            if isinstance(v, bool):
                continue
            if isinstance(v, (int, float)):
                lo, hi = _INT_PROPS[k]
                out[k] = _clampi(v, lo, hi)
            continue
        if k in ("skill_prof", "expertise"):
            vals = _norm_list(v, SKILLS)
            if vals:
                out[k] = vals
            continue
        if k == "save_prof":
            vals = _norm_list(v, ABILITIES)
            if vals:
                out[k] = vals
            continue
        if k == "attribute_set":
            aset = _norm_attr_set(v)
            if aset:
                out[k] = aset
            continue
        if k == "attribute_bonus":
            ab = _norm_attr_bonus(v)
            if ab:
                out[k] = ab
            continue
        if isinstance(v, bool):
            out[k] = v
        elif isinstance(v, (int, float)):
            out[k] = max(-10000, min(10000, v))
        elif isinstance(v, str):
            out[k] = v[:48]
    return out


def weapon_profiles(ch):
    """D93/D98: SERVER-derived attack profiles — equipped items (main/off hand)
    carrying a valid props.damage_dice. THE single source for sheet display AND
    the attack path; clients render these numbers and attack by item_id, they
    never carry a bonus of their own. Every modifier is applied EXACTLY once:
    ability mod + proficiency (if props.proficient) + props.attack_bonus. D98 adds
    the grip-aware dice (versatile), finesse/ranged ability choice, extra damage
    dice, and the attunement gate (an unequipped-attuned magic weapon is just the
    plain weapon: its attack/damage bonus and extra dice go inert)."""
    equip = clean_equipment(ch.get("equipment"), ch.get("items"))
    by_id = {i.get("id"): i for i in ch.get("items") or [] if isinstance(i, dict)}
    out = []
    for slot in ("main_hand", "off_hand"):
        it = by_id.get(equip.get(slot))
        if not it:
            continue
        p = clean_props(it.get("props"))
        dice = str(p.get("damage_dice") or "")
        two = str(p.get("damage_dice_two_handed") or "")
        grip_two = (bool(p.get("two_handed"))
                    or (bool(p.get("versatile")) and str(it.get("grip", "one")) == "two"))
        if two and grip_two and _DMG_DICE_RE.match(two):
            dice = two                                   # two-handed grip uses the versatile dice
        if not _DMG_DICE_RE.match(dice):
            continue
        ranged = (_clampi(p.get("range_ft", 0), 0, 600) > 0
                  or _clampi(p.get("range_long_ft", 0), 0, 600) > 0)
        ability = p.get("ability") if p.get("ability") in ABILITIES else ("dex" if ranged else "str")
        if (not ranged) and p.get("finesse") and ability == "str" \
                and stat_mod(ch, "dex") > stat_mod(ch, "str"):
            ability = "dex"                              # finesse: the wielder's better mod
        gated = bool(it.get("attunable")) and not bool(it.get("attuned"))
        to_hit = (stat_mod(ch, ability)
                  + (prof_bonus(ch) if p.get("proficient") else 0)
                  + (0 if gated else _clampi(p.get("attack_bonus", 0), -10, 10)))
        dmg_bonus = (0 if gated else _clampi(p.get("damage_bonus", 0), -10, 10))
        if p.get("mod_to_damage", True):                 # a weapon attack adds its ability mod
            dmg_bonus += stat_mod(ch, ability)
        extra = "" if gated else str(p.get("extra_damage_dice") or "")
        out.append({"slot": slot, "item_id": it.get("id"),
                    "name": str(it.get("name", "Weapon"))[:48],
                    "ability": ability, "proficient": bool(p.get("proficient")),
                    "to_hit": to_hit, "dmg": dice.lower(), "dmg_bonus": dmg_bonus,
                    "dmg_type": p.get("damage_type") or "",
                    "range_ft": _clampi(p.get("range_ft", 0), 0, 600),
                    "range_long_ft": _clampi(p.get("range_long_ft", 0), 0, 600),
                    "reach_ft": _clampi(p.get("reach_ft", 0), 0, 60),
                    "ranged": ranged, "two_handed": bool(p.get("two_handed")),
                    "versatile": bool(p.get("versatile")), "grip": "two" if grip_two else "one",
                    "finesse": bool(p.get("finesse")), "gated": gated,
                    "extra_dmg": extra.lstrip("+").lower(),
                    "extra_dmg_type": p.get("extra_damage_type") or ""})
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


def wields_two_handed(item):
    """D98: does this ITEM occupy both hands right now? True for a fixed
    two-hander (props.two_handed), or a VERSATILE weapon currently gripped
    two-handed (per-instance 'grip' the owner chose). The single rule used by
    both can_equip and inventory.equip_slot / set_grip."""
    if not isinstance(item, dict):
        return False
    p = item.get("props") or {}
    return bool(p.get("two_handed")) or (bool(p.get("versatile"))
                                         and str(item.get("grip", "one")) == "two")


def can_equip(item, slot, equipment=None, items=None):
    """May THIS item occupy THIS slot? props.slot overrides the generic table
    (a string must match; false/empty bans equipping entirely). A two-handed
    weapon (fixed, or a versatile weapon gripped two-handed — D98) leaves the
    off hand empty and can never share it with a shield."""
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
    if wields_two_handed(item) and slot == "off_hand":
        return False
    if slot == "off_hand":
        for s, iid in (equipment or {}).items():
            other = next((i for i in (items or []) if i.get("id") == iid), None)
            if s == "main_hand" and other and wields_two_handed(other):
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
        # D98: only EQUIPPED and (where required) ATTUNED items count; their AC comes
        # from the props the content importer wrote (ac_base/ac_bonus/ac_max_dex),
        # dexterity is the EFFECTIVE score (a headband of charisma raises AC too).
        return _ac_from_set(char, effective_gear(char)["active"])
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


def _ac_from_set(char, pairs):
    """AC from the authoritative equipped set (attune-gated upstream). One formula,
    two admission rules vs. the legacy path. Entry-level ac/acBonus keep D84's
    identified-gate for legacy items; CONTENT bonuses live in props (ac_base = the
    armour's own base, ac_bonus = a flat/enhancement bonus, ac_max_dex = the dex cap)
    and, per D98, apply while worn+attuned regardless of identification."""
    armor = None
    for it, p in pairs:
        if it.get("kind") == "armor" and (it.get("ac") or p.get("ac_base")):
            armor = (it, p)
            break
    if armor:
        it, p = armor
        base = it.get("ac") or _clampi(p.get("ac_base", 0), 0, 40, 0)
        dm = dex_mod(char)
        if "ac_max_dex" in p:
            cap = _clampi(p.get("ac_max_dex"), -1, 99, -1)
            add = dm if cap < 0 else (min(dm, cap) if dm > 0 else 0)
        else:
            add = max(0, dm) if it.get("light") else 0
        total = base + add
    else:
        total = _clampi(char.get("ac", 10), 1, 40, 10)
    for it, p in pairs:
        prop_ac = _clampi(p.get("ac_bonus", 0), -5, 10, 0)
        if armor and it is armor[0]:
            total += prop_ac                            # armour enhancement
            continue
        ident = it.get("identified", True)
        if it.get("kind") == "shield":
            if ident:
                total += _clampi(it.get("ac", 0), 0, 10, 0)   # legacy shield ac
            total += prop_ac
        else:
            if ident:
                total += _clampi(it.get("acBonus", 0), -5, 10, 0)   # legacy ring bonus
            total += prop_ac
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


# ---------- D98: the equipment overlay (DERIVED, transient, never persisted) --
# Everything a character gets from what it wears/wields is computed FROM the base
# columns + items + equipment on EVERY read, so equipping, unequipping, attuning
# or a restart can never double-apply or go stale: there is nothing stored to go
# stale. Base stats are NEVER mutated; effective stats live only here. Identification
# affects the DISPLAY of unknown properties, but not the passive mechanic of an
# equipped+attuned item (D98 decision 1), so this overlay reads the REAL props.

def _base_score(char, ability):
    stats = char.get("stats") if isinstance(char.get("stats"), dict) else {}
    try:
        v = int(stats.get(ability, 10))
    except (TypeError, ValueError):
        v = 10
    return max(1, min(30, v))


def _active_gear(char):
    """Equipped items whose passive effect is live: occupying a slot AND (when
    attunable) currently attuned. Returns [(item, normalised_props), ...]."""
    items = char.get("items")
    if not isinstance(items, list):
        items = []
    equip = clean_equipment(char.get("equipment"), items)
    by_id = {i.get("id"): i for i in items if isinstance(i, dict)}
    out = []
    for iid in equip.values():
        it = by_id.get(iid)
        if it is None:
            continue
        if it.get("attunable") and not it.get("attuned"):
            continue                             # attunement required and not met → inert
        out.append((it, clean_props(it.get("props"))))
    return out


def effective_gear(char):
    """One derivation for every gear-driven character value. Recomputed fresh per
    call — no memo on a mutable dict, so it can never be stale after equip/unequip.
    attribute_set applies first (a score becomes the item's value unless it is
    already higher — a belt/gloves never LOWER a score), then attribute_bonus
    (stacking deltas); skill/save grants and expertise are SETS (no double
    proficiency); darkvision is the max granted, speed_bonus the sum."""
    active = _active_gear(char) if isinstance(char, dict) else []
    stats = {a: _base_score(char, a) for a in ABILITIES}
    bonus, skill_prof, expertise, save_prof = {}, set(), set(), set()
    darkvision, speed, carry = 0, 0, 0
    for _it, p in active:
        aset = p.get("attribute_set")
        if aset:
            a = aset.get("ability")
            if a in ABILITIES:
                stats[a] = max(stats[a], _clampi(aset.get("value"), 1, 30, stats[a]))
        for a, d in (p.get("attribute_bonus") or {}).items():
            if a in ABILITIES:
                bonus[a] = bonus.get(a, 0) + d
        for k in p.get("skill_prof") or []:
            if k in SKILLS:
                skill_prof.add(k)
        for k in p.get("expertise") or []:
            if k in SKILLS:
                expertise.add(k)
        for a in p.get("save_prof") or []:
            if a in ABILITIES:
                save_prof.add(a)
        darkvision = max(darkvision, _clampi(p.get("darkvision_ft", 0), 0, 999, 0))
        speed += _clampi(p.get("speed_bonus_ft", 0), -99, 999, 0)
        carry += _clampi(p.get("carry_bonus", 0), 0, 9999, 0)
    for a, d in bonus.items():
        stats[a] = max(1, min(30, stats[a] + d))
    return {"stats": stats, "skill_prof": skill_prof, "expertise": expertise,
            "save_prof": save_prof, "darkvision_ft": darkvision,
            "speed_bonus_ft": speed, "carry_bonus": carry, "active": active}


# ---------- skills ----------

def _stat_mod(char, ability):
    ability = str(ability or "").lower()
    score = effective_gear(char)["stats"].get(ability, 10)     # base + worn/wielded items
    return (score - 10) // 2


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
    if isinstance(char, dict) and char.get("equipment"):     # D98: worn/wielded speed bonus
        walk = max(5, walk + effective_gear(char)["speed_bonus_ft"])
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
    """Return (total_bonus, is_proficient). D98: a skill the character is merely
    EQUIPMENT-proficient (or expert) in counts once — the grant never stacks with
    itself and never downgrades a higher existing level."""
    if key not in SKILLS:
        return 0, False
    eg = effective_gear(char)
    lvl = skills.get(key, 0) if isinstance(skills, dict) else 0
    if key in eg["expertise"]:
        lvl = max(lvl, 2)
    elif key in eg["skill_prof"]:
        lvl = max(lvl, 1)
    score = eg["stats"].get(SKILLS[key][1], 10)
    return (score - 10) // 2 + prof_bonus(char) * lvl, lvl > 0


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
    eg = effective_gear(char)
    prof = clean_saves(saves).get(ability) or ability in eg["save_prof"]
    return (eg["stats"].get(ability, 10) - 10) // 2 + (prof_bonus(char) if prof else 0)


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
            "targeting": str(s.get("targeting", "single")).strip().lower()[:12] or "single",
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


# ---------- D99: currency (integer copper) + encumbrance (pounds) ----------
# Single source of truth. EVERY balance is stored as an integer number of COPPER
# PIECES (cp) — never a float, never a per-coin dict that could go negative per
# denomination. A purse is ONE non-negative integer; the per-coin split below is
# DISPLAY ONLY (greedy from the richest denomination down, so electrum change at
# 50 cp always divides exactly). Rates and coin weight are DATA, not rules: edit
# this table (later a content row) to reshape the economy, not the engine.
COIN_BASE = "cp"
COIN_WEIGHT = 0.02                      # pounds per coin (5e: 50 coins = 1 lb)
CURRENCIES = (
    {"id": "cp", "name": "Copper",   "value_cp": 1,    "coin_weight": COIN_WEIGHT},
    {"id": "sp", "name": "Silver",   "value_cp": 10,   "coin_weight": COIN_WEIGHT},
    {"id": "ep", "name": "Electrum", "value_cp": 50,   "coin_weight": COIN_WEIGHT},
    {"id": "gp", "name": "Gold",     "value_cp": 100,  "coin_weight": COIN_WEIGHT},
    {"id": "pp", "name": "Platinum", "value_cp": 1000, "coin_weight": COIN_WEIGHT},
)
_BY_ID = {c["id"]: c for c in CURRENCIES}
_DENOMS = sorted(_BY_ID.values(), key=lambda c: -c["value_cp"])   # richest first
WALLET_MAX = 10_000_000                 # cp ceiling, far above any plausible hoard

CARRY_PER_STR = 15                      # lb a MEDIUM character carries per STR point
SIZE_CARRY = {"tiny": 0.5, "small": 0.5, "medium": 1.0,
              "large": 2.0, "huge": 4.0, "gargantuan": 8.0}


def clean_wallet(v):
    try:
        cp = int(v)
    except (TypeError, ValueError):
        cp = 0
    return max(0, min(WALLET_MAX, cp))


def clean_size(v):
    s = str(v or "medium").strip().lower()
    return s if s in SIZE_CARRY else "medium"


def currency_table():
    """Read-only view of the currency definitions (UI + docs render this)."""
    return [dict(c) for c in CURRENCIES]


def to_cp(amount, coin_id):
    """One denomination -> integer copper. Rejects unknown coins, booleans,
    non-integers and out-of-range amounts. The engine NEVER trusts a copper
    total sent by a client — it always derives it from an integer + coin id."""
    c = _BY_ID.get(str(coin_id or "").strip().lower())
    if c is None:
        raise ValueError("Unknown currency")
    if isinstance(amount, bool):
        raise ValueError("Bad amount")
    if isinstance(amount, float) and amount != int(amount):
        raise ValueError("Bad amount")             # fractional coin is not allowed
    try:
        n = int(amount)
    except (TypeError, ValueError):
        raise ValueError("Bad amount")
    if n < 0 or n > 1_000_000:
        raise ValueError("Bad amount")
    return n * c["value_cp"]


def cp_breakdown(cp):
    """Greedy display split, richest first. Deterministic; the sum of
    value_cp*count always equals the input."""
    rem = clean_wallet(cp)
    out = []
    for c in _DENOMS:
        n, rem = divmod(rem, c["value_cp"])
        out.append({"id": c["id"], "name": c["name"], "count": n,
                    "coin_weight": c["coin_weight"]})
    return out


def cp_label(cp):
    """Human string for the chronicle, e.g. '1 gp 2 sp 3 cp'."""
    parts = [f"{b['count']} {b['id']}" for b in cp_breakdown(cp) if b["count"]]
    return " ".join(parts) if parts else "0 cp"


def coins_weight(cp):
    """Pounds the coins in a purse weigh — from the SAME greedy split the sheet
    shows, so the displayed pile and its weight can never disagree."""
    return round(sum(b["count"] * b["coin_weight"] for b in cp_breakdown(cp)), 2)


def carry_capacity(char):
    """Max pounds: effective STR * per-STR * size modifier, plus any carry_bonus
    from WORN gear. effective_gear is the ONLY source (no second gear read)."""
    eg = effective_gear(char) if isinstance(char, dict) else {"stats": {}, "carry_bonus": 0}
    str_score = max(1, int(eg.get("stats", {}).get("str", 10) or 10))
    mult = SIZE_CARRY.get(clean_size(char.get("size") if isinstance(char, dict) else None), 1.0)
    return int(round(str_score * CARRY_PER_STR * mult + eg.get("carry_bonus", 0)))


def inventory_weight(char, wallet_cp=0):
    """Pounds carried: for every DISTINCT stack qty*weight (equipped items live
    INSIDE items[], so they count exactly once — no double counting), plus coins."""
    carried = 0.0
    items = char.get("items") if isinstance(char, dict) else None
    if not isinstance(items, list):
        items = []
    for it in items:
        if not isinstance(it, dict):
            continue
        try:
            w = float(it.get("weight", 0) or 0)
            q = int(it.get("qty", 1) or 1)
        except (TypeError, ValueError):
            continue
        carried += max(0.0, w) * max(1, q)
    return round(carried + coins_weight(wallet_cp), 2)


def encumbrance(char, wallet_cp=None):
    """Derived carrying report the sheet renders. carried/capacity in pounds.
    overloaded is a WARN FLAG ONLY — D99 adds NO movement penalty until that
    rule is fully specified and tested."""
    wc = wallet_cp if wallet_cp is not None else (char.get("wallet", 0) if isinstance(char, dict) else 0)
    carried = inventory_weight(char, clean_wallet(wc))
    capacity = carry_capacity(char)
    pct = round(100.0 * carried / capacity, 1) if capacity > 0 else (0.0 if carried <= 0 else 999.0)
    return {"carried": carried, "capacity": capacity, "percent": pct,
            "overloaded": carried > capacity, "coin_weight": COIN_WEIGHT}
