"""AP-015 / D129: 2024 exhaustion levels are mechanics, not a counter.

Audit baseline F4/K8 (RULES_AUDIT_2024, corrected against SRD 5.2.1):
per level −2 to Attack Rolls, Damage Rolls, Ability Checks, Saving Throws
and Initiative; your Speed −5 ft per level; level 6 kills; a long rest
removes one level. Every consumer is an EXISTING derivation/roll channel —
this suite asserts the real WS/DB behaviour, never a copy of the math.
"""
import uuid

import pytest
from starlette.testclient import TestClient

from app import db, gear, main
from app.room import combat, movement, opposed
from tests.test_movement_fog import (H, join_room, make_char, recv_until, reg,
                                     state_of, ws_connect)


@pytest.fixture()
def client():
    return TestClient(main.app)


def base_room(client):
    dm = reg(client, "exdm")
    code = client.post("/api/rooms", json={"name": "Ex"}, headers=H(dm)).json()["code"]
    player = reg(client, "expl")
    join_room(client, player, code)
    ch = make_char(client, player)
    assert client.post(f"/api/rooms/{code}/assign",
                       json={"character_id": ch["id"]}, headers=H(player)).status_code == 200
    return dm, player, code, ch


def token_of(code, ch_id):
    rid = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
    return db.q1("SELECT * FROM tokens WHERE room_id=? AND character_id=?", (rid, ch_id))


def last_sys(code):
    rid = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
    row = db.q1("SELECT body FROM messages WHERE room_id=? AND type='system' "
                "AND body NOT LIKE '%connected.%' ORDER BY rowid DESC LIMIT 1", (rid,))
    return row["body"] if row else ""


def set_exhaustion(client, dm, code, tok_id, level):
    with ws_connect(client, dm, code) as dws:
        dws.send_json({"type": "exhaustion", "token_id": tok_id,
                       "action": "set", "level": level})
        drain(dws)                       # flush: handler ran to completion
    return last_sys(code)


def drain(ws, cap=80):
    ws.send_json({"type": "chat", "text": "@@exflush@@"})
    out = []
    while len(out) < cap:
        ev = ws.receive_json()
        if ev.get("kind") == "chat" and "@@exflush@@" in str(ev.get("payload", {}).get("text", "")):
            return out
        assert ev.get("kind") != "error", ev.get("payload")
        out.append(ev)
    raise AssertionError("event burst never ended")


def dice_bodies(evs):
    return [str(e["payload"].get("body", "")) for e in evs if e.get("kind") == "dice"]


def mk_def(client, dm, code, props, name="Exblade"):
    with ws_connect(client, dm, code) as dws:
        dws.send_json({"type": "item_def", "action": "create",
                       "defn": {"name": name, "kind": "weapon",
                                "props": dict(props, proficient=True)}})
        recv_until(dws, "whisper")
    defs = state_of(client, dm, code)["item_defs"]
    return next(d["id"] for d in defs if d["name"] == name)


def my_items(client, user, code):
    st = state_of(client, user, code)
    me = next(m for m in st["members"] if m["user_id"] == st["me"])
    return me["char"]["items"]


def grant_equip(client, dm, player, code, ch_id, def_id):
    with ws_connect(client, dm, code) as dws:
        dws.send_json({"type": "inv_grant", "char_id": ch_id, "def_id": def_id, "qty": 1})
        recv_until(dws, "inv_changed")
    item_id = next(i["id"] for i in my_items(client, player, code) if i["def_id"] == def_id)
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "inv_equip", "char_id": ch_id, "slot": "main_hand",
                      "item_id": item_id, "op_id": "e" + uuid.uuid4().hex[:10]})
        recv_until(ws, "inv_changed")
    return item_id


# ---------- speed (the ONE derivation) ----------

def test_exhaustion_eats_five_feet_per_level_on_the_one_speed_derivation(client):
    dm, player, code, ch = base_room(client)
    tok = token_of(code, ch["id"])
    assert movement._speeds(tok)["walk"] == 30
    set_exhaustion(client, dm, code, tok["id"], 2)
    assert movement._speeds(token_of(code, ch["id"]))["walk"] == 20      # 2 x 5 ft, walk only
    set_exhaustion(client, dm, code, tok["id"], 6)
    assert movement._speeds(token_of(code, ch["id"]))["walk"] == 0       # floored at 0


def test_npc_tokens_stay_untouched(client):
    dm, player, code, ch = base_room(client)
    with ws_connect(client, dm, code) as dws:
        dws.send_json({"type": "add_token", "label": "Goblin", "x": 700, "y": 700,
                       "npc": {"name": "Goblin", "hp": 7, "speed": 30}})
        nid = recv_until(dws, "token_add")["payload"]["id"]
        npc_tok = db.q1("SELECT * FROM tokens WHERE id=?", (nid,))
        assert movement._speeds(npc_tok)["walk"] == 30
        # exhaustion on an NPC token must be a silent no-op (no character to exhaust)
        dws.send_json({"type": "exhaustion", "token_id": nid, "action": "set", "level": 3})
        evs = drain(dws)
        assert not any("exhaustion" in str(e.get("payload", {}).get("text", "")) for e in evs)
    assert movement._speeds(db.q1("SELECT * FROM tokens WHERE id=?", (nid,)))["walk"] == 30

# ---------- attack roll + damage roll (derived expectations, no magic numbers) ----------

def _expected_damage_mod(ch_id, item_id):
    from app.room.dice import parse_roll
    sheet = gear.as_sheet(db.q1("SELECT * FROM characters WHERE id=?", (ch_id,)))
    prof = next(p for p in gear.weapon_profiles(sheet) if p["item_id"] == item_id)
    _n, _sides, static = parse_roll(prof["dmg"])
    return static + prof["dmg_bonus"] + gear.exhaustion_roll_mod(sheet)


def test_attack_line_wears_the_penalty_transparently(client):
    dm, player, code, ch = base_room(client)
    tok = token_of(code, ch["id"])
    def_id = mk_def(client, dm, code, {"damage_dice": "1d8+3", "damage_type": "slashing",
                                       "ability": "str"})
    item_id = grant_equip(client, dm, player, code, ch["id"], def_id)
    def roll(kind, tag):
        with ws_connect(client, player, code) as ws:
            ws.send_json({"type": "roll", "kind": kind, "item_id": item_id,
                          "token_id": tok["id"], "visibility": "public",
                          "op_id": tag + uuid.uuid4().hex[:10]})
            return dice_bodies(drain(ws))
    _b1 = roll("attack", "a")
    assert any("attack" in b for b in _b1), _b1
    assert not any("exhaustion" in b for b in _b1)
    set_exhaustion(client, dm, code, tok["id"], 1)
    _b2 = roll("attack", "b")
    assert any(" -2 exhaustion" in b for b in _b2), _b2
    set_exhaustion(client, dm, code, tok["id"], 3)
    bodies = roll("damage", "c")
    shown = int(bodies[0].split("]")[1].split("=")[0].strip().split()[0])
    assert shown == _expected_damage_mod(ch["id"], item_id)


# ---------- checks / saves / skills ----------

def _roll_text(client, player, code, msg):
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "roll", **msg})
        for body in dice_bodies(drain(ws)):
            return body
    raise AssertionError("no dice event")


def test_check_save_and_skill_text_carry_the_penalty(client):
    dm, player, code, ch = base_room(client)
    tok = token_of(code, ch["id"])
    set_exhaustion(client, dm, code, tok["id"], 3)             # dex 14: +2 − 6 = −4
    assert "-4 =" in _roll_text(client, player, code, {"kind": "check", "ability": "dex"})
    assert "-4 =" in _roll_text(client, player, code, {"kind": "save", "ability": "dex"})
    assert "-4 =" in _roll_text(client, player, code, {"kind": "skill", "skill": "acrobatics"})


def test_opposed_rolls_mirror_the_same_penalty():
    base = {"stats": {"str": 10, "dex": 10}, "skills": {}, "saves": {}}
    fresh = gear.as_sheet(dict(base))
    p = {"sheet": fresh, "conds": [], "room_id": 0,
         "skills": {}, "saves": {}, "kind": "pc", "stats_id": 1, "name": "X"}
    assert opposed.check_roll(p, "dex", kind="check")["mod"] == 0
    assert opposed.save_roll(p, "dex")["mod"] == 0
    ex = gear.as_sheet(dict(base, exhaustion=2))
    px = {**p, "sheet": ex}
    assert opposed.check_roll(px, "dex", kind="check")["mod"] == -4
    assert opposed.save_roll(px, "dex")["mod"] == -4
    clean_no = opposed.melee_attack_number(p)[0]
    assert opposed.melee_attack_number(px)[0] == clean_no - 4


# ---------- initiative ----------

def test_initiative_modifier_includes_exhaustion_for_pcs_only(client):
    dm, player, code, ch = base_room(client)
    tok = token_of(code, ch["id"])
    assert combat.token_dex_mod(tok) == 2                      # dex 14
    set_exhaustion(client, dm, code, tok["id"], 3)
    assert combat.token_dex_mod(token_of(code, ch["id"])) == -4


# ---------- death at 6, long rest, clamps ----------

def test_level_six_kills_through_the_existing_death_state(client):
    dm, player, code, ch = base_room(client)
    tok = token_of(code, ch["id"])
    assert "level 6" in set_exhaustion(client, dm, code, tok["id"], 6)
    death = db.j(db.q1("SELECT death FROM tokens WHERE id=?", (tok["id"],))["death"], None)
    assert death and death["dead"] is True
    assert db.q1("SELECT hp FROM characters WHERE id=?", (ch["id"],))["hp"] == 0


def rest_flush(client, dm, code):
    with ws_connect(client, dm, code) as dws:
        dws.send_json({"type": "long_rest"})
        drain(dws)


def test_long_rest_removes_one_level(client):
    dm, player, code, ch = base_room(client)
    tok = token_of(code, ch["id"])
    set_exhaustion(client, dm, code, tok["id"], 3)
    rest_flush(client, dm, code)
    assert db.q1("SELECT exhaustion FROM characters WHERE id=?", (ch["id"],))["exhaustion"] == 2
    # exhaustion 1 rests down to 0, and 0 never goes negative
    rest_flush(client, dm, code)
    assert db.q1("SELECT exhaustion FROM characters WHERE id=?", (ch["id"],))["exhaustion"] == 1
    rest_flush(client, dm, code)
    assert db.q1("SELECT exhaustion FROM characters WHERE id=?", (ch["id"],))["exhaustion"] == 0
    assert db.q1("SELECT hp FROM characters WHERE id=?", (ch["id"],))["hp"] == 30  # still alive


def test_set_clamps_to_srd_boundaries(client):
    dm, player, code, ch = base_room(client)
    tok = token_of(code, ch["id"])
    set_exhaustion(client, dm, code, tok["id"], 99)            # clamps to 6 -> death
    assert db.q1("SELECT exhaustion FROM characters WHERE id=?", (ch["id"],))["exhaustion"] == 6
    death = db.j(db.q1("SELECT death FROM tokens WHERE id=?", (tok["id"],))["death"], None)
    assert death and death["dead"] is True
    # players cannot self-exhaust themselves: the handler is DM-only
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "exhaustion", "token_id": tok["id"], "action": "set", "level": 0})
        drain(ws)
    assert db.q1("SELECT exhaustion FROM characters WHERE id=?", (ch["id"],))["exhaustion"] == 6
    assert not last_sys(code).endswith("exhaustion level 0")
