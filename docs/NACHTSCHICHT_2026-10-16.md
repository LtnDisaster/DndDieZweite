# Nachtschicht-Bericht 2026-10-16

## Rahmen

- Ziel: bis Freitag, 2026-10-16, 04:00 Europe/Berlin möglichst hohe, stabile und
  dokumentierte Verbesserung von Stabilität, Vollständigkeit, Sicherheit und
  Testintegration.
- Arbeitsprinzip: vorhandene SSOTs und Engines erweitern, keine zweite Regel-,
  Bewegungs-, Sicht-, Kampf-, Würfel- oder Inventarmaschine bauen.
- Keine Git- oder `.git`-Aktionen, keine Datenbankmigration, kein Löschen von
  Spielständen, keine Änderung an `app/static/js/55_diorama.js`.
- Regelfundament: D&D 5e Revision 2024 / SRD 5.2.1.
- Code- und Schema-Identifikatoren bleiben englisch; Dokumentation deutsch.

## Kanonisches Ergebnis

| Stand | Testergebnis |
|---|---|
| D114 / Sprint 43 | `948 passed, 1 skipped, 0 failed` |
| D115 / Nachtschicht | `959 passed, 1 skipped, 0 failed` |
| D116 / AP-001 | `960 passed, 0 skipped, 0 failed` |
| D117 / AP-003 | `963 passed, 0 skipped, 0 failed` |
| D118 / AP-004 | `964 passed, 0 skipped, 0 failed` |
| D119 / AP-005 | `964 passed, 0 skipped, 0 failed` |
| D120 / AP-006 | `964 passed, 0 skipped, 0 failed` + real-Chromium pass |
| D121 / AP-007 | `967 passed, 0 skipped, 0 failed` + real-Chromium pass |
| D122 / AP-008 | `971 passed, 0 skipped, 0 failed` + creature-projection Chromium pass |
| D123 / AP-009 | `973 passed, 0 skipped, 0 failed` + beide Chromium-Suiten grün |
| D124 / AP-010 | `976 passed, 0 skipped, 0 failed` + NPC-Skill-Display in echtem Chromium bestätigt |
| D125 / AP-011 | `977 passed, 0 skipped, 0 failed` + echter `ability_cast`-Restore |
| D126 / AP-012 | `979 passed, 0 skipped, 0 failed` + Species-Engines grün |
| D127 / AP-013 | **`981 passed, 0 skipped, 0 failed`** + Companion-Markierung grün; NPC-Angriffs-/Slotpfade gegen unvollständigen Spawn-Block abgesichert |

Die neue Suite `tests/test_engine_gear_grants.py` enthält **11 Tests**. Der
kanonische Docker-Lauf nach der letzten Code-Änderung dauerte 6:58 Minuten.

## Umgesetzte Schwerpunkt-Pakete

### 1. Ausrüstung wirkt in bestehenden Engines

- `gear.effective_gear()` ist die einzige Gear-Ableitung für getragene und
  gehaltene Gegenstände.
- `movement._speeds()` nutzt den vollständigen Charakter-Sheet und damit
  `gear.clean_speeds()`; `speed_bonus_ft` erhöht das reale Bewegungsfeld.
- `visibility._token_darkvision_cells()` hebt den Dunkelsicht-Radius um
  `darkvision_ft`. Die Umrechnung bleibt 5 ft pro Rasterschritt; es entsteht
  keine zweite LOS-Engine.
- `gear.effective_gear()["hit_dice_bonus"]` fließt in `handle_short_rest()` ein
  und wird pro verbrauchtem Hit Dice angewandt. Der Chat-Beleg zeigt den
  Gear-Anteil.
- `gear.wields_two_handed()` respektiert nun zusätzlich `props.hands == 2` und
  verwendet weiterhin die bestehende Zwei-Hände-/Off-Hand-Regel.

### 2. Origin-, Klassen- und Talent-Spalten laufen über den einen Build-Pfad

- `backgrounds.skill_prof` wird in `charbuild._replay_origin()` auf dem
  bestehenden Origin-Chronologie-Pfad angewandt.
- `feats.spells_grant` nutzt dieselbe Grant-Achse wie Subklassen und erreicht
  `spell_state`, `characters.abilities` und `characters.spells`.
- Raumfremde, aber im Raum existierende Grant-Zauber können projiziert werden;
  dafür prüft `_all_spell_rows()` alle Raum-Zauberzeilen.
- `classes.expertise` ist jetzt opt-in auf der vorhandenen Skill-Achse
  (`0`/`1`/`2`) implementiert.
  - Die Auswahl darf die Zeilenkapazität nicht überschreiten.
  - Expertise ist nur auf bereits profizienten Fertigkeiten möglich.
  - Ungültige Auswahl bricht fail-closed ab.
  - Ältere Build-Entscheidungen ohne `expertise` bleiben unverändert.

### 3. Provenienz und Lesbarkeit statt zweiter Regelkerne

Ohne zusätzliche Adjudikation werden jetzt erfasst und angezeigt:

- Background-Feature, Sprachen und Tool-Proficiencies.
- `classes.weapon_prof` und `classes.armor_prof` als Build-Ledger-Projektion.
- Subclass-Textfeatures in der Level-Chronologie.
- Die Species-Zeile als read-only `build.species`-Projektion.
- Gear-abgeleitete Dunkelsicht, effektive Gehgeschwindigkeit und Hit-Dice-Bonus
  im Charakterblatt.

Betroffene UIs: `app/static/js/80_prep.js` und `app/static/js/30_room.js`.

## Geänderte Bereiche

### Code

- `app/gear.py`
- `app/rooms.py`
- `app/charbuild.py`
- `app/room/movement.py`
- `app/room/visibility.py`
- `app/room/dice.py`
- `app/static/js/80_prep.js`
- `app/static/js/30_room.js`

### Tests

- `tests/test_engine_gear_grants.py`

Die Suite prüft unter anderem:

1. Gear-Speed erreicht `movement._speeds()`.
2. Gear-Darkvision erreicht die tatsächliche Token-Sicht.
3. Gear-Hit-Dice-Bonus erreicht den Short Rest.
4. `hands:2` verhält sich in der bestehenden Zwei-Hände-/Off-Hand-Regel korrekt.
5. Background-Fertigkeiten werden angewandt.
6. Background-Feature/Languages erscheinen in Report und Apply.
7. Origin-Talent-Zauber erreichen den bestehenden Spell-State.
8. Optionale Expertise nutzt die vorhandene Skill-Achse und bricht bei einer
   nicht profizienten Fertigkeit fail-closed ab.
9. `classes.weapon_prof` und `classes.armor_prof` erscheinen im Build-Ledger.
10. Subclass-Features erscheinen in der Build-History.
11. Species-Provenienz erscheint im Build-Ledger.

### Dokumentation

- `DECISIONS.md`: neuer D115-Abschnitt.
- `TODO.md`: Nachtschicht-Arbeitspaket und Kanon-Ergebnis.
- `docs/FEATURE_MATRIX.md`: neue Kategorie 20 und aktualisierte Zeilen 3–5.
- `docs/FEATURE_COMPLETE_GAPS.md`: Lücken und realisierte Konsumenten.
- `docs/CSV_ONLY_READINESS.md`: geänderte Spalten-Konsumenten.
- Dieser Abschlussbericht.

## Verifikation

Ausgeführt:

```text
COMPOSE_PROFILES=test docker compose run --build --rm test
COMPOSE_PROFILES=test docker compose run --build --rm test pytest \
  tests/test_engine_gear_grants.py -q

COMPOSE_PROFILES=test docker compose run --build --rm test pytest \
  tests/test_speeds.py tests/test_movement_modes.py tests/test_weapons_gear.py \
  tests/test_integration.py tests/test_d111_effects.py tests/test_lighting2.py -q

python3 -m compileall -q app
find app/static/js -name '*.js' -print0 | xargs -0 -n1 node --check
```

Ergebnis: kanonisch **959 passed, 1 skipped, 0 failed**; Python-Syntax und
JavaScript-Syntax grün.

## Real-Browserabnahme

`scripts/e2e_build_wizard.py` und
`scripts/e2e_creature_projection.py` wurden in headless Chromium gegen
`http://127.0.0.1:8010` ausgeführt. Beide Ketten sind grün:
Registrierung → Raum → Content-Import → Build-Wizard/Expertise/Apply sowie
DM-Review der Monster-Projektion → Bestiarium-Import → persistierte Bite-Attacke.
Weitere UIs sind weiterhin manuell zu prüfen:

1. Charakterblatt mit Gear-Speed, Gear-Darkvision und Gear-Hit-Dice-Bonus.
2. Short-Rest-Dialog bei ausgerüstetem Bonus-Gegenstand.
3. Off-Hand-Block einer Waffe mit `hands:2`.
4. Origin-Report/Apply mit Background-Feature, Sprachen und Tools.
5. Build-History mit Subclass-Features und Feature-Voraussetzungen.
6. Species-Provenienz im Build-/Sheet-Bereich.

## Bewusste offene Grenzen

- `feats.requires` prüft seit D121 Attributswert-, Skill-Proficiency- und
  Feature-Voraussetzungen fail-closed; Weapon-/Tool-/Spellcasting-/Rank-Formen
  bleiben unsupported, bis eine eigene Mechanik existiert.
- Species-/Klassen-/Subclass-Texte werden nicht in Größen-, Footprint-,
  Bewegungs- oder Kampfmechanik übersetzt.
- `classes.spellcasting_ability` erscheint als Provenienz; pro-Zauber-`ability`
  bleibt die ausführungsmaßgebliche Achse. `spell_replace` und
  `upcast_scaling` haben weiterhin keinen vollständigen mechanischen Leser.
- Item-`duration` außerhalb einer `condition`-Operation hat keinen Konsumenten.
- Zauber-Dauerablauf und automatische Zeit-/Initiativ-Ablaufmaschinen sind
  weiterhin separat zu planen.

## Ergebnis der Nachtschicht

Die Nachtschicht hat dokumentierte Data-to-Engine-Lücken ohne neue
Regelmaschinen geschlossen. Der autonome Anschlusslauf hob den Kanon von 948
über 964 auf **981 passed, 0 skipped, 0 failed**; AP-006 bis AP-010 wurden
in echtem Chromium bestätigt, AP-011 bis AP-013 zusätzlich über echte
WebSocket-/REST-/Engine-Pfade.

Der Arbeitsstand ist automatisch stabilisiert, dokumentiert und kanonisch grün;
alle verbleibenden Grenzen sind bewusst dokumentiert statt stillschweigend
als „fertig“ ausgegeben.