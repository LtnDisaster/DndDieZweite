"""Pure A* pathfinding on a terrain grid. Cells: 0 floor, 1 wall, 2 difficult.

The grid representation intentionally remains pure. Footprint geometry is supplied
by the caller through ``footprint`` (an ``n x n`` side), so this module can validate
large-token movement without importing token/database models.
"""
import heapq

DIRS = [(1, 0, 10), (-1, 0, 10), (0, 1, 10), (0, -1, 10),
        (1, 1, 14), (1, -1, 14), (-1, 1, 14), (-1, -1, 14)]


def _cells(w, h, origin, side):
    cx, cy = origin
    return [(cx + dx, cy + dy) for dy in range(side) for dx in range(side)]


def find_path(w, h, cells, start, goal, max_steps=400, blocked_edges=None,
              footprint=1, allowed_cells=None):
    """Return list of ``(x, y)`` origins from start (exclusive) to goal (inclusive).

    ``blocked_edges`` is a set of frozenset({(x1,y1),(x2,y2)}) interior edges that
    may not be crossed. ``footprint`` is the creature's square side in cells. Large
    creatures move as their whole footprint; diagonal movement conservatively requires
    both orthogonal intermediate footprints to be legal.
    """
    be = blocked_edges or set()
    side = max(1, int(footprint or 1))
    (sx, sy), (gx, gy) = start, goal
    if not (0 <= gx < w and 0 <= gy < h) or not (0 <= sx < w and 0 <= sy < h):
        return None

    def valid_origin(origin, require_bounds=True):
        if require_bounds and not (0 <= origin[0] < w and 0 <= origin[1] < h):
            return False
        for (x, y) in _cells(w, h, origin, side):
            if not (0 <= x < w and 0 <= y < h) or cells[y * w + x] == 1:
                return False
            if allowed_cells is not None and (x, y) not in allowed_cells:
                return False
        return True

    def edge_blocked(a, b):
        return frozenset((a, b)) in be

    def step_valid(old, new):
        if not valid_origin(new):
            return False
        old_cells = {(x, y) for (x, y) in _cells(w, h, old, side) if 0 <= x < w and 0 <= y < h}
        new_cells = {(x, y) for (x, y) in _cells(w, h, new, side) if 0 <= x < w and 0 <= y < h}
        for (x, y) in new_cells - old_cells:
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                neighbor = (x - dx, y - dy)
                if neighbor in old_cells and edge_blocked(neighbor, (x, y)):
                    return False
        return True

    def diagonal_valid(old, new):
        dx = 1 if new[0] > old[0] else -1
        dy = 1 if new[1] > old[1] else -1
        mid_x = (old[0] + dx, old[1])
        mid_y = (old[0], old[1] + dy)
        return step_valid(old, mid_x) and step_valid(mid_x, new) and \
               step_valid(old, mid_y) and step_valid(mid_y, new)

    def move_cost(old, new, base):
        if side == 1:
            return base * 2 if cells[new[1] * w + new[0]] == 2 else base
        old_cells = {(x, y) for (x, y) in _cells(w, h, old, side) if 0 <= x < w and 0 <= y < h}
        new_cells = {(x, y) for (x, y) in _cells(w, h, new, side) if 0 <= x < w and 0 <= y < h}
        rough = any(cells[y * w + x] == 2 for (x, y) in new_cells - old_cells)
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
            if not (0 <= nx < w and 0 <= ny < h):
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


def path_footprint_cost(w, h, cells, start, path, footprint=1):
    """Movement-cost units matching the legacy UI: 1 per normal step, 2 difficult."""
    side = max(1, int(footprint or 1))
    total, previous = 0, start
    for origin in path:
        old = {(x, y) for (x, y) in _cells(w, h, previous, side) if 0 <= x < w and 0 <= y < h}
        new = {(x, y) for (x, y) in _cells(w, h, origin, side) if 0 <= x < w and 0 <= y < h}
        if side == 1:
            total += 2 if cells[origin[1] * w + origin[0]] == 2 else 1
        else:
            total += 2 if any(cells[y * w + x] == 2 for (x, y) in new - old) else 1
        previous = origin
    return total
