"""Ephemeral map pings: no persistence, rate-limited, PLANE-SCOPED delivery.

SPRINT-20 (closes D88's note): a ping belongs to the plane it is sent on.
The DM may ping the plane they view; a player may only ping the plane they
stand on (owned/operated token floors — the door/interact reach precedent;
the token-less member keeps the historic primary-plane behaviour, since a
ping claims no position). Bounds clamp to THAT plane's map, and delivery
goes only to the plane's watchers (net.plane_watchers). A foreign-plane
claim is dropped silently (like the rate limiter dropping pings), so the
channel is never an oracle for which floors exist or who stands where."""
import time
from collections import defaultdict, deque

from .. import floors
from .authz import controlled_rows
from .net import get_map, send_to_plane_viewed

_hits: dict[tuple, deque] = defaultdict(deque)


def _clean_color(c):
    c = str(c or "#e74c3c")
    return c if len(c) == 7 and c[0] == "#" else "#e74c3c"


def _can_ping_plane(room_id, user_id, fl):
    if not fl:
        return True                     # primary: any member (historic behaviour)
    return fl in {(t.get("floor") or "") for t in controlled_rows(room_id, user_id)}


async def handle_ping(ws, room_id, user, is_dm, msg):
    fl = str(msg.get("floor") or "")
    if not floors.exists(room_id, fl):
        return
    if not is_dm and not _can_ping_plane(room_id, user["id"], fl):
        return
    mp = get_map(room_id, fl)
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
    await send_to_plane_viewed(room_id, fl, "ping", {"x": x, "y": y,
                                                     "color": _clean_color(msg.get("color")),
                                                     "user_id": user["id"], "at": now,
                                                     "floor": fl})
