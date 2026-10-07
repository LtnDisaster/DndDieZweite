"""Token footprint geometry: the single source of truth for size, anchor cells,
terrain placement, collision and preview cell projections.

A token's stored ``(x, y)`` remains the centre of its top-left occupied cell;
the footprint extends right and down from that anchor. Footprints are
rectangular: ``width x height`` cells, derived by ``token_span`` — explicit
``fw``/``fh`` columns when set, otherwise the square side of the size category
(Large => 2x2). Every geometry function here takes either a legacy int (square,
kept for stored data and callers) or a ``(w, h)`` pair, so there is exactly ONE
rectangle derivation in the whole stack; no caller may compute footprint cells
from size on its own.
"""
from . import mapmodel

FOOTPRINT = {
    "Tiny": 1,
    "Small": 1,
    "Medium": 1,
    "Large": 2,
    "Huge": 3,
    "Gargantuan": 4,
}
SPAN_LIMIT = 10          # generous ceiling for custom width/height (D81)


def side_for_size(size):
    return FOOTPRINT.get(str(size or "Medium").title(), 1)


def clean_span(value):
    """Client-supplied footprint dimension -> int in 1..SPAN_LIMIT, or None."""
    if value is None or value == "":
        return None
    try:
        v = int(float(value))
    except (TypeError, ValueError):
        return None
    return min(SPAN_LIMIT, max(1, v))


def wh(side):
    """Accept a legacy int (square) or a (w, h) pair; always return (w, h)."""
    if isinstance(side, (tuple, list)):
        w, h = int(side[0]), int(side[1])
    else:
        w = h = int(side or 1)
    return max(1, w), max(1, h)


def token_side(token):
    return side_for_size((token or {}).get("size"))


def token_span(token):
    """THE authoritative footprint shape: (width, height) in cells. Explicit
    fw/fh columns win; None falls back to the square size-category side."""
    t = token or {}
    side = side_for_size(t.get("size"))
    try:
        w = int(t.get("fw")) if t.get("fw") else side
        h = int(t.get("fh")) if t.get("fh") else side
    except (TypeError, ValueError):
        return side, side
    return min(SPAN_LIMIT, max(1, w)), min(SPAN_LIMIT, max(1, h))


def origin_from_pixel(x, y, cell, mp=None):
    """Token WORLD pixel centre -> WORLD cell. Clamped to the world when an
    ``mp`` is given (D72: bounds are the WORLD window, never raw storage)."""
    cx = int(float(x) // float(cell or 50))
    cy = int(float(y) // float(cell or 50))
    if mp:
        cx, cy = clamp_origin(mp, (cx, cy), 1)
    return cx, cy


def origin_pixels(origin, side, cell):
    cx, cy = origin
    return ((cx + 0.5) * cell, (cy + 0.5) * cell)


def origin_cells(mp, origin, side):
    """WORLD cells covered by a WORLD anchor, even when it intentionally
    overflows. THE one rectangle derivation: ``side`` is an int or (w, h)."""
    cx, cy = origin
    w, h = wh(side)
    return [(cx + dx, cy + dy) for dy in range(h) for dx in range(w)]


def origin_in_bounds(mp, origin, side):
    """WORLD-space bounds check against the world window (D72)."""
    x0, y0, x1, y1 = mapmodel.world_bounds(mp)
    cx, cy = origin
    w, h = wh(side)
    return x0 <= cx and y0 <= cy and cx + w <= x1 and cy + h <= y1


def clamp_origin(mp, origin, side):
    x0, y0, x1, y1 = mapmodel.world_bounds(mp)
    cx, cy = origin
    w, h = wh(side)
    return (max(x0, min(max(x0, x1 - w), cx)),
            max(y0, min(max(y0, y1 - h), cy)))


def occupied_origin(mp, token):
    """(WORLD anchor, (w, h)) — the shared footprint for every consumer."""
    span = token_span(token)
    origin = origin_from_pixel(token["x"], token["y"], mp["cell"])
    return clamp_origin(mp, origin, span), span


def occupied_cells(mp, token):
    origin, side = occupied_origin(mp, token)
    return set(origin_cells(mp, origin, side))


def valid_terrain_position(mp, origin, side, allowed_cells=None):
    if not origin_in_bounds(mp, origin, side):
        return False
    for (x, y) in origin_cells(mp, origin, side):
        t = mapmodel.terrain_at(mp, x, y)          # WORLD cell (D72)
        if t is None or not mapmodel.walkable(t):
            return False
        if allowed_cells is not None and (x, y) not in allowed_cells:
            return False
    return True


def owner_key(token):
    owner = token.get("owner_user_id")
    if owner is not None:
        return ("user", owner)
    return ("token", token.get("id", -1))


def collision_cells(mp, tokens, token):
    """Occupied cells that this token may not finish inside.

    Same-user tokens may overlap, preserving intentional friendly pass-through.
    Ownerless monster tokens are distinct entities and block one another.
    """
    target_key = owner_key(token)
    occupied = set()
    for other in tokens:
        if other["id"] == token["id"] or owner_key(other) == target_key:
            continue
        occupied.update(occupied_cells(mp, other))
    return occupied


def valid_final_position(mp, token, origin, tokens=None, allowed_cells=None):
    side = token_span(token)
    if not valid_terrain_position(mp, origin, side, allowed_cells):
        return False
    cells = set(origin_cells(mp, origin, side))
    return not (cells & collision_cells(mp, tokens or [], token))


def candidate_origins(mp, desired, side, max_distance=None):
    """Deterministic spiral of top-left anchors, nearest first."""
    dx0, dy0 = desired
    radius = max_distance if max_distance is not None else max(mp["w"], mp["h"])
    yield (dx0, dy0)
    for radius_step in range(1, radius + 1):
        for dy in range(-radius_step, radius_step + 1):
            for dx in range(-radius_step, radius_step + 1):
                if max(abs(dx), abs(dy)) != radius_step:
                    continue
                yield (dx0 + dx, dy0 + dy)


def find_valid_origin(mp, token, desired, tokens=None, allowed_cells=None):
    side = token_span(token)
    clamped = clamp_origin(mp, desired, side)
    if valid_final_position(mp, token, clamped, tokens, allowed_cells):
        return clamped
    for origin in candidate_origins(mp, desired, side):
        if valid_final_position(mp, token, origin, tokens, allowed_cells):
            return origin
    return None


def path_preview_cells(mp, side, path_origins):
    out, seen = [], set()
    for origin in path_origins:
        for cell in origin_cells(mp, origin, side):
            if not mapmodel.in_world(mp, cell[0], cell[1]) or cell in seen:
                continue
            seen.add(cell)
            out.append({"x": cell[0], "y": cell[1]})   # WORLD cells on the wire
    return out


def source_cells_for_tokens(mp, tokens):
    cells = set()
    for token in tokens:
        origin, side = occupied_origin(mp, token)
        cells.update(origin_cells(mp, origin, side))
    return cells


def player_source_cells(mp, tokens):
    return source_cells_for_tokens(mp, [t for t in tokens if t.get("owner_user_id") is not None])
