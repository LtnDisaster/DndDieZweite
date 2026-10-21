"""D149 (Nachtschicht 3.0): the in-app help system.

The overlay was a static wall of prose: no search, no categories, no context,
and nothing connecting its claims to the real UI. 65_help.js replaced it with
a data-driven manual. These tests pin the three properties that make that
safe to keep:
  * single ownership — the module owns the overlay; 60_main/50_canvas only
    delegate (the old double-toggle is gone and must not come back),
  * vocabulary truth — the help may only speak about tab names and error
    strings the server actually produces (no invented buttons),
  * bundle discipline — load slot, stamp and 99_boot gate entries exist.
"""
import pathlib
import re

from starlette.testclient import TestClient

from app.main import app

ROOT = pathlib.Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
JS = STATIC / "js"

REAL_ERRORS = (
    "It is not your turn",
    "Not your token",
    "DM only",
    "Walk up to it first",
    "Target is out of reach",
    "It won't budge.",
    "No path there",
    "Route changed",
    "That transfer was already applied.",
    "Bring a character to the table first",
)

TABS = ("⚔ Game", "👤 Chars", "🎒 Inv", "📜 Story", "🎲 DM")


def _js(name):
    return (JS / name).read_text(encoding="utf-8")


def _load_order():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    return re.findall(r'<script src="/static/js/([0-9A-Za-z_]+\.js)', html)


def test_help_module_loaded_in_its_slot():
    order = _load_order()
    assert order.index("65_help.js") == order.index("60_main.js") + 1
    assert order[-1] == "99_boot.js"


def test_help_module_defines_its_surface_and_stamps():
    t = _js("65_help.js")
    assert '["65_help.js"] = window.__BUILD__' in t
    for name in ("setHelp", "helpVisible", "helpCtxCat", "renderHelp"):
        assert f"function {name}(" in t, name


def test_gate_knows_the_help_surface():
    boot = _js("99_boot.js")
    assert '"65_help.js"' in boot
    for name in ("setHelp", "helpVisible"):
        assert f'"{name}"' in boot, name


def test_help_entries_complete_in_known_categories():
    t = _js("65_help.js")
    cats = set(re.findall(r'\["([a-z]+)",\s*"[^"]+"\]', t))
    assert len(cats) >= 8, cats
    entries = re.findall(r'\{\s*c:"([a-z]+)",\s*t:"([^"]+)",\s*k:"([^"]+)"', t)
    assert len(entries) >= 35, len(entries)
    for c, _title, k in entries:
        assert c in cats, c
        assert len(k.split()) >= 3, c
    assert {c for c, _, _ in entries} == cats   # no empty category


def test_overlay_switched_in_only_one_place():
    """The old bug class: two scripts toggling the same overlay with their own
    hidden-class logic. Only 65_help.js may touch the overlay's hidden state."""
    canvas, main = _js("50_canvas.js"), _js("60_main.js")
    assert "help-overlay" not in canvas
    for m in re.finditer(r'"help-overlay"', main):     # main may look up the id
        assert "hidden" not in main[m.end():m.end() + 120], "second toggle point"  # never toggle it
    assert "helpVisible" in canvas and "setHelp" in canvas
    assert "helpCtxCat()" in main      # Help button opens the relevant category


def test_help_errors_match_real_server_strings():
    server = "\n".join(p.read_text(encoding="utf-8", errors="replace")
                       for p in (ROOT / "app" / "room").glob("*.py"))
    help_t = _js("65_help.js")
    for msg in REAL_ERRORS:
        assert msg in server, f"not a real server message: {msg!r}"
        assert msg in help_t, f"unexplained server message: {msg!r}"


def test_tab_names_as_they_are():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    help_t = _js("65_help.js")
    for label in TABS:
        assert label in html and label in help_t, label


def test_help_content_is_cjk_free():
    assert not re.findall(r"[\u4e00-\u9fff]+", _js("65_help.js"))


def test_served_help_surface_has_its_three_homes():
    with TestClient(app) as c:
        html = c.get("/").text
    for hid in ("help-search", "help-cats", "help-list"):
        assert f'id="{hid}"' in html, hid
