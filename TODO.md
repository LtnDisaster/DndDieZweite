# TODO — D&D VTT (`/home/alp/Test`)

Living checklist. "Done" = shipped and covered by an in-repo test.
Verify state with:

```bash
docker compose run --rm test                     # CANONICAL: pinned py3.12 image — Sprint 20 close: 499 passed + 17 skipped (Sprint 21: see below) — py3.12 canonical (run with --build if the image predates the tests!)
./.venv/bin/python -m pytest                     # dev-host run (py3.14 venv) — GREEN at Sprint 16 close (431 collected)
./.venv/bin/python -m compileall -q app          # byte-compile check
for f in app/static/js/*.js; do node --check "$f"; done   # JS syntax check
```

## Done — features (context anchor)
- [x] Accounts / characters / rooms / join codes / chat / initiative
- [x] Server-authoritative dice, traps, loot, HP (D3, D6)
- [x] Grid editor, fog-of-war terrain patches, per-role map filtering (D4)
- [x] Two-click A* path planning + move HUD (D5, D7; server preview replaced the JS mirror in Sprint 4)
- [x] Strict radius-6 token event filtering and last-seen ghosts (D8, D9; true LOS in Sprint 4)
- [x] Armor & magic items: AC math, attunement cap 3, potions/heal, charges+recharge, identify/masking (D10-D13)
- [x] Weapon `+N` bonus, attack ability override, ability-on-any-roll (D12)
- [x] Rectangular footprints + in-place resize (`token_span`, D81/15B)
- [x] Visual size & rotation as pure presentation (`vw/vh/rot`, visual ≠ occupancy, D82)
- [x] World objects: data-driven allowlisted ops incl. linked doors (`interact`, D82)
- [x] Generic controller relationship (`authz.controls()`, companion foundation, D82)
- [x] Acyclic mount relationship (relationship layer only, D82)
- [x] Rotation ORIENTS the mechanical footprint, centre-preserved, illegal turns refused (D83, supersedes D82 facing clause)
- [x] Mount carrying: riders follow walk/teleport/forced/rotation, no own budget, collision-exempt pair, dismount re-home (D83)
- [x] Movement modes walk/fly/swim/climb: per-mode turn ledgers, fly = no difficult/cliff, swim/climb data-only foundation (D83)
- [x] Forced movement extracted to one server-side layer + riders carried; knock_prone op on the existing prone condition (D83)
- [x] Clicked cell = footprint CENTRE end-to-end; `center_to_anchor` single conversion rule (D84)
- [x] Secure PNG token artwork: re-encoded, opaque ids, no oracle, DM-curated assignment (D85)
- [x] Floors: independent occupancy/visibility planes; `token_floor` stairs; riders ride along (D86)
- [x] Darkness + per-token light radius: LOS-lit vision, real shadows, DM unrestricted (D87)

# Sprint 21 (privacy audit D91): canonical run with the NEW code DEFERRED at the hard stop
# (the prebuilt image was stale); host py3.14: 6/6 privacy + 110-suite regression + compileall green. Canonical: docker compose run --build --rm test
# → RETRO-VALIDATED 2026-10-09: Sprint 22's pre-change baseline canonical was GREEN (505 passed + 17 skipped).

## Done — Sprint 23: sheet → combat integration (2026-10-09)
- [x] **Item weapons are equipped data**: kind `weapon` + type-validated combat props (D93);
      one derivation `gear.weapon_profiles` feeds sheet AND attack path — client bonuses/dice are not read
- [x] **Server-side attack vs AC** in the existing roll engine: HIT/MISS + damage roll (DM applies
      via the existing hp flow, like npc_attack); range/plane gate; legacy by-name path untouched
- [x] **Action economy gets consumers**: `combat.spend_slot` first callers (attack action/bonus,
      only during active initiative; off-turn/used-slot refused; out of combat free — movement-gate semantics)
- [x] **Replay guards everywhere money moves**: inv_ops is the project-wide op ledger —
      attack/cast/resource/use_item op_id claims ride their mutation tx (cast re-reads slots in-tx)
- [x] **Peer sheet privacy**: /state member rows reduced to the tactical allow-list (D93);
      stats/items/spells/derived never ship to unrelated members; client renders a public card
- [x] **Server-derived sheet numbers** (`derived` block: mods, all skills, saves, initiative,
      profiles, attune cap) — client formula copies (legacy-level multiclass drift) removed
- [x] Canonical close: see git-less TODO footer run log (baseline 534+17 → +16 new tests)

# Sprint 23 (D93): canonical close run logged in this session; abilities.execute intentionally
# still WITHOUT turn-slot coupling (cost model = slots/resources; economy can attach later).

## Done — Sprint 22: inventory, equipment & loot (2026-10-08/09)
- [x] **Persistent quantities/stacks on the ONE item system**: `characters.items` entries gained
      `qty`/`weight`/`stackable`/`props`; split/combine/grant/remove in `app/inventory.py`, every
      mutation inside `db.tx()` with `inv_ops` op_id replay guard (D92)
- [x] **DM item definitions** (`item_defs`, `/state` DM-only) + grant/remove; ad-hoc items too
- [x] **Equipment slots** main/off/armor/acc1–3 (`characters.equipment`); legacy AC derivation
      untouched until a slot is worn; slots self-heal when an item vanishes (D92)
- [x] **World containers** as D82 objects (editor `container` op): contents ONLY in SQLite,
      reach+plane-gated inspect/take/put, atomic loot, dm_only/fog never leak, concurrent-safe (D92)
- [x] **Tactical UI**: 🎒 Inv tab (slots, stacks, equip, DM grant/def/remove), chest click opens
      contents with Take/Put/Fill; WS onopen refetch = fresh inventory after every reconnect
- [x] Canonical close: **534 passed + 17 skipped** (was 505+17; +29 new adversarial tests)

## Done — Sprint 20: cross-floor truth, security regression, browser foundation (2026-10-08)
- [x] **P0 cross-floor AoE/ping correctness** (closes D88's limitation, D90):
      `abilities.execute` resolves EVERYTHING (terrain, LOS, cover geometry,
      targeting, footprint frames, naming filter) on the **caster's plane** via
      the `net.get_map` seam; area targeting never sees other planes' tokens;
      a cross-plane single target is refused with the unknown-id message (zero
      oracle). Condition bumps for hidden tokens no longer ride the room-wide
      `cond` channel (`visibility.send_cond_bump`). Vision sources are
      plane-filtered at the shared choke points (`viewer_visible_cells` +
      `floor` param — a lantern on the attic never lights the crypt's map).
      `aoe` templates and `ping` are plane-scoped events: floor claim validated
      (DM any existing plane; players their own planes, token-less member keeps
      primary), bounds clamp to the plane's map, delivery via
      `net.send_to_plane_viewed`; client sends `viewFloor` and guards painting
      on it (`tests/test_sprint20_security.py` 12 tests, all families on live
      dispatch paths)
- [x] **P1 security regressions** riding the same suite: darkvision property
      sweep, asset serve/list across controller grant/revoke and token death,
      foreign/missing floor transitions refused in place, mount pair never
      split across planes, lamp state surviving refresh AND stale editor
      snapshots, hidden crypt token absent from `/state` token+ghost channels
      and live WS window
- [x] **P2 browser regression FOUNDATION** (`tests/test_browser_flow.py`): no
      browser runtime exists on the host (no Playwright/chromium) — documented
      fallback: the REAL client files run in a Node vm against the live
      WS/REST stack: tactical draw, real `tokenAt` on a 2×1 token, real
      `requestPathPreview` → live server → real `applyPathPreview` → real
      `confirmPlan` over the wire → walk to completion → refresh persistence.
      **No real browser was executed** — human checklist extended
- [x] **P3 map-editor resize**: `edResize()` silently dropped `pins` AND the
      `elev` layer from the editor snapshot (sanitize then legitimately
      emptied them) — pins now carry through bounds-filtered, elevation
      row-wise; a pin's plane association is preserved by construction.
      Node-vm functional test pins it
- [x] Pillow-era hygiene: `pings._hits` added to the conftest reset; canonical
      run **499 passed, 17 skipped** (the two new Node-vm suites skip inside
      the container — node is not in the test image)

## Done — Sprint 18: geometry truth, artwork, floors, darkness (2026-10-08)
- [x] **D84 centre-contract**: move/preview convert aimed-centre→anchor in one place (`footprint.center_to_anchor`, same tie-break as `anchor_for_center`, 1x1 bit-identical); preview echoes `goal`+`anchor`; DM drag drops at token centre; plan ring uses the server anchor; Escape deselects; footprint overlay is a dashed outline, not a colour block; controller/`/state`/`token_add` all carry the real geometry (the companion 3x7-as-1x1 bug); pointer math pinned by a node-vm harness running the REAL click path (`tests/test_geometry_contract.py`)
- [x] **D85 assets**: `app/assets.py` — magic+format+decode+re-encode gate (Pillow, pinned), size/pixel caps, metadata strip, random ids, per-user dedupe+quotas, 404-no-oracle serving with room-follows-token authz, `token_image` assignment stores only server-made refs, delete guarded while worn; artwork renders inside the rotate frame, aspect-kept, ellipse-clipped (`tests/test_assets.py`)
- [x] **D86 floors**: `tokens.floor` + DM floor list (REST + `floors_changed`); collision/preview/rotate/resize/forced-move filters per plane; per-viewer plane gating with add/leave re-evaluation; `token_floor` carries riders; sheet Floor row; canvas plane filter (`tests/test_floors.py`)
- [x] **D87 darkness**: `grid.dark` (explicit map_edit toggle, stale-snapshot-safe); `token_light` radius 0-30; dark vision = union of own lights' LOS-limited radii + own footprints; DM unrestricted; light changes re-evaluate every viewer + `grid_reveal`; light ring on lit tokens (`tests/test_lighting.py`)
- [x] Pillow pinned into requirements.txt (secure decode gate is the only image path); canonical py3.12 run green: **474 passed, 15 skipped**

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

## Done — DM fixes + NPC stat blocks (2026-10-02)
- [x] **Traps visible**: marker color is now actually applied — traps/loot render as a colored
      badge (DM always, players once discovered/taken), not an invisible dark-on-dark glyph (D21*).
- [x] **NPCs no longer lift fog**: fog reveal + `explored` broadcast gated to player-owned tokens
      in `movement` (NPC/DM-token moves still trigger traps/loot) (D25).
- [x] **NPC/enemy stat blocks on the token** (`tokens.npc` + `app/npc.py`): ability scores,
      HP/AC/level/speed, castable spells + per-NPC DM-tracked slots — DM edits them in the sheet (D24).
- [x] **DEX-aware for monsters**: initiative and hidden-trap saves use the NPC's real DEX mod, and
      NPCs now take trap damage on a failed save (`combat.token_dex_mod`, `traps.hit_trap`).
- [x] **NPC spell math reuses `gear`** via `npc.to_char` (spell attack / DC / damage / slots, no
      second implementation).
- [x] **DM-only by construction**: the `npc` block is stripped from token data for non-DM viewers
      in `/state` and `token_add` (verified by tests).
- [x] Tests: `tests/test_npc.py` (5) + integration (5) → 76 total; README/DECISIONS updated.

## Done — combat & map additions (2026-10-02)
- [x] **Conditions / status effects** (`app/conditions.py` SSOT, `tokens.conds` JSON): the 15
      canonical 5e conditions + homebrew, **round-progression** decrements timed ones on
      `init_end_round` and long-rest clears them; DM manages any token, players flag their own;
      Concentration shown as a dashed gold ring, other flags as colored canvas dots + sheet chips.
      Mechanical *effects* intentionally NOT auto-applied (D3). (`cond_add`/`cond_remove`) (D26)
- [x] **Death saving throws** for player characters (`tokens.death`, `app/room/death.py`): 5e
      3-success/3-fail with nat-20=n2 / nat-1=f2, damage at 0 adds a failure (+max-damage instant
      death), healing clears the state; owner or DM rolls (`death_save`), DM can `death_clear`. NPCs
      just sit at 0 HP. Canvas: red ring while dying, ☠ when dead, sheet 3×(✓/✗) box. (D27)
- [x] **NPC natural attacks** (`npc.attacks`): reusable attack list (`to_hit`/`dmg`/`dc`/`save`),
      `npc_attack` rolls d20+bonus **against the target token's effective AC** (PC's computed AC via
      `gear.compute_ac`, or another monster's AC), auto-rolling damage on a hit; Dmg-only and
      DC-post modes too. DM-only, reuses the dice/post infra. (D28)
- [x] **Doors** in the map model (`mp["doors"]`, `app/mapmodel.py` + `app/room/doors.py`): placed
      on cell edges in the map editor (🚪 brush), closed/locked state; **a closed/locked door blocks
      the pathfinder** (`blocked_edges`, both server `path.py` and client `findPathJS`); DM opens/
      closes/locks/removes any door, players may only **open/close an unlocked door they're next to**
      (server-enforced adjacency). Rendered as a leaf + 🔒 on the canvas. (D29)
- [x] **AoE targeting templates** (`app/room/aoe.py` relay + client `aoeCells`): burst/square/line/
      cone at a chosen size/direction, **purely visual** — relayed to everyone for ~7s, no game
      resolution (D30). DM-only.
- [x] **Bestiary engine** (`creatures` table + REST `/api/creatures` CRUD + `save-to-bestiary`):
      each user owns reusable, **generic** monster templates (the NPC block is the data model);
      Spawn drops one on the map via `add_token`. No copyrighted stat catalog (D31).
- [x] Tests: conditions/death/doors/aoe/bestiary unit + integration → **95 total**; docs updated.

## Done — table QoL & information control (2026-10-02)
- [x] Corrected 5e death saves (nat-20 restores 1 HP / clears dying; nat-1 remains two
      failures; massive damage only after defensive reduction) and centralized PC/NPC HP,
      temp HP, typed damage and death-state behavior in `app/room/health.py`.
- [x] **Game log** with server-side `public` / `self` / `blind` / `dm` visibility and separate
      Chat / Game Log tabs; `/state` and live delivery both filter before transmission.
- [x] Generic dice now support `kh` / `kl` (`2d20kh1`, `4d6kh3`, modifier before or after
      the keep clause), plus quick dice and a modifier input.
- [x] ADV / DIS controls added to the dice bar and character sheet; rolls remain
      server-computed and no `eval()` or client-authoritative math was introduced.
- [x] Server-authoritative saving throws: save proficiency is stored on characters and
      recomputed server-side; the client `prof` flag cannot grant save proficiency.
- [x] Short rest (owner/DM), DM long rest, hit dice, custom long/short-rest resources,
      inspiration and 0–6 exhaustion. Long rest preserves conditions unless explicitly
      requested.
- [x] Temporary HP absorbs damage first, with owner/DM controls; typed damage supports the
      13 standard 5e types and resistance/vulnerability/immunity for PCs and NPC blocks.
- [x] Private per-DM encounter templates and one-call spawn from the saved bestiary.
- [x] Room journal/handouts with DM-only, party and selected-user visibility filtering.
- [x] Map pins with DM / players / reveal-when-explored visibility, pings with server-side
      rate limiting, and a two-click client ruler.
- [x] Token size and disposition fields; NPC dispositions stay DM-only.
- [x] Explicit half / three-quarters / total cover handling for player attack rolls.
- [x] Tests: deterministic death saves, visibility, keep dice, saves, typed damage, cover,
      rest/resources/status, encounters, journals, pins, pings and DM-only disposition data
      → **113 total**.

## Done — narrative chat & atmosphere (2026-10-02)
- [x] **Server-side chat model**: global, DM and whisper channels are persisted with
      `channel`, `visibility`, `recipient_ids`, `persona`, `sender_kind` and `npc_token_id`;
      recipients are resolved server-side and private payloads are never broadcast and hidden.
- [x] **DM personas and NPC speech**: DM can speak as self, a narrative persona or an existing
      NPC token; persona names matching a room member are rejected, unknown NPC targets are rejected,
      and players cannot forge NPC/persona provenance.
- [x] **Temporary narrative overlays**: DM can send public or private narrative/voice messages;
      they are stored in Chat history and shown as a centered timed overlay.
- [x] **Secret events**: compose private narrative plus an optional DM soundboard effect and send
      both to one player or everyone; recipient selection remains server-side.
- [x] **Ambience sources**: DM can add/remove/play/stop room ambience from direct HTTP(S),
      YouTube or Spotify URLs. The server re-parses URLs, builds fixed `youtube-nocookie` /
      Spotify embeds, rejects unsafe/malformed URLs and returns room audio state on reconnect.
- [x] **Selective sound effects**: private per-DM soundboard requires direct audio URLs and can be
      targeted to one player or all; soundboards are never exposed to other users.
- [x] **Local player audio controls**: volume and mute persist in `localStorage` without changing
      room-wide ambience state.
- [x] **Chronicle split**: Chat and Game Log are separate feeds; Chat uses unread badges/collapse
      controls and the Game Log excludes chat/narrative rows at the DB query boundary.
- [x] `AGENT_GUIDE.md` added as a repository map; it explicitly defers to the implementation
      wherever the guide has drifted.
- [x] Tests: chat/whisper/persona/NPC/narrative/secret-event privacy (9) + URL/soundboard/
      selective-audio security (7) → **129 total**.

## Done — foundations: footprints, LOS, fog, movement and path preview (2026-10-02)
- [x] **Multi-cell footprints** (`app/footprint.py`, D43): Tiny–Medium 1×1, Large 2×2, Huge 3×3,
      Gargantuan 4×4. Token `x/y` is the top-left anchor; spawn, teleport, size changes and final
      movement validate the complete footprint.
- [x] **Footprint-aware server A*** (D43): Large+ tokens cannot use one-cell corridors or leave the
      map edge; wall transitions, closed-door edges and difficult terrain are evaluated for the whole
      footprint. Different owners cannot finish overlapping; same-owner pass-through remains possible.
- [x] **True wall/door LOS** (`app/los.py`, D44): deterministic DDA visibility from every footprint
      source cell. Walls and closed/locked doors block sight, while conservative diagonal-corner rules
      prevent sealed-corner leaks.
- [x] **LOS-aware persistent exploration**: live token filtering, fog reveal and `visible_map` share
      the server result; NPC/DM movement still does not lift player fog. Opening a door recalculates
      and reveals what players can now see.
- [x] **DM manual fog tools** (`fog_edit`, D45): map-editor reveal/re-hide brushes plus a working
      reset-fog option. Hiding persistent memory does not corrupt current LOS visibility.
- [x] **Movement control**: active walks broadcast `move_state`; DM can stop a walk; trap triggering
      automatically stops at the trap cell. The UI shows a moving-token ring and DM-only stop button.
- [x] **Server path previews** (D46): players preview only their own token; server checks footprint,
      collision, doors and currently known cells before drawing a route. Confirmation recomputes the
      authoritative path independently.
- [x] **Docs correction**: death-save nat-20 now correctly documented as restoring 1 HP and clearing
      dying; old square-LOS/footprint roadmap items were marked superseded.
- [x] Tests: footprint path/collision (12), LOS (9), movement/fog/path-preview (11)
      → **162 total**.

## Done — view renderers & hardening (2026-10-02, Sprint 5A/5B)
- [x] **Client-local Tactical/Diorama views** over one shared world (D47): a single `draw()`
      dispatcher, isometric `drawDiorama()`, per-browser `localStorage` preference, never sent
      to the server. Diorama reuses the server's per-viewer visibility mask.
- [x] **Diorama footprint reveal parity:** a Large+ token renders if ANY of its footprint cells
      is visible, matching the server's any-cell reveal rule (was origin-cell only).
- [x] **Licensing boundary** (`ATTRIBUTION.md`, README, AGENT_GUIDE §12): SRD 5.1 under CC BY 4.0
      with the verbatim attribution statement extracted from the official PDF; explicit DO-NOT-COPY
      list. Human legal review still recommended before public release.
- [x] **Door adjacency fix:** a player may toggle an unlocked door beside ANY token they own
      (`_player_cells`), not just the arbitrary first one — matters for legacy multi-token rows.
- [x] **Cross-system + adversarial regression suite** (`tests/test_hardening.py`, 8): door×LOS×
      persistent-explored cycle, stale-preview-is-not-authority, DM-stop-leaves-no-orphan-walk,
      out-of-map coordinate clamp, player-socket DM-only refusal, foreign-character temp-HP
      refusal, malformed-payload survivability. Reused the existing Node-`vm` view guards.
- [x] **Coupling audit** (D49): transport confirmed thin; no speculative extraction; future
      automation must call the pure gameplay helpers, never a WS handler.
- [x] Tests: +8 hardening +1 view guard → **178 total**.

## Done — mid-walk route revalidation (2026-10-02, Sprint 5C)
- [x] **No more phasing through freshly-invalid geometry** (D50): `walk()` revalidates every
      step against the CURRENT map (bounds, walls, footprint cells, closed/locked doors) via a
      new shared `path.step_legal()` extracted from `find_path`'s own rules. An illegal step is
      never applied — the walk ends with `move_state reason:"path_blocked"`, the mover gets a
      private `error`, and the token holds its last legal cell. Validation + the position write
      run under the existing `map_lock` that door/map edits already hold, so a change can't
      interleave between check and apply. Traps, DM-stop and one coherent walk lifecycle intact.
- [x] Tests: door-closed-midwalk + wall-painted-midwalk → **180 total**.

## Done — automation foundations: quests, events, classes, effect geometry (2026-10-02, Sprint 6)
- [x] **Quest Log** (D51): `quests` table + pure ops (`app/quests.py`) + thin WS
      transport (`room/quests.py`); objectives, `active/completed/failed/hidden`,
      `party|dm` visibility + hidden objectives — all filtered server-side in
      `visible_for()` (live AND `/state`). Panel in the sidebar; DM controls inline.
- [x] **Notices** (D52): quest changes post game-log system lines with visibility
      bound to the quest (DM-only quest ⇒ DM-only notice). Presentation only —
      reconnect rebuilds from `/state`.
- [x] **Game-event seam** (D52): `app/events.py` plain-dict facts emitted AFTER
      state commits; wired: door_opened/closed/removed, trap_triggered,
      quest_started/updated/completed/failed. Future triggers must call game
      operations, never fake WS clients. NOT built: trigger engine, persistence, bus.
- [x] **Multiclass-ready progression** (D53): `characters.class_levels` JSON
      collection; strict validator (whole-payload reject); `total_character_level()`
      the one derivation; legacy `level` kept in sync; `gear.prof_bonus()` derives
      from it. WS `class_levels` (owner or room-DM). No class content/tables (licensing).
- [x] **Generic effect geometry** (D54): `app/effects.py::effect_cells()`
      (point/line/cone/circle/square) + Node-vm parity test against client `aoeCells`.
      No spell catalogue.
- [x] Tests: quests 7 + progression 8 + effects 6 → **201 total**.

## Done — generic ability engine (2026-10-02, Sprint 7)
- [x] **Ability definitions as data + ONE executor** (D55): `app/abilities.py`
      (registry + `clean_definition` + async `execute()`); WS `ability_cast` is a
      thin transport; triggers/AI will call the same operation (no ws object in core).
- [x] **Canonical derivations** (D56/D57): `gear.stat_mod`, `ability_save_dc`,
      `ability_attack_bonus` (+optional bonus); casting ability is configuration.
- [x] **Save/attack/auto resolution** through existing dice/saves/AC; crit doubles
      dice; save-half floored before defense; NO second damage/condition/concentration engine.
- [x] **Slots & generic resources** ride existing columns; all-or-nothing consumption;
      `cast_level` upcast extension point (consumption only, no scaling).
- [x] **Authority**: range (Chebyshev×5ft), LOS flag, footprint-intersection targeting,
      hidden tokens counted-not-named to players (D59). 18 tests in `test_abilities.py`.
- [x] **Explicit architecture guard** (D58): slot progression must NOT derive from
      `total_character_level()` — documented, not implemented.

## Done — stability & table UX sprint (2026-10-05, Sprint 8, D60)
- [x] **Test infra:** bcrypt-5/3.14 TestClient deadlock fixed (`_fast_bcrypt` conftest fixture);
      `recv_until(..., fail_on_error=)` turns silent WS hangs into loud failures;
      five latent fixture bugs fixed.
- [x] **Diorama/Tactical parity (D60):** confirmed-path mismatch → `route_invalid` refusal instead of
      silent reroute; diorama clicks resolve in ONE camera space; double-click and all armed DM tools
      work view-aware. `test_diorama_parity.py`.
- [x] **Downed gate:** 0-HP blocks preview/move/teleport AND every walk step (`stop_reason:"downed"`);
      NPC corpses stay DM-draggable by design. `test_downed_movement.py`.
- [x] **Trap lifecycle:** `triggered`/`triggered_by` = one-shot re-entry gate beside `discovered`;
      map edits (stale snapshots AND resizes) preserve runtime flags; fixed a real
      `handle_map_edit` indentation bug that silently dropped every map save without traps.
      `test_trap_lifecycle.py`.
- [x] **Fog-off room flag:** `fog_toggle` persists `fog_off` in the map — terrain+static entities to
      all members, live foes stay LOS-filtered; editor snapshots cannot reset it. `test_fog_off.py`.
- [x] **NPC workflow:** renderSheet crash fixed (`ch.class_levels` on NPC tokens); `abilities`/
      `resources`/`notes` persist through add_token/update_npc/Bestiary/spawn; long rest refills
      monster slots+resources; fixed duplicate `npc-name` DOM id collision (DM-tools add vs sheet).
      `test_npc_workflow.py`.
- [x] **Sidebar tabs:** Game/Chars/Story/DM groups over the panels, chat+context sheets pinned,
      per-user localStorage.
- [x] **Audio pause:** distinct `audio_pause` state (source kept); direct sources resume in place per
      client, embeds restart (labeled). `test_audio_pause.py`.
- [x] **Help overlay:** `?` button + `<kbd>` overlay (Esc/backdrop close), content-only, no framework.
- [x] Deferred by decision: guided tutorial tour (until this sprint is field-stable), per-player fog
      schema, resumable walk queue.

## Done — gameplay & world sprint (2026-10-06, D66–D71)
- [x] **DM Game Log growth on rolls** — content-based flex basis replaced by
      zero-basis chain (`flex:1 1 0` + overflow guards + chat-only composers);
      pins extended in `test_layout_pins` (1A).
- [x] **Modifier matrix** — `gear.as_sheet()/as_row()` choke points; PC save/skill/
      spell paths no longer fed raw JSON-string rows (silent +0 bug fixed);
      PC≡NPC `_stat_mod` parity; `test_modifier_matrix` (8).
- [x] **Automatic world growth** — chunk-12 map extension for exploring players,
      fog/entity re-anchoring, `map_expanded` + camera compensation, cap 80×60;
      `test_map_expand` (8) (D67).
- [x] **Movement cost SSOT** — `app/movecost.py` 5e diagonals + budget on the
      preview (`cost/budget/within_budget`), A* weights untouched; `test_movecost` (8) (D68).
- [x] **Movement modes** — `gear.clean_speeds` (walk/fly/swim/climb), NPC blob +
      editor fields, walk stays budget currency; `test_speeds` (3).
- [x] **Terrain registry** — cells 3 barrier / 4 low obstacle end-to-end
      (registry → path/los/footprint/movecost → editor brushes), `wall.py` facade;
      `test_terrain` (8) (D69).
- [x] **Elevation foundation** — integer `elev` layer (-6..6, fog-gated, grown with
      the world) + `tokens.z`; |Δz|≤1 step rule; token rests on ground;
      `test_elevation` (5) (D70).
- [x] **Forced movement foundation** — `room/moveforced.py` DM-only push/pull/
      shove/knockback/throw/teleport; obstacle stop + z sync; no walk/budget/growth;
      `test_forced_move` (3) (D71).
- [x] Host suite 313 / canonical 306+7 skipped; MANUAL_FIX_NOTES checklist (browser).
- [ ] **FOUNDATION ONLY (next sprints):** fly/swim/climb path rules; elevation-based
      cover/LOS and multi-floor maps (explicitly OUT); forced-move combat
      integration (opportunity/impact damage); enforced per-turn budget (now only
      shown, not rules-enforced); diorama rendering of barrier/low/elevation.

## Done — sidebar layout fix: chat/log/dice overlap (2026-10-06, D65)
- [x] Root causes: faked `calc(100vh-topbar)` viewport + single-scroll sidebar
      (chronicle min-220px vs. 4-row dice strip outside its scroll body) +
      sticky category bar overlaying content. All removed, not re-layered.
- [x] Flex app-shell; `.side` = tabs/chronicle/`.side-cat` drawer (bounded);
      feed tabs Chat|Game Log|Dice single-surface; `#dice-out` results;
      feed persisted; all legacy ids kept; 6 static pins (`test_layout_pins`).
- [ ] **Human browser verification (checklist in MANUAL_FIX_NOTES.md)** —
      gates the spatial/movement sprint.

## Done — deployment & UX hardening (2026-10-05, Sprint 9, D61–D64)
- [x] **Root causes:** (a) starlette-1.7 per-session loops vs. anyio cross-loop wakeups
      → lost WS events / suite hangs; fixed loop-safely in `net._send` + `attach_ws` (D61).
      (b) base64 `=` padding in session cookies → parsers dropped the cookie → real
      intermittent production 401s; fixed padding-free (D62).
      (c) `_secret()` generate-raw / read-stripped → ~1.6% of installs signed with a key
      that mutated after first write; secret.key now hex-stored (D62). Suite no longer hangs.
- [x] **Docker canonical runtime:** multi-stage Dockerfile (runtime + test), compose
      services `app` (loopback bind, healthcheck, unless-stopped) + `test` (profile),
      exact dependency pins incl. previously MISSING `websockets` package, `DOCKER_BUILDKIT=0`
      fallback documented (host lacks buildx).
- [x] **Persistent VTT_DATA_DIR:** uploads moved out of the app tree, same `/uploads/`
      URLs, `scripts/move_uploads.py` for legacy installs; verified by `test_deploy_hygiene`.
- [x] **Backup/restore:** sqlite backup-API (WAL-safe + integrity_check) bundling
      db+secret.key+uploads; restore keeps previous db, clears stale WAL, verifies.
- [x] **Hardening:** X-Forwarded-* trust gated by VTT_TRUST_PROXY; WS same-origin gate +
      VTT_ALLOWED_ORIGINS (4403); README deployment section (Caddy+Nginx), single-process
      warning prominent; compose smoke: healthy + data survives `--force-recreate`.
- [x] **DM doors:** `dm_only` + `secret` flags end-to-end (sanitize, per-viewer map,
      handler auth, editor checkboxes, ghost rendering for DM); `test_doors_dmonly` (10).
- [x] **UI pass 2:** CSS tokens + merged duplicate `.wlabel` + defined `--muted`;
      sticky sidebar tab bar (aria-selected); DM tools in collapsible groups; NPC sheet
      sectioned (all ids preserved); PC sheet details; toast above movehud; help content.
- [x] **Hygiene:** `.dockerignore`, `.gitignore` additions (archives/Zone.Identifier/
      compose overrides), `scripts/make_release.sh` with post-archive forbidden-path check.

## P1 — Repo hygiene
- [ ] Add a `Makefile`/`scripts/smoke.sh`: start (pidfile) -> live `vtt_smoke*.mjs` -> stop
      (the `.mjs` suites stay a **dev-only** live-server harness; `pytest` is the durable suite).
- [ ] Pin exact Python/FastAPI/uvicorn/starlette versions (`requirements.lock`) for reproducible CI.
- [ ] Optional CI job: `pytest` + `compileall` + `node --check` on push.

## P2 — Known soft spots (call out before touching)
- [ ] **Path preview latency:** `findPathJS` was removed and movement is now server-authoritative.
      Remaining drift risk is UI formatting only; add a browser e2e test for async preview requests.
- [ ] **Ghost persistence:** `_last_seen` is in-memory (D9) — lost on restart, wrong under
      multi-worker. Persist to `room_state`/DB before scaling beyond one process.
- [ ] **Multi-token per user:** ownership is one-token-per-user by construction (assign reuses),
      but nothing enforces it in the schema; door adjacency now handles legacy multi-token rows
      (D49 era). Decide explicitly before adding a feature that creates second tokens.
- [ ] **Fog granularity:** exploration is one shared room bitmap. Manual reveal/hide is global to all
      players; private per-player fog requires a schema change.
- [ ] **Client math mirror:** the browser mirrors gear skill/spell bonus math (`_smod`/`_pb`
      in `js/10_core.js`) for previews only; the server recomputes authoritatively — keep the
      two in sync (same drift risk as the A* mirror in P2).
- [ ] Re-run the live suite 1 after ANY default-grid/token-position change (D15: movement
      tests are vision-adjacent).

## P3 — Feature gaps (nice, not blocking)
- [ ] **Ability content pipeline:** the registry ships empty — tomorrow's work is
      DATA (named spells/class/monster abilities via `abilities.register()` or an
      import format), known/prepared-spell lists per character, class-specific
      casting-ability defaults as data, upcast EFFECT scaling (dice growth) on the
      existing `cast_level` seam, concentration break-check on damage (the state
      flag exists; no auto CON-save fires today — none existed before either).
- [ ] **Quest/automation follow-ups (Sprint 6 seams, intentionally not built):** per-player
      quest visibility (reuse a `recipients` list like notes), objective counters, the
      trigger engine over `app/events.py` (condition → game operation), quest-condition
      auto-completion, XP progression.
- [ ] **Class follow-ups:** progression editor UI (currently WS+read-only sheet line),
      per-class hit dice/resources/spellcasting attached to `class_levels` entries,
      multiclass prerequisites. Subclasses/feats/feature tables: engine-only, licensing-gated.
- [ ] **Effect resolution:** abilities with `save`/damage-expression/duration riding on
      `effects.effect_cells()` (schema fields documented in D54, no spell catalogue).
- [ ] **Map visual metadata + richer vision (directions, not commitments):** floor/wall materials,
      elevation, sprite/rotation/scale/layer and per-object blocks-vision/movement should extend
      `mapmodel.sanitize()` inside `map_json` (D48), never speculative DB columns; light/darkvision
      layers come after that foundation. Both renderers then consume the same metadata (D47).
- [ ] Collision currently validates different owners at the final destination. Intermediate animation
      may temporarily overlap same-owner tokens and should be re-checked if stricter token stacking is
      ever desired.
- [ ] Trap-triggered and manually stopped walks currently require a fresh movement command; a resumable
      walk queue could reduce re-clicking without changing server authority.
- [ ] Direct audio URLs are browser-fetched and intentionally not allowlisted; an optional
      SSRF/private-network/hostname policy would tighten this without removing local files.
- [ ] YouTube/Spotify playback depends on third-party autoplay policy; direct audio is the most
      reliable channel for selective/private effects.
- [ ] Consumable potions (remove on last use) — currently charges-only, potions aren't deleted.
- [ ] Attunement UX: warn/gate attuning to an *unidentified* magic item.
- [ ] Per-party (vs per-item) knowledge of identified items; party shared notes.
- [ ] Cross-tab / reconnect: seed ghosts more robustly; multi-socket-per-user testing.
- [ ] Browser e2e (Playwright) for canvas: route preview + ghost rendering — the JS split is
      verified by parity + `node --check` + the WS/REST suites, **not** by a real DOM/canvas test.
- [ ] NPC blocks now cover abilities + HP/AC + spells (D24) **and natural attacks + a bestiary**
      (D28/D31). Remaining extensions: monster items/skills, lair/legendary actions, and a curated
      (non-copyrighted) starter bestiary seeded on first run.

## Watch / intentionally not done
- [ ] Horizontal scale-out (blocked by D9 + single-loop design).
- [ ] No build step introduced on purpose (D1) — don't add a bundler/module loader without
      revisiting D1 and D20.
- [ ] Auth is single-tenant local; no OAuth/2FA planned.

## Done — Sprint 24: hardening audit (2026-10-09, D94)
- [x] F1 TOCTOU: attack profile+token re-read inside the claim tx (dice.py)
- [x] F2 hidden-target probing oracle closed; error byte-identical to nonexistent
- [x] F3 inv_ops namespaced per acting char/object (no migration)
- [x] tests/test_sprint24_hardening.py (7 live-dispatch adversarial tests)
- [ ] DEFERRED: live range/reach pin (harness grant-of-2nd-def flaky — server
      gate itself implemented; skip marker carries the reason)

## Done — Sprint 25 Phase A: CSV content packages (2026-10-12, D95)
- [x] `app/content.py` — ONE content engine: 8-kind schema (species/class/subclass/
      item/spell/background/feat/creature), parse/validate(file/line/column),
      idempotent apply + conflict/replace, ZIP auto-detect, export with formula
      escaping; **no code executed from CSV**; size/row/zip-bomb guards.
- [x] Reuses the engines (no second engine): items→`item_defs`(typed combat props,
      `weapon_profiles` reads range), spells→`abilities.register` (slot cost),
      everything else read back from `content` (Phase B/sheet). Restart-safe
      (`main.startup` re-registers abilities from the DB).
- [x] `content` table `(kind,room_id,id)` in `db.py` (additive; room 0 = global).
- [x] `app/content_api.py` — DM-only REST `/api/content/{code}` import(preview/apply/
      replace)/export(one|zip)/kinds; raw-body transport (no python-multipart).
- [x] `app/content_pack/*.csv` technical pack (original names; ATTRIBUTION.md).
- [x] DM "📚 Rule packages" panel + `app/static/js/70_content.js` (registered in the
      D78 integrity gate). Guide: `docs/CSV_CONTENT_GUIDE.md`.
- [x] `tests/test_content.py` + `tests/test_content_examples.py` (16 doc examples
      imported by the real importer). **Canonical (py3.12): 593 passed, 18 skipped.**
- [ ] **PHASE C:** known-vs-prepared spell model; slot-progression TABLE (D58).

## Done — Sprint 25 Phase B: chronological character build (2026-10-12, D96)
- [x] `app/charbuild.py` — pure `plan()`/`apply()` Stufe 1–20 from D95 content;
      drives ONLY the existing engines (`progression.set_class_levels`, HP from
      `hp_base`/`hp_per_level`, `gear.clean_saves/clean_skills`, ASI/feat→`stats`).
      No second engine; slots never derived from total level (D58).
- [x] Additive `characters.build` ledger (class, applied_through, subclass,
      per-level decisions, `base_stats` snapshot). Idempotent forward recompute;
      missing choices → `needs_choice` writes nothing; rebuild ≤ applied_through refused.
- [x] `app/charbuild_api.py` room-scoped `/api/build/{code}/{cid}` plan/apply;
      authz mirrors `class_levels` (owner / room-DM via `room_members`).
- [x] Room-sheet "⬆️ Build / Level-up" section (generic; renders chronology, POSTs
      choices; no class logic in the client).
- [x] `tests/test_charbuild.py` (Stufe 1/8/20 chronology, subclass/ASI/feat on
      their levels, needs_choice no-write, repeat/forward guard, restart ledger,
      owner-vs-DM-vs-outsider authz).
## Done — Sprint 25 Phase C: class spellcasting through the existing engines (2026-10-12, D97)
- [x] Content schema additive: `spell_first_level`/`spell_replace`/`class_resource_reset`
      (class) + `scale_tiers` (spell); `slot_progression` is now a per-class-level
      **TABLE the build READS** (never derived from total level, D58).
- [x] `charbuild`: known-model classes CHOOSE at each total-delta level
      (`needs_choice`), prepared-model use the class list; writes castable
      `abilities`, display `spells`, the slot table and `class_resource` → the
      generic `resources` list. Non-casters write none of the spell columns.
- [x] `abilities.execute`: `cast_level` (upcast `upcast_step`) and cantrip
      `scale_tiers` applied generically into the ONE base dice term; `op_id` is
      claimed up-front inside the write tx → one slot and one effect per request.
- [x] `handle_long_rest` also refills short-reset class resources (long ≥ short).
- [x] Sheet spellbook: registered spells cast via `ability_cast` (+ upcast level
      select), AoE aimed from the map; `gear.clean_spells` carries `targeting`.
- [x] Pack templates `adept`/`warden`/`seer` + `scale_tiers`/`upcast_step` spells.
- [x] `tests/test_spells.py` — models, slot-table-vs-total-level, choice no-write,
      forward idempotency, resource reset, upcast/cantrip scaling, dup-op_id guard.
## Done — Sprint 27 Phase D: weapons, equipment & magic items through the one engine (2026-10-12, D98)
- [x] `gear.effective_gear` — a DERIVED, transient equipment overlay (stats/sets/
      darkvision/speed) consumed by `_stat_mod`/`skill_bonus`/`save_bonus`/
      `compute_ac`/`clean_speeds`/`weapon_profiles`; never persisted, base stats
      never mutated (equip/unequip/restart can't double-apply or go stale).
- [x] `gear.clean_props` = THE single prop validator (DM defs + content import).
      Five bonus scopes distinguished: per-weapon, general (`attribute_*`),
      while-equipped, while-attuned (`attune` gate → inert until attuned), on-consume.
- [x] Weapons: one/two/versatile grip (`inv_grip`, off-hand cleared atomically, dice
      chosen), finesse/ranged ability choice, ability-mod-to-damage default,
      `extra_damage_dice/_type`, long-range tiers (≤normal ok / ≤long dis / beyond
      invalid, advantage cancels), `ac_base`/`ac_bonus`/`ac_max_dex` in AC.
- [x] `items.csv` additive: `hands`; `charges`/`recharge`/`attune`/`heal_dice` now
      projected into the definition and promoted onto the inventory entry.
- [x] Sheet + DM editor (browser): item-definition editor (kind/grip/dice/range/AC/
      attribute/grant/magic + `✎ Edit` reload), grip toggle, effective speed +
      darkvision, gated 🔒, longer/extra damage shown; legacy math byte-identical.
- [x] `tests/test_weapons_gear.py` + `tests/test_content_examples.py` (ranged,
      attribute bonus/set, multi-effect). Docs: D98, CSV guide (items section 4.4 +
      section 7 + examples), AGENT_GUIDE, MANUAL.

## Done — Sprint 28 Phase E: currency, carrying & companions (2026-10-12, D99)
- [x] Currency: ONE server-owned integer of **copper** (`characters.wallet`),
      `gear.CURRENCIES` data table (cp/sp/ep/gp/pp, coin weight 0.02 lb),
      `to_cp`/`cp_breakdown`/`cp_label`; a client sends only (int, coin) → never
      mints gold. DM grant/deduct, player→member **transfer** (atomic, replay),
      container **loot** (`coins_fill`/`coins_take`, one object-namespaced claim);
      no-negative rollback; all through `inventory.py` + `op_id` replay.
- [x] Encumbrance: DERIVED (`gear.encumbrance`) — `qty×weight` per distinct stack
      (equipped counted once, never double), coins weigh the shown split, capacity
      = effective STR × `CARRY_PER_STR`(15) × `SIZE_CARRY` × + worn `carry_bonus`.
      `overloaded` is a WARN only — no movement penalty yet. `characters.size` +
      `items.carry_bonus` additive.
- [x] Companions = existing tokens with `owner_user_id`/`character_id` (DM binds in
      `add_token`); control via D82 `token_controller` (DM-only, room member),
      riding via `token_mount`; a player can never seize a foreign companion and
      only sees already-visible tokens (no hidden/other-plane leak).
- [x] Sheet collapsibles (Wallet / Encumbrance / Companions) + DM grant/deduct +
      container coin row; reload-stable (all derived, server-rendered).
- [x] `tests/test_money_encumbrance.py` (18) + `tests/test_content_examples.py`
      (carry_bonus example). Docs: D99, CSV guide (section 8 + items `carry_bonus`
      + example 15b), AGENT_GUIDE, MANUAL.
- [ ] **PHASE F (next):** overload MOVEMENT penalty (once fully specified/tested);
      content-configurable currency rate table; DM item-editor `carry_bonus` field;
      short-rest charge recharge.

## Done — Sprint 29 Phase 1-5: Operation Integration (2026-10-12, D100)
- [x] **G7 atomic cost:** op_id claim + slot/resource spend folded into ONE
      `db.tx()` (`_cast_gate`, `app/abilities.py`); refused cost rolls the claim
      back. Pinned by a synchronous thread-hammer (`_cast_gate`, max=1 → exactly 1
      success), not the flaky async engine.
- [x] **D100 autonomy lock:** editor `PUT /characters/{cid}` no longer writes
      `level`/`spells`/`spell_slots`; raw `class_levels` WS is DM-only. Validated
      `charbuild.apply` (owner/DM) + DM advance preserved; ordinary sheet fields stay
      editable; no data migrated. `test_progression.py` / `test_sprint23_combat.py`
      updated to stage authorised fields via the legitimate writers (`set_progression`).
- [x] **G5:** non-DM `long_rest`/`short_rest` now returns an explicit error (no silence).
- [x] **G8b:** `npc._clean_abilities` keeps a bare string ability id alongside prose, so
      a familiar made through the real `add_token` path stays castable by its controller.
- [x] **G9/A13:** `item_defs` create + CSV projection REFUSE a cross-room id collision
      (global PK kept, no destructive rebuild); reads/delete/grant already room-scoped;
      room-scoped `content` row still stored. Tests read `item_defs` by ROOM+id.
- [x] **Node 22 in the test image** (`COPY --from=node22 /usr/local/bin/node`, test
      stage only; no npm, no runtime change) → the ~17 node-gated parity/diorama tests
      run the real shipped JS instead of skipping.
- [x] **C1** WS flush-barrier in the mount/floor test (kills the historical flake);
      **C2** room-qualified `containers`/`item_defs` test queries.
- [x] `tests/test_d100_integration.py` (10): green end-to-end flow + each fix pinned.
      Local suite `682 passed, 0 failed`. Docs: D100, AGENT_GUIDE (hazards), MANUAL.
- [ ] **Follow-ups (honest limits):** per-room `item_defs` key (needs a schema rebuild —
      now refused, not fixed); server-authorise ability SCORES/saves (still owner-editable
      sheet fields, no confirmed exploit); `POST /characters` stays the trusted authoring/
      seed surface; content-configurable currency table (carried from Phase E).

## Done — Sprint 30 Phase 1-4: D101 Room Preparation & Guided Build (2026-10-13, D101)

- [x] **Room preparation screen** (`#view-prep` + `app/static/js/80_prep.js`, D78-stamped,
      in `MODULES`/`REQUIRED`): create/join/room-click land here; DM sees rule-pack status +
      CSV import (reuses `ctPost/ctRender`) + roster; player picks/creates a character,
      prepares, seats it and opens the table via the EXISTING `openRoom()`. Table back →
      `backToPrep()`; lobby "Bring" shortcut untouched. No server-side "phase" invented.
- [x] **`GET /api/content/{code}/options`** — room-member-readable id+name catalogue of the
      room's rule pack (class/subclass level-rows collapse per id); drives every dropdown.
      import/export/kinds stay DM-only; names only, never row payloads.
- [x] **Guided build wizard** derives ALL fields from `charbuild.plan` `needs` (skills,
      subclass, per-level feat/ASI, known-model spell picks), labels ids via the options
      catalogue, counts missing decisions, refuses nothing client-side — the server stays
      the validator. Raw choices JSON remains as opt-in EXPERT mode; unsupported decision
      types are flagged visibly there, never skipped. No hardcoded class lists.
- [x] **`characters.background`** (additive column; `None` on PUT = keep stored value so
      legacy lobby saves cannot wipe it) + **`POST /api/rooms/{code}/starting-gear`**:
      background `starting_items` granted through `app/inventory.py` only, per-room
      item-def resolution, unresolvable CSV text REPORTED as skipped, deterministic
      `op_id` → replay answers "already" (no double grant). Authz mirrors the build API.
- [x] **The confirmed reload bug is fixed at both ends**: `build_apply` broadcasts
      `snapshot` (all clients refresh + re-render sheets, DM included) AND the sheet's
      apply handler re-renders the selected token locally after `refreshRoom()`.
      No browser reload needed; pinned server-side and as a UI regression assert.
- [x] **Latent bug fixed:** re-seat of a user's second character 500'd (`sqlite3.Row`
      into `footprint.*` `.get()` in `assign_char`) — now `dict(tok)`, pinned by test.
- [x] `tests/test_d101_prep.py` (13): options access + empty room, background roundtrip
      + wipe guard, starting-gear (grant/skip/idempotent/authz/missing-data/`inv_changed`),
      apply→`snapshot`, manipulated choices refuse-and-write-nothing, prep UI wiring,
      apply re-render, legacy flows untouched. Canonical close:
      `docker compose run --rm test` → **694 passed, 1 skipped, 0 failed**.
      Docs: D101, AGENT_GUIDE (frontend list, prep section, test map), MANUAL checklist D101.
- [ ] **Follow-ups (honest limits):** species ability bonuses from `species.csv` are still
      not mechanically applied (engine decision, out of D101 scope); starting gear is bound
      by D100's GLOBAL `item_defs` id (second room importing the same pack gets refused
      projections → those items list as skipped until the per-room key rebuild happens);
      lobby editor stays legacy free-text (guided flow is room-scoped because content is);
      public room browser intentionally NOT built (join-by-code preserved).

## Done — Sprint 31: D102 Floors operable (Stockwerke: Integrität, Isolierung, DM-Verwaltung) (2026-10-13, D102)

- [x] **Plane-integrity bugs fixed (the actual "Stockwerke kaputt" reports):** trap
      discovery (`room/movement.py` walk) and the `toggle` op (`room/interact.py`)
      saved the VIEWED PLANE's map with an un-floored `set_map` → that overwrote the
      PRIMARY map's content (terrain, objects, fog). Both save with the floor they
      hold. WS-connect reveal groups tokens by floor and reveals on EACH token's own
      plane map; `assign_char` (re-seat) likewise loads/writes the token's plane —
      the primary blob is only ever written by writes that mean it. No migration.
- [x] **Visibility isolation:** `explored`/`fog_changed` payloads carry `floor`;
      clients apply them only while they match `state.viewFloor` (the aoe/ping guard
      pattern); walk/connect reveals deliver via `send_to_plane_viewed` (token
      holders + DM + token-less observers on primary). DM canvas filtering corrected
      to the VIEWED plane (`viewerPlane()` → `viewFloor` for the DM; off-plane tokens
      not rendered AND not clickable). `openRoom` honours the server's `view_floor`
      from the first frame (player on a named floor: guards, brushes and saves
      address the right plane immediately).
- [x] **Plane changes: DM + validated stairs (operator decision).** `token_floor`
      is DM-only ("Only the DM moves tokens between floors"); the stair object
      remains the players' route with the target plane fully checked; sheet floor
      row read-only for players. D88/Sprint-20/19 tests that encoded the old
      owner-may-hop policy were re-pointed to the DM socket (behavior checks kept).
- [x] **The floor manager exists** (it never did — that was "nicht bedienbar"):
      DM side panel "Floors" (own panel, DM tab): browse/add/rename/delete with
      server refusal reasons surfaced (primary, tokens standing there). NEW
      `PATCH /api/rooms/{code}/floors/{name}` — `FLOOR.rename` moves registry,
      `floor_maps` row and `tokens.floor` together, then stair `op.floor`
      references are retargeted on every plane map (rename without it dangles
      stairs); `floors_changed` + `map_changed` follow.
- [x] `tests/test_d102_floors.py` (9): trap/toggle cross-plane save pins, connect/
      assign reveal on the standing plane, plane-labelled + plane-scoped reveal and
      fog-edit delivery, DM-only hop with stairs still open, rename (registry/map/
      tokens/stairs + same-name/unknown/duplicate/non-DM refusals), player snapshot
      delivered on the token's plane. Two node-harness hit-test extractions extended
      (tokenAt now filters by onPlane). Canonical close:
      `docker compose run --rm test` → **703 passed, 1 skipped, 0 failed**.
      Docs: D102, AGENT_GUIDE (floors section,
      module table, test map), MANUAL checklist D102.
- [ ] **Follow-ups (honest limits):** ⬜-brush backlog untouched (paints cell 0, does
      not block plane separation); stale editor snapshots can resurrect an old floor
      name via their objects (editor-merge caveat, D88 class); no per-plane token
      counts in the panel; stairs remain the only player-facing plane transition.

## Done — Sprint 32: D103 Map editor truth + PNG display (Karten-Editor: echtes "kein Boden", Bildchen laden im Browser) (2026-10-13, D103)

- [x] **PNG root cause fixed at the route, not the pipeline:** the DB canon
      `/assets/<id>` (loaded verbatim by the canvas) was NEVER routed — only
      `/api/assets/<id>` existed, so artwork 404'd in every real browser (and the
      onerror blacklisted it in the art cache). New prefix-free `media_router`
      delegates to the SAME `get_asset`: identical auth, no-oracle 404, clean
      re-encode, `nosniff`. `/api` form unchanged; zero pipeline edits.
- [x] **"Kein Boden" became a real state:** terrain registry 5 = void (impassable,
      not climbable, sight passes). All engines refuse it automatically via the D69
      registry (path/LOS/placement/collision/preview) — no engine edits. Old maps
      byte-compatible (no 5 exists until painted; fog `None` stays floor; sanitize
      clamps 6→5, still rejects fog nulls). D102's ⬜-backlog resolved honestly:
      new 🕳️ brush paints 5 (drag included), ⬜ keeps 0 and finally RENDERs as
      floor (two-tone tiling), 🧹 semantics unchanged.
- [x] `tests/test_d103_editor_assets.py` (8): void blocks movement/teleport/
      placement but not vision/light (one map, one column, both proofs), paint
      preserves walls/doors/traps, void is plane-local (crypt pit ≠ primary),
      registry/sanitize/legacy semantics, player map_edit refusal, canonical asset
      url serves for owner AND riding-token DM while strangers/junk get 404 on BOTH
      urls, assigned-artwork roundtrip, client brush/canvas wiring pins. Two D69
      clamp tests updated (5 legitimate, 6+ clamps).
      Canonical close: `docker compose run --rm test` → **711 passed, 1 skipped,
      0 failed**. Docs: D103, AGENT_GUIDE (registry 0..5, asset routing, brushes),
      MANUAL checklist D103.
- [ ] **Follow-ups (honest limits):** diorama renders void as a flat tile (D97 file
      untouched); concurrent editors stay last-writer-wins (D88 class); artwork
      `max-age=86400` can outlive access revocation in a warm cache; no automatic
      "fall into void" simulation — the server only refuses occupancy.
