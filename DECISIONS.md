# Architecture Decision Records — D&D VTT (`/home/alp/Test`)

Purpose: capture the decisions taken while building this app so later instances
(human or AI) can recover the *why* without re-deriving it from code.
Each record: Context → Decision → Alternatives → Consequences → Status.

Last touched: 2026-09-29 (traps fix + round-based initiative + skills/spellbook/items).
Current test status: `pytest` **66 passed** (unit + in-repo integration). Dev-only live
WS smoke suites (still in `/tmp/opencode/`) re-run green after these changes.

## D1 — Tech stack: FastAPI + WebSockets + SQLite + vanilla JS
- **Context:** Self-hosted multiplayer VTT, must run anywhere with one command, no build toolchain.
- **Decision:** FastAPI + `uvicorn`, stdlib `sqlite3` (WAL), browser WebSocket, canvas SPA with no bundler/framework.
- **Alternatives:** Node/Socket.IO, React+Vite, Postgres.
- **Consequences:** Zero build step (`./run.sh`); single Python process; frontend is split into classic (non-module) `<script>` files under `app/static/js/` loaded in dependency order (shared global scope, no bundler).
- **Status:** Accepted.

## D2 — Auth: bcrypt + HMAC-signed 30-day cookie
- **Context:** Local single-tenant install; want stateless sessions, no DB session table.
- **Decision:** `auth.py` hashes passwords with bcrypt, signs an `HttpOnly` `vtt_session` cookie with a key in `data/secret.key`.
- **Status:** Accepted.

## D3 — Everything authoritative is server-side
- **Context:** VTT cheating is trivial if clients compute results.
- **Decision:** Dice, A* pathfinding, HP deltas, trap/loot resolution, item math (AC/heal/charges/attunement) are computed in `app/room/*` and `gear.py`, never trusted from the browser.
- **Consequences:** Slightly chattier protocol; clients are dumb renderers. This is the load-bearing security decision.
- **Status:** Accepted.

## D4 — Grid + fog model, per-role map filtering
- **Context:** Need hidden traps/loot and fog-of-war that never leak secret data to players.
- **Decision:** `mapmodel.py` holds `cells` (0 floor/1 wall/2 difficult), `traps`, `loot`, an `explored` bitmap, radius-6 reveal streamed as *terrain patches* (`explored` events carry `{cells, terrain}`). `visible_map(mp, uid, is_dm, owned)` filters per recipient.
- **Consequences:** Unexplored terrain/traps/loot are never serialized to a player; fog lifts live during a walk.
- **Status:** Accepted.

## D5 — A* pathfinding: 8-dir, no corner-cutting, difficult terrain ×2, `max_steps=400`
- **Context:** Server must move tokens along legal, believable paths.
- **Decision:** `path.py::find_path` (octile costs 10/14, walls block, difficult terrain doubles step cost, no diagonal corner cutting, 400-step cap).
- **Consequences:** The **client preview must mirror this exactly** (D7). Two implementations of one algorithm = drift risk (see TODO).
- **Status:** Accepted.

## D6 — Movement protocol: per-step events + DM teleport
- **Context:** Animate server walks; DM needs instant reposition.
- **Decision:** `{type:"move", token_id, tx, ty, teleport?}`; server walks emitting `step {token_id,x,y,cx,cy}`; `teleport` honored only for DM.
- **Status:** Accepted.

## D7 — Two-click confirm movement (players)
- **Context:** Users asked for a *visible, changeable* route before committing; drag-and-drop commits too eagerly and mis-moves.
- **Decision:** First empty-cell click **plans** (gold route preview via a JS A* mirror `findPathJS` in `js/50_canvas.js`); second click on the same cell (or the floating `#movehud` **Move** button) commits; other cell re-plans; `Esc`/Cancel aborts. Player **drag** sets a plan instead of auto-moving. DM keeps drag = teleport.
- **Alternatives:** Drag-to-commit (rejected: too easy to mis-drop), hover-preview-only (rejected: no explicit confirm).
- **Consequences:** Player and DM movement diverge; preview is advisory — server re-runs authoritative A* and may still reply "No path there".
- **Status:** Accepted.

## D8 — Strict line-of-sight, targeted token events, last-seen ghosts
- **Context:** Requirement: out-of-sight movement of *anyone* (incl. allies) must not leak; sight should fade to a "memory".
- **Decision:** Vision radius `VISION_R = 6` (Chebyshev). Replaced global broadcasts with `app/room/visibility.py::send_token_event`, which per viewer decides: first sight → `token_add`, subsequent → `step`, losing sight → `token_leave`, deletion → `token_gone`. Server keeps `_last_seen[room][viewer][token]` snapshots; `/state` returns LOS-filtered `tokens` plus `ghosts` (`ghost:true`, pinned to last-seen x,y). Client renders ghosts as faded dashed circles and keeps them live via `token_leave`.
- **Alternatives:** Broadcast-all-and-hide-in-DOM (rejected: leaks over the wire), true shadow-casting LOS (deferred — see TODO).
- **Consequences:** Out-of-sight tokens are never transmitted (strong leak-prevention); more per-viewer compute per step.
- **Status:** Accepted.

## D9 — Ghost state is in-memory (`_last_seen`), single-process
- **Context:** Ghosts are derived/ephemeral.
- **Decision:** `_last_seen` lives only in the `ws` process.
- **Consequences:** Ghosts vanish on server restart and would be wrong under multiple uvicorn workers / multi-process. Acceptable for a single-instance self-host; revisit before horizontal scaling.
- **Status:** Accepted (with caveat).

## D10 — Items model in `gear.py` (SSOT for item math)
- **Context:** Armor/magic items requirement; want one place for AC/attunement/charge logic on both REST and WS paths.
- **Decision:** `characters.items` is a JSON column; `gear.clean_items` normalizes/clamps and guarantees ids; `compute_ac`, `attuned_count`, `ATUNE_MAX=3`, `mask_items`. AC rules: **no armor → sheet AC as-is**; light armor adds full DEX mod; medium/heavy do not; `acBonus` counts only when `identified`. Magic items may start **unidentified**; `mask_items` reduces them to "Unidentified item" for viewers who mustn't know them.
- **Status:** Accepted.

## D11 — Per-viewer item masking in `/state`
- **Decision:** DM sees everything; a player sees real items for **their own** character but masked unidentified-magic for everyone else (`mask_items = role!="dm" and member.user_id != viewer`).
- **Consequence:** DM can **Identify** to reveal a magic item's true name/properties table-wide; owner always sees their own kit.
- **Status:** Accepted.

## D12 — Weapon `+N` bonus & ability override; ability on every roll
- **Decision:** Weapons carry `dmgBonus` (magic) added to **both** attack to-hit and damage (crit doubles dice and keeps bonus); `kind:"attack"` accepts an `ability` override (labels the roll `→DEX`); freeform rolls accept optional `ability`(+`prof`) resolved from the roller's sheet.
- **Status:** Accepted.

## D13 — Item actions are WS ops, owner-or-DM gated, DM-only for identify/recharge
- **Decision:** `use_item`, `attune`, `identify`, `recharge` in `app/room/items.py`; results whispered to owner (+DM); attunement capped at 3; depleted (charges 0) items refuse use. Player-initiated `identify`/`recharge` are no-ops.
- **Status:** Accepted.

## D14 — Testing: in-repo `pytest` (primary) + dev-only live WS smoke
- **Decision:** The durable test suite is `pytest` under `tests/`: unit tests
  (`test_path`, `test_mapmodel`, `test_gear`, `test_dice`) plus **integration** tests
  (`test_integration`) that drive the real ASGI app through Starlette's `TestClient`
  over both REST and WebSocket — auth/authz, hidden-info masking (peer private notes +
  unidentified magic), malformed-message resilience, DM-only guards, strict LOS/fog
  token filtering, atomic potion use, and the attunement cap. The hand-rolled raw-WS
  node smoke suites (`vtt_smoke*.mjs`) remain a **dev-only** live-server harness.
- **Consequence:** `pytest` no longer depends on the ephemeral `/tmp/opencode/` scripts
  (TODO-1 resolved). The live suites still need a running server and are **not** part of
  `pytest`; treat them as manual regression aids.
- **Operational hazard:** Do **not** stop the server with `pkill -f` (it has killed the
  tooling shell before); use the saved pidfile (`kill $(cat /tmp/opencode/vtt.pid)`).
- **Status:** Accepted.

## D15 — Kept the legacy 65 green under strict LOS by construction, not by editing assertions
- **Context:** Strict LOS could break old expectations that assumed NPC visibility.
- **Decision/Reality:** The legacy placements happen to sit within radius-6, so they still pass; new LOS assertions in suite 2 deliberately place NPCs far (no `token_add`) vs. in-vision (`token_add`+`step`) vs. leaving (`token_leave`+ghost).
- **Consequence:** Legacy movement tests are vision-adjacent and could turn fragile if the default map/positions change — re-run suite 1 after any grid change.
- **Status:** Accepted (watch item).

## D16 — Backend modularization: `app/room/*` behind a thin `ws.py`
- **Context:** `ws.py` had grown into one ~500-line hub mixing connection plumbing with
  gameplay (dice, movement, LOS, combat, items, traps, dispatch).
- **Decision:** Split gameplay into `app/room/{net,visibility,dispatch,movement,tokens,combat,dice,items,traps}.py`.
  `ws.py` keeps only the WebSocket entry (auth, accept, per-user socket set, connect/disconnect
  lifecycle, receive-loop, generic error handling) and a **re-export shim** so the REST
  call-sites in `rooms.py` (`ws.notify`, `ws.build_seen`, `ws.token_cell`, `ws._last_seen`)
  are unchanged. `dispatch.py` is a flat `type -> handler` registry (no bus/DI).
- **Alternatives:** Big rewrite with an event bus / class-based room objects / repository
  layer (rejected: more indirection than this codebase needs; the flat registry is greppable).
- **Consequences:** Each concern is one small file; message routing is one dict. Re-export
  shim keeps `rooms.py` untouched. Live WS suites (70 + 32) passed unchanged after the split.
- **Status:** Accepted.

## D17 — SQLite: autocommit + explicit `tx()` for multi-statement writes
- **Context:** `sqlite3`'s implicit-transaction mode combined with several statements per
  request (create room, delete char, kick, assign) risked interleaving under concurrency.
- **Decision:** Open connections with `isolation_level=None` (true autocommit), enable WAL
  + `busy_timeout=4000` + foreign keys, and wrap multi-statement writes in `db.tx()`
  (`BEGIN IMMEDIATE … COMMIT/ROLLBACK`). Single-statement writes stay plain `db.x`.
- **Consequences:** No partial writes; writers block briefly (fine at this scale); WAL keeps
  readers concurrent. Still single-file, no ORM.
- **Status:** Accepted.

## D18 — Per-room asyncio map lock + atomic item UPDATE
- **Context:** Map reveal / trap & loot flags / map-edit / walk all do read-modify-write on
  `map_json`; a `use_item` healed HP and decremented charges in two statements.
- **Decision:** A per-room `asyncio.Lock` (`net.map_lock`) serialises every map
  read-modify-write (movement, trap/loot, `map_edit`). `use_item` now applies HP + charge
  decrement in a **single** `UPDATE`.
- **Consequences:** Concurrent walks/edits of the same room can't clobber the map; HP and
  charges are always updated together.
- **Status:** Accepted.

## D19 — Security hardening (auth, cookies, info-leak, logging)
- **Decision:** (1) In-memory sliding-window `ratelimit` on `/login` (10/min) and
  `/register` (10/h), keyed by client IP (optional `X-Forwarded-For` under `VTT_TRUST_PROXY`),
  reset on successful login. (2) Session cookie is `Secure` whenever HTTPS is detected
  (direct scheme, `X-Forwarded-Proto`, or `VTT_COOKIE_SECURE=1`); always `HttpOnly`+`SameSite=Lax`.
  (3) `/state` **strips a peer's private `notes`** for non-DM viewers (loot is appended to
  notes, so this closes a loot/note leak) in addition to `mask_items`. (4) `_last_seen`
  ghosts are **pruned** when a viewer's last socket disconnects (no stale memory, bounded RAM).
  (5) Unexpected REST errors return a generic 500 and are logged; WS handler failures log a
  traceback and send a generic `"Could not process that action"`; non-dict / unparseable WS
  messages are ignored rather than crashing the socket.
- **Consequences:** Removes a real info leak, blunts credential stuffing, keeps dev HTTP
  working, and turns previously-silent handler bugs into logged-but-survivable events.
- **Status:** Accepted.

## D20 — Frontend split into dependency-ordered classic scripts
- **Context:** A single `app/static/app.js` (866 lines) mixed state, API, lobby, WS, canvas
  and wiring; hard to navigate.
- **Decision:** Split **verbatim** into six classic (non-module) `<script>` files under
  `app/static/js/` — `10_core`, `20_lobby`, `30_room`, `40_ws`, `50_canvas`, `60_main` —
  loaded in dependency order from `index.html`. Shared **global scope** is preserved
  deliberately (function/const globals), so no call sites change; cross-file references are
  all call-time.
- **Alternatives:** ES modules (`type=module`) (rejected: would change the whole global-scope
  model and enlarge the regression surface for zero user benefit); a bundler (rejected: adds
  the build step the project deliberately avoids — D1).
- **Consequences:** Navigation wins without touching behaviour. Verified: every top-level
  `function`/`const`/`let` present exactly once (parity-checked vs the original), all files
  pass `node --check`, and the live WS suites still pass.
- **Caveat:** Not validated in a real browser/DOM harness; correctness rests on verbatim
  copy + declaration parity + the WS/REST suites. A future small DOM/Playwright smoke would
  cover canvas wiring specifically.
- **Status:** Accepted.

## D21 — Inline trap/loot editor controls (replaces prompt())
- **Context:** Traps/loot were the only map brushes that collected data via chained
  `prompt()` dialogs. Browsers/iframes that block modal dialogs make `prompt()` return
  `null`, so trap/loot placement silently no-oped while walls/terrain/erase kept working
  (user report: "traps can't be placed").
- **Decision:** When the trap or loot brush is active, the editor toolbar shows inline
  input fields (`#trap-label/#trap-dc/#trap-dmg`, `#loot-label`); `paint()` reads those
  values instead of calling `prompt()`. Same server-side clamps/validation as before.
- **Consequences:** Placement works everywhere, no modal dependency, better UX; drag no
  longer spams prompts. Server `sanitize`/trigger path unchanged (already verified correct).
- **Status:** Accepted.

## D22 — Round-based initiative (roll once, DM ends the round)
- **Context:** Initiative had no round concept; the fighting phase should be organized
  into rounds that the DM ends.
- **Decision:** Initiative order is rolled **once** per combat (`init_start`). `init_next`
  advances `active` (wrapping) without changing the round. A new DM op `init_end_round`
  increments `round` and resets `active` to the leader (0). `room_state.initiative` now
  carries a `round` field; `get_init` back-fills it for pre-existing saves. UI shows
  "— Round N —" and an **End round** button.
- **Alternatives:** Re-rolling initiative every round (rejected — user chose standard 5e
  roll-once, count-rounds).
- **Status:** Accepted.

## D23 — Skills, spellbook + spell slots, and extended item kinds
- **Context:** Add 5e skills, a caster spellbook with slots, and more item kinds (shield,
  wand, ring, tome, …) — all server-authoritative and persisted.
- **Decision:**
  - `characters` gains three JSON columns `skills`, `spells`, `spell_slots`, added via the
    existing safe `migrate()` helper (no destructive change; SQLite only `ALTER ADD`).
  - `gear.py` is the SSOT: `SKILLS` (the 18 5e skills), `clean_skills` (`{key:0|1|2}`,
    1=proficient/2=expertise), `skill_bonus`; `clean_spells`, `clean_slots`;
    `spell_attack`/`spell_save_dc`; extended `KINDS` (shield/wand/staff/scroll/ring/tool/
    wondrous/**spellbook**/…) with shields folded into `compute_ac` (identified only).
  - Roll kinds `skill`, `spell_attack`, `spell_damage`, `spell_dc` added to `handle_roll`;
    new ops `cast` (consumes a leveled slot then rolls its effects, erroring when empty)
    and `long_rest` (DM: restores all slots + `recharge` items).
  - **Magic book = item + panel ("Both"):** the room-sheet Spellbook panel is gated on the
    character carrying a `spellbook` item; the spells/slots themselves live on the
    character. Casting is server-side and always acts on the acting user's own character.
- **Alternatives:** A separate `spells`/`skills` table (rejected — JSON columns match the
  existing `weapons`/`items` pattern and need no joins). Full auto spell-slot-by-level
  tables (rejected — manual `max` is simpler and lets homebrew classes).
- **Consequences:** Client mirrors the bonus math for previews only; the server recomputes
  authoritatively (D3). Migration is non-destructive for existing DBs.
- **Status:** Accepted.

## Cross-cutting assumptions (read before scaling)
- Single uvicorn process, single event loop; `LOOP` captured in `main.py` for thread-safe broadcasts.
- `VTT_DATA_DIR` isolates the SQLite/`secret.key`/uploads tree.
- Public deploy expects a TLS reverse proxy in front (see README Notes).
