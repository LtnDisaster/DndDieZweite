/* ---------- 65_help.js — the one help surface (D149) ----------
   Searchable, categorised, context-aware in-app help. Owns the #help-overlay:
   60_main.js (buttons) and 50_canvas.js (?, Esc) delegate through setHelp()/
   helpVisible() — the single switch. Entries reference only UI labels that
   exist in this build (tests/test_d149_help_system.py pins tab names, error
   strings and the delegation). */
(typeof window !== "undefined") && ((window.__BUILDS = window.__BUILDS || {})["65_help.js"] = window.__BUILD__ || "?");

const HELP_CATS = [
  ["start",  "🧭 Getting started"],
  ["chars",  "👤 Characters"],
  ["combat", "⚔ Combat"],
  ["magic",  "🧪 Magic & Items"],
  ["maps",   "🗺 Maps & Floors"],
  ["content","📦 Content"],
  ["dm",     "🎲 DM tools"],
  ["errors", "⚠ Errors & messages"]
];

const HELP = [
  /* ---- getting started ---- */
  { c:"start", t:"At the table in one minute", k:"join room party begin start",
    h:"Open a room and bring one of your characters to the table (pick them in the room screen). You always see chat and dice; everything else lives in the right sidebar tabs: <b>⚔ Game</b> (initiative, party), <b>👤 Chars</b> (your sheet), <b>🎒 Inv</b> (your stuff), <b>📜 Story</b> (quests, journal) and <b>🎲 DM</b> for the Dungeon Master." },
  { c:"start", t:"Keys & this manual", k:"keyboard shortcuts keys search filter help ?",
    h:"<kbd>?</kbd> opens this help · <kbd>Esc</kbd> closes it or cancels your current path/selection · <kbd>W</kbd><kbd>A</kbd><kbd>S</kbd><kbd>D</kbd> or arrow keys pan the camera · middle/right-drag pans too. The search box above filters this manual — type a word like <i>rest</i> or <i>trap</i>." },
  { c:"start", t:"Views: Tactical & Diorama", k:"view diorama tactical isometric grid switch",
    h:"<b>Tactical</b> is the top-down grid; <b>Diorama</b> is the same room and the same server pathfinding in an isometric table view. Your token, movement and path previews behave identically in both — use the view toggle at the top." },
  { c:"start", t:"Moving your token", k:"move movement walk path preview double-click stop",
    h:"Click your token, then click a destination (<i>Move: then click the destination cell</i>): you get a path preview first. Double-click the previewed goal (or press the confirm button) to walk. The walk stops at traps, closed doors, and if you drop to 0 HP. <i>Route changed — please plan it again</i> means the map moved under your preview — click the goal again." },
  { c:"start", t:"Doors & keys", k:"door open close lock locked key secret",
    h:"Click a door next to your token to open or close it. Locked doors need the key — or the DM. <i>It won't budge.</i> means the DM locked that door for players entirely. Secret passages show up on the DM's map only." },
  { c:"start", t:"Fog of war & revealed terrain", k:"fog explored darkness reveal light brush",
    h:"Explored terrain stays explored. The DM's 💡 brush toggles room-wide terrain reveal; hidden creatures still need line of sight either way. The DM can also <i>Hide explored fog</i> to re-shroud the room." },

  /* ---- characters ---- */
  { c:"chars", t:"Bring a character to the table", k:"character create join assign seat bring",
    h:"In the room screen choose one of your characters — the DM may also assign who seats where. <i>Bring a character to the table first</i> is this exact step still missing." },
  { c:"chars", t:"Your sheet (👤 Chars tab)", k:"sheet abilities check save hp hit points attack roll token select",
    h:"Click your token and the sheet opens: <b>Ability check</b> and each <i>… saving throw</i> roll straight to chat; <i>Attack roll vs target AC</i> fires when you have a target; <b>Current HP</b>/<b>Max HP</b> edit hit points, temporary HP has its own field, and conditions sit under the token with round clocks." },
  { c:"chars", t:"Creating & levelling (Prep)", k:"build create level up class species origin background feat plan apply prep",
    h:"The <b>Prep</b> screen is the guided build: species → class and level (\"Class — from this room's imported rule pack\") → origin/background → skills and feats, always <b>Plan</b> first, then <b>Apply</b>. Applying is chronological: everything you already applied stays, level-ups reuse the same path. Players advance only through the Build — a DM may set levels directly as an override." },
  { c:"chars", t:"Resting & healing", k:"rest short long hit dice heal recover spell slots",
    h:"Under your token: <b>Short rest</b> (spend hit dice from the count box to heal) and, on the DM's side, <b>🛌 Long rest</b>: restores HP, spell slots, hit dice and long-rest resources — and removes one exhaustion level." },
  { c:"chars", t:"Inspiration", k:"inspiration insp motivate Bardic",
    h:"The <b>Insp</b> button under your token shows whether you carry inspiration. Spend it on a roll you care about; at the table, an inspired character who would gain a fresh one passes theirs on instead — the DM can also grant inspiration to anyone." },

  /* ---- combat ---- */
  { c:"combat", t:"Initiative & turns", k:"initiative turn order surprise round active",
    h:"The DM rolls initiative from the <b>⚔ Game</b> tab and the order list shows who is up — the highlighted row is the <i>active turn (server-authoritative)</i>. Act on your turn: <i>It is not your turn</i> is the guard saying otherwise. Action/bonus/reaction can be ticked <i>used</i> on the active turn so the table can keep score." },
  { c:"combat", t:"Making an attack", k:"attack hit crit damage weapon roll ac",
    h:"Select the target token, then pick an attack on your sheet (<i>Attack roll vs target AC</i>): roll, modifiers and the result against AC all land in chat. Crits are honoured; the DM can <i>Apply critical damage to selected token</i> for the extra dice." },
  { c:"combat", t:"Cover", k:"cover half three quarters total shield behind wall",
    h:"Half, three-quarters and total cover apply to attack rolls and spell attacks alike. Behind <b>total cover</b> you cannot be targeted at all — and the refusal comes before any spell slot is spent, so your slots are safe." },
  { c:"combat", t:"Grapple, Push, Prone, Escape, Pick", k:"grapple shove prone push escape athletics acrobatics pickpocket sleight",
    h:"Special melee lives under your own token: <b>🤼 Grapple</b> (your Strength check sets a DC, target saves Strength or Dexterity), <b>⬇ Prone</b> and <b>➡ Push</b> shoves, <b>🤼 Escape</b> (Athletics or Acrobatics vs the grapple DC), and <b>🤝 Pick</b> — a concealed Sleight-of-Hand attempt whose result only the DM sees." },
  { c:"combat", t:"Conditions & exhaustion", k:"condition blinded poisoned charmed frightened exhaustion level stun",
    h:"Conditions ride under the token with a round countdown. If the effect says \"save ends\", you roll the save at the end of your turn and the condition drops on a success. Exhaustion stacks from −1 up to −6 on attacks, checks, saves and speed — level 6 is death, a long rest removes one level." },
  { c:"combat", t:"Dying & death saves", k:"unconscious 0 hp death save stabilize revive fail success",
    h:"At 0 HP you fall unconscious and roll death saves at the start of each of your turns: three successes stabilise you, three failures mean death. An ally adjacent to you can use the <b>Stabilize</b> button (a Medicine check DC 10 that uses their action; a natural 20 also heals you). A DM can clear the dying state outright for story revives." },

  /* ---- magic & items ---- */
  { c:"magic", t:"Inventory (🎒 Inv tab)", k:"inventory item equip use drop weight encumbrance grant",
    h:"Your items list equips and unequips (<b>Equip</b>), uses, splits and adjusts quantities, and shows weight. <b>🫱 give</b> on any of your items hands it to another character at the table — the move is one transaction, so nothing can half-transfer. Equipped gear matters: armour feeds your AC and gear can carry speed and darkvision bonuses. The DM can grant you items and remove them." },
  { c:"magic", t:"Consumables", k:"potion scroll consume charges wand recharge",
    h:"Potions and scrolls are consumed the moment you <b>Use</b> them — the healing or effect applies first, then the item leaves your pack. Wands and rechargables keep their shell: only the charge counter ticks down." },
  { c:"magic", t:"Attunement & identification", k:"attune attunement identify unknown identify magic item",
    h:"Magic items that need attunement show an <b>Attune</b> button. Attuning to an unidentified magic item is itself the identification ritual — you learn what you are binding to. Some items bite; curses are the DM's to reveal." },
  { c:"magic", t:"Containers, loot & chests", k:"chest container loot bag open take",
    h:"Some loot entries are real containers: click one you are allowed to open and the container view slides open. Use <b>Loot</b>/<b>Take</b> to move items and coins into your pack — the transfer is all-or-nothing, so nothing duplicates." },
  { c:"magic", t:"Coins & currency", k:"gold gp cp sp pp coin money purse split",
    h:"Coinage is tracked as stacked items in its own denominations. The same <b>Take</b>/<b>Loot</b> panel moves coins, and the DM can grant exact amounts. Splitting stacks works on any quantity via the −/+ controls." },
  { c:"magic", t:"Prepared spells & slots", k:"spell prepare prepared slot cantrip cast upcast",
    h:"Your spellbook comes from the build. Slot levels tick as you cast, and upcasting means simply choosing the higher slot. Prepared casters must <b>Prepare</b> before a prepared spell can be cast — cantrips are always free." },
  { c:"magic", t:"Casting & concentration", k:"concentration cast spell attack range area point",
    h:"Players cast from their sheet; the DM can also <i>Cast an area/point spell from the tactical map</i>. Only one concentration at a time — starting a new one ends the old." },

  /* ---- maps & floors ---- */
  { c:"maps", t:"Floors", k:"floor level story downstairs add delete switch",
    h:"A room can hold several floors — the DM adds them (<i>Add a floor to this room</i>) and tokens live on one at a time. <b>No floor</b> cells are impassable pits whose space sight still passes over. Deleting a floor is refused while tokens still stand on it." },
  { c:"maps", t:"Height & openings", k:"elevation height raise lower open flight vertical opening",
    h:"On a floor, cells can carry elevation: <i>Raise elevation +1 (step = 1 unit)</i> and <i>Lower elevation −1</i> sculpt steps; a token's own height and elevation matter for sight and reach. Vertical sight and movement between floors only exist through <b>openings</b> — without one, the floor keeps its secrets (fail-closed)." },
  { c:"maps", t:"Light & darkness", k:"light lamp torch darkvision glow radius",
    h:"Light is a map object: <i>Place a new lamp (bright 5)</i> puts a bright-5 light at the centre of the view; the bright radius is measured in cells and walls block the glow. In the DM's darkness, only sources and darkvision (from gear or species) reach." },
  { c:"maps", t:"The map editor & brushes", k:"edit map wall obstacle difficult terrain barrier editor save",
    h:"The DM's editor paints: walls, <b>Floor (walkable)</b>, <b>Low obstacle (passable, 2× cost)</b>, <b>Barrier (blocks movement, not sight)</b>, <b>Difficult terrain (2× walk)</b> and <b>No floor</b>; the door brush adds a door to a cell edge. <b>Save</b> publishes the change to everyone in the room." },
  { c:"maps", t:"Traps", k:"trap search disarm hidden spring DC",
    h:"DMs hide traps with the <b>Hidden trap</b> brush (disarm DC 0 means it cannot be disarmed). Players discover and disable with <b>🔍 Search</b> and <b>🔧 Disarm</b> for the cell their token stands on — tripping something hurts before it gets removed." },
  { c:"maps", t:"Objects, pins & measuring", k:"pin ruler measure distance ping world object",
    h:"<i>Place map pin</i>/<i>Remove map pin</i> drop non-mechanical markers, <i>Measure distance on the map</i> is a pure ruler that moves nobody, and pings (<i>Arm, then click the map to ping</i>) flash a spot for everyone." },

  /* ---- content ---- */
  { c:"content", t:"CSV rule packs & content", k:"csv import export pack rules content kinds options",
    h:"All game content is data: the DM's content panel lists the available kinds, imports CSVs in an <b>Import mode</b> (merge or replace) and hands you a clean template via <i>Export one kind</i>. The server validates every row — unknown fields and bad values fail closed, never silently half-imported." },
  { c:"content", t:"Creatures.csv → NPC", k:"creature bestiary monster projection import npc",
    h:"Creature rows preview as proper NPC blocks before anything is stored: check the projection, then push it into the bestiary. Anything the projection cannot express stays visible as a note instead of being silently faked." },
  { c:"content", t:"Token artwork", k:"png upload artwork portrait token image apply library",
    h:"On a token's sheet: <b>PNG…</b> uploads an image (max 1.5 MB, library shared in the room), <b>Apply</b> puts the picked artwork on the token. Existing library entries come from the dropdown." },
  { c:"content", t:"Map image & ambience", k:"map upload png audio music track ambience",
    h:"The DM can upload a background map image (PNG) from the room tools. The audio panel plays room ambience: add a self-hosted track (title + URL), <b>▶</b> starts or resumes (self-hosted resumes where it stopped), <b>⏸</b> pauses, <b>Stop</b> clears the source." },

  /* ---- dm tools ---- */
  { c:"dm", t:"The 🎲 DM tab", k:"dm dungeon master panel tools overview",
    h:"The DM tab is the workshop: encounters, bestiary, content imports and the tool switches. As DM you see through the fog; <i>Personal view (this browser only…)</i> flips you into a player's eyes for a moment — other players keep their own view." },
  { c:"dm", t:"NPCs & the bestiary", k:"npc monster statblock bestiary encounter spawn",
    h:"Create a token in 🎲 DM → add a name and the full statblock editor opens: Identity, Combat and Abilities up top; conditions, defences, spellcasting, attacks, actions and resources in collapsible sections. <b>＋ Bestiary</b> saves the block as a template; the Encounters panel spawns saved monsters." },
  { c:"dm", t:"Room-side DM levers", k:"forced move knock prone reveal grant inspiration lamp darkness fog",
    h:"Direct DM moves: <i>Browse this plane — nobody is moved</i> for safe scouting, forced-move a token, knock it prone, reveal revealed terrain room-wide (💡), toggle darkness and fog, place a lamp, grant inspiration, and run <b>🛌 Long rest</b> for the party." },
  { c:"dm", t:"Quests & the journal (📜 Story)", k:"quest objective journal chronicle story log",
    h:"Quests live in the <b>📜 Story</b> tab: add quests and objectives, tick objectives <i>done</i>, and mark the whole quest complete or failed. The Chronicle under the chat keeps the running journal of room events." },
  { c:"dm", t:"Narration, whispers & secrets", k:"whisper secret narration chat private message",
    h:"Chat has a target chooser — the whole table, your own party (<i>One of my characters</i>) or a specific listener. DM narration can carry styles, and a <i>secret event</i> stays invisible to players by design." },
  { c:"dm", t:"Advancing characters (DM override)", k:"level up advance class levels override raw setter",
    h:"Players level through the Build. <i>DM only — advance your character with the Build</i> is the wall between those paths: the raw class-level setter is the DM's documented override for assigned characters, not a second rulebook." },

  /* ---- errors ---- */
  { c:"errors", t:"Table messages, part 1", k:"error message not your turn reach lock budge adjacency",
    h:"<b>It is not your turn</b> — act when initiative says it is you.<br><b>Not your token</b> — that token belongs to someone else (your DM can still act through it).<br><b>You can't take actions right now</b> — something has you: stunned, incapacitated, similar.<br><b>DM only</b> — that lever is reserved for the DM; ask.<br><b>Walk up to it first</b> — interaction needs you to be next to it.<br><b>Target is out of reach</b> — check range or reach.<br><b>It won't budge.</b> — a locked or DM-owned door." },
  { c:"errors", t:"Table messages, part 2", k:"error message path route duplicate replay spell floor unknown",
    h:"<b>No path there</b> — the route is blocked; walls, pits and monsters get in the way.<br><b>Route changed — please plan it again</b> — the map moved during your preview; re-click the goal.<br><b>Nothing happens.</b> — the server found no legal effect there.<br><b>Who is that?</b> — the recipient is not at this table.<br><b>Spell not found on this character</b> — cast from your sheet; check prepared spells.<br><b>That transfer was already applied.</b> — a double-click guard; the first click already worked.<br><b>Bring a character to the table first</b> — pick a character in the room screen.<br><b>No such floor / Unknown character</b> — the world changed under this panel; refresh." }
];

const helpState = { cat: "start", q: "", wired: false };

function helpVisible(){
  const ov = $("help-overlay");
  return !!ov && !ov.classList.contains("hidden");
}

function helpCtxCat(){
  const b = document.querySelector("#side-tabs button.active");
  const map = { game:"combat", chars:"chars", inv:"magic", story:"dm", dm:"dm" };
  return (b && map[b.dataset.tab]) || "start";
}

function renderHelp(){
  const list = $("help-list"), catbar = $("help-cats");
  if (!list || !catbar) return;
  if (!helpState.wired){
    helpState.wired = true;
    const s = $("help-search");
    if (s) s.oninput = () => { helpState.q = s.value.toLowerCase(); renderHelp(); };
  }
  catbar.innerHTML = "";
  for (const [id, label] of HELP_CATS){
    const b = document.createElement("button");
    b.className = "ghost" + (id === helpState.cat ? " active" : "");
    b.textContent = label;
    b.onclick = () => { helpState.cat = id; renderHelp(); };
    catbar.appendChild(b);
  }
  const q = helpState.q.trim();
  list.innerHTML = "";
  let n = 0;
  for (const e of HELP){
    if (q){
      const hay = (e.t + " " + e.k + " " + e.h).toLowerCase();
      if (!hay.includes(q)) continue;
    } else if (e.c !== helpState.cat) continue;
    n++;
    const d = document.createElement("details");
    d.className = "help-entry";
    d.innerHTML = "<summary>" + esc(e.t) + "</summary><div class=\"help-body\">" + e.h + "</div>";
    list.appendChild(d);
  }
  if (!n){
    list.innerHTML = "<p class=\"meta\">Nothing matches “" + esc(q) +
      "”. Try <i>rest</i>, <i>trap</i>, <i>grapple</i> — or clear the search box.</p>";
  }
}

function setHelp(on, cat){
  const ov = $("help-overlay");
  if (!ov) return;
  if (typeof cat === "string" && cat) helpState.cat = cat;
  ov.classList.toggle("hidden", !on);
  if (on) renderHelp();
}
