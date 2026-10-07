"""Canonical movement cost — D&D 5e grid rule (PHB p.183), the single source
of truth for what a route COSTS (as opposed to what it WEIGHTS).

5e diagonal rule: the first diagonal from a start point counts 1, every second
one counts 2, alternating 1, 2, 1, 2, ... along the run of movement.
Difficult terrain doubles the unit cost of the step that enters it
(orthogonal: 2; diagonal: 2 or 4 following the alternation).

Deliberately NOT used by the A* search: app/path.py keeps constant search
weights (10 straight / 14 diagonal). The 5e alternation is history-dependent
(counted from the route start), which a greedy search cannot optimise — the
displayed cost is therefore always computed over the final, concrete route.

A "unit" is one 5-foot square: budget in squares == speed_ft // SQ.
"""
SQ = 5                                                    # feet per square

DIAGONAL_UNITS = (1, 2)                                   # 1st diagonal: 1, 2nd: 2, 3rd: 1 ...


def diagonal_unit(index: int) -> int:
    """Cost unit of the (index+1)-th diagonal step, index is 0-based."""
    return DIAGONAL_UNITS[index % 2]


def terrain_mult(mp, x, y):
    """Difficult cells (mapmodel.TERRAIN registry: difficult terrain AND
    low obstacles) double the unit of the step entering them.
    ``x, y`` are WORLD cells; indexing is mapmodel's job (D72)."""
    from . import mapmodel
    t = mapmodel.terrain_at(mp, x, y)
    return 2 if (t is not None and mapmodel.difficult(t)) else 1


def route_cost(mp, route, footprint: int = 1):
    """5e cost of moving a footprint-sized token over `route` — WORLD cell
    origins starting WITH the current position, e.g. [origin] + path.

    Diagonals are classified by the origin shift and counted from the route
    start (never per segment). For footprints larger than one cell a step is
    difficult if any newly entered cell is difficult terrain."""
    from . import mapmodel
    from .footprint import wh
    w, h = wh(footprint)
    total = 0
    diag = 0
    for prev, cur in zip(route, route[1:]):
        dx, dy = cur[0] - prev[0], cur[1] - prev[1]
        if not (abs(dx) in (0, 1) and abs(dy) in (0, 1) and (dx or dy)):
            raise ValueError(f"route step is not a single king-move: {prev} -> {cur}")
        diagonal = dx != 0 and dy != 0
        if diagonal:
            unit = diagonal_unit(diag)
            diag += 1
        else:
            unit = 1
        if (w, h) == (1, 1):
            mult = terrain_mult(mp, cur[0], cur[1])
        else:
            new = {(x, y) for x in range(cur[0], cur[0] + w)
                   for y in range(cur[1], cur[1] + h)
                   if mapmodel.in_world(mp, x, y)}
            old = {(x, y) for x in range(prev[0], prev[0] + w)
                   for y in range(prev[1], prev[1] + h)
                   if mapmodel.in_world(mp, x, y)}
            mult = max([terrain_mult(mp, x, y) for (x, y) in new - old] or [1])
        total += unit * mult
    return total


def walk_budget(speed_ft) -> int:
    """Squares a token may spend with a given walk speed; 0 speed => no move."""
    try:
        return max(0, int(speed_ft) // SQ)
    except (TypeError, ValueError):
        return 30 // SQ
