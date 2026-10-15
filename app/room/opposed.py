"""D112 (Sprint 41): the generic server-authoritative resolution primitive for
compared checks (Gegeneinanderprobe) — plus the sibling shapes D&D 2024 / SRD
5.2.1 actually uses: an attacker check that SETS a DC against a target saving
throw, and a check against a fixed DC.

This module is a THIN COMPOSITION over the engines that already exist; it is
deliberately NOT a second rules engine:

  * every die runs through ``room.dice.do_roll`` — the one d20 engine;
  * every modifier comes from ``gear`` (``skill_bonus`` / ``save_bonus`` /
    ``stat_mod`` / ``ability_attack_bonus`` / ``prof_bonus``) — never re-derived
    here;
  * advantage/disadvantage and the standing condition hooks are the SAME ones
    ``room.dice`` applies to a plain check/save (``conditions.auto_fails_save``,
    the ``my_checks_dis`` / ``my_saves_dis`` hooks, the one combine rule);
  * visibility and delivery are the caller's, through ``room.gamelog``;
  * idempotency is the caller's, through the SAME ``inventory._claim`` op guard.

Where D&D 2024 wants a fixed DC, a passive-style notice score (2024 has NO
passive perception — ``RULES_AUDIT_2024.md`` A7), or a plain saving throw, the
engine must NOT force an opposed check: the caller picks the mode. This module
exposes only the tiny, pure comparison helpers below and the per-participant
rolls; it NEVER mutates a token, posts a message or touches an inventory. The
caller posts the flavour and applies effects through the existing sub-engines
(``conditions`` / ``knock_prone`` / ``apply_forced_move`` / ``inventory``).
"""
from .. import gear, npc
from .. import conditions as CND
from .dice import do_roll, _combine_adv

ABILITIES = gear.ABILITIES


def participant(room_id, tok):
    """(sheet, skills, saves, name, conds) for a PC or an NPC token, or None.

    A PC reads the live character sheet; an NPC is handed to the SAME gear
    primitives through ``npc.to_char`` (the one adapter the ability engine and
    the dice channel already use), so a skill / save / attack bonus means
    exactly the same thing for both. NPCs carry no skill proficiencies, so a
    skill roll for an NPC degrades to the raw ability modifier — never a guess."""
    if tok is None:
        return None
    if tok.get("character_id"):
        ch = gear.as_sheet(db_char(tok["character_id"]))
        if ch is None:
            return None
        return {"kind": "pc", "sheet": ch, "skills": gear.clean_skills(_j(ch.get("skills"))),
                "saves": gear.clean_saves(_j(ch.get("saves"))), "name": ch["name"],
                "stats_id": ch["id"], "conds": CND.load(tok), "room_id": room_id,
                "token": tok}
    blk = npc.load(tok)
    if blk is None:
        return None
    return {"kind": "npc", "sheet": npc.to_char(blk, tok.get("label")),
            "skills": gear.clean_skills(blk.get("skills") or {}),
            "saves": gear.clean_saves(blk.get("saves") or {}),
            "name": tok.get("label") or blk.get("name") or "NPC",
            "stats_id": tok["id"], "conds": CND.load(tok), "room_id": room_id,
            "token": tok}


def _j(v):
    from .. import db
    return db.j(v, {}) or {}


def db_char(char_id):
    from .. import db
    return db.q1("SELECT * FROM characters WHERE id=?", (char_id,))


# ---------------------------------------------------------------------------
# one participant's d20 result — mirrors room.dice.handle_roll's branches and
# the D111 standing condition hooks exactly, so an opposed roll is not a second
# definition of what a "skill check" or a "saving throw" costs.
# ---------------------------------------------------------------------------

def check_roll(p, key, kind="skill", adv=None, prof=False):
    """A skill check (``kind='skill'``, ``key`` in gear.SKILLS) or a raw ability
    check (``kind='check'``, ``key`` in ABILITIES). Returns
    ``{kept, mod, total, adv, auto_fail}`` — ``auto_fail`` is always False for a
    check (no condition auto-fails a check in the SRD)."""
    sheet, conds, room_id = p["sheet"], p["conds"], p["room_id"]
    adv = _combine_adv(adv, "dis") if CND.hook_bool(conds, room_id, "my_checks_dis") else adv
    if kind == "skill":
        key = str(key or "").lower()
        if key not in gear.SKILLS:
            return None
        mod, prof = gear.skill_bonus(sheet, p["skills"], key)
    else:
        key = str(key or "").lower()
        if key not in ABILITIES:
            return None
        mod = gear.stat_mod(sheet, key) + (gear.prof_bonus(sheet) if prof else 0)
    res = do_roll("1d20", adv)
    return {"kept": res["kept"], "mod": mod, "total": res["kept"] + mod,
            "adv": res["adv"], "auto_fail": False, "prof": bool(prof)}


def save_roll(p, ability, adv=None):
    """A saving throw vs a DC. Honours the SRD standing rules the engine already
    applies to a normal save: an ``auto_fail_saves`` condition short-circuits,
    ``my_saves_dis`` adds disadvantage."""
    sheet, conds, room_id = p["sheet"], p["conds"], p["room_id"]
    ability = str(ability or "").lower()
    if ability not in ABILITIES:
        return None
    if CND.auto_fails_save(conds, room_id, ability):
        return {"kept": 0, "mod": 0, "total": 0, "adv": None, "auto_fail": True,
                "ability": ability}
    adv = _combine_adv(adv, "dis") if CND.hook_bool(conds, room_id, "my_saves_dis") else adv
    mod = gear.save_bonus(sheet, p["saves"], ability)
    res = do_roll("1d20", adv)
    return {"kept": res["kept"], "mod": mod, "total": res["kept"] + mod,
            "adv": res["adv"], "auto_fail": False, "ability": ability}


def bonus_roll(p, bonus, adv=None):
    """A d20 plus a flat, server-derived bonus (used for the 2024 Grapple/Shove
    attacker number, which is the HIGHER of the unarmed-strike attack bonus and
    the Athletics check — the caller computes the bonus with ``gear``)."""
    adv = _combine_adv(adv, "dis") if CND.hook_bool(p["conds"], p["room_id"], "my_checks_dis") else adv
    res = do_roll("1d20", adv)
    return {"kept": res["kept"], "mod": int(bonus), "total": res["kept"] + int(bonus),
            "adv": res["adv"], "auto_fail": False}


def melee_attack_number(p):
    """The 2024 special-melee-attack number for a Shove/Grapple: a Strength
    (Athletics) check is permitted in place of the unarmed-strike attack roll,
    so the attacker uses the BETTER of the two — both derived through ``gear``
    (``ability_attack_bonus`` for the unarmed strike, ``skill_bonus`` for
    Athletics). Returns ``(bonus, source)``; ``source`` labels which won."""
    sheet = p["sheet"]
    attack = gear.ability_attack_bonus(sheet, "str")
    athl, prof = gear.skill_bonus(sheet, p["skills"], "athletics")
    if athl >= attack:
        return athl, ("athletics" if prof or athl == attack else "athletics")
    return attack, "unarmed"


def better_save(p, opts=("str", "dex")):
    """D&D 2024 lets the target CHOOSE which of these saves to attempt; the
    default that equals a player picking best is the highest save bonus.
    A save the token auto-fails is never chosen if another option exists."""
    opts = [a for a in opts if a in ABILITIES]
    conds, room_id = p["conds"], p["room_id"]
    clean = [a for a in opts if not CND.auto_fails_save(conds, room_id, a)]
    pool = clean or opts
    return max(pool, key=lambda a: gear.save_bonus(p["sheet"], p["saves"], a))


# ---------------------------------------------------------------------------
# the three comparison shapes. Pure; no rolls, no side effects.
# ---------------------------------------------------------------------------

def opposed_wins(att_total, def_total, tie="defender"):
    """True when the attacker wins a contested pair. ``tie`` (``'defender'`` |
    ``'attacker'`` | ``'dm'``) resolves an exact tie; ``'dm'`` defers by raising
    ``Tie`` so the caller can hand the call to the DM."""
    if att_total == def_total and tie == "dm":
        raise Tie(att_total, def_total)
    if att_total == def_total:
        return tie == "attacker"
    return att_total > def_total


class Tie(Exception):
    """Raised by ``opposed_wins`` on a tie the caller asked the DM to break."""


def beats_dc(total, dc):
    """A check/save result meets or exceeds a DC (a d20 tie goes to the
    defender: the roller must STRICTLY clear or equal the DC, matching how the
    existing save/attack paths read ``total >= dc``)."""
    return total >= dc
