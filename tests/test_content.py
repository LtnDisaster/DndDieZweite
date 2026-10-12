"""Sprint 25 Phase A (D95): data-driven content packages.

Pins the CSV content engine + the room-scoped DM import/export REST surface:
validation reports file/line/column, a single bad row rejects only its row's
file, unknown files are skipped, size/zip guards refuse oversized payloads,
formula-injection is escaped on export but round-trips on import, items project
into the DM library (weapon_profiles reads the typed combat props incl. range),
spells register as castable abilities and reload from the DB on "restart",
non-DM/unauthorised writers are refused, and the SHIPPED pack imports clean
across all eight kinds and re-imports byte-idempotently.
"""
import io
import re
import uuid
import zipfile
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from app import abilities, content as C, db, main
from tests.test_movement_fog import H, base_room, reg


@pytest.fixture()
def client():
    return TestClient(main.app)


PACK = Path(__file__).resolve().parents[1] / "app" / "content_pack"


def _post(client, dm, code, body, name="items.csv", mode="apply"):
    return client.post(f"/api/content/{code}/import", content=body,
                       headers=H(dm), params={"name": name, "mode": mode})


def _zip(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, t in files.items():
            z.writestr(n, t)
    return buf.getvalue()


# ---------- pure engine ----------

def test_dice_and_range_validation():
    assert C.valid_dice("1d8") and C.valid_dice("2d6+3")
    assert not C.valid_dice("1d") and not C.valid_dice("d6")
    assert C.valid_dice_bonus("+1d8") and C.valid_dice_bonus("-1d8")
    assert not C.valid_dice_bonus("2d6+3")            # a bonus die has no flat add
    # negative-bound range specs parse (regression on the '-10-10' split bug)
    v, e = C.coerce("item", "attack_bonus", "int:-10-10", "-1")
    assert v == -1 and e is None


def test_formula_escaping_roundtrips():
    assert C._csv_safe("+1d8") == "'+1d8"
    assert C._csv_unescape("'=bad") == "=bad"
    assert C._csv_unescape("plain") == "plain"        # did not escape -> untouched
    assert C._csv_unescape("'not escaped") == "'not escaped"   # an apostrophe we didn't add stays


def test_validate_reports_file_line_column_and_rejects_only_the_file():
    rows, hdr = C.parse("id,name,kind,damage_dice\nsword,Sword,weapon,1d8\nbad,Bad,weapon,NOPE\n")
    clean, errs, warns = C.validate("item", rows, hdr, "items.csv")
    assert len(clean) == 2
    assert any(e["line"] == 3 and e["column"] == "damage_dice" for e in errs)
    # missing required name -> error on that column
    r2, h2 = C.parse("id,name,kind\nx,,weapon\n")
    _, e2, _ = C.validate("item", r2, h2, "items.csv")
    assert any(e["column"] == "name" for e in e2)
    # duplicate id within a file is an error
    r3, h3 = C.parse("id,name,kind\nx,A,weapon\nx,B,weapon\n")
    _, e3, _ = C.validate("item", r3, h3, "items.csv")
    assert any("duplicate" in e["msg"] for e in e3)
    # unknown column is a warning, not an error
    r4, h4 = C.parse("id,name,kind,colour\nx,A,weapon,red\n")
    _, e4, w4 = C.validate("item", r4, h4, "items.csv")
    assert not e4 and any(w["column"] == "colour" for w in w4)


def test_class_level_rows_share_an_id_without_false_duplicates():
    rows, hdr = C.parse("id,level,hit_die\nscout,1,8\nscout,2,8\nscout,3,8\n")
    clean, errs, _ = C.validate("class", rows, hdr, "classes.csv")
    assert len(clean) == 3 and not errs               # id repeats across levels: OK
    rows2, hdr2 = C.parse("id,level\nscout,3\nscout,3\n")
    _, errs2, _ = C.validate("class", rows2, hdr2, "classes.csv")
    assert any("duplicate" in e["msg"] for e in errs2)  # same id AND level: conflict


def test_spell_maps_to_a_valid_ability_definition():
    rows, hdr = C.parse(
        "id,name,level,casting_ability,targeting,resolution,save,on_save,damage_dice,damage_type,shape,size_ft\n"
        "bolt,Bolt,2,int,area,save,dex,half,8d6,fire,circle,20\n")
    clean, errs, _ = C.validate("spell", rows, hdr, "spells.csv")
    assert not errs
    abilities.clear_registry()
    defn = C.map_to_ability(clean[0])
    assert defn and defn["cost"] == {"type": "spell_slot", "level": 2}
    assert abilities.register(defn) is not None


# ---------- shipped pack (all eight kinds) ----------

def test_shipped_pack_imports_clean_across_all_kinds(client):
    dm, _player, code, _ch = base_room(client)
    files = {p.name: p.read_text(encoding="utf-8") for p in PACK.glob("*.csv")}
    rep = C.import_package(files, room_id=db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"],
                           mode="apply", apply=True)
    assert rep["ok"], [f for f in rep["files"] if not f["valid"]]
    for f in rep["files"]:
        assert f["valid"] and f["errors"] == []


def test_shipped_pack_reimports_idempotently(client):
    dm, _player, code, _ch = base_room(client)
    rid = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
    files = {p.name: p.read_text(encoding="utf-8") for p in PACK.glob("*.csv")}
    C.import_package(files, room_id=rid, mode="apply", apply=True)
    # every kind re-imports from its own export as 'unchanged'
    for kind in C.ALL_KINDS:
        rep = C.import_package({C.KIND_FILE[kind]: C.export_csv(kind, rid)},
                               room_id=rid, mode="apply", apply=True)
        st = rep["applied"][kind]
        assert st["inserted"] == 0 and st["conflicts"] == [] and st["unchanged"] > 0


# ---------- REST: authorisation ----------

def test_content_endpoints_require_dm(client):
    dm, player, code, _ch = base_room(client)
    outsider = reg(client, "outs")
    body = "id,name,kind\nsword,Sword,weapon\n".encode()
    # the TestClient shares one cookie jar; clear it so a "no-auth" call is truly unauthenticated
    client.cookies.clear()
    # no auth
    assert client.post(f"/api/content/{code}/import", content=body,
                       params={"name": "items.csv", "mode": "apply"}).status_code == 401
    # a player (member but not DM) is refused
    assert _post(client, player, code, body).status_code == 403
    # an outsider is refused (room_of -> 403)
    assert client.post(f"/api/content/{code}/import", content=body, headers=H(outsider),
                       params={"name": "items.csv"}).status_code == 403
    # export is DM-only too
    client.cookies.clear()
    assert client.get(f"/api/content/{code}/export", params={"kind": "item"}).status_code == 401
    assert client.get(f"/api/content/{code}/export", params={"kind": "item"},
                      headers=H(player)).status_code == 403
    assert client.get(f"/api/content/{code}/kinds", headers=H(player)).status_code == 403


def test_import_preview_writes_nothing_then_apply_writes(client):
    dm, _p, code, _ch = base_room(client)
    body = "id,name,kind,weight\nsword,Sword,weapon,3\n".encode()
    prev = _post(client, dm, code, body, mode="preview").json()
    assert prev["ok"] and prev["mode"] == "preview"
    rid = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
    assert db.q1("SELECT 1 FROM content WHERE kind='item' AND room_id=?", (rid,)) is None
    # now apply
    assert _post(client, dm, code, body, mode="apply").json()["ok"]
    assert db.q1("SELECT 1 FROM content WHERE kind='item' AND room_id=? AND id='sword'", (rid,))


def test_import_reports_row_error_and_refuses_to_write_that_file(client):
    dm, _p, code, _ch = base_room(client)
    rid = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
    body = "id,name,kind\nsword,Sword,weapon\nring,Ring,notakind\n".encode()
    rep = _post(client, dm, code, body, mode="apply").json()
    assert rep["ok"] is False
    entry = rep["files"][0]
    assert any(e["column"] == "kind" for e in entry["errors"])
    # the whole file is refused (even the good row) because one row failed
    assert db.q1("SELECT 1 FROM content WHERE kind='item' AND room_id=?", (rid,)) is None


def test_items_project_into_dm_library_with_typed_combat_props(client):
    dm, _p, code, _ch = base_room(client)
    rid = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
    # item_defs.id is GLOBAL (per-room keys need a destructive rebuild — see D100),
    # so the SAME shipped id imported by an earlier test's room would make THIS
    # room's projection conflict-and-skip by design. Give the imported rows
    # run-unique ids so THIS room reliably owns its DM-library rows; the shipped
    # typed columns are still exercised verbatim.
    uid = uuid.uuid4().hex[:6]
    sp, bl = f"sword_plus1_{uid}", f"bow_long_{uid}"
    items = ((PACK / "items.csv").read_text(encoding="utf-8")
             .replace("sword_plus1", sp).replace("bow_long", bl))
    assert _post(client, dm, code, items.encode(), name="items.csv").json()["ok"]
    # the content row is stored scoped to THIS room
    assert db.q1("SELECT 1 FROM content WHERE kind='item' AND room_id=? AND id=?", (rid, sp))
    # item_defs carries a room-scoped owner (D100): read it back BY ROOM + id so a
    # same-named definition from another room in the shared test DB cannot leak in.
    props = db.j(db.q1("SELECT props FROM item_defs WHERE room_id=? AND id=?",
                       (rid, sp))["props"], {})
    assert props["damage_dice"] == "1d8" and props["attack_bonus"] == 1 and props["damage_bonus"] == 1
    bow = db.j(db.q1("SELECT props FROM item_defs WHERE room_id=? AND id=?",
                     (rid, bl))["props"], {})
    assert bow["range_ft"] == 150 and bow["range_long_ft"] == 600
    assert C.valid_dice(bow["damage_dice"]) and bow["two_handed"] is True


def test_spells_register_and_reload_from_db_on_restart(client):
    dm, _p, code, _ch = base_room(client)
    rid = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
    spells = (PACK / "spells.csv").read_text(encoding="utf-8")
    assert _post(client, dm, code, spells.encode(), name="spells.csv").json()["ok"]
    assert abilities.get("bolt") is not None
    # simulate a restart: registry is cleared, reload repopulates from the DB
    abilities.clear_registry()
    assert abilities.get("bolt") is None
    assert C.load_registered_abilities() >= 1
    assert abilities.get("bolt") is not None


def test_export_escapes_formula_injection(client):
    dm, _p, code, _ch = base_room(client)
    rid = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
    row = {c[0]: "" for c in C.SCHEMAS["item"]} | {"id": "evil", "name": "=HYPERLINK()", "kind": "other"}
    C.store("item", rid, row)
    txt = client.get(f"/api/content/{code}/export", params={"kind": "item"},
                     headers=H(dm)).text
    evil = [l for l in txt.splitlines() if l.startswith("evil")]
    assert evil and evil[0].split(",")[1].startswith("'=")   # neutralised


def test_export_all_is_a_valid_zip_and_reimports(client):
    dm, _p, code, _ch = base_room(client)
    rid = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
    _post(client, dm, code, (PACK / "species.csv").read_text(encoding="utf-8").encode(), name="species.csv")
    r = client.get(f"/api/content/{code}/export", params={"all": "true"}, headers=H(dm))
    assert r.status_code == 200 and r.content[:2] == b"PK"
    # the export of species.csv alone must re-import as unchanged into the same room
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        species_txt = z.read("species.csv").decode("utf-8")
    rep = C.import_package({"species.csv": species_txt}, room_id=rid, mode="apply", apply=True)
    assert rep["applied"]["species"]["inserted"] == 0


def test_zip_package_import_auto_detected(client):
    dm, _p, code, _ch = base_room(client)
    rid = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
    zbody = _zip({"feats.csv": "id,name,effect\nfeat_tough,Tough,extra hit points\n",
                  "species.csv": "id,name,traits\nkin_x,X,quick\n"})
    assert client.post(f"/api/content/{code}/import", content=zbody, headers=H(dm),
                       params={"mode": "apply"}).json()["ok"]
    assert db.q1("SELECT 1 FROM content WHERE kind='feat' AND room_id=?", (rid,))


def test_unknown_file_is_skipped_not_fatal(client):
    dm, _p, code, _ch = base_room(client)
    rep = _post(client, dm, code, "a,b,c\n1,2,3\n".encode(), name="notes.csv", mode="apply").json()
    assert any(f.get("ignored") for f in rep["files"])
    assert rep["ok"] is False                          # an unknown file is flagged, not written


def test_conflict_then_replace(client):
    dm, _p, code, _ch = base_room(client)
    rid = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
    _post(client, dm, code, "id,name,kind\nsword,Sword,weapon\n".encode())
    # a DIFFERENT payload for the same id under apply -> conflict, no overwrite
    rep = _post(client, dm, code, "id,name,kind\nsword,Renamed,weapon\n".encode()).json()
    assert rep["applied"]["item"]["conflicts"] == ["sword"]
    assert db.q1("SELECT name FROM content WHERE kind='item' AND room_id=? AND id='sword'", (rid,))["name"] == "Sword"
    # replace overwrites
    rep2 = _post(client, dm, code, "id,name,kind\nsword,Renamed,weapon\n".encode(), mode="replace").json()
    assert rep2["applied"]["item"]["replaced"] == 1
    assert db.q1("SELECT name FROM content WHERE kind='item' AND room_id=? AND id='sword'", (rid,))["name"] == "Renamed"


def test_oversized_package_is_refused(client):
    dm, _p, code, _ch = base_room(client)
    big = b"x" * (C.MAX_FILE + 10)
    r = _post(client, dm, code, big, mode="apply")
    assert r.status_code == 400


# ---------- DM panel wiring (the UI must not silently drift from the API) ----------

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"


def _js(name):
    return (STATIC / "js" / name).read_text(encoding="utf-8")


def test_dm_content_panel_is_wired():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    # the module loads, and before the integrity gate
    order = re.findall(r"/static/js/([0-9A-Za-z_]+\.js)", html)
    assert "70_content.js" in order and order.index("70_content.js") < order.index("99_boot.js")
    # panel controls the JS binds to actually exist
    for cid in ("ct-file", "ct-mode", "btn-ct-upload", "ct-report", "ct-kinds",
                "ct-export-kind", "btn-ct-export", "btn-ct-export-zip"):
        assert f'id="{cid}"' in html, f"missing panel element {cid}"
    # boot gate knows the module and requires its entrypoint
    boot = _js("99_boot.js")
    assert '"70_content.js"' in boot.split("MODULES")[1].split("]")[0]
    assert '"wireContent"' in boot.split("REQUIRED")[1].split("]")[0]
    # appBoot calls it, and the DM room render refreshes the counts
    assert "wireContent();" in _js("60_main.js")
    assert "refreshContentKinds()" in _js("30_room.js")
    # the JS reads the report's real keys (file, not a made-up name)
    js = _js("70_content.js")
    assert "f.file" in js and "ct-report" in js
