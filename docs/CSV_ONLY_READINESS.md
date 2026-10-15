# CSV-Only-Readiness — was die Engine heute rein datengetrieben kann (D110)

Stand Sprint 41 (D112; vorher D111/Sprint 40). Frage dieses Dokuments: **Können neue Inhalte (Regeln,
Gegenstände, Monster, Zustände) künftig NUR als CSV geliefert werden, ohne
Engine-Code?** Bewertung je Datenfläche mit Code-Beleg — nicht nach Spalten,
sondern danach, ob die Spalte eine **Mechanik** auslöst.

Kurzantwort: **Spalte ≠ Mechanik** — aber seit D111 gibt es eine echte
Mechanik-Schicht für Effekte und Zustände: `app/effectops.py` (versionierte,
validierte Op-Ketten, ausgeführt von den bestehenden Engines; Referenz:
`docs/EFFECT_GRAMMAR.md`) und `conditions.csv` (Zustandskatalog als Daten).
Import, Validierung und Isolation sind erledigt (D101–D108); die Mechanik-
Schicht ist für Kampf/Ausrüstung/Zauber/Effekte/Zustände datengetrieben, für
Spezies/Monster-Zusammenwirkungen aber weiter Code. Was hier als „Blocker" steht, ist Restarbeit im
Sinn der Feature-Complete-Planung (`docs/FEATURE_COMPLETE_GAPS.md`), kein
optionaler Wunschzettel.

## Lesart

- **Ja** — CSV-Zelle steuert direkt das Verhalten (Executor/Regel-Pfad).
- **Teilweise** — Daten landen im System, aber ein Teilschritt braucht Code.
- **Nein** — die Fläche ist reine Buchführung oder existiert nicht als CSV.

## Bewertungs-Matrix

| Datenfläche | Ja (Mechanik aus CSV) | Teilweise | Nein (heute Code nötig) |
|---|---|---|---|
| `items.csv` | Waffe: Treffer/Schaden/Finesse/Distanzstufen/Versatile-Griff/Extra-Würfel (`gear.weapon_profiles` → `room/dice.py`), AC, Attunement-Gate, heil-Würfel+Ladungen+Recharge, Attributs-/Fertigkeits-/Rettungs-Grant, Traglast, Munition, Mastery-Berechtigung, Fluch-Metadaten (D106), Kurzwährungsgewicht, `effects`+`trigger` (D111: use/equip/unequip/on_hit/on_damaged → Op-Kette durch `app/effectops.py`, replay-geschützt) | `speed_bonus_ft`/`darkvision_ft`: nur Bogen-Anzeige — Bewegungs-/Sichtpfad lesen sie nicht (`room/movement.py:72-73`, `room/visibility.py:66`); `heal`+charges (D95) und `effects` (D111) sind zwei getrennte Pfade | `hands`, `hit_dice_bonus`, `duration` ohne Konsumenten |
| `classes.csv` | HP-Würfel/Basis/Pro-Level, Rettungsroot, Fertigkeitsauswahl, Subklasse-Wahl, Feature-Boost/Feat, cantrips/spells/prepared/Slot-Schema/Upcast-Rechengang, Klassen-Ressource+Reset, Mastery-Gain/-Options (D109), Startausrüstung + Wahlkits (D105) | `features` = Ledger-Text; `subclass_family` ordnet nur Katalog | `weapon_prof`/`armor_prof`/`expertise`/`spellcasting_ability`/`spell_replace`/`upcast_scaling` (Spalte da, null Leser) |
| `subclasses.csv` | `spells_grant` → automatisch würfelbar (`charbuild.py:106-112`) | existence-check; Wahl im Wizard | `features`-Text, `needs_choice` ohne Leser |
| `feats.csv` | `ability_boost`, `skill_prof` (bei Wahl/Origin), `category=="origin"` erzwungen, `effects` → castbare Ability `feat_<id>` (D111) | `effect` = Anzeige | `requires` (Prereq) wird nie geprüft; `spells_grant` bei Talente nie angewandt |
| `backgrounds.csv` | `asi_abilities` + `origin_feat` (genau einmal, D108), `starting_items` | — | `skill_prof`, `tool_prof`, `languages`, `feature` ohne Leser (nie auf dem Bogen) |
| `species.csv` | — (nur Dropdown-Katalog, `content_api.py:81-101`) | — | **komplette Fläche**: `ability_bonuses`, Größe/Tempo/Sinne/Sprachen/Traits schreiben nie auf Bogen oder Token — kein `content.load("species")` im Engine-Pfad |
| `spells.csv` | Slotkosten+Upcast-Wahl, Zielgeometie/Shape/Größe/Reichweite/LOS, Rettung oder Angriff mit Crit + halbe/ganzer Effekt, Schaden/Heilung mit Typ gegen Resistenzen, Konzentraitions-FLAG, `upcast_step`/`upcast_scaling`/`scale_tiers`, `class_list`-Pool-Gate, `effects`-Op-Kette im `execute()`-Zweig (D111) | `duration` als Text auf dem Bogen; `break_concentration`-Op setzt die Fahne, der SRD-Rettungswurf bei Schaden folgt in S42 | **kein Ablauf-Ticker für Zauberduern**; `casting_time` nicht einmal gemappt; Komponenten existieren nicht als Spalte |
| `creatures.csv` | — | — | **komplett datenführend isoliert**: kein Engine-Leser (`content.load("creature")` = null Treffer); Monster laufen über den strukturierten NPC-Block (DM-Editor/Bestiarium), nicht über diese CSV |
| NPC-Block (Bestiarium, kein CSV) | Angriffe (to_hit/dmg/dc), Spruch+Slot, Rettungen/Resistenzen, Ability-IDs → Executor | `reach` im NPC-Angriff advisory | Sonderaktionen (Blick, Retr0grad-Bewegung, Re-Aktionen) sind als Effekt-Zusammensetzung nicht ausdrückbar |
| Zustände (`app/conditions.py` + `conditions.csv`, D111) | Pro-Instanz: `rounds`/`until`/`src`/`ref` + drei Uhren (D80); Katalog als CSV: Hook-Flags (Bewegungs­verbot, Tempo-Delta, Vor-/Nachteil, Save-Auto-Fail) + `on_start`/`on_round`/`on_expire`-Effektketten; SRD-Keys als `BUILTIN_HOOKS`-Daten, CSV-Zeile überschreibt | eigene Homebrew-Keys via `cond_add` zulässig | quellenbezogene Hooks (frightened „of that source“), Re-Aktionen, Auren (dokumentierte Grammatik-Grenze, `docs/EFFECT_GRAMMAR.md` §6) |
| `maps/objects` (Interact-Objekte, Welt-Chesten, Lampen, Fallen, Treppen) | Fallen: `dc`+`dmg`+DEX-Rettung (Legacy-d20 über die eine Engine `dice.do_roll`, D113), data-driven `effects`-Grammatik + `trigger`/`search_dc`/`disarm_dc`/`repeat` (D113) über `effectops`; Entdecken = WIS/Wahrnehmung; Lampen-Op DM-only; Truhen-Container; Treppen validiert; vertikale Öffnungen/Treppen bleiben eigene validierte Weltobjekte (D114) | Entschärfen = pauschaler DEX-Check (`opposed.check_roll`); Loot-Objekt = Text-Buchführung | Trigger-Bedingungen aus Regeln fehlen; **Thieves'-Tools-Proficiency ist weiterhin nicht modelliert** — echtes tool-basiertes Entschärfen bleibt offene Lücke (D113/D114, dokumentiert) |
| Executor-Effektgrammatik (`app/abilities.py` + `app/effectops.py`, D111) | shapes/targeting/reach/LOS, save/attack/crit, typed damage→HP, heal, add-condition(feste Runden), Kosten Slot/Resource, Upcast/Scale-Tiers; **Op-Kette v1:** damage/heal/temp_hp/condition(+remove)/forced_move/save/check/resource(mit Kosten-Preflight) | `break_concentration` setzt nur die Fahne (Save folgt S42) | Reaktionen, Auren, Beschwörungen, Teleport, Komponenten — dokumentierte v1-Grenze (`docs/EFFECT_GRAMMAR.md` §6) |
| Kontesto-Aktionen (`app/room/opposed.py` + `grapple`/`pickpocket`, D112) | Grapple/Shove/Escape (2024) und Taschendiebstahl (beide Modelle) laufen komplett serverseitig; `pick` ist ein echtes Item-Datenfeld (autorisierbare Stehl-Teilmenge, `clean_items`-Whitelist, stapelt nie); `grappled`-Cond trägt `dc` additiv | Kontesto-Parameter pro Aktion kommen aus der WS-Message (`adv`, `notice_dc`, Rettungs-Override), nicht aus CSV; der Kontesto-Helfer ist nur über Handlers ansprechbar | **noch kein Grammatik-Op** `opposed`/`check_vs_dc`/`check_then_save` — CSV kann in v1 keine Probe-gegen-Probe autorisieren; Schnittstelle dokumentiert in `docs/EFFECT_GRAMMAR.md` §6a → S42 |

## Was „CSV-only“ heute realistisch heißt

**Jetzt schon CSV-produzierbar (nach.once Executor vorhanden):**
neue Waffen/Rüstungen/Consumables inkl. Mastery, Attunement, Kurzwährung;
neue Zauber/Klassen-Features innerhalb der Executor-Grammatik; neue
Klassen-Progression; Startpakete; Fallen/Türen/Lampen/Truhen/Treppen;
Begegnungen aus dem Bestiarium.

**Erledigt in D111 (Sprint 40):** 3. Zustands-Katalog als CSV-Schicht +
Wirkung-Hooks (inkl. SRD-Verdrahtung als Daten + Homebrew-Keys), 4.
Effektgrammatik um Bewegung/Probe/Rettung/Ressource (Dauer-mit-**Rettungs**-
Ende als Save-Wurf → S42), 5. Item-Effektgrammatik über `heal` hinaus +
Trigger use/equip/unequip/on_hit/on_damaged (Fluch-Auslöser bleiben S42),
6. Dauer-Ablauf-Konsument für Zustands-Hooks (`on_round`/`on_expire` via
D80-Turn-Uhren).

**Erledigt in D112 (Sprint 41):** Kontesto-Primitive als Helper (Drei Formen,
kein CSV-Op), 2024-Grapple/Shove/Escape (check→save) und Taschendiebstahl mit
beiden Adjudikationsmodellen; `pick` als echtes, nicht-stapelndes Item-Datenfeld
und `grappled.dc` additiv. Die Kontesto-CSV-Autorisierung (Grammatik-Op) bleibt
S42 — Helfer-Schnittstelle in `docs/EFFECT_GRAMMAR.md` §6a.

**Noch Code nötig (die eigentliche Restarbeit — Details + Sprintplanung:
`docs/FEATURE_COMPLETE_GAPS.md`):**
1. Spezies → Bogen/Token (Größe, Tempo, Sinne, Abilities). — S44
2. creatures.csv → NPC-Block-Projektion (damit Monster aus CSV spawnen). — S44
5b. Fluch-Auslöser + Konzentraitions-Save bei Schaden. — S42
7. Ausrüstungs-Speed/Darkvision an Bewegungs-/Sichtpfad hängen (klein). — S44

D110 ändert daran nichts an der Engine — aber es **belegt die Kette**:
`tests/test_d110_e2e.py` fährt dieselben Pfade, die ein reiner CSV-Nachschub
benutzt (Pack-Import → Build → Ausrüstung → Kampf → Loot → Fluch → Reload),
und die zwei von der Kette gefundenen Engine-Fehler (siehe `DECISIONS.md`
D110) sind behoben.
