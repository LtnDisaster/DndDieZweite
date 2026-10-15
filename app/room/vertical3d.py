"""D114 — cross-plane vertical geometry: the SINGLE reasoning point.

The `openv` layer (mapmodel) lets a stack of otherwise-independent planes
connect into vertical volumes. This module answers exactly three things and
NOTHING ELSE:

  * where does a token's vertical BODY reach (``body_planes``),
  * can a viewer SEE a target on another plane through an opening
    (``cross_plane_sight``),
  * is a target on another plane connected at all (``column_open``).

Same-plane line-of-sight, occupancy and 2D reach stay precisely as the existing
``los``/``footprint``/``path``/``dice`` engines compute them — this module never
reimplements 2D geometry, it only decides which planes are legitimately joined.

FAIL-CLOSED by construction: with no `openv` layer (or a solid ceiling), two
planes stay as independent as they were before D114 — no sight, no reach, no
protrusion. A wide creature is never pushed through a one-cell hole: a body only
occupies another plane when its WHOLE footprint fits an open column there and the
target cells are usable. Documented house rules: docs/VERTICAL_GEOMETRY.md.
"""
from .. import db, floors, footprint, mapmodel
from .net import get_map


def floor_list(room_id):
    room = db.q1("SELECT floors FROM rooms WHERE id=?", (room_id,))
    return [""] + floors.parse(room) if room else [""]


def level_map(room_id):
    """name -> level by declaration order (primary 0) — matches floors.level()."""
    return {name: i for i, name in enumerate(floor_list(room_id))}


def maps_for(room_id):
    return {name: get_map(room_id, name) for name in floor_list(room_id)}


def column_open(maps, lm, floor_a, floor_b, cell):
    """Unbroken vertical opening at WORLD ``cell`` between two planes: every
    adjacent plane pair between their levels carries openv=1 on its LOWER plane
    at that cell. Same plane -> True (no vertical travel)."""
    fa, fb = floor_a or "", floor_b or ""
    if fa not in lm or fb not in lm:
        return False                                # unregistered plane: fail closed
    la, lb = lm[fa], lm[fb]
    lo, hi = (la, lb) if la <= lb else (lb, la)
    names = list(maps)                                  # declaration order
    for level in range(lo, hi):
        if not mapmodel.openv_at(maps[names[level]], cell[0], cell[1]):
            return False
    return True


def _usable(maps, name, cells):
    """Every cell of ``cells`` is open VOLUME on plane ``name``. Void is open
    space; wall/barrier are physical obstruction. A body protrudes into an
    atrium/pit, but not through a wall."""
    mp = maps.get(name)
    if mp is None:
        return False
    return all(mapmodel.body_open(mapmodel.terrain_at(mp, x, y)) for (x, y) in cells)


def body_planes(room_id, token, maps=None, lm=None):
    """The set of floor NAMES a token's body segment physically occupies.

    The     home plane is always included. A higher plane is added only when the
    token's height band reaches its level, its WHOLE footprint has an open column
    across every intermediate plane, and the target plane is open volume under
    that footprint (void is air; wall/barrier block it)."""
    maps = maps if maps is not None else maps_for(room_id)
    lm = lm if lm is not None else {n: i for i, n in enumerate(maps)}
    home = token.get("floor") or ""
    if home not in lm:
        return {home}                              # unregistered plane joins nothing
    names = list(maps)
    home_map = maps.get(home) or get_map(room_id, home)
    foot = footprint.occupied_cells(home_map, token)
    out = {home}
    home_level = lm[home]
    for name, level in lm.items():
        if name == home or level not in floors.token_levels_spanned(room_id, token):
            continue
        lo, hi = min(home_level, level), max(home_level, level)
        connected = all(mapmodel.openv_at(maps[names[lvl]], x, y)
                        for lvl in range(lo, hi) for (x, y) in foot)
        if connected and _usable(maps, name, foot):
            out.add(name)
    return out


def cross_plane_sight(maps, lm, from_floor, to_floor, cell):
    """Straight vertical sight up/down a fully open column at WORLD ``cell``.
    (Diagonal cross-plane sight is deliberately out of scope — documented.)
    Same plane is normal 2D line-of-sight, not this path."""
    if (from_floor or "") == (to_floor or ""):
        return False
    return column_open(maps, lm, from_floor, to_floor, cell)


def body_cells(room_id, token, plane, maps=None, lm=None):
    """Cells on ``plane`` where the token's BODY physically reaches. Unlike
    ``observable_cells``, an open shaft alone does NOT place the body there."""
    maps = maps if maps is not None else maps_for(room_id)
    lm = lm if lm is not None else {n: i for i, n in enumerate(maps)}
    if (plane or "") in body_planes(room_id, token, maps, lm):
        home = token.get("floor") or ""
        return set(footprint.occupied_cells(maps.get(home) or get_map(room_id, home), token))
    return set()


def observable_cells(room_id, token, viewer_floor, maps=None, lm=None):
    """Cells on plane ``viewer_floor`` where ``token`` is observable — the ONE
    rule joining the two legitimate cross-plane phenomena:

      * same plane, or the token's BODY reaches this plane (protrusion) -> the
        full footprint (normal 2D line-of-sight then decides, as before D114);
      * otherwise the footprint cells that sit in an open vertical column down to
        the token's home plane (looking straight along a shaft / up through a hole).

    When the planes are not legitimately joined this returns the EMPTY set, so a
    token on another plane is EXACTLY as "elsewhere" as it was before D114 — the
    whole Sprint 19/20/21 cross-plane leak hardening is preserved by construction.
    The caller still runs the per-plane line-of-sight over these cells.
    """
    maps = maps if maps is not None else maps_for(room_id)
    lm = lm if lm is not None else {n: i for i, n in enumerate(maps)}
    home = token.get("floor") or ""
    vf = viewer_floor or ""
    home_map = maps.get(home) or get_map(room_id, home)
    foot = footprint.occupied_cells(home_map, token)
    if vf == home or vf in body_planes(room_id, token, maps, lm):
        return set(foot)
    return {cell for cell in foot if column_open(maps, lm, vf, home, cell)}


def occupied_volume(room_id, token, maps=None, lm=None):
    """The token's full BODY cells as ``(plane, x, y)`` pairs."""
    maps = maps if maps is not None else maps_for(room_id)
    lm = lm if lm is not None else {n: i for i, n in enumerate(maps)}
    out = set()
    for plane in body_planes(room_id, token, maps, lm):
        out.update((plane, x, y) for (x, y) in body_cells(room_id, token, plane, maps, lm))
    return out


def volume_terrain_clear(room_id, token, maps=None, lm=None):
    """Every plane touched by this token's current body has open volume under
    its whole footprint. Void is free air; wall/barrier stop it."""
    maps = maps if maps is not None else maps_for(room_id)
    lm = lm if lm is not None else {n: i for i, n in enumerate(maps)}
    return all(_usable(maps, plane, body_cells(room_id, token, plane, maps, lm))
               for plane in body_planes(room_id, token, maps, lm))


def vertical_path_clear(room_id, token, from_floor, to_floor, maps=None, lm=None):
    """The candidate token (whose ``floor`` is ``from_floor``) may move straight
    up/down between adjacent planes: its WHOLE footprint has an open column, and
    the destination plane is open volume."""
    maps = maps if maps is not None else maps_for(room_id)
    lm = lm if lm is not None else {n: i for i, n in enumerate(maps)}
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
    lm = lm if lm is not None else {n: i for i, n in enumerate(maps)}
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
