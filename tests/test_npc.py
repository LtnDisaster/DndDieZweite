"""Unit tests for the NPC stat-block model (app/npc.py) and its gear integration."""
from app import gear, npc


# ---------- clean_npc ----------

def test_clean_npc_defaults_and_bounds():
    b = npc.clean_npc({})
    assert b["level"] == 1 and b["ac"] == 10 and b["speed"] == 30
    assert b["hp"] == 10 and b["max_hp"] == 10
    assert set(b["stats"]) == {"str", "dex", "con", "int", "wis", "cha"}
    assert all(v == 10 for v in b["stats"].values())
    assert b["spells"] == []
    assert set(b["spell_slots"]) == set(range(1, 10))     # gear.clean_slots int keys


def test_clean_npc_clamps_and_reorders_hp():
    b = npc.clean_npc({"level": 0, "ac": 999, "max_hp": 5, "hp": 50,
                       "stats": {"str": 100, "dex": -3, "wis": 16}})
    assert b["level"] == 1 and b["ac"] == 40
    assert b["max_hp"] == 5 and b["hp"] == 5              # hp clamped to max_hp
    assert b["stats"]["str"] == 30 and b["stats"]["dex"] == 1 and b["stats"]["wis"] == 16
    assert b["stats"]["con"] == 10                         # missing ability defaults


def test_clean_npc_sanitises_spells_and_slots():
    b = npc.clean_npc({
        "spells": [{"id": "fb", "name": "Fire Bolt", "level": 1, "cast": "attack",
                    "ability": "int", "dmg": "2d10"}, {"name": ""}],
        "spell_slots": {"1": {"max": 2, "used": 5}},
    })
    assert [s["id"] for s in b["spells"]] == ["fb"]         # empty-name spell dropped, id kept
    assert b["spell_slots"][1] == {"max": 2, "used": 2}     # used clamped to max


# ---------- token block load ----------

def test_load_parses_or_none():
    assert npc.load({"npc": ""}) is None
    assert npc.load({"npc": None}) is None
    assert npc.load({"npc": "not-json"}) is None
    assert npc.load(None) is None
    tok = {"npc": '{"level": 3, "stats": {"dex": 18}}'}
    b = npc.load(tok)
    assert isinstance(b, dict) and b["stats"]["dex"] == 18


# ---------- ability / spell math flows through gear unchanged ----------

def test_dex_mod_and_prof_through_to_char():
    b = npc.clean_npc({"level": 5, "stats": {"dex": 20, "int": 18}})
    assert npc.dex_mod(b) == 5
    assert npc.stat_mod(b, "int") == 4
    nchar = npc.to_char(b, "Goblin")
    assert nchar["name"] == "Goblin" and nchar["level"] == 5
    assert gear.prof_bonus(nchar) == 3                      # 2 + (5-1)//4
    assert gear.spell_attack(nchar, "int") == 3 + 4         # prof + int mod
    assert gear.spell_save_dc(nchar, "int") == 8 + 3 + 4
