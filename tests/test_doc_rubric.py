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
EXTERNAL_KINDS = {"standard", "guideline", "process_template", "rubric", "paper", "book", "tool", "example_source", "dataset",
                  "secondary_source", "secondary_notes", "course_material", "encyclopedia", "thesis"}
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
    cited |= {r for f in rubric.load_families()["families"] for r in f["sources"]}
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

    @pytest.mark.parametrize("single", [False, True])
    def test_own_pair_is_held_out_of_the_examples(self, fixture, single):
        prompt = rubric.render_fixture_single(fixture) if single else rubric.render_fixture(fixture)
        criteria = prompt.split("\n## Criteria\n", 1)[1].split("\n## Scoring\n", 1)[0]
        assert not rubric._overlaps(criteria, [fixture["strong"], fixture["weak"]])

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
    schema = _schema(prompt)
    assert set(schema) == {"criteria", "overall_score"}
    assert all(set(r) == {"criterion", "score"} for r in schema["criteria"])
    assert "### continuity — " not in prompt
    prompt = rubric.render_single("continuation", prefix="PREFIX TEXT", document="NEXT ONLY",
                                  section_request="Write the migration section.")
    assert prompt.index("PREFIX TEXT") < prompt.index("NEXT ONLY")
    assert "The request for this section: Write the migration section." in prompt
    assert "### continuity — " in prompt
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


def test_prompt_carries_definitions_anchors_and_examples_only():
    # Detection guidance, track notes and not-a-fault lists are reference material, not judge input.
    for case_type in rubric.CASE_TYPES:
        kw = {"brief": "b"} if case_type == "whole_document" else {"prefix": "p"}
        prompt = rubric.render_judge(case_type, document_a="a", document_b="c", **kw)
        for d in rubric.dimensions_for(case_type):
            assert d["definition"] in prompt
            assert all(v in prompt for v in d["score_anchors"].values())
            ex = d["examples"]
            assert ex["strong"]["text"] in prompt and ex["weak"]["text"] in prompt
            if ex.get("context"):
                assert ex["context"]["text"] in prompt
            texts = d["detection_guidance"] + d["not_a_defect"] + list(d.get("track_notes", {}).values())
            texts += [ex["strong"].get("note", "")]
            assert not any(t and t in prompt for t in texts), d["id"]


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
    schema = _schema(prompt)
    assert [r["criterion"] for r in schema["criteria"]] == ["fidelity", "concision"]
    assert rubric.render_judge("whole_document", brief="b", document_a="a", document_b="c",
                               criteria=["concision", "fidelity"]) == prompt
    with pytest.raises(ValueError):
        rubric.render_judge("whole_document", brief="b", document_a="a", document_b="c",
                            criteria=["concision"], dimensions=["concision"])


def _schema(prompt):
    return json.loads(prompt.split("in this shape:\n\n", 1)[1].split("\n\nEach score uses", 1)[0])


def test_fill_rejects_missing_and_unused_values():
    with pytest.raises(KeyError):
        rubric.fill("{{a}} {{b}}", {"a": "x"})
    with pytest.raises(KeyError):
        rubric.fill("{{a}}", {"a": "x", "b": "y"})


# ---- judgment contract ------------------------------------------------------

def _judgment(ids, **over):
    j = {"criteria": [{"criterion": i, "score_a": 4, "score_b": 2, "preference": "A"} for i in ids],
         "overall_preference": "A"}
    j.update(over)
    return j


def test_validate_judgment():
    ids = [d["id"] for d in rubric.dimensions_for("continuation")]
    assert rubric.validate_judgment(_judgment(ids), ids) == []
    # No evidence or rationale is required, and extra keys a judge adds are not an error.
    chatty = _judgment(ids)
    chatty["criteria"][0]["rationale"] = "r"
    assert rubric.validate_judgment(chatty, ids) == []
    assert rubric.validate_judgment([], ids)
    assert any("missing criterion" in p for p in rubric.validate_judgment(_judgment(ids[1:]), ids))
    bad = _judgment(ids)
    bad["criteria"][0]["score_a"] = 7
    bad["criteria"][1]["preference"] = "first"
    problems = rubric.validate_judgment(bad, ids)
    assert any("score_a" in p for p in problems) and any("preference" in p for p in problems)
    assert rubric.validate_judgment(_judgment(ids, overall_preference=None), ids)
    dup = _judgment(ids)
    dup["criteria"].append(dict(dup["criteria"][0]))
    assert any("duplicate" in p for p in rubric.validate_judgment(dup, ids))
    odd = _judgment(ids)
    odd["criteria"][0]["criterion"] = ["not", "hashable"]
    assert any("malformed" in p for p in rubric.validate_judgment(odd, ids))


def test_validate_uses_each_criterion_scale():
    crit = [{"id": "four_level", "scale": {"min": 1, "max": 4}}, {"id": "six_level", "scale": {"min": 1, "max": 6}}]
    ok = {"criteria": [{"criterion": "four_level", "score": 4}, {"criterion": "six_level", "score": 6}],
          "overall_score": 3}
    assert rubric.validate_judgment(ok, crit, single=True) == []
    ok["criteria"][0]["score"] = 5
    assert any("four_level: score not an integer 1-4" in p for p in rubric.validate_judgment(ok, crit, single=True))


def test_validate_single_judgment():
    ids = [d["id"] for d in rubric.dimensions_for("whole_document")]
    good = {"criteria": [{"criterion": i, "score": 3} for i in ids], "overall_score": 4}
    assert rubric.validate_judgment(good, ids, single=True) == []
    # A paired reply is not a valid single reply, and the reverse.
    assert rubric.validate_judgment(_judgment(ids), ids, single=True)
    assert rubric.validate_judgment(good, ids)
    bad = json.loads(json.dumps(good))
    bad["criteria"][0]["score"] = True
    bad["overall_score"] = 6
    problems = rubric.validate_judgment(bad, ids, single=True)
    assert any(": score not" in p for p in problems) and any("overall_score" in p for p in problems)


def test_extract_judgment_takes_the_final_json_object():
    obj = {"criteria": [{"criterion": "x", "score": 3}], "overall_score": 3}
    text = json.dumps(obj)
    assert rubric.extract_judgment(text) == obj
    assert rubric.extract_judgment("Notes {not json} and {\"a\": 1}.\n\n" + text + "\n") == obj
    assert rubric.extract_judgment("Notes.\n```json\n" + json.dumps(obj, indent=2) + "\n```\n") == obj
    for bad in ("no json here", text + "\nTrailing words.", "[1, 2]"):
        with pytest.raises(ValueError):
            rubric.extract_judgment(bad)


def test_render_fixture_rejects_bad_slot():
    with pytest.raises(ValueError):
        rubric.render_fixture(FIXTURES[0], strong_as="a")
    with pytest.raises(ValueError):
        rubric.render_fixture_single(FIXTURES[0], variant="A")


RUBRIC_FILES = ("dimensions.json", "references.json", "families.json", "examples.json", "rubric.md", "families.md")


def _copy_rubric(tmp_path):
    for name in RUBRIC_FILES:
        (tmp_path / name).write_text((EXP / "rubric" / name).read_text())
    for name in ("fixtures", "families"):
        (tmp_path / name).symlink_to(EXP / "rubric" / name)


def test_write_doc_replaces_file_by_rename(tmp_path, monkeypatch):
    # A rename never exposes a partial rubric.md or families.md to a concurrent reader or --write-doc.
    _copy_rubric(tmp_path)
    doc = tmp_path / "rubric.md"
    doc.chmod(0o640)
    before = doc.stat().st_ino
    monkeypatch.setattr(rubric, "RUBRIC", tmp_path)
    rubric.write_doc()
    assert doc.read_text() == (EXP / "rubric" / "rubric.md").read_text()
    assert doc.stat().st_ino != before and doc.stat().st_mode & 0o777 == 0o640
    assert (tmp_path / "families.md").read_text() == (EXP / "rubric" / "families.md").read_text()
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(RUBRIC_FILES + ("fixtures", "families"))


def test_write_doc_interrupt_after_temp_created_leaves_no_temp(tmp_path, monkeypatch):
    # Ctrl-C can land the moment the temp file exists; the cleanup must still know its name and remove it.
    _copy_rubric(tmp_path)
    monkeypatch.setattr(rubric, "RUBRIC", tmp_path)

    def interrupted_open(file, mode="r", *args, **kwargs):
        Path(file).touch()
        raise KeyboardInterrupt

    monkeypatch.setattr(rubric, "open", interrupted_open, raising=False)
    with pytest.raises(KeyboardInterrupt):
        rubric.write_doc()
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(RUBRIC_FILES + ("fixtures", "families"))
    assert (tmp_path / "rubric.md").read_text() == (EXP / "rubric" / "rubric.md").read_text()


def test_write_doc_rejects_missing_markers(tmp_path, monkeypatch):
    (tmp_path / "rubric.md").write_text("hand-written text, markers deleted\n")
    monkeypatch.setattr(rubric, "RUBRIC", tmp_path)
    with pytest.raises(ValueError, match="GENERATED"):
        rubric.write_doc()
    assert (tmp_path / "rubric.md").read_text() == "hand-written text, markers deleted\n"


# ---- family rubrics -----------------------------------------------------------

FAMILIES = rubric.load_families()
POOL = rubric.load_examples()
RUBRIC_IDS = rubric.list_rubrics()


def _family_data(fid):
    return json.loads((EXP / "rubric" / "families" / (fid + ".json")).read_text())


def test_families_index():
    ids = [f["id"] for f in FAMILIES["families"]]
    assert len(ids) == len(set(ids))
    assert RUBRIC_IDS == ["aggregate"] + [f["id"] for f in FAMILIES["families"] if f["rubric"]]
    files = {p.stem for p in (EXP / "rubric" / "families").glob("*.json")}
    assert files == {f["id"] for f in FAMILIES["families"] if f["rubric"]}
    for f in FAMILIES["families"]:
        assert f["contributes"] and set(f["sources"]) <= set(REFS), f["id"]
        # A family that supplies methods, bias checks or examples is listed as such, with no invented criteria.
        assert ("criteria" in f["contributes"]) == f["rubric"]
        for n in f["not_criteria"]:
            assert n["source_ref"] in REFS and n["contributes"] in {"methods", "bias_checks", "examples"} and n["note"].strip()
    assert {"methods", "bias_checks", "examples"} <= {c for f in FAMILIES["families"] for c in f["contributes"]}
    generic = FAMILIES["generic_levels"]
    assert set(map(int, generic["levels"])) <= set(range(generic["scale"]["min"], generic["scale"]["max"] + 1))


@pytest.mark.parametrize("fid", RUBRIC_IDS[1:])
def test_family_criteria_are_sourced(fid):
    data = _family_data(fid)
    ids = [c["id"] for c in data["criteria"]]
    assert ids and len(ids) == len(set(ids)) and all(re.fullmatch(r"[a-z0-9_]+", i) for i in ids)
    for c in data["criteria"]:
        d = c["definition"]
        assert c["name"].strip() and d["ref"] in REFS and d["locator"].strip() and set(d.get("via", [])) <= set(REFS)
        # Every criterion is stated by its source; a criterion may lack prose only if the source publishes levels.
        assert (d["text"] or "").strip() or c["levels"] or c.get("levels_restricted"), c["id"]
        # Level tables from sources that forbid republishing never reach the repo.
        if REFS[d["ref"]].get("licence") == "restricted":
            assert not c["levels"] and "sub_criteria" not in c
            if c.get("levels_restricted"):
                assert c["published_scale"]["min"] < c["published_scale"]["max"]
        if c["levels"]:
            lo, hi = c["scale"]["min"], c["scale"]["max"]
            assert {int(k) for k in c["levels"]} <= set(range(lo, hi + 1)) and all(v.strip() for v in c["levels"].values())
        for e in c["examples"]:
            assert e in POOL, (c["id"], e)


def test_example_pool():
    used = {e for fid in RUBRIC_IDS[1:] for c in _family_data(fid)["criteria"] for e in c["examples"]}
    assert used == set(POOL)
    for e in POOL.values():
        sides = [s for s in (e["stronger"], e["weaker"]) if s]
        assert sides and all(s["text"].strip() and s["ref"] in REFS and s["locator"].strip() for s in sides)
        if e["context"]:
            assert e["context"]["text"].strip() and e["context"]["ref"] in REFS
        if e["scores"]:
            assert e["scores"]["text"].strip() and e["scores"]["locator"].strip()


def test_family_refs_are_cited_from_the_index():
    cited = {r for f in FAMILIES["families"] for r in f["sources"]}
    for fid in RUBRIC_IDS[1:]:
        assert {c["definition"]["ref"] for c in _family_data(fid)["criteria"]} <= cited
    assert {(e["stronger"] or e["weaker"])["ref"] for e in POOL.values()} <= cited


@pytest.mark.parametrize("rid", RUBRIC_IDS)
@pytest.mark.parametrize("case_type", rubric.CASE_TYPES)
def test_every_rubric_renders_paired_and_single(rid, case_type):
    kw = {"brief": "BRIEF"} if case_type == "whole_document" else {"prefix": "PREFIX"}
    crit = rubric.criteria_for(case_type, rid)
    for prompt, single in ((rubric.render_judge(case_type, document_a="DOC A", document_b="DOC B", rubric_id=rid, **kw), False),
                           (rubric.render_single(case_type, document="DOC", rubric_id=rid, **kw), True)):
        assert not rubric.PLACEHOLDER.search(prompt.split("## Criteria", 1)[0] + prompt.split("## Scoring", 1)[1])
        for c in crit:
            assert "### " + c["id"] + " — " + c["name"] in prompt
        schema = _schema(prompt)
        assert [r["criterion"] for r in schema["criteria"]] == [c["id"] for c in crit]
        reply = "Notes first.\n\n" + json.dumps(schema).replace('"A|B|tie"', '"tie"')
        assert rubric.validate_judgment(rubric.extract_judgment(reply), crit, single=single) == []
        # No evidence quotations or rationales are asked for.
        assert '"evidence"' not in prompt and '"rationale"' not in prompt and "quote or point" not in prompt


def test_family_prompt_carries_sources_definitions_and_levels():
    crit = rubric.criteria_for("whole_document", "analytic_writing_rubrics")
    prompt = rubric.render_judge("whole_document", brief="b", document_a="a", document_b="c",
                                 rubric_id="analytic_writing_rubrics")
    for c in crit:
        if c["definition"]:
            assert c["definition"] in prompt
        assert all(v in prompt for v in c["levels"].values())
        assert "Scale %d to %d:" % (c["scale"]["min"], c["scale"]["max"]) in prompt


def test_levels_source_is_recorded(monkeypatch):
    generic = FAMILIES["generic_levels"]["levels"]
    monkeypatch.setattr(rubric, "load_restricted_levels", lambda: {})
    for fid in RUBRIC_IDS[1:]:
        raw = {c["id"]: c for c in _family_data(fid)["criteria"]}
        for c in rubric.criteria_for("whole_document", fid):
            assert c["levels_source"] == ("published" if raw[c["id"]]["levels"] else "generic")
            assert (c["levels"] == generic) == (c["levels_source"] == "generic")


def test_restricted_levels_used_when_present(monkeypatch):
    fid = "analytic_writing_rubrics"
    raw = next(c for c in _family_data(fid)["criteria"] if c.get("levels_restricted"))
    levels = {str(k): "LEVEL %d" % k for k in range(raw["published_scale"]["min"], raw["published_scale"]["max"] + 1)}
    monkeypatch.setattr(rubric, "load_restricted_levels", lambda: {fid: {raw["id"]: {"levels": levels}}})
    c = next(c for c in rubric.criteria_for("whole_document", fid) if c["id"] == raw["id"])
    assert c["levels_source"] == "restricted_local" and c["levels"] == levels and c["scale"] == raw["published_scale"]


def test_source_filter_within_a_family():
    pep = rubric.criteria_for("whole_document", "process_templates", sources=["pep1"])
    assert pep and all(c["source_ref"] == "pep1" for c in pep)
    prompt = rubric.render_judge("whole_document", brief="b", document_a="a", document_b="c",
                                 rubric_id="process_templates", sources=["pep1"])
    assert [r["criterion"] for r in _schema(prompt)["criteria"]] == [c["id"] for c in pep]
    for bad in ([], ["no-such-ref"]):
        with pytest.raises(ValueError):
            rubric.criteria_for("whole_document", "process_templates", sources=bad)
    with pytest.raises(ValueError):
        rubric.criteria_for("whole_document", "aggregate", sources=["pep1"])
    with pytest.raises(ValueError):
        rubric.load_rubric_set("judge_reliability")


def test_families_doc_is_current():
    assert (EXP / "rubric" / "families.md").read_text() == rubric.families_markdown(), \
        "run: python3 experiments/plan-writing/rubric.py --write-doc"


@pytest.mark.parametrize("rid", RUBRIC_IDS)
def test_fixtures_render_with_every_rubric(rid):
    for fixture in FIXTURES:
        for prompt in (rubric.render_fixture(fixture, rubric_id=rid), rubric.render_fixture_single(fixture, rubric_id=rid)):
            criteria = prompt.split("\n## Criteria\n", 1)[1].split("\n## Scoring\n", 1)[0]
            assert not rubric._overlaps(criteria, [fixture["strong"], fixture["weak"]])
