# Regelkompatibilitäts-Audit — D&D 5e (2024, SRD 5.2.1) vs. Bestand (D107/D108)

**Status:** Das D107-Audit wurde in **D108 korrigiert** (Korrektur-Log §1). Es
wurden **keine** Regeln über den Charakterursprung hinaus implementiert; die
Ursprungs-Schicht (Background-ASI + Origin Feat) ist seit D108 **implemented**
(§4). Verbindliche Regelbasis ist **D&D 5e (2024)** in der offiziell unter
**CC BY 4.0** lizenzierten Fassung **SRD 5.2.1** (Quelle und Attribution:
`ATTRIBUTION.md`). Abweichungen der Engine sind dokumentierte Abstände mit
R-Nummern — kein stiller Drift.

---

## 1. Korrektur-Log D108 (D107-Aussagen, die sich als falsch erwiesen)

Methodik: jede Regel-Aussage jetzt gegen das **offizielle SRD-5.2.1-PDF**
(`SRD_CC_v5.2.1.pdf`, veröffentlicht 01.05.2025) und die offiziellen 2024
Basic Rules (Rules Glossary) geprüft. Der Kernfehler von D107: Annahmen aus
Playtest-/Hypothese-Material statt Primärquelle.

| # | D107 behauptete | SRD-5.2.1-Wirklichkeit (wörtlich belegt) | Folge |
|---|---|---|---|
| K1 | „2024 führt Proficiency Dice d4–d12 ein" (war R-P0.1) | fester Proficiency Bonus, „based on your total character level, not your level in a particular class" (Character Advancement) | **gestrichen** — Engine (`gear.py:699`) ist **2024-konform** |
| K2 | „Concentration-DC 2024: 11 + halber Schaden" | „The DC equals **10 or half the damage taken (round down), whichever number is higher**, up to a maximum DC of 30." (Rules Glossary, Concentration) | Formel berichtigt; Automatisierung bleibt Lücke (R-P1) |
| K3 | „Origin Feats kommen von der Species" | „**A background gives your character a specified Origin feat**" (Character Backgrounds). Species-Traits wie Human „Versatile. You gain an Origin feat of your choice" sind **separate** Boni | berichtigt; D108 implementiert genau die Background-Regel |
| K4 | „2024er Feats erhöhen keine Attributswerte" | Kategorien: „Origin, General, Fighting Style, or Epic Boon"; General-Feats dürfen: „Increase your Strength or Dexterity score by 1, to a maximum of 20" (Grappler); ASI selbst ist ein General Feat (Level 4+) | berichtigt; `ability_boost`-Spalte bleibt legitim, Kategorie-Spalte ergänzt |
| K5 | „2024 ersetzt Death Saves durch Dying 0–4" | Death Saving Throws existieren weiter: 10+ = Erfolg, „On your third success, you become **Stable**… On your third failure, you die", Nat1 = zwei Fehlschläge, Nat20 = 1 HP, Schaden bei 0 = ein Fehlschlag (Crit = zwei), Max-HP-Schaden = Tod. **Keine** Dying-Bedingung in der Conditions-Liste | Hausregel H1 entfällt: die bestehende Death-Save-Pipeline ist **2024-konform** |
| K6 | „Short Rest 2024: automatisch halbe Hit Dice" | „You can **spend** one or more of your Hit Point Dice… You can decide to spend an additional Hit Point Die after each roll." (Short Rest); Long Rest: „You regain all lost Hit Points and **all spent** Hit Point Dice." | Engine (freiwilliger HD-Verzehr) ist **2024-konform**; R-P1.2 gestrichen |
| K7 | „loading→slow"; Mastery-Mix | Weapon **Properties** 2024 (SRD): Ammunition, Finesse, Heavy, Light, **Loading**, Range, Reach, Thrown, Two-Handed, Versatile. **Mastery Properties** (eigene Liste, nur mit Weapon-Mastery-Feature): **Cleave, Graze, Nick, Push, Sap, Slow, Topple, Vex** | sauber getrennt dokumentiert (§2 E1); Mastery bleibt Backlog |
| K8 | Conditions „+Dying/+Encumbered"; Exhaustion bis 10; Passive Perception fehle; Cover +10; „Grapple in keiner Fassung" | Conditions-Liste 2024 = 15, inkl. neuer eigener Condition **Incapacitated**, ohne Dying/Encumbered. Exhaustion: „You die if your Exhaustion level is **6**", −2/−5 ft je Level. **Passive Perception ist 2024 ersatzlos entfallen** (Glossar führt keine veralteten Begriffe). Cover: Half +2 / Three-Quarter +5 / Total (kein +10). Grapple-Regeln existieren in SRD 5.2.1 (Grappling-Entry) | §2 F-Zeilen berichtigt; neue R-P2: Engine-Conditionliste um `incapacitated` ergänzen |
| K9 | Cantrip-Skalung „5/11/17 nach Charakterstufe ✓" | bestätigt, jetzt zitiert: „Cantrip Upgrade. The damage increases by 1d10 when you reach levels 5 (2d10), 11 (3d10), and 17 (4d10)." (Fire Bolt); Skala folgt der Charakterstufe | bleibt ✓ (Beleg ergänzt) |

---

## 2. Matrix — Engine-Bestand vs. SRD 5.2.1

Legende: `[2024]` konform · `[HR]` dokumentierte bewusste Abweichung ·
`[Anz.]` Anzeige/Counter ohne Mechanik · `[lück]` in der Engine nicht umgesetzt ·
Prioritäten: **R-P0** Regel-Identität, **R-P1** spürbare Lücke, **R-P2** Komfort.

### A · Ableitungen & Würfel

| # | Befund (Beleg) | SRD 5.2.1 | Einstufung | Prio |
|---|---|---|---|---|
| A1 | Proficiency `2+(L-1)//4` nach Gesamtstufe — `gear.py:699` | feste Tabelle, Gesamtcharakterstufe | `[2024]` ✓ | — |
| A2 | Expertise additiv — `gear.py:591–616` | „your Proficiency Bonus is **doubled**" | `[2024]` ✓ (Fixwert ×2) | — |
| A3 | Finesse-Wahl — `gear.py:357` | identische Regel | `[2024]` ✓ | — |
| A4 | Krit = Würfel verdoppeln — `room/dice.py:127` | „Roll all of the attack's damage dice twice" | `[2024]` ✓ | — |
| A5 | Cover manuell +2/+5/total — `room/dice.py:408` | Half +2, Three-Quarter +5, Total (nicht anvisierbar) | `[2024]` ✓ (3/4-Deckung fehlt als Auswahl) | R-P2 |
| A6 | Advantage/Disadvantage nur manuell; Conditions sind Meta | Bedingungen 2024 erzwingen Modi automatisch | `[HR]` (DM-Hoheit, bewusst) | R-P2 |
| A7 | Passive Perception nirgends | **in 2024 entfallen** — Nichtvorhandensein ist konform | `[2024]` ✓ | — |
| A8 | AC ungerüstet = manueller Sheet-Wert `ac` — `gear.py:472` | Basis-AC-Berechnung „10 plus your Dexterity modifier" | `[HR]` (nichts wird abgeleitet; Sheet bleibt Autorität) | R-P2 |
| A9 | Traglast STR×15 — `gear.py:948` | Small/Medium Carry STR×15; bei Überschreitung Speed 5 ft (Encumbered existiert nicht als Condition) | `[2024]` ✓ (Speed-Strafe nicht automatisiert) | R-P2 |
| A10 | Attunement-Kap 3 — `gear.py:10` | „no more than three magic items" | `[2024]` ✓ | — |

### B · Species / Background / ASI / Feats

| # | Befund (Beleg) | SRD 5.2.1 | Einstufung | Prio |
|---|---|---|---|---|
| B1 | Species-`ability_bonuses` nur Daten, nie automatisch angewandt | Species erhöhen keine Werte mehr | `[2024]` ✓ (Spalte ist Alt-Pack-Bookkeeping) | — |
| B2 | **Background-ASI + Origin Feat: serverseitig implementiert** — `charbuild.apply_origin`, Spalten `backgrounds.asi_abilities/origin_feat`, `feats.category` | „Increase one by 2 and another one by 1, or increase all three by 1. None of these increases can raise a score above 20." + „A background gives your character a specified Origin feat." | **`[2024]` ✓ (D108)** | — |
| B3 | ASI-Kadenz je Klassenlevel-Zeile datengetrieben (`classes.csv`, `charbuild`) | ASI ist Level-4+-Feat (General, repeatable) — Kadenz je Klasse | Schema `[2024]` ✓ | — |
| B4 | `feats.category` registriert (origin/general/fighting_style/epic_boon); `ability_boost` bleibt erlaubt | Kategorien ✓; General-Feats dürfen Werte bis max 20 erhöhen | Schema `[2024]` ✓ | — |
| B5 | Origin-Feat-Wahl-Ablauf (eigenes Feat statt Background-Feat) fehlt; Human-Bonus-Feat (`Versatile`) nicht abbildbar | Species-Traits können zusätzliche Origin Feats gewähren | `[lück]` | R-P1 |
| B6 | Requires-Freitext („5 ranks") | Prerequisites sind Attributs-Mindestwerte | `[HR]`/`[Anz.]` | R-P2 |

### C · Klassen & Zauberlisten

| # | Befund | SRD 5.2.1 | Einstufung |
|---|---|---|---|
| C1 | Cantrip-Skalung 5/11/17 nach Charakterstufe (`abilities.py`, `scale_tiers`) | „Cantrip Upgrade … levels 5/11/17" | `[2024]` ✓ |
| C2 | Slot-/Known-/Resource-Zahlen reine Klassendaten | gleiche Tabellenform | `[2024]`-tauglich |
| C3 | Prepare nur Flag, kein Ablauf | Prepare-Regeln je Klasse | `[Anz.]` | R-P2 |
| C4 | Mehrklasse über kumulierte Caster-Level (Ledger D96) | Multiclass-Tabellen | `[2024]`-tauglich |

### D · Zaubermechanik

| # | Befund | SRD 5.2.1 | Einstufung | Prio |
|---|---|---|---|---|
| D1 | Konzentration als Flag/Zustand, kein Save bei Schaden | CON-Save, DC = max(10, halber Schaden ↓), Cap 30 | `[lück]` | **R-P1** |
| D2 | attack/save/half-Auflösung, Upcast, Areas | Grundmodell gleich | `[2024]` ✓ | — |

### E · Waffen & Ausrüstung

| # | Befund (Beleg) | SRD 5.2.1 | Einstufung | Prio |
|---|---|---|---|---|
| E1 | Property-Untermenge (`finesse/two_handed/versatile/reach/…`) — `gear.py:44,331–378` | Properties: Ammunition, Finesse, Heavy, Light, Loading, Range, Reach, Thrown, Two-Handed, Versatile; **davon getrennt** Masteries (nur mit Weapon-Mastery-Feature): Cleave, Graze, Nick, Push, Sap, Slow, Topple, Vex | Properties teilweise `[2024]`; **Masteries komplett `[lück]`** (Daten + Engine) | **R-P0** |
| E2 | Nebenhand-Angriff (Light-Bonusaktion) kein Serverablauf | Light-Property erlaubt Bonusangriff (s. Property-Text) | `[lück]` | R-P1 |
| E3 | Bonus-/Extra-Schadenwürfel Items | Items tragen Boni | `[2024]` ✓ | — |
| E4 | Attunement/charges/recharge (`items.csv`) | gleiches Grundmodell; Gate D105 | `[HR]` Gate bewusst | — |

### F · Zustände, Tod, Ruhe

| # | Befund (Beleg) | SRD 5.2.1 | Einstufung | Prio |
|---|---|---|---|---|
| F1 | Death-Save-Pipeline: 10+, 3✓ Stable/3✗ tot, Nat1 zwei ✗, Nat20 1 HP, Schaden bei 0 = ✗ (Crit zwei ✗, Max-Schaden tot) — `room/death.py` | **wortgleich** (Death Saving Throws) | `[2024]` ✓ — war in D107 fälschlich Hausregel | — |
| F2 | Short Rest: HD freiwillig, cap halbes Level? — `room/dice.py:767` (D35) | „spend one or more … additional Hit Point Die after each roll" **ohne Obergrenze** | `[2014]` falls Cap greift, sonst ✓ | R-P2 |
| F3 | Long Rest: HP/Slots/HD-Reset; optional Conditions-Reset | „regain all lost HP and all spent HD"; Exhaustion −1; 16-h-Gate; Interruptions | ✓ Kern; Exhaustion-Kopplung + 16-h-Gate fehlen | R-P2 |
| F4 | Exhaustion 0–6 Counter, keine Stufeneffekte — `status.py:71` | Stufeneffekte: −2/−5ft je Level, Tod bei 6 | `[Anz.]` | R-P2 |
| F5 | 15 Zustände + `concentrating`; **`incapacitated` fehlt** — `conditions.py:20` | 15 Conditions inkl. eigenem **Incapacitated** | `[2014]`-Liste | R-P2 |
| F6 | Inspiration Boolean — `status.py:45` | Heroic Inspiration: verbraubarer Reroll; Doppelgewinn → weitergeben | `[Anz.]` | R-P2 |
| F7 | kein Grapple-Contest | Grappling-Regeln vorhanden (SRD) | `[lück]` | R-P2 |
| F8 | Help zum Stabilisieren (DC 10 Medicine) nicht automatisiert | existiert als Standard-Regel | `[lück]` | R-P2 |

---

## 3. CSV-Schema-Eignung (Stand nach D108)

D108 hat **registriert und implementiert** (additiv, alte Packs bleiben lesbar):

* `backgrounds.asi_abilities` — genau drei Ability-Kürzel; fehlt das Feld,
  verweigert der Origin-Flow sichtbar („not a 2024 background") — alte 2014er
  Zeilen gelten **nicht** stillschweigend als 2024-konform.
* `backgrounds.origin_feat` — Feat-ID; muss im Raum existieren und
  `category=origin` tragen.
* `feats.category` — `origin|general|fighting_style|epic_boon`; leer ⇒ wie
  `general` geführt; **nur explizit `origin`** qualifiziert fürs Background-Feat.
* `ability_boost` bleibt erlaubt — 2024-General-Feats dürfen Werte bis max. 20
  erhöhen (SRD-Beleg K4); für Origin-Feats sieht das SRD keine Wertboni vor.

Unverändert offene Feld-Ideen (nur dokumentiert): `items.mastery` (E1),
Species-Bonus-Feat-Modell (B5). Header bleiben stabil; neue Spalten nur
registriert via `content.SCHEMAS`.

## 4. Was D108 implementiert hat (Ursprung-Schicht)

* Server-Operation `apply_origin` (in `app/charbuild.py`, **keine** zweite
  Engine): validiert Background + Feat-Kategorie gegen den **Raum-Content**,
  akzeptiert aus dem Client ausschließlich die Verteilung (`plus2_plus1` mit
  verschiedenen Zielen oder `three`), prüft die 20-Obergrenze ablehnend (kein
  Clamp), und zeichnet den Grant als Ledger-Eintrag `characters.build.origin`
  auf — der sichere Herkunftsnachweis ohne Rückrechnung aus Attributswerten.
* Der Grant wird im **selben Voll-Recompute** wie die Klassenchronologie
  an dessen Anfang replayt (D96-Mechanik): Replays/Doppelklicks/Paralleles
  Posten wenden ihn genau einmal an; spätere Build-Schritte können ihn weder
  duplizieren noch löschen. HP/AC/Slots/Ressourcen bleiben unberührt;
  Startausrüstung wird nie über diesen Pfad vergeben (inv-Claims bleiben D94).
* REST: `GET/POST /api/build/{code}/{cid}/origin` (Authz spiegelt die
  Build-API: Owner oder DM des zugewiesenen Charakters).
* UI: „🧬 2024 Origin"-Karte in der Raumvorbereitung (Report → Vorschau →
  Apply); der Server bleibt Autorität, UI-Checks sind Bedienungshilfen.

## 5. Priorisierte Restliste

**R-P0:** Weapon Mastery als Datenfeld + Engine-Auswertung (E1); ASI-Feat-Inhalt
der Level-Up-Ebene (ASI-Feat-Splits nach SRD) — Kadenz selbst ist bereits
datengetrieben ✓.
**R-P1:** Concentration-Save (DC max(10, halber Schaden), Cap 30) (D1); Light-
Bonusangriff (E2); Origin-Feat-Wahlablauf + Species-Bonus-Feats (B5).
**R-P2:** `incapacitated`-Condition (F5); Exhaustion-Effekte (F4); Short-Rest-
HD-Cap prüfen (F2); Long-Rest 16-h-Gate/Exhaustion (F3); 3/4-Cover (A5);
Grapple (F7); Stabilize-Help (F8); Inspiration-Punkte-Semantik (F6); Prepare-
Ablauf (C3); Requires-Terminologie (B6); Auto-Modi-Diskussion (A6, bewusst HR).

## 6. Lizenzstand (R-L0 — gelöst)

SRD **5.2.1** ist offiziell unter **CC BY 4.0** veröffentlicht (EN/DE/…;
Quelle + Pflicht-Attribution: `ATTRIBUTION.md`). Beide SRDs (5.1 und 5.2.1)
bleiben nutzbar. DnDTable übernimmt daraus nur funktional eigene Mechanik und
**projekt-eigene** Demo-Namen; die Demo-Packs bleiben house-rule-markiert.
„5E compatible"-Zusatz bleibt erlaubt, nicht Pflicht (ATTRIBUTION.md).

## 7. Grenzen dieses Sprints

Keine Weapon-Masteries, keine vollständigen 2024er Klassen-/Feat-/Spell-Packs,
keine Automatisierung der R-P1-Mechaniken, keine retroaktive Migration
bestehender Charaktere (Ursprung wird nie automatisch gesetzt). Kein Git-Zugriff,
keine Änderungen an `55_diorama.js`. Kanonischer Stand: `TODO.md` Sprint-37.
