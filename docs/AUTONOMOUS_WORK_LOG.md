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

## AP-015 / D129 — Exhaustion-Stufen wirken (2026-10-17, Marathon 2.0)

- Umsetzung: `gear.exhaustion_roll_mod`/`exhaustion_speed_penalty_ft` als
  einzige Quelle; Konsumenten in `dice.py` (Angriff/Schaden/Check/Save/
  Sprüche + Long-Rest-UPDATE −1), `opposed.py`
  (check/save/bonus/melee_attack_number), `combat.token_dex_mod`
  (Initiative), `movement._speeds` (nur PC, nur walk), `status.py`
  (Stufe 6 → bestehender Death-State, hp=0).
- Tests: `tests/test_d129_exhaustion.py` (9 Tests, abgeleitete
  Erwartungswerte statt Magischer Zahlen). Kanon: **994 passed,
  0 skipped**, 102 s.
- Befunde (nur Tests/Doku, kein Produktiv-Bug): `sys_msg` ist rein
  DB-seitig (live geht nur `snapshot`); verschachtelte
  WebSocketTestClient-Sessions schlucken Sends der äußeren Session —
  Tests sessions sequentiell verbinden; `tokens.room_id` ist die
  numerische `rooms.id` (code ist nur außen); Rolls brauchen
  `"visibility": "public"`, um aufs eigene Socket zurückzukehren;
  Item-def-props-Schlüssel ist `damage_dice` (nicht `damage`).
- Doku: DECISIONS D129, FEATURE_MATRIX Zeile 10/74,
  FEATURE_COMPLETE_GAPS, RULES_AUDIT F3/F4/R-P2, dieses Log.
- Nächster Schritt: AP-016 (save-ends-Konsumenten).

## AP-016 / D130 — Save Ends (2026-10-17, Marathon 2.0)

- Umsetzung: additiv-Feld `sa` auf Condition-Instanzen
  (`conditions._clean_sa`, Whitelist `gear.ABILITIES`);
  `combat._save_ends` an beiden Turn-Übergabepunkten
  (`_end_turn_common`, `handle_init_next`) VOR `advance_turn`;
  Würfel via `opposed.participant`/`save_roll`/`beats_dc` (PC+NPC gleich);
  Ankündigung via `concentration._announce_roll` (PC öffentlich,
  NPC DM-only); Erfolg entfernt genau den Eintrag (Identität, nicht Key —
  D109-Coexistenz bleibt heil). `cond_add` transportiert jetzt `dc`+`sa`.
- Tests: `tests/test_d130_saveends.py` (6 Tests; dc 1/dex vs dc 30/wis als
  nie-falsch/Determinismus-Anker). Kanon: **1000 passed, 0 skipped**, 106 s.
- Befunde: `messages`-Sys-Nachrichten können vom Runden-Wrap
  („— Round N —") den letzten Eintrag verdrängen — Tests suchen per LIKE,
  nicht „letzte Nachricht"; `_clean_dc` band 1–30 (DC 0 gibt es nicht —
  dc 1 ist der Immer-Erfolg-Anker).
- Doku: DECISIONS D130, FEATURE_COMPLETE_GAPS (D117-Zeile ✅),
  FEATURE_MATRIX-Kanon, dieses Log.
- Nächster Schritt: AP-017 (casting_time-Gate am Slot-Verbrauch).

## AP-017 / D131 — casting_time verbraucht den benannten Turn-Slot (2026-10-17, Marathon 2.0)

- Umsetzung: `gear.casting_slot` (bonus/reaction schlagen action;
  minute/hour/ritual → None), Gate in `handle_cast` (Reihenfolge:
  Spell-Lookup → `inventory.claimed` stumm → Token-Pflicht → turn →
  Slot frei → Claim/Spell-Slot → `spend_slot`), `clean_spells` +
  `charbuild`-Projektion tragen `casting_time` durch.
- Tests: `tests/test_d131_casting_time.py` (7 Tests). Kanon:
  **1007 passed, 0 skipped**, 126 s. Kein Bestands-Cast wirkt im Kampf
  ohne Token — null Regression.
- Befunde: Sheet-Projection (`gear.clean_spells`) und Katalog→Bogen
  (`charbuild`) warfen unbekannte Spell-Keys still weg — Datenfeld-Features
  brauchen beide Durchgangsstellen, sonst stirbt die CSV-Linie vor dem
  Konsumenten; Replay nach verbrauchsAction wurde als "No action left"
  sichtbar → stumme nicht-destruktive `inv_ops`-Probe (claimed) vor dem
  Action-Gate.
- Doku: DECISIONS D131, CSV_ONLY_READINESS (casting_time-Zeile),
  FEATURE_MATRIX-Kanon, dieses Log.
- Nächster Schritt: AP-018 (value_gp/cr-Konsumenten).

## AP-018 / D132 — value_gp und cr bekommen Konsumenten (2026-10-17, Marathon 2.0)

- Umsetzung: additive Migration `item_defs.value`; clean_def/
  `_project_item`/entry_from_def/clean_items tragen value (0..999999);
  `npc._clean_cr` (SRD-Band, sonst ''), project_creature + add_token-
  Whitelist → cr im NPC-Block/Sheet-Payload.
- Tests: `tests/test_d132_value_cr.py` (6 Tests). Kanon: **1013 passed,
  0 skipped**, 112 s.
- Befunde: `item_defs.id` ist GLOBAL UNIQUE (D100) — Tests mit
  Pack-Import-Kollisionen brauchen frische ids; SQL-Platzhalterzahl wird bei
  Spaltenanzahl-Drift durch den Projektions-Warnkanal gefangen
  ("stored but not projected") — fail-loud-Design bewährt sich.
- Doku: DECISIONS D132, MATRIX-Kanon, CSV_ONLY_READINESS (CR erledigt),
  FEATURE_COMPLETE_GAPS (value_gp-Zeile), dieses Log.
- Nächster Schritt: AP-019 (Loot-Objekt als echter D92-Container).

## AP-019 / D133 — Loot-Objekte mit container-Flag = echte D92-Container (2026-10-17, Marathon 2.0)

- Umsetzung: mapmodel._entity lässt container/hinted/dm_only durch (loot-
  Whitelist-Zweig); handle_map_edit bewahrt hinted wie taken_by;
  handle_inv_container löst "loot:<id>" auf (Anker-Zelle/dm_only/Reichweite
  geteilt mit Welttruhen); take_loot verweigert Notiz-Pickup bei Flag +
  Einmal-Hinweis; Client: Editor-Checkbox, lootAt + openLootObject auf dem
  bestehenden inv_container-Kanal.
- Tests: tests/test_d133_loot_container.py (5 Tests). Kanon: **1018 passed,
  0 skipped**, 123 s.
- Befunde: mapmodel.sanitize ist Whitelist — neue Entitätsfelder brauchen
  dort ihre Passage (sonst stille Null-Auflösung, Test hing in recv_until);
  Primary-Ebene liegt in room_state.map_json, floor_maps nur für Zusatz-
  ebenen (Test-Helfer entsprechend gefixt); member-Char-Ansicht hat wallet als int-cp.
- Doku: DECISIONS D133, MATRIX-Kanon, FEATURE_COMPLETE_GAPS (Loot-Zeile ✅),
  dieses Log.
- Nächster Schritt: AP-020 (incapacitated-Feinschliff + Matrix-Nachaudit).

## AP-020 / D134 — 2024-Incapacitated: Hook `no_actions` auf allen Aktionspfaden (2026-10-17, Marathon 2.0)

- Umsetzung: HOOKS + BUILTIN_HOOKS um `no_actions`; Eltern-Condition auf
  {no_actions} reduziert (Bewegung frei, keine Auto-Fails), vier
  Familienmitglieder +no_actions; Konsumenten: _item_attack, cast-Gate,
  grapple._take_action (Attack/Escape-Choke), combat.handle_dash — alle vor
  Konsumtion; Grapple-Ende prüft jetzt no_actions des Greifers.
- Tests: tests/test_d134_incapacitated.py (4 Tests). Kanon: **1022 passed,
  0 skipped**, 115 s. Bestands-Hooks (D110/D113) unverändert.
- Doku: DECISIONS D134, MATRIX (Zeile 74 + Kanon), RULES_AUDIT F5 ✓/R-P2
  bereinigt, FEATURE_COMPLETE_GAPS (Familien-Zeile ✅), dieses Log.
- AP-015..020 sind DAMIT ABARBEITET. Weiter mit der dynamischen Restliste
  (nächster Kandidat laut PLAN: F6 Inspiration-Punkte-Semantik prüfen).

## AP-021 / D135 — Heroic Inspiration: Verbrauchs- und Weitergabe-Regel (2026-10-17, Marathon 2.0)

- Umsetzung: dice.py `_spend_insp` (adv:"insp" → Marker weg, Advantage-Falte;
  Blind/NPC-Pfade lehnen ab, NPC innen nach _npc_target — der frühe
  token_id-Guard war zu breit und hätte PC-Angriffe mit Token erwischt);
  status.py `gain`: voll → pass_to_char oder "nothing gained" (Sitz = Token
  im Raum, characters hat KEINEN room_id-Spalten — Sitz führt tokens).
- Fallen: messages-Spalte heißt body (nicht text); reg() liefert kein user-id
  → state_of()["me"]; _own_char braucht token_id und schweigt sonst.
- Tests: tests/test_d135_inspiration.py (7). Kanon: **1029 passed, 0 skipped**, 101 s.
- Doku: DECISIONS D135, MATRIX-Kanon, RULES_AUDIT F6 ✓ (R-P2-F6-Streicher),
  FEATURE_COMPLETE_GAPS, dieses Log.

## AP-022 / D136 — Help-to-Stabilize als DC-10-Medicine-Check (2026-10-17, Marathon 2.0)

- Umsetzung: death.py `handle_stabilize` (+dispatch `stabilize`): Patient-
  guards, Selbst-Guard (MUSS vor Patient-Guard, sonst falsche Meldung),
  _adjacent, Turn/Action via get_init+set_init, no_actions, skill_bonus
  medicine, nat20 -> 1 HP, Fehler ohne Zähler-Bewegung.
- Fallen: get_init liefert frischen DB-Read (Mutation -> set_init!);
  room_state-Spalte heißt initiative; "stable"-Substring im JSON-Key immer
  True -> JSON parsen statt Substring.
- Tests: tests/test_d136_stabilize.py (4; random-robust: Würfeltext ⇔
  stable-Zustand). Kanon: **1033 passed, 0 skipped**, 102 s.
- Doku: DECISIONS D136, MATRIX, RULES_AUDIT F8 ✓ + R-P2-Liste, GAPS, Log.

## AP-023 / D137 — Deckung auf Zauber-Angriffswürfen (2026-10-17, Marathon 2.0)

- Befund: A5 war halb erledigt — 3/4-Cover (+5) existierte in Backend
  (COVER_BONUS) UND Client-Select; die echte Lücke: Spell-Attack-Wege
  (handle_roll-Manual, handle_cast, _npc_roll, _npc_cast) ignorierten msg
  cover.
- Umsetzung: _spell_cover/_total_cover_note Helfer, _spell_attack_text
  cover-Param (Text + Abzug), Total-Ablehnung VOR Slot/Action in beiden
  cast-Handlern.
- Tests: tests/test_d137_spell_cover.py (4; Slot-Nichtverbrauch bei total).
  Kanon: **1037 passed, 0 skipped**, 115 s. A5 vollständig abgearbeitet.
- Doku: DECISIONS D137, MATRIX, RULES_AUDIT A5 ✓ + R-P2-Streicher, GAPS, Log.

## AP-024/025 / D138 — Prepare-Gate datengetrieben; F2/E2 verifiziert (2026-10-17, Marathon 2.0)

- AP-024 (Pflege): F2 verifiziert (hit_dice_max = Level-Pool, kein
  Halb-Level-Cap — SRD-seitig fertig); E2 erledigt durch D109 Nick-Mastery
  (2024 existiert kein Nebenhand-Bonusangriff mehr). Audit-Zeilen +
  R-P1/R-P2-Listen bereinigt.
- AP-025: gear.clean_spells + charbuild: prep/prepared-Felder; handle_cast:
  Gate (Liste gated bei einem prep-Eintrag; level>0 braucht prepared;
  Kantrip ausgenommen; VOR Slotverbrauch). Kein Klassencode.
- Fallen: total-cover-Zeile existiert doppelt (PC+NPC) — PC-Anker mit
  Vor-Kontext patchen.
- Tests: tests/test_d138_prepared.py (3). Kanon: **1040 passed, 0 skipped**, 109 s.
- Doku: DECISIONS D138, MATRIX, RULES_AUDIT C3 ✓, GAPS, Log.

## AP-026 / D139 — Species-Origin-Feat + „no feat twice" (2026-10-17, Marathon 2.0)

- B6 verifiziert: _parse_feat_requires ist maschinell fail-closed, Pack
  enthält kein „ranks" — Audit-Zeile ✓.
- B5: species-Schema-Feld origin_feat; _species_projection gibt es weiter;
  _feat_choice_options: taken-Set (Ledger + Species) -> „already chosen";
  Level-Up-Aufrufstelle injiziert Species-Feat in feats_applied (prereq-Ketten).
- Falle (haftend): SCHEMAS speist scripts/make_content_pack.py — Schema-Zeile
  = CSV-Regeneration; D109-Idempotenztest zeigt das; mit-geschriebene
  species.csv ist jetzt der neue Stand. mutate in Tests muss CSV-Modul
  nutzen (Quoting!), nicht String-Replace.
- Tests: tests/test_d139_species_origin.py (3). Kanon: **1043 passed, 0 skipped**, 115 s.
- Doku: DECISIONS D139, MATRIX, RULES_AUDIT B5/B6 ✓ + R-P1-B5-Streicher, Log.

## AP-027 / D140 — SRD-Aufschlag für Swim/Climb ohne Speed (2026-10-17, Marathon 2.0)

- Umsetzung: movement._mode_or_error verlangt Speed nur noch für fly;
  movecost.route_cost: strained = swim/climb -> unit + (2 if difficult
  else 1) — wörtliche SRD-Addition; Client-Picker: swim/climb immer, fly
  nur mit Speed.
- Fallen: movecost-Tests brauchen grid()-Zellenlisten (nicht dict);
  1. Diagonale hat Basis 1 (Erwartung 2+3 war falsch -> 2+2, zweiter Diag
  ergänzt).
- Tests: tests/test_d140_swim_climb.py (2). Kanon: **1045 passed, 0 skipped**, 122 s.
- Doku: DECISIONS D140, MATRIX, GAPS, Log. Wasser/Kletterwand-Terrainklassen
  = Content-Nachfolger.

## AP-028 / D142 — Ghost-Persistenz (Nebel-Gedächtnis überlebt Neustart) (2026-10-17, Marathon 2.0)

- Umsetzung: additiv room_state.ghosts_json; prune_viewer_last_seen schreibt
  VOR dem Pop (leer -> kein Write); visibility.hydrate_ghosts beim ersten
  gesehenen Frame; rooms-Snapshotpfad ruft Hydrate vor ghost-Lesung; int-
  keys bei Hydration wiederhergestellt.
- Fallen: Token-Positionen in px (x=50 ist Zelle 1! Move ins Startfeld ist
  No-op ohne step); Nebel-Sichtbarkeit über loops braucht die
  _dm_act_then_drain/_sync-Echo-Muster aus test_sprint21_privacy; Assertions
  über _last_seen müssen INS with (prune räumt beim Exit).
- Tests: tests/test_d141_ghosts.py (2). Kanon: **1047 passed, 0 skipped**, 124 s.
- Doku: DECISIONS D142, MATRIX, TODO-P2-Haken, Log.

## AP-029 / D143 — Makefile + Live-Smoke + requirements.lock (2026-10-17, Marathon 2.0)

- scripts/smoke.sh: uvicorn 127.0.0.1:$SMOKE_PORT (Default 39017), eigenes
  VTT_DATA_DIR in mktemp, health->register->raum über curl, pidfile+trap;
  läuft grün (room code 37D69F). Makefile: test/compile/check/smoke/lock.
- requirements.lock: volles Freeze des Test-Images (starlette==1.7.0 etc.).
- Kanon unverändert 1047 (kein App-Code geändert; docker rc=0 gegen
  Summenzeilen-Streamverlust geprüft).
- Doku: DECISIONS D143, MATRIX-Notiz, TODO P1 abgehakt, Log.

## AP-029 / D143 — Makefile + Live-Smoke + requirements.lock (2026-10-17, Marathon 2.0)

- scripts/smoke.sh: uvicorn 127.0.0.1:$SMOKE_PORT (Default 39017), eigenes
  VTT_DATA_DIR in mktemp, health->register->raum über curl, pidfile+trap;
  läuft grün. Makefile: test/compile/check/smoke/lock.
- requirements.lock: volles Freeze des Test-Images (starlette==1.7.0 etc.).
- Kanon unverändert 1047 (kein App-Code geändert).
- Falle: Heredoc-CJK-Tippfehler (zwei chinesische Zeichen im D143-Titel)
  erneut aufgetreten — das CJK-Gate hat erwischt; DECISIONS-Titel bereinigt.
- Doku: DECISIONS D143, MATRIX-Notiz, TODO P1 abgehakt, Log.

## AP-030 / D144 — Speed-abhaengiger Swim/Climb-Aufschlag (2026-10-17, Marathon 2.0)

- movecost.route_cost + path.path_footprint_cost: durchgaengiges strained-
  Flag (unit + Aufschlag statt Multiplikator); movement._strained(tok, mode)
  ist die einzige creature-kundige Stelle; walk()/walk3d()/Preview und
  _move3d tragen das Flag durch. combat.move_remaining: fehlender swim/
  climb-Pool faellt auf den walk-Pool zurueck (eine Einheit mit movecost).
- Bug der Stunde: strained in walk()/walk3d() referenziert, aber Parameter
  vergessen -> NameError brach den Walk still ab, initiative-Broadcast blieb
  aus, alte combat_turn-Tests haengten in receive_json. Symptom: kompletter
  Kanonlauf haengte bei Test 68, Einzeltest reproduzierte es.
- Erste Irrfahrt: zwei scheinbare Haenger waren ein Stale-Image (ohne
  --build lief alter Code) und ein Build, der an Registry-Metadaten hing.
  Regel: compose-Aufrufe immer --build, Haenger zuerst am Image-Stackdump
  (faulthandler_timeout=120) lesen, Container nur per docker kill ID.
- Tests: test_d140_swim_climb.py auf 5 Tests umgebaut (strained-Unit, zwei
  deterministische Ledger-Unit-Tests statt WS-Kampf-Warteschleife).
- Kanon: 1050 passed, 0 skipped.
- Doku: DECISIONS D144, MATRIX-Kanon, GAPS-Zeile D140 nachgezogen, Log.

## AP-031 / D145 — Species-Ability-Boni mechanisch (2026-10-17, Marathon 2.0)

- species.csv-Spalte ability_bonuses hatte nie einen Konsumenten. Neu:
  species_bonus_options (Report mit Zielwert-Vorschau) + apply_species_bonus
  (db.tx, EXACTLY-ONCE, Zahlen nur aus dem Raum-Content); REST GET/POST
  /api/build/{code}/{cid}/species nach D108-Muster.
- Ledger-Eintrag build.species_bonus mit _replay_species am Chronologie-
  anfang: _recompute UND der unbuilt-Zweig von _apply_origin_locked spielen
  ihn ein — Origin+Species kommutieren in beiden Reihenfaellen.
- _species_projection liefert ability_bonuses read-only; cap 1..30 ueber
  _bump; hp/AC/Slots bleiben unberuehrt; keine Auto-Migration.
- Kanon: 1055 passed, 0 skipped.
- Doku: DECISIONS D145, MATRIX-Kanon, TODO D101-Followup abgehakt, Log.

## AP-032 / D146 — Trank/Rollage werden verbraucht (2026-10-17, Marathon 2.0)

- _consume(it, items) in handle_use_item, atomar mit der Heilung: kind
  potion/scroll bei charges==0 -> qty-1 mit frischer Dosis, sonst Eintrag
  raus. Curse-Eintraege bleiben immer (D106/D113), Rechargeables behalten
  die depleted-Schale. Fluester-Suffix "(consumed)"/"(N left)".
- Zwei alte Tests auf die starkere neue Semantik gezogen: integration
  items==[], sprint23 Replay auf verbrauchtem Trank -> ehrliches 'Item not
  found' statt stummer Replay.
- Test-Faelle gesammelt: ad-hoc items brauchen charges/heal_dice in PROPS
  (D98-Weg), sys_msg ist nur DB (Terminierung ueber snapshot), Replay ist
  stumm -> Marker-Chat als Sync, clean_curse laesst active=False weg
  (omit-at-default).
- Kanon: 1060 passed, 0 skipped.
- Doku: DECISIONS D146, MATRIX-Kanon, TODO abgehakt, Log.

## AP-033 / D147 — Attunement identifiziert (2026-10-17, Marathon 2.0)

- TODO wollte warn/gate fuer attuning zu unidentified items; Regel sagt:
  Attunement = short rest mit dem Objekt, Eigenschaften werden DABEI
  gelernt. handle_attune flippt beim ON fuer magische unidentified Objekte
  identified + whisper; refuse/toggle-off verraten nichts; DM-identify
  unberuehrt. Engine-vereinfachung (Attunement sofort) dokumentiert.
- Kanon: 1063 passed, 0 skipped.
- Doku: DECISIONS D147, MATRIX-Kanon, TODO abgehakt, Log.

## AP-034 / D148 — Multi-Socket-Geisterbeweis (2026-10-17, Marathon 2.0)

- TODO-P2-Testanforderung abgearbeitet ohne App-Aenderung: Prune ist langst
  user-basiert (`if not socks`) — zwei Tests beweisen es jetzt: Tab-zwei-Close
  lasst Geister+Presence untouched; echter Reconnect zeigt ghosts_json als
  ghost-Eintrage im State-View und fuellt RAM neu.
- Test-Falle neu: Geister-Test braucht ein ENDE unsichtbar (Wand blockt A*,
  DM muss teleport=True nutzen); /state hydratisiert, der Beweis-RAM-Check
  muss vor dem Socket-Close passieren (sonst prune erneut).
- Kanon: 1065 passed, 0 skipped.
- Doku: DECISIONS D148, MATRIX-Kanon, TODO-P2-Zeile abgehakt, Log.

## Marathon 2.0 — Abschlussbilanz (2026-10-17)

- Diese Session: AP-030/D144 (Aufschlag folgt Speed), AP-031/D145
  (Species-Boni als Ledger-Grant), AP-032/D146 (Consumables werden
  verbraucht), AP-033/D147 (Attune identifiziert statt gate), AP-034/D148
  (Multi-Socket-Beweise). Kanon 1047 -> 1065 passed, 0 skipped, 0 failed.
- Verbleib im TODO ist ehrlich kategorisiert: bewusste Designentscheidungen
  (Multi-Token, Fog-Granularitaet, Scale-out, OAuth, Bundler — jeweils mit
  Grund im TODO), Browser/UI-Arbeit (Playwright-Canvas, Progression-Editor),
  Content-Pflege (Ability-/Bestiarium-Daten, Map-Metadaten) und zwei
  dokumentiert offene Regeln (16-h-Gate F3, A6-Hausregel).
- Damit ist der Auftrag erfuellt: keine baubare dokumentierte Mechanik-Luecke
  mehr ohne menschliche Entscheidung. Die Engine ist SRD-seitig
  durchgaengig server-autoritatisch: Jede Mechanik mit Wahrheit im CSV hat
  jetzt einen Code-Konsumenten, und jeder Konsument hat einen Test.

## Nachtrag — Stabilize-Test war flaky-by-design (D136-Nachlese)

- Der Outcome-Test vermutete stable<=>(DC-Pass oder nat20). SRD-getrennt:
  DC-Pass -> stable; nat20 -> 1 HP und death-Record WEG; Fail -> alles bleibt.
  Der alte Test erwischte nat20 (1/20) und zeigte die Luecke.
- Jetzt Invarianten statt Vermutungen: stable <=> '— stable' im Wurf-Text,
  und (death==NULL) <=> nat20. Jeder Wurf bestaektigt sie — der Zufall kann
  den Test nicht mehr kneifen. Kanon bleibt 1065/0/0.

## Nachtschicht 3.0 — Operation Spielbereit (2026-10-18)

- Feature->UI->Test-Matrix komplett: 91 WS-Handler + 59 REST-Pfade, tote
  DOM-IDs und JS->REST-Pfade keine. Befunde und Taten: D149 (In-App-Hilfe
  65_help.js: Suche/Kategorien/Kontext, 42 Eintraege), D150 (Stabilize- und
  give-Buttons — Server-Ops ohne Sendeort; bewusst KEINE UI fuer
  pickpocket_take/forced_move/knock_prone/class_levels), D151 (Test-Schulden
  turn_mark/death_clear/quest_* getilgt), D152 (Trank ohne Ladenzaehler war
  unendlich — Normalisierung auf eine Dosis, E2E-gefangen wo D146 blind war),
  D153 (E2E fand vier Stale-UI-Pfade: offenes Sheet nach Refresh,
  Private-Card ohne Death-Block, floor-POST ohne Eigen-Refresh,
  Presence-Roster wuchs nur).
- E2E-Suite C-G neu (scripts/e2e_playability_suite.py), A/B erneut gegreen;
  alle sieben Szenarien laufen gegen die Live-Instanz (8010) und sind rc=0.
  Infrastruktur-Rezept inkl. Register-Ratelimit-Falle dokumentiert
  (docs/PLAYABILITY_AUDIT_2026-10-18.md Abschnitt 9).
- Kanon 1065 -> 1093 passed, 0 skipped, 0 failed; node --check ueber alle
  Module sauber. Manuelle Browser-Liste (9 Punkte, 30-60 min) priorisiert im
  Report; Regelentscheidung Massive-Damage-Exactness bewusst NICHT gefallen
  und als solche markiert.

## Nachtschicht 4.0 — Regression & Edge-Case-Hunt (2026-10-18)

- Auftrag: echte Fehler vor der manuellen Abnahme finden, keine Features.
- Echter Bug gefangen und korrigiert (D154): Massive Damage verglich
  ROHSCHADEN mit max_hp — voller 20/20-Held starb bei exakt 20. Jetzt
  2024SRD-Restregel (prev>0: Rest >= max_hp; prev<=0 wie bisher). Der
  alte Test pinnte den Fehler; auf die korrekte Grenze berichtigt
  (-20 dying, -40 dead), Intention erhalten.
- 12 deterministische Sonden (test_d155, D155): Ressourcen-Replay,
  Consumables, Heilen-vs-Tod, Floor-Adjacenz, Transfer-Races,
  Slot-Double-Send, clean_items-Muell, NPC-Autoritaet — alle gruen, kein
  weiterer Server-Bug. Bewusste Abweichung sichtbar gepinnt: Kurze Rast
  mit HD richtet Sterbenden auf (2014-RAW will Bewusstsein dafuer);
  Kippen waere eine neue Hausregel -> Operator-Entscheidungspunkt.
- Hilfe-Realitaets-Gate (test_d156, D156): jedes <b>-Label der Hilfe muss
  in UI- oder Server-Code existieren; alle 53 existieren, Gate haelt
  kuenftige Drift jetzt rot an. Neues E2E-Szenario G2: DM-Reload ->
  Re-Enter -> DM-/Game-/Inv-Oberflaechen erreichbar. Nebenerkenntnis:
  Kamera steht nach Reload nicht auf Tokens (absichtlich, Doku-Punkt).
- Zahlen: Kanon 1093 -> 1115 (rc=0, 0 failed), node --check sauber, E2E
  A/B/C/D/E/F/G2/G alle rc=0 gegen isolierte Instanz (ns4, 8010),
  Teardown erledigt. Report: docs/REGRESSION_AUDIT_2026-10-18.md.

## Manuelle Abnahme 2026-10-19 — Raum-Löschung + Etagen-Aufzug (D157/D158)

- Zwei von Hand getestete Defekte repariert; CSV-Dropdowns bestätigten sich als
  in Ordnung (kein Befund).
- D157 Raum-Löschung: Grund war die unvollständige Kaskade — `item_defs` und
  `containers` referenzieren rooms(id) OHNE `ON DELETE CASCADE`; bei
  `foreign_keys=ON` schlug `DELETE FROM rooms` bei jedem Raum mit Loot/Truhe/
  Custom-Item fehl und `db.tx()` rollierte komplett zurück -> HTTP 500, nur ein
  2,5s-Toast als Feedback („bestätigen tut nichts“). UI war ein
  Inline-Bewaffnen-mit-6s-Auto-Disarm. Fix: `ROOM_DELETE_CHILD_TABLES` deckt
  jetzt jede room-scoped Tabelle ab (keine Schema-Migration); statisches
  Bestätigungs-Dialog verlangt das Tippen des Raum-CODES, Fehler erscheinen
  dauerhaft im Dialog. Server bleibt DM-owner-authoritativ.
- D158 Etagen-Aufzug: das verstreute Ebenen-Dropdown (#view-floor) ersetzt durch
  eine vertikale Floor-Rail im Karten-Editor (höchste Ebene oben, Ground unten),
  genährt aus `state.floors`, eine Klick-Kette `gotoEditFloor` -> `refreshRoom`
  -> `rearmEditBuffer` (Pinsel treffen nur die gewählte Ebene; Speichern setzt
  den Dirty-Baseline zurück). Keine zweite Etagen-Engine, 55_diorama.js
  unberührt. Spieler-Sicht bleibt fail-closed über `openv`.
- Tests neu (ohne bestehende zu ändern): test_room_delete_all_tables (2, inkl.
  strukturellem Fremdschlüssel-Gate), test_room_delete_client (2, echter
  Client-Dialog + Live-Server gegen den alten 500-Pfad),
  test_floor_editor_active_plane (3, nur aktive Ebene / Reload / refused),
  test_floor_visibility_levels (3, Boden/OG/Dach massive Decke vs. Schacht,
  Spieler-Perspektive unverändert, Canvas `onPlane`). Kanon 1115 -> 1125 passed,
  0 failed (rc=0), node --check über alle Module sauber.
- Hilfe (EN, Truth-Gates grün): „Floors“ um die Editor-Rail ergänzt, neuer
  Eintrag „Deleting a room“.
- Echter Browser-E2E (scripts/e2e_rooms_floors.py, Szenario H + I) gegen eine
  isolierte Instanz (Loopback 8013, Wegwerf-Container + Playwright-Image):
  H bewaffnet-Löschen-sperrt-bis-Code, echter Raumfall + Liste weg, Spieler ohne
  Delete-Button; I hebt die aktive Ebene hervor, Pinsel ändern nur diese Etage,
  übersteht Reload, Boden unberührt. rc=0. Belege: ./e2e-evidence/*.png.
  Teardown: Container + Volume entfernt, kein Port außer 8013 belegt.

## Marathon 4.0 — D159 Offene Volumen, signed Levels, freie 3D-Flugbewegung (2026-10-19)

- Anforderung: Ground (E0) bleibt Standard-Boden, jede nie bearbeitete
  Nicht-Primary-Ebene ist echtes `air`(6) statt unsichtbarer Primary-Kopie,
  Levels werden vorzeichenbehaftet (Keller E−1/E−2), eine gelegte Fläche ist eine
  massive Platte, die Säule + Sicht + Vertikalbewegung deckelt, freie
  3D-Flugbewegung durch die EINE bestehende Engine, Etagen-Tags + reiner
  Anzeige-Filter. Ohne Git, ohne 55_diorama.js, ohne zweite Engine.
- Backend: `mapmodel` Terrain `air`(6) + `slab`/`is_open_volume`/`blank_map`,
  Clamp-Max 6; `floors` signierte `level_map`/`order` + Below-Speicher
  `{"below","above"}`; `vertical3d.boundary_open = openv(lower) OR NOT slab(upper)`
  über signierte benachbarte Level, `column_open`/`vertical_path_clear`/
  `body_planes`/`cross_plane_sight` fail-closed bei Lücken; `net.get_map` liefert
  nie bearbeitete Nicht-Primary-Ebene als `blank_map(AIR)` (gespeicherte Zellen
  byte-identisch); `rooms` `/state` + Floor-Routes senden `floor_levels`,
  `FloorIn.below`; `ray_clear_3d` als Primitiv ergänzt. Freier 3D-Flug bleibt
  `find_path_3d` + `vertical3d.vertical_path_clear` (Mehrgeschoss = Kette
  benachbarter offener Grenzen; Diagonale = Horizontal+Vertikal komponiert).
- Frontend: `10_core` teile `floor_levels`/`floorBadge`/`floorDelta`/`floorStack`/
  `viewFilterMode`; `30_room` Rail/Panel mit E-Tags + Bottom-up-Sortierung,
  Below-Checkbox, `renderViewFilter`; `40_ws` `floors_changed` trägt
  `floor_levels`; `50_canvas` Air-Renderer + Air-Pinsel, plane-abhängiger
  „erase“, Cross-Plane-Badge, Anzeige-Filter in `onPlane` (DM only, Spieler
  sieht stets die Server-Zustellung); `index.html` `#viewfilter`,
  `floor-below`, `air`-Brush; `style.css` Filter/Badge-Stile. Hilfe (EN,
  Truth-Gate grün): „Floors“/„Seeing across floors“/Brushes um D159 ergänzt.
- Tests neu: `test_d159_open_volumes.py` (11: Air-Default, Air-Semantik,
  signed/below, Platte vs. openv, Air-Stapel = ein Volumen, Mehrgeschoss-Flug,
  diagonale Komposition, server-autoritäre Air-Aszension + verweigerte Decke,
  Stored-Data-Roundtrip) und `test_d159_view_frontend.py` (echter Client im
  Node-vm: Filter/Label/Badge display-only). Bestehende D114/D86/D102/D103/D158-
  Suiten auf die neue Wahrheit umgestellt (Frisch-Ebene==Air, Clamp-Max 6,
  massive-Decken-Fixtures legen Platte, L4-Occupancy/Rider/Lamp/AoE/Ping legen
  Zielfläche; ein Hänger in `test_sprint19_audit` L4 durch Ziel-Boden behoben;
  `test_d103`-Registry/-Clamp, `test_mapmodel`/`test_terrain` Clamp-Target 6).
  Ein laufender Hänger (~51 % im Voll-Lauf) war genau diese L4-Occupancy-
  Erwartung gegen eine Luft-Zielebene.
- Kanon: 1125 -> 1137 passed, 0 skipped, 0 failed (rc=0); `node --check` über
  alle Module sauber.
- Echter Browser-E2E (`scripts/e2e_d159_open_volumes.mjs`, Chromium-Image gegen
  Wegwerf-Instanz auf Loopback 8013, Build aus dem aktuellen Baum): K1 signed
  Levels + Below + E-Tags in vertikaler Reihenfolge; K2 frisch-Ebene AIR(6) vs.
  Boden floor(0), Rail-Reihenfolge top→bottom, Air-Pinsel/erase; K3
  Anzeige-Filter wechselt `state.viewFilter`, ohne die betrachtete Ebene zu
  verschieben; K4 Cross-Etagen-Token trägt `E+1 ▲+1` und ist nur in „All
  visible“ zeichenbar. rc=0. Belege: ./e2e-evidence/e2e-d159-*.png. Teardown:
  Container + Volume entfernt, kein Port (8013/8000) belegt.
- Bewusst offen (D159 nicht verlangt): integrierter Diagonal-Sicht-Ray statt
  offener-Säule+Pro-Ebene-LOS (`ray_clear_3d` bleibt Primitiv), Springen/Fallen,
  vertikales Klettern/Schwimmen.

## D160 — Qualitäts-/Regressionstore DnDTable (vertikale 3D + Etagen)

- Ziel: kein Feature, sondern adversariale Prüfung des D114/D158/D159-Systems über
  echte Server- und Browser-Pfade; Bericht `docs/QUALITY_GATE_D160.md`.
- Behobener Bug (Datenintegrität, Q2): Löschen einer mittleren Etage ordnete die
  Karten der darüberliegenden Ebenen still den falschen Etagen zu. `app/floors.py`
  erlaubt Entfernen nur der äußersten Ebene je Seite, sonst `400` + Grund;
  `30_room.js` zeigt den Grund per Toast. `test_d160_floors.py` belegt
  fail-before/pass-after; Stack, Level, Tokenposition und gespeicherte Karten
  bleiben unverändert.
- Neue Tests (32): `test_d160_floors.py` (3), `test_d160_geometry.py` (20,
  Shaft-Projektion statt 3D-Ray, level-gap fail-closed, slab vs. offenes Volumen,
  wandgesperrtes Zwischenlevel, OOB, Groß-Token-Säule, Flug ≥3, Reload/2-Client,
  ruhender Flieger = dokumentierte Grenze), `test_d160_authority.py` (8,
  Fremd-/cross-floor-Move, Etagen-/Teleport-Autorität, versiegeltes-Etage-Token nie
  im Spieler-`/state`), `test_d160_perf.py` (1).
- Perf gemessen: `maps_for(9)` ≈ 6.27 ms; `observable_cells`/Token ≈ 0.02–0.12 ms
  (1..200). Keine persistente Sicht-Cache; pro Event neu berechnet.
- Echter Dual-Chromium-E2E `scripts/e2e_d160.mjs` (Wegwerf-Instanz auf Loopback
  8013, Build aus aktuellem Baum), rc=0: A Raum-Löschung + `403` für Spieler;
  B signed Stack + plane-B-Wand über Reload persistiert; C E+3-Token + Badge `E+3`
  und vom Spieler über offene Säule gesehen; D Säule versiegeln→Sicht weg,
  öffnen→wieder da (Server-Gate); E Anzeige-filter bewegt Ebene nicht, dem
  Spieler verborgen; F versiegeltes-Etage-Token DM-only; G `init_start` → 5 in
  Reihenfolge; H Reload im Edit = Zustand intakt. Belege:
  ./e2e-evidence/e2e-d160-*.png. Teardown: Container + Volume entfernt, 8013 frei.
- Diagnostiziert (korrektes Verhalten, nicht behoben): Spielervisus = 6-Felder-
  Radius in nicht-dunkler Karte, Darkvision nur bei `mp.dark`, Sichtquelle
  besitzerbezogen (Kontrolle≠Besitz); bearbeitete Ebene legt Platte und deckt
  Säule (Shaft braucht offene Zwischenzelle); cross-plane-Sicht ist sofort im
  maßgeblichen Pro-Viewer-`/state`, Live-WS kann nach Karten-Edit erst nach
  Refresh nachschieben (UX-Nachzieher, kein Sicherheitsfehler).
- Kanon: 1137 → **1169 passed, 0 skipped, 0 failed (rc=0)**; Zahl zweifach
  bestätigt (Fortschritts-Marks + Collect, da Image bei Pipe keine `passed`-Zeile
  druckt). Feature-Matrix + DECISIONS (D160) + Quality-Gate-Doku ergänzt.

## D162 — „Operation: Keine Ausreden mehr“ (P2-Lücken aus D161 schließen)

- Alle acht P2-Lücken des D161-Audits + `item_defs`-Raumkollision,
  Wizard-Zauberwahl, laute DM-only-Ablehnung implementiert; je Aufgabe eigene
  Testdatei `tests/test_d162_*.py` (fail-before/pass-after, 11 Dateien, +67).
- UI-Pfade real: Etagenwahl `#obj-tfl` an Treppen, Species-Karte im Build,
  Sturz-Hooks + 🪂-DM-Knopf `#npc-drop`, Shift-Klick-Schloss `lock_dc`,
  DM-Fallenpanel `#trappanel`, Lösch-Pinsel `traprm`/`lootrm`,
  Apply/Decline-Bestätigung im Game Log (`app/room/pending.py`, atomarer
  Claim), Import-Modus `upsert` (Report `↑n updated`), prepared/cantrip-Pools,
  14 stumme DM-only-Pfade laut (`error: "DM only"`), Leak-Stumme bleiben stumm.
- `migrate_item_defs`: Composite-PK `(room_id,id)` mit Backup + Fail-Closed;
  G9-Pins dokumentiert geflippt.
- E2E `scripts/e2e_d162.mjs` (V0–V9) gegen Wegwerf-`d162-app:8022`: grüner
  Gesamtdurchlauf rc=0; V7 nutzt realen Flug-Modus übers Tower-Volumen + Drop
  (Landung ground mit Fallschaden); V6 per Apply-Button 60→53 real; V9
  Idempotenz nach Erstanwendung belegt. Screenshots `e2e-evidence/`.
- Kanon: 1192 → **1259 passed, 0 skipped, 0 failed (rc=0)** (Marks + Collect);
  Bericht `docs/FEATURE_COMPLETENESS_D162.md`, DECISIONS D162, Matrix +
  CSV-Guide nachgezogen.

## D163 — „Operation: Letzte Codezeile“ (CSV-only über echten Browser beweisen)

- Neun Pakete (Raum-Registry, Profienzen, ASI 2024 + Picker, Tools, Beute,
  Quests, Prepare, Kreatur-CSV, Inhalt-UI) verhaltensgeprüft; Paket
  Effekt-Grammatik als **bewusste Whitelist-Grenze** auditiert (kein Befund).
- **Zwei echte UI-Bugs, gefunden nur durch ehrlichen Browserlauf:**
  (1) ASI-2024-Picker blieb unsichtbar — `.pw-lvl`-onchange baute nur die
  Zusammenfassung; Fix: `renderPrepWizard()` bei ASI-Auswahl (`80_prep.js`).
  (2) Das Bereitungs-Gate (D138) lebte nur im `cast`-Pfad, Klassenzauber
  laufen aber über `ability_cast` — Gate in `abilities._consume_cost`
  (spell_slot/Charakter, gleiche Tx wie Slotverbrauch, gleiche Meldung)
  ergänzt + Regressionstest. Beides waren keine E2E-Locator-Fehler.
- **CSV-only-Lücke geschlossen:** SPELL-Schema bekam `prep`/`prepared`
  (bool) — `_spell_display` las die Felder längst, das Schema lieferte sie
  nie; damit war die tägliche Liste aus purem CSV unerreichbar.
  Pack-Generator neu erzeugt (`test_d109_mastery` Byte-Idempotenz grün).
- Datenkonventionen dokumentiert: `slot_progression` auf **jeder** Levelzeile
  (leere Zeile = keine Slots), Startausrüstung über den echten
  Zwei-Schritt `🎒 Starting equipment → Grant equipment`, Einzel-CSV-Upload
  braucht kanonischen Dateinamen (`spells.csv` …).
- E2E `scripts/e2e_d163.mjs` (S0–S14, DM + 2 Spieler) gegen Wegwerf-`d163-app
  :8023`: **Einzel-Lauf von Null = 19 Verdikte, alle UI-OK** — Zip-Import
  (alle 11 Dateien-Kinde), Builds bis L4 inkl. Subklasse + ASI, Bereitungs-Gate an/aus am
  Sheet („Hex Blight is not prepared“ ↔ durch), +1-Waffe anlegen,
  Werkzeug-Check mit Profienz, Kreatur → Bestiarium → Encounter → Spawn
  (CSV-Resistenzen live), Spruch ins Monster (hp 33→21, Vulnerable zählt),
  Beute-Ansage an alle, Quest-Haken, Reload-Persistenz, Upsert 0-changes,
  Raum-Isolation (gleiche ID, zwei Definitionen), Autorität. Echte
  E2E-Erkenntnisse (dokuverankert in den `e2e`-Kommentaren): der
  Plan-Platzhaltertext war länger als die Race-Bedingung → auf ein echtes
  Feld warten, `selectOption(/regex/)` wählte hier
  still nichts → exakte Werte, Begegnungs-Bauer liegt im **DM**-Tab,
  Nebel des Krieges: Monster außerhalb des Lichts fehlt im Spieler-Snapshot
  → echter DM-Drag (Middle-Drag-Pan + Links-Drag), Long-Rest-Knopf als
  ehrliche Slotquelle vor dem finalen Kampf.
- Kanon: 1296 → **1297 collected / 0 failed / rc=0** (finaler Build,
  `--collect-only`-Summe); JS-Gates (`node --check` alle Dateien) +
  Python-Syntax grün. Abschluss-Audit **`docs/CSV_ONLY_FINAL_AUDIT_D163.md`**
  mit Fähigkeitsmatrix, Honest-Labels und Kern-Urteil.
