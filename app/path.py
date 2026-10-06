"""Pure A* pathfinding on a terrain grid (D72: all cells are WORLD cells).

The grid representation intentionally remains pure. Footprint geometry is supplied
by the caller through ``footprint`` (an ``n x n`` side), so this module can validate
large-token movement without importing token/database models. Terrain lookups and
bounds go through mapmodel's world<->storage conversion — this module never
indexes the raw arrays itself.
"""
import heapq

from . import mapmodel, movecost

DIRS = [(1, 0, 10), (-1, 0, 10), (0, 1, 10), (0, -1, 10),
        (1, 1, 14), (1, -1, 14), (-1, 1, 14), (-1, -1, 14)]


def _cells(origin, side):
    cx, cy = origin
    return [(cx + dx, cy + dy) for dy in range(side) for dx in range(side)]


def _valid_origin(mp, origin, side, allowed_cells=None):
    if not mapmodel.in_world(mp, origin[0], origin[1]):
        return False
    for (x, y) in _cells(origin, side):
        t = mapmodel.terrain_at(mp, x, y)
        if t is None or not mapmodel.walkable(t):
            return False
        if allowed_cells is not None and (x, y) not in allowed_cells:
            return False
    return True


def _elev_passable(mp, old_cells, new_cells):
    """A newly covered cell may be entered only if at least one neighbouring
    (old or new) footprint cell is at most one elevation unit away (D70).
    Maps without an elev layer behave flat."""
    if not mp.get("elev"):
        return True
    for (x, y) in new_cells - old_cells:
        z = mapmodel.elev_at(mp, x, y)
        reach = [abs(z - mapmodel.elev_at(mp, nx, ny))
                 for (nx, ny) in (old_cells | new_cells)
                 if abs(nx - x) + abs(ny - y) == 1 and mapmodel.in_world(mp, nx, ny)]
        if reach and min(reach) > 1:
            return False
    return True


def _step_valid(mp, old, new, side, be, elev_layer=None):
    if not _valid_origin(mp, new, side):
        return False
    old_cells = {(x, y) for (x, y) in _cells(old, side) if mapmodel.in_world(mp, x, y)}
    new_cells = {(x, y) for (x, y) in _cells(new, side) if mapmodel.in_world(mp, x, y)}
    for (x, y) in new_cells - old_cells:
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            neighbor = (x - dx, y - dy)
            if neighbor in old_cells and frozenset((neighbor, (x, y))) in be:
                return False
    return _elev_passable(mp, old_cells, new_cells)


def _diagonal_valid(mp, old, new, side, be, elev_layer=None):
    dx = 1 if new[0] > old[0] else -1
    dy = 1 if new[1] > old[1] else -1
    mid_x = (old[0] + dx, old[1])
    mid_y = (old[0], old[1] + dy)
    return (_step_valid(mp, old, mid_x, side, be, elev_layer) and
            _step_valid(mp, mid_x, new, side, be, elev_layer) and
            _step_valid(mp, old, mid_y, side, be, elev_layer) and
            _step_valid(mp, mid_y, new, side, be, elev_layer))


def step_legal(mp, old, new, blocked_edges=None, footprint=1, elev=None):
    """True if moving the footprint square from WORLD origin ``old`` to WORLD
    ``new`` is legal on the CURRENT grid. Single source of truth shared with
    ``find_path``: bounds, walls, blocked edges (closed doors) for every newly
    entered footprint cell, and the conservative diagonal mid-cell rule. The
    ``elev`` parameter is accepted for call compatibility; the elevation layer
    is read from the authoritative map (D70/D72).
    """
    be = blocked_edges or set()
    side = max(1, int(footprint or 1))
    dx, dy = new[0] - old[0], new[1] - old[1]
    if max(abs(dx), abs(dy)) != 1:
        return False
    if dx and dy:
        return _diagonal_valid(mp, old, new, side, be)
    return _step_valid(mp, old, new, side, be)


def find_path(mp, start, goal, max_steps=400, blocked_edges=None,
              footprint=1, allowed_cells=None, elev=None):
    """Return list of ``(x, y)`` WORLD origins from start (exclusive) to goal
    (inclusive).

    ``blocked_edges`` is a set of frozenset({(x1,y1),(x2,y2)}) interior edges that
    may not be crossed. ``footprint`` is the creature's square side in cells. Large
    creatures move as their whole footprint; diagonal movement conservatively requires
    both orthogonal intermediate footprints to be legal.
    """
    be = blocked_edges or set()
    side = max(1, int(footprint or 1))
    (sx, sy), (gx, gy) = start, goal
    if not mapmodel.in_world(mp, gx, gy) or not mapmodel.in_world(mp, sx, sy):
        return None

    def valid_origin(origin):
        return _valid_origin(mp, origin, side, allowed_cells)

    def step_valid(old, new):
        return _step_valid(mp, old, new, side, be)

    def diagonal_valid(old, new):
        return _diagonal_valid(mp, old, new, side, be)

    def move_cost(old, new, base):
        if side == 1:
            return base * 2 if mapmodel.difficult(mapmodel.terrain_at(mp, new[0], new[1])) else base
        old_cells = {(x, y) for (x, y) in _cells(old, side) if mapmodel.in_world(mp, x, y)}
        new_cells = {(x, y) for (x, y) in _cells(new, side) if mapmodel.in_world(mp, x, y)}
        rough = any(mapmodel.difficult(mapmodel.terrain_at(mp, x, y)) for (x, y) in new_cells - old_cells)
        return base * 2 if rough else base

    if not valid_origin(goal):
        return None
    if start == goal:
        return []

    def hcost(x, y):
        dx, dy = abs(gx - x), abs(gy - y)
        return 10 * (dx + dy) + (14 - 20) * min(dx, dy)

    open_q = [(hcost(sx, sy), 0, sx, sy)]
    g = {(sx, sy): 0}
    came = {}
    tie = 0
    while open_q:
        _, _, x, y = heapq.heappop(open_q)
        if (x, y) == (gx, gy):
            break
        for dx, dy, base in DIRS:
            nx, ny = x + dx, y + dy
            if not mapmodel.in_world(mp, nx, ny):
                continue
            new = (nx, ny)
            if dx and dy:
                if not diagonal_valid((x, y), new):
                    continue
            elif not step_valid((x, y), new):
                continue
            cost = move_cost((x, y), new, base)
            ng = g[(x, y)] + cost
            if ng < g.get(new, 1e18):
                g[new] = ng
                came[new] = (x, y)
                tie += 1
                heapq.heappush(open_q, (ng + hcost(nx, ny), tie, nx, ny))
    else:
        return None

    path, node = [], (gx, gy)
    while node != (sx, sy):
        path.append(node)
        node = came[node]
    path.reverse()
    return path if len(path) <= max_steps else None


def path_footprint_cost(mp, start, path, footprint=1):
    """Movement-cost units over an executed route — canonical 5e rule, see
    app/movecost.py (SSOT): orthogonal 1, difficult 2, diagonals 1, 2, 1, 2..."""
    return movecost.route_cost(mp, [start] + list(path), footprint)
