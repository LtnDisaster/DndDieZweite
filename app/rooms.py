"""REST endpoints: auth, characters, rooms, map upload."""
import os
import re
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from . import content as CONTENT, db, footprint, floors as FLOOR, gear, inventory as INV, los, mapmodel, progression, ratelimit, ws
from . import quests as questlog
from . import conditions as C
from . import npc
from .room import audio, chat
from .room import death as D
from . import events as game_events
from .room import gamelog
from .room import net as room_net
from .room.net import sys_msg
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
    # D101: None = "leave the stored background untouched" — a PUT from a client
    # that predates the field must never wipe it; "" is an explicit reset.
    background: str | None = None
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
    # D92: parsed BEFORE ac_total — compute_ac switches to equipped mode off
    # this column; clean_equipment drops dangling refs at READ time too.
    r["equipment"] = gear.clean_equipment(db.j(r.get("equipment"), {}), r["items"])
    # D99: money is one integer of copper; size drives the encumbrance modifier.
    r["wallet"] = gear.clean_wallet(r.get("wallet", 0))
    r["size"] = gear.clean_size(r.get("size"))
    r["hit_dice_max"] = gear.hit_dice_max(r)
    r["hit_dice_spent"] = max(0, min(gear.hit_dice_max(r), int(r.get("hit_dice_spent") or 0)))
    r["has_spellbook"] = gear.has_spellbook(r["items"])
    r["ac_total"] = gear.compute_ac(r)
    if mask_items:
        r["items"] = gear.mask_items(r["items"], True)
    # D93: server-derived numbers ride the sheet — the client RENDERS these
    # and never recomputes bonuses (client copies of the formulas drifted on
    # multiclass level before; that class of bug is now structurally gone).
    r["derived"] = {
        "stat_mods": {a: gear.stat_mod(r, a) for a in gear.ABILITIES},
        "save_bonuses": {a: gear.save_bonus(r, r["saves"], a) for a in gear.ABILITIES},
        "skill_bonuses": {s: gear.skill_bonus(r, r["skills"], s)[0] for s in gear.SKILLS},
        "skill_prof": {s: gear.skill_bonus(r, r["skills"], s)[1] for s in gear.SKILLS},
        "prof_bonus": gear.prof_bonus(r),
        "initiative": gear.dex_mod(r),
        "attack_profiles": gear.weapon_profiles(r),
        "attune_max": gear.ATUNE_MAX,
        # D98: worn/wielded-derived values the sheet must show but must never
        # recompute — darkvision granted by gear, and the effective walk speed
        # (base + any speed_bonus_ft from worn items).
        "darkvision_ft": gear.effective_gear(r)["darkvision_ft"],
        "speed_effective": gear.clean_speeds(r)["walk"],
        # D99: the purse (copper + a display breakdown + the currency table the
        # sheet renders) and the derived carrying report. Both are READ-only
        # server derivations — the client renders, never recomputes, so a client
        # can never inflate its own gold or shrink its own load.
        "wallet": {"cp": r["wallet"], "coins": gear.cp_breakdown(r["wallet"]),
                   "currencies": gear.currency_table()},
        "encumbrance": gear.encumbrance(r, r["wallet"]),
    }
    return r


# D93: what an UNRELATED room member may see of someone else's character —
# the table-visible tactical layer only (identity, level, HP/AC as narrated
# in the chronicle anyway, speed). Everything else (stats, skills, saves,
# spells/slots, items/equipment, resources, defenses, notes) is sheet-private.
_PEER_FIELDS = ("id", "name", "race", "char_class", "level", "total_level",
                "hp", "max_hp", "temp_hp", "ac", "ac_total", "speed")


def _peer_view(c):
    return {k: c.get(k) for k in _PEER_FIELDS} if c else c


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
        "INSERT INTO characters (user_id,name,race,char_class,background,level,stats,hp,max_hp,ac,speed,notes,weapons,items,skills,spells,spell_slots,saves,resources,defenses,hit_die) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (user["id"], ch.name, ch.race, ch.char_class, ch.background or "", ch.level,
         db.json_dumps(ch.stats), ch.hp, ch.max_hp, ch.ac, ch.speed, ch.notes,
         db.json_dumps(_clean_weapons(ch.weapons)), db.json_dumps(gear.clean_items(ch.items)),
         db.json_dumps(gear.clean_skills(ch.skills)), db.json_dumps(gear.clean_spells(ch.spells)),
         db.json_dumps(gear.clean_slots(ch.spell_slots)),
         db.json_dumps(gear.clean_saves(ch.saves)), db.json_dumps(gear.clean_resources(ch.resources)),
         db.json_dumps(gear.clean_defenses(ch.defenses)), gear.clean_hit_die(ch.hit_die)))
    return _char_row(db.q1("SELECT * FROM characters WHERE id=?", (cid,)))


@router.put("/characters/{cid}")
def update_char(cid: int, ch: CharIn, user=Depends(require_user)):
    cur = _load_char(cid, user["id"])
    # D100 autonomy lock: the raw character-editor PUT may no longer rewrite the
    # SERVER-AUTHORISED progression fields. `level`, `spells` and `spell_slots` are
    # kept EXACTLY as stored — a sheet owner cannot refill consumed slots, self-grant
    # a spell list, or set their own level by hand. Authorised writers are untouched:
    # the validated build/level-up (`charbuild.apply`), the DM `class_levels` transport,
    # and the WS rest/ability/progression handlers. DMs never hit this endpoint at all
    # (_load_char is owner-scoped). Everything else on the sheet stays editable.
    db.x(
        "UPDATE characters SET name=?,race=?,char_class=?,background=?,stats=?,hp=?,max_hp=?,ac=?,speed=?,notes=?,"
        "weapons=?,items=?,skills=?,saves=?,defenses=?,resources=?,hit_die=? WHERE id=?",
        (ch.name, ch.race, ch.char_class,
         ch.background if ch.background is not None else (cur.get("background") or ""),
         db.json_dumps(ch.stats),
         ch.hp, ch.max_hp, ch.ac, ch.speed, ch.notes,
         db.json_dumps(_clean_weapons(ch.weapons)), db.json_dumps(gear.clean_items(ch.items)),
         db.json_dumps(gear.clean_skills(ch.skills)),
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


def _viewer_token_view(room, user, tokens_all, view_floor, mp):
    """D104 — THE player-view token/fog decision of the REST snapshot, in ONE
    function: /state's player branch and the DM's view_as preview share this
    exact code. A second visibility logic must never exist — the preview's
    security promise (it IS the server's character sight, not a cosmetic
    dimming) is anchored here. Pure read: nothing is written, revealed or
    broadcast; explored fog and ghost memory are only READ."""
    uid = user["id"]
    visible = ws.viewer_visible_cells(room["id"], uid, mp, floor=view_floor)
    # D86: which planes this viewer stands on (floors of own/operated
    # tokens). Tokens on other planes are ELSEWHERE, not hidden — they
    # must not even be listed, so their plane leaks nothing either.
    planes = {(t.get("floor") or "") for t in tokens_all
              if t["owner_user_id"] == uid
              or t.get("controller_user_id") == uid}
    _plane_cache = {"": (mp, visible)}
    def _plane(fl):
        # D88: sight must be evaluated on the map the token STANDS ON —
        # never decide a crypt token's visibility from the tavern's fog.
        if fl not in _plane_cache:
            mp_p = room_net.get_map(room["id"], fl)
            _plane_cache[fl] = (mp_p, ws.viewer_visible_cells(room["id"], uid,
                                                              mp_p, floor=fl))
        return _plane_cache[fl]
    def _visible_token(t):
        fl = t.get("floor") or ""
        if fl not in planes:
            return False                      # D86: different plane = elsewhere
        if t["owner_user_id"] == uid or t.get("controller_user_id") == uid:
            return True                       # D82: controllers always see their token
        mp_p, vis_p = _plane(fl)
        origin, side = footprint.occupied_origin(mp_p, t)
        return any((i := mapmodel.flat_idx(mp_p, x, y)) is not None and i in vis_p
                   for (x, y) in footprint.origin_cells(mp_p, origin, side))   # D72
    tokens = [t for t in tokens_all if _visible_token(t)]
    for t in tokens:                                   # NPC stat blocks are DM-only
        t["npc"] = None
        if (t.get("character_id") is None and t.get("owner_user_id") is None
                and t.get("controller_user_id") != uid):   # D83 duty: controllers keep the shape
            t.pop("disposition", None)
            t.pop("size", None)
            t.pop("fw", None)                    # D81: hidden tokens leak no footprint
            t.pop("fh", None)
            t.pop("vw", None)                    # D82: nor the visual silhouette
            t.pop("vh", None)
            t.pop("rot", None)
            t.pop("controller_user_id", None)    # D82: nor who leads it
            t.pop("image", None)                 # D85: nor what artwork it wears
            t.pop("floor", None)                 # D86: nor which plane it stands on
            t.pop("light", None)                 # D87: nor how brightly it burns
            t.pop("darkvision", None)            # D89: nor how well it sees
    last = ws._last_seen.get(room["id"], {}).get(uid, {})
    vis_ids = {t["id"] for t in tokens}
    ghosts = [dict(v, ghost=True) for tid, v in last.items() if tid not in vis_ids]
    return tokens, ghosts, visible


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
        # D93: a peer row is now the tactical allow-list — the old notes/
        # unidentified-magic redaction was the tip of a much bigger row.
        if masked:
            m["char"] = _peer_view(m["char"])
    tokens_all = db.q("SELECT * FROM tokens WHERE room_id=? ORDER BY id", (room["id"],))
    st = db.q1("SELECT initiative, map_json, audio_json FROM room_state WHERE room_id=?", (room["id"],)) or {}
    # D88: WHICH plane's map is this snapshot about? The DM may pass ?floor=
    # to browse a plane (viewing never moves a token); a player's snapshot is
    # always their own primary plane (first owned token's floor). Unknown or
    # unauthorized floor values fall back silently — never an error that
    # would reveal which floors exist.
    view_floor = ""
    if room["_role"] == "dm":
        req = str(request.query_params.get("floor") or "")
        if req and FLOOR.exists(room["id"], req):
            view_floor = req
    else:
        # own tokens first (home plane), then operated ones
        pool = [t for t in tokens_all if t["owner_user_id"] == user["id"]] \
            or [t for t in tokens_all if t.get("controller_user_id") == user["id"]]
        view_floor = (pool[0].get("floor") or "") if pool else ""
    mp = room_net.get_map(room["id"], view_floor)
    if room["_role"] == "dm":
        tokens, ghosts, visible = tokens_all, [], set()
        for t in tokens:                                   # DM sees full stat blocks
            t["npc"] = db.j(t.get("npc"), None) or None
    else:
        tokens, ghosts, visible = _viewer_token_view(room, user, tokens_all,
                                                     view_floor, mp)
    for t in tokens:                                   # conditions/death ride with visible tokens
        t["conds"] = C.load(t)
        t["death"] = D.load(t)
    msgs = gamelog.filter_messages_for_viewer(room["id"], user["id"], room["_role"] == "dm", 100)[::-1]
    for m in msgs:
        m["meta"] = db.j(m.get("meta"), {})
    chat_msgs = chat.chat_history_for_viewer(room["id"], user["id"], room["_role"] == "dm", 200)
    return {
        "code": room["code"], "name": room["name"], "map": room["map_image"],
        "role": room["_role"], "me": user["id"], "floors": [""] + FLOOR.parse(room),
        "members": members, "tokens": tokens, "ghosts": ghosts, "messages": msgs,
        "chat": chat_msgs,
        "audio": audio.load_state(st.get("audio_json")),
        "view_floor": view_floor,
        "grid": mapmodel.visible_map(mp, user["id"], room["_role"] == "dm", visible),
        "initiative": db.j(st.get("initiative"), {"combat": False, "order": [], "active": -1}),
        "quests": questlog.visible_for(room["id"], room["_role"] == "dm"),
        "characters": [_char_row(c) for c in db.q("SELECT * FROM characters WHERE user_id=?", (user["id"],))],
        # D92: the DM's item-definition library travels to the DM only; players
        # receive [] (defs are authoring templates — no player has a use for a
        # peer's future loot). Container CONTENTS never appear here at all —
        # they travel exclusively through an authorised inv_container inspect.
        "item_defs": ([{**d, "props": db.j(d.get("props"), {}), "stackable": bool(d["stackable"])}
                       for d in db.q("SELECT * FROM item_defs WHERE room_id=? ORDER BY name",
                                     (room["id"],))]
                      if room["_role"] == "dm" else []),
    }


@router.get("/rooms/{code}/view_as/{cid}")
def room_view_as(code: str, cid: int, request: Request):
    """D104 — DM preview: THE server-side sight of one character, read-only.
    Runs the same _viewer_token_view the character's own /state runs — the
    same LOS, the same dark/lamp/darkvision decision (it lives inside
    viewer_visible_cells), the same hidden-token strips, the same fog
    masking. Nothing is written: explored fog, ghost memory, broadcasts and
    every real viewer's state stay untouched — the DM sees what the player
    sees, and NOTHING gains what the DM sees. DM-only channel; to anyone
    else it answers like a floor that does not exist (no oracle)."""
    user, room = room_of(request, code)
    if room["_role"] != "dm":
        raise HTTPException(404, "Not found")
    ch = db.q1("SELECT * FROM characters WHERE id=?", (cid,))
    owner = db.q1("SELECT * FROM users WHERE id=?", (ch["user_id"],)) if ch else None
    tok = db.q1("SELECT * FROM tokens WHERE room_id=? AND character_id=?",
                (room["id"], cid)) if ch else None
    if owner is None or tok is None or not db.q1(
            "SELECT 1 AS hit FROM room_members WHERE room_id=? AND user_id=?",
            (room["id"], owner["id"])):
        raise HTTPException(404, "Not found")
    view_floor = tok.get("floor") or ""            # the preview FOLLOWS the character
    tokens_all = db.q("SELECT * FROM tokens WHERE room_id=? ORDER BY id", (room["id"],))
    mp = room_net.get_map(room["id"], view_floor)
    tokens, ghosts, visible = _viewer_token_view(room, owner, tokens_all,
                                                 view_floor, mp)
    for t in tokens:
        t["conds"] = C.load(t)
        t["death"] = D.load(t)
    return {"as": {"user_id": owner["id"], "username": owner["username"],
                   "character_id": ch["id"], "character": ch["name"],
                   "token_id": tok["id"]},
            "view_floor": view_floor, "dark": bool(mp.get("dark")),
            "grid": mapmodel.visible_map(mp, owner["id"], False, visible),
            "tokens": tokens, "ghosts": ghosts}


class FloorIn(BaseModel):
    name: str = Field(min_length=1, max_length=24)


@router.post("/rooms/{code}/floors")
async def add_floor_route(code: str, body: FloorIn, request: Request):
    user, room = _room_dm(request, code)
    ok, res = FLOOR.add(room["id"], body.name)
    if not ok:
        raise HTTPException(400, res)
    await room_net.broadcast(room["id"], "floors_changed", {"floors": [""] + res})
    return {"floors": [""] + res}


@router.delete("/rooms/{code}/floors/{name}")
async def remove_floor_route(code: str, name: str, request: Request):
    user, room = _room_dm(request, code)
    ok, res = FLOOR.remove(room["id"], name)
    if not ok:
        raise HTTPException(400, res)
    await room_net.broadcast(room["id"], "floors_changed", {"floors": [""] + res})
    return {"floors": [""] + res}


@router.patch("/rooms/{code}/floors/{name}")
async def rename_floor_route(code: str, name: str, body: FloorIn, request: Request):
    """D102 — rename a floor. Registry, plane map and tokens move atomically
    in FLOOR.rename; stair destinations naming the old floor live INSIDE map
    contents on every plane, so they are rewritten here before the room is
    told anything changed. This handler awaits nothing between the rename and
    the rewrites — the event loop is the serialiser against concurrent walks."""
    user, room = _room_dm(request, code)
    ok, res = FLOOR.rename(room["id"], name, body.name)
    if not ok:
        raise HTTPException(400, res)
    for fl in [""] + res:
        mp = room_net.get_map(room["id"], fl)
        hits = False
        for o in (mp.get("objects") or []):
            op = (o.get("interact") or {}).get("op") or {}
            if op.get("kind") == "stair" and str(op.get("floor") or "") == name:
                op["floor"] = body.name
                hits = True
        if hits:
            room_net.set_map(room["id"], mp, fl)
    await room_net.broadcast(room["id"], "floors_changed", {"floors": [""] + res})
    await room_net.broadcast(room["id"], "map_changed", None)
    return {"floors": [""] + res}


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
        # footprint.* read via .get() — a raw Row (the SECOND bring for one user,
        # i.e. any re-seat with an existing token) has no .get and 500'd there.
        tok = dict(tok) if tok else None
        if tok:
            c.execute("UPDATE tokens SET character_id=?, label=?, color=? WHERE id=?",
                      (ch["id"], ch["name"], color, tok["id"]))
            px, py = tok["x"], tok["y"]
        else:
            c.execute("INSERT INTO tokens (room_id,owner_user_id,character_id,label,color,x,y) "
                      "VALUES (?,?,?,?,?,400,300)", (room["id"], user["id"], ch["id"], ch["name"], color))
            px, py = 400, 300
        # D102: reveal on the plane the token STANDS ON — a re-seat onto a
        # named floor must not poke holes into the primary map's fog.
        fl = (tok.get("floor") or "") if tok else ""
        strow = c.execute("SELECT map_json FROM room_state WHERE room_id=?", (room["id"],)).fetchone()
        base = mapmodel.load(strow["map_json"] if strow else "")
        if fl:
            frow = c.execute("SELECT map_json FROM floor_maps WHERE room_id=? AND floor=?",
                             (room["id"], fl)).fetchone()
            mp = mapmodel.fit(mapmodel.load(frow["map_json"] if frow else None), base)
            mp["fog_off"] = bool(base.get("fog_off")) if frow else False
        else:
            mp = base
        size = tok["size"] if tok else "Medium"
        span = footprint.token_span(tok) if tok else footprint.token_span({"size": size})
        desired = footprint.origin_from_pixel(px, py, mp["cell"], mp)
        candidate = {"id": tok["id"] if tok else -1, "owner_user_id": user["id"],
                     "size": size, "fw": tok.get("fw") if tok else None,
                     "fh": tok.get("fh") if tok else None, "x": px, "y": py,
                     "rot": tok.get("rot") if tok else None}
        existing = [dict(r) for r in c.execute(
            "SELECT id, x, y, owner_user_id, size, fw, fh, rot, mount_token_id FROM tokens WHERE room_id=?",
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
            if fl:
                c.execute("INSERT INTO floor_maps(room_id,floor,map_json) VALUES(?,?,?) "
                          "ON CONFLICT(room_id,floor) DO UPDATE SET map_json=excluded.map_json",
                          (room["id"], fl, db.json_dumps(mp)))
            else:
                c.execute("UPDATE room_state SET map_json=? WHERE room_id=?",
                          (db.json_dumps(mp), room["id"]))
            revealed = True
    if revealed:
        ws.notify(room["id"], "map_changed", None)
    return {"ok": True}


class GearIn(BaseModel):
    character_id: int = 0
    class_choices: dict | None = None


def _gear_authz(request, code, cid):
    user, room = room_of(request, code)
    ch = db.q1("SELECT * FROM characters WHERE id=?", (cid,))
    if ch is None:
        raise HTTPException(404, "Unknown character")
    if ch["user_id"] != user["id"]:
        if room.get("_role") != "dm" or db.q1(
                "SELECT 1 AS ok FROM room_members WHERE room_id=? AND character_id=?",
                (room["id"], ch["id"])) is None:
            raise HTTPException(403, "Not your character")
    return user, room, ch


def _gear_tokens(text):
    """'dagger_surge, potion_heal x2' -> ([(item_id, qty)], [errors]). Strict:
    lowercase id (≤24) plus an OPTIONAL ' xN' (1–999). A malformed token is an
    ERROR, never a silently granted prefix or a dropped line (D105)."""
    out, errs = [], []
    for raw in str(text or "").split(","):
        tok = raw.strip()
        if not tok:
            continue
        m = re.fullmatch(r"([a-z0-9][a-z0-9_-]{0,23})(?: x([1-9]\d{0,2}))?", tok)
        if not m:
            errs.append(f"Malformed item token '{tok[:32]}'")
            continue
        out.append((m.group(1), int(m.group(2) or 1)))
    return out, errs


def _gear_choices(text):
    """'weapon=bow_long|sword_versatile; kit=goggles_night|gloves_thief x2'
    -> ([(label, [(item_id, qty), …])], [errors]). Each group needs at least
    two alternatives; labels are unique and free of the group delimiters."""
    groups, errs = [], []
    for raw in str(text or "").split(";"):
        grp = raw.strip()
        if not grp:
            continue
        label, sep, rest = grp.partition("=")
        label = label.strip()
        if not sep or not label or len(label) > 24 or any(c in label for c in "|=,"):
            errs.append(f"Malformed choice group '{grp[:32]}'")
            continue
        if any(g[0] == label.lower() for g in groups):
            errs.append(f"Duplicate choice group '{label}'")
            continue
        opts, oerrs = _gear_tokens(rest.replace("|", ","))
        errs.extend(oerrs)
        if len(opts) < 2:
            errs.append(f"Choice group '{label}' needs at least two alternatives")
            continue
        groups.append((label.lower(), opts))
    return groups, errs


def _class_gear_row(class_id, room_id):
    cid = str(class_id or "").strip().lower()
    if not cid:
        return None
    for r in CONTENT.load("class", room_id):
        if int(r.get("level") or 0) != 1:
            continue
        if str(r.get("id") or "").lower() == cid or \
                (r.get("name") or "").lower() == cid:
            return r
    return None


def _class_gear_plan(row, picks):
    """Resolve a class row's level-1 gear against the (optional) picks.
    ALL-OR-NOTHING: returns (items, groups, errors, missing) where items is
    populated ONLY when errors and missing are both empty — a broken or
    unresolved definition can never mint a partial grant that the idempotency
    claim would then freeze (D105)."""
    fixed, errors = _gear_tokens(row.get("starting_items"))
    groups, gerrs = _gear_choices(row.get("starting_choices"))
    errors.extend(gerrs)
    picks = picks if isinstance(picks, dict) else {}
    labels = [g[0] for g in groups]
    for key in picks:
        if str(key).strip().lower() not in labels:
            errors.append(f"Unknown choice group '{str(key)[:24]}'")
    missing = []
    for label, opts in groups:
        pick = picks.get(label)
        if pick is None:
            pick = next((p for k, p in picks.items()
                         if str(k).strip().lower() == label), None)
        if pick is None:
            missing.append(label)
            continue
        wanted = str(pick).strip().lower()
        if not any(item == wanted for item, _q in opts):
            errors.append(f"'{pick}' is not an offered alternative for '{label}'")
            continue
        fixed.append(next((item, qty) for item, qty in opts if item == wanted))
    if errors or missing or not fixed:
        return [], groups, errors, missing
    return fixed, groups, errors, missing


def _gear_report(room, ch):
    """Server-side resolution of BOTH gear parts for one character — names and
    problems only, never raw pack rows. The prep UI renders this; the POST
    re-validates independently, so the report can never be a side channel."""
    out = {"ok": True, "background": None, "class": None, "needs_choice": []}
    bg_id = (ch.get("background") or "").strip()
    if bg_id:
        bg = next((r for r in CONTENT.load("background", room["id"])
                   if r.get("id") == bg_id or (r.get("name") or "").lower() == bg_id.lower()),
                  None)
        if bg is None:
            out["background"] = {"error": f"Background '{bg_id}' is not in this room's rule pack"}
        else:
            toks = [t.strip() for t in str(bg.get("starting_items") or "").split(",") if t.strip()]
            items, skipped = [], []
            for t in toks:
                d = db.q1("SELECT name FROM item_defs WHERE id=? AND room_id=?", (t[:24], room["id"]))
                if d is None:
                    skipped.append(t)
                else:
                    items.append({"token": t[:24], "name": d["name"], "qty": 1})
            out["background"] = {"id": bg["id"], "items": items, "skipped": skipped}
    cls_id = (ch.get("char_class") or "").strip()
    if cls_id:
        row = _class_gear_row(cls_id, room["id"])
        if row is None:
            out["class"] = {"status": "not_in_pack", "id": cls_id}
        else:
            groups, gerrs = _gear_choices(row.get("starting_choices"))
            fixed, ferrs = _gear_tokens(row.get("starting_items"))
            errors = ferrs + gerrs
            def named(iq):
                item, qty = iq
                d = db.q1("SELECT name FROM item_defs WHERE id=? AND room_id=?",
                          (item, room["id"]))
                return {"token": item, "name": d["name"] if d else item, "qty": qty,
                        "resolved": d is not None}
            unresolved = [i for i, _q in fixed if db.q1(
                "SELECT 1 AS hit FROM item_defs WHERE id=? AND room_id=?",
                (i, room["id"])) is None]
            for label, opts in groups:
                for item, _q in opts:
                    if db.q1("SELECT 1 AS hit FROM item_defs WHERE id=? AND room_id=?",
                             (item, room["id"])) is None:
                        unresolved.append(item)
            if unresolved:
                errors.append("No item definition in this room's pack for: "
                              + ", ".join(sorted(set(unresolved))))
            groups_out = [{"label": label,
                           "options": [named(iq) for iq in opts]} for label, opts in groups]
            claimed = db.q1("SELECT 1 AS hit FROM inv_ops WHERE op_id=?",
                            (f"{ch['id']}|class-gear-{row['id']}"[:40],)) is not None
            out["class"] = {
                "status": "already" if claimed else (
                    "invalid" if errors else ("needs_choice" if groups_out else
                          ("gear" if fixed else "none"))),
                "id": row.get("id"),
                "fixed": [named(iq) for iq in fixed],
                "groups": groups_out,
                "errors": errors,
            }
            if not errors and groups_out and not claimed:
                out["needs_choice"] = [g["label"] for g in groups_out]
    return out


@router.get("/rooms/{code}/starting-gear/{cid}")
def starting_gear_report(code: str, cid: int, request: Request):
    """D105: the resolved gear report (fixed items, choice groups, AND every
    error that the grant would refuse on) — shown BEFORE granting so a broken
    pack fails visibly, never as a half-grant."""
    _user, room, ch = _gear_authz(request, code, cid)
    return _gear_report(room, ch)


@router.post("/rooms/{code}/starting-gear")
async def starting_gear_route(code: str, body: GearIn, request: Request):
    """D101/D105: grant background AND class starting gear from THIS room's
    rule pack — THE one grant path (no second route exists). Background part
    keeps its D101 semantics (unresolvable tokens reported as skipped). The
    class part is all-or-nothing: one malformed token, one missing item
    definition or one unanswered group refuses the WHOLE class grant and
    writes NO idempotency claim, so fixing the pack stays possible (D105).
    Each part is exactly-once through the D94 inv_ops replay guard: a replay
    answers 'already' and can never add items or overwrite the original
    choice. Authorisation mirrors the build API EXACTLY (owner, or DM of an
    assigned character) — mutation still runs through app/inventory.py, the
    one SSOT."""
    _user, room, ch = _gear_authz(request, code, body.character_id)
    ratelimit.limit("starting-gear", request, max_n=10, window=60)
    resp = {"ok": None, "granted": [], "skipped": [], "already": False, "error": "",
            "class_status": "none", "class_granted": [], "class_errors": [],
            "needs_choice": []}

    # ---- background part (D101 semantics unchanged) ----
    bg_done = False
    bg_id = (ch.get("background") or "").strip()
    if not bg_id:
        resp["error"] = "This character has no background set"
    else:
        bg = next((r for r in CONTENT.load("background", room["id"])
                   if r.get("id") == bg_id or (r.get("name") or "").lower() == bg_id.lower()),
                  None)
        if bg is None:
            resp["error"] = f"Background '{bg_id}' is not in this room's rule pack"
        else:
            tokens = [t.strip() for t in str(bg.get("starting_items") or "").split(",")
                      if t.strip()]
            if not tokens:
                resp["error"] = "This background lists no starting_items in the rule pack"
            else:
                entries, skipped = [], []
                for tok in tokens:
                    d = db.q1("SELECT * FROM item_defs WHERE id=? AND room_id=?",
                              (tok[:24], room["id"]))
                    if d is not None:
                        entries.append(INV.entry_from_def(d, 1))
                    else:
                        skipped.append(tok)
                resp["skipped"] = skipped
                if entries:
                    try:
                        res = INV.grant(room["id"], ch["id"], entries,
                                        f"starting-gear-{bg['id']}"[:40])
                    except INV.InvError as ex:
                        raise HTTPException(400, str(ex))
                    if res == "replay":
                        resp["already"] = True
                    else:
                        resp["granted"] = res
                        await room_net.broadcast(room["id"], "inv_changed", None)
                        names = ", ".join(f"{r['qty']} × {r['name']}" for r in res)
                        sys_msg(room["id"],
                                f"🎒 {ch['name']} receives starting equipment: {names}.")
                bg_done = True

    # ---- class part (D105, all-or-nothing, exactly-once) ----
    cls_id = (ch.get("char_class") or "").strip()
    if cls_id:
        row = _class_gear_row(cls_id, room["id"])
        if row is None:
            resp["class_status"] = "not_in_pack"
        elif db.q1("SELECT 1 AS hit FROM inv_ops WHERE op_id=?",
                   (f"{ch['id']}|class-gear-{str(row.get('id') or '')}"[:40],)) is not None:
            # exactly-once (D105): the kit was granted BEFORE — a later request
            # answers 'already' whatever it carries. It can neither add items
            # nor overwrite the original choice, so the picks are not even
            # parsed. The claim key mirrors inventory._claim (ns = char id).
            resp["class_status"] = "already"
        else:
            items, groups, errors, missing = _class_gear_plan(row, body.class_choices)
            if errors:
                resp["class_status"] = "invalid"
                resp["class_errors"] = errors[:8]
            elif missing:
                resp["class_status"] = "needs_choice"
                resp["needs_choice"] = missing
            elif not items:
                resp["class_status"] = "none"
            else:
                entries, unresolved = [], []
                for item_id, qty in items:
                    d = db.q1("SELECT * FROM item_defs WHERE id=? AND room_id=?",
                              (item_id, room["id"]))
                    if d is None:
                        unresolved.append(item_id)
                    else:
                        entries.append(INV.entry_from_def(d, qty))
                if unresolved:
                    resp["class_status"] = "invalid"
                    resp["class_errors"] = [
                        "No item definition in this room's pack for: "
                        + ", ".join(sorted(set(unresolved)))]
                else:
                    try:
                        res = INV.grant(room["id"], ch["id"], entries,
                                        f"class-gear-{row['id']}"[:40])
                    except INV.InvError as ex:
                        raise HTTPException(400, str(ex))
                    if res == "replay":
                        resp["class_status"] = "already"
                    else:
                        resp["class_status"] = "granted"
                        resp["class_granted"] = res
                        await room_net.broadcast(room["id"], "inv_changed", None)
                        names = ", ".join(f"{r['qty']} × {r['name']}" for r in res)
                        sys_msg(room["id"],
                                f"🎒 {ch['name']} receives the "
                                f"{row.get('name') or row['id']} kit: {names}.")

    resp["ok"] = bg_done or bool(resp["class_granted"]) or \
        (resp["class_status"] == "already" and not resp["error"])
    return resp


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
