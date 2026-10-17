"""NPC / enemy stat blocks stored on a token (the ``tokens.npc`` JSON column).

A monster token has no ``characters`` row and no owner; everything the DM needs at
the table lives in this JSON blob: ability scores, HP/AC, level, speed, a castable
spell list and DM-tracked spell slots. The math reuses the same ``gear`` primitives
that player sheets use, by handing them a lightweight "pseudo-character" via
:func:`to_char` (``{"name", "stats", "level"}``) so spell attack / save DC / damage
stay a single source of truth.

``project_creature`` is the one-way CSV-content projection. It produces the same
NPC block shape accepted by the existing DM editor and token path — no second
monster engine.
"""
import re

from . import db, gear

ABILITIES = gear.ABILITIES
SIZES = ("Tiny", "Small", "Medium", "Large", "Huge", "Gargantuan")
DISPOSITIONS = ("", "friend", "neutral", "hostile")
_ATTACK_RE = re.compile(
    r"(?P<name>[^;\n]+?)\s+(?P<hit>[+-]\d+)\s+to hit\b[^\d]*?"
    r"(?P<dmg>\d{0,3}d\d+(?:[+-]\d+)?)",
    re.I)


def _content_list(value):
    if isinstance(value, (list, tuple)):
        return [str(x).strip().lower() for x in value if str(x).strip()]
    return [x.strip().lower() for x in re.split(r"[,;]+", str(value or "")) if x.strip()]


def _project_attack(text):
    match = _ATTACK_RE.search(str(text or "").strip())
    if not match:
        return None
    try:
        hit = int(match.group("hit"))
    except (TypeError, ValueError):
        return None
    reach = re.search(r"reach\s+(\d+)\s*ft", str(text or ""), re.I)
    return {"id": re.sub(r"[^a-z0-9]+", "_", match.group("name").lower()).strip("_")[:24] or "attack",
            "name": match.group("name").strip()[:32] or "Attack",
            "to_hit": hit, "dmg": (match.group("dmg") or "")[:16],
            "reach": int(reach.group(1)) if reach else 5}


def project_creature(row, spell_rows=()):
    """Project one validated ``creatures.csv`` row into the existing NPC block.

    Unsupported free-form text is preserved in notes. The projection never
    invents mechanics that the existing NPC path cannot execute.
    """
    if not isinstance(row, dict):
        raise ValueError("creature content row required")
    raw_name = str(row.get("name") or "").strip()
    if not raw_name:
        raise ValueError("creature content row has no name")
    by_spells = {str(r.get("id") or "").lower(): r for r in spell_rows if isinstance(r, dict)}
    spells = []
    for spell_id in _content_list(row.get("spells")):
        spell = by_spells.get(spell_id)
        if not spell:
            continue
        resolution = str(spell.get("resolution") or "").lower()
        damage = spell.get("damage_dice") or spell.get("heal_dice") or ""
        spells.append({
            "id": str(spell.get("id"))[:16], "name": str(spell.get("name") or spell_id)[:48],
            "level": int(spell.get("level") or 0), "school": str(spell.get("school") or "")[:24],
            "cast": "attack" if resolution == "attack" else ("save" if resolution == "save" else "none"),
            "ability": str(spell.get("casting_ability") or "int").lower(),
            "dmg": str(damage)[:16], "save": str(spell.get("save") or "").lower(),
            "range": str(spell.get("range_ft") or "")[:24],
            "duration": str(spell.get("duration") or "")[:24],
            "targeting": str(spell.get("targeting") or "single")[:12],
        })
    attacks = []
    for part in str(row.get("attacks") or "").splitlines():
        attack = _project_attack(part)
        if attack:
            attacks.append(attack)
    skills = {s: 1 for s in _content_list(row.get("skills")) if s in gear.SKILLS}
    saves = {s: True for s in _content_list(row.get("saves")) if s in ABILITIES}
    manual = str(row.get("manual") or "").strip()
    unsupported = []
    if row.get("attacks") and not attacks:
        unsupported.append(f"attacks: {row['attacks']}")
    if row.get("abilities"):
        unsupported.append(f"abilities: {row['abilities']}")
    notes = " | ".join(unsupported + ([manual] if manual else []))[:1000]
    block = clean_npc({
        "name": raw_name[:32], "level": 1, "stats": {a: row.get(a) for a in ABILITIES},
        "hp": row.get("hp"), "max_hp": row.get("hp"), "ac": row.get("ac"),
        "speed": row.get("speed_ft"), "fly": row.get("fly_ft"),
        "darkvision_ft": row.get("darkvision_ft"),
        "attacks": attacks, "spells": spells, "saves": saves,
        "skills": skills, "notes": notes, "size": row.get("size"),
        "disposition": "hostile" if str(row.get("type") or "").lower() != "beast" else "",
        "companion": str(row.get("companion") or "").lower() in ("1", "true", "yes")
    })
    block["unsupported"] = unsupported
    block["tags"] = str(row.get("tags") or "")[:120]
    block["content_id"] = str(row.get("id") or "")[:32]
    return block


def _clamp(v, lo, hi, dflt):
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return dflt


def clean_stats(stats):
    stats = stats if isinstance(stats, dict) else {}
    return {a: _clamp(stats.get(a, 10), 1, 30, 10) for a in ABILITIES}


def clean_attacks(raw):
    """Normalise a monster's attack list: ``[{id,name,to_hit,dmg,dc,save,reach}]``.

    ``dmg`` is a free-form dice expression (rolled via the shared dice parser);
    ``to_hit`` is the flat attack bonus, ``dc`` an optional save DC, ``save`` the
    ability a target rolls against. ``reach`` is a measured distance in feet and
    is enforced by ``room.dice.handle_npc_attack`` through the one vertical/footprint
    range helper used by player attacks.
    """
    out = []
    for i, a in enumerate(raw if isinstance(raw, list) else []):
        if not isinstance(a, dict):
            continue
        save = str(a.get("save", "")).strip().lower()
        out.append({
            "id": (str(a.get("id", ""))[:24] or f"atk{i}"),
            "name": (str(a.get("name", ""))[:32] or "Attack"),
            "to_hit": _clamp(a.get("to_hit", 0), -20, 30, 0),
            "dmg": str(a.get("dmg", ""))[:16],
            "dc": _clamp(a.get("dc", 0), 0, 30, 0),
            "save": save if save in ABILITIES else "",
            "reach": _clamp(a.get("reach", 5), 0, 999, 5),
        })
    return out[:8]


def clean_size(size):
    size = str(size or "Medium").title()
    return size if size in SIZES else "Medium"


def clean_disposition(disposition):
    disposition = str(disposition or "").lower()
    return disposition if disposition in DISPOSITIONS else ""


def clean_npc(d):
    """Normalise an arbitrary DM-supplied blob into a full, bounded NPC block."""
    d = d if isinstance(d, dict) else {}
    stats = clean_stats(d.get("stats"))
    max_hp = _clamp(d.get("max_hp", d.get("hp", 10)), 1, 9999, 10)
    hp = _clamp(d.get("hp", max_hp), 0, max_hp, max_hp)
    speeds = gear.clean_speeds(d)              # walk/fly/swim/climb, SSOT in gear
    return {
        "name": str(d.get("name", ""))[:32],
        "level": _clamp(d.get("level", 1), 1, 30, 1),
        "stats": stats,
        "hp": hp,
        "max_hp": max_hp,
        "ac": _clamp(d.get("ac", 10), 1, 40, 10),
        "speed": speeds["walk"],
        "fly": speeds["fly"],
        "swim": speeds["swim"],
        "climb": speeds["climb"],
        "speeds": speeds,
        "darkvision_ft": _clamp(d.get("darkvision_ft", 0), 0, 999, 0),
        "attacks": clean_attacks(d.get("attacks", [])),
        "spells": gear.clean_spells(d.get("spells", [])),
        "spell_slots": gear.clean_slots(d.get("spell_slots", {})),
        "skills": gear.clean_skills(d.get("skills", {})),
        "saves": gear.clean_saves(d.get("saves", {})),
        "defenses": gear.clean_defenses(d.get("defenses", {})),
        "size": clean_size(d.get("size")),
        "disposition": clean_disposition(d.get("disposition")),
        "companion": bool(d.get("companion", False)),
        "abilities": _clean_abilities(d.get("abilities")),
        "resources": _clean_resources(d.get("resources")),
        "notes": str(d.get("notes", ""))[:1000],
    }


def _clean_abilities(v):
    """A mixed action list: prose entries ({name, desc} — the DM editor writes
    those) OR a bare registered-ability id string. Prose keeps the {name, desc}
    shape; a bare string is normalised to a canonical ability id so an NPC granted
    ids through the REAL add_token/update_npc path stays castable — _rollable_by
    reads exactly this list (D100/G8b: previously string ids were dropped here,
    so only DM-controlled casts worked). Anything else is dropped."""
    out = []
    for a in (v or [])[:12]:
        if isinstance(a, str):
            s = a.strip().lower()[:32]
            if s:
                out.append(s)
            continue
        if not isinstance(a, dict):
            continue
        name = str(a.get("name", ""))[:32].strip()
        desc = str(a.get("desc", ""))[:240].strip()
        if name or desc:
            out.append({"name": name or "Action", "desc": desc})
    return out


def _clean_resources(v):
    """Tracked non-spell resources (breath weapon uses, lair actions...).

    'cur' is live state; a long rest refills it (room.dice handle_long_rest).
    """
    out = []
    for r in (v or [])[:10]:
        if not isinstance(r, dict):
            continue
        name = str(r.get("name", ""))[:32].strip()
        if not name:
            continue
        mx = _clamp(r.get("max", 1), 0, 99, 1)
        cur = _clamp(r.get("cur", mx), 0, mx, mx)
        out.append({"name": name, "max": mx, "cur": cur})
    return out


def load(tok):
    """Parse a token row's ``npc`` column into a dict, or None if it isn't an NPC."""
    npc = db.j(tok.get("npc"), None) if tok else None
    return npc if isinstance(npc, dict) else None


def to_char(npc, name=""):
    """Adapter so gear/spell math treats an NPC block like a character sheet."""
    return {"name": name or npc.get("name", "NPC"),
            "stats": npc.get("stats", {}), "level": npc.get("level", 1)}


def stat_mod(npc, ability):
    """Delegate to the canonical derivation (D56) — same clamp, same fallback."""
    return gear.stat_mod(npc if isinstance(npc, dict) else {}, ability)


def dex_mod(npc):
    return gear.dex_mod(npc if isinstance(npc, dict) else {})
