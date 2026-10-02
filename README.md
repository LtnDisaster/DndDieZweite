# 🐉 D&D Multiplayer Tabletop

A self-hosted virtual tabletop for Dungeons & Dragons: user accounts, a character
library, rooms with join codes, a shared grid map with DM map editor, hidden traps
and loot, footprint-aware server path previews, wall/door line-of-sight fog and last-seen ghosts,
armor & magic
items (AC, attunement, potions, charges), ability-aware dice, **combat conditions,
5e death saving throws, NPC natural attacks, doors that block movement and sight, AoE targeting
templates and a reusable bestiary**, server-authoritative saving throws, temporary HP,
hit-dice rests, resources, exhaustion and typed damage, chat, and an initiative tracker.

**Table QoL:** visibility-filtered game log (public / self / blind / DM), advantage and
disadvantage controls, `2d20kh1` style dice, map pins, pings, a two-click ruler,
private encounter templates, a party/selected/DM journal, token footprints and disposition.

**Stack:** FastAPI + WebSockets + SQLite, vanilla JS/canvas frontend (no build step).

> Design rationale & decisions: see [`DECISIONS.md`](DECISIONS.md) (ADRs D1–D37).
> Current status & open work: see [`TODO.md`](TODO.md).

## Run

```bash
./run.sh                 # http://localhost:8000
HOST=0.0.0.0 PORT=9000 ./run.sh
```

### Docker

```bash
docker build -t dnd-vtt .
docker run -d -p 8000:8000 -v dnd-vtt-data:/srv/data dnd-vtt
```

## How to play

1. **Register** an account (stored locally, bcrypt-hashed).
2. **Create characters** in the lobby library: race, class, ability scores, HP, AC,
   a **weapon list** (name, ability, proficient, damage dice like `1d8+3`, optional
   **magic bonus** `+N`), and an **Armor & Items** list (see *Items* below).
3. **Create a room** (you become the DM) or **join** one via its 6-character code.
4. In a room, click **Bring** on a character — it becomes your colored token.
5. **Two-click move** (players): click a destination to *plan* the route (a gold path
   preview appears; walls block, difficult terrain counts double), then a **second
   click on the same cell** — or the floating **Move** button — commits the walk.
   Click another cell to re-plan; **Esc**/**Cancel** aborts. DM can still **drag** any
   token to teleport it instantly.
6. **Roll** with the dice bar (`2d6+3`, d20 with ADV/DIS) — and pick an **ability**
   (+proficient) on any freeform roll to add that modifier from your sheet. **Sheet-
   aware rolls**: ability checks & saving throws (click a chip; toggle *proficient*,
   ADV/DIS) and per-weapon **⚔️ attack / damage / ×2 crit** buttons. Attacks honour a
   magic weapon's `+N` bonus on both to-hit and damage, and you can **override the
   attack ability** (e.g. a finesse-style DEX attack) from the sheet. Modifiers are
   always computed on the server; proficiency bonus is `2 + ⌊(lvl-1)/4⌋`. Nat 20 shows
   **CRITICAL**; crit damage doubles the dice. Rolls are visible to everyone.
 7. **Chat** persists in the room's Chronicle. Choose **Global**, **DM** or **Whisper**
    (or type `/w Bob …`, `/dm …`, `/g …`). The DM can speak as a **persona or NPC**, send
    temporary **narration overlays**, and trigger ambience or selective sound effects.
8. DM: **⚔️ Start** rolls initiative once (DEX-mod aware — for PCs **and** NPC stat
   blocks); **Next ▸** advances the turn (gold ring = active combatant); **⏭ End round**
   closes the round and returns to the top of the order (a `— Round N —` marker is shown).
   DM can heal/damage via the sheet (−1/−5/+1/+5), kick players, **add & edit NPC/enemy
    tokens** (see *NPC & Enemy Stat Blocks*), take a **🛌 Long rest** (restores HP, spell
    slots, hit dice and long-rest resources; arbitrary conditions are cleared only when
    explicitly requested), and upload a map background (PNG/JPEG ≤ 8 MB).

## Views (Tactical / Diorama)

Each player (and the DM) can independently pick **Tactical** (the top-down
canvas) or **Diorama** (a 2:1 isometric 2.5D view) from the room's
**Tactical | Diorama** buttons. This choice is **per-browser only**: it is
saved in your browser's local storage and never sent to the server, so two
players in the same room can use different views of the same shared world.
Nothing about gameplay (movement, fog, LOS, combat, permissions) depends on
the view. Diorama is a minimal prototype: floors, walls, doors (open/closed/
locked), and paper-card token billboards, all placeholder shapes. Precise
manual movement and the DM map tools remain in the Tactical view.

## Grid, Map Editor, Traps & Loot

- **Two-click A\* path planning**: first click requests a server preview; second click (or the Move
  button) commits it. The preview validates the requester's token, footprint, terrain, closed doors,
  collision and currently known area. The confirmed move still recomputes the authoritative A* route,
  animates the token step by step, and refuses an invalid final footprint. Active walks show a dashed
  ring and a DM-only **⏹ Stop** control. A DM dragging a token teleports it instantly.
- **🛠 Edit map** (DM): paint 🧱 walls, ⬜ floors, 🌿 difficult terrain; place ⚠️ hidden
  traps (label, save DC, damage dice) and 🎁 hidden loot — when the trap/loot brush is
  active, its properties are typed into **inline fields in the toolbar** (no browser popups,
  so it works even where modals are blocked); resize the map, optionally reset the fog, and use the
  👁/🌫 brushes to manually reveal or re-hide explored cells. Save
  applies for everyone.
- **Traps**: the moment a character's token steps on a hidden trap the server rolls a
  DEX save (d20 + DEX-mod vs DC). Failure rolls the trap's damage and applies it.
  The token stops on the trap; movement must be resumed with a fresh route.
  The table sees "⚠ X triggered a trap!" but only the player and DM see which trap
  and the details; afterwards it stays visible as triggered.
- **Loot**: stepping on hidden loot sends a private whisper to that player only and
  appends the item to the character's notes — the rest of the table learns nothing.
- **🚪 Doors**: place doors on cell edges with the 🚪 brush in the map editor (click the
  edge; 🚫 removes; a "start locked" box locks on placement). A door renders as a leaf with
  a 🔒 when locked and is revealed by the usual fog. **A closed or locked door blocks the
  pathfinder** (both the authoritative server A* and the client preview). The DM can open /
  close / lock / unlock / remove any door by clicking it; a **player may only open or close an
  unlocked door whose edge they are on or beside** (server-enforced — locking is DM-only).
- **Fog of war and LOS**: cells start dark; player tokens reveal only cells currently visible within
  a **radius-6 line of sight**, streamed as terrain patches. Walls and closed/locked doors block both
  sight and exploration. A diagonal ray through a grid corner is allowed only when both orthogonal
  transitions are open, so sealed corners do not leak vision. **Only player-owned tokens reveal**; NPC
  and DM tokens never lift player fog. The DM can reveal or re-hide persistent exploration manually;
  hiding memory does not blind a player who is currently seeing the cell. Opening a door recalculates
  LOS and reveals what the players can now legitimately see.
- **Token footprints**: Tiny/Small/Medium occupy 1×1, Large 2×2, Huge 3×3, and Gargantuan 4×4 cells.
  The token's stored position is the footprint's top-left anchor. Server pathfinding requires the whole
  footprint to fit in open terrain; a Large token cannot use a one-cell corridor, and spawns or size
  changes find a valid nearby placement. Same-owner tokens may intentionally pass through/overlap each
  other, while different tokens cannot finish overlapping.
  **Sight is per-viewer**: a viewer only receives live token data when at least one footprint cell is
  currently visible under server LOS.
  Anything outside simply never arrives — no `step`, no `token_add`. When a token a viewer
  *was* seeing leaves their sight, the client keeps it as a faded, dashed **last-seen ghost**
  pinned to its final known position (a "memory", not live info), and the server records the
  same ghosts so they survive a refresh.
  The server filters map *and* token data per recipient — hidden traps, loot,
  unexplored terrain, and out-of-sight tokens are never sent to a player at all.
- Pan the map with **middle/right mouse drag** or **WASD / arrow keys**.

## Armor, Magic Items & Attunement

Each character carries an item list (edited in the lobby):

- **Armor** — a basic AC (`ac`) plus a *light* flag (light armour adds your full DEX
  modifier; medium/heavy do not). If you wear no armour your sheet AC is used as-is.
- **AC bonuses** — any item with an `acBonus` (e.g. *Ring of Protection* `+1`) adds to
  AC, but only **once identified**. The room sheet shows the computed **AC**.
- **Potions / healing** — a `heal` dice (e.g. `2d4+2`); **Use** rolls it server-side,
  heals the character, and whispers the result only to the owner + DM.
- **Charges** — items can have limited charges (unlimited = `-1`); **Use** spends one
  and whispers when the item is **depleted**. DM **Recharge** (long rest) restores
  charges to their maximum.
- **Attunement** — attunable items are capped at **3** at once; the sheet shows an
  **Attune / Untune** button and a running `n/3` tally.
- **Magic & identification** — magic items can be added **unidentified**: other
  players and (on others' sheets) see only "Unidentified item" with all bonuses
  suppressed. The **owner** always sees their own items, and the **DM** can
  **Identify** an item to reveal its true name/properties to everyone.
- **Magic weapons** — a weapon's `+N` bonus adds to attack *and* damage rolls.
- **More item kinds** — beyond armor/potion there are now **shield** (adds its AC to your
  total once identified), **wand / staff / scroll / ring / tool / wondrous**, and a
  **📖 spellbook** (see below). Each shows an icon on the sheet.

## Skills & Spellcasting

- **Skills** — every character has the 18 standard 5e skills. In the lobby editor you cycle
  each one `– → ✓ proficient → ★ expertise`; the sheet shows the computed bonus
  (`ability mod + proficiency bonus × level`) and a **Roll** button that runs a skill check
  server-side.
- **Spellbook** — edit spells in the lobby (name, level, school, casting ability, cast mode
  *attack/save/none*, damage dice, save, range, duration) and set your **spell slots per
  level (1–9)**. To use it at the table, give the character a **📖 spellbook** item — that
  item is what unlocks the sheet's Spellbook panel.
- **Casting** — the sheet shows your spell attack bonus and save DC and per-spell buttons:
  **Atk**, **DC**, **Dmg / ×2 crit**, and **Cast ▸**. Casting a leveled spell consumes one
  slot (and is refused when none are left); cantrips are free. A **🛌 Long rest** (DM)
  restores all slots and rechargeable items.

All skill/spell math and slot accounting is authoritative on the server (`app/gear.py`,
`app/room/dice.py`).

All item math (AC, heal, attunement cap, charge decrement, identification masking) is
validated and computed on the server (`app/gear.py`).

## NPC & Enemy Stat Blocks

A token the DM adds with **＋ Token** carries a full stat block (stored on the token, not in
the character library). Click the token to open its sheet and edit it:

- **Ability scores** — STR/DEX/CON/INT/WIS/CHA, shown with modifiers. **Ability checks** and
  **saving throws** roll server-side from the block (toggle *proficient* / ADV / DIS).
- **HP / AC / level / speed** — the DM can heal/damage an enemy with the same ±HP buttons; its
  HP bar renders on the canvas (DM view only).
- **DEX-aware, everywhere** — a monster's initiative (`⚔️ Start`) and its **DEX save against a
  hidden trap** now use its real DEX modifier, and it **takes the trap's damage** on a failed
  save. (Previously NPCs had no stats and skipped both.)
- **Attacks** — add a reusable attack list (name, **to-hit** bonus, damage dice like `1d6+3`,
  optional save **DC** + ability). Pick a **target** from the dropdown and hit **Atk**: the server
  rolls `d20 + to-hit` **against that target's effective AC** (a PC's computed AC, or another
  monster's AC) and posts **HIT/MISS**, auto-rolling the damage on a hit (crit on nat-20). **Dmg**
  rolls damage only; a save-based attack posts its **DC**. All through the same dice engine.
- **Spellbook + slots** — add spells (name, level, school, casting ability, cast mode, damage)
  and set slots per level, exactly like a player sheet. **Atk / DC / Dmg / ×2 / Cast** roll
  from the block; a leveled cast consumes one slot (refused when empty). Spell attack / save DC
  reuse the same `gear` math as players, so there is one source of truth.

**NPC blocks are DM-only.** Players never receive the numbers: the `npc` block is stripped from
token data for non-DM viewers in both `/state` and live `token_add` events. Casting, damage and
initiative results are posted publicly as normal (as at a real table).

### Bestiary

Because a monster block *is* the data model, the **Bestiary** (DM tools) stores reusable monster
templates: on an NPC's sheet, **＋ Bestiary** saves the current block as a named template; the
Bestiary list then offers **Spawn** (click the map to drop a fresh token built from it) and delete.
Templates are **private to you** and intentionally **generic/homebrew** — no copyrighted stat catalog
is shipped.

## Conditions, Death Saves & AoE Templates

- **Conditions** — the sheet has a Conditions panel (and tokens show colored dots on the map). The
  DM flags any condition on any token; **players may flag their own**. The 15 standard 5e conditions
  are built in and homebrew names are accepted; a **round counter** (blank = "until removed") ticks
  down automatically whenever the DM ends a round, and a **🛌 Long rest** clears everything.
  **Concentrating** shows as a dashed gold ring. Conditions are *tracked and displayed*, not
  auto-enforced (mechanical effects stay a table call).
- **Death saving throws** — when a **player character** drops to 0 HP they start making death saves:
  a straight d20, **10+ succeeds**, below fails, **nat-20 regains 1 HP and becomes conscious**, **nat-1 = two failures**;
  **3 successes stabilise**, **3 failures are death**. The owner (or DM) clicks **Roll Death Save**;
  the sheet shows the ✓/✗ tally and the canvas marks the token (red ring dying, ☠ dead). Taking
  damage at 0 adds a failure (and damage ≥ your max HP kills outright); healing above 0 clears it.
  Monsters simply sit at 0 HP — no saves.
- **AoE templates** — the DM arms a template (**Burst / Square / Line / Cone**, size + direction +
  colour) and clicks the map; the shape is shown to **everyone** as a short overlay so the party can
  see the area. It is **purely visual** — resolving the area's effect stays a manual step at the table.

## Game Log, Dice & Advantage

- **Chat / Game Log tabs** separate prose from dice results. Game-log messages carry a
  server-assigned visibility: `public`, `self` (actor + DM), `blind` (DM sees the result,
  the actor only sees a request), or `dm` (DM only). Chat messages use global, DM or whisper
  channels and store authorized `recipient_ids` server-side. Filtering happens before data
  reaches the browser and again for `/state`, so hidden rolls and whispers are never merely
  CSS-hidden. Non-DM clients requesting `dm` visibility are safely downgraded to `self`.
- **Advantage / disadvantage** are applied server-side using the official two-d20
  keep-high/keep-low procedure. The dice bar and character sheet expose them separately.
- **Keep dice** — the parser understands bounded expressions such as `4d6kh3`,
  `2d20kh1`, `2d20kl1`, and modifiers before or after the keep clause. There is no `eval()`.
- **Cover** — attacks may explicitly declare half (`-2`), three-quarters (`-5`) or total
  cover. Total cover blocks the attack without rolling; reduced cover is reflected in the
  authoritative attack total.
- **Quick dice and a modifier field** let a player roll common dice without typing an
  expression. All totals and modifiers remain server-computed.

## Narrative Chat, Personas & Ambience

- **Global, DM and whisper chat** are persisted in the Chat feed. The server resolves all
  recipients; a whisper is sent only to its sender and selected participants. DM-only notes
  are visible to DMs, while player-to-player whispers are deliberately **not** secret-visible
  to the DM.
- **DM personas and NPC speech** are DM-only. A persona may not impersonate a real room-member
  username, and NPC speech must reference an existing NPC token in the room. Players cannot
  forge either provenance.
- **Narration overlays** are temporary centered messages for the table. The DM can address
  everyone or one player; private narrative/voice messages remain in authorized chat history.
- **Secret events** combine a private/public narrative with an optional DM soundboard effect.
  The sound is delivered only to the selected player(s).
- **Room ambience** supports direct HTTP(S), YouTube and Spotify URLs. The server validates the
  URL, rebuilds a fixed safe embed, persists the room state, and returns it on reconnect.
  Players can locally mute or adjust volume; local mute does not stop the DM's room-wide ambience.
- **Soundboard** entries are private to the DM that saved them and must use direct audio URLs.
  A trigger can target one player or everyone without exposing the sound to bystanders.
- The DM audio panel exposes **Secret event**, **Send narration**, optional targeted sound,
  ambience add/play/stop and soundboard management. Players see only the compact local
  ambience bar in Chronicle.

## Saves, Rests, Resources & Condition Tools

- **Saving throws** are stored as proficiency flags and always recomputed server-side from
  the character's ability score and level. The client's `prof` field is deliberately ignored
  for saves, so a crafted message cannot claim bonus proficiency.
- **Short rest** (owner or DM) lets a character spend hit dice, heal, and reset short-rest
  resources; it clears death if the character leaves 0 HP. **Long rest** is DM-triggered and
  restores HP, resources, slots and hit dice. Conditions are preserved unless the DM
  explicitly requests `clear_conditions`.
- **Temporary HP** absorbs damage before real HP; higher grants replace lower values. The
  owner and DM can set, add or clear it. **Inspiration** is a per-character counter.
- **Custom resources** have a name, current/max values and a long/short rest reset rule.
  The sheet exposes increment/decrement/reset controls.
- **Exhaustion** is stored as a 0–6 level. Players may view it; only the DM may change it.
- **Typed damage** accepts the 13 standard 5e damage types. A target may declare resistances,
  vulnerabilities and immunities; the server applies immunity before damage or a temporary-HP
  pool can absorb it, then doubles or halves the remaining amount.

## Encounters, Journal & Map Markers

- **Encounters** are private templates per DM. Pick bestiary creatures, quantities and an
  optional hidden flag, save them, then spawn the saved group onto the map. Spawned NPCs
  receive size, disposition and defensive data from their bestiary blocks.
- **Journal & handouts** are room-scoped DM tools. Notes can be DM-only, visible to the
  party, or restricted to selected users; players receive only what they may read.
- **Map pins** support DM-only, player-visible and reveal-on-explored visibility. Players
  cannot see the DM-only pins' data at all.
- **Pings** are ephemeral live-map signals. They are rate-limited and broadcast only to
  room members; they are deliberately not persisted as game state.
- **Ruler** is a client-side measurement tool: arm it, click the start cell, then the end
  cell. It uses the familiar diagonal 5 ft/10 ft table convention and never mutates state.
- Tokens can be marked **Tiny → Gargantuan** and **friendly / neutral / hostile**. Size is
  rendered on the map; NPC disposition is DM-only information.

## Layout

```
app/
├── main.py        # FastAPI app, logging, LOOP wiring on app.room.net, static serving
├── db.py          # SQLite schema + helpers (data/vtt.db, WAL, busy_timeout, tx())
├── auth.py        # bcrypt passwords, HMAC-signed session cookies, cookie_secure()
├── ratelimit.py   # in-memory sliding-window limiter for /login and /register
├── rooms.py       # REST: auth, characters, creatures, encounters, rooms, notes, map upload, role-filtered state
├── path.py        # footprint-aware A* (8-dir, conservative diagonals, doors, terrain, preview areas)
├── footprint.py   # token size -> n×n footprint, collision and placement helpers
├── los.py         # deterministic wall/door line-of-sight and visible-cell calculation
├── gear.py        # items/skills/spells SSOT: AC, saves, defenses, resources, attunement, charges, skill/spell math
├── npc.py         # NPC/enemy stat blocks on tokens: sanitize, DEX mod, attacks, gear spell-math adapter
├── conditions.py  # conditions/status-effects SSOT: catalog, clean/add/remove, round decrement
├── mapmodel.py    # map grid schema, sanitize, fog reveal, doors (blocked edges), per-role filtering
├── ws.py          # WebSocket entry: auth, lifecycle, dispatch, re-export shim
└── room/
    ├── net.py        # clients, LOOP, broadcast/send, map helpers, per-room locks
    ├── visibility.py # footprint LOS visibility, ghosts, targeted token events, last-seen pruning
    ├── fog.py        # DM manual exploration reveal/hide
    ├── dispatch.py   # flat message registry -> handlers
    ├── movement.py   # walks, DM teleport/stop, trap auto-stop, authoritative path previews
    ├── tokens.py     # DM add/remove token + NPC block, size/disposition edit
    ├── health.py     # PC/NPC HP, temp HP, typed damage, death-state transitions
    ├── combat.py     # initiative + HP handlers + condition round tick
    ├── chat.py         # global/DM/whisper chat, personas, NPC speech, narrative delivery
    ├── audio.py        # safe URL parsing, room ambience state, selective sound triggers
    ├── secret_events.py # private narrative + targeted sound composition
    ├── gamelog.py      # visibility-filtered dice/system game-log delivery
    ├── status.py     # temporary HP, inspiration, exhaustion handlers
    ├── encounters.py # saved encounter spawn handler
    ├── pings.py      # rate-limited ephemeral map-ping broadcast
    ├── conditions.py # cond_add / cond_remove handlers
    ├── death.py      # death saving throws (5e) for player characters
    ├── doors.py      # door open/close/lock/remove (DM) + adjacent player toggle
    ├── aoe.py        # AoE template relay (visual only)
    ├── dice.py       # server-authoritative rolls, saves, attacks, cover, rests, resources
    ├── items.py      # use / attune / identify / recharge
    └── traps.py      # trap / loot resolution

app/static/
├── index.html
├── style.css
└── js/            # classic scripts, loaded in dependency order (shared globals)
    ├── 10_core.js   ├── 20_lobby.js   ├── 30_room.js
    ├── 40_ws.js     ├── 50_canvas.js  ├── 55_diorama.js
    └── 60_main.js

tests/             # pytest unit (footprint/path/LOS/map/gear/dice) + movement-fog + integration suites
```

## Configuration (environment)

| Variable | Default | Effect |
|---|---|---|
| `VTT_DATA_DIR` | `./data` | Where `vtt.db` and `secret.key` live |
| `HOST` / `PORT` | `127.0.0.1` / `8000` | Bind address (`run.sh` reads these) |
| `VTT_COOKIE_SECURE` | unset | Force `Secure` on the session cookie |
| `VTT_TRUST_PROXY` | unset | Trust `X-Forwarded-For` for rate limiting |
| `VTT_LOG_LEVEL` | `INFO` | Root logging level |

Session cookies are always `HttpOnly` + `SameSite=Lax`; `Secure` is added automatically
under HTTPS (direct, or via `X-Forwarded-Proto`) or when `VTT_COOKIE_SECURE=1`. See
[`.env.example`](.env.example).

## Tests

```bash
./.venv/bin/python -m pytest          # 201 tests
```

The suite mixes fast unit tests (`test_path`, `test_mapmodel`, `test_gear`, `test_dice`,
`test_npc`) with integration tests (`test_integration`) that drive the real ASGI app through
Starlette's `TestClient` — both REST and WebSocket — covering auth/authz, hidden-info
masking (peer private notes + unidentified magic), malformed-message resilience, DM-only
guards, per-viewer fog token filtering, atomic potion use, the attunement cap, round-based
initiative, skill checks + spell-slot consumption (and the empty-slot refusal), and trap
placement via `map_edit` triggering on a walk. Also covered: **NPC stat blocks**;
**conditions**, **deterministic death saves**, **NPC attacks**, **doors**, **AoE**, and the
**bestiary**; **game-log public/self/DM/blind visibility**, deterministic **keeping dice**
parsing, server-authoritative **saving throws**, **typed damage/resistance/immunity**,
**cover**, **short/long rest**, **temp HP/resources/exhaustion**, **private encounters**,
**room journals/handouts**, **map-pin visibility**, **rate-limited pings**, DM-only
**size/disposition**; **chat/whisper/DM-persona/NPC-speech privacy**, **narrative overlays**,
**secret events**, **safe audio URL parsing**, **DM-private soundboards**, room ambience and
**selective audio delivery**. Tests run against an
isolated temporary `VTT_DATA_DIR`; no live server, browser, or network is required. Dev deps
live in [`requirements-dev.txt`](requirements-dev.txt).


## Notes

- Sessions: 30-day HttpOnly cookies signed with `data/secret.key`.
- All dice rolls and pathfinding are server-side (clients cannot cheat).
- Token movement and path previews are server-validated; players may move/preview only their own token.
- Hidden traps/loot and unexplored terrain are filtered out server-side per viewer,
  so nothing secret ever reaches a player's browser. Game-log visibility, chat/whisper
  recipients, journal recipients, encounter ownership, NPC stat blocks and NPC dispositions
  obey the same rule.
- Out-of-sight tokens (per-viewer radius-6 footprint LOS blocked by walls and closed/locked doors)
  are likewise never
  transmitted; what remains client-side is a faded last-seen ghost, not live state.
- For public internet deployment, put a TLS proxy (nginx/caddy) in front.

## License & Attribution

DnDTable is an independent project, not affiliated with Wizards of the Coast.
Its rules foundation is intended to come from the **D&D SRD 5.1**, used under
the **Creative Commons Attribution 4.0 International (CC BY 4.0)** license.
The exact required attribution text, the content boundary (what the SRD does
*and does not* cover), and rules for third-party assets are documented in
[`ATTRIBUTION.md`](ATTRIBUTION.md).
