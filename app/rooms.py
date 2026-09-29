"""REST endpoints: auth, characters, rooms, map upload."""
import os
import re
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from . import db, gear, mapmodel, ratelimit, ws
from .auth import COOKIE, cookie_secure, hash_pw, make_token, require_user, room_of, verify_pw

router = APIRouter(prefix="/api")

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "uploads")
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
    r["has_spellbook"] = gear.has_spellbook(r["items"])
    r["ac_total"] = gear.compute_ac(r)
    if mask_items:
        r["items"] = gear.mask_items(r["items"], True)
    return r


class JoinIn(BaseModel):
    code: str = Field(min_length=4, max_length=10)


class RoomIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class AssignIn(BaseModel):
    character_id: int


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
        "INSERT INTO characters (user_id,name,race,char_class,level,stats,hp,max_hp,ac,speed,notes,weapons,items,skills,spells,spell_slots) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (user["id"], ch.name, ch.race, ch.char_class, ch.level,
         db.json_dumps(ch.stats), ch.hp, ch.max_hp, ch.ac, ch.speed, ch.notes,
         db.json_dumps(_clean_weapons(ch.weapons)), db.json_dumps(gear.clean_items(ch.items)),
         db.json_dumps(gear.clean_skills(ch.skills)), db.json_dumps(gear.clean_spells(ch.spells)),
         db.json_dumps(gear.clean_slots(ch.spell_slots))))
    return _char_row(db.q1("SELECT * FROM characters WHERE id=?", (cid,)))


@router.put("/characters/{cid}")
def update_char(cid: int, ch: CharIn, user=Depends(require_user)):
    _load_char(cid, user["id"])
    db.x(
        "UPDATE characters SET name=?,race=?,char_class=?,level=?,stats=?,hp=?,max_hp=?,ac=?,speed=?,notes=?,weapons=?,items=?,skills=?,spells=?,spell_slots=? WHERE id=?",
        (ch.name, ch.race, ch.char_class, ch.level, db.json_dumps(ch.stats),
         ch.hp, ch.max_hp, ch.ac, ch.speed, ch.notes,
         db.json_dumps(_clean_weapons(ch.weapons)), db.json_dumps(gear.clean_items(ch.items)),
         db.json_dumps(gear.clean_skills(ch.skills)), db.json_dumps(gear.clean_spells(ch.spells)),
         db.json_dumps(gear.clean_slots(ch.spell_slots)), cid))
    return _char_row(db.q1("SELECT * FROM characters WHERE id=?", (cid,)))


@router.delete("/characters/{cid}")
def delete_char(cid: int, user=Depends(require_user)):
    _load_char(cid, user["id"])
    with db.tx() as c:
        c.execute("UPDATE tokens SET character_id=NULL WHERE character_id=?", (cid,))
        c.execute("DELETE FROM characters WHERE id=?", (cid,))
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
    st = db.q1("SELECT initiative, map_json FROM room_state WHERE room_id=?", (room["id"],)) or {}
    mp = mapmodel.load(st.get("map_json"))
    owned = [(max(0, min(mp["w"] - 1, int(t["x"] // mp["cell"]))),
              max(0, min(mp["h"] - 1, int(t["y"] // mp["cell"]))))
             for t in db.q("SELECT x, y FROM tokens WHERE room_id=? AND owner_user_id=?",
                           (room["id"], user["id"]))]
    if room["_role"] == "dm":
        tokens, ghosts = tokens_all, []
    else:
        seen = ws.build_seen(owned)
        tokens = [t for t in tokens_all
                  if t["owner_user_id"] == user["id"] or ws.token_cell(t, mp) in seen]
        last = ws._last_seen.get(room["id"], {}).get(user["id"], {})
        vis_ids = {t["id"] for t in tokens}
        ghosts = [dict(v, ghost=True) for tid, v in last.items() if tid not in vis_ids]
    msgs = db.q(
        "SELECT ms.id, u.username, ms.type, ms.body, ms.created_at FROM messages ms "
        "LEFT JOIN users u ON u.id=ms.user_id WHERE ms.room_id=? ORDER BY ms.id DESC LIMIT 100",
        (room["id"],))[::-1]
    return {
        "code": room["code"], "name": room["name"], "map": room["map_image"],
        "role": room["_role"], "me": user["id"],
        "members": members, "tokens": tokens, "ghosts": ghosts, "messages": msgs,
        "grid": mapmodel.visible_map(mp, user["id"], room["_role"] == "dm", owned),
        "initiative": db.j(st.get("initiative"), {"combat": False, "order": [], "active": -1}),
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
        cx = max(0, min(mp["w"] - 1, int(px // mp["cell"])))
        cy = max(0, min(mp["h"] - 1, int(py // mp["cell"])))
        if mapmodel.reveal(mp, cx, cy):
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
