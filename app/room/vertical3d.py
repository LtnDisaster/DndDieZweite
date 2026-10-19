"""D114/D159 — cross-plane vertical geometry: the SINGLE reasoning point.

The `openv` layer plus the D159 `air`/floor material decide how a stack of
storeys joins into one volume. This module answers exactly:

  * where does a token's vertical BODY reach (``body_planes``),
  * can a viewer SEE a target on another plane (``observable_cells`` — a token
    is seen where its open column meets a plane the viewer can see into),
  * is a column/segment physically open (``column_open`` / ``ray_clear_3d``),
  * may a body move up/down (``vertical_path_clear``).

D159 model (docs/VERTICAL_GEOMETRY.md):
  * a laid floor (or wall) is a MASSIVE SLAB — it caps the storey below and
    blocks sight and vertical movement through its surface;
  * `air` (the default of every non-primary plane) and `void` (a pit) are OPEN —
    light, sight and flight carry through;
  * `openv` stays the explicit opening (stair / trapdoor) that punches a hole in
    an otherwise solid slab;
  * levels are SIGNED (a cellar is -1), and adjacency is by LEVEL, not by list
    position.

Same-plane line-of-sight, occupancy and 2D reach stay exactly as the existing
``los``/``footprint``/``path``/``dice`` engines compute them — this module never
reimplements 2D geometry, it only decides which planes are legitimately joined.

FAIL-CLOSED by construction: an unregistered plane, a gap level, or a solid slab
joins nothing — no sight, no reach, no protrusion — so a token behind a laid
floor is EXACTLY as "elsewhere" as before D114. A wide creature is never pushed
through a one-cell hole: a body only occupies another plane when its WHOLE
footprint has an open column there and the target cells are usable.
"""
from .. import db, floors, footprint, mapmodel
from .net import get_map

# A sight/flight ray never spans more storeys than the world can hold, nor
# reaches further horizontally than a torch sees — the ray is BOUNDED so it is
# O(1) per pair regardless of map size (hobby-table scale: a handful of planes).
MAX_LEVEL_SPAN = floors.MAX_FLOORS + 2


def floor_list(room_id):
    """The full vertical stack including the primary "" in its true position,
    ordered bottom→top (levels ascending) — D159 signed levels."""
    room = db.q1("SELECT floors FROM rooms WHERE id=?", (room_id,))
    return floors.order(room) if room else [""]


def level_map(room_id):
    """name -> SIGNED level (primary 0). Matches floors.level()."""
    room = db.q1("SELECT floors FROM rooms WHERE id=?", (room_id,))
    return floors.level_map(room) if room else {"": 0}


def maps_for(room_id):
    return {name: get_map(room_id, name) for name in floor_list(room_id)}


def _by_level(lm):
    return {lvl: name for name, lvl in lm.items()}


def boundary_open(maps, lower_name, upper_name, cell):
    """Is the shared surface between two ADJACENT levels open at WORLD ``cell``?
    The upper plane's cell is that storey's floor — a slab (floor/wall) caps the
    column unless an explicit opening (`openv` on the lower plane) is punched,
    or the upper cell is itself an opening (air / void)."""
    lo = maps.get(lower_name)
    up = maps.get(upper_name)
    if lo is None or up is None:
        return False                              # unregistered plane: fail closed
    x, y = cell
    if mapmodel.openv_at(lo, x, y):
        return True                               # explicit opening beats a slab
    return not mapmodel.slab(mapmodel.terrain_at(up, x, y))


def column_open(maps, lm, floor_a, floor_b, cell):
    """Unbroken vertical openness at WORLD ``cell`` between two planes: every
    adjacent level between theirs is an open boundary (a laid slab stops it).
    Same plane -> True (no vertical travel). Levels are signed and adjacent by
    level value; a gap with no registered plane fails closed."""
    fa, fb = floor_a or "", floor_b or ""
    if fa not in lm or fb not in lm:
        return False                                # unregistered plane: fail closed
    la, lb = lm[fa], lm[fb]
    if la == lb:
        return True
    lo, hi = (la, lb) if la < lb else (lb, la)
    if hi - lo > MAX_LEVEL_SPAN:
        return False
    names = _by_level(lm)
    for lvl in range(lo, hi):
        lower, upper = names.get(lvl), names.get(lvl + 1)
        if lower is None or upper is None:
            return False                            # gap with no plane: fail closed
        if not boundary_open(maps, lower, upper, cell):
            return False
    return True


def _usable(maps, name, cells):
    """Every cell of ``cells`` is open VOLUME on plane ``name``. Air and void are
    free space; a walkable floor is body-open but a wall/barrier is not. A body
    protrudes into an atrium/pit, but not through a wall."""
    mp = maps.get(name)
    if mp is None:
        return False
    return all(mapmodel.body_open(mapmodel.terrain_at(mp, x, y)) for (x, y) in cells)


def body_planes(room_id, token, maps=None, lm=None):
    """The set of floor NAMES a token's body segment physically occupies.

    The home plane is always included. A higher/lower plane is added only when the
    token's height band reaches its level, its WHOLE footprint has an open column
    across every intermediate boundary, and the target plane is open volume under
    that footprint (air/void is free; wall/barrier blocks it)."""
    maps = maps if maps is not None else maps_for(room_id)
    lm = lm if lm is not None else level_map(room_id)
    home = token.get("floor") or ""
    if home not in lm:
        return {home}                              # unregistered plane joins nothing
    home_map = maps.get(home) or get_map(room_id, home)
    foot = footprint.occupied_cells(home_map, token)
    out = {home}
    for name, level in lm.items():
        if name == home or level not in floors.token_levels_spanned(room_id, token):
            continue
        if not all(column_open(maps, lm, home, name, cell) for cell in foot):
            continue
        if _usable(maps, name, foot):
            out.add(name)
    return out


def cross_plane_sight(maps, lm, from_floor, to_floor, cell):
    """Straight vertical sight up/down an open column at WORLD ``cell``. Same
    plane is normal 2D line-of-sight, not this path. Diagonal sight is decided by
    ``ray_clear_3d`` / ``cross_plane_seen`` (D159)."""
    if (from_floor or "") == (to_floor or ""):
        return False
    return column_open(maps, lm, from_floor, to_floor, cell)


def body_cells(room_id, token, plane, maps=None, lm=None):
    """Cells on ``plane`` where the token's BODY physically reaches. Unlike
    ``observable_cells``, an open shaft alone does NOT place the body there."""
    maps = maps if maps is not None else maps_for(room_id)
    lm = lm if lm is not None else level_map(room_id)
    if (plane or "") in body_planes(room_id, token, maps, lm):
        home = token.get("floor") or ""
        return set(footprint.occupied_cells(maps.get(home) or get_map(room_id, home), token))
    return set()


def observable_cells(room_id, token, viewer_floor, maps=None, lm=None):
    """Cells on plane ``viewer_floor`` where ``token`` is observable — the ONE
    rule joining the two legitimate cross-plane phenomena:

      * same plane, or the token's BODY reaches this plane (protrusion) -> the
        full footprint (normal 2D line-of-sight then decides, as before D114);
      * otherwise the footprint cells that sit in an open vertical column to the
        token's home plane (looking straight up/down an open shaft). D159: with
        the default open-air storeys that column is unobstructed unless a laid
        floor caps it.

    When the planes are not legitimately joined this returns the EMPTY set, so a
    token on another plane is EXACTLY as "elsewhere" as before D114 — the whole
    Sprint 19/20/21 cross-plane leak hardening is preserved by construction. The
    caller still runs the per-plane line-of-sight over these cells — so a viewer
    sees a cross-plane token exactly where an OPEN column of that token reaches a
    plane they can see into (looking up/down an open shaft or an open atrium).
    """
    maps = maps if maps is not None else maps_for(room_id)
    lm = lm if lm is not None else level_map(room_id)
    home = token.get("floor") or ""
    vf = viewer_floor or ""
    home_map = maps.get(home) or get_map(room_id, home)
    foot = footprint.occupied_cells(home_map, token)
    if vf == home or vf in body_planes(room_id, token, maps, lm):
        return set(foot)
    return {cell for cell in foot if column_open(maps, lm, vf, home, cell)}


# ---------------------------------------------------------------------------
# D159 — the real 3D ray: bounded, cached maps, no second geometry engine.
# A sight line between two storeys is a digital line through integer voxels
# (x, y, level). Within a level it is blocked by whatever 2D line-of-sight is
# blocked by (a wall / an out-of-world cell); crossing a level boundary is
# blocked by a laid slab unless an opening is present. Endpoints are never
# blockers. The span bounds keep this O(1).
# ---------------------------------------------------------------------------

def _ray_voxels(a, b):
    """Integer voxels on the 3D digital line a->b, ENDPOINTS EXCLUDED. Bounded by
    ``max_steps``; returns None when the pair is out of bound (caller fails
    closed)."""
    ax, ay, az = a
    bx, by, bz = b
    dx, dy, dz = bx - ax, by - ay, bz - az
    if abs(dz) > MAX_LEVEL_SPAN:
        return None
    steps = max(abs(dx), abs(dy), abs(dz))
    if steps == 0:
        return []
    out = []
    prev = None
    for k in range(1, steps):
        x = round(ax + dx * k / steps)
        y = round(ay + dy * k / steps)
        z = round(az + dz * k / steps)
        voxel = (x, y, z)
        if voxel != prev:
            out.append(voxel)
            prev = voxel
    return out


def ray_clear_3d(maps, lm, from_floor, from_cell, to_floor, to_cell):
    """True when a bounded 3D line from ``(from_floor, from_cell)`` to
    ``(to_floor, to_cell)`` is clear of blockers. Wall (or an out-of-world cell)
    blocks a level's slice; a laid slab blocks a level crossing. Same voxel -> True.
    Out of bound (span too great) -> False (fail closed)."""
    if from_floor not in lm or to_floor not in lm:
        return False
    names = _by_level(lm)
    a = (from_cell[0], from_cell[1], lm[from_floor])
    b = (to_cell[0], to_cell[1], lm[to_floor])
    voxels = _ray_voxels(a, b)
    if voxels is None:
        return False
    prev = a
    for (x, y, z) in voxels:
        name = names.get(z)
        mp = maps.get(name)
        if mp is None or not mapmodel.in_world(mp, x, y):
            return False                            # out of the world: fail closed
        if mapmodel.blocks_vision(mapmodel.terrain_at(mp, x, y)):
            return False                            # a wall cuts the ray
        if z != prev[2]:                             # crossed a level boundary
            lower, upper = (prev[2], z) if prev[2] < z else (z, prev[2])
            lo, up = names.get(lower), names.get(upper)
            if lo is None or up is None or abs(lower - upper) != 1:
                return False
            if not boundary_open(maps, lo, up, (x, y)):
                return False
        prev = (x, y, z)
    return True


def occupied_volume(room_id, token, maps=None, lm=None):
    """The token's full BODY cells as ``(plane, x, y)`` pairs."""
    maps = maps if maps is not None else maps_for(room_id)
    lm = lm if lm is not None else level_map(room_id)
    out = set()
    for plane in body_planes(room_id, token, maps, lm):
        out.update((plane, x, y) for (x, y) in body_cells(room_id, token, plane, maps, lm))
    return out


def volume_terrain_clear(room_id, token, maps=None, lm=None):
    """Every plane touched by this token's current body has open volume under
    its whole footprint. Air/void is free; wall/barrier stop it."""
    maps = maps if maps is not None else maps_for(room_id)
    lm = lm if lm is not None else level_map(room_id)
    return all(_usable(maps, plane, body_cells(room_id, token, plane, maps, lm))
               for plane in body_planes(room_id, token, maps, lm))


def vertical_path_clear(room_id, token, from_floor, to_floor, maps=None, lm=None):
    """The candidate token (whose ``floor`` is ``from_floor``) may move straight
    up/down between ADJACENT planes (adjacency is by signed LEVEL): its WHOLE
    footprint has an open column across the shared boundary, and the destination
    plane is open volume. Multi-storey flight is a chain of these steps (path.py
    does the A*), so free flight over several open storeys needs no special case."""
    maps = maps if maps is not None else maps_for(room_id)
    lm = lm if lm is not None else level_map(room_id)
    from_floor, to_floor = from_floor or "", to_floor or ""
    if from_floor == to_floor or lm.get(from_floor) is None or lm.get(to_floor) is None:
        return False
    if abs(lm[from_floor] - lm[to_floor]) != 1:
        return False
    foot = footprint.occupied_cells(maps.get(from_floor) or get_map(room_id, from_floor), token)
    return (_usable(maps, to_floor, foot)
            and all(column_open(maps, lm, from_floor, to_floor, cell) for cell in foot))


def volume_final_valid(room_id, token, tokens, maps=None, lm=None):
    """Whole-volume terrain + collision fit for a candidate token. It reuses
    the SAME owner/mount exemption semantics as footprint collision — no second
    collision rule."""
    maps = maps if maps is not None else maps_for(room_id)
    lm = lm if lm is not None else level_map(room_id)
    if not volume_terrain_clear(room_id, token, maps, lm):
        return False
    by_id = {t["id"]: t for t in tokens}
    by_id.setdefault(token["id"], token)
    target_chain = footprint.mount_chain_ids(token, by_id)
    target_key = footprint.owner_key(token)
    target_cells = occupied_volume(room_id, token, maps, lm)
    for other in tokens:
        if other["id"] == token["id"] or footprint.owner_key(other) == target_key:
            continue
        if other["id"] in target_chain or target_chain & footprint.mount_chain_ids(other, by_id):
            continue
        if target_cells & occupied_volume(room_id, other, maps, lm):
            return False
    return True
