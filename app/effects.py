"""Generic ability/effect geometry — engine structure, no spell content (D54).

The pure cell-coverage math behind area abilities, independent of any named
spell, item or monster: an effect is described by

    shape (point | line | cone | circle | square) + size + origin + direction

and resolved against a map rectangle. Future ability fields (range, save,
damage expression, damage type, condition, duration, concentration) attach
HERE as data — not to spell names, and not to the visual relay path
(``app/room/aoe.py``, which stays presentation-only per D30; no game
resolution happens here either today).

The rules deliberately mirror the client-side ``aoeCells`` in ``10_core.js``
so server and preview agree; ``tests/test_effects.py`` locks that parity in a
Node ``vm``. Callers get cell indices (``y * w + x``), clipped to the map.
"""

SHAPES = ("point", "line", "cone", "circle", "square")
DIRV = {"N": (0, -1), "NE": (1, -1), "E": (1, 0), "SE": (1, 1),
        "S": (0, 1), "SW": (-1, 1), "W": (-1, 0), "NW": (-1, -1)}
# Same tolerance the client uses: half-cell grace on the radius edge, 45° cone.
_EDGE_EPS = 0.4
_COS_45 = 0.7071067811865476  # math.sqrt(0.5) == Math.SQRT1_2


def effect_cells(shape, size, x, y, w, h, direction="E") -> list:
    """Cell indices covered by an effect of `shape`/`size` at (x, y) on a
    w×h map. Deterministic, order-stable (sorted), boundary-clipped."""
    shape = str(shape or "").lower()
    if shape not in SHAPES:
        shape = "circle"
    try:
        R = max(0, round(int(size)))
    except (TypeError, ValueError):
        R = 0
    try:
        cx, cy = int(x), int(y)
    except (TypeError, ValueError):
        return []
    d = DIRV.get(str(direction or "E").upper(), DIRV["E"])
    out = set()

    def push(px, py):
        if 0 <= px < w and 0 <= py < h:
            out.add(py * w + px)

    if shape == "point":
        push(cx, cy)
    elif shape == "line":
        for t in range(0, R + 1):
            push(cx + d[0] * t, cy + d[1] * t)
    elif shape == "cone":
        import math
        dl = math.hypot(d[0], d[1]) or 1.0
        for dy in range(-R, R + 1):
            for dx in range(-R, R + 1):
                r = math.hypot(dx, dy)
                if r > R + _EDGE_EPS:
                    continue
                # ``>`` not ``>=``: exact-45° edge cells are mathematical ties whose
                # float comparison is libm-dependent; the shipped client preview
                # (Math.hypot) excludes them, so the server excludes them too —
                # preview and future resolution must agree cell for cell.
                if r == 0 or (dx * d[0] + dy * d[1]) / (r * dl) > _COS_45:
                    push(cx + dx, cy + dy)
    else:  # circle / square
        import math
        for dy in range(-R, R + 1):
            for dx in range(-R, R + 1):
                if shape == "circle" and math.hypot(dx, dy) > R + _EDGE_EPS:
                    continue
                push(cx + dx, cy + dy)
    return sorted(out)
