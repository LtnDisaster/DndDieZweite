"""Room ambience and selective sound effects.

External audio URLs are treated as hostile input. Only a small set of HTTPS
hosts is recognized, media IDs are re-validated, and embeds are built from the
validated IDs rather than any caller-supplied HTML.
"""
import re
import secrets
import time
from collections import defaultdict, deque
from urllib.parse import parse_qs, urlparse

from .. import db
from .chat import _valid_recipients
from .net import broadcast, send_to, send_user

MAX_SOURCES = 20
MAX_SOUNDS = 80
CATEGORIES = {"music", "ambience", "sfx"}
YT_HOSTS = {"youtube.com", "m.youtube.com", "music.youtube.com", "youtube-nocookie.com"}
SPOTIFY_HOSTS = {"open.spotify.com"}
YT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
SP_ID_RE = re.compile(r"^[A-Za-z0-9]{22}$")
SRC_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_hits: dict[tuple, deque] = defaultdict(deque)


def _rate_ok(room_id, user_id, bucket="audio", limit=20, window=10.0):
    now = time.time()
    q = _hits[(room_id, user_id, bucket)]
    while q and q[0] < now - window:
        q.popleft()
    if len(q) >= limit:
        return False
    q.append(now)
    return True


def clear_rate_state():
    _hits.clear()


def _clean_text(value, limit=80):
    return "".join(ch for ch in str(value or "") if 32 <= ord(ch) != 127).strip()[:limit].strip()


def _clean_id(value):
    v = str(value or "").strip()
    return v if SRC_ID_RE.fullmatch(v) else secrets.token_hex(8)


def _stamp():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _host(netloc):
    host = str(netloc or "").lower()
    return host[4:] if host.startswith("www.") else host


def _youtube_video(path, query):
    parsed = urlparse(f"?{query}")
    qs = parse_qs(parsed.query or "")
    values = qs.get("v") or []
    if values and YT_ID_RE.fullmatch(values[0] or ""):
        return values[0]
    parts = [p for p in str(path or "").split("/") if p]
    if len(parts) >= 2 and parts[0] in ("shorts", "embed", "live") and YT_ID_RE.fullmatch(parts[1] or ""):
        return parts[1]
    return None


def parse_audio_source(value):
    raw = str(value or "").strip()
    if len(raw) > 2048:
        return None
    if any(ord(ch) < 32 or ord(ch) == 127 or ch in " \t\n\r" for ch in raw):
        return None
    if any(ch in raw for ch in "<>\"'{}|\\^`"):
        return None
    if raw.startswith("/uploads/"):
        return {"kind": "direct", "url": raw, "embed": ""}
    try:
        p = urlparse(raw)
    except ValueError:
        return None
    if p.scheme not in ("http", "https") or not p.netloc or p.username or p.password:
        return None
    host = _host(p.netloc)
    if host in YT_HOSTS:
        vid = _youtube_video(p.path, p.query)
        if vid:
            return {"kind": "youtube", "url": f"https://www.youtube.com/watch?v={vid}",
                    "embed": f"https://www.youtube-nocookie.com/embed/{vid}?rel=0&modestbranding=1&playsinline=1"}
        return None
    if host == "youtu.be":
        vid = str(p.path or "").strip("/").split("/")[0]
        if YT_ID_RE.fullmatch(vid or ""):
            return {"kind": "youtube", "url": f"https://youtu.be/{vid}",
                    "embed": f"https://www.youtube-nocookie.com/embed/{vid}?rel=0&modestbranding=1&playsinline=1"}
        return None
    if host in SPOTIFY_HOSTS:
        parts = [x for x in str(p.path or "").split("/") if x]
        if len(parts) >= 2 and parts[0] in ("track", "album", "playlist") and SP_ID_RE.fullmatch(parts[1] or ""):
            return {"kind": "spotify", "url": f"https://open.spotify.com/{parts[0]}/{parts[1]}",
                    "embed": f"https://open.spotify.com/embed/{parts[0]}/{parts[1]}?utm_source=generator"}
        return None
    return {"kind": "direct", "url": raw, "embed": ""}


def clean_source(raw, *, source_id=None):
    if not isinstance(raw, dict):
        return None
    parsed = parse_audio_source(raw.get("url"))
    if not parsed:
        return None
    title = _clean_text(raw.get("title"), 80)
    if not title:
        title = {"youtube": "YouTube ambience", "spotify": "Spotify ambience",
                 "direct": "Audio source"}.get(parsed["kind"], "Audio source")
    category = str(raw.get("category") or ("sfx" if parsed["kind"] == "direct" else "ambience")).lower()
    if category not in CATEGORIES:
        category = "sfx" if parsed["kind"] == "direct" else "ambience"
    return {
        "id": _clean_id(source_id or raw.get("id")),
        "title": title,
        "url": parsed["url"],
        "embed": parsed.get("embed", ""),
        "kind": parsed["kind"],
        "category": category,
    }


def load_state(raw_state):
    if isinstance(raw_state, dict):
        raw = raw_state
    else:
        raw = db.j(raw_state, {})
    if not isinstance(raw, dict):
        raw = {}
    sources = []
    seen = set()
    for raw_source in list(raw.get("sources") or [])[:MAX_SOURCES]:
        source = clean_source(raw_source)
        if source and source["id"] not in seen:
            sources.append(source)
            seen.add(source["id"])
    current = str(raw.get("current_id") or "")
    if current not in seen:
        current = ""
    return {
        "sources": sources,
        "current_id": current or None,
        "playing": bool(raw.get("playing")) and bool(current),
        "updated_at": str(raw.get("updated_at") or ""),
    }


def save_state(room_id, state):
    state = load_state(state)
    db.x("UPDATE room_state SET audio_json=? WHERE room_id=?", (db.json_dumps(state), room_id))
    return state


async def _error(ws, message):
    await send_to(ws, "error", {"msg": message})


async def _broadcast(room_id):
    st = db.q1("SELECT audio_json FROM room_state WHERE room_id=?", (room_id,))
    await broadcast(room_id, "ambience", load_state((st or {}).get("audio_json")))


async def handle_audio_add(ws, room_id, user, is_dm, msg):
    if not is_dm:
        await _error(ws, "DM only")
        return
    source = clean_source(msg, source_id=secrets.token_hex(8))
    if source is None:
        await _error(ws, "Unsupported or unsafe audio URL")
        return
    raw = db.q1("SELECT audio_json FROM room_state WHERE room_id=?", (room_id,))
    state = load_state((raw or {}).get("audio_json"))
    if len(state["sources"]) >= MAX_SOURCES:
        await _error(ws, "Ambience list is full")
        return
    state["sources"].append(source)
    state["updated_at"] = _stamp()
    save_state(room_id, state)
    await _broadcast(room_id)


async def handle_audio_remove(ws, room_id, user, is_dm, msg):
    if not is_dm:
        await _error(ws, "DM only")
        return
    source_id = str(msg.get("source_id") or msg.get("id") or "")
    raw = db.q1("SELECT audio_json FROM room_state WHERE room_id=?", (room_id,))
    state = load_state((raw or {}).get("audio_json"))
    before = len(state["sources"])
    state["sources"] = [s for s in state["sources"] if s.get("id") != source_id]
    if len(state["sources"]) == before:
        return
    if state.get("current_id") == source_id:
        state["current_id"] = None
        state["playing"] = False
    state["updated_at"] = _stamp()
    save_state(room_id, state)
    await _broadcast(room_id)


async def handle_audio_play(ws, room_id, user, is_dm, msg):
    if not is_dm:
        await _error(ws, "DM only")
        return
    source_id = str(msg.get("source_id") or msg.get("id") or "")
    raw = db.q1("SELECT audio_json FROM room_state WHERE room_id=?", (room_id,))
    state = load_state((raw or {}).get("audio_json"))
    if not any(s.get("id") == source_id for s in state["sources"]):
        await _error(ws, "Unknown audio source")
        return
    state["current_id"] = source_id
    state["playing"] = True
    state["updated_at"] = _stamp()
    save_state(room_id, state)
    await _broadcast(room_id)


async def handle_audio_stop(ws, room_id, user, is_dm, msg):
    if not is_dm:
        await _error(ws, "DM only")
        return
    raw = db.q1("SELECT audio_json FROM room_state WHERE room_id=?", (room_id,))
    state = load_state((raw or {}).get("audio_json"))
    state["current_id"] = None
    state["playing"] = False
    state["updated_at"] = _stamp()
    save_state(room_id, state)
    await _broadcast(room_id)


def list_sounds(user_id):
    return [{"id": r["id"], "name": r["name"], "url": r["url"], "category": r["category"],
             "kind": "direct", "embed": ""}
            for r in db.q("SELECT * FROM soundboard WHERE user_id=? ORDER BY name, id", (user_id,))]


def create_sound(user_id, name, url, category="sfx"):
    name = _clean_text(name, 80)
    if not name:
        return None
    parsed = parse_audio_source(url)
    if parsed is None or parsed["kind"] != "direct":
        return None
    category = str(category or "sfx").lower()
    if category not in CATEGORIES:
        category = "sfx"
    if len(list_sounds(user_id)) >= MAX_SOUNDS:
        return None
    sid = db.x("INSERT INTO soundboard (user_id,name,url,category) VALUES (?,?,?,?)",
               (user_id, name, parsed["url"], category))
    return db.q1("SELECT id,name,url,category FROM soundboard WHERE id=? AND user_id=?", (sid, user_id))


def delete_sound(user_id, sound_id):
    row = db.q1("SELECT id FROM soundboard WHERE id=? AND user_id=?", (sound_id, user_id))
    if row is None:
        return False
    db.x("DELETE FROM soundboard WHERE id=? AND user_id=?", (sound_id, user_id))
    return True


async def handle_sound_trigger(ws, room_id, user, is_dm, msg):
    if not is_dm:
        await _error(ws, "DM only")
        return
    if not _rate_ok(room_id, user["id"], "sound", limit=20, window=5.0):
        return
    try:
        sid = int(msg.get("sound_id") or msg.get("id"))
    except (TypeError, ValueError):
        await _error(ws, "Unknown sound")
        return
    sound = db.q1("SELECT * FROM soundboard WHERE id=? AND user_id=?", (sid, user["id"]))
    if sound is None:
        await _error(ws, "Unknown sound")
        return
    parsed = parse_audio_source(sound["url"])
    if parsed is None or parsed["kind"] != "direct":
        await _error(ws, "Soundboard effects must use a direct audio URL")
        return
    target = msg.get("target", "all")
    target_ids = []
    if str(target or "").lower() in ("all", "everyone", "room", "party"):
        target_ids = sorted(_valid_recipients(room_id, [
            r["user_id"] for r in db.q("SELECT user_id FROM room_members WHERE room_id=?", (room_id,))]))
    else:
        target_ids = _valid_recipients(room_id, [target])
    if not target_ids:
        await _error(ws, "Unknown sound recipient")
        return
    payload = {
        "event_id": secrets.token_hex(6),
        "sound_id": sound["id"],
        "title": _clean_text(sound["name"], 80),
        "category": sound["category"],
        "kind": "direct",
        "url": parsed["url"],
        "at": time.time(),
    }
    for uid in target_ids:
        await send_user(room_id, uid, "sound", payload)
