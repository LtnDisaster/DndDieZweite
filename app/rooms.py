"""REST endpoints: auth, characters, rooms, map upload."""
import os
import re
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from . import db, footprint, gear, los, mapmodel, progression, ratelimit, ws
from . import quests as questlog
from . import conditions as C
from . import npc
from .room import audio, chat
from .room import death as D
from . import events as game_events
from .room import gamelog
from .room import net as room_net
from .auth import COOKIE, cookie_secure, hash_pw, make_token, require_user, room_of, verify_pw

router = APIRouter(prefix="/api")

UPLOAD_DIR = os.path.join(db.DATA_DIR, "uploads")   # persistent tree (P3) — see scripts/move_uploads.py
MAX_UPLOAD = 8 * 1024 * 1024


class Cred(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=6, max_length=128)


class CharIn(BaseModel):
    name: str = Field(min_length=1, max_length=48)
    race: str = ""
    char_class: str = ""
    level: int = Field(1, ge=1, le=20)
    stats: dict = {}
    hp: int = Field(10, ge=-999, le=9999)
    max_hp: int = Field(10, ge=1, le=9999)
    ac: int = Field(10, ge=-10, le=99)
    speed: int = Field(30, ge=0, le=999)
    notes: str = ""
    weapons: list = []
    items: list = []
    skills: dict = {}
    spells: list = []
    spell_slots: dict = {}
    saves: dict = {}
    defenses: dict = {}
    resources: list = []
    hit_die: int = 8


class EncounterEntryIn(BaseModel):
    creature_id: int
    quantity: int = Field(1, ge=1, le=50)
    hidden: bool = False


class EncounterIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    notes: str = ""
    entries: list = []


class NoteIn(BaseModel):
    category: str = "notes"
    title: str = Field(min_length=1, max_length=120)
    body: str = ""
    visibility: str = "dm"
    recipients: list = []


ABILITIES = ("str", "dex", "con", "int", "wis", "cha")
DMG_RE = re.compile(r"^\d{0,3}d\d+([+-]\d+)?$", re.I)


def _clean_weapons(items):
    out = []
    for w in items[:20]:
        if not isinstance(w, dict):
            continue
        name = str(w.get("name", "")).strip()[:40]
        if not name:
            continue
        ab = str(w.get("ability", "str")).lower()
        if ab not in ABILITIES:
            ab = "str"
        dmg = str(w.get("dmg", "1d6"))[:16]
        if not DMG_RE.match(dmg):
            dmg = "1d6"
        try:
            bonus = max(-3, min(10, int(w.get("dmgBonus", 0))))
        except (TypeError, ValueError):
            bonus = 0
        out.append({"name": name, "ability": ab,
                    "proficient": bool(w.get("proficient")), "dmg": dmg,
                    "magic": bool(w.get("magic")) or bonus > 0, "dmgBonus": bonus})
    return out


def _char_row(r, mask_items=False):
    if not r:
        return r
    r = dict(r)
    r["stats"] = db.j(r.get("stats"), {})
    r["weapons"] = db.j(r.get("weapons"), [])
    r["items"] = gear.clean_items(db.j(r.get("items"), []))
    r["skills"] = gear.clean_skills(db.j(r.get("skills"), {}))
    r["spells"] = gear.clean_spells(db.j(r.get("spells"), []))
    r["spell_slots"] = gear.clean_slots(db.j(r.get("spell_slots"), {}))
    r["saves"] = gear.clean_saves(db.j(r.get("saves"), {}))
    r["defenses"] = gear.clean_defenses(db.j(r.get("defenses"), {}))
    r["resources"] = gear.clean_resources(db.j(r.get("resources"), []))
    r["temp_hp"] = max(0, min(999, int(r.get("temp_hp") or 0)))
    r["inspiration"] = 1 if r.get("inspiration") else 0
    r["exhaustion"] = max(0, min(6, int(r.get("exhaustion") or 0)))
    r["hit_die"] = gear.clean_hit_die(r.get("hit_die", 8))
    r["class_levels"] = progression.load(r)
    r["total_level"] = progression.total_character_level(r)
    r["abilities"] = [str(a) for a in (db.j(r.get("abilities"), []) or [])][:60]
    r["hit_dice_max"] = gear.hit_dice_max(r)
    r["hit_dice_spent"] = max(0, min(gear.hit_dice_max(r), int(r.get("hit_dice_spent") or 0)))
    r["has_spellbook"] = gear.has_spellbook(r["items"])
    r["ac_total"] = gear.compute_ac(r)
    if mask_items:
        r["items"] = gear.mask_items(r["items"], True)
    return r


class SoundIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    url: str = Field(min_length=1, max_length=2048)
    category: str = "sfx"


class JoinIn(BaseModel):
    code: str = Field(min_length=4, max_length=10)


class RoomIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class AssignIn(BaseModel):
    character_id: int


class CreatureIn(BaseModel):
    name: str = Field(min_length=1, max_length=32)
    level: int = 1
    stats: dict = {}
    hp: int = 10
    max_hp: int = 10
    ac: int = 10
    speed: int = 30
    attacks: list = []
    spells: list = []
    spell_slots: dict = {}
    saves: dict = {}
    defenses: dict = {}
    abilities: list = []
    resources: list = []
    notes: str = ""
    size: str = "Medium"
    disposition: str = ""
    tags: str = Field(default="", max_length=120)


COLORS = ["#e74c3c", "#3498db", "#2ecc71", "#f1c40f", "#9b59b6", "#e67e22", "#1abc9c", "#fd79a8"]


def _load_char(cid: int, user_id: int):
    ch = db.q1("SELECT * FROM characters WHERE id=? AND user_id=?", (cid, user_id))
    if ch is None:
        raise HTTPException(404, "Character not found")
    return ch


@router.post("/register")
def register(cred: Cred, request: Request, response: Response):
    ratelimit.limit("register", request, max_n=10, window=3600)
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", cred.username):
        raise HTTPException(400, "Username may contain letters, digits, _ . -")
    if db.q1("SELECT id FROM users WHERE username=?", (cred.username,)):
        raise HTTPException(409, "Username taken")
    uid = db.x("INSERT INTO users (username, pw_hash) VALUES (?,?)", (cred.username, hash_pw(cred.password)))
    response.set_cookie(COOKIE, make_token(uid), max_age=30 * 24 * 3600,
                        httponly=True, samesite="lax", secure=cookie_secure(request))
    return {"id": uid, "username": cred.username}


@router.post("/login")
def login(cred: Cred, request: Request, response: Response):
    ratelimit.limit("login", request, max_n=10, window=60)
    user = db.q1("SELECT * FROM users WHERE username=?", (cred.username,))
    if user is None or not verify_pw(cred.password, user["pw_hash"]):
        raise HTTPException(401, "Bad username or password")
    ratelimit.reset("login", request)
    response.set_cookie(COOKIE, make_token(user["id"]), max_age=30 * 24 * 3600,
                        httponly=True, samesite="lax", secure=cookie_secure(request))
    return {"id": user["id"], "username": user["username"]}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE)
    return {"ok": True}


@router.get("/me")
def me(user=Depends(require_user)):
    return user


@router.get("/characters")
def list_chars(user=Depends(require_user)):
    return [_char_row(r) for r in db.q(
        "SELECT * FROM characters WHERE user_id=? ORDER BY name", (user["id"],))]


@router.post("/characters")
def create_char(ch: CharIn, user=Depends(require_user)):
    cid = db.x(
        "INSERT INTO characters (user_id,name,race,char_class,level,stats,hp,max_hp,ac,speed,notes,weapons,items,skills,spells,spell_slots,saves,resources,defenses,hit_die) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (user["id"], ch.name, ch.race, ch.char_class, ch.level,
         db.json_dumps(ch.stats), ch.hp, ch.max_hp, ch.ac, ch.speed, ch.notes,
         db.json_dumps(_clean_weapons(ch.weapons)), db.json_dumps(gear.clean_items(ch.items)),
         db.json_dumps(gear.clean_skills(ch.skills)), db.json_dumps(gear.clean_spells(ch.spells)),
         db.json_dumps(gear.clean_slots(ch.spell_slots)),
         db.json_dumps(gear.clean_saves(ch.saves)), db.json_dumps(gear.clean_resources(ch.resources)),
         db.json_dumps(gear.clean_defenses(ch.defenses)), gear.clean_hit_die(ch.hit_die)))
    return _char_row(db.q1("SELECT * FROM characters WHERE id=?", (cid,)))


@router.put("/characters/{cid}")
def update_char(cid: int, ch: CharIn, user=Depends(require_user)):
    _load_char(cid, user["id"])
    db.x(
        "UPDATE characters SET name=?,race=?,char_class=?,level=?,stats=?,hp=?,max_hp=?,ac=?,speed=?,notes=?,"
        "weapons=?,items=?,skills=?,spells=?,spell_slots=?,saves=?,defenses=?,resources=?,hit_die=? WHERE id=?",
        (ch.name, ch.race, ch.char_class, ch.level, db.json_dumps(ch.stats),
         ch.hp, ch.max_hp, ch.ac, ch.speed, ch.notes,
         db.json_dumps(_clean_weapons(ch.weapons)), db.json_dumps(gear.clean_items(ch.items)),
         db.json_dumps(gear.clean_skills(ch.skills)), db.json_dumps(gear.clean_spells(ch.spells)),
         db.json_dumps(gear.clean_slots(ch.spell_slots)),
         db.json_dumps(gear.clean_saves(ch.saves)), db.json_dumps(gear.clean_defenses(ch.defenses)),
         db.json_dumps(gear.clean_resources(ch.resources)), gear.clean_hit_die(ch.hit_die), cid))
    return _char_row(db.q1("SELECT * FROM characters WHERE id=?", (cid,)))


@router.delete("/characters/{cid}")
def delete_char(cid: int, user=Depends(require_user)):
    _load_char(cid, user["id"])
    with db.tx() as c:
        c.execute("UPDATE tokens SET character_id=NULL WHERE character_id=?", (cid,))
        c.execute("DELETE FROM characters WHERE id=?", (cid,))
    return {"ok": True}


# ---------- bestiary (generic monster templates owned by a user) ----------

def _creature_block(cr: "CreatureIn"):
    block = npc.clean_npc({"name": cr.name, "level": cr.level, "stats": cr.stats,
                           "hp": cr.hp, "max_hp": cr.max_hp, "ac": cr.ac, "speed": cr.speed,
                           "attacks": cr.attacks, "spells": cr.spells, "spell_slots": cr.spell_slots,
                           "saves": cr.saves, "defenses": cr.defenses,
                           "abilities": cr.abilities, "resources": cr.resources,
                           "notes": cr.notes,
                           "size": cr.size, "disposition": cr.disposition})
    block["name"] = cr.name
    return block


def _creature_row(r):
    if not r:
        return r
    r = dict(r)
    r["block"] = db.j(r.get("block"), {})
    return r


def _load_creature(cid: int, user_id: int):
    cr = db.q1("SELECT * FROM creatures WHERE id=? AND user_id=?", (cid, user_id))
    if cr is None:
        raise HTTPException(404, "Creature not found")
    return cr


@router.get("/creatures")
def list_creatures(user=Depends(require_user)):
    return [_creature_row(r) for r in db.q(
        "SELECT * FROM creatures WHERE user_id=? ORDER BY name", (user["id"],))]


@router.post("/creatures")
def create_creature(cr: CreatureIn, user=Depends(require_user)):
    cid = db.x("INSERT INTO creatures (user_id,name,block,tags) VALUES (?,?,?,?)",
               (user["id"], cr.name, db.json_dumps(_creature_block(cr)), cr.tags))
    return _creature_row(db.q1("SELECT * FROM creatures WHERE id=?", (cid,)))


@router.put("/creatures/{cid}")
def update_creature(cid: int, cr: CreatureIn, user=Depends(require_user)):
    _load_creature(cid, user["id"])
    db.x("UPDATE creatures SET name=?, block=?, tags=? WHERE id=?",
         (cr.name, db.json_dumps(_creature_block(cr)), cr.tags, cid))
    return _creature_row(db.q1("SELECT * FROM creatures WHERE id=?", (cid,)))


@router.delete("/creatures/{cid}")
def delete_creature(cid: int, user=Depends(require_user)):
    _load_creature(cid, user["id"])
    db.x("DELETE FROM creatures WHERE id=?", (cid,))
    return {"ok": True}


def _clean_enc_entries(user_id, entries):
    out = []
    for e in entries[:50] if isinstance(entries, list) else []:
        if not isinstance(e, dict):
            continue
        try:
            cid = int(e.get("creature_id", -1))
            qty = max(1, min(50, int(e.get("quantity", 1))))
        except (TypeError, ValueError):
            continue
        cr = db.q1("SELECT id,name FROM creatures WHERE id=? AND user_id=?", (cid, user_id))
        if cr is None:
            raise HTTPException(400, "Encounter creature not found")
        out.append({"creature_id": cid, "name": cr["name"], "quantity": qty,
                    "hidden": bool(e.get("hidden"))})
    return out


def _enc_row(r, user_id):
    r = dict(r)
    r["entries"] = _clean_enc_entries(user_id, db.j(r.get("entries"), []))
    return r


@router.get("/encounters")
def list_encounters(user=Depends(require_user)):
    return [_enc_row(r, user["id"]) for r in db.q(
        "SELECT * FROM encounters WHERE user_id=? ORDER BY name", (user["id"],))]


@router.get("/encounters/{eid}")
def get_encounter(eid: int, user=Depends(require_user)):
    r = db.q1("SELECT * FROM encounters WHERE id=? AND user_id=?", (eid, user["id"]))
    if r is None:
        raise HTTPException(404, "Not found")
    return _enc_row(r, user["id"])


@router.post("/encounters")
def create_encounter(enc: EncounterIn, user=Depends(require_user)):
    entries = _clean_enc_entries(user["id"], enc.entries)
    rid = db.x("INSERT INTO encounters (user_id,name,notes,entries) VALUES (?,?,?,?)",
               (user["id"], enc.name, enc.notes, db.json_dumps(entries)))
    return _enc_row(db.q1("SELECT * FROM encounters WHERE id=?", (rid,)), user["id"])


@router.put("/encounters/{eid}")
def update_encounter(eid: int, enc: EncounterIn, user=Depends(require_user)):
    if db.q1("SELECT id FROM encounters WHERE id=? AND user_id=?", (eid, user["id"])) is None:
        raise HTTPException(404, "Not found")
    entries = _clean_enc_entries(user["id"], enc.entries)
    db.x("UPDATE encounters SET name=?, notes=?, entries=? WHERE id=?",
         (enc.name, enc.notes, db.json_dumps(entries), eid))
    return _enc_row(db.q1("SELECT * FROM encounters WHERE id=?", (eid,)), user["id"])


@router.delete("/encounters/{eid}")
def delete_encounter(eid: int, user=Depends(require_user)):
    if db.q1("SELECT id FROM encounters WHERE id=? AND user_id=?", (eid, user["id"])) is None:
        raise HTTPException(404, "Not found")
    db.x("DELETE FROM encounters WHERE id=?", (eid,))
    return {"ok": True}


# ---------- room-scoped journal / handouts ----------

def _clean_note_body(body: "NoteIn"):
    cat = str(body.category or "notes").lower()
    if cat not in ("notes", "locations", "npcs", "quests", "handouts"):
        cat = "notes"
    vis = str(body.visibility or "dm").lower()
    if vis not in ("dm", "party", "selected"):
        vis = "dm"
    recipients = []
    for uid in (body.recipients or [])[:100]:
        try:
            recipients.append(int(uid))
        except (TypeError, ValueError):
            pass
    return cat, vis, recipients


def _note_row(n):
    n = dict(n)
    n["recipients"] = db.j(n.get("recipients"), [])
    return n


def _room_dm(request: Request, code: str):
    user, room = room_of(request, code)
    if room["_role"] != "dm":
        raise HTTPException(403, "DM only")
    return user, room


@router.get("/rooms/{code}/notes")
def list_notes(code: str, request: Request):
    user, room = room_of(request, code)
    is_dm = room["_role"] == "dm"
    rows = db.q("SELECT * FROM notes WHERE room_id=? ORDER BY title", (room["id"],))
    out = []
    for r in rows:
        n = _note_row(r)
        if is_dm:
            out.append(n)
        elif n["visibility"] == "party" or (n["visibility"] == "selected" and user["id"] in (n["recipients"] or [])):
            out.append(n)
    return out


@router.post("/rooms/{code}/notes")
def create_note(code: str, body: NoteIn, request: Request):
    user, room = _room_dm(request, code)
    cat, vis, recips = _clean_note_body(body)
    nid = db.x("INSERT INTO notes (room_id,user_id,category,title,body,visibility,recipients) "
               "VALUES (?,?,?,?,?,?,?)",
               (room["id"], user["id"], cat, body.title, body.body, vis, db.json_dumps(recips)))
    return _note_row(db.q1("SELECT * FROM notes WHERE id=?", (nid,)))


@router.put("/rooms/{code}/notes/{nid}")
def update_note(code: str, nid: int, body: NoteIn, request: Request):
    _, room = _room_dm(request, code)
    n = db.q1("SELECT id FROM notes WHERE id=? AND room_id=?", (nid, room["id"]))
    if n is None:
        raise HTTPException(404, "Not found")
    cat, vis, recips = _clean_note_body(body)
    db.x("UPDATE notes SET category=?, title=?, body=?, visibility=?, recipients=?, updated_at=datetime('now') "
         "WHERE id=?", (cat, body.title, body.body, vis, db.json_dumps(recips), nid))
    return _note_row(db.q1("SELECT * FROM notes WHERE id=?", (nid,)))


@router.delete("/rooms/{code}/notes/{nid}")
def delete_note(code: str, nid: int, request: Request):
    _, room = _room_dm(request, code)
    if db.q1("SELECT id FROM notes WHERE id=? AND room_id=?", (nid, room["id"])) is None:
        raise HTTPException(404, "Not found")
    db.x("DELETE FROM notes WHERE id=?", (nid,))
    return {"ok": True}


@router.get("/sounds")
def list_sounds(user=Depends(require_user)):
    return audio.list_sounds(user["id"])


@router.post("/sounds")
def add_sound(body: SoundIn, user=Depends(require_user)):
    row = audio.create_sound(user["id"], body.name, body.url, body.category)
    if row is None:
        raise HTTPException(400, "Name and a safe direct audio URL are required")
    return row


@router.delete("/sounds/{sid}")
def remove_sound(sid: int, user=Depends(require_user)):
    if not audio.delete_sound(user["id"], sid):
        raise HTTPException(404, "Not found")
    return {"ok": True}


@router.get("/rooms")
def list_rooms(user=Depends(require_user)):
    return db.q(
        "SELECT r.code, r.name, r.created_at, m.role FROM rooms r "
        "JOIN room_members m ON m.room_id=r.id AND m.user_id=? ORDER BY r.id DESC",
        (user["id"],))


@router.post("/rooms")
def create_room(body: RoomIn, user=Depends(require_user)):
    code = secrets.token_hex(3).upper()
    while db.q1("SELECT id FROM rooms WHERE code=?", (code,)):
        code = secrets.token_hex(3).upper()
    with db.tx() as c:
        rid = c.execute("INSERT INTO rooms (code,name,dm_id) VALUES (?,?,?)",
                        (code, body.name, user["id"])).lastrowid
        c.execute("INSERT INTO room_members (room_id,user_id,role) VALUES (?,?, 'dm')", (rid, user["id"]))
        c.execute("INSERT INTO room_state (room_id) VALUES (?)", (rid,))
        c.execute("INSERT INTO messages (room_id,user_id,type,body) VALUES (?,?,'system',?)",
                  (rid, user["id"], f"Room '{body.name}' created. Share code {code}."))
    return {"code": code, "name": body.name}


@router.post("/rooms/join")
def join_room(body: JoinIn, user=Depends(require_user)):
    room = db.q1("SELECT * FROM rooms WHERE code=?", (body.code.strip().upper(),))
    if room is None:
        raise HTTPException(404, "No room with that code")
    if not db.q1("SELECT 1 AS ok FROM room_members WHERE room_id=? AND user_id=?", (room["id"], user["id"])):
        db.x("INSERT INTO room_members (room_id,user_id,role) VALUES (?,?,'player')", (room["id"], user["id"]))
        db.x("INSERT INTO messages (room_id,user_id,type,body) VALUES (?,?,'system',?)",
             (room["id"], user["id"], f"{user['username']} joined."))
    return {"code": room["code"], "name": room["name"]}


@router.delete("/rooms/{code}")
def delete_room(code: str, request: Request):
    """Delete a room permanently (D76). Only the room's DM (creator-equivalent
    membership role) may do this — a player crafting the HTTP request gets 403,
    a stranger gets 403/404 via room_of(); repeated calls 404 (idempotent-safe).

    Cascades exactly this room's persistent rows, removes the room's own
    background upload (never shared assets), and purges every in-memory trace
    (clients, map locks, ghost memory, walks) with a final room_deleted event
    so sockets land in the lobby instead of zombie-reconnecting."""
    user, room = room_of(request, code)
    if room["_role"] != "dm" or user["id"] != room["dm_id"]:
        raise HTTPException(403, "Only the room's DM can delete the room")
    room_id = room["id"]
    tok_ids = [t["id"] for t in db.q("SELECT id FROM tokens WHERE room_id=?", (room_id,))]
    image = room.get("map_image") or ""
    with db.tx() as c:
        for table in ("tokens", "messages", "room_state", "notes", "quests",
                      "room_members"):
            c.execute(f"DELETE FROM {table} WHERE room_id=?", (room_id,))
        c.execute("DELETE FROM rooms WHERE id=?", (room_id,))
    if image.startswith("/uploads/"):
        # rooms.map_image is written exclusively by THIS room's upload endpoint
        # (single-purpose file) — deleting it can never touch shared assets.
        fname = os.path.basename(image)
        if fname and fname != os.path.basename(fname):
            fname = None                      # path traversal guard
        if fname:
            try:
                os.remove(os.path.join(UPLOAD_DIR, fname))
            except OSError:
                pass                          # missing/unwritable: deletion is done
    game_events.recent = type(game_events.recent)(
        (e for e in game_events.recent if e.get("room_id") != room_id),
        maxlen=game_events.recent.maxlen)
    room_net.purge_room_nowait(room_id, code, tok_ids)
    return {"ok": True, "deleted": code}


@router.get("/rooms/{code}/state")
def room_state(code: str, request: Request):
    user, room = room_of(request, code)
    members = db.q(
        "SELECT m.user_id, m.role, m.character_id, u.username "
        "FROM room_members m JOIN users u ON u.id=m.user_id WHERE m.room_id=?", (room["id"],))
    for m in members:
        masked = room["_role"] != "dm" and m["user_id"] != user["id"]
        m["char"] = _char_row(
            db.q1("SELECT * FROM characters WHERE id=?", (m["character_id"],)),
            mask_items=masked) if m["character_id"] else None
        # Other players must not read a peer's private notes (loot is appended to notes).
        if m["char"] and masked:
            m["char"]["notes"] = ""
    tokens_all = db.q("SELECT * FROM tokens WHERE room_id=? ORDER BY id", (room["id"],))
    st = db.q1("SELECT initiative, map_json, audio_json FROM room_state WHERE room_id=?", (room["id"],)) or {}
    mp = mapmodel.load(st.get("map_json"))
    visible = set()
    if room["_role"] == "dm":
        tokens, ghosts = tokens_all, []
        for t in tokens:                                   # DM sees full stat blocks
            t["npc"] = db.j(t.get("npc"), None) or None
    else:
        visible = ws.viewer_visible_cells(room["id"], user["id"], mp)
        def _visible_token(t):
            if t["owner_user_id"] == user["id"] or t.get("controller_user_id") == user["id"]:
                return True                       # D82: controllers always see their token
            origin, side = footprint.occupied_origin(mp, t)
            return any((i := mapmodel.flat_idx(mp, x, y)) is not None and i in visible
                       for (x, y) in footprint.origin_cells(mp, origin, side))   # D72
        tokens = [t for t in tokens_all if _visible_token(t)]
        for t in tokens:                                   # NPC stat blocks are DM-only
            t["npc"] = None
            if t.get("character_id") is None and t.get("owner_user_id") is None:
                t.pop("disposition", None)
                t.pop("size", None)
                t.pop("fw", None)                    # D81: hidden tokens leak no footprint
                t.pop("fh", None)
                t.pop("vw", None)                    # D82: nor the visual silhouette
                t.pop("vh", None)
                t.pop("rot", None)
                t.pop("controller_user_id", None)    # D82: nor who leads it
        last = ws._last_seen.get(room["id"], {}).get(user["id"], {})
        vis_ids = {t["id"] for t in tokens}
        ghosts = [dict(v, ghost=True) for tid, v in last.items() if tid not in vis_ids]
    for t in tokens:                                   # conditions/death ride with visible tokens
        t["conds"] = C.load(t)
        t["death"] = D.load(t)
    msgs = gamelog.filter_messages_for_viewer(room["id"], user["id"], room["_role"] == "dm", 100)[::-1]
    for m in msgs:
        m["meta"] = db.j(m.get("meta"), {})
    chat_msgs = chat.chat_history_for_viewer(room["id"], user["id"], room["_role"] == "dm", 200)
    return {
        "code": room["code"], "name": room["name"], "map": room["map_image"],
        "role": room["_role"], "me": user["id"],
        "members": members, "tokens": tokens, "ghosts": ghosts, "messages": msgs,
        "chat": chat_msgs,
        "audio": audio.load_state(st.get("audio_json")),
        "grid": mapmodel.visible_map(mp, user["id"], room["_role"] == "dm", visible),
        "initiative": db.j(st.get("initiative"), {"combat": False, "order": [], "active": -1}),
        "quests": questlog.visible_for(room["id"], room["_role"] == "dm"),
        "characters": [_char_row(c) for c in db.q("SELECT * FROM characters WHERE user_id=?", (user["id"],))],
    }


@router.post("/rooms/{code}/assign")
def assign_char(code: str, body: AssignIn, request: Request):
    user, room = room_of(request, code)
    ch = _load_char(body.character_id, user["id"])
    color = COLORS[(user["id"] - 1) % len(COLORS)]
    revealed = False
    with db.tx() as c:
        c.execute("UPDATE room_members SET character_id=? WHERE room_id=? AND user_id=?",
                  (ch["id"], room["id"], user["id"]))
        tok = c.execute("SELECT * FROM tokens WHERE room_id=? AND owner_user_id=?",
                        (room["id"], user["id"])).fetchone()
        if tok:
            c.execute("UPDATE tokens SET character_id=?, label=?, color=? WHERE id=?",
                      (ch["id"], ch["name"], color, tok["id"]))
            px, py = tok["x"], tok["y"]
        else:
            c.execute("INSERT INTO tokens (room_id,owner_user_id,character_id,label,color,x,y) "
                      "VALUES (?,?,?,?,?,400,300)", (room["id"], user["id"], ch["id"], ch["name"], color))
            px, py = 400, 300
        strow = c.execute("SELECT map_json FROM room_state WHERE room_id=?", (room["id"],)).fetchone()
        mp = mapmodel.load(strow["map_json"] if strow else "")
        size = tok["size"] if tok else "Medium"
        span = footprint.token_span(tok) if tok else footprint.token_span({"size": size})
        desired = footprint.origin_from_pixel(px, py, mp["cell"], mp)
        candidate = {"id": tok["id"] if tok else -1, "owner_user_id": user["id"],
                     "size": size, "fw": tok.get("fw") if tok else None,
                     "fh": tok.get("fh") if tok else None, "x": px, "y": py}
        existing = [dict(r) for r in c.execute(
            "SELECT id, x, y, owner_user_id, size, fw, fh FROM tokens WHERE room_id=?",
            (room["id"],)).fetchall()]
        origin = footprint.find_valid_origin(mp, candidate, desired, existing) or desired
        px, py = footprint.origin_pixels(origin, span, mp["cell"])
        if (tok and (px != tok["x"] or py != tok["y"])) or not tok:
            c.execute("UPDATE tokens SET x=?, y=? WHERE room_id=? AND owner_user_id=?",
                      (px, py, room["id"], user["id"]))
        tok_for_reveal = {"id": tok["id"] if tok else -1, "x": px, "y": py,
                          "owner_user_id": user["id"], "size": size,
                          "fw": tok.get("fw") if tok else None,
                          "fh": tok.get("fh") if tok else None}
        source = footprint.player_source_cells(mp, [tok_for_reveal])
        visible_indices = los.visible_cells(mp, source)
        if mapmodel.reveal_cells(mp, visible_indices):
            c.execute("UPDATE room_state SET map_json=? WHERE room_id=?", (db.json_dumps(mp), room["id"]))
            revealed = True
    if revealed:
        ws.notify(room["id"], "map_changed", None)
    return {"ok": True}


@router.delete("/rooms/{code}/members/{uid}")
def kick(code: str, uid: int, request: Request):
    user, room = room_of(request, code)
    if room["_role"] != "dm":
        raise HTTPException(403, "DM only")
    if uid == user["id"]:
        raise HTTPException(400, "Cannot kick yourself")
    with db.tx() as c:
        tok = c.execute("SELECT id FROM tokens WHERE room_id=? AND owner_user_id=?",
                        (room["id"], uid)).fetchone()
        if tok:
            c.execute("UPDATE tokens SET owner_user_id=NULL, character_id=NULL, label='Defeated' WHERE id=?",
                      (tok["id"],))
        c.execute("DELETE FROM room_members WHERE room_id=? AND user_id=?", (room["id"], uid))
    return {"ok": True, "kicked": uid}


@router.put("/rooms/{code}/map")
async def upload_map(code: str, request: Request, name: str = "map"):
    user, room = room_of(request, code)
    if room["_role"] != "dm":
        raise HTTPException(403, "DM only")
    body = await request.body()
    if not body or len(body) > MAX_UPLOAD:
        raise HTTPException(400, "Empty or too large image (max 8 MB)")
    if body[:3] != b"\xff\xd8\xff" and body[:8] != b"\x89PNG\r\n\x1a\n":
        raise HTTPException(400, "Only PNG/JPEG images")
    safe = re.sub(r"[^A-Za-z0-9_-]", "", name) or "map"
    fname = f"{room['id']}_{safe}_{secrets.token_hex(3)}.png" if body[:8] == b"\x89PNG\r\n\x1a\n" \
        else f"{room['id']}_{safe}_{secrets.token_hex(3)}.jpg"
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    with open(os.path.join(UPLOAD_DIR, fname), "wb") as f:
        f.write(body)
    db.x("UPDATE rooms SET map_image=? WHERE id=?", (f"/uploads/{fname}", room["id"]))
    return {"ok": True, "map": f"/uploads/{fname}"}
