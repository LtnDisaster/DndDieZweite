"""D111: the ONE effect grammar (Sprint 40).

A versioned, declarative operation list that later content (spells, items,
feats, condition definitions) carries in CSV cells — and that ONLY ever calls
the existing authoritative game operations (health, conditions, moveforced,
the resource ledger). There is no second combat/save/movement engine here and
there must never be one: every op below is a thin, validated adapter in front
of the operation a human at the table already triggers.

Grammar (v1/v2) — a cell is strict JSON, either ``{"v":2,"ops":[...]}`` (or the
legacy ``{"v":1,"ops":[...]}``) or a bare list (normalised as v1). Every list is
closed-world: an unknown op or field fails VALIDATION (the row is refused at
import), never execution. A cell with ``v`` outside ``V_MIN..V_MAX`` is refused.
v2 adds only the ``opposed`` op below; every v1 cell keeps validating unchanged.
Ops:

    damage   {expr, type?, target?}          -> room.health.change_hp(-)
    heal     {expr, target?}                 -> room.health.change_hp(+)
    temp_hp  {expr, target?}                 -> characters.temp_hp (no stacking)
    condition         {key, rounds?, until?, target?}
    condition_remove  {key, target?}         -> app.conditions add/remove (SSOT)
    break_concentration {target?}            -> removes the concentrating flag
    save     {ability, dc, success:[ops], failure:[ops]}
    check    {kind: check|save, ability, dc, success, failure}
    forced_move {kind: push|pull|slide, cells, from?}   -> room.moveforced
    resource {id, amount:1, mode?}         -> the existing resource ledger
    opposed {ability, tie?, success, failure}  (v2) -> room.opposed: subject's
               check vs the target's, same ability; tie -> defender|attacker|dm

Targets: "target" (the op's current target, default where damage-like) or
"self" (the carrier: caster for spells/feats, wielder for items). Branch
lists nest at most MAX_DEPTH below the root; the whole cell is bounded by
MAX_OPS (per list), MAX_NODES and MAX_CELL (see limits).

Triggers (equip/unequip/on_hit/on_damaged and the condition hooks on_start /
on_round / on_expire) never run through the event bus (events.py forbids
side-effecting listeners): thin seams call :func:`fire` inline at the exact
site the existing engine already committed its write. Guarded threefold —
trigger-fired effects fire NO further triggers (depth), one firing per
(token, trigger, key, round-uid) rides the ``inv_ops`` claim table, and a
per-token per-round op budget bounds any ping-pong.
"""
import json
import re

from . import db

V = 2                          # the CURRENT grammar version (what new cells author)
V_MIN, V_MAX = 1, 2            # every stored cell between these still validates
MAX_OPS = 8                    # ops per list (branches are separate lists)
MAX_DEPTH = 1                  # nesting levels below the root list (save/check)
MAX_NODES = 40                 # total JSON nodes in one cell (parse bomb guard)
MAX_CELL = 4000                # characters per CSV cell
MAX_CELLS_MOVE = 10
MAX_EXPR = re.compile(r"^\d{1,3}d\d{1,3}([+-]\d{1,3})?$", re.I)
ABILITIES = ("str", "dex", "con", "int", "wis", "cha")
DAMAGE_TYPES = ("slashing", "piercing", "bludgeoning", "fire", "cold", "lightning",
                "acid", "poison", "necrotic", "radiant", "psychic", "thunder",
                "force")
ON_SAVE = ("none", "half", "negate")
TARGETS = ("target", "self")
MOVE_KINDS = ("push", "pull", "slide")
TRIGGERS = ("use", "equip", "unequip", "on_hit", "on_damaged", "on_transfer")
COND_HOOKS = ("on_start", "on_round", "on_expire")
# D113: a hidden CURSE may arm any of the item triggers plus the owner-change
# event. An un-armed / de-activated curse fires NOTHING (see room/concentration
# discipline: an effect fires only where its definition explicitly says so).
CURSE_TRIGGERS = TRIGGERS
# raw keys that may legitimately NOT appear in the normalised op (the cleaner
# drops them when empty) — everything else not produced is refused.
_ALLOW = {"damage": {"type"}, "condition": {"rounds", "until"}}
COND_UNTIL = ("", "start", "end")
_KEY_RE = re.compile(r"^[\x20-\x7e]{1,24}$")
_DURATION_UNITS = {"round": 1, "minute": 10, "hour": 60, "day": 1440}
_DURATION_RE = re.compile(
    r"(?<!\d)(\d+)\s*(rounds?|minutes?|hours?|days?)(?![a-z])", re.I)


def duration_rounds(value):
    """Translate a SRD-style duration string to combat rounds for a condition.

    This is deliberately NOT a second duration engine. The existing condition
    lifecycle owns ``rounds``; this parser only converts a spell/item's declared
    duration into an initial number of rounds. Unknown/instant/permanent values
    return 0, which remains the existing indefinite/instant marker. A 999-round
    ceiling matches the condition rounds guard already enforced by the grammar.
    """
    text = str(value or "").strip().lower()
    if not text or "instant" in text or "permanent" in text:
        return 0
    total = 0
    for amount, unit in _DURATION_RE.findall(text):
        unit = unit[:-1] if unit.endswith("s") else unit
        try:
            total = max(total, int(amount) * _DURATION_UNITS[unit])
        except (TypeError, ValueError, KeyError):
            continue
    return max(0, min(999, total))


class EffectError(ValueError):
    """A definition that validation refuses — the import rejects the row."""


def _count(node):
    n = 1
    if isinstance(node, dict):
        for v in node.values():
            n += _count(v)
    elif isinstance(node, list):
        for v in node:
            n += _count(v)
    return n


def _req(op, field, types, default=None):
    v = op.get(field, default)
    if isinstance(v, bool) or not isinstance(v, types):
        raise EffectError(f"'{field}': expected {types}")
    return v


def _clean_expr(v, field):
    s = str(v or "").strip().lower()
    if not MAX_EXPR.match(s):
        raise EffectError(f"'{field}': invalid dice expression '{s[:24]}'")
    return s


def _clean_target(op, default="target"):
    t = str(op.get("target", default)).lower()
    if t not in TARGETS:
        raise EffectError(f"target must be one of {TARGETS}")
    return t


def _clean_ops(value, depth, allow_empty=False, ver=V, duration_rounds=0,
               preserve_duration=False):
    """Validate a (possibly nested) ops list; returns the normalised list."""
    if not isinstance(value, list):
        raise EffectError("ops must be a list")
    if not value and not allow_empty:
        raise EffectError("ops must be a non-empty list")
    if len(value) > MAX_OPS:
        raise EffectError(f"max {MAX_OPS} ops per list")
    if depth > MAX_DEPTH:
        raise EffectError("branches must not nest deeper")
    out = []
    for raw in value:
        if not isinstance(raw, dict) or "op" not in raw:
            raise EffectError("every op needs an 'op' field")
        kind = str(raw["op"]).lower()
        op = {"op": kind}
        if kind == "damage":
            op.update(expr=_clean_expr(_req(raw, "expr", str), "expr"),
                      target=_clean_target(raw))
            t = str(raw.get("type", "") or "").lower()
            if t:
                if t not in DAMAGE_TYPES:
                    raise EffectError(f"unknown damage type '{t}'")
                op["type"] = t
        elif kind in ("heal", "temp_hp"):
            op.update(expr=_clean_expr(_req(raw, "expr", str), "expr"),
                      target=_clean_target(raw, "self" if kind == "temp_hp" else "target"))
        elif kind in ("condition", "condition_remove"):
            key = str(_req(raw, "key", str)).strip()
            if not _KEY_RE.match(key):
                raise EffectError(f"invalid condition key '{key[:24]}'")
            op["key"] = key
            op["target"] = _clean_target(raw)
            if kind == "condition":
                raw_rounds = raw.get("rounds")
                wants_duration = (raw_rounds is None or (isinstance(raw_rounds, str)
                                                         and raw_rounds.strip().lower() == "duration"))
                if wants_duration and preserve_duration:
                    rounds = "duration"
                elif wants_duration:
                    rounds = max(0, min(999, int(duration_rounds or 0)))
                else:
                    try:
                        rounds = int(raw_rounds)
                    except (TypeError, ValueError):
                        raise EffectError("'rounds' must be an integer")
                    if not 0 <= rounds <= 999:
                        raise EffectError("'rounds' out of range 0..999")
                until = str(raw.get("until", "")).lower()
                if until not in COND_UNTIL:
                    raise EffectError("'until' must be '', 'start' or 'end'")
                op["rounds"], op["until"] = rounds, until
        elif kind == "break_concentration":
            op["target"] = _clean_target(raw, "self")
        elif kind in ("save", "check"):
            ab = str(_req(raw, "ability", str)).lower()
            if ab not in ABILITIES:
                raise EffectError(f"unknown ability '{ab}'")
            dc = raw.get("dc", "auto")
            if isinstance(dc, str) and dc.lower() == "auto":
                dc = "auto"
            else:
                try:
                    dc = int(dc)
                except (TypeError, ValueError):
                    raise EffectError("'dc' must be 'auto' or an integer")
                if not 0 <= dc <= 30:
                    raise EffectError("'dc' out of range 0..30")
            branches = {}
            for name in ("success", "failure"):
                if name not in raw:
                    raise EffectError(f"'{kind}' needs a '{name}' branch")
                branches[name] = _clean_ops(raw[name], depth + 1, allow_empty=True,
                                            ver=ver, duration_rounds=duration_rounds,
                                            preserve_duration=preserve_duration)
            op.update(ability=ab, dc=dc, **branches)
            if kind == "check":
                ck = str(raw.get("kind", "check")).lower()
                if ck not in ("check", "save"):
                    raise EffectError("check.kind must be 'check' or 'save'")
                op["kind"] = ck
            op["target"] = _clean_target(raw)
        elif kind == "forced_move":
            mk = str(_req(raw, "kind", str)).lower()
            if mk not in MOVE_KINDS:
                raise EffectError(f"forced_move kind must be one of {MOVE_KINDS}")
            try:
                cells = int(raw.get("cells", 1))
            except (TypeError, ValueError):
                raise EffectError("'cells' must be an integer")
            if not 1 <= cells <= MAX_CELLS_MOVE:
                raise EffectError(f"'cells' out of range 1..{MAX_CELLS_MOVE}")
            src = str(raw.get("from", "caster")).lower()
            if src not in ("caster", "self"):
                raise EffectError("'from' must be 'caster' or 'self'")
            op.update(kind=mk, cells=cells, target=_clean_target(raw), **{"from": src})
        elif kind == "resource":
            rid = str(_req(raw, "id", str)).strip().lower()[:24]
            if not rid or not re.match(r"^[a-z0-9_-]{1,24}$", rid):
                raise EffectError("resource id must be [a-z0-9_-]{1,24}")
            amount = raw.get("amount", 1)
            try:
                amount = int(amount)
            except (TypeError, ValueError):
                raise EffectError("'amount' must be an integer")
            if amount != 1:
                raise EffectError("v1 supports resource amount 1 only")
            mode = str(raw.get("mode", "cost")).lower()
            if mode not in ("cost", "restore"):
                raise EffectError("resource mode must be 'cost' or 'restore'")
            op.update(id=rid, amount=1, mode=mode, target=_clean_target(raw, "self"))
        elif kind == "opposed":
            if ver < 2:
                raise EffectError("'opposed' requires grammar v2")
            ab = str(_req(raw, "ability", str)).lower()
            if ab not in ABILITIES:
                raise EffectError(f"unknown ability '{ab}'")
            tie = str(raw.get("tie", "defender")).lower()
            if tie not in ("defender", "attacker", "dm"):
                raise EffectError("opposed 'tie' must be defender/attacker/dm")
            op.update(ability=ab, tie=tie, target=_clean_target(raw))
            for name in ("success", "failure"):
                if name not in raw:
                    raise EffectError(f"'opposed' needs a '{name}' branch")
                op[name] = _clean_ops(raw[name], depth + 1, allow_empty=True,
                                      ver=ver, duration_rounds=duration_rounds,
                                      preserve_duration=preserve_duration)
        else:
            raise EffectError(f"unknown op '{kind}'")
        # closed world: reject any key the cleaner above never produced
        allowed = _ALLOW.get(kind)
        leftovers = set(raw) - set(op) - (allowed or set())
        if leftovers:
            raise EffectError(f"unexpected fields: {sorted(leftovers)}")
        out.append(op)
    return out


def validate(value, duration_rounds=0, preserve_duration=False):
    """Parse+validate one effect definition. Accepts dict/list/JSON-string.
    Returns the normalised ops list — or, for a condition-definition cell,
    the normalised HOOK dict {on_start|on_round|on_expire: ops}; raises
    :class:`EffectError` on anything else."""
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return []
        if len(s) > MAX_CELL:
            raise EffectError(f"cell exceeds {MAX_CELL} characters")
        try:
            value = json.loads(s)
        except (ValueError, RecursionError):
            raise EffectError("cell is not valid JSON")
    if _count(value) > MAX_NODES:
        raise EffectError(f"definition exceeds {MAX_NODES} JSON nodes")
    if isinstance(value, dict) and "v" not in value and "ops" not in value:
        # condition-definition grammar: {"on_start": [...], "on_round": [...],
        # "on_expire": [...]} — effect lists anchored to existing clocks.
        if not value or set(value) - set(COND_HOOKS):
            raise EffectError("definition dict needs v/ops or condition hooks")
        return {k: _clean_ops(value[k], 1, allow_empty=True,
                              duration_rounds=duration_rounds,
                              preserve_duration=preserve_duration)
                for k in sorted(value) if value[k]}
    ops = value
    if isinstance(value, dict):
        try:
            ver = int(value.get("v", 0) or 0)
        except (TypeError, ValueError):
            raise EffectError("grammar version must be an integer")
        if not V_MIN <= ver <= V_MAX:
            raise EffectError(f"grammar version must be {V_MIN}..{V_MAX}")
        ops = value.get("ops")
    else:
        ver = V_MIN                      # a bare legacy list is v1 (no opposed)
    return _clean_ops(ops, 0, ver=ver, duration_rounds=duration_rounds,
                     preserve_duration=preserve_duration)


def canon(value, duration_rounds=0, preserve_duration=False):
    """Validated value -> canonical JSON string (byte-stable for generator
    and content export), '' for an empty definition. PRESERVES the definition's
    own grammar version (a v1 / bare-list cell keeps canon-ing to v1, byte-
    identically to before D113; only an explicitly v2-authored cell becomes v2),
    so adopting v2 never silently rewrites every stored effect."""
    ops = validate(value, duration_rounds=duration_rounds,
                   preserve_duration=preserve_duration)
    if not ops:
        return ""
    if isinstance(ops, dict):          # condition hook dict
        return json.dumps(ops, separators=(",", ":"), sort_keys=True)
    raw = value
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, RecursionError):
            raw = None
    ver = int(raw.get("v", V_MIN) or V_MIN) if isinstance(raw, dict) else V_MIN
    ver = ver if V_MIN <= ver <= V_MAX else V_MIN
    return json.dumps({"v": ver, "ops": ops}, separators=(",", ":"), sort_keys=True)


# ---------------------------------------------------------------------------
# execution — every branch below calls ANOTHER MODULE'S operation
# ---------------------------------------------------------------------------

def _tokens_room(room_id, token):
    return token is not None and token.get("room_id") in (None, room_id)


def _resolve(ctx, which):
    return ctx["self"] if which == "self" else ctx.get("target")


def _sheet_of(tok):
    from . import abilities as ABIL
    return ABIL._sheet_and_saves(tok)


async def _run_op(op, ctx):
    """Apply ONE op. Returns a short human fragment ('') or raises nothing —
    an op whose subject vanished mid-chain is simply skipped."""
    from . import conditions as C, inventory as INV
    from .room import health, moveforced
    room_id, caster = ctx["room_id"], ctx["caster"]
    kind = op["op"]

    if kind in ("damage", "heal"):
        tok = _resolve(ctx, op["target"])
        if not _tokens_room(room_id, tok):
            return ""
        from .room.dice import do_roll
        res = do_roll(op["expr"], None)
        if not res:
            return ""
        sign = -res["total"] if kind == "damage" else res["total"]
        r = await health.change_hp(room_id, tok, sign,
                                   damage_type=op.get("type") if kind == "damage" else None,
                                   broadcast_change=False,
                                   from_trigger_depth=ctx.get("depth", 0))
        if not r:
            return ""
        ctx["changed"] = True
        if kind == "damage" and r["damage"]:
            return f"{r['damage']} dmg to {tok['label']}"
        if kind == "heal" and r["healed"]:
            return f"+{r['healed']} HP to {tok['label']}"
        return ""

    if kind == "temp_hp":
        tok = _resolve(ctx, op["target"])
        if tok is None or tok.get("character_id") is None:
            return ""
        from .room.dice import do_roll
        res = do_roll(op["expr"], None)
        if not res:
            return ""
        ch = db.q1("SELECT temp_hp FROM characters WHERE id=?", (tok["character_id"],))
        if ch is None:
            return ""
        cur = max(0, int(ch["temp_hp"] or 0))
        # SRD temp HP: never stacks — you keep the higher of the two.
        new = max(cur, res["total"])
        db.x("UPDATE characters SET temp_hp=? WHERE id=?", (new, tok["character_id"]))
        ctx["changed"] = True
        return f"temp HP {new} on {tok['label']}" if new > cur else ""

    if kind in ("condition", "condition_remove", "break_concentration"):
        tok = _resolve(ctx, "self" if kind == "break_concentration" else op["target"])
        if not _tokens_room(room_id, tok):
            return ""
        conds = C.load(tok)
        if kind == "break_concentration":
            if not C.is_concentrating(conds):
                return ""
            # D113: the lifecycle owns the WHOLE end (flag + every conc-linked
            # condition, room-wide) — pop our own pending bump so it can deliver
            # the reconciled state itself without a stale re-send.
            ctx["cond_bumps"] = [b for b in ctx["cond_bumps"] if b.get("id") != tok["id"]]
            from .room import concentration
            await concentration.break_link(room_id, tok, "")
            ctx["changed"] = True
            return f"concentration broken on {tok['label']}"
        if kind == "condition":
            if C.immune(tok, op["key"]):                   # D163-2: data immunity
                return f"{tok['label']} is immune to {op['key']}"
            conds = C.add(conds, op["key"], op["rounds"], op["until"],
                          conc=ctx.get("conc"))
            frag = f"{op['key']} on {tok['label']}"
        else:                                    # condition_remove
            conds = C.remove(conds, op["key"])
            frag = f"{op['key']} off {tok['label']}"
        payload = db.json_dumps(conds)
        db.x("UPDATE tokens SET conds=? WHERE id=?", (payload, tok["id"]))
        ctx["cond_bumps"].append({**tok, "conds": payload})
        ctx["changed"] = True
        # D113 (2024): a concentration-ending state (incapacitated family) just
        # landed on a concentrating creature → its concentration ends outright.
        # The lifecycle owns the (now-stale) bump for this token and the cross-
        # token clear of everything it linked (``conc``), so pop our entry first.
        if kind == "condition" and C.blocks_concentration(conds) \
                and C.is_concentrating(conds):
            ctx["cond_bumps"] = [b for b in ctx["cond_bumps"] if b.get("id") != tok["id"]]
            from .room import concentration
            await concentration.break_link(room_id, tok, "incapacitated")
        return frag

    if kind in ("save", "check"):
        from . import gear
        from .room.dice import do_roll
        tok = _resolve(ctx, op["target"])
        if not _tokens_room(room_id, tok):
            return ""
        sheet, saves = _sheet_of(tok)
        if sheet is None:
            return ""
        dc = ctx.get("dc") if op["dc"] == "auto" else op["dc"]
        if not isinstance(dc, int):
            return ""                      # 'auto' needs a resolving context (cast shell)
        mod = (gear.save_bonus(sheet, saves, op["ability"]) if kind == "save"
               else gear.stat_mod(sheet, op["ability"]))
        from . import conditions as CND
        conds = C.load(tok)
        room = tok.get("room_id") or room_id
        if kind == "save" and CND.auto_fails_save(conds, room, op["ability"]):
            branch, total = "failure", None
        else:
            hook = "my_saves_dis" if kind == "save" else "my_checks_dis"
            dis = "dis" if CND.hook_bool(conds, room, hook) else None
            roll = do_roll("1d20", dis)
            total = (roll["kept"] or 0) + mod
            branch = "success" if total >= dc else "failure"
        ctx["changed"] = True
        frag = (f"{tok['label']}: {op['ability'].upper()} "
                f"{'save' if kind == 'save' else 'check'} "
                + (f"d20({total - mod}) {mod:+d} = {total} vs DC {dc}" if total is not None
                   else "AUTO-FAIL")
                + f" → {branch.upper()}")
        ctx["log"].append(frag)
        await run_ops(op[branch], ctx, _nested=True)
        return ""

    if kind == "opposed":
        # D113 v2: a contested ability check — the SUBJECT (carrier/caster) versus
        # the TARGET, same ability, decided by room.opposed (the SAME primitive a
        # grapple/shove/steal use). No second opposed engine, no new dice.
        from .room import opposed
        a = ctx["self"] or ctx["caster"]
        b = _resolve(ctx, op["target"])
        ap = opposed.participant(room_id, a) if a else None
        bp = opposed.participant(room_id, b) if b else None
        if ap is None or bp is None:
            return ""
        ar = opposed.check_roll(ap, op["ability"], kind="check")
        br = opposed.check_roll(bp, op["ability"], kind="check")
        if ar is None or br is None:
            return ""
        try:
            win = opposed.opposed_wins(ar["total"], br["total"], tie=op["tie"])
            tie = False
        except opposed.Tie:
            win, tie = False, True                 # tie -> DM: default to failure
        branch = "success" if win else "failure"
        ctx["changed"] = True
        ctx["log"].append(f"{a['label']} vs {b['label']}: {op['ability'].upper()} "
                          f"opposed {ar['total']} vs {br['total']}"
                          + (" tie" if tie else "") + f" → {branch.upper()}")
        await run_ops(op[branch], ctx, _nested=True)
        return ""

    if kind == "forced_move":
        from .room import net, moveforced
        from . import footprint
        tok = _resolve(ctx, op["target"])
        if not _tokens_room(room_id, tok):
            return ""
        anchor = caster if op["from"] == "caster" else ctx["self"]
        fl = tok.get("floor") or ""
        if anchor is not None and (anchor.get("floor") or "") != fl:
            anchor = None
        mp = net.get_map(room_id, fl)
        t0 = footprint.occupied_origin(mp, tok)[0]
        if anchor is None:
            sx, sy = 1, 0
        else:
            a0 = footprint.occupied_origin(mp, anchor)[0]
            dx, dy = t0[0] - a0[0], t0[1] - a0[1]
            sx, sy = (dx > 0) - (dx < 0), (dy > 0) - (dy < 0)
            if op["kind"] == "pull":
                sx, sy = -sx, -sy
            if sx == 0 and sy == 0:
                sx = 1
        dest = (t0[0] + sx * op["cells"], t0[1] + sy * op["cells"])
        final = await moveforced.apply_forced_move(room_id, tok, op["kind"], dest)
        if final is not None and final != t0:
            ctx["changed"] = True
            return f"{tok['label']} {op['kind']}ed {op['cells']} cells"
        return ""

    if kind == "resource":
        if op.get("mode", "cost") == "restore":
            return _restore_resource(ctx, op)
        # Consumed in the single claim+pay transaction at the end of the chain
        # (see run_ops); reaching here means the preflight passed.
        return ""

    return ""


def _restore_resource(ctx, op):
    """Restore one use in the SAME character resource ledger used by costs."""
    from . import gear
    tok = _resolve(ctx, op["target"])
    if tok is None or tok.get("character_id") is None:
        raise EffectError("resource restore has no paying character")
    row = db.q1("SELECT resources FROM characters WHERE id=?", (tok["character_id"],))
    pool = gear.clean_resources(db.j(row["resources"], []) if row else [])
    entry = next((r for r in pool if r["id"] == op["id"]), None)
    if entry is None:
        raise EffectError(f"resource '{op['id']}' is not available")
    if entry["current"] >= entry["max"]:
        return ""
    entry["current"] += op["amount"]
    db.x("UPDATE characters SET resources=? WHERE id=?",
         (db.json_dumps(pool), tok["character_id"]))
    ctx["changed"] = True
    return f"{tok['label']} restores {entry['name']}"


def _resource_preflight(ctx):
    """Every resource op in the chain must be payable BEFORE anything is
    applied (D111: a rejected or impossible action costs nothing)."""
    from . import gear
    def scan(ops, seen):
        for op in ops:
            if op["op"] == "resource":
                if op["mode"] == "cost":
                    seen.append(op)
            elif op["op"] in ("save", "check", "opposed"):
                scan(op["success"], seen)
                scan(op["failure"], seen)
    wanted = []
    scan(ctx["ops"], wanted)
    for op in wanted:
        tok = _resolve(ctx, op["target"])
        if tok is None or tok.get("character_id") is None:
            raise EffectError("resource cost has no paying character")
        row = db.q1("SELECT resources FROM characters WHERE id=?", (tok["character_id"],))
        pool = gear.clean_resources(db.j(row["resources"], []) if row else [])
        entry = next((r for r in pool if r["id"] == op["id"]), None)
        if entry is None or entry["current"] < op["amount"]:
            raise EffectError(f"resource '{op['id']}' is not available")
    return wanted


def make_ctx(room_id, *, caster=None, target=None, trigger="manual", op_id="",
             round_uid="", depth=0, conc=None):
    return {"room_id": room_id, "caster": caster, "target": target,
            "trigger": trigger, "op_id": op_id, "round_uid": str(round_uid),
            "depth": depth, "log": [], "changed": False, "cond_bumps": [],
            "conc": conc}


async def run_ops(ops, ctx, _nested=False):
    """Run a validated ops list in ``ctx``. The subject ('self') is the carrier
    token; ``target`` the current target. Applies nothing unless EVERY
    resource cost can be paid — the preflight scans into branches, so a
    nested resource op is prepaid by the top-level claim transaction and a
    nested call skips the claim entirely. Trigger-fired chains (depth>0) fire
    no further triggers. Returns the ctx (log fragments, changed, cond_bumps)."""
    from . import inventory as INV
    ctx["self"] = ctx["self"] if "self" in ctx else (ctx["caster"] or ctx["target"])
    if not _nested:
        ctx["ops"] = ops
        wanted = _resource_preflight(ctx)
        if ctx["op_id"]:
            with db.tx() as c:
                if not INV._claim(c, str(ctx["op_id"])[:40], ctx["room_id"],
                                  "effect", (ctx["self"] or {}).get("id", 0)):
                    ctx["replayed"] = True
                    return ctx
                for op in wanted:                # pay inside the SAME tx
                    tok = _resolve(ctx, op["target"])
                    from . import gear
                    row = c.execute("SELECT resources FROM characters WHERE id=?",
                                    (tok["character_id"],)).fetchone()
                    pool = gear.clean_resources(db.j(row["resources"], []) if row else [])
                    entry = next((r for r in pool if r["id"] == op["id"]), None)
                    if entry is None or entry["current"] < op["amount"]:
                        raise EffectError(f"resource '{op['id']}' is not available")
                    entry["current"] -= op["amount"]
                    c.execute("UPDATE characters SET resources=? WHERE id=?",
                              (db.json_dumps(pool), tok["character_id"]))
    for op in ops:
        frag = await _run_op(op, ctx)
        if frag:
            ctx["log"].append(frag)
    if not _nested:
        await _finish(ctx)
    return ctx


async def _finish(ctx):
    """Visibility-correct condition bumps + one snapshot — the same channels
    the engine's own operations use."""
    if not ctx["cond_bumps"] and not ctx["changed"]:
        return
    from .room.visibility import send_cond_bump
    from .room import net
    for bump in ctx["cond_bumps"]:
        await send_cond_bump(ctx["room_id"], bump, db.j(bump["conds"], []))
    await net.broadcast(ctx["room_id"], "snapshot", None)


# ---------------------------------------------------------------------------
# trigger seams (guarded)
# ---------------------------------------------------------------------------

async def fire(room_id, event, *, token, caster=None, items=(), conds=None,
               round_uid="", budget=None, target=None):
    """Fire one trigger for ``token``. ``items`` are candidate carrier rows
    (runtime items dicts), ``conds`` the token's current condition entries.
    NEVER call from inside a trigger-fired chain — the depth guard makes that
    a no-op by design; keep it that way (D111, no recursion)."""
    if not event or event not in TRIGGERS and event not in COND_HOOKS:
        return []
    if token is None:
        return []
    if not round_uid:
        # Non-combat one-shot events (a single on_damaged hit) get a fresh
        # firing id: the claim then guards against RETRIES of the same call,
        # not against a legitimate new event.
        import uuid
        round_uid = uuid.uuid4().hex[:8]
    from . import conditions as C
    budget = budget if budget is not None else 8
    fired = []
    for it in items:
        if len(fired) >= budget:
            break
        props = (it or {}).get("props") or {}
        carriers = []
        cell = props.get("effects")
        if cell and str(props.get("trigger", "")) == event:
            carriers.append((cell, "item", f"it:{it.get('id')}"))
        # D113: an ACTIVE curse on the same carrier may arm this event too — an
        # inactive / differently-armed curse contributes nothing (fail-closed:
        # a mere read/sync of inventory never reaches this loop at all).
        cur = (it or {}).get("curse")
        if (isinstance(cur, dict) and cur.get("active")
                and str(cur.get("trigger", "")) == event and cur.get("effects")):
            carriers.append((cur["effects"], "curse", f"curse:{it.get('id')}"))
        item_duration_rounds = duration_rounds(props.get("duration"))
        for cell, src, key in carriers:
            if len(fired) >= budget:
                break
            uid = f"trg:{event}:{token['id']}:{key}:{round_uid}"
            if not _claim(room_id, token["id"], uid):
                continue
            ops = _safe_validate(cell, item_duration_rounds)
            if not ops:
                continue
            ctx = make_ctx(room_id, caster=caster or token,
                           target=target or token,
                           trigger=event, round_uid=round_uid, depth=1)
            ctx["self"] = token
            ctx["src"] = src
            ctx["item_id"] = it.get("id")
            await run_ops(ops, ctx)
            fired.append(ctx)
    for entry in (conds or []):
        if len(fired) >= budget:
            break
        key = str(entry.get("k", ""))
        hooks = C.effects_for(key, room_id, event)
        if not hooks:
            continue
        uid = f"trg:{event}:{token['id']}:{key}:{round_uid}"
        if not _claim(room_id, token["id"], uid):
            continue
        ctx = make_ctx(room_id, caster=_src_token(entry), target=token,
                       trigger=event, round_uid=round_uid, depth=1)
        ctx["self"] = token
        await run_ops(hooks, ctx)
        fired.append(ctx)
    return fired


def _src_token(entry):
    sid = entry.get("src")
    if not sid:
        return None
    return db.q1("SELECT * FROM tokens WHERE id=?", (sid,))


def _safe_validate(cell, duration_rounds=0):
    try:
        return validate(cell, duration_rounds=duration_rounds)
    except EffectError:
        return []            # a once-valid row that went bad never executes


def _claim(room_id, token_id, uid):
    """One firing per (token, trigger, source, round) — rides inv_ops."""
    from . import inventory as INV
    with db.tx() as c:
        return INV._claim(c, uid[:40], room_id, "effect_trigger", token_id)
