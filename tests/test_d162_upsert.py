"""D162-8 — mode=upsert: the follow-up-delivery import (audit P2-3).

apply treats a differing same-id row as a conflict and skips it; replace
silently overwrites without saying WHAT changed. Neither is the workflow for
a delivery of corrections ("here are three fixed item rows"). upsert writes
the new version AND names every id it updated — report path
applied.<kind>.updated. apply/replace semantics themselves are UNTOUCHED."""
import pytest
from starlette.testclient import TestClient

from app import content, db, main
from tests.test_movement_fog import H, base_room

CSV_V1 = "id,name,weight\nring1,Gold Ring,0\nlantern,Travel Lantern,2\n"
CSV_V2 = "id,name,weight\nring1,Platinum Ring,0\n"


@pytest.fixture()
def client():
    return TestClient(main.app)


def post(client, dm, code, body, mode):
    return client.post(f"/api/content/{code}/import", content=body.encode(),
                       headers=H(dm), params={"name": "items.csv", "mode": mode})


def row_name(client, dm, code, item_id):
    st = {"r": None}
    rid = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
    row = db.q1("SELECT data FROM content WHERE kind='item' AND room_id=? AND id=?",
                (rid, item_id))
    return (db.j(row["data"], {}) or {}).get("name") if row else None


def test_upsert_updates_and_names_changed_rows(client):
    dm, player, code, _ = base_room(client)
    r1 = post(client, dm, code, CSV_V1, "apply").json()
    assert r1["applied"]["item"]["inserted"] == 2
    # the corrected delivery, plain apply → conflict, nothing changes
    r2 = post(client, dm, code, CSV_V2, "apply").json()
    assert r2["applied"]["item"]["conflicts"] == ["ring1"]
    assert row_name(client, dm, code, "ring1") == "Gold Ring"
    # upsert → updated, and the report says WHICH
    r3 = post(client, dm, code, CSV_V2, "upsert").json()
    ap = r3["applied"]["item"]
    assert ap["updated"] == ["ring1"] and ap["conflicts"] == []
    assert ap["replaced"] == 1 and ap["inserted"] == 0
    assert row_name(client, dm, code, "ring1") == "Platinum Ring"
    # the OTHER row survives untouched (upsert never deletes)
    assert row_name(client, dm, code, "lantern") == "Travel Lantern"


def test_upsert_projection_refreshes_item_defs(client):
    dm, player, code, _ = base_room(client)
    post(client, dm, code, CSV_V1, "apply")
    post(client, dm, code, CSV_V2, "upsert")
    rid = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
    rows = content.load("item", rid)
    defs = {r["id"]: r for r in (rows.values() if isinstance(rows, dict) else rows)}
    assert defs["ring1"]["name"] == "Platinum Ring"


def test_apply_and_replace_semantics_untouched(client):
    dm, player, code, _ = base_room(client)
    post(client, dm, code, CSV_V1, "apply")
    r = post(client, dm, code, CSV_V2, "replace").json()
    assert r["applied"]["item"]["replaced"] == 1
    assert "updated" not in r["applied"]["item"]       # replace keeps its shape
    assert row_name(client, dm, code, "ring1") == "Platinum Ring"


def test_mode_validation_mentions_upsert(client):
    dm, player, code, _ = base_room(client)
    r = post(client, dm, code, CSV_V1, "bogus")
    assert r.status_code == 400 and "upsert" in r.text
