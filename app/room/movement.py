"""Grid movement: DM teleport and animated A* walks, with LOS reveal + trap/loot checks.

Map read-modify-write (reveal, trap/loot flag flip, persist) is serialised per room
by net.map_lock so concurrent walks of different tokens can't clobber each other.
"""
import asyncio

from .. import conditions as C
from .. import db, footprint, gear, los, mapmodel, movecost
from ..path import find_path, find_path_3d, path_footprint_cost, step_legal
from .growth import maybe_grow_map
from . import authz, combat as CB
from .net import (broadcast, fog_patch, get_map, map_lock, send_to,
                  send_to_plane_viewed, set_map)
from .traps import at_cell, hit_trap, take_loot
from .visibility import (broadcast_token_step, send_property_to_interested,
                         viewer_visible_cells, send_presence_event)

STEP_DELAY = 0.11
# token_id -> walk asyncio.Task
_walks: dict[int, asyncio.Task] = {}


async def _cancel_walk(token_id):
    task = _walks.pop(token_id, None)
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


async def _announce_move(room_id, token_id, moving, reason=None):
    payload = {"token_id": token_id, "moving": bool(moving)}
    if reason:
        payload["reason"] = reason
    # SPRINT-21: a walk ring for a token no player can see must not announce
    # its id either. Presence-gated (owned/character walks stay room-wide);
    # deleted tokens (row None) keep the plain channel for client cleanup.
    tok = db.q1("SELECT id, owner_user_id, character_id, controller_user_id, floor, x, y "
                "FROM tokens WHERE id=?", (token_id,))
    if tok is None:
        await broadcast(room_id, "move_state", payload)
    else:
        await send_presence_event(room_id, tok, "move_state", payload)


def _room_tokens(room_id, exclude_id=None, floor=None):
    # D86: with a floor given, only tokens ON THAT PLANE collide — a token on
    # the attic never blocks the dungeon below. None = every plane (DM views).
    rows = db.q("SELECT id, x, y, owner_user_id, size, fw, fh, rot, mount_token_id, "
                "floor FROM tokens WHERE room_id=?", (room_id,))
    return [t for t in rows if t["id"] != exclude_id
            and (floor is None or (t.get("floor") or "") == floor)]


def _reveal_player_token(mp, tok):
    if tok["owner_user_id"] is None:
        return [], mp
    return los.visible_cells(mp, footprint.player_source_cells(mp, [tok]), radius=mapmodel.FOG_R), mp


def _cell_elev(mp, cx, cy):
    """Integer elevation unit of one WORLD cell (0 = ground; D70)."""
    return mapmodel.elev_at(mp, cx, cy)


def _speeds(tok):
    """All movement allowances in feet — always through gear.clean_speeds (SSOT).

    D115: a PC sheet must be read as the full gear-aware sheet, not merely its
    legacy `speed` column: equipment speed_bonus_ft already belongs to that one
    canonical derivation. NPCs keep using their structured NPC block."""
    if tok["character_id"]:
        sheet = gear.as_sheet(db.q1("SELECT * FROM characters WHERE id=?",
                                    (tok["character_id"],)) or {})
        species = (sheet.get("build") or {}).get("species") or {}
        if species:
            sheet = dict(sheet)
            for sheet_key, species_key in (("speed", "speed_ft"), ("fly", "fly_ft"),
                                           ("swim", "swim_ft"), ("climb", "climb_ft")):
                value = int(species.get(species_key) or 0)
                if value:
                    sheet[sheet_key] = value
        speeds = gear.clean_speeds(sheet)
    else:
        speeds = gear.clean_speeds(db.j(tok["npc"]) if tok["npc"] else {})
    # D109 SRD Slow / D111 catalog hook: speed_delta from the condition
    # definitions (slowed = -10 built-in; several sources stack, but slowed
    # itself can never appear twice — condition entries dedupe by key),
    # floored at 0, applied to walk only.
    from .. import conditions as CND
    delta = CND.speed_delta(CND.load(tok), tok.get("room_id"))
    if delta:
        speeds = dict(speeds, walk=max(0, speeds["walk"] + delta))
    # AP-015 (audit F4): 2024 exhaustion reduces your Speed by 5 ft per level.
    # "Your Speed" is the walk speed of the sheet; fly/swim/climb are separate
    # modes and deliberately stay untouched.
    if tok["character_id"]:
        exh = gear.exhaustion_speed_penalty_ft(sheet)
        if exh:
            speeds = dict(speeds, walk=max(0, speeds["walk"] + exh))
    return speeds


def _walk_speed(tok):
    """Walk speed in feet (legacy single-mode entry point)."""
    return _speeds(tok)["walk"]


MODES = ("walk", "fly", "swim", "climb")


def _mode_or_error(tok, msg):
    """(D83) One active mode per movement operation. Unknown mode words fall
    back to walk. Flying genuinely needs a fly speed (D140); swim and climb
    are always allowed — WITHOUT the matching speed they pay the SRD
    surcharge, which _strained hands to movecost (D144)."""
    mode = str(msg.get("mode") or "walk").lower()
    if mode not in MODES:
        mode = "walk"
    if mode == "fly" and _speeds(tok).get("fly", 0) <= 0:
        return None, "This creature has no fly speed"
    return mode, None


def _strained(tok, mode):
    """D144: the SRD surcharge belongs to creatures WITHOUT the speed —
    the grid modules stay creature-blind, this is the one lookup."""
    return mode in ("swim", "climb") and _speeds(tok).get(mode, 0) <= 0


MOVE_BLOCKED_CONDS = {"incapacitated", "unconscious", "paralyzed", "stunned",
                      "petrified"}    # pre-D111 hardcode — kept as the
# documentation of the SRD baseline. The gate below reads the catalog hook
# blocks_movement instead, so built-ins AND conditions.csv rows decide it.


async def carry_riders(room_id, token_id):
    """(D83) Mount carrying: every token riding (transitively) on a token that
    just MOVED is re-centred inside its mount's oriented footprint through
    footprint.anchor_for_center and pushed out over the visibility-filtered
    step channel. Carried riders NEVER spend their own movement budget and are
    never independently validated — while carried, the mount's legal position
    is their position (latent footprint, collision-exempt, see footprint).
    Nested chains (A on B on C) propagate top-down, bounded and cycle-tolerant;
    the cycle guard at assignment time (tokens.handle_token_mount) stays the
    real protection."""
    parent = db.q1("SELECT * FROM tokens WHERE id=?", (token_id,))
    if parent is None:
        return
    mp = get_map(room_id, parent.get("floor") or "")   # D88: carry on the mount's plane
    frontier, seen = [parent], {token_id}
    while frontier:
        nxt = []
        for p in frontier:
            p_origin, p_span = footprint.occupied_origin(mp, p)
            for r in db.q("SELECT * FROM tokens WHERE room_id=? AND mount_token_id=?",
                          (room_id, p["id"])):
                if r["id"] in seen or len(seen) > 64:
                    continue
                seen.add(r["id"])
                # SPRINT-19 plane guard: carrying is same-plane only (D86
                # planes are independent worlds). Defensive: legacy or
                # inconsistent data must never teleport a rider's position
                # onto another floor's coordinate space.
                if (r.get("floor") or "") != (p.get("floor") or ""):
                    continue
                anchor = footprint.anchor_for_center(p_origin, p_span,
                                                     footprint.oriented_span(r))
                x, y = footprint.origin_pixels(anchor, footprint.token_span(r),
                                               mp["cell"])
                db.x("UPDATE tokens SET x=?, y=? WHERE id=?", (x, y, r["id"]))
                r["x"], r["y"] = x, y
                await broadcast_token_step(room_id, r, x, y, anchor[0], anchor[1])
                nxt.append(r)
        frontier = nxt


def _carries_riders(token_id):
    return db.q1("SELECT 1 AS hit FROM tokens WHERE mount_token_id=? LIMIT 1",
                 (token_id,)) is not None


def _movement_block_reason(tok):
    """Authoritative voluntary-movement gate (D80): a creature at 0 HP (downed)
    or carrying a condition of the incapacitated family cannot move under its
    own power — no client request can talk its way past this. DM moves and
    forced movement (moveforced) are separate, authority-based paths."""
    cid = tok.get("character_id")
    if cid is not None:
        ch = db.q1("SELECT hp FROM characters WHERE id=?", (cid,))
        if ch is not None and int(ch.get("hp") or 0) <= 0:
            return "You cannot move while downed"
    conds = C.load(tok)
    hit_key = next((c["k"] for c in conds
                    if C.hook_bool([c], tok.get("room_id") or 0, "blocks_movement")), None)
    if hit_key:
        return f"You cannot move while {C.label(hit_key).lower()}"
    return None


async def handle_move(ws, room_id, user, is_dm, msg):
    tok = db.q1("SELECT * FROM tokens WHERE id=? AND room_id=?", (msg.get("token_id", -1), room_id))
    if tok is None:
        return
    if not authz.controls(tok, user["id"], is_dm):        # D82: owner or assigned controller
        await send_to(ws, "error", {"msg": "You can only move your own token"})
        return
    blocked = _movement_block_reason(tok)
    if blocked:
        await send_to(ws, "error", {"msg": blocked})
        return
    mode, why = _mode_or_error(tok, msg)                 # D83: one mode per move
    if why:
        await send_to(ws, "error", {"msg": why})
        return
    strained = _strained(tok, mode)                      # D144: SRD surcharge
    # Action economy gate (D74, strict 5e): a token that is in the initiative
    # order may only be moved by its owner on its OWN turn. The DM is exempt
    # (the DM moves everyone, ever); tokens that are not listed (mid-combat
    # joiners) are not in combat and move freely.
    init = CB.get_init(room_id)
    budget = None
    if not is_dm and CB.is_listed(init, tok["id"]):
        if CB.turn_token(init) != tok["id"]:
            await send_to(ws, "error", {"msg": "It is not your turn"})
            return
        budget = CB.move_remaining(init, tok["id"], mode)
        if budget <= 0:
            await send_to(ws, "error", {"msg": "No movement left this turn — Dash or End Turn"})
            return
    current_floor = tok.get("floor") or ""
    cross_3d = "floor" in msg and str(msg["floor"] or "") != current_floor
    if not cross_3d:
        proposed = msg.get("path")
        cross_3d = isinstance(proposed, list) and any(
            isinstance(p, dict) and "floor" in p and str(p["floor"] or "") != current_floor
            for p in proposed)
    if cross_3d:
        if msg.get("teleport") and is_dm:
            await _teleport3d(ws, tok, msg)
            return
        if mode != "fly":
            await send_to(ws, "error", {"msg": "Vertical movement requires a fly speed"})
            return
        await _move3d(ws, tok, msg, mode, budget)
        return

    mp = get_map(room_id, tok.get("floor") or "")     # D88: YOUR plane's map
    cell = mp["cell"]
    try:
        tx, ty = int(msg["tx"]), int(msg["ty"])
    except (KeyError, ValueError, TypeError):
        return
    origin, side = footprint.occupied_origin(mp, tok)
    # D84: the wire destination is the desired CENTER cell (pointer contract);
    # the server converts it to the canonical integer footprint anchor here —
    # the ONE place this happens for moves, teleports and previews alike.
    tx, ty = footprint.center_to_anchor((tx, ty), side)
    tx, ty = footprint.clamp_origin(mp, (tx, ty), side)          # WORLD clamp (D72)
    tokens = _room_tokens(room_id, tok["id"], tok.get("floor") or "")

    if msg.get("teleport") and is_dm:
        if origin == (tx, ty):
            return
        if not footprint.valid_final_position(mp, tok, (tx, ty), tokens):
            await send_to(ws, "error", {"msg": "Invalid teleport destination for this footprint"})
            return
        x, y = footprint.origin_pixels((tx, ty), side, cell)
        db.x("UPDATE tokens SET x=?, y=?, z=? WHERE id=?",
             (x, y, _cell_elev(mp, tx, ty), tok["id"]))
        tok["x"], tok["y"] = x, y
        await broadcast_token_step(room_id, tok, x, y, tx, ty)
        if _carries_riders(tok["id"]):
            await carry_riders(room_id, tok["id"])         # D83: riders come along
        # Only a player-owned token lifts fog; NPC/DM tokens never reveal for players.
        if tok["owner_user_id"] is not None:
            fl_tp = tok.get("floor") or ""                        # D88 plane
            async with map_lock(room_id):
                mp = get_map(room_id, fl_tp)
                visible, _ = _reveal_player_token(mp, tok)
                newly = mapmodel.reveal_cells(mp, visible)
                if newly:
                    set_map(room_id, mp, fl_tp)
            if newly:
                # D102: plane-scoped — a walk on one plane reveals fog on THAT
                # plane's map only; sockets standing elsewhere must not receive it.
                await send_to_plane_viewed(room_id, fl_tp, "explored",
                                           fog_patch(mp, newly, fl_tp))
        from .grapple import end_grapples_out_of_reach
        await end_grapples_out_of_reach(room_id, tok)
        await maybe_grow_map(room_id, tok)
        return

    if origin == (tx, ty):
        return
    # A confirmed preview must execute EXACTLY the route the preview showed.
    # The route is fully revalidated against the current authoritative map,
    # and walk() revalidates every step again while moving. If the world
    # changed since the preview (door closed, token nudged, route edited)
    # the route is REJECTED so the client must re-preview and re-confirm —
    # the server never silently sends the token on a different route.
    path = None
    proposed = msg.get("path")
    if isinstance(proposed, list) and proposed:
        candidate = []
        cur = origin
        valid = True
        for point in proposed[:mp["w"] * mp["h"]]:
            try:
                nxt = (int(point["x"]), int(point["y"]))
            except (KeyError, TypeError, ValueError):
                valid = False
                break
            if not step_legal(mp, cur, nxt,
                              blocked_edges=mapmodel.blocked_edges(mp), footprint=side,
                              mode=mode):
                valid = False
                break
            candidate.append(nxt)
            cur = nxt
        if valid and candidate and candidate[-1] == (tx, ty):
            path = candidate
        else:
            await send_to(ws, "error", {"msg": "Route changed — please plan it again",
                                        "code": "route_invalid"})
            return
    if path is None:
        # No proposed route at all: DM drags/teleports and direct integrations.
        # (Interactive player moves always come with a confirmed preview path.)
        path = find_path(mp, origin, (tx, ty),
                         blocked_edges=mapmodel.blocked_edges(mp), footprint=side,
                         mode=mode)
    if path is None:
        await send_to(ws, "error", {"msg": "No path there"})
        return
    if not footprint.valid_final_position(mp, tok, (tx, ty), tokens, mode=mode):
        await send_to(ws, "error", {"msg": "That token footprint cannot finish there"})
        return

    await _cancel_walk(tok["id"])
    _walks[tok["id"]] = asyncio.create_task(walk(room_id, tok["id"], path, mover_ws=ws,
                                                 budget=budget, mode=mode,
                                                 strained=strained))
    await _announce_move(room_id, tok["id"], True)


def _all_tokens(room_id):
    return db.q("SELECT * FROM tokens WHERE room_id=?", (room_id,))


def _state_pixel(mp, cx, cy):
    return (cx + .5) * mp["cell"], (cy + .5) * mp["cell"]


def _state_token(tok, state, maps):
    fl, (cx, cy) = state
    mp = maps[fl]
    x, y = _state_pixel(mp, cx, cy)
    return {**tok, "floor": fl, "x": x, "y": y, "z": _cell_elev(mp, cx, cy)}


async def _teleport3d(ws, tok, msg):
    from . import vertical3d
    room_id = tok["room_id"]
    current = tok.get("floor") or ""
    to_fl = str(msg["floor"] or current) if "floor" in msg else current
    maps = vertical3d.maps_for(room_id)
    lm = vertical3d.level_map(room_id)
    if to_fl not in maps or current not in maps:
        await send_to(ws, "error", {"msg": "That floor is not registered"})
        return
    try:
        cx, cy = int(msg["tx"]), int(msg["ty"])
    except (KeyError, TypeError, ValueError):
        return
    start_origin, side = footprint.occupied_origin(maps[current], tok)
    goal = (to_fl, footprint.clamp_origin(maps[to_fl], footprint.center_to_anchor((cx, cy), side), side))
    if start_origin == goal[1] and current == to_fl:
        return
    cand = _state_token(tok, goal, maps)
    if not vertical3d.volume_final_valid(room_id, cand, _all_tokens(room_id), maps, lm):
        await send_to(ws, "error", {"msg": "Invalid 3D teleport destination for this footprint"})
        return
    mp = maps[to_fl]
    x, y = _state_pixel(mp, *goal[1])
    db.x("UPDATE tokens SET floor=?, x=?, y=?, z=? WHERE id=?",
         (to_fl, x, y, _cell_elev(mp, *goal[1]), tok["id"]))
    tok["floor"], tok["x"], tok["y"] = to_fl, x, y
    await send_property_to_interested(room_id, tok, "token_floor",
                                      {"token_id": tok["id"], "floor": to_fl})
    await broadcast_token_step(room_id, tok, x, y, goal[1][0], goal[1][1])
    if _carries_riders(tok["id"]):
        await carry_riders(room_id, tok["id"])
    if tok["owner_user_id"] is not None:
        async with map_lock(room_id):
            mp = get_map(room_id, to_fl)
            visible, _ = _reveal_player_token(mp, tok)
            newly = mapmodel.reveal_cells(mp, visible)
            if newly:
                set_map(room_id, mp, to_fl)
        if newly:
            await send_to_plane_viewed(room_id, to_fl, "explored", fog_patch(mp, newly, to_fl))
    from .grapple import end_grapples_out_of_reach
    await end_grapples_out_of_reach(room_id, tok)
    await maybe_grow_map(room_id, tok)


async def _move3d(ws, tok, msg, mode, budget):
    """D114 Phase 6: flight through a legitimate open vertical column. Terrain,
    openings and collision are checked by path.py + vertical3d.py, never by a
    second geometry implementation."""
    from . import vertical3d
    room_id = tok["room_id"]
    current = tok.get("floor") or ""
    to_fl = str(msg["floor"] or current) if "floor" in msg else current
    maps = vertical3d.maps_for(room_id)
    lm = vertical3d.level_map(room_id)
    if to_fl not in maps or current not in maps:
        await send_to(ws, "error", {"msg": "That floor is not registered"})
        return
    try:
        cx, cy = int(msg["tx"]), int(msg["ty"])
    except (KeyError, TypeError, ValueError):
        return
    start_origin, side = footprint.occupied_origin(maps[current], tok)
    start = (current, start_origin)
    goal_anchor = footprint.clamp_origin(
        maps[to_fl], footprint.center_to_anchor((cx, cy), side), side)
    goal = (to_fl, goal_anchor)
    if start == goal:
        return
    proposed = msg.get("path")
    raw = proposed if isinstance(proposed, list) else []
    states = []
    for entry in raw:
        if not isinstance(entry, dict):
            await send_to(ws, "error", {"msg": "3D path points need x and y", "code": "route_invalid"})
            return
        fl = str(entry["floor"] or current) if "floor" in entry else current
        if fl not in maps:
            await send_to(ws, "error", {"msg": "That floor is not registered"})
            return
        try:
            cell = (int(entry["x"]), int(entry["y"]))
        except (KeyError, TypeError, ValueError):
            await send_to(ws, "error", {"msg": "3D path points need x and y", "code": "route_invalid"})
            return
        states.append((fl, cell))

    blocked_edges = {fl: mapmodel.blocked_edges(mp) for fl, mp in maps.items()}
    all_tokens = _all_tokens(room_id)

    def state_ok(state):
        cand = _state_token(tok, state, maps)
        return vertical3d.volume_final_valid(room_id, cand, all_tokens, maps, lm)

    def vertical_ok(prev, nxt, cells):
        cand = _state_token(tok, prev, maps)
        return vertical3d.vertical_path_clear(room_id, cand, prev[0], nxt[0], maps, lm)

    def step_ok(prev_state, state):
        pf, porigin = prev_state
        fl, origin = state
        if pf != fl:
            return (abs(lm.get(pf, 99) - lm.get(fl, 99)) == 1
                    and vertical_ok(prev_state, state, footprint.origin_cells(maps[pf], porigin, side)))
        return step_legal(maps[pf], porigin, origin, blocked_edges=blocked_edges.get(pf) or set(),
                          footprint=side, mode=mode)

    if raw:
        cur = start
        for state in states:
            if not step_ok(cur, state) or not state_ok(state):
                await send_to(ws, "error", {"msg": "Route changed — please plan it again",
                                            "code": "route_invalid"})
                return
            cur = state
        if cur != goal:
            await send_to(ws, "error", {"msg": "Route changed — please plan it again",
                                        "code": "route_invalid"})
            return
        path = states
    else:
        path = find_path_3d(start, goal, maps, lm, side, mode=mode,
                            vertical_ok=vertical_ok, state_ok=state_ok,
                            blocked_edges=blocked_edges)
        if path is None:
            await send_to(ws, "error", {"msg": "No vertical flight path there"})
            return

    strained = _strained(tok, mode)                      # D144: SRD surcharge
    await _cancel_walk(tok["id"])
    _walks[tok["id"]] = asyncio.create_task(walk3d(room_id, tok["id"], path, mover_ws=ws,
                                                   budget=budget, mode=mode,
                                                   strained=strained))
    await _announce_move(room_id, tok["id"], True)


async def walk3d(room_id, token_id, path, mover_ws=None, budget=None, mode="fly",
                 strained=False):
    from . import vertical3d
    stop_reason = None
    spent = 0
    has_riders = _carries_riders(token_id)
    try:
        for i, state in enumerate(path):
            tok = db.q1("SELECT * FROM tokens WHERE id=?", (token_id,))
            if tok is None or tok["room_id"] != room_id:
                return
            downed = _movement_block_reason(tok)
            if downed:
                stop_reason = "downed"
                if mover_ws is not None:
                    await send_to(mover_ws, "error", {"msg": downed})
                break

            legal = False
            x = y = None
            old_floor = tok.get("floor") or ""
            cell = state[1]
            fl = state[0]
            async with map_lock(room_id):
                maps = vertical3d.maps_for(room_id)
                lm = vertical3d.level_map(room_id)
                current = old_floor
                if current in maps and fl in maps:
                    prev = (current, footprint.occupied_origin(maps[current], tok)[0])
                    pf, pcell = prev
                    side = footprint.token_span(tok)
                    all_tokens = _all_tokens(room_id)
                    if pf == fl:
                        legal = step_legal(maps[pf], pcell, cell,
                                           blocked_edges=mapmodel.blocked_edges(maps[pf]),
                                           footprint=side, mode=mode)
                    else:
                        legal = (abs(lm.get(pf, 99) - lm.get(fl, 99)) == 1
                                 and vertical3d.vertical_path_clear(
                                     room_id, _state_token(tok, prev, maps), pf, fl, maps, lm))
                    if legal:
                        cand = _state_token(tok, state, maps)
                        legal = vertical3d.volume_final_valid(room_id, cand, all_tokens, maps, lm)
                    if legal:
                        step_c = (movecost.vertical_cost() if pf != fl
                                  else movecost.route_cost(maps[pf], [pcell, cell], side, mode=mode, strained=strained))
                        if budget is not None and spent + step_c > budget:
                            stop_reason = "budget"
                            legal = False
                        else:
                            spent += step_c
                    if legal:
                        mp = maps[fl]
                        x, y = _state_pixel(mp, *cell)
                        db.x("UPDATE tokens SET floor=?, x=?, y=?, z=? WHERE id=?",
                             (fl, x, y, _cell_elev(mp, *cell), token_id))
                        tok["floor"], tok["x"], tok["y"] = fl, x, y

            if stop_reason == "budget":
                if mover_ws is not None:
                    await send_to(mover_ws, "error", {"msg": "Out of movement — Dash or End Turn"})
                break
            if not legal:
                stop_reason = "path_blocked"
                if mover_ws is not None:
                    await send_to(mover_ws, "error", {"msg": "Your path was blocked"})
                break
            if old_floor != fl:
                await send_property_to_interested(room_id, tok, "token_floor",
                                                  {"token_id": token_id, "floor": fl})
            await broadcast_token_step(room_id, tok, x, y, cell[0], cell[1])
            if has_riders:
                await carry_riders(room_id, token_id)
            reveals = tok["owner_user_id"] is not None
            async with map_lock(room_id):
                mp = get_map(room_id, fl)
                visible, _ = _reveal_player_token(mp, tok)
                newly = mapmodel.reveal_cells(mp, visible) if reveals else []
                map_dirty = False
                trap = at_cell(mp["traps"], *cell)
                if trap and not trap.get("triggered"):
                    trap["discovered"] = True
                    set_map(room_id, mp, fl)
                    stop_reason = "trap" if await hit_trap(room_id, tok, trap) else stop_reason
                    map_dirty = True
                loot = at_cell(mp["loot"], *cell)
                if loot and loot.get("taken_by") is None:
                    if await take_loot(room_id, tok, loot):
                        map_dirty = True
                if newly or map_dirty:
                    set_map(room_id, mp, fl)
            if newly:
                await send_to_plane_viewed(room_id, fl, "explored", fog_patch(mp, newly, fl))
            if map_dirty:
                await broadcast(room_id, "map_changed", None)
            if stop_reason:
                break
            if i < len(path) - 1:
                await asyncio.sleep(STEP_DELAY)
        await _announce_move(room_id, token_id, False, stop_reason)
        _moved = db.q1("SELECT * FROM tokens WHERE id=?", (token_id,))
        if _moved is not None:
            from .grapple import end_grapples_out_of_reach
            await end_grapples_out_of_reach(room_id, _moved)
        if spent:
            updated = CB.spend_move(room_id, token_id, spent, mode=mode)
            if updated is not None:
                await broadcast(room_id, "initiative", updated)
        if stop_reason is None:
            final = db.q1("SELECT * FROM tokens WHERE id=?", (token_id,))
            if final is not None:
                await maybe_grow_map(room_id, final)
    except asyncio.CancelledError:
        await _announce_move(room_id, token_id, False, "cancelled")
        raise


async def walk(room_id, token_id, path, mover_ws=None, budget=None, mode="walk",
               strained=False):
    stop_reason = None
    spent = 0
    has_riders = _carries_riders(token_id)          # D83: carry check, once per walk
    try:
        for i, (cx, cy) in enumerate(path):
            tok = db.q1("SELECT * FROM tokens WHERE id=?", (token_id,))
            if tok is None or tok["room_id"] != room_id:
                return
            # A token that dropped to 0 HP or became incapacitated mid-walk
            # (trap on the route, condition applied between steps) must not
            # finish the trip: the same authoritative gate as move/preview
            # applies to every step.
            downed = _movement_block_reason(tok)
            if downed:
                stop_reason = "downed"
                if mover_ws is not None:
                    await send_to(mover_ws, "error", {"msg": downed})
                break
            # Revalidate against the CURRENT world before committing the step. Door,
            # wall and map edits hold this same map_lock, so validation + the position
            # write are atomic against them: a route valid when the walk began can no
            # longer carry the token through geometry that became illegal mid-walk.
            async with map_lock(room_id):
                mp = get_map(room_id, tok.get("floor") or "")   # D88 plane
                from_origin, side = footprint.occupied_origin(mp, tok)
                legal = step_legal(mp, from_origin, (cx, cy),
                                   blocked_edges=mapmodel.blocked_edges(mp), footprint=side,
                                   mode=mode)
                if legal and budget is not None:
                    step_c = movecost.route_cost(mp, [from_origin, (cx, cy)], side, mode=mode, strained=strained)
                    if spent + step_c > budget:
                        stop_reason = "budget"        # the turn's movement is spent
                        legal = False
                    else:
                        spent += step_c
                if legal:
                    x, y = (cx + .5) * mp["cell"], (cy + .5) * mp["cell"]
                    db.x("UPDATE tokens SET x=?, y=?, z=? WHERE id=?",
                         (x, y, _cell_elev(mp, cx, cy), token_id))
                    tok["x"], tok["y"] = x, y
            if stop_reason == "budget":
                if mover_ws is not None:
                    await send_to(mover_ws, "error", {"msg": "Out of movement — Dash or End Turn"})
                break
            if not legal:
                stop_reason = "path_blocked"
                if mover_ws is not None:
                    await send_to(mover_ws, "error", {"msg": "Your path was blocked"})
                break
            await broadcast_token_step(room_id, tok, x, y, cx, cy)
            if has_riders:
                await carry_riders(room_id, token_id)   # riders track every step
            reveals = tok["owner_user_id"] is not None
            fl_walk = tok.get("floor") or ""                   # D88 plane
            async with map_lock(room_id):
                mp = get_map(room_id, fl_walk)
                visible, _ = _reveal_player_token(mp, tok)
                newly = mapmodel.reveal_cells(mp, visible) if reveals else []
                map_dirty = False
                trap = at_cell(mp["traps"], cx, cy)
                # One-shot re-entry gate: TRIGGERED (sprung), not discovered —
                # a detected-but-un-sprung trap still springs on a later step.
                if trap and not trap.get("triggered"):
                    # Persist discovery before hit_trap emits HP/snapshot events.
                    # Otherwise a refresh triggered during resolution can briefly
                    # reload the old hidden trap and make it appear to vanish.
                    trap["discovered"] = True
                    # D102: save the PLANE you walked — an un-floored save here
                    # clobbered the primary map with this plane's content.
                    set_map(room_id, mp, fl_walk)
                    stop_reason = "trap" if await hit_trap(room_id, tok, trap) else stop_reason
                    map_dirty = True
                loot = at_cell(mp["loot"], cx, cy)
                if loot and loot.get("taken_by") is None:
                    if await take_loot(room_id, tok, loot):
                        map_dirty = True
                if newly or map_dirty:
                    set_map(room_id, mp, fl_walk)
            if newly:
                await send_to_plane_viewed(room_id, fl_walk, "explored",
                                           fog_patch(mp, newly, fl_walk))
            if map_dirty:
                await broadcast(room_id, "map_changed", None)
            if stop_reason:
                break
            if i < len(path) - 1:
                await asyncio.sleep(STEP_DELAY)
        await _announce_move(room_id, token_id, False, stop_reason)
        # D112: a grappler that walked away is not itself grappled (so it CAN
        # move) — it releases every creature now beyond its reach. One check at
        # walk END; grappled creatures cannot walk at all (blocks_movement).
        _moved = db.q1("SELECT * FROM tokens WHERE id=?", (token_id,))
        if _moved is not None:
            from .grapple import end_grapples_out_of_reach
            await end_grapples_out_of_reach(room_id, _moved)
        if spent:                                  # charge the turn's move meter (D74,
            updated = CB.spend_move(room_id, token_id, spent, mode=mode)   # D83 per-mode)
            if updated is not None:
                await broadcast(room_id, "initiative", updated)
        # World growth happens at walk END (not per step): shifting the map
        # mid-walk would move the coordinate space under the remaining route.
        # Only VOLUNTARY arrivals grow the world — a walk forced to stop
        # (downed) is not a player approaching the edge (D67).
        if stop_reason is None:
            final = db.q1("SELECT * FROM tokens WHERE id=?", (token_id,))
            if final is not None:
                await maybe_grow_map(room_id, final)
    finally:
        if _walks.get(token_id) is asyncio.current_task():
            _walks.pop(token_id, None)


async def handle_stop_move(ws, room_id, user, is_dm, msg):
    if not is_dm:
        await send_to(ws, "error", {"msg": "DM only"})
        return
    try:
        tid = int(msg.get("token_id", -1))
    except (TypeError, ValueError):
        return
    tok = db.q1("SELECT * FROM tokens WHERE id=? AND room_id=?", (tid, room_id))
    if tok is None:
        return
    await _cancel_walk(tid)
    mp = get_map(room_id, tok.get("floor") or "")
    origin, side = footprint.occupied_origin(mp, tok)
    tok = db.q1("SELECT * FROM tokens WHERE id=?", (tid,)) or tok
    await broadcast_token_step(room_id, tok, tok["x"], tok["y"], origin[0], origin[1])
    await _announce_move(room_id, tid, False, "manual")


def _preview_allowed_cells(mp, room_id, user, is_dm, floor=""):
    if is_dm:
        return None
    # flat STORAGE indices (explored array / los) -> WORLD cells for path/footprint
    allowed = {mapmodel.world_of(mp, i % mp["w"], i // mp["w"])
               for i, explored in enumerate(mp["explored"]) if explored}
    allowed.update(mapmodel.world_of(mp, i % mp["w"], i // mp["w"]) for i in
                   viewer_visible_cells(room_id, user["id"], mp, floor=floor))
    return allowed


async def handle_path_preview(ws, room_id, user, is_dm, msg):
    tok = db.q1("SELECT * FROM tokens WHERE id=? AND room_id=?", (msg.get("token_id", -1), room_id))
    if tok is None:
        await send_to(ws, "error", {"msg": "Unknown token"})
        return
    if not authz.controls(tok, user["id"], is_dm):        # D82: owner or assigned controller
        await send_to(ws, "error", {"msg": "You can only preview your own token"})
        return
    blocked = _movement_block_reason(tok)
    if blocked:
        await send_to(ws, "error", {"msg": blocked})
        return
    try:
        tx, ty = int(msg["tx"]), int(msg["ty"])
    except (KeyError, ValueError, TypeError):
        await send_to(ws, "error", {"msg": "Invalid path preview"})
        return
    mode, why = _mode_or_error(tok, msg)                 # D83
    if why:
        await send_to(ws, "error", {"msg": why})
        return
    strained = _strained(tok, mode)                      # D144: SRD surcharge
    mp = get_map(room_id, tok.get("floor") or "")     # D88: the token's own plane
    origin, side = footprint.occupied_origin(mp, tok)
    # D84: clicked cell = desired CENTER; convert to the canonical anchor
    # (same single rule as handle_move — preview and execution must agree).
    goal_cx, goal_cy = tx, ty                       # the CENTER the player aimed at
    tx, ty = footprint.center_to_anchor((goal_cx, goal_cy), side)
    tx, ty = footprint.clamp_origin(mp, (tx, ty), side)          # WORLD clamp (D72)
    allowed = _preview_allowed_cells(mp, room_id, user, is_dm,
                                     floor=tok.get("floor") or "")
    if not footprint.valid_final_position(mp, tok, (tx, ty), _room_tokens(room_id, tok["id"], tok.get("floor") or ""), allowed, mode=mode):
        await send_to(ws, "error", {"msg": "No path there"})
        return
    path = find_path(mp, origin, (tx, ty),
                     blocked_edges=mapmodel.blocked_edges(mp), footprint=side,
                     allowed_cells=allowed, mode=mode)
    if path is None:
        await send_to(ws, "error", {"msg": "No path there"})
        return
    request_id = msg.get("request_id")
    try:
        request_id = int(request_id) if request_id is not None else None
    except (TypeError, ValueError):
        request_id = None
    speed = _speeds(tok).get(mode, 0) or _walk_speed(tok)
    budget = movecost.walk_budget(speed)                 # THE SSOT feet->squares
    cost = path_footprint_cost(mp, origin, path, side, mode=mode, strained=strained)
    # During combat a listed token spends its TURN's remaining movement, not
    # the raw speed (D74). None = economy does not apply (no combat/unlisted/DM).
    init = CB.get_init(room_id)
    remaining = CB.move_remaining(init, tok["id"], mode) if not is_dm else None
    eff_budget = budget if remaining is None else remaining
    await send_to(ws, "path_preview", {
        "request_id": request_id,
        "token_id": tok["id"],
        "size": tok["size"] or "Medium",
        "w": side[0], "h": side[1],                    # D81: authoritative preview shape
        "mode": mode,                                  # D83: the mode priced here
        "goal": {"cx": goal_cx, "cy": goal_cy},        # D84: the aimed CENTER cell
        "anchor": {"cx": tx, "cy": ty},                # D84: landing footprint anchor
        "path": [{"x": x, "y": y} for (x, y) in path],
        "cells": footprint.path_preview_cells(mp, side, [origin] + path),
        "cost": cost,
        "speed_ft": speed,
        "budget": budget,
        "move_remaining": eff_budget,
        "within_budget": cost <= eff_budget,
    })
