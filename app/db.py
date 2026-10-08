"""SQLite persistence for the D&D VTT."""
import json
import os
import sqlite3
import threading
from contextlib import contextmanager

DATA_DIR = os.environ.get("VTT_DATA_DIR", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"))
DB_PATH = os.path.join(DATA_DIR, "vtt.db")

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    pw_hash TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS characters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,
    race TEXT DEFAULT '',
    char_class TEXT DEFAULT '',
    level INTEGER DEFAULT 1,
    stats TEXT DEFAULT '{}',
    hp INTEGER DEFAULT 10,
    max_hp INTEGER DEFAULT 10,
    ac INTEGER DEFAULT 10,
    speed INTEGER DEFAULT 30,
    notes TEXT DEFAULT '',
    weapons TEXT DEFAULT '[]',
    items TEXT DEFAULT '[]',
    skills TEXT DEFAULT '{}',
    spells TEXT DEFAULT '[]',
    spell_slots TEXT DEFAULT '{}',
    saves TEXT DEFAULT '{}',
    temp_hp INTEGER DEFAULT 0,
    inspiration INTEGER DEFAULT 0,
    exhaustion INTEGER DEFAULT 0,
    hit_die INTEGER DEFAULT 8,
    hit_dice_spent INTEGER DEFAULT 0,
    resources TEXT DEFAULT '[]',
    defenses TEXT DEFAULT '{}',
    class_levels TEXT DEFAULT '',
    abilities TEXT DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS creatures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,
    block TEXT DEFAULT '{}',
    tags TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS rooms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    dm_id INTEGER NOT NULL REFERENCES users(id),
    map_image TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS room_members (
    room_id INTEGER NOT NULL REFERENCES rooms(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    role TEXT NOT NULL DEFAULT 'player',
    character_id INTEGER REFERENCES characters(id),
    joined_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (room_id, user_id)
);
CREATE TABLE IF NOT EXISTS tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id INTEGER NOT NULL REFERENCES rooms(id),
    owner_user_id INTEGER REFERENCES users(id),
    character_id INTEGER REFERENCES characters(id),
    label TEXT NOT NULL,
    color TEXT DEFAULT '#888',
    x REAL DEFAULT 100,
    y REAL DEFAULT 100,
    npc TEXT DEFAULT '',
    conds TEXT DEFAULT '[]',
    death TEXT,
    disposition TEXT DEFAULT '',
    size TEXT DEFAULT 'Medium'
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id INTEGER NOT NULL REFERENCES rooms(id),
    user_id INTEGER REFERENCES users(id),
    type TEXT NOT NULL DEFAULT 'chat',
    body TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    visibility TEXT NOT NULL DEFAULT 'public',
    recipient_user_id INTEGER REFERENCES users(id),
    meta TEXT DEFAULT '{}',
    channel TEXT DEFAULT '',
    recipient_ids TEXT DEFAULT '[]',
    persona TEXT DEFAULT '',
    sender_kind TEXT DEFAULT 'user',
    npc_token_id INTEGER,
    style TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS room_state (
    room_id INTEGER PRIMARY KEY REFERENCES rooms(id),
    initiative TEXT DEFAULT '{"combat": false, "order": [], "active": -1, "round": 0}',
    map_json TEXT DEFAULT '',
    audio_json TEXT DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS soundboard (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    category TEXT DEFAULT 'sfx',
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_messages_room_type_created
    ON messages (room_id, type, created_at);
CREATE TABLE IF NOT EXISTS encounters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,
    notes TEXT DEFAULT '',
    entries TEXT DEFAULT '[]',
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id INTEGER NOT NULL REFERENCES rooms(id),
    user_id INTEGER REFERENCES users(id),
    category TEXT DEFAULT 'notes',
    title TEXT NOT NULL,
    body TEXT DEFAULT '',
    visibility TEXT NOT NULL DEFAULT 'dm',
    recipients TEXT DEFAULT '[]',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS quests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id INTEGER NOT NULL REFERENCES rooms(id),
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    objectives TEXT DEFAULT '[]',
    visibility TEXT DEFAULT 'party',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS floor_maps(
  room_id  INTEGER NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
  floor    TEXT    NOT NULL,
  map_json TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS assets (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,
    file TEXT NOT NULL,
    w INTEGER NOT NULL,
    h INTEGER NOT NULL,
    bytes INTEGER NOT NULL,
    sha TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);
"""


def conn() -> sqlite3.Connection:
    c = getattr(_local, "conn", None)
    if c is None:
        os.makedirs(DATA_DIR, exist_ok=True)
        # isolation_level=None => autocommit; multi-statement writes opt into an
        # explicit transaction via tx() so we control BEGIN/COMMIT and lock timing.
        c = sqlite3.connect(DB_PATH, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=4000")
        c.execute("PRAGMA foreign_keys=ON")
        _local.conn = c
    return c


@contextmanager
def tx():
    """Explicit transaction on the thread's connection: BEGIN IMMEDIATE … COMMIT.

    Use for multi-statement writes so they are all-or-nothing (e.g. create room +
    seed member/state/message). No await/other work should happen inside it.
    """
    c = conn()
    c.execute("BEGIN IMMEDIATE")
    try:
        yield c
    except BaseException:
        try:
            c.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
    else:
        c.execute("COMMIT")


def init_db():
    c = conn()
    c.executescript(SCHEMA)
    # D88: (room_id, floor) must be unique for set_map's upsert. DBs created
    # mid-sprint hold the unindexed table (possibly with duplicates) —
    # keep-last, then index. Idempotent on fresh DBs.
    c.execute("DELETE FROM floor_maps WHERE rowid NOT IN "
              "(SELECT MAX(rowid) FROM floor_maps GROUP BY room_id, floor)")
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS floor_maps_ux "
              "ON floor_maps(room_id, floor)")
    def migrate(table, col, ddl):
        cols = [r["name"] for r in c.execute(f"PRAGMA table_info({table})").fetchall()]
        if col not in cols:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")
    migrate("room_state", "map_json", "map_json TEXT DEFAULT ''")
    migrate("characters", "weapons", "weapons TEXT DEFAULT '[]'")
    migrate("characters", "items", "items TEXT DEFAULT '[]'")
    migrate("characters", "skills", "skills TEXT DEFAULT '{}'")
    migrate("characters", "spells", "spells TEXT DEFAULT '[]'")
    migrate("characters", "spell_slots", "spell_slots TEXT DEFAULT '{}'")
    migrate("tokens", "npc", "npc TEXT DEFAULT ''")
    migrate("tokens", "conds", "conds TEXT DEFAULT '[]'")
    migrate("tokens", "death", "death TEXT")
    migrate("tokens", "disposition", "disposition TEXT DEFAULT ''")
    migrate("tokens", "size", "size TEXT DEFAULT 'Medium'")
    migrate("tokens", "fw", "fw INTEGER")   # D81: custom footprint width (NULL = square of size)
    migrate("tokens", "fh", "fh INTEGER")   # D81: custom footprint height (NULL = square of size)
    migrate("tokens", "z", "z INTEGER DEFAULT 0")
    migrate("tokens", "vw", "vw INTEGER")   # D82: visual width (NULL = mechanical span; RENDER ONLY)
    migrate("tokens", "vh", "vh INTEGER")   # D82: visual height (NULL = mechanical span; RENDER ONLY)
    migrate("tokens", "rot", "rot INTEGER")  # D82: visual facing 0/90/180/270 (NULL = 0; RENDER ONLY)
    # D82: generic CONTROLLER relationship (companion foundation) — a room
    # member may act through the token; NOT ownership, NOT an account.
    migrate("tokens", "controller_user_id",
            "controller_user_id INTEGER REFERENCES users(id)")
    # D82: generic MOUNT relationship — a token MAY ride exactly one other
    # token in the same room. Acyclic by construction; NOT the controller
    # relationship; carrying movement is a separate, later mechanic.
    migrate("tokens", "mount_token_id", "mount_token_id INTEGER REFERENCES tokens(id)")
    # D85: token artwork — server-generated "/assets/<id>" reference only
    # (see app/assets.py); never a client-supplied path or URL.
    migrate("tokens", "image", "image TEXT DEFAULT ''")
    # D86: floor of residence — '' = the primary (legacy) floor, so every
    # existing token lives on the default level with no data migration.
    migrate("tokens", "floor", "floor TEXT DEFAULT ''")
    # D87: light radius in grid cells a token EMITS (0 = none). Only matters
    # in DARK rooms (grid.dark); the DM branch never restricts.
    migrate("tokens", "light", "light INTEGER DEFAULT 0")
    migrate("tokens", "darkvision", "darkvision INTEGER DEFAULT 0")   # D89
    # D86: the room's floor list — JSON [{name}], '' = primary (legacy) floor.
    migrate("rooms", "floors", "floors TEXT DEFAULT '[]'")
    migrate("messages", "visibility", "visibility TEXT NOT NULL DEFAULT 'public'")
    migrate("messages", "recipient_user_id", "recipient_user_id INTEGER REFERENCES users(id)")
    migrate("messages", "meta", "meta TEXT DEFAULT '{}'")
    migrate("characters", "saves", "saves TEXT DEFAULT '{}'")
    migrate("characters", "temp_hp", "temp_hp INTEGER DEFAULT 0")
    migrate("characters", "inspiration", "inspiration INTEGER DEFAULT 0")
    migrate("characters", "exhaustion", "exhaustion INTEGER DEFAULT 0")
    migrate("characters", "hit_die", "hit_die INTEGER DEFAULT 8")
    migrate("characters", "hit_dice_spent", "hit_dice_spent INTEGER DEFAULT 0")
    migrate("characters", "resources", "resources TEXT DEFAULT '[]'")
    migrate("characters", "defenses", "defenses TEXT DEFAULT '{}'")
    migrate("messages", "channel", "channel TEXT DEFAULT ''")
    migrate("messages", "recipient_ids", "recipient_ids TEXT DEFAULT '[]'")
    migrate("messages", "persona", "persona TEXT DEFAULT ''")
    migrate("messages", "sender_kind", "sender_kind TEXT DEFAULT 'user'")
    migrate("messages", "npc_token_id", "npc_token_id INTEGER")
    migrate("messages", "style", "style TEXT DEFAULT ''")
    migrate("room_state", "audio_json", "audio_json TEXT DEFAULT '{}'")
    migrate("characters", "class_levels", "class_levels TEXT DEFAULT ''")
    migrate("characters", "abilities", "abilities TEXT DEFAULT '[]'")
    c.execute("CREATE INDEX IF NOT EXISTS idx_messages_room_type_created "
              "ON messages (room_id, type, created_at)")
    c.commit()


def q(sql, args=()):
    return [dict(r) for r in conn().execute(sql, args).fetchall()]


def q1(sql, args=()):
    r = conn().execute(sql, args).fetchone()
    return dict(r) if r else None


def x(sql, args=()):
    c = conn()
    cur = c.execute(sql, args)
    c.commit()
    return cur.lastrowid


def json_dumps(d) -> str:
    return json.dumps(d if d is not None else {})


def j(s, default=None):
    """Parse a JSON column. Idempotent: an already-parsed dict/list passes
    through unchanged — sheets loaded via gear.as_sheet() hold parsed columns,
    and re-'parsing' them must never silently yield the default."""
    if isinstance(s, (dict, list)):
        return s
    try:
        return json.loads(s) if s else default
    except (ValueError, TypeError):
        return default
