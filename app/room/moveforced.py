"""Forced movement (D71): the DM pushes, pulls, shoves, knocks back, throws or
teleports a token against its owner's will.

Deliberately NOT a walk: forced movement never enters ``movement._walks``, never
spends the voluntary walk budget and never grows the world (world growth stays
a player-exploration feature). It reuses the same authoritative footprint and
terrain checks — a pushed creature stops at the first cell it cannot legally
occupy (wall, barrier, occupied square, cliff) and stays on the ground, so its
z follows the destination cell.

kinds: push | pull | shove | knockback | throw  -> move along a straight line
toward {tx,ty} as far as requested, stopping on obstacles.
       teleport -> exact destination, no obstacle pathfinding.
"""
from .. import db, footprint, mapmodel
from .movement import _cancel_walk, _carries_riders, _cell_elev, _reveal_player_token, carry_riders
from .net import broadcast, fog_patch, get_map, map_lock, send_to, set_map, sys_msg
from .visibility import broadcast_token_step

KINDS = ("push", "pull", "shove", "knockback", "throw", "teleport")
MAX_DISTANCE = 60                                          # generous hard cap (cells)


def _sign(v):
    return (v > 0) - (v < 0)


def line_cells(origin, dest):
    """King-move line from origin (exclusive) to dest (inclusive). The axis with
    the bigger remaining delta steps first, so diagonals shorten evenly."""
    x, y = origin
    tx, ty = dest
    out = []
    guard = abs(tx - x) + abs(ty - y) + 1
    while (x, y) != (tx, ty) and guard > 0:
        guard -= 1
        dx, dy = tx - x, ty - y
        if abs(dx) >= abs(dy):
            x += _sign(dx)
            if dy:
                y += _sign(dy)
        else:
            y += _sign(dy)
            if dx:
                x += _sign(dx)
        out.append((x, y))
    return out


def _resolve(mp, tok, kind, dest):
    """Farthest legal cell along the forced path (or the exact teleport cell).
    All cells are WORLD cells (D72); the clamp is the world window's."""
    origin, side = footprint.occupied_origin(mp, tok)
    tx, ty = footprint.clamp_origin(mp, dest, side)
    others = db.q("SELECT * FROM tokens WHERE room_id=? AND id!=?", (mp["room_id"], tok["id"]))
    candidates = [(tx, ty)] if kind == "teleport" else line_cells(origin, (tx, ty))[:MAX_DISTANCE]
    final, reached = origin, False
    for cell in candidates:
        if not footprint.valid_final_position(mp, tok, cell, others):
            break
        if kind != "teleport":
            if abs(_cell_elev(mp, cell[0], cell[1]) - _cell_elev(mp, final[0], final[1])) > 1:
                break                                      # cliff: the push stops before it
            final = cell
        else:
            final, reached = cell, True
            break
    return origin, final, reached


async def apply_forced_move(room_id, tok, kind, dest, notify_ws=None):
    """(D83) THE server-side forced-movement operation: validates through the
    same authoritative footprint/terrain checks, writes the position, carries
    riders, reveals for player-owned tokens and chronicles the event. NOT a
    walk: no voluntary-movement budget is consumed and the target's voluntary
    movement gate (downed/incapacitated) does not apply — forced movement is
    a different kind of thing. Traps and allowlisted interactions call THIS
    function server-side; it never trusts a client. Returns the final cell or
    None when nothing could legally change."""
    await _cancel_walk(tok["id"])
    async with map_lock(room_id):
        mp = get_map(room_id)
        mp = dict(mp)
        mp["room_id"] = room_id
        origin, final, reached = _resolve(mp, tok, kind, dest)
        if final == origin and not reached:
            return None
        cell = mp["cell"]
        x, y = (final[0] + .5) * cell, (final[1] + .5) * cell
        z = _cell_elev(mp, final[0], final[1])
        db.x("UPDATE tokens SET x=?, y=?, z=? WHERE id=?", (x, y, z, tok["id"]))
        tok["x"], tok["y"], tok["z"] = x, y, z
        await broadcast_token_step(room_id, tok, x, y, final[0], final[1])
        if _carries_riders(tok["id"]):
            await carry_riders(room_id, tok["id"])         # D83: a pushed mount carries
        if tok["owner_user_id"] is not None:               # only player-owned tokens reveal
            visible, _ = _reveal_player_token(mp, tok)
            newly = mapmodel.reveal_cells(mp, visible)
            if newly:
                set_map(room_id, mp)
                await broadcast(room_id, "explored", fog_patch(mp, newly))
        squares = max(abs(final[0] - origin[0]), abs(final[1] - origin[1]))
        verb = {"push": "pushes", "pull": "pulls", "shove": "shoves", "knockback": "knocks back",
                "throw": "throws", "teleport": "teleports"}[kind]
        sys_msg(room_id, f"DM {verb} {tok['label']} {squares} square(s) to "
                         f"{final[0]},{final[1]}.")
        if notify_ws is not None:
            await send_to(notify_ws, "forced_moved", {"token_id": tok["id"], "kind": kind,
                                                      "from": {"cx": origin[0], "cy": origin[1]},
                                                      "to": {"cx": final[0], "cy": final[1], "z": z}})
        return final


async def handle_forced_move(ws, room_id, user, is_dm, msg):
    if not is_dm:
        return await send_to(ws, "error", {"msg": "Forced movement is DM-only"})
    tok = db.q1("SELECT * FROM tokens WHERE id=? AND room_id=?",
                (msg.get("token_id", -1), room_id))
    if tok is None:
        return await send_to(ws, "error", {"msg": "Unknown token"})
    kind = msg.get("kind", "push")
    if kind not in KINDS:
        return await send_to(ws, "error", {"msg": "Unknown forced-move kind"})
    try:
        dest = (int(msg["tx"]), int(msg["ty"]))
    except (KeyError, ValueError, TypeError):
        return await send_to(ws, "error", {"msg": "Invalid forced-move destination"})
    if await apply_forced_move(room_id, tok, kind, dest, notify_ws=ws) is None:
        return await send_to(ws, "error", {"msg": "The target cannot be moved there"})
