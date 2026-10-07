# AGENT_GUIDE.md — DnDTable repository map

> This is a navigation map, not a source of truth.
> Use it to locate relevant files, then inspect the actual implementation.
> If this guide and the code disagree, the CODE wins.
> Update this file when an architectural change is made.

---

# 1. Architecture overview

DnDTable is a self-hosted multiplayer virtual tabletop.

## Backend

- **FastAPI** app: `app/main.py`
  - REST API mounted from `app/rooms.py` under `/api`.
  - WebSocket router mounted from `app/ws.py`.
- **WebSockets**:
  - One connection per user per room: `/ws/{code}`.
  - Room clients are tracked in `app/room/net.py::_clients`.
  - Messages are dispatched through `app/room/dispatch.py::HANDLERS`.
- **SQLite persistence**:
  - `app/db.py` defines schema and additive migrations.
  - Thread-local SQLite connections use WAL mode and `busy_timeout`.
  - Multi-statement writes use `db.tx()`.
- **Server-authoritative gameplay philosophy**:
  - Dice, HP, damage, saves, movement validation, traps, hidden information,
    visibility filtering, room membership, character ownership, and audio-source
    safety are decided by the server.
  - The frontend is mostly a renderer and input surface.

## Frontend

- No framework, no build step, no bundler.
- Classic scripts are loaded in dependency order:
  1. `app/static/js/10_core.js` — global state and shared helpers.
  2. `app/static/js/20_lobby.js` — auth/lobby/character editor.
  3. `app/static/js/30_room.js` — room rendering and most UI state.
  4. `app/static/js/40_ws.js` — WebSocket connection and event dispatch.
  5. `app/static/js/50_canvas.js` — canvas map, tokens, fog, pins, movement.
  6. `app/static/js/55_diorama.js` — client-local isometric diorama renderer.
  7. `app/static/js/60_main.js` — DOM wiring and boot.
- Single mutable global `state` object in `10_core.js`.
- DOM rendering is imperative `innerHTML`/`createElement` code.
- Sidebar panels are grouped behind client-local tabs (Game/Chars/Story/DM,
  `#side-tabs`, `applySideTab()` in `30_room.js`, choice persisted per user in
  localStorage); Chronicle (chat+dice) and context sheets stay always visible.
  A `?` help overlay (`#help-overlay`) is opened/closed from `#btn-help`, `?`
  and `Esc` — content-only, no framework.

---

# 2. Repository map

| File / module | Purpose | Important entry points |
|---|---|---|
| `app/main.py` | FastAPI app, startup, static mounts | `app`, `startup()` |
| `app/rooms.py` | REST API, role-filtered room state | `/api/*`, `room_state()`; uploads write to `<VTT_DATA_DIR>/uploads` (D62) |
| `app/ws.py` | WebSocket auth/lifecycle | `ws_room()` |
| `app/auth.py` | bcrypt passwords, signed cookie sessions, room access | `read_token()`, `current_user()`, `require_user()`, `room_of()`; tokens are padding-free base64url (cookie-safe, D62) |
| `app/db.py` | SQLite schema and migrations | `init_db()`, `q()`, `q1()`, `x()`, `tx()` |
| `app/gear.py` | Shared sheet/item/skill/spell/defense math | `compute_ac()`, `save_bonus()`, `skill_bonus()`, `apply_defense()` |
| `app/npc.py` | NPC stat-block model | `clean_npc()`, `load()`, `to_char()` |
| `app/conditions.py` | Conditions catalog and logic | `clean_conds()`, `add()`, `remove()`, `step_rounds()` |
| `app/path.py` | Footprint-aware server A* | `find_path()`, `path_footprint_cost()` |
| `app/footprint.py` | Token size and collision footprint | `FOOTPRINT`, `occupied_origin()`, `valid_final_position()`, `find_valid_origin()` |
| `app/los.py` | Wall/door line of sight | `line_of_sight()`, `visible_cells()` |
| `app/mapmodel.py` | Map schema, fog, doors, traps, loot, pins | `sanitize()`, `visible_map()`, `blocked_edges()`, `reveal_cells()` |
| `app/quests.py` | Quest Log game operations (persistent, filtered) | `create_quest()`, `set_objective()`, `complete_quest()`, `visible_for()` |
| `app/progression.py` | Multiclass-ready class model | `clean_class_levels()`, `total_character_level()`, `set_class_levels()` |
| `app/events.py` | Plain-dict game-event facts + listener seam (D52) | `make()`, `emit()`, `subscribe()`, `recent` |
| `app/effects.py` | Generic ability/effect geometry (D54) | `effect_cells()` |
| `app/abilities.py` | Generic ability engine: data defs + authoritative executor (D55) | `register()`, `clean_definition()`, `execute()` |
| `app/room/quests.py` | Quest WS transport (thin) | `handle_quest_add/complete/…` |
| `app/room/progression.py` | `class_levels` WS transport (thin) | `handle_class_levels()` |
| `app/ratelimit.py` | In-memory request limiter | `limit()` |
| `app/room/dispatch.py` | WebSocket message registry | `HANDLERS`, `handle()` |
| `app/room/net.py` | Broadcast/map helpers | `broadcast()`, `send_user()`, `sys_msg()`, `get_map()`, `set_map()`, `attach_ws()`/`detach_ws()` (socket→loop registry, D61) |
| `app/room/chat.py` | Chat, personas, whispers, narrative delivery | `handle_chat()`, `handle_narrative()` |
| `app/room/audio.py` | Safe audio URL parsing and room ambience state | `parse_audio_source()`, `load_state()`, `handle_audio_*()` |
| `app/room/secret_events.py` | Composes private narrative + optional sound | `handle_secret_event()` |
| `app/room/gamelog.py` | Game-log dice/system delivery and visibility | `post_message()`, `filter_messages_for_viewer()` |
| `app/room/health.py` | Central HP/temp/typed-damage/death reducer | `change_hp()`, `heal()`, `damage()` |
| `app/room/dice.py` | Server dice parser/roller, rolls, saves, attacks, rests | `do_roll()`, `parse_roll()`, `handle_roll()`, `handle_cast()` |
| `app/room/combat.py` | Initiative and HP handlers | `handle_init_start()`, `handle_init_next()`, `handle_hp()` |
| `app/room/movement.py` | Walks, stop, trap auto-stop, path previews | `handle_move()`, `handle_stop_move()`, `handle_path_preview()`, `walk()` |
| `app/room/fog.py` | DM manual exploration edits + room-wide fog on/off | `handle_fog_edit()`, `handle_fog_toggle()` |
| `app/room/tokens.py` | Token add/remove/NPC edits | `handle_add_token()`, `handle_update_npc()` |
| `app/room/items.py` | Item use/attune/identify/recharge | `handle_use_item()`, `handle_attune()` |
| `app/room/traps.py` | Trap and loot resolution | `hit_trap()`, `take_loot()` |
| `app/room/doors.py` | Door permissions incl. dm_only/secret (D63) | `handle_door()` |
| `app/room/visibility.py` | Footprint LOS token delivery and ghosts | `viewer_visible_cells()`, `send_token_event()`, `broadcast_token_add()` |
| `app/static/js/10_core.js` | Global `state`, API helper, toast | `state`, `api()`, `esc()`, `toast()` |
| `app/static/js/30_room.js` | Room state, chat, sheet, journal, party rendering | `openRoom()`, `refreshRoom()`, `renderFeed()` |
| `app/static/js/40_ws.js` | WebSocket event dispatch | `connectWS()`, `wsSend()` |
| `app/static/js/50_canvas.js` | Map/canvas rendering and overlays; view dispatcher | `draw()`, `drawTactical()`, `tick()`, `showAoe()`, `showPing()` |
| `app/static/js/55_diorama.js` | Isometric diorama renderer + click routing | `drawDiorama()`, `dioProj()`, `dioramaDown()` |
| `app/static/js/60_main.js` | Wire DOM events | `wire()`, boot function |
| `tests/test_integration.py` | REST/WS integration suite | auth, visibility, rest, map, combat, items |

---

# 3. Feature → files map

## Authentication / rooms / lifecycle

- Server:
  - `app/auth.py`
  - `app/rooms.py`
  - `app/ws.py`
  - `app/db.py`
  - Room deletion (D76): `DELETE /api/rooms/{code}` — creator-DM only (role `dm`
    AND `rooms.dm_id`), cascades tokens/messages/room_state/notes/quests/
    room_members/rooms, removes the room's own `map_image` upload only, then
    `net.purge_room_nowait()` announces `room_deleted`, closes every socket on
    its owning loop, cancels walks via `Task.get_loop()` and forgets
    `_clients/_map_locks/_last_seen`. `ws.py` teardown checks the room row first
    (deleted room → skip bookkeeping, else FK fails and zombies return).
- Client:
  - `app/static/js/20_lobby.js` — DM-only two-step Delete (arm + confirm)
  - `app/static/js/30_room.js`
  - `app/static/js/40_ws.js` — `room_deleted` case: leave to lobby, never
    reconnect (reconnect is also guarded by `state.roomDeleted`)
  - `app/static/js/60_main.js` — `btn-back` is the permanent "← Lobby" escape
    (works in Tactical AND Diorama; kills reconnect + ws)
- Tests:
  - `tests/test_integration.py`
  - `tests/test_room_delete.py` — authorization matrix, cascade, idempotency,
    `room_deleted` + registry purge

## Characters / ownership

- Server:
  - `app/rooms.py` REST CRUD and room assignment.
  - `app/gear.py` sheet math.
- Client:
  - `app/static/js/20_lobby.js`
  - `app/static/js/30_room.js`
- Tests:
  - `tests/test_gear.py`
  - `tests/test_integration.py`

## Tokens / NPCs / bestiary

- Server:
  - `app/room/tokens.py`
  - `app/npc.py` — clean_npc normalises movement modes via `gear.clean_speeds`
    (walk/fly/swim/climb persisted as blob fields + `speeds` dict); authoring UI
    in the NPC editor. `to_hit`/`dmg` stay complete author bonuses (no engine
    double-add, D66).
  - `app/rooms.py` creature CRUD
- Token row: `z` column = elevation units of the ground cell the token rests on
  (walk/teleport/forced-move sync it; D70).
- Client:
  - `app/static/js/30_room.js`
  - `app/static/js/50_canvas.js`
- Tests:
  - `tests/test_npc.py`
  - `tests/test_integration.py`

## Movement / footprints / pathfinding / doors

- Server:
  - `app/room/movement.py` — walk task, stop move, trap auto-stop and path previews;
    preview surfaces `cost`/`speed_ft`/`budget`/`within_budget`; walk end (reason None)
    and player teleports are the ONLY automatic-growth triggers (D67).
  - `app/room/moveforced.py` — DM-only forced movement (push/pull/shove/knockback/
    throw/teleport): stops at first illegal cell, syncs z, never a walk, no budget,
    never world growth (D71). Not in `_walks`.
  - `app/room/growth.py` + `mapmodel.grow_map` — automatic chunk growth (12) for
    player-owned tokens within 11 cells of an edge, cap 80×60; broadcasts `map_expanded`.
    **Feature-flagged OFF by default (D77)**: `mapmodel.AUTO_GROW` =
    `DNDTABLE_AUTO_GROW=1` env; `maybe_grow_map` returns immediately when off.
    The machinery stays fully implemented and tested (`test_map_expand.py`
    enables the flag explicitly); DM map-editor resize is the manual path.
  - `app/movecost.py` — cost SSOT (5e diagonals 1,2,1,2; difficult ×2; budget = speed//5).
    A* weights in `path.py` stay 10/14 — cost is a route post-processing, not search.
  - `app/path.py` — footprint-aware A*; optional `elev=` gates steps at |Δz| ≤ 1 (D70).
  - `app/footprint.py` — size/anchor/collision SSOT.
    **Footprint invariant (D43+D81):** token `(x, y)` is the canonical anchor
    (centre of its top-left occupied cell); `footprint_width`/`footprint_height`
    (`tokens.fw`/`tokens.fh`, NULL = square of the size category) define the
    occupied rectangle. EVERY gameplay system — movement, collision, path
    preview/execution, growth, LOS/vision source cells, snapshot visibility,
    ability/AoE intersection, client render and hit test — derives its cells
    from the shared helper (`token_span` → `occupied_cells`/`origin_cells`);
    never compute a footprint rectangle from size anywhere else. Old square
    tokens load unchanged; a size-category change resets the custom span.
  - `app/mapmodel.py`
  - `app/room/doors.py` — open/close/lock plus door-open LOS reveal; `dm_only`
    doors answer players with "It won't budge." (checked before lock state),
    `secret` doors are never transmitted to players (silent refusal like a
    nonexistent edge) and their moves stay out of the chronicle (D63).
- Client:
  - `app/static/js/50_canvas.js` — requests `path_preview`, renders footprint center, server path cells,
    active-walk ring and DM stop control; HUD shows `cost/budget squares`;
    `map_expanded` NEVER moves the camera (D72: world coordinates do not move;
    in Diorama the known-world fit is re-applied after the state refresh).
- Tests:
  - `tests/test_path.py`
  - `tests/test_footprint_path.py`
  - `tests/test_mapmodel.py`
  - `tests/test_movement_fog.py`
  - `tests/test_integration.py`
  - `tests/test_movecost.py`, `tests/test_map_expand.py`, `tests/test_terrain.py`,
    `tests/test_elevation.py`, `tests/test_forced_move.py`

## Vision / fog / manual DM reveal

- Server:
  - `app/los.py` — conservative integer DDA wall/door LOS.
  - `app/room/visibility.py` — per-viewer token filtering and ghost retention.
  - `app/room/fog.py` — DM-only batch `explored` reveal/hide.
  - `app/mapmodel.py`
  - `app/room/movement.py`
  - `app/room/doors.py`
- Client:
  - `app/static/js/50_canvas.js` — renders server-known cells and fog brushes.
  - `app/static/js/40_ws.js` — handles `fog_changed`.
  - `app/static/js/60_main.js` — fog brush UI wiring.
- Tests:
  - `tests/test_los.py`
  - `tests/test_movement_fog.py`
  - `tests/test_mapmodel.py`
  - `tests/test_integration.py`

## Map / traps / loot / pins

- Server:
  - `app/mapmodel.py` — cell vocabulary via **TERRAIN registry** (D69): 0 floor,
    1 wall, 2 difficult, 3 barrier (move✗/vision✓, climbable), 4 low_obstacle
    (move✓ ×2 cost, climbable); `elev` integer layer -6..6 (D70, missing = flat,
    fog-gated in `visible_map`); `grow_map`/`growth_needed` (D67).
  - `app/wall.py` — semantics facade: blocks_movement/blocks_vision/climbable/
    height_units per cell; never re-encode cell values in features.
  - `app/room/movement.py` — triggers traps/loot on walk and stops movement on a trap.
  - `app/room/traps.py`
  - `app/room/net.py`
- Client:
  - `app/static/js/50_canvas.js`
- Tests:
  - `tests/test_mapmodel.py`
  - `tests/test_integration.py`

## Combat / initiative / HP / typed damage

- Server:
  - `app/room/combat.py`
  - `app/room/health.py`
  - `app/gear.py`
- Client:
  - `app/static/js/30_room.js`
- Tests:
  - `tests/test_integration.py`

## Conditions / death saves / status

- Server:
  - `app/conditions.py`
  - `app/room/conditions.py`
  - `app/room/death.py`
  - `app/room/status.py`
- Client:
  - `app/static/js/30_room.js`
  - `app/static/js/50_canvas.js`
- Tests:
  - `tests/test_integration.py`

## Dice / saves / cover / private rolls

- Server:
  - `app/room/dice.py`
  - `app/room/gamelog.py`
  - `app/gear.py`
- Client:
  - `app/static/js/30_room.js`
  - `app/static/js/60_main.js`
- Tests:
  - `tests/test_dice.py`
  - `tests/test_integration.py`

## Rests / resources / temp HP / exhaustion

- Server:
  - `app/room/dice.py`
  - `app/room/status.py`
  - `app/room/health.py`
- Client:
  - `app/static/js/30_room.js`
- Tests:
  - `tests/test_integration.py`

## Encounters / journal / notes

- Server:
  - `app/rooms.py`
  - `app/room/encounters.py`
- Client:
  - `app/static/js/30_room.js`
  - `app/static/js/60_main.js`
- Tests:
  - `tests/test_integration.py`

## Chat / personas / whispers / narrative

- Server:
  - `app/room/chat.py`
  - `app/room/dispatch.py`
  - `app/rooms.py` `/api/rooms/{code}/state`
  - `app/db.py`
- Client:
  - `app/static/js/10_core.js`
  - `app/static/js/30_room.js`
  - `app/static/js/40_ws.js`
  - `app/static/js/60_main.js`
  - `app/static/index.html`
  - `app/static/style.css`
- Tests:
  - `tests/test_chat.py`
  - `tests/test_integration.py`

## Audio / ambience / soundboard / selective audio

- Server:
  - `app/room/audio.py`
  - `app/room/dispatch.py`
  - `app/rooms.py`
  - `app/db.py`
- Client:
  - `app/static/js/10_core.js`
  - `app/static/js/30_room.js`
  - `app/static/js/40_ws.js`
  - `app/static/js/60_main.js`
  - `app/static/index.html`
  - `app/static/style.css`
- Tests:
  - `tests/test_audio.py`
  - `tests/test_integration.py`

## Secret events

- Server:
  - `app/room/secret_events.py`
  - `app/room/chat.py`
  - `app/room/audio.py`
  - `app/room/dispatch.py`
- Client:
  - `app/static/js/60_main.js`
- Tests:
  - `tests/test_chat.py`
  - `tests/test_integration.py`

## Quests / progression / events / effect geometry (Sprint 6)

- Quests:
  - `app/quests.py` (pure ops + `visible_for` filter) → `app/room/quests.py`
    (WS parse→DM-check→op→notice→`quests_changed`) → `rooms.py::room_state()`
    (`"quests"` key) → `30_room.js::renderQuests()` / `wireQuestUI()`.
  - Notices reuse `gamelog.post_message(kind="system")` with visibility bound
    to the quest. Reconstruction is `/state`-only, never notice replay (D51/D52).
- Class progression:
  - `app/progression.py` (`class_levels` JSON on characters; one canonical
    `total_character_level`) → `gear.prof_bonus()` derives from it →
    `app/room/progression.py` (`class_levels` message) → sheet line in
    `30_room.js`.
- Game events:
  - `app/events.py` — facts emitted AFTER state commits; wired today:
    doors, traps (`hit_trap`), quest ops. Future triggers call game
    operations; never fake WS clients (D52).
- Effect geometry:
  - `app/effects.py::effect_cells()` — pure `point|line|cone|circle|square`;
    client parity locked by Node-vm test. Visual relay `room/aoe.py` unchanged.
- Tests:
  - `tests/test_quests.py`, `tests/test_progression.py`, `tests/test_effects.py`

## Ability engine (Sprint 7)

- Flow: `ability_cast` msg → `app/room/abilities.py` (auth: own-token for
  players, any token for DM) → `app/abilities.execute()` (ONE game operation —
  also the call target for future triggers/AI, never needs a ws object):
  registry lookup → availability (PC `abilities` list / NPC block / DM bypass) →
  cost (slot/resource, all-or-nothing) → range (Chebyshev×5ft, 0=touch) →
  LOS if `los_required` → cells via `effects.effect_cells` → tokens via
  footprint intersection → per-target save (`gear.save_bonus` + `do_roll`) or
  attack (`ability_attack_bonus` vs AC) → effects through
  `health.change_hp` / `conditions.add` → chronicle (`system` line, hidden
  tokens counted not named) → `ability_result` (privacy-filtered) + cond/snapshot.
- Canonical derivations (do not re-derive anywhere):
  `gear.stat_mod()`, `gear.ability_save_dc(char, ability, bonus=0)`,
  `gear.ability_attack_bonus(...)`; `spell_save_dc/spell_attack` delegate.
  Casting ability = data on the definition — never hard-coded by class (D57).
- Content: production registry is EMPTY; definitions register via
  `abilities.register(clean dict)` (tests use original names). No spell DB.
- Multiclass caveat (D58): slot progression must NOT be derived from
  `total_character_level()` — separate axis, table attaches later.
- Tests: `tests/test_abilities.py`

## Stability & table UX (Sprint 8)

- **Reject-not-reroute (D60):** `move` carrying a client `path` that fails
  server revalidation → error `route_invalid` ("Route changed — please plan it
  again"), never a silent different route. Pathless moves (DM drags) still
  recompute. Diorama clicks resolve cells in ONE camera space (same math as
  `dioProj`), so both views produce identical previews; armed DM tools
  (ruler/AoE/ping/spawn/door) work in both views via `clickCell` dispatch.
- **Downed gate:** `_movement_block_reason` blocks preview/move/teleport at 0 HP
  and is rechecked per walk step (`stop_reason:"downed"`). NPC tokens at 0 HP
  remain DM-draggable by design.
- **Trap lifecycle:** traps carry `triggered`/`triggered_by` beside
  `discovered`; one-shot re-entry gate is `triggered`; `map_edit` (stale editor
  snapshots included) preserves runtime flags; only re-placing a fresh trap
  re-arms. `handle_map_edit` preserves `explored` row-wise on resize.
- **Fog off:** `fog_toggle` persists `fog_off` in the map (sanitize owns the
  field; editor snapshots cannot reset it). Terrain+traps visible to all
  members; `visible_map` keeps the live-token LOS pipeline untouched.
- **NPC blocks:** `clean_npc` is the ONE normalizer and persists
  `abilities`/`resources`/`notes`; whitelists in `add_token`/`update_npc` and
  `CreatureIn`/`_creature_block` carry them (bestiary + spawn round-trip);
  long rest refills NPC spell slots + resources (HP untouched).
- **Audio:** `audio_pause` keeps `current_id` (`playing:false`); clients resume
  direct sources in place, embeds restart (labeled in UI).
- **UI:** sidebar tabs + `?` help overlay (see Frontend); DM token-add input is
  `#dm-npc-name` (the sheet's `#npc-name` is the NPC editor's — do not collide).
- Tests: `test_diorama_parity`, `test_downed_movement`, `test_trap_lifecycle`,
  `test_fog_off`, `test_npc_workflow`, `test_audio_pause`.

## Deployment & table UX hardening (Sprint 9)

- **Canonical runtime is Docker**: `docker compose up --build` (runtime stage),
  `docker compose run --rm test` (test stage = full pytest, pinned deps, Python 3.12).
  Bind mount `./data:/srv/data`; container runs as uid 1000, has a HEALTHCHECK on
  `/api/health`, `restart: unless-stopped`; single uvicorn process — in-memory rooms
  make `--workers`/replicas a hard NO (D61). Hosts without buildx: `DOCKER_BUILDKIT=0`.
- **Persistent tree**: `VTT_DATA_DIR` = db + `secret.key` + `uploads/` (D62).
  `/uploads/...` URLs unchanged; `scripts/move_uploads.py` migrates legacy files.
  Backups: `scripts/vtt-backup.sh` (sqlite backup API = WAL-safe, integrity-checked) /
  `scripts/vtt-restore.sh`. Source packaging: `scripts/make_release.sh`.
- **Cookie-safe session tokens**: make_token payload is base64url WITHOUT `=`
  (an unquoted cookie value containing `=` is dropped by cookie parsers — the old
  intermittent-401 production bug); read_token re-pads so legacy cookies verify (D62).
  `secret.key` is stored HEX-encoded: raw random bytes can contain whitespace, and
  the generating call vs. the stripped read-back used to disagree (~1.6% of installs,
  D62). Legacy raw files load unchanged via the fromhex-fallback.
- **Trust boundaries**: `X-Forwarded-Proto`/`X-Forwarded-For` honored only with
  `VTT_TRUST_PROXY=1`; WS handshake enforces same-origin or `VTT_ALLOWED_ORIGINS`
  (close 4403); cookie flags HttpOnly+Lax(+Secure per D62 rules) (D64).
- **Loop-safe delivery (D61)**: each socket is registered with its owning event loop
  (`attach_ws` in `ws.py` pump). `net._send` delivers in-loop; a foreign loop (only
  ever Starlette TestClient, which gives each WS session its own loop) is crossed via
  `run_coroutine_threadsafe` — anyio wakeups must never cross loops. Production stays
  single-loop and hits the fast path.
- **Doors**: `dm_only` (operation restricted to DM, checked BEFORE lock-state answer)
  and `secret` (never in any player payload; silent refusal; no chronicle line) are
  sanitized map fields — both views read the same server data (D63).
- **UI layout (post-sprint fix, 2026-10-06)**: `#view-room` is a flex app-shell
  (`100vh`, topbar auto-height, `.room-grid flex:1; min-height:0` — NEVER guess
  the topbar height again). `.side` never scrolls: three fixed regions —
  `#side-tabs` (category nav, top), `#chronicle` (the single main feed area:
  tabs Chat|Game Log|Dice via `switchFeed`, `applyFeedPanels` keeps exactly one
  surface + chat-only composer rows, feed persisted in localStorage `vtt-feed`),
  and `.side-cat` (drawer for category/context panels, `max-height:46%`, own
  scroll). Roll results mirror into `#dice-out`. NPC sheet sectioned (all
  `#npc-*` ids kept). Static pins: `tests/test_layout_pins.py` — change the
  layout there, in the same PR, if you must change this structure.
- Tests: `test_doors_dmonly.py`, `test_deploy_hygiene.py`, `test_auth_token.py`.

---

# 4. WebSocket message map

## General permission pattern

Handlers receive:

```python
async def handler(ws, room_id, user, is_dm, msg):
    ...
```

- `user` is the authenticated WebSocket user.
- `is_dm` comes from the room-membership row.
- Private messages must never be broadcast and filtered client-side.

## Important inbound message types

| Type | Handler | Permission | Private? | Notes |
|---|---|---|---|---|
| `chat` | `room.chat.handle_chat` | any member | maybe | supports global, dm, whisper, personas |
| `narrative` | `room.chat.handle_narrative` | DM only | maybe | public/private narrative overlay/history |
| `secret_event` | `room.secret_events.handle_secret_event` | DM only | maybe | narrative + optional targeted sound |
| `roll` | `room.dice.handle_roll` | member | maybe | visibility public/self/dm/blind |
| `hp` | `room.combat.handle_hp` | DM | maybe | routed through health reducer |
| `move` | `room.movement.handle_move` | own token or DM teleport | no | with `path`: revalidates and refuses silently-different routes (`route_invalid`, D60); without: recomputes authoritative footprint-aware path |
| `stop_move` | `room.movement.handle_stop_move` | DM | no | cancels active `_walks` task |
| `path_preview` | `room.movement.handle_path_preview` | own token or DM | yes (requester) | server preview; never mutates token; carries `cost`/`budget`/`within_budget` (D68) |
| `forced_move` | `room.moveforced.handle_forced_move` | DM | yes (DM) | push/pull/shove/knockback/throw/teleport; stops on first illegal cell; no walk/budget/growth (D71) |
| `fog_edit` | `room.fog.handle_fog_edit` | DM | no | batch reveal/hide shared `explored` memory |
| `fog_toggle` | `room.fog.handle_fog_toggle` | DM | no | room-wide `fog_off` flag: terrain+static visible to all, live NPCs stay LOS-filtered (D60) |
| `map_edit` | `dispatch.handle_map_edit` | DM | no | map model sanitized; preserves trap/loot/fog runtime state; resize carries `explored` overlap |
| `door` | `room.doors.handle_door` | DM or adjacent player | no | closed/locked edges block movement and LOS |
| `spawn_encounter` | `room.encounters.handle_spawn_encounter` | DM | no | validates encounter ownership |
| `audio_add/remove/play/pause/stop` | `room.audio.*` | DM | no | room ambience; `pause` = `playing:false` with `current_id` kept (D60) |
| `sound_trigger` | `room.audio.handle_sound_trigger` | DM | maybe | targeted private SFX |
| `quest_add/update/obj_add/obj_done/complete/fail/delete` | `room.quests.*` | DM | no | thin transport over `app/quests.py` ops |
| `class_levels` | `room.progression.handle_class_levels` | owner or DM (room members) | no | multiclass entries; legacy `level` kept in sync |
| `ability_cast` | `room.abilities.handle_ability_cast` | owner (own token) or DM | no | thin transport over `abilities.execute` (D55) |

## Important outbound event kinds

| Kind | Sent by | Typical recipients | Private? |
|---|---|---|---|
| `chat` | chat handler | room/public or explicit whisper recipients | maybe |
| `narrative` | narrative/secret handler | public or private recipients | maybe |
| `sound` | audio handler | selected recipient(s) | maybe |
| `ambience` | audio handler | all room members | no |
| `dice` | dice/gamelog | per visibility | maybe |
| `whisper` | traps/items/loot | owner/DM only | yes |
| `token_add` / `token_leave` / `token_gone` | visibility | per-viewer LOS | maybe |
| `step` / `move` | movement/visibility | per-viewer LOS | maybe |
| `move_state` | movement | room | no | moving start/stop and manual/trap reason |
| `path_preview` | movement | requester only | yes | requested route and footprint cells |
| `fog_changed` | fog | room | no | batch persistent-explored updates |
| `initiative` | combat | room | no |
| `cond` / `death` | conditions/death | room or snapshot | usually no |
| `ping` | pings | room | no |
| `map_expanded` | room.growth | room | no | auto world growth (D67, flag-off default D77): new `w,h,origin`; NO pixel shift (D72) — clients refetch; player-owned token walks/teleports only |
| `forced_moved` | room.moveforced | DM socket | private | final cell + z of a forced move (D71); movement itself rides `step` |
| `quests_changed` | room quests | room | no | payload-less; clients refetch filtered `/state` |
| `ability_result` | caster socket | private | yes | entries privacy-filtered; hidden targets counted, never named |
| `system` | gamelog notices (incl. quest notices) | per visibility | maybe | chronicle line, never reconstruction source |
| `error` | various | sender socket | private |
| `room_deleted` | rooms.delete_room → net.purge | room, then sockets close | no | room permanently deleted (D76); clients leave to lobby and must not reconnect |

---

# 5. Server-authoritative boundaries

These must remain server-side:

- Dice results.
- Saving throws and proficiency claims.
- Attack bonuses and cover effects.
- HP changes.
- Temporary HP absorption.
- Typed damage/resistance/vulnerability/immunity.
- Death-save state.
- Inventory/item effects and charges.
- Attunement cap.
- Spell slots.
- Movement legality, path previews and stop transitions.
- Footprint collision and placement.
- Line of sight, token visibility and fog exploration.
- Traps and loot.
- Hidden NPC stat blocks.
- NPC disposition/size if marked hidden.
- Game-log visibility.
- Chat/whisper/narrative recipient filtering.
- DM persona and NPC-speech permissions.
- Audio source parsing and embedding.
- Selective audio recipient filtering.
- Character ownership.
- Room membership and DM role.
- Quest visibility (`party`/`dm`, `hidden` status, hidden objectives) —
  filtered in `quests.visible_for` before any serialization.
- Class-level validation (owner or room-DM only; strict whole-payload reject).

Frontend filtering may improve presentation but may not be the security boundary.

---

# 6. Shared SSOT functions / helpers

## Dice and visibility

- `app/room/dice.py::_parse_dice()`
- `app/room/dice.py::do_roll()`
- `app/room/gamelog.py::post_message()`
- `app/room/chat.py::post_chat()`
- `app/room/chat.py::chat_history_for_viewer()`

## HP and damage

- `app/room/health.py::change_hp()`
- `app/room/health.py::heal()`
- `app/room/health.py::damage()`
- `app/gear.py::apply_defense()`

## Proficiency and sheet math

- `app/gear.py::as_sheet()` / `as_row()` — THE canonical DB-row↔sheet converters;
  every `gear.*` calculation must receive an `as_sheet()` result (D66 — raw rows
  silently produced modifier 0)
- `app/gear.py::prof_bonus()`
- `app/gear.py::skill_bonus()`
- `app/gear.py::save_bonus()`
- `app/gear.py::spell_attack()`
- `app/gear.py::spell_save_dc()`
- `app/gear.py::compute_ac()`

## Movement, footprints, LOS and map

- `app/path.py::find_path()`
- `app/path.py::path_footprint_cost()`
- `app/movecost.py::route_cost()` / `walk_budget()` (cost & budget SSOT, D68)
- `app/mapmodel.py::TERRAIN` / `walkable()` / `difficult()` / `blocks_vision()` (D69)
- `app/wall.py::blocks_movement()` / `blocks_vision()` / `height_units()` (D69)
- `app/gear.py::clean_speeds()` (walk/fly/swim/climb SSOT)
- `app/room/moveforced.py::handle_forced_move()` (D71)
- `app/footprint.py::valid_final_position()`
- `app/footprint.py::find_valid_origin()`
- `app/los.py::line_of_sight()`
- `app/los.py::visible_cells()`
- `app/room/movement.py::handle_move()`
- `app/room/movement.py::handle_stop_move()`
- `app/room/movement.py::handle_path_preview()`
- `app/mapmodel.py::blocked_edges()`
- `app/mapmodel.py::visible_map()`
- `app/mapmodel.py::reveal_cells()`
- `app/room/fog.py::handle_fog_edit()`

## Quests, progression, events, geometry (Sprint 6)

- `app/quests.py::visible_for()` — the ONLY quest visibility filter (live and
  `/state` both call it).
- `app/quests.py::create_quest/update_quest/set_objective/complete_quest/
  fail_quest/delete_quest` — quest state changes go through these ops only.
- `app/progression.py::total_character_level()` — the ONLY level derivation
  (never re-`sum` class entries elsewhere).
- `app/progression.py::set_class_levels()` — the ONLY class-level mutation.
- `app/events.py::emit()` — event facts AFTER state commits; state must never
  be reconstructed from events or notices.
- `app/effects.py::effect_cells()` — shared ability geometry; client parity
  enforced by `tests/test_effects.py`.
- `app/abilities.py::execute()` — the ONLY ability operation; definitions via
  `abilities.register()`; all targeting/range/LOS/resources decided here, server-side.
- `app/gear.py::stat_mod()/ability_save_dc()/ability_attack_bonus()` — the only
  modifier/DC/attack derivations.

## Permissions and visibility

- `app/auth.py::room_of()`
- WebSocket `is_dm` from `app/ws.py`.
- `app/room/gamelog.py::filter_messages_for_viewer()`
- `app/room/chat.py::chat_history_for_viewer()`
- `app/room/visibility.py::viewer_visible_cells()`
- `app/room/visibility.py::send_token_event()`
- `app/room/visibility.py::broadcast_token_add()`

## Audio source safety

- `app/room/audio.py::parse_audio_source()`
- `app/room/audio.py::load_state()`
- `app/room/audio.py::clean_source()`

Do not reimplement these elsewhere without a strong reason.

---

# 7. Database map

Important tables:

- `users` — authentication identities.
- `characters` — owned characters, JSON columns for sheet data.
- `creatures` — private per-user bestiary templates.
- `rooms` — room metadata and join code.
- `room_members` — membership and role.
- `tokens` — PC/NPC tokens, NPC block JSON, conditions, death state, size (interpreted as footprint), disposition.
- `messages` — game-log and chat/narrative messages with visibility metadata.
- `room_state` — initiative JSON, map JSON, audio JSON.
- `encounters` — private per-user encounter templates.
- `notes` — room journal/handouts.
- `quests` — structured quest log: `status (active|completed|failed|hidden)`,
  `objectives` JSON, `visibility (party|dm)`; players see only party-visible
  non-hidden rows, filtered in `quests.visible_for` (live and `/state`).
- `characters.class_levels` — JSON multiclass entries (D53); `level` column
  kept in sync by `progression.set_class_levels`.
- `characters.abilities` — JSON list of granted ability ids (access model only;
  no prep/spellbook rules — D55). NPC equivalents live in the token's npc block.
- `soundboard` — private reusable DM sound effects.

Migrations are append-only. Add columns with `db.py::init_db()`'s `migrate()` helper and add new tables to `SCHEMA`.

## Chat-related message fields

Important `messages` columns:

- `type`: `chat`, `narrative`, `dice`, `system`
- `visibility`: `public`, `whisper`, `dm`
- `recipient_ids`: JSON list of authorized recipient user IDs
- `channel`: `global`, `dm`, `whisper`, `narrative`
- `persona`: narrative display name
- `sender_kind`: `user`, `persona`, `npc`
- `npc_token_id`: NPC provenance
- `style`: `normal`, `voice`, `overlay`, etc.

Private delivery uses the database fields plus server-side delivery; never only `meta`.

---

# 8. Test map

| Test file | Covers |
|---|---|
| `tests/test_dice.py` | dice parsing, keep clauses, spell text formatting |
| `tests/test_gear.py` | AC, items, skills, saves, defenses, spell math |
| `tests/test_path.py` | legacy and current A*, walls, doors, difficult terrain |
| `tests/test_footprint_path.py` | large/Huge footprints, collision, preview terrain restrictions |
| `tests/test_los.py` | wall/door LOS, sealed corners, footprint sources/targets |
| `tests/test_mapmodel.py` | map sanitize, reveal cells, doors, pins |
| `tests/test_movement_fog.py` | path previews, hidden token payloads, fog edits, movement stop, trap stop |
| `tests/test_npc.py` | NPC block normalization |
| `tests/test_integration.py` | auth/room lifecycle, hidden info, game log, dice, HP, traps, items, combat, visibility |
| `tests/test_chat.py` | chat privacy, personas, narrative, secret events |
| `tests/test_audio.py` | audio URL parsing, room ambience state, selective audio |
| `tests/test_view_mode.py` | client-local view mode: no server/WS plumbing, fallback/persistence, diorama empty/hidden-safe rendering (Node vm) |
| `tests/test_hardening.py` | door×LOS×explored cycle, stale-preview authority, walk cancellation, mid-walk door/wall route invalidation, coordinate invariants, adversarial permissions and malformed payloads |
| `tests/test_quests.py` | quest CRUD via WS, DM-only server filtering (live + `/state` + raw-payload grep), notice visibility, reconnect reconstruction, player mutation refusal, quest/door event emission |
| `tests/test_progression.py` | class-level validation, derived total + PB, legacy-column sync, owner/DM/stranger authorization |
| `tests/test_effects.py` | point/line/cone/circle/square geometry, clipping, determinism, server≡client `aoeCells` parity (Node vm) |
| `tests/test_abilities.py` | DC/attack derivation, save-half, resist/immune through defense pipeline, death-pipeline entry, heal, condition, concentration flag, slot+resource consumption, upcast validation, attack-vs-AC+crit, footprint flank, LOS/door, range authority, actor spoofing refusal, hidden-token non-leak |
| `tests/test_diorama_parity.py` | confirmed-path revalidation refusal (`route_invalid`), shared camera-space click math (Node vm), view-aware click/token/double-click, tool parity, sheet-crash guard |
| `tests/test_downed_movement.py` | 0-HP preview/move/teleport refusal, per-step downed stop, NPC corpse DM-drag stays allowed |
| `tests/test_trap_lifecycle.py` | triggered one-shot, stale map_edit keeps traps disarmed, resize carries explored overlap (map-saves-without-traps regression) |
| `tests/test_fog_off.py` | fog_toggle DM-only, player visibility under fog_off (terrain yes / live foes no), map_edit cannot reset flag |
| `tests/test_npc_workflow.py` | abilities/resources/notes persist through add/update/bestiary/spawn, long-rest refill, same-name spawn distinct |
| `tests/test_audio_pause.py` | audio_pause keeps current_id, play resumes, stop clears |
| `tests/test_doors_dmonly.py` | dm_only/secret doors: sanitize roundtrip, player non-operability, hostile set/remove refusal, secret invisibility + silence, chronicle non-leak, normal/locked regressions |
| `tests/test_deploy_hygiene.py` | cookie flags + XFP trust gate, WS origin rejection/allowance, uploads under VTT_DATA_DIR served at same URL, health endpoint |
| `tests/test_auth_token.py` | padding-free tokens, legacy padded verify, tamper/expiry rejection, SimpleCookie roundtrip, secret-key stability across generation |

Canonical full-suite run: `docker compose run --rm test` (pinned Python 3.12 image);
host dev runs `.venv` (Python 3.14) — the `_fast_bcrypt` + loop-safe `_send`
make both environments deterministic.

`tests/conftest.py`:

- isolates `VTT_DATA_DIR`
- initializes DB
- clears transient in-memory hubs before tests
- `_fast_bcrypt`: session fixture lowering bcrypt rounds to 4 (bcrypt 5.x +
  Python 3.14 could deadlock inside TestClient's portal; production default
  rounds stay 12). Production code must never import this.
- `recv_until(..., fail_on_error=True)` (test_movement_fog helpers) fails loud
  with the payload when the server sends an unexpected `error` instead of the
  awaited event — silent WS hangs become readable failures.

---

# 9. Dependency map

Important dependencies:

```text
WebSocket lifecycle
  → app/ws.py
  → app/room/dispatch.py
  → individual room handlers

Chat
  → app/room/chat.py
  → net.send_user/broadcast
  → messages table
  → /api/rooms/{code}/state chat_history_for_viewer()

Narrative
  → app/room/chat.py
  → private/public delivery
  → frontend narrative overlay

Secret event
  → app/room/secret_events.py
  → app/room/chat.py
  → app/room/audio.py

Audio
  → app/room/audio.py URL parser
  → room_state.audio_json
  → ambience broadcast
  → localStorage local volume
  → selective sound event delivery

Typed damage
  → app/room/combat.handle_hp()
  → app/room/health.change_hp()
  → app/gear.apply_defense()

Death saves
  → health.drop-to-zero transition
  → app/room/death.py save state
  → HP heal/nat-20 interactions

Movement preview
  → app/room/movement.handle_path_preview()
  → app/footprint.valid_final_position()
  → app/room/visibility.viewer_visible_cells()
  → app/path.find_path()
  → requester-only path_preview

Confirmed movement
  → app/room/movement.handle_move()
  → app/footprint.valid_final_position()
  → app/path.find_path()
  → app/mapmodel.blocked_edges()
  → walk task + move_state
  → app/room/visibility.send_token_event()
  → optional trap stop

Stop movement
  → app/room/movement.handle_stop_move()
  → _walks task cancel
  → authoritative step + move_state false

LOS / fog
  → app/room/visibility.viewer_source_cells()
  → app/footprint.player_source_cells()
  → app/los.visible_cells()
  → app/mapmodel.reveal_cells()
  → app/mapmodel.visible_map()
  → app/rooms.room_state()

Manual DM fog
  → app/room/fog.handle_fog_edit()
  → app/mapmodel.explored update
  → fog_changed broadcast
```

---

# 10. Known architectural hazards

## Hidden information leakage

The most important class of bug.

Rules:

- Private data must never be sent to unauthorized sockets.
- Never use `display:none` or client filtering as privacy.
- `/state` must filter as strictly as live delivery.
- When adding a new private event, verify:
  1. live delivery excludes others
  2. `/state` excludes others
  3. malformed recipients fail safely

## Client/server duplicated math

The frontend mirrors some rules for preview:

- ability checks/saves/spells
- skill bonus display

Movement preview no longer mirrors A* on the client. The server computes the route and the client only
draws the returned cells. Each animated walk step is revalidated against the CURRENT map before it is
applied (`path.step_legal()` + `map_lock`): a door closed or wall painted mid-walk ends the route with
`move_state reason:"path_blocked"` and the token holds its last legal cell (D50).

## LOS/fog model and limitations

LOS is a radius-6 deterministic wall/door line calculation. It conservatively blocks sealed diagonal
corners. `explored` is shared persistent room memory; live LOS is calculated separately and OR-ed with
memory in `visible_map()`. Manual DM hide therefore cannot corrupt current sight. Collision currently
authoritatively validates the final footprint, while same-owner intermediate pass-through remains a
design choice rather than a stacking guarantee.

## Backwards compatibility

SQLite migrations are additive. Existing deployments may have old rows.

- Default JSON columns to `{}` or `[]`.
- New message visibility types must not accidentally expose old public rows.
- Old `recipient_user_id` is legacy; chat uses `recipient_ids`.

## In-memory transient state

Hub clients, walks, ghosts, rate-limit buckets, and temporary caches are in-memory.

If new state is added:

- clear it in `tests/conftest.py`
- decide whether it should be persisted
- avoid treating it as durable room state unless explicitly documented

---

# 11. Editing hints

## Before modifying HP/damage

Inspect:

- `app/room/health.py::change_hp()`
- `app/room/combat.py::handle_hp()`
- `app/gear.py::apply_defense()`
- `app/room/death.py`

Do not introduce second HP mutation paths unless they call the health reducer.

## Before modifying dice/visibility

Inspect:

- `app/room/dice.py`
- `app/room/gamelog.py`
- `app/room/chat.py`
- `app/rooms.py::room_state()`

Live delivery and `/state` replay must match.

## Before modifying chat/narrative privacy

Inspect:

- `app/room/chat.py`
- `app/room/gamelog.py`
- `app/room/net.py`
- `tests/test_chat.py`

A new private message type needs live-delivery and history-filter tests.

## Before modifying audio

Inspect:

- `app/room/audio.py`
- `app/static/js/10_core.js`
- `app/static/js/40_ws.js`
- `app/static/js/60_main.js`
- `tests/test_audio.py`

Treat external URLs as untrusted. Construct embeds from validated IDs; never render caller-provided HTML.

## Before modifying map rendering

Inspect:

- `app/mapmodel.py::visible_map()`
- `app/static/js/50_canvas.js::draw()`
- `tests/test_mapmodel.py`
- `tests/test_integration.py`

Do not expose hidden map objects to players from the server.

## Before adding a WebSocket message

Inspect:

- `app/room/dispatch.py`
- existing handlers in `app/room/*.py`
- frontend handler switch in `app/static/js/40_ws.js`

Add:

1. handler
2. permission checks
3. recipient filtering if private
4. event kind
5. tests

## Database changes

Add:

- new table to `SCHEMA`
- or new column through `init_db()`'s `migrate()` helper

Then run tests to ensure old database shapes still work.

---

# 12. Content licensing boundary (read before adding D&D-flavored content)

Full legal text: `ATTRIBUTION.md`. Working rules for coding agents:

## Allowed without additional human review

- project-original mechanics, content, names, maps, artwork
- original monsters / items / spells (invented names and text)
- appropriately attributed SRD 5.1 material (CC BY 4.0; use the exact
  attribution statement from `ATTRIBUTION.md`, nothing more)
- third-party assets whose license is compatible AND recorded where used

## Do NOT copy (needs licensing/human review first)

- D&D Beyond catalog content
- Monster Manual content outside the SRD
- Player's Handbook text outside licensed SRD material
- adventure book text
- Forgotten Realms (or any setting) text/content unless separately licensed
- official artwork, official maps, logos, trade dress
- non-SRD proprietary monster descriptions/statblocks
- copyrighted music/audio

The SRD is **not** "all of D&D". When in doubt: invent an original equivalent
instead of copying. YouTube/Spotify integrations are user-entitled playback
links only; they never grant redistribution rights.

---

# 13. Views: Tactical vs Diorama (client-local presentation)

- One authoritative world (`state.grid`, `state.tokens`, `state.ghosts` — all
  already server-filtered per viewer). TWO renderers display it.
- Tactical renderer: `app/static/js/50_canvas.js::drawTactical()` (original
  `draw()` body, untouched logic).
- Diorama renderer: `app/static/js/55_diorama.js::drawDiorama()` — 2:1
  isometric prototype (floors, extruded walls, door panels, token billboards).
- Single dispatch point: `draw()` in `50_canvas.js` routes to the active
  renderer. All existing call sites (tick, fog_changed, pings, AoE…) keep
  calling `draw()` and therefore follow the current view.
- View selection lives ONLY in the client: `state.viewMode`
  ("tactical" | "diorama", invalid → tactical) plus localStorage
  `dndtable-view-mode`, helper `normalizeViewMode()` in `10_core.js`, switch
  UI wired in `60_main.js`.
- View mode is NEVER sent over WebSocket, never persisted server-side, never
  affects permissions, movement, LOS, fog, or combat. Each player picks their
  own view independently. The DM map editor always renders tactical.
- Diorama interaction covers token selection, door toggle and server path
  preview/move confirm. DM tools (ruler, AoE, ping, spawn-drop, map editor)
  are tactical-view tools; switch to Tactical to use them.
- **View framing (D75, fixes the manual "black screen / one-way door")**:
  opening a room calls `initViewCam()` AFTER `resize()` — Tactical centers on
  the player's own token (`centerOnMyToken`), Diorama centers the camera on the
  viewer's KNOWN world (`fitDiorama`, reuses `visibleHere` so it reveals
  nothing new). Each mode keeps its own camera (`state.camT`/`state.camD`);
  `setViewMode` saves and restores the slots so a fit never corrupts the other
  view. Tactical→Diorama→Tactical must always round-trip the world unchanged
  and restore the user's own camera — pinned by `test_view_mode.py` (Node vm,
  real renderer code, player-shaped payload).
- **Turn & movement economy (D74 + D79 — extend, never fork)**: combat state
  lives ONLY in `room_state.initiative` (`combat.py`: `get_init/begin_turn/
  advance/move_remaining/spend_move/spend_slot`). The turn's
  `move_total/move_spent` are in **movecost units (squares)** — the same
  `movecost.route_cost`/`walk_budget` that prices previews and charges steps
  (`movement.walk`). Never convert feet back into turn fields, never add a
  second cost function. Outside combat the economy does not apply (unlisted
  or no combat → unlimited movement, all geometry/fog rules intact). Inside
  combat: listed tokens move only on their own turn (DM exempt), Dash spends
  the **action** for +1×speed units this turn, `end_turn` advances initiative
  and `begin_turn` hands fresh resources to the next combatant. The client's
  turn bar (`renderInit` in 30_room.js) only renders the broadcast initiative
  object; the server re-enforces everything, the preview is a hint.
- **Footprint editing (D81/15B)**: the `token_span` operation is the ONLY
  resize path (owner or DM, 1..10, validated as the COMPLETE rectangle at the
  token's CURRENT anchor — never relocates; a rejection keeps everything).
  The sheet's Footprint W/H row drives it. Render-loop code must NEVER
  shadow this loop scope's viewport `w`/`h` names (the 15B all-tokens-invisible
  incident; pinned in `test_sprint15b.py`).
- **Condition lifecycle (D80 — one clock per condition)**: a condition is
  `{k, rounds, until}` on `tokens.conds` (`app/conditions.py` owns catalog and
  ALL progression). `until` = "" → round clock (`step_rounds`, once per wrap);
  "start"/"end" → the creature's own turn clock (`step_turn`) — advanced ONLY
  by `combat.advance_turn`, the single turn lifecycle (end hooks → advance →
  round clock on wrap → start hooks → fresh resources). Never call
  `step_conditions`/`step_turn` from anywhere else; a condition must never
  tick through two hooks. Voluntary movement is gated by
  `movement._movement_block_reason` (0 HP or the incapacitated family) at the
  entry AND every walk step — DM moves and `moveforced` stay separate.
  Standing from prone is the `stand` handler: own turn, charges
  `ceil(walk_budget/2)` of the BASE via `spend_move` (same accounting as Dash
  and walk — never a second tracker); outside combat it is free.
- Diagnostics for future "all black" bugs: open the page with `?debug` —
  the topbar shows build token + `integrity=ok/FAIL/DRIFT` (D78), view mode,
  canvas size/DPR, cam/camT/camD, camInit trace, `grid=y/n` + window
  (origin, w×h, cell), own token's world cell and screen position,
  known/explored/painted counts, `bring=<last result/error>` and the last
  client/boot exception (all derived from this viewer's own filtered payload
  or build identity; counts only, never hidden entities).
- **Frontend generation integrity (D78 — read before touching ANY file in
  `app/static/js/`)**: the black-canvas saga was a mixed script generation
  (new 50_canvas calling `gridOrigin` against a cached pre-D72 10_core), not
  a game-rule bug. Rules that keep it from returning: (1) `app/buildinfo.py`
  computes ONE build token over all owned JS/CSS + index.html; `/` injects it
  into every asset URL and `window.__BUILD__` — never add an asset URL without
  `?v=__BUILDTOKEN__`. (2) Every module stamps `window.__BUILDS["<file>"]`
  (first line) — copy the line when creating a new file and add it to
  `MODULES` in `99_boot.js` and to index.html in load order. (3) A genuinely
  required cross-file global must be added to `REQUIRED` in `99_boot.js`;
  `tests/test_frontend_bundle.py` then proves definition-before-call in load
  order (it reproduces the exact incident as a negative control). (4) Boot
  belongs to `99_boot.js` ONLY (`appBoot()` in 60_main is never self-called).
  (5) Gameplay results and presentation results stay separate: a successful
  server operation must never be toasted as failed because camera/render
  setup threw afterwards.
- Manual verification for frontend changes: follow
  `MANUAL_BROWSER_CHECKLIST.md` — BUILD CHECK first (console `BUILD <token>`
  == `/api/build` == asset `?v=` == no mismatch banner), then the smoke test.
