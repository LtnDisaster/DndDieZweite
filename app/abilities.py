"""Generic ability engine: definitions are DATA, resolution is one authoritative executor.

An ability is a plain dict (registered server-side, never trusted from a client):
which casting ability score powers it, its range/targeting/geometry, resolution
(auto | save | attack), its generic effects (damage/heal/condition), an optional
resource cost and an optional concentration requirement. Spells, class features,
monster actions and traps are meant to be *rows of this shape* — no per-named-
ability code paths (D55). The executor deliberately owns ONLY orchestration:

  range/LOS/targeting  -> los.py, footprint.py, effects.py        (existing)
  modifiers/DC/attack  -> gear.stat_mod / ability_save_dc / ability_attack_bonus
  dice                 -> room.dice.do_roll                        (existing)
  damage/heal          -> room.health.change_hp (resistances, temp HP, death) (existing)
  conditions           -> app.conditions                            (existing)
  concentration state  -> the "concentrating" condition flag        (existing)
  slots / resources    -> characters.spell_slots / .resources       (existing)

Rounding conventions follow the existing pipeline: save-half damage is floored
BEFORE resistance/immunity, exactly like ``gear.apply_defense`` floors resistance.
Core execution takes a room id and plain values only — never a WebSocket object —
so WS handlers, future triggers and the AI DM all call the same operation (D60).
"""
import re

from . import db, effects, events, footprint, gear, mapmodel, npc, ws
from . import conditions as C

ABILITIES = gear.ABILITIES
TARGETINGS = ("self", "single", "point", "area")
RESOLUTIONS = ("auto", "save", "attack")
ON_SAVE = ("none", "half", "negate")
CELL = 5                                      # grid convention: 1 cell == 5 ft
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
_DICE_RE = re.compile(r"^\d{1,3}d\d{1,3}([+-]\d{1,3})?$", re.I)

_REGISTRY: dict = {}


def register(raw):
    """Validate and register an ability definition. Returns the clean dict or None."""
    defn = clean_definition(raw)
    if defn is not None:
        _REGISTRY[defn["id"]] = defn
    return defn


def unregister(ability_id):
    _REGISTRY.pop(str(ability_id), None)


def get(ability_id):
    return _REGISTRY.get(str(ability_id))


def registry():
    return list(_REGISTRY.values())


def clear_registry():
    _REGISTRY.clear()


def clean_definition(raw):
    """Validate one ability definition. Any invalid definition → None (whole reject)."""
    if not isinstance(raw, dict):
        return None
    aid = str(raw.get("id", "")).strip().lower()
    if not _ID_RE.match(aid):
        return None
    name = str(raw.get("name", "")).strip()[:48]
    if not name:
        return None
    ability = str(raw.get("ability", "int")).lower()
    if ability not in ABILITIES:
        return None
    try:
        range_ft = int(raw.get("range_ft", 0))
    except (TypeError, ValueError):
        return None
    if not 0 <= range_ft <= 600:
        return None
    targeting = str(raw.get("targeting", "single")).lower()
    if targeting not in TARGETINGS:
        return None
    resolution = str(raw.get("resolution", "auto")).lower()
    if resolution not in RESOLUTIONS:
        return None
    on_save = str(raw.get("on_save", "none")).lower()
    if on_save not in ON_SAVE:
        return None
    save = str(raw.get("save", "")).lower()
    if resolution == "save" and save not in ABILITIES:
        return None
    out = {
        "id": aid, "name": name, "ability": ability, "range_ft": range_ft,
        "targeting": targeting, "resolution": resolution, "save": save,
        "on_save": on_save, "los_required": bool(raw.get("los_required", True)),
        "concentration": bool(raw.get("concentration", False)),
        "bonus": _clampi(raw.get("bonus", 0), -20, 20, 0),
        "shape": "", "size_ft": 0, "damage": "", "damage_type": "",
        "heal": "", "condition": None, "cost": None,
    }
    if targeting == "area":
        shape = str(raw.get("shape", "")).lower()
        if shape not in effects.SHAPES:
            return None
        try:
            size = int(raw.get("size_ft", 5))
        except (TypeError, ValueError):
            return None
        if not 5 <= size <= 600:
            return None
        out["shape"], out["size_ft"] = shape, size
    for key in ("damage", "heal"):
        expr = str(raw.get(key, "")).strip().lower()
        if expr and not _DICE_RE.match(expr):
            return None
        out[key] = expr
    if out["damage"]:
        dtype = str(raw.get("damage_type", "")).strip().lower()
        if dtype not in gear.DAMAGE_TYPES:
            return None                                  # typed damage only — SSOT list
        out["damage_type"] = dtype
    cond = raw.get("condition")
    if isinstance(cond, dict) and str(cond.get("key", "")).strip():
        out["condition"] = {"key": str(cond["key"]).strip()[:24],
                            "rounds": _clampi(cond.get("rounds", 0), 0, 999, 0)}
    cost = raw.get("cost")
    if isinstance(cost, dict):
        ctype = str(cost.get("type", "")).lower()
        if ctype == "spell_slot":
            out["cost"] = {"type": "spell_slot", "level": _clampi(cost.get("level", 1), 1, 9, 1)}
        elif ctype == "resource":
            rid = str(cost.get("id", "")).strip()[:24]
            if rid:
                out["cost"] = {"type": "resource", "id": rid}
        else:
            return None
    return out


def _clampi(v, lo, hi, dflt=0):
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return dflt


# ---------------- targeting helpers (pure, unit-testable) ----------------

def origin_cell(mp, tok):
    return footprint.origin_from_pixel(tok["x"], tok["y"], mp["cell"])


def grid_distance(a, b):
    """Chebyshev cell distance — the project's range metric (diagonal = one move)."""
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def in_range(defn, from_cell, to_cell):
    if defn["targeting"] == "self":
        return True
    if defn["range_ft"] == 0:                            # touch: same/adjacent cell
        return grid_distance(from_cell, to_cell) <= 1
    return grid_distance(from_cell, to_cell) * CELL <= defn["range_ft"]


def target_cells(defn, mp, point, direction="E"):
    """Cells an ability aims at (anchor cell first in the list is NOT guaranteed —
    use defn['targeting'] to know semantics). Empty list = invalid geometry.
    WORLD in, WORLD tuples or flat STORAGE indices out (tokens_in_cells
    normalizes). effects.py is space-free grid maths, so the anchor is shifted
    into the map's STORAGE space (D72) and the flat results stay storage-based."""
    w, h = mp["w"], mp["h"]
    ox, oy = mapmodel.origin_of(mp)
    x, y = point
    if not mapmodel.in_world(mp, x, y):
        return []
    if defn["targeting"] == "area":
        return effects.effect_cells(defn["shape"], defn["size_ft"], x - ox, y - oy, w, h, direction)
    return [(x, y)]


def tokens_in_cells(mp, room_id, cells, exclude_id=None, floor=None):
    """Tokens with ANY occupied footprint cell inside ``cells`` — the centralized
    footprint-aware targeting rule (a 1-cell overlap is enough; D61).
    ``cells`` accepts WORLD ``(x, y)`` pairs or flat STORAGE ``y*w+x`` indices
    (effects.py returns indices, footprint.py returns pairs — normalize once
    HERE; flat indices are converted through mapmodel, D72).
    SPRINT-20 / D86: with a floor given, tokens on OTHER planes are not even
    candidates — a fireball on the tavern floor never cooks the crypt; a
    cross-plane token is ELSEWHERE, so it is not hit and not counted."""
    w = mp["w"]
    hit = {c if isinstance(c, tuple) else mapmodel.world_of(mp, c % w, c // w) for c in cells}
    out = []
    for tok in db.q("SELECT * FROM tokens WHERE room_id=?", (room_id,)):
        if exclude_id is not None and tok["id"] == exclude_id:
            continue
        if floor is not None and (tok.get("floor") or "") != (floor or ""):
            continue
        if any(c in hit for c in footprint.occupied_cells(mp, tok)):
            out.append(tok)
    return out


def _sheet_and_saves(tok):
    """(sheet-dict, saves-dict) for gear helpers, PC or NPC token."""
    if tok["character_id"]:
        ch = db.q1("SELECT * FROM characters WHERE id=?", (tok["character_id"],))
        if ch is None:
            return None, {}
        ch["stats"] = db.j(ch.get("stats"), {}) or {}
        return ch, gear.clean_saves(db.j(ch.get("saves"), {}))
    block = npc.load(tok)
    if block is None:
        return None, {}
    sheet = npc.to_char(block, tok["label"])
    sheet["level"] = block.get("level", 1)
    return sheet, gear.clean_saves(block.get("saves", {}))


def target_ac(room_id, tok):
    """Effective AC of a target token (character computes via gear, NPC from block)."""
    if tok["character_id"]:
        ch = db.q1("SELECT * FROM characters WHERE id=?", (tok["character_id"],))
        if ch is None:
            return None
        ch["items"] = db.j(ch.get("items"), []) or []
        ch["stats"] = db.j(ch.get("stats"), {}) or {}
        return gear.compute_ac(ch)
    block = npc.load(tok)
    return block.get("ac", 10) if block else None


def _rollable_by(defn, tok, is_dm):
    """Availability: DM may use anything registered; PCs need the id granted on the
    character; NPC blocks carry their own id list. Access model only — no prep rules."""
    if is_dm:
        return True
    if tok["character_id"]:
        ch = db.q1("SELECT abilities FROM characters WHERE id=?", (tok["character_id"],))
        return defn["id"] in (db.j(ch["abilities"], []) if ch else [])
    block = npc.load(tok)
    return defn["id"] in ((block or {}).get("abilities") or [])


def _consume_cost(room_id, tok, defn, cast_level):
    """Return (ok, error, consumed_desc). Mutates only on success."""
    cost = defn["cost"]
    if not cost:
        return True, None, None
    if cost["type"] == "spell_slot":
        lvl = cost["level"]
        if cast_level is not None:                          # upcast extension point:
            try:                                            # consumes a HIGHER slot,
                cast_level = int(cast_level)                # no dice scaling today (D58)
            except (TypeError, ValueError):
                return False, "Invalid cast level", None
            if not 1 <= cast_level <= 9 or cast_level < lvl:
                return False, "Invalid cast level", None
            lvl = cast_level
        slots_holder = None
        if tok["character_id"]:
            ch = db.q1("SELECT id, spell_slots FROM characters WHERE id=?", (tok["character_id"],))
            if ch is None:
                return False, "Caster gone", None
            slots = gear.clean_slots(db.j(ch["spell_slots"], {}))
            slots_holder = ("char", ch["id"])
        else:
            block = npc.load(tok)
            if block is None:
                return False, "Caster gone", None
            slots = gear.clean_slots(block.get("spell_slots", {}))
            slots_holder = ("npc", tok["id"])
        s = slots.get(lvl, {"max": 0, "used": 0})
        if s["used"] >= s["max"]:
            return False, f"No {lvl}-level spell slots left", None
        s["used"] += 1
        _save_slots(slots_holder, slots)
        return True, None, {"type": "spell_slot", "level": lvl}
    # generic resource (ki-like, charges, rage, …)
    rid = cost["id"]
    if tok["character_id"]:
        ch = db.q1("SELECT id, resources FROM characters WHERE id=?", (tok["character_id"],))
        if ch is None:
            return False, "Caster gone", None
        resources = gear.clean_resources(db.j(ch["resources"], []))
        target = next((r for r in resources if r["id"] == rid), None)
        if target is None:
            return False, "Resource not found", None
        if target["current"] < 1:
            return False, "Resource exhausted", None
        target["current"] -= 1
        db.x("UPDATE characters SET resources=? WHERE id=?", (db.json_dumps(resources), ch["id"]))
        return True, None, {"type": "resource", "id": rid}
    block = npc.load(tok)
    if block is None:
        return False, "Caster gone", None
    resources = gear.clean_resources(block.get("resources", []))
    target = next((r for r in resources if r["id"] == rid), None)
    if target is None or target["current"] < 1:
        return False, "Resource not found or exhausted", None
    target["current"] -= 1
    block["resources"] = resources
    db.x("UPDATE tokens SET npc=? WHERE id=?", (db.json_dumps(block), tok["id"]))
    return True, None, {"type": "resource", "id": rid}


def _save_slots(holder, slots):
    kind, ident = holder
    if kind == "char":
        db.x("UPDATE characters SET spell_slots=? WHERE id=?", (db.json_dumps(slots), ident))
    else:
        tok = db.q1("SELECT npc FROM tokens WHERE id=?", (ident,))
        block = db.j(tok["npc"], {}) if tok else {}
        block["spell_slots"] = slots
        db.x("UPDATE tokens SET npc=? WHERE id=?", (db.json_dumps(block), ident))


def _roll_expr(expr, adv=None):
    from .room import dice
    return dice.do_roll(expr, adv)


# ---------------- authoritative execution ----------------

async def execute(room_id, *, actor_token_id, ability_id, is_dm=False, actor_user_id=None,
                  target_id=None, point=None, direction="E", cast_level=None,
                  adv=None, user=None):
    """The ONE ability operation (D55/D60). Validates EVERYTHING server-side,
    applies effects through the existing authoritative subsystems, returns a plain
    result dict (``{"ok": False, "error": ...}`` on refusal, nothing applied).
    ``user`` (dict or None) enables the chronicle posting; transport is never required."""
    from .room import gamelog, health, net

    defn = get(ability_id)
    if defn is None:
        return _fail("Unknown ability")
    tok = db.q1("SELECT * FROM tokens WHERE id=? AND room_id=?", (actor_token_id, room_id))
    if tok is None:
        return _fail("No such token in this room")
    actor_sheet, _ = _sheet_and_saves(tok)
    if actor_sheet is None:
        return _fail("Token has no usable stat block")
    if not _rollable_by(defn, tok, is_dm):
        return _fail("This caster does not have that ability")
    if defn["cost"] is not None:
        ok, err, consumed = _consume_cost(room_id, tok, defn, cast_level)
        if not ok:
            return _fail(err)
    else:
        consumed = None

    # SPRINT-20 (closes the limitation documented in D88): EVERYTHING about a
    # cast resolves on the CASTER's plane — its terrain, walls, doors, fog and
    # footprint frames. The map seam (net.get_map) is the one plane switch.
    fl = tok.get("floor") or ""
    mp = net.get_map(room_id, fl)
    from_cell = origin_cell(mp, tok)

    # --- resolve target / cells -------------------------------------------
    targets, cells, anchor = [], [], None
    if defn["targeting"] == "self":
        targets, cells, anchor = [tok], list(footprint.occupied_cells(mp, tok)), from_cell
    else:
        if defn["targeting"] == "single":
            tgt = db.q1("SELECT * FROM tokens WHERE id=? AND room_id=?",
                        (target_id, room_id))
            # SPRINT-20: a token on another plane is ELSEWHERE (D86) — refused
            # with the same message an unknown id gets, so the refusal never
            # becomes an oracle for "a token exists on some other plane".
            if tgt is None or (tgt.get("floor") or "") != fl:
                return _fail("No target token")
            anchor, cells = origin_cell(mp, tgt), list(footprint.occupied_cells(mp, tgt))
            targets = [tgt]
        else:                                            # point | area
            try:
                px, py = int(point[0]), int(point[1])
            except (TypeError, ValueError, KeyError, IndexError):
                return _fail("Point target required")
            if defn["targeting"] == "area" and str(direction).upper() not in effects.DIRV:
                return _fail("Invalid direction")
            cells = target_cells(defn, mp, (px, py), str(direction or "E").upper())
            if not cells:
                return _fail("Target outside the map")
            anchor = (px, py)
            targets = tokens_in_cells(mp, room_id, cells, floor=fl)
        if not in_range(defn, from_cell, anchor):
            return _fail(f"Target out of range ({defn['range_ft']} ft)")
        if defn["los_required"]:
            blocked = mapmodel.blocked_edges(mp)
            if not los_ok(mp, from_cell, anchor, blocked):
                return _fail("Line of sight blocked")

    dc = None
    if defn["resolution"] in ("save", "attack"):
        dc = gear.ability_save_dc(actor_sheet, defn["ability"], defn["bonus"])

    entries, cond_bumps, changed = [], [], False
    for t in targets:
        entry = {"token_id": t["id"], "label": t["label"]}
        sheet, saves = _sheet_and_saves(t)
        apply = True
        if sheet is not None and defn["resolution"] == "save" and t["id"] != tok["id"]:
            roll = _roll_expr("1d20")
            mod = gear.save_bonus(sheet, saves, defn["save"])
            total = roll["kept"] + mod
            success = total >= dc
            entry["save"] = {"ability": defn["save"], "roll": roll["kept"], "mod": mod,
                             "total": total, "success": success}
            if success and defn["on_save"] == "negate":
                apply = False
        elif defn["resolution"] == "attack" and t["id"] != tok["id"]:
            roll = _roll_expr("1d20", adv if adv in ("adv", "dis") else None)
            bonus = gear.ability_attack_bonus(actor_sheet, defn["ability"], defn["bonus"])
            ac = target_ac(room_id, t)
            nat, total = roll["kept"], roll["kept"] + bonus
            crit = nat == 20
            hit = crit or (nat != 1 and ac is not None and total >= (ac or 99))
            entry["attack"] = {"roll": nat, "mod": bonus, "total": total,
                               "ac": ac, "hit": hit, "crit": crit}
            apply = hit                                    # crit doubles damage dice below
        damage = heal = 0
        dtype = defn["damage_type"] or None
        if apply and defn["damage"] and sheet is not None:
            expr = defn["damage"]
            if entry.get("attack", {}).get("crit"):
                expr = _crit_expr(expr)
            res = _roll_expr(expr)
            damage = res["total"]
            if entry.get("save", {}).get("success") and defn["on_save"] == "half":
                damage //= 2                               # floor BEFORE defense (documented)
            r = await health.change_hp(room_id, t, -damage, damage_type=dtype,
                                       broadcast_change=False)
            if r:
                entry["damage"] = r["damage"]              # POST-resistance/immunity amount
                entry["immune"] = r.get("immune", False)
                changed = changed or r.get("changed", False)
        if apply and defn["heal"] and sheet is not None:
            res = _roll_expr(defn["heal"])
            r = await health.change_hp(room_id, t, res["total"], broadcast_change=False)
            if r:
                heal = entry["heal"] = r["healed"]
                changed = changed or r.get("changed", False)
        if apply and defn["condition"]:
            conds = C.add(C.load(t), defn["condition"]["key"], defn["condition"]["rounds"])
            db.x("UPDATE tokens SET conds=? WHERE id=?", (db.json_dumps(conds), t["id"]))
            entry["condition"] = defn["condition"]["key"]
            cond_bumps.append({"tok": t, "conds": conds})
        entry["applied"] = apply and (damage > 0 or heal > 0 or "condition" in entry)
        entries.append(entry)

    if defn["concentration"]:                              # existing flag as state (D59)
        conds = C.add(C.load(tok), "concentrating", 0)
        db.x("UPDATE tokens SET conds=? WHERE id=?", (db.json_dumps(conds), tok["id"]))
        cond_bumps.append({"tok": tok, "conds": conds})

    # --- privacy + chronicle + events + broadcasts -------------------------
    if not is_dm and actor_user_id is not None:            # name only what actor can see
        visible = ws.viewer_visible_cells(room_id, actor_user_id, mp, floor=fl)
        for e in entries:
            t = db.q1("SELECT x, y FROM tokens WHERE id=?", (e["token_id"],))
            e["visible"] = (mapmodel.flat_idx(mp, origin_cell(mp, t)[0], origin_cell(mp, t)[1])
                            in visible) if t else False
    else:
        for e in entries:
            e["visible"] = True

    if user is not None:                                   # chronicle — never names hidden tokens
        hidden = sum(1 for e in entries if not e["visible"])
        named = [e["label"] for e in entries if e["visible"]]
        who = ", ".join(named) + (f" (+{hidden} hidden)" if hidden else "")
        bits = []
        for e in entries:
            b = ""
            if e.get("save"):
                b = (f"{e['label']}: {e['save']['ability'].upper()} save "
                     f"{e['save']['total']} vs DC {dc} "
                     f"{'— saved' if e['save']['success'] else '— failed'}")
            elif e.get("attack"):
                b = (f"{e['label']}: {'HIT' if e['attack']['hit'] else 'MISS'}"
                     f"{' (crit!)' if e['attack']['crit'] else ''}")
            if e.get("damage"):
                b += f" → {e['damage']} {dtype or ''} dmg".rstrip()
            if e.get("heal"):
                b += f" → +{e['heal']} HP"
            if e.get("condition"):
                b += f" → {e['condition']}"
            if b:
                bits.append(b)
        text = f"⚡ {tok['label']} — {defn['name']}" + (f" (DC {dc})" if dc else "") + \
               (f": {who}" if who else " — no targets") + \
               (f" | {'; '.join(bits)}" if bits else "")
        await gamelog.post_message(room_id, user, text, kind="system")

    for bump in cond_bumps:
        # SPRINT-20: never name a hidden token on a room-wide channel.
        from .room.visibility import send_cond_bump
        await send_cond_bump(room_id, bump["tok"], bump["conds"])
    if changed or cond_bumps or consumed:
        await net.broadcast(room_id, "snapshot", None)

    events.emit(events.make("ability_cast", room_id=room_id, actor_id=str(tok["id"]),
                            target_id=str(entries[0]["token_id"]) if entries else "",
                            data={"ability": defn["id"], "dc": dc,
                                  "affected": len(entries), "consumed": bool(consumed)}))
    return {"ok": True, "ability": defn, "dc": dc, "entries": entries,
            "hidden_count": sum(1 for e in entries if not e["visible"]),
            "consumed": consumed, "changed": changed or bool(cond_bumps)}


def los_ok(mp, source, target, blocked_edges):
    from . import los
    return los.line_of_sight(mp, source, target, blocked_edges=blocked_edges)


def _crit_expr(expr):
    try:
        n, rest = expr.split("d", 1)
        return f"{min(200, int(n) * 2)}d{rest}"
    except (TypeError, ValueError):
        return expr


def _fail(msg):
    return {"ok": False, "error": msg}
