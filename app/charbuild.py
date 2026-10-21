"""Sprint 25 Phase B (D96): chronological character build (Stufe 1..20).

A PURE operation module (like ``app.progression``): it turns "build class X up to
level N" against the DATA a DM imported through the content engine into the SAME
mutations the existing engines already own — it builds NO second character, level
or spell engine:

  * class levels via ``progression.set_class_levels`` (single entry per build;
    slot progression stays a class-row table, never derived from total level — D58)
  * hit points from the class rows' ``hp_base`` / ``hp_per_level`` (documented,
    fixed formula — not a dice roll)
  * saving-throw and skill proficiencies through ``gear.clean_saves`` /
    ``gear.clean_skills`` (canonical shapes)
  * ability-score increases (ASI) and the ``ability_boost``/``skill_prof`` of a
    chosen feat, written into ``stats``/``skills``

The build LEDGER — which class, through which level it has been applied, the
subclass and the choices made per level — lives in ``characters.build``. It is
BOOKKEEPING for the sheet and the forward-only guard; it is NOT a second source of
truth for level/HP/abilities (those stay in the columns above).

Anything a level grants that no engine implements (subclass features, granted
spells) is recorded as TEXT in the ledger and displayed at the sheet; it is never
re-implemented or silently interpreted here (D95 boundary).
"""
import re

from . import content, db, gear, progression

ABILITY_SHORT = ("str", "dex", "con", "int", "wis", "cha")
_ABILITY_REQ_RE = re.compile(
    r"(?<![a-z])((?:str|dex|con|int|wis|cha))[^\d]{1,20}(\d{1,2})(?:[^\d]{1,20}(?:minimum|or\s+higher))?\b"
)
_FEAT_REQ_RE = re.compile(r"(?<![a-z])feat[^\w]+(.+)$")
_BOOST_RE = re.compile(r"^([a-z]+)([+-]\d{1,2})$")
MAX = progression.MAX_TOTAL_LEVEL


# --------------------------------------------------------------------------
# ledger (characters.build)
# --------------------------------------------------------------------------
def ledger(char) -> dict:
    """Parse the build ledger from a raw character row/sheet. '' -> {}."""
    led = db.j((char or {}).get("build"), None) or {}
    return led if isinstance(led, dict) else {}


def _decisions(led) -> dict:
    d = led.get("decisions")
    return d if isinstance(d, dict) else {}


# --------------------------------------------------------------------------
# content access
# --------------------------------------------------------------------------
def _class_rows(class_id, room_id):
    return {int(r.get("level") or 0): r for r in content.class_levels(class_id, room_id)}


def _species_row(ref, room_id):
    want = str(ref or "").strip().lower()
    if not want:
        return None
    for r in content.load("species", room_id):
        if str(r.get("id") or "").lower() == want or str(r.get("name") or "").lower() == want:
            return r
    return None


def _species_projection(char, room_id):
    """Read-only projection of the species row named by the character."""
    row = _species_row((char or {}).get("race"), room_id)
    if row is None:
        return None
    return {
        "id": row.get("id"), "name": row.get("name") or row.get("id"),
        "size": row.get("size") or "", "speed_ft": _int(row.get("speed_ft")),
        "fly_ft": _int(row.get("fly_ft")), "swim_ft": _int(row.get("swim_ft")),
        "climb_ft": _int(row.get("climb_ft")), "darkvision_ft": _int(row.get("darkvision_ft")),
        "languages": _split_raw(row.get("languages")),
        "traits": _split_raw(row.get("traits")),
        # D139 (audit B5): species that grant an extra Origin Feat name it
        # here; the feat-choice flow treats it as ALREADY TAKEN (SRD: no
        # feat twice) and prerequisite chains count it as applied.
        "origin_feat": str(row.get("origin_feat") or "").strip().lower(),
        # D145: the row's ability increases (e.g. 'dex+2'); apply_species_
        # bonus is the ONLY writer that moves them onto the sheet.
        "ability_bonuses": str(row.get("ability_bonuses") or "").strip().lower(),
    }


def species_projection(char, room_id):
    """Public projection used by room seating; it never replaces movement/sight."""
    return _species_projection(char, room_id)


def _class_proficiencies(rows, to):
    """Weapon/armor/tool proficiencies named by the class rows applied so far.

    This is a read-only ledger snapshot for the sheet. It intentionally does not
    replace item/weapon adjudication or invent a second proficiency engine.
    """
    out = {"weapons": [], "armor": [], "tools": []}
    for level in range(1, to + 1):
        row = rows.get(level) or {}
        out["weapons"] = sorted(set(out["weapons"]) | set(_split_raw(row.get("weapon_prof"))))
        out["armor"] = sorted(set(out["armor"]) | set(_split_raw(row.get("armor_prof"))))
        out["tools"] = sorted(set(out["tools"]) | set(_split_raw(row.get("tool_prof"))))
    return out


def _feat_rows(room_id):
    return {r.get("id"): r for r in content.load("feat", room_id)}


def _norm_words(text):
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


def _parse_feat_requires(raw):
    """Machine-readable prerequisite list from ``feats.csv:requires``.

    Semicolons separate independent requirements. Supported: ``Dex 13``,
    ``Skill Proficiency — Stealth`` and ``feat Alert``. Anything else fails
    closed — an unmodelled prerequisite must never be read as 'no prerequisite'.
    """
    conds = []
    for part in str(raw or "").split(";"):
        part = part.strip()
        if not part:
            continue
        words = _norm_words(part)
        feat = _FEAT_REQ_RE.match(part.strip().lower())
        if feat:
            conds.append({"kind": "feat", "feat": " ".join(feat.group(1).split())})
            continue
        ability = _ABILITY_REQ_RE.search(part.strip().lower())
        if ability:
            score = int(ability.group(2))
            if 1 <= score <= 30:
                conds.append({"kind": "ability", "ability": ability.group(1),
                              "score": score})
                continue
        skill = next((s for s in gear.SKILLS if f" {s} " in f" {words} "), None)
        if skill and re.search(r"\b(?:skill|proficien\w*)\b", words):
            conds.append({"kind": "skill", "skill": skill})
            continue
        return None, f"unsupported prerequisite {part!r} — model it or remove it"
    return conds, ""


def _feat_prereq_errors(row, stats, skills, feats_applied):
    conds, error = _parse_feat_requires(row.get("requires"))
    if error:
        return [error]
    stats = stats if isinstance(stats, dict) else {}
    skills = gear.clean_skills(skills if isinstance(skills, dict) else {})
    names = {str(f.get("id") or "").strip().lower() for f in feats_applied}
    names |= {str(f.get("name") or "").strip().lower() for f in feats_applied}
    out = []
    for cond in conds:
        kind = cond["kind"]
        if kind == "ability":
            ab = cond["ability"]
            have = _int(stats.get(ab, 10)) or 10
            if have < cond["score"]:
                out.append(f"{ab.upper()} {cond['score']} (currently {have})")
        elif kind == "skill":
            sk = cond["skill"]
            if _int(skills.get(sk, 0)) < 1:
                out.append(f"proficiency in {sk}")
        elif kind == "feat":
            if cond["feat"] not in names:
                out.append(f"feat {cond['feat']}")
    return out


def _feat_choice_options(room_id, stats, skills, feats_applied, level=None):
    rows = _feat_rows(room_id)
    out = []
    taken = {str(f.get("id") or "").strip().lower() for f in feats_applied}
    taken |= {str(f.get("name") or "").strip().lower() for f in feats_applied}
    for feat_id in sorted(rows):
        row = rows[feat_id]
        cat = str(row.get("category") or "")
        if level is not None and cat == "epic_boon" and level < 19:
            continue          # D163-5: Epic Boons belong to level 19+ only
        missing = _feat_prereq_errors(row, stats, skills, feats_applied)
        if feat_id in taken or str(row.get("name") or "").strip().lower() in taken:
            missing = missing + ["already chosen"]      # D139: no feat twice
        out.append({"id": feat_id, "name": row.get("name") or feat_id,
                    "category": str(row.get("category") or "general"),
                    "requires": str(row.get("requires") or ""),
                    "available": not missing, "missing": missing})
    return out


def _ledger_feat_ids(led):
    led = led if isinstance(led, dict) else {}
    out = []
    origin = led.get("origin")
    if isinstance(origin, dict) and origin.get("feat"):
        out.append(str(origin["feat"]))
    for entry in led.get("history") or []:
        if isinstance(entry, dict) and entry.get("feat"):
            out.append(str(entry["feat"]))
    return list(dict.fromkeys(out))


def _subclass_rows(class_id, room_id):
    out = {}
    for r in content.load("subclass", room_id):
        if r.get("class_id") == class_id:
            out.setdefault(r.get("id"), []).append(r)
    return out


def _spell_rows(class_id, room_id):
    """Class spell pool split into cantrip (level 0) and leveled spell ids."""
    cantrips, spells = [], []
    for r in content.spell_pool(class_id, room_id):
        try:
            lvl = int(r.get("level") or 0)
        except (TypeError, ValueError):
            lvl = 0
        (cantrips if lvl == 0 else spells).append(r["id"])
    return {"cantrips": sorted(cantrips), "spells": sorted(spells),
            "by_id": {r["id"]: r for r in content.spell_pool(class_id, room_id)}}


def _feat_grants(feats_applied, room_id):
    """Spell ids automatically granted by feats in ``spells_grant``.

    The same column already existed for subclasses; D115 brings feats into the
    one existing spell-grant chronology instead of adding a second source."""
    rows = _feat_rows(room_id)
    grants = []
    for entry in feats_applied:
        row = rows.get(str(entry.get("id") or "")) or {}
        grants += _split(row.get("spells_grant"))
    return grants


def _all_spell_rows(room_id):
    """All room-visible spell definitions, used only to render granted ids that
    may live outside the class list (for example a subclass/feat grant)."""
    return {r["id"]: r for r in content.load("spell", room_id)}


def _casting(rows):
    """Casting meta from class rows: first casting class level, prepared/known
    model — or None for a non-caster. Slot tables are read per level, never here
    (D58: a table on the row, never derived from total character level)."""
    first = 0
    prepared = False
    casting = False
    for lvl in sorted(rows):
        r = rows[lvl]
        if _int(r.get("spell_first_level")):
            first = first or _int(r.get("spell_first_level"))
        has = (_int(r.get("cantrips_known")) or _int(r.get("spells_known"))
               or str(r.get("slot_progression") or "").strip())
        if has:
            casting = True
            first = first or lvl
        if _bool(r.get("prepared")):
            prepared = True
    if not casting and first:               # a class can cast with only slots/cantrips set
        casting = True
    if not casting:
        return None
    ability = ""
    for lvl in sorted(rows):
        raw = rows[lvl].get("spellcasting_ability")
        v = raw[0] if isinstance(raw, (list, tuple)) and raw else raw
        v = str(v or "").strip().lower()
        if v:
            ability = v if v in ABILITY_SHORT else ""
            break
    return {"first": first or 1, "model": "prepared" if prepared else "known",
            "ability": ability}


def _subclass_grants(subclass, room_id):
    """Spell ids a subclass auto-activates (``spells_grant``) — no choice needed."""
    grants = []
    for r in content.load("subclass", room_id):
        if r.get("id") == subclass:
            grants += _split(r.get("spells_grant"))
    return grants



# --------------------------------------------------------------------------
# plan (pure, no mutation) — also drives the wizard's required choices
# --------------------------------------------------------------------------
def plan(class_id, to, room_id) -> dict:
    """Describe building ``class_id`` to ``to`` for a room, WITHOUT mutating.

    Returns {ok, class_id, to, levels:[...], needs:{skills, subclass, levels},
    subclass_options:[...], errors:[...]}. ``levels`` is the strict chronology
    (level 1 .. to). A level with no stored row contributes only HP bookkeeping.
    """
    errors = []
    try:
        to = int(to)
    except (TypeError, ValueError):
        to = 0
    if not 1 <= to <= MAX:
        return {"ok": False, "class_id": class_id, "to": to, "levels": [],
                "needs": {}, "subclass_options": [],
                "errors": [f"target level must be 1..{MAX}"]}
    rows = _class_rows(class_id, room_id)
    if 1 not in rows:
        return {"ok": False, "class_id": class_id, "to": to, "levels": [],
                "needs": {}, "subclass_options": [],
                "errors": [f"class '{class_id}' has no level-1 row in this room"]}

    first = rows[1]
    subclass_opts = _subclass_rows(class_id, room_id)
    casting = _casting(rows)
    pool = _spell_rows(class_id, room_id) if casting else {"cantrips": [], "spells": []}
    levels, needs = [], {"skills": False, "skill_options": [], "skill_count": 0,
                         "subclass": False, "levels": {}}
    if casting and casting["first"] <= to:
        needs["spell"] = {"model": casting["model"], "first": casting["first"],
                           "ability": casting.get("ability") or "",
                           "pool_cantrips": pool["cantrips"], "pool_spells": pool["spells"]}
    for lvl in range(1, to + 1):
        r = rows.get(lvl, {})
        info = {
            "level": lvl,
            "features": _split(r.get("features")),
            "hit_die": _int(r.get("hit_die")) or _int(first.get("hit_die")) or 8,
            "hp_per_level": _int(r.get("hp_per_level")) if lvl > 1 else _int(first.get("hp_base")),
            "subclass_choice": _bool(r.get("subclass_choice")),
            "ability_boost_or_feat": _bool(r.get("ability_boost_or_feat")),
            "feat_choice": _bool(r.get("feat_choice")),
            "needs_choice": False,
        }
        if lvl == 1:
            opts = _split(r.get("skill_options"))
            cnt = _int(r.get("skill_count")) or 0
            if cnt and opts:
                needs["skills"] = True
                needs["skill_options"], needs["skill_count"] = opts, cnt
        if info["subclass_choice"]:
            needs["subclass"] = True
        if info["ability_boost_or_feat"] or info["feat_choice"]:
            needs["levels"].setdefault(str(lvl), {}).update({
                "ability_boost_or_feat": info["ability_boost_or_feat"],
                "feat_choice": info["feat_choice"],
            })
            info["needs_choice"] = True
        expertise = _int(r.get("expertise"))
        if expertise:
            needs["levels"].setdefault(str(lvl), {})["expertise"] = expertise
            info["needs_choice"] = True
        # spell progression (D97): classes pick new spells where the class row's
        # totals increase. D162-10: PREPARED casters pick too — the pool is the
        # class list, the counts are the row's totals; re-PREPARING a day stays
        # a table/long-rest step (D138 gate), the BUILD decision is the player's.
        if casting and lvl >= casting["first"]:
            prev = rows.get(lvl - 1, {})
            cd = max(0, _int(r.get("cantrips_known")) - _int(prev.get("cantrips_known")))
            sd = max(0, _int(r.get("spells_known")) - _int(prev.get("spells_known")))
            if casting["model"] == "prepared":
                # D162-10: prepared counts are the class row's TOTALS (not the
                # known-model deltas), capped by what the pack's class list can
                # actually offer — a pick must always be satisfiable (a demo-row
                # total above the pool size could never be picked otherwise).
                cum_c = min(_int(r.get("cantrips_known")), len(pool["cantrips"]))
                cum_s = min(_int(r.get("spells_known")), len(pool["spells"]))
                cum_pc = min(_int(prev.get("cantrips_known")), len(pool["cantrips"]))
                cum_ps = min(_int(prev.get("spells_known")), len(pool["spells"]))
                cd, sd = max(0, cum_c - cum_pc), max(0, cum_s - cum_ps)
            if cd or sd:
                ent = needs["levels"].setdefault(str(lvl), {})
                ent["cantrips"], ent["spells"] = cd, sd
                ent["pool_cantrips"], ent["pool_spells"] = pool["cantrips"], pool["spells"]
                info["spell_choice"] = True
                info["needs_choice"] = True
        levels.append(info)
    return {"ok": not errors, "class_id": class_id, "to": to, "levels": levels,
            "needs": needs, "subclass_options": sorted(subclass_opts),
            "errors": errors}



# --------------------------------------------------------------------------
# apply (the single mutation site)
# --------------------------------------------------------------------------
def _expertise_options(class_id, room_id, ch):
    """Skills that may legitimately become expert. A class's own level-1 skill
    options are available while its level-1 choices are being made; already
    proficient skills remain available for later class features."""
    rows = _class_rows(class_id, room_id)
    current = gear.clean_skills(_as_dict((ch or {}).get("skills")))
    current = {k for k, v in current.items() if v >= 1}
    class_options = {k for k in _split(rows.get(1, {}).get("skill_options")) if k in gear.SKILLS}
    return sorted(current | class_options)


def plan_for_character(char_id, class_id, to, room_id=0):
    """``plan`` enriched with the per-character choices an interactive client can
    offer. The rules themselves remain in ``plan``/``apply`` — this helper only
    supplies the current candidate list; it is not a second validator."""
    p = plan(class_id, to, room_id)
    ch = db.q1("SELECT * FROM characters WHERE id=?", (int(char_id),))
    if not p.get("ok") or ch is None:
        return p
    raw_stats = _as_dict(ch.get("stats"))
    stats = {str(k).lower(): (_int(raw_stats.get(k, 10)) or 10) for k in raw_stats}
    skills = gear.clean_skills(_as_dict(ch.get("skills")))
    feats_applied = [{"id": fid} for fid in _ledger_feat_ids(ledger(ch))]
    sp = _species_projection(ch, room_id)
    if sp and sp.get("origin_feat"):
        feats_applied = [{"id": sp["origin_feat"]}] + feats_applied   # D139
    for lvl, spec in (p.get("needs") or {}).get("levels", {}).items():
        if spec.get("feat_choice") or spec.get("ability_boost_or_feat"):
            spec["feat_options"] = _feat_choice_options(room_id, stats, skills,
                                                    feats_applied, int(lvl))
        if spec.get("expertise"):
            spec["expertise_skills"] = _expertise_options(p["class_id"], room_id, ch)
    return p


def apply(char_id, class_id, to, choices=None, room_id=0):
    """Advance ``class_id`` to ``to`` for a character, forward-only and
    idempotent. ``choices`` may carry only the NEW decisions; earlier ones are
    remembered in the ledger. Returns ``(ok, result)`` — on missing choices
    ``result`` is ``{"needs_choice": [...]}`` and NOTHING is written."""
    ch = db.q1("SELECT * FROM characters WHERE id=?", (int(char_id),))
    if ch is None:
        return False, {"error": "unknown character"}
    led = ledger(ch)
    class_id = str(class_id or "").strip().lower()
    built = led.get("class_id")
    if built and built != class_id:
        return False, {"error": f"already building '{built}'; adjust levels directly"}

    applied = int(led.get("applied_through") or 0)
    try:
        to = int(to)
    except (TypeError, ValueError):
        return False, {"error": "bad target level"}
    if to <= applied:
        return False, {"error": f"already built to {applied} (build is forward-only)"}

    p = plan(class_id, to, room_id)
    if not p["ok"]:
        return False, {"error": "; ".join(p["errors"]) or "cannot plan build"}
    for lvl, spec in p["needs"].get("levels", {}).items():
        if spec.get("expertise"):
            spec["expertise_skills"] = _expertise_options(class_id, room_id, ch)

    dec = dict(_decisions(led))              # merge incoming over remembered
    for k, v in (choices or {}).items():
        if k == "levels" and isinstance(v, dict):
            merged = dict(dec.get("levels") or {})
            merged.update(v)
            dec["levels"] = merged
        elif v not in (None, "", [], {}):
            dec[k] = v
    dec.setdefault("levels", {})

    # D162-10: FRESH spell picks must match the granted counts exactly — the
    # wizard asks "pick N" and more than granted would over-grant known spells.
    # Remembered/legacy decisions are never re-validated against count (the
    # legacy prepared tolerance below records pools, not picks).
    fresh = (choices or {}).get("levels") or {}
    for lvl, spec in p["needs"].get("levels", {}).items():
        got = fresh.get(str(lvl))
        if not isinstance(got, dict):
            continue
        for key, label in (("cantrips", "cantrip"), ("spells", "spell")):
            reqn = int(spec.get(key) or 0)
            have_n = len(_split(got.get(key)))
            if reqn and have_n > reqn:
                return False, {"error": f"level {lvl}: {reqn} {label}(s) granted, "
                                        f"{have_n} selected"}

    # D162-10 legacy tolerance: a prepared caster built BEFORE the build-time
    # choice step existed recorded no spell picks — their sheet was derived
    # from the whole class pool. Re-applying (leveling) must NOT silently
    # shrink that sheet: the missing pick for an ALREADY-APPLIED level is
    # recorded as exactly the pool that built it (the sheet stays byte-true).
    # Every NEW level above `applied` demands a real player pick.
    casting = p["needs"].get("spell") or {}
    if (casting.get("model") == "prepared" and applied > 0 and casting.get("first")
            and str(class_id) == str(built or "").lower()):
        pool = _spell_rows(class_id, room_id)
        for lvl, spec in p["needs"].get("levels", {}).items():
            if int(lvl) > applied or int(lvl) < int(casting["first"]):
                continue
            entry = dec["levels"].setdefault(str(lvl), {})
            if spec.get("cantrips") and not entry.get("cantrips"):
                entry["cantrips"] = list(pool["cantrips"])
            if spec.get("spells") and not entry.get("spells"):
                entry["spells"] = list(pool["spells"])

    needs_choice = _check_choices(p, dec, class_id, room_id)
    if needs_choice:
        return False, {"needs_choice": needs_choice}

    ok, payload = _recompute(ch, led, class_id, to, p, dec, room_id)
    if not ok:
        return False, payload

    # -- persist through the ONE mutation site + the columns the engines read.
    #    D109: every statement shares ONE db.tx() — a concurrent reader or
    #    writer can never observe or interleave with a half-applied build.
    stats, skills, saves = payload["stats"], payload["skills"], payload["saves"]
    spell_state = payload["spell_state"]
    led.update({"class_id": class_id, "applied_through": to,
                "subclass": payload["subclass"], "base_stats": payload["base_stats"],
                "decisions": dec, "history": payload["history"],
                "class_proficiencies": payload["class_proficiencies"],
                "casting": payload["casting"],
                "species": payload["species"]})
    # D109: masteries accrued by the levels applied NOW (forward-only —
    # levels applied earlier never produce grants retroactively).
    gains = _mastery_gains(class_id, applied, to, room_id)
    if gains:
        led["masteries"] = {"grants": _mastery_grants(led) + gains}
    # D111: an EFFECTS-bearing feat grants its registered ability feat_<id> as
    # an entitlement — the same characters.abilities axis _rollable_by reads.
    frows = _feat_rows(room_id)
    feat_abilities = sorted({f"feat_{str(f.get('id'))[:22]}" for f in payload["feats_applied"]
                             if str((frows.get(f.get("id")) or {}).get("effects") or "").strip()})
    if spell_state:
        spell_state["abilities"] = sorted(set(spell_state["abilities"]) | set(feat_abilities))
    with db.tx() as c:
        if not progression.set_class_levels(ch["id"],
                                            [{"class_id": class_id, "level": to}], c=c):
            return False, {"error": "invalid class levels"}
        axes = payload.get("axes") or {}          # D163-3/-4: persisted axes
        c.execute("UPDATE characters SET char_class=?, hit_die=?, max_hp=?, hp=?, "
                  "stats=?, skills=?, saves=?, build=?, "
                  "tool_profs=?, weapon_profs=?, armor_profs=? WHERE id=?",
                  (class_id, payload["hit_die"], payload["max_hp"], payload["max_hp"],
                   db.json_dumps(stats), db.json_dumps(skills),
                   db.json_dumps({k: v for k, v in saves.items() if v}),
                   db.json_dumps(led),
                   db.json_dumps(axes.get("tool") or []),
                   db.json_dumps(axes.get("weapon") or []),
                   db.json_dumps(axes.get("armor") or []), ch["id"]))
        if spell_state:
            c.execute("UPDATE characters SET abilities=?, spells=?, spell_slots=?, "
                      "resources=? WHERE id=?",
                      (db.json_dumps(spell_state["abilities"]),
                       db.json_dumps(spell_state["spells"]),
                       db.json_dumps(spell_state["spell_slots"]),
                       db.json_dumps(spell_state["resources"]), ch["id"]))
        elif payload.get("class_resources"):
            # D161: a NON-caster class row may still carry class_resource
            # (Action Surge, Rage, Ki). ``resources`` rode ONLY the spell_state
            # write, so every non-caster silently lost it. Same projection,
            # resources column only.
            c.execute("UPDATE characters SET resources=? WHERE id=?",
                      (db.json_dumps(payload["class_resources"]), ch["id"]))
        elif feat_abilities:
            cur = db.j(c.execute("SELECT abilities FROM characters WHERE id=?",
                                 (ch["id"],)).fetchone()[0], []) or []
            c.execute("UPDATE characters SET abilities=? WHERE id=?",
                      (db.json_dumps(sorted(set(cur) | set(feat_abilities))), ch["id"]))
    res = {"level": to, "max_hp": payload["max_hp"], "subclass": payload["subclass"],
           "skills": sorted(k for k, v in skills.items() if v),
           "saves": sorted(k for k, v in saves.items() if v),
           "feats": payload["feats_applied"]}
    if spell_state:
        res["known"] = sorted(spell_state["abilities"])
        res["slots"] = {lv: d["max"] for lv, d in spell_state["spell_slots"].items() if d["max"]}
        res["spell_model"] = p["needs"]["spell"]["model"]
        if p["needs"]["spell"].get("ability"):
            res["casting_ability"] = p["needs"]["spell"]["ability"]
    return True, res



# --------------------------------------------------------------------------
# D108 — character origin (2024): background ASI + Origin feat, server-authorised
# --------------------------------------------------------------------------
def _background_row(ref, room_id):
    """Resolve a background reference (row id OR name, case-insensitive — the
    same matcher the D101 starting-gear path uses) against THIS room's content."""
    want = str(ref or "").strip().lower()
    if not want:
        return None
    for r in content.load("background", room_id):
        if str(r.get("id") or "").lower() == want or str(r.get("name") or "").lower() == want:
            return r
    return None


def _origin_errors(row, room_id):
    """What makes a background row 2024-ready: its three ASI abilities and one
    feat row IN THIS ROOM whose category is exactly 'origin' (SRD 5.2.1:
    'A background gives your character a specified Origin feat'). A 2014-style
    row fails here visibly — never silently treated as 2024-conformant."""
    errs = []
    name = row.get("name") or row.get("id")
    ab = [a for a in (row.get("asi_abilities") or []) if a in ABILITY_SHORT]
    if len(ab) != 3 or len(set(ab)) != 3:
        errs.append(f"background '{name}' has no valid asi_abilities "
                    "(needs exactly three ability scores) — not a 2024 background")
    feat_id = str(row.get("origin_feat") or "").strip()
    if not feat_id:
        errs.append(f"background '{name}' grants no origin_feat")
    else:
        feat = _feat_rows(room_id).get(feat_id)
        if feat is None:
            errs.append(f"origin_feat '{feat_id}' is not in this room's rule pack")
        elif str(feat.get("category") or "") != "origin":
            errs.append(f"feat '{feat_id}' is category "
                        f"'{feat.get('category') or 'general'}', not 'origin'")
    return errs


def origin_options(char, room_id):
    """The origin REPORT (GET side, D105 report-then-grant pattern): readiness,
    the three allowed abilities with their CURRENT values (for the preview), the
    Origin feat — and every error apply_origin would refuse on."""
    led = ledger(char)
    applied = led.get("origin") if isinstance(led.get("origin"), dict) else None
    ref = str((char or {}).get("background") or "").strip()
    out = {"applied": applied, "ready": False, "background": None,
           "background_name": ref or None, "asi_abilities": [], "feat": None,
           "current": {}, "modes": ["plus2_plus1", "three"], "errors": []}
    if not ref:
        out["errors"].append("This character has no background set")
        return out
    row = _background_row(ref, room_id)
    if row is None:
        out["errors"].append(f"Background '{ref}' is not in this room's rule pack")
        return out
    out["background"] = row.get("id")
    out["background_name"] = row.get("name") or row.get("id")
    out["background_tool_prof"] = _split_raw(row.get("tool_prof"))
    out["background_languages"] = _split_raw(row.get("languages"))
    out["background_feature"] = row.get("feature") or ""
    out["background_manual"] = row.get("manual") or ""
    ab = [a for a in (row.get("asi_abilities") or []) if a in ABILITY_SHORT]
    out["asi_abilities"] = ab
    stats = _as_dict(char.get("stats"))
    out["current"] = {a: _int(stats.get(a, 10)) or 10 for a in ab}
    feat_id = str(row.get("origin_feat") or "").strip()
    feat = _feat_rows(room_id).get(feat_id) if feat_id else None
    if feat:
        out["feat"] = {"id": feat["id"], "name": feat.get("name", feat["id"]),
                       "category": feat.get("category") or "general",
                       "effect": feat.get("effect") or ""}
    out["errors"] = _origin_errors(row, room_id)
    out["ready"] = not out["errors"] and applied is None
    return out


def apply_origin(char_id, background, asi, room_id=0):
    """Grant the 2024 background origin (ability increases + Origin feat) EXACTLY
    ONCE. Every decision is validated against THIS room's imported content — the
    client picks a distribution among the background's THREE listed abilities and
    nothing else; feat id and amount come from the background row. The grant is
    recorded in the build ledger (``characters.build.origin`` = the secure proof
    of origin, no heuristic back-computation) and replayed inside the SAME full
    recompute the class chronology uses, so it can never be applied twice and
    survives any later build step. hp/max_hp/slots/resources are never touched;
    existing sheets are never auto-migrated.
    D109: the idempotency read AND the write run inside ONE db.tx()
    (BEGIN IMMEDIATE) — check-then-write races against another writer are
    closed by SQLite's single-writer lock, so EXACTLY-ONCE holds even under
    concurrent requests, not just sequential ones."""
    with db.tx() as c:
        return _apply_origin_locked(c, char_id, background, asi, room_id)


def _apply_origin_locked(c, char_id, background, asi, room_id):
    row = c.execute("SELECT * FROM characters WHERE id=?", (int(char_id),)).fetchone()
    ch = dict(row) if row else None
    if ch is None:
        return False, {"error": "unknown character"}
    led = ledger(ch)
    applied = led.get("origin")
    if isinstance(applied, dict) and applied:
        return True, {"already": True, "origin": applied}
    row = _background_row(background, room_id)
    if row is None:
        return False, {"error": f"background '{background}' is not in this room's rule pack"}
    errs = _origin_errors(row, room_id)
    if errs:
        return False, {"error": "; ".join(errs)}
    allowed = [a for a in (row.get("asi_abilities") or []) if a in ABILITY_SHORT]
    deltas, err = _origin_deltas(allowed, asi, _as_dict(ch.get("stats")))
    if err:
        return False, {"error": err}
    if not isinstance(led.get("base_stats"), dict) or not led.get("base_stats"):
        led["base_stats"] = dict(_as_dict(ch.get("stats")))
    led["origin"] = {"background": row["id"], "feat": str(row["origin_feat"]).strip(),
                     "asi": deltas}
    led["species"] = _species_projection(ch, room_id)

    built = str(led.get("class_id") or "")
    applied_through = int(led.get("applied_through") or 0)
    feats_applied = []
    if built and applied_through > 0:
        # A built sheet: replay the WHOLE chronology (base snapshot + origin +
        # class levels) — deterministic, so HP/spells/resources come out exactly
        # as stored; only stats/skills may change (origin feat skill_prof).
        p = plan(built, applied_through, room_id)
        if not p["ok"]:
            return False, {"error": "; ".join(p["errors"]) or "cannot replay build"}
        ok, payload = _recompute(ch, led, built, applied_through, p,
                                 dict(_decisions(led)), room_id)
        if not ok:
            return False, payload
        stats, skills = payload["stats"], payload["skills"]
        led["class_proficiencies"] = payload["class_proficiencies"]
        axes = payload.get("axes") or {}
    else:
        stats = dict(led["base_stats"])
        _replay_species(led, stats)
        skills = dict(gear.clean_skills(_as_dict(ch.get("skills"))))
        ok, note = _replay_origin(led["origin"], room_id, stats, skills, feats_applied)
        if not ok:
            return False, {"error": note}
        axes = _prof_axes({}, room_id, led, feats_applied)   # origin-only: no class rows yet
        axes["weapon"] = sorted(set(axes["weapon"]) | set(gear._axis_list(ch, "weapon_profs")))
        axes["armor"] = sorted(set(axes["armor"]) | set(gear._axis_list(ch, "armor_profs")))
        axes["tool"] = sorted(set(axes["tool"]) | set(gear._axis_list(ch, "tool_profs")))
    c.execute("UPDATE characters SET stats=?, skills=?, build=?, "
              "tool_profs=?, weapon_profs=?, armor_profs=? WHERE id=?",
              (db.json_dumps(stats), db.json_dumps(skills), db.json_dumps(led),
               db.json_dumps(axes.get("tool") or []),
               db.json_dumps(axes.get("weapon") or []),
               db.json_dumps(axes.get("armor") or []), ch["id"]))
    feat_row = _feat_rows(room_id).get(led["origin"]["feat"], {})
    return True, {"origin": led["origin"], "background": row["id"],
                  "background_name": row.get("name", row["id"]),
                  "background_tool_prof": _split_raw(row.get("tool_prof")),
                  "background_languages": _split_raw(row.get("languages")),
                  "background_feature": row.get("feature") or "",
                  "background_manual": row.get("manual") or "",
                  "feat": feat_row.get("name", led["origin"]["feat"]),
                  "stats": stats,
                  "skills": sorted(k for k, v in skills.items() if v)}



def species_bonus_options(char, room_id=0):
    """D145: the species ability-bonus REPORT (report-then-grant pattern).
    Read-only — the numbers come from the room's species row, never from a
    client. `result` previews the post-grant scores the way _bump will apply
    them (1..30 clamped); `errors` lists everything apply_species_bonus would
    refuse on."""
    led = ledger(char)
    applied = led.get("species_bonus") if isinstance(led.get("species_bonus"), dict) else None
    sp = _species_projection(char, room_id)
    out = {"applied": applied, "ready": False, "species": None,
           "species_name": None, "bonuses": [], "current": {}, "result": {},
           "errors": []}
    if sp is None:
        out["errors"].append("This character's species is not in this room's rule pack")
        return out
    out["species"] = sp["id"]
    out["species_name"] = sp.get("name") or sp["id"]
    # D162-2: the card shows the species' 2024 FEATURES too (traits, languages,
    # size, speeds) — read-only display; seating engines already project them.
    out["features"] = {"size": sp.get("size") or "",
                       "speed_ft": sp.get("speed_ft"),
                       "fly_ft": sp.get("fly_ft"),
                       "swim_ft": sp.get("swim_ft"),
                       "climb_ft": sp.get("climb_ft"),
                       "darkvision_ft": sp.get("darkvision_ft"),
                       "languages": sp.get("languages") or [],
                       "traits": sp.get("traits") or []}
    bonuses = _parse_bonuses(sp.get("ability_bonuses"))
    if not bonuses:
        out["errors"].append("This species grants no ability bonuses")
        return out
    stats = _as_dict(char.get("stats"))
    for ab, delta in bonuses:
        out["bonuses"].append({"ability": ab, "delta": delta})
        cur = _int(stats.get(ab, 10)) or 10
        out["current"][ab] = cur
        out["result"][ab] = max(1, min(30, cur + delta))
    out["errors"] = [] if applied else out["errors"]
    out["ready"] = applied is None and not out["errors"]
    return out


def apply_species_bonus(char_id, room_id=0):
    """Grant the species ability bonuses EXACTLY ONCE (D145, 2024: Species
    increases belong to character creation). The bonus is a RECORDED LEDGER
    entry (``characters.build.species_bonus``) that the full recompute replays
    at the front of the chronology — the same idempotency machinery D108
    established for origins — so a later level-up or origin apply can never
    silently drop it, and double clicks answer ``already``. The read AND the
    write run inside ONE db.tx() (BEGIN IMMEDIATE). Existing sheets are never
    auto-migrated; hp/AC/slots/resources are never touched."""
    with db.tx() as c:
        return _apply_species_bonus_locked(c, char_id, room_id)


def _apply_species_bonus_locked(c, char_id, room_id):
    row = c.execute("SELECT * FROM characters WHERE id=?", (int(char_id),)).fetchone()
    ch = dict(row) if row else None
    if ch is None:
        return False, {"error": "unknown character"}
    led = ledger(ch)
    done = led.get("species_bonus")
    if isinstance(done, dict) and done:
        return True, {"already": True, "species_bonus": done}
    sp = _species_projection(ch, room_id)
    if sp is None:
        return False, {"error": "This character's species is not in this room's rule pack"}
    bonuses = _parse_bonuses(sp.get("ability_bonuses"))
    if not bonuses:
        return False, {"error": "This species grants no ability bonuses"}
    if not isinstance(led.get("base_stats"), dict) or not led.get("base_stats"):
        led["base_stats"] = dict(_as_dict(ch.get("stats")))
    led["species_bonus"] = {"species": sp["id"], "bonuses": sp["ability_bonuses"],
                            "as": [{"ability": ab, "delta": d} for ab, d in bonuses]}
    built = str(led.get("class_id") or "")
    applied_through = int(led.get("applied_through") or 0)
    if built and applied_through > 0:
        p = plan(built, applied_through, room_id)
        if not p["ok"]:
            return False, {"error": "; ".join(p["errors"]) or "cannot replay build"}
        ok, payload = _recompute(ch, led, built, applied_through, p,
                                 dict(_decisions(led)), room_id)
        if not ok:
            return False, payload
        stats, skills = payload["stats"], payload["skills"]
        led["class_proficiencies"] = payload["class_proficiencies"]
    else:
        stats = dict(led["base_stats"])
        _replay_species(led, stats)
        skills = dict(gear.clean_skills(_as_dict(ch.get("skills"))))
        if isinstance(led.get("origin"), dict) and led.get("origin"):
            ok, note = _replay_origin(led["origin"], room_id, stats, skills, [])
            if not ok:
                return False, {"error": note}
    c.execute("UPDATE characters SET stats=?, skills=?, build=? WHERE id=?",
              (db.json_dumps(stats), db.json_dumps(skills), db.json_dumps(led), ch["id"]))
    return True, {"species_bonus": led["species_bonus"], "stats": stats,
                  "species": sp["id"], "species_name": sp.get("name") or sp["id"]}


def protect_species_floor(cur, stats):
    """D162-2: the raw character-editor PUT may rewrite `stats` freely (D100
    trusted-owner seam) — but it must never silently UNDO a species bonus the
    ledger has already granted. This clamps the granted abilities at the
    base+delta floor; legitimate higher values (feats, ASI, items) pass.
    Characters without a recorded species grant are untouched."""
    led = ledger(cur)
    sb = led.get("species_bonus")
    base = led.get("base_stats")
    if not (isinstance(sb, dict) and sb) or not isinstance(base, dict) or not base:
        return stats
    out = dict(_as_dict(stats))
    for rec in (sb.get("as") or []):
        ab, delta = str(rec.get("ability") or ""), _int(rec.get("delta"))
        if ab not in ABILITY_SHORT or not delta:
            continue
        floor = max(1, min(30, _int(base.get(ab, 10)) + delta))
        if _int(out.get(ab, 10)) < floor:
            out[ab] = floor
    return out


# --------------------------------------------------------------------------
# recompute core (D96 chronology + D108 origin replay) — the single mutation
# arithmetic behind apply() and apply_origin()
# --------------------------------------------------------------------------
def _prof_axes(rows, room_id, led, feats_applied):
    """D163-3/-4: the persisted proficiency AXSES (weapon groups / armor groups /
    tool keys) — projected from the class rows (weapon_prof/armor_prof/tool_prof),
    the origin background's tool_prof and every applied feat's tool_prof. These
    are the columns the combat engines read (gear.weapon_proficient /
    armor_proficient / tool_trained); before D163 the same CSV strings existed
    only as ledger text."""
    def iter_rows():
        if isinstance(rows, dict):
            for v in rows.values():
                if isinstance(v, dict):
                    yield v
        else:
            for v in (rows or []):
                if isinstance(v, dict):
                    yield v

    def words(text):
        return [w for w in _split(text) if w]
    wp, ap = set(), set()
    tp = set()
    for r in iter_rows():
        wp.update(w.lower() for w in words(r.get("weapon_prof")))
        ap.update(w.lower() for w in words(r.get("armor_prof")))
        tp.update(gear.tool_key(w) for w in words(r.get("tool_prof")) if gear.tool_key(w))
    bg = str((led.get("origin") or {}).get("background") or "").strip()         if isinstance(led.get("origin"), dict) else ""
    if bg:
        row = _background_row(bg, room_id)
        if row:
            tp.update(gear.tool_key(w) for w in words(row.get("tool_prof")) if gear.tool_key(w))
    frows = _feat_rows(room_id)
    for f in feats_applied or []:
        frow = frows.get(str(f.get("id") or "").strip().lower()) or {}
        tp.update(gear.tool_key(w) for w in words(frow.get("tool_prof")) if gear.tool_key(w))
    return {"weapon": sorted(wp), "armor": sorted(ap), "tool": sorted(tp)}


def _recompute(ch, led, class_id, to, p, dec, room_id):
    """Full recompute 1..to from the ledger's base_stats snapshot — idempotent
    by construction. The D108 origin grant (if the ledger has one) replays at
    the FRONT of the chronology (2024: origins exist before class level 1).
    Returns (False, {"error": ...}) or (True, payload)."""
    rows = _class_rows(class_id, room_id)
    first = rows[1]
    # ability deltas are RECOMPUTED from the pre-build base scores (snapshot at
    # first build), never stacked onto the already-mutated row — otherwise every
    # forward step would re-apply the earlier ASI/feat boosts.
    base_stats = led.get("base_stats")
    if not isinstance(base_stats, dict) or not base_stats:
        base_stats = _as_dict(ch.get("stats"))
    stats = dict(base_stats)
    _replay_species(led, stats)
    skills = dict(gear.clean_skills(_as_dict(ch.get("skills"))))
    saves = dict(gear.clean_saves(_as_dict(ch.get("saves"))))

    for ab in _split(first.get("saves")):
        if ab in ABILITY_SHORT:
            saves[ab] = True

    hit_die = _int(first.get("hit_die")) or 8
    max_hp = _int(first.get("hp_base")) or (hit_die)
    feats_applied, history = [], []
    requested_expertise = {}
    origin = led.get("origin") if isinstance(led.get("origin"), dict) else None
    if origin:
        ok, note = _replay_origin(origin, room_id, stats, skills, feats_applied)
        if not ok:
            return False, {"error": note}
    # Level-1 skill choices are chronologically available before any later
    # feat prerequisite is checked. Applying them after all feats would make a
    # later prerequisite see a character who had not made the first-level choice.
    if p["needs"]["skills"]:
        for sk in _split(dec.get("skills"))[: p["needs"]["skill_count"]]:
            if sk in gear.SKILLS:
                skills[sk] = max(skills.get(sk, 0), 1)
    for lvl in range(1, to + 1):
        r = rows.get(lvl, {})
        if lvl > 1:
            max_hp += _int(r.get("hp_per_level")) or _int(first.get("hp_per_level")) or 0
        entry = {"level": lvl, "features": _split(r.get("features"))}
        ch_level = dec.get("levels", {}).get(str(lvl))
        if isinstance(ch_level, dict) and ch_level.get("feat"):
            ok, note = _apply_feat(ch_level["feat"], room_id, stats, skills, feats_applied)
            entry["feat"] = ch_level["feat"]
            if not ok:
                return False, {"error": note}
        elif isinstance(ch_level, dict) and ch_level.get("ability"):
            ok, note = _apply_level_asi(ch_level["ability"], stats)
            if not ok:
                return False, {"error": f"level {lvl}: {note}"}
            entry["ability"] = ch_level["ability"]
        if isinstance(ch_level, dict) and ch_level.get("expertise"):
            requested_expertise[lvl] = _split(ch_level["expertise"])
        history.append(entry)

    # Expertise selections ride the existing skill value axis. Every source is
    # applied first; validation then requires the exact number granted by the
    # class row and rejects duplicates or non-proficient selections.
    for lvl, raw in sorted(requested_expertise.items()):
        chosen = list(dict.fromkeys(raw))
        allowed = _int((rows.get(lvl) or {}).get("expertise"))
        if len(raw) != allowed or len(chosen) != allowed:
            return False, {"error": f"level {lvl} requires exactly {allowed} expertise choice(s)"}
        for sk in chosen:
            if sk not in gear.SKILLS:
                return False, {"error": f"unknown skill for expertise: {sk}"}
            if skills.get(sk, 0) < 1:
                return False, {"error": f"cannot gain expertise in non-proficient {sk}"}
        for sk in chosen:
            skills[sk] = 2
            history[lvl - 1]["expertise"] = sorted(set((history[lvl - 1].get("expertise") or []) + chosen))

    subclass = str(dec.get("subclass") or "")
    if subclass and subclass not in _subclass_rows(class_id, room_id):
        return False, {"error": f"unknown subclass '{subclass}' for {class_id}"}
    if subclass:
        by_level = {int(r.get("level") or 0): r for r in _subclass_rows(class_id, room_id)[subclass]}
        for level, srow in sorted(by_level.items()):
            if level > to:
                continue
            entry = history[level - 1]
            entry["subclass"] = srow.get("name") or subclass
            entry["features"] += _split_raw(srow.get("features"))

    # -- spell state (Phase C / D97) — only for a class that actually casts up to
    # ``to``; a non-caster (or a caster below its first casting level) leaves the
    # existing abilities/spells/slots/resources columns completely untouched.
    # D115: subclass AND feat grants ride the same chronology. They are still
    # projected through the existing abilities/spells columns — no new engine.
    spell_state = None
    casting = p["needs"].get("spell")
    if casting:
        pool = _spell_rows(class_id, room_id)
        by_id = {**pool["by_id"], **_all_spell_rows(room_id)}
        grants = (set(_subclass_grants(subclass, room_id)) if subclass else set())
        grants |= set(_feat_grants(feats_applied, room_id))
        known = set()
        # D162-10: BOTH models read the player's recorded picks — nothing is
        # auto-granted from the pool any more. Legacy prepared sheets keep
        # their old whole-pool list because apply() records the pool as their
        # (historical) pick for already-applied levels (see D162-10 note).
        for lvl in range(casting["first"], to + 1):
            pick = dec.get("levels", {}).get(str(lvl)) or {}
            if isinstance(pick, dict):
                known |= {x for x in _split(pick.get("cantrips")) if x in pool["cantrips"]}
                known |= {x for x in _split(pick.get("spells")) if x in pool["spells"]}
        known |= {g for g in grants if g in by_id}
        maxes = content.slot_table(rows.get(to, {}))
        prev = gear.clean_slots(db.j(ch.get("spell_slots"), {}))
        slots_out = {}
        for lv in range(1, 10):
            mx = max(0, min(9, int(maxes.get(lv, 0) or 0)))
            slots_out[lv] = {"max": mx, "used": min(prev[lv]["used"], mx)}
        abilities_out = list(dict.fromkeys(
            [a for a in (db.j(ch.get("abilities"), []) or [])] + sorted(known)))
        book = gear.clean_spells(_spell_display(known, by_id))
        # D163-7: an explicit daily pick (spell_prepare) overrides the static
        # per-row prepared flag — for prep-gated lists only, so known-spell
        # casters and pre-D163 sheets are untouched.
        picks = set(gear._axis_list(ch, "prepared_spells"))
        if picks and any(x.get("prep") for x in book):
            for x in book:
                if x.get("prep"):
                    x["prepared"] = x.get("id") in picks
        spell_state = {
            "abilities": abilities_out,
            "spells": book,
            "spell_slots": slots_out,
            "resources": _class_resources(rows, to, ch),
            "casting_ability": casting.get("ability") or "",
        }

    return True, {"base_stats": base_stats, "stats": stats, "skills": skills,
                  "saves": saves, "hit_die": hit_die, "max_hp": max_hp,
                  "feats_applied": feats_applied, "history": history,
                  "subclass": subclass, "spell_state": spell_state,
                  "casting": casting,
                  # D161: projected class resource for EVERY class (casters get
                  # it inside spell_state too) — the non-caster write path was
                  # missing and silently lost Action Surge / Rage / Ki.
                  "class_resources": _class_resources(rows, to, ch),
                  "class_proficiencies": _class_proficiencies(rows, to),
                  "axes": _prof_axes(rows, room_id, led, feats_applied),
                  "species": _species_projection(ch, room_id)}


def _replay_species(led, stats):
    """D145: a RECORDED species bonus replays at the very front of the
    chronology (2024: species increases precede origin, class and ASI), from
    the string the projection normalised at grant time. An edited pack whose
    species row vanished simply keeps the recorded numbers — the grant was
    validated against the room's content when it happened, and unlike origin
    there is no skill/feat tail that could half-apply."""
    sb = led.get("species_bonus") if isinstance(led.get("species_bonus"), dict) else None
    if not sb:
        return
    for ab, delta in _parse_bonuses(sb.get("bonuses")):
        _bump(stats, ab, delta)


def _replay_origin(origin, room_id, stats, skills, feats_applied):
    """Apply a RECORDED origin grant onto the recompute state. The deltas were
    validated at grant time; the background's skill proficiencies come from the
    SAME background row, and the feat must STILL exist and STILL be an Origin
    feat — a later pack edit that drops or recategorises it fails the whole
    recompute visibly (no half-grant, no silent skip)."""
    for ab, delta in sorted((origin.get("asi") or {}).items()):
        _bump(stats, str(ab).lower(), _int(delta))
    bg_row = _background_row(str(origin.get("background") or ""), room_id) or {}
    for sk in _split(bg_row.get("skill_prof")):
        if sk in gear.SKILLS:
            skills[sk] = max(skills.get(sk, 0), 1)
    feat_id = str(origin.get("feat") or "")
    if feat_id:
        ok, note = _apply_feat(feat_id, room_id, stats, skills, feats_applied,
                               category="origin")
        if not ok:
            return False, note
    return True, ""


def _origin_deltas(allowed, asi, cur):
    """Validate the client's ASI choice against SRD 5.2.1 'Character
    Backgrounds': '+2 to one of the three and +1 to another' OR '+1 to all
    three' — targets from the background's list only, +2 and +1 on DIFFERENT
    scores, and NO score may rise above 20. Returns (deltas, error)."""
    asi = asi if isinstance(asi, dict) else {}
    mode = str(asi.get("mode") or "").strip().lower()
    if mode == "three":
        if set(asi) - {"mode"}:
            return None, "mode 'three' takes no extra keys"
        deltas = {a: 1 for a in allowed}
    elif mode in ("plus2_plus1", "plus"):
        if set(asi) - {"mode", "plus2", "plus1"}:
            return None, "unknown keys in asi (use mode/plus2/plus1 only)"
        p2 = str(asi.get("plus2") or "").strip().lower()
        p1 = str(asi.get("plus1") or "").strip().lower()
        if p2 not in allowed or p1 not in allowed:
            return None, "asi targets must be abilities listed by the background"
        if p2 == p1:
            return None, "+2 and +1 must go to DIFFERENT abilities"
        deltas = {p2: 2, p1: 1}
    else:
        return None, "asi mode must be 'plus2_plus1' or 'three'"
    for ab, d in sorted(deltas.items()):
        now = _int(cur.get(ab, 10)) or 10
        if now + d > 20:
            return None, f"{ab} would rise above 20 (currently {now})"
    return deltas, ""



# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _check_choices(p, dec, class_id, room_id):
    """List every required decision for 1..to that has not been made."""
    need = []
    if p["needs"]["skills"]:
        chosen = [s for s in _split(dec.get("skills")) if s in p["needs"]["skill_options"]]
        if len(chosen) < p["needs"]["skill_count"]:
            need.append({"kind": "skills", "count": p["needs"]["skill_count"],
                         "options": p["needs"]["skill_options"]})
    if p["needs"]["subclass"] and not dec.get("subclass"):
        need.append({"kind": "subclass", "options": p["subclass_options"]})
    for lvl, spec in p["needs"]["levels"].items():
        chosen = dec.get("levels", {}).get(lvl) or {}
        if spec.get("feat_choice") or spec.get("ability_boost_or_feat"):
            if not dec.get("levels", {}).get(lvl):
                need.append({"kind": "level_choice", "level": int(lvl),
                             "feat_choice": bool(spec.get("feat_choice")),
                             "ability_boost_or_feat": bool(spec.get("ability_boost_or_feat"))})
        req_c, req_s = int(spec.get("cantrips") or 0), int(spec.get("spells") or 0)
        if req_c or req_s:
            pc, ps = spec.get("pool_cantrips") or [], spec.get("pool_spells") or []
            got_c = _split(chosen.get("cantrips")) if isinstance(chosen, dict) else []
            got_s = _split(chosen.get("spells")) if isinstance(chosen, dict) else []
            sel_c = [x for x in got_c if x in pc]
            sel_s = [x for x in got_s if x in ps]
            if len(sel_c) < req_c or len(sel_s) < req_s:
                need.append({"kind": "spells", "level": int(lvl), "cantrips": req_c,
                             "spells": req_s, "pool_cantrips": pc, "pool_spells": ps})
        req_e = int(spec.get("expertise") or 0)
        if req_e:
            opts = list(spec.get("expertise_skills") or [])
            got_e = _split(chosen.get("expertise")) if isinstance(chosen, dict) else []
            sel_e = [x for x in got_e if x in opts]
            if len(sel_e) != req_e or len(set(sel_e)) != len(sel_e):
                need.append({"kind": "expertise", "level": int(lvl), "count": req_e,
                             "options": opts})
    return need



def _apply_feat(feat_id, room_id, stats, skills, applied, category=None):
    row = _feat_rows(room_id).get(feat_id)
    if row is None:
        return False, f"unknown feat '{feat_id}'"
    if category is not None and str(row.get("category") or "") != category:
        return False, (f"feat '{feat_id}' is category "
                       f"'{row.get('category') or 'general'}', not '{category}'")
    missing = _feat_prereq_errors(row, stats, skills, applied)
    if missing:
        name = row.get("name") or feat_id
        return False, f"feat '{name}' prerequisites not met: {'; '.join(missing)}"
    for ab, delta in _parse_bonuses(row.get("ability_boost")):
        _bump(stats, ab, delta, cap=20)            # D163-5: SRD score cap 20
    for sk in _split(row.get("skill_prof")):
        if sk in gear.SKILLS:
            skills[sk] = max(skills.get(sk, 0), 1)
    applied.append({"id": feat_id, "name": row.get("name", feat_id),
                    "effect": row.get("effect", "")})
    return True, ""


def _apply_ability_boost(boost, stats):
    if isinstance(boost, dict):
        for ab, delta in boost.items():
            _bump(stats, str(ab).lower(), _int(delta))
    else:
        for ab, delta in _parse_bonuses(boost):
            _bump(stats, ab, delta)


def _bump(stats, ab, delta, cap=30):
    if ab in ABILITY_SHORT:
        stats[ab] = max(1, min(cap, _int(stats.get(ab, 10)) + _int(delta)))


def _apply_level_asi(decision, stats):
    """D163-5: the 2024 Ability Score Improvement (SRD 5.2.1): +2 to one score
    and +1 to a different one, OR +1 to three different scores — never above 20.
    The SAME two modes the origin ASI already speaks (plus2_plus1 | three).
    A plain string/dict delta from pre-D163 decisions stays accepted (no silent
    rewrite of existing ledgers) but is now capped at 20 as the SRD demands."""
    if isinstance(decision, dict) and isinstance(decision.get("asi"), dict):
        asi = decision["asi"]
        mode = str(asi.get("mode") or "").strip().lower()
        if mode == "plus2_plus1":
            a = str(asi.get("plus2") or "").strip().lower()
            b = str(asi.get("plus1") or "").strip().lower()
            if a not in ABILITY_SHORT or b not in ABILITY_SHORT or a == b:
                return False, "ASI +2/+1 needs two DIFFERENT abilities"
            _bump(stats, a, 2, cap=20)
            _bump(stats, b, 1, cap=20)
            return True, ""
        if mode == "three":
            abils = list(asi.get("abilities") or [])
            abils = [str(x).strip().lower() for x in abils]
            if (len(abils) != 3 or len(set(abils)) != 3
                    or any(x not in ABILITY_SHORT for x in abils)):
                return False, "ASI three needs exactly three DIFFERENT abilities"
            for x in abils:
                _bump(stats, x, 1, cap=20)
            return True, ""
        return False, f"unknown ASI mode '{mode}' (plus2_plus1|three)"
    _apply_ability_boost_cap(decision, stats)
    return True, ""


def _apply_ability_boost_cap(boost, stats):
    """Pre-D163 ASI shapes kept compatible; scores stop at 20 (D163-5)."""
    if isinstance(boost, dict):
        for ab, delta in boost.items():
            _bump(stats, str(ab).lower(), _int(delta), cap=20)
    else:
        for ab, delta in _parse_bonuses(boost):
            _bump(stats, ab, delta, cap=20)


def _parse_bonuses(v):
    out = []
    for part in re.split(r"[,;]+", str(v or "")):
        m = _BOOST_RE.match(part.strip().lower())
        if m and m.group(1) in ABILITY_SHORT:
            out.append((m.group(1), int(m.group(2))))
    return out


def _as_dict(v):
    if isinstance(v, str):
        return db.j(v, {}) or {}
    return v if isinstance(v, dict) else {}


def _split_raw(v):
    if isinstance(v, (list, tuple)):
        return [str(x).strip() for x in v if str(x).strip()]
    return [x.strip() for x in re.split(r"[,;]+", str(v or "")) if x.strip()]


def _split(v):
    if isinstance(v, (list, tuple)):
        return [str(x).strip().lower() for x in v if str(x).strip()]
    return [x.strip().lower() for x in re.split(r"[,;]+", str(v or "")) if x.strip()]


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _bool(v):
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def _spell_display(known, by_id):
    """Sheet spellbook rows (gear.clean_spells shape) for the castable id set,
    built straight from the content spell rows — the DISPLAY pool; execution stays
    in abilities.execute (no second engine). Unknown ids are skipped."""
    out = []
    for sid in sorted(known):
        r = by_id.get(sid)
        if not r:
            continue
        res = str(r.get("resolution") or "auto").lower()
        cast = "attack" if res == "attack" else ("save" if res == "save" else "none")
        try:
            rng = str(int(r.get("range_ft") or 0))
        except (TypeError, ValueError):
            rng = str(r.get("range_ft") or "")
        out.append({"id": sid, "name": r.get("name") or sid,
                    "level": _int(r.get("level")), "school": r.get("school") or "",
                    "cast": cast, "ability": r.get("casting_ability") or "int",
                    "dmg": r.get("damage_dice") or r.get("heal_dice") or "",
                    "save": r.get("save") or "", "range": rng,
                    "targeting": r.get("targeting") or "single",
                    "duration": r.get("duration") or "",
                    "casting_time": r.get("casting_time") or "",
                    "prep": _int(r.get("prep")) > 0,
                    "prepared": _int(r.get("prepared")) > 0})
    return out


def _class_resources(rows, to, ch):
    """Merge a class's ``class_resource`` (D97) into the character's resources with
    the CSV's ``class_resource_reset`` timing; other resources are preserved.
    ``class_resource`` is 'id' or 'id:spec' (spec = level | half_level | third_level
    | <int>), max read from the CLASS level (never total level — D58)."""
    existing = gear.clean_resources(db.j(ch.get("resources"), []))
    spec = ""
    reset = ""
    for lvl in sorted(rows):
        v = str(rows[lvl].get("class_resource") or "").strip()
        if v:
            spec = v
        rr = str(rows[lvl].get("class_resource_reset") or "").strip().lower()
        if rr:
            reset = rr
    if not spec:
        return existing
    rid, _, ms = spec.partition(":")
    rid, ms = rid.strip().lower(), ms.strip().lower()
    if ms in ("", "level", "lvl"):
        mx = to
    elif ms == "half_level":
        mx = max(1, to // 2)
    elif ms == "third_level":
        mx = max(1, to // 3)
    else:
        mx = _int(ms) or to
    rid = rid[:24] or "class_resource"
    merged = [r for r in existing if r["id"] != rid]
    merged.append({"id": rid, "name": rid.replace("_", " ").title()[:40],
                   "max": mx, "current": mx, "reset": reset or "long"})
    return gear.clean_resources(merged)


# --------------------------------------------------------------------------
# D109 — weapon masteries (2024): grants, picks, entitlements. The weapon
# carries the PROPERTY (item content); the CHARACTER unlocks it here — the
# ledger is the only proof. Masteries accrue strictly at level application
# time (forward-only, exactly like the level chronology itself: a level that
# was applied before a grant existed never produces one retroactively) or by
# an explicit DM grant. Picks never touch stats/hp/slots — masteries are
# combat options, validated again at attack time (room/attack).
# --------------------------------------------------------------------------
def _mastery_class_rows(class_id, room_id):
    """Raw (unindexed) class rows of one class in this room's content."""
    return [r for r in content.load("class", room_id)
            if str(r.get("id") or "").lower() == str(class_id or "").lower()]


def _mastery_pool(row):
    """The class row's mastery pool: 'nick|vex' — unknown names are ignored,
    empty means all eight (SRD default: the full list)."""
    out = []
    for p in str(row.get("mastery_options") or "").replace(",", "|").split("|"):
        name = p.strip().lower()
        if name in content.MASTERIES and name not in out:
            out.append(name)
    return out or list(content.MASTERIES)


def _mastery_grants(led):
    m = led.get("masteries")
    grants = m.get("grants") if isinstance(m, dict) else None
    return [g for g in (grants or []) if isinstance(g, dict)]


def allowed_masteries(ch):
    """The ids a character may actually use in combat (resolved grants only)."""
    led = _as_dict(ch.get("build")) if isinstance(ch, dict) else {}
    return sorted({str(g.get("id") or "").strip().lower()
                   for g in _mastery_grants(led)
                   if str(g.get("id") or "").strip().lower() in content.MASTERIES})


def mastery_options(ch, room_id):
    """Report for the build wizard: every grant with its source, the pending
    picks and the pool they must come from, and the resolved entitlements."""
    led = ledger(ch)
    built = str(led.get("class_id") or "")
    rows = {int(r.get("level") or 0): r for r in _mastery_class_rows(built, room_id)
            if str(r.get("id") or "").lower() == built.lower()}
    out = []
    for g in _mastery_grants(led):
        mid = str(g.get("id") or "").strip().lower() or None
        pool = (_mastery_pool(rows[int(g["level"])])
                if g.get("via") == "level" and int(g.get("level") or 0) in rows
                else list(content.MASTERIES))
        out.append({"via": str(g.get("via") or "?"), "level": g.get("level"),
                    "actor": g.get("actor") or "", "id": mid, "pool": pool})
    return {"class": built, "grants": out,
            "pending": sum(1 for g in out if not g["id"]),
            "allowed": sorted({g["id"] for g in out if g["id"]})}


def apply_mastery(char_id, pick, room_id=0):
    """Resolve ONE pending level-grant to the picked mastery. Exactly one per
    pending grant; the pick must be in THAT grant level's pool; the pick is
    final (changing it needs a fresh DM grant). Transactional like origin."""
    with db.tx() as c:
        return _apply_mastery_locked(c, char_id, pick, room_id)


def _apply_mastery_locked(c, char_id, pick, room_id):
    row = c.execute("SELECT * FROM characters WHERE id=?", (int(char_id),)).fetchone()
    ch = dict(row) if row else None
    if ch is None:
        return False, {"error": "unknown character"}
    led = ledger(ch)
    pick = str(pick or "").strip().lower()
    if pick not in content.MASTERIES:
        return False, {"error": f"'{pick}' is not a weapon mastery"}
    built = str(led.get("class_id") or "")
    if not built:
        return False, {"error": "no class build — nothing to choose from"}
    rows = {int(r.get("level") or 0): r for r in _mastery_class_rows(built, room_id)}
    grants = _mastery_grants(led)
    for g in grants:
        if g.get("id"):
            continue
        if pick not in _mastery_pool(rows.get(int(g.get("level") or 0), {})):
            return False, {"error": f"'{pick}' is not in this level's mastery pool"}
        g["id"] = pick
        led["masteries"] = {"grants": grants}
        c.execute("UPDATE characters SET build=? WHERE id=?",
                  (db.json_dumps(led), ch["id"]))
        return True, {"masteries": led["masteries"], "picked": pick}
    return False, {"error": "no pending mastery choice"}


def grant_mastery(char_id, mastery, actor, room_id=0):
    """DM-granted mastery (the only path to a LATER or extra mastery — never a
    retroactive auto-grant). Idempotent: an already-resolved mastery answers
    'already' and adds nothing."""
    with db.tx() as c:
        return _grant_mastery_locked(c, char_id, mastery, actor, room_id)


def _grant_mastery_locked(c, char_id, mastery, actor, room_id):
    row = c.execute("SELECT * FROM characters WHERE id=?", (int(char_id),)).fetchone()
    ch = dict(row) if row else None
    if ch is None:
        return False, {"error": "unknown character"}
    led = ledger(ch)
    mastery = str(mastery or "").strip().lower()
    if mastery not in content.MASTERIES:
        return False, {"error": f"'{mastery}' is not a weapon mastery"}
    grants = _mastery_grants(led)
    if any(str(g.get("id") or "").lower() == mastery for g in grants):
        return True, {"already": True, "masteries": {"grants": grants}}
    grants.append({"via": "dm", "actor": str(actor or "DM")[:24], "id": mastery})
    led["masteries"] = {"grants": grants}
    c.execute("UPDATE characters SET build=? WHERE id=?",
              (db.json_dumps(led), ch["id"]))
    return True, {"masteries": led["masteries"], "granted": mastery}


def _mastery_gains(class_id, frm, to, room_id):
    """Grant events for levels (frm, to] whose class row carries a gain>0.
    One pending grant per gained mastery — snapshot semantics, so a later
    content edit of the class row cannot mint or void past grants."""
    rows = {int(r.get("level") or 0): r for r in _mastery_class_rows(class_id, room_id)}
    gains = []
    for lv in range(max(0, int(frm)) + 1, int(to) + 1):
        row = rows.get(lv)
        if not row:
            continue
        try:
            n = int(row.get("mastery_gain") or 0)
        except (TypeError, ValueError):
            n = 0
        for _ in range(max(0, min(8, n))):
            gains.append({"via": "level", "level": lv, "id": None})
    return gains
