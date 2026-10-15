"""REST: chronological character build (D96), room-scoped.

Authorization mirrors the ``class_levels`` transport EXACTLY — the owner may
always build their own character, and a DM may build any character ASSIGNED to
this room (``room_members``); anyone else is refused server-side. This is the one
place Phase B exposes build over HTTP; the mutation itself is the pure
``charbuild.apply`` / ``charbuild.plan``, so a WS handler or future automation can
reuse the same calls.
"""
from fastapi import APIRouter, Depends, HTTPException, Request

from . import charbuild, db, ratelimit
from .auth import require_user, room_of
from .room import net as room_net

router = APIRouter(prefix="/api/build")


def _authorize(request, code, cid):
    """Return the room after owner-or-room-DM authorisation for this character."""
    user, room = room_of(request, code)          # 401 unauth / 403 not a member
    ch = db.q1("SELECT id, user_id FROM characters WHERE id=?", (int(cid),))
    if ch is None:
        raise HTTPException(404, "Unknown character")
    if ch["user_id"] == user["id"]:
        return room
    if room.get("_role") == "dm" and db.q1(
            "SELECT 1 AS ok FROM room_members WHERE room_id=? AND character_id=?",
            (room["id"], ch["id"])):
        return room
    raise HTTPException(403, "Not your character")


@router.get("/{code}/{cid}/plan")
def build_plan(request: Request, code: str, cid: int,
               class_id: str = "", to: int = 1, user=Depends(require_user)):
    room = _authorize(request, code, cid)
    return charbuild.plan(class_id, to, room["id"])


@router.post("/{code}/{cid}/apply")
async def build_apply(request: Request, code: str, cid: int, user=Depends(require_user)):
    room = _authorize(request, code, cid)
    ratelimit.limit("charbuild-apply", request, max_n=30, window=60)
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(400, "Body must be a JSON object")
    ok, result = charbuild.apply(cid, body.get("class_id", ""), body.get("to", 0),
                                 body.get("choices") or {}, room["id"])
    if ok:
        # D101: the build changed sheets the table is showing — notify every
        # client exactly like the DM class_levels transport, so the sheet updates
        # WITHOUT a browser reload (the confirmed D101 browser bug).
        await room_net.broadcast(room["id"], "snapshot", None)
        return {"ok": True, "result": result}
    return {"ok": False, **result}


# ------------------------------------------------------------- D108: origin
@router.get("/{code}/{cid}/origin")
def build_origin(request: Request, code: str, cid: int, user=Depends(require_user)):
    """2024 origin report (D105 report-then-grant pattern): readiness, the
    background's three abilities with current values, its Origin feat, and
    every refusal the apply would answer."""
    room = _authorize(request, code, cid)
    ch = db.q1("SELECT * FROM characters WHERE id=?", (int(cid),))
    if ch is None:
        raise HTTPException(404, "Unknown character")
    return charbuild.origin_options(ch, room["id"])


@router.post("/{code}/{cid}/origin")
async def build_origin_apply(request: Request, code: str, cid: int,
                             user=Depends(require_user)):
    """Apply the 2024 background origin (ASI + Origin feat) exactly once. The
    body may carry ONLY ``background`` (id/name; defaults to the sheet value)
    and the ``asi`` choice — feat id and amounts come from the ROOM'S CONTENT,
    never from this request. Replays/double clicks answer ``already``."""
    room = _authorize(request, code, cid)
    ratelimit.limit("charbuild-origin", request, max_n=10, window=60)
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(400, "Body must be a JSON object")
    ch = db.q1("SELECT * FROM characters WHERE id=?", (int(cid),))
    if ch is None:
        raise HTTPException(404, "Unknown character")
    bg = str(body.get("background") or "").strip() or (ch.get("background") or "")
    ok, result = charbuild.apply_origin(cid, bg, body.get("asi") or {}, room["id"])
    if ok:
        if not result.get("already"):
            await room_net.broadcast(room["id"], "snapshot", None)
        return {"ok": True, "result": result}
    return {"ok": False, **result}


# -------------------------------------------------------- D109: masteries
@router.get("/{code}/{cid}/mastery")
def build_mastery(request: Request, code: str, cid: int, user=Depends(require_user)):
    """Weapon-mastery report: grants with sources, pending picks and their
    pools, resolved entitlements (mirrors the origin report-then-grant pattern)."""
    room = _authorize(request, code, cid)
    ch = db.q1("SELECT * FROM characters WHERE id=?", (int(cid),))
    if ch is None:
        raise HTTPException(404, "Unknown character")
    return charbuild.mastery_options(ch, room["id"])


@router.post("/{code}/{cid}/mastery")
async def build_mastery_pick(request: Request, code: str, cid: int,
                             user=Depends(require_user)):
    """Resolve ONE pending level-grant. Body may carry ONLY ``pick`` — the
    mastery must be in that grant level's pool; already-granted masteries are
    immutable here (a DM grant is the only way to add more)."""
    room = _authorize(request, code, cid)
    ratelimit.limit("charbuild-mastery", request, max_n=10, window=60)
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(400, "Body must be a JSON object")
    ch = db.q1("SELECT * FROM characters WHERE id=?", (int(cid),))
    if ch is None:
        raise HTTPException(404, "Unknown character")
    ok, result = charbuild.apply_mastery(cid, body.get("pick"), room["id"])
    if not ok:
        return {"ok": False, **result}
    await room_net.broadcast(room["id"], "snapshot", None)
    return {"ok": True, "result": result}


@router.post("/{code}/{cid}/mastery/grant")
async def build_mastery_grant(request: Request, code: str, cid: int,
                              user=Depends(require_user)):
    """DM-only mastery grant (audited in the ledger with the granting actor).
    The ONLY path to extra or later masteries — never retroactive, never
    client-side."""
    user, room = room_of(request, code)
    if room.get("_role") != "dm":
        raise HTTPException(403, "DM only")
    room = _authorize(request, code, cid)
    if not db.q1("SELECT 1 AS ok FROM room_members WHERE room_id=? AND character_id=?",
                 (room["id"], int(cid))):
        raise HTTPException(403, "Character not assigned to this room")
    ratelimit.limit("charbuild-mastery-grant", request, max_n=10, window=60)
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(400, "Body must be a JSON object")
    ok, result = charbuild.grant_mastery(cid, body.get("mastery"),
                                         user.get("username", "DM"), room["id"])
    if not ok:
        return {"ok": False, **result}
    await room_net.broadcast(room["id"], "snapshot", None)
    return {"ok": True, "result": result}
