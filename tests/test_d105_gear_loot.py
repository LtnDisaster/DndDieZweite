"""D105: class starting gear, NPC inventories and looting.

Everything reuses the engines that already exist: grants run through
app/inventory.py with the D94 op_id replay guard, NPC gear lives in the SAME
containers table under the synthetic key "tok:<token_id>", and looting mirrors
the D82/D92 container authorisation (same room, same plane, standing adjacent,
own character — the DM may act for any seated one). The class grant is
ALL-OR-NOTHING: a broken pack refuses completely and writes NO claim, so
fixing the CSV stays possible; a granted class kit is exactly-once and a later
request with different choices answers "already" — it can neither add items
nor overwrite the original pick. Loot opens exactly while the NPC's
server-side hp is 0 and locks again the moment it is healed above 0.
"""
import uuid
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from app import content as C, db, inventory as INV, main
from tests.test_movement_fog import (H, add_npc, base_room, join_room,
                                     make_char, park, reg, recv_until,
                                     set_grid, state_of, ws_connect)
from tests.test_d102_floors import add_floor, dm_hop
from tests.test_sprint22_containers import _chest_at_player, _fill

PACK = Path(__file__).resolve().parents[1] / "app" / "content_pack"
GEAR_IDS = ("sword_plus1", "sword_versatile", "axe_great", "bow_long",
            "dagger_surge", "ring_warding", "leather_vest", "gloves_thief",
            "goggles_night", "gloves_giant", "potion_heal", "talisman_fate")


@pytest.fixture()
def client():
    return TestClient(main.app)


def _room(client):
    """base_room + pack import with EVERY item id tagged — item_defs.id is a
    global pk, so each room owns its projections (same trick as D101). The
    class gear strings in classes.csv are rewritten too, so the scout/warden
    kits still resolve to this room's definitions."""
    dm, player, code, ch = base_room(client)
    rid = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
    files = {p.name: p.read_text(encoding="utf-8") for p in PACK.glob("*.csv")}
    tag = uuid.uuid4().hex[:6]
    for name in ("items.csv", "backgrounds.csv", "classes.csv"):
        for gid in GEAR_IDS:
            files[name] = files[name].replace(gid, f"{gid}_{tag}")
    C.import_package(files, room_id=rid, mode="apply", apply=True)
    return dm, player, code, ch, tag


def _char(client, user, bg="", cls=""):
    r = client.post("/api/characters", headers=H(user), json={
        "name": "Kit-" + cls + bg, "race": "Kit-kin", "char_class": cls,
        "background": bg, "level": 1, "hp": 10, "max_hp": 10})
    assert r.status_code == 200, r.text
    return r.json()


def _gear(client, user, code, cid, picks=None):
    body = {"character_id": cid}
    if picks is not None:
        body["class_choices"] = picks
    return client.post(f"/api/rooms/{code}/starting-gear", headers=H(user), json=body)


def _names(rows):
    return sorted(f"{r['qty']}×{r['name']}" for r in rows)


def _sheet_items(char_id):
    row = db.q1("SELECT items FROM characters WHERE id=?", (char_id,))
    return db.j(row["items"], [])


def _qty(char_id, def_startswith):
    return sum(i["qty"] for i in _sheet_items(char_id)
               if (i.get("def_id") or "").startswith(def_startswith))


def _qty_sheet(char_id, name):
    return sum(i["qty"] for i in _sheet_items(char_id) if i["name"] == name)


def _tokcell(client, user, code):
    st = state_of(client, user, code)
    tok = next(t for t in st["tokens"] if t.get("owner_user_id") == st["me"])
    return int(tok["x"] // 50), int(tok["y"] // 50)


def _npc(client, dm, code, cx=16, cy=12, hp=0):
    """DM spawns an NPC token at cell (cx,cy) WITH a stat block (hp)."""
    with ws_connect(client, dm, code) as ws:
        tok = add_npc(ws, label="Goblin", cx=cx, cy=cy)
        ws.send_json({"type": "update_npc", "token_id": tok, "label": "Goblin",
                      "hp": hp, "max_hp": 7, "ac": 13, "stats": {"str": 12}})
        recv_until(ws, "snapshot")
    return tok


def _npcinv(ws, **kw):
    ws.send_json({"type": "npc_inv", **kw})
    return recv_until(ws, "inv_contents")


def _fill_npc(client, dm, code, tok, name, qty, cp=None):
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "item_def", "action": "create",
                      "defn": {"name": name, "kind": "other", "stackable": True}})
        recv_until(ws, "whisper")
    did = next(d["id"] for d in state_of(client, dm, code)["item_defs"]
               if d["name"] == name)
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "npc_inv", "action": "fill", "token_id": tok,
                      "def_id": did, "qty": qty, "op_id": f"fill-{did}"})
        got = recv_until(ws, "inv_contents")["payload"]
        if cp:
            ws.send_json({"type": "npc_inv", "action": "coins_fill", "token_id": tok,
                          "amount": cp, "coin": "gp", "op_id": "fill-coins"})
            got = recv_until(ws, "inv_contents")["payload"]
    return got


# ================= Phase 2: class starting gear =================

def test_class_gear_grants_fixed_and_chosen(client):
    dm, player, code, _ch, tag = _room(client)
    ch = _char(client, player, "bg_urchin", "scout")
    r = _gear(client, player, code, ch["id"], {"weapon": "bow_long_" + tag,
                                               "kit": "gloves_thief_" + tag})
    j = r.json()
    assert j["ok"] and j["class_status"] == "granted"
    assert _names(j["class_granted"]) == sorted([
        "1×Dagger of the Surge", "1×Gloves of the Thief", "1×Long Bow",
        "2×Healing Draught"])
    assert _qty(ch["id"], f"potion_heal_{tag}") == 2
    assert _qty(ch["id"], f"bow_long_{tag}") == 1
    assert _qty(ch["id"], f"goggles_night_{tag}") == 0     # the ALTERNATIVE stays ungranted


def test_class_gear_needs_choice_before_any_grant(client):
    dm, player, code, _ch, tag = _room(client)
    ch = _char(client, player, "", "scout")
    j = _gear(client, player, code, ch["id"]).json()
    assert j["class_status"] == "needs_choice"
    assert j["needs_choice"] == ["weapon", "kit"] and j["class_granted"] == []
    assert _sheet_items(ch["id"]) == []                   # NOTHING granted yet
    j = _gear(client, player, code, ch["id"], {"weapon": "sword_versatile_" + tag,
                                               "kit": "goggles_night_" + tag}).json()
    assert j["class_status"] == "granted"
    assert _qty(ch["id"], f"sword_versatile_{tag}") == 1


def test_class_gear_exactly_once_other_choices_cannot_override(client):
    dm, player, code, _ch, tag = _room(client)
    ch = _char(client, player, "", "scout")
    picks = {"weapon": "bow_long_" + tag, "kit": "goggles_night_" + tag}
    assert _gear(client, player, code, ch["id"], picks).json()["class_status"] == "granted"
    before = _sheet_items(ch["id"])
    # a later request with DIFFERENT choices: unique status, no items, no overwrite
    j = _gear(client, player, code, ch["id"], {"weapon": "axe_great_" + tag,
                                               "kit": "gloves_thief_" + tag}).json()
    assert j["class_status"] == "already" and j["class_granted"] == []
    assert _sheet_items(ch["id"]) == before


def test_class_gear_all_or_nothing_and_retryable(client):
    dm, player, code, _ch, tag = _room(client)
    rid = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
    C.store("class", rid, {"id": "broken", "level": "1", "name": "Broken",
                           "starting_items": f"bow_long_{tag}, missing_def x2"})
    ch = _char(client, player, "", "broken")
    j = _gear(client, player, code, ch["id"]).json()
    assert j["class_status"] == "invalid"
    assert any("missing_def" in e for e in j["class_errors"])
    assert _sheet_items(ch["id"]) == []                   # not even the bow
    # fixing the pack must stay possible: NO idempotency claim was written
    C.store("class", rid, {"id": "broken", "level": "1", "name": "Broken",
                           "starting_items": f"bow_long_{tag}"})
    j = _gear(client, player, code, ch["id"]).json()
    assert j["class_status"] == "granted" and _qty(ch["id"], f"bow_long_{tag}") == 1


def test_malformed_tokens_are_errors_not_grants(client):
    dm, player, code, _ch, tag = _room(client)
    rid = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
    C.store("class", rid, {"id": "badtok", "level": "1", "name": "Bad",
                           "starting_items": f"bow_long_{tag}, Sword +1, axe x0"})
    ch = _char(client, player, "", "badtok")
    j = _gear(client, player, code, ch["id"]).json()
    assert j["class_status"] == "invalid" and _sheet_items(ch["id"]) == []


def test_report_shows_gear_errors_before_granting(client):
    dm, player, code, _ch, tag = _room(client)
    ch = _char(client, player, "bg_urchin", "scout")
    j = client.get(f"/api/rooms/{code}/starting-gear/{ch['id']}",
                   headers=H(player)).json()
    assert j["needs_choice"] == ["weapon", "kit"]
    cls = j["class"]
    assert {f["name"] for f in cls["fixed"]} == {"Dagger of the Surge", "Healing Draught"}
    assert [g["label"] for g in cls["groups"]] == ["weapon", "kit"]
    assert all(o["resolved"] for g in cls["groups"] for o in g["options"])
    assert j["background"]["skipped"] == ["coin purse"]   # D101 report semantics kept
    outsider = reg(client, "out")
    assert client.get(f"/api/rooms/{code}/starting-gear/{ch['id']}",
                      headers=H(outsider)).status_code == 403


def test_class_only_and_no_pack_class_paths(client):
    dm, player, code, _ch, tag = _room(client)
    only = _char(client, player, "", "warden")
    j = _gear(client, player, code, only["id"], {"focus": "ring_warding_" + tag}).json()
    assert j["ok"] and j["class_status"] == "granted"     # no background is no blocker
    assert "no background" in j["error"]
    bard = _char(client, player, "bg_urchin", "bard")
    j = _gear(client, player, code, bard["id"]).json()
    assert j["ok"] and j["class_status"] == "not_in_pack"
    assert j["granted"] != []                               # bg still grants


def test_choice_injection_and_unknown_groups_refused(client):
    dm, player, code, _ch, tag = _room(client)
    ch = _char(client, player, "", "scout")
    j = _gear(client, player, code, ch["id"], {"weapon": "axe_great_" + tag,
                                               "kit": "gloves_thief_" + tag}).json()
    assert j["class_status"] == "invalid" and _sheet_items(ch["id"]) == []
    j = _gear(client, player, code, ch["id"], {"weapon": "bow_long_" + tag,
                                               "kit": "gloves_thief_" + tag,
                                               "money": "sword_plus1_" + tag}).json()
    assert j["class_status"] == "invalid" and _sheet_items(ch["id"]) == []


def test_background_grant_semantics_unchanged(client):
    dm, player, code, _ch, tag = _room(client)
    ch = _char(client, player, "bg_urchin", "")           # bg only — D101 shape
    j = _gear(client, player, code, ch["id"]).json()
    assert j["ok"] and not j["already"] and j["class_status"] == "none"
    assert [g["name"] for g in j["granted"]] == ["Sword +1"] and j["skipped"] == ["coin purse"]
    j2 = _gear(client, player, code, ch["id"]).json()
    assert j2["ok"] and j2["already"] and j2["granted"] == []
    # parts are independent: on a class-carrying twin the class part grants
    # while the background part answers 'already'
    twin = _char(client, player, "bg_urchin", "scout")
    j3 = _gear(client, player, code, twin["id"], {"weapon": "bow_long_" + tag,
                                                  "kit": "gloves_thief_" + tag}).json()
    assert j3["ok"] and not j3["already"] and j3["class_status"] == "granted"
    assert _qty(twin["id"], f"bow_long_{tag}") == 1 and _qty(twin["id"], f"sword_plus1_{tag}") == 1


# ================= Phase 3: DM-side NPC inventories =================

def test_npc_inv_fill_and_inspect_by_dm(client):
    dm, player, code, _ch, _tag = _room(client)
    tok = _npc(client, dm, code, hp=7)
    got = _fill_npc(client, dm, code, tok, "Torch", 3, cp=5)
    assert got["items"][0]["qty"] == 3 and got["coins"] == 500     # 5 gp = 500 cp
    with ws_connect(client, dm, code) as ws:
        got = _npcinv(ws, action="inspect", token_id=tok)
    assert got["payload"]["items"][0]["name"] == "Torch"
    with ws_connect(client, dm, code) as ws:              # remove one
        ws.send_json({"type": "npc_inv", "action": "remove", "token_id": tok,
                      "item_id": got["payload"]["items"][0]["id"], "qty": 1, "op_id": "r1"})
        back = recv_until(ws, "inv_contents")["payload"]
    assert back["items"][0]["qty"] == 2


def test_npc_inv_is_dm_only_and_never_in_snapshots(client):
    dm, player, code, _ch, _tag = _room(client)
    tok = _npc(client, dm, code, hp=7)
    _fill_npc(client, dm, code, tok, "Secret Amulet", 1, cp=2)
    # players may not see or edit a LIVING NPC's inventory: no reply at all —
    # proven with a canary: the loot inspect on the SAME living NPC answers
    # with an error, and no inv_contents may arrive before that error.
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "npc_inv", "action": "inspect", "token_id": tok})
        ws.send_json({"type": "loot", "action": "inspect", "token_id": tok})
        seen = []
        while True:
            ev = ws.receive_json()
            seen.append(ev.get("kind"))
            if ev.get("kind") in ("error", "inv_contents"):
                break
        assert seen.count("inv_contents") == 0 and seen[-1] == "error"
    st = state_of(client, player, code)
    assert "Secret Amulet" not in str(st)                  # contents never ride a state
    dmt = {t["id"]: t for t in state_of(client, dm, code)["tokens"]}
    assert dmt[tok]["npc"]["hp"] == 7                      # DM sheet: hp yes, gear never in payload


def test_npc_coins_remove_and_shortfall(client):
    dm, player, code, _ch, _tag = _room(client)
    tok = _npc(client, dm, code, hp=7)
    _fill_npc(client, dm, code, tok, "Torch", 1, cp=5)
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "npc_inv", "action": "coins_remove", "token_id": tok,
                      "amount": 2, "coin": "gp", "op_id": "cr1"})
        got = recv_until(ws, "inv_contents")["payload"]
        assert got["coins"] == 300
        ws.send_json({"type": "npc_inv", "action": "coins_remove", "token_id": tok,
                      "amount": 99, "coin": "gp", "op_id": "cr2"})
        err = recv_until(ws, "error")
    assert "enough coin" in err["payload"]["msg"].lower()


# ================= Phase 4/5: looting a downed NPC =================

def _loot_take(ws, tok, char_id, item_id, qty, op):
    ws.send_json({"type": "loot", "action": "take", "token_id": tok, "char_id": char_id,
                  "item_id": item_id, "qty": qty, "op_id": op})


def test_loot_alive_denied_for_player_and_dm(client):
    dm, player, code, ch, _tag = _room(client)
    cx, cy = _tokcell(client, player, code)
    tok = _npc(client, dm, code, cx=cx, cy=cy + 1, hp=4)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "loot", "action": "inspect", "token_id": tok})
        assert recv_until(ws, "error")["payload"]["msg"] == "It isn't here."
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "loot", "action": "inspect", "token_id": tok})
        assert "still standing" in recv_until(ws, "error")["payload"]["msg"]


def test_loot_dead_take_by_player(client):
    dm, player, code, ch, _tag = _room(client)
    cx, cy = _tokcell(client, player, code)
    tok = _npc(client, dm, code, cx=cx, cy=cy + 1, hp=0)
    got = _fill_npc(client, dm, code, tok, "Torch", 2)
    iid = got["items"][0]["id"]
    with ws_connect(client, player, code) as ws:
        _loot_take(ws, tok, ch["id"], iid, 1, "L1")
        after = recv_until(ws, "inv_contents")["payload"]
    assert after["items"][0]["qty"] == 1
    assert _qty_sheet(ch["id"], "Torch") == 1
    # replay of the SAME op_id: whisper, no second copy, corpse keeps 1 torch
    with ws_connect(client, player, code) as ws:
        _loot_take(ws, tok, ch["id"], iid, 1, "L1")
        recv_until(ws, "whisper")
    assert _qty_sheet(ch["id"], "Torch") == 1


def test_loot_requires_adjacency(client):
    dm, player, code, ch, _tag = _room(client)
    cx, cy = _tokcell(client, player, code)
    tok = _npc(client, dm, code, cx=cx + 6, cy=cy, hp=0)
    _fill_npc(client, dm, code, tok, "Torch", 1)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "loot", "action": "inspect", "token_id": tok})
        assert recv_until(ws, "error")["payload"]["msg"] == "Walk up to it first"


def test_loot_foreign_character_refused(client):
    dm, player, code, _ch, _tag = _room(client)
    other = reg(client, "other"); join_room(client, other, code)
    rival = _char(client, other, "", "")
    client.post(f"/api/rooms/{code}/assign", headers=H(other),
                json={"character_id": rival["id"]})
    cx, cy = _tokcell(client, player, code)
    tok = _npc(client, dm, code, cx=cx, cy=cy + 1, hp=0)
    _fill_npc(client, dm, code, tok, "Torch", 1)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "loot", "action": "take", "token_id": tok,
                      "char_id": rival["id"], "item_id": "x", "qty": 1, "op_id": "F1"})
        assert recv_until(ws, "error")["payload"]["msg"] == "Not your character"
    # the DM may act for any seated character (mirrors the items.py pattern)
    with ws_connect(client, dm, code) as ws:
        got = _npcinv(ws, action="inspect", token_id=tok)
        iid = got["payload"]["items"][0]["id"]
    with ws_connect(client, dm, code) as ws:
        _loot_take(ws, tok, rival["id"], iid, 1, "DM1")
        recv_until(ws, "inv_contents")
    assert _qty_sheet(rival["id"], "Torch") == 1


def test_loot_cross_plane_and_foreign_room_stay_silent(client):
    dm, player, code, ch, _tag = _room(client)
    cx, cy = _tokcell(client, player, code)
    add_floor(client, dm, code, "Cellar")
    far = _npc(client, dm, code, cx=cx, cy=cy + 1, hp=0)
    _fill_npc(client, dm, code, far, "CellarCoin", 1)
    dm_hop(client, dm, code, far, "Cellar")               # corpse downstairs
    near = _npc(client, dm, code, cx=cx + 1, cy=cy, hp=0)
    _fill_npc(client, dm, code, near, "NearTorch", 1)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "loot", "action": "inspect", "token_id": far})
        ws.send_json({"type": "loot", "action": "inspect", "token_id": near})
        got = recv_until(ws, "inv_contents")["payload"]
    assert got["npc_token"] == near                        # cellar corpse never answered
    # foreign room's token id is silently unknown here
    dm2, player2, code2, _c2 = base_room(client)
    other_tok = _npc(client, dm2, code2, hp=0)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "loot", "action": "inspect", "token_id": other_tok})
        ws.send_json({"type": "loot", "action": "inspect", "token_id": near})
        got = recv_until(ws, "inv_contents")["payload"]
    assert got["npc_token"] == near


def test_last_item_race_only_one_winner(client):
    dm, player, code, ch, _tag = _room(client)
    p2 = reg(client, "second"); join_room(client, p2, code)
    ch2 = _char(client, p2, "", "")
    client.post(f"/api/rooms/{code}/assign", headers=H(p2), json={"character_id": ch2["id"]})
    cx, cy = _tokcell(client, player, code)
    tok = _npc(client, dm, code, cx=cx, cy=cy + 1, hp=0)
    got = _fill_npc(client, dm, code, tok, "Last Torch", 1)
    iid = got["items"][0]["id"]
    st2 = state_of(client, p2, code)
    t2 = next(t["id"] for t in st2["tokens"] if t.get("owner_user_id") == st2["me"])
    park(client, dm, code, t2, tx=cx, ty=cy + 2)          # second player adjacent too
    with ws_connect(client, player, code) as wsA, ws_connect(client, p2, code) as wsB:
        _loot_take(wsA, tok, ch["id"], iid, 1, "A1")
        recv_until(wsA, "inv_contents")
        _loot_take(wsB, tok, ch2["id"], iid, 1, "B1")
        err = recv_until(wsB, "error")
    assert "not found" in err["payload"]["msg"].lower() or "only" in err["payload"]["msg"].lower()
    assert _qty_sheet(ch["id"], "Last Torch") + _qty_sheet(ch2["id"], "Last Torch") == 1


def test_loot_direction_is_forced_take(client):
    # the looter ALREADY carries the same definition — a take must never turn
    # into a deposit into the corpse (container_move's fundort rule would!)
    dm, player, code, ch, _tag = _room(client)
    cx, cy = _tokcell(client, player, code)
    tok = _npc(client, dm, code, cx=cx, cy=cy + 1, hp=0)
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "item_def", "action": "create",
                      "defn": {"name": "Coin Purse Loot", "kind": "other", "stackable": True}})
        recv_until(ws, "whisper")
    did = next(d["id"] for d in state_of(client, dm, code)["item_defs"]
               if d["name"] == "Coin Purse Loot")
    with ws_connect(client, dm, code) as ws:              # give the player one already
        # the grant's whisper goes to the RECIPIENT's socket, not the DM's —
        # the DM only needs the fill's inv_contents (inv_changed is skipped)
        ws.send_json({"type": "inv_grant", "char_id": ch["id"], "def_id": did, "qty": 1,
                      "op_id": "pre"})
        ws.send_json({"type": "npc_inv", "action": "fill", "token_id": tok,
                      "def_id": did, "qty": 2, "op_id": "pre2"})
        got = recv_until(ws, "inv_contents")["payload"]
    iid = got["items"][0]["id"]
    with ws_connect(client, player, code) as ws:
        _loot_take(ws, tok, ch["id"], iid, 1, "P1")
        recv_until(ws, "inv_contents")
    assert _qty_sheet(ch["id"], "Coin Purse Loot") == 2    # 1 old + 1 looted
    row = db.q1("SELECT items FROM containers WHERE room_id=(SELECT id FROM rooms WHERE code=?) "
                "AND object_id=?", (code, f"tok:{tok}"))
    assert db.j(row["items"], [])[0]["qty"] == 1           # corpse lost exactly one


def test_loot_coins_into_own_purse(client):
    dm, player, code, ch, _tag = _room(client)
    cx, cy = _tokcell(client, player, code)
    tok = _npc(client, dm, code, cx=cx, cy=cy + 1, hp=0)
    _fill_npc(client, dm, code, tok, "Torch", 1, cp=3)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "loot", "action": "coins_take", "token_id": tok,
                      "char_id": ch["id"], "amount": 1, "coin": "gp", "op_id": "C1"})
        got = recv_until(ws, "inv_contents")["payload"]
    assert got["coins"] == 200
    assert INV.wallet_of(db.q1("SELECT * FROM characters WHERE id=?", (ch["id"],))) == 100


def test_loot_heal_above_zero_relocks_immediately(client):
    dm, player, code, ch, _tag = _room(client)
    cx, cy = _tokcell(client, player, code)
    tok = _npc(client, dm, code, cx=cx, cy=cy + 1, hp=0)
    got = _fill_npc(client, dm, code, tok, "Torch", 2)
    iid = got["items"][0]["id"]
    with ws_connect(client, player, code) as ws:
        _loot_take(ws, tok, ch["id"], iid, 1, "H1")
        recv_until(ws, "inv_contents")
    with ws_connect(client, dm, code) as ws:              # heal to 3
        ws.send_json({"type": "update_npc", "token_id": tok, "label": "Goblin",
                      "hp": 3, "max_hp": 7})
        recv_until(ws, "snapshot")
    with ws_connect(client, player, code) as ws:
        _loot_take(ws, tok, ch["id"], iid, 1, "H2")
        assert recv_until(ws, "error")["payload"]["msg"] == "It isn't here."
    assert _qty_sheet(ch["id"], "Torch") == 1


def test_token_deletion_cleans_only_its_container(client):
    dm, player, code, ch, _tag = _room(client)
    cx, cy = _chest_at_player(client, dm, player, code)
    chest = _fill(client, dm, code, "chest", "Chest Gold", 2)
    assert chest["items"][0]["qty"] == 2
    tok = _npc(client, dm, code, cx=cx + 2, cy=cy, hp=0)
    _fill_npc(client, dm, code, tok, "Corpse Torch", 1, cp=1)
    rid = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
    assert db.q1("SELECT 1 AS hit FROM containers WHERE room_id=? AND object_id=?",
                 (rid, f"tok:{tok}")) is not None
    with ws_connect(client, dm, code) as ws:
        ws.send_json({"type": "del_token", "token_id": tok})
        recv_until(ws, "token_gone")
    assert db.q1("SELECT 1 AS hit FROM containers WHERE room_id=? AND object_id=?",
                 (rid, f"tok:{tok}")) is None              # no orphan hoard
    assert db.q1("SELECT 1 AS hit FROM containers WHERE room_id=? AND object_id=?",
                 (rid, "chest")) is not None               # world container untouched


# ================= UI wiring (source pins, D101 style) =================

def _js(name):
    from pathlib import Path
    return (Path(__file__).resolve().parents[1] / "app" / "static" / "js" / name)\
        .read_text(encoding="utf-8")


def test_prep_ui_is_server_driven_with_choices(client):
    js = _js("80_prep.js")
    assert "/starting-gear/${ch.id}" in js                  # GET report first …
    assert "class_choices" in js                            # … one POST carries the picks
    assert 'name="gear-' in js                              # server's groups become radio fields
    assert "renderGearReport" in js and "prepGearGrant" in js
    assert "class_status" in js                             # needs_choice / already / invalid shown


def test_loot_and_npc_inventory_are_wired(client):
    js = _js("30_room.js")
    assert 'function openNpcChest' in js and 'function openLootChest' in js
    assert 'wsSend({ type: "npc_inv", action: "inspect", token_id: tokId })' in js
    assert 'wsSend({ type: "loot", action: "inspect", token_id: tokId })' in js
    assert 'type: src === "npc" ? "npc_inv" : "loot", token_id: cs.token_id' in js
    assert '"btn-loot-npc"' in js and '"npc-inventory"' in js   # sheet buttons exist
    # every mutation from the chest panel carries an op_id (replay protection):
    # take/move, remove, fill and the three coin actions all share one builder
    chest = js[js.index("function renderInvChest"):]
    assert chest.count("op_id: invOpId()") >= 4
