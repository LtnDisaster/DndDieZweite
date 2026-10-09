# Architecture Decision Records — D&D VTT (`/home/alp/Test`)

Purpose: capture the decisions taken while building this app so later instances
(human or AI) can recover the *why* without re-deriving it from code.
Each record: Context → Decision → Alternatives → Consequences → Status.

Last touched: 2026-10-02 (multi-cell footprints, wall/door LOS, manual fog, movement stop,
server path preview).
Current test status: `pytest` **162 passed** (unit + in-repo integration). Dev-only live
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
- **Alternatives:** Broadcast-all-and-hide-in-DOM (rejected: leaks over the wire), true shadow-casting LOS (deferred at the time — now implemented by D44).
- **Consequences:** Out-of-sight tokens are never transmitted (strong leak-prevention); more per-viewer compute per step.
- **Status:** Superseded for geometry by D44; targeted-event/guest mechanics remain accepted.

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

## D24 — NPC / enemy stat blocks live on the token (DM-only)
- **Context:** Monster tokens carried only a label+color; initiative and DEX-save traps used
  DEX=0 for them, they took no trap damage, and DMs had no way to give an enemy ability scores
  or let it cast spells.
- **Decision:**
  - New single JSON column `tokens.npc` (added via `migrate()`, non-destructive) holds the whole
    block: `{name, level, stats{6}, hp, max_hp, ac, speed, spells[], spell_slots{}}`. `app/npc.py`
    is the SSOT: `clean_npc` (bounded), `load`, `dex_mod`/`stat_mod`, and `to_char(block,name)`.
  - **Reuse, don't fork:** `to_char` returns a `{name, stats, level}` pseudo-character so the
    existing `gear.spell_attack`/`spell_save_dc`/`prof_bonus` and the `dice._spell_*_text`
    builders serve NPCs unchanged — one source of truth for all spell math (no second impl).
  - Token-keyed DM actions: `add_token`/`update_npc` (edit the block), `hp` and `roll`/`cast`
    accept a `token_id` for an owner-less, character-less monster token (guarded `if not is_dm`).
    Initiative (`combat.token_dex_mod`) and traps (`traps.hit_trap`) resolve DEX from the token's
    block and apply damage to `npc.hp`. Leveled casts consume per-NPC `spell_slots`.
  - **Hidden from players:** the `npc` block is stripped for non-DM viewers in `rooms.room_state`
    and in the `token_add` path of `visibility.send_token_event`, extending the D11/D19
    hidden-info posture. Rolls themselves post publicly, as at a real table.
- **Alternatives:** DM-owned rows in `characters` (rejected — muddies the library/ownership model
  and the per-user character list). Full PC mirror with weapons/items (deferred — beyond scope).
- **Consequences:** `SELECT * FROM tokens` now carries `npc`; every reader that hands a token to a
  client must keep the strip in sync. Initiative reveals monster DEX mod + totals as before (D22).
- **Status:** Accepted.

## D25 — Fog reveal is gated to player-owned tokens
- **Context:** `movement.walk`/teleport revealed fog on the **shared** `explored` array and
  broadcast `explored` to everyone for *any* token that moved, so marching an NPC lifted fog for
  the whole party (and leaked it on refresh, since the array is persisted).
- **Decision:** Reveal + `set_map` + the `explored` broadcast run only when
  `token.owner_user_id is not None`. NPC/DM-token movement keeps triggering traps/loot but touches
  no fog. Party-shared vision (one player's discovery reveals for the party) is intentionally kept.
  Other reveal sites — `ws` connect (own tokens) and REST `assign` (a player character) — were
  already owner-scoped. The DM needs no reveal (`visible_map` returns the full map for `is_dm`).
- **Alternatives:** Strict per-viewer fog (rejected here — would mean a per-user `explored` array;
  revisit only if the party-shared model is ever dropped).
- **Consequences:** The DM moving a monster can no longer be used to scout the map for players.
- **Status:** Accepted.

## D21 (amendment) — Trap/loot markers render as a colored badge
- The map icon loop computed a marker color but never applied it, so the ⚠/🎁 glyphs drew in the
  leftover dark cell fill-style (effectively invisible where emoji fall back to monochrome, e.g.
  Linux). They are now drawn as a filled circle in the marker color with a white glyph, gated
  role-wise: DM always, players only once `discovered`/`taken_by`.

## D26 — Conditions ride on the token, effects are NOT auto-applied
- **Context:** The table wants a reliable flag for blinded/prone/concentrating/… so the state
  survives refresh and reaches every viewer, without inventing a rules engine.
- **Decision:** `tokens.conds` is a compact JSON list `[{k, rounds}]` normalised by the SSOT
  `app/conditions.py` (`clean_conds`, `add`/`remove`, `step_rounds`, `is_concentrating`). The 15
  canonical 5e conditions ship with a label/glyph/color; any bounded ASCII string is accepted as a
  homebrew condition. **Round progression** runs only at the DM's `init_end_round` (timed entries
  decrement, `rounds==0` are permanent); **long rest clears all**. `cond_add`/`cond_remove` let the
  DM manage any token and players flag **their own**. Conds are carried in `room_state`, the
  `token_add` payload and `_snapshot`, and broadcast live as a `cond` event. Concentrating renders a
  dashed gold ring; other flags as colored dots + sheet chips.
- **Alternatives:** A `character_conditions` table (rejected — conditions are a play-time state, so
  the token is the right owner, matching the `npc`/`death` pattern). Auto-applying mechanical effects
  like every engine (rejected — D3 keeps rules explicit and additive; the flag is the contract,
  effects layer on later).
- **Consequences:** Conditions are **carried, not enforced** by design. Per-round decrement is tied
  to the initiative round counter (D22), so it only advances when the DM ends a round.
- **Status:** Accepted.

## D27 — Death saves are 5e and token-scoped, characters only
- **Context:** A PC dropping to 0 HP needs the 5e dying/stable/dead arc without touching the
  character library (the same character may be dying in one room and fine in the lobby).
- **Decision:** `tokens.death` (`app/room/death.py`) holds `{s, f, stable, dead}`. `handle_hp`
  transitions on damage: fresh state at 0, `+1 fail` per damage while already at 0 (instant death
  when the hit ≥ max HP, re-enter on damage to a *stable* creature), cleared on healing above 0.
  `death_save` (owner or DM) rolls a straight d20: ≥10 success, <10 fail, nat-20 regains 1 HP and
  becomes conscious, nat-1 = two failures; 3 successes → stable, 3 fails → dead. `death_clear` is the DM override.
  **NPCs never enter the state** — they just sit at 0 HP.
- **Alternatives:** Storing `death` on `characters` (rejected — pollutes the library with a transient
  room state). Auto-rolling saves for the player (rejected — the owner rolls their own, DM may proxy).
- **Consequences:** Death state is per-token, so it's hidden/scoped like every other token field; the
  canvas shows a red ring (dying) / ☠ (dead) and a 3×(✓/✗) sheet panel.
- **Status:** Accepted.

## D28 — NPC attacks resolve against a target token's AC, reusing the dice path
- **Context:** A monster needs more than spell slots — reusable natural attacks with a to-hit bonus,
  ideally answering "did it hit and for how much" in one click.
- **Decision:** `npc.attacks` (`clean_attacks`) stores `{id, name, to_hit, dmg, dc, save, reach}`.
  `npc_attack` (DM-only) rolls d20+`to_hit` and, when a `target_id` is given, compares against the
  target's **effective AC** — a character's `gear.compute_ac` or another monster's `ac` — then rolls
  `dmg` on a hit (crit on nat-20, fumble on nat-1). `mode:"damage"`/`mode:"dc"` post just the dice /
  save DC. Everything flows through the existing `do_roll`/`dice_post` (no second dice engine).
- **Alternatives:** Full attack bundles with damage types/conditions and auto-apply (rejected — out of
  scope, and D3 keeps effects manual). Player-facing target picking (rejected — monsters act on the DM's turn).
- **Consequences:** Attack outcomes post publicly (rolls are public at a table, D24); AC is read
  authoritatively server-side, so the DM never sees a wrong AC.
- **Status:** Accepted.

## D29 — Doors are first-class map geometry and block the pathfinder
- **Context:** Closed/locked doors are the one map feature that must actually stop movement, not just
  look the part, and must be authorable and interactable at the table.
- **Decision:** A door sits on an **interior edge** (`dir v` = `x↔x+1`, `dir h` = `y↔y+1`), stored in
  `mp["doors"]` and normalised in `mapmodel.sanitize` (`_canon_door` re-anchors to the lower cell and
  drops out-of-bounds/dup edges). `blocked_edges()` → the pathfinder (`find_path`'s new
  `blocked_edges` param, mirrored in `findPathJS`) refuses to cross a closed edge (and a diagonal may
  not squeeze past one). `mapmodel.find_door` matches either orientation. **Authoring** is the 🚪 map-
  editor brush (edge chosen from the click position); **interaction** is the `door` WS op: DM
  open/close/lock/unlock/remove anything; a player may only **toggle an unlocked door their token is
  adjacent to** (`_player_cell` vs the door's two cells), locking being DM-only. `visible_map` withholds
  doors in unexplored cells.
- **Alternatives:** Doors as terrain cells (rejected — a cell is not an edge; walls already exist).
  Auto path-through when a door is open (rejected — path re-runs on move, so an open door simply
  isn't in `blocked_edges`; no special case needed).
- **Consequences:** `find_path` gained a parameter; every caller must pass `mapmodel.blocked_edges`.
  The JS↔Python pathfinder parity (a known P2 soft spot) must keep the door logic in lockstep.
- **Status:** Accepted.

## D30 — AoE templates are a visual relay, not a resolver
- **Context:** Casting a fireball needs the area shown to the party, but auto-resolving saves/damage
  in an area is a much larger (D3-forbidden) step.
- **Decision:** The DM arms a template (burst/square/line/cone + size + direction), clicks the grid,
  and `app/room/aoe.py` relays the *parameters* to everyone; each client recomputes the covered cells
  from the shared client-side `aoeCells()` and paints a ~7s overlay. Nothing is stored or resolved.
- **Alternatives:** Server computing the cell list (rejected — the geometry is a pure function of the
  params and the client's grid; recomputing avoids trusting a client-supplied array). Auto-resolving
  the area (rejected — D3).
- **Consequences:** DM-only presentation tool; the overlay is transient and cosmetic.
- **Status:** Accepted.

## D31 — Bestiary is a generic, per-user template store keyed on the NPC block
- **Context:** Reusing a well-built monster (or sharing a homebrew archetype) beats rebuilding it per
  room, without importing a copyrighted stat catalog.
- **Decision:** A `creatures(user_id, name, block, tags)` table where `block` is exactly a
  `npc.clean_npc` output — one data model for monsters everywhere (library token, spawned token,
  bestiary entry). REST CRUD (`/api/creatures`, owner-scoped, private) + a sheet "Save to Bestiary"
  capture. **Spawn reuses `add_token`** from the client, so no new spawn authority surface is needed.
- **Alternatives:** A global shared monster library (rejected — ownership/privacy; keep it per-user).
  Seeding a stock catalog (deferred — must be IP-clean; see TODO P3).
- **Consequences:** Any change to `npc.clean_npc` immediately changes the stored-block shape the
  bestiary round-trips — keep them in sync (same mirror concern as D24).
- **Status:** Accepted.

## D32 — Line-of-sight fog was evaluated and gated out (square vision retained)
- **Context:** The vision model was a Chebyshev radius-6 square that ignored walls (D8). True
  shadow-casting LOS was requested as the final roadmap item, hard-gated on the existing
  visibility/fog/hidden-info suites staying green.
- **Decision:** Originally not shipped. A correct LOS must gate **both** the transient light *and* the
  persistent `explored` memory, otherwise terrain already revealed through a
  wall stays visible in `visible_map` and LOS hides nothing that matters. At the time `test_reveal_*`
  and the fog suite pinned `reveal` to the current square contract.
- **Alternatives:** LOS for the live view only (rejected — pointless while memory leaks square);
  rewrite the fog tests to the new model (later accepted as its own Sprint 4 change).
- **Consequences:** The original square-vision gate is obsolete. Walls and closed doors now gate
  both live visibility and exploration under D44; the tests were deliberately rewritten to the
  stricter model.
- **Status:** Superseded by D44.

## D33 — Game-log visibility is a transport property, not a client filter
- **Context:** The game log needs secret GM rolls, self-only rolls and blind rolls without
  leaking their results over the wire.
- **Decision:** `messages.visibility`, `recipient_user_id` and `meta` are canonical fields.
  `app/room/gamelog.py` owns both live delivery and `/state` reconstruction. The four modes
  are `public`, `self`, `blind` and `dm`; blind only sends an acknowledgment to the actor and
  the result to DMs. A non-DM request for `dm` visibility is normalized to `self`.
- **Alternatives:** CSS hiding (rejected: full data leak), separate per-recipient message
  copies (rejected: redundant and hard to reconstruct), client filtering (rejected: violates D3).
- **Consequences:** Message queries return role-filtered rows. Dice results and roll metadata
  are deliberately carried together, allowing the UI to retain ADV/DIS and cover context.
- **Status:** Accepted.

## D34 — HP, death and defenses use one server-side health reducer
- **Context:** Damage could enter from manual HP edits, traps, potions and NPC attacks, while
  temp HP, typed damage and death saves were beginning to duplicate transition logic.
- **Decision:** `app/room/health.py::change_hp` is the single transition path for PCs and NPC
  blocks. Damage type is an explicit optional field. Defensive reduction runs before temp HP
  or real HP is consumed; death save nat-20 restores 1 HP and clears dying. Massive damage
  uses post-defense damage and only fires when damage actually occurs.
- **Alternatives:** Patching each call site separately (rejected: divergence), encoding
  vulnerability in dice rolls (rejected: defensive properties belong to the target).
- **Consequences:** Manual HP remains supported, while typed interactions receive a clear
  extension point without adding a full effect engine.
- **Status:** Accepted.

## D35 — Rests separate narrative recovery from condition removal
- **Context:** D&D 5e long rest restores class/spell resources and does not automatically
  erase arbitrary conditions. A blanket clear was a table surprise.
- **Decision:** Short rest is owner-or-DM and is hit-dice based. Long rest is DM-triggered;
  HP, slots, hit dice and resource state reset, while `conditions` remain untouched unless the
  message supplies explicit `clear_conditions: true`.
- **Alternatives:** Auto-clear all conditions (rejected), automatic party-wide short rest
  (rejected: the party may not actually be resting).
- **Consequences:** Existing long-rest behavior remains opt-in, and the table retains control
  over magical/condition effects without inventing auto-resolution.
- **Status:** Accepted.

## D36 — Encounter and journal data are server-scoped by ownership and room
- **Context:** Saved encounters and handouts are DM materials that should never leak through
  the shared room state.
- **Decision:** `encounters` are owner-scoped global templates. `notes` are room-scoped and
  carry `dm`, `party` or `selected` visibility plus an explicit recipient ID list. The note
  endpoint parses recipients server-side instead of using textual SQL matching.
- **Alternatives:** Storing JSON in `room_state` (rejected: unbounded state blob), client
  filtering (rejected: violates D3), JSON `LIKE` recipient lookup (rejected: false positives).
- **Consequences:** Encounter spawn can reuse saved creature blocks and private note reads are
  safe against malformed `recipients` values.
- **Status:** Accepted.

## D37 — Map pins, pings and ruler have different trust levels
- **Context:** Map annotations and communication tools have different state, visibility and
  abuse characteristics.
- **Decision:** Pins are sanitized persistent map data with `dm`/`players`/`revealed`
  visibility. Pings are rate-limited live broadcasts and are deliberately not persisted.
  The ruler is purely client-side measurement. Server-side visibility and fog filtering own
  the security boundary for pins.
- **Alternatives:** Make all ephemeral (rejected: DM planning notes should survive refresh),
  make all persistent (rejected: pings have no audit value and can spam state), validate ruler
  server-side (rejected: it is display-only and cannot mutate state).
- **Consequences:** UI tools can be lightweight without weakening the map information model.
- **Status:** Accepted.

## D38 — Chat history is separated from game-log delivery at the database boundary
- **Context:** The `messages` table had become both a game log and chat store. Client-side
  filtering could separate presentation but could not prevent private data from being sent.
- **Decision:** Chat and narrative rows are delivered by `app/room/chat.py`; dice/system rows
  remain in `app/room/gamelog.py`. Message metadata carries `channel`, `visibility` and a
  JSON `recipient_ids` list. `/state` queries chat and game log separately and applies the
  viewer's authorization in SQL.
- **Alternatives:** Use only `meta` (rejected: unqueryable), add `display:none` (rejected: leaks
  data), create a separate `chat` table (deferred: existing message history and replay code are
  already built around `messages`).
- **Consequences:** Replay and live delivery share explicit visibility concepts, and private
  chat can be tested without changing dice visibility.
- **Status:** Accepted.

## D39 — Player whispers are not secretly visible to the DM
- **Context:** Some VTTs make every player whisper DM-visible; others protect player-to-player
  private communication.
- **Decision:** A whisper is visible only to its sender and explicit recipients. Player-to-DM
  messages naturally include the DM. A DM's untargeted `dm` channel message is visible only to
  DMs. This choice is deliberately documented in the README.
- **Alternatives:** Make the DM an omniscient listener (rejected for this product: it removes a
  trust boundary players expect), make all chat visible to everyone (rejected: no whisper).
- **Consequences:** DM private notes and player whispers need separate handling. The rule must be
  preserved by any future moderation/audit feature if added.
- **Status:** Accepted.

## D40 — DM personas and NPC speech are authorized server-side
- **Context:** Narrative immersion requires speaking as NPCs/personas, but the chat sender is a
  security and identity boundary.
- **Decision:** Only DM sockets may set `sender_kind` to `persona` or `npc`. The database always
  records the real `user_id`. Persona names matching any room member username are rejected. NPC
  speech requires a target token that belongs to the room, has no owner/character attachment and
  has a parseable NPC block.
- **Alternatives:** Let players impersonate anyone (rejected: identity spoofing), hide provenance
  in `meta` only (rejected: unqueryable), validate only on the client (rejected: D3).
- **Consequences:** NPCs can be renamed/deleted while old messages retain their display persona;
  this is preferable to changing chat history or enforcing cascading edits.
- **Status:** Accepted.

## D41 — Audio is a safe-URL projection, not an embedded content pipeline
- **Context:** Direct audio, YouTube and Spotify can all improve table atmosphere, but arbitrary
  URLs, embed HTML and media downloading introduce different security and legal risks.
- **Decision:** Direct HTTP(S) audio and same-origin `/uploads` paths are allowed. YouTube and
  Spotify URLs are parsed and their media IDs revalidated; fixed `youtube-nocookie` or
  Spotify embeds are constructed by the server. No caller-supplied iframe/HTML is rendered and
  no media is scraped or downloaded. Selective effects are limited to direct audio URLs and
  receive server-resolved recipients.
- **Alternatives:** Accept arbitrary iframe embeds (rejected: XSS/CSP), download media (rejected:
  out of scope and rights risk), allow players to control room ambience (rejected: atmosphere
  control is DM responsibility).
- **Consequences:** Player volume/mute are local UX, not authoritative room state. Third-party
  browsers may still block autoplay, so direct effects are the more reliable selective channel.
- **Status:** Accepted.

## D42 — `AGENT_GUIDE.md` is a map, not an authoritative specification
- **Context:** Future agents need a fast architecture map but generated documentation tends to
  drift and can confidently mislead.
- **Decision:** Add `AGENT_GUIDE.md` as a deliberately concise repository/feature/file/message/
  hazard map with an explicit code-wins rule.
- **Alternatives:** No guide (rejected: repeated discovery cost), generate every fact with line
  numbers (rejected: brittle and noisy), treat it as an ADR/source of truth (rejected).
- **Consequences:** Changes to architectural boundaries should update the guide, but implementation
  inspection remains mandatory before edits.
- **Status:** Accepted.

## D43 — Token footprint is an `n×n` square anchored at `x/y`  (EXTENDED BY D81: rectangles)
- **Context:** Large monsters were visually scaled but still occupied only one pathfinding cell, so
  a Huge creature could stand on the map edge or squeeze through a one-cell corridor.
- **Decision:** `app/footprint.py` is the footprint SSOT: Tiny/Small/Medium 1×1, Large 2×2, Huge 3×3,
  Gargantuan 4×4. The existing token `x/y` remains the top-left occupied cell center; footprint
  extends right/down. A clicked movement destination is the anchor. Spawns and size changes find the
  nearest valid origin; confirmed moves require a valid final footprint.
- **Alternatives:** Center-based storage (rejected: it would reinterpret every legacy token),
  circular templates (rejected: the existing grid and rules use squares), per-client geometry (rejected).
- **Consequences:** Server pathfinding can enforce Large+ terrain rules, collision and spawning with
  one representation. Same-owner pass-through is intentionally retained; collision blocks different
  distinct owners only at final placement.
- **Status:** Accepted.

## D44 — Deterministic conservative LOS replaces square vision
- **Context:** Sprint 4 requires walls and closed doors to hide terrain/tokens, including exploration
  memory, not merely the current view.
- **Decision:** `app/los.py` casts deterministic integer DDA rays from footprint source cells. Walls
  and closed-door edges block. A ray through an exact grid corner is allowed only when both relevant
  orthogonal transitions are open, preventing vision through sealed diagonal corners. The existing
  radius 6 remains; footprint sources/targets need only one occupied cell to be visible. Live LOS and
  persistent exploration use the same result.
- **Alternatives:** Recursive shadowcasting (rejected for now: larger rewrite and floating-point drift),
  live-view-only LOS (rejected: old memory leaks), optimistic Bresenham (rejected: corner ambiguity).
- **Consequences:** DM hiding or re-fogging can no longer be undone merely by moving a player token.
  Visibility and fog are server-authoritative; hidden token payloads remain absent before transmission.
- **Status:** Accepted. Supersedes the square-vision portions of D8 and the deferral in D32.

## D45 — Manual fog edits room-wide exploration, not live sight
- **Context:** DMs need explicit reveal/hide tools while a player's current line of sight remains
  mechanically correct.
- **Decision:** DM-only `fog_edit` updates `map.explored` for up to 512 cells. Revealed/hid state is
  broadcast to all players. `visible_map` returns terrain when persistent exploration **or** current
  LOS visibility is true, so hiding an old memory cell does not corrupt a live view.
- **Alternatives:** Per-player fog (rejected: current schema has one shared `explored` bitmap),
  erase current visibility too (rejected: would blind a player standing in plain sight).
- **Consequences:** Manual reveal is simple and shared across all players; private per-player fog needs
  a schema change later. Map-editor reset-fog checkbox now has an actual server effect.
- **Status:** Accepted.

## D46 — Movement state and path previews are server-owned
- **Context:** The client previously mirrored A*, while walk tasks and traps were server-controlled;
  large footprints/LOS made duplicated route planning unsafe.
- **Decision:** Players preview their own token via `path_preview`; the server validates ownership,
  footprint, walls/doors, collision and current explored/visible cells. Walk tasks emit `move_state`;
  trap trigger and DM `stop_move` cancel the task and announce a stopped walk. Movement confirmation
  recomputes the authoritative path independently of the preview.
- **Alternatives:** Keep client A* as source of truth (rejected), block friendly pass-through at every
  animation step (rejected: conflicts with chosen pass-through policy), add a resumable move queue
  (deferred).
- **Consequences:** Hidden terrain cannot be inferred through preview, path/UI remain synchronized,
  and traps now interrupt an in-flight walk. Intermediate movement may still overlap same-owner tokens;
  only final placements are collision-authoritative.
- **Status:** Accepted.

## D47 — One authoritative world, multiple client-local renderers
- **Context:** We want a Tactical view and a Diorama view of the same room without duplicating game
  state or forcing every player into one presentation. A naive "view mode" flag on the server would
  turn a personal preference into shared, room-level state.
- **Decision:** The server keeps one authoritative, already per-viewer-filtered world
  (`state.grid`/`state.tokens`/`state.ghosts`). Each browser picks its own renderer via a
  **client-local** `state.viewMode` ("tactical" | "diorama", invalid → tactical) persisted in
  localStorage (`dndtable-view-mode`). `draw()` is the single dispatch point to `drawTactical()` or
  `drawDiorama()`; every existing call site keeps calling `draw()` and follows the active view. The
  DM map editor always renders tactical. View mode is **never** sent over WebSocket, persisted
  server-side, or allowed to influence permissions, movement, LOS, fog or combat.
- **Alternatives:** Room-level view setting (rejected: not personal), separate map/state per view
  (rejected: duplication and divergence), a full OO renderer framework (rejected: the frontend is
  function-based; a thin dispatcher is enough).
- **Consequences:** Two clients in the same room can show different views independently. Rendering
  mode can never change gameplay, and the existing per-viewer visibility boundary is reused
  unchanged, so a second renderer cannot leak hidden information.
- **Status:** Accepted.

## D48 — Diorama is a projection prototype over reused state, not a new engine
- **Context:** We need to prove "one world → two renderers" cheaply, with no sprite assets, no WebGL,
  and no risk to the freshly hardened Tactical renderer.
- **Decision:** `app/static/js/55_diorama.js` projects the shared grid through a deterministic 2:1
  isometric map (`dioProj`/`dioUnproj`) onto the same Canvas: floors as diamonds, walls as extruded
  boxes, doors as upright open/closed/locked panels, tokens/ghosts as upright "paper" billboards.
  Painter sort is split into a tile pass then a billboard pass (tokens always on top, as in Tactical).
  Visibility is read through the existing `visibleHere()` mask — no second visibility authority.
  Interaction reuses authoritative handlers only (door toggle, `path_preview`, `move`); there is no
  client-side A*. **No speculative schema:** visual metadata (materials, elevation, sprite/scale/
  rotation/layer, per-object blocks-movement/vision) is *deferred*; it is expected to live inside the
  existing `room_state.map_json` document via the map sanitizer, not as new DB columns.
- **Alternatives:** Three.js/WebGL (rejected: complexity/risk), a bespoke 3D camera (rejected), new
  DB columns for visual metadata now (rejected: speculative).
- **Consequences:** Diorama is a functional placeholder view. Deferred/limited: no sprite art, no
  dynamic lighting/shadows, no elevation gameplay, no rotation/zoom camera, coarse billboard picking,
  and Diorama movement is a server-preview only (precise manual movement stays a Tactical action).
  Future visual metadata should extend `mapmodel.sanitize()` rather than the schema.
- **Status:** Accepted.

## D49 — Core/transport coupling audit; keep handlers thin, extract nothing speculative
- **Context:** Sprint 5B audited whether gameplay rules are welded to FastAPI/WebSocket
  transport, to keep a future DM-automation or local/single-player adapter possible. Goal
  was a boring, test-safe separation — not a rewrite.
- **Decision:** The transport layer is already thin: `ws.py` keeps only connection plumbing
  and every `app/room/*` handler parses+authorizes, then calls pure gameplay helpers
  (`path.find_path`, `footprint.*`, `los.*`, `mapmodel.*`, `health.*`, `gear.*`, `npc.*`).
  No CQRS/event-sourcing/DI/bus/plugin layer was introduced. The only cross-handler duplication
  worth naming is the "reveal a player token's LOS cells" expression, used by `ws.py` and
  `movement.py`; it is a two-line call into pure functions with **different** `owner=None`
  semantics and one copy sits on the movement hot path, so it was deliberately **not** extracted
  (marginal gain, real regression risk). Gameplay operations should continue to read like
  commands (move/door/damage/heal/reveal) reachable without a socket; new automation must call
  those helpers, never a WebSocket handler.
- **Alternatives:** A `visibility.token_reveal_cells()` dedup (rejected as not clearly
  beneficial); an application/command layer (rejected: speculative, violates D16's thin-shim
  intent and would churn hot paths for no behavioral gain).
- **Consequences:** The rules core stays callable headlessly; the audit added cross-system
  regression tests (`tests/test_hardening.py`) instead of moving code. A known design gap was
  recorded rather than fixed: `walk()` computes its path once, so a door closed *mid-walk* does
  not reroute the in-flight token (see TODO).
- **Status:** Accepted.

## D50 — Per-step authoritative movement revalidation (`path_blocked` stop)
- **Context:** A walk computed its A* route once and replayed it blindly (D46). If a door
  closed or a wall appeared mid-walk, the token could phase through the new obstacle — the
  route was only authoritative when the walk began (recorded gap in D49 / TODO).
- **Decision:** `walk()` revalidates **every step immediately before applying it** against the
  current map: bounds, walls, footprint cells and `blocked_edges` (closed/locked doors) via
  `path.step_legal()`. That function was extracted from `find_path`'s own validity closures,
  so pathfinding and revalidation share one legality source (footprint-aware, including the
  conservative diagonal mid-cell rule — Sprint 4 rules unchanged). An illegal step is never
  written: the walk ends with `move_state {moving:false, reason:"path_blocked"}`, the mover's
  socket additionally gets a private `error`, and the token stays on its last broadcast cell.
  Validation and the position write run inside the existing per-room `map_lock` — the same
  lock `handle_door`/`handle_map_edit` hold — so on the single event loop no world mutation
  can interleave between "check" and "apply". One lifecycle, four endings: completed,
  manual (DM stop), trap, path_blocked; all clean up `_walks` via the existing `finally`.
- **Alternatives:** Re-running A* each step (rejected: expensive and re-plans routes the
  player never chose); cancelling silently (rejected: mover gets at least a private reason);
  a lock-free "validate then write" (rejected: the door close could slip between the two).
- **Consequences:** Stale routes can no longer violate geometry; mid-walk token resizes also
  stop safely (current side is used). Residual limitation: single-loop atomicity — a
  multi-worker deployment would need shared state before this guarantee means anything
  (already voided for ghosts/fog by the cross-cutting assumptions). Pixel math now reads the
  live `mp["cell"]` per step instead of a value captured at walk start.
- **Status:** Accepted. Tests: door-closed-mid-walk and wall-painted-mid-walk
  (`tests/test_hardening.py`); trap-stop and DM-stop suites unchanged.

## D51 — Quest Log: structured persistent progress; journal stays free-form
- **Context:** DMs need objectives with authoritative state ("Speak with the
  guard ✓"), not only prose journal notes. Journal notes were never queryable
  and mixing the two would make "what is still open?" a text-parsing problem.
- **Decision:** New `quests` table: `title, description, status
  (active|completed|failed|hidden), objectives JSON [{id,text,done,hidden}],
  visibility (party|dm), created/updated`. Pure game operations in
  `app/quests.py` (create/update/add_objective/set_objective/complete/fail/
  delete + `visible_for`); WS handlers in `app/room/quests.py` are thin
  (parse → DM-authorize → op → notice → payload-less `quests_changed`
  broadcast; clients refetch `/state`). **Server-side filtering in
  `visible_for` is the security boundary**: DM-only quests, `hidden` status
  and objective-level `hidden` hints are never serialized into any player
  payload, live or `/state`; reconnecting clients rebuild quests from
  `/state` only. `room_state()` gained `"quests"`.
- **Alternatives:** Journal notes with a quest category (rejected: no
  structure/derivation); REST CRUD like notes (rejected: mutations need live
  room broadcast; REST kept read-free); per-player visibility (deferred — fits
  `recipients` later, not built today).
- **Consequences:** Triggers can later call `complete_quest(...)` exactly like
  a DM click. Quest edits are last-write-wins (no lock) — acceptable for
  low-frequency DM authoring; revisit if automation starts editing quests.
- **Status:** Accepted. Tests: `tests/test_quests.py`.

## D52 — Notices are transient presentation; game events are facts, not state
- **Context:** Quest changes must be visible in the moment, and future
  automation needs a seam to observe the game — without either becoming a
  second source of truth.
- **Decision:** **Notices** (`QUEST ADDED …`) go through the existing
  game-log (`gamelog.post_message`, `kind="system"`) with visibility bound to
  the quest's visibility (DM-only quests produce DM-only notices). They are
  chronicle/presentation only: reconnect reconstructs quests from `/state`,
  never by replaying notices. **Game events** (`app/events.py`) are small
  plain dicts `{type, room_id, actor_id, target_id, data}` emitted **after**
  an operation has committed its state change — an event is never where state
  lives. One bounded in-process ring for diagnostics; synchronous listener
  registry; a raising listener can never break the emitting operation.
  Deliberately NOT an event bus: no queue, no persistence, no DI container.
- **Future trigger direction (documented, NOT built):**
  `GameEvent → trigger condition → game operation`, e.g.
  `enter_area("crypt") → CompleteObjective(quest, objective)` or
  `open_door("ancient_gate") → StartEncounter(...)`. Triggers must call the
  same pure operations humans use (D49) — never fake WebSocket clients.
- **Wired today (facts only, 4 families):** `door_opened/door_closed/
  door_removed`, `trap_triggered`, `quest_started/updated/completed/failed`.
  More events are added when an operation needs observers, not speculatively.
- **Consequences:** Dropping every event loses nothing authoritative (tests
  prove state and events co-exist, not that state depends on events).
- **Status:** Accepted. Tests: quest-event + door-event emission + plain-JSON
  transport-freeness in `tests/test_quests.py`.

## D53 — Character classes are a collection; total level is derived
- **Context:** A single `char_class`/`level` pair makes multiclassing a schema
  migration later. Modeling it wrong now is the expensive mistake.
- **Decision:** Progression is a collection:
  `class_levels = [{"class_id":"fighter","level":3},{"class_id":"wizard","level":2}]`
  (JSON column, additive migration). `app/progression.py` provides the strict
  validator (ids lowercase ≤24 chars, levels 1–20, no duplicates, total ≤20 —
  invalid input is **rejected whole**, never half-applied), the single
  canonical `total_character_level()` (sum of entries, legacy `level` column
  as single-class fallback) and the `set_class_levels()` operation which also
  keeps the legacy `level` column in sync so every existing consumer (hit
  dice, slots, sheet math) sees the derived total. `gear.prof_bonus()` now
  derives from `total_character_level` — no re-summed copies. WS
  `class_levels`: owners manage their own characters, the DM may advance
  characters **of this room's members**; anyone else is refused server-side.
  Engine structure only — no class feature tables, subclass text or
  progression prose (licensing boundary, ATTRIBUTION.md); per-class hit dice/
  resources/spellcasting attach to these entries later (TODO), no speculative
  columns today. UI is a read-only sheet line `Warrior 3 / Adept 2 Lv4`.
- **Alternatives:** `class = "fighter/wizard 3/2"` string (rejected: parsed
  forever); one row per class in a table (rejected: overkill for one JSON
  list at this scale).
- **Status:** Accepted. Tests: `tests/test_progression.py`.

## D54 — Ability geometry is generic and independent of named spells
- **Context:** AoE templates existed only as a client-side visual relay
  (`aoeCells` in `10_core.js`). Future abilities need the same geometry
  resolved server-side, and it must not become hard-wired to spell names.
- **Decision:** `app/effects.py::effect_cells(shape, size, x, y, w, h,
  direction)` — pure, deterministic, boundary-clipped — covering
  `point|line|cone|circle|square` (circle/square double as sphere/cube map
  projections). An effect is `shape + size + origin + direction`; future
  fields (range, save, damage expression/type, condition, duration,
  concentration) attach as data HERE — never as spell names. NO spell
  catalogue is introduced; tests use original names ("Training Cone" style
  parameters, not content). The exact-45° cone edge is a float tie: the
  server matches the shipped client's exclude-behavior, and the parity test
  (`tests/test_effects.py`, Node `vm`) locks server preview ≡ client cells
  cell-for-cell. The DM relay (`app/room/aoe.py`, D30) stays presentation-
  only; resolution remains a deliberate future step.
- **Status:** Accepted.

## D55 — Abilities are DATA; one generic executor owns mechanical resolution
- **Context:** fireball/healing-word/dragon-breath/trap-flame as separate code
  paths is the classic VTT death spiral. The sprint goal was the ENGINE, not
  the spellbook.
- **Decision:** `app/abilities.py` holds validated definitions (`clean_definition`:
  casting `ability` score, `range_ft`, `targeting self|single|point|area`,
  area `shape+size_ft` via `effects.py`, `resolution auto|save|attack`,
  `on_save none|half|negate`, generic effects `damage(+type)|heal|condition`,
  `concentration` flag, `cost {spell_slot|resource}`) in a server-side registry —
  the client sends ONLY `ability_id` + target. `abilities.execute()` is the ONE
  operation every caller uses (WS handler, future trigger, future AI DM); it
  takes plain ids, never a WebSocket object. Named content becomes rows later;
  zero named-spell code paths exist. Definitions are whole-rejected on any
  invalid field; production ships an EMPTY registry (engine, no content DB).
- **Geometry independence:** shapes/sizes are pure `effects.effect_cells()`
  inputs (D54) — nothing in the engine knows what a "fireball" is.
- **Status:** Accepted. Tests: `tests/test_abilities.py` (Training Bolt/Burst
  etc. — original fixture names, no licensed content).

## D56 — Existing subsystems stay authoritative; the executor only orchestrates
- **Decision:** the executor implements NO second engine. Damage/heal go through
  `room.health.change_hp` (typed damage → `gear.apply_defense` resist/immune/
  vulnerable → temp HP → death saves — verified by a test where ability damage
  drives a token into the dying state). Saves use `gear.save_bonus` +
  `room.dice.do_roll`; conditions use `app.conditions`; concentration IS the
  existing `concentrating` condition flag; slots/resources are the existing
  `spell_slots`/`resources` columns (long/short rest already restore them).
  Canonical derivation helpers live in `gear.py`: `stat_mod()` (the one
  modifier formula, scores clamped 1–30), `ability_save_dc()` and
  `ability_attack_bonus()` — `spell_save_dc/spell_attack` now delegate.
- **Rounding:** save-half damage is floored BEFORE defense (`//2`, matching
  `apply_defense`'s resistance floor); crit doubles damage dice count.
- **Status:** Accepted.

## D57 — The casting ability is configuration, never a class assumption
- **Decision:** nothing in gear/abilities hard-codes "wizard→INT". The ability
  definition carries `ability`; the executor derives DC/attack from it. Class
  defaults can become data later. Save DC/attack take an explicit `bonus`
  parameter so magic-item/racial bonuses never need formula copies.
- **Status:** Accepted.

## D58 — Spell slots ride on the generic resource system; multiclass total level MUST NOT derive slot tables
- **Decision:** slot state stays the existing `{1..9: {max, used}}` JSON with
  the existing consume/restore semantics (rest handlers unchanged); a new op
  consumes exactly one slot or rejects — never negative, never consumed when
  the cast later refuses. Generic `{type:resource,id}` costs ride the existing
  `resources` list (ki/rage/charges are first-class, not spell slots).
  `cast_level` is the upcast EXTENSION POINT: validated (1–9, ≥ base level) and
  consumed at that level, but effect scaling is intentionally NOT implemented.
- **The trap documented for tomorrow:** `progression.total_character_level()`
  is for PB and legacy sync only. Spell-slot progression is a SEPARATE axis
  (multiclass casters combine HALF levels, rounding — and full multiclass
  tables are licensing-uncertain anyway). Deriving slots naively from total
  level is explicitly forbidden; the architecture keeps class levels and
  casting resources in different fields so the correct table can attach later.
- **Status:** Accepted.

## D59 — Targeting, range and LOS are server-authoritative; hidden info never leaks through AoE
- **Decision:** the server computes affected cells (`effects`), affected tokens
  (footprint intersection: ANY occupied cell counts — a Large token is hit on
  its flank, not just its origin cell), range (Chebyshev cells × 5 ft; range 0
  = touch/adjacent) and LOS (`los.line_of_sight` + `mapmodel.blocked_edges`,
  per-definition `los_required` flag — not every ability needs sight). Clients
  never choose affected creatures or damage. For a player actor, result entries
  and the game-log chronicle name only tokens inside that player's current
  visibility (`ws.viewer_visible_cells`, the same filter `/state` uses);
  everyone else appears as `+N hidden` — while the mechanical effect still
  applies server-side. Conservative by construction.
- **Status:** Accepted. Tests: footprint-flank hit, wall/door LOS, out-of-range
  refusal, and a fog-hidden NPC that takes damage but is never named.

## D60 — Sprint 8: reject-not-reroute movement, one-shot traps, fog-off room flag, NPC blocks complete
- **Movement:** a `move` that carries a `path` is a promise about the preview
  the client showed. If the server's recomputed A* differs, the move is refused
  with `route_invalid` — never silently replaced by a different route (a player
  must never watch a token walk down streets they did not confirm). Moves with
  no proposed path (DM drags/teleports, integrations) keep recomputing. Both
  views share one world: the diorama click resolves cells through the same
  camera space as `dioProj` (absolute canvas coords), so Tactical and Diorama
  produce identical previews (D59 extended to input).
- **Downed gate:** `_movement_block_reason` blocks preview/move/teleport at 0
  HP and is re-checked at every walk step (`stop_reason:"downed"`). NPC tokens
  at 0 HP stay DM-draggable by design (corpse handling).
- **Traps:** explicit lifecycle `triggered`/`triggered_by` beside `discovered`;
  one-shot by `triggered`, runtime flags survive `map_edit` (stale editor
  snapshots included); only re-placing a fresh trap entity re-arms.
- **Fog:** `fog_off` is a persisted room-flag inside the map, owned solely by
  `fog_toggle`; it reveals terrain+static entities to all members while the
  LOS pipeline still hides live foes. `map_edit` resize preserves the
  `explored` overlap instead of wiping it.
- **NPC blocks:** `clean_npc` is the single normalizer and persists
  `abilities`/`resources`/`notes` through add_token, update_npc, Bestiary and
  spawn; long rest refills monster spell slots and resources (HP stays DM's
  call). Players receive `npc:None` — stat blocks are DM-only (unchanged).
- **Audio:** pause is a distinct state (`playing:false`, `current_id` kept);
  self-hosted sources resume in place, embeds restart (labeled in UI).
- **Status:** Accepted. Tests: `test_diorama_parity`, `test_downed_movement`,
  `test_trap_lifecycle`, `test_fog_off`, `test_npc_workflow`, `test_audio_pause`.

## D61 — Docker is the canonical runtime; delivery is loop-safe; still ONE process
- `docker compose up --build` runs the app; `docker compose run --rm test` runs the
  suite in the same pinned environment (multi-stage Dockerfile, exact pins —
  the host's Python/package state can no longer cause mysterious failures).
  Bind mount `./data:/srv/data`; run as uid 1000; HEALTHCHECK + `unless-stopped`.
- In-memory rooms keep the **single-process** assumption absolute: no uvicorn
  workers, no replicas — documented at compose/Dockerfile/README level.
- Sockets register their owning event loop (`attach_ws`); `net._send` fast-paths
  same-loop (production always does) and crosses loops only via
  `run_coroutine_threadsafe`. This removes a real class of TestClient flakes
  (starlette >=1.7 gives each WS session its own loop; anyio wakeups must not
  cross loops) without changing production semantics.
- **Status:** Accepted. Hosts without the buildx plugin need `DOCKER_BUILDKIT=0`.

## D62 — Everything persistent lives under VTT_DATA_DIR; session tokens are cookie-safe by construction
- `uploads/` joined `vtt.db` and `secret.key` under `VTT_DATA_DIR`; the container
  filesystem holds nothing worth keeping. `/uploads/<file>` URLs and DB rows are
  unchanged; `scripts/move_uploads.py` migrates legacy app-tree uploads.
- Backups/restore: sqlite online-backup API (WAL-safe, integrity-checked) +
  secret.key + uploads in one tarball (`scripts/vtt-backup.sh` / `vtt-restore.sh`).
- `make_token` emits padding-free base64url payloads: a `=` inside an unquoted
  cookie value makes cookie parsers drop the whole cookie — the old intermittent
  401 was a real production bug, not a test artifact. `read_token` re-pads, so
  deployed (padded) tokens keep verifying — no forced logouts on upgrade.
- `secret.key` is stored HEX-encoded. The old code returned raw random bytes on
  creation but `.strip()`ed on every read — whitespace bytes inside a fresh key
  (~1.6%) mutated the effective signing key after the first write. Legacy raw
  files are read unchanged (fromhex fallback), so deployed installs keep all
  sessions; hex has no whitespace, so generation/read-back are identical by
  construction.
- **Status:** Accepted. Tests: `test_deploy_hygiene`, `test_auth_token`.

## D63 — Doors gain dm_only (operation) and secret (transmission) flags, orthogonal to locked
- `locked` stays the physical/game-mechanical state; `dm_only` restricts WHO may
  operate; `secret` restricts WHO may even SEE the door. Player answers are
  information-minimal: secret door → identical to "no door at this edge" (silent);
  dm_only → "It won't budge." checked BEFORE any lock-state message; dm-only/
  secret moves never enter the shared chronicle.
- Movement/LOS keep reading plain closed state — a hidden closed door still
  blocks, which is the DM's informed choice. Server enforces everything;
  Tactical and Diorama cannot diverge because both consume the same filtered map.
- **Status:** Accepted. Tests: `test_doors_dmonly` (10).

## D64 — Forwarded headers and WebSocket origins are trusted only where declared
- `X-Forwarded-Proto` influences the Secure cookie flag only with
  `VTT_TRUST_PROXY=1`; same switch gates rate-limit client IP. Direct internet
  connections never get header-driven trust.
- WS handshakes must be same-origin against `Host` or be listed in
  `VTT_ALLOWED_ORIGINS`; mismatch closes with 4403 before accept. SameSite=Lax
  already blocks cross-site WS cookies — this is the explicit second line.
- Deployment shape is fixed: HTTPS reverse proxy (Caddy/Nginx examples in README)
  → container on loopback only.
- **Status:** Accepted. Tests: `test_deploy_hygiene`.

## D65 — Room UI is a flex app-shell with a three-region sidebar; feeds are single-surface tabs
- The viewport split is computed by flex (`#view-room` 100vh column,
  `.room-grid flex:1; min-height:0`), never by `calc(100vh - guessed_topbar)`;
  a content-driven topbar made the old math push the chat composer below the
  screen edge on wrapped toolbars.
- `.side` is non-scrolling with three fixed regions: category tabs (top),
  chronicle (flex:1 — the ONE main area), `.side-cat` drawer (bounded
  max-height, own scroll). The previous single-scroll-column + sticky-tab-bar
  design stacked chat/log/dice against a 220px floor and let panels slide
  under the bar — the reported overlap; it is structurally gone, and
  `test_layout_pins.py` fails if the removed patterns (faked viewport height,
  sticky `.side-tabs`, `min-height:220px`, dice strip as chronicle sibling,
  multi-surface feed) return.
- Chat / Game Log / Dice are mutually exclusive feed tabs inside the
  chronicle (`switchFeed` + `applyFeedPanels`), composer rows are chat-only,
  roll results mirror to `#dice-out`; the user's last feed tab is remembered
  per browser profile. Initiative/Party stay stacked in the drawer so combat
  keeps initiative and chat visible together.
- **Status:** Accepted. Pending: human browser checklist (MANUAL_FIX_NOTES.md);
  spatial/movement sprint starts only after that verification.

## D66 — All gear math runs on sheets; gear.as_sheet/as_row are the only row converters
- The modifier-matrix test exposed a silent production bug: PC save/skill/spell
  paths passed RAW DB rows (JSON-string columns) into `gear.*` helpers, where a
  non-dict stats value degrades to modifier 0 — PC saves showed +3 where the NPC
  equivalent showed +4. The NPC path had always converted correctly.
- Fix: `db.j` idempotent; **`gear.as_sheet()`/`gear.as_row()` are THE canonical
  row↔sheet converters**; every load feeding gear math goes through
  `as_sheet` (single choke point `roller_char` + explicit wraps at each site).
  `_stat_mod` is shared PC/NPC (clamp floor 1, ceiling 40).
- NPC `to_hit`/`dmg` stay author-authored complete bonuses — no double-adding
  of stat/prof by the engine.

## D67 — Maps grow automatically for exploring players (chunk 12, cap 80×60)
- A PLAYER-owned token within `FOG_R + GROW_MARGIN = 11` cells of an edge
  (footprint-aware) grows the world by `EXPAND_CHUNK = 12` cells in that
  direction; new cells are plain floor and unexplored; fog, traps, loot, pins,
  doors and token positions re-anchor with the world (`mapmodel.grow_map`,
  `room/growth.maybe_grow_map`).
- Triggers: end of a WALK that reached its target (`stop_reason is None`) and
  player teleports. Never: NPC/DM-owned tokens, blocked/downed/trap stops, or
  mid-walk (a coordinate shift under a running route would corrupt it).
- Cap stays `MAX_W/MAX_H` (80×60); at the cap growth is a silent no-op.
  Players receive `map_expanded` and the client compensates the camera by the
  shift, so the view stays stable. Tests that pin absolute coordinates park
  tokens in the safe zone (`tests/test_movement_fog.park`).

## D68 — app/movecost.py is the cost SSOT: 5e diagonals 1,2,1,2 for display/budget; search weights stay 10/14
- Displayed route cost follows the 5e grid rule (first diagonal from the start
  counts 1, then 2, 1, 2…; difficult terrain and low obstacles double the
  entering step). The alternation is route-history dependent, therefore the A*
  keeps its constant search weights (straight 10, diagonal 14, difficult ×2) —
  cost is computed over the FINAL route, never during search.
- The preview payload gained `speed_ft`, `budget = speed//5` (squares) and
  `within_budget`; the move HUD shows `cost/budget squares`. This is a
  transparency surface only — enforced turn economics remain combat-scope.

## D69 — Terrain registry 0–4: barrier and low obstacle join the vocabulary; wall.py is the semantics facade
- Cell vocabulary: 0 floor, 1 wall, 2 difficult, **3 barrier** (blocks
  movement, NOT vision; climbable), **4 low_obstacle** (passable, double cost,
  climbable). `mapmodel.TERRAIN` is the single registry; `mapmodel.sanitize`
  clamps 0..4 (an intentional, documented change of the old 0..2 clamp).
- `path`, `los`, `footprint`, `movecost` consume the registry
  (`walkable/difficult/blocks_vision`) — no hard-coded cell values left.
  `wall.py` answers cell queries (blocks_movement/blocks_vision/climbable/
  height_units) for DM-facing features.
- Editor brushes: 🚧 barrier, 🪨 low obstacle.

## D70 — Elevation is an integer layer on the map plus tokens.z; one unit per step
- Map gains `elev: [int]` (-6..6, clamped; missing/invalid → flat — old maps
  load unchanged), grown/remapped with the world like cells. Players learn
  height only through explored fog (None = unseen).
- Stepping between cells whose elevations differ by ≤ 1 unit is legal; ≥ 2 is
  a cliff (blocks path, preview and forced moves). Movement legality checks
  newly covered footprint cells against their neighbours.
- `tokens.z` (additive migration, default 0) always mirrors the ground cell the
  token rests on — walks and teleports sync it; it is not free-flying.
- Cover/LOS height interactions and multi-floor maps are explicitly OUT (3D).

## D71 — Forced movement is DM-only, not a walk, and never grows the world
- `app/room/moveforced.py`: push | pull | shove | knockback | throw move a
  token along a straight line toward {tx,ty}, stopping at the first cell it may
  not legally occupy (wall/barrier, occupied square, cliff); teleport is exact.
  All reuse the authoritative footprint/terrain checks.
- Explicitly NOT registered in `movement._walks`, no walk budget consumed, and
  **no automatic world growth even for player-owned tokens** — growth stays an
  exploration phenomenon. z follows the destination ground; a mid-walk target
  has its walk cancelled first; player-owned tokens still reveal fog on arrival.
- DM-only over the socket (`forced_move`); players get an error, tokens of
  others are fair game for the DM.

## D75 — Every view frames itself: no unframed camera, per-mode camera slots, ?debug diagnostics

Manual browser testing (sprint 10) found the player view COMPLETELY BLACK while
the DM saw fine, and the Diorama felt like a one-way door. Root causes proven
by running the REAL renderer code against a player-shaped payload (Node vm):

1. No client ever framed the camera. `openRoom()` left `state.cam` at (0,0);
   a token living deep in the world renders its known ring far outside the
   viewport, and unknown cells paint NOTHING -> a black canvas. The DM never
   notices (their camera was already panned there, and DM sees everything).
2. The Diorama's isometric projection has no fit either: a default 40x26 map
   projects past 800x600, so almost all tiles left the screen (3 of 126 in
   view in the probe) and nothing was clickable; panning was hidden on
   middle/right-click only. "Can't return" was a black canvas in BOTH
   directions — the topbar switch itself always worked and is not coverable.

Fix: `centerOnMyToken()` / `fitDiorama()` (both reuse `visibleHere`, so they
reveal nothing the viewer may not see), called via `initViewCam()` after
`resize()` in `openRoom`, on assignment ("Bring"), and on mode switch;
per-mode camera slots `state.camT/camD` make Tactical->Diorama->Tactical a
guaranteed round-trip. Presentation-only: no server round-trip, no world
mutation (pinned by tests). `?debug` in the URL shows view mode, map window,
own token cell, known/explored counts and painted tiles — diagnostics for the
next "all black" report, derived solely from this viewer's own payload.

## D76 — Room deletion is creator-DM-only, cascades fully, and announces room_deleted

The lobby had no way to remove junk rooms and the server had no endpoint.
`DELETE /api/rooms/{code}` now requires membership role `dm` AND being
`rooms.dm_id` (the creator) — a crafted player request 403s, a stranger
403/404s, a second delete 404s. One transaction cascades this room's rows
(tokens, messages, room_state, notes, quests, room_members, rooms); only the
room's OWN `map_image` upload file is removed (never shared assets).
`net.purge_room_nowait` then announces `room_deleted`, closes every socket on
the loop that owns it, cancels walks on the loop that created each task
(`Task.get_loop` — deliberately NOT via the lifespan LOOP, which TestClient
never starts), and forgets `_clients/_map_locks/_last_seen`. `ws.py` teardown
checks the room row before any bookkeeping (else the FK on a deleted room
throws and resurrects zombies). Client: `room_deleted` -> lobby + no reconnect;
`btn-back` remains the permanent escape in every view and role.

## D77 — Automatic world growth is feature-flagged OFF: a working fixed map beats a broken infinite one

Automatic expansion (D67/D72) survived three rounds of manual regressions
(token teleport, fog artifacts, player-triggered surprises) without ever being
verified in a real browser. The human's standing preference: stable fixed map.
`mapmodel.AUTO_GROW` (env `DNDTABLE_AUTO_GROW=1`) now gates the trigger;
default OFF. The growth machinery, invariants (world coordinates NEVER move)
and its full test suite stay in place and run with the flag explicitly enabled
— re-enabling is a config change, not a rewrite. DM map-editor resize remains
the manual path. Expansion status: implemented, tested, NOT READY for default.

## D78 — One build token binds the frontend: the black canvas was a mixed script generation, not the grid

Three sprint-rounds of "black screen / Bring fails / fixes work in tests but
not in the browser" end with a verbatim browser error:
`ReferenceError: gridOrigin is not defined`. The string proves the mix:
`50_canvas.js` (D72, calls `gridOrigin`) ran against a cached pre-D72
`10_core.js` (which does not define it) — `index.html` requested every asset
under an unchanged URL with no `Cache-Control`, so after rebuilds browsers
freely assembled half-old/half-new bundles. The first ReferenceError killed
the `requestAnimationFrame` loop silently -> black canvas; Bring succeeded
server-side (verified against the live DB) but the presentation code throwing
right after it made the success look like "grid not found".
Decision: an asset pipeline WITHOUT a bundler — `app/buildinfo.py` hashes all
owned JS/CSS + index.html into ONE generation token; `/` renders
`?v=<token>` onto every asset URL plus inline `window.__BUILD__`; all
bootstrap/asset responses are `no-cache`; `GET /api/build` publishes token +
per-file hashes (identity only, no paths/secrets); startup logs `BUILD <tok>`.
`99_boot.js` loads last, verifies (a) required cross-file globals exist,
(b) every module stamped itself with the page token, (c) every fetched
`/static/js/*` carried `?v=<token>`, (d) server token == page token — and on
ANY mismatch shows a red banner, logs to console and DOES NOT boot, instead of
degrading into an unexplained black canvas. Bring now reports the
authoritative result and the presentation result separately, so a placed
character can never be mislabelled as a failed Bring again.

## D79 — The turn/movement loop is completed in place: squares everywhere, Dash spends the Action

The D74 engine (turn inside the ONE initiative object, movement.py
enforcement, movecost SSOT pricing) existed but had never been wired whole:
`end_turn`/`dash`/`turn_mark` were not registered in dispatch (three finished
handlers were dead code), and `move_total` was seeded in FEET while `walk()`
and the preview priced routes in movecost UNITS (squares) — a listed token
could walk five times its turn budget, and `within_budget` lied during
combat. Decision: complete, do not redesign. `begin_turn` now prices
`move_total = movecost.walk_budget(speed)` — the same single formula that
validates, charges and previews; there is still no second tracker and no
second cost function. Dash spends the ACTION (correcting the D74-era bonus
experiment) and adds one turn-speed to `move_total` for this turn only —
stored speed untouched, a spent Action can never dash twice. End Turn is the
owner-of-active-turn (DM exempt as everywhere), advances the existing
initiative and hands the next combatant fresh resources. Outside combat the
economy provably does not apply (movement stays unlimited; pathfinding,
fog, doors, traps, footprints unchanged). The compact turn bar in the
Initiative panel renders the server's initiative object only — Diorama and
Tactical share it because combat is world state, and a pinned Node test
proves the view round-trip mutates none of it.

## D80 — Conditions get ONE clock each; downed/incapacitated gates move; Stand Up is an explicit, budgeted operation

The condition store (`tokens.conds`, `app/conditions.py`) only had a round clock
and no way to express "lasts until the start/end of my turn", while the
incapacitated conditions carried no movement consequence at all. Decision:
extend the SAME store, never fork it. Every entry is `{k, rounds, until}` and
`until` picks the condition's single clock: `""` = round clock (ticks once at
the round wrap, as before), `"start"`/`"end"` = the affected creature's own
turn clock, advanced ONLY by the combat turn hooks — `step_rounds` never
touches anchored conditions and `step_turn` never touches round conditions,
so double-stepping is structurally impossible. The turn lifecycle itself is
consolidated into ONE function (`combat.advance_turn`): end-of-turn hooks of
the leaving token → initiative advance → round clock on wrap → start-of-turn
hooks of the new token → fresh resources. Outside combat no clock runs;
walking through the map advances no duration, provably. The voluntary-movement
gate (`_movement_block_reason`) now blocks 0-HP (downed) AND the incapacitated
family (`incapacitated, unconscious, paralyzed, stunned, petrified`) for any
client request, at the entry and again on every walk step; restrained/grappled
deliberately are NOT in the set (their mechanics are their own future feature).
DM moves and `moveforced` (push/pull/teleport) are separate authority paths and
unaffected. Standing from prone is a new server operation (`stand`): explicit,
never moves the token, free outside combat; in combat only on the creature's
own turn and charged `ceil(walk_budget/2)` — half the BASE turn movement,
independent of a Dash boost — through the SAME `spend_move` accounting Dash and
walking use; rejection leaves prone untouched; the client's turn bar updates
from the authoritative initiative broadcast. No attack advantage rules, no
crawling, no spell-specific logic (out of scope, by design).

## D81 — Token footprints are rectangles; one helper derives every occupied cell set  (EXTENDED BY D82: visual size, facing, controller and mount are separate axes)

Footprints were locked to the square size categories (Large=2x2, Huge=3x3),
which cannot express real creatures like a 3x7 serpent. Decision: token
position `(x, y)` remains the canonical anchor (centre of its top-left
occupied cell); two optional columns `tokens.fw`/`tokens.fh` give the
independent WIDTH and HEIGHT in cells (clamped 1..10). `NULL` means "square of
the size category" — so EVERY existing token keeps loading and behaving
exactly as before, no migration of data required, and changing the size
category clears a custom span back to its square. The rectangle itself is
derived in exactly ONE place: `footprint.token_span` feeding
`footprint.origin_cells` (extends right and down from the anchor);
`footprint.wh()` normalizes the legacy `side`-int parameter that already ran
through path/movecost/mapmodel into a `(w, h)` pair, so movement, collision,
path preview/execution, world growth, vision source cells, snapshot visibility
and the ability/hit intersection all became rectangular by going through the
same code path — no caller may compute footprint cells from size on its own.
The diagonal mid-footprint rule and the difficulty rule ("any newly entered
cell") generalize without touching A*. Footprint size does NOT change speed,
budget or cost. Rotation/facing is explicitly out of scope: 3x7 stays 3x7
until a later rotation feature exists. Client mirrors via `tokenSpan(t)`
(fw/fh win, category is the fallback) for rendering, hit testing and the path
preview goal marker; hidden NPC tokens leak neither size nor fw/fh to players.

AMENDMENT (Sprint 15B): resizing is a first-class operation (`token_span`,
owner or DM): the COMPLETE new rectangle must fit at the token's CURRENT
anchor — an ill-fitting resize is rejected unchanged and never relocates the
token. The sheet's labelled Footprint W/H + Apply row is the single edit path
for every controllable token. Render-loop code must not shadow the viewport
`w`/`h` names (the 15B invisibility incident, pinned in `test_sprint15b.py`).

## D82 — Visual bounds, facing, controllers and mounts are separate from mechanical truth  (FACING CLAUSE SUPERSEDED BY D83: rotation now ORIENTS the mechanical footprint too, centre-preserved; the visual≠mechanical separation itself remains)

The tactical board has been showing a token's MECHANICAL footprint ever since
D81/D82-15B made it a first-class value — which forces false trade-offs: a
giant-wyrm artwork in a 2×2 body, a token facing east, a wolf the ranger
plays, a centaur that rides. This decision keeps the mechanical axis
untouchable and introduces four strictly separate axes beside it. All columns
are nullable additive migrations (`NULL` = old behavior), so every existing
room loads and renders exactly as before.

**Visual bounds (`tokens.vw`/`vh`).** Optional VISUAL width/height in grid
cells for the tactical renderer; when unset they default to the EFFECTIVE
collision span (`footprint.visual_span`), so legacy tokens render unchanged.
The visual rect is CENTERED on the mechanical footprint center — the one
anchoring rule; future artwork masks may refine it, but presentation may
never change which cells are occupied. Occupancy, collision, A*, vision
source cells, trap/AoE mechanics and combat budgets keep asking
`token_span()`/`occupied_cells()`; they never call the visual derivation —
VISUAL BOUNDS ARE NOT MECHANICAL OCCUPANCY. `token_visual` (owner or DM) is
the only write path; unlike `token_span` it needs NO clearance check, because
it can legally displace nothing. The collision outline is drawn when useful
(selected / map-editing / `?debug`) instead of permanently; the hit test
follows the visible artwork (clicking art = selecting the token), which is
presentation — the server still collides with the mechanical rect only.

**Facing (`tokens.rot`).** Visual orientation, normalized server-side to
0/90/180/270 (`footprint.clean_rot`); `token_rotate` (owner or DM) persists
and broadcasts it. Tactical rotates the body/ring group around the visual
center and keeps labels, HP bars and condition dots upright; a gold facing
wedge makes rotation visible even on plain circle tokens. ROTATION NEVER
ROTATES THE MECHANICAL FOOTPRINT — a 2×4 collision rect does not silently
become 4×2 because the artwork turned; mechanical rotation would be its own
future mechanic.

**World objects (`mp["objects"]`).** Generic levers/switches/chests as
map-authored DATA, same lifecycle as traps/loot (sanitize → runtime state
merged across editor saves). An INTERACT definition is a label plus exactly
one ALLOWLISTED operation — `toggle` (generic boolean `state.on`) or `door`
(open/close an existing door through `doors.door_toggled`, the one door
lifecycle shared with the direct door click: same reveal, chronicle, event
fact). There is no eval, no expression language, no scripting field — DM
automation may later call these same operations, never generated code.
Authorization follows the door precedent: adjacent (or overlapping) token
required, dm_only answers "It won't budge." before any state detail, and a
linked SECRET door answers "Nothing happens." without confirming it exists.
Players receive label and operation KIND only — never the linked door
position; the server resolves by object id.

**Controller (`tokens.controller_user_id`).** A DM-assignable generic
relationship (companion/familiar/hireling FOUNDATION, not class rules): a
room member who may act through the token. The single question "may this user
act through this token?" is answered ONLY in `room/authz.py` (`controls()`);
movement, path preview, dash/end-turn/turn-mark, conditions and Stand Up,
death saves, casting and door/object reach were rewired through it — the
owner idiom is never re-implemented per module. A controller is NOT an owner
and NOT an account: no character-sheet rights, no fake login, the DM always
keeps full authority, assignment is revocable at any time (`token_controller`,
targets must be room members), and a controller token reveals NO fog — fog
sources stay owner-scoped, the companion is DELIVERED to its controller
without lifting sight for anyone.

**Mount (`tokens.mount_token_id`).** A rider rides at most one token in the
same room; assignments are validated acyclic (self and multi-hop chains
rejected). Deliberately SEPARATE from the controller relationship (who acts ≠
who carries) and deliberately NOT a parent-coordinate system. This ships the
RELATIONSHIP layer only (persist/broadcast/reconnect/persistence tests);
carrying movement is a distinct mechanic and was not silently half-built.

Invariant summary — VISUAL BOUNDS ARE NOT MECHANICAL OCCUPANCY;
`occupied_cells(token)` is gameplay truth; renderer presentation must never
become collision truth; a CONTROLLER RELATIONSHIP IS NOT LOGGED-IN USER
OWNERSHIP; a MOUNT RELATIONSHIP IS NOT THE CONTROLLER RELATIONSHIP; and
INTERACTION DEFINITIONS ARE DATA driving allowlisted operations, never
executable code. Diorama (out of scope in this sprint) ignores the new axes
and keeps its old behavior; Tactical is the reference renderer that got the
feature. Hidden NPC tokens leak none of the new fields (vw/vh/rot/controller),
parity with the D81 geometry-leak guard.

## D83 — Rotation orients the entity (footprint included); centre-preserving anchors; riders are carried; per-mode move ledgers

Supersedes D82's facing clause after a REAL browser result: "rotation rotates
the visible token but not its mechanical footprint" and "the visual sits at
the top-left of the footprint" were wrong for entities. D82's VISUAL≠MECHANICAL
separation stays — the two boxes are still independent sizes; what changed is
that both are now ORIENTED by the same facing and SHARE a centre.

**Orientation.** `footprint.orient(span, rot)`; `token_span()` now returns the
EFFECTIVE oriented box (a 3x7 at 90/270 IS a 7x3) — occupancy, collision, A*,
LOS, traps, AoE, preview and path validation all follow automatically because
every consumer already goes through `token_span`/`occupied_origin`. `base_span`
is the un-rotated stored shape for the rotation op and UIs. `visual_span`
orients vw/vh by the same rule. No caller anywhere may swap width/height by
rotation itself; the client mirrors the same two functions (and the renderer
uses BASE visual dimensions inside its `ctx.rotate` transform — feeding it
oriented dims would rotate the artwork twice).

**Centre convention (integer-only).** World coordinates stay pixel+cell
integers. THE rule is `anchor_for_center(origin, outer, inner)`:
`anchor + (outer−inner)//2` per axis (floor is the documented tie-break; a
mixed-parity turn moves the doubled centre by exactly one half-cell). Reuses:
rotation re-anchoring (the entity turns around its centre instead of
teleporting), carried riders (rider centred inside the mount's oriented box),
and the visual centring that D82 already had. 90-then-180 back lands on the
EXACT original pixel — pinned.

**Rotation is validated.** The rotation op (owner-or-DM as before) cancels any
walk, computes the new anchor, and runs the EXISTING `valid_final_position`
check; an illegal turn (bounds, blocking terrain, overlap) is rejected with
rotation, position and footprint fully intact — the server never rotates and
relocates to make it fit. The facing broadcast carries NO coordinates (D63
leak-parity); the re-centring move rides the visibility-filtered step channel.

**Mechanical partial SELECTs must carry `rot`.** Eight room-wide token SELECTs
feed collision/LOS/spawn — any geometry column omitted silently un-rotates
that subsystem. `rot` (and `mount_token_id`) are now part of that required
column set; new geometry columns must be added to all of them.

**Mount carrying.** A moving mount (authoritative walk, DM teleport, forced
movement, rotation re-centre) carries its riders: `movement.carry_riders`
re-centres every transitive rider with `anchor_for_center` and broadcasts
through the filtered step channel. Riders NEVER spend their own movement (the
carried footprint is latent: the mount's legal position is their position, and
`footprint.collision_cells` treats mount↔riders as ONE entity so a rider can
never block its own mount). Nested chains propagate top-down, bounded and
cycle-tolerant; the assignment-time cycle guard stays the real protection.
Dismounting re-homes the rider deterministically via `find_valid_origin`.
Mounted combat rules, mount/dismount action costs and speed bonuses remain
out of scope.

**Movement modes are a bounded FOUNDATION.** `gear.clean_speeds`
(walk/fly/swim/climb) was already the data SSOT; `movecost.walk_budget` stays
the ONLY feet→squares conversion — per mode. One active mode per movement
operation (a creature's missing mode is refused, never substituted). The turn
object gained per-mode ledgers `move_by {mode:{total,spent}}`; the legacy
top-level `move_total/move_spent` mirror the ACTIVE mode, so every pre-D83
reader keeps working. Switching modes can only spend each mode's own
remaining budget — the per-turn ceiling is sum(mode budgets) plus ONE Dash,
which now doubles every mode exactly once behind the spent Action. No
step-wise mixed-mode accounting (would need a combat redesign; refused).
Fly ignores difficult terrain and the elevation cliff gate while still
respecting walls, closed doors, blocked edges and world bounds. Swim/climb
ship as DATA ONLY — the terrain registry has no water or climbable semantics
and inventing fake terrain rules was explicitly declined.

**Forced movement is its own operation layer.** `moveforced.apply_forced_move`
is the single server-side entry (handler now validates and delegates; zero
position writes outside it). Traps and future allowlisted interactions call
it directly, never impersonating a player. It still spends no voluntary
budget and is not gated by the downed/incapacitated VOLUNTARY movement gate.
`knock_prone` (D83, DM entry) applies the EXISTING D80 prone condition — one
prone representation — for future trap/fall hooks; no height math, no damage
tables (elevation sprint territory).

Invariant summary — VISUAL SIZE ≠ MECHANICAL FOOTPRINT (sizes independent);
ROTATION ORIENTS THE ENTITY AND THEREFORE ITS MECHANICAL FOOTPRINT; VISUAL
AND MECHANICAL BOUNDS SHARE A CONCEPTUAL CENTRE; `occupied_cells(token)`
REMAINS GAMEPLAY TRUTH; FORCED MOVEMENT ≠ VOLUNTARY MOVEMENT; CONTROLLER ≠
OWNER; MOUNT RELATIONSHIP ≠ CONTROLLER RELATIONSHIP; CARRIED RIDER DOES NOT
SPEND PERSONAL MOVEMENT. Diorama untouched as ever; Tactical is the
reference renderer.

## Cross-cutting assumptions (read before scaling)
- Single uvicorn process, single event loop; `LOOP` captured in `main.py` for thread-safe broadcasts.
- `VTT_DATA_DIR` isolates the SQLite/`secret.key`/uploads tree.
- Public deploy expects a TLS reverse proxy in front (see README Notes).

## D84 — The clicked cell is the token's CENTER; anchor conversion lives in exactly one place
The wire contract for `move`/`path_preview` said goal cell, the client drew and
hit-tested footprint CENTRES, and the server treated the goal as the top-left
ANCHOR. For 1x1 tokens the two coincide — every bug hid there until big and
rotated tokens made it obvious ("No path there" while the ring hovered free
air; the companion arriving as 1x1; the DM drop shifting 3x7). D84 fixes the
CONTRACT, not the symptom: the clicked/aimed cell is the desired centre of the
ORIENTED box; `footprint.center_to_anchor(cell, span)` is the single rule
converting it to the canonical landing anchor — the same floor tie-break the
existing `anchor_for_center` uses (even spans bias lower-right), so a 1x1 is
bit-identical to the old behaviour and nothing else had to change semantics.
Both server entries (move + preview) convert; the preview response echoes
`goal` (aimed centre) AND `anchor` (landing box) so the client can draw the
truth it is being granted. Client-side: a drag-drop lands a token with its
CENTRE on the drop cell (not the pointer cell), the plan ring draws at the
server's anchor, Escape deselects, and the footprint overlay is a thin dashed
OUTLINE — the old translucent colour block read as a stuck debug rectangle.
Pointer→cell math is proven by a node-vm harness that runs the REAL
10_core/50_canvas click path against a rotated 3x7 and checks the wire cell.
**Clicked cell == intended footprint CENTRE, on the wire; the anchor is a
server-derived implementation detail.**

## D85 — Token artwork: server-cleaned PNG assets with opaque ids
Token art is the one place where users feed BYTES into the renderer, so the
pipeline is adversarial by design (`app/assets.py`): size cap → PNG magic →
Pillow FORMAT check (a GIF wearing a .png name is a lie, refused 415) →
dimension/pixel caps (decompression-bomb gate) → FULL decode (truncated or
malicious pixels raise, 415) → metadata strip → clean re-encode → final size
re-check → atomic write under DATA_DIR/assets/<uid>/<random-hex>.png → row.
Display names are titles, never paths. Asset ids are 16 random hex chars;
"not yours" and "does not exist" answer with the same 404 — no existence
oracle. An asset may be served to its owner and to members of any room whose
tokens wear it (`/assets/<id>` carries nosniff + image/png, auth per request,
NOT a static mount). Assignment (`token_image`) trusts only the opaque id;
players attach their OWN assets, the DM any; the token column stores nothing
but the server-made `/assets/<id>` form — a client-typed URL is an error, not
a feature. Delete is refused while a live token references the asset (a 409
with a defined story beats a silently broken token). Hidden NPC tokens leak
no artwork, parity with D81/D82 leak guards. The canvas draws the image
inside the token's own rotate frame (ONE rotation — facing turns the artwork,
the artwork never rotates twice), aspect-preserved, clipped to the body
ellipse; colour remains the fallback while loading and for unlit tokens.

## D86 — Floors are independent occupancy/visibility planes inside one map
Multi-floor without a second map engine: a room keeps its single map and gains
a DM-curated floor list. The PRIMARY floor ("") predates the feature, so no
data migration exists — every token starts on the primary plane. Tokens on
DIFFERENT floors never collide, never block pathfinding, and are not visible
to a viewer who stands on another plane (planes are not fog — being elsewhere
reveals nothing, not even which plane, so hidden tokens leak neither floor
nor artwork). The collision feeds gained ONE parameter (the mover's floor) at
their choke points (`_room_tokens`, `_room_token_rows`, forced movement) and
visibility filters per viewer-plane sets computed from owned/operated tokens;
a viewer without tokens (the DM) sees every plane. Changing floors is the
explicit `token_floor` operation — stairs, ladders, teleporters; it costs no
movement budget and re-evaluates every viewer through the same
add/leave machinery the fog already uses. Mounted riders ride along.
**FLOOR ≠ FOG: same map, different plane; collision and visibility are
per-plane, terrain and the world window are not.**

## D87 — Darkness: sight comes from carried light only
A room may be dark (DM toggle, `grid.dark`, explicit `map_edit` field — stale
editor snapshots must not flip it, fog_off precedent). In a dark room a
player's vision is exactly the union of the LOS-limited light radii of the
tokens they own or operate (`token_light`, 0-30 cells, owner/DM-set) plus
each such token's own footprint cells — light 0 means you feel the floor you
stand on and nothing more. Walls cast real shadows (same LOS engine, same
blocked edges); the DM is never restricted; non-dark rooms behave EXACTLY as
before (single branch in `viewer_visible_cells` — the choke point every
visibility consumer already shared, which is why lighting needed no new
transport). Changing any light re-evaluates every viewer: newly seen tokens
arrive via the standard `token_add` path, lost ones via `token_leave`, and a
`grid_reveal` nudge refreshes terrain. Hidden tokens leak neither radius nor
plane. **IN A DARK ROOM, LIGHT IS VISION — and every light you carry is a
window into your position.**

## D88 — Independent floor maps: one world frame, per-plane content

Rooms may now hold a MAP PER PLANE. The primary floor ("") keeps reading the
legacy `room_state.map_json` byte-for-byte — zero migration, every old room
behaves identically. Named floors get their own row in the new
`floor_maps(room_id, floor, map_json)` table (UNIQUE index added in
`init_db`, dedup-safe for DBs created mid-sprint). `net.get_map(room_id,
floor)` / `set_map(..., floor)` are the single seam: every former call site
(movement, walk, forced moves, doors, fog, interact, vision, /state, map/fog
edits) is now plane-parameterized. Invariants: every floor map is
`mapmodel.fit()`-clamped to the PRIMARY map's dimensions and world anchor
(one camera, one world window, one growth story); `fog_off` stays room-wide
(primary-SSOT, injected into every plane read); `dark` is a per-floor field.

Vision is computed ON THE MAP THE TOKEN STANDS ON — never is a crypt token's
visibility decided by the tavern's fog (`send_token_event`, /state
`_visible_token` via per-plane caches). Player transitions run only through
validated connectors: the D82 allowlisted `stair {floor,x,y}` object op,
reach-gated like doors, destination validated on the TARGET plane (terrain +
occupants; occupied or walled refuses outright, viewing never moves anyone).
Plane-scoped delivery (`net.send_to_plane`) keeps `fog_changed`, door reveals
and `object_state` from ever repainting a socket that stands on another
plane. DMs get a view-floor selector; players' /state is always their own
primary plane (their first owned — else operated — token's floor).
Remaining documented limitation (SPRINT 18/19): `abilities.py` resolved areas
on the primary map (aoe/pings room-global). CLOSED BY D90.

## D89 — Lighting v2: lamps are world objects, darkvision is a private sense

Static light sources are authored, not coded: map objects with the allowlisted
`lamp {bright}` op light their PLANE for everyone standing there — light is
not owned information — and each source reveals exactly what its own LOS
carries (`_lit_cells` per plane). Lamps toggle through the same allowlisted
interact op; the boolean `state.on` carrier now PERSISTS explicitly-off
(`{"on": false}` is truth — the sanitizer previously normalized it away, a
latent D82 lever bug). Token `darkvision` (new column, 0–30) is a SENSE:
owner-only in the dark-branch sight budget, DM/owner-writable via the
filtered `token_darkvision` channel, stripped from every hidden-token
payload like light/floor. Map edits that add or move lamps re-run the
per-viewer visibility decision; plain terrain edits keep the classic
next-move semantics. **The Sprint-19 audit additionally closed L1–L5: all
property broadcasts (`token_image/span/visual/rot/controller/light/floor`)
now travel via `visibility.send_property_to_interested` (DMs, owner, current
controller only); first-sight `token_add` and the ghost store use the same
hidden-strip as the add channel; asset listing/serving follows the RIDING
token (own/operate it, or DM its room) instead of room membership; floor
changes validate the destination and refuse mounted riders; cross-plane
mounts are rejected; and operated tokens light nothing their controller
should not see.**

## D90 — The caster's plane is ability truth; templates and pings are plane events

Sprint 20 closes D88's documented limitation on the real dispatch paths.

**Ability resolution.** `abilities.execute` loads its map through the ONE
plane seam (`net.get_map(room_id, caster_token.floor)`) — so range, LOS,
cover geometry, obstacles, footprint frames and the naming filter all answer
to the CASTER's plane, never to `room_state.map_json`. Area targeting
(`tokens_in_cells(floor=)`) never considers another plane's tokens: a token
elsewhere is not "hidden in the blast", it is not there — entries,
hidden_count and the chronicle all agree. A `single` target on another plane
is refused with the SAME message an unknown id gets (`No target token`): the
channel is not an oracle for "a token exists somewhere else". No second
targeting engine: the ability executor gained one floor variable and one map
seam call.

**Vision sources.** With a plane passed (`viewer_visible_cells(..., floor)`),
a viewer's tokens are sight sources only on their OWN plane's map — a
lantern or the mere body of a token on the attic no longer projects phantom
vision into the crypt's coordinates (classic and dark branches, all live
call sites: token delivery, `/state`, path previews, ability naming).

**Property channels.** Condition bumps for tokens without a table presence
(hidden NPC tokens) are delivered through the token-delivery audience
(`visibility.send_cond_bump`) — an AoE that restrains an unseen patrol no
longer announces id+condition to every socket.

**Templates and pings.** `aoe` (DM tool) validates the claimed floor
(map_edit precedent) and delivers via `net.send_to_plane_viewed` — the
plane's token holders, every DM, and the token-less observers who, per the
`/state` convention, stand on the PRIMARY plane. `ping` follows the same
watcher set for delivery; its SEND gate keeps the historic primary-plane
freedom (a ping claims no position; joining before seating was always legal)
and requires standing on (or DM-ing) any NAMED plane. Both clamp bounds to
the plane's map; both carry `floor` on the wire and the client paints only
on the matching view floor. Strict map-truth channels (fog/door/object) keep
the narrower `plane_viewers` set unchanged.

**Editor resize (P3).** `edResize()` rebuilt the edit snapshot with traps,
loot, doors and objects but NOT `pins` or `elev` — sanitize then legitimately
emptied both, so every resize silently deleted the plane's pins and heights.
Carried through now (bounds-filtered pins, row-wise elevation); a pin lives
in its plane's map, so its floor association survives resize by construction.

## D91 — The presence gate is the choke point for ALL id-bearing token state

Sprint 20 closed the ability path; the audit closed the rest. Every channel
that NAMES a token with state (manual cond_add/cond_remove/stand,
knock_prone — trap callers included, initiative-driven condition ticks, walk
`move_state`, `token_gone`) now flows through ONE helper:
`visibility.send_presence_event`. Table presence (owned token or character
token) keeps the classic room-wide channel — the gate is presence, not
sender, so players' own tokens stay fully public to the table. Unseen tokens
are delivered per-viewer through the same plane+LOS+controller decision as
the token channel itself. `token_mount` joins the D82 property audience
(rider ∪ mount owners/controllers — a player always learns who rides their
horse). `death` and `snapshot` were verified SAFE by construction (PC-only
or null-payload refetch — /state is server-filtered).

Audited-and-kept by convention: the `initiative` payload lists every combatant's
id/label (DM adding a monster to the tracker is a table-visible act; per-viewer
initiative would fork the turn UI = rewrite, not hardening); chronicle `sys_msg`
lines name conditions by design (public table record, D90).

## D92 — Inventory is the character sheet extended, never a second system; containers are D82 objects with SQLite contents

- **Context:** Sprint 22 (persistent inventory + quantities/stacks, equipment
  slots, world loot). `characters.items` already held magic items as one-entry-
  per-instance JSON; `gear.compute_ac` derived AC implicitly from owned armor;
  map `loot` entities were step-on-CELL notes, not containers; the interactable
  framework (D82) owned object authoring, fog, dm_only and reach.
- **Decision:**
  - OWNERSHIP MODEL: items stay on `characters.items` (tokens act through the
    linked character). Sheet authority = owner or DM, exactly the attune
    precedent — a D82 CONTROLLER never gains inventory rights. No parallel
    inventory table, no competing character system.
  - Item entries gain `qty` (default 1 ⇒ every old row IS a one-item stack),
    `weight`, `stackable`, `def_id`, generic `props` (sanitised scalars;
    combat integration reads them later — no D&D rules hardcoded).
    `item_defs` is a DM TEMPLATE library only; grants snapshot the def into
    the sheet (def edits never mutate granted items).
  - `app/inventory.py` is the ONLY mutation site: every op re-reads its rows
    inside `db.tx()` (BEGIN IMMEDIATE) — concurrent mutations serialise on the
    database, quantities can never duplicate, go negative or half-apply.
    Client `op_id`s claim a row in `inv_ops` inside the same transaction:
    a replayed request is a no-op (rows expire after a day).
  - EQUIPMENT: `characters.equipment {slot: item_id}` for
    main_hand/off_hand/armor/acc1..acc3; admission via a generic kind→slot
    table with `props.slot` per-item override; `props.two_handed` is the only
    cross-slot rule. AC switches to equipped mode ONLY once a slot is worn —
    empty `{}` keeps the legacy derivation byte-identical (old sheets, old
    tests untouched). Every mutation and read runs `clean_equipment`: a slot
    pointing at a vanished/lost item is dropped in the same breath.
  - CONTAINERS reuse the D82 object framework (editor, fog/dm_only
    transmission, same-plane adjacency) as op kind `container`; CONTENTS live
    ONLY in SQLite (`containers (room_id, object_id, items)`) so a
    character↔chest move is ONE database transaction, and contents never
    travel in map JSON, `/state` or broadcasts — an authorised
    `inv_container inspect` is the only carrier (requester socket only).
    Legacy map `loot` entities are unchanged (documented supersession only).
  - Transfers are member↔member of the SAME room, atomic debit+credit;
    a full or non-member target rolls the whole operation back.
- **Consequences:** `/state` carries own sheet + equipment + (DM-only)
  `item_defs`; a payload-less `inv_changed` drives refetch; the client
  refreshes on WS `onopen` so no reconnect ever renders stale quantities;
  the equip kind-table is mirrored client-side for BUTTONS ONLY (the server
  decides — forged slot claims answer with an error, not with state).

## D93 — Weapons are equipped items with typed props; attacks derive server-side and feed the ONE action ledger; peer sheet rows are an allow-list

- **Context:** Sprint 22 reserved item `props` as "combat integration reads
  these later" (D92). PC attacks existed only as a name-lookup posting a
  client-trusted `+to_hit` with no target and no AC verdict (dice.py), while
  the NPC path already did full HIT/MISS (`_target_ac`); `combat.spend_slot`
  existed but no game action consumed it; `/state` shipped EVERY member's
  full character row to every other member (only notes + unidentified magic
  were redacted); cast/resource/use_item had no replay guard.
- **Decision:**
  - ITEM WEAPONS ARE DATA: `kind "weapon"` (main_hand via the coarse slot
    table; `props.slot` still overrides). The attack profile lives in the
    SAME D92 props bag, now type-validated for the named combat keys
    (`damage_dice` regex, `damage_type` from `gear.DAMAGE_TYPES`,
    `ability` from `gear.ABILITIES`, `attack_bonus`/`damage_bonus` −10..10,
    `range_ft` 0-600, `reach_ft` 0-60, `proficient`/`two_handed`/
    `mod_to_damage` bool). A wrongly-typed key is dropped — a corrupt prop
    must never manufacture a bonus. No rules catalogue is hardcoded.
  - ONE DERIVATION: `gear.weapon_profiles(sheet)` computes
    `to_hit = stat_mod + prof_bonus·props.proficient + attack_bonus`
    (each modifier exactly once; damage may add the ability mod once via
    `mod_to_damage`). The sheet DISPLAYS these numbers and attacks by
    `item_id` only — client-supplied to_hit/dmg fields are not read. The
    legacy `characters.weapons` name path is untouched for legacy sheets.
  - ATTACK = the existing `roll kind:"attack"` engine with an `item_id`
    branch: item must sit in `characters.equipment`, target AC resolves via
    `_target_ac`, crit/fumble semantics mirror the ability engine, damage
    is ROLLED (crit doubles dice count, like every existing path) but
    APPLIED by the DM through the existing `hp` flow — same table flow as
    `npc_attack` today, no new HP writers.
  - ACTION ECONOMY: `combat.spend_slot` gets its first callers. During an
    ACTIVE initiative the attack consumes the attacker's action (or bonus
    via `slot:"bonus"`), refuses when used, refuses off-turn; outside a
    combat nothing is consumed — exactly the movement gate's established
    "table discretion" semantics. The consumption broadcasts the updated
    `initiative` so trackers stay honest.
  - REPLAY: `inv_ops` is now the project-wide op ledger (D92 pattern,
    unchanged table). Attack, cast, resource and use_item accept an
    optional `op_id`; the claim rides the same `db.tx()` as the mutation
    (cast now re-reads slots INSIDE the tx). No op_id = old behaviour —
    fully backward compatible clients.
  - SHEET PRIVACY: `/state` member rows for unrelated players are the
    tactical allow-list `{id,name,race,char_class,level,total_level,hp,
    max_hp,temp_hp,ac,ac_total,speed}`. Identity + the numbers the DM
    narrates anyway stay; stats/skills/saves/spells/slots/items/equipment/
    resources/defenses/derived/notes are sheet-private. DM and owner keep
    the full row; the room client renders peer tokens as a compact public
    card (the server field being absent is the marker — UI cannot leak
    what never ships).
  - SHEET NUMBERS ARE SERVER NUMBERS: `_char_row` ships a read-time
    `derived` block (stat mods, save/skill bonuses for the full skill
    list, prof bonus, initiative, attack profiles, attune cap). The client
    renders it; its own copies of the formulas (which used legacy `level`
    and drifted on multiclass) are gone from the sheet path.
- **Consequences:** unequip/remove instantly invalidates profiles and AC
  (both recomputed at read, `inv_changed` refetch); an attack against a
  removed item answers "No equipped weapon…"; hidden NPC data never rode
  the sheet path anyway (`t.npc` is DM-only) and now peers' sheets don't
  either. `abilities.execute` still has no turn-slot coupling (documented
  gap — the engine's cost model is slots/resources, economy can attach to
  the same `spend_slot` seam later).

## D94 — Sprint 24 audit: op claims re-read the acting row in-tx, hidden targets are invisible to attackers, client op_ids are namespaced

- **Context:** read-only audit of the Sprint 22/23 dispatch paths found three
  confirmed defects. (1) `_item_attack` derived its weapon profile from a
  character row read BEFORE the replay-guard transaction — an interleaved
  unequip/remove could make an attack roll on a stale profile. (2) the
  attack's target lookup accepted ANY token id in the room; hidden monsters
  were hittable by guessing integer ids and the dice line printed their
  label+AC (a probing oracle). (3) `inv_ops` keyed only on the client-chosen
  `op_id` — one player could pre-claim guessable op_ids and silently swallow
  other players' operations.
- **Decision:**
  - SELECT-THEN-EXECUTE IS ONE TRANSACTION: the attack re-reads its
    character row and the acting token INSIDE the claim transaction
    (`gear.weapon_profiles` on the fresh row). A removed/unequipped item
    can never arm a roll; WAL semantics make the tx snapshot the attack's
    well-defined "now".
  - AN ATTACK MAY ONLY HIT WHAT THE MEMBER COULD SEE: `_visible_to_member`
    mirrors the /state token filter (planes, fog sight, own/controlled).
    A hidden target answers with the BYTE-IDENTICAL "No target token" error
    a nonexistent id gets — attacks are not probes. DM path unrestricted
    (verified via state, not attack UI). Legacy by-name and npc_attack
    paths are DM-restricted upstream and were confirmed unaffected.
  - OP_CLAIM NAMESPACING: `_claim` stores `f"{ns}|{op_id}"` where ns is the
    acting character/object id. Client op_ids stay freely choosable but are
    only authoritative inside their own namespace; legacy un-namespaced rows
    keep working until expiry (no schema change).
- **Consequences:** cross-player op_id lockout closed without a migration;
  the ledger now guards (namespace, op_id) — same op_id reused for another
  payload by the SAME character is still silently ignored (operation-level
  guard, documented in `test_duplicate_op_id_changed_payload_is_silent`).
  DM-side damage dice caps remain DM-trust territory (a DM can author any
  NPC bonus anyway — D92 doctrine).
