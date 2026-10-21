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
  - Room clients are tracked in `app/room/net.py::_clients`. The owning
    event loop lives ON the socket (`ws._iio_loop`) — never keyed by
    `id(ws)`: CPython reuses ids and a dead-loop `wrap_future` would hang
    the delivery forever (D111 hardening; `_send` also times out cross-loop
    sends and refuses stopped loops).
  - Messages are dispatched through `app/room/dispatch.py::HANDLERS`.
- **SQLite persistence**:
  - `app/db.py` defines schema and additive migrations.
  - Thread-local SQLite connections use WAL mode and `busy_timeout`.
  - Multi-statement writes use `db.tx()`.
- **Effect grammar (D111)**: `app/effectops.py` — versioned, validated op
  cells (`damage/heal/temp_hp/condition/condition_remove/break_concentration/
  save/check/forced_move/resource`) executed by the EXISTING engines; trigger
  seams (`use/equip/unequip/on_hit/on_damaged`) ride the existing room
  handlers, claim-guarded (once per round/op, no trigger chains, cost paid
   only when allowed). Reference: `docs/EFFECT_GRAMMAR.md`.
- **Contested primitive (D112)**: `app/room/opposed.py` is a thin helper over the
  EXISTING dice channel + `gear` bonuses implementing the three contested shapes
  (check-vs-check, check→DC→save, check-vs-fixed-DC) with NO rules of its own
  (tie default `defender`; `tie="dm"` defers via `Tie`). The 2024 special-melee
  family (`app/room/grapple.py`: Grapple/Shove/Escape) and both pickpocket models
  (`app/room/pickpocket.py`) run on it; grapple state stays additive on the
  `grappled` cond (`src`+`dc`) and ends via `end_grapples_out_of_reach` at the
  movement ends. `pick`/`grappled.dc` are additive data only. Reference:
  `docs/EFFECT_GRAMMAR.md` §6a (the S42 wrapping point — no second engine).
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
  8. `app/static/js/70_content.js` — DM CSV rule-package import/export panel (D95).
  9. `app/static/js/80_prep.js` — room-preparation screen + guided character
     build wizard (D101); talks to `/api/content/{code}/options` and the
     existing build/assign/starting-gear routes, holds NO class rules.
  10. `app/static/js/99_boot.js` — bundle-integrity gate; runs LAST and is the only
     caller of `appBoot()` (D78). Any new script module must be added to its
     `MODULES` list, stamp itself, and (if it exposes a boot entrypoint) be added
     to `REQUIRED` — see `tests/test_frontend_bundle.py`.
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
| `app/gear.py` | Shared sheet/item/skill/spell/defense math. D98: gear is a DERIVED, transient overlay (`effective_gear`) consumed by `_stat_mod`/`skill_bonus`/`save_bonus`/`compute_ac`/`clean_speeds`/`weapon_profiles` — never persisted, base stats untouched. One prop validator (`clean_props`). D99: currency SSOT (integer copper: `CURRENCIES`/`to_cp`/`cp_breakdown`/`cp_label`) + derived carrying (`carry_capacity`/`inventory_weight`/`encumbrance`, `CARRY_PER_STR`/`SIZE_CARRY`, `carry_bonus`) | `effective_gear()`, `clean_props()`, `weapon_profiles()`, `compute_ac()`, `save_bonus()`, `skill_bonus()`, `wields_two_handed()`, `to_cp()`, `cp_breakdown()`, `encumbrance()`, `carry_capacity()` |
| `app/npc.py` | NPC stat-block model | `clean_npc()`, `load()`, `to_char()` |
| `app/conditions.py` | Conditions catalog and logic | `clean_conds()`, `add()`, `remove()`, `step_rounds()` |
| `app/path.py` | Footprint-aware server A*; D114 3D state search | `find_path()`, `find_path_3d()`, `path_footprint_cost()` |
| `app/footprint.py` | Token size and collision footprint | `FOOTPRINT`, `occupied_origin()`, `valid_final_position()`, `find_valid_origin()` |
| `app/los.py` | Wall/door line of sight | `line_of_sight()`, `visible_cells()` |
| `app/mapmodel.py` | Map schema, fog, doors, traps, loot, pins, D114 `openv` | `sanitize()`, `visible_map()`, `blocked_edges()`, `reveal_cells()`, `openv_at()` |
| `app/vertical.py` | D113/D114 canonical vertical scale + token volume defaults | `ELEV_FT`/`FLOOR_FT` (=10), `SIZE_HEIGHT_FT`, `token_height_ft()`, `base_ft()`, `top_ft()`; floor→level in `floors.level()` |
| `app/quests.py` | Quest Log game operations (persistent, filtered) | `create_quest()`, `set_objective()`, `complete_quest()`, `visible_for()` |
| `app/progression.py` | Multiclass-ready class model | `clean_class_levels()`, `total_character_level()`, `set_class_levels()` |
| `app/events.py` | Plain-dict game-event facts + listener seam (D52) | `make()`, `emit()`, `subscribe()`, `recent` |
| `app/effects.py` | Generic ability/effect geometry (D54) | `effect_cells()` |
| `app/abilities.py` | Generic ability engine: data defs + authoritative executor (D55) | `register()`, `clean_definition()`, `execute()` |
| `app/content.py` | CSV content packages (D95): schema/validate/import/export. DATA read by the engines (items→item_defs, spells→abilities), **never code**; generic `content(kind,room_id,id)` SSOT, room 0 = global | `SCHEMAS`, `parse()`, `validate()`, `import_package()`, `export_csv()`, `load_registered_abilities()` |
| `app/content_api.py` | DM-only content import/export REST, raw-body (no multipart) (D95) | `/api/content/{code}` import/export/kinds |
| `app/charbuild.py` | Chronological build Stufe 1–20 from CONTENT, drives the EXISTING columns (D96); Phase C adds spellcasting — known/prepared model, slot TABLE, class resource (D97). Ledger in `characters.build` is bookkeeping, not a second truth | `plan()`, `apply()`, `ledger()` |
| `app/charbuild_api.py` | Room-scoped build REST; owner-or-room-DM (mirrors `class_levels`) (D96); D108 origin report/apply inside the SAME engine | `/api/build/{code}/{cid}` plan/apply · `…/origin` GET/POST |
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
| `app/room/movement.py` | Walks, stop, trap auto-stop, path previews; D114 explicit cross-plane move/teleport + animated 3D walk | `handle_move()`, `handle_stop_move()`, `handle_path_preview()`, `walk()`, `walk3d()`, `_move3d()`, `_teleport3d()` |
| `app/room/opposed.py` | D112 contested/DC primitive — thin helper over the EXISTING dice channel + gear bonuses, NO own rules (three shapes are just composition) | `participant()`, `check_roll()`, `save_roll()`, `bonus_roll()`, `melee_attack_number()`, `better_save()`, `opposed_wins(att,def,tie=)`, `beats_dc()`, `Tie` (tie default `defender`; `tie="dm"` defers) |
| `app/room/grapple.py` | D112 2024 special melee (NOT the 2014 Athletics contest): Grapple=check→save `better_save`, Shove prone/push, Escape vs stored `dc`; size+reach gates; ends on leaving reach | `handle_grapple()`, `handle_shove()`, `handle_escape()`, `end_grapples_out_of_reach()` (wired into `moveforced`+`movement` move ends) |
| `app/room/pickpocket.py` | D112 steal, BOTH 2024 models: DM-mediated attempt + DM-`pick`-subset auto-take; hidden Sleight→DM only, notice via fixed `notice_dc` OR real Perception (no passive perc, A7); atomic curse-preserving transfer; `pick`-only leak guard, claim-before-spend | `handle_pickpocket()`, `handle_pickpocket_take()`, `handle_pickable()` (DM toggles `pick`) |
| `app/room/fog.py` | DM manual exploration edits + room-wide fog on/off | `handle_fog_edit()`, `handle_fog_toggle()` |
| `app/room/lights.py` | D104 DM lamp management over the D89 object model | `handle_lamp()` (add/update/remove — DM-only, plane-scoped) |
| `app/room/tokens.py` | Token add/remove/NPC edits | `handle_add_token()`, `handle_update_npc()` |
| `app/room/items.py` | Item use/attune/identify/recharge | `handle_use_item()`, `handle_attune()` |
| `app/room/traps.py` | Trap and loot resolution | `hit_trap()`, `take_loot()` |
| `app/room/doors.py` | Door permissions incl. dm_only/secret (D63) | `handle_door()` |
| `app/room/authz.py` | The single token-control authority question (owner/controller/DM, D82) | `controls()`, `controlled_rows()` |
| `app/floors.py` | Floor registry: named occupancy/visibility planes per room (D86/D88/D102) | `parse()`, `exists()`, `add()`, `rename()`, `remove()` |
| `app/room/interact.py` | World-object interaction over allowlisted ops (D82) | `handle_interact()` |
| `app/room/visibility.py` | Footprint LOS token delivery and ghosts; D114 body-plane vision sources | `viewer_visible_cells()`, `send_token_event()`, `broadcast_token_add()` |
| `app/room/vertical3d.py` | D114 single cross-plane reasoning point: body planes, openings, sight/reach join and whole-volume fit | `body_planes()`, `body_cells()`, `observable_cells()`, `column_open()`, `occupied_volume()`, `volume_terrain_clear()`, `vertical_path_clear()`, `volume_final_valid()` |
| `app/static/js/10_core.js` | Global `state`, API helper, toast | `state`, `api()`, `esc()`, `toast()` |
| `app/static/js/30_room.js` | Room state, chat, sheet, journal, party rendering | `openRoom()`, `refreshRoom()`, `renderFeed()` |
| `app/static/js/40_ws.js` | WebSocket event dispatch | `connectWS()`, `wsSend()` |
| `app/static/js/50_canvas.js` | Map/canvas rendering and overlays; view dispatcher | `draw()`, `drawTactical()`, `tick()`, `showAoe()`, `showPing()` |
| `app/static/js/55_diorama.js` | Isometric diorama renderer + click routing | `drawDiorama()`, `dioProj()`, `dioramaDown()` |
| `app/static/js/60_main.js` | Wire DOM events | `wire()`, boot function |
| `app/static/js/70_content.js` | DM CSV rule-package import/export panel (D95), registered in the D78 integrity gate | `wireContent()`, `refreshContentKinds()` |
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
  - `app/static/js/60_main.js` — `btn-back` is the permanent escape from the
    table (works in Tactical AND Diorama; kills reconnect + ws). D101: it now
    returns to the room's PREPARATION screen via `backToPrep()` (80_prep.js);
    the lobby is one level further back via the prep screen's "← Lobby".
- Tests:
  - `tests/test_integration.py`
  - `tests/test_d111_effects.py`
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
  - `app/movecost.py` — cost SSOT (5e diagonals 1,2,1,2; difficult ×2; budget = speed//5;
    D114 one declared level = `10 ft = 2` units via `vertical_cost()`).
    A* weights in `path.py` stay 10/14 — cost is a route post-processing, not search.
  - `app/path.py` — footprint-aware A*; optional `elev=` gates steps at |Δz| ≤ 1 (D70);
    D114 `find_path_3d()` searches `(floor, origin)` states while reusing the
    horizontal step rules and delegated vertical callbacks.
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
    **Visual invariant (D82, oriented by D83):** `tokens.vw`/`vh` (optional;
    default = the effective collision span) and `tokens.rot` (0/90/180/270).
    D83: the facing ORIENTS THE ENTITY — `token_span()` returns the EFFECTIVE
    ORIENTED mechanical box (a 3×7 at 90 IS a 7×3 for occupancy, collision,
    A*, LOS and AoE alike; `base_span()` is the un-rotated stored shape) and
    `visual_span()` orients vw/vh by the same rule, so visual and mechanical
    bounds SHARE A CENTRE. Visual size and mechanical size stay INDEPENDENT
    sizes — VISUAL BOUNDS ARE NOT MECHANICAL OCCUPANCY; gameplay never asks
    `visual_span`. The renderer draws the body from BASE visual dims INSIDE
    its `ctx.rotate` transform (oriented dims there = double rotation).
    Centre convention: `footprint.anchor_for_center` — integer anchors, floor
    tie-break; rotation RE-ANCHORS instead of teleporting and an illegal turn
    is REJECTED whole (rot/pos/footprint untouched, never a move-to-fit).
    Room-wide partial token SELECTs MUST carry `size, fw, fh, rot,
    mount_token_id` — a missing geometry column silently un-rotates or
    un-carries that subsystem. `app/room/authz.py::controls()` is the
    single answer to "may this user act through this token?" (owner OR DM-
    assigned `controller_user_id` OR DM) — movement/turn/conditions/death/
    casting/door-and-object reach all ask it; a controller is not an owner,
    gets no sheet rights, and reveals no fog. `tokens.mount_token_id` is an
    acyclic rider→mount RELATIONSHIP (D83: moving mounts CARRY riders —
    `movement.carry_riders` re-centres them via `anchor_for_center`; riders
    spend no own budget and never block their own mount) and separate from
    the controller axis.
  - `app/mapmodel.py` — plus `objects` (D82): generic world objects as DATA
    (label + allowlisted op `toggle`/`door`); `room/interact.py` executes the
    op (`door` reuses the one `doors.door_toggled` lifecycle); no eval, ever.
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
  - `app/room/lights.py` — D104: the DM's lamp management channel; mutates the
    SAME objects list the editor saves, then `reevaluate_visibility` (D87/D89).
  - `app/room/fog.py` — DM-only batch `explored` reveal/hide.
  - `app/mapmodel.py`
  - `app/room/movement.py`
  - `app/room/doors.py`
- Client:
  - `app/static/js/50_canvas.js` — renders server-known cells and fog brushes.
    D103: floor 0 renders as visible tiling, the 🕳️ void brush paints 5, 🧹 erase
    keeps its old meaning (0 + clear entities at the cell).
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
    (move✓ ×2 cost, climbable), 5 void (D103: move✗/vision✓, NOT climbable — a pit
    is not a wall; nothing stores a 5 until a DM paints it, `terrain(None)` stays
    floor, sanitize clamps 6+ to 5); `elev` integer layer -6..6 (D70, missing = flat,
    fog-gated in `visible_map`); `grow_map`/`growth_needed` (D67).
  - `app/assets.py` — token artwork (D85): uploads validated as REAL PNG (magic,
    Pillow re-encode strips metadata, caps), 16-hex ids, private assets serve only
    owner / room DM / token rider via `serve_allowed`, uniform 404 (no oracle).
    D103: `tokens.image` canon is `/assets/<id>` and the canvas loads it VERBATIM —
    `media_router` (no prefix) routes that exact url to the same `get_asset` as
    `/api/assets/<id>` does. Clients never re-derive a url from an asset id;
    servers never store anything but the canonical form. FastAPI ≥0.142 defers
    include_router into `_IncludedRouter` wrappers — pin routing behaviour in tests,
    do not scan `app.routes`.
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

## Floors / planes (D86/D88, operated since D102)

- Concept: one room, one world frame, INDEPENDENT planes. The primary floor
  (`""`) is the legacy `room_state.map_json` byte-for-byte; every named floor
  has its own `floor_maps` row (own terrain/traps/objects/fog), tokens carry
  `tokens.floor`. No migration, no second map engine — one map model.
- Server:
  - `app/floors.py` — the registry (`rooms.floors` JSON, MAX 8, name rules) +
    D102 `rename()` (registry + plane map + tokens move together).
  - `app/room/net.py` — the map seam `get_map(room_id, floor)` /
    `set_map(..., floor)`; **an un-floored `set_map` writes the PRIMARY** —
    the classic D102 bug: every save must pass the floor of the map it holds.
    `fog_patch(mp, newly, floor)` labels every reveal; `send_to_plane` (strict
    map truth) vs `send_to_plane_viewed` (+ token-less observers on primary).
  - `app/rooms.py` — REST: POST/DELETE + **PATCH `/api/rooms/{code}/floors/
    {name}`** (D102 rename: FLOOR.rename, then stair `op.floor` references are
    retargeted across ALL plane maps, then `floors_changed` + `map_changed`).
    `/state` derives `view_floor`: DM browses via `?floor=`, a player is
    DELIVERED on their token's plane. `assign_char` reveals on the TOKEN's
    plane (D102).
  - `app/ws.py` — connect reveal runs per token floor on that plane's map.
  - `app/room/tokens.py` — `handle_token_floor` is **DM-only since D102**;
    players change planes through the validated stair object
    (`interact` kind `stair` → `apply_forced_move`, destination checked on the
    target plane) — never by self-service hop.
  - `app/room/movement.py` / `moveforced.py` / `doors.py` / `fog.py` — every
    plane-scoped save/broadcast carries its floor.
- Client:
  - `app/static/js/30_room.js` — `renderViewFloor()` (DM plane browse select)
    + D102 `renderFloorPanel()`/`editFloor()` (DM Floors panel: add / view /
    rename / delete; delete-refusals show the server reason); sheet floor row
    is read-only for players.
  - `app/static/js/50_canvas.js` — `viewerPlane()`/`onPlane()` (DM browsing is
    plane-local; players and character previews render only server-delivered
    observable rows, so D114 cross-plane delivery needs no second client
    visibility engine); D114 `openv` brush/rendering and vertical token hints.
  - `app/static/js/30_room.js` — D114 token height/elevation rows and the
    owner/DM vertical flight control; its `floor` wire field is an explicit move
    intent, never inferred from an omitted field.
  - `app/static/js/40_ws.js` — `explored`/`fog_changed` carry `payload.floor`
    and are only applied when it equals `state.viewFloor`; a mismatch means
    the patch belongs to a plane this client is not looking at.
- Tests: `tests/test_floors.py`, `tests/test_floor_maps.py`,
  `tests/test_d102_floors.py` (integrity, isolation, DM management).

## Combat / initiative / HP / typed damage

- Server:
  - `app/room/combat.py`
  - `app/room/health.py`
  - `app/gear.py`
  - `app/room/opposed.py` (D112 contested/DC primitive — helper over the dice
    channel + gear bonuses, three shapes, tie `defender`/`attacker`/`dm`)
  - `app/room/grapple.py` (D112 2024 Grapple/Shove/Escape, check→save
    `better_save`, `end_grapples_out_of_reach` on the movement ends)
  - `app/room/pickpocket.py` (D112 both steal models, `pick`-subset leak guard,
    atomic curse-preserving transfer; authoring via `handle_pickable`)
- Client:
  - `app/static/js/30_room.js`
- Tests:
  - `tests/test_integration.py`
  - `tests/test_d112_contested.py`

## Conditions / death saves / status

- Server:
  - `app/conditions.py`
  - `app/effectops.py` (condition DEFINITION layer: `conditions.csv` catalog
    + `BUILTIN_HOOKS` as data, `on_start/on_round/on_expire` effect hooks,
    `/state cond_catalog`; per-room catalog cache invalidated on import)
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
    client parity locked by Node-vm test. Visual relay `room/aoe.py` is
    PLANE-SCOPED (D90): DM's claimed floor validated, delivered via
    `send_to_plane_viewed`. `abilities.execute` resolves everything on the
    CASTER's plane (map seam `net.get_map`, targeting `tokens_in_cells(floor=)`,
    cross-plane single target = `No target token`).
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
- D111: a definition may carry an `effects` op-cell — `execute()` runs it in
  the SAME shell (cost/chronicle/privacy unchanged); feats surface as
  castable `feat_<id>` abilities (`charbuild` entitlement). Definition cells
  are re-validated on every load.
- Content: production registry is EMPTY; definitions register via
  `abilities.register(clean dict)` (tests use original names). No spell DB.
- Multiclass caveat (D58): slot progression must NOT be derived from
  `total_character_level()` — separate axis, table attaches later.
- Tests: `tests/test_abilities.py`, `tests/test_d111_effects.py`

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
- **Lights & darkness (D87/D89/D104):** ONE model — the plane's `mp["dark"]`
  flag (🕯 via `map_edit`'s `dark` field), lamps as world OBJECTS
  (`interact.op.kind:"lamp"`, `bright` cells 0..30, `state.on`), token
  `light`/`darkvision`. In darkness sight comes from light ALONE:
  `visibility._lit_cells` = own footprint + max(light,darkvision) + every lamp's
  own LOS on THAT plane (plane-local; walls block glow through the engine's own
  LOS, never a light copy). The DM management channel is `lamp`
  (`room/lights.py`: add/update(bright,label,on,x,y)/remove by id; DM-only;
  `floor` arg with the D102 save rule; same object canon, same id-state-merge,
  same `reevaluate_visibility`; the "Lights" DM panel toggles SILENTLY —
  player-run lamp interacts keep their chronicle, management does not fake one).
  WS connect reveal defers to `viewer_visible_cells` on dark planes (D104:
  no classic-radius light-budget bypass on reconnect). NOT in the model, by
  documented decision: magical darkness that ignores light — ordinary light
  DOES defeat ordinary darkness (D89), variants stay documentation.
- **DM peek (D104):** `GET /api/rooms/{code}/view_as/{character_id}` answers
  with THE character's own `/state` sight — `rooms._viewer_token_view` is the
  extracted player branch both endpoints share (a second visibility logic is
  forbidden; the equivalence is pinned byte-for-byte). Read-only: explored
  bytes, ghost memory and broadcasts stay untouched (pinned). DM-only (member
  404, outsider 403 like `/state`, character without a token here 404), and it
  follows the character's plane. The client swaps RENDER DATA only
  (`viewG/viewTokens/viewGhosts`); live state keeps receiving events
  underneath; all canvas input is dead during preview, diorama is blocked, and
  tokens invisible to the character are ABSENT from the payload — nothing
  hidden is clickable, hoverable or listable. Snapshot + Refresh; live replay
  would mean a second state path (forbidden).
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
| `roll` | `room.dice.handle_roll` | member | maybe | visibility public/self/dm/blind. D93: `kind:"attack"` + `item_id` = item attack — profile, AC verdict, damage dice ALL server-derived; optional `token_id`/`target_id`/`slot` (action|bonus, consumed only during active initiative)/`op_id` (replay). No item_id = legacy by-name weapon path |
| `hp` | `room.combat.handle_hp` | DM | maybe | routed through health reducer |
| `move` | `room.movement.handle_move` | own token or DM teleport | no | with `path`: revalidates and refuses silently-different routes (`route_invalid`, D60); without: recomputes authoritative footprint-aware path. `mode` (walk/fly/swim/climb, D83): one active mode, missing speed refused; carried riders follow automatically |
| `stop_move` | `room.movement.handle_stop_move` | DM | no | cancels active `_walks` task |
| `path_preview` | `room.movement.handle_path_preview` | own token or DM | yes (requester) | server preview; never mutates token; carries `cost`/`budget`/`within_budget` (D68) and the priced `mode` (D83) |
| `forced_move` | `room.moveforced.handle_forced_move` | DM | yes (DM) | push/pull/shove/knockback/throw/teleport; stops on first illegal cell; no walk/budget/growth (D71); D83: the logic lives in `apply_forced_move` — the ONLY forced-write, callable server-side by traps/interactions; riders are carried along |
| `knock_prone` | `room.conditions.handle_knock_prone` | DM | no | D83 generic forced-state op applying the EXISTING prone condition (D80); server entry `knock_prone()` for future trap/fall hooks; no height math |
| `fog_edit` | `room.fog.handle_fog_edit` | DM | no | batch reveal/hide shared `explored` memory |
| `fog_toggle` | `room.fog.handle_fog_toggle` | DM | no | room-wide `fog_off` flag: terrain+static visible to all, live NPCs stay LOS-filtered (D60) |
| `lamp` | `room.lights.handle_lamp` | DM | no | D104 lamp add/update(bright,label,on,move)/remove on a plane — same canon + reevaluate as lamp-interact/map-edit; silent administration |
| `map_edit` | `dispatch.handle_map_edit` | DM | no | map model sanitized; preserves trap/loot/fog runtime state; resize carries `explored` overlap; D114 `openv` changes re-evaluate cross-plane visibility |
| `door` | `room.doors.handle_door` | DM or adjacent player | no | closed/locked edges block movement and LOS |
| `token_span` | `room.tokens.handle_token_span` | owner or DM | no | mechanical resize; complete rect must fit at the CURRENT anchor or it is rejected unchanged (D81/15B) |
| `token_height` | `room.tokens.handle_token_height` | owner or DM | no | D114 vertical body: optional `height_ft`/`elevation_ft`, server-clamped to 0..200 ft; triggers visibility re-evaluation when the body may join another plane |
| `token_visual` | `room.tokens.handle_token_visual` | owner or DM | no | D82 VISUAL bounds (vw/vh) — presentation; no clearance check, footprint untouched |
| `token_rotate` | `room.tokens.handle_token_rotate` | owner or DM | no | D83 facing 0/90/180/270 — ORIENTS the mechanical footprint too; re-centres via `anchor_for_center`; illegal turn rejected whole; broadcast carries NO coordinates (the move rides the filtered step channel) |
| `token_controller` | `room.tokens.handle_token_controller` | DM only | no | D82 assign/clear generic controller (must be a room member; revocable) |
| `token_mount` | `room.tokens.handle_token_mount` | DM only | no | D82 acyclic rider→mount relationship, same room; D83: riding mounts now CARRY riders (walk/teleport/forced/rotation re-centre them; dismount re-homes the rider) |
| `interact` | `room.interact.handle_interact` | member (reach-gated like doors) | no | D82 allowlisted world-object ops (`toggle` / linked `door`); dm_only/secret refuse without leaks |
| `spawn_encounter` | `room.encounters.handle_spawn_encounter` | DM | no | validates encounter ownership |
| `audio_add/remove/play/pause/stop` | `room.audio.*` | DM | no | room ambience; `pause` = `playing:false` with `current_id` kept (D60) |
| `sound_trigger` | `room.audio.handle_sound_trigger` | DM | maybe | targeted private SFX |
| `quest_add/update/obj_add/obj_done/complete/fail/delete` | `room.quests.*` | DM | no | thin transport over `app/quests.py` ops |
| `class_levels` | `room.progression.handle_class_levels` | owner or DM (room members) | no | multiclass entries; legacy `level` kept in sync |
| `ability_cast` | `room.abilities.handle_ability_cast` | owner (own token) or DM | no | thin transport over `abilities.execute` (D55) |
| `item_def` | `room.inv.handle_item_def` | DM | no | D92: item-definition library (create/update/delete); defs travel via `/state` DM-only |
| `inv_grant` / `inv_remove` | `room.inv.*` | DM | no | D92: grant (def or ad-hoc) / take; target = character of a member of THIS room |
| `inv_adjust` | `room.inv.handle_inv_adjust` | sheet owner or DM | no | D92: split/combine stacks |
| `inv_transfer` | `room.inv.handle_inv_transfer` | sheet owner or DM | no | D92: member→member hand-off, ONE atomic transaction, slots stripped |
| `inv_equip` | `room.inv.handle_inv_equip` | sheet owner or DM | no | D92: (un)equip {slot, item_id|null}; generic kind table + props.slot; a two-hander (or versatile gripped two, D98) leaves the off hand empty |
| `inv_grip` | `room.inv.handle_inv_grip` | sheet owner or DM | no | D98: {item_id, grip:one/two} for an equipped VERSATILE weapon — picks the damage dice; two-handed grip clears the off hand atomically |
| `inv_money` | `room.inv.handle_inv_money` | grant/deduct: DM; transfer: sheet owner | no | D99: {action:grant/deduct/transfer, amount(int), coin:cp/sp/ep/gp/pp, char_id[, to_char_id]}. Server converts via `gear.to_cp` (never trusts a copper total); atomic + `op_id`-replay-guarded; a shortfall raises before any store. `inv_container{action:coins_fill/coins_take}` moves loot coin |
| `inv_container` | `room.inv.handle_inv_container` | reach-gated like `interact` (D82) | inspect private | D92: inspect/move/fill/remove on container objects; dm_only/cross-plane refuse without leaking |
| `npc_inv` | `room.inv.handle_npc_inv` | DM only | contents = inspect only | D105: manage `tok:<token_id>` gear (inspect/fill/remove/coins_*); silent to non-DM |
| `loot` | `room.inv.handle_loot` | reach-gated, while NPC hp==0 | contents = inspect only | D105: inspect/take/coins_take on a downed NPC; forced direction via `container_give` |
| `curse` | `room.inv.handle_curse` | DM only | full metadata = DM socket only | D106: {action:set/clear, item_id, name/desc/whisper} on a char-, chest- or NPC-carried instance; {action:reveal/conceal/whisper} additionally needs a seated PLAYER owner — recipient resolved server-side from the item's holder, delivered through `chat.post_chat` whisper (never broadcast, never in foreign histories). DM gets the authoritative `curse_updated` event; no `inv_changed` broadcast for curse ops (secrecy) |
| `grapple` | `room.grapple.handle_grapple` | own token or DM | maybe | D112 2024 grapple: `{token_id, target_id, op_id, adv, save?}`. Adjacency (Chebyshev ≤1 closest footprint corners) + size (≤ one size larger, `npc.SIZES`) + visibility + authz ALL validated before anything is spent; claim(op) BEFORE the action slot. Attacker `melee_attack_number` → DC, target `save_roll` (default `better_save` Str/Dex, `save` field overrides). Emits `dice` (attacker self / save dm-visible) + `cond` (`grappled` with `src`+`dc`) + `initiative` |
| `shove` | `room.grapple.handle_shove` | own token or DM | maybe | D112 2024 shove: `{token_id, target_id, mode:prone|push, op_id, adv}`. Same gate/economy as grapple; prone → existing prone path, push → `moveforced.apply_forced_move` (which itself fires `end_grapples_out_of_reach`) |
| `escape` | `room.grapple.handle_escape` | own token or DM | maybe | D112 escape: `{token_id, op_id}` — no target. Athletics OR Acrobatics vs the stored `grappled.dc`; if the grappler is gone/incapacitated it auto-succeeds. Emits `dice` + `cond` |
| `pickpocket` | `room.pickpocket.handle_pickpocket` | own token or DM | yes (DM) | D112 Model A: `{token_id, target_id, op_id, adv, notice_dc?}`. Hidden Sleight-of-Hand check reported ONLY to the DM (thief only gets a "made covertly" whisper, never the result); noticed = fixed `notice_dc` (`beats_dc`) OR a real Perception check (`opposed_wins`, tie→defender) — 2024 has no passive perception. Claim BEFORE spend; nothing is moved |
| `pickpocket_take` | `room.pickpocket.handle_pickpocket_take` | own token or DM | yes (DM) | D112 Model B: `{token_id, target_id, item_id, qty?, op_id}`. Only DM-`pick`-flagged items stealable (`_pick_entry`), an unflagged/unknown item answers EXACTLY like a failed check (never an inventory oracle). Success = one atomic `inventory.transfer`/`container_give` preserving curse metadata + resetting `revealed`; emits `whisper` + `dice` + `inv_changed` |
| `pickable` | `room.pickpocket.handle_pickable` | DM only | whisper | D112 authoring: `{token_id (NPC) OR char_id, item_id, action:set|clear, op_id}` toggles the `pick` flag (`container_set_pick`/`set_pick_char`); NPC path re-sends `inv_contents`, char path broadcasts `inv_changed`. `pick` never stacks (`_stack_key`) and rides the `clean_items` whitelist |
| `trap` | `room.traps.handle_trap` | owner (search/disarm) · DM (all) | whisper | D113 Phase 5: data-driven trap. `{action, token_id, x, y, adv?, target_id?}` — `search` = WIS(Perception) check vs `search_dc` (reveals on success), `disarm` = DEX check vs `disarm_dc` on a DISCOVERED trap (→ `disarmed`+`triggered`), `trigger` = DM force-spring on `target_id`. The actor names a CELL, never a trap id; a missed/absent search and a hidden-trap miss answer byte-identically (no oracle). Springing is `hit_trap` → the trap's `effects` grammar cell |

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
| `token_span` / `token_visual` / `token_rot` | room.tokens | room | no | D81/D82 mechanical span, visual bounds and facing (fields also ride snapshots/token_add) |
| `token_controller` / `token_mount` | room.tokens | room | no | D82 relationship broadcasts; hidden NPC tokens strip controller (D81 leak-parity) |
| `object_state` | room.interact | room | no | D82 generic object boolean flipped (state also rides `/state` grid) |
| `ping` | pings | plane's watchers (D90: token holders + DM + token-less observers on primary) | no |
| `aoe` | aoe relay | plane's watchers (DM tool, D90) | no |
| `map_expanded` | room.growth | room | no | auto world growth (D67, flag-off default D77): new `w,h,origin`; NO pixel shift (D72) — clients refetch; player-owned token walks/teleports only |
| `forced_moved` | room.moveforced | DM socket | private | final cell + z of a forced move (D71); movement itself rides `step` |
| `quests_changed` | room quests | room | no | payload-less; clients refetch filtered `/state` |
| `ability_result` | caster socket | private | yes | entries privacy-filtered; hidden targets counted, never named |
| `system` | gamelog notices (incl. quest notices) | per visibility | maybe | chronicle line, never reconstruction source |
| `inv_changed` | room.inv | room | no | D92 payload-less refetch (quests_changed pattern) — inventory/equipment/defs ride `/state` |
| `inv_contents` | room.inv | requester socket | yes | D92 authorised container inspect/move answer; contents exist in NO other channel |
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
- Item quantities, stacking, transfers, equipment slots, container contents
  and the replay ledger (D92) — `app/inventory.py` inside `db.tx()` only.
- Attack bonuses, damage dice, range and the action-slot verdict (D93):
  server derives from equipped props + `gear` math; the client claims
  `item_id` only. Peer character rows are the tactical allow-list (`_peer_view`),
  full sheets ship to owner and DM only.
- Attunement cap.
- Spell slots.
- Movement legality, path previews and stop transitions.
- Footprint collision and placement.
- Which cells are occupied — never derived from visual bounds (D82), always
  the ORIENTED mechanical box (D83).
- Turn movement budgets — per-mode ledgers (`move_by`), charged in movecost
  units only; Dash doubles every mode exactly once (D83).
- Forced movement — only through `moveforced.apply_forced_move` (D71/D83).
- Token-control authority (owner/controller/DM via `room/authz.py`, D82).
- World-object operations: only the allowlisted ops, never code (D82).
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

## Inventory, equipment and containers (Sprint 22)

- `app/inventory.py` — THE only mutation site for item quantities, stacks
  (split/combine/stack_add), grants, removals, transfers, equipment slots and
  container moves; every op re-reads its rows INSIDE `db.tx()` and claims the
  client `op_id` in `inv_ops` in the same transaction. `InvError` rolls back.
- `inv_ops` is the PROJECT-WIDE op ledger (D93): attack/cast/resource/use_item
  claim through `inventory._claim` in their mutation transaction; no op_id
  sent keeps the pre-D93 behaviour. One-day expiry applies to all kinds.
- Combat props (D93) are typed in `gear.clean_props` (`damage_dice`,
  `damage_type`, `ability`, `attack_bonus`, `damage_bonus`, `range_ft`,
  `reach_ft`, `proficient`, `two_handed`, `mod_to_damage`); everything else
  stays the D92 generic scalar bag. `gear.weapon_profiles(sheet)` is the ONLY
  attack-profile derivation (sheet display AND the attack path read it);
  clients render its numbers and claim `item_id` — never a bonus.
- `rooms.py::_peer_view` — unrelated members receive ONLY the tactical
  allow-list of a peer's character (identity, level, HP/AC/speed). The sheet
  itself (`_char_row` with `derived`) ships to the owner and the DM only.
- `app/gear.py::clean_items()` — item-entry sanitizer incl. D92 `qty`/`weight`/
  `stackable`/`def_id`/`props`; `clean_props()`/`clean_equipment()`/
  `can_equip()` — D92 property/slot normalisation (slot table is generic DATA,
  `props.slot` is the per-item override, `props.two_handed` the only cross-slot rule).
- `app/gear.py::compute_ac()` — equipped mode (any slot occupied → only worn
  items count) with untouched legacy fallback for sheets without equipment.
- `app/room/authz.py` — unchanged: CONTROLLER ≠ sheet authority; inventory
  rights are owner-or-DM like attune.

## CSV content packages (Sprint 25, D95)

- `app/content.py` — THE content engine, and the ONLY reader of rule CSV. It
  stores rows as data in `content(kind, room_id, id)` (room 0 = global, read by
  every room); that JSON is the export SSOT. **NEVER evaluate code from a CSV**
  and **NEVER build a second combat/dice/character/spell engine** — content only
  describes WHAT exists and its PARAMETERS; mechanics stay where they are.
  Anything no engine implements is carried as `manual`/`needs_choice` TEXT and is
  displayed, never silently interpreted. Validation reports `file`/`line`/
  `column`; one bad row refuses only its file; apply is idempotent (identical →
  unchanged, differing id → conflict).
- PROJECTION, not duplication: an `item` row → one `item_defs` row via the SAME
  insert the DM library uses (global `id` PK, `gear.clean_props`;
  `range_normal_ft`→`range_ft` which `gear.weapon_profiles` reads). A `spell` row
  → `abilities.register` with `cost.spell_slot.level`; `main.startup`
  re-registers from the DB so a restart repopulates the in-memory registry. Do
  not compute AC/damage/slots here — the engines already do.
- Slot progression is a class-row TABLE (`slot_progression`), NEVER derived from
  total level (D58). Upcast/cantrip dice scaling, `value_gp` currency and
  `weight` encumbrance are columns that import cleanly but are Phase C–E work.
- `app/content_api.py` — DM-only (`_require_dm` via `room_of`), raw-body transport
  (the pinned image has no `python-multipart`); export escapes formula injection.
- Frontend `app/static/js/70_content.js` is registered in the D78 bundle-integrity
  gate (`MODULES`+`REQUIRED` in `99_boot.js`, `wireContent()` in `appBoot`) — keep
  all three in sync or the boot gate refuses to start.
- Licensing: the shipped `app/content_pack/*.csv` uses ORIGINAL names
  (`scout`, `sword_plus1`, `kin_fey`); no protected text is committed
  (ATTRIBUTION.md). `docs/CSV_CONTENT_GUIDE.md` and `tests/test_content_examples.py`
  must stay in lockstep.

## Character build (Sprint 25, D96)

- `app/charbuild.py` builds a character STUFE 1..20 **from the D95 content** and
  performs ONLY the mutations the engines already own — `progression.set_class_levels`
  (single entry; `level` stays derived, never re-`sum`med), HP from the class
  rows' `hp_base`/`hp_per_level`, `gear.clean_saves`/`clean_skills`, and ASI/feat
  boosts into `stats`. Do NOT add a second level/HP/slot engine or re-derive slots
  from total level (D58).
- The build LEDGER in `characters.build` (`class_id`, `applied_through`, subclass,
  per-level `decisions`, `base_stats`) is BOOKKEEPING for the forward-only guard
  and the sheet. `apply()` RECOMPUTES 1..to from content + decisions each time,
  starting ability deltas from `base_stats` — never from the mutated row.
- Missing required choices → `needs_choice`, NOTHING written; a rebuild to a
  level `<= applied_through` is refused; a second class once started is refused.
- `app/charbuild_api.py` authz MUST mirror `app/room/progression.py` exactly
  (owner always; DM only if the character is in `room_members` of THAT room).
  The UI is the room sheet, not the lobby — one rule, one transport.
- The client holds NO class logic: it renders the chronology and POSTs a choices
  object; `charbuild` re-validates every rule server-side.
- D101: a successful `POST /api/build/{code}/{cid}/apply` broadcasts a `snapshot`
  (like the `class_levels` transport) — every client then refetches state and
  re-renders its open sheet. The apply handler in `30_room.js` ALSO re-renders
  locally after `refreshRoom()`; neither alone is enough (the browser-confirmed
  "stays unbuilt until reload" bug needed both). Never remove either without a
  real-browser re-check.

## Room preparation & guided build (Sprint 30, D101)

- The landing screen between join and table: `#view-prep` + `80_prep.js`
  (`openPrep(code)`). Joining/creating a room and clicking one in the lobby
  land HERE; the table is reached via "Open the table"/`openRoom()` and the
  table's ⚙/back buttons return here. The classic lobby "Bring" path still
  jumps straight to the table (legacy flow preserved).
- `GET /api/content/{code}/options` (`app/content_api.py`) — id+name catalogue
  of the room's rule pack for the species/class/background dropdowns, readable
  by EVERY room member (names only, never row payloads). import/export/kinds
  stay DM-only. Levels of class/subclass collapse to one entry per id.
- `characters.background` — additive bookkeeping column; `CharIn.background`
  defaults to `None` = "leave stored value untouched" so legacy PUT clients
  (the lobby editor) cannot wipe it; `""` is an explicit reset.
- `POST /api/rooms/{code}/starting-gear` (`app/rooms.py`) — grants the chosen
  background's `starting_items` from THIS room's rule pack through
  `app/inventory.py` (the SSOT); only tokens that resolve to a room item
  definition are granted, unresolvable CSV text is REPORTED as skipped, never
  invented. Idempotent via a deterministic `op_id` (`starting-gear-<bg>`,
  D94 inv_ops replay → `"already"`, never a double grant). Authz mirrors the
  build API EXACTLY (owner, or DM of a character assigned to the room).
- D108 `GET/POST /api/build/{code}/{cid}/origin` (`charbuild.py`/`charbuild_api.py`) —
  the 2024 character ORIGIN (background ASI + Origin feat). One operation module
  function `apply_origin` lives INSIDE the build engine: the background and its
  Origin feat resolve against THIS room's content (`asi_abilities` exactly three
  abilities, `origin_feat` a feat row with `category=origin`), the client may send
  only the DISTRIBUTION (`{"mode":"plus2_plus1","plus2":…,"plus1":…}` with distinct
  allowed targets, or `{"mode":"three"}`), scores may not rise above 20 (refused,
  never clamped), and `_apply_feat` (category-aware) applies the feat. The grant is
  recorded in the build ledger (`characters.build.origin` — secure proof, no
  reverse-computing from stats) and replayed at the FRONT of the D96 full recompute,
  so replay/double-click/parallel posts apply it exactly once and a later level-up
  replays instead of wiping it. hp/AC/slots/resources and the D94/D101 gear claims
  are untouched; no character is ever auto-migrated.
- The guided wizard derives EVERY field from `charbuild.plan` (`needs`) — skill
  options, subclass, per-level feat/ASI, spell picks — and labels ids with the
  `options` catalogue. Decision types the form cannot render are surfaced with
  an explicit expert-mode hint, never skipped. No list of classes/skills is
  hardcoded in the client; the shipped pack is data.

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
- `tokens` — PC/NPC tokens, NPC block JSON, conditions, death state, size (interpreted as footprint), disposition; `fw`/`fh` mechanical span (D81); `vw`/`vh` visual bounds + `rot` facing — `rot` ORIENTS the entity incl. its mechanical footprint (D83), vw/vh stay pure presentation sizes; `controller_user_id` generic controller relationship + `mount_token_id` acyclic rider→mount — NOT ownership (D82; D83 carries riders).
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
- `item_defs` — D92 room-scoped DM item definitions (id TEXT PK, name, desc,
  kind, weight, stackable, `props` JSON). Templates only: granting snapshots
  them into `characters.items` (def edits never mutate granted items).
- `containers` — D92 container CONTENTS keyed `(room_id, object_id)`; the
  world object itself lives in the map (D82), the contents live here and in
  NO other place — never in map JSON, `/state` or broadcasts.
- `inv_ops` — D92 replay ledger: first claim of a client `op_id` wins, a
  replayed claim answers as a no-op. Rows expire after one day.
- `characters.equipment` — D92 JSON `{slot: item_id}` for
  main_hand/off_hand/armor/acc1..acc3; `'{}'` = no explicit rig, which keeps
  the legacy auto-derivation in `gear.compute_ac` byte-identical.

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
| `tests/test_visual_size.py` | D82 visual bounds ≠ collision: fallback, independence, persistence, node hit test |
| `tests/test_rotation.py` | D83 facing: footprint ORIENTS (3x7→7x3), centre-preserving re-anchor + exact roundtrip, illegal-turn rejection, visual independence under rotation, upright-text pin |
| `tests/test_movement_modes.py` | D83 modes: SSOT budget conversion, fly ignores difficult+cliffs (not walls), per-mode ledgers cannot be farmed by switching, missing speed refused, legacy turn objects still read |
| `tests/test_interact.py` | D82 world objects: schema is data (allowlist), reach, dm_only/secret/locked refusals, door-lifecycle reuse, state survives stale map_edit, no-exec pin |
| `tests/test_controller.py` | D82 controller: assign/revoke, member-only, operational authority, unrelated refused, delivery without fog reveal |
| `tests/test_mount.py` | D82 mount: assign/revoke, self + multi-hop cycle rejection, same-room, DM-only |
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
| `tests/test_sprint20_security.py` | D90: caster-plane ability truth, cross-plane refusal no-oracle, hidden-token cond gate, plane-scoped aoe/ping (+darkvision/asset/floor/mount/lamp/state sweeps), editor resize pin/elev carry (Node vm) |
| `tests/test_browser_flow.py` | real-JS tactical flow against the live WS stack: tactical draw, rectangular-token hit test, preview→confirm over the wire, refresh persistence — the documented NO-BROWSER harness |
| `tests/test_d102_floors.py` | D102 floors: trap/toggle saves stay ON their plane (never clobber primary), connect/assign reveals land on the token's plane, reveal/fog patches carry `floor` and reach plane viewers only, `token_floor` DM-only while stairs stay the player route, floor RENAME moves registry+map+tokens and retargets stair destinations (refusals included), player `/state` delivered on the token's plane |
| `tests/test_d103_editor_assets.py` | D103: void(5) blocks movement/teleport/placement but NOT vision/light; brush edits never touch wall/door/trap entities; void is plane-local (crypt pit ≠ primary); registry/sanitize keep legacy maps byte-identical; player map_edit refused; canonical `/assets/<id>` serves exactly like `/api/assets/<id>` (owner 200 PNG+nosniff, riding-DM 200, stranger/junk 404); assigned artwork roundtrip keeps DB canon; client brush/canvas wiring pinned |
| `tests/test_d104_lights_preview.py` | D104: `lamp` channel roundtrip (add/update/off/remove, radius in/out, walls block glow like sight), darkness = memory+footstep only, darkvision effective, lamps plane-local AND plane-lighting, non-DM refused; `view_as` byte-equal to the player's own `/state`, leak-free (hidden NPC/traps/dm_only/secret doors/op payloads), purity (explored & player state unchanged), auth matrix (member 404/outsider 403/foreign char 404); reconnect reveals exactly by the light's reach; legacy rooms classic; toggled-off survives later map_edit; preview client wiring pinned |
| `tests/test_d106_curses.py` | D106: per-instance curse metadata (twin daggers stay distinct, stack carve-out to qty=1, no merge into ordinary stacks, split refused), survival matrix (container move, loot, equip/unequip, use with charge debit, attune, identify, recharge, long rest, honest sheet-PUT round-trip), secrecy matrix (player /state, lobby sheet, gear snapshot/derived, chest+loot inspect, view_as, chat chronicle — no secret on any wire), REST tamper (forged curse ignored, stripped PUT cannot wipe), curse channel DM-only + foreign-room refusal, owner-change resets `revealed` but never the curse, whisper recipient forced server-side and invisible to peers (live + history), `del_token` atomicity incl. FK-failure rollback of BOTH token and container |
| `tests/test_d108_origin.py` | D108 origin: report (abilities/feat/errors), both ASI modes, wrong/identical targets, 20-cap refuses, feat-category refusal, missing rows, 2014-background refusal, cross-room isolation, owner/DM/foreign authz, replay + concurrent double-post = one grant, reload-persistent ledger, no auto-migration, species stats untouched, gear never double, build-before/after origin replay once, PUT cannot forgery-erase |
| `tests/test_d110_e2e.py` | D110 integration chain: ONE continuous A→F dungeon run over the real REST/WS handlers (pack import, 2024 origin+apply+mastery-pick+kit-gear, move/wall/door/fog/view-as/floors, initiative with Cleave/Topple/Graze/Vex + condition clocks, 0-HP loot with adjacency + atomic replay, curse set/reveal/whisper owner-only, reconnect snapshot equality + replay idempotency) + guardians (foreign token/cond control, view-as DM-only excerpt, cross-room content isolation, whisper history leak). Pins the two D110 P1 fixes: refused attacks never spend the turn slot; curse `whisper` never mutates `revealed` |
| `tests/test_d111_effects.py` | D111 effect grammar + `conditions.csv`: validator/canon (unknown op/field/NaN refused, byte-stable canon), SRD `BUILTIN_HOOKS` wiring + CSV row overriding a builtin + cache invalidation on import, `clean_props`/`clean_definition` hardening (corrupt cells dropped), condition-expire without recursion, ops execute through the REAL WS for spell/feat/item-use/equip/on-hit/on-damaged with replay idempotency (one firing per fresh op), resource preflight (refused cast costs nothing), ping-pong condition chains across two tokens, cross-room isolation, `/state cond_catalog` ships | 
| `tests/test_d112_contested.py` | D112 contested/2024 special-melee/pickpocket over the REAL WS: `save_roll`/`better_save`/`opposed_wins` tie (`defender`/`attacker`/`dm`→`Tie`) unit; full Grapple (check→save, DC stored on `grappled.dc`, size+adjacency gates, ends on forced move/walk-away/grappler-gone) + Shove prone/push + Escape (Athletics/Acrobatics vs `dc`, auto-succeed when grappler gone); both pickpocket models (DM-mediated hidden result, Model-B `pick`-subset auto-take), leak guard (unflagged/unknown item == a failed check, never an oracle), replay (claim-before-spend: a replay spends+rolls nothing), concurrency, cursed-item transfer preserving curse + resetting `revealed`, cross-room, cross-plane, action-economy (spends only in initiative). No new skips, no source pins |
| `tests/test_d113_concentration.py` | D113 Phase 2: 2024 concentration lifecycle over the REAL WS — `conc`-linked condition ends room-wide with the concentration; CON save DC `max(10, floor(actual_hp_lost/2))` uncapped (temp-HP + resistance excluded from the DC); 0-HP and an incapacitating condition break WITHOUT a save; casting a new concentration ends the old first (old `conc` effects gone, new ones kept); `break_concentration` op; `on_damaged` depth gate (a trigger-originated damage does not re-fire the seam). Unrelated conditions are preserved |
| `tests/test_d113_curses.py` | D113 Phase 3: automatic curses — active equip fires, dormant does NOT, trigger-mismatch no-fire; owner-change `on_transfer` fires exactly once and op-id claim is idempotent (replay no double-fire); reads/inspect never fire; activation (`activate`/`deactivate`) is orthogonal to disclosure (reveal/conceal/whisper never change `active`, activation never reveals); a curse-origin fragment goes to the DM ONLY (`net.dm_whisper`), the owner view stays `curse_view`-strict (no `active`/`trigger`/`effects` leak); legacy curse (no activation keys) round-trips byte-identically and stays dormant; player-authored `arm`/`activate` refused; invalid effect cell refused |
| `tests/test_d113_opposed.py` | D113 Phase 4: effect grammar v2 — v1 and v2 validate, `v3`/`v0` refused, `opposed` accepted only under v2, required `success`/`failure` branches; `canon()` preserves the authored version (a v1 cell stays byte-identical `{"v":1}`, only explicit `{"v":2}` emits v2); `opposed` runs end-to-end through the real dice engine on deterministic rolls, taking the success branch on a win and the failure branch on a loss |
| `tests/test_d113_traps.py` | D113 Phase 5: data-driven traps (map ENTITY, not a CSV). Legacy trap (dc/dmg only) round-trips byte-identical with NO stray keys; a modern trap stores an `effects` grammar cell (+ `search_dc`/`disarm_dc`/`repeat`); an invalid effect cell is dropped (fail-closed) yet the trap survives. Springing runs the grammar through `effectops.run_ops` (`trigger` → prone, no `random.randint`); `repeat` keeps `triggered=false` (re-arms) vs one-shot `triggered=true`. Leak-safe discovery: a missed search vs a hidden trap and a search of an empty cell answer byte-identically (never a trap oracle); a successful Perception check sets `discovered` and reveals it; a trap with no `search_dc` is indistinguishable from empty. Disarm is a DEX check vs `disarm_dc` (success → `disarmed`+`triggered`), and a hidden trap is never acknowledged on a disarm. `trigger` is DM-only |
| `tests/test_d113_vertical.py` | D113 Phase 7: the canonical 10 ft vertical scale — `vertical.ELEV_FT==FLOOR_FT==10`; `elev_to_ft`/`floor_to_ft` (sign preserved, below-primary negative). The declared floor order IS the height stack (`floors.level`: primary 0, each added floor +1 level = +10 ft; holds after `rename`); `absolute_height_ft` = floor offset + ground elevation×10. Backward-compat pin: `mapmodel.sanitize` still clamps `elev` to -6..6 UNITS (the scale is reporting only; a +90 brush stays +6 units = 60 ft). No height combat, no movement-rule change |
| `tests/test_d114_vertical.py` | D114 Phase 3: size defaults are not ceilings; owner height/elevation persistence/reload, server validation/clamps, non-owner refusal, DM authority, hidden-NPC vertical metadata strip parity |
| `tests/test_d114_openings.py` | D114 Phase 4: `openv` default-solid/junk fail-closed, whole-footprint protrusion only through a matching opening, straight-shaft sight requires every intermediate column open, fog masks unexplored openings |
| `tests/test_d114_phase5_integration.py` | D114 Phase 5 live handlers: protruding body shares upper-plane fog/delivery and melee attack; solid ceiling stays hidden/untargetable; shaft gives sight but not physical melee/grapple reach; live height growth triggers visibility recalc; protrusion reaches a plane-local object |
| `tests/test_d114_phase6_vertical_movement.py` | D114 Phase 6: 30-ft whole-body projection across three open planes, solid-ceiling fail-closed, Large footprint cannot use a one-cell opening, flight crosses void while walking cannot, canonical vertical cost/budget, solid-ceiling move refusal and whole-volume target-plane collision |
| `tests/test_d114_phase8_integration.py` | D114 Phase 8: real WS horizontal approach + vertical flight with canonical spend, walk-mode refusal through a shaft, named-plane `openv` map-edit roundtrip, and live server-delivered cross-plane token rendering/hit-testing through the real canvas JS harness |
| `tests/test_d101_prep.py` | D101 prep screen: content `options` (member read, non-member/anon refused, empty room), `characters.background` roundtrip + no-PUT-wipe guard, `starting-gear` (resolves/skips/idempotent, authz mirrors build API, missing-data reported, `inv_changed` broadcast), `apply` broadcasts `snapshot` (reload-bug fix), and the prep UI wiring (source asserts — no browser runner) |
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

## Server-authorised character fields (Sprint 29, D100)

These fields are the game's AUTHORITATIVE progression and must NOT be writable
through the raw sheet editor `PUT /characters/{cid}` (owner) — that path preserves
`level`, `spells`, `spell_slots` from the stored row. The authorised writers are:
`charbuild.apply` (validated build/level-up, owner or room-DM), the DM `class_levels`
WS transport (DM-only), and the WS rest/ability/progression handlers. When staging a
caster in a test, set these via `db.x(...)`/`charbuild.apply` — the way the game itself
does — NOT via `put_char`/the editor PUT (`tests/test_d100_integration.py` shows the
`set_progression` idiom).

## The shared item library & atomic cost (Sprint 29, D100)

- `item_defs.id` is a GLOBAL primary key. Reads/deletes/grants filter `WHERE room_id=?`;
  a create or CSV projection that collides with ANOTHER room's id is REFUSED (never
  silently overwritten), because a per-room key would need a destructive rebuild. Do not
  "fix" a collision by widening the UPSERT to clobber across rooms.
- Slot / charge / resource consumption lives in `app/abilities.py` `_cast_gate`, which
  claims the `op_id` AND pays the cost in ONE `db.tx()`. Any new cost path must keep the
  read→check→increment inside a single `BEGIN IMMEDIATE` transaction (mirroring
  `room/dice.py`) so concurrent casts cannot lose an increment.

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
- `app/rooms.py::_viewer_token_view()` — the player branch shared with
  `room_view_as()` (D104): live delivery and `/state` replay must match, and
  the DM preview must be the same computation — one function, no drift.

Live delivery and `/state` replay must match.

## Before modifying inventory, containers or looting
- Inventory, equipment, containers and coin have ONE engine:
  `app/inventory.py`. Every mutation runs in `db.tx()` with an op_id claim
  (`_claim`, namespaced per character/object) — a missing op_id means "no
  replay protection", so every client path must send `invOpId()` (D94).
- NPC gear lives in the `containers` table under the synthetic key
  `tok:<token_id>` (D105). It is DM-visible through the `npc_inv` channel
  only and looting (`loot` channel) opens exactly while the NPC's stored
  hp is 0; both answer contents ONLY to the requester's own inspect. Never
  add inventory data to a token payload, snapshot or broadcast.
- Looting direction is `container_give` (forced out of the container) —
  do NOT "simplify" it to `container_move`, whose direction follows the
  item's current location and would let a carrier deposit INTO the corpse.
- Starting gear: the ONLY grant path is `POST /api/rooms/{code}/starting-
  gear` (+ its GET report). Background part = D101 semantics; class part =
  all-or-nothing (a broken pack must not write its claim) and exactly-once
  (the claim answers `already` before choices are parsed). `classes.csv`
  token grammar: `id [xN]`, groups `Label=alt|alt xN;…` — item ids in a
  payload are never trusted, the CSV's alternatives are the allowlist.
- D106 SECRET CURSES: `entry["curse"]` rides INSIDE the item entry (there is
  no stable global instance id — `stack_add` re-issues entry ids on every
  transfer, so a side table could not follow the instance; the entry dict IS
  the instance and travels transfer/chest/loot for free). `gear.clean_items`
  STRIPS the field by default (fail-closed — client PUTs, /state renders and
  every legacy path stay clean without knowing curses exist); only the engine's
  trusted reads pass `keep_curse=True` (`inventory._load`/`container_load`,
  the write-backs in `room/items.py`, `room/dice.py` long rest, `rooms.py` DM
  sheet view) — a plain mutation that re-writes items WITHOUT the trusted read
  silently deletes a curse, that is the class of bug D106 pins with tests.
  Disclosure has ONE gate: `gear.curse_view(items, mode)` — 'dm' full,
  'owner' only a revealed curse's name+desc (the whisper text never rides a
  sheet), anything else strips. A cursed entry NEVER stacks and NEVER splits
  (`_stack_key` returns None, `adjust("split")` refuses) — marking a qty>1
  stack carves one qty=1 piece atomically. Any owner change (transfer,
  container put/take, loot) keeps the curse but clears `revealed` — knowledge
  never travels; only `curse{action:reveal}` sets it again for the CURRENT
  owner. `curse{action:whisper}` resolves the recipient from the item's
  holder server-side — a recipient field in the message is ignored; delivery
  is the existing private `chat.post_chat` whisper (no broadcast, recipients'
  + sender's history only). Sheet PUT round-trips must neither forge
  (`_preserve_curses` strips client-authored curses) nor wipe (`update_char`
  re-attaches the stored ones by entry id).
- Reach maths: tokens carry PIXEL x/y, map objects carry CELL coords —
  convert with `map.cell` before intersecting (`room/inv.py` loot gate).
- Deleting a token must delete its `tok:<id>` container row too — in the
  SAME transaction as the token row itself (D106: `handle_del_token`
  wraps seat-unassign + container + token + chronicle line in one
  `db.tx()`; a failing DELETE rolls everything back, no orphan hoard and
  no headless corpse). Nothing else in `containers` may be touched.
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

---

## D113 (Sprint 42) — Konzentration, automatische Flüche, `opposed`-Op

- **Konzentration** bleibt dasselbe `concentrating`-Flag; NEU ist ein additives
  Link-Feld `conc` = Token-ID an einer Condition (die Condition „gehört" zur
  Konzentration und endet raumweit mit ihr). Lebenszyklus ONLY in
  `app/room/concentration.py` (`end_previous`/`break_link`/`on_damage`/
  `enforce_after_condition`); Save über `room.opposed.save_roll`; Anschluss in
  `room.health.change_hp` (DC auf tatsächlich verlorene HP, kein Cap) und
  `app/abilities.py` (neue Konzentration zuerst beenden, `conc`-Stempel). Keine
  zweite Concentration-Engine.
- **Flüche** sind DM-Autorisierung auf der Item-Instanz: `trigger` + `effects`
  (Wirkgrammatik) + `active`. WS `curse` bekam die DM-Aktionen `arm`
  (`trigger`,`effects`), `activate`, `deactivate` (`app/room/inv.py::handle_curse`,
  `app/inventory.py::curse_arm`/`curse_active` + Container-Varianten). `active`
  ⟂ `revealed`. `gear.clean_curse` speichert die neue Felder nur, wenn gesetzt
  (Omit-when-Default) → alte Flüche bleiben byte-identisch und inaktiv.
  `effectops.fire` behandelt einen aktiven Fluch als zusätzlichen Wirk-Träger
  (`ctx["src"]="curse"`); curse-origin-Fragmente gehen via `net.dm_whisper` nur
  an den DM; Owner-Ansicht bleibt `curse_view`-streng. `on_transfer` feuert beim
  Besitzerwechsel, geclaimt an der Transfer-`op_id` (atomar, kein Doppel-Feuer).
- **Grammatik v2:** `effectops` akzeptiert `v1`+`v2` (`V=2`, `V_MIN..V_MAX`),
  neuer `opposed`-Op (nur v2) über `room.opposed`; `canon()` erhält die Version
  des Cells. v3/unbekannt bleibt abgelehnt (closed world).
- **UI (Englisch):** `⚙ arm`, `🔮 active`/`💤 dormant` im Charakterblatt und im
  Container-Panel (`app/static/js/30_room.js`), `curseArm()` sendet `arm`.
- **Fallen (Phase 5):** Map-ENTITÄT (kein `traps.csv`), optionale Felder
  `effects`/`trigger`/`search_dc`/`disarm_dc`/`repeat` (Omit-when-Default → alte
  Fallen byte-identisch). `hit_trap` führt den `effects`-Cell über
  `effectops.run_ops` aus (kein `random.randint`). WS `trap`
  (`room/traps.py::handle_trap`): `search` (WIS/Wahrnehmung vs `search_dc`),
  `disarm` (DEX vs `disarm_dc`, nur bei enthüllter Falle), DM `trigger`.
  Leak-frei: Fehlsuche == leeres Feld; `disarmed` überlebt Editor-Snapshots.
  UI: Editor-Felder im Karten-Editor + 🔍/🔧-HUD am Token-Feld (`30_room.js`).
- **Vertikale Skala (Phase 7):** `app/vertical.py` ist DIE eine Quelle:
  `ELEV_FT=10`, `FLOOR_FT=10`, `elev_to_ft`/`floor_to_ft`/`absolute_ft`. Eine
  `elev`-Einheit UND eine deklarierte Ebenen-Stufe = exakt 10 ft. Die
  Ebenen-Reihenfolge ist der Höhen-Stack: `floors.level(room_id, name)`
  (Primär=0, +1 je weiterer Ebene) und `floors.absolute_height_ft(room_id,
  floor, elev_units)`. Rein Reporting — Ebenen bleiben unabhängig (D86/D88),
  Pfad gateert weiter |Δz| ≤ 1 in EINHEITEN, `elev`-Klammer bleibt -6..6,
  KEIN Höhenkampf (Sturz/Deckung/Flug bleiben D70/D83 aus). `55_diorama.js` tabu.
- Sprint 42 (D113, Phasen 2–7) erledigt; offen bleibt nur der menschliche
  Browser-Durchlauf der Phase-6-Oberflächen.
