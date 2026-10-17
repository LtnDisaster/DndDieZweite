"""D145: species ability bonuses become mechanical — server-authorised and
EXACTLY-ONCE. The numbers come from the ROOM'S species row (ability_bonuses
column), never from a client; the grant is a recorded ledger entry that the
full recompute replays at the front of the chronology (2024: species comes
before origin, class and ASI). Existing sheets are never auto-migrated, and
hp/AC/slots/resources are never touched.
"""
import pytest
from starlette.testclient import TestClient

from app import db, main
from tests.test_d108_origin import _char, _room
from tests.test_movement_fog import H


@pytest.fixture()
def client():
    return TestClient(main.app)


def _get(client, user, code, cid):
    return client.get(f"/api/build/{code}/{cid}/species", headers=H(user)).json()


def _post(client, user, code, cid):
    return client.post(f"/api/build/{code}/{cid}/species", headers=H(user),
                       json={}).json()


def _stats(cid):
    return db.j(db.q1("SELECT stats FROM characters WHERE id=?", (cid,))["stats"], {})


def test_report_previews_the_row_bonus(client):
    dm, player, code, _ = _room(client)
    cid = _char(client, player, bg="", race="kin_fey")["id"]
    out = _get(client, player, code, cid)
    assert out["ready"] is True and out["errors"] == []
    assert out["species"] == "kin_fey"
    assert out["bonuses"] == [{"ability": "dex", "delta": 2}]
    assert out["current"]["dex"] == 10 and out["result"]["dex"] == 12


def test_grant_once_and_idempotent(client):
    dm, player, code, _ = _room(client)
    cid = _char(client, player, bg="", race="kin_fey")["id"]
    r = _post(client, player, code, cid)
    assert r["ok"] is True and r["result"]["stats"]["dex"] == 12
    r2 = _post(client, player, code, cid)
    assert r2["ok"] is True and r2["result"].get("already") is True
    assert _stats(cid)["dex"] == 12           # exactly once, even on replay
    assert _get(client, player, code, cid)["applied"] is not None


def test_bump_is_clamped_to_thirty(client):
    dm, player, code, _ = _room(client)
    cid = _char(client, player, bg="", race="kin_fey",
                stats={"str": 10, "dex": 29, "con": 10,
                       "int": 10, "wis": 10, "cha": 10})["id"]
    assert _post(client, player, code, cid)["result"]["stats"]["dex"] == 30


def test_unknown_or_bonusless_species_refuses(client):
    dm, player, code, _ = _room(client)
    cid = _char(client, player, bg="", race="no_such_species")["id"]
    r = _post(client, player, code, cid)
    assert r["ok"] is False and "rule pack" in r["error"]
    assert _stats(cid)["dex"] == 10           # refusal never mutates

    def blank(files):
        import csv, io
        rows = list(csv.DictReader(io.StringIO(files["species.csv"])))
        for r in rows:
            r["ability_bonuses"] = ""
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()),
                           lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
        files["species.csv"] = buf.getvalue()

    dm2, player2, code2, _ = _room(client, mutate=blank)
    cid2 = _char(client, player2, bg="", race="kin_fey")["id"]
    r = _post(client, player2, code2, cid2)
    assert r["ok"] is False and "no ability bonuses" in r["error"]


def test_species_and_origin_compose_in_any_order(client):
    # origin first, species second: the origin apply replays the recorded
    # species bonus in its own unbuilt branch (no silent drop)...
    dm, player, code, _ = _room(client)
    cid = _char(client, player, bg="bg_scholar", race="kin_fey")["id"]
    asi = {"mode": "three"}                # scholar's three: int/wis/cha
    r = client.post(f"/api/build/{code}/{cid}/origin", headers=H(player),
                    json={"asi": asi}).json()
    assert r["ok"] is True
    assert _post(client, player, code, cid)["result"]["stats"]["dex"] == 12
    # ... and species first, origin second: origin's unbuilt branch must
    # replay the species bonus before its own deltas.
    cid2 = _char(client, player, bg="bg_scholar", race="kin_fey")["id"]
    assert _post(client, player, code, cid2)["result"]["stats"]["dex"] == 12
    r2 = client.post(f"/api/build/{code}/{cid2}/origin", headers=H(player),
                     json={"asi": asi}).json()
    assert r2["ok"] is True
    s2 = _stats(cid2)
    assert s2["dex"] == 12 and s2["int"] == s2["wis"] == s2["cha"] == 11
    assert r2["result"]["stats"] == s2
