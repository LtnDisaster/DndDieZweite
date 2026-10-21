"""D163-5 — the 2024 ASI inside the level-up loop, and Epic Boons at 19+.

The level rows already asked for "ability boost or feat"; D163 gives the ASI
branch the SRD 5.2.1 shape: +2 and +1 to two DIFFERENT scores, or +1 to three
DIFFERENT scores — never above 20. The SAME two decision shapes the origin ASI
speaks (plus2_plus1 | three); pre-D163 decisions (plain "str+2" strings, bare
{...} deltas) stay accepted but are now capped at 20 too. Feat choices at
levels below 19 no longer list Epic Boons; the feat's own CSV category is the
only thing that decides.
"""
import pytest
from starlette.testclient import TestClient

from app import charbuild, db, main
from tests.test_movement_fog import H, base_room


@pytest.fixture()
def client():
    return TestClient(main.app)


def asi_class(client, code, cid, player, boost_at=(4,)):
    from app import content as CT
    rid = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
    CT.store("class", rid, {"id": "tasi", "level": "1", "name": "ASI",
                            "hit_die": "8", "hp_base": "10",
                            "hp_per_level": "5"})
    for lvl in boost_at:
        CT.store("class", rid, {"id": "tasi", "level": str(lvl), "name": "ASI",
                                "hit_die": "8", "hp_base": "10",
                                "hp_per_level": "5",
                                "ability_boost_or_feat": "1"})
    return rid


def stats_of(cid):
    return db.j(db.q1("SELECT stats FROM characters WHERE id=?", (cid,))["stats"], {})


def pick(client, code, cid, player, to, ability):
    return client.post(f"/api/build/{code}/{cid}/apply",
                       json={"class_id": "tasi", "to": to,
                             "choices": {"levels": {str(to): {"ability": ability}}}},
                       headers=H(player))


def test_asi_plus2_plus1(client):
    dm, player, code, ch = base_room(client)
    asi_class(client, code, ch["id"], player)
    before = stats_of(ch["id"])
    r = pick(client, code, ch["id"], player, 4,
             {"asi": {"mode": "plus2_plus1", "plus2": "str", "plus1": "dex"}})
    assert r.status_code == 200 and r.json()["ok"], r.text
    after = stats_of(ch["id"])
    assert after["str"] == before["str"] + 2 and after["dex"] == before["dex"] + 1


def test_asi_three(client):
    dm, player, code, ch = base_room(client)
    asi_class(client, code, ch["id"], player)
    before = stats_of(ch["id"])
    r = pick(client, code, ch["id"], player, 4,
             {"asi": {"mode": "three", "abilities": ["str", "con", "wis"]}})
    assert r.status_code == 200 and r.json()["ok"], r.text
    after = stats_of(ch["id"])
    assert all(after[k] == before[k] + 1 for k in ("str", "con", "wis"))
    assert after["dex"] == before["dex"]


def test_asi_never_exceeds_20(client):
    dm, player, code, ch = base_room(client)
    asi_class(client, code, ch["id"], player)
    st = stats_of(ch["id"])
    st["str"] = 19
    db.x("UPDATE characters SET stats=? WHERE id=?", (db.json_dumps(st), ch["id"]))
    r = pick(client, code, ch["id"], player, 4,
             {"asi": {"mode": "plus2_plus1", "plus2": "str", "plus1": "dex"}})
    assert r.json()["ok"], r.text
    assert stats_of(ch["id"])["str"] == 20            # 19+2 stops at 20


def test_asi_rejects_bad_shapes(client):
    dm, player, code, ch = base_room(client)
    asi_class(client, code, ch["id"], player)
    bad = [
        {"asi": {"mode": "plus2_plus1", "plus2": "str", "plus1": "str"}},
        {"asi": {"mode": "plus2_plus1", "plus2": "str", "plus1": ""}},
        {"asi": {"mode": "three", "abilities": ["str", "con"]}},
        {"asi": {"mode": "three", "abilities": ["str", "con", "con"]}},
        {"asi": {"mode": "wishes"}},
    ]
    snapshot = stats_of(ch["id"])
    for b in bad:
        r = pick(client, code, ch["id"], player, 4, b)
        assert not r.json().get("ok"), f"accepted {b}: {r.text}"
    assert stats_of(ch["id"]) == snapshot             # untouched by rejections


def test_legacy_asi_shapes_accepted_but_capped(client):
    dm, player, code, ch = base_room(client)
    asi_class(client, code, ch["id"], player)
    st = stats_of(ch["id"])
    st["str"] = 19
    db.x("UPDATE characters SET stats=? WHERE id=?", (db.json_dumps(st), ch["id"]))
    r = pick(client, code, ch["id"], player, 4, {"str": 4, "dex": 1})
    assert r.json()["ok"], r.text
    after = stats_of(ch["id"])
    assert after["str"] == 20 and after["dex"] == st["dex"] + 1


def test_epic_boons_hidden_below_19(client):
    dm, player, code, _ = base_room(client)
    rid = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
    from app import content as CT
    CT.store("feat", rid, {"id": "boon_living", "name": "Boon of Vitality",
                           "category": "epic_boon"})
    CT.store("feat", rid, {"id": "feat_quick_study", "name": "Quick Study"})
    low = {f["id"] for f in charbuild._feat_choice_options(rid, {}, {}, [], level=4)}
    assert "boon_living" not in low and "feat_quick_study" in low
    high = {f["id"] for f in charbuild._feat_choice_options(rid, {}, {}, [], level=19)}
    assert "boon_living" in high
