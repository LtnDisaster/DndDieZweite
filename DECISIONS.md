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

## D95 — CSV content packages are DATA read by the existing engines, never code; a generic room-scoped `content` table is the round-trip source of truth

- **Context:** Sprint 25 asks for hand-editable rule content (weapons, armour,
  spells, species, classes/subclasses, backgrounds, feats, creatures) without a
  second combat/dice/character/spell engine and without ever executing code from
  a file. The engines (gear/abilities/progression/health/dice) already own the
  MECHANICS; what was missing is a place to describe WHAT exists and its
  PARAMETERS, editable by a DM and versionable as text.
- **Decision:**
  - ONE CONTENT ENGINE (`app/content.py`). It PARSES and VALIDATES CSV against a
    per-kind column schema (spec = key/required/vtype/default) and stores the
    validated row as JSON in a generic `content(kind, room_id, id)` table — that
    JSON is the round-trip source of truth for export. It NEVER evaluates code;
    anything no engine implements is carried as `manual`/`needs_choice` TEXT and
    only displayed. Validation reports file/line/column; one bad row refuses only
    its own file; unknown files are skipped; size/row/zip-uncompressed caps stop
    zip-bombs. Import modes preview/apply/replace; apply is IDEMPOTENT (an
    identical row re-imports as `unchanged`, a DIFFERENT existing id is a
    CONFLICT that apply refuses and replace overwrites).
  - REUSE, NOT REPLACE. Content only projects into the LIVE systems where a
    mechanic already exists: an `item` row becomes an `item_defs` row (D92/D93
    DM library — `gear.weapon_profiles` reads the TYPED combat props, and
    `range_normal_ft` maps to the single `range_ft` that profile consumes); a
    `spell` row `abilities.register`s as a castable ability whose `level` sets the
    slot cost (D41 deduction path unchanged). Species/classes/subclasses/
    backgrounds/feats/creatures are read back from `content` by the sheet and the
    Phase-B build engine. `main.startup` re-registers spell abilities from the DB,
    so a restart repopulates the in-memory registry.
  - TRANSPORT IS MULTIPART-FREE. The pinned image has no `python-multipart`, so
    the DM tool POSTs a file's RAW BYTES (or a whole `.zip`, auto-detected by the
    `PK\003\004` signature) to `/api/content/{code}/import`; the frontend reads
    bytes with `FileReader`/`fetch(File)` exactly as the map upload already does.
    No new dependency, no build step (D1). Export escapes spreadsheet formula
    injection (`= + - @ TAB/CR` get a leading `'`) and the importer reverses ONLY
    that escape, so export→import is byte-true.
  - ROOM SCOPING + GLOBAL LIBRARY. Content keys on `(kind, room_id, id)`;
    `room_id` 0 is a reserved GLOBAL library read by every room. Class/subclass
    ids repeat across levels, so `store_key` encodes `"<id>#L<level>"` to avoid a
    false duplicate. Authorization mirrors D92: only this room's DM may
    import/export/read counts.
- **Consequences:**
  - The projection reuses the DM library's EXACT insert (global `id` PK, same
    `ON CONFLICT DO UPDATE`, same `clean_def`); because that update does not move
    `room_id`, the FIRST room to author a def id keeps the library row while every
    room keeps its OWN authoritative copy in `content`. Tests therefore read the
    projected `item_defs` by its global id and assert the CONTENT row is the one
    scoped to the room.
  - Slot progression stays a TABLE owned by class rows (`slot_progression`) and is
    explicitly NOT derived from total level (D58). Cantrip/upcast dice scaling,
    currency (`value_gp`) and encumbrance (`weight`, STR-derived) are columns that
    already import cleanly but are deferred to Phases C–E and marked accordingly.
  - SHIPPED pack uses ORIGINAL names (`scout`, `sword_plus1`, `kin_fey`) so no
    protected text is committed; real rule packages are authored by humans
    (ATTRIBUTION.md). `tests/test_content_examples.py` imports every documentation
    example through the SAME code path, so docs and importer cannot drift apart.

## D96 — Character build is a chronology that DRIVES the existing columns, and the per-level ledger is bookkeeping — never a second source of level/HP/abilities

- **Context:** Sprint 25 Phase B needs a Stufe 1–20 build (subclass on its
  unlock level, ASI/feat on theirs, skill choices) built from the D95 CONTENT,
  without a second character/level/slot engine and without breaking D53
  (multiclass entries + derived total) or D58 (slot progression is a TABLE,
  never derived from total level).
- **Decision:**
  - `app/charbuild.py` is a PURE operation module (like `progression`). `plan()`
    reads `content.class_levels/class/load` and returns the strict chronology
    (level 1..to) plus the decisions still required — it mutates nothing.
    `apply()` advances a class FORWARD and performs only the mutations the
    engines already own: `progression.set_class_levels` (single entry per build;
    `level` stays derived), HP from the rows' `hp_base`/`hp_per_level` (fixed
    documented formula, not a roll), `gear.clean_saves`/`clean_skills` for
    proficiencies, and ASI/feat `ability_boost` written into `stats`. Anything
    no engine implements (subclass features, granted spells) is recorded as TEXT
    in the ledger and shown, never re-implemented (D95 boundary).
  - LEDGER, not truth. The build state (class id, `applied_through`, subclass,
    per-level choices, and a `base_stats` snapshot) lives in the new additive
    `characters.build` column. It drives the forward-only guard and the sheet;
    level/HP/abilities remain the columns the rest of the app reads.
  - IDEMPOTENT FORWARD BUILD. `apply()` RECOMPUTES levels 1..to from the content
    rows + accumulated decisions each time, starting ability deltas from the
    snapshot `base_stats` (never from the already-mutated row, which would
    re-stack each ASI). Guard: a rebuild to a level `<= applied_through` is
    refused; a different class once started is refused. Missing choices return
    `needs_choice` and write NOTHING.
  - ONE auth rule, ONE transport. `app/charbuild_api.py` (room-scoped) copies
    the `class_levels` authorization EXACTLY: owner always, DM only for a
    character in `room_members` of that room; the frontend lives in the room
    sheet (owner/DM), not the lobby, so there is a single owner-or-room-DM rule
    rather than a second unauthenticated lobby path.
- **Consequences:** the wizard is fully generic — the client renders the
  chronology and POSTs a choices object, and `charbuild` re-validates every
  rule, so no class logic ships to the browser and no rule can be bypassed by a
  hand-edited payload. Multiclass is untouched (build writes one entry;
  `progression` still accepts several). `base_stats` means later item/stat edits
  by other systems are NOT clobbered by a rebuild of the build-owned deltas.

## D97 — Class spellcasting is DATA the build reads and the ONE ability engine executes; slots stay a per-class TABLE, never derived from total level
- **Decision:** Phase C closes the spell axis D58 left open, with NO new engines:
  - **Consumer, not creator.** The class-row spell columns
    (`spellcasting_ability`, `cantrips_known`, `spells_known`, `prepared`,
    `slot_progression`, `upcast_scaling`) were validated in D95 but read by
    nothing; `charbuild` is now that consumer. It derives the castable ability
    ids (`characters.abilities`), a sheet display pool (`characters.spells`) and
    the slot table (`characters.spell_slots`) straight from the rows + the
    build ledger. Known-model classes CHOOSE at each level where the cumulative
    totals rise (`needs_choice`); prepared-model classes take the whole class
    list and re-prepare as a DM/long-rest step — that daily activity is NOT
    auto-faked.
  - **Slots are a TABLE, still never a derivation.** `slot_progression` is
    `level:count;…` for THAT class level; a 2nd-level half caster has two 1st-level
    slots and no 2nd-level slot, which a naive total-level lookup would never
    produce. This is the concrete realisation of the D58 trap.
  - **One cast op, now scaled and replay-safe.** Casting routes through
    `abilities.execute` (D55) — for both PACT (`cast` legacy rows) and registered
    content spells the SAME engine. `cast_level` finally does something:
    `upcast_step` raises the base dice per slot level above base; a cantrip's
    `scale_tiers` raises it by character level — generically, folded into the ONE
    base dice term (added dice must share the base die's sides, else the roll is
    left at base and `manual` covers it; nothing is fabricated). `execute` now
    claims a client `op_id` up-front inside the write transaction, so a repeated
    request consumes one slot AND applies effects once (closes the D93 gap for
    the ability path; the sheet sends `op_id` like the legacy path does).
  - **Class resources ride the generic system.** `class_resource[:spec]` +
    `class_resource_reset` become a normal resource (e.g. sorcery points,
    `short` reset); `handle_long_rest` was corrected to also refill short-reset
    resources (a long rest is never less than a short one). Slots/resources use
    the EXISTING `{max,used}` consume/restore semantics unchanged.
- **Honest limits (not faked):** choosing each new spell is a build `needs_choice`
  step; `spell_replace` swaps, daily re-preparation for prepared casters, and
  AREA/POINT aiming of a spell (cast from the tactical map, not the sheet) are
  table/DM decisions, shown as such.
- **Consequences:** the shipped technical pack gains original-name caster
  templates (`adept` prepared, `warden` half-known, `seer` known + sorcery
  points) with SRD-style — not copied — tables, and `spells.csv` demonstrates
  `scale_tiers`/`upcast_step`. Existing non-caster builds and legacy sheet
  spellbooks are untouched (a non-caster build writes none of the spell columns;
  a sheet spell not in `abilities` still casts via the legacy path). Cantrip
  scaling by total character level is legitimate (unlike SLOTS, D58 only forbade
  deriving SLOTS from total level). Tests: `tests/test_spells.py` pins the models,
  the slot table, choice-gating, resource reset, upcast/cantrip scaling and the
  duplicate-`op_id` guard.

## D98 — Gear is a DERIVED overlay consumed by the existing math, never a second equipment engine or a persisted stat
- **Decision:** Phase D closes the weapon/armor/magic-item axis WITHOUT a second
  engine. The item SCHEMA already carried almost every column; what was missing was
  the CONSUMERS, which ignored `attribute_*`, `ac_base/ac_bonus/ac_max_dex`,
  `skill_prof/save_prof/expertise`, `darkvision_ft`, `speed_bonus_ft`,
  `extra_damage_dice`, `finesse`, versatile grip, `range_long_ft`, `attune` gating.
  - **One derivation, transient.** `gear.effective_gear(char)` computes effective
    scores + skill/save/expertise sets + darkvision + speed FROM the base columns +
    `items` + `equipment` on EVERY read, and NOTHING is memoised on a mutable dict
    or written back. `attribute_set` applies first (`max(base, value)` — an item
    never lowers a score), then `attribute_bonus` (stacking deltas); `_stat_mod`,
    `dex_mod`, `skill_bonus`, `save_bonus`, `compute_ac`, `clean_speeds` and
    `weapon_profiles` all read it, so base stats are never mutated and equipping,
    unequipping, attuning or restarting can neither double-apply nor go stale.
  - **One prop vocabulary.** `gear.clean_props` is THE validator for DM definitions
    (`inventory.clean_def`) AND the content importer (which projects through it), so
    a prop means the same thing everywhere — no second validator. Typed keys are
    range-clamped and wrongly-typed values are DROPPED (never coerced).
  - **Five bonus scopes, distinguished exactly.** per-weapon (`attack_bonus`,
    `damage_bonus`, `extra_damage_dice`) → the server attack profile only; general
    (`attribute_bonus`/`attribute_set`) → every derived value; while-equipped (all
    gear bonuses live only in a slot; a slotless legacy sheet is byte-identical);
    while-attuned (an `attune` item that is not attuned is INERT, even its weapon
    bonus); on-consume (`heal_dice`, `op_id`-guarded).
  - **Weapon mechanics ride `weapon_profiles`.** versatile `grip` is per-instance
    (`inv_grip`, off-hand cleared atomically for two-handed grip; shield conflict
    resolved) and picks `damage_dice` vs `damage_dice_two_handed`; finesse/ranged
    choose the ability; a weapon attack adds its ability mod to damage by default
    (a legacy DM weapon can opt out with `mod_to_damage=false`); long range is
    server-tiered (≤normal ok, ≤long disadvantage — advantage cancels it, beyond
    invalid).
  - **Identification ≠ inertness.** Unidentified gear still applies its passive
    mechanic while worn+attuned (it gates only the DISPLAY of unknown properties);
    blindly USING an unidentified magic item still needs identification (D98).
  - **Additive only.** `characters` gains no new column; grip is a field on the
    inventory entry, `hands`/`charges`/`recharge` are additive item columns; legacy
    sheets and pre-Phase-A items (no props / no equipment) are unchanged.
- **Honest limits:** long-rest is the only charge recharge (short-rest recharge
  deferred); `duration`/`trigger`/`hit_dice_bonus`/`properties` remain table notes;
  creatures use the SAME overlay only when they carry the compatible item/equipment
  model (no NPC-specific engine).
- **Consequences:** DMs author any item in the browser (item-definition editor with
  kind/grip/dice/range/AC/attribute/grant/magic fields, `✎ Edit` to reload a
  definition), see effective values on the sheet (darkvision, effective walk speed,
  server-derived attack profiles with extra dice + tiers + grip + 🔒 when gated).
  Tests `tests/test_weapons_gear.py` pin grip dice + hand/shield occupancy, ranged
  tiers + finesse, the attunement gate, AC base/bonus/max-dex, attribute set/bonus
  feeding AC + initiative + stats, skill/save grants + expertise (never double
  proficiency), darkvision/speed, heal-once, equip persistence, grip replay +
  main-hand precondition. `tests/test_content_examples.py` gains importable ranged,
  attribute-bonus, attribute-set and multi-effect item examples.

## D99 — Money is one integer of copper; carrying is derived; a companion is just a token with an owner/controller
- **Decision:** Phase E finishes currency, encumbrance and companions WITHOUT a new
  engine. **Currency** is stored on the character as ONE non-negative INTEGER of
  copper pieces (`characters.wallet`) — never a float, never a per-coin dict that
  could go negative per denomination. `gear.CURRENCIES` is the single data table
  (cp/sp/ep/gp/pp, value in copper, coin weight 0.02 lb); the per-coin purse split
  (`cp_breakdown`) is DISPLAY ONLY and greedy richest-first, so electrum change at
  50 cp divides exactly. A client can only ever send `(integer amount, coin id)`
  through `gear.to_cp` — it can never post a copper total, so no request mints
  gold. All purse and container-coin writes live in `app/inventory.py` reusing the
  SAME transaction + `op_id` replay claim as items: atomic across sender/receiver,
  refuse a shortfall before any store (so the whole op rolls back), namespace the
  claim to the character/object acted on. DM grant/deduct; player→member transfer
  (both must be THIS room's characters via `_validate_parties`); a DM fills hoards
  and a character loots them (`coins_take`, one object-namespaced claim so a
  double-click cannot duplicate the scoop).
- **Carrying** is DERIVED, never persisted. `gear.encumbrance(char)` sums `qty ×
  weight` over the character's DISTINCT stacks — equipped items live INSIDE
  `items[]`, so equipping never double-counts weight — plus the coins' weight from
  the same greedy split. Capacity = effective STR (`effective_gear`) ×
  `CARRY_PER_STR` (15) × a SIZE_CARRY modifier (tiny/small ½, medium 1, large 2,
  huge 4, gargantuan 8) + any `carry_bonus` from WORN gear (a new additive item
  prop/column). The result rides `derived.encumbrance`; the sheet renders it and
  the client never recomputes. `overloaded` is a WARN FLAG ONLY — no movement
  penalty is applied until that rule is fully specified and tested.
- **Companions are the existing token model, surfaced not duplicated.** A companion
  is a `tokens` row with `owner_user_id` and/or `character_id` set by the DM
  (`add_token` now binds those, DM-only, validating room membership) — the same
  columns a player token already uses. Control is handed out ONLY through the D82
  `token_controller` (DM-only; the target must be a room member), and riding stays
  the D82 acyclic `token_mount`. A player can therefore never seize a foreign
  companion through a forged message; a player sees companions only among the
  tokens already visible to them (owner/controller = them), so no hidden token or
  other-plane token is ever named.
- **Additive only.** New columns: `characters.wallet`, `characters.size`,
  `containers.coins`; new additive item column/prop `carry_bonus`. `CharIn`, item
  defs and every pre-Phase-E row read defaults; nothing is migrated destructively.
- **Honest limits:** currencies are a documented code table (a content-configurable
  rate table is a later step); coin recharge/interest, minting rules, and the
  overload MOVEMENT penalty are deferred; the DM item-definition editor does not
  yet expose the `carry_bonus` field (author it via CSV or an ad-hoc grant).
- **Consequences:** sheet collapsibles render Wallet (rates + greedy coins + DM
  grant/deduct + owner transfer), Encumbrance (bar + OVERLOADED warn) and
  Companions (list + DM controller/mount/add/remove reusing existing ops); the
  container chest shows and loots coin. `tests/test_money_encumbrance.py` pins the
  integer/range strictness of `to_cp`, the lossless greedy split, grant/deduct +
  persistence, the no-negative rollback, `op_id` replay, DM-only grants, member
  transfers (atomic, insufficient, replay), stranger refusal, container fill→take
  (adjacent, atomic, replay), quantity/equipment non-double-counting, size + carry
  bonuses, the overload warn, companion/controller authorisation, and
  reload-stable derived state. `tests/test_content_examples.py` gains an importable
  `carry_bonus` example.

## D100 — Integration hardening: atomic resource spend, server-authorised progression fields, room-scoped item library, real-JS testing via a pinned node

- **Decision:** Sprint 29 was an audit, not a feature. An adversarial read of the
  D95–D99 subsystems surfaced five real defects and one legitimate design tension;
  each is closed with a REAL regression test (no xfail, no new skips), and the
  remaining non-issues are documented as honest limits.
- **G7 — the ONE ability engine is now atomic about cost.** `_consume_cost` read,
  checked and incremented a slot/resource across SEPARATE autocommit statements, so
  two concurrent casts of the same caster could both pass the "slots left?" check and
  LOSE an increment (probe: 91/120 rounds cast 4 against `max=3`). The legacy `cast`
  path was already single-tx; D97's `ability_cast` path was the outlier. `op_id` claim
  + cost now happen inside ONE `db.tx()` (`_cast_gate`, `app/abilities.py`), and a
  refused cost ROLLS the claim back so a genuine retry is not swallowed. The fix is
  pinned by a synchronous thread-hammer invariant (`tests/test_d100_integration.py`):
  N concurrent `_cast_gate` calls against `max=1` yield EXACTLY 1 success, never more.
- **Autonomy lock (design).** The raw character-editor `PUT /characters/{cid}` no
  longer writes the SERVER-AUTHORISED fields `level` / `spells` / `spell_slots` — a
  sheet owner can neither refill consumed slots, self-grant a spell list, nor set
  their own level by hand. The raw `class_levels` WS transport is DM-only. The
  SELF-SERVICE progression the players keep is the VALIDATED path: `charbuild.apply`
  (`/api/build/{code}/{cid}/apply`, owner- or room-DM-authorised) plus the DM's WS
  advance. Nothing was migrated: existing characters are untouched; only the unauthorised
  write doors closed. Ordinary sheet fields (name, AC, HP, stats, items, skills, …) stay
  editable by the owner, and DM/server-side progression is fully preserved.
- **G8b — a granted NPC ability id survives the real editor path.** `npc.clean_npc`
  dropped bare STRING ability ids (it only kept `{name,desc}` prose), so a familiar
  created through the real `add_token`/`update_npc` path could never be cast by its
  controller — the existing tests masked this by writing the block straight to the DB.
  `_clean_abilities` now preserves a bare string as a canonical id alongside prose
  entries, which is exactly the list `_rollable_by` reads.
- **G9/A13 — the DM item library is room-scoped, and a shared id is refused, never
  clobbered.** Reads/deletes/grants already filtered `WHERE room_id=?`; the two
  `item_defs` UPSERTs (editor create + CSV projection) silently rewrote ANOTHER room's
  row on an id collision. Because `item_defs.id` is a GLOBAL primary key (a per-room
  key needs a destructive table rebuild, which is off-limits), a cross-room collision
  is now REFUSED with a clear message instead of overwriting — the authoritative
  room-scoped `content` row is still stored, so no content is lost. This is the honest
  resolution the schema permits without a migration.
- **G5 — a non-DM rest answers.** A player-initiated `long_rest`/`short_rest` on a
  token they may not rest returned silently; it now sends an explicit error, matching
  every other refusal.
- **Real-JS testing.** The `test` Docker stage copies the pinned `node:22-slim` binary
  (no npm, no node_modules, nothing fetched at run time — `python:3.12-slim` already
  ships its only extra lib, `libstdc++.so.6`) so the ~17 node-gated tests run the
  ACTUAL shipped client JS (and the diorama parity) instead of skipping. The runtime
  image is unchanged and never sees node.
- **Consequences:** the canonical suite is `682 tests, 0 failed, 0 errors` (node-less it
  reports the ~18 node skips; with node in the image those become real runs).
  `tests/test_d100_integration.py` pins all of the above plus a green end-to-end flow
  (import → build → cast → consume → money → companion → reload → consistency);
  `tests/test_progression.py` and `tests/test_sprint23_combat.py` were updated to stage
  the server-authorised fields through the legitimate writers instead of the now-locked
  editor PUT; `test_content.py` reads `item_defs` BY ROOM+id and run-unique ids.
  Remaining honest limits: `POST /characters` stays the trusted authoring/seed surface
  (used to create a blank sheet and by tooling); ability SCORES / saves remain
  owner-editable sheet fields (lower-severity, no confirmed exploit, the build is the
  intended author of a fresh sheet's scores); and the global `item_defs` id means two
  rooms independently choosing the same item id collide by design and are refused.

## D101 — Room preparation screen, guided character build, background starting gear, apply-refresh fix

- **Context:** browser findings (12.10.2026): DnDTable worked but presented like a test
  tool — joining landed directly on the canvas, species/class/background were free-text
  fields, the build demanded raw class ids and hand-written choices JSON, and after a
  SUCCESSFUL build apply the sheet kept showing `unbuilt` + old skills until a full
  browser reload. Goal: the flow Login → room → room preparation → table must read like
  a usable app WITHOUT a second character/content/auth engine, without stockwerk/map
  editor work, and without new mechanics.
- **Decision — one new screen, everything else re-used.** `#view-prep` +
  `app/static/js/80_prep.js` is the landing screen for create/join/room-click;
  "Open the table" IS the existing `openRoom()`, the table's back button is now
  `backToPrep()`, and the legacy lobby "Bring" shortcut still enters the table
  directly. The DM block re-uses `ctPost/ctRender` (D95) for CSV import and the DM-only
  `kinds` counts; the player block re-uses `/rooms/{code}/state`, `POST /assign`,
  `/characters` CRUD and `charbuild.plan/apply` exactly as they are. No room "phase"
  was invented server-side — preparation is a client view over existing truth.
- **Dropdowns are data, never lists.** New `GET /api/content/{code}/options` gives every
  ROOM MEMBER the id+name catalogue of the room's rule pack (species/class/background/
  subclass/feat/spell/item; class level-rows collapse per id). The wizard derives every
  field from `charbuild.plan`'s `needs` (skill options, subclass, per-level feat/ASI,
  spell picks) and never hardcodes classes or skills; decision types the guided form
  cannot show are surfaced explicitly with an expert-mode JSON field — never skipped.
- **Background is a column; starting gear is one authorised route.** Additive
  `characters.background` (D101); `CharIn.background=None` means "keep stored value",
  so legacy lobby PUTs cannot wipe it. `POST /api/rooms/{code}/starting-gear` grants the
  background's `starting_items` through `app/inventory.py` only, resolves each CSV token
  strictly against THIS room's item definitions (grants what is unambiguous, REPORTS the
  rest — nothing is invented), and is idempotent by D94 `inv_ops` (deterministic
  `starting-gear-<bg>` op → a replay answers "already", never doubles). Authz mirrors
  the build API exactly (owner, or DM of an assigned character).
- **The reload bug had TWO causes and got BOTH fixes.** Server: `charbuild.apply` over
  REST broadcast NOTHING, so open sheets on every client aged silently — it now emits
  `snapshot` (the `class_levels` precedent). Client: even the apply caller's own
  `refreshRoom()` never re-rendered an OPEN sheet (only the WS `snapshot` handler did)
  — the handler now re-renders the selected token's sheet itself, mirroring
  `40_ws.js`. Pinned by `tests/test_d101_prep.py` (server broadcast + client source).
- **Found and fixed on the way:** re-seating a user's second character (any assign with
  an existing token) 500'd — `assign_char` passed a raw `sqlite3.Row` into
  `footprint.*`, which read it via `.get()`. Now `dict(tok)`; the exact preparation-
  screen path that exposed it is pinned as a test.
- **Consequences:** the canonical suite is `694 passed, 1 skipped` (Docker, node 22
  included; baseline 682 + `tests/test_d101_prep.py` 13). UI text stays English as
  decided for this sprint (the task's "UI Deutsch" was scoped down by the operator);
  internal ids and CSV fields were always English. No DB migration data — one additive
  column with defaults; every old room/character/URL keeps working.
- **Honest limits:** the lobby editor stays the legacy trusted surface (free-text
  race/class, now background-preserving); species rows are still bookkeeping only
  (ability bonuses from `species.csv` are not mechanically applied — that is an
  existing engine decision D101 did not touch); starting gear covers only what a
  background lists AND this room's import projected (D100's global `item_defs` id can
  refuse a second room's projection, and then those items surface as skipped); a
  background change after a grant only re-grants under a DIFFERENT background id
  (the replay guard is per background, 1-day `inv_ops` TTL otherwise); the guided
  form covers skills/subclass/feat/ASI/known-spells — anything new a future pack
  introduces falls back to the visible expert-mode hint until a form exists.

## D102 — Floors become operable: plane-integrity fixes, DM-only plane changes, the floor manager

- **Context:** browser findings repeated floor after floor — "Stockwerke funktionieren
  nicht / sind nicht bedienbar". The D86/D88 foundation (named planes, per-plane maps,
  validated stair connectors) was sound, but three server defects corrupted data across
  planes (trap/toggle saves wrote the viewed PLANE's map into the PRIMARY blob; WS
  connect and character seats revealed fog on the primary map regardless of the token's
  floor), reveals/fog edits reached every client without naming their plane (the DM's
  browser painted another plane's terrain into the grid it was looking at), and the
  management UI was a chicken-and-egg trap: floors could only be CREATED from a token
  sheet, the "Viewing plane" select appeared only once ≥2 floors existed, rename/delete
  had no UI at all — and renaming was impossible without dangling every stair that
  pointed at the old name.
- **Integrity first — one rule: a save carries the floor of the map it holds.**
  `set_map(room_id, mp)` means the PRIMARY map; the trap branch
  (`room/movement.py`) and the `toggle` op (`room/interact.py`) now pass the token's/
  object's floor. Connect reveal groups tokens by floor and reveals each on ITS map;
  `assign_char` loads and writes the token's plane map (same fit/blank semantics as the
  `net.get_map` seam). No migration — the primary floor stays the legacy blob.
- **Visibility isolation is double-keyed.** Every reveal/fog patch now carries
  `payload.floor` (server `fog_patch` gains the argument) and the client applies it
  only while it equals `state.viewFloor`; delivery itself is plane-scoped
  (`send_to_plane_viewed` for walks/connects — token holders + DM + token-less
  observers on primary). The DM canvas obeys the VIEWED plane (`viewerPlane()` returns
  `viewFloor` for the DM): browsing one floor shows exactly that floor's tokens — no
  more sprites floating over another plane's map.
- **Plane changes are a DM/stairs decision (operator decision).** Players may no
  longer hop planes via `token_floor` ("Only the DM moves tokens between floors") —
  the free self-service hop skipped every destination check. The validated STAIR
  object stays their route (terrain + occupants checked on the target plane, view
  follows the mover via `grid_reveal`). The sheet's floor row became read-only for
  players. D88/Sprint-20 tests that encoded the old policy were updated, not deleted.
- **The missing manager got built.** New DM side panel "Floors" (own panel in the
  DM tab): list with active-plane highlight, add, view (browse without moving
  anyone), rename, delete — delete refuses with the server's reason (primary,
  occupied). New `PATCH /api/rooms/{code}/floors/{name}`: registry, `floor_maps`
  row and `tokens.floor` move atomically in `FLOOR.rename`, then stair
  destinations naming the OLD floor are retargeted across ALL plane maps —
  otherwise renaming silently dangles every stair. The view is re-labelled
  client-side BEFORE the fetch so no in-flight refresh can request a floor that
  stops existing mid-request. `openRoom` now honours the server's `view_floor`
  (a player joining a token on a named floor is delivered ON that plane and the
  plane guards address the right one from the first frame).
- **Consequences:** canonical suite `docker compose run --rm test` →
  **703 passed, 1 skipped, 0 failed** (baseline 694 + `tests/test_d102_floors.py`
  9; two node-harness tests updated because `tokenAt` now filters by `onPlane`).
  Two D101-relevant behaviours stay intact and are pinned: join lands in prep, and
  `map_changed`/`refreshRoom` remain the view SSOT (`state.viewFloor = s.view_floor`).
- **Honest limits:** the ⬜ "floor" brush backlog (it paints cell 0, unrelated to
  plane separation) was NOT touched — it does not block per-floor separation;
  renaming while an editor session holds a stale snapshot can re-introduce the old
  name through that snapshot's objects (editor merge caveat, same class as D88's
  stale-lamp case); floor rows carry no per-plane token counts in the panel; the
  DM browse select and the panel share `state.viewFloor` but the panel intentionally
  carries the management actions   — the canvas stays the single map surface.

## D103 — The map editor paints truth: a real "no floor" state, and PNG artwork that loads in the browser

- **Context:** browser findings named two broken surfaces. (1) Token artwork: uploads,
  auth and serving all worked — yet every portrait stayed a grey disc in a real browser.
  (2) The map editor: "Boden malen/löschen funktioniert nicht" and the missing answer
  to the most basic map question — what does a cell with NO FLOOR even mean here?
- **PNG root cause: the url the browser was told to load was never routed.** The DB
  canon for `tokens.image` is `/assets/<id>` (since D85, stored in rows — immutable
  without touching data) and the canvas loads it verbatim (`img.src = t.image`), but
  FastAPI only ever routed `/api/assets/<id>`; the asset router's prefix hides it. So
  artwork looked perfect in REST tests (they use the /api form) and 404'd in browsers —
  where the onerror handler then BLACKLISTED the url in the session's art cache, making
  even later successes stay grey. Fix is one second router WITHOUT the prefix delegating
  to the same `get_asset` handler: identical auth (`serve_allowed`), identical
  no-oracle 404, identical clean-re-encode + `nosniff` headers. The `/api` form stays
  the documented REST surface. No pipeline rework — the pipeline was sound.
- **"No floor" was a missing STATE, not a broken brush.** The cell mechanics (save,
  per-plane isolation, fog) were intact (D102 pinned them); but the terrain registry
  had no impassable-but-visible cell: the eraser and ⬜ both paint 0 (always walkable),
  and floor 0 rendered at #151823 on a #0a0b10 page — two hex steps from the
  background, so even correct painting LOOKED like nothing happened. Decision (asked,
  approved): extend the D69 registry with **5 = void** — blocks movement, NOT climbable,
  sight passes over it (a pit is not a wall). Because every engine (path, LOS,
  footprint placement, collision, preview) already asks the registry, the refusal
  propagates with zero engine edits. Old maps cannot contain a 5, `terrain(None)`
  stays floor (fog semantics untouched), sanitize clamps 6+ to 5 and still rejects fog
  nulls — byte-compatibility is the invariant, no migration.
- **Editor:** new 🕳️ brush paints 5 (drag included); ⬜ keeps painting 0 and now
  RENDERS as floor (quiet two-tone tiling); 🕳️ renders as a dark hatched hole. 🧹
  keeps its old meaning (0 + clear trap/loot/objects at the cell) — erase must not
  silently create impassable world edges. The diorama file is untouched (D97 rule):
  a void simply extrudes as a flat tile there — cosmetic only.
- **Consequences:** canonical suite `docker compose run --rm test` →
  **711 passed, 1 skipped, 0 failed** (baseline 703 + `tests/test_d103_editor_assets.py`
  8; two D69 vocabulary-clamp tests updated — 5 is now legitimate, 6+ clamps). One
  discovery for the toolbox: FastAPI 0.142 defers `include_router` into opaque
  `_IncludedRouter` wrappers, so route-table scans are version-dependent — the asset
  tests pin BEHAVIOUR (both urls serve, auth-gated) instead.
- **Honest limits:** the diorama shows void as a flat floor tile until D97-territory
  work happens; concurrent editors remain last-writer-wins on save (D88 class);
  served artwork carries `max-age=86400`, so a revoked private asset may survive in a
  warm browser cache for a day; "void kills a standing token" is intentionally NOT
  automated — the server refuses occupancy of void but does not simulate falling.

## D104 — Lights become manageable and the DM can stand in a player's eyes: the `lamp` channel and the read-only `view_as`

- **Context:** browser findings: darkness renders the map black (and cannot be
  diagnosed), light sources "cannot be sensibly placed or managed", and the DM has
  no way to check what a specific player actually sees. Phase 1 found the premises
  half wrong: the light MODEL existed since D87/D89 (`mp["dark"]` room flag, lamp
  world-objects with `bright`/`state.on`, token `light`/`darkvision`, all
  plane-local, all LOS-correct, pinned by `test_lighting2.py`) — what was missing
  was the MANAGEMENT SURFACE (no move, no retune, no list; delete+replace silently
  loses `state.on` because the id merge keys on id), and the PLAYER-VIEW PREVIEW
  did not exist at all. "Darkness = black" is Rule-as-Designed for a dark plane
  without light sources.
- **No new entities, no second light rule.** The lamp IS the light source
  (registry of INTERACT_OPS unchanged). New DM-only WS message `lamp`
  (`room/lights.py`): add/update/remove by id ON A PLANE (`floor` arg, D102
  save rule), same canon as the object sanitizer (bright 0..30, world-window
  clamp, 16-char ids, uuid ids for adds), same state-merge survival, ending in
  the SAME `reevaluate_visibility` the lamp-interact and map-edit already call.
  Panel toggling is silent administration: players experience the WORLD result
  via `map_changed`, never a fake chronicle action (player-driven lamp interact
  keeps its chronicle, untouched). New DM panels "Lights" (per viewed plane:
  label/radius/on-off/move-by-click/delete/add-at-centre) and "Peek".
- **`GET /rooms/{code}/view_as/{character_id}` — the security promise is
  structural.** The /state player branch was EXTRACTED into
  `rooms._viewer_token_view` and `/state` itself now calls it; `view_as` calls
  the SAME function with the character's owner. There is no second visibility
  logic to drift: same LOS, same `_lit_cells` dark/lamp/darkvision decision,
  same hidden-token strips, same fog masking. Pure read (explored bytes and
  ghost memory are only read — pinned). DM-only; members get 404, non-members
  the classic 403 membership gate; a character without a token in the room
  answers 404 like a floor that does not exist.
- **The client preview is a DATA swap, not a state fork.** `viewData` accessors
  (`viewG/viewTokens/viewGhosts`) feed the tactical renderer; the live DM state
  keeps receiving every WS event underneath (map_changed keeps the panels
  honest). While a preview shows: ALL canvas input is dead (select/drag/roll/
  interact/dblclick), diorama switching is blocked (its renderer reads live DM
  data), the plane filter is skipped on preview payloads (server-filtered), and
  the banner names the character ("👁 DM preview: sight of …"). Invisible
  tokens are absent from the payload — they cannot be clicked, hovered or
  listed because they were never sent. Snapshot + Refresh (decision): live
  replay would mean a second render/state path (forbidden).
- **Side bug found by the audit and fixed:** WS connect reveal used the classic
  FOG_R radius REGARDLESS of darkness — a D87 light-budget bypass at reconnect
  (dark rooms revealed 6 cells of memory from nothing). It now defers to
  `viewer_visible_cells` (the one light-aware function) when the plane is dark.
- **Rule-variant documentation (not implemented):** the model knows ONE
  darkness — the ordinary kind that light defeats (D89's standing decision).
  "Magical darkness that ignores light" does not exist as a state and was NOT
  silently invented; darkvision remains a private sense that only matters
  where light fails (D89), and gear-granted `darkvision_ft` stays sheet-level.
- **Consequences:** canonical suite `docker compose run --rm test` →
  **725 passed, 1 skipped, 0 failed** (baseline 711 + `tests/test_d104_lights_preview.py`
  14; two source pins updated to the preview accessor loop head — D102
  precedent; layout-z pin satisfied by reusing `--z-movehud`).
- **Honest limits:** the preview is a moment-image (Refresh re-fetches; a
  vanished character exits the preview honestly); managing lights while a
  preview is open only affects the preview after Refresh; the panel cannot
  express dm_only-lamps per plane yet (checkbox exists in the editor tool, not
  in the panel); no falling/feeling mechanics for darkness; connect reveal in
  dark rooms now reveals exactly the light's reach — a player whose lantern sat
  lit before disconnecting may legitimately re-learn that map area.


## D105 — Class kits, NPC gear and looting: all-or-nothing grants, `tok:<id>` containers, and the corpse as a loot source

- **Context:** D101 granted background gear only; `classes.csv` had no kit
  columns; NPC tokens carried no inventory; a downed monster could not be
  looted — although the container (D92), currency (D99) and op-id replay
  (D94) engines had long existed. D105 adds the missing *rules*, not a
  second engine.
- **Pack schema (additive):** level-1 class rows gain `starting_items`
  (fixed tokens `id` or `id xN`, comma-separated) and `starting_choices`
  (pick-one groups `Label=alt|alt xN;Label2=…`). Unknown-column tolerance
  made the extension safe, but the exporter's byte-stability required the
  pack rows themselves to carry the new columns — `DictReader` turns a
  missing trailing column into `None`, and `None` silently stringifies.
  Demo kits live in `scout` and `warden`.
- **One grant path:** the D101 route is the only grant path. POST gains an
  optional `class_choices`; a new GET `starting-gear/{cid}` resolves the
  pack server-side (names + every error the grant would refuse on) so the
  prep screen shows problems BEFORE anything is granted. The background
  part keeps D101 semantics verbatim (skipped-but-reported, replay→already).
- **Class part is ALL-OR-NOTHING (D105 addendum):** one malformed token,
  one missing item definition or one unanswered group refuses the entire
  class grant and writes NO idempotency claim — fixing the CSV stays
  possible and a half-grant can never freeze behind a claim. Choices are
  re-checked against the CSV's offered alternatives only; a client can
  never name an arbitrary item id.
- **Exactly-once (D105 addendum):** the claim key `class-gear-<class>` is
  probed BEFORE the choices are even parsed — a later request answers
  `already` whatever it carries, adds nothing and overwrites nothing.
- **NPC inventory = the containers table, keyed `tok:<token_id>`:** no new
  table, no migration. A DM-only `npc_inv` channel manages it (inspect /
  fill / remove / coins_fill / coins_remove). Contents travel exclusively
  through the requester's own inspect — never in a snapshot, token payload
  or broadcast — so a living NPC's gear is structurally invisible to
  players.
- **Loot gate = server-side NPC hp == 0:** death saves remain PC-only (the
  model "sits NPCs at 0 HP", D56); no new death state was invented. The
  gate reads the live token row on every action, so healing above 0
  re-locks the corpse instantly. PCs (death saves or not) are never loot
  sources.
- **Loot authorisation mirrors D82/D92 exactly:** same room, same plane,
  controlled token adjacent to the body, receiving character is yours —
  the DM may act for any seated character. `inspect` reveals, `take` and
  `coins_take` move — each through ONE transaction with ONE op_id claim,
  so a replay after a reconnect can never duplicate, and two players
  racing for the last dagger serialise on BEGIN IMMEDIATE with the loser
  re-checking (and failing) inside the transaction.
- **New SSOT primitives (`app/inventory.py`):** `container_give` forces
  container→character — `container_move` decides direction by WHERE THE
  ITEM IS, so a looter already carrying the same stack would have silently
  PUT INTO the corpse. `container_remove_coins` lets the DM take coin out
  of a container without minting a purse.
- **Token deletion cleans exactly its own container** (`tok:<id>` of that
  room): no orphan hoard outlives the carcass, world containers in the
  same table are untouched (D105 addendum).
- **Side bug found by the tests:** token `x/y` are PIXELS while map-object
  coordinates are CELLS — the first reach check compared pixels against
  cells and every looting attempt died at "Walk up to it first". Reach now
  converts via `map.cell`.
- **Consequences:** canonical suite `docker compose run --rm test` →
  **749 passed, 1 skipped, 0 failed** (baseline 725 +
  `tests/test_d105_gear_loot.py` 24, of which 2 are UI source pins).
  classes.csv exports gain the two columns everywhere (byte-stable).
- **Honest limits:** NPC death is HP==0 — there is no dying/revive
  distinction for monsters and no corpse state; looting is standing
  adjacency, no search time; a class kit is one row (level 1) — multi-
  class kits were not invented; the prep screen's gear step grants what the
  pack lists and never lets a player choose outside it; NPC inventories are
  DM knowledge only — a DM who wants to reveal a corpse's exact gear to the
  table uses the same loot panel.

## D106 — Secret per-instance curses: metadata inside the item entry, per-viewer disclosure, DM-gated whispers (+ atomic token delete)

- **Why the entry, not a table:** there is no stable GLOBAL item-instance id —
  `inventory.stack_add` re-issues entry ids on every transfer/chest/loot move
  (ids are only unique inside one inventory). A side table keyed by instance id
  would lose the instance at the first transfer. The entry dict inside
  `characters.items` / `containers.items` IS the instance and rides every
  existing atomic move (`dict(it)` copy) for free — so `curse`
  (`{name, desc, whisper, revealed}`) lives there. **No schema change, no
  migration**: old items simply have no field; the JSON columns are the
  existing storage of instance truth.
- **Fail-closed by default:** `gear.clean_items` STRIPS the field unless the
  caller explicitly passes `keep_curse=True`. Every pre-D106 read path
  (client PUT sanitising, /state renders, container peeks, legacy tests) is
  byte-identical and structurally incapable of leaking; the engine's mutation
  round-trips (`_load`, `container_load`, `room/items.py`, long rest) read
  trusted so a plain mutation can never wipe the secret. `PUT /characters` is
  covered both ways: client-authored curses are stripped (cannot forge,
  cannot flip `revealed`), stored curses are re-attached by entry id (a sheet
  round-trip cannot wipe them) — `_preserve_curses`.
- **Instance identity = the curse itself:** a cursed entry never stacks
  (`_stack_key` → None) and can never be split (refused) — marking a qty>1
  stack ATOMICALLY carves one qty=1 piece (DM decision confirmed: carve, not
  reject). Minting a second cursed instance via merge/split/replay is
  structurally impossible; op_id claims guard the metadata writes like every
  other mutation.
- **One disclosure gate:** `gear.curse_view(items, mode)` — `dm` sees
  everything, `owner` sees ONLY a revealed curse's `name` + `desc` (the
  whisper text never rides any sheet payload — DM decision confirmed), every
  other mode strips. Applied at the sheet serializer (`_char_row`), the
  container replies (`container_peek(curse=is_dm)`), and nothing else; WS
  broadcasts carry no inventory payload at all (the client refetches its own
  entitled `/state`). No HTML-hiding anywhere in the path.
- **Owner change resets knowledge, never touches the curse:** transfer,
  container put/take and loot clear `revealed` on the MOVING copy (the curse
  itself survives every move and every reload — it is stored data). A new
  holder learns nothing from the previous holder's revelation; the DM must
  reveal again. Internal operations (equip, use, rest, recharge, identify,
  attune, sheet PUT) do NOT clear it.
- **Whisper authority is the item, never the client:** `curse{action:whisper}`
  resolves the recipient from the instance's current holder
  (`characters.user_id`, room-membership enforced) — recipient fields in the
  message are ignored by construction; container/NPC-carried items have no
  player owner and are refused with a clear reason. Delivery is the existing
  private `chat.post_chat` whisper model (per-socket delivery, recipient-
  filtered history) — no second chat infrastructure, no broadcast, no
  automatic whisper on loot/equip/rest (all triggers remain DM decisions).
  Revealing sends exactly the released name+desc through the same channel.
- **No curse engine (deliberate):** no random tables, no saves, no damage, no
  tick timers — D106 stores what the DM authors and delivers it when the DM
  asks. Mechanics stay in the DM's hands (backlog: pickpocketing, automatic
  curse triggers, secret saves, curse consequences).
- **D105 follow-up fixed:** `handle_del_token` now deletes token + `tok:<id>`
  container + seat-unassign + chronicle line inside ONE `db.tx()`; a failing
  DELETE (e.g. FOREIGN KEY from a mounted rider) rolls BOTH back — verified
  with the real FK failure, no monkeypatching.
- **Consequences:** canonical suite `docker compose run --rm test` →
  **775 passed, 1 skipped, 0 failed** (baseline 749 +
  `tests/test_d106_curses.py` 26 behaviour tests, 0 source-only pins).
- **Honest limits:** instance identity is per-inventory — after a transfer the
  DM panel must re-read ids (the UI does, via `inv_changed`/`curse_updated`);
  a curse travels to a NEW holder revealed=False but the DM panel still shows
  the truth (that is the point); whisper text length is capped (1000 chars,
  chat-clean); curses on equipment are still passive story facts — nothing
  fires mechanically.

## D107 — 2024 is THE primary rules baseline; compatibility becomes documentation, prioritised — never silent drift

- **Baseline decision:** DnDTable's binding primary rules foundation is
  **D&D 5e (2024)**. Everything the engine implements in 2014 semantics is now
  a DOCUMENTED distance with a backlog id (R-P0.x … R-P2), not an accident —
  the audit lives at `docs/RULES_AUDIT_2024.md` (matrix with `file:line`
  evidence, CSV-schema suitability per file, house-rule register H1–H9,
  prioritised R-list).
- **D107 stays an audit:** no rule implementations, no schema changes, no new
  content packs — only the audit document, a §11 in the CSV guide, this
  decision, the TODO sprint block/backlog and one README sentence. The suite
  is re-run canonically to prove nothing else moved.
- **Already-2024 findings are recorded too:** cantrip scaling already runs on
  TOTAL CHARACTER LEVEL (`abilities.py`, spells.csv `scale_tiers 5/11/17`) and
  the class-CSV ASI cadence is data-driven (Fighter 1/2/6 would be pure data)
  — both are kept as-is and pinned by the audit, not "fixed".
- **Copyright wall stands:** quotable rule text stays SRD 5.1 (CC BY 4.0,
  ATTRIBUTION.md); 2024 differences are phrased functionally in our own
  words; adopting ANY 2024 official text requires the human-verified SRD 5.2
  status step (R-L0) first.
- **Existing house rules get explicit labels instead of quiet divergence:**
  the death-save pipeline (D34), NPC-at-0-HP (D56/D105), attunement gate
  (D105), display-only exhaustion/inspiration/skill-ranks are now the
  register H1–H9 in the audit; changing any of them is a conscious,
  R-numbered decision, never a side effect.
- **Consequences:** canonical suite stays **775 passed, 1 skipped, 0 failed**
  (docs-only sprint); the R-list is the ordered starting point for whichever
  rules sprint comes next.

## D108 — The D107 audit is corrected against SRD 5.2.1; the 2024 character origin becomes a real, ledgered operation

- **D107 was wrong where it guessed.** Re-verified against the official SRD
  5.2.1 PDF (CC BY 4.0, 2025-05-01) and the 2024 rules glossary: there is NO
  Proficiency-Dice change (the fixed bonus stays — D107's R-P0.1 deleted),
  the Concentration DC is max(10, half the damage) not "11 + half", Origin
  feats come from the BACKGROUND (species extras like Human's Versatile are
  separate traits), 2024 feat categories are Origin/General/Fighting
  Style/Epic Boon and GENERAL feats MAY raise scores (to 20), death saves
  remain 3✓/3✗ exactly as `room/death.py` already implements (no Dying
  condition), short-rest Hit Dice stay player-spent, Weapon Masteries are the
  SRD list Cleave/Graze/Nick/Push/Sap/Slow/Topple/Vex SEPARATE from the
  weapon properties, 2024's condition list gained the standalone
  Incapacitated and never had Dying/Encumbered, Exhaustion caps at level 6
  with flat penalties, and Passive Perception simply no longer exists — its
  absence is conformance, not a gap. Every correction is row-marked (K1–K9)
  in `docs/RULES_AUDIT_2024.md` §1.
- **R-L0 is closed:** SRD 5.2.1 is officially CC BY 4.0 (source URLs + the
  verbatim attribution statement are in `ATTRIBUTION.md`). The shipped packs
  stay project-original with house-rule notes — following 2024 MECHANICS
  needs no SRD names.
- **The origin operation lives in the build engine, not beside it.**
  `charbuild.apply_origin` validates the background against THIS room's
  content (three ASI abilities + a feat whose category is exactly `origin`),
  accepts from the client ONLY the distribution (`plus2_plus1` on DIFFERENT
  allowed abilities, or `three` × +1), REFUSES any score that would rise
  above 20 (no clamping), and reuses `_apply_feat` (now category-aware).
  The feat id and the amounts come from the background row — never from the
  request.
- **The ledger is the proof; the recompute is the guard.** The grant is
  recorded as `characters.build.origin` (no heuristic "which score did this
  come from?" reverse math) and replayed at the FRONT of the existing
  D96 full recompute — so origin-before-build and build-before-origin both
  produce one application, double posts/replays/reloads answer `already`,
  and later level-ups replay it instead of wiping it. hp/max_hp/slots/
  resources are untouched; starting gear keeps its separate D94/D101 claim
  path. A sheet PUT cannot forge or erase the ledger (`build` is not a
  writable sheet column).
- **Old data never becomes 2024 silently:** `asi_abilities`/`origin_feat`/
  `feats.category` are additive optional columns; a background row without
  them reports "not a 2024 background" and refuses. Existing characters are
  never auto-migrated — the origin is applied only by an explicit, authorised
  operation. Species `ability_bonuses` stay data-only.
- **UI stays a client-side convenience:** the "🧬 2024 Origin" prep card
  shows the server's report (allowed abilities + current values + feat +
  every refusal), a live preview, and one apply button; every real check is
  server-side (`GET/POST /api/build/{code}/{cid}/origin`, same
  owner-or-assigned-DM authorisation as the build API).
- **Consequences:** `tests/test_d108_origin.py` (22 behaviour tests, no new
  skips) + the untouched canonical suite; the corrected audit's remaining
  work is Weapon Mastery (R-P0), Concentration saves / Light bonus attack /
  origin-feat-choice flows (R-P1) and the display tier (R-P2).

## D109 — The 2024 weapon masteries become a server-authoritative layer: property, entitlement and intent are three separate gates

- **Context:** the D108 audit left R-P0 (weapon masteries) open. The eight
  SRD 5.2.1 masteries (Cleave, Graze, Nick, Push, Sap, Slow, Topple, Vex) are
  NOT weapon properties — a property says what a weapon can do, a character
  feature says what they may do, and combat says whether THIS attack
  qualifies. Merging those axes would let a magic sword silently hand out
  class features or let a client opt a plain swing into extra effects.
- **Three-gate model, validated before any die is touched:** (1) the item's
  `mastery` prop (new additive `items.mastery` column, whitelist-registered
  in content.SCHEMAS), (2) the build ledger `characters.build.masteries`
  (`grants` + `pending` — granted only by applying a level with
  `mastery_gain`, chosen from the class row's `mastery_options` pool, or by
  an explicit DM-grant route; NEVER retroactively, same principle as D108's
  origin), (3) the request's explicit `mastery` intent plus per-mastery
  legality (mode, hands, initiative anchor, reach, once-per-turn markers
  `m_cleave`/`m_nick` on the turn object). An invalid intent is refused
  pre-roll — it never rolls a "free" attack.
- **No second engine.** Push calls `apply_forced_move` (kind `push`, fixed
  2 cells = up to 10 ft, obstacles truncate like every forced move); Topple
  reuses the save/prone path; Sap/Slow/Vex write existing condition markers
  (`sapped`/`slowed`/`vexed`) carrying a `src` token anchor whose expiry
  lives ONLY in the existing D80 turn-lifecycle hook (`step_src`);
  adv+dis stays the engine's confusion rule; `slowed` is a −10 ft hook in
  the one `_speeds` function (flat, never stacks); a Light weapon may now
  occupy the off hand (2024 two-weapon precondition for Nick).
- **Documented deviations:** "when you deal damage" (Slow/Vex) = server-
  rolled damage > 0 (HP stays manual); marker masteries need active
  initiative and a listed token (src expiry is turn-hook-anchored); spell
  attacks consume markers only with a token reference; Cleave's second hit
  drops the ability modifier (unless negative) but keeps magic flat
  bonuses and extra dice.
- **Audit fixes folded in:** `apply_origin` and the persistent block of
  `apply()` each run inside ONE `db.tx()` (BEGIN IMMEDIATE) — check-then-
  write windows closed; the reach/range maths now measures authoritative
  footprint CELLS ×5 ft instead of raw pixel deltas (latent D93 bug that
  made any spaced target "out of reach").
- **Consequences:** `tests/test_d109_mastery.py` (29 behaviour tests, no new
  skips; a deterministic chat-sentinel drain helper replaces flaky event
  loops), `Dockerfile` test stage now copies `scripts/` so the generator's
  byte-idempotency test guards the shipped pack in the canonical image too.
  Canonical: 826 passed, 1 skipped, 0 failed.

## D110 — The "back-backlog" rule is retired for DnDTable; the engine's remaining wish-list becomes planned residual work, and one continuous integration chain guards the shipped paths

- **Context:** Sprints 34–38 closed the rules gaps (D106–D109), but the
  question "what is actually still missing to call this feature-complete?"
  was only answerable from TODO prose — not from code evidence. The TODO
  section "bewusst nicht gebaut" (deliberately-unbuilt timebox artefacts)
  carried a "back-log it" framing imported from a different project.
- **Decision:** (1) The framing is retired: everything still desired for
  DnDTable is planned residual work, classified and sequenced in
  `docs/FEATURE_COMPLETE_GAPS.md` (S40 genericity → S41 opposed/sleight →
  S42 automatic magic → S43 combat R-P1 → S44 data projection → S45+
  CSV content + operations). (2) The real state is now documented from
  file:line evidence in `docs/FEATURE_MATRIX.md` and
  `docs/CSV_ONLY_READINESS.md` — column ≠ mechanic is a named, measured
  property (species/creatures are data-only; the executor cannot express
  movement/check/duration-with-save effects; the condition catalogue is
  hardcoded). (3) D110 itself ships no new mechanic: it integrates.
- **The chain:** `tests/test_d110_e2e.py` drives one continuous A→F run
  over the REAL REST/WS handlers — pack import → 2024 characters (origin,
  class apply, mastery pick, kit-choice starting gear) → move/wall/door/
  fog/view-as/floors → initiative with Cleave/Topple/Graze/Vex and real
  condition clocks → down → adjacency-gated atomic loot → DM curse set/
  reveal/whisper with owner-only delivery → reconnect snapshot equality +
  replay idempotency. It is the machine-checkable twin of
  `docs/SATURDAY_ACCEPTANCE.md`.
- **Two P1 integration bugs found and fixed by the chain:**
  (a) `room/dice.py` spent the turn's action (and the Nick marker) BEFORE
  validating target visibility/reach/push-size/cleave-pair — every refused
  attack burned a slot; slot accounting now runs after all pre-roll
  validation. (b) `room/inv.py` let the curse action `whisper` fall into
  the reveal/conceal branch, executing `curse_reveal(False)` — a whisper
  silently UN-revealed a disclosed curse (latent since D106; the suite
  never combined reveal→whisper). `whisper` now performs no mutation.
- **Consequences:** the canonical suite grows the e2e file (5 tests, no
  skips); D106/d109/combat/inventory neighbours re-verified green after
  both fixes; the browser acceptance (Sat 2026-10-17) has a written script.

## D111 — Effects become a validated, versioned data grammar executed by the existing engines, and the condition catalogue becomes CSV data with behaviour hooks

- **Context:** D110 measured the gap (`docs/CSV_ONLY_READINESS.md`):
  columns existed without mechanics — items could only `heal`, spells had no
  movement/check/resource effects, the condition catalogue was 18 hardcoded
  keys, and S40 of `docs/FEATURE_COMPLETE_GAPS.md` defined the generic base
  every later sprint (S41–S44) builds on.
- **Decision:** (1) One versioned cell grammar (`app/effectops.py`, `v:1`):
  ops `damage/heal/temp_hp/condition/condition_remove/break_concentration/
  save/check/forced_move/resource`, canonical JSON (byte-stable canon, strict
  parse, hard node/op/cell/depth/dc/cell-count/cost limits), unknown op or
  field REFUSES the row at import. (2) Cells run through the EXISTING
  engines only — health/damage, movement's `apply_forced_move`, saves/checks
  over the normal dice channel, conditions through the D80 clocks, resources
  through `gear`/`inventory`; `abilities.execute()` runs the cell in its own
  shell. No second engine. (3) Conditions gained a DEFINITION layer:
  `conditions.csv` (hook flags `blocks_movement/speed_delta/my_*_dis/
  attacks_against_me_*/auto_fail_saves` read by the existing movement/dice/
  ability paths + `on_start/on_round/on_expire` effect hooks fired by the
  turn lifecycle); the SRD keys became `BUILTIN_HOOKS` data a CSV row can
  override. (4) Triggers `use/equip/unequip/on_hit/on_damaged` fire inline at
  the authoritative handlers, claim-guarded (one firing per token+trigger+
  carrier+round/op, no trigger chains, ≤8 carriers), with all-or-nothing
  resource preflight inside the claim transaction — a refused action never
  pays, a replayed one never re-fires. (5) Feats with a cell surface as
  castable `feat_<id>` abilities (charbuild entitlement). Documented v1
  non-goals (source-keyed hooks, reactions, auras, summons, components, the
  concentration SAVE — S42) live in `docs/EFFECT_GRAMMAR.md`; 2024
  simplifications (blanket disadvantage for frightened, blinded checks-dis,
  DM-prone, grappled/restrained now blocking movement outright) are named
  there too.
- **One latent P1 infrastructure bug found by the new tests:**
  `room/net.py` keyed cross-loop socket delivery by `id(ws)` — CPython reuses
  ids, so a fresh socket could inherit a STOPPED owner loop and every send to
  it awaited a future that could never resolve (hang). The owning loop now
  lives on the socket (`ws._iio_loop`), stopped loops are refused, and
  cross-loop sends carry a timeout. (D111's third ws session in one test
  exposed it; production uvicorn had only ever had one loop.)
- **Consequences:** S40 closed (`docs/FEATURE_COMPLETE_GAPS.md`);
  `docs/EFFECT_GRAMMAR.md` is the author-facing reference and
  `docs/CSV_ONLY_READINESS.md` re-scored per surface; the demo pack gained
   `conditions.csv` + trigger/effect demo rows (generator byte-idempotent);
   `tests/test_d111_effects.py` (21 tests, real WS paths, no source pins)
   green; canonical suite grows accordingly.

## D112 — Contested actions become ONE reusable primitive the 2024 special-melee and pickpocket rules run on; no second rules engine

- **Context:** D111 gave effects a data grammar but left every *contested*
  action (grapple, shove, escape, a secret steal) without a shared way to ask
  "check vs check", "check → DC → save" or "check vs a fixed DC". S41 of
  `docs/FEATURE_COMPLETE_GAPS.md` named exactly this: a generic opposed/DC
  primitive plus the 2024 special-melee family and pickpocket, built on the
  existing dice/conditions/inventory engines — explicitly NOT a parallel rules
  engine, and 2024 (D107/D108) is the baseline, not 2014.
- **Decision:** (1) `app/room/opposed.py` is a thin, reusable helper over the
  EXISTING dice channel (`do_roll`/`_combine_adv`) and `gear` bonus sources —
  `participant`, `check_roll`, `save_roll`, `bonus_roll`, `melee_attack_number`,
  `better_save`, `opposed_wins(att, def, tie=)`, `beats_dc(total, dc)`, and a
  `Tie` exception for a caller-deferred tie. It ships NO rules of its own; the
  three shapes are just composition. The default tie rule is
  `tie="defender"` (a d20 tie goes to the defender/roller-must-meet-DC);
  `tie="attacker"` flips it; `tie="dm"` raises `Tie` so the caller defers to a
  DM — never a silent coin flip. A closed-world *effect-grammar* op that would
  let CSV data express an opposed check is deferred to S42; the interface is
  documented in `docs/EFFECT_GRAMMAR.md` so S42 can wrap this helper without a
  second implementation. (2) `app/room/grapple.py`: the **2024** special-melee
  family, not the 2014 Athletics-vs-Athletics contest. Grapple = the attacker's
  special-melee number — `melee_attack_number` = max(unarmed attack bonus, an
  Athletics check) — becomes a DC the target answers with a **save** (`save_roll`),
  by default the target's HIGHER of Str/Dex (`better_save`), DM-overridable
  (`save` field); Shove (prone / 5-ft push) resolves the same check, push via
  the existing `moveforced.apply_forced_move`. State is additive only: the
  grappled `conds` entry carries the grappler `src` and a new optional `dc`
  (int 1–30, `_clean_dc`) so escape is "Athletics or Acrobatics vs the stored
  DC". The grapple ends when the target leaves the grappler's reach —
  `end_grapples_out_of_reach` is wired into the three authoritative movement
  ends (forced move incl. a shove, a normal walk, a DM teleport) — or when the
  grappler is gone/incapacitated (escape then auto-succeeds). Reach and
  adjacency use the SAME closest-footprint-corner geometry (Chebyshev ≤ 1) the
  dice module already uses for reach; the size gate is "no more than one size
  larger" via `npc.SIZES` index. (3) `app/room/pickpocket.py`: BOTH 2024
  adjudication models ship. Model A `pickpocket` is the DM-mediated attempt — a
  hidden Sleight-of-Hand check reported ONLY to the DM; Model B
  `pickpocket_take` lets a thief choose one concrete DM-authorised item and
  auto-transfer it on success. Because 2024 has NO passive perception
  (`RULES_AUDIT_2024` A7), "noticed" is EITHER a DM-set fixed `notice_dc`
  (`beats_dc`) OR a real Perception check the engine rolls and resolves with
  `opposed_wins(tie="defender")` — the engine never forces a mode. Discovery is
  reported to the DM *separately* from theft success. Success is one atomic
  `inventory.transfer` (PC victim) or `inventory.container_give` (NPC
  `tok:<id>`), with `_ownership_moves` preserving curse metadata and resetting
  `revealed`. `handle_pickable` (DM only) toggles the new `pick` flag on a
  character item (`set_pick_char`) or an NPC container (`container_set_pick`).
  (4) Leak- and replay-guards are load-bearing: ONLY DM-flagged `pick` items are
  stealable, and an unflagged/unknown item answers exactly like a failed check
  (`_pick_entry` returns None) so the endpoint is never an inventory oracle;
  the op-id guard (`inventory._claim`) is taken BEFORE the action slot is spent
  and before any roll, so a replay spends and rolls nothing; every precondition
  (room, floor, reach, visibility, authz, size, target-alive) is validated
  before anything is spent. `pick` never stacks (`_stack_key` returns None) and
  rides the `clean_items` whitelist; a fresh `VTT_DATA_DIR` and a replayed op
  both stay idempotent. (5) UI (Phase 5) is actor+target only — the sheet names
  who acts on whom and a fresh `op_id`; the whole resolution is server-side.
  The DM authorises `pick` items from the NPC chest and the character sheet
  (`🤝 steal`). No new reply kinds were needed: grapple/shove/escape reuse the
  `dice`+`cond`+`initiative` kinds, pickpocket reuses `whisper`+`dice`+
  `inv_changed`, `pickable` reuses `inv_contents`/`inv_changed` — `40_ws.js`
  was untouched. `55_diorama.js` was not touched.
- **Consequences:** S41 closed (`docs/FEATURE_COMPLETE_GAPS.md`);
  `docs/FEATURE_MATRIX.md`, `docs/RULES_AUDIT_2024.md` (grapple/shove/escape +
  pickpocket now implemented, 2024-correct) and `docs/CSV_ONLY_READINESS.md`
  re-scored per surface; the opposed interface is documented as the S42
  wrapping point in `docs/EFFECT_GRAMMAR.md`; `AGENT_GUIDE.md` gained the three
  modules + six WS message types + test map; `MANUAL_BROWSER_CHECKLIST.md`
  gained the D112 walkthrough; `tests/test_d112_contested.py` (31 tests, real
  WS paths — save/tie unit, full grapple/shove/escape, both pickpocket models,
  leak, replay, concurrency, cursed transfer, cross-room, cross-plane, action
  economy) green; canonical suite: 883 passed, 1 skipped, 0 failed.

## D113 — Konzentration, automatische Flüche und die Opposed-Wirkgrammatik werden 2024-konform datengetrieben (Sprint 42)

- **Kontext:** Sprint 42 setzt die in D111 (Wirkgrammatik) und D112
  (Opposed-Primitive) gelegten Grundlagen in drei echte 2024-Regeloberflächen um,
  ohne irgendwo eine zweite Engine zu bauen: die 2024-Konzentration (Phase 2),
  automatische, DM-autorierte Flüche (Phase 3) und ein `opposed`-Op der
  Wirkgrammatik (Phase 4). Alle drei laufen ausschließlich über die vorhandenen
  authoritativen Operationen (`room.health`, `app.conditions`, `room.opposed`,
  `room.moveforced`, das Ressourcen-Ledger) und die D111-Triggerseams.
  UI-Texte bleiben Englisch, diese Dokumentation ist Deutsch. `55_diorama.js`
  wurde nicht angefasst; keine Git-/`.git`-Zugriffe.

- **Entscheidung Phase 2 (Konzentration):** Konzentration behält ihre einzige
  Darstellung — das `concentrating`-Flag in `conds` (D59). Neu ist ein
  additives Link-Feld `conc` = Token-ID des Konzentrierenden an einer
  Condition-Instanz: eine Condition „gehört" zu einer Konzentration und endet
  raumweit mit ihr. Der Lebenszyklus liegt in `app/room/concentration.py`
  (`end_previous`, `break_link`, `on_damage`, `enforce_after_condition`). Der
  Wurf läuft über `room.opposed.save_roll` (derselbe d20-Kanal inkl.
  `auto_fail_saves`/`my_saves_dis`), kein zweiter Würfelweg. Der Schadens-DC ist
  `max(10, floor(HP_verlust / 2))` OHNE Cap, wobei HP_verlust die TATSÄCHLICH
  verlorenen HP nach Resistenz UND Temp-HP-Absorption sind — `change_hp` übergibt
  genau diesen Wert. Runtergehen auf 0 HP oder ein
  Dekondensierungs-/Inkapazitätszustand bricht SOFORT ohne Wurf. Beim Zaubern
  einer neuen Konzentration wird die alte BEVOR die neuen Effekte landen beendet
  (`end_previous`), damit die alten Link-Effekte weg sind und die neuen bestehen
  bleiben. Ein `break_concentration`-Op und ein inkapazitätsauslösende Condition
  löschen zusätzlich alle `conc`-verlinkten Conditions des Wirkenden.

- **Entscheidung Phase 3 (automatische Flüche):** `active` und `revealed` sind
  vollständig unabhängige Zustände. Der DM kann mit `activate`/`deactivate`
  schalten; Enthüllen/Verbergen/Whisper ändern die Aktivierung niemals. Die
  Schemaerweiterung ist strikt rückwärtskompatibel: `clean_curse` speichert
  `trigger`/`effects`/`active` NUR wenn gesetzt — ein alter Fluch round-trippt
  byte-identisch und ist per Default inaktiv; keine Schemaänderung kann einen
  alten Fluch versehentlich einschalten. Bewaffnet wird über `arm`
  (`trigger` + Wirk-Cell), der Cell wird mit derselben `effectops`-Grammatik
  validiert (keine zweite Fluch-/Effektengine). Ausgelöst wird nur an echten
  Mutationen (`equip`/`unequip`/`use`/`on_hit`/`on_damaged`/`on_transfer`) und
  nur wenn `active` UND `trigger` passen — ein bloßes Lesen/Anzeigen/Synchronisieren
  von Inventar feuert nichts. Besitzerwechsel feuern `on_transfer` über
  `_item_transfer_effects`, geclaimed an der Transfer-`op_id` (Replay/Race feuert
  nicht doppelt), atomar über das bestehende `inventory`-Kommando.
  Fluch-Herkunft wird nie an Spieler verraten: curse-origin-Fragmente gehen über
  `net.dm_whisper` nur an den DM; die Owner-Ansicht bleibt `curse_view`-streng
  (Name/Beschreibung nur wenn enthüllt; `active`/`trigger`/`effects` nie).
  D111-Budget und Tiefen-Rekursionsschutz werden wiederverwendet. 2024-getreu
  endet ein Fluch NICHT automatisch durch Unequip/Besitzerwechsel — Dauer,
  Bindung und Entfernung sind ausdrücklich zu definieren; nichts entfernt einen
  Fluch implizit.

- **Entscheidung Phase 4 (Opposed-Op, Grammatik v2):** Die Grammatik akzeptiert
  `v1` UND `v2` (`V=2`, `V_MIN..V_MAX=1..2`); alles andere (v0/v3) wird
  weiterhin abgelehnt, unbekannte Ops/Felder bleiben closed-world. v2 fügt nur
  den `opposed`-Op hinzu (unter v1 ausdrücklich verboten): ein Attributswurf des
  Subjekts gegen denselben Wurf des Ziels, entschieden von `room.opposed`
  (`check_roll` + `opposed_wins`, `tie` = defender/attacker/dm) — keine zweite
  Opposed-Engine. `canon()` erhält die Version des Cells, sodass ein v1-Cell
  byte-identisch bleibt und v2-Nahme keine gespeicherten Inhalte umschreibt.

- **Konsequenzen:** Neue additive, rückwärtskompatible Felder ohne Migration
  (`conc` an Conditions, `trigger`/`effects`/`active` an Curses, `on_transfer`
  als Trigger). `tests/test_d113_concentration.py` (9),
  `tests/test_d113_curses.py` (9) und `tests/test_d113_opposed.py` (6) decken
  die Flächen über echte WS-Pfade ab; eine D111-Assertion (v2 war „falsche
  Version") wurde auf v3 umgestellt, weil v2 jetzt gültig ist. Kanonische
  Suite (Python 3.12): 917 passed, 1 skipped, 0 failed (inkl. 10 Fallen-Tests,
  Phase 5). Erledigt in Sprint 42: datengetriebene Fallen (Phase 5) und die
  Curse-/Fallen-Autoren-UI + diese Doku (Phase 6; Browser-Durchlauf bleibt
  menschliche Abnahme). Offen bleibt nur vertikale 10-ft-Geometrie (Phase 7).

- **Entscheidung Phase 5 (datengetriebene Fallen):** Eine Falle bleibt eine
  MAP-ENTITÄT (kein `traps.csv`), nur ihre Felder werden erweiterbar. Neu und
  optional (Omit-when-Default → alte Fallen round-trippen byte-identisch):
  `effects` (Wirk-Cell derselben Grammatik), `trigger` (heute nur `step`
  verdrahtet), `search_dc`, `disarm_dc`, `repeat`. Eine alte Falle (nur
  `dc`+`dmg`) behält den unveränderten Einweg-Pfad. Die ganze Auslösung läuft
  über `effectops.run_ops` (Save/Check/Schaden/Condition/Forced-Move) — der
  `random.randint`-Wurf ist raus, kein zweiter Würfel-/Save-Kern. Entdecken ist
  ein Weisheit-(Wahrnehmung)-Check gegen `search_dc`, Entschärfen ein
  DEX-Geschicklichkeitswurf gegen `disarm_dc` über `room.opposed`
  (`participant`/`check_roll`/`beats_dc`) — keine neue Werkzeug-Proficiency-Engine
  (DM gewährt ggf. Vorteil). Neue WS-Nachricht `trap` (`search`/`disarm`/DM
  `trigger`), Actor benennt ein FELD, nie eine Fallen-ID. Leak-Schutz: Die
  Antwort auf „leeres Feld durchsucht" und „versteckte Falle, Wurf verpatzt" ist
  byte-identisch — der Endpunkt ist kein Fallen-Oracle; `discovered` wird nur bei
  Erfolg gesetzt und dann per `map_changed` enthüllt. `disarmed` ist ein
  Runtime-Flag, das ein veraltetes Editor-Snapshot nicht re-armed (dispatch-
  Merge), und entschärfte Fallen federn auf `triggered`.

- **Entscheidung Phase 7 (vertikale Geometrie, 10 ft je Stockwerk):** Eine
  einzige kanonische vertikale Skala in `app/vertical.py`: EINE Höhen-Einheit der
  `elev`-Ebene UND EINE deklarierte Ebenen-Stufe entsprechen JEDEM exakt 10 ft
  (`ELEV_FT=10`, `FLOOR_FT=10`; `elev_to_ft`/`floor_to_ft`/`absolute_ft`).
  Bewusst NUR die Skala/Buchführung — KEIN Höhenkampf: Sturzschaden,
  Höhen-Deckung und Flug/Schwimm/Kletter-Kosten bleiben die bewusst
  ausgelagerte Engine-Kante aus D70/D83. Pfadfindung gateert Schritte weiterhin
  an |Δz| ≤ 1 in EINHEITEN (unverändert); die Fuß-Angabe ist, was eine Einheit
  bedeutet, keine zweite Geometrie. Die Ebenen (`floors.py`) sind eine
  unsortierte, voneinander unabhängige Namensliste (Kollision/Sicht getrennt,
  D86/D88) — der deklarierten Reihenfolge wird eine Höhen-Ordnung gegeben
  (`floors.level`: Primär=0, jede weitere Ebene +1 Stufe = +10 ft;
  `absolute_height_ft` = Ebenen-Offset + Boden-Elevation×10 ft), rein
  geometrisch/reporting, ohne die Ebenen zu einem Kollisions-Stack zu machen.
  Die `elev`-Klammer bleibt bei -6..6 EINHEITEN. `55_diorama.js` bleibt tabu.

- **Konsequenzen Phase 7:** `app/vertical.py` (Skala, importfrei), additive
  Ebenen-Helfer in `app/floors.py` (kein Schema/Migration), Doku-Hinweis an der
  `elev`-Klammer. `tests/test_d113_vertical.py` (4) pins die Skala, den Ebenen-
  Stack (inkl. Reihenfolge nach `rename`) und dass die Einheiten-Klammer
  unverändert ist. Kanonische Suite: **921 passed, 1 skipped, 0 failed**
  (917 + 4). Sprint 42 (D113) ist damit in allen Phasen 2–7 erledigt; offen
   bleibt nur der menschliche Browser-Durchlauf der Phase-6-Oberflächen.

## D114 — Vertikale Token-Geometrie wird über Körper-Ebenen und Öffnungen entschieden; Sicht und physische Reichweite bleiben bewusst verschieden (Sprint 43)

- **Problem und Abgrenzung:** D86/D88/D102 behandelten Ebenen korrekt als
  voneinander unabhängige Besetzungs-/Sichtebenen. D113 führte nur eine
  Höhen-Skala ein. D114 macht Token zu echten vertikalen Volumina und Ebenen zu
  gestapelten Räumen, ohne eine zweite LOS-, Footprint-, Würfel- oder
  Bewegungsmaschine zu erzeugen. Die Entscheidung gilt für die Backend-Phasen
  0–5; Flug/echte vertikale Bewegung und UI bleiben ausdrücklich offen.

- **Token-Volumen:** `tokens.height_ft` ist die physische vertikale Ausdehnung,
  `tokens.elevation_ft` die Unterkante über der STANDFLÄCHE. Beide sind
  additiv-migriert; alte Tokens bleiben mit `NULL`/`0` gültig. Größenkategorien
  liefern nur dokumentierte Hausregel-Defaults (Tiny/Small/Medium 5 ft, Large
  10 ft, Huge 15 ft, Gargantuan 20 ft) und sind ausdrücklich keine Obergrenze.
  Technisches Validationsband: Höhe/Elevation jeweils 0..200 ft, negative
  Elevation wird auf 0 gekürzt. `app/vertical.py` bleibt die einzige Skala;
  `floors.py` berechnet daraus absolute Fuß- und gespannte Ebenen.

- **Öffnungen:** Neue pro-Ebene/pro-Zelle-Karte `openv` in `mapmodel`.
  `openv=1` bedeutet eine Deckenöffnung über dieser Zelle zur einen Level
  höher deklarierten Ebene. Fehlend, ungültig, falsche Länge oder `0` bedeutet
  durchgehend feste Decke — Fail-closed. `void`/Treppen werden nicht zweckentfremdet.
  Die Spieleransicht maskiert unerforschte `openv`-Zellen auf `0`; ein Opening
  darf nie durch Fog als Weltwahrheit durchsickern.

- **Einheitliche Schlussstelle:** `app/room/vertical3d.py` ist die einzige
  Etage-übergreifende Geometrie-Entscheidung. `body_planes()` liefert nur die
  Ebenen, in denen der Tokenkörper physisch ist; eine höhere Ebene wird nur
  aufgenommen, wenn die Höhe sie erreicht, das GESAMTE Footprint durch jede
  zwischenliegende Öffnung geht und die Zielzellen nutzbarer Boden sind.
  Ein einzelnes Loch lässt ein breites Geschöpf nicht durch.
  `observable_cells()` trennt bewusst zwei Phänomene: Körperpräsenz oder
  gleiche Ebene zeigen das volle Footprint; sonst nur ein senkrechter Shaft.
  Nicht verbundene Ebenen liefern leer. Damit bleibt das D86/D88 „elsewhere“
  ohne Öffnungen byte-identisch.

- **Sicht ist nicht Reichweite:** Für Nebel und Token-Delivery zählen
  `body_planes` als echtes Stehen (`_viewer_planes`, `viewer_source_cells`);
  ein aufragender Körper ist Licht-/Sichtquelle auf der oberen Ebene. Für
  Angriffe/Anvisieren nutzt `room.dice` `observable_cells`, weil ein Schacht
  Sicht gewähren kann. Melee-/Grapple-Nachbarschaft und Interaktionen nutzen
  hingegen nur `body_cells`: ein offener Schacht allein erlaubt kein Greifen,
  Drängen oder physisches Hantieren. Gleiche Ebene bleibt rein 2D; die
  vertikale Reichweiten-Zugabe entsteht erst bei einem Schacht.

- **Live-Sicherheit:** Token-Delivery, Präsenz-/Condition-Ereignisse,
  `/state`-Snapshot, `plane_viewers` und Interaktionen verwenden dieselbe
  Körperpräsenz-Entscheidung. `token_height` und `map_edit` lösen
  `reevaluate_visibility` aus, damit eine wachsende Höhe oder neu gesetztes
  `openv` Tokens sofort korrekt verteilt/entfernt statt erst beim nächsten Zug.
  Unregistrierte/unbekannte Floor-Namen verbinden nichts (fail-closed). Ein
  Push/Shove über Ebenen wird abgelehnt; nur Angriffe und Grapple können eine
  Körperpräsenz im gemeinsamen Ebenenanteil nutzen.

- **Bewusste Lücken:** Echtes Fliegen, vertikale Bewegungs-/Flugbudgets und die
  Client-Darstellung mehrerer Ebenenanteile sind Phase 6/7 und NICHT
  Feature-complete. Die D113-Werkzeuglücke bleibt bestehen: Entschärfen ist ein
  echter DEX-Check, aber Thieves'-Tools-Proficiency ist weiterhin nicht
  modelliert. UI-Beschriftungen sagen daher „Dexterity check“, nicht „Thieves'
  tools“.

- **Konsequenzen:** `authz.TOKEN_COLS` trägt `height_ft`/`elevation_ft`;
  `net.plane_viewers`, `room.visibility`, `room.rooms`, `room.dice`,
  `room.grapple` und `room.interact` fragen die zentrale
  `vertical3d`-Schlussstelle statt Home-Floor-Pauschalen. Neue Integrationstests:
  `tests/test_d114_vertical.py` (5), `tests/test_d114_openings.py` (4) und
  `tests/test_d114_phase5_integration.py` (5). Kanonischer Stand nach Phase 5:
  **937 passed, 1 skipped, 0 failed**.

### D114-Ergänzung — vertikaler Flug, Volumen-Kollision und UI sind umgesetzt

- **Vertikale Bewegung:** `app/path.py::find_path_3d` sucht über
  `(floor, origin)`-Zuständen. Horizontale Schritte bleiben ausschließlich in
  der bestehenden `path`/`step_legal`-Maschine; ein senkrechter Schritt prüft
  genau eine Levelstufe, eine vollständige Footprint-Öffnung und offenes
  Zielvolumen in `vertical3d`. `movecost.vertical_cost()` rechnet einen vollen
  Ebenenwechsel als `10 ft = 2` kanonische Bewegungsfelder — keine zweite
  Wirtschaft.

- **Flug und `void`:** `void` ist freies Flugvolumen, aber kein begehbarer
  Boden. `mode="fly"` darf `void` betreten und ebeneübergreifend fliegen;
  `mode="walk"` bleibt auf Standflächen und darf eine offene Vertikalachse nicht
  benutzen. Die Ganzzervolumen-Kollision nutzt `volume_final_valid()` mit den
  bestehenden Owner-/Reiter-Ausnahmen, ohne eine zweite Kollisionsregel.

- **Explizite Absicht:** Ein `move` wechselt die Ebene nur, wenn das Wire-Feld
  `floor` vorhanden und anders als die aktuelle Ebene ist — oder wenn ein
  Pfadpunkt ausdrücklich ein anderes `floor` trägt. Ein fehlendes Feld ist
  weiterhin die aktuelle Ebene und darf nicht als 3D-Wunsch missverstanden
  werden. `walk3d()` validiert jeden Schritt erneut, sendet `token_floor`,
  trägt Budget ab und führt Reiter mit.

- **UI/Canvas:** Token-Sheets setzen `height_ft`/`elevation_ft`; ein
  vertikaler Flugknopf sendet eine explizite Etagenabsicht, ohne die Route im
  Client zu erraten. Der DM-Editor besitzt einen `openv`-Pinsel, `openv` wird
  bei Resize mitgeführt und erscheint als `↕`-Hinweis. Tokens zeigen Elevation
  mit `↑<ft>` und eine gesetzte Körperhöhe mit `↕<ft>`.

- **Keine zweite Sichtautorität:** Für Spieler und DM-Charaktervorschau rendert
  der Canvas genau die servergefilterten Rows. Das DM-Browsing bleibt auf
  `state.viewFloor` beschränkt. `viewerPlane()` stellt die Browsing-Ebene bereit;
  `onPlane()` wendet sie nur für DM-Browsing an. Ein Client entscheidet nicht
  eigenständig, wer durch einen Schacht sichtbar sein könnte.

- **Bewusst offen:** Diagonale + vertikale Kombination, Springen/Fallen,
  vertikales Klettern/Schwimmen, interaktive 3D-Pfadvorschau, automatische
  Terrain-Erkennung und echte Browser-/Playwright-Akzeptanz sind nicht Teil von
  D114. Thieves'-Tools-Proficiency bleibt weiterhin die bekannte D113-Lücke.

- **Konsequenzen Phase 6–8:** Neue Phase-6-Tests in
  `tests/test_d114_phase6_vertical_movement.py` (7) und Phase-8-Integrationstests
  in `tests/test_d114_phase8_integration.py` (4). Kanonischer Stand nach
  Sprint-43-Abschluss: **948 passed, 1 skipped, 0 failed**.

## D115 — Nachtschicht 2026-10-16: bereits vorhandene Gear-/Build-Spalten erreichen die bestehenden Pfade, ohne neue Regelmaschinen

- **Ausgangslage:** D114 ließ eine dokumentierte, schmale Lücke: mehrere
  CSV-Felder (`speed_bonus_ft`, `darkvision_ft`, `backgrounds.skill_prof`,
  `feats.spells_grant`, Klassen-/Spezies-/Subclass-Felder) waren bereits
  validiert importiert, aber teilweise ohne Konsumenten oder nur als Bogenanzeige.
  Die Nachtschicht entschied nicht für neue Mechanik, sondern dafür, die
  vorhandenen Kanäle tatsächlich bis zu ihren Konsumenten zu führen.

- **Ausrüstung:** `movement._speeds` liest den vollständigen PC-Sheet durch
  `gear.as_sheet` und damit `gear.clean_speeds`, statt isoliert nur die
  `speed`-Spalte. `visibility._token_darkvision_cells` übernimmt zusätzlich
  `gear.effective_gear()["darkvision_ft"]`; Zellenradius bleibt 5 ft pro
  Rasterschritt. Der Tokenwert bleibt DM-/Operator-Authoring, Ausrüstung hebt
  ihn nur auf, ohne eine zweite Sichtmaschine. `hit_dice_bonus` wird über den
  einen Gear-SSOT in den Short-Rest-Weg gehoben, und `hands:2` nutzt
  ausschließlich die bestehende Zwei-Hände-Regel.

- **Build:** `backgrounds.skill_prof` wird in `_replay_origin` auf dem
  bestehenden Origin-/Chronology-Pfad angewandt. `feats.spells_grant` nutzt
  dieselbe Grant-Achse wie Subklassen und fließt in den bestehenden
  `spell_state`/`characters.spells`-Pfad; auch außerhalb des Klassenpools
  gültige Raum-Zauber können projiziert werden. `classes.expertise` wird
  optional auf der bereits vorhandenen Skill-Achse angewandt (0/1/2): Die
  Auswahl bleibt hinter der Zeilenkapazität und einer bereits bestehenden
  Profizienz zurück, wenn die Klasse keine Expertise zulässt.

- **Provenienz statt zweiter Regelkern:** Background-Tools/Sprachen/Features,
  `classes.weapon_prof`/`armor_prof`, Subclass-Features und die Species-Zeile
  werden als read-only Ledger-/UI-Projektion erfasst. Sie liefern nachvollziehbare
  Sheet-Informationen, ohne Größentypen, Bewegung oder Waffen-/Rüstungsadjudikation
  aus dem bestehenden Fußabdruck-/Item-/Executor-Kern wegzunehmen.

- **Bewusste Grenzen:** `feats.requires` bleibt Inhaltstext; eine echte Prüfung
  würde ein 2024-Fertigkeitsrangmodell erfordern, das die Engine nicht besitzt.
  Species-, Klassen- und Subclass-Texte steuern weiterhin nicht automatisch
  Bewegung, Footprint oder Kampfentscheidungen. `items.duration` und
  Zauber-Dauerablauf bleiben offene, separat dokumentierte Punkte.

- **Konsequenzen:** Neue Tests in
  `tests/test_engine_gear_grants.py` (11) pinen Ausrüstungs-Speed, Ausrüstungs-
  Dunkelsicht, Hit-Dice-Bonus, Hand-Count, Background-Fertigkeiten,
  Background-Feature/Languages, Feat-Spell-Grant, optionale Klassen-Expertise,
  Klassen-/Subclass-/Species-Projektion. Kanonischer Stand nach der
  Nachtschicht: **959 passed, 1 skipped, 0 failed**.

## D116 — AP-001: Der Reichweiten-/Reach-Härtungstest wird nicht reaktiviert, sondern seine eigentliche Testfehlerquelle entfernt

- **Ausgangslage:** Der einzige dauerhafte Kanon-Skip markierte den
  Live-Härtungstest `test_out_of_range_and_cross_reach_refused` als „flaky in
  the test harness“. Die Server-Engine hatte die Reichweiten- und Reach-Gates
  bereits, aber ohne Live-Test blieb die Behauptung unbewiesen.

- **Diagnose:** Kein Race und keine Engine-Lücke: `item_defs` werden im
  `/state`-Payload alphabetisch sortiert. Der Test griff nach dem Anlegen
  zweier Definitionen positionell auf `[0]` und `[-1]` zu. Nach der zweiten
  Anlage war `Dagger` alphabetisch vor `Dart`, sodass der Test versehentlich
  die erste Waffe erneut grantete. Eine zusätzliche Assert-Drift erwartete die
  ehemalige Textur „out of range“, während die Engine heute „maximum range“
  zurückgibt.

- **Entscheidung:** Der Test wird durch eindeutige Namensauflösung determinisch
  gemacht und prüft die aktuell autoritativen Fehlerformulierungen exakt. Der
  Skip wird entfernt, statt ihn mit einem Retry zuzukleistern.

- **Konsequenzen:** Die Kanonsuite läuft erstmals wieder vollständig ohne
  dauerhaften Skip: **960 passed, 0 skipped, 0 failed**. Der angebundene
  Reichweiten-/Reach-Sicherheitsnachweis ist als AP-001 abgeschlossen und im
  `docs/AUTONOMOUS_WORK_LOG.md` dokumentiert.

## D117 — AP-003: `duration` wird Startwert der bestehenden Bedingungsuhr, nicht eine zweite Uhr

- **Ausgangslage:** `duration` existierte in `spells.csv` und `items.csv`, aber
  nur als Text. Eine `condition`-Operation musste ihre Runden manuell
  wiederholen, was CSV-Inhalt und Mechanik unnötig koppelte und eine falsche
  „ohne Konsumenten“-Lücke erzeugte.

- **Entscheidung:** Die bestehende Condition/Runden-Lifecycle-Engine bleibt die
  einzige Uhr. Für ihren START-WERT darf eine condition-Operation `"duration"`
  verwenden; ein fehlendes `rounds` ist gleichbedeutend. `duration_rounds()`
  übersetzt ausschließlich in Runden (`1 minute → 10`, `1 hour → 60`, `1 day`
  auf die bestehende 999-Runden-Obergrenze). `instant`, `permanent` und
  unbekannte Texte bleiben 0, was dem bisherigen Marker-Verhalten entspricht.

- **Speicherstrategie:** Zaubereffekte werden beim Mapping mit der konkreten
  Dauer aufgelöst. Item-Definitionen behalten den Marker im kanonischen JSON,
  damit eine Änderung von `props.duration` beim nächsten Auslösen wirksam wird.
  Dadurch bleibt die Canonisierung stabil, ohne den Itemwert einzubrennen.

- **Konsequenzen:** Die Kanonsuite wuchs auf **963 passed, 0 skipped, 0 failed**.
  Die Dokumentation unterscheidet jetzt sauber zwischen combat round expiry,
  Noncombat-Wanduhr und einem zusätzlichen Save, der eine Bedingung vorzeitig
  beendet. Nur Ersteres ist durch diese Entscheidung abgedeckt.

## D118 — AP-004: Klassen-Casting-Ability als additive Build-Meta (2026-10-16)

- **Status:** umgesetzt
- **Kontext:** `classes.spellcasting_ability` war in den Klassendaten vorhanden,
  wurde aber vom Build-Plan, Apply-Resultat, Ledger und der UI ignoriert.
- **Entscheidung:** `charbuild` liest die erste gültige Klassenlevel-Angabe und
  stellt sie als `plan.needs.spell.ability`, `apply.casting_ability` sowie
  `build.casting.ability` bereit. Prep-Wizard und Raum-Bogen zeigen die Meta an.
  Die Ausführung eines registrierten Zaubers behält weiterhin seinen eigenen,
  geprüften `ability`-Wert.
- **Grund:** Die Klasse kann ohne einen Execution-Override ehrlich dokumentiert
  werden. Eine automatische Überschreibung aller Zauber hätte ein zweites,
  klassenbasiertes Spellcasting-Modell neben der bestehenden Ability-Registry
  erzeugt und wäre mit Einzel-Zauber-Definitionen, Monster-Abilities und
  Feat-Abilities in Konflikt geraten.
- **Konsequenzen:** Das Build-Ledger enthält jetzt casting-Provenienz.
  Die Kanonsuite wuchs auf **964 passed, 0 skipped, 0 failed**. Eine spätere
  Execution-Integration bleibt möglich, erfordert aber eine ausdrückliche
  Architektur- und Migrationsentscheidung.

## D119 — AP-005: Expertise als geführte, serverseitig erzwungene Wahl (2026-10-16)

- **Status:** umgesetzt
- **Kontext:** `classes.expertise` war bereits als Datenfeld vorhanden. Das
  Wizard zeigte es aber nur als ununterstützten Entscheidungstyp, während
  `apply()` eine Auswahl optional und lückenhaft validierte.
- **Entscheidung:** Die Klassen-Expertise ist jetzt eine reguläre Build-Wahl.
  `plan()` und `apply()` melden Level, Anzahl und zulässige Kandidaten; das
  Wizard rendert Checkboxen. Die Serverprüfung verlangt genau die deklarierte
  Anzahl, weist Duplikate ab und akzeptiert nur bereits geübte Fertigkeiten.
  Der Erfolg bleibt eine additive Erhöhung des bestehenden Skillwerts auf `2`.
- **Grund:** Ohne geführte UI und exakte Validierung wäre CSV-Expertise eine
  bloße Zahl ohne vertikale Funktionskette. Eine neue Expertise-Engine oder
  ein zweiter Skillwert wäre überflüssig und würde die bestehende Skill-Achse
  spalten.
- **Konsequenzen:** Alle betroffenen Tests versenden jetzt die erforderliche
  Wahl. Kanon: **964 passed, 0 skipped, 0 failed**. Die eigentliche
  Browserabnahme der neuen Checkboxen folgt als AP-006.

## D120 — AP-006: reproduzierbarer lokaler Chromium-Runner (2026-10-16)

- **Status:** umgesetzt
- **Kontext:** Der Build-Wizard war backend- und quelltextseitig getestet, aber
  die neue Expertise-Checkbox war noch nie in einem echten Browser gerendert
  worden.
- **Entscheidung:** `scripts/e2e_build_wizard.py` startet gegen eine
  lokale Testinstanz und prüft in headless Chromium die komplette Kette:
  Registrierung, Raum, Content-Import, Beitreten, Charakteranlage, Wizard,
  Skill-/Expertise-Checkboxen, Apply und persistierten Skillwert. Playwright
  wird bewusst in einem temporären venv installiert und nicht in die
  Kanon-Test-Image aufgenommen.
- **Grund:** Ein echtes Browserwerkzeug gehört in die Acceptance, darf aber
  die deterministische Kanonsuite nicht von Netzwerkzugriffen, großen
  Binärdateien oder Browser-Library-Abhängigkeiten des Wirts abhängig machen.
  Der Runner bleibt getrennt, reproduzierbar und optional ausführbar.
- **Konsequenzen:** Die Wizard-Kette ist erstmals mit echtem Chromium grün.
  Kanon bleibt **964 passed, 0 skipped, 0 failed**. Weitere Browserketten
  können schrittweise in demselben Muster ergänzt werden.

## D121 — AP-007: Feature-Voraussetzungen fail-closed und chronologisch (2026-10-16)

- **Status:** umgesetzt
- **Kontext:** `feats.requires` war importierbar, wurde aber nie geprüft.
  Zusätzlich bestand im Recompute eine Chronologie-Lücke: Level-8-Features
  wurden vor der Level-1-Fertigkeitswahl angewandt.
- **Entscheidung:** `requires` wird jetzt für Attributswerte, Skill-Proficiency
  und vorangehende Features geparst. Unbekannte Bedingungen werden abgewiesen.
  `apply()` prüft sie serverseitig; `plan_for_character()` liefert verfügbare
  Optionen inklusive fehlender Voraussetzungen, und der Wizard deaktiviert
  unzulässige Features. Level-1-Skills werden vor späteren Features angewandt.
- **Grund:** Eine ignorierte CSV-Spalte erzeugt falsche Vertrautheit. Fail-closed
  verhindert, dass „5 ranks" oder andere unmodellierten Bedingungen als
  „keine Voraussetzung" gelesen werden. Die Chronologie muss denselben
  Charakterzustand sehen, den der Bogen und die UI darstellen.
- **Konsequenzen:** Kanon: **967 passed, 0 skipped, 0 failed**. Der Demo-Feat
  `feat_keen` nutzt jetzt `Skill Proficiency — Perception` statt des alten
  rangbasierten Demo-Texts. Weapon-/Tool-/Spellcasting-/Rank-Voraussetzungen
  bleiben bewusst unsupported, bis eine echte Mechanik existiert.

## D122 — AP-008: Creature-CSV nutzt den einen bestehenden NPC-Block (2026-10-16)

- **Status:** umgesetzt
- **Kontext:** `creatures.csv` hatte einen Import, aber keinen Konsumenten;
  die tatsächlich ausführbaren Monster liefen ausschließlich über die
  handgepflegten `npc`-Blöcke in Bestiarium/Tokens.
- **Entscheidung:** `npc.project_creature()` erzeugt aus einer Raum-Zeile den
  unveränderten `npc.clean_npc()`-Block. DMs können ihn previewen und per POST
  als persönliches Bestiarium-Template anlegen. Importiertes Freitext-Material,
  das die NPC-Grammatik nicht trägt, bleibt sichtbar unsupported.
- **Grund:** Ein eigener `creature_token`-Zweig oder ein zweites Monstermodell
  hätte Kampf, Bewegung und Ressourcen gespalten. Die Projektion macht CSV zu
  einem Zulieferer des bestehenden NPC-Pfads, ohne die Autorisierung oder
  State-Achsen zu duplizieren.
- **Konsequenzen:** Kanon: **971 passed, 0 skipped, 0 failed**; zwei
  Chromium-Suiten sind grün. Die projection ist DM-only, raum-scoped und
  Duplikate werden sichtbar abgewiesen. Komplexere Freitextaktionen bleiben
  bewusst als DM-Notiz erhalten, statt falsch automatisiert zu werden.

## D123 — AP-009: Dunkelsicht bleibt auf einer Sinnensäule (2026-10-16)

- **Status:** umgesetzt
- **Kontext:** CSV und Token hatten bereits Dunkelsicht-Felder, aber der
  NPC-Block verlor die Information; ein Monster konnte sie nie nutzen.
- **Entscheidung:** `npc.clean_npc()` führt Feet als `darkvision_ft`, Spawn und
  NPC-Editor übersetzen sie in die bestehende Token-Spalte in Zellen
  (`ft / 5`). Legacy-Token ohne Blockwert bleiben über die Tokenspalte erhalten;
  eine bewusste Blockbearbeitung aktualisiert die Spalte.
- **Grund:** Die D89-Sicht-Engine und die D115-Ausrüstungs-Dunkelsicht sind die
  einzigen mechanischen Dunkelsicht-Pfade. Eine zweite Monster-Sicht oder eine
  eigene CSV-Tabelle würde dieselbe Sinne-Achse spalten.
- **Konsequenzen:** Kanon: **973 passed, 0 skipped, 0 failed**. Importierte
  Monster sehen mit ihren deklarierten 60 ft = 12 Zellen, und der Editor kann
  den Wert ohne DB-Migration korrigieren. Bewegungsfelder aus Creature-Zeilen
  bleiben beim Spawn ebenfalls erhalten.

## D124 — AP-010: NPC-Skills bleiben auf einer Daten- und Anzeigensäule (2026-10-16)

- **Status:** umgesetzt
- **Kontext:** Skills wurden bereits in den NPC-Block projiziert, aber das
  Sheet zeigte sie nicht und der Bestiarium-Spawn schickte nur ein manuell
  zusammengesetztes Teilfeld.
- **Entscheidung:** Das Monster-Sheet rendert die bestehende `skills`-Map
  read-only über den kanonischen `SKILLS`-Namen. Der Spawn sendet den ganzen
  `npc`-Block an den bestehenden Handler; Server-normalisiert weiterhin Block,
  Sinnensäule und alle übrigen Werte.
- **Grund:** Anzeige, Spawn und CSV-Projektion müssen dieselbe Skill-Achse
  verwenden. Ein clientseitig erratener Block oder eine zweite Monster-Skill-
  Logik würde dieselbe Information spalten.
- **Konsequenzen:** Kanon: **976 passed, 0 skipped, 0 failed**; realer Chromium-
  Import + Spawn zeigt Hawk-kin mit Dunkelsicht 60 ft / 12 Zellen und Perception
  im Sheet. Expertise bleibt eine Anzeige-Ebene, keine eigene Mechanik.

## D125 — AP-011: Ressourcen-Gewährung bleibt auf dem einen Ressourcen-Ledger (2026-10-16)

- **Status:** umgesetzt
- **Kontext:** Die Effektgrammatik konnte vorhandene Ressourcen nur verbrauchen.
  Ein zurückgebender Zauber/Trigger hätte sonst einen zweiten Zähler erzeugen
  müssen.
- **Entscheidung:** `resource` erhält `mode: cost|restore`; `cost` bleibt
  Default für alte Zellen. Restore erhöht eine bereits registrierte,
  kanonische Charakter-Ressource um einen Wert innerhalb ihres `max`-Feldes.
- **Grund:** `characters.resources` und der resource-Handler sind die einzige
  Ressourcendarstellung. Die Grammatik darf sie erweitern, aber nicht duplizieren.
- **Konsequenzen:** Kanon: **977 passed, 0 skipped, 0 failed**. Bestehende
  Kosten-Preflights bleiben atomar, unbekannte IDs fail-closed, volle
  Ressourcen unverändert. Die CSV-Schicht kann jetzt sowohl Klassen-/Focus-
  Nutzungen kosten als auch im Erfolg zurückgeben.

## D126 — AP-012: Speziesdaten nutzen Bewegung, Sicht und Footprint, statt sie nachzubauen (2026-10-16)

- **Status:** umgesetzt
- **Kontext:** `species.csv` besaß Geschwindigkeit, Sinne und Größe, aber nur
  eine Anzeige-Projektion.
- **Entscheidung:** Die Spezies-Projektion in `characters.build` wird Teil der
  kanonischen Sheet-Ableitung. Bewegung, LOS-Sicht und Token-Footprint lesen
  daraus ihre Werte; keine neue Movement-, Sight- oder Footprint-Engine.
- **Grund:** Eine Spezies ist kein neuer Mechanismus, sondern Input für die
  bestehenden Engines. Separate Werte in Sheet, Token oder DM-Notiz würden
  dieselbe Existenz dreimal beschreiben.
- **Konsequenzen:** Kanon: **979 passed, 0 skipped, 0 failed**. Stoutheart bewegt
  sich 25 ft und sieht 12 Zellen; Kit-kin bekommt Small-Footprint. Ausrüstungs-
  Boni und DM-Autoring bleiben übereinanderliegende, unveränderte Ebenen.

## D127 — AP-013: `companion` ist Markierung im NPC-Block, keine zweite Ownership-Engine (2026-10-16)

- **Status:** umgesetzt
- **Kontext:** `creatures.csv` führte `companion`, doch die Information verlor
  sich zwischen Content-API, NPC-Block und DM-UI.
- **Entscheidung:** `companion` wird als bool-Feld in `npc.clean_npc()` und über
  `add_token`/`update_npc` in den bestehenden NPC-Block übernommen. Review,
  Sheet und Bestiarium zeigen/bearbeiten nur dieselbe Markierung.
- **Grund:** Ob ein Monster ein Begleiter ist, ist Content-Metadatum und
  Spielhinweis. Ownership, Kontrolle, Kampfnähe und Summon-Regeln gehören zu den
  bestehenden Token-, Combat- und Encounter-Pfaden und werden hier nicht neu
  erfunden.
- **Konsequenzen:** Kanon: **981 passed, 0 skipped, 0 failed**. Der Spawn-Pfad
  muss weiterhin alle relevanten NPC-Felder vollständig in `clean_npc()` übergeben;
  ein während der Entwicklung verlorener `attacks`/`spell_slots`-Anteil wurde durch
  echte WS-Angriffstests sichtbar und behoben.

## D128 — NPC-Angriffsreichweite wird hartes Gate auf der bestehenden Footprint-/Ebenen-Distanz (2026-10-16/17; Doku nachgereicht in der Recovery-Sitzung 2026-10-17)

- **Status:** umgesetzt (Code und Tests waren bereits im gepushten Stand
  enthalten; der Doku-Abschnitt wurde vor dem Abbruch der autonomen Sitzung
  nicht mehr geschrieben und wird hier in `docs/RECOVERY_2026-10-17.md`
  belegter Session nachgereicht, statt die Umsetzung neu zu erfinden).
- **Kontext:** Der Angriffsauslöser des NPC-Blocks behandelte Distanz nur als
  Nachbarschafts-Advisory. Deklarierte Reichweiten (SRD: „reach 10 ft“,
  Longspear usw.) existierten als Freitext in `creatures.csv`, ohne Konsument —
  jede entfernte Ansage war entweder still falsch oder vom DM-Gefühl abhängig.
  `dice._vertical_range_distance` (D109/D114) war bereits DIE eine
  Footprint-Zellen × 5 ft messende, ebenenrichtige Distanz der
  Spielerangriffe.
- **Entscheidung:** `npc.project_creature()` liest „reach N ft“ aus der
  Angriffszeile; `npc.clean_npc()` normalisiert `reach` (Clamp 0–999, Default
  5 ft). `handle_npc_attack` prüft das Ziel gegen `atk["reach"]` über
  `_vertical_range_distance` — dieselbe Distanzquelle wie Spielerangriffe und
  Interaktionen; Fail-closed mit „out of reach“, wenn keine meszbare Linie
  existiert. Der NPC-Editor zeigt/bearbeitet `reach` je Angriff
  (`na-reach`-Feld, 0–999). Es wurde keine zweite Reichweiten-Mechanik gebaut.
- **Grund:** Angriffsauslösung und Interaktion müssen dieselbe Geometrie
  wahrnehmen. Eine advisory deklarierte Regelzahl ist eine falsifizierte
  Datenlinie ohne Konsument — sie wird entweder Leser-fähig gemacht oder
  sichtbar abgelehnt.
- **Konsequenzen:** Kanon: **985 passed, 0 skipped, 0 failed** (Baseline der
  Recovery-Sitzung 2026-10-17, `tests/test_d128_npc_reach.py`: 4 neue Tests —
  Standard-Reichweite verweigert die zweite Zelle, deklarierte 10-ft-Reichweite
  trifft, CSV-Projektion und `clean_npc`-Rundreise behalten `reach`,
  Editor-Pin). `docs/CSV_ONLY_READINESS.md` wurde von „advisory“ auf das
  durchgesetzte Gate korrigiert.

## D129 — Exhaustion wird ein echter, kumulativer Modifikator aus derselben SSOT (2026-10-17, AP-015)

- **Status:** umgesetzt.
- **Kontext:** Der Exhaustion-Zaehler (0-6) existierte seit D35 als DM-Feld
  und Bogen-Anzeige, aber ohne jede mechanische Wirkung. RULES_AUDIT
  F3/F4/K8 dokumentierte die Abweichung von SRD 5.2.1: -2 auf
  Angriffs-/Schadens-/Probe-/Rettungswuerfe, -5 ft Tempo je Stufe, Tod bei
  Stufe 6, Long Rest -1.
- **Entscheidung:** Zwei Helfer in `gear.py` sind die einzige
  Ableitungsquelle: `exhaustion_roll_mod()` (-2 x Stufe) und
  `exhaustion_speed_penalty_ft()` (-5 x Stufe). Bestehende Konsumenten
  werden angebunden: `movement._speeds` (nur PC-Tokens, nur walk -
  fly/swim/climb bleiben bewusst unberuehrt, weil die
  Footprint-Engine nur walk ableitet), die
  Waffen-Angriffs-/Schadenszeilen, Check/Save/Skill und die
  Spruch-Angriffs-/Spruch-Schadens-Texte in `dice.py`,
  `opposed.check_roll/save_roll/bonus_roll/melee_attack_number` und
  `combat.token_dex_mod` (Initiative). Der Tod bei Stufe 6 entschieden
  durch `status.py` ueber den bestehenden Death-State
  (`death.new()/apply_thresholds`, hp=0) - keine zweite
  Tod-Mechanik, kein erfundener Death Save. Long Rest senkt eine Stufe im
  bestehenden `handle_long_rest`-UPDATE
  (`exhaustion=MAX(0, COALESCE(exhaustion,0)-1)`).
- **Grund:** Eine Regelzahl, die nur als Datenfeld im Bogen lebt, ist eine
  Bogen-Luege. Statt einer zweiten "Exhaustion-Engine" wird an den Stellen
  erweitert, die laengst das Sheet fragen.
- **Konsequenzen:** Kanon: **994 passed, 0 skipped** (9 neue Tests in
  `tests/test_d129_exhaustion.py`: Temp ableitung inkl. NPC-No-op,
  Angriffs-/Schadenszeile mit "-N exhaustion"-Suffix und abgeleiteten
  Erwartungswerten statt Magischer Zahlen, Check/Save/Skill,
  Opposed-Paritaet per Delta-Vergleich, Initiativ-Modifikator, Tod bei 6,
  Long-Rest-Kaskade 3-2-1-0, Clampung). Das 16-h-Gate des Long Rest
  bleibt bewusst offene, dokumentierte Hausregel-Grenze (F3 bleibt
  teilweise offen).

## D130 - Save Ends: Bedingungen mit sa+dc wuerfen am Ende des eigenen Zuges durch die bestehende Rettungs-Ableitung (2026-10-17, AP-016)

- **Status:** umgesetzt.
- **Kontext:** SRD 5.2.1 laesst viele Effekte enden, wenn das betroffene
  Wesen am Ende seines eigenen Zug eine Rettungswiederholung besteht
  ("Save Ends"). D117 hatte die Dauer-mit-Rettungs-Ende-Wirkung bewusst
  offen gelassen (FEATURE_COMPLETE_GAPS Zeile "Effektgrammatik: Dauer mit
  Rettungs-Ende"). Der Escape-DC (D112) und die Opposed-Rettungs-Ableitung
  (`opposed.save_roll`/`beats_dc`) existierten bereits als Konsumenten-Pfade;
  ein Escape ist jedoch eine ACTION und kein End-of-Turn-Ereignis - die
  Luecke war das Wiederholungs-Ereignis selbst.
- **Entscheidung:** Condition-Instanzen bekommen ein additives Feld `sa`
  (Rettungs-At ability, SSOT-Whitelist `gear.ABILITIES`, geputzt in
  `conditions._clean_sa`). `combat._save_ends(room_id, token_id)` feuert am
  Ende des Zuges des betroffenen Tokens - an beiden bestehenden
  Turn-Uebergabepunkten (`_end_turn_common` und `handle_init_next`), VOR
  `advance_turn`, damit die Uhrzeit "Ende seines Zuges" bleibt. Wuerfel,
  Modifikator und Sichtbarkeit sind dieselbe Ableitung wie bei
  Spielerrettungen (`opposed.participant` loest PC wie NPC ueber
  `npc.to_char`); die Ankundigung folgt der Concentration-Konvention
  (PC oeffentlich, NPC DM-only via `_announce_roll`). Erfolg entfernt genau
  den einen Eintrag - Geschwister-Eintraege mit gleichem Key (D109
  src/ref-Coexistenz) bleiben. Eintrag OHNE `sa` - jeder Prae-D130-Eintrag
  und jede Grapple-Instanz - wuerfelt nicht. `cond_add` transportiert jetzt
  auch `dc` (DM-Autoren Weg zum DC, D112-Muster).
- **Grund:** Ein zweiter Rettungswuerfel-Weg oder eine zweite Uhr haette
  genau die D80-Ein-Uhr-Invariante gebrochen. Die Regelzahl "Save Ends"
  bekommt einen Konsumenten auf der bestehenden Uhr und der bestehenden
  Rettungs-Mathematik - nicht mehr.
- **Konsequenzen:** Kanon: **1000 passed, 0 skipped** (6 neue Tests in
  `tests/test_d130_saveends.py`: sa-Feld-Rundreise/Validierung inkl.
  Prae-D130-Bytekompatibilitaet, Erfolg entfernt (dc 1 dex - kann nie
  fehlschlagen), Misserfolg erhaelt Instanz mit dc+sa (dc 30 wis - kann nie
  gelingen), fremde Zuende loesen NICHT deine Rettung aus, dc-only-Eintraege
  bleiben unangetastet, NPC-Pfad ueber denselben Participant).
  Effekt-Operateure (effectops) koennen `sa`/`dc` spaeter als Daten
  durchreichen; der Mechanik-Konsument ist jetzt fertig.

## D131 - Casting Time verbraucht den Turn-Slot, den es benennt (2026-10-17, AP-017)

- **Status:** umgesetzt.
- **Kontext:** `spells.csv` fuehrt `casting_time` als Spalte (content-Schema),
  aber kein Konsument las sie - jedes Wirken war action-oekonomisch
  gleichgueltig, und `handle_cast` konsumierte ueberhaupt keinen
  Turn-Slot. Die Turn-Slot-Oekonomie (action/bonus/reaction, D74) und ihr
  Verbraucher-Muster existierten bereits im Angriffspfad (`_item_attack`:
  Token-Pflicht im Kampf, turn-Pruefung, `spend_slot`), die
  Replay-Guard-Mechanik (D93/D94: `inv_ops`) ebenso.
- **Entscheidung:** `gear.casting_slot()` mappt den Freitext auf den
  benannten Slot ("bonus"/"reaction" schlagen "action";
  minute/hour/ritual = ausserhalb des Turn-Tempos -> None = kein Slot).
  `handle_cast` validiert zunaechst (Spell-Lookup -> nicht-destruktiver
  Replay-Probe `inventory.claimed` -> Token-Pflicht im Kampf -> turn ->
  Slot verfuegbar) und verbraucht via `spend_slot` erst nach erfolgreichem
  Spell-Slot-Claim (D110: abgelehnte Zauber verausgaben nichts).
  `clean_spells` und die Katalog-Projektion (`charbuild`) tragen
  `casting_time` jetzt durch - die CSV-Spalte hat damit ihren Konsumenten.
  Der NPC-Wurfpfad (`_npc_cast`) verändert sich nicht (NPC-Blocks fuehren
  kein casting_time; das waere ein Daten-Feature, keine Mechanik-Luecke).
- **Grund:** Action-Oekonomie ist eine einzelne Uhr mit drei Zeigern. Eine
  Spruchfeld-Angabe ohne Konsument ist eine Bogen-Luege; ein zweiter
  Slot-Zaehler haette genau die D74-Invariante gebrochen.
- **Konsequenzen:** Kanon: **1007 passed, 0 skipped** (7 neue Tests in
  `tests/test_d131_casting_time.py`: Text-Mapping inkl. SRD-Default '' =
  action, action-Verbrauch + Zweitsperre, bonus verbraucht nicht die action,
  minute-Sprueche lassen beide Slots heil (Spell-Slot trotzdem belegt),
  Token-Pflicht verausgabet vorher nichts, Replay bleibt still trotz
  verbrauchsaction, Spell-not-found antwortet vor dem Token-Gate).
  Die uebrigen bestehenden Cast-Tests wirken out of combat - die
  Kanontreue des Gates bleibt ohne kuenstliche Testspruenge belegt.

## D132 - value_gp und cr bekommen Konsumenten auf den bestehenden Datenlinien (2026-10-17, AP-018)

- **Status:** umgesetzt.
- **Kontext:** `items.csv` fuehrt `value_gp` seit je als Spalte, doch die
  Projektionskette CSV -> `item_defs` -> Inventar-Eintrag liess das Feld
  fallen; `creatures.csv`-`cr` wurde nie in den NPC-Block projektiert
  (CSV_ONLY_READINESS listete "CR->Challenge-Projektion" als offen). Beide
  Felder waren Bogen-Daten ohne Konsumenten.
- **Entscheidung:** Keine neue Oekonomie, keine XP-Mechanik (2024 arbeitet
  Meilensteine). Die bestehenden Linien tragen die Felder: additive
  Migration `item_defs.value` (REAL DEFAULT 0); `inventory.clean_def`
  normalisiert 0..999999 (2 Dezimalstellen); `content._project_item`
  uebergibt `value_gp`; `entry_from_def`/`gear.clean_items` fuihren `value`
  bis auf den Charakter-Eintrag (Prae-D132-Entries = 0, byte-stabil).
  `npc._clean_cr` laesst nur das SRD-Band zu (0, 1/8, 1/4, 1/2, 3/4, 1..30;
  Rest = '' = unbekannt, nie ein gefaelschter Wert); `project_creature` und
  der `add_token`-Whitelist-Pfad transportieren `cr` in den Block, der ins
  Monster-Sheet-Payload wandert (D124-Praezedenzfall: read-only-Sichtbarkeit
  ist ein akzeptierter Konsument).
- **Grund:** Der Zustand "Spalte ohne Konsument" ist eine Datenlinie, die
  Luegen erzaehlt. Ein Konsument auf der bestehenden Projektion ist redlich;
  eine erfundene Shop- oder XP-Mechanik waer eine zweite Engine.
- **Konsequenzen:** Kanon: **1013 passed, 0 skipped** (6 neue Tests in
  `tests/test_d132_value_cr.py`: CR-Band inkl. Ausreisser-Verwerfung,
  Projektion ueber die eine Blockform, value-Clamps + Eintrag-Rundreise,
  `_project_item` mit frischem id (item_defs.id ist GLOBAL, D100),
  DM-def -> Grant -> Character-Item, NPC-Token traegt cr). Der
  Projektions-Warnkanal (stored-but-not-projected) hat den Placeholder-Fehler
  des Patches selbst gefangen - fail-loud wirkt.

## D133 - Loot-Objekte mit container-Flag sind echte D92-Container (2026-10-17, AP-019)

- **Status:** umgesetzt.
- **Kontext:** Der Karten-Editor konnte seit je Loot-Glyphen ablegen; der
  Weglaufweg schrieb beim Betreten nur "[loot] Label" in die Notizen des
  Charakters und markierte taken_by - Inhalt als Daten gab es nicht.
  FEATURE_COMPLETE_GAPS fuehrte das als Luecke mit dem Hinweis, das
  Container-System (D92) und der loot-Kanal (D105, Schluessel tok:<id>)
  seien eins zu eins uebertragbar.
- **Entscheidung:** Loot-Eintraege bekommen das Flag `container`.
  `mapmodel._entity` laesst `container`/`hinted`/`dm_only` durch die
  Sanitisierung (die Beute-Liste war ein Whitelist-Schluessel ohne diese
  Felder); `handle_map_edit` bewahrt `hinted` als Runtime-Markierung wie
  `taken_by`. `handle_inv_container` loest zusaetzlich den Schluessel
  `loot:<eintrag-id>` auf (Praezedenz: D105 `tok:<token_id>`) und nutzt
  denselben Anker (Zelle, dm_only, Reichweite, Ebene) wie Welttruhen.
  `take_loot` verweigert bei gesetztem Flag das Notiz-Picken endgueltig und
  fluestert einmalig den Oeffnen-Hinweis. Client: Editor-Checkbox
  "Container", Klick auf die Geaefen-Offnung per `openLootObject` auf dem
  existierenden `inv_container`-Kanal, Inhalt laeuft ausschliesslich ueber
  die autorisierten Antworten - nie ueber map JSON oder /state (D92-Invariante).
- **Grund:** Loot auf der Karte ohne Inhalt ist eine Dekoration, die
  Beute vorgaukelt. Die Uebertragung auf die bestehende
  Container-Tabelle (Raum, Schluessel) - nicht eine zweite Truhen-Mechanik
  - haelt die D92-Regeln (Replay, Serialisierung, Fog-Gates) fuer Loot
  gratis mit.
- **Konsequenzen:** Kanon: **1018 passed, 0 skipped** (5 neue Tests in
  `tests/test_d133_loot_container.py`: kein Notiz-Pickup trotz Ueberlaufen,
  Muenz-Rundfuellen/Entnehmen ueber den loot:-Schluessel mit Wallet-Wahrheit,
  Reichweiten-Antwort von ferne, Legacy-Notiz ohne Flag unveraendert,
  unbekannter/nicht markierter Schluessel bleibt still).
  Editor-Eintraege ohne Flag verhalten sich byte-identisch wie vorher.

## D134 - Das eine 2024-Incapacitated regelt Aktionen, nicht Bewegung (2026-10-17, AP-020)

- **Status:** umgesetzt.
- **Kontext:** F5 hatte die Condition-Liste 2024-konform gemacht (key da),
  die Wirkung war aber falsch geerbt: `incapacitated` trug
  `blocks_movement + auto_fail_saves` - beides sagt SRD 5.2.1 der EINFACHEN
  Incapacitated gerade NICHT zu (Bewegung bleibt frei, Retten normal); die
  Auto-Fails gehoeren zu paralyzed/petrified/stunned/unconscious. Ausserdem
  gab es kein Wort in der Hook-Grammatik fuer "keine Aktionen/reactions",
  und die Grapple-Loesung pruefte einen Bewegungs-Block statt des vom SRD
  genannten Incapacitated-Zustands des Greifenden.
- **Entscheidung:** Neuer Hook `no_actions` in HOOKS-Grammatik und
  BUILTIN_HOOKS: parent = {no_actions} pur; die vier Familienmitglieder
  behalten ihre Bloecke und bekommen no_actions. Konsumenten - alle vor
  jeder Konsumtion validiert: Angriffspfad (`_item_attack`), Wirk-Gate
  (D131), der Attack/Escape-Choke `_take_action` (grapple-Flucht und
  Grapple-Offensive laufen ueber ihn), Dash (`handle_dash`). Reaktionen sind
  im Engine-v1-Scope nicht modelliert - dokumentierte Grenze (EFFECT_GRAMMAR
  S6), no_actions benennt sie, der Angriffspfad kann nichts verbieten, was
  der Wuerfel nie verbraucht. Grapple-Loesung auf `no_actions` umgestellt:
  der SRD-Satz "the grappler is incapacitated" trifft jetzt genau die
  Condition, nicht eine Naherungs-Flag.
- **Grund:** Eine Zustandstabelle, die einem Eltern-Zustand Kind-Effects
  anhaengt, erzeugt stille Regel-Falschaendungen an jedem Konsumenten. Ein
  Wort pro Satz der Regelquelle haelt die Zuordnung pruefbar.
- **Konsequenzen:** Kanon: **1022 passed, 0 skipped** (4 neue Tests in
  `tests/test_d134_incapacitated.py`: Hook-Tabelle als executable Norm,
  Angriff+Dash blockiert, Bewegung frei, nach cond_remove wieder frei,
  Wirken blockiert OHNE Slot-Verbrauch, Flucht braucht eine Aktion).
  Bestehende Familien-Erwartungen (D110/D113) unveraendert gruen.

## D135 - Heroic Inspiration ist ein verbrauchbares Marker (2026-10-17, AP-021)

- **Status:** umgesetzt.
- **Kontext:** F6: Inspiration war ein An/Aus-Schalter ohne jeden Konsumenten.
  SRD 5.2.1: man hat HÖCHSTENS EINE Held-Inspiration; sie wird beim Wurf
  (Angriffs-, Attributs-, Rettungswurf) VERBRAUCHT; wer bei voller Zahl
  weitere bekäme, gibt sie weiter oder verliert sie kampflos.
- **Entscheidung:** `adv:"insp"` auf den Charakter-d20-Pfaden (Angriff,
  Check, Save, Skill) — `_spend_insp` verbraucht das Marker VOR dem Wurf und
  faltet in die vorhandene Advantage-Ableitung (SRD "wähle einen Würfel" =
  keep-higher als dokumentierte Vereinfachung, Klasse wie der frightened-
  Pauschalhook). Blind-Ausdrücke und NPC-Würfe tragen das Marker nicht
  (frühe Ablehnung, kein Marker-Diebstahl). Die `gain`-Aktion: Pool bei
  voll -> `pass_to_char` (Charakter mit Token in DIESEM Raum) schiebt das
  Marker; ohne Weitergabe: nichts gewonnen, nichts verloren.
- **Grund:** Ein Statusfeld ohne Konsumenten ist ein UI-Ornament. Der
  Verbrauch wird zum Engine-Ereignis, weil nur dort die Regel (max 1,
  Verbrauch beim Wurf, Weitergabe bei voll) erzwingbar ist.
- **Konsequenzen:** Kanon: **1029 passed, 0 skipped** (7 Tests: Verbrauch am
  Check inkl. sys-Beleg, Verbrauch am Angriff ohne Flag-Fehler, Blind/NPC-
  Ablehnung, Voll-Verlust ohne Weitergabe, Weitergabe, Fremd-Raum-Ablehnung).
  Marker bleibt Boolean (Pool >1 = Klassengrenze, dokumentiert).

## D136 - Help-to-Stabilize ist ein Check, kein Automatismus (2026-10-17, AP-022)

- **Status:** umgesetzt.
- **Kontext:** F8: Sterbende zu stabilisieren war engine-seitig gar nicht
  modelliert; 2024 verlangt dafür die Help-Aktion mit einem DC-10-
  Wisdom-(Medicine)-Check (2014 schaffte das automatisch). Tod-Rettet sind
  schon D101-Spezialität (death.py) — nur der Helfer-Pfad fehlte.
- **Entscheidung:** Neue WS-Nachricht `stabilize` (token_id = Helfer,
  target_token_id = Patient): Patient muss sterbend (nicht stable/tot) sein;
  Selbst-Stabilize abgelehnt; Adjazenz über das vorhandene
  `grapple._adjacent` (5 ft, Footprint/Ebenen-korrekt); im Kampf dreht der
  Helfer die Initiative-Liste -> eigener Turn + Action verbrauchen
  (`set_init` persistiert, D8-Muster), D134 no_actions-Gate; Würfel durch die
  vorhandene Skills-Ableitung (`skill_bonus medicine`, wis); natural 20
  heilt auf 1 HP (death-Block weg, wie nat-20 der Tod-Rette), total ≥ 10
  setzt stable, Fehler bewegen KEINEN Tod-Rette-Zähler. Außerhalb des
  Kampfes: erlaubt, ohne Action-Verbrauch (dokumentierte v1-Grenze).
- **Grund:** Der Sterbepfad war der einzige Kampf-Kernmechanismus ohne
  Helfer-Interaktion. Alles Neue läuft über bestehende kanonische
  Ableitungen (Adjazenz, Skills, Action-Ökonomie, Condition-Hooks).
- **Konsequenzen:** Kanon: **1033 passed, 0 skipped** (4 Tests: Würfel-Text
  ⇔ stable-Zustand über zufälligen Wurf robust, Selbst-/Patient-Guards,
  Distanz/Turn/Action-Verbrauch, stunned blockiert). get_init ist ein
  FRISCHER DB-Read — Mutationen brauchen set_init (Fallstrick geheftet).

## D137 - Deckung reitet jeden Angriffs­wurf, auch den der Zauber (2026-10-17, AP-023)

- **Status:** umgesetzt.
- **Kontext:** A5 prüfte die Cover-Werte (half +2, 3/4 +5, total = nicht
  anvisierbar) — die waren inkl. 3/4-Auswahl in Backend und Client längst
  da; die Lücke war eine andere: die Deckung fehlte auf den ZAUBER-
  Angriffs­würfen (PC-Manual-Roll, PC-Cast, NPC-Roll, NPC-Cast), während
  Waffenwürfe sie trugen. SRD-seitig ist Deckung eine Eigenschaft des
  Ziels, nicht des Angriffs­werkzeugs.
- **Entscheidung:** `_spell_cover(msg)` + `_total_cover_note` als gemeinsamer
  Pfad; `_spell_attack_text` bekommt den cover-Parameter (Text `vs 3/4
  cover`, `-5 cover`, totaler Abzug auf die Summe). Total Cover LEHNT das
  Ziel ab, BEVOR in handle_cast/_npc_cast ein Slot, Marker oder eine Action
  angefasst wird (order same as D131: validate first, spend after).
- **Grund:** Ein Regelwert, der nur auf einer von zwei Angriffs­pfaden
  wirkt, ist eine stille Hausregel. Eine gemeinsame Deckungs­funktion pro
  Würfel­gattung hält die Pfade deckungsgleich.
- **Konsequenzen:** Kanon: **1037 passed, 0 skipped** (4 Tests: 3/4 und half
  auf Spell-Attack-Rolls, Total-Verweigerung OHNE Slot-Verbrauch, Cast mit
  3/4, Plain-Text unverändert). Audit A5 damit vollständig abgearbeitet.

## D138 - Vorbereitung ist Daten, kein Klassencode (2026-10-17, AP-024/025)

- **Status:** umgesetzt (+ Audit-Verifikation F2/E2).
- **Kontext:** C3 wollte den Prepare-Ablauf "je Klasse". Klassennamen im
  Engine-Kern wären der zweite Motor im Haus. Beim Prüfen der R-P2-Liste
  erwiesen sich zwei Posten als bereits erledigt: F2 (HD-Pool = Level,
  `hit_dice_max` 1-20, KEIN Halb-Level-Cap — SRD 5.2.1 ohne Obergrenze ✓)
  und E2 (2024 kennt keinen Nebenhand-Bonusangriff; die Light-Regel lebt als
  Nick-Mastery, D109, vollständig gating-getestet ✓).
- **Entscheidung:** Prepare-Gate datengetrieben wie casting_time (D131):
  `clean_spells` trägt `prep`/`prepared`; enthält die Liste EINEN Eintrag
  mit prep=true, ist die Liste gated; Zauber ab Grad 1 brauchen prepared,
  Kantrips sind ausgenommen; die Ablehnung geschieht vor jedem Slot-/
  Action-/Marker-Verbrauch. CSV projiziert beide Felder (charbuild).
  Long-Rest und Prepare-Wechsel bleiben Spieler-/DM-Flow über den
  bestehenden Spell-Listen-Kanal — die Engine erzwingt nur die Konsequenz.
- **Grund:** "Regel je Klasse" ist Inhalt; "wer vorbereitet sein muss, kann
  Unvorbereitetes nicht wirken" ist Mechanik. Nur die Mechanik gehört in die
  Engine — dieselbe Trennung, die schon D131 trug.
- **Konsequenzen:** Kanon: **1040 passed, 0 skipped** (3 Tests: Gated-Liste
  verweigert ohne Verbrauch, Prepared wirkt, Kantrip-Ausnahme + ungated
  frei). Audit: C3 ✓, F2 ✓ verifiziert, E2 ✓ (Nick), R-P1/R-P2-Listen
  bereinigt.

## D139 - Species-Origin-Feat erreicht die Auswahl-Logik (2026-10-17, AP-026)

- **Status:** umgesetzt (+ B6-Verifikation).
- **Kontext:** B5 forderte den Origin-Feat-Ablauf (D108, erledigt) und
  Species-Bonus-Feats; SRD 5.2.1 kennt artenbezogene Origin-Feats, aber
  species.csv hatte weder Feld noch Konsumenten. B6 („Requires-Freitext")
  war bei Prüfung bereits erledigt: `_parse_feat_requires` parst
  Attributs-/Skill-/Feat-Bedingungen maschinell fail-closed, das Pack trägt
  kein „ranks" mehr.
- **Entscheidung:** Schema-Feld `origin_feat` (id) für species; Projektion
  gibt es weiter; die Feat-Auswahl konsumentiert es doppelt: (a)
  Prerequisite-Ketten zählen es als angewandt, (b) die gleiche Feat kann
  nicht noch einmal gewählt werden — `taken`-Set + „already chosen". (b)
  schließt gleich die generische SRD-Regel „no feat twice" für den ganzen
  Level-Up-Flow, nicht nur für Species.
- **Grund:** Ein Datenfeld ohne Konsumenten ist Dekoration (D135-Lektion).
  Der Konsument wurde an die bestehende options-Ableitung gehängt statt
  einen zweiten Wahl-Kanal zu bauen.
- **Konsequenzen:** Kanon: **1043 passed, 0 skipped** (3 Tests: Projektion
  liefert/leert origin_feat, Species-Feat zählt als genommen + stillt
  Prerequisite-Kette, Ledger-Duplikat blockiert). Nebenbefund geheftet:
  SCHEMAS ist auch Generator-Input — Schema-Zeilen ändern schreibt den
  content_pack-CSV neu (D109-Idempotenztest fängt das korrekt); der
  mit-generierte species.csv ist jetzt Stand des Schutzes.

## D140 - Schwimmen/Klettern ohne Speed: der SRD preist es an, er verbietet es nicht (2026-10-17, AP-027)

- **Status:** umgesetzt.
- **Kontext:** D83 erlaubte Bewegungsmodi strikt nur MIT zugehörigem Speed
  („no silent substitution") — für Schwimmen/Klettern ist das strenger als
  SRD 5.2.1: Ohne Schwimm-/Kletterspeed ist beides möglich, jeder Fuß
  kostet 1 Extra-Fuß (2 in schwierigem Gelände). Nur Fliegen ohne Speed
  ist tatsächlich unmöglich.
- **Entscheidung:** `_mode_or_error` verlangt einen Speed nur noch für
  fly; swim/climb durchnach immer, mit dem Aufschlag als EINER Regel in
  `movecost.route_cost`: `unit + (2 if difficult else 1)` — wörtliche SRD-
  Addition, keine Multiplikation (schwierig+schwimmen = 3, nicht 4).
  Diagonal-Alternierung bleibt Basis; der Aufschlag kommt pro Schritt
  obendrauf. Client: Modus-Picker zeigt swim/climb immer, fly nur mit
  Speed. Budget bleibt walk_budget (D83-Konversion unverändert).
- **Grund:** Die D83-Weigerung war ein Platzhalter („no fake terrain rules
  yet"). Die Regelquelle liefert eine Zahl, keinen Verbotsatz — also Zahl.
- **Konsequenzen:** Kanon: **1045 passed, 0 skipped** (2 Tests:
  Kosten-Tabelle als ausführbare Norm inkl. Diagonal-Mix, WS: fly verweigert
  / swim bewegt). terrain.py/movement_modes-Suiten unverändert grün.
  Wasser-/Kletterwände als Terrainklassen bleiben Content (AP-031-Kandidat).

## D142 - Nebel-Gedächtnis überlebt den Prozess (2026-10-17, AP-028)

- **Status:** umgesetzt.
- **Kontext:** TODO P2 „Ghost persistence": D9's _last_seen war reiner
  Speicher — ein Server-Neustart fraß alle Nebel-Ghosts (und Multi-Worker
  wäre ohnehin falsch). Gezielt wurde NIE pro Step geschrieben.
- **Entscheidung:** additiv room_state.ghosts_json (ein Blob pro Raum:
  {user_id: {token_id: snapshot}}). Schreibzeitpunkt = disconnect des
  letzten Sockets des Viewers (prune_viewer_last_seen schreibt VOR dem
  Pop; leere Geister schreiben nichts). Lesezeitpunkt = erster gesehener
  Frame des Viewers im Raum (visibility-Hydrate) und Raum-Beitritt
  (rooms-Snapshotpfad). JSON-Keys werden beim Hydratieren wieder zu int —
  die token_id-Nachschlage bleibt int. Kein Write pro Step, ein Write pro
  Abmeldung.
- **Grund:** Persistenzkosten gehören an die Lebensereignisse des Gedächt-
  nisses (anmelden/abmelden), nicht an den Heißpfad.
- **Konsequenzen:** Kanon: **1047 passed, 0 skipped** (2 Tests: Schritt ->
  Ghost im Speicher -> Disconnect schreibt DB -> Speicher leer -> Hydrat
  liefert int-keys zurück; Geisterleere schreibt nichts). Alle Nebel-Suiten
  unverändert grün. Multi-Worker bleibt bewusste Grenze (ein Prozess, wie
  zuvor; die Grundlage ist jetzt gelegt).

## D143 - Ein Einstiegspunkt für die Checks: Makefile, Live-Smoke, Lockfile (2026-10-17, AP-029)

- **Status:** umgesetzt.
- **Kontext:** TODO P1 wollte drei Dinge, die bisher nur in Köpfen und
  Logs lebten: einen reproduzierbaren Python-Stand, einen lebenden
  Server-Smoke vor „macht Sinn"-Deploys und einen einzigen Einstiegspunkt
  für die Checks, die der Marathon sowas jedes Mal manuell ausführt.
- **Entscheidung:** requirements.lock = komplettes transitive Freeze des
  kanonischen Docker-Test-Images (nur `==`-Zeilen, sortiert; Regeneration
  per `make lock`). scripts/smoke.sh startet uvicorn auf Loopback mit
  eigenem VTT_DATA_DIR und Port per SMOKE_PORT, beweist health -> register
  -> Raum per HTTP und stoppt per pidfile-trap; kein Docker, kein
  geteilter Zustand. Makefile kapselt test/compile/check/smoke/lock.
- **Grund:** Check-Routinen, die nur als lange bash-Zeilen existieren,
  altern still. Ein Skript mit Exit-Code ist ein Test; ein Freeze mit
  Regenerations-Kommando ist wartbar.
- **Konsequenzen:** App-Code unverändert (Kanon bleibt 1047). Die
  .mjs-Smoke-Suite aus dem TODO-Original existiert nicht und wurde nicht
  erfunden — der HTTP-Smoke ist die ehrliche Form davon.

## D144 — Swim/Climb-Aufschlag nur OHNE Speed (AP-030)
- **Status:** umgesetzt.
- **Kontext:** D140 machte swim/climb für alle Creaturen bewegungs-erlaubt
  und belegte jedes Feld mit dem SRD-Aufschlag (+1/ Feld, +2 schwierig).
  Das war zu scharf: Wer eine swim-/climb-Geschwindigkeit besitzt, schwimmt
  und klettert nach SRD ohne Kostenzuschlag. D83 durfte nicht bedeuten,
  bestatte Wesen mit Fischgeschwindigkeit zu bestrafen.
- **Entscheidung:** Der Aufschlag folgt dem Speed, nie der terrain-Zelle.
  movecost.route_cost und path.path_footprint_cost erhalten ein durchgängiges
  strained-Flag (unit + Aufschlag statt unit * Multiplikator), das die
  creature-kundige Schicht setzt: movement._strained(tok, mode) prüft die
  Speed-Tabelle, walk()/walk3d()/Preview tragen es durch. combat.move_remaining
  führt fehlende swim/climb-Pool-Einträge auf den walk-Pool zurück, damit das
  Ledger dieselbe Einheit wie movecost spricht. fly bleibt Speed-Pflicht
  (D140), swim/climb bleiben immer erlaubt.
- **Grund:** Die Grid-Module bleiben creature-blind (eine Lookup-Stelle),
  die Mechanik folgt exakt der SRD-Regel „speed vorhanden = kein Aufschlag",
  und die Wirtschaft (Budget) bleibt in einer Währung.
- **Konsequenzen:** Kanon 1050 (5 Tests in test_d140_swim_climb.py: Unit-
  strained, zwei Ledger-Unit-Tests, Surcharge-Erwartungen auf strained=True
  umgestellt). Der alte WS-Kampf-Budgettest wurde durch deterministische
  Unit-Tests ersetzt — er hing bei entferntem End-Event in receive_json.
  Lernkurve dokumentiert: compose-Aufrufe IMMER mit --build (ein vergessenes
  --build ließ zweimal alten Image-Code laufen und produzierte Scheinhänger).

## D145 — Species-Ability-Boni mechanisch (AP-031)
- **Status:** umgesetzt.
- **Kontext:** Die species.csv führt seit jeher die Spalte ability_bonuses
  (z. B. dex+2), aber kein Konsument hat sie je angelegt — die D101-Follow-up-Zeile
  „not mechanically applied" war die letzte offene Mechanik-Lücke im geführten
  Charakterfluss.
- **Entscheidung:** Grant nach D108-Muster: Report-Endpoint (Vorschau der
  Zielwerte) und Apply-Endpoint je Charakter, EXACTLY-ONCE innerhalb eines
  db.tx(), Zahlen ausschließlich aus dem Raum-Content. Der Bonus ist ein
  Ledger-Eintrag (build.species_bonus), den _replay_species am ANFANG der
  Chronologie einspielt (2024: Species vor Origin, Klasse, ASI) — in
  _recompute ebenso wie im unbuilt-Zweig von apply_origin, damit kein
  späterer Bauschritt ihn je still verlieren kann. Bestehende Blätter werden
  nie automatisch migriert; hp/AC/Slots/Ressources bleiben unberührt.
- **Grund:** Ein Direktschreib-Knopf wäre beim nächsten Full-Recompute vom
  base_stats-Snapshot verschluckt worden. Die Ledger-Replik ist dieselbe
  Idempotenz-Maschine, die D108 für Origin bewiesen hat — zwei Grants in
  beliebiger Reihenfolge kommutieren nachweislich.
- **Konsequenzen:** Kanon 1055 (5 neue Tests inkl. Kompositionstest Origin
  +Species in beiden Reihenfolgen). _species_projection zeigt die Boni jetzt
  read-only. Die UI-Knöpfe im geführten Fluss sind Folgearbeit (API ist
  vollständig); TODO-D101-Followup entsprechend nachgezogen.

## D146 — Trank/Rollage wird verbraucht (AP-032)
- **Status:** umgesetzt.
- **Kontext:** Consumables hinterließen als „leere Hülle" im Inventar (nur der
  charges-Zähler ging auf 0). SRD: ein Trank ist nach dem Trinken WEG. Die
  TODO-Zeile „potions aren't deleted" war der letzte echte Regel-Overpass der
  Inventar-Mechanik.
- **Entscheidung:** _consume(it, items) in handle_use_item, innerhalb derselben
  Schreibtransaktion wie die Heilung (nie Heilung ohne Verbrauch, nie
  Verbrauch ohne Heilung; der op_id-Replay-Guard D93 bleibt der Türsteher).
  Regel: kind potion/scroll UND charges==0 -> wenn qty>1: eine Dosis weniger
  und die aktuelle ist frisch (charges zurück auf chargesMax); sonst fällt der
  Eintrag aus der Liste. Ein Fluch-Eintrag bleibt IMMER (D106/D113: eine
  Flurspur darf nicht verschwinden). Alles andere (Wandern, Ringe, …) behält
  die bekannte depleted-Schale — aufladbare Items werden nicht weggeworfen.
- **Grund:** Eine Regel, vier Hüllen-Workarounds (Client-Greyout, DM-Mülleimer,
  Test-Erwartungen) sind vier Erklärungen. Die Inventarliste ist ab jetzt
  wieder die Wahrheit: was drin steht, existiert.
- **Konsequenzen:** Zwei alte Tests beweisen die neue Semantik und wurden auf
  die stärkere Assertion gezogen (test_integration: items == []; sprint23: der
  Replay eines verbrauchten Tranks antwortet ehrlich 'Item not found' statt
  stumm). Kanon 1060 (5 neue Tests in test_d146_potion_consumed.py inkl.
  qty-Stack, curse-Guard und Replay-Nachweis per Marker-Chat).

## D147 — Attunement identifiziert (statt zu gate-en) (AP-033)
- **Status:** umgesetzt.
- **Kontext:** Die TODO-Zeile wollte „warn/gate attuning to an unidentified
  magic item". Die Regel-Faktenlage (DMG wie SRD): das Attunement IST eine
  kurze Rast mit dem Objekt, und die Regel sagt ausdrücklich, dass die
  Creature beim Attunement die Eigenschaften des Objekts ERFÄHRT. Ein Gate
  wäre eine Hausregel gegen die Regel.
- **Entscheidung:** handle_attune flippt beim ATTUNE-ON für magische,
  unidentifizierte Objekte zusätzlich identified und flüstert den Fund dem
  Besitzer (desc-Zelle oder Hinweis ohne Text). refuse (Cap 3) und Toggle-off
  verraten nichts; der DM-identify-Pfad bleibt unberührt. Die Vereinfachung
  (Erkundung am Ende des Attune-Handlers, nicht an einer eigenen Short-Rest-
  Uhr) ist explizit dokumentiert, weil die Engine Attunement ohnehin
  augenblicklich modelliert.
- **Grund:** Ein Warn-Gate hätte eine echte SRD-Erfahrung bestraft, die der
  Spieler gerade durchführt. Die Identifikation ist die Belohnung des
  Attunements selbst — jetzt ist sie auch die Implementierung.
- **Konsequenzen:** Kanon 1063 (3 Tests in test_d147_attune_identify.py).
  TODO-Zeile auf „resolved by rule, not by gate" gezogen. Für den Spieler
  unbekannte Objekte bleiben unbekannte Objekte, bis er sie benutzt, einer
  Rast widmet oder ein Attunement eingeht.

## D148 — Multi-Socket-Geisterbeweis (AP-034)
- **Status:** umgesetzt (Test-Evidence, kein App-Code).
- **Kontext:** TODO P2 wollte „seed ghosts more robustly; multi-socket-per-user
  testing". Die Prune-/Persist-/Hydrate-Maschinerie war bereits socket-richtig
  gebaut (prune nur bei `if not socks`) — es fehlte der Beweis, und ein
  Reconnect-Test fand ihn ohne neuen Code.
- **Entscheidung:** Zwei Tests in test_d148_multisocket_ghosts.py: (1) schließt
  einen von zwei Tabs eines Users — Geister bleiben in RAM, nichts wird
  persistiert, keine offline-Presence; (2) nach dem echten letzten Socket
  schreibt die DB, und der nächste State-View des Users zeigt die verblichenen
  Tokens wieder (hydrate über denselben Weg wie nach einem echten Neustart).
- **Grund:** „bereits richtig" ohne Test ist ein Gerücht. Die D142-Schichten
  (RAM, ghosts_json, State-Hydrate) werden hier genau an der Naht geprüft,
  die ein Browser-Tab-Wechsel schlägt.
- **Konsequenzen:** Kanon 1065. Erkenntnis fürs Testen: Nebel-Geister brauchen
  ein Token, das UNSICHTBAR endet — ein Pfad durch die Wand existiert nicht,
  der DM muss teleportieren; und /state hydratisiert, prune aber auch wieder,
  wenn der Beweis-Socket vorher schließt. TODO-P2-Zeile damit belegt.
