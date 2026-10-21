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

from .gear import ABILITIES as _SAVES

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
    # D109 mastery markers (house markers, not SRD conditions): 'sapped' =
    # disadvantage on the NEXT attack roll (SRD Sap), 'slowed' = -10 ft speed
    # (SRD Slow), 'vexed' = the bearer has advantage against token 'ref'
    # (SRD Vex). They carry src (the anchoring attacker's turn clock) and the
    # optional ref (vexed's target) — see step_src.
    "sapped": ("Sapped", "😨", "#a1887f"),
    "slowed": ("Slowed", "🐌", "#90a4ae"),
    "vexed": ("Vexed", "🎯", "#7e57c2"),
}
MAX_CONDS = 24
_KEY_RE = re.compile(r"^[\x20-\x7e]{1,24}$")
# The ONE clock per condition (D80): "" = round clock, "start"/"end" = the
# affected creature's turn clock (driven by room/combat.py turn hooks only).
UNTIL = ("", "start", "end")


def _clean_until(value):
    v = str(value or "").strip().lower()
    return v if v in ("start", "end") else ""


def _clean_sa(value):
    """D130: the save ability of a save-ends entry ('str'..'cha'), or '' = none."""
    v = str(value or "").strip().lower()[:3]
    return v if v in _SAVES else ""


def label(key):
    meta = CONDITIONS.get(key)
    return meta[0] if meta else str(key)[:24]


def info(key):
    """(label, glyph, color) for a known key; a neutral gray dot for homebrew."""
    return CONDITIONS.get(key, (label(key), "•", "#7f8c8d"))


def _clean_tok_ref(v):
    """D109: optional src/ref token ids — positive ints or absent (None)."""
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _clean_dc(v):
    """D112: an optional escape DC carried on a condition instance (grapple).
    A plain int in the 1–30 band or absent (None) — additive, so every pre-D112
    entry (which has no ``dc``) round-trips byte-identically."""
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if 1 <= n <= 30 else None


def _clean_conc(v):
    """D113: the token id of the CONCENTRATOR that owns this condition instance.
    A positive int (a caster token) or absent (None) — additive, so a pre-D113
    entry (no ``conc``) round-trips byte-identically and an entry without a link
    behaves exactly as before. See room/concentration.py for the lifecycle."""
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


# Conditions that end concentration the instant they land on a concentrating
# creature (2024: incapacitated — and the states that impose it — breaks
# concentration). A token at 0 HP is handled by the damage reducer directly.
INCAP_KEYS = ("incapacitated", "paralyzed", "stunned", "unconscious", "petrified")


def blocks_concentration(conds):
    """True when any held condition is one of the concentration-ending states."""
    ks = {str(c.get("k", "")).lower() for c in clean_conds(conds)}
    return bool(ks & set(INCAP_KEYS))


def strip_link(conds, caster_id):
    """D113: drop every entry LINKED to a concentrator's token id (``conc``).
    The concentrating flag is NOT removed here (the caller owns that); a caster_id
    that is not a positive token id removes nothing."""
    cid = _clean_conc(caster_id)
    out = clean_conds(conds)
    if cid is None:
        return out
    return [c for c in out if c.get("conc") != cid]


def has_link(conds, caster_id):
    """True when any entry is linked to this concentrator's token id."""
    cid = _clean_conc(caster_id)
    return cid is not None and any(c.get("conc") == cid for c in clean_conds(conds))


def clean_conds(raw):
    """Normalise an arbitrary list into ``[{k, rounds, until, src?, ref?}]``,
    deduped, bounded. D109: ``src`` anchors a marker's expiry to ANOTHER
    token's turn clock (see step_src); entries may then share a key when their
    refs differ (vexed against several targets), everything else dedupes by
    key exactly as before."""
    out, seen = [], set()
    if not isinstance(raw, list):
        return out
    for e in raw[:MAX_CONDS]:
        if isinstance(e, dict):
            k, rounds = e.get("k", e.get("key")), e.get("rounds", 0)
            until = _clean_until(e.get("until"))
            src, ref = _clean_tok_ref(e.get("src")), _clean_tok_ref(e.get("ref"))
            dc = _clean_dc(e.get("dc"))
            conc = _clean_conc(e.get("conc"))
            sa = _clean_sa(e.get("sa"))
        else:
            k, rounds, until, src, ref, dc, conc, sa = e, 0, "", None, None, None, None, ""
        k = str(k).strip()
        sig = (k.lower(), ref, src) if src is not None else k.lower()
        if not k or not _KEY_RE.match(k) or sig in seen:
            continue
        try:
            rounds = max(0, min(999, int(rounds)))
        except (TypeError, ValueError):
            rounds = 0
        seen.add(sig)
        entry = {"k": k, "rounds": rounds, "until": until}
        if src is not None:
            entry["src"] = src
            if ref is not None:
                entry["ref"] = ref
        if dc is not None:
            entry["dc"] = dc
        if conc is not None:
            entry["conc"] = conc
        if sa:
            entry["sa"] = sa
        out.append(entry)
    return out


def immune(tok, key):
    """D163-2: data-driven condition immunity (NPC block ``cond_immune``,
    projected from creatures.csv). PCs carry no data immunity today — the
    engine has no PC source for one (documented limit). DM manual condition
    edits stay un-gated on purpose (DM authority over the raw truth)."""
    from . import npc as _NPC                     # lazy: npc imports gear/db only
    block = _NPC.load(tok)
    if not block:
        return False
    keys = block.get("cond_immune") or []
    key = str(key).strip().lower()
    return bool(key) and key in {str(k).strip().lower() for k in keys}


def load(tok):
    return clean_conds(db.j(tok.get("conds"), [])) if tok else []


def add(conds, key, rounds=0, until="", src=None, ref=None, dc=None, conc=None, sa=""):
    """Add or refresh a condition; returns a new list. D109: ``src``/``ref``
    mark a mastery marker anchored to the SRC token's turn clock (a refresh
    matches key AND ref AND src, so e.g. two 'vexed' markers against two
    different targets coexist and each refreshes itself). D112: ``dc`` carries an
    optional escape DC on the instance (a grapple's escape DC); a refresh to the
    same key/src/ref updates it too. D113: ``conc`` links the instance to a
    concentrator's token id — a condition a concentration spell OWNS, ended when
    that concentration breaks; it is pure metadata and never affects dedup.
    D130: ``sa`` marks a save-ends entry — the affected creature repeats this
    save at the end of its own turn (room/combat.py ``_save_ends`` against the
    instance ``dc``); success removes exactly this entry. Never affects
    dedup."""
    key = str(key).strip()
    until = _clean_until(until)
    src, ref = _clean_tok_ref(src), _clean_tok_ref(ref)
    dc = _clean_dc(dc)
    conc = _clean_conc(conc)
    sa = _clean_sa(sa)
    out = clean_conds(conds)
    if not key or not _KEY_RE.match(key):
        return out
    try:
        rounds = max(0, min(999, int(rounds or 0)))
    except (TypeError, ValueError):
        rounds = 0
    for c in out:
        if c["k"].lower() == key.lower() and c.get("src") == src and c.get("ref") == ref:
            c["rounds"], c["until"] = rounds, until
            if dc is not None:
                c["dc"] = dc
            if conc is not None:
                c["conc"] = conc
            if sa:
                c["sa"] = sa
            return out
    if len(out) < MAX_CONDS:
        out.append({"k": key, "rounds": rounds, "until": until,
                    **({"src": src, **({"ref": ref} if ref is not None else {})}
                       if src is not None else {}),
                    **({"dc": dc} if dc is not None else {}),
                    **({"conc": conc} if conc is not None else {}),
                    **({"sa": sa} if sa else {})})
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
    (``until`` == "") are never touched here (D80 — one clock per condition).
    D109: entries with a ``src`` do NOT run on their owner's clock — they are
    advanced exclusively by step_src."""
    out, changed = [], False
    for c in clean_conds(conds):
        if c.get("src") is not None:
            out.append(c)
            continue
        if c["until"] == phase and c["rounds"] > 0:
            c["rounds"] -= 1
            changed = True
            if c["rounds"] == 0:
                continue                      # expired at this turn hook → drop
        out.append(c)
    return out, changed


def step_src(conds, token_id, phase):
    """D109 (mastery durations anchored to the ATTACKER): advance every marker
    whose ``src`` is ``token_id`` at that token's turn ``phase`` — the same
    single lifecycle hooks room/combat.py already owns (D80). ``rounds`` 1
    decays toward expiry (SRD Vex: 'until the END of my next turn' survives
    one end-hook); ``rounds`` 0 drops at the first matching hook (SRD Sap/Slow:
    'until the START of my next turn'). Returns ``(new_list, changed_bool)``."""
    out, changed = [], False
    for c in clean_conds(conds):
        if c.get("src") == token_id and c["until"] == phase:
            changed = True
            if c["rounds"] > 0:
                c["rounds"] -= 1
                out.append(c)
            continue                          # rounds 0 → expired here, drop
        out.append(c)
    return out, changed


def has(conds, key, ref=None):
    """The (first) entry for key [+ ref], or None."""
    key = str(key).strip().lower()
    for c in conds:
        if c["k"].lower() == key and (ref is None or c.get("ref") == ref):
            return c
    return None


def consume(conds, key, ref=None):
    """Remove ONE entry for key [+ ref]. Returns ``(new_list, removed_entry|None)``."""
    key = str(key).strip().lower()
    out, removed = [], None
    for c in conds:
        if removed is None and c["k"].lower() == key and (ref is None or c.get("ref") == ref):
            removed = c
            continue
        out.append(c)
    return out, removed


def is_concentrating(conds):
    return any(c["k"].lower() == "concentrating" for c in conds)


# ---------------------------------------------------------------------------
# D111: the DEFINITION layer — conditions.csv (content kind "condition") adds
# to the built-in catalog above; instances stay exactly the {k,rounds,until,
# src,ref} entries this module has always owned (no migration, no second
# state). A definition carries (a) presentation (name/glyph/color) and (b)
# mechanical HOOKS from one closed vocabulary; the engine's existing readers
# (movement, dice, abilities) ask THIS module which flags a key sets instead
# of comparing key names themselves. Homebrew keys without a row keep working
# as pure labels exactly as before (D3 stayed additive).
# ---------------------------------------------------------------------------
HOOKS = ("blocks_movement", "speed_delta", "my_attacks_dis", "my_checks_dis",
         "my_saves_dis", "attacks_against_me_adv", "attacks_against_me_dis",
         "auto_fail_saves", "no_actions")
# SRD 5.2.1 'Conditions', wired data-style (2024 simplifications documented in
# docs/EFFECT_GRAMMAR.md: blanket disadvantage where the SRD keys on a source
# (frightened), sight-check auto-fails folded into checks-dis (blinded),
# prone's melee-adv/ranged-dis split stays DM-adjudicated).
BUILTIN_HOOKS = {
    "blinded": {"attacks_against_me_adv": True, "my_attacks_dis": True,
                "my_checks_dis": True},
    "frightened": {"my_attacks_dis": True, "my_checks_dis": True},
    "grappled": {"blocks_movement": True},
    # D134: 2024 THE ONE Incapacitated — no actions, no reactions (reactions
    # are the documented v1 gap), but MOVEMENT stays free; the STR/DEX auto-
    # fail belongs to the family members below, not to the parent condition.
    "incapacitated": {"no_actions": True},
    "invisible": {"attacks_against_me_dis": True},
    "paralyzed": {"blocks_movement": True, "attacks_against_me_adv": True,
                  "auto_fail_saves": "str,dex", "no_actions": True},
    "petrified": {"blocks_movement": True, "auto_fail_saves": "str,dex",
                "no_actions": True},
    "poisoned": {"my_attacks_dis": True, "my_checks_dis": True},
    "restrained": {"blocks_movement": True, "attacks_against_me_adv": True,
                   "my_attacks_dis": True, "my_saves_dis": True},
    "slowed": {"speed_delta": -10},
    "stunned": {"blocks_movement": True, "attacks_against_me_adv": True,
                "auto_fail_saves": "str,dex", "no_actions": True},
    "unconscious": {"blocks_movement": True, "attacks_against_me_adv": True,
                    "my_attacks_dis": True, "my_checks_dis": True,
                    "auto_fail_saves": "str,dex", "no_actions": True},
}
_cache = {}                                     # room_id -> {key: definition}


def invalidate(room_id=None):
    if room_id is None:
        _cache.clear()
    else:
        _cache.pop(room_id, None)


def catalog(room_id):
    """Built-in catalog + conditions.csv rows of this room (rows win/extend).
    Cache per room; a content import invalidates it (content.apply_rows)."""
    cached = _cache.get(room_id)
    if cached is not None:
        return cached
    out = {}
    for k, (name, glyph, color) in CONDITIONS.items():
        out[k] = {"id": k, "name": name, "glyph": glyph, "color": color,
                  "group": "marker" if k in ("sapped", "slowed", "vexed",
                                             "concentrating") else "condition",
                  **BUILTIN_HOOKS.get(k, {})}
    try:
        from . import content
        rows = content.load("condition", room_id) if "condition" in content.ALL_KINDS else []
    except Exception:                            # catalog reads must never break play
        rows = []
    for row in rows:
        key = str(row.get("id", "")).strip().lower()
        if not key or not _KEY_RE.match(key):
            continue
        base = dict(out.get(key, {"id": key, "name": row.get("name") or key,
                                  "glyph": "•", "color": "#7f8c8d",
                                  "group": "condition"}))
        for fld in ("name", "glyph", "color", "group"):
            v = str(row.get(fld) or "").strip()
            if v:
                base[fld] = v
        try:
            if int(row.get("blocks_movement") or 0):
                base["blocks_movement"] = True
        except (TypeError, ValueError):
            pass
        try:
            sd = int(row.get("speed_delta") or 0)
            if sd:
                base["speed_delta"] = max(-100, min(100, sd))
        except (TypeError, ValueError):
            pass
        for h in ("my_attacks_dis", "my_checks_dis", "my_saves_dis",
                  "attacks_against_me_adv", "attacks_against_me_dis"):
            if str(row.get(h) or "").strip() in ("1", "true", "yes", "on"):
                base[h] = True
        afs = str(row.get("auto_fail_saves") or "").strip().lower()
        if afs:
            good = [a for a in afs.split(",")
                    if a in ("str", "dex", "con", "int", "wis", "cha")]
            if good:
                prev = set(str(base.get("auto_fail_saves", "")).split(",")) - {""}
                base["auto_fail_saves"] = ",".join(sorted(prev | set(good)))
        eff = str(row.get("effects") or "").strip()
        if eff:
            base["effects"] = eff
        out[key] = base
    _cache[room_id] = out
    return out


def definition(key, room_id):
    return catalog(room_id).get(str(key or "").strip().lower())


def info_room(key, room_id):
    """info() against the room's merged catalog (falls back to the built-in)."""
    d = definition(key, room_id)
    if d:
        return d.get("name", label(key)), d.get("glyph", "•"), d.get("color", "#7f8c8d")
    return info(key)


def hook_bool(conds, room_id, name):
    """True when ANY condition on the token sets the boolean hook ``name``."""
    cat = catalog(room_id)
    for c in conds:
        d = cat.get(str(c.get("k", "")).lower())
        if d and d.get(name):
            return True
    return False


def speed_delta(conds, room_id):
    """Summed ft delta from speed_delta hooks."""
    cat = catalog(room_id)
    total = 0
    for c in conds:
        d = cat.get(str(c.get("k", "")).lower())
        if d and isinstance(d.get("speed_delta"), int):
            total += d["speed_delta"]
    return total


def auto_fails_save(conds, room_id, ability):
    ab = str(ability or "").lower()
    if ab not in ("str", "dex", "con", "int", "wis", "cha"):
        return False
    cat = catalog(room_id)
    for c in conds:
        d = cat.get(str(c.get("k", "")).lower())
        if d and ab in str(d.get("auto_fail_saves", "")).split(","):
            return True
    return False


def effects_for(key, room_id, hook):
    """The validated ops list a condition definition runs on ``hook``
    (on_start/on_round/on_expire), or None."""
    import json as _json
    d = definition(key, room_id)
    cell = str((d or {}).get("effects") or "")
    if not cell:
        return None
    try:
        hooks = _json.loads(cell)
    except ValueError:
        return None
    if not isinstance(hooks, dict):
        return None
    ops = hooks.get(hook)
    if not ops:
        return None
    from . import effectops
    try:
        out = effectops.validate({hook: ops})
        return out.get(hook) or None
    except effectops.EffectError:
        return None


def expired_keys(old, new):
    """Keys present in ``old`` but gone from ``new`` (a key expired only when
    NO entry of that key survived — src/ref refreshes keep it alive)."""
    nk = {c["k"].lower() for c in new}
    return [c["k"] for c in old if c["k"].lower() not in nk]
