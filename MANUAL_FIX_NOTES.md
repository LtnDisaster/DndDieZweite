# Gameplay & World sprint (2026-10-06) — DM log, modifiers, auto-map, terrain, elevation, forced moves

Canonical suite now: **306 passed + 7 node-skipped** (host 313). Decision records D66–D71.

## Manual browser checklist (pixels/rules cannot be fully auto-tested)
1. **DM Game Log must NOT grow on dice rolls.** DM+player windows: roll several
   dice from the DM panel while the player has the Game Log tab open — the
   chronicle keeps its height (only the internal list scrolls); Chat and Dice
   tabs unaffected; switching Chat→Log→Dice→Chat keeps each surface stable.
2. **PC/NPC modifier parity.** Character with STR 12 + proficient save: the
   save roll result must include +1 (total = prof + stat mod), identical to an
   NPC sheet with the same ability. Check a spell attack/DC display too.
3. **Automatic world growth.** Player walks toward the north edge: on reaching
   the trigger band the map extends by a chunk — camera stays stable (no jump),
   old explored fog stays at the SAME world place, new land is dark floor.
   NPCs/DM tokens walking near edges never grow anything; a DM forced-push of a
   PC token to the edge never grows either (D71).
4. **Terrain brushes.** Map editor: 🚧 barrier blocks walking but you can see
   through it; 🪨 low obstacle is walkable and the move HUD shows the doubled
   cost (e.g. 7/6 squares for a crossing route).
5. **Elevation brushes.** ⛰️+/⛰️−: one-step heights are walkable (HUD normal),
   two-step cliffs make previews refuse; the corner label shows +N/−N per cell;
   players only see heights in explored fog; a token moved onto a +2 plateau
   shows z=2 in its data (state/sheet), back on ground z=0.
6. **NPC movement modes.** NPC editor: Spd plus new fly/swim/climb fields;
   values persist across save/reopen; walk stays the budget currency.
7. **Forced moves (DM).** DM drags a monster: right-click/menu not needed —
   forced_move via DM tooling: a shoved PC stops before a wall/cliff/other
   creature (never phases through), the game log shows a DM line, the player's
   own walk budget is untouched.
8. **Budget HUD.** Preview a far route with default speed: HUD shows
   `9/6 squares · beyond speed` style text; the move itself is still allowed
   (combat enforcement is deliberately out of this sprint).

## Root causes fixed this sprint
- DM Game Log growth: content-based flex basis (`flex:1 1 auto` + DM-only
  extra entries) — fixed to zero-basis flex chain (see D65 follow-through).
- Silent +0 modifiers for PCs: raw DB rows (JSON strings) fed into gear math —
  `gear.as_sheet()` choke point (D66).

## Not verified / known
- Diorama mode: barrier/low/elevation cells render as normal floor there
  (grid view carries the new terrain visuals) — diorama polish is future scope.
- Free elevation (floats), multi-floor maps, elevation-based cover: out (D70).
- Fly/swim/climb path rules and forced-move combat integration: FOUNDATION ONLY
  (see TODO.md).

---

# Sidebar layout fix (2026-10-06) — chat/log/dice overlap — ROOT CAUSES
The Docker deploy works; this section covers the UI regression and its
STRUCTURAL fix (no z-index layering). Canonical suite now: **269 passed**
(263 + 6 new `test_layout_pins` static pins).

## What actually caused the overlap
1. `.room-grid { height: calc(100vh - var(--topbar-h)) }` with a GUESSED 56px
   topbar. The real topbar is content-driven (buttons/online list wrap at
   1366px) → sidebar bottom (chat input, dice, party) fell BELOW the viewport.
2. `.side` was ONE scroll column: chronicle (`flex:1; min-height:220px`, with
   the 4-row dice block OUTSIDE its own scroll body) + category panels stacked
   below it. When space ran out, the chat/log scroll area collapsed to a few
   lines — chat, log and dice squeezed the same 220px, everything else lived
   further down the same scroll stream.
3. The category bar `.side-tabs` sat BELOW the chronicle in the DOM and was
   only glued with `position:sticky; top:0; z-index:5` — content slid visibly
   UNDER it, and switching categories reclaimed no area.

## Structural fix (what changed)
- `style.css`: `#view-room` is a real flex shell (`height:100vh`, topbar
  `flex:0 0 auto`, `.room-grid` `flex:1; min-height:0`); `calc(100vh…)` and
  `--topbar-h` DELETED. `.side` no longer scrolls (`overflow:hidden`) — three
  fixed regions: `#side-tabs` (moved to top of `.side`, sticky/z5 rules
  DELETED), `#chronicle` (`flex:1; min-height:0`, the ONE main area), new
  `.side-cat` drawer (initiative/party/chars/story/dm/sheet panels:
  `max-height:46%; overflow-y:auto` — bounded, single scroll, never squeezes
  chronicle). `.panel.grow{min-height:220px}` DELETED.
- `index.html`: feed tabs are now **Chat | Game Log | Dice** (`#tab-dice`);
  the dice block moved INSIDE `#chronicle-body` as `#dice-panel` (all ids
  kept: roll-*, qdice, dice-btns), plus `#dice-out` — roll results with own
  scroll (last 50, `aria-live`). `.dice-sep` removed. Category panels wrapped
  in `.side-cat`. No ids removed; `applySideTab` selector still matches.
- `30_room.js`/`60_main.js`: `switchFeed("dice")` + `applyFeedPanels()` —
  exactly one of chat/log/dice visible, composer rows chat-only, feed choice
  persisted (`vtt-feed` localStorage), dice results appended live while the
  dice tab is open. No server/protocol changes; Tactical/Diorama untouched.
- Tests: `tests/test_layout_pins.py` (6 static pins: no faked viewport height,
  region sidebar, feed surface nesting, single-surface switching, no stale
  dice-sep, overlay layers only via vars).

## Browser checklist (please verify — pixels cannot be auto-tested)
- [ ] **1920x1080**: map centered, sidebar fully inside viewport; chat input
      and chronicle bottom edge visible WITHOUT page scroll.
- [ ] **1366x768**: same — nothing below the screen edge; chat scroll area
      still several lines tall; initiative+party visible under it in the
      drawer (drawer may scroll, chronicle must not shrink to nothing).
- [ ] **Narrow window (<900px)**: stacked layout, page scrolls normally,
      chronicle ≥ usable height, tabs wrap.
- [ ] GAME → Chat: history visible, scroll works, channel/whisper + send
      usable; type+send one message.
- [ ] GAME → Log: own scroll area, timestamps; long history scrolls smoothly.
- [ ] GAME → Dice: roll d20 → result appears in the dice panel's output area;
      quick-dice + ability roll work.
- [ ] Switch Chat↔Log↔Dice repeatedly: never two surfaces at once, no blank
      panel, unread counter still lands on Chat.
- [ ] Long chat history + long log: only the inner list scrolls (no sidebar
      double-scroll, no sticky-bar overlap).
- [ ] DM tab (map editor + tool groups) and CHARS/STORY tabs: chronicle stays
      on screen; drawer scrolls independently.
- [ ] Chronicle collapse ▾: hides everything incl. dice; ▸ restores the LAST
      selected tab.
- [ ] Tactical and Diorama: movement/path/fog unchanged.
- [ ] Reload (F5) while on Dice tab: Dice tab is restored (localStorage).

---

# Sprint 9 — Deployment & UX hardening (2026-10-05) — manual review guide
No git was used; review the working tree file by file. Canonical suite:
`docker compose run --rm test` → **263 passed** (256 + 7 node-vm skips) (host venv: same 263).
`node --check` clean on every JS file; `compileall` clean.

## Three REAL root causes found (not test-only)
1. **Intermittent 401 after login (production bug).** `make_token` embedded
   base64 **`=` padding** in the session cookie; cookie parsers drop values
   containing `=`, so ~1 in 3 tokens died at parse time (the flake looked random
   because payload length decided). `app/auth.py` now emits padding-free
   base64url and `read_token` re-pads → deployed padded tokens still verify,
   nobody gets logged out by the upgrade. Test: `tests/test_auth_token.py`.
1b. **Signing key mutated after first use (production bug).** `_secret()`
   returned the RAW 32 random bytes when creating `secret.key`, but every later
   read did `.read().strip()` — and random bytes can BE whitespace (0x0a, 0x20).
   ~1.6% of fresh installs signed with one key and verified with another
   (first session dead; the test flake made it visible). Key is now stored
   HEX-encoded (whitespace-free by construction); legacy raw files still load
   unchanged via the ValueError fallback. Test:
   `test_secret_is_stable_across_generation`.
2. **Suite hangs / lost WS events under starlette ≥1.7.** Each TestClient WS
   session now runs on its OWN event loop; `broadcast()` used to `await
   ws.send_text()` into foreign loops, where anyio wakeups can be lost (idle
   loops + forever-pending receive — captured via `faulthandler_timeout`).
   `app/room/net.py` gained `attach_ws`/`detach_ws` (socket→loop registry) and
   `_send` (same-loop fast path — production ALWAYS — plus threadsafe
   cross-loop delivery for the test harness). `app/ws.py` calls attach/detach.
   This is why the old full-suite runs hung in `test_chat`/`test_integration`.

## Server changes
- `app/room/net.py` — loop registry + `_send`; broadcast discards+detaches dead
  sockets. `app/ws.py` — `attach_ws` after accept, `detach_ws` in finally; NEW:
  WS handshake Origin gate (`_origin_ok`, 4403) before auth-adjacent accept.
- `app/auth.py` — padding-free tokens (D62); `cookie_secure` honours
  `X-Forwarded-Proto` only with `VTT_TRUST_PROXY=1` (D64).
- `app/mapmodel.py` — door sanitize keeps `dm_only`/`secret`; `visible_map`
  never transmits secret doors to players.
- `app/room/doors.py` — player branch: secret → silent (identical to “no door”),
  dm_only → “It won't budge.” BEFORE any lock-state leak; chronicle line
  suppressed for dm_only/secret moves. (Watch indentation of the state/sys_msg
  block — it sits at function level, outside `if opened:`.)
- `app/rooms.py` + `app/main.py` — uploads under `db.DATA_DIR/uploads`, mounted
  at unchanged `/uploads/`; startup mkdir moved to import time.
- `Dockerfile` (NEW multi-stage: `test` stage + runtime, non-root uid 1000,
  HEALTHCHECK, single uvicorn), `compose.yaml` (NEW: app on 127.0.0.1:8000 +
  bind `./data`, `test` under profile), `requirements*.txt` exact pins — note
  the **previously missing `websockets`** package (uvicorn needs it; docker
  runs would have died on first WS connect!).
- `.dockerignore` (NEW — excludes data/.git/.venv but KEEPS tests/ for the
  test stage), `.gitignore` (archives, Zone.Identifier, compose overrides),
  `pytest.ini` (`-o faulthandler_timeout=120`: any future hang dumps stacks).

## Scripts (NEW)
- `scripts/vtt-backup.sh` — sqlite backup API (WAL-safe live), PRAGMA
  integrity_check BEFORE archiving, bundles secret.key + uploads.
- `scripts/vtt-restore.sh` — refuses silently over a live db (keeps
  `vtt.db.pre-restore.*`), deletes stale `-wal/-shm`, integrity-checks result.
- `scripts/move_uploads.py` — idempotent legacy upload migration (app tree →
  data dir). `scripts/make_release.sh` — clean source tar + forbidden-path guard.

## Client changes
- `style.css` — token block (spacing/side width/z-scale, defines `--muted`),
  one `.wlabel` definition (was duplicated with different values), sticky
  `#side-tabs` with real active state, `details.group` + `.sheet-sec`,
  `.dice-sep`, toast z above movehud, 1100px media, 900px room-grid un-squeeze.
- `index.html` — sidebar tab roles, dice toolbar separated, DM panels in
  collapsible groups (all ids kept), door editor gains DM-only + hidden
  checkboxes, help text (doors/NPC workflow).
- `30_room.js` — NPC sheet re-sectioned (**every `#npc-*` id preserved**, the
  pinned `clsTxt` guard untouched); PC sheet Skills/Spellbook `details.sheet-sec`;
  `applySideTab` maintains `aria-selected`.
- `50_canvas.js` — `doorEdit` sends dm_only/secret; `drawDoor` renders DM-side
  ghosting for secret and purple for dm_only.

## Tests added (21 total)
`tests/test_auth_token.py` (5) · `tests/test_deploy_hygiene.py` (6) ·
`tests/test_doors_dmonly.py` (10). Diagnostic evidence kept in `tmp/byfile/`.

## Not verified / known
- Host lacks docker buildx → classic builder used (`DOCKER_BUILDKIT=0`).
- Browser hand-tests pending (see chat report) — DOM layout changes verified by
  code review + pin tests only.
- `#editor` inside the DM tab remains a JS-toggled block (not `<details>`) by
  design; its show/hide button drives visibility.

---

# Sprint 11 — CRITICAL MANUAL-TEST REGRESSION SPRINT (D75–D77)

## Root causes (empirically proven, not assumed)
1. **Player black screen**: no client ever framed the camera. `openRoom` left
   cam (0,0); the player's LOS ring around their token was off-viewport and
   unknown cells paint nothing → black. DM unaffected (own cam already panned,
   DM sees everything). Proven: Node-vm run of the REAL renderers with a
   player payload — token deep in world + cam(0,0) = 1 painted tile.
2. **Diorama one-way/interaction**: iso projection without fit left ~3 of 126
   tiles on screen; panning was middle/right-click only → black canvas,
   nothing clickable; the topbar switch worked the whole time (chrome is
   outside the canvas and was never covered — now also pinned by a test).
3. **No room deletion existed** — no endpoint, no UI (feature gap, not a
   regression).
4. Relationship to expansion/origin work: none of the six symptoms traced to
   the D72 coordinate invariant itself (DM/Player payload probe: consistent);
   the expansion machinery, being unverifiable in-browser, is flag-OFF by
   default (D77) per the human's fixed-map preference.

## Fixed
- `10_core.js` — per-mode camera slots (camT/camD), save/restore in
  `setViewMode` (T→D→T round-trip guaranteed), `roomDeleted` state.
- `50_canvas.js` — `centerOnMyToken`/`fitDiorama`/`initViewCam` (framing only,
  reveal nothing via `visibleHere` reuse), `?debug` HUD + painted-tile counter.
- `30_room.js`/`20_lobby.js` — framing after `resize()` in openRoom and on
  Bring/assign; **lobby two-step Delete** for DM rooms.
- `40_ws.js` — `room_deleted` → lobby + no reconnect; onclose reconnect guard.
- `rooms.py` — `DELETE /api/rooms/{code}` (creator-DM only, full cascade, own
  map_image file only, idempotent 404).
- `net.py` — `purge_room_nowait`: owner-loop closes, `Task.get_loop` walk
  cancels, registry purge; NOT dependent on lifespan LOOP (TestClient-safe).
- `ws.py` — teardown checks room row before bookkeeping (FK/zombie fix).
- `mapmodel.py`/`growth.py` — `AUTO_GROW` feature flag, default OFF (env
  `DNDTABLE_AUTO_GROW=1` to re-enable).

## Tests added
`tests/test_room_delete.py` (4) · `tests/test_player_view.py` (4) ·
3 new renderer-framing + chrome-pin tests in `tests/test_view_mode.py`.

## Status
Canonical run: **322 passed, 9 skipped** (node-harnesses skip without node),
single run, no retries. Manual 14-step smoke checklist:
`MANUAL_BROWSER_CHECKLIST.md` — human browser verification PENDING (automated
tests prove mechanics, not pixels).

---

# Sprint 12 — Frontend deployment integrity (D78): the black canvas was a MIXED BUNDLE

Human browser error (verbatim): `ReferenceError: gridOrigin is not defined`
— the smoking gun. New `50_canvas.js` + stale cached pre-D72 `10_core.js`
(no `gridOrigin`): every draw threw, the render loop died silently, Bring
succeeded server-side (live-DB verified) but the follow-up client error made
it look like "grid not found". Root mechanism: assets served under unchanged
URLs with no cache headers -> browsers mixed generations after rebuilds.

## Fixed / shipped
- `app/buildinfo.py` — ONE build token = sha256 over all owned JS/CSS +
  index.html, computed once per process; `/api/build` publishes token +
  per-file hashes (no paths, no secrets); startup logs `BUILD <token>`.
- `main.py` — `/` renders `__BUILDTOKEN__` into every asset URL and inline
  `window.__BUILD__`; middleware sets `Cache-Control: no-cache` on `/` and
  everything under `/static/`.
- `index.html` — tokenised asset URLs, inline `window.__BUILD__` stamp and an
  EARLY `error`/`unhandledrejection` capture (`window.__BOOTERRORS`) that
  predates every module, so generation-one crashes are recorded, not silent.
- Every module stamps `window.__BUILDS["<file>"]` (env-guarded for node-vm).
- `60_main.js` — boot extracted to `appBoot()`; `99_boot.js` (loaded LAST)
  runs the integrity gate: required globals present, all modules stamped,
  every fetched `/static/js/*` URL carries the current token, server token ==
  page token (async `/api/build`). Mismatch => red banner + console + NO boot.
  Coherent => `appBoot()` exactly as before.
- Bring path (`30_room.js`, `20_lobby.js`, `openRoom`) — authoritative result
  and presentation result separated: placement success toasts first, camera
  errors afterwards are labelled as view problems, never as Bring failures.
- `?debug` HUD — adds build token, integrity state (ok/FAIL/DRIFT),
  grid present, bring last result/error, last client/boot exception.

## Tests added
`tests/test_frontend_bundle.py` (8): load-order dependency scanner with
negative control reproducing the exact incident, served-index token binding
(mixed tokens impossible), `/api/build` identity + no-leak, no-cache headers,
gate-is-last/owns-boot, all-modules-stamp.

## Status
Manual browser verification PENDING (human): rebuild, then run the new
checklist beginning (BUILD token + /api/build + asset URLs + no banner) before
any gameplay step. Automated tests cannot prove the browser's cache story —
the checklist's step 1–5 can.

---

# Sprint 13 — Combat turn & movement loop completed in place (D79)

The D74 engine was fully written but never wired whole: `end_turn`, `dash`
and `turn_mark` had no dispatch registration (dead handlers), and the turn's
`move_total` carried FEET while `walk()`/preview priced routes in movecost
SQUARES — a 30-ft token could walk 30 squares per turn and `within_budget`
lied in combat.

## Fixed / shipped
- `combat.py` — turn money is movecost units: `begin_turn` seeds
  `move_total = movecost.walk_budget(speed)`; Dash now spends the ACTION
  (D74-era bonus usage corrected) and adds one turn-speed of units for THIS
  turn only (stored speed untouched; no second dash once the Action is used).
- `dispatch.py` — `end_turn`, `dash`, `turn_mark` registered; the completed
  handlers (owner-of-active-turn / DM exempt, slot marking, broadcasts) go
  live against the ONE initiative object.
- Client turn bar (`30_room.js renderInit`, `index.html #turn-bar`,
  `style.css` chips) — active token, movement remaining/total, A/B/R chips
  (owner/DM can mark), Dash + End Turn where appropriate. Pure rendering of
  the authoritative `initiative` payload; Diorama/Tactical share it.

## Tests added
`tests/test_combat_turn.py` (11): exploration unlimited; combat move charges
the budget in the SAME units (3 steps → move_spent 3, move_total pinned at
walk_budget(30)=6); over-budget walk stops at the budget with reason=budget
at the right cell; inactive listed combatant blocked; preview reports
cost/remaining/within_budget in cost units; Dash (action spent, +6 units,
stored speed untouched, no second dash, not-on-own-turn refused); End Turn
(advances, next gets fresh 6/x + available slots; stranger refused); full
round resets resources. `test_view_mode.py`: view round-trip never mutates
initiative/plan/token positions.

---

# Sprint 14 — Conditions connected to the turn lifecycle (D80)

The D74/D79 turn loop worked but conditions only had a round clock, no
turn-anchored durations existed, "incapacitated" was decorative (movement was
gated only at 0 HP), and prone had no mechanical ending.

## Fixed / shipped
- `conditions.py` — every entry is now `{k, rounds, until}`; `until` selects
  the condition's ONE clock ("": round, "start"/"end": own turn clock via new
  `step_turn`). Round and turn clocks provably never touch the same entry.
- `room/combat.py` — the turn lifecycle is ONE function `advance_turn`
  (end hooks of the leaving token → advance → round clock on wrap → start
  hooks of the new token → fresh resources); `init_start/next/end_turn/
  end_round` all consolidated onto it (three duplicated wrap blocks removed).
- `room/movement.py` — the voluntary-movement gate now covers the
  incapacitated family (incapacitated/unconscious/paralyzed/stunned/
  petrified) next to 0 HP; entry-checked AND re-checked on every walk step.
  DM moves and forced movement (`moveforced`) are separate authority paths.
- `room/conditions.py` + `dispatch.py` — new `stand` handler: prone only,
  never moves the token, free outside combat; in own combat turn charges
  `ceil(walk_budget/2)` of the BASE (Dash-independent) through the ONE
  `spend_move` accounting; every validation runs before prone is removed.
- Client (Tactical): condition chips show `(Nr)` / `→turn start|end`,
  a "Stand Up" button appears exactly when legal to try, and the condition
  editor got an expiry select. Reconnect replays conditions from the token
  DB (nothing lives in the DOM).

## Tests added
`tests/test_conditions_lifecycle.py` (15): exact round-clock expiry; start-
anchor ticks only at own turn starts (wrap never touches it); end-anchor
expires exactly at the turn end; both clocks on one token with per-step
delta checks; exploration never advances durations; downed cannot move but
forced movement works; unconscious blocks and unblocks movement; stand free
outside combat (and "Not prone" rejection); combat stand costs 3/6 and the
rest still walks; rejection without budget keeps prone; Dash keeps the BASE
cost; not-on-own-turn rejected; downed cannot stand; reconnect replays full
condition state; End Turn resets resources after hooks ran. Three
`test_integration` pins updated to the 3-field condition schema.

---

# Sprint 15 — Rectangular token footprints (D81)

Footprints were square-only (size category ⇒ n×n); a 3×7 serpent could not
exist, and every consumer (A*, collision, fog growth, vision, rendering)
threaded a single `side` integer.

## Fixed / shipped
- `db.py` — `tokens.fw`/`tokens.fh` (NULL = square of size category) added via
  the existing migration helper; every existing token loads unchanged.
  Width/height clamp 1..10; changing the size category clears the custom span.
- `footprint.py` — `token_span()` is THE rectangle derivation (fw/fh win,
  category fallback); `wh()` normalizes the legacy side-int parameters into
  (w, h); anchor extends right/down. All geometry functions accept either.
- `path.py`, `movecost.py`, `mapmodel.growth_needed` — same single normalizer;
  the conservative diagonal mid-footprint rule and the "any newly entered cell
  is difficult" rule generalize without touching A* semantics or costs.
- `movement/visibility/doors/encounters/ws/rooms` — the eight SELECT column
  lists and the bring-back/reveal paths carry fw/fh; hidden NPC tokens leak no
  shape to players (size, fw, fh all popped).
- NPC editor — Width/Height number inputs beside the existing size select;
  add/update accept the span and re-place via the shared find_valid_origin.
- Client — `tokenSpan()` mirrors the server derivation; render rect, hit
  testing, path-preview goal marker and the plan payload (w/h) all follow the
  real footprint. Diorama untouched (renders the category square as before).

## Tests added
`tests/test_footprint_rect.py` (16): exact 21-cell sets for 3×7 and 7×3 (and
their inequality), 1×1/2×2 squares, independent-edge clamp; a 3×7 NPC blocked
by a 2-row corridor while an Imp walks the same corridor; the same Ogre walking
a 7-row gate with preview cells including the far row; preview and execution
agree on a refused goal; two 3×7 spawns never overlap and a far-cell teleport
onto the rectangle is rejected; trap still springs only on the anchor step
(footprint rows do NOT), the shared occupied_cells intersection fires on a far
row; vision source cells = full rectangle and strictly more world in view;
category change clears fw/fh; /state round-trip keeps the shape; legacy square
tokens untouched; client tokenSpan parity (node).

---

# Sprint 15B — Recovery: invisible Tactical tokens + undiscoverable footprint UI

## Root cause A (ALL tokens invisible)
Sprint 15's render-loop edit declared `const [w, h] = tokenSpan(t)` INSIDE the
token loop whose scope owns the VIEWPORT dimensions `w`/`h`; the culling
`continue` two lines below (`tx > w+80 || ty > h+80`) therefore compared
against the token's own span — every token more than ~81 px from the canvas
origin was skipped. No console error (legal JS), map fine, tokens gone.
Fixed by renaming the loop variables to `tw`/`th`; pinned by a static
regression-class test plus a node harness that runs the real client
`tokenSpan` over real snapshot tokens (legacy 1x1/2x2 must be visible,
3x7/7x3 must be correct).

## Root cause B (no way to edit width/height)
The inputs were only in the NPC stat-block sheet (DM-owned monster tokens).
Any other selected token — including one's own — opens the character sheet,
which had nothing. Now: a labelled **Footprint W/H + Apply** row at the top of
the normal sheet for every token you may control (DM any token, player own
token), driving the new server operation `token_span` (D81 amendment):
owner check, 1..10 integers, COMPLETE rectangle validated at the token's
CURRENT anchor via the shared footprint helper — an invalid resize is rejected
with old dimensions and position untouched (no relocation, ever). Successful
resize broadcasts `token_span`; sheet and canvas update live and a fresh
snapshot keeps the shape. `update_npc` now follows the same in-place rule when
the span or size category changes.
