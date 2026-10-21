"""D139 (AP-026): the species Origin Feat reaches the engine, and no feat
is ever choosable twice.

Audit B5: SRD 5.2.1 species may grant an extra Origin Feat; the species
row now names it (origin_feat column — content may stay empty until packs
carry it), the projection exposes it, and the feat-choice flow consumes it
as ALREADY TAKEN. The same consumption closes the old free-text side of B6:
prerequisite chains ("feat Quick Study") count species and ledger feats as
applied, and a taken feat leaves the option pool (SRD: no feat twice).
"""
import pytest
from starlette.testclient import TestClient

from app import charbuild, db, main
from tests.test_d108_origin import _room

ADD_ORIGIN = ("feat_quick_study")


def mutate_species(files):
    import csv as _csv
    import io as _io
    buf = _io.StringIO()
    rows = list(_csv.DictReader(_io.StringIO(files["species.csv"])))
    head = list(rows[0])
    head.insert(head.index("size"), "origin_feat")
    w = _csv.DictWriter(buf, fieldnames=head)
    w.writeheader()
    for r in rows:
        r["origin_feat"] = ADD_ORIGIN if r["id"] == "kin_fey" else ""
        w.writerow(r)
    files["species.csv"] = buf.getvalue()


def mutate_chain(files):
    mutate_species(files)
    files["feats.csv"] = files["feats.csv"].replace(
        "feat_alley_cat,Alley Cat,,stealth",
        "feat_alley_cat,Alley Cat,feat Quick Study,stealth")


def test_species_row_projects_its_origin_feat(client):
    dm, player, code, ch = _room(client, mutate_species)
    rid = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
    sp = charbuild.species_projection({"race": "kin_fey"}, rid)
    assert sp["origin_feat"] == ADD_ORIGIN
    assert charbuild.species_projection({"race": "kin_stoutheart"}, rid)["origin_feat"] == ""


def test_species_feat_counts_as_taken_and_satisfies_prereqs(client):
    dm, player, code, ch = _room(client, mutate_chain)
    rid = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
    stats = {k: 10 for k in ("str", "dex", "con", "int", "wis", "cha")}
    opts = {o["id"]: o for o in
            charbuild._feat_choice_options(rid, stats, {},
                                           [{"id": ADD_ORIGIN}])}
    assert opts[ADD_ORIGIN]["available"] is False
    assert "already chosen" in opts[ADD_ORIGIN]["missing"]
    assert opts["feat_alley_cat"]["available"] is True      # prereq met via species


def test_no_feat_twice_from_the_ledger(client):
    dm, player, code, ch = _room(client)
    rid = db.q1("SELECT id FROM rooms WHERE code=?", (code,))["id"]
    stats = {k: 10 for k in ("str", "dex", "con", "int", "wis", "cha")}
    opts = {o["id"]: o for o in
            charbuild._feat_choice_options(rid, stats, {},
                                           [{"id": "feat_alley_cat"}])}
    assert opts["feat_alley_cat"]["available"] is False


@pytest.fixture
def client():
    app = main.app
    with TestClient(app) as c:
        yield c
