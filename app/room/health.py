"""HP, temporary HP, typed damage and death-state transitions."""
from .. import db, gear, npc
from . import death as D
from .net import broadcast


def _int(v, d=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return d


def _clamp(v, lo, hi, d):
    return max(lo, min(hi, _int(v, d)))


def _json(v, d):
    return db.j(v, d) if isinstance(v, str) else (v if v is not None else d)


def _defenses(value):
    return gear.clean_defenses(_json(value, {}))


def _token_defenses(tok):
    block = npc.load(tok) if tok else None
    return gear.clean_defenses((block or {}).get("defenses"))


def _death_note(death):
    if not death:
        return ""
    if death["dead"]:
        return " — ☠ DEAD"
    if death["stable"]:
        return f" — stable ({death['s']}✓/{death['f']}✗)"
    return f" — dying ({death['s']}✓/{death['f']}✗)"


async def change_hp(room_id, tok, delta, *, crit=False, damage_type=None, broadcast_change=True):
    """Apply a signed HP change to a PC token or NPC block.

    Negative values are damage. ``damage_type`` makes defensive reduction explicit;
    when it is omitted, existing generic/manual HP behavior is preserved.
    """
    if tok is None:
        return None
    try:
        delta = max(-9999, min(9999, int(delta)))
    except (TypeError, ValueError):
        return None

    if tok.get("character_id") is None:
        block = npc.load(tok)
        if block is None:
            return None
        prev = _clamp(block.get("hp", 0), 0, _clamp(block.get("max_hp", 10), 1, 9999, 10), 0)
        max_hp = _clamp(block.get("max_hp", prev or 10), 1, 9999, 10)
        damage = 0
        healed = 0
        if delta < 0:
            damage = gear.apply_defense(abs(delta), damage_type, _token_defenses(tok))
            hp = max(0, prev - damage)
        elif delta > 0:
            hp = min(max_hp, prev + delta)
            healed = hp - prev
        else:
            hp = prev
        block["hp"] = hp
        db.x("UPDATE tokens SET npc=? WHERE id=?", (db.json_dumps(block), tok["id"]))
        if broadcast_change and hp != prev:
            await broadcast(room_id, "snapshot", None)
        return {"kind": "npc", "name": tok.get("label", "NPC"), "hp": hp, "max_hp": max_hp,
                "temp_hp": 0, "death": None, "damage": damage, "healed": healed,
                "changed": hp != prev, "immune": bool(damage_type) and delta < 0 and damage == 0}

    ch = gear.as_sheet(db.q1("SELECT * FROM characters WHERE id=?", (tok["character_id"],)))
    if ch is None:
        return None
    prev = _clamp(ch.get("hp", 0), -9999, 9999, 0)
    max_hp = max(1, _clamp(ch.get("max_hp", 10), 1, 9999, 10))
    temp = max(0, _clamp(ch.get("temp_hp", 0), 0, 9999, 0))
    damage = 0
    healed = 0
    death = D.load(tok)

    if delta < 0:
        raw = abs(delta)
        damage = gear.apply_defense(raw, damage_type, _defenses(ch.get("defenses")))
        absorbed = min(temp, damage)
        temp -= absorbed
        remaining = damage - absorbed
        hp = max(0, prev - remaining)
        db.x("UPDATE characters SET hp=?, temp_hp=? WHERE id=?", (hp, temp, ch["id"]))
        changed = hp != prev or temp != max(0, _clamp(ch.get("temp_hp", 0), 0, 9999, 0))

        if hp <= 0:
            if death is None or prev > 0 or (death.get("stable") and not death.get("dead")):
                death = D.new()
            if prev <= 0 and damage > 0:
                death["f"] = min(3, death["f"] + (2 if crit else 1))
            if damage >= max_hp:
                death["dead"] = True
                death["f"] = 3
            D.apply_thresholds(death)
            db.x("UPDATE tokens SET death=? WHERE id=?", (db.json_dumps(death), tok["id"]))
            changed = True
        elif death is not None:
            death = None
            db.x("UPDATE tokens SET death=NULL WHERE id=?", (tok["id"],))
            changed = True

        if broadcast_change and changed:
            await broadcast(room_id, "snapshot", None)
        return {"kind": "char", "name": ch["name"], "hp": hp, "max_hp": max_hp, "temp_hp": temp,
                "death": death, "damage": damage, "healed": 0, "changed": changed,
                "note": _death_note(death), "immune": bool(damage_type) and damage == 0}

    if delta > 0:
        hp = min(max_hp, prev + delta)
        healed = hp - prev
        db.x("UPDATE characters SET hp=?, temp_hp=? WHERE id=?", (hp, temp, ch["id"]))
        changed = hp != prev
        if hp > 0 and death is not None:
            death = None
            db.x("UPDATE tokens SET death=NULL WHERE id=?", (tok["id"],))
            changed = True
        if broadcast_change and changed:
            await broadcast(room_id, "snapshot", None)
        return {"kind": "char", "name": ch["name"], "hp": hp, "max_hp": max_hp, "temp_hp": temp,
                "death": death, "damage": 0, "healed": healed, "changed": changed,
                "note": _death_note(death), "immune": False}

    return {"kind": "char", "name": ch["name"], "hp": prev, "max_hp": max_hp, "temp_hp": temp,
            "death": death, "damage": 0, "healed": 0, "changed": False,
            "note": _death_note(death), "immune": False}


async def heal(room_id, tok, amount, *, broadcast_change=True):
    return await change_hp(room_id, tok, abs(int(amount or 0)), broadcast_change=broadcast_change)


async def damage(room_id, tok, amount, *, crit=False, damage_type=None, broadcast_change=True):
    return await change_hp(room_id, tok, -abs(int(amount or 0)), crit=crit,
                           damage_type=damage_type, broadcast_change=broadcast_change)
