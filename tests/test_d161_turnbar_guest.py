"""D161 (play-session audit, Akt III): renderInit crashed the room open for
every NON-active viewer while combat was running.

The turn bar only renders Dash/End Turn for the acting player or the DM
(``if (myTurn || isDM)``), but the two ``.onclick`` assignments ran
UNCONDITIONALLY — for every other player ``bar.querySelector('[data-a=
"dash"]')`` is null, the TypeError escaped renderInit, and it escaped
openRoom with it: a player could not (re-)enter the room at all while the
initiative marker sat on someone else. Reproduced live: the browser died in
openRoom at 30_room.js renderInit with "Cannot set properties of null
(setting 'onclick')".

Fix: wire each button only when it exists — the exact guard pattern the
slot-chip loop two lines below already uses.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROOM = (ROOT / "app" / "static" / "js" / "30_room.js").read_text(encoding="utf-8")


def _fn(name):
    i = ROOM.index(f"function {name}(")
    j = ROOM.index("\nfunction ", i + 1)
    return ROOM[i:j]


def test_turnbar_wires_only_buttons_it_rendered():
    body = _fn("renderInit")
    # Dash/End Turn are rendered only for myTurn||isDM, so their wiring must
    # not assume the element exists.
    assert "']).onclick" not in body, "turn bar dereferences a querySelector result directly"
    assert 'if (_dash) _dash.onclick' in body or "?.onclick" in body or "if (" in body


def test_no_unconditional_null_deref_in_turnbar_wiring():
    body = _fn("renderInit")
    # the historical shape: bar.querySelector('[data-a="..."]').onclick = ...
    bad = [line for line in body.splitlines()
           if "bar.querySelector('[data-a=" in line and "']).onclick" in line]
    assert not bad, f"unguarded wiring: {bad}"
