"""Data-driven content packages: CSV schema, validation, import and export.

This module is the ONE content engine. It parses and validates hand-editable
CSV rule packages and stores them as data; it NEVER evaluates code from a file
(Verbot: no Python/JS/SQL execution out of CSV). Game MECHANICS stay in the
existing engines (gear, abilities, progression, health, dice); content only
describes WHAT exists and its PARAMETERS. Anything a CSV row asks for that no
engine implements is explicitly marked ``needs_manual`` and shown as a
description — never silently interpreted.

STORAGE: a generic ``content`` table keyed (kind, room_id, id) holds the full
validated row as JSON — the round-trip source of truth for export. Content is
room-scoped; ``room_id`` 0 is a reserved GLOBAL library read by every room. The
mechanically-supported subset additionally projects into the live systems so it
is usable at the table:
  * ``item``   -> an ``item_defs`` row (DM grant library, weapon_profiles read it)
  * ``spell``  -> a registered ability (``abilities.register``) + the sheet pool
Everything else (species/classes/subclasses/backgrounds/feats/creatures) is read
back from ``content`` by the character-build engine (Phase B) and the sheet.

Licensing (ATTRIBUTION.md): the shipped technical pack uses ORIGINAL names and
descriptions; the human authors supply the real rule packages later.
"""
import csv
import io
import os
import re
import zipfile

from . import db

# --------------------------------------------------------------------------
# Vocabulary / regexes
# --------------------------------------------------------------------------
ABILITIES = ("str", "dex", "con", "int", "wis", "cha")
SKILLS = ("acrobatics", "animal_handling", "arcana", "athletics", "deception",
          "history", "insight", "intimidation", "investigation", "medicine",
          "nature", "perception", "performance", "persuasion", "religion",
          "sleight_of_hand", "stealth", "survival")
SIZES = ("tiny", "small", "medium", "large", "huge", "gargantuan")
DAMAGE_TYPES = ("acid", "bludgeoning", "cold", "fire", "force", "lightning",
                "necrotic", "piercing", "poison", "psychic", "radiant",
                "slashing", "thunder")
ITEM_KINDS = ("armor", "shield", "potion", "scroll", "wand", "staff", "ring",
              "tool", "wondrous", "spellbook", "weapon", "other")
TARGETINGS = ("self", "single", "point", "area")
SHAPES = ("point", "line", "cone", "circle", "square")
RESOLUTIONS = ("auto", "save", "attack")
ON_SAVE = ("none", "half", "negate")

_BASE_DICE = re.compile(r"^\d{1,3}d\d{1,3}([+-]\d{1,3})?$", re.I)   # 1d8 / 2d6+3
_BONUS_DICE = re.compile(r"^[+-]?\d{1,3}d\d{1,3}$", re.I)           # +1d8 / 1d6
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
_ASSET_RE = re.compile(r"^/assets/[0-9a-f]{16}$")


def valid_dice(expr):
    return bool(_BASE_DICE.match(str(expr or "").strip().lower()))


def valid_dice_bonus(expr):
    return bool(_BONUS_DICE.match(str(expr or "").strip().lower()))


# --------------------------------------------------------------------------
# Schemas — one column list per kind. spec = (key, required, vtype, default)
# vtype: str text int fint bool list dice diceb ab choices:<a|b> int:a-b
#        ability_bonuses attribute_set asset
# --------------------------------------------------------------------------
SCHEMAS = {
    "species": [
        ("id", True, "id", ""), ("name", True, "str", ""),
        ("size", False, "choices:" + "|".join(SIZES), "medium"),
        ("speed_ft", False, "int:0-999", 30), ("fly_ft", False, "int:0-999", 0),
        ("swim_ft", False, "int:0-999", 0), ("climb_ft", False, "int:0-999", 0),
        ("darkvision_ft", False, "int:0-999", 0),
        ("ability_bonuses", False, "ability_bonuses", ""),
        ("languages", False, "str", ""), ("traits", False, "text", ""),
        ("image", False, "asset", ""), ("manual", False, "text", ""),
    ],
    "class": [  # one row per level 1..20
        ("id", True, "id", ""), ("level", True, "int:1-20", ""),
        ("name", False, "str", ""),
        ("hit_die", False, "int:4-12", 8), ("hp_base", False, "int:1-99", 0),
        ("hp_per_level", False, "int:1-12", 0),
        ("saves", False, "ab", ""), ("skill_options", False, "skills", ""),
        ("skill_count", False, "int:0-8", 0),
        ("weapon_prof", False, "text", ""), ("armor_prof", False, "text", ""),
        ("features", False, "text", ""), ("expertise", False, "bool", False),
        ("subclass_family", False, "str", ""),
        ("subclass_choice", False, "bool", False),
        ("ability_boost_or_feat", False, "bool", False),
        ("feat_choice", False, "bool", False), ("class_resource", False, "str", ""),
        ("spellcasting_ability", False, "ab", ""),
        ("cantrips_known", False, "int:0-20", 0), ("spells_known", False, "int:0-99", 0),
        ("prepared", False, "bool", False),
        ("slot_progression", False, "str", ""), ("upcast_scaling", False, "bool", False),
        ("spell_first_level", False, "int:0-20", 0), ("spell_replace", False, "bool", False),
        ("class_resource_reset", False, "choices:|short|long", ""),
        ("manual", False, "text", ""),
    ],
    "subclass": [
        ("id", True, "id", ""), ("class_id", True, "id", ""),
        ("level", True, "int:1-20", ""), ("name", False, "str", ""),
        ("features", False, "text", ""), ("spells_grant", False, "str", ""),
        ("needs_choice", False, "bool", False), ("manual", False, "text", ""),
    ],
    "item": [
        ("id", True, "id", ""), ("name", True, "str", ""),
        ("category", False, "str", "other"), ("kind", False, "choices:" + "|".join(ITEM_KINDS), "other"),
        ("weight", False, "fint:0-9999", 0.0), ("qty", False, "int:1-9999", 1),
        ("value_gp", False, "fint:0-999999", 0.0),
        ("damage_dice", False, "dice", ""), ("damage_dice_two_handed", False, "dice", ""),
        ("versatile", False, "bool", False), ("two_handed", False, "bool", False),
        ("hands", False, "int:0-2", 0), ("finesse", False, "bool", False), ("properties", False, "text", ""),
        ("range_normal_ft", False, "int:0-600", 0), ("range_long_ft", False, "int:0-600", 0),
        ("reach_ft", False, "int:0-60", 0),
        ("carry_bonus", False, "int:0-9999", 0),
        ("attack_bonus", False, "int:-10-10", 0), ("damage_bonus", False, "int:-10-10", 0),
        ("damage_type", False, "choices:" + "|".join(DAMAGE_TYPES), ""),
        ("ac_base", False, "int:0-40", 0), ("ac_bonus", False, "int:-5-10", 0),
        ("ac_max_dex", False, "int:-1-99", -1),
        ("attribute_set", False, "attribute_set", ""),
        ("attribute_bonus", False, "ability_bonuses", ""),
        ("skill_prof", False, "skills", ""), ("save_prof", False, "ab", ""),
        ("expertise", False, "skills", ""),
        ("darkvision_ft", False, "int:0-999", 0), ("speed_bonus_ft", False, "int:-99-999", 0),
        ("extra_damage_dice", False, "diceb", ""), ("extra_damage_type", False, "choices:" + "|".join(DAMAGE_TYPES), ""),
        ("heal_dice", False, "dice", ""), ("hit_dice_bonus", False, "int:-10-10", 0),
        ("charges", False, "int:-1-999", -1), ("recharge", False, "choices:|long", ""),
        ("attune", False, "bool", False), ("magic", False, "bool", False),
        ("duration", False, "str", ""), ("trigger", False, "str", ""),
        ("light", False, "bool", False),
        ("image", False, "asset", ""), ("desc", False, "text", ""), ("manual", False, "text", ""),
    ],
    "spell": [
        ("id", True, "id", ""), ("name", True, "str", ""),
        ("level", False, "int:0-9", 0), ("school", False, "str", ""),
        ("casting_ability", False, "ab1", "int"),
        ("targeting", False, "choices:" + "|".join(TARGETINGS), "single"),
        ("shape", False, "choices:" + "|".join(SHAPES), ""), ("size_ft", False, "int:0-600", 0),
        ("range_ft", False, "int:0-600", 0), ("casting_time", False, "str", ""),
        ("duration", False, "str", ""), ("concentration", False, "bool", False),
        ("resolution", False, "choices:" + "|".join(RESOLUTIONS), "auto"),
        ("save", False, "ab1", ""), ("on_save", False, "choices:" + "|".join(ON_SAVE), "none"),
        ("damage_dice", False, "dice", ""), ("damage_type", False, "choices:" + "|".join(DAMAGE_TYPES), ""),
        ("heal_dice", False, "dice", ""),
        ("upcast_step", False, "diceb", ""), ("upcast_scaling", False, "bool", False),
        ("scale_tiers", False, "str", ""),
        ("class_list", False, "str", ""), ("scaling_note", False, "text", ""),
        ("manual", False, "text", ""),
    ],
    "background": [
        ("id", True, "id", ""), ("name", True, "str", ""),
        ("skill_prof", False, "skills", ""), ("tool_prof", False, "text", ""),
        ("languages", False, "str", ""), ("starting_items", False, "str", ""),
        ("feature", False, "text", ""), ("manual", False, "text", ""),
    ],
    "feat": [
        ("id", True, "id", ""), ("name", True, "str", ""),
        ("requires", False, "str", ""), ("ability_boost", False, "ability_bonuses", ""),
        ("skill_prof", False, "skills", ""), ("spells_grant", False, "str", ""),
        ("effect", False, "text", ""), ("manual", False, "text", ""),
    ],
    "creature": [
        ("id", True, "id", ""), ("name", True, "str", ""),
        ("size", False, "choices:" + "|".join(SIZES), "medium"), ("type", False, "str", ""),
        ("ac", False, "int:0-40", 10), ("hp", False, "int:0-9999", 1),
        ("speed_ft", False, "int:0-999", 30), ("fly_ft", False, "int:0-999", 0),
        ("str", False, "int:1-30", 10), ("dex", False, "int:1-30", 10),
        ("con", False, "int:1-30", 10), ("int", False, "int:1-30", 10),
        ("wis", False, "int:1-30", 10), ("cha", False, "int:1-30", 10),
        ("cr", False, "str", ""), ("skills", False, "str", ""),
        ("saves", False, "ab", ""), ("attacks", False, "text", ""),
        ("spells", False, "str", ""), ("abilities", False, "str", ""),
        ("darkvision_ft", False, "int:0-999", 0), ("tags", False, "str", ""),
        ("companion", False, "bool", False), ("image", False, "asset", ""),
        ("manual", False, "text", ""),
    ],
}
# filename (basename) -> kind
FILE_KIND = {
    "species.csv": "species", "classes.csv": "class", "subclasses.csv": "subclass",
    "items.csv": "item", "spells.csv": "spell", "backgrounds.csv": "background",
    "feats.csv": "feat", "creatures.csv": "creature",
}
KIND_FILE = {v: k for k, v in FILE_KIND.items()}
ALL_KINDS = list(SCHEMAS)


# --------------------------------------------------------------------------
# Column coercion
# --------------------------------------------------------------------------
def _parse_list(v):
    out, seen = [], set()
    for part in re.split(r"[,;]+", str(v or "")):
        p = part.strip().lower()
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _parse_ability_bonuses(v):
    """'str+2,con+1' -> (ordered-dict-like str 'con+1,str+2', error)."""
    s = str(v or "").strip()
    if not s:
        return "", None
    got = {}
    for part in re.split(r"[,;]+", s):
        p = part.strip().lower()
        if not p:
            continue
        m = re.match(r"^([a-z]+)([+-]\d{1,2})$", p)
        if not m:
            return None, f"expected 'ability+mod' (e.g. str+2), got '{part.strip()}'"
        ab, mod = m.group(1), int(m.group(2))
        if ab not in ABILITIES:
            return None, f"unknown ability '{ab}'"
        if not -5 <= mod <= 5:
            return None, f"modifier for '{ab}' out of range -5..5"
        got[ab] = got.get(ab, 0) + mod
    return ",".join(f"{k}{v:+d}" for k, v in sorted(got.items())), None


def _parse_attribute_set(v):
    """'int=15,wis=13' -> normalised string or error."""
    s = str(v or "").strip()
    if not s:
        return "", None
    out = {}
    for part in re.split(r"[,;]+", s):
        p = part.strip().lower()
        if not p:
            continue
        m = re.match(r"^([a-z]+)=(\d{1,2})$", p)
        if not m:
            return None, f"expected 'ability=score' (e.g. int=15), got '{part.strip()}'"
        ab, sc = m.group(1), int(m.group(2))
        if ab not in ABILITIES:
            return None, f"unknown ability '{ab}'"
        if not 1 <= sc <= 30:
            return None, f"score for '{ab}' out of range 1..30"
        out[ab] = sc
    return ",".join(f"{k}={v}" for k, v in sorted(out.items())), None


_RANGE_RE = re.compile(r"^(-?\d+(?:\.\d+)?)-(-?\d+(?:\.\d+)?)$")


def _parse_range(vtype_rest):
    m = _RANGE_RE.match(vtype_rest)
    if not m:
        raise ValueError(f"bad range spec '{vtype_rest}'")
    return m.group(1), m.group(2)


def coerce(kind, key, vtype, raw):
    """Return (value, error|None). raw is the CSV string."""
    s = (raw or "").strip()
    if vtype == "id":
        if not s:
            return "", "required" if key == "id" else ""
        if not _ID_RE.match(s.lower()):
            return None, "id must match [a-z0-9][a-z0-9_-] (max 32)"
        return s.lower(), None
    if vtype == "str":
        return s[:48], None
    if vtype == "text":
        return s[:2000], None
    if vtype == "asset":
        if not s:
            return "", None
        return (s, None) if _ASSET_RE.match(s) else (None, "image must be '/assets/<16 hex>'")
    if vtype.startswith("choices:"):
        allowed = vtype.split(":", 1)[1].split("|")
        if not s:
            return "", None
        low = s.lower()
        if low not in allowed:
            return None, f"must be one of {allowed}"
        return low, None
    if vtype == "bool":
        return s.lower() in ("1", "true", "yes", "y", "x"), None
    if vtype == "int":
        if not s:
            return "", None
        try:
            return int(float(s)), None
        except ValueError:
            return None, "must be a whole number"
    if vtype.startswith("int:"):
        lo, hi = (int(x) for x in _parse_range(vtype[4:]))
        if not s:
            return "", None
        try:
            n = int(float(s))
        except ValueError:
            return None, "must be a whole number"
        if not lo <= n <= hi:
            return None, f"out of range {lo}..{hi}"
        return n, None
    if vtype.startswith("fint:"):
        lo, hi = (float(x) for x in _parse_range(vtype[5:]))
        if not s:
            return "", None
        try:
            n = round(float(s), 1)
        except ValueError:
            return None, "must be a number"
        if not lo <= n <= hi:
            return None, f"out of range {lo}..{hi}"
        return n, None
    if vtype == "list":
        return _parse_list(s), None
    if vtype == "ab":
        items = _parse_list(s)
        bad = [x for x in items if x not in ABILITIES]
        if bad:
            return None, f"unknown ability in {bad} (str/dex/con/int/wis/cha)"
        return items, None
    if vtype == "ab1":
        if not s:
            return "", None
        low = s.lower()
        if low not in ABILITIES:
            return None, "must be one ability (str/dex/con/int/wis/cha)"
        return low, None
    if vtype == "skills":
        items = _parse_list(s)
        bad = [x for x in items if x not in SKILLS]
        if bad:
            return None, f"unknown skill in {bad}"
        return items, None
    if vtype == "dice":
        if not s:
            return "", None
        return (s.lower(), None) if valid_dice(s) else (None, "invalid dice (e.g. 1d8, 2d6+3)")
    if vtype == "diceb":
        if not s:
            return "", None
        return (s.lower(), None) if valid_dice_bonus(s) else (None, "invalid bonus dice (e.g. +1d8)")
    if vtype == "ability_bonuses":
        v, e = _parse_ability_bonuses(s)
        return (None, e) if e else (v, None)
    if vtype == "attribute_set":
        v, e = _parse_attribute_set(s)
        return (None, e) if e else (v, None)
    return None, f"unknown vtype {vtype}"      # internal bug guard


# --------------------------------------------------------------------------
# CSV parsing + validation
# --------------------------------------------------------------------------
def parse(text):
    """Parse CSV text -> (rows, header|None). BOM-tolerant, UTF-8."""
    text = text.lstrip("\ufeff")
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        return [], None
    rows = [dict(r) for r in reader]
    return rows, [f.strip() for f in reader.fieldnames]


def validate(kind, rows, header=None, file_label=""):
    """Validate parsed rows against a kind schema.

    Returns (clean, errors, warnings). clean = list[dict] with EVERY schema
    column normalised (empty -> its default) so export is byte-stable.
    errors = list[{file, line, column, msg}]. Unknown CSV columns are warnings.
    """
    schema = SCHEMAS[kind]
    cols = {k: (req, vt, dflt) for (k, req, vt, dflt) in schema}
    seen_ids = {}
    clean, errors, warnings = [], [], []

    if header is not None:
        for h in header:
            if h and h not in cols:
                warnings.append({"file": file_label, "column": h,
                                 "msg": "unknown column ignored"})

    for i, row in enumerate(rows):
        line = i + 2                                   # header is line 1
        out, row_err = {}, False
        for key, (req, vt, dflt) in cols.items():
            raw = row.get(key, "")
            if isinstance(raw, list):                  # duplicate header cell
                raw = raw[0] if raw else ""
            raw = _csv_unescape(raw)                   # undo our own export escaping
            val, err = coerce(kind, key, vt, raw)
            if err:
                errors.append({"file": file_label, "line": line, "column": key, "msg": err})
                row_err = True
                val = [] if vt in ("ab", "skills", "list") else ""
            out[key] = val
            if req and (val == "" or val is None or val == []):
                errors.append({"file": file_label, "line": line, "column": key,
                               "msg": "required column is empty"})
                row_err = True
        # uniqueness within the file. For classes/subclasses the id repeats
        # across the level rows, so the key is (id, level) there, plain id elsewhere.
        cid = out.get("id", "")
        if cid:
            leveled = kind in ("class", "subclass")
            ukey = (cid, out.get("level")) if leveled else cid
            if ukey in seen_ids:
                first = seen_ids[ukey]
                errors.append({"file": file_label, "line": line, "column": "id",
                               "msg": f"duplicate {kind} id '{cid}'"
                                      + (f" at level {out.get('level')}" if leveled else "")
                                      + f" (first seen line {first})"})
                row_err = True
            else:
                seen_ids[ukey] = line
        clean.append(out)
    return clean, errors, warnings


# --------------------------------------------------------------------------
# Persistence
# --------------------------------------------------------------------------
def store_key(kind, row):
    """Content-table row key. Class/subclass ids repeat across levels, so those
    kinds are keyed by '<id>#L<level>'; every other kind is keyed by its id."""
    cid = row.get("id", "")
    if kind in ("class", "subclass"):
        return f"{cid}#L{row.get('level')}"
    return cid


def existing_ids(kind, room_id):
    return {r["id"] for r in db.q(
        "SELECT id FROM content WHERE kind=? AND room_id=?", (kind, room_id))}


def load(kind, room_id, include_global=True):
    """Rows for a room, optionally merged with the GLOBAL (room_id=0) library.
    A room row overrides a global row of the same stored key (per-level for
    classes/subclasses)."""
    scope = [room_id, 0] if include_global and room_id != 0 else [room_id]
    placeholders = ",".join("?" for _ in scope)
    rows = db.q(f"SELECT * FROM content WHERE kind=? AND room_id IN ({placeholders}) "
                f"ORDER BY id", [kind] + scope)
    merged = {}
    for r in rows:
        data = db.j(r["data"], {}) or {}
        data["_room_id"] = r["room_id"]
        data.setdefault("id", r["id"].split("#L")[0])
        data.setdefault("name", r["name"])
        merged[r["id"]] = data                          # room rows win (id-asc: 0 first)
    return list(merged.values())


def class_levels(class_id, room_id):
    """All stored level rows for one class, sorted by level (build engine)."""
    rows = [r for r in load("class", room_id) if r.get("id") == class_id]
    return sorted(rows, key=lambda r: int(r.get("level") or 0))


def store(kind, room_id, row, source="csv"):
    cols = [c[0] for c in SCHEMAS[kind]]
    data = {c: row.get(c) for c in cols}
    db.x("INSERT INTO content(kind,room_id,id,name,data,source,version,updated_at) "
         "VALUES(?,?,?,?,?,?,?,datetime('now')) "
         "ON CONFLICT(kind,room_id,id) DO UPDATE SET name=excluded.name,"
         "data=excluded.data,source=excluded.source,"
         "version=content.version+1,updated_at=datetime('now')",
         (kind, room_id, store_key(kind, row), row.get("name", ""),
          db.json_dumps(data), source, 1))


def _project_item(room_id, row):
    """Best-effort projection of an item row into item_defs so a DM can grant
    it at the table. The full definition stays in `content` (export SSOT)."""
    from . import inventory as INV
    props = {}
    for pk in ("attack_bonus", "damage_bonus", "range_ft", "reach_ft", "two_handed",
               "ac_bonus", "ac_base", "ac_max_dex", "extra_damage_dice", "extra_damage_type",
               "darkvision_ft", "speed_bonus_ft", "heal_dice", "hit_dice_bonus",
               "skill_prof", "save_prof", "expertise", "attribute_set", "attribute_bonus",
               "attune", "versatile", "finesse", "damage_dice_two_handed", "trigger",
               "duration", "light", "hands", "charges", "recharge", "carry_bonus"):
        v = row.get(pk)
        if v in ("", None, 0, False, []):
            continue
        props[pk] = v
    if row.get("damage_dice"):
        props["damage_dice"] = row["damage_dice"]
    if row.get("damage_type"):
        props["damage_type"] = row["damage_type"]
    # weapon_profiles() reads a single 'range_ft'; keep the long range as an
    # extra prop for display (long-range rules are a Phase D concern).
    if row.get("range_normal_ft"):
        props["range_ft"] = int(row["range_normal_ft"])
    if row.get("range_long_ft"):
        props["range_long_ft"] = int(row["range_long_ft"])
    if row.get("reach_ft"):
        props["reach_ft"] = int(row["reach_ft"])
    # skill/save/expertise grants are canonicalised by gear.clean_props (via
    # inventory.clean_def) — no lossy comma-string round-trip here (D98).
    did = row["id"][:24]
    kind = row.get("kind") or "other"
    defn = INV.clean_def({"id": did, "name": row["name"], "desc": row.get("desc", ""),
                          "kind": kind, "weight": row.get("weight", 0),
                          "stackable": False, "props": props})
    if defn is None:
        return "invalid"
    defn_id = defn.pop("id") or did
    # D100: item_defs.id is a GLOBAL primary key — per-room duplicates would need a
    # destructive table rebuild. If another room already owns this shared id, refuse
    # rather than silently rewrite its DM-library row (its authoritative content row
    # is already stored room-scoped, so nothing is LOST — only the shared library
    # projection is skipped and reported). The caller surfaces it as a warning.
    owner = db.q1("SELECT room_id FROM item_defs WHERE id=?", (defn_id,))
    if owner is not None and owner["room_id"] != room_id:
        raise ValueError("shared item id owned by another room")
    db.x("INSERT INTO item_defs(id,room_id,name,desc,kind,weight,stackable,props,created_by) "
         "VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,"
         "desc=excluded.desc,kind=excluded.kind,weight=excluded.weight,"
         "stackable=excluded.stackable,props=excluded.props",
         (defn_id, room_id, defn["name"], defn["desc"], defn["kind"], defn["weight"],
          defn["stackable"], db.json_dumps(defn["props"]), None))
    return "ok"


def map_to_ability(row):
    """Map a spell row to an abilities.clean_definition-compatible dict."""
    from . import abilities
    lvl = int(row.get("level") or 0)
    targeting = row.get("targeting") or "single"
    resolution = row.get("resolution") or "auto"
    defn = {
        "id": row["id"], "name": row["name"], "ability": row.get("casting_ability") or "int",
        "range_ft": int(row.get("range_ft") or 0), "targeting": targeting,
        "resolution": resolution, "save": row.get("save") or "",
        "on_save": row.get("on_save") or "none", "concentration": bool(row.get("concentration")),
        "los_required": True,
    }
    if targeting == "area":
        defn["shape"] = row.get("shape") or "circle"
        defn["size_ft"] = int(row.get("size_ft") or 5)
    if row.get("damage_dice"):
        defn["damage"] = row["damage_dice"]
        if row.get("damage_type"):
            defn["damage_type"] = row["damage_type"]
    if row.get("heal_dice"):
        defn["heal"] = row["heal_dice"]
    if lvl > 0:
        defn["cost"] = {"type": "spell_slot", "level": lvl}
    # scaling metadata (D97): applied generically in abilities.execute — the engine
    # raises the BASE dice count from a slot-level step (upcast) or a character-level
    # tier table (cantrips). Data-driven; nothing here names a specific spell.
    defn["base_level"] = lvl
    if row.get("upcast_step"):
        defn["upcast_step"] = row["upcast_step"]
        defn["upcast_scaling"] = bool(row.get("upcast_scaling"))
    if row.get("scale_tiers"):
        defn["scale_tiers"] = row["scale_tiers"]
    return abilities.clean_definition(defn)


# --------------------------------------------------------------------------
# spell-progression readers (pure) — the CONSUMER of the class-row spell axis
# (D58: a TABLE on the class row, never derived from total character level)
# --------------------------------------------------------------------------
def slot_table(row):
    """Parse a class row's ``slot_progression`` ("1:4;2:3") into {level: max}.
    Malformed parts are ignored; returns {} for a non-casting/blank row."""
    out = {}
    for part in re.split(r"[,;]+", str((row or {}).get("slot_progression", "") or "")):
        if ":" not in part:
            continue
        lv, _, mx = part.partition(":")
        try:
            lv, mx = int(lv.strip()), int(mx.strip())
        except (TypeError, ValueError):
            continue
        if 1 <= lv <= 9 and mx >= 0:
            out[lv] = mx
    return out


def spell_pool(class_id, room_id):
    """Spell rows available to a class: those whose ``class_list`` names it."""
    cid = str(class_id or "").strip().lower()
    out = []
    for r in load("spell", room_id):
        cls = {x.strip().lower() for x in re.split(r"[,;]+", str(r.get("class_list", "") or ""))}
        if cid and cid in cls:
            out.append(r)
    return out



def _project_spell(row):
    from . import abilities
    defn = map_to_ability(row)
    if defn is None:
        return "manual"
    abilities.register(defn)
    return "ok"


def apply_rows(kind, room_id, clean_rows, mode="apply"):
    """Write validated rows. mode 'apply' reports an existing DIFFERENT row as a
    conflict (not overwritten); mode 'replace' overwrites. Returns {inserted,
    replaced, unchanged, conflicts:[ids]}. Side projects (item/spell) run for
    every written row."""
    stats = {"inserted": 0, "replaced": 0, "unchanged": 0, "conflicts": []}
    for row in clean_rows:
        key = store_key(kind, row)
        cur = db.q1("SELECT data FROM content WHERE kind=? AND room_id=? AND id=?",
                    (kind, room_id, key))
        new_data = {c[0]: row.get(c[0]) for c in SCHEMAS[kind]}
        if cur is not None:
            if (db.j(cur["data"], {}) or {}) == new_data:
                stats["unchanged"] += 1
                continue                                # identical: idempotent, skip
            if mode != "replace":
                stats["conflicts"].append(row["id"] if kind not in ("class", "subclass")
                                          else f"{row['id']}@{row.get('level')}")
                continue
            stats["replaced"] += 1
        else:
            stats["inserted"] += 1
        store(kind, room_id, row)
        if kind == "item":
            try:
                _project_item(room_id, row)
            except Exception as ex:                      # projection must never lose content
                stats.setdefault("warnings", []).append(
                    f"item '{row['id']}' stored but not projected to the DM library"
                    + (f" ({ex})" if str(ex) else ""))
        elif kind == "spell":
            try:
                _project_spell(row)
            except Exception:
                stats.setdefault("warnings", []).append(
                    f"spell '{row['id']}' stored but not registered (manual)")
    return stats


# --------------------------------------------------------------------------
# Package import (single file or ZIP) with preview
# --------------------------------------------------------------------------
MAX_FILE = 400_000
MAX_ROWS = 5000
MAX_ZIP_FILES = 40
MAX_ZIP_UNCOMPRESSED = 4_000_000


def read_package(name, body, fmt):
    """Split an upload into {basename -> text}. Guarded for a single CSV or a
    ZIP of CSVs. Raises ValueError on an unsafe/oversized package."""
    files = {}
    if fmt == "zip":
        if len(body) > MAX_FILE:
            raise ValueError("ZIP too large")
        import io as _io
        with zipfile.ZipFile(_io.BytesIO(body)) as z:
            infos = z.infolist()
            if len(infos) > MAX_ZIP_FILES:
                raise ValueError("ZIP has too many files")
            if sum(i.file_size for i in infos) > MAX_ZIP_UNCOMPRESSED:
                raise ValueError("ZIP uncompressed size too large (zip-bomb guard)")
            for info in infos:
                base = os.path.basename(info.filename.replace("\\", "/"))
                if info.is_dir() or not base.lower().endswith(".csv"):
                    continue
                raw = z.read(info, )
                if len(raw) > MAX_FILE:
                    raise ValueError(f"{base} too large")
                files[base] = raw.decode("utf-8-sig", errors="replace")
        return files
    base = os.path.basename((name or "upload").replace("\\", "/"))
    if len(body) > MAX_FILE:
        raise ValueError("File too large")
    files[base] = body.decode("utf-8-sig", errors="replace")
    return files


def import_package(files, room_id, mode="apply", apply=True):
    """Validate (always) and optionally apply a package. Returns a report:
    {ok, files:[{file, kind, rows, valid, errors:[...]}], applied:{...}}.
    Nothing is written unless apply=True and the file has zero errors."""
    report = {"ok": True, "files": [], "applied": {}}
    if isinstance(files, (bytes, str)):
        files = {"upload": files}
    for base, text in files.items():
        kind = FILE_KIND.get(base.lower())
        if kind is None:
            report["ok"] = False
            report["files"].append({"file": base, "kind": None, "rows": 0,
                                    "valid": False, "ignored": True,
                                    "errors": [{"file": base, "line": 0, "column": "",
                                                "msg": "unknown content file (skipped)"}]})
            continue
        rows, header = parse(text)
        if not rows:
            report["ok"] = False
            report["files"].append({"file": base, "kind": kind, "rows": 0, "valid": False,
                                    "errors": [{"file": base, "line": 0, "column": "",
                                                "msg": "no rows / missing header"}]})
            continue
        if len(rows) > MAX_ROWS:
            report["ok"] = False
            report["files"].append({"file": base, "kind": kind, "rows": len(rows),
                                    "valid": False,
                                    "errors": [{"file": base, "line": 0, "column": "",
                                                "msg": f"too many rows (max {MAX_ROWS})"}]})
            continue
        clean, errors, warnings = validate(kind, rows, header, base)
        valid = not errors
        existing = existing_ids(kind, room_id)
        entry = {"file": base, "kind": kind, "rows": len(rows), "valid": valid,
                 "errors": errors, "warnings": warnings,
                 "would_insert": sum(1 for r in clean
                                     if store_key(kind, r) not in existing)}
        report["files"].append(entry)
        if not valid:
            report["ok"] = False
            continue
        if apply:
            applied = apply_rows(kind, room_id, clean, mode="replace" if mode == "replace" else "apply")
            report["applied"][kind] = applied
    return report


# --------------------------------------------------------------------------
# Export (formula-injection-safe)
# --------------------------------------------------------------------------
def _csv_safe(v):
    """Neutralise spreadsheet formula injection (leading = + - @ TAB CR)."""
    s = "" if v is None else (",".join(map(str, v)) if isinstance(v, list) else str(v))
    if s and s[0] in "=+-@\t\r":
        return "'" + s
    return s


def _csv_unescape(s):
    """Reverse _csv_safe: strip the single leading apostrophe the exporter added
    in front of a value that starts with = + - @ TAB CR. A value we did not
    escape (an ordinary leading char) is returned unchanged, so round-tripping
    our own export never corrupts a legitimate '+1d8' cell."""
    s = s if isinstance(s, str) else str(s)
    if s[:1] == "'" and len(s) > 1 and s[1] in "=+-@\t\r":
        return s[1:]
    return s


def export_csv(kind, room_id, include_global=False):
    """Serialise stored rows for a kind (room-scoped) back to CSV text."""
    cols = [c[0] for c in SCHEMAS[kind]]
    rows = load(kind, room_id, include_global=include_global)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(cols)
    for r in sorted(rows, key=lambda x: (x.get("id", ""))):
        w.writerow([_csv_safe(r.get(c, "")) for c in cols])
    return buf.getvalue()


def export_package(room_id, kinds=None):
    """Build a ZIP (bytes) of every kind's CSV for a room."""
    kinds = kinds or ALL_KINDS
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for kind in kinds:
            fname = KIND_FILE.get(kind)
            if not fname:
                continue
            z.writestr(fname, export_csv(kind, room_id))
    return buf.getvalue()


def load_registered_abilities():
    """Startup hook: re-register every stored spell so casts survive a restart."""
    from . import abilities
    n = 0
    for r in db.q("SELECT data FROM content WHERE kind='spell'"):
        row = db.j(r["data"], {}) or {}
        try:
            defn = map_to_ability(row)
            if defn is not None:
                abilities.register(defn)
                n += 1
        except Exception:                              # a bad row must not break boot
            continue
    return n
