# Effektgrammatik v1 & Zustandskatalog — D111 (Sprint 40)

Frage aus `docs/CSV_ONLY_READINESS.md`: *„Was kann die Engine aus einer CSV-Zelle
heraus wirklich auslösen?"* D111 beantwortet das für Effekte und Zustände:
Eine **versionierte, validierte Effektgrammatik** (`app/effectops.py`) und ein
**Zustandskatalog als CSV** (`conditions.csv`, `app/conditions.py`) — ausgeführt
ausschließlich von den bestehenden Engines (Schaden/Rettungen via `room/dice`
+ `room/health`, Bewegung via `room/movement`, Inventar/Ressourcen via
`inventory`/`gear`, Zustandsuhren via `room/combat`). **Keine zweite Engine.**

## 1. Die Zelle

Eine Effekt-Zelle (CSV-Feld `effects`) ist striktes JSON, kein Python, keine
Dateinamen, keine Kommentare (`NaN`/`Infinity`/Trailing-Komma → Import verwirft
die Zeile). Zwei Formen:

1. **Op-Kette** — Zauber/Talent/Gegenstand: `{"v": 1, "ops": [ … ]}`
   (die nackte Liste `[ … ]` wird akzeptiert und kanonisiert).
2. **Hook-Dict** — nur in `conditions.csv`:
   `{"on_start": [...], "on_round": [...], "on_expire": [...]}` — Ketten pro
   Lebenszyklus-Ereignis des Zustands.

Kanonisierung: sortierte Keys, kompakte Separatoren (`json.dumps(sort_keys=True,
separators=(",",":"))`). Gedruckte Zellbyte = Importbyte = Speicherbyte; der
Generator schreibt `conditions.csv` byte-idempotent.

**Grenzen (Parse-Bomben- und Missbrauchs-Schutz):** max. 8 Ops pro Liste,
Einbettungs­tiefe 1 (nur unter `save`/`check`), max. 40 JSON-Knoten und 4000
Zeichen pro Zelle, Zwangsbewegung 1–10 Zellen, `dc` 0–30 oder `"auto"`
(braucht Kontext-DC, sonst überspringt der Op), Ressourcen-Kosten genau 1 pro
Op, Unbekannte Ops/Felder → `EffectError` → **Zeile wird beim Import
verweigert** (laut im Bericht, nie still korrigiert).

## 2. Die Ops

| Op | Pflicht | optional | tut (wiederverwendete Engine) |
|---|---|---|---|
| `damage` | `expr` | `type`, `target` | Würfel → `room/health`-Schadenspfad inkl. Resistenz-Filter, Chronik |
| `heal` | `expr` | `target` | `health.change_hp` (Heilung) |
| `temp_hp` | `expr` | `target` | Temp-HP-Aktualisierung des Blatts (never stacks, max) |
| `condition` | `key` | `rounds` (0–999 oder `"duration"`), `until` (`start`/`end`), `target` | `cond_add`-Pfad; `"duration"` bzw. ein fehlendes `rounds` übernimmt den vom Zauber/Item in Runden umgerechneten `duration`-Wert — keine zweite Uhr |
| `condition_remove` | `key` | `target` | entfernt den Key über den bestehenden Pfad |
| `break_concentration` | — | `target` | setzt die Concentration-Fahne + Konzentrit-Sichtbarkeit (BRUCH-Rettungswurf selbst = S42, dokumentiert) |
| `save` | `dc`, `ability` | `success` / `failure` (je Op-Kette) | echter Rettungswurf über den Würfelkanal (sichtbar gefiltert wie everywhere else); Teilketten laufen nur bei passendem Ausgang |
| `check` | `dc`, `ability` | `success` / `failure` | Attributsprobe über denselben Würfelkanal |
| `forced_move` | `cells` (1–10), `dir` | `target`, `path` (`push`/`pull`) | `moveforced.apply_forced_move` — Hindernis-Trunkierung wie bei Push-Mastery |
| `resource` | `id` (Ressourcen-Pool der Klasse) | `amount` (nur 1), `mode` (`cost` Standard oder `restore`) | `cost`: Klassenressource **zahlen**; nur zahlbar → sonst keine Wirkung, kein Verbrauch. `restore`: eine vorhandene Ressource um 1 bis zu `max` auf demselben `characters.resources`-Ledger zurückgeben; unbekannte ID scheitert, volle Ressource bleibt unverändert |

`target`: `self` (der Träger/Wirkende) oder `target` (aktueller Kontext-Ziel —
bei `on_hit` z. B. das Getroffene). `expr` = einfacher Würfelausdruck
(`\d*d\d+(\s*[+-]\s*\d+)?`, nichts anderes — kein Mathe, keine Variablen).

### Dauer als Startwert von Bedingungen

`condition.rounds` darf entweder explizit sein oder den Marker `"duration"`
tragen (ein fehlendes `rounds` ist gleichbedeutend). Der Effekt-Core rechnet
ausschließlich für diesen Startwert die vorhandene Spalte `duration` des Zauber-
oder Item-Eintrags in Runden um:

- `1 round` → 1
- `1 minute` → 10
- `1 hour` → 60
- `1 day` → 999 (bestehende Obergrenze des Zustandszählers)
- `instant`, `permanent` oder ein nicht parsebarer Wert → 0 (bisheriges
  Dauer-/Sofort-Marker-Verhalten)

Die bestehende Initiativ-/Rundenlogik bleibt die einzige Uhr. Der Item-Effekt
speichert den Marker `"duration"` im prop, damit ein später geänderter
`props.duration` beim nächsten Auslösen tatsächlich wirkt.

## 3. Der Zustandskatalog (`conditions.csv`)

**Instanzen** (Token-Spalte, Uhren, `cond_add`) sind unangetastet — neu ist die
**Definitions­schicht**: Katalog-Keys + Homebrew-Keys bekommen Verhalten aus der
CSV, nicht mehr aus Code. Spalten: `id,name,glyph,color,group
(condition|marker),blocks_movement,speed_delta,my_attacks_dis,my_checks_dis,
my_saves_dis,attacks_against_me_adv,attacks_against_me_dis,auto_fail_saves,
effects,manual`.

* Die acht Hook-Flags liest die **bestehende** Engine an ihren bestehenden
  Stellen: Bewegungs­verbot + Tempo (`room/movement._speeds`,
  `_movement_block_reason`), Vor-/Nachteil (Würfelvorzeichen `dice.py`),
  Save-Auto-Fail (`abilities`-Fixed-Pfad + Würfelkanal), `auto_fail_saves`
  (z. B. stunned/unconscious: Liste „alle" = `ab`).
* `effects` (Hook-Dict): `on_start` beim Aufsetzen, `on_round` pro Runde
  Tick (D80-Turn-Lifecycle), `on_expire` beim natürlichen Ablauf.
* SRD-Verdrahtung: `BUILTIN_HOOKS` in `app/conditions.py` legt die 2024er
  SRD-Hooks **als Daten** über die alten Hardcodes (blinded/frightened/
  grappled/incapacitated/invisible/paralyzed/petrified/poisoned/restrained/
  slowed/stunned/unconscious). Eine `conditions.csv`-Zeile mit demselben `id`
  **überschreibt** den Builtin (Katalog-Layer), Import/Änderung invalidiert den
  per-Room-Cache.
* `/state` liefert `cond_catalog` (nur `n`ame/`g`lyph/`c`olor/`m`anual) für die
  Client-Legende; die UI (`10_core.js`) konsumiert sie.

**2024er Vereinfachungen (bewusst, dokumentiert):** Wo das SRD an eine
*Quelle* keyed (frightened „of that source"), gilt pauschaler Nachteil;
blinde Sight-Auto-Fails sind zu `my_checks_dis` gefaltet; prone bleibt
DM-adjudiziert; grappled/restrained blockieren jetzt komplett die Bewegung
(alles unter SRD „speed 0"; die bisherigen Move-Ban-Hardcodes sind ersetzt).

## 4. Trigger & Wächter

`TRIGGERS = use | equip | unequip | on_hit | on_damaged` (plus die drei
Zustands-Hooks). Auslösung inline an den bestehenden Handlers (`room/items.py`,
`room/inv.py`, `room/dice.py`×2, `room/health.py`, `room/combat.py`) — der
Events-Bus bleibt side-effect-frei. Maschinelle Wächter:

* **Einmal pro Runde/Op:** Claim pro `(token, trigger, Träger-Zeile, runde/op)`
  in `inv_ops` (`kind=effect_trigger`) — Retry/Doppelklick feuert nichts nach.
* **Keine Trigger-Kette:** Trigger-Feuer (Tiefe ≥ 1) lösen selbst keine
  Trigger aus; pro Auslösung max. 8 Träger (Budget).
* **Kosten nur bei Erlaubnis:** Ressourcen-Zahlung + Claim in **einem**
  `db.tx()`; abgelehnte Aktion (preflight in alle Zweige) kostet nichts,
  Nested-Zweige claims nicht erneut.
* **Idempotenz:** Replay einer gewirkten Op (= gleicher `op_id`) bewirkt
  erneut nichts (getestet: Zauber, Talent, Item-Benutzung, Equip).

## 5. Wo Grammatik überall akzeptiert wird

| Träger | Zelle/Spalte | Weg |
|---|---|---|
| `spells.csv` | `effects` | `abilities.execute`-Zweig (wirkt in derselben Shell wie Slots/Chronik, Slot-Kostentabelle unverändert) |
| `feats.csv` | `effects` | → castbare Ability `feat_<id>` (Entitlement im Build, `charbuild`) |
| `items.csv` (Def) | props `effects` + `trigger` | `use` (consume-Pfad `room/items.py`), `equip`/`unequip` (getragen, `room/inv.py`), `on_hit` (Waffe, `room/dice.py`), `on_damaged` (getragen, `room/health.py`) |
| `conditions.csv` | `effects` (Hook-Dict) | `room/combat.py` (`_fire_events` in `step_conditions`/Turn-Tick/Turn-Start) |

Defekte `effects`-Zellen auf Items werden beim Laden verworfen (wie alle
korrupten Props, `gear.clean_props`) — nie halbtot ausgeführt.

## 6. Was die Grammatik v1 bewusst NICHT kann

Re-Aktionen, Auren/Dauerfelder, Beschwörungen, Zauber-Komponenten
(komponenten-Spalte existiert nicht), frightened-Quellenbindung,
Konzentrations-**Rettungswurf** bei Schaden (der Op setzt nur die Fahne; SRD-
Save kommt in S42), zeitgesteuerte Ablauf-Engine jenseits der D80-Turn-Uhren,
Zonen-/Flächen-Effekt-Kopplung, Quellen-Referenzen in Hooks. Das sind
dokumentierte Grenzen, keine stillen Löcher — Restarbeit:
`docs/FEATURE_COMPLETE_GAPS.md` (S42/S43).
**Kontesto (Gegeneinanderprobe) ist weiterhin KEIN Grammatik-Op** — CSV kann in
v1 keine Probe-gegen-Probe ausdrücken. Die Auflösung lebt aber bereits als
dokumentierte Helfer-Schnittstelle (siehe 6a), die S42 nur noch als Op
einwickeln muss, statt eine zweite zu bauen.

## 6a. Kontesto-Helfer-Schnittstelle (`app/room/opposed.py`, D112) — der S42-Einwickelpunkt

D112 braucht für Grapple/Shove/Escape/Taschendiebstahl Gegeneinanderwürfe, aber
KEINE zweite Rules-Engine und noch keinen Grammatik-Op. `app/room/opposed.py`
deshalb als dünner Helfer über dem BESTEHENDEN Würfelkanal (`dice.do_roll`,
`dice._combine_adv`) und den `gear`-Bonusquellen; das Modul trägt keine eigenen
Regeln, die drei Formen sind nur Komposition:

| Baustein | Form | Hinweis |
|---|---|---|
| `participant(room_id, tok)` | — | ein Würfel-Teilnehmer aus Token (Charakter- oder NPC-Werte über `gear`) |
| `check_roll(p, key, kind, adv, prof)` / `save_roll(p, ability, adv)` / `bonus_roll(p, bonus, adv)` | Wurf | jeweils EIN Wurf über den normalen Kanal, Sichtbarkeit wie überall |
| `melee_attack_number(p)` | Angriffswert | 2024-Sonderkampf = max(unbewaffneter Angriffsbonus, Athletik-Wurf) |
| `better_save(p, ("str","dex"))` | Vorschlag | die höhere der Optionen (2024-Grapple-Rettungsdefault) |
| `opposed_wins(att, def, tie=)` | Wurf vs. Wurf | Gleichstand: `tie="defender"` (Default) / `"attacker"` / `"dm"` → wirft `Tie` |
| `beats_dc(total, dc)` | Wurf vs. DC | DC muss ERREICHT werden (d20-Gleichstand → Verteidiger) |

Drei kanonische Formen, alle über dieselben Bausteine: **Wurf-gegen-Wurf**
(`opposed_wins`), **Wurf → DC → Rettung** (`melee_attack_number`-Total als DC +
`save_roll`, Grapple), **Wurf gegen feste DC** (`beats_dc`, Escape/`notice_dc`).
Der Tie ist NIE ein stiller Münzwurf: Default `defender`, DM-Delegation über
`tie="dm"`/`Tie`. **S42-Auftrag:** genau diese Schnittstelle als Ops
(`opposed`, `check_vs_dc`, `check_then_save`) in die Grammatik einwickeln —
canonical JSON + strikter Parser wie die übrigen Ops, Ausführung wieder nur
durch diesen Helfer. Bis dahin ist der Helfer die einzige Kontesto-Autorität
und ausschließlich über Handlers ansprechbar (`grapple`/`shove`/`escape`/
`pickpocket*`), nicht über CSV.

## 7. Beispiele (aus dem Demo-Pack, `scripts/make_content_pack.py`)

* `thunder_lure` (spell): `damage 2d6 thunder` + `save` (STRK, DC 12) —
  bei Fehlschlag `forced_move` (push, 2 Zellen) auf das Ziel.
* `oil_vial` (potion, trigger `use`): `condition slicked` (3 Runden) aufs Ziel.
* `ring_ember` (ring, trigger `on_damaged`): `temp_hp 1d4+1` auf den Träger.
* `blade_quake` (weapon, trigger `on_hit`): `condition shaken` (1 Runde,
  `until end`) aufs **Ziel**.
* `martyr` (feat): `temp_hp 2d4+2` auf sich — wird als `feat_martyr` wirksam.
* `smouldering` (condition): `{"on_start":[{"op":"damage","expr":"1d4",
  "type":"fire","target":"self"}]}`.

## 8. Tests

`tests/test_d111_effects.py` (21 Tests): Validator/Kanon-Einheiten, SRD-Hook-
Verdrahtung, Katalog-Überschreibung + Cache-Invalidierung, `clean_props`-
Härtung, rekursionsfreier Condition-Ablauf, Zauber/Talent/Item/Equip/On-Hit/
On-Damaged-Feuer inkl. Replay-Idempotenz, Preflight-Kosten, Ping-Pong-Zustand
über zwei Token, Cross-Room-Isolation, `/state`-Katalog. Kanonlauf D111: **852 passed, 1 skipped, 0 failed**
(831er-Baseline + 21).

Der Kontesto-Helfer (6a) ist nicht Teil dieses Grammatik-Tests, sondern wird von
`tests/test_d112_contested.py` über seine Handlers abgedeckt (Grapple/Shove/
Escape/Taschendiebstahl inkl. Save-/Tie-Einheiten). Kanonlauf D112: **883
passed, 1 skipped, 0 failed** (852er-Basis + 31).

## 9. Grammatik v2 (D113, Sprint 42): `opposed`, `on_transfer`, Fluch-Träger

Die Grammatik ist versioniert und akzeptiert jetzt `v1` **und** `v2`
(`V=2`, gültiger Bereich `1..2`). Eine `{"v":3,...}` oder `v0` wird weiterhin
abgelehnt, genau wie unbekannte Ops/Felder (closed world). `canon()` bewahrt die
Version des Cells — ein v1-Cell kanonisiert byte-identisch weiter nach `{"v":1,...}`,
nur ein ausdrücklich `v2`-autorisierter Cell wird zu `{"v":2,...}`. v2 führt
**ausschließlich** den `opposed`-Op ein (und er ist unter v1 verboten):

* `opposed {ability, tie?, success, failure, target?}` — ein Attributswurf des
  Subjekts (Carrier/Caster) gegen denselben Wurf des Ziels, entschieden von
  `room.opposed` (`check_roll` + `opposed_wins`, `tie` = `defender`/`attacker`/
  `dm`). Es gibt keine zweite Opposed-Engine und keinen neuen Würfelkanal.

Neue Trigger und Träger:

* `on_transfer` ist ein regulärer Trigger geworden: Er feuert beim
  **Besitzerwechsel** (Transfer, Loot-Aufnahme, gelungener Taschendiebstahl),
  geclaimt an der Transfer-`op_id`, damit ein Replay/Wettlauf nicht doppelt
  feuert.
* **Flüche als Wirk-Träger:** `effectops.fire` prüft neben `props.effects` auch
  den `effects`-Cell eines Fluchs auf demselben Gegenstand — aber nur, wenn der
  Fluch `active` ist und sein `trigger` zum Event passt. Die D111-Budgets, der
  Tiefen-Rekursionsschutz und der `inv_ops`-Claim gelten unverändert. Curse-
  Herkunft wird mit `ctx["src"]="curse"` markiert; die Auslieferungsstelle
  sendet solche Fragmente ausschließlich an den DM (`net.dm_whisper`), damit ein
  verborgener Fluch sich nicht über einen Chattext verrät. Ein bloßes
  Lesen/Anzeigen/Synchronisieren von Inventar durchläuft `fire` nie.

Tests: `tests/test_d113_opposed.py` (6: v1+v2-Akzeptanz, v3-/`opposed`-unter-v1-
Ablehnung, Canon-Versionserhalt, Erfolgs-/Misserfolgszweig Ende-zu-Ende) und
`tests/test_d113_curses.py` (9). Kanonlauf D113 (Phases 2–4): **907 passed,
1 skipped, 0 failed**.

## 10. Fallen als dritter Wirk-Träger (D113 Phase 5)

Eine Falle (Map-Entität) kann denselben `effects`-Cell tragen wie ein magischer
Gegenstand oder ein Fluch. Tritt eine Kreatur auf das Feld (Trigger `step`),
führt `room/traps.py::hit_trap` den Cell über `effectops.run_ops` aus — mit dem
tretenden Token als `self` UND `target`, `depth=1` (ein Fallen-Effekt feuert
keine weiteren Trigger). Typische Zelle: ein `save`-Op mit `success`/`failure`
(darin `damage`/`condition`), ganz ohne `random.randint`.

Das Entdecken (`search`) und Entschärfen (`disarm`) einer Falle sind KEINE
Wirk-Ops, sondern eigene Checks über `room.opposed` (`check_roll` + `beats_dc`)
in der WS-Nachricht `trap` — Entdecken ein WIS-(Wahrnehmungs)-Check gegen
`search_dc`, Entschärfen ein DEX-Wurf gegen `disarm_dc`. Der Fehlschlag gegen
eine verborgene Falle antwortet byte-identisch wie die Suche auf einem leeren
Feld; der Endpunkt verrät nie, ob eine Falle da ist.

Schema: `effects`, `trigger`, `search_dc`, `disarm_dc`, `repeat` sind optional
und werden nur bei Bedarf gespeichert — eine legacy Falle (nur `dc`+`dmg`,
`room/traps.py` Alt-Pfad) bleibt byte-identisch und unverändert. `repeat=True`
lässt die Falle wieder scharf werden (`triggered` bleibt `false`).

Tests: `tests/test_d113_traps.py` (10). Kanonlauf inkl. Phase 5: **917 passed,
1 skipped, 0 failed**.
