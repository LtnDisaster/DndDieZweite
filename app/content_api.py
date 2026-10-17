"""REST: content-package import/export, room-scoped, DM-authorised only.

Transport is deliberately multipart-free (the pinned image has no python-
multipart): the DM tool POSTs a file's raw bytes (a single .csv) or a whole
.zip, and the server auto-detects which. Import runs a PREVIEW pass first
(validate every file, report file/line/column errors + conflicts) and only
writes when the caller asks to apply and a file is error-free. Export always
escapes spreadsheet formula injection; ZIP export bundles every kind.

Authorization mirrors the D92 item-definition library: only the DM of THIS room
may change or read the room's content. ``room_id`` here is the numeric room id;
content never crosses rooms.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response

from . import content, db, npc, ratelimit
from .auth import require_user, room_of

router = APIRouter(prefix="/api/content")


def _require_dm(request, code):
    _, room = room_of(request, code)
    if room.get("_role") != "dm":
        raise HTTPException(403, "DM only")
    return room


@router.post("/{code}/import")
async def import_content(request: Request, code: str,
                         name: str = Query("upload.csv"),
                         mode: str = Query("preview"),
                         user=Depends(require_user)):
    """Import one CSV file or a ZIP of CSVs into THIS room.

    mode=preview  — validate only, nothing written (returns file/line/column).
    mode=apply    — write error-free files; a differing existing id is a conflict.
    mode=replace  — write and overwrite differing existing ids.
    """
    room = _require_dm(request, code)
    ratelimit.limit("content-import", request, max_n=30, window=60)
    body = await request.body()
    if not body:
        raise HTTPException(400, "Empty upload")
    if mode not in ("preview", "apply", "replace"):
        raise HTTPException(400, "mode must be preview|apply|replace")
    fmt = "zip" if body[:4] == b"PK\x03\x04" else "csv"
    try:
        files = content.read_package(name, body, fmt)
    except Exception as e:
        raise HTTPException(400, f"Package rejected: {e}")
    report = content.import_package(files, room["id"],
                                    mode=("replace" if mode == "replace" else "apply"),
                                    apply=(mode != "preview"))
    report["mode"] = mode
    return report


@router.get("/{code}/export")
def export_content(request: Request, code: str,
                   kind: str = Query(""), all: bool = Query(False),
                   user=Depends(require_user)):
    """Export the room's content. A single kind -> CSV; all=1 -> a ZIP."""
    room = _require_dm(request, code)
    if all:
        data = content.export_package(room["id"])
        return Response(content=data, media_type="application/zip",
                        headers={"Content-Disposition":
                                 f'attachment; filename="content-{room["code"]}.zip"',
                                 "X-Content-Type-Options": "nosniff"})
    if kind not in content.ALL_KINDS:
        raise HTTPException(400, f"kind must be one of {content.ALL_KINDS}")
    csv_text = content.export_csv(kind, room["id"])
    return Response(content=csv_text.encode("utf-8"), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition":
                             f'attachment; filename="{content.KIND_FILE[kind]}"',
                             "X-Content-Type-Options": "nosniff"})


OPTION_KINDS = ("species", "class", "subclass", "background", "feat", "spell", "item")


@router.get("/{code}/options")
def content_options(request: Request, code: str, user=Depends(require_user)):
    """D101: the rule pack's id+name catalogue that drives the guided character
    dropdowns. Readable by every room MEMBER (import/export/kinds stay DM-only)
    — it carries NAMES ONLY, never row payloads, so it exposes nothing a member
    may not already see on a sheet. Class/subclass level-rows collapse to one
    entry per class id."""
    _, room = room_of(request, code)
    out = {}
    for kind in OPTION_KINDS:
        seen = {}
        for r in content.load(kind, room["id"]):
            cid = str(r.get("id") or "")
            if not cid or cid in seen:
                continue
            seen[cid] = str(r.get("name") or cid)
        out[kind] = [{"id": k, "name": seen[k]}
                     for k in sorted(seen, key=lambda k: (seen[k].lower(), k))]
    return {"options": out}


@router.get("/{code}/kinds")
def content_kinds(request: Request, code: str, user=Depends(require_user)):
    """Per-kind counts for the DM panel (how much is loaded in this room)."""
    room = _require_dm(request, code)
    out = {}
    for kind in content.ALL_KINDS:
        n = db.q1("SELECT COUNT(*) AS n FROM content WHERE kind=? AND room_id=?",
                  (kind, room["id"]))
        out[kind] = n["n"] if n else 0
    return {"kinds": out}


@router.get("/{code}/creature-rows")
def creature_rows(request: Request, code: str, user=Depends(require_user)):
    """DM preview list of imported monster rows, names and supported projection only."""
    room = _require_dm(request, code)
    out = []
    for row in content.load("creature", room["id"]):
        try:
            block = npc.project_creature(row, content.load("spell", room["id"]))
            error = ""
        except ValueError as e:
            block, error = {}, str(e)
        out.append({"id": row.get("id"), "name": row.get("name") or row.get("id"),
                    "ready": not error and not block.get("unsupported"),
                    "companion": bool(block.get("companion")),
                    "error": error, "projection": block})
    return {"creatures": out}


@router.get("/{code}/creature/{creature_id}/projection")
def creature_projection(request: Request, code: str, creature_id: str,
                        user=Depends(require_user)):
    """Preview the NPC block a room's ``creatures.csv`` row would project to."""
    room = _require_dm(request, code)
    row = _creature_row_by_id(creature_id, room["id"])
    try:
        block = npc.project_creature(row, content.load("spell", room["id"]))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "projection": block}


@router.post("/{code}/creature/{creature_id}/to-bestiary")
def creature_to_bestiary(request: Request, code: str, creature_id: str,
                         user=Depends(require_user)):
    """Project one room creature into the DM's existing personal bestiary.

    The endpoint writes through the same ``npc.clean_npc`` shape used by the
    creature editor, so encounters and NPC tokens need no new data model.
    """
    room = _require_dm(request, code)
    row = _creature_row_by_id(creature_id, room["id"])
    try:
        block = npc.project_creature(row, content.load("spell", room["id"]))
    except ValueError as e:
        raise HTTPException(400, str(e))
    existing = db.q1("SELECT id FROM creatures WHERE user_id=? AND name=?",
                     (user["id"], block["name"]))
    if existing:
        raise HTTPException(409, f"'{block['name']}' already exists in your bestiary")
    cid = db.x("INSERT INTO creatures (user_id,name,block,tags) VALUES (?,?,?,?)",
               (user["id"], block["name"], db.json_dumps(block), block.get("tags", "")[:120]))
    created = db.q1("SELECT * FROM creatures WHERE id=?", (cid,))
    return {"ok": True, "creature_id": cid, "projection": block,
            "creature": {"id": cid, "name": created["name"], "tags": created["tags"]}}


def _creature_row_by_id(creature_id, room_id):
    wanted = str(creature_id or "").strip().lower()
    for row in content.load("creature", room_id):
        if str(row.get("id") or "").lower() == wanted:
            return row
    raise HTTPException(404, "Creature is not in this room's rule pack")
