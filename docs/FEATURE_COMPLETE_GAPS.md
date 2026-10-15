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
| `incapacitated`-Familie (blind/deaf/paralyzed/unconscious/stun) | Keys da, keine Wirkung | Adv/Dis-Hook (`dice.py:316-337`), Bewegungs-Hook | M | K |
| Exhaustion-Stufen (0–6 mit kumulativen Effekten) | Key existiert nicht als Mechanik | Condition-Uhr + Bogen-Anzeige | M | K |
| Tod/Incap-Flows: Tod-save-Flow existiert ✓ | (kein Gap) | — | — | — |
| Echte Loot-/Kistenobjekte mit Inhalt auf der Karte | „Loot“-Objekt schreibt nur Notiz-Text (`room/traps.py:86-91`) | Container-System D92 + loot-Handler D105 (eins zu eins übertragbar) | M | K |
| Monster-Sonderaktionen aus Daten (Blick, Konzent-Blick, Re-Aktion) | NPC nur struktur. Angriffe + Spruch-ID-Liste | Executor + `npc._clean_abilities` | L | K+G |

## B. Fehlende generische Regelunterstützung (die CSV-only-Blocker)

Ohne diese Punkte bleibt jeder neue Inhalt Code-Arbeit — mit ihnen wird er
CSV-Arbeit. Reihenfolge ist die einzige sinnvolle (Unterbau zuerst).

| Lücke | Detail | Gr. | Art |
|---|---|---|---|
| Effektgrammatik: Bewegungs-/Positionseffekte | Schub, Teleport, erzwungener Schritt — `moveforced`-Engine existiert schon, nur nicht als Effekttyp ansprechbar | M | G |
| Effektgrammatik: Probe/Wurf als Effekt | Rettung/Angriff innerhalb einer Effekt-Kette (nicht nur als Auflösung eines Zaubers) | M | G |
| Effektgrammatik: Ressourcen ändern (gewähren, nicht nur kosten) | `resource`-Feld kennt nur Kosten | S | G |
| Effektgrammatik: Dauer mit Rettungs-Ende | Bedingungs-Runden kennen nur feste `rounds`/`until`-Anker | M | G |
| Zustandskatalog als CSV (`conditions.csv`) | 18 Keys hartcodiert; Wirkung-Hooks bleiben Code pro KEY-TYP, Katalog+Anker+Hooks-Flags werden Daten | M | G |
| Item-Effektgrammatik | heute `heal`+charges; Ziel: dieselbe Effektgrammatik wie der Executor, ausgelöst bei use/equip/attack | L (baut auf G oben auf) | G |
| creatures.csv → NPC-Block-Projektion | Import heute bereits, Projektion fehlt komplett | M | G |
| Spezies → Bogen (Größe→Token-Footprint, Tempo, Sinne, Sprach-Traits) | Größen-Footprint-Engine ist fertig (NPC-Seite), nur nicht für PC gemappt | M | G |
| Dauer-Ablauf-Engine für Zauber-Effekte | Bedingungen ticken bereits (3 Uhren) — Konsument für spell `duration` | M | G |
| Ausrüstungs-Speed/`darkvision_ft` an die Pfade hängen | Ein `_speeds`-Pflegestück + Sicht-Hook | S | G |
| `feats.requires`, `feats.spells_grant`, Background-Fertigkeiten auf den Bogen, `classes.proficiencies` | jeweils ein klarer, kleiner Anwendungspunkt im Build-Rechner | je S–M | G |

## C. Reiner CSV-Inhalt (sobald A/B grünen — keine Engine-Arbeit mehr)

* Vollständiges SRD-5.2.1-Regelwerk als Pack (Waffen/ Rüstungen /
  Gegenstände / Zauber / Klassen / Spezies / Hintergrund-Feats),
* Monster-Bestiario als `creatures.csv` + Projektion,
* Abenteuermodule: Karten (PNG-Assets + Editor), Fallen/Türen/Truhen,
  Quests, Audio, Begegnungen — alles bereits engine-seitig fertig,
* Kurzwährungs-/Werttabellen (`value_gp`-Spalte mit Konsument ergänzen — s. B).

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
6. **S45+ — CSV-Produktion (C) & Betrieb (O):** SRD-Packs, Bestiarium,
   Abenteuer, Deploy-Härtung.

Größenklassen: S ≤ halber Tag, M ≈ 1 Sprint-Tag, L ≈ 2 Sprint-Tage.
Realistisch sind S40–S44 als **Feature-Complete-Sprintblock** (eine
Engine, ein Kanon-Lauf pro Sprint, wie seit Sprint 1 etabliert).
