# CSV-Only-Final-Audit — D163 „Operation: Letzte Codezeile“

Datum: 2026-10-21. Frage dieses Audits (Kernfrage des ganzen Projekts):

> **Ist neuer D&D-5e-2024-Inhalt vollständig CSV-gesteuert lieferbar — ohne
> eine einzige Zeile Engine-Code — und ist das mit echten Browser-Aktionen
> (DM + zwei Spieler) bewiesen?**

## Urteil

**JA-MIT-GRENZEN.**

* **JA** — der komplette D163-Akzeptanzinhalt (11 CSV-Dateien: Spezies,
  Klassen inkl. Halbcaster-Progression, Unterklasse, Hintergrund, Talente,
  Zauber inkl. Bereitungs-Gate, Waffen-/Werkzeug-Gegenstände, Kreatur mit
  Abwehrwerten, Beutetabelle mit Mengenwürfel, Quest, eigener Zustand) wurde
  per Zip hochgeladen und **jede einzelne Spieler-/DM-Handlung war im echten
  Browser ausführbar**: 19 Verdikte, **alle UI-OK**, in einem einzigen Lauf
  von Null (frischer Container, frische Volume, frischer Nutzer-Stammbaum).
  Kein Schritt brauchte API-Direktaufruf, Fixture-Handarbeit oder
  Hand am Code.
* **GRENZEN** — „vollständig“ heißt *innerhalb der dokumentierten
  Effekt-Grammatik*. Reaktionen, Auren, Beschwörungen, Teleport,
  Komponenten und Proben-gegen-Probe sind weiterhin **NICHT SUPPORTED als
  Daten** (Whitelist in `effectops.canon()/run()`, bewusst gewählte
  Sicherheitsgrenze — in D163 Paket für Paket auditiert, keine neue Lücke,
  keine Änderung). Details in „Restarbeit braucht Code“ unten.

Ein pauschales JA wäre unehrlich (die Grammatik hat dokumentierte Grenzen);
ein NEIN wäre falsch (alle D163-Kandidaten und alles, was die Grammatik
hergibt, sind nachweislich rein datengetrieben — bis hin zur täglichen
Bereitungsliste und dem Gate auf *beiden* Wirkpfaden).

## Methodik — was als Beweis gilt

1. **Ehrlicher Browser-E2E** `scripts/e2e_d163.mjs` gegen eine Wegwerf-Instanz
   (`d163-app` auf `127.0.0.1:8023`, eigener Container, eigene Volume;
   `d161-app`/`d162-app` und deren Volumes unberührt). Jeder Schritt spielt
   mit Maus/Klick/Drag/Tastatur, was ein Mensch spielt, und wird klassifiziert:
   | Label | Bedeutung |
   |---|---|
   | **UI-OK** | echter Klickpfad funktioniert, Wirkung serverseitig belegt |
   | **API-ONLY** | geht nur per API, nicht im UI |
   | **FIXTURE-ONLY** | nur mit Test-Handarbeit (DB-Handstand) erreichbar |
   | **BROKEN** | UI-Element vorhanden, Funktion kaputt |
   | **NOT SUPPORTED** | bewusst nicht vorgesehen (dokumentierte Grenze) |
   Das E2E darf nichts schönreden: ein Schritt, der nur über einen Umweg
   ginge, fiele als API-ONLY/FIXTURE-ONLY auf. Genau so wurden die zwei
   echten UI-Bugs gefunden (unten).
2. **Vollständiger Test-Kanon** gegen den finalen Build:
   **1297 gesammelte Tests, geordneter Voll-Lauf rc=0**
   (`COMPOSE_PROFILES=test docker compose run --rm --build test pytest -q -p
   no:randomly`; `--build` ist Pflicht — der `test`-Service brennt den Baum
   ins Image, mountet ihn nicht). Die Zahl 1297 stammt aus der Summe der
   `tests/x.py: N`-Zeilen von `pytest --collect-only -q` (dieses Image druckt
   durch Pipes keine `N passed`-Zeile; rc=0 ist der verlässliche grüne Beleg —
   selbe Messmethode wie bei 1296 vorher, Differenz = der eine neue
   Regressionstest).
3. **Statische Gates**: `node --check` über alle `app/static/js/*.js` (OK);
   alle Python-Dateien kompilieren (`compile()`-Schleife — `tests/__pycache__`
   gehört root aus den Docker-Läufen, daher kein `compileall` dort).
4. **Unversehrtheits-Pins**: `app/static/js/55_diorama.js` unangetastet
   (mtime 2026-10-17); keine Git-Kommandos; keine Migrationen; keine
   abgeschwächten Tests (der einzige Test-Neuzugang ist ein schärferes Pin).

## Fähigkeits-Matrix (D163-Pakete, jeweils mit echtem Beleg)

| # | Fähigkeit (aus CSV) | Label | Beleg |
|---|---|---|---|
| 1 | Raum-Registry: gleicher-Zauber-ID in zwei Räumen, eigene Definitionen | UI-OK | S13: Raum B importiert `hex_spark`-Variante → B exportiert „OF B“, A bleibt unverändert |
| 2 | Waffen-/Werkzeug-Profienzen als Achsen (Klasse/Hintergrund/Talent) | UI-OK | S6b: `🧰 Hexing Kit: INT 14+3 = 17 (with proficiency)` — +3 = INT-Mod (+1 auf den ASI-geboosteten Wert 13, DB-verifiziert) + TB (+2 aus Stufe 4); „with proficiency“ kommt aus der Werkzeug-Achse des Hintergrunds |
| 3 | ASI 2024 im Assistenten (+2/+1, +1/+1/+1) | UI-OK | S2/S3: `asi {mode: plus2_plus1, plus2: wis, plus1: int}` rein per Klick (nach Picker-Fix, s. u.) |
| 4 | Werkzeug-Gegenstände sind benutzbar (`kind=tool`, `tool_ability`) | UI-OK | S6b: Use-Knopf im Inv-Tab → echter Check über die eine Check-Engine (`opposed.check_roll`), Flüstern an den Spieler |
| 5 | Beutetabellen mit Gewichten + Mengenwürfeln (`2d6+5`) | UI-OK | S9: „🎲 Grick cache: 14 × Coin purse“ — über die eine Chat-Pipeline bei DM **und** beiden Spielern sichtbar |
| 6 | Effekt-Grammatik-Erweiterbarkeit | NOT SUPPORTED (bewusst) | auditiert: Whitelist in `effectops.canon()/run()` ist die Sicherheitsgrenze; „Reaktionen/Auren/Beschwörungen als Daten“ bleibt dokumentierte Grenze (`docs/EFFECT_GRAMMAR.md` §6) — kein Befund, keine Änderung |
| 7 | Tägliche Bereitungsliste aus CSV (`prep`/`prepared`) + Gate auf `cast` UND `ability_cast` | UI-OK | S5a `Hex Blight is not prepared` ↔ S5b gleicher Knopf, Haken wieder dran → kein „not prepared“ mehr; S11: Liste überlebt Reload |
| 8 | Kreatur-CSV: Abwehrwerte/Klettern/Ladungen → projiziert ins Spawn | UI-OK | S7a/b: Zeile → Reviewer → Bestiarium → Encounter → Spawn, Am Board: `resist=[psychic,poison] vulnerable=[necrotic]` |
| 9 | Inhalt-UI-Sichten (Importer-Report, Kreatur-Reviewer, Kinds-Zähler) | UI-OK | S1/S7a/S12: alle Reports per Klick lesbar; Upsert-Reimport meldet 0 Changes, Inhalte bleiben identisch |
| — | Zauber mit Op-Kette (Schaden + Rettung + Zustand) gegen Monster | UI-OK | S8: Sheet-Zielwahl + Cast → Server-HP `33→21` (12 = 2d6×Vulnerability, CSV-Wert zählt) |
| — | Quest-CSV → lebendes Questlog, DM-Haken, Persistenz | UI-OK | S10a/b + S11: Ziel hakt per Klick, Haken bleibt, Upsert-Reimport verwüstet den Fortschritt nicht |
| — | Magiewaffe (+1/+1, attunement) anlegen | UI-OK | S6a: Inv-Tab → „Main hand“ |
| — | Startausrüstung aus Klassen-/Hintergrundzeilen | UI-OK | S2/S3: echter Zwei-Schritt `🎒 Starting equipment → Grant equipment` |
| — | Reload-Persistenz aller CSV-Spielzustände | UI-OK | S11: Quest + Monster + Prep-Liste nach Neuladen identisch |
| — | Autorität: Spieler sehen keine DM-Werkzeuge | UI-OK | S14 |

Alle 19 Verdikte des Einzellaufs: Klasse `ui`. Kein Schritt brauchte
API-ONLY oder FIXTURE-ONLY — das war vor D163 anders (ASI-Picker und
Ability-Gate waren BROKEN bzw. Lücke).

## E2E-Beweiskette (Einzellauf von Null, Einzel-Instanz)

Frisch-Zyklus: Container + Volume + State weg → `docker run` → E2E →
S0–S14 ohne Wiederaufnahme. Belege: 13 Screenshots
`e2e-evidence/d163-*.png` + `/home/alp/d163state/verdicts_d163.jsonl`
(Verdikte der Vor-/Resume-Phasen archiviert unter
`verdicts_d163_resume_phases.jsonl` und `e2e-evidence/d163-resume-phase/`).

| Schritt | Kernbeleg (wörtlich aus dem Lauf) |
|---|---|
| S0–S4 | Registrierung/Logins, Zip-Import `species: 1 · class: 4 · subclass: 1 · item: 2 · spell: 2 · background: 1 · feat: 2 · creature: 1 …` (11 Dateien), zwei Builds (L4/L1), Sitzen |
| S5a/b | Haken raus → `error: "Hex Blight is not prepared"`; Haken rein → dasselbe Feld antwortet nicht mehr mit dem Gate |
| S6a/b | `Main hand` + `Dagger of Misery`; `🧰 Hexing Kit: INT 14+3 = 17 (with proficiency)` |
| S7a/b | `Grick Guard` im Bestiarium; Spawn trägt `{"resist":["psychic","poison"],"vulnerable":["necrotic"]}` |
| S8 | `hp 33->21 lost=12` (Vulnerability gegen nekrotisch zählt — aus der CSV-Zeile) |
| S9 | `🎲 Grick cache: 14 × Coin purse` (chat-Kind, alle drei Clients) |
| S10a/b | Quest „The Blighted Garden“ live; Zielhaken `☑` gesetzt und fest |
| S11 | `quest=true grick=true prep=true` nach komplettem Reload |
| S12 | Upsert: `OK` pro Datei, keine Inhaltsänderung |
| S13 | `A untouched=true B own=true` |
| S14 | kein Loot-Knopf, kein DM-Tab für Spieler |

Ehrliche Kleingedruckte:

* S8 misst am **Server-HP-Delta** (Autorität), nicht an Chat-Schönfärberei;
  der Text-Zähler für die Schadenszeile im WS-Mitschnitt war 0 (regex
  traf die Zeilenformate nicht) — das Verdikt stützt sich nicht darauf.
* Vor S8 drückt der DM den echten `🛌 Long rest`-Knopf (raumweiter Reset —
  bestehende Engine-Semantik), damit der finale Wurf Slots hat. Das ist
  ein realistischer Tisch-Schritt, kein Cheat.
* Nebel des Krieges: ein frisch gespawntes Monster außerhalb des Spielerlichts
  fehlt im Spieler-Snapshot — das Sheet kann nichts anvisieren, was der
  Charakter nicht sieht. Der E2E zieht es per **echtem DM-Drag**
  (Middle-Drag-Kamerapan + Links-Drag) ins Licht. Das ist die korrekte
  Spielregel, hier als UI-Pfad bewiesen.

## Was das ehrliche E2E gefunden hat (echte Produkt-Bugs, nicht Locator-Müll)

1. **ASI-2024-Picker tot im Browser** (`80_prep.js`): `onchange` der
   Level-Zeile baute nur die Zusammenfassung, nie den +2/+1-Picker — der
   2024-ASI war per Klick nie durchführbar. Fix: Assistenten-Rebuild bei
   ASI-Auswahl. S2/S3 spielen den Weg jetzt; die DB nach dem UI-Bau zeigt
   die Anwendung (wis 14→16, int 12→13).
2. **Bereitungs-Gate fehlte auf der Ability-Schiene** (`app/abilities.py`):
   charbuild legt jeden Klassenzauber in `characters.abilities`; das Sheet
   rendert dafür `.cast-ab` → `ability_cast` — und dort verbrauchte der Wurf
   einfach Slots, egal ob vorbereitet. Die tägliche Liste wäre für genau die
   CSV-Caster dekorativ gewesen, für die sie gebaut wurde. Fix in
   `_consume_cost` (spell_slot-Zweig für Charaktere, Regel/Meldung
   deckungsgleich mit `room/dice.py`, Lesung in derselben Transaktion wie der
   Slot-Zähler). Fest genagelt:
   `test_d163_prepare.py::test_ability_pipeline_cast_respects_the_daily_list`
   (prüft auch: abgelehnter Wurf lässt den Slot unversehrt).
3. **Schema-Lücke `prep`/`prepared`** (`app/content.py`): die Sheet-Anzeige
   las die Felder seit D138 — das SPELL-Schema hatte sie nie geliefert, also
   war die tägliche Liste aus purem CSV unerreichbar. Jetzt bool-Spalten;
   Auslieferungspack neu generiert (`scripts/make_content_pack.py` leitet die
   Spalten aus den Live-SCHEMAS ab → Byte-Idempotenz `test_d109_mastery`
   wieder grün; nur `spells.csv` geändert, alle Werte leer → Verhalten
   identisch).

## Dokumentierte Abweichungen und Engine-Semantik (bewusst nichts geändert)

* **Slotverbrauch vor Ziel-Ablehnung** auf der Ability-Schiene: ein Wurf
  ohne Ziel verbraucht den Slot trotzdem (bestehende Execute-Reihenfolge,
  historischer Engine-Kanon). Das Prepared-Gate greift **vor** dem Verbrauch
  — der Regressionstest pinnt genau das.
* **Nebel des Krieges**: Spieler-Zielwahl zeigt nur, was gesehen wird
  (Snapshot-Stripping). Korrekte Regel; der ehrliche Pfad ist DM-Zug oder
  Licht.
* **DM-Long-Rest-Knopf** stellt im ganzen Raum wieder her (bestehende
  Semantik, Titel-Tooltip sagt es).
* **Pack-Homebrew-Labels**: `hedgehex`/`hex_blight`/`Grick Guard` sind
  eigene Akzeptanzinhalte (kein SRD 5.2.1), im Pack als D163-Akzeptanz
  markiert; die Slot-Tabelle `1:2` pro Zeile ist eine eigene Halbcaster-
  Progression — Regelkanon bleibt D&D 2024/SRD 5.2.1, Abweichendes ist
  beschriftet.
* **Datenkonventionen ohne Codeänderung** (Guide nachgezogen):
  `slot_progression` muss auf **jeder** Levelzeile stehen (leere Zeile =
  keine Slots); Einzel-CSV-Uploads brauchen den kanonischen Dateinamen
  (`spells.csv` …, Kind-Erkennung am Basisnamen, Phantasiename läuft
  wirkungslos durch); Startausrüstung = Zwei-Schritt `🎒 Starting
  equipment → Grant equipment`.

## Restarbeit braucht Code (die Grenzen des JA)

Aus `docs/CSV_ONLY_READINESS.md` (D110) geerbt, in D163 erneut abgeklopft —
**unverändert wahr**, jeweils dokumentierte Grenze, kein D163-Befund:

1. **Reaktionen, Auren, Beschwörungen, Teleport, Komponenten (V/S/M)** —
   nicht als Op ausdrückbar (`docs/EFFECT_GRAMMAR.md` §6); die Whitelist in
   `effectops.canon()/run()` ist die bewusste Sicherheitsschwelle. Ein
   „neuer Paket-Typ“ wäre genau die letzte Codezeile, die es hier nicht gibt.
2. **Probe gegen Probe** (Athletics-vs-Athletics als Daten-Autorisierung) —
   Kontesto-Primitives existieren als Helper, aber kein Grammatik-Op (§6a).
3. **Kreaturen-Sonderaktionen/Auren** aus `creatures.csv`; automatischer
   Spawn direkt aus der Raumzeile (der ehrliche Weg bleibt Bestiarium →
   Encounter → Spawn — was funktioniert und in S7 UI-OK ist).
4. **`needs_choice` ohne Leser, `spell_replace`/`features` als
   Ledger-Prosa, Dauer-Uhr außerhalb des Kampfes** — Flächen ohne
   Mechanik-Leser bleiben Buchführung (Matrix in `CSV_ONLY_READINESS.md`).

Das ist Feature-Complete-Restarbeit im Sinne von
`docs/FEATURE_COMPLETE_GAPS.md`, kein Wunschzettel — und nichts davon
blockiert den D163-Akzeptanzinhalt oder irgendetwas innerhalb der
Grammatik.

## Nachbau dieses Beweises

Die Beweisinstanz `d163-app` läuft noch auf `127.0.0.1:8023` (Evidenz-DB mit
dem E2E-Endzustand; bewusst behalten, `d161-app`/`d162-app` unberührt). Für
den Frisch-Beweis:

```bash
# Instanz (Frisch-Zyklus): Container + Volume + /home/alp/d163state/* weg, dann
docker build -t d163-app:latest ~/DndDieZweite
docker run -d --name d163-app -p 127.0.0.1:8023:8000 -v d163-data:/srv/data d163-app:latest
# E2E (Einzel-Lauf, exaktes Rezept):
cd ~/DndDieZweite && docker run --rm --network host \
  -v "$PWD/scripts":/work -v "$PWD/e2e-evidence":/shots -v /home/alp/d163state:/st \
  -e VTT_E2E_BASE_URL=http://127.0.0.1:8023 -e VTT_E2E_EVIDENCE=/shots \
  -e VTT_E2E_STATE=/st -e D161_TAG=d163 \
  mcr.microsoft.com/playwright:v1.64.0-noble bash -lc \
  "cd /tmp && cp /work/e2e_d163.mjs /work/e2e_d161_lib.mjs . && \
   PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm i playwright@1.64.1 >/dev/null 2>&1 && \
   node e2e_d163.mjs"
# Kanon:
COMPOSE_PROFILES=test docker compose run --rm --build test pytest -q -p no:randomly
COMPOSE_PROFILES=test docker compose run --rm test pytest --collect-only -q  # Summe der „tests/x.py: N“-Zeilen = 1297
```

## Fazit

Die Kernfrage ist beantwortet: **Was die Effekt-Grammatik ausdrückt, ist
komplett CSV-lieferbar — und jeder Mensch am Tisch kann es mit Maus und
Klick tun**, bewiesen in einem einzigen frischen Browserlauf mit zwei
Spielern und einem DM, inklusive der Zauber-Bereitschafts-Entscheidung, die
D138 erfand und die erst durch D163 aus dem CSV erreichbar *und* auf dem
echten Sheet-Knopf wirksam wurde. Die Grenzen sind nicht versteckt, sondern
in einer Whitelist-Datei und zwei Doku-Abschnitten betoniert: jenseits von
damage/heal/condition/save/check/resource reicht der Datensatz nicht, ohne
den Sicherheitsring zu erweitern — und das ist eine Entscheidung, kein
Vergessen. **Urteil: JA-MIT-GRENZEN.**
