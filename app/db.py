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
    spell_slots TEXT DEFAULT '{}'
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
    y REAL DEFAULT 100
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id INTEGER NOT NULL REFERENCES rooms(id),
    user_id INTEGER REFERENCES users(id),
    type TEXT NOT NULL DEFAULT 'chat',
    body TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS room_state (
    room_id INTEGER PRIMARY KEY REFERENCES rooms(id),
    initiative TEXT DEFAULT '{"combat": false, "order": [], "active": -1, "round": 0}',
    map_json TEXT DEFAULT ''
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
    try:
        return json.loads(s) if s else default
    except (ValueError, TypeError):
        return default
