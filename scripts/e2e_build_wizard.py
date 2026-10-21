#!/usr/bin/env python3
"""Real-Chromium regression for the guided build wizard (AP-006)."""
import io
import os
import sys
import time
import zipfile
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BASE = os.environ.get("VTT_E2E_BASE_URL", "http://127.0.0.1:8010")
SKILLS = ("stealth", "perception", "acrobatics", "athletics")


def package_bytes():
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted((ROOT / "app" / "content_pack").glob("*.csv")):
            archive.write(path, path.name)
    return out.getvalue()


def register(page, username, password):
    page.goto("/")
    expect(page.locator("#btn-register")).to_be_visible()
    page.fill("#au-user", username)
    page.fill("#au-pass", password)
    page.click("#btn-register")
    expect(page.locator("#lobby-user")).to_contain_text(username)


def main():
    stamp = int(time.time() * 1000)
    room_name = f"E2E build {stamp}"
    char_name = f"E2E Scout {stamp}"

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            dm = browser.new_context(base_url=BASE)
            dm_page = dm.new_page()
            register(dm_page, f"e2e_dm_{stamp}", "secret12345")
            dm_page.fill("#rm-name", room_name)
            dm_page.click("#btn-room-create")
            expect(dm_page.locator("#view-prep")).to_be_visible()
            code = dm_page.locator("#prep-code").inner_text().strip().upper()
            assert code, "DM prep screen did not show a room code"

            response = dm_page.context.request.post(
                f"{BASE}/api/content/{code}/import?mode=apply&name=content.zip",
                data=package_bytes(),
                headers={"Content-Type": "application/zip"},
            )
            assert response.ok, response.text()
            report = response.json()
            assert report.get("ok"), report

            player = browser.new_context(base_url=BASE)
            player_page = player.new_page()
            register(player_page, f"e2e_player_{stamp}", "secret12345")
            player_page.fill("#rm-code", code)
            player_page.click("#btn-room-join")
            expect(player_page.locator("#view-prep")).to_be_visible()

            player_page.click("#prep-new-toggle")
            player_page.fill("#prep-name", char_name)
            player_page.select_option("#prep-species", label="Kit-kin")
            player_page.select_option("#prep-class", label="Scout")
            player_page.select_option("#prep-bg", label="Urchin")
            player_page.click("#prep-create")
            player_page.eval_on_selector("#prep-wizbox", "element => { element.open = true; }")
            expect(player_page.locator("#prep-wiz")).to_be_visible()

            player_page.click("#prep-plan")
            wizard = player_page.locator("#prep-wiz")
            expect(wizard).to_contain_text("Expertise")
            for skill in SKILLS:
                player_page.check(f'.pw-sk[value="{skill}"]')
            player_page.check(".pw-exp[value='stealth']")
            expect(wizard).to_contain_text("All guided choices collected")

            player_page.click("#prep-apply")
            expect(player_page.locator("#prep-out")).to_contain_text("built to 1")
            player_page.screenshot(path="/tmp/opencode/e2e-prep-wizard.png", full_page=True)

            characters = player_page.evaluate(
                "() => fetch('/api/characters').then(response => response.json())"
            )
            character = next(c for c in characters if c["name"] == char_name)
            assert character["skills"]["stealth"] == 2, character["skills"]
            assert character["skills"]["perception"] == 1, character["skills"]
        finally:
            browser.close()

    print(f"PASS: guided expertise build verified in Chromium at {BASE}")


if __name__ == "__main__":
    sys.exit(main())
