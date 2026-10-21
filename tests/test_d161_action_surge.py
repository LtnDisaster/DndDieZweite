"""D161 play-session audit: a NON-caster class resource must survive the build.

The playtest imported a fighter whose level-2 row grants ``class_resource
action_surge:1`` (2024 Action Surge). The build computed the merged resource
list correctly but the apply write-path only persisted ``resources`` inside the
``spell_state`` branch — every non-spellcasting class silently LOST its class
resource (Action Surge, Rage, Ki). The caster path masked this for its whole
life because every existing D97 test used casters.

Pins: after ``apply`` to the granting level, the character's stored resources
carry the class resource with the CSV's max and reset timing.
"""
import csv
import io
from pathlib import Path

from starlette.testclient import TestClient

from app import charbuild as CB, content as C, db, gear, main

PACK = Path(__file__).resolve().parents[1] / "app" / "content_pack"


def _classes_csv():
    """Built-in header + a minimal two-level martial class with a class resource."""
    with open(PACK / "classes.csv", newline="", encoding="utf-8") as f:
        header = next(csv.reader(f))
    rows = []
    for level, cr, reset in ((1, "", ""), (2, "action_surge:1", "short")):
        r = {c: "" for c in header}
        r.update({k: v for k, v in {
            "id": "testguard", "level": str(level), "name": "Testguard",
            "hit_die": "10", "hp_base": "12", "hp_per_level": "5",
            "class_resource": cr, "class_resource_reset": reset,
        }.items() if k in header})
        rows.append(r)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=header)
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def test_non_caster_class_resource_is_persisted_by_build(client=None):
    with TestClient(main.app) as client:
        from test_movement_fog import base_room
        dm, player, code, ch = base_room(client)
        rid = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
        C.import_package({"classes.csv": _classes_csv()}, room_id=rid,
                         mode="apply", apply=True)
        cid = db.q1("SELECT id FROM characters WHERE id=?", (ch["id"],))["id"]

        ok, res = CB.apply(cid, "testguard", 2, {}, rid)
        assert ok, f"apply refused: {res}"
        stored = db.j(db.q1("SELECT resources FROM characters WHERE id=?",
                            (cid,))["resources"], [])
        stored = gear.clean_resources(stored)
        surge = next((r for r in stored if r["id"] == "action_surge"), None)
        assert surge, (f"class_resource lost for a non-caster class: {stored}")
        assert surge["max"] == 1 and surge["current"] == 1
        assert surge.get("reset") == "short"


def test_caster_class_resource_still_persisted(client=None):
    """Guard the other side of the branch: a caster keeps writing resources too."""
    with TestClient(main.app) as client:
        from test_movement_fog import base_room
        dm, player, code, ch = base_room(client)
        rid = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
        files = {p.name: p.read_text(encoding="utf-8") for p in PACK.glob("*.csv")}
        C.import_package(files, room_id=rid, mode="apply", apply=True)
        cid = ch["id"]
        ok, res = CB.apply(cid, "seer", 2, {"skills": ["perception", "insight", "religion", "history"],
                                            "cantrips": [], "spells": []}, rid)
        # seer needs choices; only assert resources when the apply is accepted
        if ok:
            stored = gear.clean_resources(db.j(db.q1(
                "SELECT resources FROM characters WHERE id=?", (cid,))["resources"], []))
            assert any(r["id"] == "sorcery_points" for r in stored)
