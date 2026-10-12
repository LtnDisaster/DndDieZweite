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
        return {"ok": True, "result": result}
    return {"ok": False, **result}
