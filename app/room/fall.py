"""D162-3 — the fall (SRD 2024). 1d6 bludgeoning per FULL 10 ft of a fall,
capped at 20d6 (= the engine's 200 ft volume ceiling), under 10 ft hurts
nothing, the landing leaves the body PRONE. One resolution function, reached
from exactly four triggers:

  1. a move ends (walk3d's finally) and the token now RESTS on an unsupported
     cell (Air/Void — nothing walkable under it) and cannot hold the air;
  2. the token is knocked PRONE while flying without hover (knock_prone hook —
     the docstring there deferred exactly this sprint);
  3. an INCAPACITATING condition (stunned/paralyzed/petrified/unconscious —
     the same gate movement uses: _movement_block_reason) lands while it
     rests in the air (add_condition + spell-effect hooks);
  4. the DM explicitly lets go: `token_drop` (a held flyer, a carry released).

Natural flight (fly speed) simply HOLDS — hover or not; hover is irrelevant
while the flyer still flies and only matters for the PRONE trigger, exactly as
the SRD says. A fall that cannot resolve a landing (every plane in the column
is open) FAILS CLOSED: no state change, the DM is whispered about it. Damage
enters the world only through health.damage — resistances, immunity, temp HP,
death saves and massive damage are inherited, never re-implemented (D34).
"""
import asyncio

from .. import charbuild, db, floors, mapmodel, npc
from .net import broadcast, dm_whisper, sys_msg

MAX_FALL_DICE = 20                 # 20d6 cap — the 200 ft volume ceiling


def _fly_state(room_id, tok):
    """(fly_ft, hover) from the ONE projection each kind of token has."""
    if tok.get("character_id"):
        raw = db.q1("SELECT * FROM characters WHERE id=?", (tok["character_id"],))
        sp = charbuild.species_projection(dict(raw), room_id) if raw else None
        traits = str((sp or {}).get("traits") or "").lower()
        return int((sp or {}).get("fly_ft") or 0), "hover" in traits
    blk = npc.load(tok)
    if blk is None:
        return 0, False
    return (int(blk.get("fly") or 0),
            bool(blk.get("hover")) or "hover" in str(blk.get("traits") or "").lower())


def _cell_of(mp, tok):
    c = mp["cell"]
    return int(tok["x"] // c), int(tok["y"] // c)


def _walkable_at(mp, cx, cy):
    if not (0 <= cx < mp["w"] and 0 <= cy < mp["h"]):
        return False
    return mapmodel.walkable(mp["cells"][mapmodel.flat_idx(mp, cx, cy)])


async def resolve_fall(room_id, tok_id, *, forced=False, tag=""):
    """Resolve a possible fall for ONE token; True when it fell. Never raises:
    an internal problem resolves to no-fall (the world only ever loses the
    optional physics, never a token)."""
    try:
        return await _resolve(room_id, tok_id, forced=forced, tag=tag)
    except Exception:
        return False


async def _resolve(room_id, tok_id, *, forced=False, tag=""):
    from . import vertical3d
    tok = db.q1("SELECT * FROM tokens WHERE id=? AND room_id=?", (tok_id, room_id))
    if tok is None:
        return False
    fl = tok.get("floor") or ""
    maps = vertical3d.maps_for(room_id)
    lm = vertical3d.level_map(room_id)
    mp = maps.get(fl)
    if mp is None:
        return False
    cx, cy = _cell_of(mp, tok)
    supported = _walkable_at(mp, cx, cy)
    fly, hover = _fly_state(room_id, tok)
    from .movement import _movement_block_reason
    grounded_state = _movement_block_reason(tok) is not None   # downed / incapacitated
    holding_air = fly > 0 and not grounded_state
    if supported and not forced:
        return False                       # standing on something solid
    if supported and forced and holding_air:
        pass                               # the DM let a flyer go — it falls from here
    elif supported:
        return False                       # a ground drop is a placement, not a fall
    if holding_air:
        # SRD 2024: a PRONE flyer must land or fall — and HOVER is exactly the
        # special movement that saves it there. Stun/paralysis/petrification
        # are the incapacitated family (grounded_state above) and fall through
        # hover; a forced DM release falls regardless of hover.
        from .. import conditions as C
        prone = any(str(c.get("k", "")).lower() == "prone" for c in C.load(tok))
        if not (forced or (prone and not hover)):
            return False                   # natural flight holds, hover or not

    # ---- find the first solid cell under this column, scanning this plane and
    # every plane at or below it, highest first.
    here = lm.get(fl, 0)
    stack = sorted(((n, lv) for n, lv in lm.items() if n in maps and lv <= here),
                   key=lambda kv: -kv[1])
    land = None
    for name, lv in stack:
        cmp_ = maps[name]
        if _walkable_at(cmp_, cx, cy):
            land = (name, cmp_)
            break
    if land is None:
        await dm_whisper(room_id,
                         f"🕯 {tok['label']}: a fall cannot resolve a landing "
                         f"(column {cx},{cy} is open down to the lowest plane) — "
                         "nothing moved. Close the column or move the token.")
        return False
    land_name, land_mp = land
    start_ft = floors.token_base_ft(room_id, tok)
    land_ft = floors.absolute_height_ft(room_id, land_name,
                                        mapmodel.elev_at(land_mp, cx, cy))
    fall_ft = max(0, int(start_ft) - int(land_ft))
    if fall_ft <= 0:
        return False                       # nothing above nothing: no fall
    dice_n = min(MAX_FALL_DICE, fall_ft // 10)

    # ---- the move itself: same cell, landing plane, elevation stack released
    from .movement import _state_pixel
    x, y = _state_pixel(land_mp, cx, cy)
    db.x("UPDATE tokens SET floor=?, x=?, y=?, z=?, elevation_ft=0 WHERE id=?",
         (land_name, x, y, mapmodel.elev_at(land_mp, cx, cy), tok_id))
    tok = db.q1("SELECT * FROM tokens WHERE id=?", (tok_id,))

    # ---- damage through the ONE HP mutation site (resist/temp-HP/death saves)
    dmg = 0
    hp_left = None
    if dice_n > 0:
        from .dice import do_roll
        res = do_roll(f"{dice_n}d6", None)
        dmg = res["total"]
        from . import health
        hp_res = await health.damage(room_id, tok, dmg, damage_type="bludgeoning") or {}
        hp_left = hp_res.get("hp")

    line = (f"🪂 {tok['label']} falls {fall_ft} ft"
            + (f" and takes {dmg} bludgeoning damage" if dmg else " without harm"))
    # ---- landing: a body that can still be sprawled sprawls (prone). A flyer
    # the DM simply released lands on its feet.
    survived = hp_left is None or hp_left > 0
    landed_flyer = fly > 0 and not grounded_state and forced
    if survived and not landed_flyer:
        from .conditions import knock_prone
        await knock_prone(room_id, tok, actor="the fall")
        line += " and lands prone."
    else:
        line += "."
    if tag:
        line = line.replace("🪂 ", f"🪂 [{tag}] ")
    sys_msg(room_id, line)
    await broadcast(room_id, "snapshot", None)
    return True


async def after_move(room_id, tok_id):
    """Hook: a voluntary move ended — rest support is now authoritative."""
    await resolve_fall(room_id, tok_id)


async def after_condition(room_id, tok):
    """Hook: prone / an incapacitating state just landed on this token while it
    may be resting on air."""
    await resolve_fall(room_id, tok["id"])
