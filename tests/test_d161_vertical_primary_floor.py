"""D161 (play-session audit, Akt IV): flying (or teleporting) a token DOWN to
the primary plane was a silent no-op.

Both 3-D entry points parsed the destination plane as
``str(msg["floor"] or current)``. The primary plane's *name* is the empty
string — a legitimate destination ``""`` is falsy, so the ``or current``
fallback rewrote every ``to_floor == ""`` request to the token's *current*
plane; the subsequent ``start == goal`` check then returned WITHOUT an error
frame. Observed live: the sheet's "Ground (primary)" vertical-flight row
(the option's value is "" by the floor-stack contract) clicked, nothing
moved, nothing was refused — the table just sees a dead button.

Fix: only fall back to ``current`` when the key is absent/None, never when
it is the empty string. (The dispatch guard at ``cross_3d`` already uses the
correct ``or ""`` form — the asymmetry was the bug.)
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MOVE = (ROOT / "app" / "room" / "movement.py").read_text(encoding="utf-8")


def test_plane_parse_keeps_the_empty_primary_name():
    bad = re.findall(r'to_fl\s*=\s*str\(msg\["floor"\]\s+or\s+current\)', MOVE)
    assert not bad, (
        "destination-plane parsing must not `or current` away the primary "
        "plane's empty-string name — it silently cancels flights DOWN")


def test_both_3d_entrypoints_parse_the_floor_key_identically():
    good = re.findall(r'to_fl\s*=\s*str\(msg\["floor"\]\)\s+if\s+"floor"\s+in\s+msg\s+and\s+msg\["floor"\]\s+is\s+not\s+None\s+else\s+current', MOVE)
    assert len(good) == 2, (
        "_teleport3d and _move3d must both distinguish 'no floor key' from "
        "'primary plane \"\"' — found %d corrected sites" % len(good))
