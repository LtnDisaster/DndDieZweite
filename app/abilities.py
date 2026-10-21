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
_BONUS_RE = re.compile(r"^([+-]?)(\d{1,3})d(\d{1,3})$", re.I)      # +1d6 / -2d8 / 1d6
_TIER_RE = re.compile(r"^(\d{1,3}):\s*([+-]?\d{1,3}d\d{1,3})$", re.I)


def _dice_bonus(v):
    """Parse a bonus-dice string ('+1d6' / '1d6' / '-2d8') to (signed_count, sides).
    Returns (0, 0) when it is not a clean dice term."""
    m = _BONUS_RE.match(str(v or "").strip().lower())
    if not m:
        return (0, 0)
    sign = -1 if m.group(1) == "-" else 1
    return (sign * int(m.group(2)), int(m.group(3)))


_REGISTRY: dict = {}


def _scoped_key(room_id, aid):
    # D163-1: per-room registration. Content is already room-scoped in the DB
    # (PK kind,room_id,id) — the registry used to collapse every room's ids into
    # one bare key, so a later import in room B silently re-defined room A's
    # live spells. Room rows now additionally register under "<room>::<id>".
    return f"{int(room_id)}::{aid}"


def register(raw, room_id=0):
    """Validate and register an ability definition. Returns the clean dict or None.

    D163-1: with a non-zero room_id the definition ALSO registers under the
    room-scoped key. The bare key keeps its legacy meaning (last writer wins,
    global/manual definitions) so out-of-room callers and tests keep working."""
    defn = clean_definition(raw)
    if defn is not None:
        rid = int(room_id or 0)
        _REGISTRY[_scoped_key(rid, defn["id"])] = defn
        if rid == 0:
            # bare lane = manual/global definitions only; live room resolution
            # never consults it, so a room import can no longer clobber another
            # room (the pre-D163 bug) and cannot pollute the global lane either.
            _REGISTRY[defn["id"]] = defn
    return defn


def unregister(ability_id, room_id=0):
    aid = str(ability_id)
    rid = int(room_id or 0)
    _REGISTRY.pop(_scoped_key(rid, aid), None)
    if rid == 0:
        _REGISTRY.pop(aid, None)


def get(ability_id, room_id=0):
    """Resolve an ability. Live lookup (non-zero room) checks the room's own
    definition first, then the GLOBAL lane (room 0 / manual registrations);
    it never falls back to the bare legacy key. A room-less get() reads the
    bare lane (tests, tooling). D163-1."""
    aid = str(ability_id)
    rid = int(room_id or 0)
    if rid:
        d = _REGISTRY.get(_scoped_key(rid, aid))
        if d is None:
            d = _REGISTRY.get(_scoped_key(0, aid))
        return d
    return _REGISTRY.get(aid)


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
        # D97 scaling (data-driven, generic): base slot level + an upcast step
        # (dice added per slot level above base) + cantrip tier table (dice added
        # by character level). Dice are folded into the ONE base dice term, so the
        # step/tier die must share the base die's sides (else it is not applied).
        "base_level": _clampi(raw.get("base_level", 0), 0, 9, 0),
        "upcast_step": "", "upcast_scaling": False, "scale_tiers": [],
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
    # scaling metadata (D97) — validated, invalid pieces drop out (fail-safe: no scaling)
    step = str(raw.get("upcast_step", "") or "").strip().lower()
    if step:
        cnt, sides = _dice_bonus(step)
        if cnt > 0:
            out["upcast_step"] = f"{cnt}d{sides}"
            out["upcast_scaling"] = bool(raw.get("upcast_scaling"))
    tiers = []
    st = raw.get("scale_tiers")
    if isinstance(st, (list, tuple)):                 # already normalised (idempotent re-clean)
        for pair in st:
            try:
                thr, ds = pair
                thr = int(thr)
            except (TypeError, ValueError):
                continue
            cnt, dsides = _dice_bonus(ds)
            if cnt > 0:
                tiers.append((max(0, thr), f"{cnt}d{dsides}"))
    else:
        for part in re.split(r"[,;]+", str(st or "")):
            m = _TIER_RE.match(part.strip())
            if m:
                cnt, sides = _dice_bonus(m.group(2))
                if cnt > 0:
                    tiers.append((max(0, int(m.group(1))), f"{cnt}d{sides}"))
    out["scale_tiers"] = sorted(tiers)
    ops = raw.get("ops")
    if isinstance(ops, (list, tuple)) and ops:
        # D111: a definition may carry the generic op list — validated, and
        # re-validation of an already-normalised list is byte-idempotent.
        from . import effectops
        try:
            out["ops"] = effectops.validate(list(ops))
        except effectops.EffectError:
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


class _CastRejected(Exception):
    """Signal that a cast's cost could not be paid so the surrounding transaction
    (including a just-inserted op_id claim) rolls back — a genuine retry with the
    same op_id must not be swallowed by a failed first attempt."""


def _consume_cost(c, room_id, tok, defn, cast_level):
    """Return (ok, error, consumed_desc). EVERY read+write happens on the caller's
    open transaction ``c`` (a BEGIN IMMEDIATE tx), so the "slots left?" check and
    the increment share one write lock: two concurrent casts cannot both pass the
    check and lose an increment (D100 / G7 — mirrors the single-tx legacy cast
    path in room.dice). Mutates only on success."""
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
        if tok["character_id"]:
            ch = c.execute("SELECT id, spell_slots, spells FROM characters WHERE id=?",
                           (tok["character_id"],)).fetchone()
            if ch is None:
                return False, "Caster gone", None
            # D163-7: the prepared-caster gate rides the ABILITY pipeline too —
            # class spells live in characters.abilities, so their sheet button is
            # an ability_cast; without this check the daily list (spell_prepare)
            # would be decorative for exactly the CSV built casters it exists
            # for. Same rule as the legacy cast path (room.dice, D138): a
            # prep-gated list casts only what the player prepared today. The
            # read rides the SAME tx as the slot increment — no race window.
            ent = next((x for x in gear.clean_spells(db.j(ch["spells"], []) or [])
                        if x.get("id") == defn["id"] and x.get("prep")), None)
            if ent is not None and not ent.get("prepared"):
                return False, f"{ent.get('name') or defn['id']} is not prepared", None
            slots = gear.clean_slots(db.j(ch["spell_slots"], {}))
            holder = ("char", ch["id"])
        else:
            row = c.execute("SELECT npc FROM tokens WHERE id=?", (tok["id"],)).fetchone()
            block = db.j(row["npc"], {}) if row else None
            if not isinstance(block, dict):
                return False, "Caster gone", None
            slots = gear.clean_slots(block.get("spell_slots", {}))
            holder = ("npc", tok["id"])
        s = slots.get(lvl, {"max": 0, "used": 0})
        if s["used"] >= s["max"]:
            return False, f"No {lvl}-level spell slots left", None
        s["used"] += 1
        _save_slots(c, holder, slots)
        return True, None, {"type": "spell_slot", "level": lvl}
    # generic resource (ki-like, charges, rage, …)
    rid = cost["id"]
    if tok["character_id"]:
        ch = c.execute("SELECT id, resources FROM characters WHERE id=?",
                       (tok["character_id"],)).fetchone()
        if ch is None:
            return False, "Caster gone", None
        resources = gear.clean_resources(db.j(ch["resources"], []))
        target = next((r for r in resources if r["id"] == rid), None)
        if target is None:
            return False, "Resource not found", None
        if target["current"] < 1:
            return False, "Resource exhausted", None
        target["current"] -= 1
        c.execute("UPDATE characters SET resources=? WHERE id=?",
                  (db.json_dumps(resources), ch["id"]))
        return True, None, {"type": "resource", "id": rid}
    row = c.execute("SELECT npc FROM tokens WHERE id=?", (tok["id"],)).fetchone()
    block = db.j(row["npc"], {}) if row else None
    if not isinstance(block, dict):
        return False, "Caster gone", None
    resources = gear.clean_resources(block.get("resources", []))
    target = next((r for r in resources if r["id"] == rid), None)
    if target is None or target["current"] < 1:
        return False, "Resource not found or exhausted", None
    target["current"] -= 1
    block["resources"] = resources
    c.execute("UPDATE tokens SET npc=? WHERE id=?", (db.json_dumps(block), tok["id"]))
    return True, None, {"type": "resource", "id": rid}


def _save_slots(c, holder, slots):
    """Persist a slot ledger through the caller's transaction ``c``. The NPC row is
    RE-read inside the tx (never the pre-fetched token) so the increment rides the
    freshest committed value under the write lock."""
    kind, ident = holder
    if kind == "char":
        c.execute("UPDATE characters SET spell_slots=? WHERE id=?",
                  (db.json_dumps(slots), ident))
    else:
        tok = c.execute("SELECT npc FROM tokens WHERE id=?", (ident,)).fetchone()
        block = db.j(tok["npc"], {}) if tok else {}
        block["spell_slots"] = slots
        c.execute("UPDATE tokens SET npc=? WHERE id=?", (db.json_dumps(block), ident))


def _cast_gate(room_id, tok, defn, cast_level, op_id):
    """Claim the op_id (if any) and pay the cost in ONE BEGIN IMMEDIATE tx so the
    slot/resource check is race-free. Returns (status, err, consumed) with status
    in {"replayed", "fail", "ok"}. A refused cost rolls the tx back — including the
    op_id claim — so a genuine retry is never swallowed."""
    from . import inventory as INV
    with db.tx() as c:
        if op_id and not INV._claim(c, str(op_id)[:40], room_id, "ability_cast", tok["id"]):
            return "replayed", None, None
        ok, err, consumed = _consume_cost(c, room_id, tok, defn, cast_level)
        if not ok:
            raise _CastRejected(err)
        return "ok", None, consumed


def _roll_expr(expr, adv=None):
    from .room import dice
    return dice.do_roll(expr, adv)


# ---------------- authoritative execution ----------------

async def execute(room_id, *, actor_token_id, ability_id, is_dm=False, actor_user_id=None,
                  target_id=None, point=None, direction="E", cast_level=None,
                  adv=None, user=None, op_id=None):
    """The ONE ability operation (D55/D60). Validates EVERYTHING server-side,
    applies effects through the existing authoritative subsystems, returns a plain
    result dict (``{"ok": False, "error": ...}`` on refusal, nothing applied).
    ``user`` (dict or None) enables the chronicle posting; transport is never required.
    ``op_id`` (D93/D97): when present it is claimed up-front inside the write
    transaction, so a duplicate request consumes NOTHING and applies no effect —
    the whole cast is idempotent against a repeated ``op_id``."""
    from .room import gamelog, health, net

    defn = get(ability_id, room_id)             # D163-1: the room's own definition wins
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
    from . import progression
    char_level = progression.total_character_level(actor_sheet)
    if defn["cost"] is not None:
        # D100/G7: claim + pay atomically in one tx so concurrent casts of the same
        # caster cannot both pass a slot/resource check and lose an increment.
        try:
            status, err, consumed = _cast_gate(room_id, tok, defn, cast_level, op_id)
        except _CastRejected as ex:
            return _fail(str(ex))
        if status == "replayed":
            return {"ok": True, "replayed": True}          # duplicate op_id: no slot, no effect
        if status == "fail":
            return _fail(err)
    else:
        # Zero-cost (e.g. a cantrip): no counter to race, but still honour the
        # op_id replay guard so a duplicate no-effect cast stays idempotent.
        if op_id:
            from . import inventory as INV
            with db.tx() as c:
                if not INV._claim(c, str(op_id)[:40], room_id, "ability_cast", tok["id"]):
                    return {"ok": True, "replayed": True}
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
    ops = defn.get("ops") or []
    if defn["concentration"]:
        # D113 (2024): casting a new concentration ENDS the previous one — run it
        # BEFORE this spell's own effects, so the old concentration's linked
        # conditions are cleared first and the fresh ones (stamped below with
        # this caster's conc id) survive the clear.
        from .room import concentration as _conc
        await _conc.end_previous(room_id, tok)
    for t in targets:
        entry = {"token_id": t["id"], "label": t["label"]}
        sheet, saves = _sheet_and_saves(t)
        apply = True
        if sheet is not None and defn["resolution"] == "save" and t["id"] != tok["id"]:
            conds = C.load(t)
            if C.auto_fails_save(conds, room_id, defn["save"]):
                entry["save"] = {"ability": defn["save"], "roll": 0, "mod": 0, "total": 0,
                                 "success": False, "auto_fail": True}
            else:
                dis = "dis" if C.hook_bool(conds, room_id, "my_saves_dis") else None
                roll = _roll_expr("1d20", dis)
                mod = gear.save_bonus(sheet, saves, defn["save"])
                total = roll["kept"] + mod
                success = total >= dc
                entry["save"] = {"ability": defn["save"], "roll": roll["kept"], "mod": mod,
                                 "total": total, "success": success}
            if entry["save"]["success"] and defn["on_save"] == "negate":
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
        if ops:
            # D111: the generic op list runs INSIDE this one shell — same
            # targeting, range, LOS, DC resolution, cost gate and chronicle.
            # The fixed blocks below are the pre-D111 fast lane and stay
            # byte-identical for every definition without an op list.
            from . import effectops
            if apply:
                ctx = effectops.make_ctx(room_id, caster=tok, target=t,
                                         trigger="cast",
                                         conc=(tok["id"] if defn["concentration"] else None))
                ctx["self"], ctx["dc"] = tok, dc
                try:
                    await effectops.run_ops(ops, ctx)
                except effectops.EffectError as ex:
                    return _fail(f"Effect refused: {ex}")
                if ctx.get("replayed"):
                    return {"ok": True, "replayed": True}
                entry["ops"] = ctx["log"]
                changed = changed or ctx["changed"]
                for bump in ctx["cond_bumps"]:
                    cond_bumps.append({"tok": bump, "conds": db.j(bump["conds"], [])})
            entry["applied"] = apply
        else:
            if apply and defn["damage"] and sheet is not None:
                expr = _scaled_expr(defn, defn["damage"], cast_level, char_level)
                if entry.get("attack", {}).get("crit"):
                    expr = _crit_expr(expr)
                res = _roll_expr(expr)
                damage = res["total"]
                if entry.get("save", {}).get("success") and defn["on_save"] == "half":
                    damage //= 2                           # floor BEFORE defense (documented)
                r = await health.change_hp(room_id, t, -damage, damage_type=dtype,
                                           broadcast_change=False)
                if r:
                    entry["damage"] = r["damage"]          # POST-resistance/immunity amount
                    entry["immune"] = r.get("immune", False)
                    changed = changed or r.get("changed", False)
            if apply and defn["heal"] and sheet is not None:
                res = _roll_expr(defn["heal"])
                r = await health.change_hp(room_id, t, res["total"], broadcast_change=False)
                if r:
                    heal = entry["heal"] = r["healed"]
                    changed = changed or r.get("changed", False)
            if apply and defn["condition"] and C.immune(t, defn["condition"]["key"]):
                entry["condition_immune"] = defn["condition"]["key"]
            elif apply and defn["condition"]:
                conds = C.add(C.load(t), defn["condition"]["key"],
                              defn["condition"]["rounds"],
                              conc=(tok["id"] if defn["concentration"] else None))
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
                     f"{'— saved' if e['save']['success'] else '— failed'}"
                     + (" (auto-fail)" if e["save"].get("auto_fail") else ""))
            elif e.get("attack"):
                b = (f"{e['label']}: {'HIT' if e['attack']['hit'] else 'MISS'}"
                     f"{' (crit!)' if e['attack']['crit'] else ''}")
            if e.get("damage"):
                b += f" → {e['damage']} {dtype or ''} dmg".rstrip()
            if e.get("heal"):
                b += f" → +{e['heal']} HP"
            if e.get("condition"):
                b += f" → {e['condition']}"
            if e.get("ops"):                               # D111: op-chain outcome
                b = ((b + " → ") if b else "") + "; ".join(e["ops"])
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


_BASE_RE = re.compile(r"^(\d{1,3})d(\d{1,3})((?:[+-]\d{1,3})?)$", re.I)


def _scaled_expr(defn, base, cast_level, char_level):
    """Raise the BASE dice count from upcast (slot levels above base) or a cantrip
    tier table (by character level). The added dice must share the base die's sides,
    else nothing changes (a cross-die step is left to the DM, never faked — D97)."""
    m = _BASE_RE.match(str(base or "").strip().lower())
    if not m:
        return base
    n, sides, tail = int(m.group(1)), int(m.group(2)), m.group(3)
    add = 0
    cost = defn.get("cost") or {}
    if defn.get("upcast_scaling") and defn.get("upcast_step") and cost.get("type") == "spell_slot":
        try:
            cl = int(cast_level) if cast_level is not None else 0
        except (TypeError, ValueError):
            cl = 0
        delta = cl - int(defn.get("base_level") or cost.get("level") or 0)
        if delta > 0:
            cnt, dsides = _dice_bonus(defn["upcast_step"])
            if dsides == sides:
                add += cnt * delta
    if defn.get("scale_tiers") and not cost.get("type"):        # cantrip-only
        try:
            lvl = int(char_level or 0)
        except (TypeError, ValueError):
            lvl = 0
        for thr, ds in defn["scale_tiers"]:
            if lvl >= thr:
                cnt, dsides = _dice_bonus(ds)
                if dsides == sides:
                    add += cnt
    if add <= 0:
        return base
    return f"{min(200, n + add)}d{sides}{tail}"


def _fail(msg):
    return {"ok": False, "error": msg}
