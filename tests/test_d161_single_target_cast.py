"""D161 (play-session audit, Akt III): single-targeted sheet abilities were
uncastable — the spell row rendered a Cast button but NO target control, so
``ability_cast`` left the socket without ``target_id`` and the server (correctly)
answered "No target token". Every ally heal, every Bane: dead end for players.
Reproduced live: Solea's Mend Pain row offered no target select; the cast errored.

Fix: single-targeting rows get an ``.ab-tgt`` select (visible-token list, same
one the attack rows use) and the click handler ships ``target_id`` with the cast.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROOM = (ROOT / "app" / "static" / "js" / "30_room.js").read_text(encoding="utf-8")


def test_single_target_rows_get_a_target_select():
    i = ROOM.index('} else if (registered){')
    block = ROOM[i:i + 1500]
    assert 'taring === "single"' in block or "single" in block
    assert 'class="ab-tgt"' in block, "single-target rows must render a target select"
    # and it must ride into the cast button line, not sit unused
    assert "btns += sel +" in block


def test_cast_handler_ships_the_target():
    i = ROOM.index('querySelectorAll(".cast-ab")')
    block = ROOM[i:i + 700]
    assert ".ab-tgt" in block, "handler ignores the target select"
    assert "msg.target_id" in block, "target_id never joins the ability_cast message"
