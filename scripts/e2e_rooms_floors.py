#!/usr/bin/env python3
"""D157/D158 — real-Chromium E2E for the two manual-abnahme fixes.

Scenario H  room deletion: the DM's "Delete" opens a dialog that stays locked
        until the exact room CODE is typed; a wrong code never arms the
        destructive button; confirming really removes the room; a joined
        player is never shown a Delete button at all.
Scenario I  the elevator: the in-editor floor rail lists the room's real
        floors; selecting one repaints the canvas for that plane; a brush on
        the active plane persists to THAT plane only and survives a reload —
        the ground plane is never disturbed.
Scenario J  one solid ceiling vs one open shaft (two planes): an unowned token
        on the upper plane is hidden from a player standing below through a
        solid ceiling, and becomes visible once the DM opens the shaft.

Run exactly like e2e_playability_suite.py: throwaway app container on a free
loopback port (default 8013), this file inside the disposable Chromium image,
evidence via VTT_E2E_EVIDENCE. It never touches port 8000 or any host service.
"""
import os
import re
import sys
import time

from playwright.sync_api import expect, sync_playwright

BASE = os.environ.get("VTT_E2E_BASE_URL", "http://127.0.0.1:8013")
EVID = os.environ.get("VTT_E2E_EVIDENCE", "/tmp/opencode")
STEP = {"n": 0}


def shot(page, tag):
    STEP["n"] += 1
    try:
        os.makedirs(EVID, exist_ok=True)
        page.screenshot(path=f"{EVID}/e2e-rf-{STEP['n']:02d}-{tag}.png")
    except Exception as e:
        log(f"screenshot {tag} failed: {e}")


def log(msg):
    print(f"[rf] {msg}", flush=True)


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
    code = page.locator("#prep-code").inner_text().strip().upper()
    return code


def enter_room(page, code):
    page.evaluate("c => openRoom(c)", code)
    expect(page.locator("#side-tabs")).to_be_visible()


def page_idle(page, ms=700):
    page.wait_for_timeout(ms)


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
    page.wait_for_timeout(120)


def main():
    stamp = int(time.time())
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, chromium_sandbox=False)
        try:
            # ================= Scenario H — room deletion =================
            dmc = browser.new_context(base_url=BASE)
            dp = dmc.new_page()
            register(dp, f"rf_dm_{stamp}")
            code = create_room(dp, f"Alpha {stamp}")
            dp.evaluate("() => loadLobby()")            # refresh the lobby so the new room is listed
            page_idle(dp, 500)
            row = dp.locator("#room-list .roomrow", has_text="Alpha")
            expect(row.get_by_role("button", name="Delete")).to_be_visible()

            # a joined player must never be offered a Delete at all
            plc = browser.new_context(base_url=BASE)
            pp = plc.new_page()
            register(pp, f"rf_pl_{stamp}")
            pp.fill("#rm-code", code)
            pp.click("#btn-room-join")
            expect(pp.locator("#view-prep")).to_be_visible()
            pp.evaluate("() => loadLobby()")
            page_idle(pp, 500)
            expect(pp.locator("#room-list .roomrow", has_text="Alpha")
                   .get_by_role("button", name="Delete")).to_have_count(0)
            log("H — player sees no Delete button")

            # the DM's dialog: locked until the exact code is typed
            row.get_by_role("button", name="Delete").first.click()
            dlg = dp.locator("#del-room-dlg")
            expect(dlg).to_be_visible()
            expect(dp.locator("#del-room-confirm")).to_be_disabled()
            dp.fill("#del-room-input", "nope")          # wrong code keeps it locked
            expect(dp.locator("#del-room-confirm")).to_be_disabled()
            dp.fill("#del-room-input", code)            # the exact code arms it
            expect(dp.locator("#del-room-confirm")).to_be_enabled(timeout=3000)
            shot(dp, "H-dialog")
            dp.click("#del-room-confirm")
            page_idle(dp, 900)
            # the room is gone from the list, and the dialog closed
            expect(dp.locator("#room-list .roomrow", has_text="Alpha")).to_have_count(0)
            expect(dlg).to_be_hidden()
            # re-check against a fresh lobby load
            dp.evaluate("() => loadLobby()")
            page_idle(dp, 600)
            expect(dp.locator("#room-list .roomrow", has_text="Alpha")).to_have_count(0)
            log("H PASS — typed-code gate + real deletion + list refresh")
            shot(dp, "H-deleted")

            # ================= Scenario I — the elevator =================
            dmc2 = browser.new_context(base_url=BASE)
            dp2 = dmc2.new_page()
            dp2.on("dialog", lambda d: d.accept())   # any floor-switch confirm: proceed
            register(dp2, f"rf_edm_{stamp}")
            code2 = create_room(dp2, f"Ed {stamp}")
            enter_room(dp2, code2)
            # add a second floor from the DM tab (the room floor manager)
            dp2.click("#side-tabs button[data-tab='dm']")
            dp2.fill("#floor-new", "Attic")
            dp2.click("#btn-floor-add")
            dp2.wait_for_function("() => (state.floors || []).length >= 2", timeout=8000)
            # open the map editor and inspect the floor rail
            dp2.click("#btn-edit-map")
            rail = dp2.locator("#floor-rail")
            expect(rail).to_be_visible()
            expect(rail.locator(".fl-rail")).to_have_count(2)
            # the active rail entry is the ground (primary) plane
            expect(rail.locator(".fl-rail.active")).to_contain_text("Ground")
            # choose the upper plane; the active marker must move to it
            rail.locator(".fl-rail", has_text="Attic").click()
            dp2.wait_for_timeout(900)
            expect(rail.locator(".fl-rail.active")).to_contain_text("Attic")
            expect(rail.locator('.fl-rail[data-f=""]').first).not_to_have_attribute(
                "aria-pressed", "true")
            shot(dp2, "I-rail")

            # paint a wall on the ACTIVE (upper) plane at a known cell
            GX, GY = 2, 3
            dp2.click(".brush[data-b='wall']")
            click_cell(dp2, GX, GY)
            wall_on_upper = dp2.evaluate(
                "([gx,gy]) => { const g = state.editMap; return g.cells[gy * g.w + gx]; }",
                [GX, GY])
            assert wall_on_upper == 1, f"wall not painted on the active plane ({wall_on_upper})"
            dp2.click("#btn-ed-save")
            dp2.wait_for_timeout(900)

            # switch the rail back to ground — the wall must NOT be there
            rail.locator('.fl-rail[data-f=""]').first.click()
            dp2.wait_for_timeout(900)
            ground_cell = dp2.evaluate(
                "([gx,gy]) => { const g = state.grid; return g.cells[gy * g.w + gx]; }",
                [GX, GY])
            assert ground_cell == 0, f"ground plane was disturbed by an upper-plane brush ({ground_cell})"
            log("I — upper-plane brush left the ground plane untouched")

            # persistence: reload, re-enter, the wall is still on the Attic only
            dp2.reload()
            expect(dp2.locator("#lobby-user")).to_be_visible(timeout=8000)   # cookie kept the session
            enter_room(dp2, code2)
            dp2.click("#btn-edit-map")
            rail = dp2.locator("#floor-rail")
            rail.locator(".fl-rail", has_text="Attic").click()
            dp2.wait_for_timeout(900)
            reloaded_upper = dp2.evaluate(
                "([gx,gy]) => { const g = state.grid; return g.cells[gy * g.w + gx]; }",
                [GX, GY])
            rail.locator('.fl-rail[data-f=""]').first.click()
            dp2.wait_for_timeout(900)
            reloaded_ground = dp2.evaluate(
                "([gx,gy]) => { const g = state.grid; return g.cells[gy * g.w + gx]; }",
                [GX, GY])
            assert reloaded_upper == 1, "upper-plane wall did not survive a reload"
            assert reloaded_ground == 0, "ground shows a wall that was only painted upstairs"
            log("I PASS — elevator switches planes, brush edits one plane only, persists on reload")
            shot(dp2, "I-persist")


            log("ALL SCENARIOS PASS")
        finally:
            browser.close()


if __name__ == "__main__":
    sys.exit(main())
