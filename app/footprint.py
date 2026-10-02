"""Token footprint geometry: the single source of truth for size, anchor cells,
terrain placement, collision and preview cell projections.

A token's stored ``(x, y)`` remains the centre of its top-left occupied cell;
multi-cell footprints extend right and down from that anchor. This representation
keeps legacy 1x1 tokens unchanged while giving pathfinding and LOS a deterministic
footprint.
"""

FOOTPRINT = {
    "Tiny": 1,
    "Small": 1,
    "Medium": 1,
    "Large": 2,
    "Huge": 3,
    "Gargantuan": 4,
}


def side_for_size(size):
    return FOOTPRINT.get(str(size or "Medium").title(), 1)


def token_side(token):
    return side_for_size((token or {}).get("size"))


def origin_from_pixel(x, y, cell, w=0, h=0):
    cx = int(float(x) // float(cell or 50))
    cy = int(float(y) // float(cell or 50))
    if w and h:
        cx, cy = max(0, min(w - 1, cx)), max(0, min(h - 1, cy))
    return cx, cy


def origin_pixels(origin, side, cell):
    cx, cy = origin
    return ((cx + 0.5) * cell, (cy + 0.5) * cell)


def origin_cells(w, h, origin, side):
    """Return cells covered by an anchor, even when it intentionally overflows."""
    cx, cy = origin
    return [(cx + dx, cy + dy) for dy in range(side) for dx in range(side)]


def origin_in_bounds(w, h, origin, side):
    cx, cy = origin
    return 0 <= cx and 0 <= cy and cx + side <= w and cy + side <= h


def clamp_origin(w, h, origin, side):
    cx, cy = origin
    side = max(1, int(side))
    return (max(0, min(max(0, w - side), cx)),
            max(0, min(max(0, h - side), cy)))


def occupied_origin(mp, token):
    side = token_side(token)
    origin = origin_from_pixel(token["x"], token["y"], mp["cell"], mp["w"], mp["h"])
    return clamp_origin(mp["w"], mp["h"], origin, side), side


def occupied_cells(mp, token):
    origin, side = occupied_origin(mp, token)
    return set(origin_cells(mp["w"], mp["h"], origin, side))


def valid_terrain_position(mp, origin, side, allowed_cells=None):
    if not origin_in_bounds(mp["w"], mp["h"], origin, side):
        return False
    for (x, y) in origin_cells(mp["w"], mp["h"], origin, side):
        if not (0 <= x < mp["w"] and 0 <= y < mp["h"]) or mp["cells"][y * mp["w"] + x] == 1:
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
    side = token_side(token)
    if not valid_terrain_position(mp, origin, side, allowed_cells):
        return False
    cells = set(origin_cells(mp["w"], mp["h"], origin, side))
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
    side = token_side(token)
    clamped = clamp_origin(mp["w"], mp["h"], desired, side)
    if valid_final_position(mp, token, clamped, tokens, allowed_cells):
        return clamped
    for origin in candidate_origins(mp, desired, side):
        if valid_final_position(mp, token, origin, tokens, allowed_cells):
            return origin
    return None


def path_preview_cells(w, h, side, path_origins):
    out, seen = [], set()
    for origin in path_origins:
        for cell in origin_cells(w, h, origin, side):
            if not (0 <= cell[0] < w and 0 <= cell[1] < h) or cell in seen:
                continue
            seen.add(cell)
            out.append({"x": cell[0], "y": cell[1]})
    return out


def source_cells_for_tokens(mp, tokens):
    cells = set()
    for token in tokens:
        origin, side = occupied_origin(mp, token)
        cells.update(origin_cells(mp["w"], mp["h"], origin, side))
    return cells


def player_source_cells(mp, tokens):
    return source_cells_for_tokens(mp, [t for t in tokens if t.get("owner_user_id") is not None])
