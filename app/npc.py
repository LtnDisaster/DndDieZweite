"""NPC / enemy stat blocks stored on a token (the ``tokens.npc`` JSON column).

A monster token has no ``characters`` row and no owner; everything the DM needs at
the table lives in this JSON blob: ability scores, HP/AC, level, speed, a castable
spell list and DM-tracked spell slots. The math reuses the same ``gear`` primitives
that player sheets use, by handing them a lightweight "pseudo-character" via
:func:`to_char` (``{"name", "stats", "level"}``) so spell attack / save DC / damage
stay a single source of truth.
"""
from . import db, gear

ABILITIES = gear.ABILITIES
SIZES = ("Tiny", "Small", "Medium", "Large", "Huge", "Gargantuan")
DISPOSITIONS = ("", "friend", "neutral", "hostile")


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
    ability a target rolls against. ``reach`` is advisory (measured in cells).
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
    return {
        "name": str(d.get("name", ""))[:32],
        "level": _clamp(d.get("level", 1), 1, 30, 1),
        "stats": stats,
        "hp": hp,
        "max_hp": max_hp,
        "ac": _clamp(d.get("ac", 10), 1, 40, 10),
        "speed": _clamp(d.get("speed", 30), 0, 999, 30),
        "attacks": clean_attacks(d.get("attacks", [])),
        "spells": gear.clean_spells(d.get("spells", [])),
        "spell_slots": gear.clean_slots(d.get("spell_slots", {})),
        "saves": gear.clean_saves(d.get("saves", {})),
        "defenses": gear.clean_defenses(d.get("defenses", {})),
        "size": clean_size(d.get("size")),
        "disposition": clean_disposition(d.get("disposition")),
        "abilities": _clean_abilities(d.get("abilities")),
        "resources": _clean_resources(d.get("resources")),
        "notes": str(d.get("notes", ""))[:1000],
    }


def _clean_abilities(v):
    """Prose action entries ({name, desc}) — the 'Multiattack/Breath' block."""
    out = []
    for a in (v or [])[:12]:
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
    try:
        return (int(npc["stats"].get(ability, 10)) - 10) // 2
    except (TypeError, ValueError, KeyError, AttributeError):
        return 0


def dex_mod(npc):
    return stat_mod(npc, "dex")
