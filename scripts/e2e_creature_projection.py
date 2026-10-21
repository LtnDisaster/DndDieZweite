#!/usr/bin/env python3
"""Real-Chromium acceptance for creature CSV → bestiary projection (AP-008)."""
import io
import os
import sys
import time
import zipfile
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BASE = os.environ.get("VTT_E2E_BASE_URL", "http://127.0.0.1:8010")


def package_bytes():
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted((ROOT / "app" / "content_pack").glob("*.csv")):
            archive.write(path, path.name)
    return out.getvalue()


def reveal_dm_content_panel(page, username):
    page.evaluate(
        """(username) => {
          localStorage.setItem('vtt-side-tab-' + username, 'dm');
          applySideTab();
          let el = document.getElementById('btn-ct-creatures');
          while (el) {
            if (el.tagName === 'DETAILS') el.open = true;
            el = el.parentElement;
          }
        }""",
        username,
    )


def main():
    stamp = int(time.time() * 1000)
    username = f"e2e_dm_{stamp}"
    room_name = f"E2E bestiary {stamp}"

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            context = browser.new_context(base_url=BASE)
            page = context.new_page()
            page.goto("/")
            page.fill("#au-user", username)
            page.fill("#au-pass", "secret12345")
            page.click("#btn-register")
            page.fill("#rm-name", room_name)
            page.click("#btn-room-create")
            page.wait_for_function("() => state.room && state.room.code")
            code = page.evaluate("() => state.room.code")
            assert code
            page.click("#prep-table")
            expect(page.locator("#side-tabs")).to_be_visible()

            response = page.context.request.post(
                f"{BASE}/api/content/{code}/import?mode=apply&name=content.zip",
                data=package_bytes(),
                headers={"Content-Type": "application/zip"},
            )
            assert response.ok, response.text()
            report = response.json()
            assert report.get("ok"), report

            reveal_dm_content_panel(page, username)
            page.click("#btn-ct-creatures")
            creatures = page.locator("#ct-creatures")
            expect(creatures).to_contain_text("Wolfkin")
            wolf_button = creatures.locator(
                ".journal-item", has_text="Wolfkin"
            ).get_by_role("button", name="To bestiary")
            expect(wolf_button).to_be_enabled()
            wolf_button.click()
            expect(page.locator("#best-list")).to_contain_text("Wolfkin")
            bestiary = page.evaluate(
                "() => fetch('/api/creatures').then(response => response.json())"
            )
            wolf = next(item for item in bestiary if item["name"] == "Wolfkin")
            assert wolf["block"]["attacks"][0]["dmg"] == "1d6+2", wolf
            page.screenshot(path="/tmp/opencode/e2e-creature-projection.png",
                            full_page=True)

            hawk_button = creatures.locator(
                ".journal-item", has_text="Hawk-kin"
            ).get_by_role("button", name="To bestiary")
            expect(hawk_button).to_be_enabled()
            hawk_button.click()
            hawk_row = page.locator(".creature-row", has_text="Hawk-kin")
            expect(hawk_row).to_be_visible()
            hawk_row.get_by_role("button", name="Spawn").click()

            canvas = page.locator("#map")
            canvas.scroll_into_view_if_needed()
            box = canvas.bounding_box()
            assert box
            page.mouse.click(box["x"] + box["width"] / 2,
                             box["y"] + box["height"] / 2)
            page.wait_for_function(
                "() => state.tokens && state.tokens.some(t => t.label === 'Hawk-kin')"
            )
            token = page.evaluate(
                """() => {
                  const t = state.tokens.find(t => t.label === 'Hawk-kin');
                  return t && {darkvision: t.darkvision, npc: t.npc};
                }"""
            )
            assert token and token["darkvision"] == 12, token
            assert token["npc"]["skills"]["perception"] == 1, token
            assert token["npc"]["darkvision_ft"] == 60, token

            token_pos = page.evaluate(
                """() => {
                  const t = state.tokens.find(t => t.label === 'Hawk-kin');
                  const box = document.getElementById('map').getBoundingClientRect();
                  return {x: box.left + t.x + state.cam.ox,
                          y: box.top + t.y + state.cam.oy};
                }"""
            )
            page.mouse.click(token_pos["x"], token_pos["y"])
            skills = page.locator("#npc-skills")
            expect(skills).to_be_visible()
            expect(skills).to_contain_text("Perception")
            page.screenshot(path="/tmp/opencode/e2e-npc-skill-display.png",
                            full_page=True)
        finally:
            browser.close()

    print(f"PASS: creature projection verified in Chromium at {BASE}")


if __name__ == "__main__":
    sys.exit(main())
