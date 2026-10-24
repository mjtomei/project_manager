"""Tests for the technical document quality rubric (experiments/plan-writing/rubric)."""

import importlib.util
import json
import re
from pathlib import Path

import pytest

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
EXTERNAL_KINDS = {"standard", "guideline", "process_template", "rubric", "paper", "book", "tool", "example_source"}
CONCERN_IDS = [c["id"] for c in RUBRIC["concerns"]]


@pytest.mark.parametrize("dim", DIMS, ids=DIM_IDS)
class TestDimension:
    def test_has_definition_example_guidance_question(self, dim):
        assert dim["definition"].strip()
        strong, weak = dim["examples"]["strong"], dim["examples"]["weak"]
        assert strong["text"].strip() and weak["text"].strip() and strong["text"] != weak["text"]
        assert dim["detection_guidance"] and all(g.strip() for g in dim["detection_guidance"])
        assert set(dim["score_anchors"]) == {"1", "3", "5"}

    def test_examples_are_external_quotations(self, dim):
        # Examples are quoted from published sources, never written for the rubric.
        for side in ("strong", "weak"):
            ex = dim["examples"][side]
            assert ex["ref"] in REFS and REFS[ex["ref"]]["url"].startswith("https://")
            assert ex["locator"].strip()

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
    cited = {ref for d in DIMS for ref in d["references"] + [r for m in d["candidate_measures"] for r in m.get("references", [])]
             + [d["examples"][side]["ref"] for side in ("strong", "weak")]}
    cited |= {f["provenance"][part]["ref"] for f in FIXTURES for part in f["provenance"]}
    cited |= {f["source_framing"]["ref"] for f in FIXTURES}
    assert set(RUBRIC["judge_design_references"]) <= set(REFS)
    cited |= set(RUBRIC["judge_design_references"])
    assert set(REFS) <= cited, "uncited references: " + ", ".join(sorted(set(REFS) - cited))


def test_concerns_map_onto_dimensions():
    concerns = {c["id"]: c for c in RUBRIC["concerns"]}
    assert set(RUBRIC["previously_identified_concerns"]) == {
        "padding", "premature_implementation_detail", "poor_progression", "lost_requirements"}
    assert set(RUBRIC["previously_identified_concerns"]) | {"fidelity"} | set(RUBRIC["reader_reported_concerns"]) \
        == set(concerns)
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


@pytest.mark.parametrize("concern", CONCERN_IDS)
def test_fixture_for_every_concern(concern):
    tagged = [f for f in FIXTURES if concern in f["concerns"]]
    assert tagged
    primary = next(c for c in RUBRIC["concerns"] if c["id"] == concern)["primary_dimension"]
    assert any(f["dimension"] == primary for f in tagged)


def test_fixtures_cover_both_case_types():
    assert {f["case_type"] for f in FIXTURES} == set(rubric.CASE_TYPES)


FIXTURE_TEXT_PARTS = ("brief", "prefix", "material", "strong", "weak")
DIRECTION_SOURCES = {"independent_verifier", "annotators", "oversight_body", "maintainer_fix",
                     "reviewer_then_revision", "source_author_rewrite", "author_label"}


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
        assert fixture["pair_kind"] in {"before_after", "erratum", "revision_history", "annotated_dataset"}
        assert set(fixture["concerns"]) <= set(CONCERN_IDS)
        if fixture["case_type"] == "whole_document":
            assert "prefix" not in fixture
        else:
            assert fixture.get("prefix") and "brief" not in fixture and "material" not in fixture

    def test_direction_and_dimension_labels(self, fixture):
        # Which side is better comes from outside the project; which dimensions the pair tests is our
        # reading, so the source's own words for the fault are kept next to it.
        assert fixture["direction_source"] in DIRECTION_SOURCES
        framing = fixture["source_framing"]
        assert framing["text"].strip() and framing["ref"] in REFS and framing["locator"].strip()
        applicable = {d["id"] for d in rubric.dimensions_for(fixture["case_type"])}
        also = fixture["also_moves"]
        assert len(also) == len(set(also)) and set(also) <= applicable - {fixture["dimension"]}

    def test_every_text_is_quoted_from_a_cited_source(self, fixture):
        # Fixture texts are published passages, never written for the rubric: each one names its source.
        parts = [p for p in FIXTURE_TEXT_PARTS if fixture.get(p)]
        assert set(fixture["provenance"]) == set(parts)
        for part in parts:
            prov = fixture["provenance"][part]
            assert prov["ref"] in REFS and prov["locator"].strip()

    def test_length_confound_is_flagged(self, fixture):
        # Published pairs cannot be length-matched; a large difference is flagged so calibration can
        # separate it from verbosity bias. Padding pairs are long on the weak side by design.
        a, b = len(fixture["strong"].split()), len(fixture["weak"].split())
        if "padding" in fixture["concerns"]:
            assert b > a and "length_confound" not in fixture
        else:
            assert fixture.get("length_confound", False) == (max(a, b) > 1.6 * min(a, b))

    @pytest.mark.parametrize("strong_as", ["A", "B"])
    def test_renders_in_both_orders(self, fixture, strong_as):
        prompt = rubric.render_fixture(fixture, strong_as=strong_as)
        assert "{{" not in prompt.replace(fixture["strong"], "").replace(fixture["weak"], "")
        first, second = (fixture["strong"], fixture["weak"]) if strong_as == "A" else (fixture["weak"], fixture["strong"])
        tag = "document" if fixture["case_type"] == "whole_document" else "section"
        assert "<%s_a>\n%s\n</%s_a>" % (tag, first, tag) in prompt
        assert "<%s_b>\n%s\n</%s_b>" % (tag, second, tag) in prompt
        assert "### " + fixture["dimension"] + " — " in prompt
        assert ("No brief is available" in prompt) == (fixture["case_type"] == "whole_document" and not fixture.get("brief"))

    @pytest.mark.parametrize("variant", ["strong", "weak"])
    def test_renders_single(self, fixture, variant):
        prompt = rubric.render_fixture_single(fixture, variant)
        tag = "document" if fixture["case_type"] == "whole_document" else "section"
        assert "<%s>\n%s\n</%s>" % (tag, fixture[variant], tag) in prompt
        assert prompt.count("<" + tag + ">") == 1 and "<document_a>" not in prompt
        assert "{{" not in prompt.replace(fixture[variant], "")
        assert "### " + fixture["dimension"] + " — " in prompt

    def test_prompt_does_not_leak_provenance(self, fixture):
        prompt = rubric.render_fixture(fixture)
        for part in fixture["provenance"].values():
            ref = REFS[part["ref"]]
            assert ref["url"] not in prompt and part["ref"] not in prompt
        assert fixture["id"] not in prompt
        framing = fixture["source_framing"]["text"]
        if not any(framing in fixture[p] for p in FIXTURE_TEXT_PARTS if fixture.get(p)):
            assert framing not in prompt


def test_fixtures_include_a_report_judged_against_material():
    f = next(f for f in FIXTURES if f.get("material"))
    declared = set(re.findall(r"^func (?:\(r \*Rand\) )?(\w+)", f["material"], re.M))
    named = lambda text: set(re.findall(r"\b(?:Int|Uint)\w*", text.split("math/rand/v2:", 1)[1]))
    assert named(f["strong"]) <= declared
    assert named(f["weak"]) - declared == {"Uint"}


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
    assert "The request for this section: Write the migration section." in prompt
    assert not rubric.PLACEHOLDER.search(prompt)
    for d in DIMS:
        assert "### " + d["id"] + " — " in prompt
    assert "imitating the prefix author's personal style" in prompt


ALL_TEMPLATES = list(rubric.TEMPLATES.values()) + list(rubric.SINGLE_TEMPLATES.values())


def test_templates_do_not_leak_origin():
    for name in ALL_TEMPLATES:
        text = (EXP / "rubric" / "templates" / name).read_text().lower()
        for word in ("original", "reference", "generated", "human-written", "llm", "provenance", "source"):
            assert not re.search(r"\b" + word + r"\b", text), word
    fields = set(rubric.PLACEHOLDER.findall("".join(
        (EXP / "rubric" / "templates" / n).read_text() for n in ALL_TEMPLATES)))
    assert not fields & {"source", "url", "origin", "provenance", "author"}


def test_single_templates_render():
    prompt = rubric.render_single("whole_document", brief="BRIEF TEXT", document="ONLY DOC",
                                  document_kind="sign-off report")
    assert prompt.index("BRIEF TEXT") < prompt.index("ONLY DOC")
    assert "Document kind: sign-off report." in prompt
    assert "Document A" not in prompt and "preference" not in prompt and "<material>" not in prompt
    assert not rubric.PLACEHOLDER.search(prompt)
    schema = json.loads(prompt.split("in this shape:\n\n", 1)[1].split("\n\nScores are integers", 1)[0])
    assert set(schema) == {"dimensions", "overall_score", "overall_rationale"}
    assert all(set(r) == {"dimension", "evidence", "rationale", "score"} for r in schema["dimensions"])
    assert "### continuity — " not in prompt
    prompt = rubric.render_single("continuation", prefix="PREFIX TEXT", document="NEXT ONLY",
                                  section_request="Write the migration section.")
    assert prompt.index("PREFIX TEXT") < prompt.index("NEXT ONLY")
    assert "The request for this section: Write the migration section." in prompt
    assert "### continuity — " in prompt and "imitating the prefix author's personal style" in prompt
    assert not rubric.PLACEHOLDER.search(prompt)


def test_material_for_reports():
    for prompt in (rubric.render_judge("whole_document", brief="B", document_a="a", document_b="b",
                                       material="MATERIAL TEXT {{brief}}"),
                   rubric.render_single("whole_document", brief="B", document="a", material="MATERIAL TEXT {{brief}}")):
        assert prompt.index("</brief>") < prompt.index("<material>\nMATERIAL TEXT {{brief}}\n</material>") \
            < prompt.index("<document")
        assert "## Material the document describes" in prompt
    with pytest.raises(ValueError):
        rubric.render_judge("continuation", prefix="p", document_a="a", document_b="b", material="m")
    with pytest.raises(ValueError):
        rubric.render_single("continuation", prefix="p", document="a", material="m")


def test_render_single_rejects_wrong_inputs():
    with pytest.raises(ValueError):
        rubric.render_single("whole_document", brief="b", document="")
    with pytest.raises(ValueError):
        rubric.render_single("whole_document", prefix="p", document="a")
    with pytest.raises(ValueError):
        rubric.render_single("continuation", brief="b", document="a")
    with pytest.raises(ValueError):
        rubric.render_single("whole_document", brief="b", document="a", dimensions=[])


def test_prompt_carries_only_definitions_and_anchors():
    # Detection guidance, track notes and not-a-fault lists are reference material, not judge input.
    for case_type in rubric.CASE_TYPES:
        kw = {"brief": "b"} if case_type == "whole_document" else {"prefix": "p"}
        prompt = rubric.render_judge(case_type, document_a="a", document_b="c", **kw)
        for d in rubric.dimensions_for(case_type):
            assert d["definition"] in prompt
            assert all(v in prompt for v in d["score_anchors"].values())
            texts = d["detection_guidance"] + d["not_a_defect"] + list(d.get("track_notes", {}).values())
            assert not any(t in prompt for t in texts), d["id"]


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
    # A missing brief must be declared, never silently rendered empty.
    with pytest.raises(ValueError):
        rubric.render_judge("whole_document", document_a="a", document_b="b")
    with pytest.raises(ValueError):
        rubric.render_judge("whole_document", brief="b", no_brief=True, document_a="a", document_b="b")
    with pytest.raises(ValueError):
        rubric.render_judge("continuation", prefix="p", no_brief=True, document_a="a", document_b="b")


def test_no_brief_rendering():
    prompt = rubric.render_judge("whole_document", no_brief=True, document_a="a", document_b="b")
    assert "No brief is available." in prompt and "<brief>" not in prompt
    prompt = rubric.render_single("whole_document", no_brief=True, document="a", material="m")
    assert "establishes and the material it describes." in prompt and "<material>\nm\n</material>" in prompt


def test_dimension_subset():
    prompt = rubric.render_judge("whole_document", brief="b", document_a="a", document_b="c",
                                 dimensions=["concision", "fidelity"])
    assert "### concision — " in prompt and "### fidelity — " in prompt
    assert "### clarity_and_precision — " not in prompt
    schema = json.loads(prompt.split("in this shape:\n\n", 1)[1].split("\n\nScores are integers", 1)[0])
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


def test_validate_single_judgment():
    ids = [d["id"] for d in rubric.dimensions_for("whole_document")]
    good = {"dimensions": [{"dimension": i, "evidence": ["q"], "rationale": "r", "score": 3} for i in ids],
            "overall_score": 4, "overall_rationale": "r"}
    assert rubric.validate_judgment(good, ids, single=True) == []
    # A paired reply is not a valid single reply, and the reverse.
    assert rubric.validate_judgment(_judgment(ids), ids, single=True)
    assert rubric.validate_judgment(good, ids)
    bad = json.loads(json.dumps(good))
    bad["dimensions"][0]["score"] = True
    bad["overall_score"] = 6
    problems = rubric.validate_judgment(bad, ids, single=True)
    assert any(": score not" in p for p in problems) and any("overall_score" in p for p in problems)


def test_render_fixture_rejects_bad_slot():
    with pytest.raises(ValueError):
        rubric.render_fixture(FIXTURES[0], strong_as="a")
    with pytest.raises(ValueError):
        rubric.render_fixture_single(FIXTURES[0], variant="A")


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
