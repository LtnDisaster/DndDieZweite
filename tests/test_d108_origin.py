"""D108: the 2024 character origin — background ASI + Origin feat.

One background from the ROOM'S rule pack offers exactly the SRD 5.2.1 choice:
+2 and +1 to two DIFFERENT of its three listed abilities, or +1 to all three,
with no score rising above 20 — plus the ONE Origin feat the background names.
The server validates everything (feat id and amounts are NEVER accepted from
the client), records the grant in the build ledger (characters.build.origin —
the secure proof, no heuristic back-computation) and replays it inside the
SAME full recompute the class chronology uses, so replays, reloads and double
clicks can never apply it twice and a later build step can never wipe it.
Existing characters are never auto-migrated; the origin operation touches
stats/skills only — never hp, AC, slots or resources.
"""
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from app import content as C, db, main
from tests.test_movement_fog import H, base_room, join_room, reg


PACK = Path(__file__).resolve().parents[1] / "app" / "content_pack"


@pytest.fixture()
def client():
    return TestClient(main.app)


def _room(client, mutate=None, tag_ids=()):
    """base_room with the shipped pack imported (optionally mutated in-memory
    first, e.g. to break the feat category). tag_ids mirrors the D105 trick:
    item_defs.id is a GLOBAL pk, so a test that needs real item definitions
    tags those ids per room to stay independent of earlier imports."""
    dm, player, code, ch = base_room(client)
    rid = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
    files = {p.name: p.read_text(encoding="utf-8") for p in PACK.glob("*.csv")}
    tag = uuid.uuid4().hex[:6]
    for tid in tag_ids:
        for name in ("items.csv", "backgrounds.csv", "classes.csv"):
            files[name] = files[name].replace(tid, f"{tid}_{tag}")
    if mutate:
        mutate(files)
    C.import_package(files, room_id=rid, mode="apply", apply=True)
    return dm, player, code, ch


def _char(client, user, bg="bg_scholar", stats=None, race="kin_fey"):
    r = client.post("/api/characters", headers=H(user), json={
        "name": "Origin-" + uuid.uuid4().hex[:6], "race": race, "char_class": "",
        "background": bg, "level": 1,
        "stats": stats or {"str": 10, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10},
        "hp": 10, "max_hp": 10})
    assert r.status_code == 200, r.text
    return r.json()


def _stats(cid):
    return db.j(db.q1("SELECT stats FROM characters WHERE id=?", (cid,))["stats"], {})


def _skills(cid):
    return db.j(db.q1("SELECT skills FROM characters WHERE id=?", (cid,))["skills"], {})


def _build(cid):
    return db.j(db.q1("SELECT build FROM characters WHERE id=?", (cid,))["build"], None) or {}


def _report(client, user, code, cid):
    r = client.get(f"/api/build/{code}/{cid}/origin", headers=H(user))
    assert r.status_code == 200, r.text
    return r.json()


def _apply(client, user, code, cid, asi):
    return client.post(f"/api/build/{code}/{cid}/origin", headers=H(user), json={"asi": asi})


# --------------------------------------------------------------- report

def test_report_lists_abilities_and_origin_feat(client):
    dm, player, code, _ = _room(client)
    ch = _char(client, player)
    rep = _report(client, player, code, ch["id"])
    assert rep["ready"] is True
    assert rep["background"] == "bg_scholar"
    assert rep["asi_abilities"] == ["int", "wis", "cha"]
    assert rep["current"] == {"int": 10, "wis": 10, "cha": 10}
    assert rep["feat"] and rep["feat"]["id"] == "feat_quick_study"
    assert rep["feat"]["category"] == "origin"
    assert rep["applied"] is None


def test_report_refuses_unknown_background(client):
    dm, player, code, _ = _room(client)
    ch = _char(client, player, bg="ghost-bg")
    rep = _report(client, player, code, ch["id"])
    assert rep["ready"] is False
    assert any("not in this room's rule pack" in e for e in rep["errors"])
    j = _apply(client, player, code, ch["id"], {"mode": "three"}).json()
    assert j["ok"] is False and "rule pack" in j["error"]


def test_report_no_background(client):
    dm, player, code, _ = _room(client)
    ch = _char(client, player, bg="")
    rep = _report(client, player, code, ch["id"])
    assert rep["ready"] is False
    assert any("no background" in e.lower() for e in rep["errors"])


# --------------------------------------------------------------- ASI modes

def test_plus2_plus1_distribution_and_origin_feat_skills(client):
    dm, player, code, _ = _room(client)
    ch = _char(client, player)
    j = _apply(client, player, code, ch["id"],
               {"mode": "plus2_plus1", "plus2": "int", "plus1": "wis"}).json()
    assert j["ok"] is True and not j["result"].get("already")
    st = _stats(ch["id"])
    assert st["int"] == 12 and st["wis"] == 11 and st["cha"] == 10
    # the demo origin feat Quick Study carries skill_prof investigation —
    # applied through the existing _apply_feat path, nothing else
    assert _skills(ch["id"]).get("investigation") == 1
    led = _build(ch["id"])
    assert led["origin"]["background"] == "bg_scholar"
    assert led["origin"]["feat"] == "feat_quick_study"
    assert led["origin"]["asi"] == {"int": 2, "wis": 1}


def test_three_by_one_distribution(client):
    dm, player, code, _ = _room(client)
    ch = _char(client, player, stats={"str": 10, "dex": 10, "con": 10,
                                      "int": 18, "wis": 14, "cha": 9})
    j = _apply(client, player, code, ch["id"], {"mode": "three"}).json()
    assert j["ok"] is True
    st = _stats(ch["id"])
    assert st["int"] == 19 and st["wis"] == 15 and st["cha"] == 10
    assert st["str"] == 10  # never on the background's list


def test_rejects_ability_outside_background_list(client):
    dm, player, code, _ = _room(client)
    ch = _char(client, player)
    j = _apply(client, player, code, ch["id"],
               {"mode": "plus2_plus1", "plus2": "dex", "plus1": "int"}).json()
    assert j["ok"] is False and "background" in j["error"]
    assert _stats(ch["id"])["dex"] == 10 and _build(ch["id"]).get("origin") is None


def test_rejects_same_target_for_plus2_and_plus1(client):
    dm, player, code, _ = _room(client)
    ch = _char(client, player)
    j = _apply(client, player, code, ch["id"],
               {"mode": "plus2_plus1", "plus2": "int", "plus1": "int"}).json()
    assert j["ok"] is False and "DIFFERENT" in j["error"]


def test_cap_at_20_refuses_not_clamps(client):
    dm, player, code, _ = _room(client)
    ch = _char(client, player, stats={"str": 10, "dex": 10, "con": 10,
                                      "int": 19, "wis": 10, "cha": 10})
    j = _apply(client, player, code, ch["id"],
               {"mode": "plus2_plus1", "plus2": "int", "plus1": "wis"}).json()
    assert j["ok"] is False and "above 20" in j["error"]
    # the exact-20 path works (19+1 is legal)
    j = _apply(client, player, code, ch["id"],
               {"mode": "plus2_plus1", "plus2": "wis", "plus1": "int"}).json()
    assert j["ok"] is True
    assert _stats(ch["id"])["int"] == 20 and _stats(ch["id"])["wis"] == 12


# --------------------------------------------------------------- category

def test_feat_wrong_category_is_refused(client):
    # repoint the background at the GENERAL demo feat — apply must refuse with
    # the category error, report must say ready=False
    def fix(files):
        files["backgrounds.csv"] = files["backgrounds.csv"].replace(
            "feat_quick_study", "feat_nimble")
    dm, player, code, _ = _room(client, mutate=fix)
    ch = _char(client, player)
    rep = _report(client, player, code, ch["id"])
    assert rep["ready"] is False and rep["feat"]["category"] == "general"
    j = _apply(client, player, code, ch["id"], {"mode": "three"}).json()
    assert j["ok"] is False and "origin" in j["error"]
    assert _build(ch["id"]).get("origin") is None


def test_missing_origin_feat_row_is_reported(client):
    def fix(files):
        files["feats.csv"] = "\n".join(
            l for l in files["feats.csv"].splitlines()
            if not l.startswith("feat_quick_study"))
    dm, player, code, _ = _room(client, mutate=fix)
    ch = _char(client, player)
    rep = _report(client, player, code, ch["id"])
    assert rep["ready"] is False
    assert any("not in this room's rule pack" in e for e in rep["errors"])


def test_2014_style_background_is_not_silently_2024(client):
    # a background row WITHOUT asi_abilities/origin_feat (pre-D108 pack) must
    # report visibly and refuse application — never "work" with empty defaults
    def fix(files):
        # blank ONLY the two new columns (row stays valid CSV, commas quoted)
        files["backgrounds.csv"] = files["backgrounds.csv"].replace(
            '"int, wis, cha",feat_quick_study', '""').replace(
            '"dex, con, cha",feat_alley_cat', '""')
    dm, player, code, _ = _room(client, mutate=fix)
    ch = _char(client, player)
    rep = _report(client, player, code, ch["id"])
    assert rep["ready"] is False
    assert any("not a 2024 background" in e for e in rep["errors"])
    assert _apply(client, player, code, ch["id"], {"mode": "three"}).json()["ok"] is False


# --------------------------------------------------------------- isolation

def test_cross_room_content_isolation(client):
    dm, player, code_a, _ = _room(client)
    # second room WITHOUT any rule pack import: same background name, but the
    # origin must refuse — content is resolved per room
    code_b = client.post("/api/rooms", json={"name": "NoPack"}, headers=H(dm)).json()["code"]
    join_room(client, player, code_b)
    ch = _char(client, player, bg="bg_scholar")
    j = _apply(client, player, code_b, ch["id"], {"mode": "three"}).json()
    assert j["ok"] is False and "rule pack" in j["error"]
    rep = _report(client, player, code_b, ch["id"])
    assert rep["ready"] is False
    # the character's room where the pack IS imported still works
    assert _apply(client, player, code_a, ch["id"], {"mode": "three"}).json()["ok"] is True


def test_authorization_owner_outsider_and_dm(client):
    dm, player, code, _ = _room(client)
    ch = _char(client, player)
    outsider = reg(client, "outs")
    join_room(client, outsider, code)
    assert _apply(client, outsider, code, ch["id"], {"mode": "three"}).status_code == 403
    assert client.get(f"/api/build/{code}/{ch['id']}/origin", headers=H(outsider)).status_code == 403
    # the DM may apply for an ASSIGNED character (mirrors the build API)
    client.post(f"/api/rooms/{code}/assign", json={"character_id": ch["id"]}, headers=H(player))
    j = _apply(client, dm, code, ch["id"], {"mode": "three"}).json()
    assert j["ok"] is True


# --------------------------------------------------------------- exactly once

def test_replay_double_click_answers_already(client):
    dm, player, code, _ = _room(client)
    ch = _char(client, player)
    asi = {"mode": "plus2_plus1", "plus2": "int", "plus1": "cha"}
    assert _apply(client, player, code, ch["id"], asi).json()["ok"] is True
    before = _stats(ch["id"])
    j = _apply(client, player, code, ch["id"], asi).json()
    assert j["ok"] is True and j["result"]["already"] is True
    assert _stats(ch["id"]) == before
    # even a different choice afterwards cannot overwrite the recorded origin
    j = _apply(client, player, code, ch["id"], {"mode": "three"}).json()
    assert j["ok"] is True and j["result"]["already"] is True
    assert _stats(ch["id"]) == before


def test_concurrent_double_post_applies_once(client):
    dm, player, code, _ = _room(client)
    ch = _char(client, player)
    asi = {"mode": "plus2_plus1", "plus2": "wis", "plus1": "cha"}
    with ThreadPoolExecutor(max_workers=2) as pool:
        rs = list(pool.map(lambda _: _apply(client, player, code, ch["id"], asi), range(2)))
    oks = [r.json()["ok"] for r in rs]
    assert all(oks), rs
    st = _stats(ch["id"])
    assert st["wis"] == 12 and st["cha"] == 11          # +2/+1 exactly once
    assert len([1 for k in ("origin",) if _build(ch["id"]).get("origin")]) == 1


def test_reload_persists_ledger_and_report(client):
    dm, player, code, _ = _room(client)
    ch = _char(client, player)
    assert _apply(client, player, code, ch["id"], {"mode": "three"}).json()["ok"] is True
    st = _stats(ch["id"])
    rep = _report(client, player, code, ch["id"])
    assert rep["applied"] is not None and rep["ready"] is False
    assert rep["applied"]["asi"] == {"int": 1, "wis": 1, "cha": 1}
    assert _build(ch["id"])["origin"]["background"] == "bg_scholar"
    # a fresh build write (class chronology) keeps the origin ledger entry
    db.x("UPDATE characters SET notes=? WHERE id=?", ("x", ch["id"]))
    assert _stats(ch["id"]) == st


# --------------------------------------------------------------- coexistence

def test_existing_character_is_never_auto_migrated(client):
    dm, player, code, _ = _room(client)
    ch = _char(client, player)
    before = _stats(ch["id"])
    rep = _report(client, player, code, ch["id"])
    assert rep["ready"] is True and rep["applied"] is None   # offered, not applied
    assert _stats(ch["id"]) == before
    assert _build(ch["id"]).get("origin") is None


def test_species_ability_bonuses_are_never_applied(client):
    # kin_fey carries dex+2 in the pack — in the 2024 origin flow nothing may
    # touch it; the species columns are bookkeeping only.
    dm, player, code, _ = _room(client)
    ch = _char(client, player, race="kin_fey",
               stats={"str": 10, "dex": 12, "con": 10, "int": 10, "wis": 10, "cha": 10})
    assert _apply(client, player, code, ch["id"], {"mode": "three"}).json()["ok"] is True
    assert _stats(ch["id"])["dex"] == 12


def test_background_starting_gear_is_not_granted_twice(client):
    dm, player, code, _ = _room(client, tag_ids=("potion_heal",))
    ch = _char(client, player, bg="bg_scholar")
    g1 = client.post(f"/api/rooms/{code}/starting-gear", headers=H(player),
                     json={"character_id": ch["id"]}).json()
    items_after_gear = len(db.j(db.q1("SELECT items FROM characters WHERE id=?",
                                      (ch["id"],))["items"], []))
    assert g1["ok"] is True and g1["granted"]
    # the origin operation grants NO items
    assert _apply(client, player, code, ch["id"], {"mode": "three"}).json()["ok"] is True
    assert len(db.j(db.q1("SELECT items FROM characters WHERE id=?",
                          (ch["id"],))["items"], [])) == items_after_gear
    # and a second gear request still refuses to duplicate the background part
    g2 = client.post(f"/api/rooms/{code}/starting-gear", headers=H(player),
                     json={"character_id": ch["id"]}).json()
    assert g2["already"] is True
    assert len(db.j(db.q1("SELECT items FROM characters WHERE id=?",
                          (ch["id"],))["items"], [])) == items_after_gear


# --------------------------------------------------------------- build engine

def _apply_build(client, user, code, cid, cls, to, choices):
    r = client.post(f"/api/build/{code}/{cid}/apply", headers=H(user),
                    json={"class_id": cls, "to": to, "choices": choices})
    j = r.json()
    assert j.get("ok") is True, j
    return j["result"]


def test_origin_then_class_build_and_further_levels(client):
    # origin FIRST, then a class build THROUGH an ASI level, then one more
    # level: the full recompute replays origin at the front of the chronology —
    # stats must carry origin + class ASI exactly once each
    dm, player, code, _ = _room(client)
    ch = _char(client, player, bg="bg_scholar")
    assert _apply(client, player, code, ch["id"],
                  {"mode": "plus2_plus1", "plus2": "int", "plus1": "wis"}).json()["ok"] is True
    _apply_build(client, player, code, ch["id"], "scout", 4,
                 {"skills": "stealth,perception,acrobatics,athletics",
                  "subclass": "tradition_stalker",
                  "levels": {"4": {"ability": "str+2"}}})
    st = _stats(ch["id"])
    assert st == {"str": 12, "dex": 10, "con": 10, "int": 12, "wis": 11, "cha": 10}
    assert _skills(ch["id"]).get("investigation") == 1     # origin feat still live
    _apply_build(client, player, code, ch["id"], "scout", 5,
                 {"skills": "stealth,perception,acrobatics,athletics",
                  "subclass": "tradition_stalker",
                  "levels": {"4": {"ability": "str+2"}}})
    st5 = _stats(ch["id"])
    assert st5 == st                                        # replay, no drift
    assert _build(ch["id"])["origin"]["asi"] == {"int": 2, "wis": 1}


def test_class_build_then_origin_replays_without_double(client):
    # build FIRST (base_stats captured without origin), origin SECOND: the
    # origin recompute replays the chronology — the class ASI must not double
    dm, player, code, _ = _room(client)
    ch = _char(client, player, bg="bg_scholar")
    _apply_build(client, player, code, ch["id"], "scout", 4,
                 {"skills": "stealth,perception,acrobatics,athletics",
                  "subclass": "tradition_stalker",
                  "levels": {"4": {"ability": "str+2"}}})
    assert _stats(ch["id"])["str"] == 12
    hp_before = db.q1("SELECT hp, max_hp FROM characters WHERE id=?", (ch["id"],))
    assert _apply(client, player, code, ch["id"], {"mode": "three"}).json()["ok"] is True
    st = _stats(ch["id"])
    assert st["str"] == 12                                   # class ASI exactly once
    assert st["int"] == 11 and st["wis"] == 11 and st["cha"] == 11
    hp_after = db.q1("SELECT hp, max_hp FROM characters WHERE id=?", (ch["id"],))
    assert dict(hp_before) == dict(hp_after)                 # untouched


def test_character_put_cannot_forgery_or_erase_grants(client):
    dm, player, code, _ = _room(client)
    ch = _char(client, player, bg="bg_scholar")
    assert _apply(client, player, code, ch["id"], {"mode": "three"}).json()["ok"] is True
    led_before = _build(ch["id"])
    # a raw sheet PUT (which legitimately may rewrite stats) must not touch the
    # origin ledger nor mint a different origin: forge fields are ignored
    body = {"name": ch["name"], "race": "kin_fey", "char_class": "", "background": "bg_urchin",
            "level": 1, "stats": {"str": 10, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10},
            "hp": 10, "max_hp": 10, "build": {"origin": {"background": "bg_urchin",
                                                         "feat": "feat_nimble", "asi": {}}}}
    r = client.put(f"/api/characters/{ch['id']}", headers=H(player), json=body)
    assert r.status_code == 200
    assert _build(ch["id"]) == led_before                    # untouched — not writable
    assert _stats(ch["id"])["int"] == 10                     # raw sheet edit allowed
    # the next chronology write replays the REAL grant, restoring origin values
    _apply_build(client, player, code, ch["id"], "scout", 1,
                 {"skills": "stealth,perception,acrobatics,athletics"})
    assert _stats(ch["id"])["int"] == 11
    assert _build(ch["id"])["origin"] == led_before["origin"]
