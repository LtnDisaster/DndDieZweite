"""Conditions / status effects (SSOT).

A combat condition (blinded, prone, concentrating, …) is stored as a compact JSON
list on the **token** (play-time entity, not the character library): ``tokens.conds``.
Each entry is ``{"k": key, "rounds": n}`` where ``rounds`` is 0 for "until removed"
or a positive countdown decremented once per round. This module owns the catalog,
validation and round-progression logic; the *mechanical* consequences are NOT applied
here by design (D3 keeps gameplay rules explicit and additive) — the architecture
just needs to carry the flag reliably so effects can be layered on later.
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


def label(key):
    meta = CONDITIONS.get(key)
    return meta[0] if meta else str(key)[:24]


def info(key):
    """(label, glyph, color) for a known key; a neutral gray dot for homebrew."""
    return CONDITIONS.get(key, (label(key), "•", "#7f8c8d"))


def clean_conds(raw):
    """Normalise an arbitrary list into ``[{k, rounds}]``, deduped and bounded."""
    out, seen = [], set()
    if not isinstance(raw, list):
        return out
    for e in raw[:MAX_CONDS]:
        if isinstance(e, dict):
            k, rounds = e.get("k", e.get("key")), e.get("rounds", 0)
        else:
            k, rounds = e, 0
        k = str(k).strip()
        if not k or not _KEY_RE.match(k) or k.lower() in seen:
            continue
        try:
            rounds = max(0, min(999, int(rounds)))
        except (TypeError, ValueError):
            rounds = 0
        seen.add(k.lower())
        out.append({"k": k, "rounds": rounds})
    return out


def load(tok):
    return clean_conds(db.j(tok.get("conds"), [])) if tok else []


def add(conds, key, rounds=0):
    """Add or refresh a condition; returns a new list."""
    key = str(key).strip()
    out = clean_conds(conds)
    if not key or not _KEY_RE.match(key):
        return out
    for c in out:
        if c["k"].lower() == key.lower():
            c["rounds"] = max(0, min(999, int(rounds or 0)))
            return out
    if len(out) < MAX_CONDS:
        out.append({"k": key, "rounds": max(0, min(999, int(rounds or 0)))})
    return out


def remove(conds, key):
    key = str(key).strip().lower()
    return [c for c in clean_conds(conds) if c["k"].lower() != key]


def step_rounds(conds):
    """Advance one round: decrement timed conditions and drop the ones that expire.

    Returns ``(new_list, changed_bool)``. Conditions with ``rounds == 0`` are
    permanent ("until removed") and are left untouched.
    """
    out, changed = [], False
    for c in clean_conds(conds):
        if c["rounds"] > 0:
            c["rounds"] -= 1
            changed = True
            if c["rounds"] == 0:
                continue                      # expired this round → drop
        out.append(c)
    return out, changed


def is_concentrating(conds):
    return any(c["k"].lower() == "concentrating" for c in conds)
