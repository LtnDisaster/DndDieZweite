"""D101: room preparation UX — the guided flow's server edge + UI wiring.

Pins the three NEW server surfaces the preparation screen is built on and the
regression paths the browser findings demanded:

  1. ``GET /api/content/{code}/options`` — every ROOM MEMBER may read the
     rule pack's id+name catalogue (the dropdown source); non-members may not.
  2. ``characters.background`` + ``POST /api/rooms/{code}/starting-gear`` —
     the background's starting_items are granted ONLY where they resolve to an
     item definition of this room (through app/inventory.py), idempotently
     (inv_ops replay → "already", never a double grant), unresolvable text is
     reported, and authorisation mirrors the build API exactly.
  3. ``charbuild.apply`` now BROADCASTS a snapshot (the confirmed browser bug:
     apply stored fine but every open sheet kept showing "unbuilt" until a
     full reload — the client-side re-render is pinned by source assertion).

The UI regressions follow the established source-assert style of
test_content.test_dm_content_panel_is_wired (no browser runner exists).
"""
import re
import uuid
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from app import content as C, db, gear, main
from tests.test_movement_fog import (H, base_room, join_room, make_char, reg,
                                     recv_until, ws_connect)

PACK = Path(__file__).resolve().parents[1] / "app" / "content_pack"
STATIC = Path(__file__).resolve().parents[1] / "app" / "static"


@pytest.fixture()
def client():
    return TestClient(main.app)


def _js(name):
    return (STATIC / "js" / name).read_text(encoding="utf-8")


def _room(client, import_pack=True):
    dm, player, code, ch = base_room(client)
    if import_pack:
        rid = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
        files = {p.name: p.read_text(encoding="utf-8") for p in PACK.glob("*.csv")}
        # item_defs.id is a GLOBAL pk (D100 G9): every test in this session shares
        # one DB, so a plain pack re-import into room #2 would REFUSE the item
        # projection ("shared id owned by another room"). Tests import a variant
        # with unique item ids so THIS room always owns its projections.
        tag = uuid.uuid4().hex[:6]
        for name in ("items.csv", "backgrounds.csv"):
            files[name] = (files[name]
                           .replace("sword_plus1", f"sword_plus1_{tag}")
                           .replace("potion_heal", f"potion_heal_{tag}"))
        C.import_package(files, room_id=rid, mode="apply", apply=True)
    return dm, player, code, ch


def _char_with_bg(client, user, bg):
    r = client.post("/api/characters", headers=H(user), json={
        "name": "Bggy", "race": "Kit-kin", "char_class": "scout",
        "background": bg, "level": 1, "hp": 10, "max_hp": 10})
    assert r.status_code == 200, r.text
    return r.json()


# ---------- options catalogue (dropdown source) ----------

def test_options_member_reads_catalogue(client):
    _dm, player, code, _ch = _room(client)
    r = client.get(f"/api/content/{code}/options", headers=H(player))
    assert r.status_code == 200, r.text
    o = r.json()["options"]
    assert {"species", "class", "subclass", "background", "feat", "spell", "item"} <= set(o)
    assert {"scout", "adept", "warden", "seer"} == {c["id"] for c in o["class"]}   # one row per class, not per level
    assert all(c["name"] for c in o["class"])
    assert "bg_urchin" in {b["id"] for b in o["background"]}
    assert any(i["id"].startswith("potion_heal") for i in o["item"])


def test_options_outsider_and_anon_refused(client):
    _dm, _player, code, _ch = _room(client)
    outsider = reg(client, "out")
    assert client.get(f"/api/content/{code}/options", headers=H(outsider)).status_code == 403
    client.cookies.clear()
    assert client.get(f"/api/content/{code}/options").status_code == 401


def test_options_empty_room_lists_nothing(client):
    _dm, player, code, _ch = _room(client, import_pack=False)
    o = client.get(f"/api/content/{code}/options", headers=H(player)).json()["options"]
    assert o["class"] == [] and o["species"] == []


# ---------- characters.background (additive column) ----------

def test_background_roundtrip_and_put_wipe_guard(client):
    _dm, player, _code, _ch = _room(client)
    ch = _char_with_bg(client, player, "bg_scholar")
    assert ch["background"] == "bg_scholar"
    assert db.q1("SELECT background FROM characters WHERE id=?", (ch["id"],))["background"] == "bg_scholar"
    # a PUT that predates the field (no background key at all) must NOT wipe it
    body = {"name": "Renamed", "race": "Kit-kin", "char_class": "scout",
            "level": 1, "hp": 10, "max_hp": 10}
    r = client.put(f"/api/characters/{ch['id']}", headers=H(player), json=body)
    assert r.status_code == 200 and r.json()["background"] == "bg_scholar"
    # the explicit reset stays available
    body["background"] = ""
    r = client.put(f"/api/characters/{ch['id']}", headers=H(player), json=body)
    assert r.json()["background"] == ""


# ---------- starting gear ----------

def _gear(client, user, code, cid):
    return client.post(f"/api/rooms/{code}/starting-gear", headers=H(user),
                       json={"character_id": cid})


def test_starting_gear_grants_resolves_skips_and_is_idempotent(client):
    _dm, player, code, _ch = _room(client)
    ch = _char_with_bg(client, player, "bg_urchin")   # "sword_plus1, coin purse"
    r = _gear(client, player, code, ch["id"])
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ok"] and not j["already"]
    assert [g["name"] for g in j["granted"]] == ["Sword +1"]
    assert j["skipped"] == ["coin purse"]             # reported, never invented
    items = gear.clean_items(db.j(db.q1("SELECT items FROM characters WHERE id=?", (ch["id"],))["items"], []))
    assert sum(i["qty"] for i in items if (i["def_id"] or "").startswith("sword_plus1")) == 1
    # replay: same background again — the inv_ops guard answers, nothing doubles
    j2 = _gear(client, player, code, ch["id"]).json()
    assert j2["ok"] and j2["already"] and j2["granted"] == []
    items2 = gear.clean_items(db.j(db.q1("SELECT items FROM characters WHERE id=?", (ch["id"],))["items"], []))
    assert sum(i["qty"] for i in items2 if (i["def_id"] or "").startswith("sword_plus1")) == 1


def test_starting_gear_authorization_mirrors_build_api(client):
    dm, player, code, ch = _room(client)
    member2 = reg(client, "mem")
    join_room(client, member2, code)
    outsider = reg(client, "out")
    bggy = _char_with_bg(client, player, "bg_scholar")
    assert _gear(client, player, code, bggy["id"]).json()["ok"] is True      # owner
    assert _gear(client, member2, code, bggy["id"]).status_code == 403       # member, not owner
    assert _gear(client, outsider, code, bggy["id"]).status_code == 403      # not a member
    client.cookies.clear()
    assert client.post(f"/api/rooms/{code}/starting-gear", json={"character_id": bggy["id"]}).status_code == 401
    # the DM may grant onto a character ASSIGNED to the room ...
    assert _gear(client, dm, code, ch["id"]).json()["ok"] is False           # ... but this one has no background yet
    ch2 = _char_with_bg(client, player, "bg_scholar")
    # re-seat (second assign for one user, token already exists) — D101 pins the
    # latent Row-vs-dict crash that 500'd exactly this preparation-screen path.
    assert client.post(f"/api/rooms/{code}/assign", headers=H(player),
                       json={"character_id": ch2["id"]}).status_code == 200
    assert _gear(client, dm, code, ch2["id"]).json()["granted"] != []
    # ... and NOT onto an unassigned foreign character
    ch3 = _char_with_bg(client, player, "bg_urchin")
    assert _gear(client, dm, code, ch3["id"]).status_code == 403


def test_starting_gear_missing_data_is_reported(client):
    _dm, player, code, _ch = _room(client)
    no_bg = make_char(client, player)
    j = _gear(client, player, code, no_bg["id"]).json()
    assert j["ok"] is False and "no background" in j["error"]
    ghost = _char_with_bg(client, player, "bg_nonexistent")
    j = _gear(client, player, code, ghost["id"]).json()
    assert j["ok"] is False and "not in this room" in j["error"]
    # room WITHOUT a rule pack: even a valid background id cannot resolve
    _dm2, player2, code2, _c2 = _room(client, import_pack=False)
    orphan = _char_with_bg(client, player2, "bg_scholar")
    j = _gear(client, player2, code2, orphan["id"]).json()
    assert j["ok"] is False and "not in this room" in j["error"]


def test_starting_gear_broadcasts_inv_changed(client):
    dm, player, code, _ch = _room(client)
    bggy = _char_with_bg(client, player, "bg_scholar")
    with ws_connect(client, dm, code) as ws:
        assert _gear(client, player, code, bggy["id"]).json()["ok"] is True
        recv_until(ws, "inv_changed")


# ---------- the confirmed reload bug: apply must notify every client ----------

SCOUT_L1 = {"class_id": "scout", "to": 1,
            "choices": {"skills": ["stealth", "perception", "acrobatics", "athletics"],
                        "levels": {"1": {"expertise": "stealth"}}}}


def test_apply_broadcasts_snapshot_so_sheets_update_without_reload(client):
    _dm, player, code, ch = _room(client)
    with ws_connect(client, player, code) as ws:
        r = client.post(f"/api/build/{code}/{ch['id']}/apply", headers=H(player), json=SCOUT_L1)
        assert r.status_code == 200 and r.json()["ok"] is True
        recv_until(ws, "snapshot")          # every client refetches + re-renders its sheet


def test_apply_rejects_manipulated_choices(client):
    _dm, player, code, ch = _room(client)
    body = {"class_id": "scout", "to": 1, "choices": {"skills": ["not_a_skill"]}}
    j = client.post(f"/api/build/{code}/{ch['id']}/apply", headers=H(player), json=body).json()
    assert j["ok"] is False and j["needs_choice"][0]["kind"] == "skills"
    body = {"class_id": "scout", "to": 3,
            "choices": {"skills": ["stealth", "perception", "acrobatics", "athletics"],
                        "subclass": "tradition_ghost",
                        "levels": {"1": {"expertise": "stealth"}}}}
    j = client.post(f"/api/build/{code}/{ch['id']}/apply", headers=H(player), json=body).json()
    assert j["ok"] is False and "subclass" in j["error"]
    # the refusals wrote nothing: still unbuilt
    row = db.q1("SELECT build FROM characters WHERE id=?", (ch["id"],))
    assert (row["build"] or "") == ""


# ---------- UI wiring regressions (source asserts — no browser runner exists) ----------

def test_prep_screen_is_wired():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    order = re.findall(r"/static/js/([0-9A-Za-z_]+\.js)", html)
    assert order.index("70_content.js") < order.index("80_prep.js") < order.index("99_boot.js")
    for cid in ("view-prep", "prep-char", "prep-class", "prep-species", "prep-bg",
                "prep-plan", "prep-apply", "prep-assign", "prep-gear", "prep-table",
                "prep-ct-file", "prep-ct-upload", "prep-kinds", "btn-prep"):
        assert f'id="{cid}"' in html, f"missing prep element {cid}"
    boot = _js("99_boot.js")
    assert '"80_prep.js"' in boot.split("MODULES")[1].split("]")[0]
    for fn in ("wirePrep", "openPrep", "backToPrep"):
        assert f'"{fn}"' in boot.split("REQUIRED")[1].split("]")[0]
    assert "wirePrep();" in _js("60_main.js")
    # join/create and the room list land on PREP; the table's back button returns there
    m = _js("60_main.js")
    assert "openPrep(r.code)" in m and "backToPrep()" in m
    assert "openPrep(r.code)" in _js("20_lobby.js")
    assert '"prep"' in _js("10_core.js")          # show() knows the view
    # the guided flow talks to the real endpoints and never to a second engine
    prep = _js("80_prep.js")
    assert "window.__BUILDS" in prep
    assert "/content/${code}/options" in prep
    assert "starting-gear" in prep and "/plan?class_id=" in prep
    assert "/build/${p.code}/" in prep and "/assign" in prep


def test_apply_then_rerenders_the_open_sheet():
    # D101 browser bug: after a successful apply the sheet stayed "unbuilt"
    # until a full reload — the handler must re-render like the snapshot path.
    room = _js("30_room.js")
    pat = re.compile(r'"Built to level "[\s\S]{0,160}await refreshRoom\(\);\s*\n?\s*if \(state\.sel\) '
                     r'renderSheet\(state\.tokens\.find\(t => t\.id === state\.sel\) \|\| null\);')
    assert pat.search(room), "apply handler must refreshRoom() AND re-render the selected sheet"


def test_old_rooms_and_legacy_flows_untouched():
    # the classic table entry (Bring -> openRoom -> WS -> Lobby-back) still exists
    lobby = _js("20_lobby.js")
    assert "/assign" in lobby and "openRoom(state.rooms[0].code)" in lobby
    room = _js("30_room.js")
    assert "/ws/${code}" not in room          # WS connect stays in 40_ws.js
    assert "/ws/${" in _js("40_ws.js")
