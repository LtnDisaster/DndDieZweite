"""Conditions / status effects (SSOT).

A combat condition (blinded, prone, concentrating, …) is stored as a compact JSON
list on the **token** (play-time entity, not the character library): ``tokens.conds``.
Each entry is ``{"k": key, "rounds": n, "until": anchor}`` where ``rounds`` is 0 for
"until removed" or a positive countdown, and ``until`` picks the condition's ONE
clock (D80): "" = the round clock (decremented once per round at the round wrap),
"start"/"end" = the affected creature's own turn clock (advanced only by the combat
turn hooks in room/combat.py — never by the round clock, so a condition can never
tick twice). This module owns the catalog, validation and progression logic; the
*mechanical* consequences are NOT applied here by design (D3 keeps gameplay rules
explicit and additive) — the architecture just needs to carry the flag reliably so
effects can be layered on later.
"""
import re

from . import db

# key -> (label, glyph, color). Color is the canvas dot tint; glyph is a compact tag.
CONDITIONS = {
    "blinded": ("Blinded", "👁", "#8e44ad"),
    "charmed": ("Charmed", "💗", "#e84393"),
    "deafened": ("Deafened", "🔇", "#7f8c8d"),
    "frightened": ("Frightened", "😱", "#e67e22"),
    "grappled": ("Grappled", "🤼", "#16a085"),
    "incapacitated": ("Incapacitated", "💫", "#c0392b"),
    "invisible": ("Invisible", "👻", "#5dade2"),
    "paralyzed": ("Paralyzed", "🧊", "#2980b9"),
    "petrified": ("Petrified", "🗿", "#95a5a6"),
    "poisoned": ("Poisoned", "☠", "#27ae60"),
    "prone": ("Prone", "⬇", "#d35400"),
    "restrained": ("Restrained", "🕸", "#34495e"),
    "stunned": ("Stunned", "💥", "#f1c40f"),
    "unconscious": ("Unconscious", "😵", "#7f8c8d"),
    "concentrating": ("Concentrating", "✨", "#d4a017"),
}
MAX_CONDS = 24
_KEY_RE = re.compile(r"^[\x20-\x7e]{1,24}$")
# The ONE clock per condition (D80): "" = round clock, "start"/"end" = the
# affected creature's turn clock (driven by room/combat.py turn hooks only).
UNTIL = ("", "start", "end")


def _clean_until(value):
    v = str(value or "").strip().lower()
    return v if v in ("start", "end") else ""


def label(key):
    meta = CONDITIONS.get(key)
    return meta[0] if meta else str(key)[:24]


def info(key):
    """(label, glyph, color) for a known key; a neutral gray dot for homebrew."""
    return CONDITIONS.get(key, (label(key), "•", "#7f8c8d"))


def clean_conds(raw):
    """Normalise an arbitrary list into ``[{k, rounds, until}]``, deduped, bounded."""
    out, seen = [], set()
    if not isinstance(raw, list):
        return out
    for e in raw[:MAX_CONDS]:
        if isinstance(e, dict):
            k, rounds = e.get("k", e.get("key")), e.get("rounds", 0)
            until = _clean_until(e.get("until"))
        else:
            k, rounds, until = e, 0, ""
        k = str(k).strip()
        if not k or not _KEY_RE.match(k) or k.lower() in seen:
            continue
        try:
            rounds = max(0, min(999, int(rounds)))
        except (TypeError, ValueError):
            rounds = 0
        seen.add(k.lower())
        out.append({"k": k, "rounds": rounds, "until": until})
    return out


def load(tok):
    return clean_conds(db.j(tok.get("conds"), [])) if tok else []


def add(conds, key, rounds=0, until=""):
    """Add or refresh a condition; returns a new list."""
    key = str(key).strip()
    until = _clean_until(until)
    out = clean_conds(conds)
    if not key or not _KEY_RE.match(key):
        return out
    try:
        rounds = max(0, min(999, int(rounds or 0)))
    except (TypeError, ValueError):
        rounds = 0
    for c in out:
        if c["k"].lower() == key.lower():
            c["rounds"], c["until"] = rounds, until
            return out
    if len(out) < MAX_CONDS:
        out.append({"k": key, "rounds": rounds, "until": until})
    return out


def remove(conds, key):
    key = str(key).strip().lower()
    return [c for c in clean_conds(conds) if c["k"].lower() != key]


def step_rounds(conds):
    """Advance the ROUND clock once: decrement untimed-anchor conditions and drop
    the ones that expire. Returns ``(new_list, changed_bool)``.

    One clock per condition (D80): entries anchored to a turn (``until`` =
    "start"/"end") are NEVER touched here — only ``step_turn`` advances them, so
    a condition can never tick through both a round and a turn hook.
    Conditions with ``rounds == 0`` and no anchor are permanent ("until removed").
    """
    out, changed = [], False
    for c in clean_conds(conds):
        if c["until"]:
            out.append(c)
            continue
        if c["rounds"] > 0:
            c["rounds"] -= 1
            changed = True
            if c["rounds"] == 0:
                continue                      # expired this round → drop
        out.append(c)
    return out, changed


def step_turn(conds, phase):
    """Advance the TURN clock of one creature: decrement conditions anchored to
    ``phase`` ("start" or "end" of this creature's turn) and drop the expiring
    ones. Returns ``(new_list, changed_bool)``. Round-clock conditions
    (``until`` == "") are never touched here (D80 — one clock per condition)."""
    out, changed = [], False
    for c in clean_conds(conds):
        if c["until"] == phase and c["rounds"] > 0:
            c["rounds"] -= 1
            changed = True
            if c["rounds"] == 0:
                continue                      # expired at this turn hook → drop
        out.append(c)
    return out, changed


def is_concentrating(conds):
    return any(c["k"].lower() == "concentrating" for c in conds)
