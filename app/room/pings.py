"""Ephemeral map pings: no persistence, rate-limited broadcast."""
import time
from collections import defaultdict, deque

from .net import broadcast, get_map

_hits: dict[tuple, deque] = defaultdict(deque)


def _clean_color(c):
    c = str(c or "#e74c3c")
    return c if len(c) == 7 and c[0] == "#" else "#e74c3c"


async def handle_ping(ws, room_id, user, is_dm, msg):
    mp = get_map(room_id)
    try:
        w, h = int(mp.get("w", 40)), int(mp.get("h", 25))
    except (TypeError, ValueError):
        w, h = 40, 25
    try:
        x = max(0, min(w - 1, int(msg.get("x"))))
        y = max(0, min(h - 1, int(msg.get("y"))))
    except (TypeError, ValueError):
        return
    now = time.time()
    q = _hits[(room_id, user["id"])]
    while q and q[0] < now - 2:
        q.popleft()
    if len(q) >= 5:
        return
    q.append(now)
    await broadcast(room_id, "ping", {"x": x, "y": y, "color": _clean_color(msg.get("color")),
                                       "user_id": user["id"], "at": now})
