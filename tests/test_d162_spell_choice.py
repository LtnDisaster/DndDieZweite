"""D162-10 — prepared casters PICK their spells; no silent alphabetical fill.

D161 P3: the wizard/prepared model auto-granted the entire class pool and the
sheet showed it sorted by id — the player never decided anything. Now the
BUILD asks (needs_choice kind "spells" with cantrips/spells counts from the
class row, capped by the pack's pool so a pick is always satisfiable), refuses
wrong counts, writes nothing while a decision is missing, and legacy sheets
built under the old semantics keep their whole-pool list (the missing pick of
an already-applied level is recorded as the pool that built it — a level-up
may never silently shrink a sheet)."""
import pytest
from starlette.testclient import TestClient

from app import charbuild as CB, content as C, db, gear, main
from tests.test_spells import abilities_of, room_pack
from tests.test_movement_fog import make_char


@pytest.fixture()
def client():
    return TestClient(main.app)


def disp_of(cid):
    return {s["id"] for s in gear.clean_spells(db.j(
        db.q1("SELECT spells FROM characters WHERE id=?", (cid,))["spells"], []))}


def pool_parts(rid):
    rows = C.spell_pool("adept", rid)
    pc = sorted(r["id"] for r in rows if str(r.get("level")) == "0")
    ps = sorted(r["id"] for r in rows if str(r.get("level")) != "0")
    return pc, ps


def test_plan_asks_prepared_pick_with_pool_capped_counts(client):
    _dm, player, _code, _ch, rid = room_pack(client)
    p = CB.plan("adept", 1, rid)
    assert p["ok"] and p["needs"]["spell"]["model"] == "prepared"
    ent = p["needs"]["levels"]["1"]
    pc, ps = pool_parts(rid)
    # class row says 3/6 but the pack's class list offers 2/4 — the demand is
    # capped by reality, never above the pool the player can pick from:
    assert ent["cantrips"] == len(pc) == 2
    assert ent["spells"] == len(ps) == 4
    assert ent["pool_cantrips"] == pc and ent["pool_spells"] == ps


def test_missing_pick_writes_nothing(client):
    _dm, player, _code, _ch, rid = room_pack(client)
    cid = make_char(client, player)["id"]
    ok, res = CB.apply(cid, "adept", 1, {"skills": ["arcana", "history"]}, rid)
    assert ok is False
    assert any(n["kind"] == "spells" and n["level"] == 1 for n in res["needs_choice"])
    assert abilities_of(cid) == set() and disp_of(cid) == set()
    assert CB.ledger(db.q1("SELECT * FROM characters WHERE id=?", (cid,))) == {}


def test_exact_picks_are_what_the_sheet_holds(client):
    _dm, player, _code, _ch, rid = room_pack(client)
    cid = make_char(client, player)["id"]
    pc, ps = pool_parts(rid)
    # pick ONLY the cantrips + ONE spell (under-picking spells answers needs)
    ok, res = CB.apply(cid, "adept", 1, {
        "skills": ["arcana", "history"],
        "levels": {"1": {"cantrips": pc, "spells": [ps[0]]}}}, rid)
    assert ok is False                                   # 4 spells demanded
    ok, res = CB.apply(cid, "adept", 1, {
        "skills": ["arcana", "history"],
        "levels": {"1": {"cantrips": pc, "spells": ps}}}, rid)
    assert ok is True, res
    assert abilities_of(cid) == set(pc) | set(ps)
    assert disp_of(cid) == set(pc) | set(ps)             # exactly the picks


def test_over_pick_is_refused_without_writing(client):
    _dm, player, _code, _ch, rid = room_pack(client)
    cid = make_char(client, player)["id"]
    pc, ps = pool_parts(rid)
    ok, res = CB.apply(cid, "adept", 1, {
        "skills": ["arcana", "history"],
        "levels": {"1": {"cantrips": pc, "spells": ps + ["phantom_extra"]}}}, rid)
    assert ok is False and "spell(s) granted" in res.get("error", "")
    assert abilities_of(cid) == set() and CB.ledger(
        db.q1("SELECT * FROM characters WHERE id=?", (cid,))) == {}


def test_legacy_prepared_sheet_never_shrinks_on_level_up(client):
    """A sheet built under the OLD whole-pool semantics keeps every spell when
    the owner levels up: the missing historical pick is recorded as the pool."""
    _dm, player, _code, _ch, rid = room_pack(client)
    cid = make_char(client, player)["id"]
    pc, ps = pool_parts(rid)
    ok, _ = CB.apply(cid, "adept", 1, {
        "skills": ["arcana", "history"],
        "levels": {"1": {"cantrips": pc, "spells": ps}}}, rid)
    assert ok
    # simulate the pre-D162 ledger: applied_through=1 but NO spell decisions,
    # the old columns already hold the whole pool:
    led = CB.ledger(db.q1("SELECT * FROM characters WHERE id=?", (cid,)))
    decisions = led.get("decisions") or {}
    (decisions.get("levels") or {}).pop("1", None)
    db.x("UPDATE characters SET build=? WHERE id=?", (db.json_dumps(led), cid))
    ok, res = CB.apply(cid, "adept", 2, {"subclass": "school_ember"}, rid)
    assert ok is True, res                        # no needs_choice for history
    assert set(pc) | set(ps) <= abilities_of(cid)     # nothing shrank
    led2 = CB.ledger(db.q1("SELECT * FROM characters WHERE id=?", (cid,)))
    assert led2["decisions"]["levels"]["1"]["cantrips"] == pc   # pool recorded


def test_known_model_unchanged_deltas_still_drive_picks(client):
    _dm, player, _code, _ch, rid = room_pack(client)
    p = CB.plan("seer", 3, rid)
    ent = p["needs"]["levels"]["1"]
    assert ent["cantrips"] == 3 and ent["spells"] == 3
    assert "3" in p["needs"]["levels"]                    # +1 spell at level 3
    assert p["needs"]["spell"]["model"] == "known"


# ---------- UI copy honesty ----------

def test_wizard_no_longer_claims_prepared_needs_no_choice():
    js = open("app/static/js/80_prep.js", encoding="utf-8").read()
    assert "no spell choice needed" not in js
    assert "you choose the cantrips and spells" in js
