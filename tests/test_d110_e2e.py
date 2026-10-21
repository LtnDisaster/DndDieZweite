"""D110: the end-to-end dungeon run — one continuous A→F scenario over the
REAL REST + WebSocket paths (no parallel rule simulation), plus small guardian
tests for the seams an integrator must not be able to fall through.

The chain deliberately rides the same handler entry points the browser uses:
register/join/import-pack/character/origin/apply/starting-gear (A),
move/walls/doors/fog/view-as/floors (B), initiative/masteries/conditions/down
(C), adjacency-gated atomic looting (D), DM-authored secret curses with
owner-only whisper delivery (E), reconnect + replay idempotency (F).
"""
import json
import uuid
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from app import content as C, db, main
from app.room import dice as RD
from tests.test_movement_fog import (H, base_room, join_room, reg, recv_until,
                                     set_grid, state_of, ws_connect)
from tests.test_d102_floors import add_floor, dm_hop, state_floor
from tests.test_d104_lights_preview import view_as
from tests.test_d105_gear_loot import GEAR_IDS, _fill_npc, _npc
from tests.test_d106_curses import _curse
from tests.test_d109_mastery import (add_dummy, attack, char_items, conds_of,
                                     dice_bodies, drain, equip, grant_item,
                                     mk_def, rid_of, token_of)
from tests.test_sprint23_combat import _to_player_turn

ROOT = Path(__file__).resolve().parent.parent
PACK = ROOT / "app" / "content_pack"

CURSE_NAME = "Whispering Edge"
CURSE_WHISPER = "It hums to the moon 110-AB."
SECRET = "moonlit-only-110-CD"

SWORD_1H = {"damage_dice": "1d8", "damage_type": "slashing", "ability": "str"}
RD_do_roll0 = RD.do_roll                      # the unpatched roller, for restore


@pytest.fixture()
def client():
    return TestClient(main.app)


# --------------------------------------------------------------- builders

def _campaign_room(client):
    """A fresh room: DM + two players, the shipped pack imported with every
    item id tagged (item_defs.id is a global pk — each room owns its
    projections, the D100/D105 trick)."""
    dm, p1, p2 = reg(client, "dm"), reg(client, "p1"), reg(client, "p2")
    code = client.post("/api/rooms", json={"name": "D110"}, headers=H(dm)).json()["code"]
    join_room(client, p1, code)
    join_room(client, p2, code)
    files = {p.name: p.read_text(encoding="utf-8") for p in PACK.glob("*.csv")}
    tag = uuid.uuid4().hex[:6]
    for name in ("items.csv", "backgrounds.csv", "classes.csv"):
        for gid in GEAR_IDS:
            files[name] = files[name].replace(gid, f"{gid}_{tag}")
    C.import_package(files, room_id=rid_of(code), mode="apply", apply=True)
    return dm, p1, p2, code, tag


def _mk2024(client, user, code, bg, cls):
    r = client.post("/api/characters", headers=H(user), json={
        "name": f"{cls}-{user['name'][:6]}", "race": "kin_fey", "char_class": cls,
        "background": bg, "level": 1, "hp": 10, "max_hp": 10,
        "stats": {k: 10 for k in ("str", "dex", "con", "int", "wis", "cha")}})
    assert r.status_code == 200, r.text
    ch = r.json()
    client.post(f"/api/rooms/{code}/assign", json={"character_id": ch["id"]},
                headers=H(user))
    return ch


def _gear(client, user, code, cid, picks=None):
    body = {"character_id": cid}
    if picks:
        body["class_choices"] = picks
    return client.post(f"/api/rooms/{code}/starting-gear", headers=H(user), json=body)


def _cell(tok_id):
    row = db.q1("SELECT x, y FROM tokens WHERE id=?", (tok_id,))
    return int(row["x"] // 50), int(row["y"] // 50)


def _npc_hp(tok_id):
    block = db.j(db.q1("SELECT npc FROM tokens WHERE id=?", (tok_id,))["npc"], {}) or {}
    return block.get("hp")


def _advance_to(client, dm, code, tok):
    """init_next until `tok` owns the turn (combat must already be active)."""
    with ws_connect(client, dm, code) as dws:
        dws.send_json({"type": "init_next"})
        order = recv_until(dws, "initiative")["payload"]
        guard = 0
        while (order.get("turn") or {}).get("token_id") != tok:
            guard += 1
            assert guard <= 12, f"turn never reached {tok}: {order}"
            dws.send_json({"type": "init_next"})
            order = recv_until(dws, "initiative")["payload"]


def _teleport(client, dm, code, tok, cx, cy):
    with ws_connect(client, dm, code) as dws:
        dws.send_json({"type": "move", "token_id": tok, "tx": cx, "ty": cy,
                       "teleport": True})
        recv_until(dws, "step")


def _sheet(client, user, code, char_id):
    st = state_of(client, user, code)
    return next(m["char"] for m in st["members"]
                if m.get("char") and m["char"]["id"] == char_id)


def _count_items(sheet, name):
    return sum(i["qty"] for i in sheet["items"] if i["name"] == name)


def _snap(client, user, code):
    st = state_of(client, user, code)
    return json.dumps({
        "tokens": sorted((t["id"], t["x"], t["y"], t.get("floor")) for t in st["tokens"]),
        "items": sorted((m["user_id"],
                         sorted((i["id"], i["qty"]) for i in (m["char"] or {}).get("items", [])))
                        for m in st["members"] if m.get("char")),
        "grid": (st["grid"]["w"], st["grid"]["h"], st["grid"]["cells"][:400]),
    })


# ------------------------------------------------- the A→F campaign chain

def test_full_dungeon_runthrough(client, monkeypatch):
    # ================= A: preparation =================
    dm, p1, p2, code, tag = _campaign_room(client)

    ch1 = _mk2024(client, p1, code, "bg_urchin", "scout")
    ch2 = _mk2024(client, p2, code, "bg_scholar", "warden")

    # 2024 origin, server-authoritative: Urchin = +1 to all three (dex/con/cha)
    rep1 = client.get(f"/api/build/{code}/{ch1['id']}/origin", headers=H(p1)).json()
    assert rep1["ready"] and rep1["asi_abilities"] == ["dex", "con", "cha"]
    r = client.post(f"/api/build/{code}/{ch1['id']}/origin", headers=H(p1),
                    json={"asi": {"mode": "three"}})
    assert r.status_code == 200 and r.json()["ok"], r.text
    # Scholar = +2/+1 on two DIFFERENT of int/wis/cha
    r = client.post(f"/api/build/{code}/{ch2['id']}/origin", headers=H(p2),
                    json={"asi": {"mode": "plus2_plus1", "plus2": "int", "plus1": "wis"}})
    assert r.status_code == 200 and r.json()["ok"], r.text
    st1 = db.j(db.q1("SELECT stats FROM characters WHERE id=?", (ch1["id"],))["stats"], {})
    st2 = db.j(db.q1("SELECT stats FROM characters WHERE id=?", (ch2["id"],))["stats"], {})
    assert (st1["dex"], st1["con"], st1["cha"]) == (11, 11, 11)
    assert (st2["int"], st2["wis"]) == (12, 11) and st2["cha"] == 10

    # class level 1 through the build API (chronological, choices server-checked)
    r = client.post(f"/api/build/{code}/{ch1['id']}/apply", headers=H(p1), json={
        "class_id": "scout", "to": 1,
        "choices": {"skills": ["stealth", "perception", "acrobatics", "athletics"],
                    "levels": {"1": {"expertise": "stealth"}}}})
    assert r.status_code == 200 and r.json()["ok"], r.text
    r = client.post(f"/api/build/{code}/{ch2['id']}/apply", headers=H(p2), json={
        "class_id": "warden", "to": 1, "choices": {"skills": ["athletics", "perception"]}})
    assert r.status_code == 200 and r.json()["ok"], r.text

    # Scout L1 grants one Weapon Mastery (D109): pending -> explicit pick
    m1 = client.get(f"/api/build/{code}/{ch1['id']}/mastery", headers=H(p1)).json()
    assert m1["pending"] == 1
    r = client.post(f"/api/build/{code}/{ch1['id']}/mastery", headers=H(p1),
                    json={"pick": "nick"})
    assert r.status_code == 200 and r.json()["ok"], r.text

    # starting equipment: background part + class kit (needs_choice -> picks)
    r = _gear(client, p1, code, ch1["id"]).json()
    assert r["class_status"] == "needs_choice"
    r = _gear(client, p1, code, ch1["id"], picks={
        "weapon": f"sword_versatile_{tag}", "kit": f"gloves_thief_{tag}"}).json()
    assert r.get("ok") is True and r["class_status"] == "granted" and r["class_granted"], r
    _gear(client, p2, code, ch2["id"])
    s1, s2 = _sheet(client, p1, code, ch1["id"]), _sheet(client, p2, code, ch2["id"])
    assert _count_items(s1, "Dagger of the Surge") == 1
    assert _count_items(s1, "Versatile Sword") == 1 and _count_items(s1, "Gloves of the Thief") == 1
    assert len(s2["items"]) > 0

    tok1, tok2 = token_of(client, p1, code, ch1), token_of(client, p2, code, ch2)

    # ================= B: exploration =================
    cx, cy = _cell(tok1)
    with ws_connect(client, p1, code) as w1:
        w1.send_json({"type": "move", "token_id": tok1, "tx": cx + 1, "ty": cy})
        recv_until(w1, "step")
        assert _cell(tok1) == (cx + 1, cy)
        # foreign token control is refused
        w1.send_json({"type": "move", "token_id": tok2, "tx": 20, "ty": 20, "teleport": True})
        ev = recv_until(w1, "error", fail_on_error=False)
        assert ev["kind"] == "error" and "own" in ev["payload"]["msg"]

    cx, cy = _cell(tok1)
    # a wall on the next cell blocks the walk; removing it opens the way
    wall_idx = lambda g: cy * g["w"] + cx + 1          # noqa: E731
    set_grid(client, dm, code, lambda g: g["cells"].__setitem__(wall_idx(g), 1))
    with ws_connect(client, p1, code) as w1:
        w1.send_json({"type": "move", "token_id": tok1, "tx": cx + 1, "ty": cy})
        ev = recv_until(w1, "error", fail_on_error=False)
        assert ev["kind"] == "error"
    set_grid(client, dm, code, lambda g: g["cells"].__setitem__(wall_idx(g), 0))
    with ws_connect(client, p1, code) as w1:
        w1.send_json({"type": "move", "token_id": tok1, "tx": cx + 1, "ty": cy})
        recv_until(w1, "step")
    assert _cell(tok1) == (cx + 1, cy)

    # a door right in front of the player toggles open and shut
    dx, dy = cx + 1, cy
    grid = state_of(client, dm, code)["grid"]
    grid["doors"] = [{"id": "e2e-door", "x": dx, "y": dy, "dir": "v", "open": 0}]
    with ws_connect(client, dm, code) as wsd:
        wsd.send_json({"type": "map_edit", "map": grid})
        recv_until(wsd, "map_changed")
    with ws_connect(client, p1, code) as w1:
        w1.send_json({"type": "door", "x": dx, "y": dy, "dir": "v", "action": "toggle"})
        recv_until(w1, "map_changed")
    first = state_of(client, dm, code)["grid"]["doors"][0].get("closed")
    with ws_connect(client, p1, code) as w1:
        w1.send_json({"type": "door", "x": dx, "y": dy, "dir": "v", "action": "toggle"})
        recv_until(w1, "map_changed")
    second = state_of(client, dm, code)["grid"]["doors"][0].get("closed")
    assert first != second                                  # closed flag flips

    # fog/LOS from the player's seat: a far NPC is invisible to players,
    # visible to the DM; view_as mirrors the PLAYER's view, not the DM's truth
    far_npc = _npc(client, dm, code, cx=40, cy=40, hp=1)
    assert far_npc in {t["id"] for t in state_of(client, dm, code)["tokens"]}
    assert far_npc not in {t["id"] for t in state_of(client, p1, code)["tokens"]}
    pv = view_as(client, dm, code, ch2["id"]).json()
    assert {t["id"] for t in pv["tokens"]} == {t["id"] for t in state_of(client, p2, code)["tokens"]}
    assert far_npc not in {t["id"] for t in pv["tokens"]}

    # floors: the DM moves a PC token down into the crypt and back
    add_floor(client, dm, code, "crypt")
    dm_hop(client, dm, code, tok1, "crypt")
    assert tok1 in {t["id"] for t in state_floor(client, p1, code, "crypt")["tokens"]}
    with ws_connect(client, p1, code) as w1:
        w1.send_json({"type": "token_floor", "token_id": tok1, "floor": ""})
        ev = recv_until(w1, "error", fail_on_error=False)
        assert ev["kind"] == "error", "players may not self-hop planes"
    dm_hop(client, dm, code, tok1, "")
    assert tok1 in {t["id"] for t in state_of(client, p1, code)["tokens"]}

    # ================= C: combat =================
    cx, cy = _cell(tok1)
    npc = _npc(client, dm, code, cx=cx, cy=cy - 1, hp=7)            # north neighbour
    _fill_npc(client, dm, code, npc, "Lucky Coin", 3, cp=500)
    # the cleave pair: NW neighbour of the NPC — within 5 ft of BOTH the body
    # and the attacker, on the side the player has already explored
    d2 = add_dummy(client, dm, code, (cx - 1 + .5) * 50, (cy - 1 + .5) * 50)

    cleaver = mk_def(client, dm, code, dict(SWORD_1H, mastery="cleave"), "E2E Cleaver")
    grazer = mk_def(client, dm, code, dict(SWORD_1H, damage_type="bludgeoning", ability="dex",
                                           mastery="graze"), "E2E Grazer")
    vexer = mk_def(client, dm, code, {"damage_dice": "1d6", "damage_type": "piercing",
                                      "ability": "dex", "mastery": "vex"}, "E2E Vexer")
    grant_item(client, dm, code, ch1["id"], cleaver)
    grant_item(client, dm, code, ch1["id"], grazer)
    grant_item(client, dm, code, ch2["id"], vexer)
    items1 = char_items(client, p1, code)
    cleaver_i = next(i for i in items1 if i["name"] == "E2E Cleaver")["id"]
    grazer_i = next(i for i in items1 if i["name"] == "E2E Grazer")["id"]
    vexer_i = next(i for i in char_items(client, p2, code) if i["name"] == "E2E Vexer")["id"]
    from tests.test_d106_curses import _grant as _dm_grant
    _dm_grant(client, dm, code, ch2["id"], f"sword_versatile_{tag}")
    sword2 = next(i for i in char_items(client, p2, code) if i["name"] == "Versatile Sword")
    assert sword2["props"].get("mastery") == "topple"           # pack mastery rode along
    equip(client, p1, code, ch1["id"], cleaver_i)
    equip(client, p2, code, ch2["id"], sword2["id"])
    from tests.test_d109_mastery import grant
    grant(ch1["id"], "cleave", rid_of(code))
    grant(ch1["id"], "graze", rid_of(code))
    grant(ch2["id"], "vex", rid_of(code))
    r = client.post(f"/api/build/{code}/{ch2['id']}/mastery/grant", headers=H(dm),
                    json={"mastery": "topple"})                    # DM grant route
    assert r.status_code == 200 and r.json()["ok"], r.text

    _to_player_turn(client, dm, code, tok1)
    monkeypatch.setattr(RD.random, "randint", lambda a, b: 20)      # everything hits

    _teleport(client, dm, code, tok2, cx - 1, cy)             # in reach, wrong turn
    with ws_connect(client, p2, code) as w2:
        w2.send_json({"type": "roll", "kind": "attack", "item_id": sword2["id"],
                      "token_id": tok2, "target_id": npc, "visibility": "public",
                      "op_id": "ooff1"})
        ev = recv_until(w2, "error", fail_on_error=False)
        assert ev["kind"] == "error" and "turn" in ev["payload"]["msg"]

    with ws_connect(client, p1, code) as w1:
        # refused BEFORE any die is touched: either "out of reach" (visible but
        # far) or the D94 hidden-target answer — a player may never learn more
        # about a token in the dark than "it is not there". Both are pre-roll.
        attack(w1, cleaver_i, tok1, far_npc, op="reach1")
        ev = recv_until(w1, "error", fail_on_error=False)
        assert ev["kind"] == "error"
        assert "reach" in ev["payload"]["msg"] or "No target" in ev["payload"]["msg"]
        # round 1, p1: Cleave hits npc AND the second target within 5 ft
        attack(w1, cleaver_i, tok1, npc, op="cl1", mastery="cleave", t2=d2)
        bodies = dice_bodies(drain(w1))
        assert any("HIT" in b for b in bodies) and any("AC 13" in b for b in bodies)
        assert any("Cleave vs" in b for b in bodies) and any("Cleave damage" in b for b in bodies)

    _advance_to(client, dm, code, tok2)
    # Topple with a CONTROLLED save: hit 20, CON save 1 — the prone branch is
    # the one under test (a saved Topple correctly says "resists", see D109)
    rolls = iter([{"kept": 20, "adv": None, "rolls": [20], "mod": 0, "total": 20},
                  {"kept": 1, "adv": None, "rolls": [1], "mod": 0, "total": 1}])
    monkeypatch.setattr(RD, "do_roll", lambda expr, adv: next(rolls))
    with ws_connect(client, p2, code) as w2:
        attack(w2, sword2["id"], tok2, npc, op="tp1", mastery="topple")
        bodies = dice_bodies(drain(w2))
        assert any("Topple" in b and "PRONE" in b for b in bodies)
    assert any(c["k"] == "prone" for c in conds_of(npc))

    monkeypatch.setattr(RD, "do_roll", RD_do_roll0)
    _advance_to(client, dm, code, tok1)
    equip(client, p1, code, ch1["id"], grazer_i)
    monkeypatch.setattr(RD.random, "randint", lambda a, b: 1)       # force a miss
    with ws_connect(client, p1, code) as w1:
        # round 2, p1: Graze turns the miss into flat ability damage (str 10 -> +0;
        # the line itself is the contract, the amount is computed server-side)
        attack(w1, grazer_i, tok1, npc, op="gz1", mastery="graze")
        bodies = dice_bodies(drain(w1))
        assert any("MISS" in b for b in bodies) and any("Graze" in b for b in bodies)
    monkeypatch.setattr(RD.random, "randint", lambda a, b: 20)

    _advance_to(client, dm, code, tok2)
    equip(client, p2, code, ch2["id"], vexer_i)
    with ws_connect(client, p2, code) as w2:
        # round 2, p2: Vex marks the victim after a damaging hit; the marker
        # is TURN-anchored (D109), so the advantage belongs to the rest of
        # THIS turn — p2's bonus attack consumes it and the marker together
        attack(w2, vexer_i, tok2, npc, op="vx1", mastery="vex")
        drain(w2)
        # the vexed marker rides the ATTACKER (self-advantage anchored to the
        # victim via ref — D109 design, mirrors the consume path)
        assert any(c["k"] == "vexed" and c.get("ref") == npc for c in conds_of(tok2))
        attack(w2, vexer_i, tok2, npc, op="adv1", slot="bonus")
        bodies = dice_bodies(drain(w2))
        assert any(" adv" in b for b in bodies)
    assert not any(c["k"] == "vexed" for c in conds_of(tok2))

    _advance_to(client, dm, code, tok1)
    equip(client, p1, code, ch1["id"], cleaver_i)
    with ws_connect(client, p1, code) as w1:
        # round 3: fresh action — p1 swings at the second dummy, no mastery
        attack(w1, cleaver_i, tok1, d2, op="r3")
        bodies = dice_bodies(drain(w1))
        assert any("HIT" in b for b in bodies)

    # the NPC drops to 0 HP and the DM's view reflects it; players never saw
    # the stat block itself
    with ws_connect(client, dm, code) as dws:
        dws.send_json({"type": "hp", "token_id": npc, "delta": -999})
        recv_until(dws, "snapshot")
    assert _npc_hp(npc) == 0

    # ================= D: loot =================
    with ws_connect(client, p1, code) as w1:
        w1.send_json({"type": "loot", "action": "inspect", "token_id": npc})
        got = recv_until(w1, "inv_contents")["payload"]
        assert any(r.get("name") == "Lucky Coin" and r.get("qty") == 3 for r in got["items"])
        coin = next(r for r in got["items"] if r.get("name") == "Lucky Coin")["id"]
        w1.send_json({"type": "loot", "action": "take", "token_id": npc,
                      "char_id": ch1["id"], "item_id": coin, "qty": 2, "op_id": "lt1"})
        recv_until(w1, "inv_changed")
        # replay of the SAME op changes nothing
        w1.send_json({"type": "loot", "action": "take", "token_id": npc,
                      "char_id": ch1["id"], "item_id": coin, "qty": 2, "op_id": "lt1"})
        drain(w1)
    assert _count_items(_sheet(client, p1, code, ch1["id"]), "Lucky Coin") == 2

    _teleport(client, dm, code, tok2, 40, 20)                      # far away
    with ws_connect(client, p2, code) as w2:
        w2.send_json({"type": "loot", "action": "inspect", "token_id": npc})
        ev = recv_until(w2, "error", fail_on_error=False)
        assert ev["kind"] == "error", "loot needs the player at the body"
    _teleport(client, dm, code, tok2, cx - 1, cy)                  # next to the body
    with ws_connect(client, p2, code) as w2:
        w2.send_json({"type": "loot", "action": "inspect", "token_id": npc})
        got = recv_until(w2, "inv_contents")["payload"]
        coin2 = next(r for r in got["items"] if r.get("name") == "Lucky Coin")["id"]
        w2.send_json({"type": "loot", "action": "take", "token_id": npc,
                      "char_id": ch2["id"], "item_id": coin2, "qty": 1, "op_id": "lt2"})
        recv_until(w2, "inv_changed")
        w2.send_json({"type": "loot", "action": "coins_take", "token_id": npc,
                      "char_id": ch2["id"], "amount": 500, "coin": "gp", "op_id": "lt3"})
        recv_until(w2, "inv_changed")
    assert _count_items(_sheet(client, p2, code, ch2["id"]), "Lucky Coin") == 1
    assert _count_items(_sheet(client, p1, code, ch1["id"]), "Lucky Coin") == 2
    with ws_connect(client, p1, code) as w1:
        w1.send_json({"type": "loot", "action": "inspect", "token_id": npc})
        got = recv_until(w1, "inv_contents")["payload"]
        assert not any((r.get("qty") or 0) > 0 for r in got["items"]), "body is empty"
        assert not got["coins"], "coins all taken"

    # ================= E: the cursed coin purse =================
    coin_entry = next(i for i in _sheet(client, p1, code, ch1["id"])["items"]
                      if i["name"] == "Lucky Coin")["id"]
    # set answers with the id of the CURSED instance (an atomic carve-out of
    # the stack — the d106 contract); that id is the handle for disclosure
    set_ev = _curse(client, dm, code, action="set", char_id=ch1["id"], item_id=coin_entry,
                    name=CURSE_NAME, desc="It ticks like a countdown.", whisper=CURSE_WHISPER)
    cursed_id = set_ev["payload"]["item_id"]
    assert CURSE_NAME not in json.dumps(state_of(client, p1, code))
    assert CURSE_WHISPER not in json.dumps(state_of(client, p1, code))

    with ws_connect(client, p1, code) as w1, ws_connect(client, p2, code) as w2:
        _curse(client, dm, code, action="reveal", char_id=ch1["id"], item_id=cursed_id)
        # "whisper" answers with a DM-socket whisper receipt, not curse_updated
        _curse(client, dm, code, expect="whisper", action="whisper",
               char_id=ch1["id"], item_id=cursed_id)
        evs1 = drain(w1)
        got1 = [str(e["payload"].get("text", "")) for e in evs1
                if e.get("kind") == "chat" and e["payload"].get("visibility") == "whisper"]
        assert any(CURSE_NAME in t for t in got1) and any(CURSE_WHISPER in t for t in got1)
        evs2 = drain(w2)
        assert not [e for e in evs2 if CURSE_NAME in json.dumps(e)
                    or CURSE_WHISPER in json.dumps(e)], "no leak to p2"
        sheet1 = json.dumps(_sheet(client, p1, code, ch1["id"]))
    assert CURSE_NAME in sheet1                                    # owner now sees it
    assert CURSE_WHISPER not in sheet1        # the whisper text NEVER rides a sheet

    # ================= F: persistence & replay =================
    snap1, snap2 = _snap(client, p1, code), _snap(client, p2, code)
    msgs_before = len(state_of(client, dm, code)["messages"])

    with ws_connect(client, p1, code) as w1:                       # fresh sockets
        recv_until(w1, "presence")
    assert _snap(client, p1, code) == snap1 and _snap(client, p2, code) == snap2
    assert CURSE_NAME in json.dumps(_sheet(client, p1, code, ch1["id"]))

    # replays across the reconnect change NOTHING
    client.post(f"/api/build/{code}/{ch1['id']}/origin", headers=H(p1),
                json={"asi": {"mode": "three"}})
    assert db.j(db.q1("SELECT stats FROM characters WHERE id=?", (ch1["id"],))["stats"], {}) == st1
    r = _gear(client, p1, code, ch1["id"],
              picks={"weapon": f"sword_versatile_{tag}"}).json()
    assert r.get("already") or r.get("class_status") == "already"
    with ws_connect(client, p1, code) as w1:
        w1.send_json({"type": "roll", "kind": "attack", "item_id": cleaver_i,
                      "token_id": tok1, "target_id": d2, "visibility": "public",
                      "op_id": "r3"})
        evs = drain(w1)
        assert not [e for e in evs if e.get("kind") == "dice"], "replayed op rolls nothing"
    assert len(state_of(client, dm, code)["messages"]) == msgs_before


# ------------------------------------------------------------- guardians

def test_guard_foreign_token_and_condition_control(client):
    dm, player, code, ch = base_room(client)
    from tests.test_d106_curses import _second_player
    u2, ch2 = _second_player(client, code)
    tok2 = token_of(client, u2, code, ch2)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "cond_add", "token_id": tok2, "key": "prone"})
        ev = recv_until(ws, "error", fail_on_error=False)
        assert ev["kind"] == "error" and "your token" in ev["payload"]["msg"]
    with ws_connect(client, dm, code) as dws:
        dws.send_json({"type": "cond_add", "token_id": tok2, "key": "prone"})
        assert recv_until(dws, "cond") is not None


def test_guard_view_as_is_player_view_only(client):
    dm, player, code, ch = base_room(client)
    far = _npc(client, dm, code, cx=40, cy=40, hp=1)
    r = client.get(f"/api/rooms/{code}/view_as/{ch['id']}", headers=H(player))
    assert r.status_code in (403, 404), "view-as is a DM tool"
    pv = view_as(client, dm, code, ch["id"]).json()
    assert far not in {t["id"] for t in pv["tokens"]}
    assert far in {t["id"] for t in state_of(client, dm, code)["tokens"]}


def test_guard_content_isolation_between_rooms(client):
    dm, p1, _p2, code, _tag = _campaign_room(client)
    code2 = client.post("/api/rooms", json={"name": "NoPack"}, headers=H(dm)).json()["code"]
    join_room(client, p1, code2)
    o2 = client.get(f"/api/content/{code2}/options", headers=H(p1)).json()["options"]
    assert not o2.get("class"), "a second room sees NO content of room one"
    o1 = client.get(f"/api/content/{code}/options", headers=H(p1)).json()["options"]
    assert any(c["id"] == "scout" for c in o1.get("class", []))
    outsider = reg(client, "out")
    assert client.get(f"/api/rooms/{code}/state", headers=H(outsider)).status_code == 403


def test_guard_whisper_history_never_reaches_uninvited(client):
    dm, player, code, ch = base_room(client)
    from tests.test_d106_curses import _second_player
    u2, _ch2 = _second_player(client, code)
    st = state_of(client, dm, code)
    p1_member = next(m["user_id"] for m in st["members"]
                     if m.get("character_id") == ch["id"])   # the PLAYER, not the DM
    with ws_connect(client, dm, code) as dws:
        dws.send_json({"type": "chat", "text": SECRET, "channel": "whisper",
                       "recipient_id": p1_member})
        recv_until(dws, "chat")
    with ws_connect(client, u2, code) as w2:
        assert not any(SECRET in json.dumps(e) for e in drain(w2))
    assert SECRET not in json.dumps(state_of(client, u2, code))
    assert SECRET in json.dumps(state_of(client, dm, code))
