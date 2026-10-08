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


def owned_tokens(room_id, user_id, floor=None):
    rows = db.q("SELECT id, x, y, owner_user_id, size, fw, fh, rot, mount_token_id, floor "
                "FROM tokens WHERE room_id=? AND owner_user_id=?", (room_id, user_id))
    if floor is not None:
        # SPRINT-20: a token standing on another plane is a vision source on ITS
        # map, never on this one — its cells would otherwise be projected onto
        # the queried plane's map (phantom vision through cross-plane tokens).
        rows = [r for r in rows if (r.get("floor") or "") == (floor or "")]
    return rows


def viewer_source_cells(room_id, user_id, mp, floor=None):
    return footprint.player_source_cells(mp, owned_tokens(room_id, user_id, floor))


def viewer_visible_cells(room_id, user_id, mp, floor=None):
    if mp.get("dark"):
        return _lit_cells(room_id, user_id, mp, floor)
    return los.visible_cells(mp, viewer_source_cells(room_id, user_id, mp, floor),
                             radius=VISION_R)


def _lit_cells(room_id, user_id, mp, floor=None):
    """D87 — sight in a DARK room comes only from the light the viewer owns
    or operates: the LOS-limited radius of each of their tokens' light, plus
    the tokens' own footprint cells (you always feel the floor you stand on).
    No token, no light — but the DM branch never calls this way. Rooms that
    are not dark keep the classic personal-vision behaviour untouched.
    SPRINT-20: floor=None keeps the legacy any-plane behaviour; a plane-aware
    caller passes the plane whose map this is, so a lantern carried on the
    attic never lights the crypt's map below."""
    # SPRINT-19 AUDIT (L5): light vision is FOG, and a controller reveals no
    # fog (D82). The classic channel has always used owner-only source cells;
    # the dark branch must not hand a controller the world through an NPC's
    # lantern. Controllers keep seeing the token itself (delivery channel),
    # never what its light reveals.
    rows = owned_tokens(room_id, user_id, floor)
    full = {r["id"]: r for r in db.q(
        "SELECT * FROM tokens WHERE room_id=? AND owner_user_id=?", (room_id, user_id))}
    rows = [full[r["id"]] for r in rows]
    out = set()
    for r in rows:
        wc = _token_cells(mp, r)                       # WORLD cells as sources
        out |= {i for (x, y) in wc if (i := mapmodel.flat_idx(mp, x, y)) is not None}
        # D89: darkvision is a SENSE, not a torch — it only matters exactly
        # where light fails (this branch), and it is still owner-only (L5).
        rad = max(int(r.get("light") or 0), int(r.get("darkvision") or 0))
        if rad > 0 and wc:
            out |= los.visible_cells(mp, wc, radius=rad)   # -> STORAGE indices
    # D89: static light sources (map lamps, lanterns, braziers) belong to the
    # PLANE and light it for everyone standing there — light is not owned
    # information. Each source reveals what its own LOS can carry.
    for o in mp.get("objects", []):
        op = (o.get("interact") or {}).get("op") or {}
        if op.get("kind") != "lamp" or not (o.get("state") or {}).get("on", True):
            continue
        b = int(op.get("bright") or 0)
        if b > 0:
            out |= los.visible_cells(mp, {(int(o["x"]), int(o["y"]))}, radius=b)
    return out


def _viewer_planes(room_id, uid):
    """D86: the floor planes a viewer stands on — the floors of the tokens
    they own or operate. No token at all (DM, observer) = every plane."""
    rows = db.q("SELECT floor FROM tokens WHERE room_id=? "
                "AND (owner_user_id=? OR controller_user_id=?)", (room_id, uid, uid))
    return {(r.get("floor") or "") for r in rows}


def _token_cells(mp, token):
    origin, side = footprint.occupied_origin(mp, token)
    return footprint.origin_cells(mp, origin, side)


def _token_index_cells(mp, token):
    # WORLD footprint cells -> flat STORAGE indices (the space los.visible_cells
    # returns). Cells outside the world have no index and cannot be seen (D72).
    return {i for (x, y) in _token_cells(mp, token)
            if (i := mapmodel.flat_idx(mp, x, y)) is not None}


def _hidden_strip(add_player, token):
    """THE strip of the unowned-NPC payload (D81/D82/D85/D86/D87): silhouette,
    facing, controller, artwork, plane and light are DM/operator knowledge.
    ONE list — the add channel and the first-sight step share it."""
    if token.get("character_id") is None and token.get("owner_user_id") is None:
        for k in ("disposition", "size", "fw", "fh", "vw", "vh", "rot",
                  "controller_user_id", "image", "floor", "light", "darkvision"):
            add_player.pop(k, None)
    return add_player


async def send_presence_event(room_id, token, kind, payload):
    """SPRINT-21: the ONE presence gate. A token with a table presence (a
    character's token, or any owned token) keeps the classic room-wide channel
    for its state events; every other token — the unseen patrol, the crypt
    stalker — is delivered through exactly the plane gate + LOS + controller
    decision the token channel itself uses. Sprint 20 closed this hole for
    ability condition bumps (send_cond_bump); Sprint 21 routes cond_add/
    cond_remove/stand/knock, initiative-driven cond ticks and walk move_state
    through the same choke point, so id-bearing state events for hidden
    tokens never name them to players who cannot see them."""
    if token.get("owner_user_id") is not None or token.get("character_id") is not None:
        await broadcast(room_id, kind, payload)
        return
    fl = token.get("floor") or ""
    mp = get_map(room_id, fl)
    token_cells = _token_index_cells(mp, token)
    roles = {m["user_id"]: m["role"] for m in db.q(
        "SELECT user_id, role FROM room_members WHERE room_id=?", (room_id,))}
    plane_cache = {}
    for uid, socks in list(clients(room_id).items()):
        if roles.get(uid) == "dm":
            for ws in list(socks):
                await send_to(ws, kind, payload)
            continue
        if uid not in plane_cache:
            plane_cache[uid] = (_viewer_planes(room_id, uid),
                                viewer_visible_cells(room_id, uid, mp, floor=fl))
        planes, seen = plane_cache[uid]
        if fl not in planes:
            continue
        if (token.get("controller_user_id") == uid or (token_cells & seen)):
            for ws in list(socks):
                await send_to(ws, kind, payload)


async def send_cond_bump(room_id, token, conds):
    """SPRINT-20: the ability executor used to ``broadcast`` every condition
    bump room-wide — a hidden NPC hit by an AoE leaked its token id and its
    fresh condition (``restrained`` next to nothing visible) to every player
    socket. A token with a table presence (a character's token, or any owned
    token) keeps the classic room-wide channel; every other token is delivered
    through exactly the same plane gate + LOS decision the token channel uses."""
    await send_presence_event(room_id, token, "cond",
                              {"token_id": token["id"], "conds": conds})


async def send_property_to_interested(room_id, token, kind, payload, extra_uids=()):
    """SPRINT-19 AUDIT (L1) — id-bearing PROPERTY events (token_span/visual/rot/
    controller/image/floor/light) used to be room-wide broadcasts: setting a
    hidden NPC's artwork, plane, light or controller leaked its id, asset URL,
    floor name and radius to EVERY player socket — and from there the artwork
    was downloadable. The token_add/`/state` channels correctly strip that
    data for players; the property channel must answer to the same audience:
    the DM, the token's owner, and its current controller — plus any uid
    named in extra_uids (the CONTROLLER channel notifies the revoked one).
    Plain viewers simply never learn these properties exist on tokens they
    may not fully see."""
    uids = set()
    for m in db.q("SELECT user_id, role FROM room_members WHERE room_id=?", (room_id,)):
        if m["role"] == "dm":
            uids.add(m["user_id"])
    if token.get("owner_user_id"):
        uids.add(token["owner_user_id"])
    if token.get("controller_user_id"):
        uids.add(token["controller_user_id"])
    uids.update(u for u in extra_uids if u)
    for uid in uids:
        for ws in list(clients(room_id).get(uid) or ()):
            await send_to(ws, kind, payload)


def _snapshot(tok, viewer_id=None):
    snap = {k: tok.get(k) for k in ("id", "label", "color", "x", "y", "owner_user_id",
                                    "character_id", "controller_user_id", "mount_token_id",
                                    "image", "floor", "light", "darkvision")}
    # SPRINT-19 AUDIT — snapshot-channel leak parity: the add path strips an
    # unowned NPC's controller/artwork/plane/light for players, but the
    # step-first token_add and the ghost memory used to ship the UNSTRIPPED
    # snapshot — the first-sight step was a leak bypass and /state ghosts
    # replayed it. Same predicate as /state: unowned NPC the viewer does not
    # operate. viewer_id=None (DM stores/rebuilds) keeps the full row.
    if viewer_id is not None and tok.get("character_id") is None \
            and tok.get("owner_user_id") is None \
            and tok.get("controller_user_id") != viewer_id:
        for k in ("controller_user_id", "image", "floor", "light", "darkvision"):
            snap.pop(k, None)
    # D83 duty, delivery channel: a token you CONTROL is operated through —
    # wrong geometry silently un-rotates/un-centres it for you (the companion
    # 3x7-as-1x1 bug). Owner AND controller carry the shape; the hidden-token
    # leak guard (unowned NPC tokens) is unchanged — it never reaches here for
    # anyone but a legitimately-delivered DM view.
    if viewer_id is not None and (tok.get("owner_user_id") == viewer_id
                                  or tok.get("controller_user_id") == viewer_id):
        snap["size"] = tok.get("size", "Medium")
        snap["fw"], snap["fh"] = tok.get("fw"), tok.get("fh")
        snap["vw"], snap["vh"] = tok.get("vw"), tok.get("vh")
        snap["rot"] = tok.get("rot")
    snap["conds"] = _conds.load(tok)
    snap["death"] = _death.load(tok)
    return snap


def _player_add_for(token, add_player, uid):
    """D83 duty on the token_add channel: a token you CONTROL is operated
    through — you carry its shape (the companion 3x7-as-1x1 delivery bug).
    The hidden-token strip above stands for every other viewer."""
    if token.get("controller_user_id") == uid and token.get("owner_user_id") != uid:
        # SPRINT-19: /state keeps image/floor/light for the OPERATOR of an NPC
        # (it is their eyes/hands for that token) — the live add channel must
        # deliver the identical set, or the two reconstruction paths disagree
        # and REST cannot state one serve rule.
        return {**add_player, **{k: token.get(k) for k in
                                 ("size", "fw", "fh", "vw", "vh", "rot",
                                  "image", "floor", "light", "darkvision", "controller_user_id")
                                 if k in token and token[k] is not None}}
    return add_player


async def send_token_event(room_id, token, kind="token_add", extra=None):
    """Send a token event only to viewers who can currently see it; un-ghost on
    first sight, ghost (token_leave) those who just lost it."""
    mp = get_map(room_id, token.get("floor") or "")   # D88: the token's plane map
    token_cells = _token_index_cells(mp, token)
    roles = {m["user_id"]: m["role"] for m in db.q(
        "SELECT user_id, role FROM room_members WHERE room_id=?", (room_id,))}
    payload = extra if extra is not None else token
    add_dm = add_player = None                       # built on demand (steps)
    # token_add streams the whole token row: hand the DM the stat block as an object,
    # and strip it entirely from what players receive (NPC blocks are DM-only).
    if kind == "token_add":
        cl, dd = _conds.load(token), _death.load(token)
        add_dm = {**token, "npc": db.j(token.get("npc"), None) or None,
                  "conds": cl, "death": dd}
        add_player = _hidden_strip(
            {**{k: v for k, v in token.items() if k != "npc"}, "conds": cl, "death": dd},
            token)
    seen_cache = {}
    plane_cache = {}
    for uid, socks in list(clients(room_id).items()):
        is_dm = roles.get(uid) == "dm"
        if is_dm:
            seen = None
            visible = True
        else:
            if uid not in plane_cache:
                plane_cache[uid] = _viewer_planes(room_id, uid)
            # D86: other planes are not fogged, they are ELSEWHERE — a token
            # on the attic is invisible below, without revealing anything.
            if (token.get("floor") or "") not in plane_cache[uid]:
                vls = _last_seen.setdefault(room_id, {}).setdefault(uid, {})
                if token["id"] in vls:
                    for ws in list(socks):
                        await send_to(ws, "token_leave", {"token_id": token["id"]})
                continue
            if uid not in seen_cache:
                seen_cache[uid] = viewer_visible_cells(room_id, uid, mp,
                                                       floor=token.get("floor") or "")
            seen = seen_cache[uid]
            # D82: a player always sees a token they control (like their own);
            # this is DELIVERY, not fog — controller tokens still never REVEAL.
            visible = (token.get("owner_user_id") == uid
                       or token.get("controller_user_id") == uid
                       or bool(token_cells & seen))
        vls = _last_seen.setdefault(room_id, {}).setdefault(uid, {})
        first_time = token["id"] not in vls
        if visible:
            vls[token["id"]] = _snapshot(token, None if is_dm else uid)
            for ws in list(socks):
                if kind == "step" and first_time and token.get("owner_user_id") != uid:
                    # SPRINT-19: the same strips as the real add channel — the
                    # first-sight step was a leak bypass (L2). Built on demand
                    # (steps are hot; first-sight is rare).
                    if add_dm is None:
                        cl, dd = _conds.load(token), _death.load(token)
                        add_dm = {**token, "npc": db.j(token.get("npc"), None) or None,
                                  "conds": cl, "death": dd}
                        add_player = _hidden_strip(
                            {**{k: v for k, v in token.items() if k != "npc"},
                             "conds": cl, "death": dd}, token)
                    await send_to(ws, "token_add", add_dm if is_dm
                                  else _player_add_for(token, add_player, uid))
                if kind == "token_add":
                    await send_to(ws, kind, add_dm if is_dm
                                  else _player_add_for(token, add_player, uid))
                else:
                    await send_to(ws, kind, payload)
        elif token["id"] in vls:
            for ws in list(socks):
                await send_to(ws, "token_leave", {"token_id": token["id"]})


async def reevaluate_visibility(room_id):
    """D87/D86 helper: re-run the per-viewer token visibility decision for
    every token of a room (at their CURRENT positions — broadcast_token_step
    with unchanged coordinates delivers token_add to viewers who now see the
    token and token_leave to those who lost it, and changes nothing for
    everyone else)."""
    for tok in db.q("SELECT * FROM tokens WHERE room_id=?", (room_id,)):
        mp = get_map(room_id, tok.get("floor") or "")   # D88 per-plane re-evaluation
        origin, _side = footprint.occupied_origin(mp, tok)
        await broadcast_token_step(room_id, tok, tok["x"], tok["y"], *origin)


async def broadcast_token_add(room_id, token):
    await send_token_event(room_id, token, "token_add")


async def broadcast_token_step(room_id, token, x, y, cx, cy):
    await send_token_event(room_id, token, "step", {"token_id": token["id"], "x": x, "y": y,
                                                    "cx": cx, "cy": cy})


async def forget_token(room_id, token_id, token=None):
    holders = {uid for uid, viewers in _last_seen.get(room_id, {}).items()
               if token_id in viewers}
    for viewers in _last_seen.get(room_id, {}).values():
        viewers.pop(token_id, None)
    # SPRINT-21: token_gone is a GHOST-REMOVAL sync. A token with a table
    # presence keeps the room-wide channel; deleting an unseen NPC must not
    # name it to players who never saw it — its ghost holders (and every DM,
    # whose canvas holds all tokens) are the audience.
    if token is not None and token.get("owner_user_id") is None \
            and token.get("character_id") is None:
        # audience: DMs + viewers who can see it right now (token is on their
        # canvas) + viewers holding its ghost (row was loaded pre-delete).
        fl = token.get("floor") or ""
        mp = get_map(room_id, fl)
        token_cells = _token_index_cells(mp, token)
        roles = {m["user_id"]: m["role"] for m in db.q(
            "SELECT user_id, role FROM room_members WHERE room_id=?", (room_id,))}
        for uid, socks in list(clients(room_id).items()):
            if roles.get(uid) == "dm" or uid in holders:
                reach = True
            else:
                planes = _viewer_planes(room_id, uid)
                reach = fl in planes and bool(
                    token_cells & viewer_visible_cells(room_id, uid, mp, floor=fl))
            if reach:
                for ws in list(socks):
                    await send_to(ws, "token_gone", {"token_id": token_id})
        return
    await broadcast(room_id, "token_gone", {"token_id": token_id})


def prune_viewer_last_seen(room_id, user_id):
    """Drop a viewer's ghost memory when their last socket closes, so _last_seen
    doesn't grow without bound across a long-lived server."""
    room = _last_seen.get(room_id)
    if room is not None:
        room.pop(user_id, None)
        if not room:
            _last_seen.pop(room_id, None)
