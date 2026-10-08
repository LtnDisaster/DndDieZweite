"""D85 — secure PNG token-artwork assets.

Adversarial-user threat model. Everything the client sends is untrusted: the
filename (display only, never a path), the bytes (decoded, validated and
RE-ENCODED into a clean PNG, so untrusted metadata/pixels never survive), the
MIME type, the id and any URL. What the caller gets back is a server-made
opaque id and a server-controlled storage path only.

Pipeline (fail-closed, every rejection is a plain 4xx):

  size cap -> PNG magic -> real-format check via Pillow -> dimension/pixel
  caps -> FULL decode (verify + convert = rejects truncated/oversized/
  decompression bombs) -> metadata strip -> clean PNG re-encode -> final size
  re-check -> atomic write under DATA_DIR/assets/<uid>/<random id> -> row.

Authorization model:

  * an asset belongs to a user; only they (or the DM of a room the artwork
    already rides in) may read it;
  * GET returns 404 for "does not exist" AND "private to you" identically —
    no existence oracle;
  * assignment (room/tokens.py::token_image) lets a player attach only their
    own asset; a DM may attach any; the token field stores only the canonical
    "/assets/<id>" form generated here, never anything the client typed.

Storage ids are random and unguessable; deleting an asset that a live token
references is refused (defined fallback beats a silently broken token).
"""
import io
import os
import re
import secrets
import hashlib

from fastapi import APIRouter, HTTPException, Request, Response

from . import db, ratelimit
from .auth import require_user, room_of
from fastapi import Depends

try:                                  # maintained decoder — the ONE image gate
    from PIL import Image, ImageFile, UnidentifiedImageError
except ImportError:                    # pragma: no cover — pinned dependency
    Image = None

router = APIRouter(prefix="/api")

MAX_UPLOAD = 1_500_000            # compressed request bytes
MAX_PIXELS = 4_000_000            # decoded w*h ceiling (decompression-bomb gate)
MAX_DIM = 4096                    # per-axis ceiling
MAX_RECODED = 6_000_000           # re-encoded PNG may legitimately exceed the cap? no
PER_USER_COUNT = 400
PER_USER_BYTES = 30_000_000
ID_RE = re.compile(r"^[0-9a-f]{16}$")

ASSET_DIR = os.path.join(db.DATA_DIR, "assets")

# Pillow's own bomb detector; keep it, our stricter caps sit in front.
if Image is not None:
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    ImageFile.LOAD_TRUNCATED_IMAGES = False     # truncated files must RAISE


def _safe_name(name) -> str:
    """Display title only — never touches the filesystem (the storage name is
    generated). Control chars/RTL junk stripped; the ORIGINAL name is never a
    path, a URL or an id."""
    s = re.sub(r"[\x00-\x1f\x7f\u200e\u200f\u202a-\u202e]", "", str(name or ""))
    s = s.strip()[:60]
    return s or "Token art"


def ingest(user_id: int, body: bytes, name: str) -> dict:
    """Validate -> decode -> re-encode -> store. Raises HTTPException(4xx)."""
    if Image is None:                              # pragma: no cover
        raise HTTPException(503, "Image library unavailable")
    if not body or len(body) > MAX_UPLOAD:
        raise HTTPException(413, "Empty or too large upload (max 1.5 MB)")
    if body[:8] != b"\x89PNG\r\n\x1a\n":           # cheap pre-gate; NOT the check
        raise HTTPException(415, "PNG only for token artwork")
    try:
        im = Image.open(io.BytesIO(body))
        im.verify()                                # structural validation pass
    except Exception:
        raise HTTPException(415, "Not a valid PNG file")
    if im.format != "PNG":                         # disguised HTML/SVG/...
        raise HTTPException(415, "PNG only for token artwork")
    try:
        im = Image.open(io.BytesIO(body))          # second open after verify()
        w, h = im.size
        if w < 1 or h < 1 or w > MAX_DIM or h > MAX_DIM or w * h > MAX_PIXELS:
            raise HTTPException(413, "Image dimensions exceed the limits")
        im = im.convert("RGBA")                    # FULL decode; raises on bombs/
    except HTTPException:                          # truncation/garbage pixels
        raise
    except Exception:
        raise HTTPException(415, "Not a decodable PNG file")
    im.info.clear()                                # strip untrusted metadata
    out = io.BytesIO()
    im.save(out, "PNG", optimize=True)             # clean re-encode, no originals
    clean = out.getvalue()
    if len(clean) > MAX_UPLOAD:
        raise HTTPException(413, "Image too large after re-encode")
    sha = hashlib.sha256(clean).hexdigest()
    row = db.q1("SELECT * FROM assets WHERE user_id=? AND sha=?", (user_id, sha))
    if row is None:
        used = db.q1("SELECT COUNT(*) AS n, COALESCE(SUM(bytes),0) AS b FROM assets "
                     "WHERE user_id=?", (user_id,))
        if (used["n"] or 0) >= PER_USER_COUNT or (used["b"] or 0) + len(clean) > PER_USER_BYTES:
            raise HTTPException(429, "Your asset storage is full — delete unused images")
        aid = secrets.token_hex(8)
        sub = os.path.join(ASSET_DIR, str(int(user_id)))   # uid is an int: no traversal
        os.makedirs(sub, exist_ok=True)
        fname = f"{aid}.png"
        tmp = os.path.join(sub, fname + ".tmp")
        with open(tmp, "wb") as f:
            f.write(clean)
        os.replace(tmp, os.path.join(sub, fname))          # atomic publish
        db.x("INSERT INTO assets(id,user_id,name,file,w,h,bytes,sha) VALUES(?,?,?,?,?,?,?,?)",
             (aid, user_id, _safe_name(name), fname, w, h, len(clean), sha))
    else:
        aid = row["id"]                                    # dedupe for THIS user only
    return {"id": aid, "name": _safe_name(name), "w": w, "h": h}


def image_path(row) -> str | None:
    p = os.path.join(ASSET_DIR, str(int(row["user_id"])), row["file"])
    root = os.path.abspath(ASSET_DIR)
    if not os.path.abspath(p).startswith(root + os.sep) or not os.path.isfile(p):
        return None
    return p


def serve_allowed(row, requester_id: int) -> bool:
    """Owner, or the asset rides a token in a room the requester belongs to."""
    if row["user_id"] == requester_id:
        return True
    return db.q1("SELECT 1 AS hit FROM tokens t "
                 "JOIN room_members m ON m.room_id = t.room_id "
                 "WHERE t.image=? AND m.user_id=? LIMIT 1",
                 (f"/assets/{row['id']}", requester_id)) is not None


@router.put("/assets")
async def upload_asset(request: Request, name: str = "token",
                    user=Depends(require_user)):
    ratelimit.limit("asset-upload", request, max_n=20, window=60)
    body = await request.body()
    return ingest(user["id"], body, name)


@router.get("/assets")
def list_assets(request: Request, room: str = "", user=Depends(require_user)):
    rows = db.q("SELECT id,name,w,h,bytes,created_at FROM assets WHERE user_id=? "
                "ORDER BY created_at DESC LIMIT 500", (user["id"],))
    if room:
        _, r = room_of(request, room)
        if r["_role"] == "dm":
            mine = {a["id"] for a in rows}
            for a in db.q("SELECT id,name,w,h,bytes,created_at FROM assets "
                          "WHERE user_id != ? ORDER BY created_at DESC LIMIT 500",
                          (user["id"],)):
                if a["id"] not in mine:
                    rows.append(a)
        else:
            mine = {a["id"] for a in rows}
            for a in db.q("SELECT DISTINCT a.id,a.name,a.w,a.h,a.bytes,a.created_at "
                          "FROM assets a JOIN tokens t ON t.image = '/assets/'||a.id "
                          "WHERE t.room_id=?", (r["id"],)):
                if a["id"] not in mine:
                    rows.append(a)
                    mine.add(a["id"])
    return {"assets": rows}


@router.get("/assets/{aid}")
def get_asset(aid: str, request: Request, user=Depends(require_user)):
    if not ID_RE.fullmatch(aid or ""):
        raise HTTPException(404, "Not found")
    row = db.q1("SELECT * FROM assets WHERE id=?", (aid,))
    if row is None or not serve_allowed(row, user["id"]):
        raise HTTPException(404, "Not found")     # same shape: no existence oracle
    p = image_path(row)
    if p is None:                                  # pragma: no cover — DB/file drift
        raise HTTPException(404, "Not found")
    with open(p, "rb") as f:
        data = f.read()
    return Response(content=data, media_type="image/png",
                    headers={"X-Content-Type-Options": "nosniff",
                             "Cache-Control": "private, max-age=86400"})


@router.delete("/assets/{aid}")
def delete_asset(aid: str, request: Request, user=Depends(require_user)):
    if not ID_RE.fullmatch(aid or ""):
        raise HTTPException(404, "Not found")
    row = db.q1("SELECT * FROM assets WHERE id=?", (aid,))
    if row is None:
        raise HTTPException(404, "Not found")
    if row["user_id"] != user["id"]:
        raise HTTPException(404, "Not found")      # no oracle for others' ids
    if db.q1("SELECT 1 AS hit FROM tokens WHERE image=? LIMIT 1",
             (f"/assets/{aid}",)) is not None:
        raise HTTPException(409, "In use by a live token — remove it there first")
    p = image_path(row)
    if p:
        try:
            os.remove(p)
        except OSError:                             # pragma: no cover
            pass
    db.x("DELETE FROM assets WHERE id=?", (aid,))
    return {"ok": True}
