"""Line-of-sight / fog-memory visibility and per-viewer token streaming.

Strict radius vision: a viewer only ever receives tokens currently inside their
sight. Out-of-sight movement is never transmitted; a token that leaves a viewer's
sight becomes a faded 'ghost' pinned to its last-seen position (in-memory, session
state — see DECISIONS D8/D9)."""
from .. import db
from .net import clients, send_to, broadcast, get_map

VISION_R = 6
# room -> viewer user_id -> token_id -> last-seen token snapshot (for ghosts)
_last_seen: dict[int, dict[int, dict]] = {}


def token_cell(tok, mp):
    return (int(tok["x"] // mp["cell"]), int(tok["y"] // mp["cell"]))


def owned_cells(room_id, user_id, mp):
    return [(int(t["x"] // mp["cell"]), int(t["y"] // mp["cell"]))
            for t in db.q("SELECT x, y FROM tokens WHERE room_id=? AND owner_user_id=?",
                          (room_id, user_id))]


def build_seen(owned, r=VISION_R):
    cells = set()
    for (x, y) in owned:
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                cells.add((x + dx, y + dy))
    return cells


def _snapshot(tok):
    return {k: tok.get(k) for k in ("id", "label", "color", "x", "y",
                                    "owner_user_id", "character_id")}


async def send_token_event(room_id, token, kind="token_add", extra=None):
    """Send a token event only to viewers who can currently see it; un-ghost on
    first sight, ghost (token_leave) those who just lost it."""
    mp = get_map(room_id)
    tcell = token_cell(token, mp)
    roles = {m["user_id"]: m["role"] for m in db.q(
        "SELECT user_id, role FROM room_members WHERE room_id=?", (room_id,))}
    payload = extra if extra is not None else token
    seen_cache = {}
    for uid, socks in list(clients(room_id).items()):
        is_dm = roles.get(uid) == "dm"
        if is_dm:
            seen = None
        else:
            if uid not in seen_cache:
                seen_cache[uid] = build_seen(owned_cells(room_id, uid, mp))
            seen = seen_cache[uid]
        visible = is_dm or token.get("owner_user_id") == uid or tcell in seen
        vls = _last_seen.setdefault(room_id, {}).setdefault(uid, {})
        first_time = token["id"] not in vls
        if visible:
            vls[token["id"]] = _snapshot(token)
            for ws in list(socks):
                if kind == "step" and first_time and token.get("owner_user_id") != uid:
                    await send_to(ws, "token_add", _snapshot(token))
                await send_to(ws, kind, payload)
        elif token["id"] in vls:
            for ws in list(socks):
                await send_to(ws, "token_leave", {"token_id": token["id"]})


async def broadcast_token_add(room_id, token):
    await send_token_event(room_id, token, "token_add")


async def broadcast_token_step(room_id, token, x, y, cx, cy):
    await send_token_event(room_id, token, "step", {"token_id": token["id"], "x": x, "y": y,
                                                    "cx": cx, "cy": cy})


async def forget_token(room_id, token_id):
    for viewers in _last_seen.get(room_id, {}).values():
        viewers.pop(token_id, None)
    await broadcast(room_id, "token_gone", {"token_id": token_id})


def prune_viewer_last_seen(room_id, user_id):
    """Drop a viewer's ghost memory when their last socket closes, so _last_seen
    doesn't grow without bound across a long-lived server."""
    room = _last_seen.get(room_id)
    if room is not None:
        room.pop(user_id, None)
        if not room:
            _last_seen.pop(room_id, None)
