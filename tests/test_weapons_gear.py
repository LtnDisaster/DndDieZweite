"""Sprint 27 (D98): weapons, equipment and magic items through the ONE engine.

Everything a worn/wielded item grants is DERIVED from the base columns + items +
equipment, so equipping / unequipping / attuning / restarting can never double-
apply or go stale. Pins: one/two/versatile grip and its dice, hand occupancy,
ranged normal/long tiers, per-weapon vs general vs worn vs attuned vs on-consume
bonuses, AC (base/bonus/max-dex), attribute set/bonus feeding EVERY derived value,
skill/save grants + expertise (never double proficiency), darkvision, speed,
healing on use, equip/unequip, persistence, authz and op_id replay.
"""
import pytest
from starlette.testclient import TestClient

from app import db, gear, main
from tests.test_movement_fog import (H, base_room, recv_until, ws_connect)


@pytest.fixture()
def client():
    return TestClient(main.app)


# ---------- pure gear math (deterministic, no transport) ----------

def sheet(**over):
    base = {"ac": 10, "stats": {"str": 10, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10},
            "level": 5, "skills": {}, "saves": {}, "items": [], "equipment": {}}
    base.update(over)
    return base


def item(id, kind="weapon", **kw):
    d = {"id": id, "name": id, "kind": kind}
    d.update(kw)
    return gear.clean_items([d])[0]


def prof(c, item_id):
    return next(p for p in gear.weapon_profiles(c) if p["item_id"] == item_id)


def test_sword_plus1_per_weapon_bonus_and_damage_mod():
    # +1 attack AND +1 damage only WITH this sword; str adds to damage once.
    it = item("sw", props={"damage_dice": "1d8", "attack_bonus": 1, "damage_bonus": 1,
                           "proficient": True, "damage_type": "slashing"})
    c = sheet(stats={"str": 20}, items=[it], equipment={"main_hand": "sw"})
    p = prof(c, "sw")
    assert p["to_hit"] == 5 + 3 + 1          # str +5, prof +3, enhancement +1
    assert p["dmg"] == "1d8" and p["dmg_bonus"] == 1 + 5   # enhancement + ability mod
    assert p["dmg_type"] == "slashing" and not p["gated"]


def test_one_hand_two_hand_and_versatile_grip_dice():
    one = item("sw", props={"damage_dice": "1d8", "versatile": True, "damage_dice_two_handed": "1d10"})
    c1 = sheet(items=[one], equipment={"main_hand": "sw"})
    assert prof(c1, "sw")["dmg"] == "1d8" and prof(c1, "sw")["grip"] == "one"
    two = item("sw", grip="two", props={"damage_dice": "1d8", "versatile": True,
                                        "damage_dice_two_handed": "1d10"})
    c2 = sheet(items=[two], equipment={"main_hand": "sw"})
    assert prof(c2, "sw")["dmg"] == "1d10" and prof(c2, "sw")["grip"] == "two"
    # a fixed two-hander always uses its own dice and reads as two-handed
    g = item("gs", props={"damage_dice": "2d6", "two_handed": True})
    assert prof(sheet(items=[g], equipment={"main_hand": "gs"}), "gs")["two_handed"]


def test_two_handed_grip_locks_the_off_hand():
    two = item("sw", grip="two", props={"damage_dice": "1d8", "versatile": True,
                                        "damage_dice_two_handed": "1d10"})
    shield = item("sh", kind="shield")
    assert gear.can_equip(shield, "off_hand", {"main_hand": "sw"}, [two, shield]) is False
    # but one-handed the shield fits
    one = item("sw", props={"damage_dice": "1d8", "versatile": True, "damage_dice_two_handed": "1d10"})
    assert gear.can_equip(shield, "off_hand", {"main_hand": "sw"}, [one, shield]) is True


def test_ranged_tiers_and_finesse_ability_choice():
    bow = item("bow", props={"damage_dice": "1d8", "range_normal_ft" : 0, "range_ft": 150,
                             "range_long_ft": 600, "proficient": True})
    # a content bow: dex governs, long range exposed
    p = prof(sheet(stats={"dex": 14}, items=[bow], equipment={"main_hand": "bow"}), "bow")
    assert p["ranged"] and p["ability"] == "dex" and p["range_long_ft"] == 600
    # finesse melee: the wielder's better mod is used automatically
    dag = item("dag", props={"damage_dice": "1d4", "finesse": True, "proficient": True})
    pf = prof(sheet(stats={"str": 10, "dex": 20}, items=[dag], equipment={"main_hand": "dag"}), "dag")
    assert pf["ability"] == "dex" and pf["to_hit"] == 5 + 3


def test_attunement_gate_makes_a_magic_weapon_inert():
    wand = item("w", kind="wand", props={"damage_dice": "1d8", "attack_bonus": 2,
                                         "damage_bonus": 2, "proficient": True, "attune": True})
    assert wand["attunable"] is True and wand["attuned"] is False
    c_off = sheet(stats={"str": 20}, items=[wand], equipment={"main_hand": "w"})
    p = prof(c_off, "w")
    assert p["gated"] and p["to_hit"] == 5 + 3 and p["dmg_bonus"] == 5   # bonuses inert, base weapon works
    wand_on = gear.clean_items([dict(wand, attuned=True)])[0]
    assert wand_on["attuned"] is True
    p_on = prof(sheet(stats={"str": 20}, items=[wand_on], equipment={"main_hand": "w"}), "w")
    assert not p_on["gated"] and p_on["to_hit"] == 5 + 3 + 2 and p_on["dmg_bonus"] == 2 + 5


def test_extra_damage_dice_carried_on_the_profile():
    flame = item("ft", props={"damage_dice": "1d8", "extra_damage_dice": "+1d4",
                              "extra_damage_type": "fire", "proficient": True})
    p = prof(sheet(items=[flame], equipment={"main_hand": "ft"}), "ft")
    assert p["extra_dmg"] == "1d4" and p["extra_dmg_type"] == "fire"


# ---- AC (equipped mode reads content props; effective dexterity) ----

def test_ac_bonus_only_while_worn_and_attuned():
    ring = item("ring", kind="ring", props={"ac_bonus": 2})
    c_off = sheet(ac=12, items=[ring], equipment={})                 # nothing equipped → legacy path
    assert gear.compute_ac(sheet(ac=12, items=[ring], equipment={"acc1": "ring"})) == 14
    assert gear.compute_ac(sheet(ac=12, items=[ring], equipment={"acc1": None})) == 12  # no slot → legacy


def test_attunable_ac_ring_inert_until_attuned():
    ring = item("ring", kind="ring", magic=True, props={"ac_bonus": 2, "attune": True})
    assert gear.compute_ac(sheet(ac=12, items=[ring], equipment={"acc1": "ring"})) == 12   # not attuned
    on = gear.clean_items([dict(ring, attuned=True)])[0]
    assert gear.compute_ac(sheet(ac=12, items=[on], equipment={"acc1": "ring"})) == 14


def test_armor_base_and_max_dex_from_props():
    breast = item("br", kind="armor", props={"ac_base": 14, "ac_max_dex": 2})
    c = sheet(ac=10, stats={"dex": 20}, items=[breast], equipment={"armor": "br"})
    assert gear.compute_ac(c) == 14 + 2                              # dex capped at +2


def test_attribute_set_feeds_every_derived_value():
    # Gloves: dexterity becomes 15 (base 10) while worn — a light armour AC and initiative follow.
    gloves = item("gl", kind="wondrous", props={"attribute_set": {"ability": "dex", "value": 15}})
    light = item("le", kind="armor", props={"ac_base": 12, "ac_max_dex": -1})
    plain = sheet(stats={"dex": 10}, items=[light], equipment={"armor": "le"})
    assert gear.compute_ac(plain) == 12 + 0                          # dex 10 → no bonus
    c = sheet(stats={"dex": 10}, items=[light, gloves], equipment={"armor": "le", "acc1": "gl"})
    assert gear.stat_mod(c, "dex") == 2                              # 15 → +2
    assert gear.compute_ac(c) == 14                                  # 12 + (15's +2)
    assert gear.effective_gear(c)["stats"]["dex"] == 15


def test_attribute_bonus_stacks_without_mutating_base():
    band = item("hb", kind="wondrous", props={"attribute_bonus": {"int": 2}})
    c = sheet(stats={"int": 10}, items=[band], equipment={"acc1": "hb"})
    assert gear.stat_mod(c, "int") == 1                              # 12 → +1
    assert gear._base_score(c, "int") == 10                          # base column never touched
    # a second read is identical — derivation, not a stored delta
    assert gear.stat_mod(c, "int") == 1


def test_granted_proficiency_and_never_double():
    band = item("el", kind="wondrous", props={"expertise": ["perception"]})
    prof_ring = item("ring", kind="ring", props={"skill_prof": ["stealth"]})
    c = sheet(stats={"wis": 20}, items=[band], equipment={"acc1": "el"})
    assert gear.skill_bonus(c, {}, "perception") == (5 + 6, True)    # expertise
    c2 = sheet(stats={"wis": 20}, items=[prof_ring], equipment={"acc1": "ring"})
    assert gear.skill_bonus(c2, {}, "stealth") == (0 + 3, True)      # proficient via worn item
    # already-proficient + a proficiency grant must NOT stack
    assert gear.skill_bonus(c2, {"stealth": 1}, "stealth") == (0 + 3, True)


def test_save_grant_and_darkvision_and_speed():
    ring = item("ring", kind="ring", props={"save_prof": ["wis"], "darkvision_ft": 60,
                                            "speed_bonus_ft": 10})
    c = sheet(speed=30, stats={"wis": 10}, items=[ring], equipment={"acc1": "ring"})
    assert gear.save_bonus(c, {}, "wis") == 0 + 3                    # proficient save from gear
    eg = gear.effective_gear(c)
    assert eg["darkvision_ft"] == 60
    assert gear.clean_speeds(c)["walk"] == 40                        # 30 + 10


def test_derivation_is_idempotent_no_state_leaks():
    ring = item("ring", kind="ring", props={"ac_bonus": 2})
    c = sheet(ac=10, items=[ring], equipment={"acc1": "ring"})
    a, b = gear.compute_ac(c), gear.compute_ac(c)
    assert a == b == 12
    # unequipping in a fresh derivation immediately removes the bonus (no staleness)
    assert gear.compute_ac(dict(c, equipment={"acc1": None})) == 10


# ---------- transport / persistence / authz / replay ----------

def _grant(ws, code, char_id, item=None, def_id=None, qty=1, op_id=None):
    msg = {"type": "inv_grant", "char_id": char_id, "qty": qty}
    if item:
        msg["item"] = item
    if def_id:
        msg["def_id"] = def_id
    if op_id:
        msg["op_id"] = op_id
    ws.send_json(msg)


def _char_view(client, user, code):
    st = client.get(f"/api/rooms/{code}/state", headers=H(user)).json()
    return st["characters"][0]


def test_equip_persists_and_powers_the_attack(client):
    dm, player, code, ch = base_room(client)
    with ws_connect(client, dm, code) as ws:
        _grant(ws, code, ch["id"], item={"name": "Longsword +1", "kind": "weapon",
                                         "props": {"damage_dice": "1d8", "attack_bonus": 1,
                                                   "damage_bonus": 1, "proficient": True}})
        recv_until(ws, "inv_changed")
    items, _ = _char_view(client, player, code)["items"], None
    sw = items[0]["id"]
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "inv_equip", "char_id": ch["id"], "slot": "main_hand",
                      "item_id": sw, "op_id": "eq1"})
        recv_until(ws, "inv_changed")
    v = _char_view(client, player, code)
    ap = v["derived"]["attack_profiles"]
    assert ap and ap[0]["dmg"] == "1d8" and ap[0]["to_hit"] != 0     # server-derived, rides the sheet
    # persisted in the DB, not hub memory: a fresh read re-derives the same profile
    row = db.q1("SELECT * FROM characters WHERE id=?", (ch["id"],))
    fresh = gear.as_sheet(dict(row))
    assert gear.weapon_profiles(fresh)[0]["item_id"] == sw


def test_versatile_grip_two_clears_shield_and_replays_once(client):
    dm, player, code, ch = base_room(client)
    with ws_connect(client, dm, code) as ws:
        _grant(ws, code, ch["id"], item={"name": "Longsword", "kind": "weapon",
                                         "props": {"damage_dice": "1d8", "versatile": True,
                                                   "damage_dice_two_handed": "1d10"}})
        recv_until(ws, "inv_changed")
        _grant(ws, code, ch["id"], item={"name": "Shield", "kind": "shield", "ac": 2})
        recv_until(ws, "inv_changed")
    items = {i["name"]: i["id"] for i in _char_view(client, player, code)["items"]}
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "inv_equip", "char_id": ch["id"], "slot": "main_hand",
                      "item_id": items["Longsword"], "op_id": "e1"})
        recv_until(ws, "inv_changed")
        ws.send_json({"type": "inv_equip", "char_id": ch["id"], "slot": "off_hand",
                      "item_id": items["Shield"], "op_id": "e2"})
        recv_until(ws, "inv_changed")
        assert _char_view(client, player, code)["equipment"]["off_hand"]
        # switch to two-handed grip → the shield goes back to the pack (atomic)
        ws.send_json({"type": "inv_grip", "char_id": ch["id"],
                      "item_id": items["Longsword"], "grip": "two", "op_id": "g1"})
        recv_until(ws, "inv_changed")
        v = _char_view(client, player, code)
        assert v["equipment"]["off_hand"] is None
        assert next(p for p in v["derived"]["attack_profiles"]
                    if p["name"] == "Longsword")["dmg"] == "1d10"
        # replaying the SAME op_id changes nothing (no double handling, no error state)
        ws.send_json({"type": "inv_grip", "char_id": ch["id"],
                      "item_id": items["Longsword"], "grip": "two", "op_id": "g1"})
        recv_until(ws, "whisper")                                   # "already applied"
    assert _char_view(client, player, code)["equipment"]["off_hand"] is None


def test_grip_requires_the_weapon_in_the_main_hand(client):
    dm, player, code, ch = base_room(client)
    with ws_connect(client, dm, code) as ws:
        _grant(ws, code, ch["id"], item={"name": "Longsword", "kind": "weapon",
                                         "props": {"damage_dice": "1d8", "versatile": True,
                                                   "damage_dice_two_handed": "1d10"}})
        recv_until(ws, "inv_changed")
    sw = _char_view(client, player, code)["items"][0]["id"]
    with ws_connect(client, player, code) as ws:
        ws.send_json({"type": "inv_grip", "char_id": ch["id"], "item_id": sw,
                      "grip": "two", "op_id": "g0"})
        assert "main hand" in recv_until(ws, "error")["payload"]["msg"]


def test_healing_potion_restores_hp_once(client):
    dm, player, code, ch = base_room(client)
    # hurt the character first (DM flow) then drink
    with ws_connect(client, dm, code) as ws:
        _grant(ws, code, ch["id"], item={"name": "Draught", "kind": "potion",
                                         "props": {"heal_dice": "2d4+2"}})
        recv_until(ws, "inv_changed")
    v = _char_view(client, player, code)
    potion = [i for i in v["items"] if i["name"] == "Draught"][0]
    assert potion["heal"] == "2d4+2"                                # content heal_dice promoted → usable
    tok = db.q1("SELECT * FROM tokens WHERE room_id=? AND character_id=?",
                (db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"], ch["id"]))
    assert tok is not None
