"""Deterministic, conservative grid line-of-sight over the existing map model.

The map stores walls as blocked cells and doors as blocked edges. This module reuses
that representation exactly. Diagonal rays that pass exactly through a grid corner
require both relevant orthogonal transitions to be open, which prevents vision
through a sealed diagonal corner.
"""
from . import mapmodel


def _inside(w, h, x, y):
    return 0 <= x < w and 0 <= y < h


def _wall(mp, x, y):
    return mp["cells"][y * mp["w"] + x] == 1


def _edge_closed(a, b, blocked_edges):
    return frozenset((a, b)) in blocked_edges


def _cross(a, b, mp, blocked_edges, target=None):
    w, h = mp["w"], mp["h"]
    return (not _inside(w, h, b[0], b[1])
            or _edge_closed(a, b, blocked_edges)
            or (_wall(mp, b[0], b[1]) and b != target))


def line_of_sight(mp, source, target, blocked_edges=None):
    w, h = mp["w"], mp["h"]
    if not _inside(w, h, source[0], source[1]) or not _inside(w, h, target[0], target[1]):
        return False
    if source == target:
        return True
    be = blocked_edges if blocked_edges is not None else mapmodel.blocked_edges(mp)

    sx, sy = 2 * source[0] + 1, 2 * source[1] + 1
    tx, ty = 2 * target[0] + 1, 2 * target[1] + 1
    dx = 1 if tx > sx else (-1 if tx < sx else 0)
    dy = 1 if ty > sy else (-1 if ty < sy else 0)
    den_x = abs(tx - sx)
    den_y = abs(ty - sy)
    if den_x == 0 and den_y == 0:
        return True

    cx, cy = source
    nx, ny = 1, 1
    max_steps = abs(target[0] - source[0]) + abs(target[1] - source[1]) + 4
    for _ in range(max_steps):
        left = nx * den_y if dx else None
        right = ny * den_x if dy else None

        if left is not None and right is not None and left == right:
            old = (cx, cy)
            horiz, vert, diag = (cx + dx, cy), (cx, cy + dy), (cx + dx, cy + dy)
            corner_ok = (_inside(w, h, horiz[0], horiz[1])
                         and _inside(w, h, vert[0], vert[1])
                         and _inside(w, h, diag[0], diag[1])
                         and not _edge_closed(old, horiz, be)
                         and not _edge_closed(old, vert, be)
                         and (not _wall(mp, horiz[0], horiz[1]) or horiz == target)
                         and (not _wall(mp, vert[0], vert[1]) or vert == target))
            if not corner_ok:
                return False
            cx, cy = diag
            nx, ny = nx + 2, ny + 2
            if (cx, cy) == target:
                return True
            if _wall(mp, cx, cy):
                return False
        elif left is not None and (right is None or left < right):
            old = (cx, cy)
            cx += dx
            nx += 2
            if _cross(old, (cx, cy), mp, be, target):
                return False
            if (cx, cy) == target:
                return True
        elif right is not None and (left is None or right < left):
            old = (cx, cy)
            cy += dy
            ny += 2
            if _cross(old, (cx, cy), mp, be, target):
                return False
            if (cx, cy) == target:
                return True
        else:
            return (cx, cy) == target
    return False


def visible_cells(mp, sources, radius=mapmodel.FOG_R, blocked_edges=None):
    w, h = mp["w"], mp["h"]
    be = blocked_edges if blocked_edges is not None else mapmodel.blocked_edges(mp)
    r = max(0, int(radius))
    seen = set()
    for source in sources:
        sx, sy = source
        if not _inside(w, h, sx, sy):
            continue
        x0, x1 = max(0, sx - r), min(w - 1, sx + r)
        y0, y1 = max(0, sy - r), min(h - 1, sy + r)
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                if line_of_sight(mp, (sx, sy), (x, y), be):
                    seen.add(y * w + x)
    return seen
