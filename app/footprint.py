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

D83: ROTATION ORIENTS THE ENTITY, so ``token_span`` returns the EFFECTIVE
oriented box — a 3x7 at rot 90/270 IS a 7x3 for every consumer (occupancy,
collision, A*, LOS, AoE). The stored ``fw``/``fh`` stay the BASE shape; the
anchor convention plus ``anchor_for_center`` keeps the conceptual centre stable
when the box turns. Visual bounds are oriented by the same rule, so visual and
mechanical bounds always share their centre.
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


def orient(span, rot):
    """(D83) A span seen through an entity orientation: 90/270 turn the box."""
    w, h = wh(span)
    try:
        r = int(rot or 0)
    except (TypeError, ValueError):
        r = 0
    return (h, w) if r % 180 == 90 else (w, h)


def base_span(token):
    """The UN-rotated stored shape (width, height). Only the rotation op and
    UIs that show base-vs-effective need this — gameplay never does."""
    t = token or {}
    side = side_for_size(t.get("size"))
    try:
        w = int(t.get("fw")) if t.get("fw") else side
        h = int(t.get("fh")) if t.get("fh") else side
    except (TypeError, ValueError):
        return side, side
    return min(SPAN_LIMIT, max(1, w)), min(SPAN_LIMIT, max(1, h))


def token_span(token):
    """THE authoritative footprint shape: the EFFECTIVE ORIENTED box (D83).
    Explicit fw/fh win over the size category, then the token's facing turns
    the box (rot 90/270 => width and height swapped). Every consumer of
    occupied_cells/origin automatically obeys rotation — no caller may
    swap-by-rot anywhere else."""
    return orient(base_span(token), (token or {}).get("rot"))


def oriented_span(token):
    """Intent-revealing alias of token_span (both THE effective box)."""
    return token_span(token)


def anchor_for_center(origin, outer, inner):
    """(D83) THE centre-preserving anchor rule, integer-only: the top-left
    anchor of ``inner`` placed so its centre matches ``outer``'s centre.
    Floor division is the tie-break: with mixed parities the centre shifts by
    at most half a cell toward the lower-right — deterministic, documented,
    and no floating-point world coordinates anywhere. Used for rotation
    re-anchoring AND carried riders."""
    ox, oy = origin
    ow, oh = wh(outer)
    iw, ih = wh(inner)
    return (ox + (ow - iw) // 2, oy + (oh - ih) // 2)


def center_to_anchor(cell, span):
    """(D84) THE pointer-destination rule. A clicked WORLD cell names where the
    player wants the entity CENTRE; return the canonical integer footprint
    ANCHOR (top-left cell) the oriented ``span`` must occupy so its centre
    lands on that cell. Exact for odd extents; even extents bias the centre to
    the lower-right half-cell — the same documented floor tie-break as
    ``anchor_for_center`` (placing a 1x1 inner box in an even outer box also
    shifts it (d-1)//2 down-right), so the two rules are one convention.
    Integer-only, deterministic, inverse of the centre a span projects to:
    ``span_at(anchor).centre`` rounds back onto ``cell``.
    This is THE conversion for every client-supplied destination
    (path_preview goal, move goal, DM teleport goal); nothing else may
    re-derive it, and the client must never pre-convert."""
    cx, cy = cell
    w, h = wh(span)
    return (cx - (w - 1) // 2, cy - (h - 1) // 2)


def visual_span(token):
    """THE authoritative VISUAL shape (D82, oriented by D83): explicit vw/vh
    win (turned by the same facing rule), otherwise the EFFECTIVE collision
    span — so every legacy token renders unchanged. RENDERING ONLY: occupancy,
    collision, A*, LOS and AoE never call this; their shape is token_span().
    Visual bounds must never silently become collision truth."""
    t = token or {}
    w0, h0 = base_span(t)
    try:
        vw = int(t.get("vw")) if t.get("vw") else w0
        vh = int(t.get("vh")) if t.get("vh") else h0
    except (TypeError, ValueError):
        vw, vh = w0, h0
    return orient((min(SPAN_LIMIT, max(1, vw)), min(SPAN_LIMIT, max(1, vh))),
                  t.get("rot"))


def clean_rot(value):
    """Client-supplied facing -> degrees in {0, 90, 180, 270}, or None.
    D83: the facing orients the WHOLE entity — token_span and visual_span turn
    with it. A rotation that would drive the oriented box into illegal ground
    is rejected by the rotation op, never sneakily relocated."""
    if value is None or value == "":
        return None
    try:
        v = int(float(value))
    except (TypeError, ValueError):
        return None
    v %= 360
    return v if v % 90 == 0 else None


def visual_cells(mp, token):
    """Presentation cells of the visual rect, CENTERED on the (oriented)
    mechanical footprint center (the one visual anchoring rule, D83).
    RENDER ONLY — callers that need gameplay truth use occupied_cells()."""
    origin, (w, h) = occupied_origin(mp, token)
    vw, vh = visual_span(token)
    cx = origin[0] + (w - vw) / 2
    cy = origin[1] + (h - vh) / 2
    out = []
    for dy in range(vh):
        for dx in range(vw):
            out.append((int(cx + dx), int(cy + dy)))
    return out


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


def mount_chain_ids(token, by_id, cap=16):
    """(D83) The token itself plus its mount ancestors — the carrying chain.
    Bounded and cycle-tolerant: tampered data loops stop at ``cap``."""
    out, cur, depth = set(), token, 0
    while cur is not None and depth <= cap:
        cid = cur.get("id")
        if cid in out:
            break
        out.add(cid)
        cur = by_id.get(cur.get("mount_token_id"))
        depth += 1
    return out


def collision_cells(mp, tokens, token):
    """Occupied cells that this token may not finish inside.

    Same-user tokens may overlap, preserving intentional friendly pass-through.
    Ownerless monster tokens are distinct entities and block one another.
    D83: a mount and its (transitive) riders are ONE moving entity for
    collision — a rider may never block its own mount's movement, and a
    carried rider's latent cells are the mount's validity to answer for.
    """
    target_key = owner_key(token)
    by_id = {t["id"]: t for t in tokens}
    by_id.setdefault(token["id"], token)
    target_chain = mount_chain_ids(token, by_id)
    occupied = set()
    for other in tokens:
        if other["id"] == token["id"] or owner_key(other) == target_key:
            continue
        if other["id"] in target_chain or target_chain & mount_chain_ids(other, by_id):
            continue                               # same mount/rider entity
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
