#!/usr/bin/env python3
"""D159 — real-Chromium E2E for open-volume floors, signed levels and the
display-only floor filter.

Run exactly like e2e_rooms_floors.py: a throwaway app container on a free
loopback port (default 8013) built from the CURRENT tree, this file inside the
disposable Chromium image, evidence via VTT_E2E_EVIDENCE. It never touches port
8000 or any host service.

Scenario K  the D159 floor model in the real client:
  K1  add one plane above and one BELOW the ground -> state carries signed
      floor_levels (E0=0, above=+1, below=-1) and the rail/panel render E-tags
      in true vertical order.
  K2  a never-edited named plane is open AIR (a fresh cell is terrain 6); the
      ground plane is floor (0).
  K3  the map shows a floor DISPLAY filter (DM only) that flips
      state.viewFilter between "This floor only" and "All visible" WITHOUT
      changing the plane actually in view (display-only, not a vision change).
  K4  a token the viewer is NOT standing on carries an absolute floor tag
      (E+1 …) and is drawable only in "All visible" — proven on the REAL
      client onPlane()/tokenPlaneLabel(), not a node mock.
"""
import os
import sys
import time

from playwright.sync_api import expect, sync_playwright

BASE = os.environ.get("VTT_E2E_BASE_URL", "http://127.0.0.1:8013")
EVID = os.environ.get("VTT_E2E_EVIDENCE", "/tmp/opencode")
STEP = {"n": 0}
MINUS = "\u2212"


def log(msg):
    print(f"[d159] {msg}", flush=True)


def shot(page, tag):
    STEP["n"] += 1
    try:
        os.makedirs(EVID, exist_ok=True)
        page.screenshot(path=f"{EVID}/e2e-d159-{STEP['n']:02d}-{tag}.png")
    except Exception as e:
        log(f"screenshot {tag} failed: {e}")


def register(page, username):
    page.goto("/")
    expect(page.locator("#btn-register")).to_be_visible()
    page.fill("#au-user", username)
    page.fill("#au-pass", "secret12345")
    page.click("#btn-register")
    expect(page.locator("#lobby-user")).to_contain_text(username)


def create_room(page, name):
    page.fill("#rm-name", name)
    page.click("#btn-room-create")
    expect(page.locator("#view-prep")).to_be_visible()
    return page.locator("#prep-code").inner_text().strip().upper()


def enter_room(page, code):
    page.evaluate("c => openRoom(c)", code)
    expect(page.locator("#side-tabs")).to_be_visible()


def cell_px(page, gx, gy):
    return page.evaluate(
        """([gx, gy]) => { const c = cellSize();
            const r = document.getElementById('map').getBoundingClientRect();
            return [r.left + gx * c + c / 2 + state.cam.ox,
                    r.top + gy * c + c / 2 + state.cam.oy]; }""",
        [gx, gy])


def click_cell(page, gx, gy):
    x, y = cell_px(page, gx, gy)
    page.mouse.click(x, y)
    page.wait_for_timeout(140)


def main():
    stamp = int(time.time())
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, chromium_sandbox=False)
        try:
            ctx = browser.new_context(base_url=BASE)
            p = ctx.new_page()
            p.on("dialog", lambda d: d.accept())          # any floor-switch confirm: proceed
            register(p, f"d159_dm_{stamp}")
            code = create_room(p, f"D159 {stamp}")
            enter_room(p, code)

            # ---- K1: signed levels + below-floor + E-tags -------------------
            p.click("#side-tabs button[data-tab='dm']")
            p.fill("#floor-new", "Attic")
            p.click("#btn-floor-add")
            p.wait_for_function("() => (state.floors||[]).length === 2", timeout=8000)
            p.fill("#floor-new", "Cellar")
            p.check("#floor-below")                       # D159: declare it UNDER the ground
            p.click("#btn-floor-add")
            p.wait_for_function(
                "() => state.floor_levels && Object.keys(state.floor_levels).length >= 3",
                timeout=8000)
            lv = p.evaluate("() => state.floor_levels")
            fl = p.evaluate("() => state.floors")
            assert lv == {"": 0, "Attic": 1, "Cellar": -1}, lv
            assert fl == ["Cellar", "", "Attic"], fl       # bottom -> top, primary in the middle
            tags = p.locator("#floor-list .fl-lvl").all_inner_texts()
            assert "E+1" in tags and "E0" in tags and ("E" + MINUS + "1") in tags, tags
            log(f"K1 PASS — signed levels {lv}; panel tags {tags}")
            shot(p, "K1-levels")

            # ---- K2: a fresh named plane is AIR, ground is floor -------------
            p.click("#btn-edit-map")
            rail = p.locator("#floor-rail")
            expect(rail).to_be_visible()
            order = rail.locator(".fl-rail .nm").all_inner_texts()
            assert order == ["Attic", "Ground", "Cellar"], order   # highest on top
            lvl_top = rail.locator(".fl-rail").first.locator(".lvl").inner_text()
            assert lvl_top == "E+1", lvl_top
            rail.locator(".fl-rail", has_text="Attic").click()
            p.wait_for_function("() => state.viewFloor === 'Attic'", timeout=8000)
            p.wait_for_timeout(400)
            attic_cell = p.evaluate("() => state.editMap.cells[0]")
            ground_btn = rail.locator('.fl-rail[data-f=""]').first
            ground_btn.click()
            p.wait_for_function("() => state.viewFloor === ''", timeout=8000)
            p.wait_for_timeout(400)
            ground_cell = p.evaluate("() => state.editMap.cells[0]")
            assert attic_cell == 6, f"a fresh plane must be open AIR(6), got {attic_cell}"
            assert ground_cell == 0, f"the ground plane must default to floor(0), got {ground_cell}"
            log(f"K2 PASS — fresh plane AIR(6), ground floor(0)")
            shot(p, "K2-air")

            # the air brush paints 6; erase on a named plane restores 6
            rail.locator(".fl-rail", has_text="Attic").click()
            p.wait_for_function("() => state.viewFloor === 'Attic'", timeout=8000)
            p.wait_for_timeout(300)
            p.click(".brush[data-b='floor']")
            click_cell(p, 4, 4)
            laid = p.evaluate("() => { const m=state.editMap; return m.cells[4*m.w+4]; }")
            assert laid == 0, laid
            p.click(".brush[data-b='erase']")
            click_cell(p, 4, 4)
            erased = p.evaluate("() => { const m=state.editMap; return m.cells[4*m.w+4]; }")
            assert erased == 6, f"erase on a named plane must restore AIR(6), got {erased}"
            log("K2b PASS — air brush lays floor; erase on a named plane restores air")

            # ---- K3: the display-only floor filter --------------------------
            vf = p.locator("#viewfilter")
            expect(vf).to_be_visible()
            before_view = p.evaluate("() => state.viewFloor")
            assert p.evaluate("() => state.viewFilter") == "current"
            p.click("#vf-all")
            p.wait_for_function("() => state.viewFilter === 'all'", timeout=4000)
            expect(p.locator("#vf-all")).to_have_attribute("aria-pressed", "true")
            expect(p.locator("#vf-current")).to_have_attribute("aria-pressed", "false")
            after_view = p.evaluate("() => state.viewFloor")
            assert before_view == after_view, "the display filter must not change the viewed plane"
            log("K3 PASS — filter toggles state, never moves the viewer")
            shot(p, "K3-filter")

            # ---- K4: a cross-floor token is badged + gated by the filter -----
            # Attic is open AIR, so a token cannot stand there — the DM first
            # lays a floor at (8,8) on Attic (D159: author ground before a
            # walker stands), saves it, then drops a token on that cell while
            # BROWSING the ground.
            p.click(".brush[data-b='floor']")
            click_cell(p, 8, 8)
            p.click("#btn-ed-save")
            p.wait_for_timeout(900)
            p.evaluate("() => state.viewFloor = ''")     # browse the ground
            p.evaluate("""() => { const c = cellSize();
                wsSend({ type:'add_token', label:'Up', x:(8+.5)*c, y:(8+.5)*c,
                         size:'Medium', floor:'Attic' }); }""")
            p.wait_for_function(
                "() => (state.tokens||[]).some(t => t.floor === 'Attic' && t.label === 'Up')",
                timeout=8000)
            probe = p.evaluate("""() => {
                const t = state.tokens.find(t => t.floor === 'Attic');
                state.viewFilter = 'current'; const cur = onPlane(t);
                const label = tokenPlaneLabel(t);
                state.viewFilter = 'all'; const all = onPlane(t);
                return { cur, all, label }; }""")
            assert probe["cur"] is False, "in 'this floor only' a floor-A token is not drawn below"
            assert probe["all"] is True, "in 'all visible' the floor-A token becomes drawable"
            assert probe["label"].startswith("E+1"), probe["label"]
            log(f"K4 PASS — cross-floor token labelled '{probe['label']}', gated by the filter")
            shot(p, "K4-badge")

            log("ALL D159 SCENARIOS PASS")
        finally:
            browser.close()


if __name__ == "__main__":
    sys.exit(main())
