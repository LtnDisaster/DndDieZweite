"""Automatic map growth operation (D67, reworked by D72).

Server-authoritative and deterministic: PLAYER tokens approaching an edge grow
the world; hidden NPC/DM tokens approaching an edge never do (no oracle effect
— an NPC scouting the boundary must not leak that "there is more world").
Growth ONLY moves the storage window: world coordinates of every entity are
untouched (no DB writes, no token shifts, no in-flight-route invalidation).
New cells start as plain floor and UNEXPLORED, so players see only fog —
growing is not exploration and reveals nothing.
"""
from .. import footprint, mapmodel
from .net import broadcast, get_map, map_lock, set_map


async def maybe_grow_map(room_id, tok, vision=mapmodel.FOG_R):
    """Grow the room map when a PLAYER-controlled token is within
    ``vision + GROW_MARGIN`` WORLD cells of an edge (chunked, capped at
    MAX_W/MAX_H). Returns the directions grown (empty list = nothing happened).

    D77: automatic growth is feature-flagged OFF by default (manual testing
    found it unsafe to leave on without live browser verification). The whole
    mechanism below stays intact and fully tested; set DNDTABLE_AUTO_GROW=1 to
    re-enable. A stable fixed-size map beats a broken infinite one.

    Compute -> mutate map JSON in memory -> validate-by-construction -> persist
    -> broadcast. One atomic transition under ``map_lock``; no client can
    observe a half-grown world, and because world coordinates never move, even
    a client that misses the event converges on its next refetch."""
    if not mapmodel.AUTO_GROW:
        return []
    if tok.get("owner_user_id") is None:
        return []                       # NPC/DM tokens never trigger growth
    async with map_lock(room_id):
        mp = get_map(room_id)
        origin, side = footprint.occupied_origin(mp, tok)   # WORLD origin
        dirs = mapmodel.growth_needed(mp, origin, side, vision)
        if not dirs:
            return []
        grown, (_dx, _dy) = mapmodel.grow_map(mp, dirs)
        if grown is None:
            return []                   # at the documented world cap
        set_map(room_id, grown)
    await broadcast(room_id, "map_expanded", {"w": grown["w"], "h": grown["h"],
                                              "origin": grown["origin"]})
    return dirs
