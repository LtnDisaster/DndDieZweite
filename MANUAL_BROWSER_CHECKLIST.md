# Manual Browser Checklist

Run the **BUILD CHECK first**. A mixed/stale frontend bundle reproduces every
old symptom (black canvas, weird toasts) — deeper gameplay testing is
BLOCKED until steps B1–B5 pass. Report, don't continue, on any failure.

## BUILD CHECK (blocking — D78)

1. Open the application (fresh rebuild, private window recommended).
2. Open the browser console (F12): first line must report `BUILD <token>`.
3. Open `/api/build` in the same browser: it must show the SAME token.
4. DevTools → Network: every `10_core.js`, `20_lobby.js`, `30_room.js`,
   `40_ws.js`, `50_canvas.js`, `55_diorama.js`, `60_main.js`, `99_boot.js`
   and `style.css` request must carry `?v=<that token>`.
5. No red **FRONTEND GENERATION MISMATCH** banner anywhere on the page.

## SMOKE TEST (blocking)

1. DM creates/opens a room.
2. Player joins (same or second browser).
3. Player creates or selects a character (lobby editor) and clicks **Bring** —
   expect the "takes a seat at the table" toast. If the toast instead says the
   view could not initialize, the character IS seated (server truth) — report
   it as a presentation bug, not a Bring failure.
4. Player sees map, **not complete blackness** (area around own token; rest
   may be fog). If black: check console for `ReferenceError` (bundle!) and
   open the page again with `?debug`.
5. Player sees **own token** (view opens centered on it — D75).
6. Player moves in Tactical (click → gold preview → confirm).
7. Player clicks **Diorama** (topbar switch).
8. Player still sees map/token in Diorama (view auto-frames the visible world).
9. Player moves in Diorama (click own token, click destination, confirm).
10. Player switches back to **Tactical**.
11. Token is at the **same world position** as before switching.
12. Fog remains coherent (no new black regions, no wrong-cell fog).
13. Player clicks **← Lobby** and is back at room selection.
14. DM clicks **Delete** on a disposable test room in the lobby, confirms the
    armed button (`Delete "<name>" permanently?`).
15. The room is gone from both lists; joining by its old code fails.

## COMBAT LOOP (D79 — after smoke passes)

1. **Exploration movement:** before any combat, walk your token a clearly
   long route (> speed) — it must complete. No combat budget applies.
2. **Start combat:** DM clicks ⚔️ Start. The Initiative panel shows the round
   line, the order, and the compact turn bar (active name, move x/y, A/B/R).
3. **Active token movement:** when it's your turn, move — the turn bar's
   movement counter drops by exactly the route cost shown in the preview
   (e.g. 3 of 6 for 3 straight steps).
4. **Budget display:** remaining/total visible at a glance; the path preview
   shows `cost/budget` and marks an unaffordable route.
5. **Over-budget attempt:** confirm a too-long route — the token walks until
   the budget runs out and stops with "Out of movement — Dash or End Turn"
   (never silently beyond).
6. **Dash:** click 💨 Dash — the Action chip flips to spent and the movement
   total grows by one speed (e.g. 6 → 12); you can now walk the extra range.
7. **Second Dash:** must be refused ("No action left this turn").
8. **End Turn:** click End Turn (or DM clicks Next) — initiative advances.
9. **Next combatant:** the turn bar shows the new active token with a FULL
   budget (x/6) and fresh A/B/R.
10. **Tactical → Diorama → Tactical** mid-turn: move spent, A/B/R, token
    position and initiative must be exactly as before the round trip.
11. **End combat:** DM clicks End — turn bar disappears, combat ends.
12. **Exploration again:** walk a long route — no budget applies any more.

## CONDITIONS & TURNS (D80 — Tactical only)

1. **Timed condition:** open your token sheet → Conditions row; add e.g.
   poisoned with rounds 2, anchor "round end". The chip shows "(2r)".
2. **Start combat** (DM ⚔️).
3. **Duration visible:** the chip still counts 2 during round 1.
4. **End turns** until one full round wraps — chip shows "(1r)"; not before
   the wrap, not twice at it.
5. **Exact expiry:** after the next wrap the chip is gone. Repeat with anchor
   "my turn start" — it must change ONLY when your turn begins, and a "my
   turn end" condition must clear the moment your turn ends.
6. **Apply prone** (DM or yourself) — dot on the token, chip "Prone".
7. **Stand Up:** when it is your turn, the Conditions row shows a "Stand Up"
   button — click it.
8. **Budget:** the turn bar goes Move 6/6 → 3/6 immediately; the token did
   not move.
9. **Move with the rest:** walk up to 3 squares — works; a 4th is refused.
10. **Down a creature** (DM sets your HP to 0): any move attempt is refused
    with "cannot move while downed"; the DM can still push/teleport it.
11. **Voluntary movement rejected** also with unconscious/stunned applied.
12. **End combat:** prone outside combat stands for free; long walks stay
    unlimited and no condition duration ticks while exploring.

## RECTANGULAR FOOTPRINTS (D81/15B — Tactical only)

1. Open an existing room.
2. Confirm the OLD tokens are visible (the 15B incident: they were gone).
3. Select an existing token (your own, or any token as DM).
4. The sheet shows a labelled **Footprint** row (W, H, Apply) — no hidden UI.
5. Set Width 3, Height 7 and hit Apply.
6. The token visibly becomes a 3×7 rectangle at the SAME spot instantly.
7. Press F5 (refresh) — it is still 3×7 and the row shows 3 and 7.
8. Move it once — walk/preview account for the whole rectangle.
9. Select an old Large NPC: the row shows 2×2 (its size category) — untouched.
10. Try a footprint that does not fit (e.g. 10×10 in a corridor): refused,
    error message shown, old size and position preserved.

## VISUAL SIZE, ROTATION, WORLD OBJECTS, COMPANIONS (D82 — Tactical only)

1. Open an EXISTING room: nothing looks changed (visual defaults to the
   mechanical footprint — legacy tokens render exactly as before).
2. Select a token: a labelled **Visual Size** row (W, H, Apply) sits below the
   Footprint row, and a **Rotation** row (⟲ degrees ⟳ 0°) below that.
3. Keep Footprint 1×1, set Visual Size 3×7, Apply: the artwork grows tall and
   stays CENTERED on the token's cell; movement preview/collision still use
   exactly the 1×1 (walk it through a one-cell corridor — it fits).
4. Footprint 3×7 with Visual Size 1×1: small circle, but the whole 3×7 still
   collides — select it (or press `?debug` / open the map editor) and the
   collision outline proves the occupied cells.
5. A visual resize NEVER needs clearance (no "does not fit" error) and never
   moves anything; the mechanical resize still refuses an ill-fitting rect
   exactly as in the D81 checklist — the two operations are independent.
6. The collision outline is only visible while the token is SELECTED, while
   map-editing, or with `?debug` — not as a permanent translucent block.
7. Click on the outer artwork of a big visual token (outside its real cells):
   the token gets selected (presentation hit area; gameplay unaffected).
8. Rotation ⟲/⟳: the body rotates in 90° steps — non-square visuals visibly
   swap orientation; square/circle visuals show a small gold facing wedge.
   Labels, HP bars and condition dots stay upright. D83: the FOOTPRINT turns
   with the entity (see the D83 section below for the real checks); F5 keeps
   the facing.
9. DM map editor 🕹️ brush: place a Lever (op "toggle state"), close the
   editor. Players see the marker on explored ground.
10. Player clicks the lever from across the map: "Walk up to it first".
    Adjacent: state flips — marker turns green/grey in BOTH windows, F5 keeps
    it, a 🕹 line appears in the chronicle.
11. Lever with op "door: open/close nearest" placed next to a door edge:
    player clicks the lever → the door swings open with the normal door fog
    reveal; again → closes. A LOCKED door resists ("It won't budge."). A
    DM-only lever is invisible to players and refuses them without leaking
    anything; a lever wired to a SECRET door answers "Nothing happens." and
    the secret door stays invisible.
12. NPC sheet → "Controlled by: led by <player>": that player can move the
    token, preview paths, add conditions, use its turn (combat), cast through
    it and open doors next to it. An unrelated player is refused for all of
    these; the DM changes nothing. F5 keeps the assignment; the sheet header
    shows "· led by <player>".
13. Revoke (—""): the player's move attempts fail immediately; DM still acts.
14. Fog rule: a controlled companion standing in unexplored dark is VISIBLE
    to its controller (it's the token they play) but lifts NO fog around it
    — the surroundings stay black until the DM reveals.
15. NPC sheet → "Mounted on: rides <token>": assign, F5 — persists. Assign
    the reverse direction (mount rides its own rider): "riding cycle" refused.
    Ride itself: refused. Tokens from another room: refused. Carrying moved to
    the D83 section below (Sprint 17).

## ROTATION-ORIENTS / CARRYING / MODES / FORCED (D83 — Tactical only)

GEOMETRY
1. Give a token mechanical Footprint 3×7 (sheet) and an independent Visual
   Size (e.g. 1×5): the artwork and the collision rect differ — select it and
   watch the outline. F5: both persist.
2. Confirm the artwork is CENTERED on the footprint (visual 1×5 on a 3×7:
   symmetric overhang top/bottom, not hanging off a corner).
3. Rotate 90° (⟳): the token stays on the same spot — the FOOTPRINT becomes
   7×3 (select it; the collision outline proves it), the artwork turns with
   it, and the doubled centre did not visibly jump.
4. Rotate 180° back: the footprint is 3×7 again at the EXACT original cells.
5. Walk a rotated 2×4 through a 2-wide corridor: it fits (still 2 wide — the
   box turned back at 0/180 would not; check with ⟲/⟳ that 90 makes it 4×2
   and the corridor preview then refuses).
6. Rotate a wide token tight against a wall/another token: refused with "No
   room to turn there" — old facing AND old position AND old cells intact.
7. Visual 3×7 with mechanical 1×1: the artwork reaches over walls, but path
   previews and finish checks still use only the 1 cell (walk it into a
   one-cell corridor — it fits).

MOUNT CARRYING
8. Mount a rider on a mount (sheet "Mounted on"), then move the MOUNT (walk
   or DM drag): the rider tracks every step, centred inside the mount.
9. Move the mount through cells the rider sits on: never self-blocked.
10. Unmount (—""): the rider is re-homed to a legal adjacent cell instead of
    standing inside its former mount; move the mount again — rider stays put.
11. Nested chain (A on B on C): moving C carries B and A; refresh keeps all
    positions and relationships; cycles still refused (D82 pin).

MOVEMENT MODES
12. NPC with a fly speed: sheet shows Move-mode chips (🚶 walk / 🕊 fly ft).
    Creature WITHOUT a speed: that mode is refused by the server even if the
    client asked ("This creature has no fly speed").
13. In combat on its turn: move while walk selected until the meter is spent;
    switch to fly — fly has its own budget and still works; switch BACK to
    walk: the walk meter is NOT refilled. Dash doubles every mode exactly
    once; nothing else regenerates movement.
14. Fly over a difficult-terrain strip / elevation cliff: costs 1 per square
    and crosses the cliff; the same route on foot costs double / stops.
    Flying still cannot cross walls or closed doors.

FORCED MOVEMENT (DM panel / console)
15. Push a token: it stops at the first illegal cell (wall/closed door/
    occupied); pull moves toward the source; teleport may skip the path but
    never an illegal destination.
16. Target's move meter is UNCHANGED after any forced move (forced ≠ voluntary);
    a DOWNED/incapacitated token can still be pushed or teleported by the DM.
17. DM knocks a token prone ("knock_prone" op / future trap): it shows the
    normal prone condition and must pay the normal Stand Up cost — the same
    one prone system, no second one.

No Diorama verification anywhere (out of scope by decision).
16. Diorama shows none of the new UI/objects (out of scope, by design) and
    old data never shows anything new until the DM assigns it.

## Extended manual checks (after smoke passes)

- Two clients: one stays Diorama while the other stays Tactical (views are
  independent, world state shared).
- DM: Tactical and Diorama both fine; map editor opens in Tactical.
- DM drags a player token deep into the world → the player's view does NOT
  jump; the player's next own-action recenters via ← Lobby → reopen.
- Token teleports show no coordinate drift after resize/growth (fixed map:
  auto growth is flag-off by default, D77).
- Room deletion with an open player WS: player lands in lobby with a toast,
  browser does not spam reconnects (check network tab: no reconnect loop).
- `?debug` URL suffix (dev mode): topbar HUD shows build token +
  `integrity=ok`, view mode, canvas size, cam/camT/camD, camInit trace,
  `grid=y/n` + window/origin/dims, own token cell/screen pos,
  known/explored/painted, `bring=<last result/error>`, last client error.
  Black screen triage: `integrity=FAIL` or any `ERR:` line → bundle/client
  bug (console shows the exact ReferenceError). `grid=n`/payload issues →
  server/WS. `known>0, painted=0` → camera/framing. `known=0` without own
  token → legitimate fog (Bring first). Never expose hidden data.

## Sprint 18 — geometry centre (D84), artwork (D85), floors (D86), darkness (D87)

Geometry (needs a big token — make one 3x7 with footprint W=3 H=7 and rotate 90°):
- Click a FREE cell far away with the big token selected → the dashed ring sits
  exactly where the token's CENTRE will land; the token walks and its centre
  box covers the clicked cell. No "No path there" while the ring is on free air.
- Drag-drop a token: it lands with its CENTRE under the pointer, not shifted.
- Press Escape → sheet closes, selection ring gone.
- The collision footprint appears only while selected / editing / `?debug` and
  is a thin dashed OUTLINE (never a filled colour block).
- Companion view: a player OPERATING a 3x7 token (DM set controller) sees it
  as 3x7 (rotated 90° → 7x3) — never as a small circle; refresh (/state path)
  keeps the same shape.

Artwork (sheet row "Artwork", DM row on NPC tokens too):
- Upload a PNG (<1.5 MB) → the token immediately wears it inside its body
  ellipse, artwork turns WITH rotation (exactly one turn — no double rotation),
  aspect preserved.
- Non-PNG (rename a JPG to .png and try) → clean error toast, no broken token.
- Another account cannot load the asset URL (404); deleting an asset a token
  wears is refused until removed from the token ("— none —" + Apply removes).
- Players can attach only their OWN uploads; DM can attach any (403-less: the
  error toast "Not your asset").

Floors (sheet row "Floor"; DM adds floors via the ＋ field):
- DM adds floor "crypt", moves an NPC there → for the player on the primary
  floor the NPC VANISHES (token_leave, fog-memory ghost stays at the stairs).
- Move the player's own token to "crypt" → the NPC reappears there; they can
  occupy the SAME map cells as tokens on the other floor without blocking.
- Refreshing the page (player) shows only their own plane; the DM sees all.
- Floor name fields refuse path-like junk (`../x`).

Darkness (DM candle button 🕯 in the brush bar):
- Toggle dark ON as DM: for players WITHOUT light only their own token and its
  immediate footprint remain — terrain goes dark beyond that.
- Player sets Light (sheet row) to 6 + Apply → world opens an LOS-limited
  bubble; cells behind walls stay dark (real shadows); set back to 0 → the
  bubble closes again (seen tokens vanish via normal leave).
- DM view is never darkened. Toggle OFF restores classic vision.
- Toggling unrelated map edits (draw a wall) does not silently flip darkness.

## History

- Sprint 30: D101 section added (room preparation screen, guided character build
  from the room's CSV content, background starting-gear grant, and the apply→sheet
  refresh fix). Canonical close: 694 passed + 1 skipped (node 22 runs the real-JS
  tests). No real browser runtime — the guided UI is additionally pinned by source
  asserts in `tests/test_d101_prep.py`; walk the checkboxes below in a real browser.
- Sprint 20: D90 section added (caster-plane ability truth, plane-scoped AoE/ping,
  resize pin/elev carry). Canonical close: 499 passed + 17 skipped. The
  "browser flow" automation is a Node-vm harness — no real browser runtime
  exists on the test host.

- Sprint 18: D84–D87 section added (centre contract, artwork pipeline, floor
  planes, darkness/light). Canonical run at close: 474 passed + 15 skipped.
- Sprint 17: D83 section (rotation orients the footprint, carrying riders,
  movement modes, forced layer, knock-prone). D82 rotation step adjusted.
- Sprint 16: D82 section added (visual size / rotation / world objects /
  controller / mount, Tactical only). Diorama deliberately unchanged.
- Sprint 12: BUILD CHECK added — `ReferenceError: gridOrigin is not defined`
  in a real browser proved mixed script generations were the black-canvas
  root cause across sprints 10–11 (DECISIONS D78). Bring step added to the
  smoke test (previously missing — the tester had no token and read the
  legitimate fog as a total failure).
- Sprint 11: smoke test created after black-screen/Diorama one-way/room-delete
  manual regressions (see DECISIONS D75–D77, MANUAL_FIX_NOTES.md).

## Sprint 19 — Floor maps, stair connectors, lighting v2 (D88/D89)
- [ ] DM: create floor "crypt", select it in "Viewing plane" — map, grid and canvas show the crypt; token positions unchanged; switch back restores primary view.
- [ ] DM: edit walls/dark/fog while crypt is selected → primary map untouched; a player on primary sees none of it.
- [ ] DM: place a "stair" object (Edit map → Object → stair → target floor/cell); player walks next to it, clicks 🕹 → token moves to crypt at the destination; player's board re-renders the crypt; chronicle shows the 🪜 line.
- [ ] DM: stand an NPC on a stair destination first → player's attempt answers "No room down there." and the token stays.
- [ ] DM: enable darkness on crypt only → crypt is dark (light-governed), primary stays normally lit.
- [ ] DM: place a lamp (Object → lamp) on crypt; a player on crypt sees what its glow circle reaches; player clicks 💡 to extinguish → circle and revealed tokens vanish for everyone on crypt; reload page → lamp stays off.
- [ ] Player: token sheet → Darkvis. 8 in a dark room with no light → that player now sees ~8 cells around their token, nobody else gains sight of it.
- [ ] DM: token light on an NPC another player controls → controller gains no light-vision from it.
- [ ] Old room (created before Sprint 19): map, fog, doors, levers behave exactly as in Sprint 18.

## Sprint 20 — Cross-floor AoE/ping truth, resize carry (D90)
- [ ] DM views "crypt"; arms AoE template and clicks: a PLAYER standing on the crypt sees the template; a player on primary sees nothing. Switch DM view back to primary → previously shown foreign-plane template does NOT linger/paint.
- [ ] Player pings on their own plane: seen by the DM and plane mates only; a player standing on another plane sees nothing. Ping spam (≥6 in 2s) still gets rate-limited.
- [ ] Player token on primary, DM moves an NPC to "crypt" at the SAME map coordinates; player casts an area ability at those cells: chronicle/roll effects hit only the primary token — the crypt NPC is not named, not counted, HP unchanged (check sheet as DM).
- [ ] Player targets the crypt NPC directly (token id known): answer is the ordinary "No target token" — identical to a bogus id.
- [ ] DM sets light/darkvision/artwork/floor on a hidden NPC while a player watches: that player's console/network sees no token_image/light/darkvision/floor events for the unseen token.
- [ ] DM edits map with resize (e.g. 40→30 wide) on a plane that has pins and elevation steps: pins that still fit are where they were (same titles/visibility), elevation heights survive; pins outside the new window drop (by design).
- [ ] Lamp toggled off on a plane → refresh the page (F5): still off. A DM with an OLD editor tab saves the map: lamp stays off.
- [ ] Tactical smoke (mirrors tests/test_browser_flow.py — automated there in a Node vm, NEVER in a real browser so far): open Tactical → own token visible → click a rectangular (≥2 wide) token: it selects → click a valid destination: gold preview appears within budget → confirm → token walks to the anchored final cell → F5 refresh: token still in place and still selectable at that spot.

## Sprint 23 — sheet & combat (D93)
- [ ] DM → Inv tab: name „Langschwert", kind weapon, dmg `1d8`, type slashing, abil STR, ☑ prof → **+ Def** → grant ×1 to a player. Player: 🎒 Inv → Equip into Main hand → sheet opens on the token: Attack section shows `⚔️ Langschwert +7` (STR3+Prof2+… verify vs your sheet), Initiative/Prof chips above the HP bar.
- [ ] Player attacks Dummy token (target select → Attack, Action): dice line names the target AC + HIT/MISS; HIT posts damage `1d8+3`. DM applies via existing HP buttons. Unequip → Attack section empty, attacking errors „No equipped weapon".
- [ ] Combat: DM starts initiative → on player's turn first attack OK, second same turn refused „No action left"; slot=Bonus attacks once more; off-turn attack refused; end combat → attacks free again. Reload (F5) mid-combat: tracker + slots intact.
- [ ] Privacy: second player logs in → clicks first player's token: compact public card (HP/AC/Speed), no items/spells/stats. DM sees the full sheet.
- [ ] Legacy: a character with a classic `weapons` entry still attacks by name exactly like before (no AC verdict).
- [ ] D94: DM hides a monster (out of your vision) → you attack it by id (devtools): error is exactly „No target token" — same as a wrong id. DM still sees/attacks it normally.

## Sprint 25 — CSV rule packages (D95)
- [ ] DM → 🎲 DM tab → „📚 Rule packages": the counts line shows `0` for all kinds in a fresh room. Choose one CSV from `app/content_pack/` (e.g. `items.csv`) with mode **Preview** → Upload: report lists the file `· ok` (or `file/line/column` errors), and NOTHING is written yet (counts stay 0).
- [ ] Switch to **Apply** → Upload `items.csv` → counts gain `item: N`. In the 🎒 Inv tab the DM can now grant `sword_plus1`; a character that equips it attacks with the +1 typed bonus (server profile, not a client claim).
- [ ] Re-Apply the SAME file → report shows `=N` unchanged, `+0` new, no duplicates (counts unchanged). Import a file whose row has a bad `kind` → Preview names the file, line, and column; a good file uploaded in the same run is still reported independently.
- [ ] **Replace** a changed row overwrites it; **Apply** on the same differing id instead reports a `⚠conflict` and keeps the old value.
- [ ] Upload a **ZIP** of several `*.csv` (auto-detected): each kind imports independently; an unknown `notes.csv` inside is `· skipped`, not fatal.
- [ ] ⬇ **CSV** exports the chosen kind as a download; ⬇ **All (ZIP)** downloads every kind. A value like `+1d8`/`=evil` re-imports byte-identically (export prefixes `'` to defuse spreadsheets; import reverses it).
- [ ] A PLAYER (non-DM) sees no DM tab; calling `/api/content/<code>/kinds` without DM (or logged out) returns 403/401.
- [ ] Persistence: import spells, then restart the container — the castable abilities are back (re-registered from the DB at startup).

## Sprint 25 — Character build (D96)
- [ ] Player opens their own token's sheet → „⬆️ Build / Level-up": class `scout`, level `1`, **Plan** → `plan ok · 1 levels` and `need: skills 4/…`. Fill 4 skills into the choices box → **Apply** → toast „Built to level 1"; sheet shows Lv 1, HP 14, the 4 skills ✓, saves DEX/INT ✓.
- [ ] Build to `8` with `{"subclass":"tradition_stalker","levels":{"4":{"ability":{"dex":2}},"8":{"feat":"feat_keen"}}}`: success; DEX +2 (level-4 ASI) and WIS +1 (Keen Mind) show on the sheet; Perception/Investigation become proficient; subclass shows.
- [ ] Missing a choice (empty choices, target 8): **Apply** shows „choices still needed" with the list (skills/subclass/level) and NOTHING changes (still the previous level/HP).
- [ ] Repeat guard: Apply the SAME level again → refused (build is forward-only); a lower target likewise refused. Advancing 5→8 keeps the earlier level-4 ASI (recompute from base, not stacked twice).
- [ ] DM opens the same player's sheet → can Build it too (room-DM). A different room member (not the owner, not DM) sees no Build controls and gets 403 from `/api/build/...`.
- [ ] Restart the container: the sheet's Build ledger (class, „built to N", subclass, per-level features) is still shown — it lives in `characters.build`.

## Sprint 25 — Spellcasting (Phase C, D97)
First import `spells.csv` + `classes.csv` from `app/content_pack/` (DM → 🎲 Rule packages → apply) so `adept`/`warden`/`seer` and the scaling spells exist.
- [ ] Known-caster choices: build `seer` to `1` with `{"skills":["persuasion","religion"],"levels":{"1":{"cantrips":["spark","mend","chill"],"spells":["arcane_ward","bolt","smite"]}}}` → Apply ok. Open the sheet: 📖 Spellbook lists the chosen spells and a slot line `L1 2/2`. Without the `spells` pick, Apply says „choices still needed" (kind `spells`) and writes nothing.
- [ ] Slot TABLE not total-derived: build `warden` to `2` (choose 2 cantrips + 2 spells). The spellbook shows only `L1 2/2` and NO 2nd-level slot — a half caster. (A level-2 full `seer` shows `L1 3/3`; a level-5 one shows `L1 4/4 · L2 3/3 · L3 2/2`.)
- [ ] Cast + upcast: with a `seer`, cast `spark` (cantrip, no slot) — a `✨ Use` button rolls; at character level ≥5 the cantrip die is larger. For a leveled single-target spell the row shows a slot-level selector; pick a higher level and Cast — the HIGHER slot's pip drops (`L3 0/1`), not the base one.
- [ ] Duplicate guard: spam the same Cast (same request) fast — the slot decrements ONCE and the target takes damage ONCE (no double-fire).
- [ ] Class resource: a `seer` built to N shows `Sorcery Points = N` (reset short). After spending, a **short** rest refills them; a **long** rest refills slots AND sorcery points.
- [ ] Prepared vs known: an `adept` (prepared) shows its whole class list as castable and notes that daily re-preparing is a long-rest/DM step; a `warden`/`seer` (known) only shows the spells actually chosen.
- [ ] Area spells (`bolt`) show `🎯 map` on the sheet — aim and cast them from the tactical map, not the sheet.
- [ ] Existing legacy spellbooks are unaffected: a character with a 📖 spellbook item still casts its data-only spells as before.

## Sprint 27 — Weapons, equipment & magic items (Phase D, D98)
- [ ] DM → 🎒 Inv → „🧩 Item definition" editor: pick a kind (e.g. weapon), set dice `1d8`,
      two-handed `1d10`, tick **ver**, set `rng`/`max` or `reach`, `atk`/`dmg` bonus,
      AC base/bonus/max-dex, `wis+2` attribute bonus, `str=15` set, darkvision, speed,
      skill/expertise/save lists, `chg`/rechg, **mag**/**att** → **💾 Save definition**.
      Reopen the dropdown → **✎ Edit** reloads exactly those values back into the form (no loss).
- [ ] Grant it to a character (Grant, qty) → the item appears in their Inventory with the right chips (✨ magic, 🔗 attunable).
- [ ] Equip a **versatile** weapon → Attack section shows `⚔️ (one) … 1d8+…`; the Inventory row shows a grip button `🤲 one→two`; click it → the attack now reads `(two) … 1d10`, and a previously-equipped shield in the off hand is returned to the pack automatically.
- [ ] Attunement gate: a 🔗 magic weapon with an attack bonus shows `🔒` and the plain bonus until you click **Attune**; after attuning, `🔒` disappears and `+atk`/`+dmg` apply (Attack profile changes).
- [ ] Effective values on the sheet: wear **Goggles of the Night** → header shows `👁 60 ft`; a speed item shows `Speed 30 ft (→ 40 ft worn)`; a `+AC` ring shows in **AC** only while equipped, and vanishes on unequip (no leftover).
- [ ] Attribute item: a `str=15` glove raises the STR modifier everywhere (skills/saves/AC-derived) while worn; unequip and it drops back exactly (nothing persisted).
- [ ] Ranged tiers: shoot within `rng` → normal; beyond `rng` up to `max` → the roll prints `dis` (server-forced); beyond `max` → "beyond the weapon's maximum range".
- [ ] Extra damage dice: a `+1d4 fire` weapon's damage line shows the base dice `+[1d4] fire = … → N total`.
- [ ] Potion: a `2d4+2` **Draught** has a **Use** button; clicking heals once (re-sending the same action does not double-heal; charge/stack decrements once).
- [ ] Invalid equip gives a clear error (e.g. a two-handed grip then "shield does not fit the off hand").
- [ ] Legacy sheets without any equipped slot are unchanged (AC/attacks identical to before).
- [ ] Restart the container: equipment, grip, and derived attack profiles recompute identically from the DB.

## Sprint 28 — Currency, carrying & companions (Phase E, D99)
- [ ] Open a player character's sheet → a **🪙 Wallet** collapsible shows the greedy
      coin split (e.g. `3 gp`) and the rate legend `cp=1cp · sp=10cp · ep=50cp ·
      gp=100cp · pp=1000cp`. A `0` balance reads `empty`.
- [ ] As DM: in the Wallet's **DM · grant / deduct** row enter amount `5`, coin `gp`,
      press **Grant** → chronicle `🪙 The DM gives <name> 5 gp.` and the wallet now
      reads `5 gp`. Enter `10` `gp` → **Deduct** → an "Not enough coin" error and the
      balance is UNCHANGED (the whole withdrawal rolled back). Press Grant twice with
      the same button quickly → the wallet only gained 5 gp once (op_id replay).
- [ ] As the player: Wallet → **Transfer to a room member** → amount `2` `gp`, pick the
      member → **Send** → chronicle `🤝 <name> hands 2 gp to <other>`; open the other
      character's sheet → their wallet shows `2 gp`; this sheet now shows `3 gp`.
- [ ] Transfer more than owned → an "Not enough coin" error; neither purse changes.
- [ ] DM → 🎒 Inv → place/inspect a **container**: add coin with the chest's **Add coin**
      (amount `1` `pp`) → it shows `🪙 1000 cp`. As a player standing NEXT to it,
      **Take** `4` `gp` → chest drops to `600 cp`, your wallet `4 gp`; take again
      (double-click) → the scoop applies once. As a player, **Add coin** is refused
      ("DM only").
- [ ] **⚖️ Encumbrance** collapsible: a bar + `carried / capacity lb`. Grant a heavy
      500 lb item → the bar turns red and reads **OVERLOADED**, but moving the token
      is still allowed (warn only, no movement penalty yet). Equip/unequip does not
      double-count a weight.
- [ ] Wear a CSV item with `carry_bonus` (e.g. Bag of Loading) → the capacity number
      rises by the bonus; unequip → it drops back exactly.
- [ ] **🐾 Companions** collapsible: DM sees a **＋ Add for <name>** box → add a
      companion → a new token owned by that player appears; the row shows owner /
      `led by …` / `rides …`. As DM use the row's controller + mount selects and ✕
      (remove). **As a player you see NO controller/mount/remove controls** — control
      and ownership are DM-assigned; a player can never take a companion they don't own.
- [ ] Coin + balance + carried weight all still correct after reloading the page
      (state comes from the server, never recomputed in the client).

## INTEGRATION HARDENING (Sprint 29, D100)

These are the manual confirmations for the D100 fixes. Most are ALREADY covered by
automated tests (`tests/test_d100_integration.py`); do them here to see the UX is honest.

- [ ] **Autonomy lock.** As a PLAYER opening your own character sheet in the lobby
      editor: changing Level, the spell list, or spell-slot maxima and saving must NOT
      change those server-authorised values on reload (AC/HP/name/etc. ordinary fields
      DO save). Level up / class via the in-room **Build** still works normally.
- [ ] **Build stays open to the owner.** Player runs the Build (e.g. a level with a
      skill/subclass choice) → it applies; the DM can also still advance a character
      with the class control. Neither path is broken by the lock.
- [ ] **Rest refusal.** A player triggering a long rest (which is DM-only) now sees a
      clear "DM only" message instead of nothing happening; short-resting someone
      else's token reports "Not your character".
- [ ] **Cross-room item library (two rooms, DM in both).** Reusing one item-definition
      id in a second room is refused with a clear message ("used by another room");
      the first room's definition is unchanged. Item reads/grants in a room only ever
      list that room's own definitions.
- [ ] **Familiar cast.** A DM-created familiar carrying a registered ability (string id)
      can still be cast by the player the DM assigned as its controller.

> Note (not a browser step): the `node`-gated parity/diorama JS tests now execute in
> the canonical Docker test run (node 22 added to the test stage), so the shipped
> client JS — including `55_diorama.js`, which is only READ there — is verified in CI
> rather than skipped.

## ROOM PREPARATION & GUIDED BUILD (Sprint 30, D101)

These confirm the D101 UX in a real browser (the flow itself is automated in
`tests/test_d101_prep.py`, but the source-assert style cannot prove the CLICK
PATHS render). Import a rule pack first (DM tab → 📚 Rule packages, or the prep
screen's own upload) — with NO content the dropdowns are legitimately empty and
the amber "no imported content" hint is the CORRECT behaviour, not a failure.

### DM — preparation + rule pack status
- [ ] Create a room → you land on the PREPARATION screen (not the canvas). Right card
      shows the rule-pack badge counts and an import row. Upload the 8 shipped CSVs
      (mode = Apply) → the badge counts rise and the report shows per-file ok/errors.
- [ ] The DM roster lists every member with their character + built/unbuilt/at-table
      badges; reload the page, reopen the room from the lobby → you land on prep again.
- [ ] Click "Open the table" → the canvas + WS connect normally (Tactical and Diorama
      both work). The topbar ⚙ and "← Prep" bring you back to the prep screen.

### Player — guided create → build → seat → table (the core D101 path)
- [ ] In a second browser (player, not DM): join by code → prep screen. The species /
      class / background dropdowns list the DM's imported pack (e.g. Scout, Adept,
      Scholar, Urchin) — NOT free-text and NOT raw ids. Pick name + species + class +
      background → Create → the character appears selected.
- [ ] Target level 1 → 🧭 Plan → the wizard shows a "Choose N skills" checkbox list (the
      class's skill_options) and any subclass/level choices as selects. Pick 4 skills →
      "All guided choices collected ✔". Leave one skill short → "Still missing: skills".
- [ ] ⬆ Apply → success toast AND the sheet/checklist immediately reads
      "built to 1" with the new skills — WITHOUT pressing F5 (this is the confirmed
      D101 bug: previously it stayed "unbuilt" + old skills until a full reload).
- [ ] "Seat character at the table" → a token appears at the table; reload the page,
      reopen the room → still built to 1, still seated (server truth, not client state).
- [ ] 🎒 Grant starting equipment (pick the Urchin background, which lists
      "sword_plus1, coin purse") → "Granted: 1 × Sword +1" and an honest note that
      "coin purse" has no item definition in this pack (nothing invented). Press it
      AGAIN → "Already granted earlier — nothing duplicated" and the inventory still
      holds exactly one Sword +1.

### Player — level-up an existing character + refusals
- [ ] Select the built character, set target level higher (e.g. 3), Plan → Apply → the
      subclass/skill fields re-appear only for the NEW decisions; the level-1 skills are
      remembered (no re-asking). Sheet updates without reload.
- [ ] Open Expert mode, paste a garbage choices JSON, Apply → a red parse/server error is
      shown and NOTHING is written (reload → the sheet is unchanged, still unbuilt/old).
- [ ] A room member who is NOT the character's owner sees the guided flow but cannot
      build/seat another player's private character (server refuses; the DM can for a
      character assigned to the room).

### Room without content + old rooms
- [ ] Join a room whose DM imported NOTHING → prep shows the amber "no imported content"
      hint; the dropdowns are empty by design; creating a character still works (identity
      fields optional) and the build's Plan answers "no level-1 row in this room", not a
      crash.
- [ ] A room/character created BEFORE D101 opens in prep with its stored race/class/level
      intact; the table behaves exactly as in the Sprint 29 checklist.

## FLOORS / STOCKWERKE operable (Sprint 31, D102)

These confirm the D102 floor UX in a real browser (the mechanics are automated in
`tests/test_floors.py`, `tests/test_floor_maps.py`, `tests/test_d102_floors.py`).

### DM — the Floors panel (was: no way to manage floors at all)
- [ ] Open a table as DM → the side panel's **DM tab shows a "Floors" panel even
      with only the primary floor**. Type a name → ＋ Add → the floor appears in the
      list AND in the DM Tools "Viewing plane" select (which now also appeared).
- [ ] Click a floor in the panel → the canvas switches to that plane's (blank) map
      with "← viewing" on the row; nothing moved, no token teleported. The ✏️ on a
      row renames inline (✓/✗, Enter/Escape) — try the same name as an existing
      floor or a junk name → the server reason appears as a toast, nothing changed.
- [ ] 🗑 on an EMPTY floor deletes it; with a token standing on it the delete refuses
      with the honest reason ("Tokens still stand on this floor"); the primary row
      says "fixed" — it can neither be deleted nor renamed.
- [ ] Edit map while a named floor is being VIEWED (any brush) → only that plane
      changes: switch back to ⬛ primary → its terrain/fog is exactly what it was.

### DM — moving tokens between planes
- [ ] Select a token → the sheet's Floor row (DM) has the picker + Go: move the token
      to "crypt" → the token vanishes from the primary canvas; with the crypt VIEWED
      it appears at the same coordinates on the crypt map. Bring it back → gone from
      crypt, back on primary. (This channel is DM-only by decision.)
- [ ] Author a stair: map editor on primary place an object whose interact op targets
      the crypt → with the crypt viewed, tokens that stand on OTHER planes are not
      rendered and not clickable on this canvas.

### Player — plane truth without admin power
- [ ] With your character ON the crypt (DM moved you): reload → you are delivered
      on the crypt map directly (no manual switching); your sheet's Floor row is a
      plain label now — no picker, no Go (players take the stairs).
- [ ] Stand your token ON a stair object cell and interact → "🪜 … takes the
      Stair to crypt", your view follows you to the crypt automatically.
- [ ] While you are on the crypt, a fog brush stroke by the DM ON THE PRIMARY
      floor does not paint anything into your crypt view (and vice versa).
- [ ] A room created BEFORE D102 (everything on primary) is untouched: same map,
      same fog, no floors listed, table behaves as in the Sprint 29/30 checklists.

## D103 — Map editor truth + PNG display (manual browser acceptance)

Automated tests (711/1/0) pin the server/registry/route semantics. They CANNOT pin
what the human eye sees — walk this list in a real browser to ACCEPT or REJECT:

### Map editor — floor, void, erase
- [ ] ⬜ floor brush: drag a rectangle on blank ground → the cells VISIBLY change
      (two-tone tiled floor vs the dark background) and the change survives a reload.
- [ ] 🕳️ void brush: paint a 3-cell line across a corridor → dark hatched holes;
      a token walked/teleported INTO the line refuses ("no path"/"invalid teleport"),
      and a NEW token dropped on it lands on the nearest real floor cell beside it.
- [ ] Sight passes the pit: with fog on, stand your token beside the void line with
      an NPC/token directly behind it — you SEE it (and its cells explore), even
      though nobody can walk through.
- [ ] 🧹 erase on a trap/loot cell still clears THAT item and paints walkable
      floor (old meaning — erase must never dig holes); ⬜ over void restores floor
      and the token can cross again.
- [ ] Walls/doors/traps elsewhere are byte-untouched by any brush stroke; the void
      line on a NAMED floor (view a floor in the Floors panel, paint, save) never
      appears on ⬛ primary or another floor — and vice versa.
- [ ] Diorama view: the void cells render as flat floor (known cosmetic limit —
      NOT a bug to report); tactical view is the source of truth.

### Token artwork (PNG) — display path
- [ ] DM/player uploads a PNG for a token → the portrait renders as an IMAGE on the
      canvas immediately (not the grey initial-disc fallback) — first try, no reload.
- [ ] Hard-reload (Ctrl+Shift+R) → still the image; DevTools→Network: the
      `/assets/<id>` request is 200 image/png (this request 404'd before D103).
- [ ] A stranger account in ANOTHER room cannot load that url by pasting it (404,
      no hint); a private asset un-assigned from any token only serves its owner;
      the DM of a room the art rides in may load it.
- [ ] Assign the same art on a token on a NAMED floor → renders there too.
- [ ] A room/map/token untouched since before D103 behaves exactly as in the
      Sprint 29/30/31 checklists (no migration happened; old maps have no 🕳️ cells).
