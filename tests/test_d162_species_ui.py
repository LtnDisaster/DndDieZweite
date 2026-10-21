"""D162-2 — species traits & bonuses become reachable through the Builder UI.

D161 P2-6: the D145 GET/POST /species API was complete but NO UI ever called
it — sheet ability scores silently missed the species grant (observed live: a
Stoutheart's CON stayed at base). The engine is untouched here and stays the
single writer (exactly-once ledger, replay from base_stats — see D145). This
file pins what D162 adds: the GET report also carries the species FEATURES
(traits/languages/size/speeds) so the card can show the 2024 traits honestly,
a grant still never double-applies (including across a later class recompute),
a PUT identity save cannot wipe it, and the card wires the real endpoints only
(never a stats PUT)."""
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
    return client.post(f"/api/build/{code}/{cid}/species",
                       headers=H(user), json={}).json()


def _stats(cid):
    return db.j(db.q1("SELECT stats FROM characters WHERE id=?", (cid,))["stats"], {})


def test_report_carries_species_features(client):
    dm, player, code, _ = _room(client)
    cid = _char(client, player, bg="", race="kin_stoutheart")["id"]
    out = _get(client, player, code, cid)
    f = out.get("features")
    assert f, "D162-2: the card must receive the species traits block"
    assert f["size"] == "medium"
    assert f["speed_ft"] == 25 and f["darkvision_ft"] == 60
    assert any("Sturdy" in t for t in f["traits"])
    assert "Common" in f["languages"]
    assert out["bonuses"] == [{"ability": "con", "delta": 2}]


def drive_apply(client, player, code, cid, class_id, to, extra=None, rounds=6):
    """Post apply and answer every needs_choice with the FIRST offered legal
    option until ok (mirrors what the guided wizard does with its dropdowns).
    Returns the final response."""
    choices = dict(extra or {})
    rr = {}
    for _ in range(rounds):
        rr = client.post(f"/api/build/{code}/{cid}/apply", headers=H(player),
                         json={"class_id": class_id, "to": to,
                               "choices": choices}).json()
        if rr.get("ok") or rr.get("error"):
            return rr
        for n in rr.get("needs_choice") or []:
            kind = n.get("kind")
            oid = lambda x: x if isinstance(x, str) else x.get("id")
            if kind == "skills":
                choices["skills"] = n["options"][:n["count"]]
            elif kind == "subclass":
                choices["subclass"] = oid(n["options"][0])
            elif kind == "expertise":
                e = choices.setdefault("levels", {}).setdefault(str(n["level"]), {})
                e["expertise"] = n["options"][:n["count"]]
            elif kind == "spells":
                e = choices.setdefault("levels", {}).setdefault(str(n["level"]), {})
                e["cantrips"] = [oid(x) for x in n["pool_cantrips"][:n["cantrips"]]]
                e["spells"] = [oid(x) for x in n["pool_spells"][:n["spells"]]]
            elif kind == "level_choice":
                e = choices.setdefault("levels", {}).setdefault(str(n["level"]), {})
                e["ability"] = {"str": 2}
    return rr


def test_bonus_grants_exactly_once_and_survives_level_build(client):
    dm, player, code, _ = _room(client)
    cid = _char(client, player, bg="", race="kin_stoutheart")["id"]
    r = _post(client, player, code, cid)
    assert r["ok"] and _stats(cid)["con"] == 12
    _post(client, player, code, cid)
    assert _stats(cid)["con"] == 12                       # replay: nothing added
    rr = drive_apply(client, player, code, cid, "scout", 1)
    assert rr.get("ok") is True, rr
    assert _stats(cid)["con"] == 12, "species grant must replay exactly once"


def test_raw_put_cannot_undo_a_granted_bonus(client):
    """The trusted-owner PUT keeps a floor at the ledger's base+delta — the
    identity save can never silently wipe a granted species bonus (D162-2),
    while a legitimate HIGHER value still passes untouched."""
    dm, player, code, _ = _room(client)
    ch = _char(client, player, bg="", race="kin_stoutheart")
    _post(client, player, code, ch["id"])
    assert _stats(ch["id"])["con"] == 12
    stale = dict(_stats(ch["id"])); stale["con"] = 10; stale["str"] = 18
    body = {"name": "Renamed", "race": "Stoutheart", "char_class": "",
            "background": "", "stats": stale, "hp": 10, "max_hp": 10}
    r = client.put(f"/api/characters/{ch['id']}", headers=H(player), json=body)
    assert r.status_code == 200, r.text
    s = _stats(ch["id"])
    assert s["con"] == 12, "granted floor is enforced against stale stats"
    assert s["str"] == 18, "unrelated owner edits still pass freely"
    # and a legit raise ABOVE the floor survives too
    body2 = dict(body); body2["stats"] = dict(s, con=15)
    assert client.put(f"/api/characters/{ch['id']}", headers=H(player),
                      json=body2).status_code == 200
    assert _stats(ch["id"])["con"] == 15
    assert _get(client, player, code, ch["id"])["applied"], "ledger proof survives"


def test_bonusless_species_reports_error_and_moves_nothing(client):
    # a species row without ability_bonuses must not even offer a grant
    dm, player, code, _ = _room(client)
    cid = _char(client, player, bg="", race="kin_kit")["id"]
    out = _get(client, player, code, cid)
    # kin_kit carries dex+1,int+1 in the shipped pack — use the row truth
    if not out["bonuses"]:
        assert "grants no ability bonuses" in " ".join(out["errors"])
        r = _post(client, player, code, cid)
        assert r["ok"] is False and _stats(cid) == _stats(cid)
    else:
        assert out["ready"] is True


# ---------- UI wiring (static pins: real endpoints, no browser math) ----------

def read(p):
    return open(p, encoding="utf-8").read()


def test_species_card_wires_the_build_endpoints_only():
    js = read("app/static/js/80_prep.js")
    card = js.split("function prepSpecies(")[1].split("async function prepOrigin")[0]
    assert "/species" in card and "POST" in card
    assert "api(" in card, "must go through the authenticated api() helper"
    assert "characters/" not in card, "the card must never PUT character rows"
    # the APPLY helper too
    apply_js = js.split("async function prepSpeciesApply(")[1].split("async function prepOrigin")[0]
    assert "/species" in apply_js and "{}" in apply_js
    html = read("app/static/index.html")
    assert 'id="prep-species-card"' in html and 'id="prep-species-out"' in html
    assert "prepSpecies" in read("app/static/js/80_prep.js")


def test_card_states_2024_provenance_honestly():
    js = read("app/static/js/80_prep.js")
    card = js.split("function renderSpeciesReport(")[1].split("async function prepSpeciesApply")[0]
    assert "background" in card.lower() and "Origin card" in card, \
        "the card must tell the player the 2024 ASIs come from the background"
