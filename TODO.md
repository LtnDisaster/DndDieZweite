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
- [x] **Makefile + scripts/smoke.sh (D143, 2026-10-17):** live smoke starts uvicorn on an
      ephemeral loopback port with its own VTT_DATA_DIR, proves health/register/room over
      HTTP, stops via pidfile trap. `make test|compile|check|smoke|lock` wraps the checks.
      (the `.mjs` suites stay a **dev-only** live-server harness; `pytest` is the durable suite).
- [x] **requirements.lock (D143, 2026-10-17):** full transitive freeze of the canonical
      Docker test image (incl. starlette); `make lock` regenerates it deliberately.
- [ ] Optional CI job: `pytest` + `compileall` + `node --check` on push.

## P2 — Known soft spots (call out before touching)
- [ ] **Path preview latency:** `findPathJS` was removed and movement is now server-authoritative.
      Remaining drift risk is UI formatting only; add a browser e2e test for async preview requests.
- [x] **Ghost persistence (D142, 2026-10-17):** viewer fog memory is persisted to
      room_state.ghosts_json at disconnect and hydrated on first sight/room join —
      restart-safe in one process; multi-worker remains the known boundary.
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
- [x] Consumable potions (remove on last use) — D146: potion/scroll entries are
      consumed in the same transaction as the heal (qty>1 loses one dose,
      cursed entries stay, rechargeables keep the depleted shell).
- [x] Attunement UX (D147: resolved by rule, not by gate — attuning to an
      unidentified magic item IDENTIFIES it, exactly as DMG/SRD prescribe).
- [ ] Per-party (vs per-item) knowledge of identified items; party shared notes.
- [x] Cross-tab / reconnect (D148): multi-socket tests prove prune/persist/hydrate
      are per-user not per-socket; reconnect re-seeds ghosts from the DB.
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
- [x] Live range/reach pin restored (`tests/test_sprint24_hardening.py`): the old
      harness failure came from alphabetically ambiguous definition-ID lookup;
      lookup is now by name. No skip remains.

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
- [x] **Follow-up (D145): species ability bonuses from `species.csv` are mechanical
      now** — report/apply endpoints grant them EXACTLY-ONCE via the build ledger
      and the recompute replays them at the chronology front (UI button optional).
      Remaining honest limits: starting gear is bound
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

## Done — Sprint 33: D104 Lights manageable + DM player-view peek (Lichtquellen-bedienung, DM-Spielersicht) (2026-10-13, D104)

- [x] **Light management on the ONE existing lamp model:** new DM-only `lamp`
      WS channel (`room/lights.py`) — add/update(bright,label,on,move)/remove by
      id on a named plane, same canon + id-merge as the object sanitizer, same
      `reevaluate_visibility` as lamp-interact/map-edit. Silent administration
      (no fake chronicle). New DM panels: **Lights** (viewed plane: toggle/
      radius/rename/move-by-click/delete/add-at-centre) — the editor's place/
      remove tools finally got the list they never had.
- [x] **DM peek `GET /rooms/{code}/view_as/{cid}`:** the /state player branch
      EXTRACTED to `rooms._viewer_token_view`, shared by both callers — zero
      second visibility logic; read-only (explored/ghost/broadcast untouched,
      pinned); DM-only (member 404 / outsider 403 / foreign-character 404).
      Client: `viewG/viewTokens/viewGhosts` render accessors, dead canvas input
      while previewing, diorama blocked, plane filter server-side, banner
      "👁 DM preview: sight of …", Snapshot + Refresh (approved design).
- [x] **Audit find fixed:** WS connect reveal ignored darkness (classic FOG_R
      light-budget bypass on reconnect) — now defers to `viewer_visible_cells`
      on dark planes; rule variants (magical darkness) documented, NOT invented.
- [x] `tests/test_d104_lights_preview.py` (14): lamp roundtrip radius/off, walls
      block light exactly like sight, darkness = memory+footstep only,
      darkvision effective, plane isolation of lamp + light, non-DM refused,
      view_as byte-equal to the player's own /state, leak-free (hidden NPC/
      undiscovered traps/dm_only/secret doors/op-payload), purity (explored +
      player state unchanged), auth matrix, reconnect reveals by light's reach,
      legacy rooms classic, toggled-off survives later map_edit, client wiring
      source pins. Two loop-head source pins followed to the accessors (D102
      precedent), z-pin satisfied via `--z-movehud`. Canonical close:
      `docker compose run --rm test` → **725 passed, 1 skipped, 0 failed**.
      Docs: D104, AGENT_GUIDE (lights section, view_as security, test map),
      MANUAL checklist D104.
- [ ] **Follow-ups (honest limits):** preview = moment-image (Refresh);
      dm_only-lamps not panel-editable yet (editor tool only); no magical-
      darkness state (documented variant); no falling mechanics; managing
      lights mid-preview only shows after Refresh.

## Done — Sprint 34: D105 Class kit, NPC gear and looting (Klassen-Startausrüstung, NPC-Inventare, Loot) (2026-10-13, D105)
- [x] classes.csv: starting_items / starting_choices (level-1, additive, Demo scout+warden);
      prep screen is server-driven (GET report + radio groups + ONE grant POST with class_choices).
- [x] Grant all-or-nothing (kein Claim bei kaputtem Pack — reparierbar), class kit exactly-once
      ("already" before choices parse), background part D101-identisch; GET starting-gear/{cid} report.
- [x] NPC inventories = containers table keyed tok:<token_id>, DM-only `npc_inv` channel
      (inspect/fill/remove/coins_fill/coins_remove); contents never in any payload but own inspect.
- [x] Looting `loot` channel: gate NPC hp==0 (live; heal>0 re-locks), D82/D92 authz
      (room/plane/reach/own char, DM per seated char), container_give forces direction,
      op_id everywhere (replay/race safe), chronicle 💰/🪙.
- [x] New SSOT primitives: INV.container_give, INV.container_remove_coins; token deletion
      cleans exactly its tok:<id> container (no orphans, no other stock touched).
- [x] Fixed by tests: token pixel vs map-object cell coords in the reach check.
- [x] UI: prep gear step (80_prep.js), NPC sheet Inventory/Loot, player "Loot search",
      chest panel routes chest/npc/loot sources with op_id per action.
- [x] tests/test_d105_gear_loot.py (24: 22 server + 2 source pins) green; suites
      content/d101/sprint22/money/hardening/integration/npc/footprint regression green;
      canonical 749 passed, 1 skipped, 0 failed (baseline 725 + 24).
      Docs: D105, AGENT_GUIDE (inventory/loot section), CSV guide (gear grammar),
      MANUAL checklist D105.

## Done — Sprint 35: D106 Cursed items + secret metadata + DM whispers (Verfluchte Gegenstände, geheime Metadaten, DM-Flüsterpost) (2026-10-14, D106)

- [x] Per-instance curse metadata INSIDE the item entry (`curse {name, desc, whisper, revealed}`)
      — no schema change, no migration; the entry dict IS the instance and travels
      transfer/chest/loot through the existing atomic moves (ids are per-inventory only).
- [x] Fail-closed sanitising: `gear.clean_items` strips `curse` by default; engine mutation
      paths read trusted (`keep_curse=True`) — equip/use/attune/identify/recharge/long rest
      and the honest sheet-PUT round-trip provably never wipe it; client PUTs can neither
      forge a curse nor flip `revealed` (`_preserve_curses`).
- [x] One disclosure gate `gear.curse_view`: DM full, owner ONLY a revealed curse's
      name+desc (whisper text never leaves chat), everyone else sees nothing — server-side,
      applied to /state, lobby sheets, container/loot replies; broadcasts never carry items.
- [x] Cursed instances never stack, never split; marking a qty>1 stack carves EXACTLY one
      qty=1 piece atomically (op_id-guarded writes; replay mints nothing).
- [x] Owner change keeps the curse, clears `revealed` (knowledge never travels);
      reveal/conceal/whisper are DM-commands, recipient resolved server-side from the
      item's current holder (room-membership enforced), delivered via the existing
      private `chat.post_chat` whisper — no second chat stack, foreign players see
      nothing live and nothing in history.
- [x] D105 follow-up: `handle_del_token` deletes token + `tok:<id>` container + seat +
      chronicle in ONE `db.tx()` (FK-failure rolls back both — tested with the real FK error).
- [x] UI: DM ☠-editor/reveal/whisper/clear on sheet + chest + NPC panels, owner sees
      revealed curse line; 55_diorama.js untouched.
- [x] tests/test_d106_curses.py (26 behaviour tests, 0 source pins) green;
      canonical 775 passed, 1 skipped, 0 failed (baseline 749 + 26).
      Docs: D106 (DECISIONS), AGENT_GUIDE (curse channel + inventory section + test map),
      MANUAL checklist D106.
- [ ] **Restarbeit (D110 umgewidmet — war „bewusst nicht gebaut“, weiterhin
      gewollt; vollständige Planung + Sprintreihenfolge S40–S44:
      `docs/FEATURE_COMPLETE_GAPS.md`):** Taschendiebstahl-Mechanik,
      automatische Fluch-Auslöser/Zufallstabellen, geheime Rettungswürfe,
      mechanische Fluch-Folgen (Schaden/Saves/Ticks), Fluch-Verbreitung.

## Done — Sprint 36: D107 Integration & Browser-Readiness-Audit + Regelkompatibilitäts-Audit 2014↔2024 (D107)

- [x] Regelbasis-Beschluss: **D&D 5e (2024)** ist verbindliche primäre Regelbasis
      (DECISIONS D107) — Abweichungen der Engine sind jetzt dokumentierte
      Abstände mit R-Nummern, kein stiler Drift.
- [x] Audit geschrieben: `docs/RULES_AUDIT_2024.md` — Matrix mit `Datei:Zeile`-
      Belegen (Ableitungen/Proficiency, Species/Background/ASI/Feats, Klassen-
      fortschritt, Zauber inkl. Concentration, Waffen inkl. Weapon Mastery,
      Zustände/Tod/Ruhe), Einstufungen [2014]/[2024]/[gleich]/[HR]/[Anz.]/[lück].
- [x] Bereits 2024-konform festgehalten: Cantrip-Skalung nach Gesamtcharakter-
      stufe (abilities.py), ASI-Kadenz datengetrieben (classes.csv), Attunement
      Kap 3, Cover-/Krit-/Traglast-Semantik.
- [x] CSV-Schema-Eignung je Datei bewertet; additive Spalten-Vorschläge
      (species.origin_feats, backgrounds.ability_bonuses, feats.tier,
      items.mastery) NUR dokumentiert — kein Schema-Change in D107.
- [x] Hausregel-Register H1–H9 (Death-Saves D34, Rests D35, NPC-0-HP D56/D105,
      Attunement-Gate, Exhaustion-/Inspiration-/Ranks-Anzeige, Modi-Hoheit,
      Content-Originalität) mit DECISIONS-Verlinkung.
- [x] Priorisierte R-Liste: 4×R-P0 (Proficiency-Dice, ASI-Träger 2024, Feat-
      Modell 2024, Weapon Mastery), 5×R-P1, ~9×R-P2 + R-L0 (SRD-5.2-Lizenz-
      prüfung durch Menschen, bevor 2024-Originaltexte übernommen werden).
- [x] README: Ein-Satz-Statushinweis; CSV-Guide §11 „Eignung für 2024".
- [x] Schranken gehalten: keine Regelimplementierung, keine neuen Content-Packs,
      keine fremden Regeltexte außer SRD-5.1-freigegeben, keine Änderung an
      55_diorama.js, keine Git-Befehle. Kanonisch: 775 passed, 1 skipped,
      0 failed (doku-only — Erwartung erfüllt).

## Done — Nachtschicht 2026-10-16 (D115): Gear-/Build-Lücken ohne neue Maschinen schließen

- [x] **Ausrüstung → Engines:** `movement._speeds` und
      `visibility._token_darkvision_cells` lesen `gear.effective_gear`;
      `speed_bonus_ft` erhöht das Bewegungsfeld, `darkvision_ft` erhöht den
      LOS-Radius in einer Darkvision-Sicht (5 ft je Rasterschritt),
      `hit_dice_bonus` wirkt im Short Rest und `hands:2` nutzt die bestehende
      Zwei-Hände-Regel.
- [x] **Origin/Build:** Background-`skill_prof` wird im bestehenden
      `_replay_origin`-Pfad angewandt; `feats.spells_grant` läuft über dieselbe
      Grant-Achse wie Subklassen und landet im bestehenden `spell_state`;
      `classes.expertise` ist eine optionale Skill-Achse mit fail-closed Prüfung.
- [x] **Provenienz/UI:** Background-Tools/Sprachen/Feature, Species-Projektion,
      `classes.weapon_prof`/`armor_prof` und Subclass-Features erscheinen als
      read-only Build-Ledger/UI; keine zweite Größen-, Bewegungs- oder
      Proficiency-Maschine.
- [x] Tests: `tests/test_engine_gear_grants.py` (11), Node-`--check` für alle
      `app/static/js/*.js` grün, `python3 -m compileall -q app` grün.
- [x] Kanonischer Docker-Lauf: **959 passed, 1 skipped, 0 failed**.
- [x] Schranken gehalten: keine Git-Befehle, keine `.git`-Aktionen, keine
      Änderung an `55_diorama.js`, keine Migration, kein externer Dienst und kein
      Fake-grüner Test. `feats.requires`, mechanische Species-/Klassenwerte und
      Item-/Zauber-Dauerablauf bleiben dokumentierte offene Grenzen.

## Done — Autonomer Lauf 2026-10-16 (D116/D117): letzter Skip entfernt, Dauer verdrahtet

- [x] **AP-001:** Der Reichweiten-/Reach-Live-Test ist nicht mehr übersprungen.
      Die Ursache lag im Test (alphabetisch mehrdeutige `item_def`-ID-Auswahl),
      nicht in der Engine. Zehn Wiederholungen und die Kanonsuite sind grün.
- [x] **AP-002:** Condition-Hooks wurden vollständig inventarisiert. Die
      Feature-Matrix ersetzte die veraltete Annahme, `blinded`, `invisible` oder
      `poisoned` seien nicht verdrahtet.
- [x] **AP-003:** `duration` ist jetzt ein mechanischer Startwert für
      `condition`-Operations: `"rounds":"duration"` oder fehlendes `rounds`
      übernimmt die in Runden umgerechnete Dauer. Die bestehende Conditionsuhr
      bleibt die einzige Uhr.
- [x] **AP-004:** `classes.spellcasting_ability` erscheint in Plan, Apply und
      Build-Ledger sowie im Wizard-/Bogen. Die pro-Zauber-Ausführung bleibt
      unverändert; es wurde kein zweites Spellcasting-Modell gebaut.
- [x] **AP-005:** `classes.expertise` ist eine geführte Checkbox-Auswahl im
      Wizard. Serverseitig werden exakte Anzahl, Duplikate und fehlende
      Übung geprüft; der Erfolg nutzt weiterhin nur die Skill-Achse.
- [x] **AP-006:** `scripts/e2e_build_wizard.py` prüft die komplette Wizard-Kette
      in echtem headless Chromium; Playwright läuft in einem temporären venv.
- [x] **AP-007:** `feats.requires` prüft Attributswert-, Skill-Proficiency- und
      Feature-Voraussetzungen fail-closed; unbekannte Formen werden abgewiesen.
      Der Wizard zeigt Verfügbarkeit und fehlende Voraussetzungen.
- [x] **AP-008:** `npc.project_creature()` übersetzt `creatures.csv` in den
      bestehenden NPC-/Bestiarium-Block; DM-Review und Bestiarium-Import sind
      DM-only, mit echtem Chromium-Nachweis.
- [x] **AP-009:** `darkvision_ft` überlebt CSV → NPC-Block → Spawn und nutzt
      die bestehende D89-Token-Sinnensäule; der NPC-Editor bearbeitet Feet und
      leitet Token-Zellen serverseitig ab.
- [x] **AP-010:** Der Bestiarium-Spawn sendet den vollständigen NPC-Block;
      projizierte Skills erscheinen im Monster-Sheet, inklusive echter
      Chromium-Verifikation an Hawk-kin.
- [x] **AP-011:** `resource.mode=restore` erweitert dieselbe Effekt- und
      Ressourcen-Achse; Kosten-Preflight, Unbekannt-Fail-closed und echter
      `ability_cast`-Nachweis bleiben erhalten.
- [x] **AP-012:** `build.species` versorgt die bestehende Movement-, LOS- und
      Footprint-Kette; Tests belegen Stoutheart 25 ft/12 Zellen und Kit-kin
      Small-Token ohne neue Engine.
- [x] **AP-013:** `companion` überlebt CSV → NPC-Block → Creature-Review, Spawn,
      Sheet und Bestiarium als Markierung; Token-Steuerung/Ownership bleiben auf
      den bestehenden Pfaden. Echte WS-Angriffs- und Slotpfade sichern den
      vollständigen Spawn-Block.
- [x] Docs: `AUTONOMOUS_WORK_LOG.md`, `DECISIONS.md`
      (D116/D117/D118/D119/D120/D121/D122/D123/D124/D125/D126/D127), `FEATURE_MATRIX.md`,
      `FEATURE_COMPLETE_GAPS.md`, `CSV_ONLY_READINESS.md` und
      `EFFECT_GRAMMAR.md`.
- [x] Kanonischer Docker-Lauf: **981 passed, 0 skipped, 0 failed**.
- [x] Schranken gehalten: keine Git-Befehle, keine `.git`-Aktionen, keine
      Änderung an `55_diorama.js`, keine Migration und keine zweite Engine.

## Done — Autonomer Nachtrag + Recovery 2026-10-17 (D128/AP-014)

- [x] **D128/AP-014 nachdokumentiert:** NPC-Angriffs-`reach` ist seit dem
      gepushten Stand hartes Gate über `dice._vertical_range_distance`
      (CSV-Projektion „reach N ft“, `clean_npc`-Clamp 0–999,
      `na-reach`-Editorfeld). Code und `tests/test_d128_npc_reach.py` waren
      bereits vorhanden; DECISIONS/AP-Abschnitt fehlten durch den
      Sitzungsabbruch und wurden in der Recovery-Sitzung nachgereicht.
- [x] **Recovery-Baseline:** kanonischer Lauf **985 passed, 0 skipped,
      0 failed** (981 + 4 D128-Tests) — keine unfertige Integration im Code;
      reparaturbedürftig war ausschließlich die Doku.
- [x] Runtime-Start + `/api/health` + Build-Hash-Konsistenz geprüft; echte
      Chromium-E2E (`e2e_build_wizard.py`, `e2e_creature_projection.py`)
      gegen Wegwerf-Instanz beide **PASS**.
- [x] `docs/CSV_ONLY_READINESS.md` („reach advisory“ → durchgesetztes Gate),
      `docs/FEATURE_MATRIX.md` (Kanon 985/D128), `docs/AUTONOMOUS_WORK_LOG.md`
      (AP-014 + Recovery-Lauf) und `DECISIONS.md` (D128) aktualisiert.
- [x] Bericht: `docs/RECOVERY_2026-10-17.md`.

## Done — Sprint 43 (D114): vertikale Token-Geometrie, `openv`, vertikaler Flug und UI

- [x] **Phase 2 Fallen-Konsistenz:** Legacy-Trap-d20 läuft über
      `dice.do_roll("1d20", None)["kept"]` statt `random.randint`; Entschärfen
      bleibt echter DEX-Check, UI sagt „Dexterity check“. Die offene
      Thieves'-Tools-Proficiency-Lücke ist dokumentiert, nicht kaschiert.
- [x] **Phase 3 Token-Volumen:** additive `tokens.height_ft`/`tokens.elevation_ft`;
      Größenkategorien nur als Defaults, keine Obergrenze; WS `token_height`;
      Server-Clamp 0..200 ft; Owner-/DM-only; verdeckte NPC-Tokens leaken weder
      Höhe noch Elevation.
- [x] **Phase 4 Öffnungen:** `mapmodel.openv` pro Ebene/Zelle, Fail-closed
      default `0`, Editor-Validation, Fog-Maske; `vertical3d.body_planes()`
      verlangt Öffnung für das gesamte Footprint und nutzbare Zielzellen;
      `observable_cells()` trennt Körperpräsenz von senkrechtem Schacht.
- [x] **Phase 5 Live-Integration:** `/state`, Token-Delivery, Präsenzereignisse,
      `plane_viewers`, Angriff, Grapple und Interact fragen die zentrale
      `vertical3d`-Entscheidung; Körperpräsenz macht Nebel-/Ebenenpublikum,
      Schacht gibt nur Sicht; `token_height` und `openv`-Änderungen lösen
      `reevaluate_visibility` aus; Push über Ebenen bleibt abgelehnt.
- [x] Tests Phase 2–5: `test_d113_traps.py` (+2), `test_d114_vertical.py` (5),
      `test_d114_openings.py` (4), `test_d114_phase5_integration.py` (5).
- [x] Kanonischer Docker-Lauf nach Phase 5: **937 passed, 1 skipped,
      0 failed**.
- [x] **Phase 6 Bewegung/Flug:** `find_path_3d()` über `(floor, origin)`-Zuständen;
      `walk3d()`/`_move3d()`/`_teleport3d()`; vertikale Schritte kosten
      kanonisch `10 ft = 2` Bewegungsfelder; `void` ist freie Flugluft, aber
      kein Standboden; `walk` darf eine offene Vertikalachse nicht nutzen;
      Ganzzervolumen-Kollision mit bestehenden Owner-/Reiter-Ausnahmen;
      Etagenwechsel nur bei explizitem `floor`-Feld.
- [x] **Phase 7 UI/Canvas:** `height_ft`/`elevation_ft` im Sheet, vertikaler
      Flugknopf, `openv`-Editorpinsel, `↕`-Öffnungshinweis,
      `↑`/`↕`-Tokenindikatoren und plane-richtige Canvaslogik.
      `55_diorama.js` blieb unverändert.
- [x] **Phase 8 Integration:** `tests/test_d114_phase8_integration.py` (4) prüft
      horizontalen Anflug + Etagenwechsel, Walk-Verweigerung, `openv`-Roundtrip
      auf benannter Ebene und Hit-Testing eines serverseitig erlaubten
      Cross-Plane-Tokens mit dem echten Canvas-Code.
- [x] **Phase 9 Doku/Abschluss:** `docs/VERTICAL_GEOMETRY.md`, `DECISIONS.md`,
      `AGENT_GUIDE.md` und Gap-Dokumente auf den tatsächlichen Stand gebracht;
      verbleibende Einschränkungen sind ausdrücklich benannt.
- [x] Tests Phase 6–8: `test_d114_phase6_vertical_movement.py` (7),
      `test_d114_phase8_integration.py` (4).
- [x] Kanonischer Docker-Lauf nach Sprint 43: **948 passed, 1 skipped,
      0 failed**.

## Done — Sprint 42 (Phases 2–4): D113 Konzentration 2024 + automatische Flüche + Opposed-Op (S42, D113)

- [x] **Phase 2 Konzentration (DECISIONS D113):** additive `conc`-Verlinkung an
      Conditions (`app/conditions.py`), Lebenszyklus in
      `app/room/concentration.py` (`end_previous`/`break_link`/`on_damage`/
      `enforce_after_condition`); Save via `room.opposed.save_roll`; DC
      `max(10, floor(HP/2))` ohne Cap auf tatsächlich verlorene HP (nach Resistenz
      + Temp-HP); Down/Inkapazität brechen ohne Wurf; `on_damaged`-Tiefen-Gate in
      `room.health.change_hp`; Cast beendet alte Konzentration zuerst und stempelt
      `conc`.
- [x] **Phase 3 automatische Flüche:** `active` ⟂ `revealed`; DM-Aktionen
      `arm` (Trigger + validierter Wirk-Cell) und `activate`/`deactivate`
      (`app/inventory.py`, `app/room/inv.py`); Omit-when-Default in
      `gear.clean_curse` (kein alter Fluch wird aktiv, byte-identisch rückwärts-
      kompatibel); Auslösung nur an Mutationen (equip/unequip/use/on_hit/
      on_damaged/on_transfer) und nur wenn aktiv+passender Trigger; curse-origin-
      Fragmente via `net.dm_whisper` nur an den DM; Owner-Ansicht bleibt
      `curse_view`-streng; `on_transfer` op-id-geclaimt (atomar, kein Doppel-Feuer).
- [x] **Phase 4 Opposed-Op (Grammatik v2):** `effectops` akzeptiert v1+v2
      (`V_MIN..V_MAX`), neuer `opposed`-Op via `room.opposed`, `canon()`
      cell-erhaltende Version; v3/unbekannt weiterhin abgelehnt; eine
      D111-Assertion (v2) auf v3 umgestellt.
- [x] **Phase 6 (teil):** Curse-Autoren-UI (⚙ arm, 🔮 active/💤 dormant) im
      Charakterblatt und Container-Panel (Englisch, `30_room.js`); deutsche
      Doku (DECISIONS D113, TODO, `docs/EFFECT_GRAMMAR.md`,
      `docs/RULES_AUDIT_2024.md`, `docs/FEATURE_MATRIX.md`,
      `MANUAL_BROWSER_CHECKLIST.md`).
- [x] **Phase 5 Fallen datengetrieben:** Map-Entity-Felder `effects`/`trigger`/
      `search_dc`/`disarm_dc`/`repeat` (Omit-when-Default, alte Fallen
      byte-identisch); Auslösung via `effectops.run_ops` statt `random.randint`
      (Save/Check/Schaden/Condition/Forced-Move, kein zweiter Würfelkern);
      Entdecken = WIS-(Wahrnehmung)-Check, Entschärfen = DEX-Geschicklichkeitswurf
      über `room.opposed` (keine Werkzeug-Proficiency-Engine); WS `trap`
      (`search`/`disarm`/DM `trigger`), Leak-frei: Fehlsuche == leeres Feld
      (byte-identisch, kein Oracle); `disarmed` überlebt Editor-Snapshots.
- [x] Tests: `tests/test_d113_concentration.py` (9), `tests/test_d113_curses.py`
      (9), `tests/test_d113_opposed.py` (6), `tests/test_d113_traps.py` (10),
      alle echte WS-Pfade, keine Skips.
- [x] **Phase 7 vertikale Geometrie (nur 10-ft-Skala):** EINE Höhen-Einheit UND
      EINE deklarierte Ebenen-Stufe = exakt 10 ft (`app/vertical.py`,
      ELEV_FT/FLOOR_FT); Ebenen-Reihenfolge = Höhen-Stack
      (`floors.level`/`absolute_height_ft`), rein Reporting — Ebenen bleiben
      unabhängig. KEIN Höhenkampf (Sturz/Deckung/Flug bleiben D70/D83 aus);
      Pfad gateert weiterhin |Δz| ≤ 1 in EINHEITEN; `elev`-Klammer bleibt -6..6.
      Kein Diorama.
- [x] Tests: `tests/test_d113_vertical.py` (4). Phase 2–7 gesamt: Konzentration
      (9) + Flüche (9) + Opposed (6) + Fallen (10) + Vertikal (4) = 38 neue Tests.
- [x] Kanonischer Docker-Lauf: **921 passed, 1 skipped, 0 failed**.
- [~] **Phase 6 (Doku):** deutsche Doku zu allen Phasen geschrieben
      (DECISIONS/TODO/EFFECT_GRAMMAR/RULES_AUDIT/FEATURE_MATRIX/AGENT_GUIDE/
      MANUAL_BROWSER_CHECKLIST); Browser-Durchlauf bleibt menschliche Abnahme.

## Done — Sprint 41: D112 Kontesto-Primitive + 2024-Sonderkampf + Taschendiebstahl (S41, D112)

- [x] **Kontesto-Primitive (`app/room/opposed.py`, DECISIONS D112):** dünner,
      wiederverwendbarer Helfer über dem BESTEHENDEN Würfelkanal
      (`do_roll`/`_combine_adv`) und den `gear`-Bonusquellen — `participant`,
      `check_roll`, `save_roll`, `bonus_roll`, `melee_attack_number`,
      `better_save`, `opposed_wins(att, def, tie=)`, `beats_dc`, `Tie`. Drei
      Formen (Wurf-vs-Wurf, Wurf→DC→Rettung, Wurf-vs-feste-DC) sind nur
      Komposition, EIGENE Regeln trägt das Modul keine. Tie-Regel per Default
      `defender` (d20-Gleichstand → Verteidiger / DC muss erreicht werden),
      `attacker` kippt, `dm` wirft `Tie` auf und übergibt an den DM — nie ein
      stiller Münzwurf. Effektgrammatik-Op für kontesto-CSV bleibt S42; die
      Schnittstelle ist in `docs/EFFECT_GRAMMAR.md` dokumentiert, damit S42
      diesen Helfer einwickeln kann statt ihn zweimal zu bauen. Keine zweite
      Rules-Engine.
- [x] **2024-Sonderkampf (`app/room/grapple.py`):** NICHT der
      2014er Athletik-gegen-Athletik-Wettkampf. Grapple = Sonderkampf-Wert des
      Angreifers (`melee_attack_number` = max(unbewaffneter Angriffsbonus,
      Athletik-Wurf)) wird zur DC, auf die das Ziel mit einer RETTUNG antwortet
      (`save_roll`), per Default die höhere der beiden Stärke/Geschicklichkeit
      (`better_save`), DM-überschreibbar (`save`); Shove (niederringen / 5 ft
      stoßen) über denselben Wurf, Stoß über das bestehende
      `moveforced.apply_forced_move`. Zustand rein additiv: der `grappled`-Conds-
      Eintrag trägt Grappler-`src` plus neues optionales `dc` (int 1–30,
      `_clean_dc`), Entkommen = „Athletik oder Akrobatik gegen gespeicherte DC".
      Der Grapple endet, sobald das Ziel die Reichweite verlässt —
      `end_grapples_out_of_reach` hängt an den drei autoritativen
      Bewegungs-Enden (erzwungene Bewegung inkl. Shove, normaler Lauf,
      DM-Teleport) — oder wenn der Grappler weg/kampunfähig ist (Entkommen
      gelingt dann automatisch). Reichweite/Nachbarschaft nutzen DIESELBE
      Eckpunkt-Geometrie (Chebyshev ≤ 1) wie `room.dice`; Größengate „höchstens
      eine Größenkategorie größer" über `npc.SIZES`-Index.
- [x] **Taschendiebstahl (`app/room/pickpocket.py`):** BEIDE
      2024-Adjudikationsmodelle. Modell A `pickpocket` = DM-vermittelte Probe —
      versteckter Fingerfertigkeits-Wurf, Ergebnis NUR an den DM; Modell B
      `pickpocket_take` lässt den Dieb EIN konkretes DM-autorisiertes Item wählen
      und bei Erfolg atomar übertragen. Weil 2024 KEINE passive Wahrnehmung hat
      (`RULES_AUDIT_2024` A7), ist „bemerkt" entweder feste DM-`notice_dc`
      (`beats_dc`) ODER ein echter, vom Helfer gewürfelter Wahrnehmungs-Wurf mit
      `opposed_wins(tie="defender")` — der Engine erzwingt nie einen Modus.
      Entdeckung wird SEPARAT vom Diebstahl-Erfolg an den DM gemeldet. Erfolg =
      eine atomare `inventory.transfer` (PC-Opfer) bzw.
      `inventory.container_give` (NPC `tok:<id>`) mit `_ownership_moves`, das
      Fluch-Metadaten erhält und `revealed` zurücksetzt. `handle_pickable`
      (nur DM) schaltet das neue `pick` an Charakter-Item (`set_pick_char`) oder
      NPC-Container (`container_set_pick`).
- [x] **Leak-/Replay-Wächter sind tragend:** nur DM-markierte `pick`-Items sind
      stehlbar, ein nicht markiertes/unbekanntes Item antwortet exakt wie eine
      misslungene Probe (`_pick_entry` → None), der Endpunkt ist nie ein
      Inventar-Orakel; die op-id-`_claim` wird VOR dem Ausgaben des
      Aktions-Slots und VOR jedem Wurf genommen, ein Replay zahlt und würfelt
      nichts; jede Voraussetzung (Raum, Ebene, Reichweite, Sichtbarkeit,
      Authz, Größe, Ziel-lebt) wird VOR jeder Ausgabe geprüft. `pick` stapelt
      nie (`_stack_key` → None) und läuft über die `clean_items`-Whitelist.
- [x] **UI (Phase 5) = nur Akteur+Ziel:** das Blatt nennt wer auf wen mit
      frischem `op_id`, die ganze Auflösung läuft serverseitig; DM autorisiert
      `pick`-Items im NPC-Truhe- und Charakterblatt (`🤝 steal`). Keine neuen
      Reply-Kinds nötig — Grapple/Shove/Escape nutzen `dice`+`cond`+
      `initiative`, Pickpocket `whisper`+`dice`+`inv_changed`, `pickable`
      `inv_contents`/`inv_changed`; `40_ws.js` unberührt, `55_diorama.js`
      unberührt.
- [x] Doku: `docs/FEATURE_COMPLETE_GAPS` (S41 UMGESETZT; Kontesto-Op → S42),
      `FEATURE_MATRIX`, `RULES_AUDIT_2024` (Grapple/Shove/Escape + Pickpocket
      jetzt implementiert, 2024-korrekt), `CSV_ONLY_READINESS` je Fläche neu
      bewertet, `EFFECT_GRAMMAR` (kontesto-Schnittstelle als S42-Einwickel-
      punkt), AGENT_GUIDE (drei Module + sechs WS-Typen + Testkarte),
      MANUAL_BROWSER_CHECKLIST (D112), DECISIONS D112.
- [x] `tests/test_d112_contested.py`: 31 echte Integrationstests über die
      WS-Pfade (Save-/Tie-Unit, voller Grapple/Shove/Escape, beide
      Pickpocket-Modelle, Leak, Replay, Nebenläufigkeit, verfluchter Transfer,
      Cross-Room, Cross-Plane, Aktions-Ökonomie). Keine neuen Skips, keine
      Source-Pins.
- [x] Kanon: `docker compose run --build --rm test` — **883 passed,
      1 skipped, 0 failed** (Basis 852 + 31; der 1 Skip bleibt die gepinnte
      Altlast aus Sprint 24). Ein einzelner Ping-Ebenen-Zustelltest
      (`test_sprint20_security`) flackerte im Voll-Lauf an einem Chat-Flush-
      Timing; isoliert stabil und im Wiederholungslauf grün, kein Regression
      (diese Phase war JS-only).

## Done — Sprint 40: D111 Effektgrammatik v1 + Zustandskatalog als CSV (S40, D111)

- [x] **Effektgrammatik v1 (`app/effectops.py`, DECISIONS D111):** versionierte,
      strikt validierte JSON-Op-Ketten (`damage/heal/temp_hp/condition/
      condition_remove/break_concentration/save/check/forced_move/resource`)
      mit harten Grenzen (8 Ops, Tiefe 1, 40 Knoten, 4000 Zeichen, DC 0–30/
      „auto“, Move 1–10 Zellen, Kosten 1) und byte-stabiler Kanonisierung;
      unbekannte Ops/Felder verwerfen die Zeile beim Import — laut, nie
      stillkorrigiert. Ausführung ausschließlich durch die bestehenden Engines
      (health/dice/moveforced/conditions/gear/inventory), `abilities.execute()`
      trägt die Kette in derselben Shell (Kosten/Chronik/Privatsphäre
      unverändert). Keine zweite Engine.
- [x] **Zustandskatalog als CSV:** `conditions.csv` (Hook-Flags
      Bewegungs­verbot/Tempo/Vor-/Nachteil/Save-Auto-Fail + `effects`-Hook-Dict
      `on_start`/`on_round`/`on_expire`), SRD-Keys als `BUILTIN_HOOKS`-Daten —
      CSV-Zeile mit gleichem `id` überschreibt, Import invalidiert den
      per-Room-Cache; `/state cond_catalog` + `10_core.js`-Legende.
- [x] **Trigger use/equip/unequip/on_hit/on_damaged** inline an den
      autoritativen Handlers (items/inv/dice/health/combat), Claim-Wächter
      (ein Feuer pro Token+Trigger+Träger+Runde/Op, keine Trigger-Ketten,
      Budget 8), Ressourcen-Preflight im Claim-Tx: abgelehnte Wirkung zahlt
      nichts, Replay feuert nie nach.
- [x] Feats mit Zelle → castbare `feat_<id>`-Ability (charbuild-Entitlement,
      Load-Pfad registriert); Items `effects`+`trigger` (getragene Pfade
      gelesen, nie aus Blatt-Kopie); Spells `effects`-Zweig im Executor;
      defekte Zellen werden verworfen (`gear.clean_props`/`clean_definition`).
- [x] **Engine-Fix 0 (P1, Condition-Ablauf):** `combat._cond_update` rief für
      gelöschte Token den broadcast-pflichtigen `remove()` statt des
      Low-Level-Pfads — schiefhängende Rekursion (Explosionsgefahr bei
      Ketten); jetzt netzfreier Abzug + eigener Test.
- [x] **Engine-Fix 2 (P1, net.py):** Cross-Loop-Zustellung war mit `id(ws)`
      verdrahtet — CPython-Id-Wiederverwendung ließ einen frischen Socket
      einen STOPPED Loop erben; jede Zustellung dorthin hing für immer
      (`wrap_future` ohne Ende). Loop wohnt jetzt auf dem Socket
      (`ws._iio_loop`), gestoppte Loops werden abgelehnt, Cross-Loop-Sends
      haben Timeout. Von den neuen Tests gefunden; Produktions-Risiken
      bestanden bisher nicht (ein Loop), Latenz war real.
- [x] SRD-Verhaltensänderung dokumentiert: grappled/restrained blockieren
      Bewegung jetzt komplett (SRD „speed 0“), Altbau-Move-Ban-Hardcodes
      ersetzt; 2024-Vereinfachungen (frightened pauschal, blinded checks-dis,
      DM-prone) in `docs/EFFECT_GRAMMAR.md`.
- [x] Demo-Pack additiv: `conditions.csv` (smouldering/shaken/slicked) +
      `thunder_lure`/`oil_vial`/`ring_ember`/`blade_quake`/`martyr` mit
      Zellen; Generator byte-idempotent (2 Läufe, Vergleich im Image).
- [x] Doku: `docs/EFFECT_GRAMMAR.md` (Autorenreferenz inkl. v1-Nichtkönnen),
      `CSV_ONLY_READINESS` je Fläche neu bewertet, `FEATURE_COMPLETE_GAPS`
      (S40 UMGESETZT; Concentration-Save → S42), `CSV_CONTENT_GUIDE`
      (§4.4/§4.7/§4.8a/§7, conditions.csv), AGENT_GUIDE (effectops + net-Loop
      + Testkarte), MANUAL_BROWSER_CHECKLIST (D111), DECISIONS D111.
- [x] `tests/test_d111_effects.py`: 21 echte Integrationstests über die
      REST/WS-Pfade (Validator/Kanon, Hooks, Katalog-Override + Cache,
      clean_props, No-Rekursion, Zauber/Talent/Item/Equip/On-Hit/On-Damaged
      inkl. Replay-Idempotenz, Preflight-Kosten, Ping-Pong, Cross-Room,
      cond_catalog). Keine neuen Skips, keine Source-Pins.
- [x] Kanon: `docker compose run --build --rm test` — **852 passed,
      1 skipped, 0 failed** (Basis 831 + 21; der 1 Skip bleibt die gepinnte
      Altlast aus Sprint 24).

## Done — Sprint 39: D110 End-to-End-Integration & Feature-Complete-Readiness (D110)

- [x] **Strategie-Beschluss (DECISIONS D110):** kein „Back Backlog“ für
      DnDTable (Regel stammte aus anderem Projekt) — Ziel = zügige
      Feature-Vollendung, danach CSV-Content + Betrieb.
- [x] Funktionsmatrix aus Code-/Test-Belegen (nicht TODO-Texten):
      `docs/FEATURE_MATRIX.md` — 16 Kategorien, Status A/B/C/D/E mit
      Datei:Zeile; fehlende Kernfunktionen als Restarbeit ausgewiesen.
- [x] CSV-only-Readiness-Bewertung je Datenfläche: `docs/CSV_ONLY_READINESS.md`
      (Spalte ≠ Mechanik: species/creatures datenführend isoliert; Executor
      kennt keine Bewegungs-/Probe-/Dauer-Effekte; Zustandskatalog hartcodiert).
- [x] Vollständige Restarbeitsplanung mit Sprintreihenfolge:
      `docs/FEATURE_COMPLETE_GAPS.md` (S40 Generik → S41 Opposed/Hehlerei →
      S42 Auto-Magie → S43 Kampf-R-P1 → S44 Datenprojektion → S45+ CSV/Betrieb);
      TODO-Backlog-Sektion entsprechend umgewidmet.
- [x] E2E-Integrationstest über die echten REST/WS-Pfade:
      `tests/test_d110_e2e.py` — eine durchgehende A→F-Kette
      (Registrierung→Pack-Import→2024-Characters inkl. Origin/Apply/Gear→
      Bewegung/Wand/Tür/Fog/LOS/View-as/Floors→Kampf mit mehreren
      Masteries (Cleave/Topple/Graze/Vex)+Bedingungen→NPC 0 HP→atomarer
      Loot mit Adjacency+Replay→Fluch set/reveal/whisper mit Besitzer-only
      Zustellung→Reconnect-Snapshots+Replay-Idempotenz) + 4 Wächter-Tests
      (Fremd-Token-/Cond-Kontrolle, View-as=Ausschnitt+DM-only, Content-
      Isolation über Räume, Whisper-Historie-Leak). 5 Tests grün.
- [x] **Engine-Fix 1 (P1, Würfel-Pfad):** abgewiesene Angriffe (verstecktes
      Ziel, out of reach, zu große Push-Last, fehlerhaftes Cleave-Paar)
      verbrannten bisher die Turn-Action, weil der Slot-Verbrauch VOR der
      Zielvalidierung lief — Konsumtion/ Nick-Buchhaltung hinter alle
      Pre-Roll-Validierungen verschoben (`app/room/dice.py`). Ein falsch
      gesetzter Angriff kostet ab sofort keinen Action-Slot mehr.
- [x] **Engine-Fix 2 (P1, Fluch-Kanal):** `curse`-Aktion `whisper` fiel in
      den reveal/conceal-Zweig und führte `curse_reveal(False)` aus — ein
      Whisper enthüllte den Fluch still wieder (D106-Latenz; d106-Suite
      erwischte es nie, weil dort nie reveal→whisper kombiniert wurde).
      `whisper` mündet jetzt in keinen Mutation-Zweig mehr
      (`app/room/inv.py`); Whispern liefert Text aus, ohne den
      Enthüllungsstatus anzufassen.
- [x] Doku: `docs/SATURDAY_ACCEPTANCE.md` (Browser-Abnahmeleitfaden A–F,
      Sa 17.10.), AGENT_GUIDE/Testkarte + MANUAL_BROWSER_CHECKLIST-Eintrag,
      DECISIONS D110, Feature-/Readiness-/Gap-Dokus wie oben.
- [x] Kanon: `docker compose run --build --rm test` — **831 passed,
      1 skipped, 0 failed** (Basis 826 + 5; der 1 Skip bleibt die gepinnte
      Altlast aus Sprint 24; keine neuen Skips, keine Source-Pins).

## Done — Sprint 38: D109 Weapon-Masteries (2024, R-P0)

- [x] Drei-Gatter-Modell serverautoritativ: Waffen-Prop `items.mastery`,
      Build-Ledger `characters.build.masteries` (grants/pending, NUR forward:
      Level-Anwendung via `classes.mastery_gain`/`mastery_options` oder
      DM-Grant-Route — nie rückwirkend), explizite Absicht im roll-Request;
      alles vor dem ersten Würfelwurf validiert.
- [x] Alle acht SRD-5.2.1-Masteries ohne zweite Engine: Graze/Cleave/Nick im
      Angriffsauflöser, Push via `apply_forced_move` (Truncation an
      Hindernissen), Topple via Rettungs-/Prone-Pfad, Sap/Slow/Vex als
      Condition-Marker mit `src`-Anker (Ablauf NUR in der D80-Turn-Lifecycle),
      `slowed` als −10-ft-Hook im `_speeds`-Pflegestück, adv+dis-Konfusion
      wiederverwendet; Cleave/Nick Einmal-pro-Turn über m_cleave/m_nick.
- [x] Off-Hand für Light-Waffen geöffnet (2024-Zwei-Waffen-Voraussetzung für
      Nick); additiver Zweig in `gear.can_equip`.
- [x] Audit-Nebenbefunde behoben: `apply_origin` und `apply()` laufen je in
      EINEM `db.tx()` (Check-then-write-Fenster geschlossen); Reach/Range
      misst jetzt Footprint-Zellen ×5 ft statt Pixel-Deltas (latenter
      D93-Bug: jedes entfernte Ziel war "out of reach").
- [x] API/UI: `GET/POST /api/build/{code}/{cid}/mastery`, DM-Grant-Route;
      Mastery-Badge + Opt-in-Checkbox + Zweitziel + Nick-Slot + 🎖-Karte in
      30_room.js.
- [x] Demo-Pack additiv erweitert (dagger_surge=nick, sword_versatile=topple,
      axe_great=cleave, bow_long=vex; Scout/Warden L1 mastery_gain=1);
      Generator byte-idempotent (Test im kanonischen Image, Dockerfile
      test-Stage kopiert jetzt scripts/).
- [x] Doku: RULES_AUDIT_2024 §8 (Modell + dokumentierte Abweichungen:
      Damage>0-Gate, Initiative-Pflicht für Marker, Spell-Angriffs-Grenze),
      CSV_CONTENT_GUIDE §11, DECISIONS D109, MANUAL_BROWSER_CHECKLIST.
- [x] Kanonisch: 826 passed, 1 skipped, 0 failed (tests/test_d109_mastery.py,
      29 neue Tests, keine neuen Skips).

## Done — Sprint 37: D108 SRD-5.2.1-Korrektur + Charakterursprung (2024)

- [x] D107-Audit gegen das offizielle SRD-5.2.1-PDF korrigiert (K1–K9 im
      Audit §1): Proficiency Dice gestrichen (Engine konform), Concentration-
      DC max(10, halb), Origin Feats aus dem Background, Feat-Kategorien inkl.
      General-Wertboni, Death Saves 3✓/3✗ bestätigt konform, Short-Rest-HD
      Spielerwahl bestätigt konform, Mastery-Liste (Cleave/Graze/Nick/Push/
      Sap/Slow/Topple/Vex) sauber von Properties getrennt, Conditions/K9-
      Korrekturen (Incapacitated fehlt; Passive Perception existiert 2024
      nicht → Abwesenheit = konform).
- [x] R-L0 gelöst: SRD 5.2.1 offiziell CC BY 4.0 — Quelle + wörtliche
      Attribution in ATTRIBUTION.md.
- [x] Schema additiv: backgrounds.asi_abilities/origin_feat, feats.category
      (registriert in content.SCHEMAS; alte Packs lesbar, 2014er Werte gelten
      nicht stillschweigend als 2024 — sichtbare Verweigerung).
- [x] Demo-Packs neu erzeugt: beide Demo-Backgrounds mit 2024-Ursprung +
      zwei projekt-eigene Demo-Origin-Feats, house-rule-markiert.
- [x] charbuild.apply_origin + origin_options: serverseitig gegen Raum-
      Content validiert, nur Verteilung aus Client, 20-Obergrenze ablehnend,
      Wiederverwendung von _apply_feat (Kategorie-Check), Ledger-Eintrag
      characters.build.origin als Herkunftsnachweis, Replay im D96-Voll-
      recompute (exakt einmal, reload-/replay-/parallel-sicher), keine
      Auto-Migration, keine HP/AC/Slot-/Ressourcen-Anfasstung, Start-
      ausrüstung über getrennten Claim-Pfad unberührt.
- [x] REST GET/POST /api/build/{code}/{cid}/origin (Authz = Build-API).
- [x] UI: 🧬-Origin-Karte in der Raumvorbereitung (Report, +2/+1 vs. +1×3,
      Vorschau, Apply; englisch; Server autoritativ).
- [x] tests/test_d108_origin.py: 22 echte Integrationstests (beide
      Verteilungen, falsche Ziele/gleiche Ziele/Cap 20, Kategorie, fehlende
      Defs, 2014-Hintergrungsverweigerung, Cross-Room, Owner/DM/Foreign,
      Replay/Doppelklick/paralleles Posten, Reload/Ledger, keine Auto-
      Migration, Species-Stats, Startausrüstung doppelfrei, Build vor/nach
      Origin ohne Verdopplung, PUT-Fälschungsschutz). Keine neuen Skips.
- [x] Kanonischer Lauf: siehe kanonischer Stand unten.
