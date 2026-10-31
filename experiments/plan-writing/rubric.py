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


# ---- rubric sets ----------------------------------------------------------------
# A rubric set is the aggregate rubric (dimensions.json) or one survey family's own rubric
# (families/<id>.json). Rendering and validation work on normalised criteria:
# {id, name, definition, condition, scale {min, max}, levels {level: text}, applies_to, examples}.

AGGREGATE = "aggregate"


def load_families():
    return json.loads((RUBRIC / "families.json").read_text())


def load_examples():
    return {e["id"]: e for e in json.loads((RUBRIC / "examples.json").read_text())["examples"]}


def load_restricted_levels():
    """Published levels whose licences forbid republishing; a local, gitignored file that may be absent."""
    path = RUBRIC / "restricted" / "levels.json"
    return json.loads(path.read_text())["families"] if path.exists() else {}


def list_rubrics():
    """Ids of the selectable rubric sets: the aggregate rubric, then each family that has criteria."""
    return [AGGREGATE] + [f["id"] for f in load_families()["families"] if f["rubric"]]


def load_rubric_set(rubric_id=AGGREGATE, rubric=None):
    if rubric_id == AGGREGATE:
        crit = []
        for d in (rubric or load_rubric())["dimensions"]:
            ex = d["examples"]
            crit.append({"id": d["id"], "name": d["name"], "definition": d["definition"], "condition": None,
                         "scale": {"min": 1, "max": 5}, "levels": d["score_anchors"], "applies_to": d["applies_to"],
                         "examples": [{"context": ex.get("context"), "stronger": ex["strong"], "weaker": ex["weak"],
                                       "scores": None}]})
        return {"id": AGGREGATE, "family": None, "title": "Aggregate rubric", "criteria": crit}
    families = load_families()
    family = next((f for f in families["families"] if f["id"] == rubric_id and f["rubric"]), None)
    if family is None:
        raise ValueError("Unknown rubric: " + str(rubric_id) + " (choose from " + ", ".join(list_rubrics()) + ")")
    data = json.loads((RUBRIC / "families" / (rubric_id + ".json")).read_text())
    pool = load_examples()
    generic = families["generic_levels"]
    restricted = load_restricted_levels().get(rubric_id, {})
    crit = []
    for c in data["criteria"]:
        # levels_source records which levels a judge saw, so results stay comparable: the source's
        # published levels, a local copy of restricted ones, or the generic levels.
        if c.get("levels"):
            scale, levels, origin = c["scale"], c["levels"], "published"
        elif c.get("levels_restricted") and c["id"] in restricted:
            scale, levels, origin = c["published_scale"], restricted[c["id"]]["levels"], "restricted_local"
        else:
            scale, levels, origin = generic["scale"], generic["levels"], "generic"
        crit.append({"id": c["id"], "name": c["name"], "definition": c["definition"]["text"],
                     "source_ref": c["definition"]["ref"], "condition": c.get("condition"),
                     "term_table": c.get("term_table"), "source_notes": c.get("source_notes"),
                     "scale": scale, "levels": levels, "levels_source": origin,
                     "applies_to": c.get("applies_to", list(CASE_TYPES)),
                     "examples": [_pool_example(pool[i]) for i in c.get("examples", [])]})
    return {"id": rubric_id, "family": rubric_id, "title": data["title"], "criteria": crit}


def _pool_example(e):
    return {"context": e.get("context"), "stronger": e["stronger"], "weaker": e["weaker"], "scores": e.get("scores")}


def criteria_for(case_type, rubric_id=AGGREGATE, ids=None, rubric=None, sources=None):
    """The criteria of a rubric set that apply to case_type, optionally limited to ids, or to the
    criteria stated by the given sources (reference ids), e.g. only PEP 1 and PEP 12 within
    process_templates."""
    if case_type not in CASE_TYPES:
        raise ValueError("Unknown case type: " + str(case_type))
    crit = [c for c in load_rubric_set(rubric_id, rubric)["criteria"] if case_type in c["applies_to"]]
    if sources is not None:
        if rubric_id == AGGREGATE:
            raise ValueError("The aggregate rubric has no per-source criteria; select dimensions by id")
        unknown = set(sources) - {c["source_ref"] for c in crit}
        if not sources or unknown:
            raise ValueError("Sources with no criteria in " + rubric_id + ": " + ", ".join(sorted(unknown)))
        crit = [c for c in crit if c["source_ref"] in sources]
    if ids is not None:
        if not ids:
            raise ValueError("Empty criterion subset for " + case_type)
        unknown = [i for i in ids if i not in {c["id"] for c in crit}]
        if unknown:
            raise ValueError("Criteria not in " + rubric_id + " for " + case_type + ": " + ", ".join(unknown))
        crit = [c for c in crit if c["id"] in ids]
    return crit


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


def _words(text):
    return re.findall(r"\w+", text.lower())


def _overlaps(example_text, inputs, run=8):
    """True when an example shares an 8-word run with the case inputs (or, if shorter, is contained in them)."""
    words = _words(example_text)
    joined = [" ".join(_words(t)) for t in inputs]
    if len(words) < run:
        return bool(words) and any(" ".join(words) in t for t in joined)
    grams = {" ".join(words[i:i + run]) for i in range(len(words) - run + 1)}
    for t in inputs:
        tw = _words(t)
        if any(" ".join(tw[i:i + run]) in grams for i in range(len(tw) - run + 1)):
            return True
    return False


def _example_text(side):
    return side["text"] if isinstance(side, dict) else side


def criteria_block(criteria, held_out=()):
    # Each criterion: its name, the source's definition, any condition the source attaches, the scale
    # with its levels, and published stronger/weaker examples. An example that shares text with the
    # case being judged is left out so a judge never sees the answer to that case.
    parts = []
    for c in criteria:
        lines = ["### " + c["id"] + " — " + c["name"]]
        if c.get("definition"):
            lines += ["", c["definition"]]
        if c.get("term_table"):
            lines += ["", "Terms as printed:"] + ["- " + " | ".join(row) for _, row in sorted(c["term_table"].items())]
        if c.get("source_notes"):
            lines += ["", "From the source:"] + ["- " + n for n in c["source_notes"]]
        if c.get("condition"):
            lines += ["", "Applies: " + c["condition"]]
        lines += ["", "Scale %d to %d:" % (c["scale"]["min"], c["scale"]["max"])]
        lines += ["- " + k + ": " + v for k, v in sorted(c["levels"].items(), key=lambda kv: int(kv[0]))]
        for ex in c["examples"]:
            # Some sources print only a good or only a poor version; render the side that exists.
            sides = [(tag, _example_text(ex[key])) for tag, key in (("stronger", "stronger"), ("weaker", "weaker"))
                     if ex.get(key)]
            texts = [t for _, t in sides] + ([_example_text(ex["context"])] if ex.get("context") else [])
            if held_out and any(_overlaps(t, held_out) for t in texts):
                continue
            lines += ["", "<example>"]
            if ex.get("context"):
                lines += ["<context>", _example_text(ex["context"]), "</context>"]
            for tag, text in sides:
                lines += ["<" + tag + ">", text, "</" + tag + ">"]
            if ex.get("scores"):
                lines += ["<published_scores>", ex["scores"]["text"], "</published_scores>"]
            lines += ["</example>"]
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def output_schema(criteria, single=False):
    mid = lambda c: (c["scale"]["min"] + c["scale"]["max"]) // 2
    if single:
        example = {"criteria": [{"criterion": c["id"], "score": mid(c)} for c in criteria], "overall_score": 3}
    else:
        example = {"criteria": [{"criterion": c["id"], "score_a": mid(c), "score_b": mid(c), "preference": "A|B|tie"}
                                for c in criteria],
                   "overall_preference": "A|B|tie"}
    return json.dumps(example, indent=2, ensure_ascii=False)


def _common_values(case_type, single, brief, prefix, section_request, document_kind, material, no_brief,
                   rubric_id, criteria, rubric, held_out, sources=None):
    crit = criteria_for(case_type, rubric_id, criteria, rubric, sources)
    values = {"document_kind_line": (" Document kind: " + document_kind + "." if document_kind else ""),
              "criteria_block": criteria_block(crit, held_out),
              "output_schema": output_schema(crit, single)}
    if case_type == "whole_document":
        if prefix is not None:
            raise ValueError("whole_document cases take a brief and no prefix")
        if bool(brief) == bool(no_brief):
            raise ValueError("whole_document cases take a brief, or no_brief=True when none exists")
        if brief:
            values["brief_block"] = "## Brief\n\n<brief>\n" + brief + "\n</brief>\n"
        else:
            values["brief_block"] = ("## Brief\n\nNo brief is available. Where a criterion refers to the brief, judge"
                                     " against what the document itself establishes"
                                     + (" and the material it describes" if material else "") + ".\n")
        values["material_block"] = ("\n## Material the document describes\n\n<material>\n" + material
                                    + "\n</material>\n" if material else "")
    else:
        if not prefix or brief is not None or no_brief:
            raise ValueError("continuation cases take a prefix and no brief")
        if material:
            raise ValueError("continuation cases take no material; the prefix is their input")
        values["prefix"] = prefix
        values["section_request_line"] = (" The request for this section: " + section_request if section_request else "")
    return values


def _case_inputs(*texts):
    return tuple(t for t in texts if t)


def render_judge(case_type, *, document_a, document_b, brief=None, prefix=None, section_request=None,
                 document_kind=None, material=None, no_brief=False, rubric_id=AGGREGATE, criteria=None,
                 dimensions=None, sources=None, rubric=None):
    """Render the judge prompt for one pair.

    whole_document needs brief; continuation needs prefix and may take the section_request
    the generator was given. rubric_id selects the rubric set (list_rubrics()); criteria limits it
    to the listed ids (dimensions is the older name for the same thing), and sources to the criteria
    stated by those reference ids within a family rubric. Catalog cases of type
    pm_plan are whole-document cases: pass the instruction and conversation turns as the brief.
    Brief attachments belong in the brief text. Reports about existing work (digests, sign-off and
    QA reports) are whole-document cases too: the brief is the request and material is what the
    report describes (diffs, code excerpts, logs, test output). no_brief=True renders a
    whole-document case that has no brief at all; the judge is told so. Examples that share text
    with the case are left out of the prompt.
    """
    if criteria is not None and dimensions is not None:
        raise ValueError("Pass criteria or dimensions, not both")
    values = _common_values(case_type, False, brief, prefix, section_request, document_kind, material, no_brief,
                            rubric_id, criteria if criteria is not None else dimensions, rubric,
                            _case_inputs(document_a, document_b, brief, prefix, material), sources)
    if not document_a or not document_b:
        raise ValueError("Both candidates are required")
    if case_type == "whole_document":
        values.update(document_a=document_a, document_b=document_b)
    else:
        values.update(section_a=document_a, section_b=document_b)
    return fill((RUBRIC / "templates" / TEMPLATES[case_type]).read_text(), values)


def render_single(case_type, *, document, brief=None, prefix=None, section_request=None, document_kind=None,
                  material=None, no_brief=False, rubric_id=AGGREGATE, criteria=None, dimensions=None, sources=None,
                  rubric=None):
    """Render the judge prompt for one document scored on its own (no comparison).

    Takes the same inputs as render_judge() with one document in place of the pair. The reply
    carries a score per criterion and an overall_score; check it with validate_judgment(..., single=True).
    """
    if criteria is not None and dimensions is not None:
        raise ValueError("Pass criteria or dimensions, not both")
    values = _common_values(case_type, True, brief, prefix, section_request, document_kind, material, no_brief,
                            rubric_id, criteria if criteria is not None else dimensions, rubric,
                            _case_inputs(document, brief, prefix, material), sources)
    if not document:
        raise ValueError("A document is required")
    values["document" if case_type == "whole_document" else "section"] = document
    return fill((RUBRIC / "templates" / SINGLE_TEMPLATES[case_type]).read_text(), values)


def render_fixture(fixture, strong_as="A", rubric_id=AGGREGATE, rubric=None):
    """Render a fixture pair with its strong variant in slot strong_as ("A" or "B")."""
    if strong_as not in ("A", "B"):
        raise ValueError("strong_as must be A or B")
    a, b = ((fixture["strong"], fixture["weak"]) if strong_as == "A" else (fixture["weak"], fixture["strong"]))
    return render_judge(fixture["case_type"], document_a=a, document_b=b, brief=fixture.get("brief"),
                        prefix=fixture.get("prefix"), section_request=fixture.get("section_request"),
                        document_kind=fixture.get("document_kind"), material=fixture.get("material"),
                        no_brief=_fixture_has_no_brief(fixture), rubric_id=rubric_id, rubric=rubric)


def render_fixture_single(fixture, variant="strong", rubric_id=AGGREGATE, rubric=None):
    """Render one variant of a fixture ("strong" or "weak") for single-document scoring."""
    if variant not in ("strong", "weak"):
        raise ValueError("variant must be strong or weak")
    return render_single(fixture["case_type"], document=fixture[variant], brief=fixture.get("brief"),
                         prefix=fixture.get("prefix"), section_request=fixture.get("section_request"),
                         document_kind=fixture.get("document_kind"), material=fixture.get("material"),
                         no_brief=_fixture_has_no_brief(fixture), rubric_id=rubric_id, rubric=rubric)


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


def families_markdown(references=None):
    """The whole of rubric/families.md: each survey family's own rubric, or what the family contributes instead."""
    refs = references or load_references()
    fams = load_families()
    pool = load_examples()
    cite = lambda r, loc: "[" + refs[r]["title"] + "](" + refs[r]["url"] + ")" + (", " + loc if loc else "")
    out = ["# Family rubrics", "",
           "Generated by `python3 experiments/plan-writing/rubric.py --write-doc` from [families.json](families.json), "
           "[families/](families/) and [examples.json](examples.json); do not edit by hand. "
           "[rubric.md](rubric.md) explains how these rubrics relate to the aggregate rubric.", "",
           "Where a source publishes no score levels, criteria use these levels (scale %d to %d), worded by the rubric "
           "authors: " % (fams["generic_levels"]["scale"]["min"], fams["generic_levels"]["scale"]["max"])
           + "; ".join(k + ": " + v for k, v in sorted(fams["generic_levels"]["levels"].items())), "",
           "| Family | Rubric | Criteria | Contributes |", "|---|---|---|---|"]
    for f in fams["families"]:
        n = len(json.loads((RUBRIC / "families" / (f["id"] + ".json")).read_text())["criteria"]) if f["rubric"] else 0
        out.append("| " + " | ".join([f["name"], "`" + f["id"] + "`" if f["rubric"] else "—", str(n) if n else "—",
                                       ", ".join(f["contributes"])]) + " |")
    for f in fams["families"]:
        out += ["", "## " + f["name"], "", "Sources: " + "; ".join(cite(r, None) for r in f["sources"]) + "."]
        if f["rubric"]:
            data = json.loads((RUBRIC / "families" / (f["id"] + ".json")).read_text())
            out += ["", "Rubric id `" + f["id"] + "`: " + data["title"] + "."]
            for c in data["criteria"]:
                d = c["definition"]
                quote = ("> " + d["text"].replace("\n", "\n> ")) if d["text"] else "The source states no definition; it publishes levels only."
                out += ["", "### " + c["id"] + " — " + c["name"], "", quote, "", "Source: " + cite(d["ref"], d["locator"])
                        + ("; quoted as checked against " + "; ".join(cite(v, None) for v in d["via"]) if d.get("via") else "") + "."]
                if c.get("condition"):
                    out += ["", "Applies: " + c["condition"]]
                if c.get("document_kind"):
                    out += ["", "Document kind: " + c["document_kind"] + "."]
                if c.get("source_notes"):
                    out += ["", "From the source: " + " ".join(c["source_notes"])]
                if c.get("levels_restricted"):
                    out += ["", "Published levels (%d to %d) are not reproduced here because of the source's licence; a local "
                            "copy in restricted/levels.json is used when present." % (c["published_scale"]["min"],
                                                                                        c["published_scale"]["max"])]
                if c.get("levels"):
                    out += ["", "Published levels (%d to %d): " % (c["scale"]["min"], c["scale"]["max"])
                            + "; ".join(k + ": " + v for k, v in sorted(c["levels"].items(), key=lambda kv: int(kv[0])))]
                if c.get("examples"):
                    out += ["", "Examples: " + ", ".join("`" + i + "` (" + cite((pool[i]["stronger"] or pool[i]["weaker"])["ref"], None)
                                                         + ")" for i in c["examples"]) + "."]
        if f.get("not_criteria"):
            out += ["", "Contributes rather than criteria:", ""]
            out += ["- " + cite(n["source_ref"], None) + " (" + n["contributes"] + "): " + n["note"] for n in f["not_criteria"]]
        if f.get("gaps"):
            out += ["", "Gaps: " + f["gaps"]]
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
    _replace_file(path, new_text)
    _replace_file(RUBRIC / "families.md", families_markdown())


def _replace_file(path, new_text):
    # Replace by rename so a concurrent reader (a test, another --write-doc) never sees a partial file.
    # The temp name is fixed before the file exists, so a Ctrl-C right after creation still removes it
    # (mkstemp can be interrupted after creating its file but before returning the name).
    # pid + thread id keep concurrent writers apart; a same-named file can only be left by a dead process.
    tmp = path.with_name(".%s.%d.%d" % (path.name, os.getpid(), threading.get_ident()))
    try:
        with open(tmp, "w") as f:
            f.write(new_text)
        if path.exists():
            os.chmod(tmp, os.stat(path).st_mode & 0o7777)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def extract_judgment(reply):
    """Return the JSON object a judge reply ends with; text before it is allowed.

    Raises ValueError when the reply does not end with a JSON object (a trailing code fence is fine)."""
    tail = reply.rstrip()
    if tail.endswith("```"):
        tail = tail[:-3].rstrip()
    decoder = json.JSONDecoder()
    pos = tail.rfind("{")
    while pos != -1:
        try:
            obj, end = decoder.raw_decode(tail, pos)
        except ValueError:
            obj, end = None, -1
        if isinstance(obj, dict) and end == len(tail):
            return obj
        pos = tail.rfind("{", 0, pos)
    raise ValueError("reply does not end with a JSON object")


def validate_judgment(judgment, criteria, single=False):
    """Return a list of problems with a parsed judge reply; empty means it meets the output contract.

    criteria is the list rendered (criteria_for(...)), or plain ids for a 1-5 scale. single=True
    checks a render_single() reply (score per criterion, overall_score)."""
    scales = {}
    for c in criteria:
        if isinstance(c, str):
            scales[c] = (1, 5)
        else:
            scales[c["id"]] = (c["scale"]["min"], c["scale"]["max"])
    if not isinstance(judgment, dict):
        return ["reply is not a JSON object"]
    problems = []
    rows = judgment.get("criteria")
    if not isinstance(rows, list):
        return ["missing criteria list"]
    # Non-string ids (a judge may emit lists or numbers) are dropped here and reported as malformed below.
    seen = [r.get("criterion") for r in rows if isinstance(r, dict) and isinstance(r.get("criterion"), str)]
    for missing in [i for i in scales if i not in seen]:
        problems.append("missing criterion " + missing)
    for extra in sorted(set(seen) - set(scales)):
        problems.append("unexpected criterion " + str(extra))
    if len(seen) != len(set(seen)) or len(seen) != len(rows):
        problems.append("duplicate or malformed criterion rows")
    for r in rows:
        if not isinstance(r, dict):
            continue
        lo, hi = scales.get(r.get("criterion"), (1, 5)) if isinstance(r.get("criterion"), str) else (1, 5)
        for key in (("score",) if single else ("score_a", "score_b")):
            if not _is_score(r.get(key), lo, hi):
                problems.append("%s: %s not an integer %d-%d" % (r.get("criterion"), key, lo, hi))
        if not single and r.get("preference") not in PREFERENCES:
            problems.append(str(r.get("criterion")) + ": preference not A, B or tie")
    if single:
        if not _is_score(judgment.get("overall_score"), 1, 5):
            problems.append("overall_score not an integer 1-5")
    elif judgment.get("overall_preference") not in PREFERENCES:
        problems.append("overall_preference not A, B or tie")
    return problems


def _is_score(value, lo=1, hi=5):
    return isinstance(value, int) and not isinstance(value, bool) and lo <= value <= hi


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-doc", action="store_true", help="Regenerate the dimension reference in rubric/rubric.md")
    parser.add_argument("--render", choices=CASE_TYPES + tuple(f["id"] for f in load_fixtures()),
                        help="Print the judge prompt for a fixture id, or for the first fixture of a case type")
    parser.add_argument("--single", choices=("strong", "weak"),
                        help="With --render, print the single-document prompt for that variant instead of the pair")
    parser.add_argument("--rubric", default=AGGREGATE, help="With --render, the rubric set to use (see --list-rubrics)")
    parser.add_argument("--list-rubrics", action="store_true", help="List the selectable rubric sets")
    args = parser.parse_args()
    if args.list_rubrics:
        for rid in list_rubrics():
            print(rid)
    if args.rubric != AGGREGATE and args.rubric not in list_rubrics():
        parser.error("unknown rubric " + args.rubric + "; see --list-rubrics")
    if args.single and not args.render:
        parser.error("--single needs --render")
    if args.write_doc:
        write_doc()
    if args.render:
        fixture = next(f for f in load_fixtures() if args.render in (f["id"], f["case_type"]))
        print(render_fixture_single(fixture, args.single, rubric_id=args.rubric) if args.single
              else render_fixture(fixture, rubric_id=args.rubric))
