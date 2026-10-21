# Feature-Complete-Gaps — die ehrliche Restarbeit (D110, Stand Sprint 39; S40 umgesetzt D111, S41 umgesetzt D112 Stand Sprint 41)

## Strategische Einordnung (verbindlich, D110)

DnDTable hat **keinen „Back Backlog“** — diese Regel stammte aus einem
anderen Projekt und ist hier ausdrücklich aufgehoben. Zielsetzung ist:

1. **schnellstmöglich alle gewollten Spielfunktionen und DM-Werkzeuge
   fertigzubauen**, damit die Engine funktional fertig ist;
2. Erweiterbarkeit primär über CSV-Inhalte und Server-Betrieb läuft
   (`docs/CSV_ONLY_READINESS.md`);
3. danach im laufenden Betrieb CONTENT (CSVs), nicht CODE, produziert wird.

Die „bewusst nicht gebaut“-Sektion in `TODO.md` (Zeile ~812) war ein
Timebox-Artefakt der Sprint-Serie. Sie wird mit D110 als **Restarbeit**
umgewidmet: was dort steht, ist weiterhin gewollt — es wurde nur
zurückgestellt, nicht verworfen. Diese Datei ist die verbindliche,
vollständige Planung darüber.

Klassifikation je Lücke:
**K** = Kern-Spielfunktion · **G** = generische Regelunterstützung
(Ausdruckskraft der CSV/Executor-Schicht) · **C** = reiner CSV-Inhalt
(sobald G erledigt ist) · **O** = Betrieb/Infrastruktur.

## A. Kernfunktionen ohne Mechanik (gewollt, nicht gebaut)

| Lücke | Stand heute | Vorhandene Vorarbeit | Gr. | Art |
|---|---|---|---|---|
| Taschendiebstahl / Hehlerei (versteckte Probe, Gegeneinanderprobe, Beutezugriff) | **D112 umgesetzt** — `app/room/pickpocket.py`, beide 2024-Modelle (DM-vermittelt + `pick`-Teilmenge), atomarer Beutezugriff mit Flucherhalt | Skill-Engine, Whisper-Verborgenheit, D94-„kein Probe“-Modell, Loot-Menge adjacency | M | K |
| Automatische Fluchwirkungen (Auslöser beim Anlegen/Benutzen/Identifizieren) | Flüche = Metadaten + DM-Enthüllung (D106) | Fluch-Infra komplett; `_item_attack`/use/equip-Hooks vorhanden | M–L | K+G |
| Konzentraitions-BRUCH bei Schaden | Concentration-FLAG + Con-Mod auf Rettungen | Rettungspfad `handle_save`, FLAG existiert (`conditions.py:229`) | S–M | K |
| Grapple / Shove als Offensive (Atletik vs. Athletik/AC, Größe, Bewegung fest) | **D112 umgesetzt** — `app/room/grapple.py`, 2024-Baseline (check→save `better_save`, kein 2014-Wettkampf), `dc` additiv, Ende über `end_grapples_out_of_reach` | Condition-Uhren, Bewegungs­verbot-Set, Opposed braucht nur 2 Würfe | M | K+G |
| Inspiration (F6) | ✅ D135: Verbrauch am Wurf, Weitergabe bei voll | — | S | K |
| Stabilize-Help (F8) | ✅ D136: DC-10-Medicine-Check, Action+Adjazenz, nat 20 heilt | — | S | K |
| Deckung auf Spell-Attacks (A5) | ✅ D137: half/3/4/total auf allen Angriffspfaden, Total vor Ressourcenverbrauch | — | S | K |
| Prepare-Ablauf (C3) | ✅ D138: prep/prepared-Datenfeld, Gate vor Verbrauch, Kantrips frei | — | S | K |
| Swim/Climb ohne Speed (D83-Platzhalter) | ✅ D140+D144: Aufschlag +1/+2 nur OHNE passenden Speed (strained-Flag creature-kundig gesetzt), fly bleibt Speed-Pflicht | — | S | K |
| `incapacitated`-Familie (blind/deaf/paralyzed/unconscious/stun) | ✅ D134: Hook `no_actions` — Angriff, Wirken, Flucht/Grapple-Choke, Dash validieren vor Konsumtion; Eltern-Condition lässt Bewegung frei, Auto-Fail nur bei der Familie; Reaktionen bleiben dokumentierte v1-Grenze | Adv/Dis-Hook (`dice.py:316-337`), Bewegungs-Hook | S | K |
| Exhaustion-Stufen (0–6 mit kumulativen Effekten) | ✅ D129: `gear.exhaustion_roll_mod`/`exhaustion_speed_penalty_ft` als einzige Quelle; Angriffe, Schaden, Checks, Saves, Skills, Sprüche, Initiative, walk-Tempo, Tod bei 6, Long Rest −1 — 16-h-Gate bewusst offen | Condition-Uhr + Bogen-Anzeige | S | K |
| Tod/Incap-Flows: Tod-save-Flow existiert ✓ | (kein Gap) | — | — | — |
| Echte Loot-/Kistenobjekte mit Inhalt auf der Karte | ✅ D133: Loot-Eintrag mit `container`-Flag ist ein echter D92-Container unter dem Schlüssel `loot:<id>` (Inhalt nur über autorisierte `inv_container`-Antworten; Editor-Checkbox + Klick-Öffnung; ohne Flag bleibt die Legacy-Notiz byte-identisch) | Container-System D92 + loot-Handler D105 | S | K |
| Monster-Sonderaktionen aus Daten (Blick, Konzent-Blick, Re-Aktion) | NPC nur struktur. Angriffe + Spruch-ID-Liste | Executor + `npc._clean_abilities` | L | K+G |

## B. Fehlende generische Regelunterstützung (die CSV-only-Blocker)

Ohne diese Punkte bleibt jeder neue Inhalt Code-Arbeit — mit ihnen wird er
CSV-Arbeit. Reihenfolge ist die einzige sinnvolle (Unterbau zuerst).

| Lücke | Detail | Gr. | Art |
|---|---|---|---|
| Effektgrammatik: Bewegungs-/Positionseffekte | Schub, Teleport, erzwungener Schritt — `moveforced`-Engine existiert schon, nur nicht als Effekttyp ansprechbar | M | G |
| Effektgrammatik: Probe/Wurf als Effekt | Rettung/Angriff innerhalb einer Effekt-Kette (nicht nur als Auflösung eines Zaubers) | M | G |
| Effektgrammatik: Ressourcen ändern (gewähren, nicht nur kosten) | ✅ D125: `resource.mode=restore` gibt eine vorhandene Charakter-Ressource um 1 Nutzung zurück; `cost` bleibt Standard alter Zellen und der atomare Preflight bezahlt nur Kosten. Eine völlig neue Ressource erzeugen bleibt bewusst nicht Aufgabe eines Effekts | S | G |
| Effektgrammatik: Dauer mit Rettungs-Ende | ✅ D130: `sa`+`dc` auf der Instanz; `combat._save_ends` würfelt am Ende des eigenen Zugs durch `opposed.save_roll`/`beats_dc` (PC und NPC über denselben Participant), Erfolg entfernt genau den Eintrag; `duration`-Quelle bleibt D117 | S | G |
| Zustandskatalog als CSV (`conditions.csv`) | 18 Keys hartcodiert; Wirkung-Hooks bleiben Code pro KEY-TYP, Katalog+Anker+Hooks-Flags werden Daten | M | G |
| Item-Effektgrammatik | heute `heal`+charges; Ziel: dieselbe Effektgrammatik wie der Executor, ausgelöst bei use/equip/attack | L (baut auf G oben auf) | G |
| creatures.csv → NPC-Block-Projektion | ✅ D122: projection to the one existing `npc.clean_npc()` shape, DM preview/import into the personal bestiary, and real-Chromium click-through; unsupported free-form text stays visible instead of being silently faked | M | G |
| Spezies → Bogen (Größe→Token-Footprint, Tempo, Sinne, Sprach-Traits) | ✅ D126: size/speed/modes/darkvision drive the existing sheet→movement/LOS/footprint paths; languages/traits remain provenance/display and deliberately have no new adjudication engine | M | G |
| Dauer-Ablauf-Engine für Zauber-Effekte | ⚠ D117: spell/item `duration` now seeds condition rounds through the existing combat clock; non-combat wall-clock expiry remains intentionally absent | M | G |
| Ausrüstungs-Speed/`darkvision_ft` an die Pfade hängen | ✅ Nachtschicht 2026-10-16: `movement._speeds` and darkvision LOS read `gear.effective_gear`; equipment feet are converted to LOS cells at 5 ft/cell | S | G |
| `feats.spells_grant`, Background-Fertigkeiten auf den Bogen | ✅ Nachtschicht 2026-10-16: origin/background skills and feat spell grants flow through the existing build chronology | je S | G |
| Background-Tools/-Sprachen/-Feature, `classes.weapon_prof/armor_prof`, Subclass-Features, Spezies-Daten | ⚠ Nachtschicht 2026-10-16: now ledger/sheet provenance and display where possible; still no separate adjudication engine (correct by design) | M | G |
| `feats.requires` | ✅ D121: ability-score, skill-proficiency and prior-feat prerequisites are parsed and server-enforced; unknown forms fail closed. Weapon/tool/spellcasting/rank prerequisites remain intentionally unsupported until a real mechanic exists | S | G |
| `classes.spellcasting_ability` in Build/UI | ✅ D118: plan/apply/build-ledger carry the class casting ability and prep/room UI display it; per-spell ability execution intentionally remains the single authoritative path | S | G |
| `classes.expertise` guided UI | ✅ D119: plan/apply expose level, count and candidate skills; prep wizard renders checkboxes; server requires exact, unique, proficient choices through the existing skill axis | S | G |

## C. Reiner CSV-Inhalt (sobald A/B grünen — keine Engine-Arbeit mehr)

* Vollständiges SRD-5.2.1-Regelwerk als Pack (Waffen/ Rüstungen /
  Gegenstände / Zauber / Klassen / Spezies / Hintergrund-Feats),
* Monster-Bestiario als `creatures.csv` + Projektion,
* Abenteuermodule: Karten (PNG-Assets + Editor), Fallen/Türen/Truhen,
  Quests, Audio, Begegnungen — alles bereits engine-seitig fertig,
* Kurzwährungs-/Werttabellen: `value_gp` hat seit D132 seinen Konsumenten (`item_defs.value` → Inventar-Eintrag, Clamps 0–999999); inhaltsseitige Werttabellen bleiben Pflegeaufgabe des SRD-Packs.

## D. Server-Betrieb / Integration (O)

* Docker-Deploy-Profil + Backup-/Restore-Übung (TODO bestehend),
* Multi-Raum-/Account-Tests unter Last,
* Browserabnahme (Samstag, siehe `docs/SATURDAY_ACCEPTANCE.md`),
* Fehler-Benachrichtigung (SMTP/Health) — Infrastruktur, kein Feature.

## E. Bewusst NICHT Teil des Feature-Complete-Ziels (Engine-Grenzen, dokumentiert)

* Diorama als eigene Regelwelt (bewusst Projektion, D48),
* Sturzschaden und höhenbedingte Deckung/Vorteile bleiben bewusst NICHT gebaut
  (`room/conditions.py:98`) — reine Kampf-Mechanik, keine Geometrie.
* KEIN Ausschluss mehr (historischer Vermerk): Vertikale TOKEN-GEOMETRIE war
  früher hier als Engine-Grenze geführt — seit D114 (Sprint 43) ist sie
  ausdrücklich TEIL des Feature-Complete-Ziels und Phase 0–8 sind umgesetzt:
  Token-Volumen (`height_ft`/`elevation_ft`), `openv`-Öffnungen,
  Körperpräsenz mehrerer Ebenen, etagenübergreifende Sicht sowie
  Angriff-/Interaktionsreichweite mit Fail-closed ohne Öffnung. Zusätzlich
  sind vertikaler Flug inkl. horizontaler Annäherung, kanonische
  Budgetabrechnung, Ganzzervolumen-Kollision, Sheet-Felder, `openv`-Editorpinsel
  und Canvas-Integration realisiert.
  **Bewusst offen bleiben:** diagonale + vertikale Kombination, Springen/Fallen,
  vertikales Klettern/Schwimmen, interaktive 3D-Pfadvorschau und automatische
  Terrain-Erkennung. Sturzschaden/höhenbedingte Deckung bleiben wie oben
  bewusst außerhalb. Kanonische Skala seit D113 P7 (1 Höhen-Einheit =
  1 Stockwerk = 10 ft, `app/vertical.py`).
  Details/Status: `docs/VERTICAL_GEOMETRY.md`.
* Auto-Weltwachstum (Flag OFF, D77),
* 3D-Ansichten/Streaming, Echtzeit-Arena-Modus.
  Diese Grenzen sind Designentscheidungen, keine offenen Baustellen.

## Empfohlene Sprint-Reihenfolge (Realisierungsplan)

Die Kette ist so geschnitten, dass jeder Sprint die Basis des nächsten ist
und jeweils eine geschlossene Nutzer-Erzählung liefert:

1. **S40 — Generische Grundlage (B, Grundgerüst):** Effektgrammatik
   (Bewegung/Probe/Ressource/Dauer-mit-Rettung) + Zustandskatalog als CSV
   mit Hook-Flags + `conditions.csv`-Schema.
   Ergebnis: neue Zustände/Effekte ohne neuen Kampf-Code.
   **UMGESETZT (D111, Sprint 40)** — `app/effectops.py` + `conditions.csv`;
   Dauer-mit-**Rettungs**-Ende als Save-Wurf bewusst nach S42 verschoben
   (`break_concentration`-Op + on_damaged-Seam sind bereits da).
 2. **S41 — Opposed & Diebeswerkzeug (A):** Gegeneinanderprobe als
    Engine-Baustein → Taschendiebstahl/Hehlerei, Shove/Grapple darauf
    aufsetzend, Beutezugriff an Inventar koppeln.
    **UMGESETZT (D112, Sprint 41)** — `app/room/opposed.py` (drei Formen,
    nur Komposition über dem bestehenden Würfelkanal, Tie per Default
    `defender`, `dm`→`Tie`-Delegation) + `app/room/grapple.py`
    (2024-Grapple/Shove/Escape, check→save `better_save`, `dc` additiv am
    `grappled`-Cond, Reichweite/Größe über bestehende Geometrie/`npc.SIZES`,
    `end_grapples_out_of_reach` an den drei Bewegungs-Enden) +
    `app/room/pickpocket.py` (beide 2024-Modelle, `pick`-Whitelist als einzige
    stehlbare Teilmenge, atomarer Transfer mit Flucherhalt, `notice_dc`
    ODER echter Wahrnehmungs-Wurf — 2024 ohne passive Wahrnehmung).
    Kontesto-Op in der Effektgrammatik (CSV-autorisierte Probe) bewusst nach
    S42 verschoben; Schnittstelle in `docs/EFFECT_GRAMMAR.md` dokumentiert.
3. **S42 — Automatische Magie-Flüsse (A+G):** Fluch-Auslöser,
   Item-Effektgrammatik, Konzentraitions-BRUCH, Dauer-Ablauf-Konsument.
4. **S43 — Kampf-R-P1 (A):** `incapacitated`-Wirkungen, Exhaustion,
   Blind/Poison-Hooks, Monster-Sonderaktionen aus NPC-Block (B-Vorstufe).
5. **S44 — Datenprojektion (B):** creatures.csv→NPC, Spezies→Bogen,
   Feat-/Background-Lücken schließen, Ausrüstungs-Speed/Darkvision.
   **Teile umgesetzt (Nachtschicht 2026-10-16):** Ausrüstungs-Speed/Darkvision,
   Background-Fertigkeiten/Tools/Sprachen/Feature, `feats.spells_grant`,
   Klassen-/Subclass-/Spezies-Provenienz. `feats.requires` sowie mechanische
   Adjudikation der Klassen-/Spezieswerte bleiben offen.
6. **S45+ — CSV-Produktion (C) & Betrieb (O):** SRD-Packs, Bestiarium,
   Abenteuer, Deploy-Härtung.

Größenklassen: S ≤ halber Tag, M ≈ 1 Sprint-Tag, L ≈ 2 Sprint-Tage.
Realistisch sind S40–S44 als **Feature-Complete-Sprintblock** (eine
Engine, ein Kanon-Lauf pro Sprint, wie seit Sprint 1 etabliert).
