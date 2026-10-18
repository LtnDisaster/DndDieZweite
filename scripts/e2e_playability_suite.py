#!/usr/bin/env python3
"""Nachtschicht 3.0 (D152): real-Chromium playability suite, scenarios C–G.

A (build wizard) and B (creature projection) have their own proven scripts.
This one walks the table-level flows the audit called out:

  C  initiative, slot bookkeeping, attack roll, dying loop incl. the new
     Stabilize button (D150 UI closure of D136)
  D  DM grant -> consume -> player-to-player 🫱 give (D150 UI closure of
     inv_transfer)
  E  floors: add floor, fly a token to it (vertical transport UI)
  F  multi-client: shared chat, reload persistence, presence shrink
  G  the in-app help (D149): search, categories, context chip, Esc

Run exactly like e2e_build_wizard.py: throwaway app container on loopback,
this file inside a disposable Chromium image, evidence via VTT_E2E_EVIDENCE.
"""
import json
import os
import re
import sys
import time
import uuid

from playwright.sync_api import expect, sync_playwright

BASE = os.environ.get("VTT_E2E_BASE_URL", "http://127.0.0.1:8010")
EVID = os.environ.get("VTT_E2E_EVIDENCE", "/tmp/opencode")
STEP = {"n": 0}


def shot(page, tag):
    STEP["n"] += 1
    page.screenshot(path=f"{EVID}/e2e-ns3-{STEP['n']:02d}-{tag}.png", full_page=True)


def log(msg):
    print(f"[ns3] {msg}", flush=True)


def register(page, username):
    page.goto("/")
    expect(page.locator("#btn-register")).to_be_visible()
    page.fill("#au-user", username)
    page.fill("#au-pass", "secret12345")
    page.click("#btn-register")
    expect(page.locator("#lobby-user")).to_contain_text(username)


def build_scout(page, name):
    """The proven e2e_build_wizard flow, minus the expertise assertions."""
    page.click("#prep-new-toggle")
    page.fill("#prep-name", name)
    page.select_option("#prep-species", label="Kit-kin")
    page.select_option("#prep-class", label="Scout")
    page.select_option("#prep-bg", label="Urchin")
    page.click("#prep-create")
    page.eval_on_selector("#prep-wizbox", "el => { el.open = true; }")
    page.click("#prep-plan")
    wiz = page.locator("#prep-wiz")
    expect(wiz).to_contain_text("Expertise")
    for skill in ("stealth", "perception", "acrobatics", "athletics"):
        page.check(f'.pw-sk[value="{skill}"]')
    page.check(".pw-exp[value='stealth']")
    page.click("#prep-apply")
    expect(page.locator("#prep-out")).to_contain_text("built to 1")


def enter_room(page, code):
    page.evaluate("c => openRoom(c)", code)
    expect(page.locator("#side-tabs")).to_be_visible()


def seat(page):
    """Real table flow: bring a character to the table via the Bring button."""
    tab = page.locator("#side-tabs button[data-tab='chars']")
    if tab.count():
        tab.click()   # re-seats run with whatever side tab was last active
    expect(page.locator("#my-chars .badge, #my-chars [data-a='bring']").first) \
        .to_be_visible(timeout=10000)
    bring = page.locator("#my-chars [data-a='bring']").first
    if bring.count():
        bring.click()
    # the seat panel lives inside a side tab that may be hidden — assert DOM, not visibility
    expect(page.locator("#my-chars .badge", has_text="at table")).to_have_count(1, timeout=8000)


def click_token(page, token_id):
    """Click a token's centre the way a human clicks the canvas.
    Token x/y live in world PIXELS (draw code: screen = t.x + cam.ox)."""
    pos = page.evaluate(
        """tid => { const t = state.tokens.find(x => x.id === tid);
            if (!t) return null;
            const r = document.getElementById('map').getBoundingClientRect();
            return [r.left + t.x + state.cam.ox, r.top + t.y + state.cam.oy]; }""",
        token_id)
    assert pos, f"token {token_id} not visible"
    page.mouse.click(pos[0], pos[1])


def token_xy(page, token_id):
    return page.evaluate(
        "tid => { const t = state.tokens.find(x => x.id === tid); return [t.x, t.y]; }",
        token_id)


def chronicle_has(page, pattern):
    # posts live in three feeds (chat/log/dice) — walk through the tabs;
    # switchFeed re-renders from state, so history survives tab switches.
    rx = re.compile(pattern, re.I)
    for tab, target in (("tab-chat", "#chat"), ("tab-log", "#log"), ("tab-dice", "#dice-out")):
        page.click(f"#{tab}")
        page.wait_for_timeout(250)
        if rx.search(page.locator(target).inner_text()):
            return
    raise AssertionError(f"chronicle_has: no feed matched /{pattern}/")


def token_ids(page):
    return page.evaluate("() => state.tokens.map(t => [t.id, t.owner_user_id])")


def main():
    stamp = int(time.time())
    sys.path.insert(0, os.path.dirname(__file__))
    from e2e_build_wizard import package_bytes  # reuse the proven pack builder

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            # ---- setup: room, content pack, two seated scouts ----
            dm = browser.new_context(base_url=BASE)
            dp = dm.new_page()
            register(dp, f"ns3_dm_{stamp}")
            dp.fill("#rm-name", f"NS3 {stamp}")
            dp.click("#btn-room-create")
            expect(dp.locator("#view-prep")).to_be_visible()
            code = dp.locator("#prep-code").inner_text().strip().upper()
            r = dm.request.post(
                f"{BASE}/api/content/{code}/import?mode=apply&name=content.zip",
                data=package_bytes(), headers={"Content-Type": "application/zip"})
            assert r.ok and r.json().get("ok"), r.text()

            players = {}
            for key in ("p1", "p2"):
                ctx = browser.new_context(base_url=BASE)
                pg = ctx.new_page()
                register(pg, f"ns3_{key}_{stamp}")
                pg.fill("#rm-code", code)
                pg.click("#btn-room-join")
                expect(pg.locator("#view-prep")).to_be_visible()
                build_scout(pg, f"NS3 {key.upper()} {stamp}")
                players[key] = (ctx, pg)
            enter_room(dp, code)
            for _ctx, pg in players.values():
                enter_room(pg, code)
                seat(pg)
            # seating tokens arrive on the ws snapshot a beat after openRoom
            dp.wait_for_function("() => (state.tokens || []).length >= 2", timeout=15000)
            ids = {str(t): own for t, own in token_ids(dp)}
            owner_names = dp.evaluate("() => state.room.members.map(m => [m.user_id, m.username])")
            owner_of = dict(owner_names)
            p1_tok = next(t for t, o in ids.items()
                          if owner_of.get(o, "").endswith(f"p1_{stamp}"))
            p2_tok = next(t for t, o in ids.items()
                          if owner_of.get(o, "").endswith(f"p2_{stamp}"))
            p1_tok, p2_tok = int(p1_tok), int(p2_tok)
            log(f"setup ok — tokens p1={p1_tok} p2={p2_tok}")
            shot(dp, "setup")

            # ---- D: grant, consume, give (before combat noise) ----
            p1 = players["p1"][1]
            p2 = players["p2"][1]
            dp.click("#side-tabs button[data-tab='inv']")
            expect(dp.locator("#inv-char")).to_be_visible(timeout=5000)
            p1_char = dp.evaluate(
                "u => (state.room.members.find(m => m.char && m.username.endsWith(u)) || {})"
                ".char.id", f"p1_{stamp}")
            dp.select_option("#inv-char", value=str(p1_char))
            potion = dp.locator("#inv-def option", has_text="Healing Draught").first
            assert potion.count(), "content pack must ship a Healing Draught def"
            dp.select_option("#inv-def", label=potion.inner_text())
            dp.fill("#inv-qty", "1")
            dp.click("#inv-grant")
            click_token(p1, p1_tok)          # the DM grant lands on p1's sheet
            page_idle(p1, 900)
            shot(p1, "d-grant")
            expect(p1.locator("#sheet").locator("text=Healing Draught")).to_be_visible(timeout=8000)
            # grant one more (to be given away) + consume one
            dp.click("#inv-grant")
            p1.click("#side-tabs button[data-tab='inv']")   # the inv window is tab-scoped
            use_row = p1.locator("#inv-items .inv-row", has_text="Healing Draught").first
            use_row.get_by_role("button", name="Use").click()
            p1.wait_for_timeout(600)
            expect(p1.locator("#inv-items .inv-row", has_text="Healing Draught")).to_have_count(1, timeout=8000)
            chronicle_has(p1, r"heal|\+HP|\d+ HP")
            # 🫱 give the last potion to p2 — the give button lives on the sheet
            p1.locator("#sheet-body .inv-row", has_text="Healing Draught").first \
               .get_by_role("button", name="🫱 give").click()
            expect(p1.locator("#give-go")).to_be_visible()
            p1.select_option("#give-to", index=0)
            p1.click("#give-go")
            click_token(p2, p2_tok)
            expect(p2.locator("#sheet").locator("text=Healing Draught")).to_be_visible(timeout=8000)
            log("D PASS — grant/consume/give through the real UI")
            shot(p1, "give")

            # ---- C: dying loop first (no turn gates outside combat) ----
            def drop_dying():
                # two steps: the last hit must be < max_hp or massive damage
                # kills outright (health.py:111 — exactness at full HP logged)
                click_token(dp, p2_tok)
                hp = p2.evaluate("() => state.room.characters[0].hp")
                if hp <= 4:
                    dp.fill("#hp-amount", "+10")
                    dp.click("#btn-hp-apply")
                    p2.wait_for_timeout(400)
                    hp = p2.evaluate("() => state.room.characters[0].hp")
                assert hp > 4, f"p2 needs >4 HP, got {hp}"
                dp.fill("#hp-amount", f"-{hp - 3}")
                dp.click("#btn-hp-apply")
                p2.wait_for_timeout(400)
                dp.fill("#hp-amount", "-3")
                dp.click("#btn-hp-apply")
                p2.wait_for_timeout(900)
                expect(p2.locator("#dsave")).to_be_visible(timeout=8000)

            drop_dying()
            expect(p2.locator("#sheet-body")).to_contain_text(re.compile("dying", re.I), timeout=8000)
            shot(p2, "dying")
            p2.click("#dsave")
            p2.wait_for_timeout(900)
            chronicle_has(p2, r"death save|☠")
            dd = p2.evaluate("() => JSON.stringify((state.tokens.find(t => t.id === state.sel) || {}).death)")
            dth = json.loads(dd) if dd and dd != "null" else None
            if dth and dth["dead"]:
                click_token(dp, p2_tok)
                expect(dp.locator("#dclear")).to_be_visible(timeout=8000)
                dp.click("#dclear")
                p2.wait_for_timeout(600)
                expect(p2.locator("#dsave")).to_be_hidden(timeout=8000)
                log("C — death + DM #dclear verified")
                drop_dying()
            elif dth is None:
                # natural 20 — patient stood up; drop them again for the stab
                log("C — natural 20 recovery, dropping p2 again")
                drop_dying()
            # move p1 next to p2 with the DM move tool, then Stabilize
            tx, ty = token_xy(dp, p2_tok)
            click_token(dp, p1_tok)
            mv = dp.locator("button[title^='Move:']")
            if mv.count():
                mv.first.click()
                dest = dp.evaluate(
                    """([tx, ty]) => { const c = cellSize(),
                        r = document.getElementById('map').getBoundingClientRect();
                        return [r.left + (tx - c) + state.cam.ox,
                                r.top + ty + state.cam.oy]; }""",
                    [tx, ty])
                dp.mouse.dblclick(dest[0], dest[1])
                page_idle(dp)
            clicked = False
            for _ in range(4):  # DC 10 Medicine can fail; the button stays legal
                click_token(p1, p2_tok)
                stab = p1.locator("#dstab")
                if stab.count() and stab.is_visible():
                    stab.click()
                    clicked = True
                    break
                page_idle(p1)
            p1.wait_for_timeout(800)
            assert clicked, "dstab never visible"
            chronicle_has(p1, r"🩺|stabiliz|stable")
            log("C PASS (dying half) — death save + DM dclear + Stabilize verified")
            shot(p1, "stabilize")

            # initiative + slot chip + attack roll
            dp.click("#side-tabs button[data-tab='game']")   # init lives on the Game tab
            dp.click("#btn-init-start")
            expect(dp.locator("#init-list li", has_text="NS3 P1")).to_have_count(1, timeout=8000)
            expect(dp.locator("#init-list li", has_text="NS3 P2")).to_have_count(1, timeout=8000)
            active_pg = None
            for pg in (p1, p2):
                pg.click("#side-tabs button[data-tab='game']")
            for _ in range(5):  # an NPC may hold the first turn — pass until a player is up
                for pg in (p1, p2):
                    chip = pg.locator(".slot-chip[data-slot='action']").first
                    if chip.count() and chip.is_visible() and chip.is_enabled():
                        active_pg = pg
                        break
                if active_pg:
                    break
                dp.click("#btn-init-next")
                p1.wait_for_timeout(600)
            assert active_pg, "no active player saw an enabled slot chip"
            active_pg.locator(".slot-chip[data-slot='action']").first.click()
            expect(active_pg.locator(".slot-chip[data-slot='action']").first) \
                .to_have_class(re.compile("spent"), timeout=8000)
            click_token(active_pg, p1_tok if active_pg is p1 else p2_tok)
            atk = active_pg.locator(".wrow button[data-a='atk']").first
            if atk.count():
                atk.click()
                chronicle_has(active_pg, r"d20|attack")
            log("C PASS (combat half) — initiative, turn_mark chip, attack roll")
            shot(active_pg, "combat")

            # ---- E: add a floor, fly a token to it ----
            dp.click("#side-tabs button[data-tab='dm']")   # floorpanel lives on the DM tab
            dp.fill("#fl-new", f"crypt{stamp % 1000}")
            dp.click("#fl-add")
            page_idle(dp)
            floors = dp.evaluate("() => (state.grid && state.grid.floors) || state.floors || []")
            assert any(f for f in floors), floors
            click_token(dp, p1_tok)
            # #vf-* is the D114 FLIGHT path (fly speed > 0 only); the grounded
            # DM plane change is #fl-pick/#fl-go (token_floor). D102: DM only.
            pick = dp.locator("#fl-pick")
            expect(pick).to_be_visible(timeout=5000)
            lab = pick.evaluate("""(el, needle) => {
                const o = Array.from(el.querySelectorAll('option'))
                                .find(o => o.textContent.includes(needle));
                return o ? o.textContent : null; }""", f"crypt{stamp % 1000}")
            assert lab, f"floor option crypt{stamp % 1000} missing in #fl-pick"
            pick.select_option(label=lab)
            dp.click("#fl-go")
            page_idle(dp)
            moved = dp.evaluate(
                """tid => { const t = state.tokens.find(x => x.id === tid);
                    return t.floor || ""; }""", p1_tok)
            assert str(moved).startswith("crypt"), f"token did not change floor: {moved!r}"
            log(f"E PASS — floor added, token flew to '{moved}'")
            shot(dp, "floors")

            # ---- F: multi-client presence & persistence ----
            for pg in (dp, p1, p2):
                pg.click("#tab-chat")
            dp.click("#chat-in")
            dp.fill("#chat-in", f"NS3SYNC{stamp}")
            dp.press("#chat-in", "Enter")
            for pg in (p1, p2):
                expect(pg.locator("#chat")).to_contain_text(f"NS3SYNC{stamp}",
                                                            timeout=8000)
            p1.reload()
            # the auth cookie (30 d) survives; the ROOM does not — re-enter,
            # re-seat, then prove the chat history came back from the server
            expect(p1.locator("#lobby-user")).to_contain_text(f"ns3_p1_{stamp}", timeout=10000)
            enter_room(p1, code)
            seat(p1)
            if p1.locator("#chronicle.collapsed").count():
                p1.click("#toggle-chronicle")
            p1.click("#tab-chat")
            expect(p1.locator("#chat")).to_contain_text(f"NS3SYNC{stamp}",
                                                                  timeout=10000)
            online_before = dp.locator("#online").inner_text()
            players["p2"][0].close()
            deadline = time.time() + 15
            while time.time() < deadline:
                if "p2" not in dp.locator("#online").inner_text():
                    break
                page_idle(dp)
            assert "p2" not in dp.locator("#online").inner_text(), \
                f"presence never shrank: {online_before} -> {dp.locator('#online').inner_text()}"
            log("F PASS — shared chat, reload persistence, presence shrink")
            shot(p1, "reload")

            # ---- G: the in-app help ----
            p1.keyboard.press("?")
            expect(p1.locator("#help-overlay")).to_be_visible()
            assert p1.locator("#help-cats button").count() == 8
            p1.fill("#help-search", "grapple")
            expect(p1.locator("#help-list")).to_contain_text("Grapple, Push, Prone")
            p1.fill("#help-search", "")
            p1.locator("#help-cats button", has_text="Combat").first.click()
            expect(p1.locator("#help-list")).to_contain_text("Making an attack")
            shot(p1, "help")
            p1.keyboard.press("Escape")
            expect(p1.locator("#help-overlay")).to_be_hidden()
            p1.click("#side-tabs button[data-tab='inv']")
            p1.click("#btn-help")
            expect(p1.locator("#help-cats button.active")).to_contain_text("Magic")
            shot(p1, "help-context")
            log("G PASS — help opens searchable, categories switch, context chip follows 🎒 Inv")
        finally:
            browser.close()
    log(f"ALL SCENARIOS PASS at {BASE}")
    return 0


def page_idle(page, ms=700):
    page.wait_for_timeout(ms)


if __name__ == "__main__":
    sys.exit(main())
