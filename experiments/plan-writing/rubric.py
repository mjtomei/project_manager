"""Technical document quality rubric: loading, fixtures and judge-prompt rendering.

The rubric lives in rubric/ (rubric.md explains it; dimensions.json and references.json are
the machine-readable source). render_judge() fills the blinded paired templates for the
whole_document and continuation tracks; ordering and origin masking stay with the caller,
which only ever passes candidates as A and B. Stdlib only, so the runner can import it
without collect.py's dependencies.
"""

import json
import os
import re
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUBRIC = HERE / "rubric"
CASE_TYPES = ("whole_document", "continuation")
TEMPLATES = {"whole_document": "whole_document.md", "continuation": "continuation.md"}
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


def output_schema(dims):
    example = {"dimensions": [{"dimension": d["id"], "evidence": ["<quoted or located passages>"],
                               "rationale": "<why>", "score_a": 3, "score_b": 3,
                               "preference": "A|B|tie"} for d in dims],
               "overall_preference": "A|B|tie", "overall_rationale": "<why>"}
    return json.dumps(example, indent=2, ensure_ascii=False)


def render_judge(case_type, *, document_a, document_b, brief=None, prefix=None,
                 section_request=None, document_kind=None, dimensions=None, rubric=None):
    """Render the judge prompt for one blinded pair.

    whole_document needs brief; continuation needs prefix and may take the section_request
    the generator was given. dimensions limits the rubric to the listed ids. Catalog cases of
    type pm_plan are whole-document cases: pass the instruction and conversation turns as the
    brief. Brief attachments belong in the brief text, since fidelity and coverage are judged
    against it.
    """
    dims = dimensions_for(case_type, dimensions, rubric)
    kind_line = (" Document kind: " + document_kind + "." if document_kind else "")
    values = {"document_kind_line": kind_line, "dimension_block": dimension_block(dims, case_type),
              "output_schema": output_schema(dims)}
    if case_type == "whole_document":
        if not brief or prefix is not None:
            raise ValueError("whole_document cases take a brief and no prefix")
        values.update(brief=brief, document_a=document_a, document_b=document_b)
    else:
        if not prefix or brief is not None:
            raise ValueError("continuation cases take a prefix and no brief")
        values.update(prefix=prefix, section_a=document_a, section_b=document_b,
                      section_request_line=(" The writers were asked: " + section_request if section_request else ""))
    if not document_a or not document_b:
        raise ValueError("Both candidates are required")
    return fill((RUBRIC / "templates" / TEMPLATES[case_type]).read_text(), values)


def render_fixture(fixture, strong_as="A", rubric=None):
    """Render a fixture pair with its strong variant in slot strong_as ("A" or "B")."""
    if strong_as not in ("A", "B"):
        raise ValueError("strong_as must be A or B")
    a, b = ((fixture["strong"], fixture["weak"]) if strong_as == "A" else (fixture["weak"], fixture["strong"]))
    return render_judge(fixture["case_type"], document_a=a, document_b=b, brief=fixture.get("brief"),
                        prefix=fixture.get("prefix"), section_request=fixture.get("section_request"),
                        document_kind=fixture.get("document_kind"), rubric=rubric)


def reference_markdown(rubric=None, references=None):
    """The generated per-dimension part of rubric.md, between the GENERATED markers."""
    rubric = rubric or load_rubric()
    refs = references or load_references()
    fixtures = {}
    for f in load_fixtures():
        fixtures.setdefault(f["dimension"], []).append(f["id"])
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
        out += ["", "**Example, stronger.** " + d["examples"]["strong"].replace("\n", " "),
                "", "**Example, weaker.** " + d["examples"]["weak"].replace("\n", " "),
                "", "**Score anchors.** " + " ".join(k + ": " + v for k, v in sorted(d["score_anchors"].items())),
                "", "**Candidate measures** (readiness: " + d["measure_readiness"] + ").", ""]
        for m in d["candidate_measures"]:
            role = ", bias covariate" if m.get("role") == "bias_covariate" else ""
            out.append("- `" + m["name"] + "` (" + m["kind"] + ", " + m["status"] + role + "): " + m["description"])
        out += ["", "**Fixtures.** " + ", ".join("`fixtures/" + i + ".json`" for i in fixtures.get(d["id"], []))]
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
    # Replace by rename so a concurrent reader (a test, another --write-doc) never sees a partial file.
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".rubric.md.")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(head + GENERATED_START + "\n" + reference_markdown() + GENERATED_END + tail)
        os.chmod(tmp, os.stat(path).st_mode & 0o7777)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


def validate_judgment(judgment, dimension_ids):
    """Return a list of problems with a parsed judge reply; empty means it meets the output contract."""
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
        for key in ("score_a", "score_b"):
            if not (isinstance(r.get(key), int) and not isinstance(r.get(key), bool) and 1 <= r[key] <= 5):
                problems.append(str(r.get("dimension")) + ": " + key + " not an integer 1-5")
        if r.get("preference") not in PREFERENCES:
            problems.append(str(r.get("dimension")) + ": preference not A, B or tie")
        if not isinstance(r.get("evidence"), list):
            problems.append(str(r.get("dimension")) + ": evidence not a list")
    if judgment.get("overall_preference") not in PREFERENCES:
        problems.append("overall_preference not A, B or tie")
    return problems


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-doc", action="store_true", help="Regenerate the dimension reference in rubric/rubric.md")
    parser.add_argument("--render", choices=CASE_TYPES + tuple(f["id"] for f in load_fixtures()),
                        help="Print the judge prompt for a fixture id, or for the first fixture of a case type")
    args = parser.parse_args()
    if args.write_doc:
        write_doc()
    if args.render:
        fixture = next(f for f in load_fixtures() if args.render in (f["id"], f["case_type"]))
        print(render_fixture(fixture))
