"""Sidebar layout regression pins (chat/log/dice overlap fix, Sprint 9 follow-up).

The room sidebar used to stack chronicle (chat/log/dice) and the category
panels in ONE scroll column behind a faked viewport height and a sticky tab
bar — panels crushed each other, slid under the bar, or fell below the
viewport. The fix is structural: a real flex app shell, three fixed sidebar
regions, and single-surface feed tabs. These static pins keep the removed
antipatterns from creeping back in; pixel-exact correctness still needs the
browser checklist (MANUAL_FIX_NOTES.md) — automated tests cannot prove visuals.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "app" / "static" / "style.css").read_text()
HTML = (ROOT / "app" / "static" / "index.html").read_text()
ROOM_JS = (ROOT / "app" / "static" / "js" / "30_room.js").read_text()
MAIN_JS = (ROOT / "app" / "static" / "js" / "60_main.js").read_text()


def test_no_faked_viewport_height():
    """The viewport split comes from flex, never from guessing the topbar height."""
    assert "calc(100vh" not in CSS
    assert "--topbar-h" not in CSS
    assert "#view-room { display: flex; flex-direction: column; height: 100vh; }" in CSS
    assert re.search(r"\.room-grid \{[^}]*flex: 1 1 auto[^}]*min-height: 0", CSS)


def test_sidebar_is_fixed_regions_not_one_scroll_column():
    body = re.search(r"\.side \{([^}]*)\}", CSS).group(1)
    assert "overflow: hidden" in body and "overflow-y: auto" not in body
    # the sticky category bar (overlay layering) must stay deleted
    assert "position: sticky" not in CSS
    assert "z-index: 5" not in CSS
    drawer = re.search(r"\.side-cat \{([^}]*)\}", CSS).group(1)
    assert "overflow-y: auto" in drawer and "max-height" in drawer
    # chronicle may shrink (min-height:220px is what crushed the chat area)
    assert "min-height: 220px" not in CSS


def test_feed_tab_surfaces_exist_and_nest_correctly():
    for token in ('id="tab-chat"', 'id="tab-log"', 'id="tab-dice"',
                  'id="dice-panel"', 'id="dice-out"', 'id="chronicle-body"',
                  'id="side-cat"', 'id="side-tabs"', 'id="chronicle"'):
        assert token in HTML, token
    # dice is a panel INSIDE the chronicle body (single-surface feed), never
    # a sibling strip below it again; drawer closes the sidebar.
    assert HTML.index('id="chronicle-body"') < HTML.index('id="dice-panel"')
    assert HTML.index('id="dice-panel"') < HTML.index('id="side-cat"')
    assert HTML.index('id="dice-panel"') < HTML.index('id="btn-roll"')
    assert HTML.index('id="btn-roll"') < HTML.index('id="dice-out"')
    # every legacy dice hook survived the move
    for token in ('id="roll-expr"', 'id="roll-mod"', 'id="roll-adv"', 'id="roll-vis"',
                  'id="roll-abil"', 'id="roll-prof"', 'id="dice-btns"', 'class="row qdice"'):
        assert token in HTML, token


def test_feed_switching_keeps_one_surface():
    assert 'which === "log" ? "log" : which === "dice" ? "dice" : "chat"' in ROOM_JS
    for needle in ('state.feed !== "chat"', 'state.feed !== "log"', 'state.feed !== "dice"'):
        assert needle in ROOM_JS
    # chat composer rows belong to the chat surface only (log/dice never own
    # a composer — rows that show in several tabs were DM-side height growth)
    assert 'send.classList.toggle("hidden", state.feed !== "chat")' in ROOM_JS
    assert 'row.classList.toggle("hidden", state.feed !== "chat"' in ROOM_JS
    # feed choice persists per user
    assert 'localStorage.setItem("vtt-feed"' in ROOM_JS
    assert '"vtt-feed"' in ROOM_JS
    assert '"tab-dice"' in MAIN_JS and 'switchFeed("dice")' in MAIN_JS


def test_no_stale_dice_seam_left_behind():
    for token in ("chronicle-dice", "dice-sep"):
        assert token not in CSS, token
        assert token not in HTML, token
        for jsf in (ROOT / "app" / "static" / "js").glob("*.js"):
            assert token not in jsf.read_text(), (token, jsf)


def test_only_legitimate_overlay_layers_remain():
    """toast/movehud/help are the only z-index users, and live in .mapwrap/overlay."""
    layers = re.findall(r"z-index:\s*([^;]+);", CSS)
    assert layers and all("var(--z-" in l for l in layers), layers
    for token in ("--z-movehud", "--z-toast", "--z-help"):
        assert token in CSS


def test_feed_surfaces_cannot_size_themselves_by_content():
    """DM-growth regression: a flex item with basis `auto` uses its CONTENT
    height as the flex base size — in the DM's over-committed sidebar that made
    every appended dice/log line grow the chronicle and squeeze the drawer.
    Every item in the feed chain must size from the viewport (basis 0), only
    the capped drawer may stay content-based."""
    grow = re.search(r"\.panel\.grow \{([^}]*)\}", CSS).group(1)
    assert "flex: 1 1 0" in grow, grow
    assert "min-height: 0" in grow
    drawer = re.search(r"\.side-cat \{([^}]*)\}", CSS).group(1)
    assert "max-height" in drawer and "overflow-y: auto" in drawer
    for rule in ("dice-panel", "dice-out"):
        body = re.search(rf"\.{rule} \{{([^}}]*)\}}", CSS).group(1)
        assert "flex: 1 1 0" in body, (rule, body)
    body = re.search(r"#chronicle-body \{([^}]*)\}", CSS).group(1)
    assert "overflow: hidden" in body
    # feed-entry styling must live on the real container class (.chat), never a
    # phantom `.log` selector (which silently dies and inflates DM line wraps)
    assert ".log .ts" not in CSS and ".log .visbadge" not in CSS
    assert ".chat .ts" in CSS and ".chat .visbadge" in CSS
    # feed state must be applied at room open, not only on switches
    assert re.search(r"function openRoom[\s\S]*?applyFeedPanels\(\);", ROOM_JS)


def test_collapsed_chronicle_shrinks_to_header():
    """Collapsed = the BOX collapses, not just the body: .grow keeps
    flex:1 1 0, so without an explicit grow-off the empty container would
    reserve the full expanded height (manual-report regression)."""
    collapsed = re.search(r"#chronicle\.collapsed \{([^}]*)\}", CSS)
    assert collapsed, "no #chronicle.collapsed rule"
    body = collapsed.group(1)
    assert re.search(r"flex:\s*0 0 auto", body), body
    # no height reservation for the collapsed state anywhere
    assert not re.search(r"#chronicle\.collapsed[^{]*\{[^}]*(?:min-height|height:)", CSS)
