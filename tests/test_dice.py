"""Server-authoritative dice: expression parsing, clamps, advantage, and spell roll builders."""
from app.room.dice import (do_roll, parse_roll, _spell_attack_text,
                           _spell_dc_text, _spell_damage_text)


def test_parse_simple_and_with_mod():
    assert parse_roll("2d6+3") == (2, 6, 3)
    assert parse_roll("d20") == (1, 20, 0)
    assert parse_roll(" 1D8 -2 ") == (1, 8, -2)


def test_parse_rejects_garbage():
    for bad in ["", "rm -rf", "d20+", "1d", "5d", "1d20*2", "abc"]:
        assert parse_roll(bad) is None, bad


def test_parse_clamps_out_of_range():
    n, sides, mod = parse_roll("9999d9999+9999")
    assert n == 100 and sides == 1000 and mod == 500


def test_do_roll_respects_dice_bounds():
    for _ in range(50):
        r = do_roll("2d6", None)
        assert r["total"] >= 2 + 0 and r["total"] <= 12
        assert len(r["rolls"]) == 2


def test_advantage_rolls_two_d20_and_keeps_high():
    for _ in range(30):
        r = do_roll("1d20", "adv")
        assert len(r["rolls"]) == 2
        assert r["kept"] == max(r["rolls"])
        assert r["total"] == r["kept"] + r["mod"]
    for _ in range(30):
        r = do_roll("1d20", "dis")
        assert r["kept"] == min(r["rolls"])


def test_modifier_is_added():
    for _ in range(30):
        r = do_roll("1d20+5", None)
        assert r["mod"] == 5
        assert 6 <= r["total"] <= 25


def test_do_roll_invalid_returns_none():
    assert do_roll("not a roll", None) is None


def test_keep_high_low_parser_and_range():
    assert parse_roll("2d20kh1") == (2, 20, 0)
    for _ in range(30):
        kh = do_roll("2d20kh1", None)
        assert len(kh["rolls"]) == 2 and len(kh["kept_rolls"]) == 1
        assert kh["kept"] == max(kh["rolls"]) == kh["total"]
        kl = do_roll("2d20kl1+2", None)
        assert len(kl["kept_rolls"]) == 1 and 3 <= kl["total"] <= 22
        assert kl["kept"] == min(kl["rolls"])
    for _ in range(30):
        r = do_roll("4d6kh3", None)
        assert len(r["rolls"]) == 4 and len(r["kept_rolls"]) == 3
        assert r["kept"] == sum(sorted(r["rolls"], reverse=True)[:3]) == r["total"]
        assert 3 <= r["total"] <= 18


# ---- spell roll builders ----
def test_spell_attack_text_format_and_range():
    ch = {"name": "Zara", "stats": {"dex": 20}, "level": 1}   # PB 2 + dex +5 = +7
    sp = {"name": "Zap", "ability": "dex", "dmg": "8d6"}
    text, total = _spell_attack_text(ch, sp, None)
    assert "Zap attack" in text and "Zara" in text
    assert 8 <= total <= 27                                    # 1..20 + 7


def test_spell_dc_text():
    ch = {"name": "Zara", "stats": {"int": 18}, "level": 4}   # PB 2 + int +4 → DC 14
    sp = {"name": "Web", "ability": "int", "save": "dex", "dmg": ""}
    text, dc = _spell_dc_text(ch, sp)
    assert dc == 14 and "save DC 14" in text and "DEX" in text


def test_spell_damage_crit_doubles_dice_count():
    sp = {"name": "Dart", "dmg": "1d6"}
    _, total = _spell_damage_text({"name": "Z"}, sp, crit=False)
    assert 1 <= total <= 6
    _, crit = _spell_damage_text({"name": "Z"}, sp, crit=True)
    assert 2 <= crit <= 12


def test_spell_damage_none_when_no_dice():
    assert _spell_damage_text({"name": "Z"}, {"name": "X", "dmg": ""}, False) is None
