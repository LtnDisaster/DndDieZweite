# Autonomer Arbeitslog — DnDTable

## Grundlinien

- Ziel: kontinuierliche, vertikal getestete Verbesserung ohne vorzeitigen Abschluss.
- Basis: D&D 5e Revision 2024 / SRD 5.2.1.
- Startpunkt dieses Laufs: `959 passed, 1 skipped, 0 failed`.
- Aktueller Kanon: `985 passed, 0 skipped, 0 failed` (D128, bestätigt im
  Recovery-Lauf 2026-10-17; davor D127 = 981).
- Grenzen: keine Git-/`.git`-Aktionen, keine Änderung an `55_diorama.js`, keine
  destruktive Migration, keine zweite Regel-/Engine, keine künstlichen Skips.
- Priorisierung: Kritikalität → Sicherheit → fehlende Engine-Verbindungen →
  Spielbarkeit → CSV-Generik → UI → Performance.

## Aktuelle Warteschlange

| ID | Aufgabe | Priorität | Status |
|---|---|---:|---|
| AP-001 | Skip des Reichweiten-/Reach-Härtungstests eliminieren | P0 | getestet |
| AP-002 | Condition-Wirkungen als vollständige Playability-Kette verifizieren | P1 | getestet |
| AP-003 | `duration` als Startwert für Bedingungen an die bestehende Uhr anschließen | P1 | getestet |
| AP-004 | `classes.spellcasting_ability` in Build-/Sheet-Anzeige einbinden | P2 | getestet |
| AP-005 | Geführte Expertise-Auswahl in der Build-UI validieren | P2 | getestet |
| AP-006 | Echte Chromium-/Playwright-Abnahme der neuen UI-/Build-Ketten | P2 | getestet |
| AP-007 | `feats.requires` als maschinenlesbare, fail-closed Prüfkette | P2 | getestet |
| AP-008 | `creatures.csv` → NPC-Block-Projektion in die bestehende Bestiarium | P2 | getestet |
| AP-009 | Monster-Dunkelsicht aus CSV/NPC-Block auf die Token-Sinnensäule | P2 | getestet |
| AP-010 | Skills aus NPC-Block im Monster-Sheet und vollständiger Spawn-Payload | P2 | getestet |
| AP-011 | Effektgrammatik: Ressourcen wiederherstellen, nicht nur verbrauchen | P2 | getestet |
| AP-012 | Spezies-Geschwindigkeit/Dunkelsicht/Größe auf bestehenden Pfaden | P2 | getestet |
| AP-013 | `companion` aus `creatures.csv` bis NPC-Block und DM-UI | P2 | getestet |
| AP-014 | `reach` aus NPC-Angriffen als hartes Reichweiten-Gate (D128) | P2 | getestet (Doku nachgereicht 2026-10-17) |

## AP-001 — Reichweiten-/Reach-Härtungstest entskippen

### Problem und Auswirkung

Der einzige dauerhafte Skip verschleierte einen fehlenden Live-Nachweis für
Waffenreichweite und Melee-Reach.

### Diagnose und Lösung

- `item_defs` war alphabetisch sortiert; positionelle ID-Auswahl griff nach dem
  Anlegen einer zweiten Definition auf die falsche Waffe zu.
- Der Test erwartete außerdem den alten Text `out of range`; die Engine nutzt
  jetzt das präzisere `maximum range`.
- Deterministische lookup-Funktion nach Name und exakte Prüfung der aktuellen
  Fehlermeldungen.

### Testnachweise

- Zehn Wiederholungen des Tests: grün.
- `tests/test_sprint24_hardening.py`: grün.
- Kanon: `960 passed, 0 skipped, 0 failed`.

## AP-002 — Condition-Wirkungen als Playability-Kette

### Ergebnis der Inventur

Alle registrierten Hooks besitzen Konsumenten:

- `blocks_movement`: Bewegung, Grapple-Auflösung.
- `speed_delta`: `movement._speeds`.
- `my_attacks_dis`: Angriffsauflösung.
- `my_checks_dis`: Würfelkanal, Opposed-Checks, Effekt-Saves/Checks.
- `my_saves_dis`: Würfelkanal, Opposed-Saves, Konzentration, Effekt-Saves.
- `attacks_against_me_adv` / `attacks_against_me_dis`: Angriffe gegen Token.
- `auto_fail_saves`: alle Save-Auflösungen, inklusive Konzentration und Grapple.

Die vorhandene Feature-Matrix war veraltet und behauptete weiterhin,
`blinded`/`invisible`/`poisoned` seien nicht verdrahtet. Die Matrix wurde auf
den tatsächlichen Stand gebracht. Es wurde bewusst keine neue Condition-Maschine
ergänzt.

### Verbleibende Grenze

Exhaustion-Level-Wirkungen bleiben offen; das ist kein fehlender Hook dieses
Systems, sondern eine separate, bekannte Modellierungslücke.

## AP-003 — `duration` als Startwert für Bedingungen

### Problem und Auswirkung

`spells.duration` und `items.duration` waren zwar im CSV-Import und auf dem
Bogen sichtbar, aber keine `condition`-Op konnte ihre Dauer mechanisch als
Anfangsrunden übernehmen.

### Lösung

- `effectops.duration_rounds()` rechnet SRD-Textduauern in Runden:
  `1 minute → 10`, `1 hour → 60`, `1 day → 999` (bestehende Obergrenze);
  `instant`/`permanent`/unbekannt → 0.
- Eine `condition`-Op kann `rounds: "duration"` schreiben; ein fehlendes
  `rounds` verhält sich identisch.
- Zauber-Dauer wird beim Mapping der Zauberdefinition aufgelöst.
- Item-Dauer bleibt als Marker im `props.effects` gespeichert und wird bei
  jedem `use`/Trigger aus dem aktuellen `props.duration` aufgelöst.
- Keine zweite Uhr: die bestehende Initiativ-/Rundenlogik tickt die Bedingung.

### Betroffene Engines

- `app/effectops.py` (Grammatik-Validierung)
- `app/gear.py` (Item-prop-Kanonisierung)
- `app/content.py` (Zauber-Mapping)
- `app/room/items.py` (Live-Item-Nutzung)
- Trigger-Auslösung in `effectops.fire()`

### Testnachweise

- Unit-Parser.
- Resolver für expliziten Marker und fehlende Runden.
- Canonisches Behalten des `"duration"`-Markers.
- Zauber-Mapping: `Concentration, up to 1 minute → 10`.
- Live-WS-Itemnutzung: Bedingung startet mit 10 Runden.
- Kanon: `963 passed, 0 skipped, 0 failed` in 12:43 Minuten.

### Verbleibende Grenze

Die Dauer endet mechanisch über den bestehenden Runden-/Initiativzähler. Eine
Wanduhr-/Noncombat-Expiry und ein expliziter Save zum vorzeitigen Ende wurden
bewusst nicht erfunden.

## AP-004 — `classes.spellcasting_ability`

### Problem und Auswirkung

Die Klasse konnte eine Casting-Ability deklarieren, aber `charbuild.plan()` und
`apply()` ignorierten das Feld. Im Wizard und auf dem Bogen war daher nicht
erkennbar, welche Ability die Klasse als Zauberbasis vorsieht.

### Lösung

- `classes.spellcasting_ability` wird in `_casting()` gelesen und für die
  erste nicht leere Klassenlevel-Zeile als `ability` zurückgegeben.
- `plan()["needs"]["spell"]` enthält `ability`.
- `apply()` meldet `casting_ability` zurück.
- Das Build-Ledger erhält `casting = {"first", "model", "ability"}`.
- Der Prep-Wizard zeigt „Casting ability: …“ an.
- Der Raum-Bogen zeigt die Casting-Ability und das Casting-Modell im
  Build-/Level-up-Abschnitt.
- Die pro-Zauber-`ability`-Ausführung bleibt unverändert. Es wurde bewusst kein
  zweites, klassenbasiertes Spellcasting-System gebaut.

### Testnachweise

- `plan()` liefert für die Testklasse `ability == "int"`.
- `apply()` liefert `casting_ability == "int"`.
- Das gespeicherte Build-Ledger enthält `casting.ability == "int"` und
  `casting.model == "known"`.
- Gezielte Suite:
  `tests/test_engine_gear_grants.py`,
  `tests/test_charbuild.py`,
  `tests/test_spells.py`,
  `tests/test_d101_prep.py` — grün.
- `node --check` über alle `app/static/js/*.js` — grün.
- Kanon: `964 passed, 0 skipped, 0 failed`.

### Verbleibende Grenze

Die Klassen-Ability ist eine ehrliche, generische Meta-/Display-Provenienz.
Sie überschreibt nicht den `ability`-Wert einer registrierten Zauber-Ability.
Eine vollständige Execution-Integration wäre nur nach einer eigenen
Architekturentscheidung sinnvoll; sie würde sonst mit dem bestehenden
pro-Zauber-Modell kollidieren.

## AP-005 — Geführte Expertise-Auswahl

### Problem und Auswirkung

Die Build-UI stellte `classes.expertise` bisher nur als „unsupported decision
type“ dar. Die Auswahl konnte zwar manuell als JSON gesendet werden, aber das
Wizard zeigte keine Kandidaten und erzwang die benötigte Anzahl nicht.

### Lösung

- `plan()` meldet Expertise-Level und Anzahl in `needs.levels`.
- `apply()` reichert pro Charakter `expertise_skills` an; Kandidaten sind
  bereits geübte Fertigkeiten und die Level-1-Klassenoptionen.
- `/api/build/.../plan` liefert diese Charakterkandidaten.
- `_check_choices()` verlangt die exakte Anzahl.
- `_recompute()` weist Duplikate und nicht geübte Fertigkeiten fail-closed ab
  und schreibt die Auswahl als `skill=2` auf die bestehende Skill-Achse.
- Das Wizard rendert Checkboxen pro Level und zählt die Auswahl im UI.
- Bestehende Builds ohne Expertise bleiben unverändert; nur Klassen mit
  Expertise-Zeile erfordern jetzt die bereits im CSV deklarierte Auswahl.

### Testnachweise

- Scout-Plan erfordert Level 1 und 6 Expertise.
- Level-1-Build setzt `stealth` von proficient auf expert.
- Auswahl einer nicht geübten Fertigkeit wird abgewiesen.
- Duplikate werden nicht als zwei verschiedene Choices gezählt.
- Alle betroffenen Build-/Integrations-Suiten wurden auf die jetzt geforderte
  Auswahl aktualisiert.
- Kanon: `964 passed, 0 skipped, 0 failed`.

### Verbleibende Grenze

Die UI ist automatisch getestet, aber noch nicht mit echtem Chromium
abgenommen. Diese Prüfung folgt als AP-006.

## AP-006 — Echte Chromium-Abnahme des Build-Wizards

### Problem und Auswirkung

Bisher waren UI-Integrationen vor allem durch Quelltext-Asserts, REST-Tests und
Node-JS-Syntaxchecks belegt. Damit war offen, ob die neuen Expertise-Checkboxen
im echten Chromium tatsächlich gezeichnet, ausgefüllt und an den Server
übergeben werden.

### Ausführung

- Playwright 1.64.0 und Chromium 156 wurden in einem temporären venv unter
  `/tmp/opencode/pw` installiert.
- Eine frische Testinstanz lief in der Kanon-Test-Image mit
  `VTT_DATA_DIR=/tmp/vtt-data` auf `http://127.0.0.1:8010`.
- `scripts/e2e_build_wizard.py` fährt:
  1. DM registrieren und Raum anlegen.
  2. komplettes Content-Pack als ZIP über den DM importieren.
  3. Spieler registrieren und über die UI dem Raum beitreten.
  4. Scout mit Kit-kin und Urchin im Wizard anlegen.
  5. Wizard planen und die vier Fertigkeits-Checkboxen wählen.
  6. die Expertise-Checkbox für Stealth wählen.
  7. Apply klicken und `built to 1` prüfen.
  8. über die authenticated `/api/characters`-Antwort prüfen, dass
     `stealth = 2` und `perception = 1` gespeichert sind.
- Screenshot: `/tmp/opencode/e2e-prep-wizard.png`.
- Ergebnis: **PASS** in echtem headless Chromium.

### Testnachweise

- `node --check app/static/js/80_prep.js`
- `tests/test_d101_prep.py`, `tests/test_charbuild.py`
- Kanon: `964 passed, 0 skipped, 0 failed`

### Verbleibende Grenze

Die Chromium-Prüfung deckt die Build-Wizard-Kette ab, nicht jede bestehende
UI-Seite. Der Runner ist bewusst ein optionales lokales Skript und ändert die
Kanon-Suite nicht. Playwright ist nicht in der Test-Image verankert; die
Installation bleibt lokal/zeitlich reproduzierbar über das Skript dokumentiert.

## AP-007 — Feature-Voraussetzungen als echte Prüfkette

### Problem und Auswirkung

`feats.csv` enthielt bereits die Spalte `requires`, aber kein Leser prüfte sie.
Damit war die Spalte irreführend: Der Wizard zeigte jedes Feature als wählbar
an, obwohl der Inhalt eine Voraussetzung erklärte. Eine nicht ausgelesene
Voraussetzung ist keine Regel — sie muss entweder machbar verdrahtet oder als
nicht unterstützt sichtbar abgewiesen werden.

### Lösung

- `_parse_feat_requires()` versteht derzeit:
  - Attributswert: `Dex 13`, `Int 13 minimum`, `Wis 13 or higher`
  - Fertigkeit: `Skill Proficiency — Stealth`, `Proficiency in Stealth`,
    `Stealth proficiency`
  - Vorheriges Feature: `feat Alert`
- Weitere Voraussetzungen werden fail-closed abgewiesen; sie werden nicht als
  leere Voraussetzung missverstanden.
- `_apply_feat()` prüft vor dem Grant gegen den bereits erreichten Zustand:
  Attributswerte, Skills und zuvor angewandte Features.
- Der Level-1-Fertigkeitswurf wird im Recompute chronologisch vor späteren
  Features angewandt. Ein Feature auf Level 8 sieht dadurch denselben
  Zustand wie auf dem Bogen, nicht einen künstlich skillslosen Zwischenzustand.
- `plan_for_character()` liefert für Level mit Feat-/ASI-Auswahl konkrete
  `feat_options` inklusive `available` und `missing`.
- Der Wizard deaktiviert unzulässige Optionen und zeigt die fehlende
  Voraussetzung, ohne eine zweite Regeln-Engine zu installieren.

### Demo-Inhalt

`feat_keen` verwendete bisher `Perception 5 ranks`. Das Projekt besitzt keine
Skill-Rang-Engine, in der „5" eine Bedeutung hätte. Die Demo-Voraussetzung wurde
in die vorhandene Skill-Achse übersetzt: `Skill Proficiency — Perception`.
Der Text bleibt ausdrücklich ein House-Rule-Demo-Feature; es wurde keine
2024-SRD-Aussage erfunden.

### Testnachweise

- Parser: unterstützte Formen und explizite Ablehnung von `Perception 5 ranks`.
- Plan: Wizard-Option markiert Keen Mind nach Perception-Übung als verfügbar.
- Apply: Verletzung der Voraussetzung schreibt nichts und nennt Perception.
- Bestehende Level-8- und Mehrschritt-Builds bleiben grün.
- AP-006-Chromium-Suite nach der UI-Änderung weiterhin PASS.
- Kanon: `967 passed, 0 skipped, 0 failed` (drei neue Tests).

### Verbleibende Grenze

Weapon-/Tool-/Spellcasting-/Rank-Voraussetzungen sind bewusst noch nicht
modelliert und werden abgewiesen. Die Unterstützung wächst pro echter
Mechanik, nicht durch Textparser-Spekulation.

## AP-008 — `creatures.csv` → NPC-Block → Bestiarium

### Problem und Auswirkung

`creatures.csv` wurde bereits validiert und importiert, aber die Engine hatte
keinen Konsumenten. Die CSV-Zeilen landeten also als Regelinhalt im Raum, ohne
einen NPC-Block, ein Bestiarium-Template oder einen Token erzeugen zu können.
Damit war Monster-Nachschub über CSV faktisch unwirksam.

### Lösung

- `npc.project_creature()` übersetzt eine Raum-Creature-Zeile in genau das
  `npc.clean_npc()`-Format, das das bestehende Bestiarium, Encounters und NPC-
  Tokens bereits verwenden.
- Übersetzt werden Attributswerte, HP, AC, Geh-/Fluggeschwindigkeit, Größe,
  Skills, Saves, simple Angriffszeilen der Form
  `Bite +4 to hit; 1d6+2 piercing` sowie Raum-Zauber-IDs.
- Nicht maschinenlesbare Freitexte bleiben als `unsupported` und in `notes`
  sichtbar. Ein Import-Button ist nur aktiv, wenn die Projektion vollständig
  mechanisch tragfähig ist.
- DM-Endpunkte:
  - `GET /api/content/{code}/creature-rows`
  - `GET /api/content/{code}/creature/{id}/projection`
  - `POST /api/content/{code}/creature/{id}/to-bestiary`
- Der DM-Bereich zeigt eine Review-Liste und legt ein projiziertes Monster im
  persönlichen Bestiarium an. Danach nutzt es den bestehenden Spawn-/Encounter-
  Weg; es gibt keine zweite Monster-Engine.

### Sicherheits-/Grenzentscheidung

Die Projektion ist ausschließlich DM-only und auf genau diesen Raum scoped.
Ein Duplikat im eigenen Bestiarium wird mit `409` abgewiesen, statt stumm
zweite Templates anzulegen. Die Raum-Zeile bleibt beim Import unverändert; die
Bestiarium-Kopie ist ein neues DM-Objekt und kann danach redigiert werden.

### Testnachweise

- Parser/Shape: Wolfkin-Attributswerte, Speed, Skills, Saves, Bite-Angriff.
- REST: Preview, Import, `GET /api/creatures`, Duplikat `409`.
- Autorisierung: Spieler/outsider abgewiesen, unbekannte Creature `404`.
- Projektliste markiert nur nicht unterstützte Inhalte als `ready: false`.
- Kanon: `971 passed, 0 skipped, 0 failed` (vier neue Tests).
- Real-Chromium:
  - `scripts/e2e_creature_projection.py` importiert das Content-Pack, öffnet
    die Review-Liste, klickt Wolfkin in das Bestiarium und prüft die gespeicherte
    `1d6+2`-Attacke: **PASS**.
  - `scripts/e2e_build_wizard.py` nach denselben UI-Änderungen weiterhin
    **PASS**.

## AP-009 — Monster-Dunkelsicht erreicht die Token-Sinnensäule

### Problem und Auswirkung

`creatures.csv` enthält `darkvision_ft`, und Token besitzen seit D89 eine
`darkvision`-Sinnensäule. Beide Enden existierten, aber der NPC-Block ließ die
Information auf dem Weg verloren gehen. Ein aus CSV importiertes Monster konnte
dadurch nicht sehen, obwohl seine Regelzeile Dunkelsicht deklarierte.

### Lösung

- `npc.clean_npc()` führt `darkvision_ft` als canonicalen Feet-Wert (0–999).
- `project_creature()` übernimmt den CSV-Wert.
- Der Spawn-Pfad leitet `darkvision_ft / 5` auf die bestehende Token-Spalte
  (Zellen) ab — exakt dieselbe Sichtmechanik, die D89 bereits nutzt.
- `add_token` übergibt zusätzlich `fly`/`swim`/`climb`, damit die Bewegung einer
  projizierten Kreatur nicht auf einen walk-only-Zustand reduziert wird.
- Der NPC-Editor zeigt ein `dark`-Feld in Fuß und schreibt/liest
  `darkvision_ft`. Bearbeiten ohne Änderung an Dunkelsicht behält den
  Token-Wert; eine Bearbeitung des Blocks aktualisiert die Spalte konsistent.
- Die bereits in D115 verdrahtete Ausrüstungs-Dunkelsicht bleibt die zweite
  Quelle; der Tokenwert ist das DM-/Monster-Autoring, nicht eine Ersatzlogik.

### Testnachweise

- Wolfkin/Hawk-kin-Projektion: 60 ft bleiben im Block erhalten.
- Reale `add_token`-Kette: NPC-Token erhält `darkvision = 12` Zellen.
- Reale `update_npc`-Kette:
  - unredigierter Wert bleibt erhalten;
  - Änderung auf 50 ft setzt den Token auf 10 Zellen.
- Kanon: `973 passed, 0 skipped, 0 failed` (zwei neue Tests gegenüber D122).
- Bestehende Chromium-Suiten für Build-Wizard und Monster-Review: weiterhin
  **PASS**.

## AP-010 — NPC-Skills erscheinen im Monster-Sheet und bleiben beim Spawn

### Problem und Auswirkung

D122 projizierte `skills` korrekt in den NPC-Block und `add_token` bewahrte sie
seit AP-009, aber das Monster-Sheet zeigte sie nicht. Zusätzlich baute der
Bestiarium-Spawn den Block aus einzelnen Top-Level-Feldern nach und ließ dabei
`skills` sowie andere Blockfelder aus. Die Daten waren also vorhanden, für den
DM aber nicht sichtbar.

### Lösung

- Das NPC-Sheet rendert eine read-only-Zeile `Skills`, die nur ausgefüllte
  Fertigkeiten zeigt und zwischen einfacher (`★`) und Expertise (`★★`)
  unterscheidet.
- Der Bestiarium-Spawn sendet nun `npc: blk` an den bestehenden `add_token`-
  Handler statt ein handgebautes Subset. Die Serverseite bleibt die einzige
  Stelle, die den NPC-Block normalisiert und daraus z. B. Dunkelsicht ableitet.
- Der bereits bestehende `SKILLS`-Kanon wird zur Anzeige verwendet; es entsteht
  keine zweite Skill-Engine.

### Testnachweise

- Unit: Wolfkin-Projektion behält Perception/Stealth.
- UI-/Architektur-Pins:
  - `30_room.js` rendert `#npc-skills` read-only;
  - `50_canvas.js` sendet `npc: blk` und leitet Dunkelsicht nicht mehr clientseitig
    doppelt ab.
- Kanon: `976 passed, 0 skipped, 0 failed` (ein neuer Test gegenüber D123).
- Reales Chromium:
  - Hawk-kin importieren, über **Spawn** auf die Karte setzen, Token prüfen:
    `darkvision_ft=60`, Token-`darkvision=12`, Perception im Block;
  - Token erneut anklicken und `#npc-skills` mit **Perception** sichtbar prüfen.
  - Build-Wizard-Chromium-Suite weiterhin **PASS**.

## AP-011 — Ressourcen können auch gewährt/wiederhergestellt werden

### Problem und Auswirkung

Die Effektgrammatik kannte `resource` ausschließlich als Kosten. Ein Zauber,
Item-Trigger oder Feature konnte vorhandene Ki-/Focus-/Class-Resource-Nutzungen
daher nicht über dieselbe Grammatik zurückgeben. Es fehlte nicht an einer UI,
sondern an einer datengetriebenen Ausdrucksseite derselben Ressourcen ledger.

### Lösung

- `resource` erhält ein optionales Feld `mode`:
  - `cost` — bisheriges Verhalten, Standard für alle alten CSV-Zellen;
  - `restore` — erhöht die vorhandene Ressource um genau eine Nutzung bis zu
    ihrem `max`-Wert.
- Preflight und die atomare claim+pay-Transaktion prüfen/bezahlen weiterhin nur
  `cost`-Ops. `restore` läuft nach der Kette auf derselben
  `characters.resources`-Spalte.
- Eine unbekannte Ressourcen-ID schlägt weiterhin fail-closed fehl; eine
  bereits volle Ressource bleibt unverändert. Es wird kein zweiter Ressourcen-
  Counter und keine automatische Ressourcenerzeugung gebaut.

### Testnachweise

- Validator:
  - altes `resource` normalisiert explizit auf `mode=cost`;
  - `mode=restore` wird akzeptiert;
  - `mode=grant` bleibt geschlossen-world abweisbar.
- Integration über echten `ability_cast`-Pfad:
  - Spell mit `mode=restore` hebt Ki von `0/2` auf `1/2`;
  - bestehender Preflight-Test bleibt grün (fehlende Kosten heilen nichts).
- Kanon: `977 passed, 0 skipped, 0 failed`.

## AP-012 — Speziesdaten erreichen Bewegung, Sicht und Footprint

### Problem und Auswirkung

Die Spezieszeile wurde zwar als Build-Provenance angezeigt, war aber mechanisch
noch ein Lesezeichen: Stouthearts 25 ft Bewegung, 60 ft Dunkelsicht und Kit-kins
Small-Größe blieben auf den jeweiligen bestehenden Pfaden wirkungslos.

### Lösung

- `gear.as_sheet()` parsed jetzt auch `characters.build`, sodass dieselbe
  kanonische Spielsheet-Repräsentation die Spezies-Projektion trägt.
- `movement._speeds()` übernimmt die Spezieswerte in die bestehende
  `gear.clean_speeds()`-Ableitung; Ausrüstungs-Boni bleiben wie bisher eine
  Ebene darüber.
- `visibility._token_darkvision_cells()` nimmt das Maximum aus Token-DM-Wert,
  Ausrüstungs-Dunkelsicht und Spezies-Dunkelsicht.
- Beim Setzen eines Charakters setzt die Raumverbindung die bestehende
  Token-Größe aus der Speziesgröße; ohne Speziesgröße bleibt der vorhandene
  Tokenwert erhalten. Es gibt weiterhin nur `tokens.size` und `footprint` als
  Footprint-Engine.

### Testnachweise

- Stoutheart über echten Assign-/Token-Pfad:
  - `movement._speeds()` liefert walk 25 ft statt 30 ft;
  - Sichtableitung liefert 12 Zellen für 60 ft.
- Kit-kin über echten Assign-Pfad: Token-Größe `small`.
- Movement-/Visibility-/Gear-/Charbuild-Regressionen: grün.
- Kanon: `979 passed, 0 skipped, 0 failed`.

## AP-013 — `companion` erreicht NPC-Block, Bestiarium und DM-UI

### Problem und Auswirkung

Die Spalte `companion` in `creatures.csv` war dokumentiert, ging aber auf dem
Weg CSV → NPC-Block → Bestiarium/Token verloren. Ein Geister-Buch hatte damit
keine maschinenlesbare Begleiter-Markierung und konnte auch nicht nachträglich
im Editor gesetzt oder gespeichert werden.

### Lösung

- `npc.project_creature()` interpretiert `1`/`true`/`yes` und schreibt ein
  boolsches `companion` in den bestehenden NPC-Block.
- `npc.clean_npc()` normalisiert und begrenzt das Feld, ohne eine zweite
  Begleiter-Engine oder Ownership-Mechanik einzuführen.
- `add_token` und `update_npc` übernehmen `companion` sowie die übrigen
  relevanten NPC-Felder vollständig in den gespeicherten Block.
- `CreatureIn`, `_creature_block()` und die Content-API liefern das Feld bis
  zur DM-Vorschau durch.
- Creature-Review und NPC-Sheet zeigen die Markierung; DM-Editor und
  Bestiarium-Speicherung senden sie zurück.

### Testnachweise

- `tests/test_d127_companion_flag.py`:
  - CSV-Projektion, REST-Bestiary-Roundtrip, Review-Marker und UI-Pins;
  - ein NPC mit `companion=True` speichert/überschreibt/zeigt den Wert.
- Die kanonischen NPC-Angriffs- und Zauberpfade deckten einen Regressionseinfall
  während der Paketerstellung ab: `add_token` hatte zwischenzeitlich `attacks`
  und `spell_slots` nicht mehr vollständig übernommen. Beide Felder sind wieder
  Teil des kanonischen Spawn-Blocks; die bestehenden echten WS-Angriffstests
  bleiben grün.
- Kanon: `981 passed, 0 skipped, 0 failed`.

## AP-014 — NPC-Angriffsreichweite als hartes Gate auf der einen Footprint-Distanz

### Problem und Auswirkung

Der NPC-Angriff prüfte Distanz nur als Nachbarschafts-Advisory. Deklarierte
Reichweiten („reach 10 ft“ in `creatures.csv`-Angriffszeilen) hatten keinen
Konsumenten; die Zahl war irreführender Inhalt statt Regel.

### Lösung

- `project_creature()` liest „reach N ft“; `clean_npc()` normalisiert das Feld
  (Clamp 0–999, Default 5 ft).
- `handle_npc_attack` gateert das Ziel über dieselbe
  `dice._vertical_range_distance`-Distanz (Footprint-Zellen × 5 ft,
  ebenenrichtig) wie Spielerangriff und Interaktion; Fail-closed mit
  „Target is out of reach“.
- Der NPC-Editor bearbeitet `reach` je Angriff (`na-reach`, 0–999).
- Keine zweite Reichweiten-Mechanik; DECISIONS D128.

### Testnachweise

- `tests/test_d128_npc_reach.py` (4 echte WS-/Unit-/UI-Pin-Tests).
- Kanon: `985 passed, 0 skipped, 0 failed`.

### Hinweis zur Doku-Lücke

Dieses Paket wurde in der abgebrochenen autonomen Sitzung (2026-10-16/17)
implementiert und gepusht, aber der Doku-Abschnitt (D128/AP-014) und der
Kanon-Eintrag fehlten. Die Recovery-Sitzung 2026-10-17 hat Code und Tests
unverändert übernommen, die Baseline als grün verifiziert und die Doku
nachgereicht. Details: `docs/RECOVERY_2026-10-17.md`.

## Recovery-Lauf 2026-10-17 (Marathon-Bergung)

- Frischer Clone, Branch `feature/csv-character-system`; keine Git-Aktionen,
  `55_diorama.js` unangetastet.
- Baseline `COMPOSE_PROFILES=test docker compose run --build --rm test`:
  **985 passed, 0 skipped, 0 failed** in 103 s — exakt D127-Kanon (981) + die
  4 D128-Tests. Keine fehlgeschlagene oder halbfertige Integration im
  Testkorpus auffindbar.
- `node --check` über alle `app/static/js/*.js` grün; alle Python-Dateien
  AST-frei von Syntaxfehlern.
- Runtime-Image startet; `/api/health` `{"ok":true}`, Build-Hash-Check über
  alle JS-Dateien konsistent. Hinweis Betrieb: Dieser Host läuft mit
  Rootless-/Fuse-Docker — der ./data-Bind des Compose-App-Dienstes braucht auf
  solchen Hosts uid-seitige Anpassung (Check hier mit einer Wegwerf-Instanz
  unter `--user 0:0` und frischem Datenverzeichnis unter `$HOME` geführt;
  keine Projektdaten berührt).
- Echte Chromium-E2E (Playwright 1.64, Chromium 156, headless, in
  Wegwerf-Containern; Repo nur lesend gemountet):
  `scripts/e2e_build_wizard.py` **PASS**, `scripts/e2e_creature_projection.py`
  **PASS** (inkl. NPC-Skill-Anzeige im Monster-Sheet).
- Repariert werden musste am Code nichts; repariert wurde die Doku:
  DECISIONS D128 nachgetragen, `CSV_ONLY_READINESS.md`-Zeile „reach advisory“
  auf das durchgesetzte Gate korrigiert, FEATURE_MATRIX-Kanon auf 985/D128.
