"""Technical document quality rubric: loading, fixtures and judge-prompt rendering.

The rubric lives in rubric/ (rubric.md explains it; dimensions.json and references.json are
the machine-readable source). render_judge() fills the blinded paired templates for the
whole_document and continuation tracks, and render_single() the single-document ones; ordering
and origin masking stay with the caller, which only ever passes candidates as A and B (or one
document). Stdlib only, so the runner can import it without collect.py's dependencies.
"""

import json
import os
import re
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUBRIC = HERE / "rubric"
CASE_TYPES = ("whole_document", "continuation")
TEMPLATES = {"whole_document": "whole_document.md", "continuation": "continuation.md"}
SINGLE_TEMPLATES = {"whole_document": "whole_document_single.md", "continuation": "continuation_single.md"}
PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")
PREFERENCES = ("A", "B", "tie")


def load_rubric():
    return json.loads((RUBRIC / "dimensions.json").read_text())


def load_references():
    return {r["id"]: r for r in json.loads((RUBRIC / "references.json").read_text())["references"]}


def load_fixtures():
    return [json.loads(p.read_text()) for p in sorted((RUBRIC / "fixtures").glob("*.json"))]


def dimensions_for(case_type, ids=None, rubric=None):
    if case_type not in CASE_TYPES:
        raise ValueError("Unknown case type: " + str(case_type))
    dims = [d for d in (rubric or load_rubric())["dimensions"] if case_type in d["applies_to"]]
    if ids is not None:
        if not ids:
            raise ValueError("Empty dimension subset for " + case_type)
        known = {d["id"] for d in dims}
        unknown = [i for i in ids if i not in known]
        if unknown:
            raise ValueError("Dimensions not applicable to " + case_type + ": " + ", ".join(unknown))
        dims = [d for d in dims if d["id"] in ids]
    return dims


def fill(template, values):
    """Single-pass substitution: document text containing {{...}} is never re-expanded."""
    used = set()

    def sub(match):
        key = match.group(1)
        if key not in values:
            raise KeyError("Template placeholder has no value: " + key)
        used.add(key)
        return values[key]

    out = PLACEHOLDER.sub(sub, template)
    unused = set(values) - used
    if unused:
        raise KeyError("Values not used by template: " + ", ".join(sorted(unused)))
    return out


def dimension_block(dims, case_type):
    parts = []
    for d in dims:
        lines = ["### " + d["id"] + " — " + d["name"], "", d["definition"]]
        note = d.get("track_notes", {}).get(case_type)
        if note:
            lines.append("For this case type: " + note)
        lines += ["", "Question: " + d["judge_question"], "", "Look for:"]
        lines += ["- " + g for g in d["detection_guidance"]]
        if d.get("not_a_defect"):
            lines += ["", "Not a fault:"] + ["- " + g for g in d["not_a_defect"]]
        lines += ["", "Score anchors:"] + ["- " + k + ": " + v for k, v in sorted(d["score_anchors"].items())]
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def output_schema(dims, single=False):
    if single:
        example = {"dimensions": [{"dimension": d["id"], "evidence": ["<quoted or located passages>"],
                                   "rationale": "<why>", "score": 3} for d in dims],
                   "overall_score": 3, "overall_rationale": "<why>"}
    else:
        example = {"dimensions": [{"dimension": d["id"], "evidence": ["<quoted or located passages>"],
                                   "rationale": "<why>", "score_a": 3, "score_b": 3,
                                   "preference": "A|B|tie"} for d in dims],
                   "overall_preference": "A|B|tie", "overall_rationale": "<why>"}
    return json.dumps(example, indent=2, ensure_ascii=False)


def _common_values(case_type, single, brief, prefix, section_request, document_kind, material, no_brief,
                   dimensions, rubric):
    dims = dimensions_for(case_type, dimensions, rubric)
    values = {"document_kind_line": (" Document kind: " + document_kind + "." if document_kind else ""),
              "dimension_block": dimension_block(dims, case_type),
              "output_schema": output_schema(dims, single)}
    if case_type == "whole_document":
        if prefix is not None:
            raise ValueError("whole_document cases take a brief and no prefix")
        if bool(brief) == bool(no_brief):
            raise ValueError("whole_document cases take a brief, or no_brief=True when none exists")
        if brief:
            values["brief_block"] = "## Brief\n\n<brief>\n" + brief + "\n</brief>\n"
        else:
            values["brief_block"] = ("## Brief\n\nNo brief is available for this case. Where the rules or dimensions below"
                                     " refer to the brief, judge against what the document itself establishes"
                                     + (" and the material it describes" if material else "") + ".\n")
        values["material_rule"] = " and the material the document describes" if material else ""
        values["material_block"] = ("\n## Material the document describes\n\n<material>\n" + material
                                    + "\n</material>\n" if material else "")
    else:
        if not prefix or brief is not None or no_brief:
            raise ValueError("continuation cases take a prefix and no brief")
        if material:
            raise ValueError("continuation cases take no material; the prefix is their input")
        values["prefix"] = prefix
        values["section_request_line"] = (" The writers were asked: " + section_request if section_request else "")
    return values


def render_judge(case_type, *, document_a, document_b, brief=None, prefix=None,
                 section_request=None, document_kind=None, material=None, no_brief=False, dimensions=None,
                 rubric=None):
    """Render the judge prompt for one blinded pair.

    whole_document needs brief; continuation needs prefix and may take the section_request
    the generator was given. dimensions limits the rubric to the listed ids. Catalog cases of
    type pm_plan are whole-document cases: pass the instruction and conversation turns as the
    brief. Brief attachments belong in the brief text, since fidelity and coverage are judged
    against it. Reports about existing work (digests, sign-off and QA reports) are whole-document
    cases too: the brief is the request and material is what the report describes (diffs, code
    excerpts, logs, test output), which fidelity is then judged against as well. no_brief=True
    renders a whole-document case that has no brief at all (some published example pairs); the
    judge is told so rather than shown an empty brief.
    """
    values = _common_values(case_type, False, brief, prefix, section_request, document_kind, material,
                            no_brief, dimensions, rubric)
    if not document_a or not document_b:
        raise ValueError("Both candidates are required")
    if case_type == "whole_document":
        values.update(document_a=document_a, document_b=document_b)
    else:
        values.update(section_a=document_a, section_b=document_b)
    return fill((RUBRIC / "templates" / TEMPLATES[case_type]).read_text(), values)


def render_single(case_type, *, document, brief=None, prefix=None, section_request=None,
                  document_kind=None, material=None, no_brief=False, dimensions=None, rubric=None):
    """Render the judge prompt for one document scored on its own (no comparison).

    Takes the same inputs as render_judge() with one document in place of the pair, for cases
    with nothing to compare against, such as a single report. The reply carries a score per
    dimension and an overall_score; check it with validate_judgment(..., single=True).
    """
    values = _common_values(case_type, True, brief, prefix, section_request, document_kind, material,
                            no_brief, dimensions, rubric)
    if not document:
        raise ValueError("A document is required")
    values["document" if case_type == "whole_document" else "section"] = document
    return fill((RUBRIC / "templates" / SINGLE_TEMPLATES[case_type]).read_text(), values)


def render_fixture(fixture, strong_as="A", rubric=None):
    """Render a fixture pair with its strong variant in slot strong_as ("A" or "B")."""
    if strong_as not in ("A", "B"):
        raise ValueError("strong_as must be A or B")
    a, b = ((fixture["strong"], fixture["weak"]) if strong_as == "A" else (fixture["weak"], fixture["strong"]))
    return render_judge(fixture["case_type"], document_a=a, document_b=b, brief=fixture.get("brief"),
                        prefix=fixture.get("prefix"), section_request=fixture.get("section_request"),
                        document_kind=fixture.get("document_kind"), material=fixture.get("material"),
                        no_brief=_fixture_has_no_brief(fixture), rubric=rubric)


def render_fixture_single(fixture, variant="strong", rubric=None):
    """Render one variant of a fixture ("strong" or "weak") for single-document scoring."""
    if variant not in ("strong", "weak"):
        raise ValueError("variant must be strong or weak")
    return render_single(fixture["case_type"], document=fixture[variant], brief=fixture.get("brief"),
                         prefix=fixture.get("prefix"), section_request=fixture.get("section_request"),
                         document_kind=fixture.get("document_kind"), material=fixture.get("material"),
                         no_brief=_fixture_has_no_brief(fixture), rubric=rubric)


def _fixture_has_no_brief(fixture):
    return fixture["case_type"] == "whole_document" and not fixture.get("brief")


def reference_markdown(rubric=None, references=None):
    """The generated per-dimension part of rubric.md, between the GENERATED markers."""
    rubric = rubric or load_rubric()
    refs = references or load_references()
    fixtures, also = {}, {}
    for f in load_fixtures():
        fixtures.setdefault(f["dimension"], []).append(f["id"])
        for dim in f["also_moves"]:
            also.setdefault(dim, []).append(f["id"])
    out = ["| Dimension | Case types | Readiness | Automatic candidates | Concerns |", "|---|---|---|---|---|"]
    for d in rubric["dimensions"]:
        auto = [m["name"] + (" (bias covariate)" if m.get("role") == "bias_covariate" else "")
                for m in d["candidate_measures"] if m["status"] == "automatic_candidate"]
        out.append("| " + " | ".join([d["id"], ", ".join(d["applies_to"]), d["measure_readiness"],
                                       ", ".join(auto) or "—", ", ".join(d["maps_concerns"]) or "—"]) + " |")
    for d in rubric["dimensions"]:
        out += ["", "### " + d["id"] + " — " + d["name"], "", "**Definition.** " + d["definition"]]
        for case_type, note in d.get("track_notes", {}).items():
            out += ["", "**" + case_type.replace("_", " ").capitalize() + ".** " + note]
        out += ["", "**Derived from.** " + d["derived_from"], "",
                "**Sources.** " + "; ".join("[" + refs[r]["title"] + "](" + refs[r]["url"] + ")" for r in d["references"]),
                "", "**Detection guidance.**", ""] + ["- " + g for g in d["detection_guidance"]]
        out += ["", "**Not a fault.**", ""] + ["- " + g for g in d["not_a_defect"]]
        for side, label in (("strong", "stronger"), ("weak", "weaker")):
            ex = d["examples"][side]
            ref = refs[ex["ref"]]
            out += ["", "**Example, " + label + "** ([" + ref["title"] + "](" + ref["url"] + "), " + ex["locator"] + ")"
                    + (". " + ex["note"] if ex.get("note") else "") + "", ""]
            out += ["> " + line if line.strip() else ">" for line in ex["text"].strip().split("\n")]
        out += ["", "**Score anchors.** " + " ".join(k + ": " + v for k, v in sorted(d["score_anchors"].items())),
                "", "**Candidate measures** (readiness: " + d["measure_readiness"] + ").", ""]
        for m in d["candidate_measures"]:
            role = ", bias covariate" if m.get("role") == "bias_covariate" else ""
            out.append("- `" + m["name"] + "` (" + m["kind"] + ", " + m["status"] + role + "): " + m["description"])
        out += ["", "**Fixtures.** " + ", ".join("`fixtures/" + i + ".json`" for i in fixtures.get(d["id"], []))]
        if also.get(d["id"]):
            out[-1] += ". May also move: " + ", ".join("`" + i + "`" for i in also[d["id"]])
    return "\n".join(out) + "\n"


GENERATED_START = "<!-- GENERATED: python3 experiments/plan-writing/rubric.py --write-doc -->"
GENERATED_END = "<!-- END GENERATED -->"


def write_doc():
    path = RUBRIC / "rubric.md"
    text = path.read_text()
    if text.count(GENERATED_START) != 1 or text.count(GENERATED_END) != 1 or \
            text.index(GENERATED_START) > text.index(GENERATED_END):
        raise ValueError(str(path) + " needs exactly one GENERATED start marker followed by one end marker")
    head, rest = text.split(GENERATED_START, 1)
    tail = rest.split(GENERATED_END, 1)[1]
    new_text = head + GENERATED_START + "\n" + reference_markdown() + GENERATED_END + tail
    # Replace by rename so a concurrent reader (a test, another --write-doc) never sees a partial file.
    # The temp name is fixed before the file exists, so a Ctrl-C right after creation still removes it
    # (mkstemp can be interrupted after creating its file but before returning the name).
    # pid + thread id keep concurrent writers apart; a same-named file can only be left by a dead process.
    tmp = path.with_name(".rubric.md.%d.%d" % (os.getpid(), threading.get_ident()))
    try:
        with open(tmp, "w") as f:
            f.write(new_text)
        os.chmod(tmp, os.stat(path).st_mode & 0o7777)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def validate_judgment(judgment, dimension_ids, single=False):
    """Return a list of problems with a parsed judge reply; empty means it meets the output contract.

    single=True checks a render_single() reply (score per dimension, overall_score)."""
    if not isinstance(judgment, dict):
        return ["reply is not a JSON object"]
    problems = []
    rows = judgment.get("dimensions")
    if not isinstance(rows, list):
        return ["missing dimensions list"]
    # Non-string ids (a judge may emit lists or numbers) are dropped here and reported as malformed below.
    seen = [r.get("dimension") for r in rows if isinstance(r, dict) and isinstance(r.get("dimension"), str)]
    for missing in [i for i in dimension_ids if i not in seen]:
        problems.append("missing dimension " + missing)
    for extra in sorted(set(seen) - set(dimension_ids)):
        problems.append("unexpected dimension " + str(extra))
    if len(seen) != len(set(seen)) or len(seen) != len(rows):
        problems.append("duplicate or malformed dimension rows")
    for r in rows:
        if not isinstance(r, dict):
            continue
        for key in (("score",) if single else ("score_a", "score_b")):
            if not _is_score(r.get(key)):
                problems.append(str(r.get("dimension")) + ": " + key + " not an integer 1-5")
        if not single and r.get("preference") not in PREFERENCES:
            problems.append(str(r.get("dimension")) + ": preference not A, B or tie")
        if not isinstance(r.get("evidence"), list):
            problems.append(str(r.get("dimension")) + ": evidence not a list")
    if single:
        if not _is_score(judgment.get("overall_score")):
            problems.append("overall_score not an integer 1-5")
    elif judgment.get("overall_preference") not in PREFERENCES:
        problems.append("overall_preference not A, B or tie")
    return problems


def _is_score(value):
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 5


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-doc", action="store_true", help="Regenerate the dimension reference in rubric/rubric.md")
    parser.add_argument("--render", choices=CASE_TYPES + tuple(f["id"] for f in load_fixtures()),
                        help="Print the judge prompt for a fixture id, or for the first fixture of a case type")
    parser.add_argument("--single", choices=("strong", "weak"),
                        help="With --render, print the single-document prompt for that variant instead of the pair")
    args = parser.parse_args()
    if args.single and not args.render:
        parser.error("--single needs --render")
    if args.write_doc:
        write_doc()
    if args.render:
        fixture = next(f for f in load_fixtures() if args.render in (f["id"], f["case_type"]))
        print(render_fixture_single(fixture, args.single) if args.single else render_fixture(fixture))
