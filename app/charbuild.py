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


def _feat_rows(room_id):
    return {r.get("id"): r for r in content.load("feat", room_id)}


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
    return {"first": first or 1, "model": "prepared" if prepared else "known"}


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
            needs["levels"][str(lvl)] = {"ability_boost_or_feat": info["ability_boost_or_feat"],
                                         "feat_choice": info["feat_choice"]}
            info["needs_choice"] = True
        # spell progression (D97): known-model classes pick new spells where the
        # class row's totals increase; prepared casters choose none (re-prepare is
        # a long-rest step the DM owns — never auto-faked).
        if casting and casting["model"] == "known" and lvl >= casting["first"]:
            prev = rows.get(lvl - 1, {})
            cd = max(0, _int(r.get("cantrips_known")) - _int(prev.get("cantrips_known")))
            sd = max(0, _int(r.get("spells_known")) - _int(prev.get("spells_known")))
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

    dec = dict(_decisions(led))              # merge incoming over remembered
    for k, v in (choices or {}).items():
        if k == "levels" and isinstance(v, dict):
            merged = dict(dec.get("levels") or {})
            merged.update(v)
            dec["levels"] = merged
        elif v not in (None, "", [], {}):
            dec[k] = v
    dec.setdefault("levels", {})

    needs_choice = _check_choices(p, dec, class_id, room_id)
    if needs_choice:
        return False, {"needs_choice": needs_choice}

    # -- chronological, full recompute 1..to (idempotent by construction) -----
    rows = _class_rows(class_id, room_id)
    first = rows[1]
    # ability deltas are RECOMPUTED from the pre-build base scores (snapshot at
    # first build), never stacked onto the already-mutated row — otherwise every
    # forward step would re-apply the earlier ASI/feat boosts.
    base_stats = led.get("base_stats")
    if not isinstance(base_stats, dict) or not base_stats:
        base_stats = _as_dict(ch.get("stats"))
    stats = dict(base_stats)
    skills = dict(gear.clean_skills(_as_dict(ch.get("skills"))))
    saves = dict(gear.clean_saves(_as_dict(ch.get("saves"))))

    for ab in _split(first.get("saves")):
        if ab in ABILITY_SHORT:
            saves[ab] = True

    hit_die = _int(first.get("hit_die")) or 8
    max_hp = _int(first.get("hp_base")) or (hit_die)
    feats_applied, history = [], []
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
            _apply_ability_boost(ch_level["ability"], stats)
            entry["ability"] = ch_level["ability"]
        history.append(entry)

    # level-1 class skill choices
    if p["needs"]["skills"]:
        for sk in _split(dec.get("skills"))[: p["needs"]["skill_count"]]:
            if sk in gear.SKILLS:
                skills[sk] = max(skills.get(sk, 0), 1)

    subclass = str(dec.get("subclass") or "")
    if subclass and subclass not in _subclass_rows(class_id, room_id):
        return False, {"error": f"unknown subclass '{subclass}' for {class_id}"}

    # -- spell state (Phase C / D97) — only for a class that actually casts up to
    # ``to``; a non-caster (or a caster below its first casting level) leaves the
    # existing abilities/spells/slots/resources columns completely untouched.
    spell_state = None
    casting = p["needs"].get("spell")
    if casting:
        pool = _spell_rows(class_id, room_id)
        by_id = pool["by_id"]
        grants = set(_subclass_grants(subclass, room_id)) if subclass else set()
        known = set()
        if casting["model"] == "prepared":
            known |= set(pool["cantrips"]) | set(pool["spells"])
        else:
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
        spell_state = {
            "abilities": abilities_out,
            "spells": gear.clean_spells(_spell_display(known, by_id)),
            "spell_slots": slots_out,
            "resources": _class_resources(rows, to, ch),
        }

    # -- persist through the ONE mutation site + the columns the engines read --
    if not progression.set_class_levels(ch["id"], [{"class_id": class_id, "level": to}]):
        return False, {"error": "invalid class levels"}
    led.update({"class_id": class_id, "applied_through": to, "subclass": subclass,
                "base_stats": base_stats, "decisions": dec, "history": history})
    db.x("UPDATE characters SET char_class=?, hit_die=?, max_hp=?, hp=?, stats=?, "
         "skills=?, saves=?, build=? WHERE id=?",
         (class_id, hit_die, max_hp, max_hp, db.json_dumps(stats),
          db.json_dumps(skills), db.json_dumps({k: v for k, v in saves.items() if v}),
          db.json_dumps(led), ch["id"]))
    if spell_state:
        db.x("UPDATE characters SET abilities=?, spells=?, spell_slots=?, resources=? "
             "WHERE id=?",
             (db.json_dumps(spell_state["abilities"]), db.json_dumps(spell_state["spells"]),
              db.json_dumps(spell_state["spell_slots"]), db.json_dumps(spell_state["resources"]),
              ch["id"]))
    res = {"level": to, "max_hp": max_hp, "subclass": subclass,
           "skills": sorted(k for k, v in skills.items() if v),
           "saves": sorted(k for k, v in saves.items() if v),
           "feats": feats_applied}
    if spell_state:
        res["known"] = sorted(spell_state["abilities"])
        res["slots"] = {lv: d["max"] for lv, d in spell_state["spell_slots"].items() if d["max"]}
        res["spell_model"] = casting["model"]
    return True, res



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
    return need



def _apply_feat(feat_id, room_id, stats, skills, applied):
    row = _feat_rows(room_id).get(feat_id)
    if row is None:
        return False, f"unknown feat '{feat_id}'"
    for ab, delta in _parse_bonuses(row.get("ability_boost")):
        _bump(stats, ab, delta)
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


def _bump(stats, ab, delta):
    if ab in ABILITY_SHORT:
        stats[ab] = max(1, min(30, _int(stats.get(ab, 10)) + _int(delta)))


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
                    "duration": r.get("duration") or ""})
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
