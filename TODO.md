# TODO — D&D VTT (`/home/alp/Test`)

Living checklist. "Done" = shipped and covered by an in-repo test.
Verify state with:

```bash
./.venv/bin/python -m pytest                       # 162 tests (unit + integration)
./.venv/bin/python -m compileall -q app            # byte-compile check
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
- [ ] **Fog granularity:** exploration is one shared room bitmap. Manual reveal/hide is global to all
      players; private per-player fog requires a schema change.
- [ ] **Client math mirror:** the browser mirrors gear skill/spell bonus math (`_smod`/`_pb`
      in `js/10_core.js`) for previews only; the server recomputes authoritatively — keep the
      two in sync (same drift risk as the A* mirror in P2).
- [ ] Re-run the live suite 1 after ANY default-grid/token-position change (D15: movement
      tests are vision-adjacent).

## P3 — Feature gaps (nice, not blocking)
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
