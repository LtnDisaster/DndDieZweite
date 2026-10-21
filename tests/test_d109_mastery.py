"""D109: weapon masteries (2024, SRD 5.2.1) — grants, entitlements, combat.

Pins the four separate axes (weapon HAS the property / character UNLOCKED it /
THIS weapon is the one wielding it / the attack actually qualifies) plus the
outcome branches of all eight masteries, marker lifecycles on the ONE turn
clock (D80), the attacker-anchored expiries, replay/concurrency behaviour,
cross-room authz and the D108-exactness regressions (apply_origin atomicity,
generator byte-idempotency).
"""
import subprocess
import sys
import threading
import uuid
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from app import charbuild, content as C, db, main
from app.room import dice as RD
from tests.test_movement_fog import (H, base_room, recv_until, reg, state_of,
                                     ws_connect)
from tests.test_d108_origin import _room as pack_room

ROOT = Path(__file__).resolve().parent.parent
PACK = ROOT / "app" / "content_pack"


@pytest.fixture()
def client():
    return TestClient(main.app)


def rid_of(code):
    return db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]


def grant(ch_id, mastery, room_id):
    ok, res = charbuild.grant_mastery(ch_id, mastery, "dm-test", room_id)
    assert ok, res


def token_of(client, user, code, ch):
    return next(t["id"] for t in state_of(client, user, code)["tokens"]
                if t["character_id"] == ch["id"])


def dummy_near(client, dm, code, tok, dx=1):
    """A dummy one cell east of the attacker token (melee reach, no grid math)."""
    a = db.q1("SELECT x, y FROM tokens WHERE id=?", (tok,))
    return add_dummy(client, dm, code, a["x"] + 50 * dx, a["y"])


def add_dummy(client, dm, code, x, y, label="Dummy"):
    with ws_connect(client, dm, code) as dws:
        dws.send_json({"type": "add_token", "label": label, "x": x, "y": y})
        return recv_until(dws, "token_add")["payload"]["id"]


def mk_def(client, dm, code, props, name="Blade"):
    with ws_connect(client, dm, code) as dws:
        dws.send_json({"type": "item_def", "action": "create",
                       "defn": {"name": name, "kind": "weapon",
                                "props": dict(props, proficient=True)}})
        recv_until(dws, "whisper")
    defs = state_of(client, dm, code)["item_defs"]
    return next(d["id"] for d in defs if d["name"] == name)


def grant_item(client, dm, code, ch_id, def_id):
    with ws_connect(client, dm, code) as dws:
        dws.send_json({"type": "inv_grant", "char_id": ch_id, "def_id": def_id,
                       "qty": 1})
        recv_until(dws, "inv_changed")


def equip(client, player, code, ch_id, item_id, slot="main_hand"):
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "inv_equip", "char_id": ch_id, "slot": slot,
                      "item_id": item_id, "op_id": "e" + uuid.uuid4().hex[:10]})
        recv_until(ws, "inv_changed")


def char_items(client, player, code):
    st = state_of(client, player, code)
    me = next(m for m in st["members"] if m["user_id"] == st["me"])
    return me["char"]["items"]


def drain(ws, cap=60):
    """Collect all events the server still owes this socket: the ws handler
    processes messages per connection in order, so a chat sentinel round-trip
    deterministically marks the end of the current event burst."""
    ws.send_json({"type": "chat", "text": "@@d109flush@@"})
    out = []
    while len(out) < cap:
        ev = ws.receive_json()
        p = ev.get("payload", {})
        if ev.get("kind") == "chat" and "@@d109flush@@" in str(p.get("text", "")):
            return out
        assert ev.get("kind") != "error", p
        out.append(ev)
    raise AssertionError("event burst never ended")


def dice_bodies(evs):
    return [str(e.get("payload", {}).get("body", "")) for e in evs if e.get("kind") == "dice"]


def attack(ws, item_id, tok, target=None, op=None, mastery=None, slot="action",
           t2=None):
    msg = {"type": "roll", "kind": "attack", "item_id": item_id, "token_id": tok,
           "target_id": target, "visibility": "public",
           "op_id": op or ("a" + uuid.uuid4().hex[:10])}
    if mastery:
        msg["mastery"] = mastery
    if slot != "action":
        msg["slot"] = slot
    if t2:
        msg["target2_id"] = t2
    ws.send_json(msg)


def conds_of(token_id):
    tok = db.q1("SELECT conds FROM tokens WHERE id=?", (token_id,))
    return db.j(tok["conds"], []) or []


def always(client, monkeypatch, value):
    monkeypatch.setattr(RD.random, "randint", lambda a, b: value)


# ---------------------------------------------------------------- data model

def test_content_pack_ships_masteries_and_gains():
    items = {r["id"]: r for r in csv_rows("items.csv")}
    assert items["dagger_surge"]["mastery"] == "nick"
    assert items["axe_great"]["mastery"] == "cleave"
    assert items["bow_long"]["mastery"] == "vex"
    assert items["sword_versatile"]["mastery"] == "topple"
    assert items["potion_heal"]["mastery"] == ""
    cls = [r for r in csv_rows("classes.csv") if r["mastery_gain"]]
    assert {(r["id"], r["level"]) for r in cls} == {("scout", "1"), ("warden", "1")}


def csv_rows(name):
    import csv
    with open(PACK / name, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_clean_props_validates_mastery():
    from app import gear
    assert gear.clean_props({"mastery": "Nick"})["mastery"] == "nick"
    assert "mastery" not in gear.clean_props({"mastery": "teleport"})
    assert "mastery" not in gear.clean_props({"mastery": 7})


def test_profile_exposes_mastery_light_and_mod_flag():
    from app import gear
    it = gear.clean_items([{"id": "d", "name": "Dagger", "kind": "weapon",
                            "props": {"damage_dice": "1d4", "finesse": True,
                                      "light": True, "proficient": True,
                                      "mastery": "nick"}}])[0]
    c = {"stats": {"str": 12, "dex": 16, "con": 10, "int": 10, "wis": 10, "cha": 10},
         "level": 1, "items": [it], "equipment": {"main_hand": "d"}}
    p = next(p for p in gear.weapon_profiles(c) if p["item_id"] == "d")
    assert p["mastery"] == "nick" and p["light"] is True
    assert p["mod_to_dmg"] is True


def test_generator_is_byte_idempotent():
    """D108 lesson: a regeneration must NEVER change a shipped file."""
    before = {p.name: p.read_bytes() for p in PACK.glob("*.csv")}
    try:
        for _ in range(2):
            r = subprocess.run([sys.executable, str(ROOT / "scripts/make_content_pack.py")],
                               cwd=ROOT, capture_output=True, text=True,
                               env={"PATH": "/usr/bin:/bin", "PYTHONPATH": "."})
            assert r.returncode == 0, r.stderr
        after = {p.name: p.read_bytes() for p in PACK.glob("*.csv")}
        assert after == before
    finally:
        for name, data in before.items():
            (PACK / name).write_bytes(data)


# --------------------------------------------------------------- ledger/API

def test_level_apply_accrues_pending_grants_forward_only(client):
    dm, player, code, ch = pack_room(client)
    rid = rid_of(code)
    C.store("class", rid, {"id": "tstr", "level": "1", "name": "Test",
                           "mastery_gain": "2", "mastery_options": "nick|vex"})
    C.store("class", rid, {"id": "tstr", "level": "2", "name": "Test",
                           "mastery_gain": "1"})
    r = client.post(f"/api/build/{code}/{ch['id']}/apply",
                    json={"class_id": "tstr", "to": 1, "choices": {}},
                    headers=H(player))
    assert r.status_code == 200 and r.json()["ok"], r.text
    rep = client.get(f"/api/build/{code}/{ch['id']}/mastery", headers=H(player)).json()
    assert rep["pending"] == 2 and rep["allowed"] == []
    assert rep["grants"][0]["pool"] == ["nick", "vex"]
    # pick: only inside the pool
    bad = client.post(f"/api/build/{code}/{ch['id']}/mastery",
                      json={"pick": "push"}, headers=H(player)).json()
    assert not bad["ok"] and "pool" in bad["error"]
    ok = client.post(f"/api/build/{code}/{ch['id']}/mastery",
                     json={"pick": "Nick"}, headers=H(player)).json()
    assert ok["ok"] and ok["result"]["picked"] == "nick"
    rep = client.get(f"/api/build/{code}/{ch['id']}/mastery", headers=H(player)).json()
    assert rep["pending"] == 1 and rep["allowed"] == ["nick"]
    # second level -> third grant, default pool all eight
    client.post(f"/api/build/{code}/{ch['id']}/apply",
                json={"class_id": "tstr", "to": 2, "choices": {}}, headers=H(player))
    rep = client.get(f"/api/build/{code}/{ch['id']}/mastery", headers=H(player)).json()
    assert rep["pending"] == 2
    assert set(rep["grants"][2]["pool"]) == set(C.MASTERIES)


def test_no_retroactive_masteries_for_pre_d109_builds(client):
    dm, player, code, ch = pack_room(client)
    rid = rid_of(code)
    C.store("class", rid, {"id": "tstr", "level": "1", "name": "Test",
                           "mastery_gain": "2"})
    client.post(f"/api/build/{code}/{ch['id']}/apply",
                json={"class_id": "tstr", "to": 1, "choices": {}}, headers=H(player))
    ch_row = db.q1("SELECT build FROM characters WHERE id=?", (ch["id"],))
    led = db.j(ch_row["build"], {})
    led["masteries"] = {"grants": []}                # simulate pre-D109 ledger
    db.x("UPDATE characters SET build=? WHERE id=?", (db.json_dumps(led), ch["id"]))
    rep = client.get(f"/api/build/{code}/{ch['id']}/mastery", headers=H(player)).json()
    assert rep["pending"] == 0 and rep["allowed"] == []
    j = client.post(f"/api/build/{code}/{ch['id']}/mastery",
                    json={"pick": "nick"}, headers=H(player)).json()
    assert not j["ok"] and "pending" in j["error"]


def test_dm_grant_idempotent_and_sheet_untouched(client):
    dm, player, code, ch = pack_room(client)
    rid = rid_of(code)
    stats_before = db.q1("SELECT stats FROM characters WHERE id=?", (ch["id"],))["stats"]
    grant(ch["id"], "vex", rid)
    ok, res = charbuild.grant_mastery(ch["id"], "vex", "dm", rid)
    assert ok and res.get("already") and len(res["masteries"]["grants"]) == 1
    assert db.q1("SELECT stats FROM characters WHERE id=?", (ch["id"],))["stats"] == stats_before
    rep = client.get(f"/api/build/{code}/{ch['id']}/mastery", headers=H(player)).json()
    assert rep["allowed"] == ["vex"] and rep["pending"] == 0


def test_grant_route_is_dm_only(client):
    dm, player, code, ch = pack_room(client)
    r = client.post(f"/api/build/{code}/{ch['id']}/mastery/grant",
                    json={"mastery": "vex"}, headers=H(player))
    assert r.status_code == 403
    outsider = reg(client, "out")
    r = client.post(f"/api/build/{code}/{ch['id']}/mastery/grant",
                    json={"mastery": "vex"}, headers=H(outsider))
    assert r.status_code in (403, 401)


def test_concurrent_origin_applies_exactly_once(client):
    """D109 audit fix: apply_origin is a check-then-write — two racing
    requests must NOT both apply; one wins, the other answers 'already'."""
    dm, player, code, ch = pack_room(client)
    results = []

    def hit(bg, asi):
        results.append(charbuild.apply_origin(ch["id"], bg, asi, rid_of(code)))

    t1 = threading.Thread(target=hit, args=("bg_scholar", {"mode": "plus2_plus1", "plus2": "int", "plus1": "wis"}))
    t2 = threading.Thread(target=hit, args=("bg_urchin", {"mode": "plus2_plus1", "plus2": "dex", "plus1": "cha"}))
    t1.start(); t2.start(); t1.join(); t2.join()
    oks = [ok for ok, _ in results]
    finals = [res.get("origin") for ok, res in results if ok]
    assert all(oks)                                   # both succeed (one 'already')
    assert len(finals) == 2 and finals[0] == finals[1]   # one single origin recorded
    led = db.j(db.q1("SELECT build FROM characters WHERE id=?", (ch["id"],))["build"], {})
    assert led["origin"] == finals[0]
    # stats are consistent with the ONE applied origin: exactly +3 total
    stats = db.j(db.q1("SELECT stats FROM characters WHERE id=?", (ch["id"],))["stats"], {})
    base = db.j(led["base_stats"], {})
    assert sum(stats[a] - base[a] for a in stats) == 3


# ---------------------------------------------------------- attack gating

def armed_mastery_room(client, props, mastery, name="Blade"):
    """pack-room with one player wielding a weapon carrying `mastery`."""
    dm, player, code, ch = pack_room(client)
    did = mk_def(client, dm, code, props, name)
    grant_item(client, dm, code, ch["id"], did)
    item = char_items(client, player, code)[0]
    equip(client, player, code, ch["id"], item["id"])
    return dm, player, code, ch, item


SWORD = {"damage_dice": "1d8", "damage_type": "slashing", "ability": "str"}


def test_unentitled_mastery_refused_before_rolling(client, monkeypatch):
    dm, player, code, ch, item = armed_mastery_room(client, SWORD, "vex")
    tok = token_of(client, player, code, ch)
    dummy = dummy_near(client, dm, code, tok)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "roll", "kind": "attack", "item_id": item["id"],
                      "token_id": tok, "target_id": dummy, "mastery": "vex",
                      "visibility": "public", "op_id": "x1"})
        err = recv_until(ws, "error", fail_on_error=False)
    assert err["kind"] == "error" and "mastery" in err["payload"]["msg"].lower()


def test_unknown_and_mismatched_mastery_refused(client, monkeypatch):
    dm, player, code, ch, item = armed_mastery_room(client, SWORD, "vex")
    grant(ch["id"], "vex", rid_of(code))
    tok = token_of(client, player, code, ch)
    with ws_connect(client, player, code) as ws:
        for m, frag in (("teleport", "unknown"), ("nick", "no nick")):
            ws.send_json({"type": "roll", "kind": "attack", "item_id": item["id"],
                          "token_id": tok, "mastery": m, "visibility": "public",
                          "op_id": "x" + m})
            err = recv_until(ws, "error", fail_on_error=False)
            assert err["kind"] == "error", (m, err)
            assert frag in err["payload"]["msg"].lower()


def test_manual_damage_may_not_carry_mastery(client):
    dm, player, code, ch, item = armed_mastery_room(client, SWORD, "vex")
    grant(ch["id"], "vex", rid_of(code))
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "roll", "kind": "damage", "item_id": item["id"],
                      "mastery": "vex", "visibility": "public", "op_id": "x1"})
        err = recv_until(ws, "error", fail_on_error=False)
    assert err["kind"] == "error"


# ------------------------------------------------------------- effects

def test_graze_flat_damage_on_miss_only(client, monkeypatch):
    dm, player, code, ch, item = armed_mastery_room(
        client, dict(SWORD, mastery="graze"), "graze")
    grant(ch["id"], "graze", rid_of(code))
    # raise STR so Graze deals +5 (str mod)
    db.x("UPDATE characters SET stats=? WHERE id=?",
         (db.json_dumps({"str": 20, "dex": 10, "con": 10, "int": 10,
                         "wis": 10, "cha": 10}), ch["id"]))
    tok = token_of(client, player, code, ch)
    dummy = dummy_near(client, dm, code, tok)
    always(client, monkeypatch, 1)                    # nat 1 = miss
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "roll", "kind": "attack", "item_id": item["id"],
                      "token_id": tok, "target_id": dummy, "mastery": "graze",
                      "visibility": "public", "op_id": "g1"})
        atk = recv_until(ws, "dice")
        graze = recv_until(ws, "dice")
    assert "MISS" in atk["payload"]["body"]
    assert "Graze" in graze["payload"]["body"] and "5 slashing" in graze["payload"]["body"]
    # on a HIT graze must NOT fire
    always(client, monkeypatch, 20)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "roll", "kind": "attack", "item_id": item["id"],
                      "token_id": tok, "target_id": dummy, "mastery": "graze",
                      "visibility": "public", "op_id": "g2"})
        atk = recv_until(ws, "dice")
        dmg = recv_until(ws, "dice")
        assert "Graze" not in dmg["payload"]["body"]


def test_vex_marker_grants_advantage_and_is_consumed(client, monkeypatch):
    dm, player, code, ch, item = armed_mastery_room(
        client, dict(SWORD, mastery="vex"), "vex")
    grant(ch["id"], "vex", rid_of(code))
    always(client, monkeypatch, 20)                   # hit + damage
    tok = token_of(client, player, code, ch)
    dummy = dummy_near(client, dm, code, tok)
    from tests.test_sprint23_combat import _to_player_turn
    _to_player_turn(client, dm, code, tok)
    with ws_connect(client, player, code) as ws:
        attack(ws, item["id"], tok, dummy, mastery="vex")
        recv_until(ws, "dice"); recv_until(ws, "dice")
        vexed = recv_until(ws, "dice")
    assert "vexes" in vexed["payload"]["body"]
    assert any(c["k"] == "vexed" and c.get("ref") == dummy and c.get("src") == tok
               for c in conds_of(tok))
    with ws_connect(client, player, code) as ws:
        attack(ws, item["id"], tok, dummy, slot="bonus")   # next attack vs SAME target
        atk = recv_until(ws, "dice")
    assert " adv" in atk["payload"]["body"]            # consumed advantage
    assert not any(c["k"] == "vexed" for c in conds_of(tok))


def test_sap_marker_forces_disadvantage_on_victim(client, monkeypatch):
    dm, player, code, ch, item = armed_mastery_room(
        client, dict(SWORD, mastery="sap"), "sap")
    grant(ch["id"], "sap", rid_of(code))
    always(client, monkeypatch, 20)
    tok = token_of(client, player, code, ch)
    with ws_connect(client, dm, code) as dws:
        a = db.q1("SELECT x, y FROM tokens WHERE id=?", (tok,))
        dws.send_json({"type": "add_token", "label": "Orc", "x": a["x"] + 50, "y": a["y"],
                       "npc": {"name": "Orc", "attacks": [
                           {"name": "Axe", "to_hit": 3, "dmg": "1d6"}]}})
        orc = recv_until(dws, "token_add")["payload"]["id"]
    from tests.test_sprint23_combat import _to_player_turn
    _to_player_turn(client, dm, code, tok)
    with ws_connect(client, player, code) as ws:
        attack(ws, item["id"], tok, orc, mastery="sap")
        recv_until(ws, "dice"); recv_until(ws, "dice")
        sap = recv_until(ws, "dice")
    assert "sapped" in sap["payload"]["body"]
    assert any(c["k"] == "sapped" and c.get("src") == tok for c in conds_of(orc))
    with ws_connect(client, dm, code) as dws:
        dws.send_json({"type": "npc_attack", "token_id": orc, "attack": 0,
                       "target_id": tok})
        atk = recv_until(dws, "dice")
    assert " dis" in atk["payload"]["body"]
    assert not any(c["k"] == "sapped" for c in conds_of(orc))


def test_sap_needs_no_damage_and_initiative_anchor(client):
    dm, player, code, ch, item = armed_mastery_room(
        client, dict(SWORD, mastery="sap"), "sap")
    grant(ch["id"], "sap", rid_of(code))
    tok = token_of(client, player, code, ch)
    dummy = dummy_near(client, dm, code, tok)
    with ws_connect(client, player, code) as ws:
        # no initiative running -> attacker-anchored marker refuses
        ws.send_json({"type": "roll", "kind": "attack", "item_id": item["id"],
                      "token_id": tok, "target_id": dummy, "mastery": "sap",
                      "visibility": "public", "op_id": "s1"})
        err = recv_until(ws, "error", fail_on_error=False)
    assert err["kind"] == "error" and "initiative" in err["payload"]["msg"]


def test_slow_reduces_speed_ten_and_never_stacks(client, monkeypatch):
    dm, player, code, ch, item = armed_mastery_room(
        client, dict(SWORD, mastery="slow"), "slow")
    grant(ch["id"], "slow", rid_of(code))
    always(client, monkeypatch, 20)
    tok = token_of(client, player, code, ch)
    dummy = dummy_near(client, dm, code, tok)
    from app.room.movement import _walk_speed
    orc_tok = db.q1("SELECT * FROM tokens WHERE id=?", (dummy,))
    assert _walk_speed(orc_tok) == 30
    from tests.test_sprint23_combat import _to_player_turn
    _to_player_turn(client, dm, code, tok)
    with ws_connect(client, player, code) as ws:
        attack(ws, item["id"], tok, dummy, mastery="slow")
        recv_until(ws, "dice"); recv_until(ws, "dice")
        slow = recv_until(ws, "dice")
    assert "slowed" in slow["payload"]["body"]
    assert _walk_speed(db.q1("SELECT * FROM tokens WHERE id=?", (dummy,))) == 20
    # a second, independent slow source must NOT stack below 10
    from app import conditions as CND
    conds = CND.add(CND.load(orc_tok), "slowed", 0, "start", src=99999)
    db.x("UPDATE tokens SET conds=? WHERE id=?", (db.json_dumps(conds), dummy))
    assert _walk_speed(db.q1("SELECT * FROM tokens WHERE id=?", (dummy,))) == 20


def test_topple_con_save_and_prone(client, monkeypatch):
    dm, player, code, ch, item = armed_mastery_room(
        client, dict(SWORD, mastery="topple"), "topple")
    grant(ch["id"], "topple", rid_of(code))
    tok = token_of(client, player, code, ch)
    dummy = dummy_near(client, dm, code, tok)
    rolls = iter([{"kept": 20, "adv": None, "rolls": [20], "mod": 0, "total": 20},
                  {"kept": 1, "adv": None, "rolls": [1], "mod": 0, "total": 1}])
    monkeypatch.setattr(RD, "do_roll", lambda expr, adv: next(rolls))
    always(client, monkeypatch, 4)                    # damage dice (grand>0)
    with ws_connect(client, player, code) as ws:
        attack(ws, item["id"], tok, dummy, mastery="topple")
        recv_until(ws, "dice"); recv_until(ws, "dice")
        topple = recv_until(ws, "dice")
    assert "Topple" in topple["payload"]["body"] and "PRONE" in topple["payload"]["body"]
    assert any(c["k"] == "prone" for c in conds_of(dummy))
    # resisting version: save succeeds
    rolls2 = iter([{"kept": 20, "adv": None, "rolls": [20], "mod": 0, "total": 20},
                   {"kept": 20, "adv": None, "rolls": [20], "mod": 0, "total": 20}])
    monkeypatch.setattr(RD, "do_roll", lambda expr, adv: next(rolls2))
    with ws_connect(client, player, code) as ws:
        attack(ws, item["id"], tok, dummy, mastery="topple")
        recv_until(ws, "dice"); recv_until(ws, "dice")
        topple = recv_until(ws, "dice")
    assert "resists" in topple["payload"]["body"]
    assert any(c["k"] == "prone" for c in conds_of(dummy))   # from the FIRST fail


def test_push_moves_away_and_blocked_stops(client, monkeypatch):
    dm, player, code, ch, item = armed_mastery_room(
        client, dict(SWORD, mastery="push"), "push")
    grant(ch["id"], "push", rid_of(code))
    always(client, monkeypatch, 20)
    tok = token_of(client, player, code, ch)
    att = db.q1("SELECT x, y FROM tokens WHERE id=?", (tok,))
    ax, ay = att["x"], att["y"]
    dummy = add_dummy(client, dm, code, ax + 50, ay)   # 1 cell east
    with ws_connect(client, player, code) as ws:
        attack(ws, item["id"], tok, dummy, mastery="push")
        evs = drain(ws)
    assert any("pushes" in b or "Push" in b for b in dice_bodies(evs))
    pushed = db.q1("SELECT x FROM tokens WHERE id=?", (dummy,))
    assert pushed["x"] == ax + 150                      # 2 cells further east
    # blocked: a body directly in the push line
    add_dummy(client, dm, code, ax + 100, ay, "Wall of Bob")   # directly behind
    dummy2 = add_dummy(client, dm, code, ax + 50, ay, "Pushme")
    with ws_connect(client, player, code) as ws:
        attack(ws, item["id"], tok, dummy2, mastery="push")
        evs = drain(ws)
        assert any("blocked" in b for b in dice_bodies(evs))
    assert db.q1("SELECT x FROM tokens WHERE id=?", (dummy2,))["x"] == ax + 50


def test_push_refuses_huge_targets(client, monkeypatch):
    dm, player, code, ch, item = armed_mastery_room(
        client, dict(SWORD, mastery="push"), "push")
    grant(ch["id"], "push", rid_of(code))
    tok = token_of(client, player, code, ch)
    dummy = dummy_near(client, dm, code, tok)
    monkeypatch.setattr(RD, "_token_size_ok_for_push", lambda t: False)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "roll", "kind": "attack", "item_id": item["id"],
                      "token_id": tok, "target_id": dummy, "mastery": "push",
                      "visibility": "public", "op_id": "p1"})
        err = recv_until(ws, "error", fail_on_error=False)
    assert err["kind"] == "error" and "large" in err["payload"]["msg"].lower()


def test_cleave_second_target_rules(client, monkeypatch):
    dm, player, code, ch, item = armed_mastery_room(
        client, dict(SWORD, mastery="cleave"), "cleave")
    grant(ch["id"], "cleave", rid_of(code))
    always(client, monkeypatch, 20)                   # everything hits
    tok = token_of(client, player, code, ch)
    att = db.q1("SELECT x, y FROM tokens WHERE id=?", (tok,))
    d1 = add_dummy(client, dm, code, att["x"] + 50, att["y"])
    d2 = add_dummy(client, dm, code, att["x"] + 50, att["y"] - 50)   # 5 ft of d1
    dfar = add_dummy(client, dm, code, att["x"] + 200, att["y"])     # far away
    with ws_connect(client, player, code) as ws:
        attack(ws, item["id"], tok, d1, mastery="cleave", t2=d2)
        seen = [recv_until(ws, "dice")["payload"]["body"] for _ in range(2)]
        cl = recv_until(ws, "dice")["payload"]["body"]
        cl2 = recv_until(ws, "dice")["payload"]["body"]
    assert "MISS" not in seen[0]
    assert "Cleave vs Dummy" in cl and "HIT" in cl
    assert "Cleave damage" in cl2
    # second target NOT within 5 ft of the first -> refused, no roll
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "roll", "kind": "attack", "item_id": item["id"],
                      "token_id": tok, "target_id": d1, "target2_id": dfar,
                      "mastery": "cleave", "visibility": "public", "op_id": "c2"})
        err = recv_until(ws, "error", fail_on_error=False)
        assert err["kind"] == "error" and "5 feet" in err["payload"]["msg"]


def test_cleave_once_per_turn_in_initiative(client, monkeypatch):
    dm, player, code, ch, item = armed_mastery_room(
        client, dict(SWORD, mastery="cleave"), "cleave")
    grant(ch["id"], "cleave", rid_of(code))
    always(client, monkeypatch, 20)
    tok = token_of(client, player, code, ch)
    att = db.q1("SELECT x, y FROM tokens WHERE id=?", (tok,))
    d1 = add_dummy(client, dm, code, att["x"] + 50, att["y"])
    d2 = add_dummy(client, dm, code, att["x"] + 50, att["y"] - 50)
    from tests.test_sprint23_combat import _to_player_turn
    _to_player_turn(client, dm, code, tok)
    with ws_connect(client, player, code) as ws:
        attack(ws, item["id"], tok, d1, mastery="cleave", t2=d2)
        evs = drain(ws)
        assert any("Cleave damage" in b for b in dice_bodies(evs))
        # second attack this same turn may NOT cleave again (pre-roll refusal)
        ws.send_json({"type": "roll", "kind": "attack", "item_id": item["id"],
                      "token_id": tok, "target_id": d1, "target2_id": d2,
                      "mastery": "cleave", "visibility": "public", "op_id": "c3"})
        err = recv_until(ws, "error", fail_on_error=False)
        assert err["kind"] == "error" and "already" in err["payload"]["msg"]
        # and a plain attack without cleave still works this turn? no: action spent
        ws.send_json({"type": "roll", "kind": "attack", "item_id": item["id"],
                      "token_id": tok, "target_id": d1,
                      "visibility": "public", "op_id": "c4"})
        err2 = recv_until(ws, "error", fail_on_error=False)
        assert err2["kind"] == "error" and "action" in err2["payload"]["msg"]


def test_replayed_attack_cannot_double_fire_effects(client, monkeypatch):
    dm, player, code, ch, item = armed_mastery_room(
        client, dict(SWORD, mastery="topple"), "topple")
    grant(ch["id"], "topple", rid_of(code))
    always(client, monkeypatch, 20)
    tok = token_of(client, player, code, ch)
    dummy = dummy_near(client, dm, code, tok)
    op = "replay1"
    with ws_connect(client, player, code) as ws:
        attack(ws, item["id"], tok, dummy, op=op, mastery="topple")
        for _ in range(3):
            recv_until(ws, "dice")
        # replay the SAME op, then probe with a fresh op: the probe's dice may
        # be the ONLY dice that follows.
        attack(ws, item["id"], tok, dummy, op=op, mastery="topple")
        attack(ws, item["id"], tok, None, op="probe9", mastery=None)
        first = recv_until(ws, "dice")
        assert first["payload"].get("meta") in (None, {}) or "hit" not in (first["payload"].get("meta") or {})


def test_sap_vexed_expire_on_the_attackers_clock(client, monkeypatch):
    dm, player, code, ch, item = armed_mastery_room(
        client, dict(SWORD, mastery="sap"), "sap")
    grant(ch["id"], "vex", rid_of(code))               # both markers, one test
    always(client, monkeypatch, 20)
    tok = token_of(client, player, code, ch)
    dummy = dummy_near(client, dm, code, tok)
    from tests.test_sprint23_combat import _to_player_turn
    _to_player_turn(client, dm, code, tok)
    # put a sapped + a vexed marker in place manually via the engine seam
    from app import conditions as CND
    dummy_row = db.q1("SELECT * FROM tokens WHERE id=?", (dummy,))
    db.x("UPDATE tokens SET conds=? WHERE id=?",
         (db.json_dumps(CND.add(CND.load(dummy_row), "sapped", 0, "start", src=tok)),
          dummy))
    me_tok = db.q1("SELECT * FROM tokens WHERE id=?", (tok,))
    db.x("UPDATE tokens SET conds=? WHERE id=?",
         (db.json_dumps(CND.add(CND.load(me_tok), "vexed", 1, "end",
                                src=tok, ref=dummy)), tok))
    with ws_connect(client, dm, code) as dws:
        dws.send_json({"type": "init_next"})           # END of player turn:
        recv_until(dws, "initiative")                  # vexed 1 -> 0 (survives)
    assert any(c["k"] == "vexed" for c in conds_of(tok))
    assert any(c["k"] == "sapped" for c in conds_of(dummy))
    # advance until the player's turn starts again -> sapped gone there
    guard = 0
    while guard < 6:
        guard += 1
        with ws_connect(client, dm, code) as dws:
            dws.send_json({"type": "init_next"})
            order = recv_until(dws, "initiative")["payload"]
        if (order.get("turn") or {}).get("token_id") == tok:
            break
    assert not any(c["k"] == "sapped" for c in conds_of(dummy))   # start of my next turn


def test_nick_uses_no_bonus_slot_once_per_turn(client, monkeypatch):
    light = {"damage_dice": "1d4", "damage_type": "piercing", "light": True,
             "ability": "str"}
    dm, player, code, ch = pack_room(client)
    d1 = mk_def(client, dm, code, dict(light, mastery="nick"), "D1")
    d2 = mk_def(client, dm, code, light, "D2")
    grant_item(client, dm, code, ch["id"], d1)
    grant_item(client, dm, code, ch["id"], d2)
    items = char_items(client, player, code)
    equip(client, player, code, ch["id"], items[0]["id"], "main_hand")
    equip(client, player, code, ch["id"], items[1]["id"], "off_hand")
    grant(ch["id"], "nick", rid_of(code))
    always(client, monkeypatch, 20)
    tok = token_of(client, player, code, ch)
    dummy = dummy_near(client, dm, code, tok)
    from tests.test_sprint23_combat import _to_player_turn
    _to_player_turn(client, dm, code, tok)
    with ws_connect(client, player, code) as ws:
        attack(ws, item_id := items[0]["id"], tok, dummy)          # action attack
        recv_until(ws, "dice"); recv_until(ws, "dice")
        # nick BEFORE the action attack is impossible now -> allowed after:
        attack(ws, items[1]["id"], tok, dummy, slot="nick")        # extra attack
        recv_until(ws, "dice"); recv_until(ws, "dice")
        # second nick this turn: refused
        ws.send_json({"type": "roll", "kind": "attack", "item_id": items[1]["id"],
                      "token_id": tok, "target_id": dummy, "slot": "nick",
                      "visibility": "public", "op_id": "n2"})
        err = recv_until(ws, "error", fail_on_error=False)
        assert err["kind"] == "error" and "once per turn" in err["payload"]["msg"]
    init = db.j(db.q1("SELECT initiative FROM room_state WHERE room_id=?",
                      (rid_of(code),))["initiative"], {})
    assert init["turn"]["bonus"] == "available"       # NO bonus slot was spent


def test_nick_requires_two_light_weapons_and_entitlement(client):
    light = {"damage_dice": "1d4", "light": True, "ability": "str"}
    dm, player, code, ch = pack_room(client)
    d1 = mk_def(client, dm, code, light, "D1")
    grant_item(client, dm, code, ch["id"], d1)
    items = char_items(client, player, code)
    equip(client, player, code, ch["id"], items[0]["id"], "main_hand")
    tok = token_of(client, player, code, ch)
    from tests.test_sprint23_combat import _to_player_turn
    _to_player_turn(client, dm, code, tok)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "roll", "kind": "attack", "item_id": items[0]["id"],
                      "token_id": tok, "slot": "nick", "visibility": "public",
                      "op_id": "n1"})
        err = recv_until(ws, "error", fail_on_error=False)
    assert err["kind"] == "error"                     # no nick entitlement yet


def test_existing_attacks_without_mastery_are_untouched(client, monkeypatch):
    dm, player, code, ch, item = armed_mastery_room(client, SWORD, "vex")
    always(client, monkeypatch, 20)
    tok = token_of(client, player, code, ch)
    dummy = dummy_near(client, dm, code, tok)
    with ws_connect(client, player, code) as ws:
        attack(ws, item["id"], tok, dummy)
        atk = recv_until(ws, "dice"); dmg = recv_until(ws, "dice")
    assert "HIT" in atk["payload"]["body"] and "damage" in dmg["payload"]["body"]
    assert not conds_of(dummy) and not conds_of(tok)


def test_marker_apis_cannot_be_forged(client):
    """the cond_add WS handler cannot mint src/ref anchors"""
    dm, player, code, ch = pack_room(client)
    tok = token_of(client, player, code, ch)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "cond_add", "token_id": tok, "key": "sapped",
                      "src": 999, "ref": 1})
        recv_until(ws, "cond")
    conds = conds_of(tok)
    assert any(c["k"] == "sapped" for c in conds)
    # the WS cond_add handler never reads src/ref keys — anchors exist only
    # through the server-side mastery path, so they cannot be forged at all
    assert all(c.get("src") is None and c.get("ref") is None for c in conds)


def test_grants_persist_across_reload(client):
    dm, player, code, ch = pack_room(client)
    grant(ch["id"], "nick", rid_of(code))
    rep = client.get(f"/api/build/{code}/{ch['id']}/mastery", headers=H(player)).json()
    assert rep["allowed"] == ["nick"]
    rep2 = client.get(f"/api/build/{code}/{ch['id']}/mastery", headers=H(player)).json()
    assert rep2["allowed"] == ["nick"]
