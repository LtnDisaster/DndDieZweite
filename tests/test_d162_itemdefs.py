"""D162-9 — the item_defs key migration, tested on ISOLATED scratch databases
only (GO #4: the real DB is never the test subject; the running test DB is a
throwaway anyway, but the migration itself runs against throwaway sqlite
files so the heal/backup/fail-closed behaviour is proven standalone)."""
import sqlite3

from app import db

LEGACY_DDL = """
CREATE TABLE rooms (id INTEGER PRIMARY KEY);
CREATE TABLE users (id INTEGER PRIMARY KEY);
CREATE TABLE item_defs (
    id TEXT PRIMARY KEY,
    room_id INTEGER NOT NULL REFERENCES rooms(id),
    name TEXT NOT NULL,
    desc TEXT DEFAULT '',
    kind TEXT DEFAULT 'other',
    weight REAL DEFAULT 0,
    stackable INTEGER DEFAULT 0,
    props TEXT DEFAULT '{}',
    created_by INTEGER REFERENCES users(id),
    created_at TEXT DEFAULT (datetime('now')),
    value REAL DEFAULT 0
);
"""


def scratch(rows):
    c = sqlite3.connect(":memory:")
    c.executescript(LEGACY_DDL)
    c.executemany("INSERT INTO item_defs(id, room_id, name) VALUES (?,?,?)", rows)
    c.commit()
    return c


def test_migration_swaps_to_composite_key_with_backup():
    # the legacy global id could only ever hold ONE row per id (that WAS the
    # bug — the second room got refused). Real migration = re-key every row to
    # (room_id,id); afterwards two rooms may legitimately share an id.
    c = scratch([("ring", 1, "Ring A"), ("blade", 2, "Blade B")])
    assert db.migrate_item_defs(c) == "migrated"
    pk = {r[1]: r[5] for r in c.execute("PRAGMA table_info(item_defs)")}
    assert pk["room_id"] == 1 and pk["id"] == 2          # composite PK now
    both = dict(c.execute("SELECT room_id, name FROM item_defs"))
    assert both == {1: "Ring A", 2: "Blade B"}           # nothing lost, no renumbering
    # the same id can exist twice side by side now:
    c.execute("INSERT INTO item_defs(id, room_id, name) VALUES('ring', 2, 'Ring B')")
    assert c.execute("SELECT COUNT(*) FROM item_defs WHERE id='ring'").fetchone()[0] == 2
    backup = c.execute("SELECT COUNT(*) FROM item_defs_pre_d162").fetchone()[0]
    assert backup == 2                                   # byte copy kept, restorable
    # restorable: the backup still carries the SINGLE-key shape (id PRIMARY KEY)
    assert any(r[1] == "id" and r[5] == 1 for r in c.execute("PRAGMA table_info(item_defs_pre_d162)"))
    assert db.migrate_item_defs(c) == "skip"             # idempotent re-run


def test_heal_path_is_defensively_wired():
    # The legacy id PRIMARY KEY made duplicate (room,id) rows STRUCTURALLY
    # impossible, so the heal (INSERT OR REPLACE over rowid order) is belt &
    # braces for any hand-repaired historic DB. It must exist as the copy
    # statement — a silent plain INSERT would be the regression.
    import inspect
    src = inspect.getsource(db.migrate_item_defs)
    assert "INSERT OR REPLACE INTO item_defs_new" in src
    assert "ORDER BY rowid" in src


def test_fail_closed_on_unexpected_shape():
    c = sqlite3.connect(":memory:")
    c.executescript(LEGACY_DDL.replace("value REAL DEFAULT 0", "xcol TEXT DEFAULT ''"))
    c.execute("INSERT INTO item_defs(id, room_id, name) VALUES('a',1,'A')")
    c.commit()
    assert db.migrate_item_defs(c) == "abort"            # missing value column
    assert c.execute("SELECT COUNT(*) FROM item_defs").fetchone()[0] == 1
    assert c.execute("SELECT name FROM item_defs WHERE id='a'").fetchone()[0] == "A"
    # the half-built table is never left behind
    assert c.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='item_defs_new'").fetchone()[0] == 0


def test_real_test_db_is_already_composite_and_skips():
    # the running (throwaway) DB is fresh → the swap must report skip, and the
    # cross-room upsert in the G9 tests runs on the composite key directly.
    c = db.conn()
    assert db.migrate_item_defs(c) == "skip"
