"""Grid movement: DM teleport and animated A* walks, with LOS reveal + trap/loot checks.

Map read-modify-write (reveal, trap/loot flag flip, persist) is serialised per room
by net.map_lock so concurrent walks of different tokens can't clobber each other.
"""
import asyncio

from .. import conditions as C
from .. import db, footprint, gear, los, mapmodel, movecost
from ..path import find_path, path_footprint_cost, step_legal
from .growth import maybe_grow_map
from . import authz, combat as CB
from .net import broadcast, fog_patch, get_map, map_lock, send_to, set_map
from .traps import at_cell, hit_trap, take_loot
from .visibility import broadcast_token_step, viewer_visible_cells

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
    await broadcast(room_id, "move_state", payload)


def _room_tokens(room_id, exclude_id=None):
    return [t for t in db.q("SELECT id, x, y, owner_user_id, size, fw, fh, rot, mount_token_id FROM tokens WHERE room_id=?",
                            (room_id,)) if t["id"] != exclude_id]


def _reveal_player_token(mp, tok):
    if tok["owner_user_id"] is None:
        return [], mp
    return los.visible_cells(mp, footprint.player_source_cells(mp, [tok]), radius=mapmodel.FOG_R), mp


def _cell_elev(mp, cx, cy):
    """Integer elevation unit of one WORLD cell (0 = ground; D70)."""
    return mapmodel.elev_at(mp, cx, cy)


def _speeds(tok):
    """All movement allowances in feet — always through gear.clean_speeds (SSOT)."""
    if tok["character_id"]:
        return gear.clean_speeds(db.q1("SELECT speed FROM characters WHERE id=?",
                                       (tok["character_id"],)))
    return gear.clean_speeds(db.j(tok["npc"]) if tok["npc"] else {})


def _walk_speed(tok):
    """Walk speed in feet (legacy single-mode entry point)."""
    return _speeds(tok)["walk"]


MODES = ("walk", "fly", "swim", "climb")


def _mode_or_error(tok, msg):
    """(D83) One active mode per movement operation. Unknown mode words fall
    back to walk; a mode the creature does not have is refused — no silent
    substitution, no fake terrain rules for swim/climb yet."""
    mode = str(msg.get("mode") or "walk").lower()
    if mode not in MODES:
        mode = "walk"
    if mode != "walk" and _speeds(tok).get(mode, 0) <= 0:
        return None, f"This creature has no {mode} speed"
    return mode, None


MOVE_BLOCKED_CONDS = {"incapacitated", "unconscious", "paralyzed", "stunned",
                      "petrified"}    # the incapacitated family (D80) — the
# restrained/grappled family deliberately is NOT here: those need their own
# mechanics (out of scope) and must not be silently turned into a movement ban.


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
    mp = get_map(room_id)
    parent = db.q1("SELECT * FROM tokens WHERE id=?", (token_id,))
    if parent is None:
        return
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
    hit = {c["k"].lower() for c in C.load(tok)} & MOVE_BLOCKED_CONDS
    if hit:
        return f"You cannot move while {C.label(sorted(hit)[0]).lower()}"
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
    mp = get_map(room_id)
    cell = mp["cell"]
    try:
        tx, ty = int(msg["tx"]), int(msg["ty"])
    except (KeyError, ValueError, TypeError):
        return
    origin, side = footprint.occupied_origin(mp, tok)
    tx, ty = footprint.clamp_origin(mp, (tx, ty), side)          # WORLD clamp (D72)
    tokens = _room_tokens(room_id, tok["id"])

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
            async with map_lock(room_id):
                mp = get_map(room_id)
                visible, _ = _reveal_player_token(mp, tok)
                newly = mapmodel.reveal_cells(mp, visible)
                if newly:
                    set_map(room_id, mp)
            if newly:
                await broadcast(room_id, "explored", fog_patch(mp, newly))
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
    if not footprint.valid_final_position(mp, tok, (tx, ty), tokens):
        await send_to(ws, "error", {"msg": "That token footprint cannot finish there"})
        return

    await _cancel_walk(tok["id"])
    _walks[tok["id"]] = asyncio.create_task(walk(room_id, tok["id"], path, mover_ws=ws,
                                                 budget=budget, mode=mode))
    await _announce_move(room_id, tok["id"], True)


async def walk(room_id, token_id, path, mover_ws=None, budget=None, mode="walk"):
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
                mp = get_map(room_id)
                from_origin, side = footprint.occupied_origin(mp, tok)
                legal = step_legal(mp, from_origin, (cx, cy),
                                   blocked_edges=mapmodel.blocked_edges(mp), footprint=side,
                                   mode=mode)
                if legal and budget is not None:
                    step_c = movecost.route_cost(mp, [from_origin, (cx, cy)], side, mode=mode)
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
            async with map_lock(room_id):
                mp = get_map(room_id)
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
                    set_map(room_id, mp)
                    stop_reason = "trap" if await hit_trap(room_id, tok, trap) else stop_reason
                    map_dirty = True
                loot = at_cell(mp["loot"], cx, cy)
                if loot and loot.get("taken_by") is None:
                    if await take_loot(room_id, tok, loot):
                        map_dirty = True
                if newly or map_dirty:
                    set_map(room_id, mp)
            if newly:
                await broadcast(room_id, "explored", fog_patch(mp, newly))
            if map_dirty:
                await broadcast(room_id, "map_changed", None)
            if stop_reason:
                break
            if i < len(path) - 1:
                await asyncio.sleep(STEP_DELAY)
        await _announce_move(room_id, token_id, False, stop_reason)
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
    mp = get_map(room_id)
    origin, side = footprint.occupied_origin(mp, tok)
    tok = db.q1("SELECT * FROM tokens WHERE id=?", (tid,)) or tok
    await broadcast_token_step(room_id, tok, tok["x"], tok["y"], origin[0], origin[1])
    await _announce_move(room_id, tid, False, "manual")


def _preview_allowed_cells(mp, room_id, user, is_dm):
    if is_dm:
        return None
    # flat STORAGE indices (explored array / los) -> WORLD cells for path/footprint
    allowed = {mapmodel.world_of(mp, i % mp["w"], i // mp["w"])
               for i, explored in enumerate(mp["explored"]) if explored}
    allowed.update(mapmodel.world_of(mp, i % mp["w"], i // mp["w"]) for i in
                   viewer_visible_cells(room_id, user["id"], mp))
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
    mp = get_map(room_id)
    origin, side = footprint.occupied_origin(mp, tok)
    tx, ty = footprint.clamp_origin(mp, (tx, ty), side)          # WORLD clamp (D72)
    allowed = _preview_allowed_cells(mp, room_id, user, is_dm)
    if not footprint.valid_final_position(mp, tok, (tx, ty), _room_tokens(room_id, tok["id"]), allowed):
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
    cost = path_footprint_cost(mp, origin, path, side, mode=mode)
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
        "goal": {"cx": tx, "cy": ty},
        "path": [{"x": x, "y": y} for (x, y) in path],
        "cells": footprint.path_preview_cells(mp, side, [origin] + path),
        "cost": cost,
        "speed_ft": speed,
        "budget": budget,
        "move_remaining": eff_budget,
        "within_budget": cost <= eff_budget,
    })
