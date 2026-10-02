"""Class progression: a multiclass-ready character model (D53).

A character's classes are a COLLECTION of class-level entries — never a single
``class = "fighter"`` field:

    [{"class_id": "fighter", "level": 3}, {"class_id": "wizard", "level": 2}]

Total character level is DERIVED (sum of entries), with the legacy ``level``
column as the single-class fallback so every existing consumer keeps working.
``total_character_level`` is the ONE canonical derivation — never re-``sum``
the entries elsewhere.

This module is ENGINE STRUCTURE ONLY: no class feature tables, no subclass
text, no progression prose (licensing boundary: ATTRIBUTION.md). Generic
identifiers are caller-supplied. Per-class hit dice / resources / spellcasting
progression can attach to these entries later; no speculative columns exist
today (TODO).

Like ``app.quests``, these are pure game operations: callable from the WS
handler today and from future automation without any transport.
"""
import re

from . import db

MAX_TOTAL_LEVEL = 20
MAX_ENTRIES = 8
_CLASS_ID_RE = re.compile(r"^[a-z0-9][a-z0-9 _-]{0,23}$")


def clean_class_levels(raw):
    """Strict canonical parse of a class-level payload.

    Returns the normalized list, or ``None`` when anything is invalid
    (non-list, junk entry, level outside 1..20, duplicate class, over cap).
    Strictness is deliberate: a partially-applied progression is worse than a
    rejected one.
    """
    if not isinstance(raw, list) or not raw or len(raw) > MAX_ENTRIES:
        return None
    out, seen = [], set()
    for e in raw:
        if not isinstance(e, dict):
            return None
        cid = str(e.get("class_id", "")).strip().lower()
        if not _CLASS_ID_RE.match(cid) or cid in seen:
            return None
        try:
            lvl = int(e.get("level"))
        except (TypeError, ValueError):
            return None
        if not 1 <= lvl <= MAX_TOTAL_LEVEL:
            return None
        seen.add(cid)
        out.append({"class_id": cid, "level": lvl})
    if sum(e["level"] for e in out) > MAX_TOTAL_LEVEL:
        return None
    return out


def load(char) -> list:
    """Read a character's class entries (row dict or dict); [] if none."""
    raw = char.get("class_levels") if char else None
    if isinstance(raw, str):
        raw = db.j(raw, None)
    return clean_class_levels(raw) or []


def total_character_level(char) -> int:
    """THE canonical total level. Derived from class entries when present,
    otherwise the legacy single-class ``level`` column."""
    entries = load(char)
    if entries:
        return max(1, min(MAX_TOTAL_LEVEL, sum(e["level"] for e in entries)))
    try:
        return max(1, min(MAX_TOTAL_LEVEL, int((char or {}).get("level") or 1)))
    except (TypeError, ValueError):
        return 1


def format_classes(char) -> str:
    """Display helper: 'Fighter 3 / Wizard 2' ('' when no entries)."""
    return " / ".join(f"{e['class_id'].title()} {e['level']}" for e in load(char))


def set_class_levels(char_id, raw) -> bool:
    """Validate + persist class levels; keeps the legacy ``level`` column in
    sync so existing consumers (hit dice, slots, sheet math) see the derived
    total without re-deriving it. Returns False on invalid input."""
    entries = clean_class_levels(raw)
    if entries is None:
        return False
    total = sum(e["level"] for e in entries)
    db.x("UPDATE characters SET class_levels=?, level=? WHERE id=?",
         (db.json_dumps(entries), total, int(char_id)))
    return True
