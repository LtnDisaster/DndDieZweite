"""Pure A* pathfinding on a terrain grid. Cells: 0 floor, 1 wall, 2 difficult."""
import heapq

DIRS = [(1, 0, 10), (-1, 0, 10), (0, 1, 10), (0, -1, 10),
        (1, 1, 14), (1, -1, 14), (-1, 1, 14), (-1, -1, 14)]


def find_path(w, h, cells, start, goal, max_steps=400):
    """Return list of (x, y) from start (exclusive) to goal (inclusive), or None."""
    (sx, sy), (gx, gy) = start, goal
    if not (0 <= gx < w and 0 <= gy < h) or not (0 <= sx < w and 0 <= sy < h):
        return None
    gidx = gy * w + gx
    if cells[gidx] == 1:
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
            ni = ny * w + nx
            if cells[ni] == 1:
                continue
            if dx and dy and (cells[ny * w + x] == 1 or cells[y * w + nx] == 1):
                continue  # no corner cutting
            cost = base * 2 if cells[ni] == 2 else base
            ng = g[(x, y)] + cost
            if ng < g.get((nx, ny), 1e18):
                g[(nx, ny)] = ng
                came[(nx, ny)] = (x, y)
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
