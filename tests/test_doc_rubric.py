"""Tests for the technical document quality rubric (experiments/plan-writing/rubric)."""

import importlib.util
import json
import re
from pathlib import Path

import pytest

from pm_core.plans.parser import parse_plan_prs

ROOT = Path(__file__).resolve().parent.parent
EXP = ROOT / "experiments" / "plan-writing"
_spec = importlib.util.spec_from_file_location("doc_rubric", EXP / "rubric.py")
rubric = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rubric)

RUBRIC = rubric.load_rubric()
REFS = rubric.load_references()
FIXTURES = rubric.load_fixtures()
DIMS = RUBRIC["dimensions"]
DIM_IDS = [d["id"] for d in DIMS]
EXTERNAL_KINDS = {"standard", "guideline", "process_template", "rubric", "paper", "book", "tool"}


@pytest.mark.parametrize("dim", DIMS, ids=DIM_IDS)
class TestDimension:
    def test_has_definition_example_guidance_question(self, dim):
        assert dim["definition"].strip()
        assert dim["examples"]["strong"].strip() and dim["examples"]["weak"].strip()
        assert dim["examples"]["strong"] != dim["examples"]["weak"]
        assert dim["detection_guidance"] and all(g.strip() for g in dim["detection_guidance"])
        assert dim["judge_question"].strip()
        assert set(dim["score_anchors"]) == {"1", "3", "5"}

    def test_cites_external_source(self, dim):
        assert dim["references"], "dimension cites no source"
        for ref in dim["references"]:
            assert ref in REFS, "unknown reference " + ref
        assert any(REFS[r]["kind"] in EXTERNAL_KINDS and REFS[r]["url"].startswith("https://")
                   for r in dim["references"])

    def test_candidate_measures_and_readiness(self, dim):
        measures = dim["candidate_measures"]
        assert measures
        statuses = set(RUBRIC["measure_statuses"])
        for m in measures:
            assert m["status"] in statuses
            assert m["kind"] in {"judge", "deterministic", "model_assisted"}
            assert m["description"].strip()
            for ref in m.get("references", []):
                assert ref in REFS
        # Judges are never treated as ready: every dimension has a judge measure awaiting calibration.
        assert any(m["kind"] == "judge" and m["status"] == "needs_calibration" for m in measures)
        quality_auto = [m for m in measures if m["status"] == "automatic_candidate" and m.get("role") != "bias_covariate"]
        expected = "automatic_candidate" if quality_auto else "calibration_required"
        assert dim["measure_readiness"] == expected

    def test_automatic_candidates_are_judge_free(self, dim):
        for m in dim["candidate_measures"]:
            if m["status"] == "automatic_candidate":
                assert m["kind"] == "deterministic"

    def test_applies_to_known_case_types(self, dim):
        assert dim["applies_to"] and set(dim["applies_to"]) <= set(rubric.CASE_TYPES)


def test_dimension_ids_unique():
    assert len(DIM_IDS) == len(set(DIM_IDS))


def test_readiness_split_is_marked():
    readiness = {d["measure_readiness"] for d in DIMS}
    assert readiness == set(RUBRIC["measure_readiness_values"])


def test_references_well_formed():
    ids = [r["id"] for r in json.loads((EXP / "rubric" / "references.json").read_text())["references"]]
    assert len(ids) == len(set(ids))
    for r in REFS.values():
        assert r["title"].strip() and r["url"].startswith("https://") and r["kind"] in EXTERNAL_KINDS
    cited = {ref for d in DIMS for ref in d["references"] + [r for m in d["candidate_measures"] for r in m.get("references", [])]}
    assert set(RUBRIC["judge_design_references"]) <= set(REFS)
    cited |= set(RUBRIC["judge_design_references"])
    assert set(REFS) <= cited, "uncited references: " + ", ".join(sorted(set(REFS) - cited))


def test_concerns_map_onto_dimensions():
    concerns = {c["id"]: c for c in RUBRIC["concerns"]}
    assert set(RUBRIC["previously_identified_concerns"]) == {
        "padding", "premature_implementation_detail", "poor_progression", "lost_requirements"}
    assert set(RUBRIC["previously_identified_concerns"]) | {"fidelity"} == set(concerns)
    for c in concerns.values():
        assert c["primary_dimension"] in DIM_IDS
        assert set(c["also_affects"]) <= set(DIM_IDS)
        assert c["boundary"].strip()
        primary = next(d for d in DIMS if d["id"] == c["primary_dimension"])
        assert c["id"] in primary["maps_concerns"]
    for d in DIMS:
        mapped = {c["id"] for c in concerns.values() if d["id"] in [c["primary_dimension"]] + c["also_affects"]}
        assert set(d["maps_concerns"]) == mapped, d["id"]


def test_rubric_doc_has_every_dimension_and_is_current():
    text = (EXP / "rubric" / "rubric.md").read_text()
    for d in DIMS:
        assert re.search(r"^### " + re.escape(d["id"]) + r" — ", text, re.M), d["id"]
    generated = text.split(rubric.GENERATED_START + "\n", 1)[1].split(rubric.GENERATED_END, 1)[0]
    assert generated == rubric.reference_markdown(), "run: python3 experiments/plan-writing/rubric.py --write-doc"
    for c in RUBRIC["previously_identified_concerns"]:
        assert c.replace("_", " ").lower() in text.lower()
    # The hand-written concern table must agree with the JSON mapping.
    for c in RUBRIC["concerns"]:
        row = "| " + " | ".join([c["name"], c["primary_dimension"], ", ".join(c["also_affects"]), c["boundary"]]) + " |"
        assert row in text, row


# ---- fixtures ---------------------------------------------------------------

def test_fixture_for_every_dimension():
    covered = {f["dimension"] for f in FIXTURES}
    assert covered == set(DIM_IDS)


@pytest.mark.parametrize("concern", RUBRIC["previously_identified_concerns"] + ["fidelity"])
def test_fixture_for_every_concern(concern):
    tagged = [f for f in FIXTURES if concern in f["concerns"]]
    assert tagged
    primary = next(c for c in RUBRIC["concerns"] if c["id"] == concern)["primary_dimension"]
    assert any(f["dimension"] == primary for f in tagged)


def test_fixtures_cover_both_case_types():
    assert {f["case_type"] for f in FIXTURES} == set(rubric.CASE_TYPES)


@pytest.mark.parametrize("fixture", FIXTURES, ids=[f["id"] for f in FIXTURES])
class TestFixture:
    def test_well_formed(self, fixture):
        path = EXP / "rubric" / "fixtures" / (fixture["id"] + ".json")
        assert path.exists()
        dim = next(d for d in DIMS if d["id"] == fixture["dimension"])
        assert fixture["case_type"] in dim["applies_to"]
        assert fixture["strong"].strip() and fixture["weak"].strip() and fixture["strong"] != fixture["weak"]
        assert fixture["expected"] == {"better": "strong", "dimension": fixture["dimension"]}
        assert fixture["held_constant"].strip() and fixture["notes"].strip()
        assert set(fixture["concerns"]) <= {c["id"] for c in RUBRIC["concerns"]}
        if fixture["case_type"] == "whole_document":
            assert fixture.get("brief") and "prefix" not in fixture
        else:
            assert fixture.get("prefix") and "brief" not in fixture

    def test_lengths_matched_unless_padding(self, fixture):
        a, b = len(fixture["strong"].split()), len(fixture["weak"].split())
        if "padding" in fixture["concerns"]:
            assert b > a
        else:
            assert max(a, b) <= 1.6 * min(a, b)

    @pytest.mark.parametrize("strong_as", ["A", "B"])
    def test_renders_in_both_orders(self, fixture, strong_as):
        prompt = rubric.render_fixture(fixture, strong_as=strong_as)
        assert "{{" not in prompt.replace(fixture["strong"], "").replace(fixture["weak"], "")
        first, second = (fixture["strong"], fixture["weak"]) if strong_as == "A" else (fixture["weak"], fixture["strong"])
        assert prompt.index(first) < prompt.index(second)
        assert "### " + fixture["dimension"] + " — " in prompt


def test_genre_fixture_matches_pm_parser():
    f = next(f for f in FIXTURES if f["id"] == "genre_pm_plan_fields")
    strong = parse_plan_prs(f["strong"])
    assert [p["title"] for p in strong] == ["Note subcommand", "Notes in session prompts"]
    assert all(p["description"] and p["tests"] and p["files"] for p in strong)
    assert parse_plan_prs(f["weak"]) == []


def test_consistency_fixture_blocks_disagree_with_prose():
    f = next(f for f in FIXTURES if f["id"] == "consistency_dependency_mismatch")
    strong_deps = {p["title"]: p["depends_on"] for p in parse_plan_prs(f["strong"])}
    weak_deps = {p["title"]: p["depends_on"] for p in parse_plan_prs(f["weak"])}
    assert strong_deps["Evaluation runner"] == weak_deps["Evaluation runner"] == "Case catalog, Rubric"
    assert weak_deps["Case catalog"] == "Rubric" and strong_deps["Case catalog"] == ""


# ---- templates ----------------------------------------------------------------

def test_whole_document_template_renders():
    prompt = rubric.render_judge("whole_document", brief="BRIEF TEXT", document_a="DOC ONE",
                                 document_b="DOC TWO", document_kind="design document")
    assert "BRIEF TEXT" in prompt and "DOC ONE" in prompt and "DOC TWO" in prompt
    assert "Document kind: design document." in prompt
    assert "<prefix>" not in prompt
    assert not rubric.PLACEHOLDER.search(prompt)
    for d in DIMS:
        assert ("### " + d["id"] + " — " in prompt) == ("whole_document" in d["applies_to"])
    assert "### continuity — " not in prompt


def test_continuation_template_renders_with_prefix():
    prompt = rubric.render_judge("continuation", prefix="PREFIX TEXT", document_a="NEXT ONE",
                                 document_b="NEXT TWO", section_request="Write the migration section.")
    assert prompt.index("PREFIX TEXT") < prompt.index("NEXT ONE") < prompt.index("NEXT TWO")
    assert "The writers were asked: Write the migration section." in prompt
    assert not rubric.PLACEHOLDER.search(prompt)
    for d in DIMS:
        assert "### " + d["id"] + " — " in prompt
    assert "For this case type:" in prompt
    assert "imitating the prefix author's personal style" in prompt


def test_templates_do_not_leak_origin():
    for name in rubric.TEMPLATES.values():
        text = (EXP / "rubric" / "templates" / name).read_text().lower()
        for word in ("original", "reference", "generated", "human-written", "llm", "provenance", "source"):
            assert not re.search(r"\b" + word + r"\b", text), word
    fields = set(rubric.PLACEHOLDER.findall("".join(
        (EXP / "rubric" / "templates" / n).read_text() for n in rubric.TEMPLATES.values())))
    assert not fields & {"source", "url", "origin", "provenance", "author"}


def test_document_text_is_not_re_expanded():
    prompt = rubric.render_judge("whole_document", brief="uses {{document_b}} literally",
                                 document_a="A $x {{brief}}", document_b="B")
    assert "uses {{document_b}} literally" in prompt and "A $x {{brief}}" in prompt


def test_render_rejects_wrong_inputs():
    with pytest.raises(ValueError):
        rubric.render_judge("whole_document", prefix="p", document_a="a", document_b="b")
    with pytest.raises(ValueError):
        rubric.render_judge("continuation", brief="b", document_a="a", document_b="b")
    with pytest.raises(ValueError):
        rubric.render_judge("continuation", prefix="p", document_a="", document_b="b")
    with pytest.raises(ValueError):
        rubric.render_judge("pooled", brief="b", document_a="a", document_b="b")
    with pytest.raises(ValueError):
        rubric.render_judge("whole_document", brief="b", document_a="a", document_b="b", dimensions=["continuity"])
    with pytest.raises(ValueError):
        rubric.render_judge("whole_document", brief="b", document_a="a", document_b="b", dimensions=[])


def test_dimension_subset():
    prompt = rubric.render_judge("whole_document", brief="b", document_a="a", document_b="c",
                                 dimensions=["concision", "fidelity"])
    assert "### concision — " in prompt and "### fidelity — " in prompt
    assert "### clarity_and_precision — " not in prompt
    schema = json.loads(prompt.split("in this shape:\n\n", 1)[1].split("\n\nScores use", 1)[0])
    assert [r["dimension"] for r in schema["dimensions"]] == ["fidelity", "concision"]


def test_fill_rejects_missing_and_unused_values():
    with pytest.raises(KeyError):
        rubric.fill("{{a}} {{b}}", {"a": "x"})
    with pytest.raises(KeyError):
        rubric.fill("{{a}}", {"a": "x", "b": "y"})


# ---- judgment contract ------------------------------------------------------

def _judgment(ids, **over):
    j = {"dimensions": [{"dimension": i, "evidence": ["q"], "rationale": "r", "score_a": 4, "score_b": 2,
                         "preference": "A"} for i in ids],
         "overall_preference": "A", "overall_rationale": "r"}
    j.update(over)
    return j


def test_validate_judgment():
    ids = [d["id"] for d in rubric.dimensions_for("continuation")]
    assert rubric.validate_judgment(_judgment(ids), ids) == []
    assert rubric.validate_judgment([], ids)
    assert any("missing dimension" in p for p in rubric.validate_judgment(_judgment(ids[1:]), ids))
    bad = _judgment(ids)
    bad["dimensions"][0]["score_a"] = 7
    bad["dimensions"][1]["preference"] = "first"
    problems = rubric.validate_judgment(bad, ids)
    assert any("score_a" in p for p in problems) and any("preference" in p for p in problems)
    assert rubric.validate_judgment(_judgment(ids, overall_preference=None), ids)
    dup = _judgment(ids)
    dup["dimensions"].append(dict(dup["dimensions"][0]))
    assert any("duplicate" in p for p in rubric.validate_judgment(dup, ids))
    odd = _judgment(ids)
    odd["dimensions"][0]["dimension"] = ["not", "hashable"]
    odd["dimensions"][1]["evidence"] = "q"
    problems = rubric.validate_judgment(odd, ids)
    assert any("malformed" in p for p in problems) and any("evidence" in p for p in problems)


def test_render_fixture_rejects_bad_slot():
    with pytest.raises(ValueError):
        rubric.render_fixture(FIXTURES[0], strong_as="a")


def test_write_doc_replaces_file_by_rename(tmp_path, monkeypatch):
    # A rename never exposes a partial rubric.md to a concurrent reader or --write-doc.
    for name in ("dimensions.json", "references.json", "rubric.md"):
        (tmp_path / name).write_text((EXP / "rubric" / name).read_text())
    (tmp_path / "fixtures").symlink_to(EXP / "rubric" / "fixtures")
    doc = tmp_path / "rubric.md"
    doc.chmod(0o640)
    before = doc.stat().st_ino
    monkeypatch.setattr(rubric, "RUBRIC", tmp_path)
    rubric.write_doc()
    assert doc.read_text() == (EXP / "rubric" / "rubric.md").read_text()
    assert doc.stat().st_ino != before and doc.stat().st_mode & 0o777 == 0o640
    assert sorted(p.name for p in tmp_path.iterdir()) == ["dimensions.json", "fixtures", "references.json", "rubric.md"]


def test_write_doc_interrupt_after_temp_created_leaves_no_temp(tmp_path, monkeypatch):
    # Ctrl-C can land the moment the temp file exists; the cleanup must still know its name and remove it.
    for name in ("dimensions.json", "references.json", "rubric.md"):
        (tmp_path / name).write_text((EXP / "rubric" / name).read_text())
    monkeypatch.setattr(rubric, "RUBRIC", tmp_path)

    def interrupted_open(file, mode="r", *args, **kwargs):
        Path(file).touch()
        raise KeyboardInterrupt

    monkeypatch.setattr(rubric, "open", interrupted_open, raising=False)
    with pytest.raises(KeyboardInterrupt):
        rubric.write_doc()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["dimensions.json", "references.json", "rubric.md"]
    assert (tmp_path / "rubric.md").read_text() == (EXP / "rubric" / "rubric.md").read_text()


def test_write_doc_rejects_missing_markers(tmp_path, monkeypatch):
    (tmp_path / "rubric.md").write_text("hand-written text, markers deleted\n")
    monkeypatch.setattr(rubric, "RUBRIC", tmp_path)
    with pytest.raises(ValueError, match="GENERATED"):
        rubric.write_doc()
    assert (tmp_path / "rubric.md").read_text() == "hand-written text, markers deleted\n"
