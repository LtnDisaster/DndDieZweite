# TODO — D&D VTT (`/home/alp/Test`)

Living checklist. "Done" = shipped and covered by an in-repo test.
Verify state with:

```bash
./.venv/bin/python -m pytest                       # 66 tests (unit + integration)
./.venv/bin/python -m compileall -q app            # byte-compile check
for f in app/static/js/*.js; do node --check "$f"; done   # JS syntax check
```

## Done — features (context anchor)
- [x] Accounts / characters / rooms / join codes / chat / initiative
- [x] Server-authoritative dice, traps, loot, HP (D3, D6)
- [x] Grid editor, fog-of-war terrain patches, per-role map filtering (D4)
- [x] Two-click A* path planning + JS mirror + move HUD (D5, D7)
- [x] Strict radius-6 LOS, targeted token events, last-seen ghosts (D8, D9)
- [x] Armor & magic items: AC math, attunement cap 3, potions/heal, charges+recharge, identify/masking (D10-D13)
- [x] Weapon `+N` bonus, attack ability override, ability-on-any-roll (D12)

## Done — maintainability / security / testing refactor (2026-09-29)
- [x] Backend split `app/room/*` behind a thin `ws.py` + re-export shim (D16); live suites unchanged
- [x] SQLite autocommit + `tx()` BEGIN IMMEDIATE for multi-statement writes (D17)
- [x] Per-room `map_lock` + single-UPDATE atomic item use (D18)
- [x] Security: login/register rate limit, conditional `Secure` cookie, peer-notes stripped in
      `/state`, last-seen prune on disconnect, generic-500 + logging, non-dict WS ignore (D19)
- [x] Frontend split into dependency-ordered classic scripts under `app/static/js/` (D20)
- [x] **In-repo pytest integration suite** (`tests/test_integration.py`) — auth/authz, hidden-info
      masking, malformed-message resilience, DM-only guards, LOS/fog filtering, atomic item use,
      attunement cap (resolves old TODO-1 "port the /tmp smoke suites")
- [x] Docs updated: README layout/config/tests; DECISIONS D16-D20 + revised D3/D8/D13/D14

## Done — gameplay additions (2026-09-29)
- [x] Traps/loot placeable via **inline editor fields** (no more blocked `prompt()`) (D21)
- [x] **Round-based initiative**: roll once, `init_end_round` advances the round + returns
      to the leader; UI shows `— Round N —` and an **End round** button (D22)
- [x] **Skills** (18 5e skills, prof/expertise, rollable) (D23)
- [x] **Spellbook + slots**: spell editor, per-level slots, sheet Spellbook gated on a
      📖 spellbook item, Cast/Atk/DC/Dmg buttons, slot consumption + empty-slot refusal (D23)
- [x] **More item kinds** incl. **shield** (adds AC when identified), wand/staff/scroll/
      ring/tool/wondrous/spellbook, with sheet icons (D23)
- [x] **🛌 Long rest** (DM) restores spell slots + `recharge` items
- [x] Safe SQLite migration added for `characters.skills/spells/spell_slots` (non-destructive)
- [x] Tests expanded: gear/dice unit + integration (rounds, skill+cast+slot, trap place+trigger)

## P1 — Repo hygiene
- [ ] Add a `Makefile`/`scripts/smoke.sh`: start (pidfile) -> live `vtt_smoke*.mjs` -> stop
      (the `.mjs` suites stay a **dev-only** live-server harness; `pytest` is the durable suite).
- [ ] Pin exact Python/FastAPI/uvicorn/starlette versions (`requirements.lock`) for reproducible CI.
- [ ] Optional CI job: `pytest` + `compileall` + `node --check` on push.

## P2 — Known soft spots (call out before touching)
- [ ] **Pathfinding drift:** server `path.py` vs client `findPathJS` are two copies of one
      algorithm. Unit tests cover each independently (`test_path`) but there is **no cross
      parity test** — add one, or generate the JS from the Python source.
- [ ] **Ghost persistence:** `_last_seen` is in-memory (D9) — lost on restart, wrong under
      multi-worker. Persist to `room_state`/DB before scaling beyond one process.
- [ ] **Vision model:** currently a Chebyshev square that ignores walls — consider true
      shadow-casting LOS and/or a circular radius.
- [ ] **Client math mirror:** the browser mirrors gear skill/spell bonus math (`_smod`/`_pb`
      in `js/10_core.js`) for previews only; the server recomputes authoritatively — keep the
      two in sync (same drift risk as the A* mirror in P2).
- [ ] Re-run the live suite 1 after ANY default-grid/token-position change (D15: movement
      tests are vision-adjacent).

## P3 — Feature gaps (nice, not blocking)
- [ ] Consumable potions (remove on last use) — currently charges-only, potions aren't deleted.
- [ ] Attunement UX: warn/gate attuning to an *unidentified* magic item.
- [ ] Per-party (vs per-item) knowledge of identified items; party shared notes.
- [ ] Cross-tab / reconnect: seed ghosts more robustly; multi-socket-per-user testing.
- [ ] Browser e2e (Playwright) for canvas: route preview + ghost rendering — the JS split is
      verified by parity + `node --check` + the WS/REST suites, **not** by a real DOM/canvas test.

## Watch / intentionally not done
- [ ] Horizontal scale-out (blocked by D9 + single-loop design).
- [ ] No build step introduced on purpose (D1) — don't add a bundler/module loader without
      revisiting D1 and D20.
- [ ] Auth is single-tenant local; no OAuth/2FA planned.
