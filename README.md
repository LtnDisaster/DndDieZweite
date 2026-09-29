# 🐉 D&D Multiplayer Tabletop

A self-hosted virtual tabletop for Dungeons & Dragons: user accounts, a character
library, rooms with join codes, a shared grid map with DM map editor, hidden traps
and loot, two-click A* path planning, fog of war with line-of-sight and last-seen
ghosts, armor & magic items (AC, attunement, potions, charges), ability-aware dice,
chat, and an initiative tracker.

**Stack:** FastAPI + WebSockets + SQLite, vanilla JS/canvas frontend (no build step).

> Design rationale & decisions: see [`DECISIONS.md`](DECISIONS.md) (ADRs D1–D15).
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
7. **Chat** persists in the room's Chronicle.
8. DM: **⚔️ Start** rolls initiative once (DEX-mod aware); **Next ▸** advances the turn
   (gold ring = active combatant); **⏭ End round** closes the round and returns to the top
   of the order (a `— Round N —` marker is shown). DM can heal/damage via the sheet
   (−1/−5/+1/+5), kick players, add NPC tokens, take a **🛌 Long rest** (restores all spell
   slots + rechargeable items), and upload a map background (PNG/JPEG ≤ 8 MB).

## Grid, Map Editor, Traps & Loot

- **Two-click A\* path planning**: first click previews the route from your token to a
  destination cell, second click (or the Move button) commits it. The server recomputes
  the authoritative A* path (walls block, difficult terrain costs double) and animates
  the token step by step; the client-side preview mirrors the same algorithm. A DM
  dragging a token teleports it instantly.
- **🛠 Edit map** (DM): paint 🧱 walls, ⬜ floors, 🌿 difficult terrain; place ⚠️ hidden
  traps (label, save DC, damage dice) and 🎁 hidden loot — when the trap/loot brush is
  active, its properties are typed into **inline fields in the toolbar** (no browser popups,
  so it works even where modals are blocked); resize the map, optionally reset the fog; Save
  applies for everyone.
- **Traps**: the moment a character's token steps on a hidden trap the server rolls a
  DEX save (d20 + DEX-mod vs DC). Failure rolls the trap's damage and applies it.
  The table sees "⚠ X triggered a trap!" but only the player and DM see which trap
  and the details; afterwards it stays visible as triggered.
- **Loot**: stepping on hidden loot sends a private whisper to that player only and
  appends the item to the character's notes — the rest of the table learns nothing.
- **Fog of war + line of sight**: cells start dark; each token reveals a radius-6 area
  (shared exploration), streamed as terrain patches so fog lifts live during a walk.
  **Vision is strict and per-viewer**: a viewer only ever receives tokens inside their
  own sight. Anything outside simply never arrives — no `step`, no `token_add`. When a
  token a viewer *was* seeing leaves their sight, the client keeps it as a faded,
  dashed **last-seen ghost** pinned to its final known position (a "memory", not live
  info), and the server records the same ghosts so they survive a refresh.
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

## Layout

```
app/
├── main.py        # FastAPI app, logging, LOOP wiring on app.room.net, static serving
├── db.py          # SQLite schema + helpers (data/vtt.db, WAL, busy_timeout, tx())
├── auth.py        # bcrypt passwords, HMAC-signed session cookies, cookie_secure()
├── ratelimit.py   # in-memory sliding-window limiter for /login and /register
├── rooms.py       # REST: auth, characters, rooms, map upload, role-filtered state
├── path.py        # A* pathfinding (8-dir, no corner cuts, difficult terrain)
├── gear.py        # items/skills/spells SSOT: AC, attunement, charges, masking, skill/spell math
├── mapmodel.py    # map grid schema, sanitize, fog reveal, per-role filtering
├── ws.py          # WebSocket entry: auth, lifecycle, dispatch, re-export shim
└── room/
    ├── net.py        # clients, LOOP, broadcast/send, map helpers, per-room locks
    ├── visibility.py # LOS, ghosts, targeted token events, last-seen pruning
    ├── dispatch.py   # flat message registry -> handlers
    ├── movement.py   # walks + DM teleport (map-lock guarded)
    ├── tokens.py     # DM add/remove token
    ├── combat.py     # initiative + HP
    ├── dice.py       # server-authoritative, sheet-aware rolls
    ├── items.py      # use / attune / identify / recharge
    └── traps.py      # trap / loot resolution

app/static/
├── index.html
├── style.css
└── js/            # classic scripts, loaded in dependency order (shared globals)
    ├── 10_core.js   ├── 20_lobby.js   ├── 30_room.js
    ├── 40_ws.js     ├── 50_canvas.js  └── 60_main.js

tests/             # pytest unit (path/map/gear/dice) + integration (REST/WS) suites
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
./.venv/bin/python -m pytest          # 66 tests
```

The suite mixes fast unit tests (`test_path`, `test_mapmodel`, `test_gear`, `test_dice`)
with integration tests (`test_integration`) that drive the real ASGI app through
Starlette's `TestClient` — both REST and WebSocket — covering auth/authz, hidden-info
masking (peer private notes + unidentified magic), malformed-message resilience, DM-only
guards, strict line-of-sight/fog token filtering, atomic potion use, the attunement cap,
**round-based initiative**, **skill checks + spell-slot consumption (and the empty-slot
refusal)**, and **trap placement via `map_edit` triggering on a walk**. Tests run against an
isolated temporary `VTT_DATA_DIR`; no live server, browser, or network is required. Dev deps
live in [`requirements-dev.txt`](requirements-dev.txt).


## Notes

- Sessions: 30-day HttpOnly cookies signed with `data/secret.key`.
- All dice rolls and pathfinding are server-side (clients cannot cheat).
- Token movement is server-validated: players may only move their own token.
- Hidden traps/loot and unexplored terrain are filtered out server-side per viewer,
  so nothing secret ever reaches a player's browser.
- Out-of-sight tokens (strict radius-6 line of sight, per viewer) are likewise never
  transmitted; what remains client-side is a faded last-seen ghost, not live state.
- For public internet deployment, put a TLS proxy (nginx/caddy) in front.
