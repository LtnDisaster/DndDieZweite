"""LOS/fog-memory visibility and per-viewer token streaming.

A player receives live token data only when at least one footprint cell is currently
visible under server-side LOS. Out-of-sight movement is never transmitted; a token
that leaves sight becomes a faded 'ghost' pinned to its last-seen position."""
from .. import db, footprint, los, mapmodel
from .. import conditions as _conds
from . import death as _death
from .net import clients, send_to, broadcast, get_map

VISION_R = los.mapmodel.FOG_R
# room -> viewer user_id -> token_id -> last-seen token snapshot (for ghosts)
_last_seen: dict[int, dict[int, dict]] = {}


def token_cell(tok, mp):
    return (int(tok["x"] // mp["cell"]), int(tok["y"] // mp["cell"]))


def owned_tokens(room_id, user_id):
    return db.q("SELECT id, x, y, owner_user_id, size FROM tokens "
                "WHERE room_id=? AND owner_user_id=?", (room_id, user_id))


def viewer_source_cells(room_id, user_id, mp):
    return footprint.player_source_cells(mp, owned_tokens(room_id, user_id))


def viewer_visible_cells(room_id, user_id, mp):
    return los.visible_cells(mp, viewer_source_cells(room_id, user_id, mp), radius=VISION_R)


def _token_cells(mp, token):
    origin, side = footprint.occupied_origin(mp, token)
    return footprint.origin_cells(mp, origin, side)


def _token_index_cells(mp, token):
    # WORLD footprint cells -> flat STORAGE indices (the space los.visible_cells
    # returns). Cells outside the world have no index and cannot be seen (D72).
    return {i for (x, y) in _token_cells(mp, token)
            if (i := mapmodel.flat_idx(mp, x, y)) is not None}


def _snapshot(tok, viewer_id=None):
    snap = {k: tok.get(k) for k in ("id", "label", "color", "x", "y",
                                    "owner_user_id", "character_id")}
    if tok.get("owner_user_id") == viewer_id:
        snap["size"] = tok.get("size", "Medium")
    snap["conds"] = _conds.load(tok)
    snap["death"] = _death.load(tok)
    return snap


async def send_token_event(room_id, token, kind="token_add", extra=None):
    """Send a token event only to viewers who can currently see it; un-ghost on
    first sight, ghost (token_leave) those who just lost it."""
    mp = get_map(room_id)
    token_cells = _token_index_cells(mp, token)
    roles = {m["user_id"]: m["role"] for m in db.q(
        "SELECT user_id, role FROM room_members WHERE room_id=?", (room_id,))}
    payload = extra if extra is not None else token
    # token_add streams the whole token row: hand the DM the stat block as an object,
    # and strip it entirely from what players receive (NPC blocks are DM-only).
    if kind == "token_add":
        cl, dd = _conds.load(token), _death.load(token)
        add_dm = {**token, "npc": db.j(token.get("npc"), None) or None,
                  "conds": cl, "death": dd}
        add_player = {**{k: v for k, v in token.items() if k != "npc"}, "conds": cl, "death": dd}
        if token.get("character_id") is None and token.get("owner_user_id") is None:
            add_player.pop("disposition", None)
            add_player.pop("size", None)
    seen_cache = {}
    for uid, socks in list(clients(room_id).items()):
        is_dm = roles.get(uid) == "dm"
        if is_dm:
            seen = None
            visible = True
        else:
            if uid not in seen_cache:
                seen_cache[uid] = viewer_visible_cells(room_id, uid, mp)
            seen = seen_cache[uid]
            visible = token.get("owner_user_id") == uid or bool(token_cells & seen)
        vls = _last_seen.setdefault(room_id, {}).setdefault(uid, {})
        first_time = token["id"] not in vls
        if visible:
            vls[token["id"]] = _snapshot(token, uid)
            for ws in list(socks):
                if kind == "step" and first_time and token.get("owner_user_id") != uid:
                    await send_to(ws, "token_add", _snapshot(token, uid))
                if kind == "token_add":
                    await send_to(ws, kind, add_dm if is_dm else add_player)
                else:
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
