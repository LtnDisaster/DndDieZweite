"""Sprint 25 Phase B (D96): chronological character build.

Pins that building a class 1..20 reads the DM-imported CONTENT (class/subclass/
feat rows), advances the character through the ONE mutation the engines already
own (progression.set_class_levels + gear cleaners), honours the strict chronology
(subclass only at its unlock level, ASI/feat at their levels), refuses to apply
without the required choices (writing nothing), guards against re-building the
same or a lower level, records the ledger in characters.build so it survives a
restart, and enforces owner-or-room-DM authorisation at the REST edge.
"""
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from app import charbuild as CB, content as C, db, gear, main, progression
from tests.test_movement_fog import H, base_room, join_room, make_char, reg

PACK = Path(__file__).resolve().parents[1] / "app" / "content_pack"


@pytest.fixture()
def client():
    return TestClient(main.app)


def _room(client):
    dm, player, code, ch = base_room(client)
    rid = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
    files = {p.name: p.read_text(encoding="utf-8") for p in PACK.glob("*.csv")}
    C.import_package(files, room_id=rid, mode="apply", apply=True)
    return dm, player, code, ch, rid


def _fresh(client, player):
    return make_char(client, player)


# ---------- plan (pure chronology) ----------

def test_plan_scout_level20_chronology(client):
    _dm, _p, _code, _ch, rid = _room(client)
    p = CB.plan("scout", 20, rid)
    assert p["ok"] and len(p["levels"]) == 20
    assert p["levels"][0]["level"] == 1 and p["levels"][-1]["level"] == 20
    assert "expertise" in p["levels"][0]["features"] and "sly strike" in p["levels"][0]["features"]
    assert p["levels"][1]["features"] == ["nimble dodge"]          # level 2
    assert p["levels"][19]["features"] == ["fortune of the scout"]  # level 20
    assert p["needs"]["skills"] and p["needs"]["skill_count"] == 4
    assert len(p["needs"]["skill_options"]) == 11
    assert p["needs"]["subclass"] and "tradition_stalker" in p["subclass_options"]
    assert set(p["needs"]["levels"]) == {"1", "4", "6", "8", "12", "16", "19"}


def test_plan_rejects_no_level1_and_out_of_range(client):
    _dm, _p, _code, _ch, rid = _room(client)
    assert CB.plan("nope", 3, rid)["ok"] is False
    assert CB.plan("scout", 21, rid)["ok"] is False


# ---------- apply: the supported subset, chronologically ----------

def test_apply_level1_sets_hp_saves_skills(client):
    _dm, player, _code, _ch, rid = _room(client)
    cid = _fresh(client, player)["id"]
    ok, res = CB.apply(cid, "scout", 1, {"skills": ["stealth", "perception", "acrobatics", "athletics"],
                                           "levels": {"1": {"expertise": "stealth"}}}, rid)
    assert ok and res["level"] == 1 and res["max_hp"] == 14
    row = db.q1("SELECT * FROM characters WHERE id=?", (cid,))
    assert progression.load(row) == [{"class_id": "scout", "level": 1}]
    assert row["level"] == 1 and row["hit_die"] == 8
    assert set(db.j(row["saves"], {})) >= {"dex", "int"}
    skills = gear.clean_skills(db.j(row["skills"], {}))
    assert {"stealth", "perception", "acrobatics", "athletics"} <= {k for k, v in skills.items() if v}
    assert skills["stealth"] == 2


def test_apply_missing_choices_writes_nothing(client):
    _dm, player, _code, _ch, rid = _room(client)
    cid = _fresh(client, player)["id"]
    ok, res = CB.apply(cid, "scout", 8, {}, rid)               # no skills/subclass/ASI
    assert ok is False and res.get("needs_choice")
    kinds = {n["kind"] for n in res["needs_choice"]}
    assert {"skills", "subclass", "level_choice"} <= kinds
    row = db.q1("SELECT * FROM characters WHERE id=?", (cid,))
    assert progression.load(row) == []                         # untouched
    assert CB.ledger(row) == {}


def test_apply_level8_applies_chronological_choices(client):
    _dm, player, _code, _ch, rid = _room(client)
    cid = _fresh(client, player)["id"]
    choices = {"skills": ["stealth", "perception", "acrobatics", "athletics"],
               "subclass": "tradition_stalker",
               "levels": {"1": {"expertise": "stealth"}, "4": {"ability": {"dex": 2}},
                          "6": {"expertise": "perception"}, "8": {"feat": "feat_keen"}}}
    ok, res = CB.apply(cid, "scout", 8, choices, rid)
    assert ok and res["level"] == 8 and res["max_hp"] == 49   # 14 + 5*7
    assert res["subclass"] == "tradition_stalker" and res["feats"][0]["id"] == "feat_keen"
    row = db.q1("SELECT * FROM characters WHERE id=?", (cid,))
    stats = gear.as_sheet(row)["stats"]
    assert stats["dex"] == 16 and stats["wis"] == 13          # 14+2 ASI, 12+1 from Keen Mind
    skills = gear.clean_skills(db.j(row["skills"], {}))
    assert {"stealth", "perception", "acrobatics", "athletics", "investigation"} <= {k for k, v in skills.items() if v}
    led = CB.ledger(row)
    assert led["applied_through"] == 8 and led["subclass"] == "tradition_stalker"
    assert [e["level"] for e in led["history"]] == list(range(1, 9))


def test_apply_level20_and_repeat_guard(client):
    _dm, player, _code, _ch, rid = _room(client)
    cid = _fresh(client, player)["id"]
    choices = {"skills": ["stealth", "perception", "acrobatics", "athletics"],
               "subclass": "tradition_stalker",
               "levels": {"1": {"expertise": "stealth"}, "4": {"ability": {"dex": 2}},
                          "6": {"expertise": "perception"}, "8": {"ability": {"dex": 2}},
                          "12": {"ability": {"dex": 2}}, "16": {"ability": {"dex": 2}},
                          "19": {"ability": {"dex": 2}}}}
    ok, res = CB.apply(cid, "scout", 20, choices, rid)
    assert ok and res["level"] == 20 and res["max_hp"] == 109   # 14 + 5*19
    # repeat guard: same target again, and a lower target, are both refused
    assert CB.apply(cid, "scout", 20, choices, rid)[0] is False
    assert CB.apply(cid, "scout", 3, choices, rid)[0] is False


def test_forward_only_multi_step_merges_decisions(client):
    _dm, player, _code, _ch, rid = _room(client)
    cid = _fresh(client, player)["id"]
    step1 = {"skills": ["stealth", "perception", "acrobatics", "athletics"],
             "subclass": "tradition_stalker",
             "levels": {"1": {"expertise": "stealth"}, "4": {"ability": {"dex": 2}}}}
    assert CB.apply(cid, "scout", 5, step1, rid)[0]
    row = db.q1("SELECT * FROM characters WHERE id=?", (cid,))
    assert gear.as_sheet(row)["stats"]["dex"] == 16
    # advancing to 8 supplies the NEW level-6/8 choices; level-1/4 are remembered
    ok, res = CB.apply(cid, "scout", 8, {"levels": {"6": {"expertise": "perception"},
                                                       "8": {"feat": "feat_keen"}}}, rid)
    assert ok and res["level"] == 8
    stats = gear.as_sheet(db.q1("SELECT * FROM characters WHERE id=?", (cid,)))["stats"]
    assert stats["dex"] == 16 and stats["wis"] == 13             # level-4 + level-8 both retained


def test_feat_prerequisite_parser_supports_modelled_and_refuses_other_forms():
    assert CB._parse_feat_requires("Dex 13 or higher")[0] == [
        {"kind": "ability", "ability": "dex", "score": 13}]
    assert CB._parse_feat_requires("Skill Proficiency — Stealth")[0] == [
        {"kind": "skill", "skill": "stealth"}]
    assert CB._parse_feat_requires("feat Alert")[0] == [
        {"kind": "feat", "feat": "alert"}]
    assert CB._parse_feat_requires("")[0] == []
    assert CB._parse_feat_requires("Perception 5 ranks")[1].startswith("unsupported prerequisite")


def test_plan_for_character_marks_feat_prerequisites(client):
    _dm, player, _code, _ch, rid = _room(client)
    cid = _fresh(client, player)["id"]
    ok, _res = CB.apply(cid, "scout", 1, {
        "skills": ["stealth", "perception", "acrobatics", "athletics"],
        "levels": {"1": {"expertise": "stealth"}}}, rid)
    assert ok
    p = CB.plan_for_character(cid, "scout", 8, rid)
    option = next(o for o in p["needs"]["levels"]["8"]["feat_options"] if o["id"] == "feat_keen")
    assert option["available"] and option["missing"] == []


def test_apply_refuses_feat_prerequisite(client):
    _dm, player, _code, _ch, rid = _room(client)
    cid = _fresh(client, player)["id"]
    ok, res = CB.apply(cid, "scout", 8, {
        "skills": ["stealth", "acrobatics", "athletics", "sleight_of_hand"],
        "subclass": "tradition_stalker",
        "levels": {"1": {"expertise": "stealth"}, "4": {"ability": {"dex": 2}},
                   "6": {"expertise": "acrobatics"}, "8": {"feat": "feat_keen"}}}, rid)
    assert ok is False
    assert "prerequisites not met" in res["error"]
    assert "perception" in res["error"]


def test_ledger_survives_reload(client):
    _dm, player, _code, _ch, rid = _room(client)
    cid = _fresh(client, player)["id"]
    CB.apply(cid, "scout", 1, {"skills": ["stealth", "perception", "acrobatics", "athletics"],
                               "levels": {"1": {"expertise": "stealth"}}}, rid)
    led = CB.ledger(db.q1("SELECT * FROM characters WHERE id=?", (cid,)))   # fresh load = "restart"
    assert led["class_id"] == "scout" and led["applied_through"] == 1


def test_different_class_refused_once_started(client):
    _dm, player, _code, _ch, rid = _room(client)
    cid = _fresh(client, player)["id"]
    CB.apply(cid, "scout", 1, {"skills": ["stealth", "perception", "acrobatics", "athletics"],
                               "levels": {"1": {"expertise": "stealth"}}}, rid)
    ok, res = CB.apply(cid, "adept", 2, {}, rid)
    assert ok is False and "already building" in res["error"]


# ---------- REST: owner-or-room-DM ----------

def _post_apply(client, user, code, cid, body):
    return client.post(f"/api/build/{code}/{cid}/apply", headers=H(user), json=body)


def test_rest_owner_can_plan_and_apply(client):
    _dm, player, code, ch, rid = _room(client)
    r = client.get(f"/api/build/{code}/{ch['id']}/plan", params={"class_id": "scout", "to": "1"},
                   headers=H(player))
    assert r.status_code == 200 and r.json()["ok"] and len(r.json()["levels"]) == 1
    r = _post_apply(client, player, code, ch["id"],
                    {"class_id": "scout", "to": 1, "choices": {"skills": ["stealth", "perception", "acrobatics", "athletics"],
                                             "levels": {"1": {"expertise": "stealth"}}}})
    assert r.status_code == 200 and r.json()["ok"] and r.json()["result"]["level"] == 1


def test_rest_room_dm_may_build_a_member_character(client):
    dm, _player, code, ch, rid = _room(client)
    r = _post_apply(client, dm, code, ch["id"],
                    {"class_id": "scout", "to": 1, "choices": {"skills": ["stealth", "perception", "acrobatics", "athletics"],
                                             "levels": {"1": {"expertise": "stealth"}}}})
    assert r.status_code == 200 and r.json()["ok"]


def test_rest_member_not_owner_and_outsider_refused(client):
    dm, player, code, ch, rid = _room(client)
    outsider = reg(client, "outs")
    member2 = reg(client, "mem")
    join_room(client, member2, code)
    body = {"class_id": "scout", "to": 1, "choices": {"skills": ["stealth", "perception", "acrobatics", "athletics"],
                                             "levels": {"1": {"expertise": "stealth"}}}}
    # a room member who is not the owner and not the DM is refused
    assert _post_apply(client, member2, code, ch["id"], body).status_code == 403
    # an outsider is refused (not even a member)
    assert _post_apply(client, outsider, code, ch["id"], body).status_code == 403
    # unauthenticated
    client.cookies.clear()
    assert client.post(f"/api/build/{code}/{ch['id']}/apply", json=body).status_code == 401
