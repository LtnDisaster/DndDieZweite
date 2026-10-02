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

---

# 2. Repository map

| File / module | Purpose | Important entry points |
|---|---|---|
| `app/main.py` | FastAPI app, startup, static mounts | `app`, `startup()` |
| `app/rooms.py` | REST API, role-filtered room state | `/api/*`, `room_state()` |
| `app/ws.py` | WebSocket auth/lifecycle | `ws_room()` |
| `app/auth.py` | bcrypt passwords, signed cookie sessions, room access | `read_token()`, `current_user()`, `require_user()`, `room_of()` |
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
| `app/room/net.py` | Broadcast/map helpers | `broadcast()`, `send_user()`, `sys_msg()`, `get_map()`, `set_map()` |
| `app/room/chat.py` | Chat, personas, whispers, narrative delivery | `handle_chat()`, `handle_narrative()` |
| `app/room/audio.py` | Safe audio URL parsing and room ambience state | `parse_audio_source()`, `load_state()`, `handle_audio_*()` |
| `app/room/secret_events.py` | Composes private narrative + optional sound | `handle_secret_event()` |
| `app/room/gamelog.py` | Game-log dice/system delivery and visibility | `post_message()`, `filter_messages_for_viewer()` |
| `app/room/health.py` | Central HP/temp/typed-damage/death reducer | `change_hp()`, `heal()`, `damage()` |
| `app/room/dice.py` | Server dice parser/roller, rolls, saves, attacks, rests | `do_roll()`, `parse_roll()`, `handle_roll()`, `handle_cast()` |
| `app/room/combat.py` | Initiative and HP handlers | `handle_init_start()`, `handle_init_next()`, `handle_hp()` |
| `app/room/movement.py` | Walks, stop, trap auto-stop, path previews | `handle_move()`, `handle_stop_move()`, `handle_path_preview()`, `walk()` |
| `app/room/fog.py` | DM manual exploration edits | `handle_fog_edit()` |
| `app/room/tokens.py` | Token add/remove/NPC edits | `handle_add_token()`, `handle_update_npc()` |
| `app/room/items.py` | Item use/attune/identify/recharge | `handle_use_item()`, `handle_attune()` |
| `app/room/traps.py` | Trap and loot resolution | `hit_trap()`, `take_loot()` |
| `app/room/doors.py` | Door permissions | `handle_door()` |
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
- Client:
  - `app/static/js/20_lobby.js`
  - `app/static/js/30_room.js`
  - `app/static/js/60_main.js`
- Tests:
  - `tests/test_integration.py`

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
  - `app/npc.py`
  - `app/rooms.py` creature CRUD
- Client:
  - `app/static/js/30_room.js`
  - `app/static/js/50_canvas.js`
- Tests:
  - `tests/test_npc.py`
  - `tests/test_integration.py`

## Movement / footprints / pathfinding / doors

- Server:
  - `app/room/movement.py` — walk task, stop move, trap auto-stop and path previews.
  - `app/path.py` — footprint-aware A*.
  - `app/footprint.py` — size/anchor/collision SSOT.
  - `app/mapmodel.py`
  - `app/room/doors.py` — open/close/lock plus door-open LOS reveal.
- Client:
  - `app/static/js/50_canvas.js` — requests `path_preview`, renders footprint center, server path cells,
    active-walk ring and DM stop control.
- Tests:
  - `tests/test_path.py`
  - `tests/test_footprint_path.py`
  - `tests/test_mapmodel.py`
  - `tests/test_movement_fog.py`
  - `tests/test_integration.py`

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
  - `app/mapmodel.py`
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
| `move` | `room.movement.handle_move` | own token or DM teleport | no | recomputes authoritative footprint-aware path |
| `stop_move` | `room.movement.handle_stop_move` | DM | no | cancels active `_walks` task |
| `path_preview` | `room.movement.handle_path_preview` | own token or DM | yes (requester) | server preview; never mutates token |
| `fog_edit` | `room.fog.handle_fog_edit` | DM | no | batch reveal/hide shared `explored` memory |
| `map_edit` | `dispatch.handle_map_edit` | DM | no | map model sanitized |
| `door` | `room.doors.handle_door` | DM or adjacent player | no | closed/locked edges block movement and LOS |
| `spawn_encounter` | `room.encounters.handle_spawn_encounter` | DM | no | validates encounter ownership |
| `audio_add/remove/play/stop` | `room.audio.*` | DM | no | room ambience state |
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
| `quests_changed` | room quests | room | no | payload-less; clients refetch filtered `/state` |
| `ability_result` | caster socket | private | yes | entries privacy-filtered; hidden targets counted, never named |
| `system` | gamelog notices (incl. quest notices) | per visibility | maybe | chronicle line, never reconstruction source |
| `error` | various | sender socket | private |

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

- `app/gear.py::prof_bonus()`
- `app/gear.py::skill_bonus()`
- `app/gear.py::save_bonus()`
- `app/gear.py::spell_attack()`
- `app/gear.py::spell_save_dc()`
- `app/gear.py::compute_ac()`

## Movement, footprints, LOS and map

- `app/path.py::find_path()`
- `app/path.py::path_footprint_cost()`
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

`tests/conftest.py`:

- isolates `VTT_DATA_DIR`
- initializes DB
- clears transient in-memory hubs before tests

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
- Manual verification checklist (frontend has no browser test automation):
  1. Join a room → Tactical loads normally; move a token.
  2. Switch to Diorama → same token position shown as a billboard.
  3. Second browser stays Tactical → the first stays Diorama (independent).
  4. Open/close a door from either view → both views reflect the same state.
  5. A hidden NPC never appears in Diorama (server filtered it already).
  6. Switch back to Tactical → movement and path preview still work.
  7. Reload the page → the local view preference persists (localStorage).
