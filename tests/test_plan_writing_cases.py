"""Tests for the plan-writing case catalog (experiments/plan-writing).

Synthetic fixtures exercise brief assembly, continuation cuts, PM case
extraction and coverage accounting; a final test validates the real catalog
when one has been built locally.
"""

import hashlib
import importlib
import json
import sys
from pathlib import Path

import pytest

PW = Path(__file__).resolve().parent.parent / "experiments" / "plan-writing"
sys.path.insert(0, str(PW))
cases = importlib.import_module("cases")
docmeta = importlib.import_module("docmeta")
pm_cases = importlib.import_module("pm_cases")
sections = importlib.import_module("sections")

N = 8

PEP_TEXT = """PEP: 9999
Title: Frobnicate the widget registry
Author: A. Author <a@example.org>
Status: Final
Type: Standards Track
Created: 01-Jan-2020

Abstract
========

The widget registry keeps every widget in a single global table that grows without bound
and is never compacted during the lifetime of the interpreter process.

Motivation
==========

Large applications register thousands of transient widgets and the registry becomes the
dominant source of memory pressure in long running services that never restart.

Specification
=============

A new compaction pass walks the registry after each garbage collection cycle and removes
entries whose widgets are no longer reachable from any live object in the program.
""" + "\n".join(f"Additional detail sentence number {i} explains a further consequence of compaction for users." for i in range(30)) + """

Rationale
=========

Compaction keeps registry size proportional to the number of live widgets, which is what
users already expect from every other cache that the standard library provides today.
"""

MD_TEXT = """# Proposal: Better widgets

Author(s): Someone

Discussion at https://golang.org/issue/12345.

## Abstract

""" + " ".join(["Widgets are slow today because the allocator is global."] * 30) + """

```
## not a heading inside code
```

## Background

""" + " ".join(["The background explains the history of widget allocation in detail."] * 10) + """

## Proposal

""" + " ".join(["We propose a per-thread widget allocator with bounded caches."] * 10) + """
"""

RFC_TEXT = """Network Working Group                                          A. Author
Request for Comments: 9999                                    Example Org

                     The Widget Transfer Protocol

Abstract

   This document specifies a protocol for moving widgets between hosts.

Table of Contents

   1.  Introduction . . . . . . . . . . . . . . . . . . . . . . . .   2
   2.  Protocol Overview  . . . . . . . . . . . . . . . . . . . . .   3

1.  Introduction

""" + "\n".join(["   Widgets need to move between hosts reliably and the existing approaches lose state."] * 20) + """

   1. This is a numbered list item, not a heading.

2.  Protocol Overview

""" + "\n".join(["   A sender opens a stream, announces the widget, and the receiver acknowledges."] * 12) + """

2.1.  Message Format

""" + "\n".join(["   Each message carries a type octet followed by a length field and the payload."] * 12) + """

3.  Security Considerations

""" + "\n".join(["   Widgets may carry sensitive state and must be transferred over protected channels."] * 8) + """
"""


# --- helpers -----------------------------------------------------------------

def doc_record(source, identity, text, root, raw=None, split_group=None, dup=None, revision="abc"):
    uid = hashlib.sha256((source + ":" + identity).encode()).hexdigest()[:24]
    tp = Path("text") / source / (uid + ".txt")
    rp = Path("raw") / source / (uid + ".raw")
    (root / tp).parent.mkdir(parents=True, exist_ok=True)
    (root / rp).parent.mkdir(parents=True, exist_ok=True)
    (root / tp).write_text(text)
    (root / rp).write_bytes(raw if raw is not None else text.encode())
    sha = hashlib.sha256(text.encode()).hexdigest()
    return {"id": uid, "source": source, "domain": "software", "document_kind": "x", "identity": identity,
            "title": identity, "url": f"https://example.org/{source}/{identity}", "revision": revision,
            "retrieved_at": "2026-10-19T00:00:00+00:00", "raw_path": str(rp), "text_path": str(tp), "sha256": sha,
            "raw_sha256": sha, "words": len(text.split()), "known_good": True, "label_basis": "",
            "split_group": split_group or source, "license_note": "", "eligible_for_text_evaluation": bool(text.split()),
            "duplicate_group": dup or sha, "canonical_id": uid}


def context_item(source, kind, key, text, applies_to, role="document", written="before", **extra):
    item = {"id": hashlib.sha256(f"{source}:{kind}:{key}".encode()).hexdigest()[:24], "source": source, "kind": kind,
            "key": key, "role": role, "url": f"https://example.org/ctx/{key}", "retrieved_at": "2026-10-20T00:00:00+00:00",
            "applies_to": applies_to, "fields": {}, "text": text, "sha256": hashlib.sha256(text.encode()).hexdigest(),
            "words": len(text.split()), "label": kind.replace("_", " "), "written": written}
    item.update(extra)
    return item


CONFIG = {
    "sources": [
        {"id": "peps", "split_group": "peps",
         "context": {"request": "Write a PEP.", "collectors": [{"type": "header", "format": "rfc822"}]}},
        {"id": "goprop", "context": {"request": "Write a Go design document.", "collectors": [{"type": "header", "format": "go"}]}},
        {"id": "rfcs", "split_group_rule": "ietf_working_group", "context": {"request": "Write an RFC.", "collectors": [{"type": "ietf"}]}},
        {"id": "plain", "kind": "git"},
    ],
    "case_preparation": {"brief_leak_ngram": N, "continuation": {"max_cases_per_document": 3, "min_prefix_words": 20,
                                                                 "min_reference_words": 10, "max_reference_words": 4000},
                         "context_timing": "Context written after the document is never used in a brief."},
}


def write_conversation(path, plan_path, extra_user=None):
    rows = [
        {"type": "user", "message": {"role": "user", "content": "## Session Context\nYou are running inside a pm session."}, "timestamp": "t0"},
        {"type": "user", "message": {"role": "user", "content": "Unrelated question about the TUI."}, "timestamp": "t1"},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "Answer about the TUI."}]}, "timestamp": "t2"},
        {"type": "user", "message": {"role": "user", "content": "Please write a plan for widget compaction with two PRs."}, "timestamp": "t3"},
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Read", "input": {"file_path": "/x"}}]}, "timestamp": "t4"},
        {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "content": "SECRET TOOL OUTPUT"}]}, "toolUseResult": {}, "timestamp": "t5"},
        {"type": "attachment", "attachment": {"type": "queued_command", "prompt": "Also keep the API stable.", "commandMode": "prompt"}, "timestamp": "t6"},
        {"type": "user", "isMeta": True, "message": {"role": "user", "content": "meta caveat"}, "timestamp": "t7"},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "Drafting the plan now."},
                                                      {"type": "tool_use", "name": "Write", "input": {"file_path": str(plan_path), "content": "# Draft plan\n"}}]},
         "timestamp": "t8"},
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return len(rows)


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    """A built catalog over a small synthetic corpus, context store and PM history."""
    data = tmp_path / "data"
    data.mkdir()
    pep = doc_record("peps", "peps/pep-9999.rst", PEP_TEXT, data)
    pep_dup = doc_record("plain", "copy/pep-9999.rst", PEP_TEXT, data, dup=pep["duplicate_group"])
    md = doc_record("goprop", "design/12345-widgets.md", MD_TEXT, data)
    md_byline_only = doc_record("goprop", "design/other.md", "# Proposal: x\n\nAuthor(s): Someone\n\nShort text only.", data)
    rfc = doc_record("rfcs", "rfc9999.txt", RFC_TEXT, data)
    empty = doc_record("plain", "empty.txt", "", data)
    flat = doc_record("plain", "notes.txt", "just a few words without any structure at all", data)
    docs = [pep, pep_dup, md, md_byline_only, rfc, empty, flat]
    (data / "corpus.jsonl").write_text("".join(json.dumps(d) + "\n" for d in docs))
    ctx = data / "context"
    ctx.mkdir()
    pep_items = [
        context_item("peps", "metadata", pep["id"], "PEP: 9999\nTitle: Frobnicate the widget registry\nType: Standards Track", [pep["id"]],
                     written="with_document"),
        context_item("peps", "discussion_thread", "t1",
                     "Title: Compacting the registry\n\nOur services leak memory through the widget table and we need a fix.\n"
                     # a sentence copied from the body, and a passage split across two lines
                     "Large applications register thousands of transient widgets and the registry becomes the dominant source.\n"
                     "The proposal walks the registry after each garbage\ncollection cycle and removes entries whose widgets\n"
                     "Please comment on the approach in this thread.", [pep["id"]], written="dated", written_at="2019-12-01"),
        context_item("peps", "discussion_thread", "t2", "Title: PEP 9999 posted\n\nThe accepted design now ships in the next release for everyone.",
                     [pep["id"]], written="dated", written_at="2020-03-01"),
        context_item("peps", "review_thread", "pr1", "Title: Add PEP 9999\n\nThis pull request adds the finished PEP for the registry.",
                     [pep["id"]], written="after"),
        context_item("peps", "process", "pep-0012@v1", "PEP template: write an Abstract and a Motivation.", [pep["id"]], role="process",
                     document_id=None, version={"path": "pep-0012.txt", "commit": "abc", "committed": "2019-06-01"}),
    ]
    md_items = [
        context_item("goprop", "tracking_issue", "go12345",
                     "Title: proposal: faster widgets\n\nThe allocator is a bottleneck for our servers; please design a fix.\n\n"
                     + MD_TEXT.split("## Background")[1][:600], [md["id"]]),
        context_item("goprop", "metadata", md_byline_only["id"], "Author(s): Someone", [md_byline_only["id"]]),
    ]
    rfc_items = [context_item("rfcs", "index_entry", "rfc9999", "Title: The Widget Transfer Protocol\nWorking group: wtp",
                              [rfc["id"]], written="identity", fields={"Working group": "wtp", "Stream": "IETF"}),
                 context_item("rfcs", "milestone", "draft-wtp", "- Submit the widget transfer protocol to the IESG for publication as a standard",
                              [rfc["id"]], written="after")]
    (ctx / "peps.dates.json").write_text(json.dumps({pep["id"]: {"date": "2020-01-01", "basis": "Created"}}))
    for name, items in (("peps", pep_items), ("goprop", md_items), ("rfcs", rfc_items)):
        (ctx / f"{name}.jsonl").write_text("".join(json.dumps(i) + "\n" for i in items))
        (ctx / f"{name}.status.json").write_text(json.dumps({"source": name, "items": len(items), "by_kind": {}, "errors": []}))
    # PM history: one mapped plan with a record, one unmounted record, one not located, one plan outside the map
    plans = tmp_path / "pm" / "plans"
    plans.mkdir(parents=True)
    for name in ("plan-widgets.md", "plan-unmounted.md", "plan-lost.md", "plan-new.md"):
        (plans / name).write_text(f"# {name}\n\nBaseline text for {name} that a generator must not see.\n")
    claude = tmp_path / "claude-projects"
    record = claude / "-home-matt-proj" / "sess.jsonl"
    event_line = write_conversation(record, plans / "plan-widgets.md")
    mp = tmp_path / "map.md"
    mp.write_text("\n".join([
        "| Plan | Evidence found | Session records (local, line reference) |", "|---|---|---|",
        f"| plan-widgets.md | Draft/write record | `/home/matt/.claude/projects/-home-matt-proj/sess.jsonl:{event_line}` |",
        "| plan-unmounted.md | Draft/write record | `/home/matt/.codex/sessions/rollout.jsonl:12` |",
        "| plan-lost.md | Not located in scoped search | Broader history search needed |", ""]))
    windows = tmp_path / "windows.json"
    windows.write_text(json.dumps({f"plan-widgets.md:sess.jsonl:{event_line}": {"start_line": 4, "request_line": 4, "note": "test"}}))
    monkeypatch.setattr(cases, "DATA", data)
    monkeypatch.setattr(cases, "CASES", data / "cases")
    monkeypatch.setattr(cases, "REPORTS", tmp_path / "reports")
    monkeypatch.setattr(cases, "load_config", lambda: CONFIG)
    monkeypatch.setattr(pm_cases, "MAP_PATH", mp)
    monkeypatch.setattr(pm_cases, "PLANS", plans)
    monkeypatch.setattr(pm_cases, "WINDOWS", windows)
    monkeypatch.setenv("PM_CLAUDE_PROJECTS", str(claude))
    monkeypatch.delenv("PM_CODEX_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    cases.build()
    built = [json.loads(l) for l in (data / "cases" / "catalog.jsonl").read_text().splitlines()]
    coverage = json.loads((data / "cases" / "coverage.json").read_text())
    return {"data": data, "cases": built, "coverage": coverage, "docs": {d["identity"]: d for d in docs},
            "record": record, "event_line": event_line, "plans": plans}


def body_grams(doc, data, fmt):
    text = (data / doc["text_path"]).read_text()
    return cases.ngrams(cases.tokens(docmeta.body_text(text, fmt)), N)


# --- briefs ------------------------------------------------------------------

def test_briefs_never_contain_document_passages(catalog):
    data = catalog["data"]
    whole = [c for c in catalog["cases"] if c["case_type"] == "whole_document"]
    assert whole
    fmts = {"peps": "rfc822", "goprop": "go", "rfcs": None}
    for case in whole:
        doc = next(d for d in catalog["docs"].values() if d["id"] == case["document_id"])
        assert not cases.shared_ngrams(case["inputs"]["brief"], body_grams(doc, data, fmts[doc["source"]]), N), case["case_id"]


def test_brief_keeps_request_context_and_drops_copied_text(catalog):
    pep = catalog["docs"]["peps/pep-9999.rst"]
    case = next(c for c in catalog["cases"] if c["case_id"] == "doc:" + pep["id"])
    brief = case["inputs"]["brief"]
    assert "Frobnicate the widget registry" in brief          # metadata title survives
    assert "leak memory through the widget table" in brief    # request text survives
    assert "dominant source" not in brief                     # copied sentence removed
    assert "collection cycle and removes entries" not in brief  # passage straddling lines removed
    assert "Status: Final" not in brief                       # decision fields never collected
    thread = next(p for p in case["provenance"]["items_considered"] if p["kind"] == "discussion_thread")
    assert thread["segments_dropped"] >= 2
    assert case["provenance"]["context_strength"] == "rich"
    # process documents are attachments with provenance, not brief text
    assert [a["label"] for a in case["inputs"]["attachments"]] == ["process"]
    assert "PEP template" not in brief


def test_pasted_document_truncates_context_item(catalog):
    md = catalog["docs"]["design/12345-widgets.md"]
    case = next(c for c in catalog["cases"] if c["case_id"] == "doc:" + md["id"])
    issue = next(p for p in case["provenance"]["items_considered"] if p["kind"] == "tracking_issue")
    assert issue["truncated_at_quoted_document"]
    assert "allocator is a bottleneck" in case["inputs"]["brief"]
    assert "history of widget allocation" not in case["inputs"]["brief"]


def test_byline_alone_is_not_recoverable_context(catalog):
    other = catalog["docs"]["design/other.md"]
    assert not any(c["case_id"] == "doc:" + other["id"] for c in catalog["cases"])
    assert catalog["coverage"]["documents"][other["id"]]["brief"] is None


def test_thin_brief_from_index_entry(catalog):
    rfc = catalog["docs"]["rfc9999.txt"]
    case = next(c for c in catalog["cases"] if c["case_id"] == "doc:" + rfc["id"])
    assert case["provenance"]["context_strength"] == "thin"
    assert "The Widget Transfer Protocol" in case["inputs"]["brief"]


# --- provenance and split groups --------------------------------------------

def test_every_case_records_provenance_and_split_group(catalog):
    assert {c["case_type"] for c in catalog["cases"]} == {"whole_document", "continuation", "pm_plan"}
    for case in catalog["cases"]:
        assert case["provenance"], case["case_id"]
        assert case["split_group"], case["case_id"]
        if case["case_type"] == "whole_document":
            for item in case["provenance"]["brief_items"]:
                assert item["url"] and item["retrieved_at"] and item["sha256"]
        if case["case_type"] == "continuation":
            assert case["provenance"]["text_sha256"] and case["provenance"]["boundary_method"]


def test_split_groups_follow_working_group_and_duplicates(catalog):
    by_doc = {c["document_id"]: c["split_group"] for c in catalog["cases"] if c["document_id"]}
    docs = catalog["docs"]
    assert by_doc[docs["rfc9999.txt"]["id"]] == "ietf-wtp"
    # identical texts in different sources share one group
    assert by_doc[docs["peps/pep-9999.rst"]["id"]] == by_doc[docs["copy/pep-9999.rst"]["id"]]


# --- continuation cases ------------------------------------------------------

def test_continuation_prefixes_end_at_section_boundaries(catalog):
    data = catalog["data"]
    conts = [c for c in catalog["cases"] if c["case_type"] == "continuation"]
    assert {c["source"] for c in conts} >= {"peps", "goprop", "rfcs"}
    for case in conts:
        doc = next(d for d in catalog["docs"].values() if d["id"] == case["document_id"])
        text = (data / doc["text_path"]).read_text()
        found = sections.headings(doc, text, (data / doc["raw_path"]).read_bytes())[1]
        end = case["inputs"]["prefix_end"]
        assert sections.is_boundary(found, end)
        assert text[end - 1] == "\n"
        assert case["reference"]["start"] == end and case["reference"]["end"] > end
        assert len(case["inputs"].get("prefix", "")) == 0, "catalog stores offsets, not copies"


def test_references_are_excluded_from_generator_inputs(catalog):
    data = catalog["data"]
    for case in catalog["cases"]:
        gen = cases.generator_input(case, data)
        blob = json.dumps(gen)
        if case["case_type"] == "continuation":
            doc = next(d for d in catalog["docs"].values() if d["id"] == case["document_id"])
            text = (data / doc["text_path"]).read_text()
            reference = text[case["reference"]["start"]: case["reference"]["end"]]
            assert reference.strip() not in gen["prefix"]
            assert set(gen) == {"instruction", "prefix"}
        elif case["case_type"] == "whole_document":
            assert set(gen) == {"brief", "attachments"}
        else:
            baseline = Path(case["baseline"]["path"]).read_text()
            assert baseline not in blob
            assert "Draft plan" not in blob


def test_generator_input_rejects_changed_text(catalog):
    data = catalog["data"]
    case = next(c for c in catalog["cases"] if c["case_type"] == "continuation")
    (data / case["inputs"]["text_path"]).write_text("changed")
    with pytest.raises(ValueError):
        cases.generator_input(case, data)


def test_markdown_headings_skip_code_fences():
    found = sections.markdown_headings(MD_TEXT)
    titles = [h.title for h in found]
    assert "not a heading inside code" not in titles
    assert titles == ["Proposal: Better widgets", "Abstract", "Background", "Proposal"]


def test_numbered_headings_reject_toc_and_lists():
    titles = [h.title for h in sections.numbered_headings(RFC_TEXT)]
    assert "1.  Introduction" in titles and "2.1.  Message Format" in titles
    assert not any("numbered list item" in t for t in titles)
    assert not any(". . ." in t for t in titles)
    assert "Abstract" in titles


def test_rst_heading_levels():
    found = sections.rst_headings("Title\n=====\n\ntext\n\nSub\n---\n\nmore\n\nNext\n====\n")
    assert [(h.title, h.level) for h in found] == [("Title", 1), ("Sub", 2), ("Next", 1)]


def test_html_headings_match_flattened_text():
    pytest.importorskip("bs4")
    collect = importlib.import_module("collect")
    raw = (b"<html><body><main><h1>Design</h1><p>Intro words here.</p><h2>Goals <a href='#'>link</a></h2>"
           b"<p>Goal text.</p><h2>Non-goals</h2><p>More.</p></main></body></html>")
    text = collect.page_text(raw)[1]
    found = sections.html_headings(text, raw)
    assert [h.title for h in found] == ["Design", "Goals link", "Non-goals"]
    for h in found:
        assert h.start == 0 or text[h.start - 1] == "\n"


# --- PM cases ----------------------------------------------------------------

def test_pm_cases_link_to_conversation_records(catalog):
    pm = [c for c in catalog["cases"] if c["case_type"] == "pm_plan"]
    assert [c["case_id"] for c in pm] == ["pm:plan-widgets"]
    case = pm[0]
    rec = case["provenance"]["records"][0]
    assert rec["path"] == str(catalog["record"]) and rec["event_line"] == catalog["event_line"]
    assert rec["event_matches_plan"] and rec["window_reviewed"] and rec["start_line"] == 4
    assert rec["draft_sha256"] == hashlib.sha256(b"# Draft plan\n").hexdigest()
    assert case["baseline"]["role"].startswith("production_baseline")
    turns = cases.generator_input(case)["conversation"]
    assert [t["role"] for t in turns] == ["human", "human"]  # reviewed window starts at the request
    assert "SECRET TOOL OUTPUT" not in json.dumps(turns)
    assert any("keep the API stable" in t["text"] for t in turns)


def test_pm_default_window_and_roles(tmp_path):
    record = tmp_path / "sess.jsonl"
    line = write_conversation(record, tmp_path / "pm" / "plans" / "plan-widgets.md")
    window = pm_cases.extract_window(pm_cases.load_records(record), line, "plan-widgets.md")
    roles = [t["role"] for t in window["turns"]]
    assert roles[0] == "injected" and roles.count("human") == 3 and "assistant" in roles
    assert window["event_tools"] == ["Write"] and window["written_content"] == "# Draft plan\n"


def test_pm_report_lists_unrecovered_plans(catalog):
    status = {p["plan"]: p["status"] for p in catalog["coverage"]["pm_plans"]}
    assert status == {"plan-widgets.md": "recovered", "plan-unmounted.md": "history_not_mounted",
                      "plan-lost.md": "not_located", "plan-new.md": "not_in_map"}


# --- coverage ----------------------------------------------------------------

def test_coverage_accounts_for_every_collected_document(catalog):
    cov = catalog["coverage"]
    ids = {d["id"] for d in catalog["docs"].values()}
    assert set(cov["documents"]) == ids
    assert cov["totals"]["documents"] == len(ids)
    dropped = {d["identity"]: d["reason"] for d in cov["dropped"]}
    assert set(dropped) == {"empty.txt", "notes.txt", "design/other.md"}
    assert dropped["empty.txt"].startswith("empty text")
    t = cov["totals"]
    assert t["both_case_types"] + t["whole_document_only"] + t["continuation_only"] + t["dropped"] == len(ids)
    md = (catalog["data"].parent / "reports" / "case-coverage.md").read_text()
    assert "| peps |" in md and "plan-unmounted.md" in md


def test_check_passes_on_clean_catalog(catalog):
    result = cases.check(data_dir=catalog["data"])
    assert result["failure_counts"] == {}, result["failures"]


def test_check_detects_violations(catalog):
    data = catalog["data"]
    path = data / "cases" / "catalog.jsonl"
    rows = [json.loads(l) for l in path.read_text().splitlines()]
    for row in rows:
        if row["case_type"] == "whole_document" and row["source"] == "peps":
            row["inputs"]["brief"] += "\nThe widget registry keeps every widget in a single global table that grows."
        if row["case_type"] == "continuation":
            row["inputs"]["prefix_end"] += 1
        if row["case_type"] == "pm_plan":
            row["split_group"] = ""
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    cov = json.loads((data / "cases" / "coverage.json").read_text())
    cov["documents"].pop(next(iter(cov["documents"])))
    counts = cases.check(data_dir=data, coverage=cov)["failure_counts"]
    for key in ("brief_quotes_document_body", "prefix_not_at_section_boundary", "missing_split_group",
                "documents_missing_from_coverage"):
        assert counts.get(key), key


REAL = PW / "data" / "cases" / "catalog.jsonl"


@pytest.mark.skipif(not REAL.exists(), reason="real catalog not built (run collect.py, context.py, cases.py)")
def test_real_catalog_passes_check():
    result = cases.check()
    assert result["failure_counts"] == {}, result["failures"]


def test_continuation_skips_boilerplate_and_repeated_sections():
    filler = " ".join(["Body text explains the design in useful detail."] * 6)
    text = (f"# Title\n\n{filler}\n\n## Design\n\n{filler} Unique design words here.\n\n"
            f"## Repeated\n\n{filler}\n\n## References\n\n{filler} More unique reference words.\n")
    doc = {"identity": "x.md", "source": "s", "revision": "r", "id": "d", "text_path": "x.txt"}
    cfg = {"max_cases_per_document": 5, "min_prefix_words": 5, "min_reference_words": 5, "max_reference_words": 4000}
    _, found, eligible, conts = cases.continuation_cases(doc, text, text.encode(), cfg)
    assert found == 4
    assert [c["reference"]["heading"] for c in conts] == ["Design"]  # "Repeated" copies the intro; "References" is boilerplate


def test_table_only_request_text_is_thin(tmp_path):
    text = "# Goal\n\n" + " ".join(["The goal document body has its own words."] * 20)
    doc = {"identity": "src/2026/goal-1234.md", "url": "https://example.org/goal", "id": "g"}
    item = context_item("goals", "tracking_issue", "i1",
                        "Title: Ship the thing\nOpened by someone on 2026-01-01\n\n| Contact | @a |\n| Team(s) | compiler, lang, types and more teams |\n"
                        "Details at https://example.org/goal-1234 for reviewers\n"
                        "## Summary\n\nThe goal document body has its own words. The goal document body has its own words.", ["g"])
    cfg = {"context": {"request": "Write a goal."}}
    brief, _ = cases.assemble_brief(doc, text, [item], cfg, N)
    assert brief["context_strength"] == "thin"
    assert "goal-1234" not in brief["brief"]          # self link stripped
    assert "## Summary" not in brief["brief"]         # heading left without content is dropped


def test_progress_lines_and_linked_issue_heading(tmp_path):
    body = " ".join(["The proposal body explains its own design in plain words."] * 20)
    text = "# Widgets\n\n- RFC PR #: [rust-lang/rfcs#243](https://github.com/rust-lang/rfcs/pull/243)\n\n" + body
    doc = {"identity": "text/0243-widgets.md", "url": "https://example.org/rfc", "id": "r"}
    item = context_item("rfcs", "review_thread", "pr243",
                        "Title: Widgets\n\nWe need widgets because the current design cannot express them at all.\n"
                        "- [x] Stabilize widgets\n  - Beta release target (x.y): 1.27\n", ["r"])
    item["url"] = "https://github.com/rust-lang/rfcs/pull/243"
    item["label"] = "RFC pull request opening post"
    cfg = {"context": {"request": "Write an RFC.", "collectors": []}}
    brief, prov = cases.assemble_brief(doc, text, [item], cfg, N)
    assert "## RFC pull request opening post" in brief["brief"]   # label kept although the body links the PR
    assert "Stabilize widgets" not in brief["brief"] and "1.27" not in brief["brief"]
    assert prov[0]["progress_lines_dropped"] == 2


def test_dash_list_header_accepts_hash_fields():
    fields, end = docmeta.parse_dash_list("- Start Date: 2014-09-16\n- RFC PR #: rust-lang/rfcs#243\n- Rust Issue #: x\n\n# Summary\n")
    assert fields == {"Start Date": "2014-09-16", "RFC PR": "rust-lang/rfcs#243", "Rust Issue": "x"}
    assert end > 0


def test_html_block_text_keeps_inline_runs():
    bs4 = pytest.importorskip("bs4")
    pytest.importorskip("yaml")
    context = importlib.import_module("context")
    soup = bs4.BeautifulSoup("<div><p>Use the <code>?</code> operator\nfor <a href='#'>errors</a>.</p><ul><li>one</li><li>two</li></ul>"
                             "<pre>a\nb</pre></div>", "html.parser")
    assert context.html_block_text(soup) == "Use the ? operator for errors.\n\none\n\ntwo\n\na\nb"


def test_check_detects_inputs_leaking_into_generator_input(catalog, monkeypatch):
    data = catalog["data"]
    real = cases.generator_input

    def leaky(case, data_dir=None, context_items=None):
        gen = real(case, data_dir, context_items)
        if case["case_type"] == "pm_plan":
            gen["conversation"].append({"role": "human", "text": Path(case["baseline"]["path"]).read_text()})
        return gen

    monkeypatch.setattr(cases, "generator_input", leaky)
    counts = cases.check(data_dir=data)["failure_counts"]
    assert counts.get("baseline_in_generator_input")


def test_check_detects_self_attachment(catalog):
    data = catalog["data"]
    pep = catalog["docs"]["peps/pep-9999.rst"]
    ctx = data / "context" / "peps.jsonl"
    items = [json.loads(l) for l in ctx.read_text().splitlines()]
    for item in items:
        if item["role"] == "process":
            item["document_id"] = pep["id"]
    ctx.write_text("".join(json.dumps(i) + "\n" for i in items))
    cases._load_context_items.cache_clear()
    counts = cases.check(data_dir=data)["failure_counts"]
    cases._load_context_items.cache_clear()
    assert counts.get("document_attached_to_itself")


# --- context timing ------------------------------------------------------------

def test_context_written_after_document_is_excluded(catalog):
    pep = catalog["docs"]["peps/pep-9999.rst"]
    case = next(c for c in catalog["cases"] if c["case_id"] == "doc:" + pep["id"])
    brief = case["inputs"]["brief"]
    assert "leak memory through the widget table" in brief       # thread opened before the PEP's date
    assert "accepted design now ships" not in brief              # thread opened after it
    assert "pull request adds the finished PEP" not in brief     # written after by nature
    excluded = {p["kind"]: p["excluded"] for p in case["provenance"]["items_considered"] if p.get("excluded")}
    assert excluded == {"discussion_thread": "written 2020-03-01, after the document (2020-01-01)",
                        "review_thread": "written after the document"}
    assert case["provenance"]["document_date"]["date"] == "2020-01-01"
    assert case["inputs"]["attachments"][0]["version"]["committed"] == "2019-06-01"
    rfc = catalog["docs"]["rfc9999.txt"]
    rfc_case = next(c for c in catalog["cases"] if c["case_id"] == "doc:" + rfc["id"])
    assert "IESG" not in rfc_case["inputs"]["brief"] and rfc_case["provenance"]["context_strength"] == "thin"
    timing = catalog["coverage"]["context_timing"]
    assert timing["peps"]["discussion_thread"] == {"admitted": 1, "excluded": 1}
    assert timing["rfcs"]["milestone"] == {"excluded": 1}
    md = (catalog["data"].parent / "reports" / "case-coverage.md").read_text()
    assert "## Context written after the document" in md


def test_timing_exclusion_rules():
    rule = cases.timing_exclusion
    assert rule({"written": "before"}, None) is None
    assert rule({"written": "with_document"}, None) is None
    assert rule({"written": "identity"}, None) is None
    assert rule({"written": "after"}, "2020-01-01") == "written after the document"
    assert rule({}, "2020-01-01") == "written after the document"                    # unstamped counts as later
    assert rule({"written": "dated", "written_at": "2020-01-01"}, "2020-01-01") is None  # same day admitted
    assert rule({"written": "dated", "written_at": "2020-01-02"}, "2020-01-01").startswith("written 2020-01-02")
    assert rule({"written": "dated", "written_at": "2019-01-01"}, None) == "document date unknown"
    assert rule({"written": "dated"}, "2020-01-01") == "item date unknown"


def test_check_flags_context_written_after_document(catalog):
    data = catalog["data"]
    pep = catalog["docs"]["peps/pep-9999.rst"]
    path = data / "cases" / "catalog.jsonl"
    rows = [json.loads(l) for l in path.read_text().splitlines()]
    late = next(json.loads(l) for l in (data / "context" / "peps.jsonl").read_text().splitlines() if '"review_thread"' in l)
    for row in rows:
        if row["case_id"] == "doc:" + pep["id"]:
            row["provenance"]["brief_items"].append({"context_id": late["id"]})
            row["inputs"]["attachments"][0]["version"]["committed"] = "2021-01-01"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    counts = cases.check(data_dir=data)["failure_counts"]
    assert counts.get("brief_uses_context_written_after_document") == 1
    assert counts.get("attachment_version_after_document") == 1


def test_stamp_timing_and_document_dates():
    pytest.importorskip("bs4")
    pytest.importorskip("yaml")
    context = importlib.import_module("context")
    source = {"id": "s", "context": {"document_date": {"from": "metadata", "field": "Created", "basis": "Created"}}}
    index = {"id": "i", "kind": "index_entry", "fields": {"Title": "Widgets", "Index entry": "A design that adds widgets."},
             "text": "Title: Widgets\nIndex entry: A design that adds widgets.", "applies_to": ["d"]}
    cfg = {"written": {"index_entry": "identity"}, "identity_fields": ["Index section", "Title"], "written_note": {"index_entry": "n"}}
    item = context.stamp_timing(index, cfg)
    assert item["written"] == "identity" and item["text"] == "Title: Widgets" and item["fields_withheld"] == ["Index entry"]
    issue = context.stamp_timing({"id": "t", "kind": "tracking_issue", "fields": {"created_at": "2019-12-31T23:30:00-05:00"},
                                  "text": "x", "applies_to": ["d"]}, {"written": "dated"})
    assert issue["written_at"] == "2020-01-01"                     # UTC day
    meta = {"id": "m", "kind": "metadata", "fields": {"Created": "05-Sep-2022"}, "applies_to": ["d"]}
    assert context.document_dates(source, [{"id": "d"}], [meta]) == {"d": {"date": "2022-09-05", "basis": "Created"}}
    with pytest.raises(ValueError):
        context.stamp_timing({"kind": "x", "fields": {}, "text": ""}, {"written": "sometime"})


def test_process_versions_predate_each_document(monkeypatch):
    pytest.importorskip("bs4")
    pytest.importorskip("yaml")
    context = importlib.import_module("context")
    history = {"tmpl.md": [("2021-05-01", "c3"), ("2020-01-01", "c2"), ("2020-01-01", "c1b")], "old-tmpl.md": [("2020-01-01", "c1b"), ("2018-01-01", "c0")]}
    monkeypatch.setattr(context, "file_history", lambda repo, branch, path: history[path])

    def fake_fetch(url, binary=False):
        if "c1b/old-tmpl.md" in url:
            raise context.FetchError("HTTP 404")  # the rename commit removed the old path
        return url.rsplit("/", 2)[-2] + " text", "2026-10-21T00:00:00+00:00"

    monkeypatch.setattr(context, "fetch", fake_fetch)
    source = {"id": "s", "url": "https://github.com/o/r.git"}
    docs = [{"id": d, "identity": f"docs/{d}.md"} for d in ("a", "b", "c", "undated")]
    dates = {"a": {"date": "2022-01-01"}, "b": {"date": "2020-01-01"}, "c": {"date": "2017-01-01"}}
    cfg = {"branch": "main", "files": [{"path": "tmpl.md", "former_paths": ["old-tmpl.md"]}], "label": "template"}
    items, errors = context.collect_process(source, docs, cfg, dates)
    assert errors == []
    used = {i["version"]["commit"]: i["applies_to"] for i in items}
    assert used == {"c3": ["a"], "c2": ["b"]}  # c: older than every version; undated: no attachment


def test_recorded_title_is_cut_from_plain_text_body():
    title = "Transition and Modernization of the Internet Registration Service"
    text = ("Network Working Group                          S. Williamson\n\n          Transition and Modernization\n"
            "       of the Internet Registration Service\n\nStatus of this Memo\n\n   This memo provides information.\n")
    entry = context_item("rfcs", "index_entry", "rfc1400", f"Title: {title}\nAuthors: S. Williamson", ["r"],
                         written="identity", fields={"Title": title})
    doc = {"identity": "rfc1400.txt", "url": "https://example.org/rfc1400", "id": "r"}
    brief, _ = cases.assemble_brief(doc, text, [entry], {"context": {"request": "Write an RFC."}}, N)
    assert title in brief["brief"] and brief["titles"] == [title]
    grams = cases.body_ngrams(text, None, N, [title])
    assert not cases.shared_ngrams(title, grams, N)
    assert cases.shared_ngrams(title, cases.body_ngrams(text, None, N), N)  # without the cut it would leak
