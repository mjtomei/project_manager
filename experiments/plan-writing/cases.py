"""Build the case catalog: whole-document briefs, continuation cases, PM cases.

Run after collect.py and context.py:
    python3 cases.py            # build data/cases/catalog.jsonl + coverage
    python3 cases.py --check    # validate the built catalog

Whole-document cases pair a brief assembled from a document's surrounding
context (never its body) with the original document as reference.
Continuation cases show a document up to a section heading and hold the
section that starts there as reference. PM cases use recovered planning
conversations as the prompt and the current plan file as the production
baseline. Generator inputs come only from `generator_input`, which never
reads a reference span or a baseline.

The catalog stores offsets into the corpus text files rather than copies of
prefixes and references, plus each text's sha256 so stale offsets are
detected. Everything is written under data/ (gitignored); the summary in
reports/ is safe to commit.
"""

import argparse
import functools
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import docmeta
import pm_cases
import sections

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
CASES = DATA / "cases"
REPORTS = HERE / "reports"
REQUEST_KINDS = {"tracking_issue", "review_thread", "discussion_thread", "study_call", "charter", "milestone"}
TITLE_FIELDS = {"Title", "title", "Feature Name", "RFC number", "RFD"}
CONTINUATION_INSTRUCTION = ("Below is the beginning of a document, ending where a new section begins. "
                            "Write the next section of the document, continuing from where the text stops.")
BRIEF_PREAMBLE = ("The following context was recovered from the project's own records: requests, metadata, "
                  "index entries and calls that state what the document is for. It does not contain the document.")
URL = re.compile(r"https?://\S+")
PASTE_FRACTION = 0.3   # share of an item's segments quoting the body that marks a pasted draft
FRAGMENT_TOKENS = 6
RICH_WORDS = 20         # prose words of request text that make a brief "rich"
BOILERPLATE = re.compile(  # sections that are not authored content: never continuation targets
    r"^(status of this memo|copyright( notice| statement)?|full copyright statement|intellectual property( rights)?|"
    r"authors?'? addresses|author's address|authors' information|contributors' addresses|(table of )?contents|index|"
    r"(normative |informative )?references|bibliography|licen[cs]e|footnotes|acknowledge?ments?|changelog|change log)$")
NON_PROSE = re.compile(r"^\s*(\||#|Title:|Opened by |[-*]?\s*$)")


# --- text utilities ---------------------------------------------------------

def tokens(text):
    return re.findall(r"[a-z0-9]+", text.lower())


def ngrams(toks, n):
    return {tuple(toks[i:i + n]) for i in range(len(toks) - n + 1)}


def segments(text):
    """Split context text into lines and long lines into sentences.

    Whitespace separators are kept as their own pieces so "".join(pieces)
    reproduces the text; only non-blank pieces are ever dropped.
    """
    out = []
    for line in text.splitlines():
        if len(line) > 200:
            out.extend(p for p in re.split(r"((?<=[.!?])\s+(?=[A-Z\[(`\"']))", line) if p)
        else:
            out.append(line)
        out.append("\n")
    return out[:-1]


def drop_dangling_headings(text):
    """Remove markdown headings left with no content after filtering."""
    lines = text.splitlines()
    keep = []
    for i, line in enumerate(lines):
        if re.match(r"^#{1,6}\s", line):
            rest = next((l for l in lines[i + 1:] if l.strip()), None)
            if rest is None or re.match(r"^#{1,6}\s", rest):
                continue
        keep.append(line)
    return "\n".join(keep)


def request_words(text):
    """Words of prose in request text: not table rows, headings, bare URLs or the collector's header lines."""
    return sum(len(URL.sub("", l).split()) for l in text.splitlines() if not NON_PROSE.match(l))


def shared_ngrams(text, body_grams, n):
    toks = tokens(text)
    return [i for i in range(len(toks) - n + 1) if tuple(toks[i:i + n]) in body_grams]


# --- corpus and context -------------------------------------------------------

def load_config():
    return json.loads((HERE / "sources.json").read_text())


def load_corpus():
    return [json.loads(line) for line in (DATA / "corpus.jsonl").read_text().splitlines()]


def load_context():
    by_doc, process = defaultdict(list), defaultdict(list)
    for path in sorted((DATA / "context").glob("*.jsonl")):
        for line in path.read_text().splitlines():
            item = json.loads(line)
            if item["role"] == "process":
                process[item["source"]].append(item)
            else:
                for doc_id in item["applies_to"]:
                    by_doc[doc_id].append(item)
    return by_doc, process


def read_text(doc):
    return (DATA / doc["text_path"]).read_text(encoding="utf-8", errors="replace")


def header_format(source_cfg):
    for c in source_cfg.get("context", {}).get("collectors", []):
        if c["type"] == "header":
            return c["format"]
    return None


# --- split groups ------------------------------------------------------------

def split_groups(docs, by_doc, source_cfgs):
    """Project-level groups, IETF by working group, then merged across duplicates."""
    base = {}
    for d in docs:
        group = d["split_group"]
        if source_cfgs.get(d["source"], {}).get("split_group_rule") == "ietf_working_group":
            entry = next((i["fields"] for i in by_doc.get(d["id"], []) if i["kind"] == "index_entry"), {})
            wg, stream = entry.get("Working group"), entry.get("Stream", "unknown")
            group = "ietf-" + (wg or "nonwg-" + re.sub(r"\W+", "-", stream.lower()))
        base[d["id"]] = group
    parent = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent.setdefault(parent[x], parent[x])
            x = parent[x]
        return x

    by_dup = defaultdict(list)
    for d in docs:
        by_dup[d["duplicate_group"]].append(base[d["id"]])
    for groups in by_dup.values():
        for g in groups[1:]:
            a, b = find(groups[0]), find(g)
            if a != b:
                parent[max(a, b)] = min(a, b)
    return {d["id"]: find(base[d["id"]]) for d in docs}


# --- briefs ------------------------------------------------------------------

def self_reference(doc):
    """Predicate for URLs that point at the document itself (its page, path or numbered name)."""
    path = Path(doc["identity"])
    marks = {doc["url"].rstrip("/")}
    if "/" in doc["identity"] and not doc["identity"].startswith("http"):
        marks.add(doc["identity"])
    for name in (path.stem, path.parent.name):
        if len(name) >= 6 and re.search(r"\d", name):
            marks.add(name)
    return lambda url: any(m in url for m in marks)


def assemble_brief(doc, text, items, process_items, source_cfg, n):
    """Brief text, attachments and provenance, or None when no purpose-stating context survives."""
    body = docmeta.body_text(text, header_format(source_cfg))
    body_grams = ngrams(tokens(body), n)
    is_self = self_reference(doc)
    request = source_cfg["context"]["request"]
    if any(i.get("doc_role") == "supporting document" for i in items):
        request += f" This is a supporting document ({Path(doc['identity']).name}) within the proposal's directory, not the proposal itself."
    blocks = [[request], [BRIEF_PREAMBLE]]
    provenance = []
    for item in sorted(items, key=lambda i: (i["kind"] not in ("index_entry", "metadata"), i["kind"], i["id"])):
        text_in = URL.sub(lambda m: "" if is_self(m.group(0)) else m.group(0), item["text"])
        segs = segments(text_in)
        hit = [bool(x.strip()) and bool(shared_ngrams(x, body_grams, n)) for x in segs]
        total, dropped = sum(1 for x in segs if x.strip()), sum(hit)
        truncated = total and dropped / total >= PASTE_FRACTION
        if truncated:
            # The item quotes the document at length (a pasted draft); keep only what precedes the quote.
            first = hit.index(True)
            hit = [h or i >= first for i, h in enumerate(hit)]
        else:
            # Short leftovers sandwiched between quoted passages are fragments of the document.
            solid = [i for i, x in enumerate(segs) if x.strip()]
            for a, b, c in zip(solid, solid[1:], solid[2:]):
                if hit[a] and hit[c] and not hit[b] and len(tokens(segs[b])) < FRAGMENT_TOKENS:
                    hit[b] = True
        kept = ["" if h else x for x, h in zip(segs, hit)]
        provenance.append({"context_id": item["id"], "kind": item["kind"], "label": item.get("label", item["kind"]),
                           "url": item["url"], "retrieved_at": item["retrieved_at"], "sha256": item["sha256"],
                           "segments_total": total, "segments_dropped": sum(1 for x, h in zip(segs, hit) if x.strip() and h),
                           "truncated_at_quoted_document": bool(truncated)})
        blocks.append([f"## {item.get('label', item['kind'])}" + (f" ({item['url']})" if item.get("url") else ""), "\n"] + kept)
    # Second pass over the assembled text: passages can straddle piece boundaries.
    while True:
        flat = [(bi, si) for bi, b in enumerate(blocks) for si in range(len(b))]
        owner, toks = [], []
        for idx, (bi, si) in enumerate(flat):
            t = tokens(blocks[bi][si])
            toks.extend(t)
            owner.extend([idx] * len(t))
        hits = [i for i in range(len(toks) - n + 1) if tuple(toks[i:i + n]) in body_grams]
        if not hits:
            break
        for idx in {owner[j] for i in hits for j in range(i, i + n)}:
            bi, si = flat[idx]
            blocks[bi][si] = ""
            if bi >= 2 and si >= 2:
                provenance[bi - 2]["segments_dropped"] += 1
    kept_items = []
    for p, block in zip(provenance, blocks[2:]):
        content = drop_dangling_headings("\n".join(l.rstrip() for l in "".join(block[2:]).splitlines()))
        content = re.sub(r"\n{3,}", "\n\n", content).strip()
        p["words_kept"] = len(content.split())
        p["request_words_kept"] = request_words(content) if p["kind"] in REQUEST_KINDS else 0
        if p["words_kept"]:
            kept_items.append((p, block[0], content))
    qualifying = [p for p, _, c in kept_items if p["kind"] in REQUEST_KINDS or p["kind"] in ("index_entry", "index_preamble")
                  or (p["kind"] == "metadata" and any(re.search(rf"^{re.escape(f)}:", c, re.M) for f in TITLE_FIELDS))]
    if not qualifying:
        return None, provenance
    parts = [blocks[0][0], blocks[1][0]] + [(head + "\n" if head else "") + content for _, head, content in kept_items]
    brief = "\n\n".join(x for x in parts if x.strip())
    rich = any(p["request_words_kept"] >= RICH_WORDS for p, _, _ in kept_items)
    attachments = [{"context_id": i["id"], "label": i.get("label"), "url": i["url"], "sha256": i["sha256"],
                    "retrieved_at": i["retrieved_at"]}
                   for i in process_items if i.get("document_id") != doc["id"]]
    return {"brief": brief, "attachments": attachments, "context_strength": "rich" if rich else "thin",
            "items": [p for p, _, _ in kept_items]}, provenance


# --- continuation cases ------------------------------------------------------

def continuation_cases(doc, text, raw, cfg):
    method, found = sections.headings(doc, text, raw)
    eligible = []
    for i, h in enumerate(found):
        if h.start == 0 or BOILERPLATE.match(re.sub(r"^(appendix\s+[a-z](\.\d+)*\.?\s+|\d+(\.\d+)*\.?\s+)", "", h.title.lower()).strip(" :.")):
            continue
        end = sections.section_end(found, i, len(text))
        prefix_words = len(text[: h.start].split())
        ref_words = len(text[h.start: end].split())
        if prefix_words >= cfg["min_prefix_words"] and cfg["min_reference_words"] <= ref_words <= cfg["max_reference_words"]:
            section_body = text[h.end: end].strip()
            if len(section_body) >= 200 and section_body in text[: h.start]:
                continue  # the document repeats this section verbatim earlier: copying is not continuing
            eligible.append((h, end, prefix_words, ref_words))
    k = cfg["max_cases_per_document"]
    if len(eligible) > k:
        picks = sorted({round(j * (len(eligible) - 1) / (k - 1)) for j in range(k)}) if k > 1 else [len(eligible) // 2]
        chosen = [eligible[j] for j in picks]
    else:
        chosen = eligible
    cases = []
    for h, end, prefix_words, ref_words in chosen:
        cases.append({
            "case_id": f"cont:{doc['id']}:{h.start}", "case_type": "continuation",
            "inputs": {"document_id": doc["id"], "text_path": doc["text_path"], "prefix_end": h.start,
                       "instruction": CONTINUATION_INSTRUCTION, "prefix_words": prefix_words},
            "reference": {"document_id": doc["id"], "start": h.start, "end": end, "heading": h.title, "level": h.level,
                          "words": ref_words},
        })
    return method, len(found), len(eligible), cases


# --- generator inputs --------------------------------------------------------

def _context_items(data_dir=None):
    return _load_context_items(str(Path(data_dir or DATA)))


@functools.lru_cache(maxsize=4)
def _load_context_items(data_dir):
    items = {}
    for path in (Path(data_dir) / "context").glob("*.jsonl"):
        for line in path.read_text().splitlines():
            item = json.loads(line)
            items[item["id"]] = item
    return items


def generator_input(case, data_dir=None, context_items=None):
    """Everything a generator may see for a case; never the reference or baseline."""
    data_dir = Path(data_dir or DATA)
    kind = case["case_type"]
    if kind == "whole_document":
        items = context_items if context_items is not None else _context_items(data_dir)
        return {"brief": case["inputs"]["brief"],
                "attachments": [{"label": a["label"], "text": items[a["context_id"]]["text"]}
                                for a in case["inputs"]["attachments"] if a["context_id"] in items]}
    if kind == "continuation":
        text = (data_dir / case["inputs"]["text_path"]).read_text(encoding="utf-8", errors="replace")
        if hashlib.sha256(text.encode()).hexdigest() != case["provenance"]["text_sha256"]:
            raise ValueError(f"{case['case_id']}: document text changed since the catalog was built")
        return {"instruction": case["inputs"]["instruction"], "prefix": text[: case["inputs"]["prefix_end"]]}
    if kind == "pm_plan":
        convo = json.loads(Path(case["inputs"]["conversation_path"]).read_text())
        turns = [{"role": t["role"], "text": t["text"]} for e in convo["excerpts"] for t in e["turns"]]
        return {"instruction": case["inputs"]["instruction"], "conversation": turns}
    raise ValueError("Unknown case type: " + kind)


# --- build -------------------------------------------------------------------

def build(limit_sources=None):
    config = load_config()
    prep = config["case_preparation"]
    source_cfgs = {s["id"]: s for s in config["sources"]}
    docs = load_corpus()
    by_doc, process = load_context()
    groups = split_groups(docs, by_doc, source_cfgs)
    CASES.mkdir(parents=True, exist_ok=True)
    statuses, cases_out = {}, []
    n = prep["brief_leak_ngram"]
    for doc in docs:
        if limit_sources and doc["source"] not in limit_sources:
            continue
        cfg = source_cfgs[doc["source"]]
        text = read_text(doc)
        raw = (DATA / doc["raw_path"]).read_bytes()
        common = {"document_id": doc["id"], "source": doc["source"], "split_group": groups[doc["id"]],
                  "duplicate_group": doc["duplicate_group"]}
        doc_prov = {"document_id": doc["id"], "source": doc["source"], "identity": doc["identity"], "url": doc["url"],
                    "revision": doc["revision"], "retrieved_at": doc["retrieved_at"], "text_sha256": doc["sha256"]}
        status = {"source": doc["source"], "identity": doc["identity"], "words": doc["words"], "brief": None,
                  "continuation_cases": 0}
        if cfg.get("context") and doc["words"]:
            brief, item_prov = assemble_brief(doc, text, by_doc.get(doc["id"], []), process.get(doc["source"], []), cfg, n)
            status["context_items"] = len(item_prov)
            if brief:
                cases_out.append({"case_id": "doc:" + doc["id"], "case_type": "whole_document", **common,
                                  "inputs": {"brief": brief["brief"], "attachments": brief["attachments"]},
                                  "reference": {"document_id": doc["id"], "text_path": doc["text_path"],
                                                "sha256": doc["sha256"], "words": doc["words"]},
                                  "provenance": {**doc_prov, "brief_items": brief["items"], "items_considered": item_prov,
                                                 "context_strength": brief["context_strength"], "leak_ngram": n,
                                                 "assembly": "deterministic; no model calls"}})
                status["brief"] = brief["context_strength"]
        method, found, eligible, conts = continuation_cases(doc, text, raw, prep["continuation"]) if doc["words"] else ("none", 0, 0, [])
        for c in conts:
            c.update(common)
            c["provenance"] = {**doc_prov, "boundary_method": method, "headings_detected": found, "eligible_boundaries": eligible}
            cases_out.append({k: c[k] for k in ("case_id", "case_type", "document_id", "source", "split_group",
                                                 "duplicate_group", "inputs", "reference", "provenance")})
        status.update({"boundary_method": method, "headings_detected": found, "eligible_boundaries": eligible,
                       "continuation_cases": len(conts)})
        if not status["brief"] and not conts:
            status["dropped"] = ("empty text" if not doc["words"] else "no headings detected" if not found
                                 else "no section boundary meets the prefix/reference length limits")
            status["dropped"] += "; no recoverable context" if cfg.get("context") else "; source has no context collector"
        statuses[doc["id"]] = status
    pm_list, pm_report = pm_cases.build(DATA / "pm")
    cases_out.extend(pm_list)
    with open(CASES / "catalog.jsonl", "w") as handle:
        for c in cases_out:
            handle.write(json.dumps(c) + "\n")
    coverage = coverage_report(docs, statuses, cases_out, pm_report, limit_sources)
    (CASES / "coverage.json").write_text(json.dumps(coverage, indent=1) + "\n")
    write_summary(coverage)
    print(json.dumps(coverage["totals"], indent=1))


def coverage_report(docs, statuses, cases_out, pm_report, limit_sources=None):
    by_source = defaultdict(Counter)
    for doc in docs:
        if limit_sources and doc["source"] not in limit_sources:
            continue
        s = statuses[doc["id"]]
        c = by_source[doc["source"]]
        c["documents"] += 1
        c["brief_rich"] += s["brief"] == "rich"
        c["brief_thin"] += s["brief"] == "thin"
        has_cont = s["continuation_cases"] > 0
        c["both_case_types"] += bool(s["brief"]) and has_cont
        c["whole_document_only"] += bool(s["brief"]) and not has_cont
        c["continuation_only"] += has_cont and not s["brief"]
        c["dropped"] += "dropped" in s
    case_counts = defaultdict(Counter)
    for case in cases_out:
        case_counts[case["source"]][case["case_type"]] += 1
    context_status = {}
    for path in sorted((DATA / "context").glob("*.status.json")):
        st = json.loads(path.read_text())
        context_status[st["source"]] = {"items": st["items"], "by_kind": st["by_kind"], "fetch_errors": len(st["errors"])}
    sources = {}
    for sid in sorted(by_source):
        sources[sid] = {**dict(by_source[sid]), "cases": dict(case_counts[sid]), "context": context_status.get(sid)}
    totals = Counter()
    for v in by_source.values():
        totals.update(v)
    totals = dict(totals)
    totals["cases"] = dict(sum((case_counts[s] for s in case_counts), Counter()))
    dropped = [{"document_id": d, "source": s["source"], "identity": s["identity"], "reason": s["dropped"]}
               for d, s in statuses.items() if "dropped" in s]
    return {"totals": totals, "sources": sources, "dropped": sorted(dropped, key=lambda x: (x["source"], x["identity"])),
            "pm_plans": pm_report, "documents": statuses}


def write_summary(coverage):
    REPORTS.mkdir(exist_ok=True)
    summary = {k: coverage[k] for k in ("totals", "sources", "dropped")}
    summary["pm_plans"] = [{k: p.get(k) for k in ("plan", "status", "case_id", "human_turns", "map_evidence")} for p in coverage["pm_plans"]]
    if "check" in coverage:
        summary["check"] = coverage["check"]
    (REPORTS / "case-coverage.json").write_text(json.dumps(summary, indent=1) + "\n")
    t = coverage["totals"]
    lines = ["# Case catalog coverage", "",
             "Generated by `experiments/plan-writing/cases.py` from the collected corpus and recovered context. "
             "The catalog itself is under the gitignored `data/cases/`; this file is the committed summary.", "",
             f"Documents: {t.get('documents', 0)}. Whole-document briefs: {t.get('brief_rich', 0) + t.get('brief_thin', 0)} "
             f"({t.get('brief_rich', 0)} rich, {t.get('brief_thin', 0)} thin). Both case types: {t.get('both_case_types', 0)}; "
             f"whole-document only: {t.get('whole_document_only', 0)}; continuation only: {t.get('continuation_only', 0)}; "
             f"dropped: {t.get('dropped', 0)}.", "",
             "Cases by type: " + ", ".join(f"{k} {v}" for k, v in sorted(t["cases"].items())) + ".", "",
             "*Rich* briefs contain request text (issue, review thread, discussion, study call, charter or milestone); "
             "*thin* briefs carry only index or metadata context.", "",
             "## By source", "",
             "| Source | Docs | Brief rich | Brief thin | Both | Whole only | Cont. only | Dropped | Whole cases | Cont. cases | Context items (fetch errors) |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for sid, s in coverage["sources"].items():
        ctx = s.get("context")
        lines.append(f"| {sid} | {s.get('documents', 0)} | {s.get('brief_rich', 0)} | {s.get('brief_thin', 0)} | {s.get('both_case_types', 0)} | "
                     f"{s.get('whole_document_only', 0)} | {s.get('continuation_only', 0)} | {s.get('dropped', 0)} | "
                     f"{s['cases'].get('whole_document', 0)} | {s['cases'].get('continuation', 0)} | "
                     + (f"{ctx['items']} ({ctx['fetch_errors']})" if ctx else "no collector") + " |")
    lines += ["", "## PM plans", "", "| Plan | Status | Case | Human turns |", "|---|---|---|---|"]
    for p in coverage["pm_plans"]:
        lines.append(f"| {p['plan']} | {p['status']} | {p.get('case_id') or ''} | {p.get('human_turns') if p.get('human_turns') is not None else ''} |")
    reasons = Counter((d["source"], d["reason"]) for d in coverage["dropped"])
    lines += ["", "## Dropped documents", "",
              "Documents with neither recoverable context nor a usable section boundary. The full list with ids is in "
              "`case-coverage.json` under `dropped`.", "", "| Source | Reason | Count |", "|---|---|---|"]
    for (sid, reason), count in sorted(reasons.items()):
        lines.append(f"| {sid} | {reason} | {count} |")
    prep = load_config()["case_preparation"]
    cont = prep["continuation"]
    lines += ["", "## Rules and limits", "",
              f"- Briefs never share a run of {prep['brief_leak_ngram']} words with the document body (body excludes the "
              "metadata header and title line). A context item that quotes the body for 30% or more of its segments is "
              "cut where the quote starts. Process documents and templates are attachments, not brief text.",
              f"- Continuation cases: up to {cont['max_cases_per_document']} per document, spread over eligible headings; "
              f"prefix at least {cont['min_prefix_words']} words, reference {cont['min_reference_words']}–"
              f"{cont['max_reference_words']} words. Boilerplate sections (copyright, IPR, references, addresses, contents) "
              "and sections repeated verbatim earlier in the document are never references.",
              "- Heading detection in PDF text (NASA, CERN, HS2) relies on numbered headings and is heuristic; "
              "numbered list items can be mistaken for sections.",
              "- PM cases carry `needs_review`: the session map locates candidate provenance, not assent. Reviewed windows "
              "are in `pm_case_windows.json`. The Codex history behind plan-delivery is not mounted in this environment.",
              "- Context fetch errors are listed per source in `data/context/<source>.status.json`."]
    if "check" in coverage:
        lines += ["", "## Validation", "", "```", json.dumps(coverage["check"], indent=1), "```"]
    (REPORTS / "case-coverage.md").write_text("\n".join(lines) + "\n")


# --- validation --------------------------------------------------------------

def check(catalog_path=None, data_dir=None, corpus=None, coverage=None):
    """Validate catalog invariants; returns a dict of failures (empty lists when clean)."""
    data_dir = Path(data_dir or DATA)
    catalog_path = Path(catalog_path or data_dir / "cases" / "catalog.jsonl")
    cases = [json.loads(line) for line in catalog_path.read_text().splitlines()]
    corpus = corpus if corpus is not None else [json.loads(l) for l in (data_dir / "corpus.jsonl").read_text().splitlines()]
    coverage = coverage if coverage is not None else json.loads((data_dir / "cases" / "coverage.json").read_text())
    docs = {d["id"]: d for d in corpus}
    source_cfgs = {s["id"]: s for s in load_config()["sources"]}
    failures = defaultdict(list)
    items = _context_items(data_dir)
    heading_cache = {}
    for case in cases:
        cid = case["case_id"]
        if not case.get("provenance"):
            failures["missing_provenance"].append(cid)
        if not case.get("split_group"):
            failures["missing_split_group"].append(cid)
        if case["case_type"] == "whole_document":
            doc = docs[case["document_id"]]
            text = (data_dir / doc["text_path"]).read_text(encoding="utf-8", errors="replace")
            n = case["provenance"]["leak_ngram"]
            body = ngrams(tokens(docmeta.body_text(text, header_format(source_cfgs.get(doc["source"], {})))), n)
            if shared_ngrams(case["inputs"]["brief"], body, n):
                failures["brief_quotes_document_body"].append(cid)
            if not case["provenance"].get("brief_items"):
                failures["brief_without_item_provenance"].append(cid)
            gen = json.dumps(generator_input(case, data_dir, items))
            if len(text) > 400 and text[len(text) // 3: len(text) // 3 + 400] in gen:
                failures["reference_in_generator_input"].append(cid)
        elif case["case_type"] == "continuation":
            doc = docs[case["document_id"]]
            text = (data_dir / doc["text_path"]).read_text(encoding="utf-8", errors="replace")
            if doc["id"] not in heading_cache:
                raw = (data_dir / doc["raw_path"]).read_bytes()
                heading_cache = {doc["id"]: sections.headings(doc, text, raw)[1]}
            found = heading_cache[doc["id"]]
            end = case["inputs"]["prefix_end"]
            if not sections.is_boundary(found, end) or case["reference"]["start"] != end:
                failures["prefix_not_at_section_boundary"].append(cid)
            gen = generator_input(case, data_dir)
            reference = text[case["reference"]["start"]: case["reference"]["end"]]
            if reference.strip() and reference.strip() in gen["prefix"] + gen["instruction"]:
                failures["reference_in_generator_input"].append(cid)
            if len(gen["prefix"]) != end:
                failures["prefix_length_mismatch"].append(cid)
        elif case["case_type"] == "pm_plan":
            for rec in case["provenance"]["records"]:
                path = Path(rec["path"])
                if not path.exists():
                    failures["pm_record_missing"].append(cid)
                    continue
                with open(path, encoding="utf-8", errors="replace") as handle:
                    count = sum(1 for _ in handle)
                if not 0 < rec["event_line"] <= count or not rec["event_matches_plan"]:
                    failures["pm_event_not_in_record"].append(cid)
            if not case["provenance"]["records"]:
                failures["pm_without_conversation_record"].append(cid)
            baseline_path = pm_cases.REPO / case["baseline"]["path"]
            baseline = baseline_path.read_text() if baseline_path.exists() else None
            if baseline and baseline in json.dumps(generator_input(case, data_dir)):
                failures["baseline_in_generator_input"].append(cid)
    covered = coverage["documents"]
    missing = sorted(set(docs) - set(covered))
    extra = sorted(set(covered) - set(docs))
    if missing:
        failures["documents_missing_from_coverage"] = missing
    if extra:
        failures["unknown_documents_in_coverage"] = extra
    if coverage["totals"].get("documents") != len(docs):
        failures["coverage_total_mismatch"].append(f"{coverage['totals'].get('documents')} != {len(docs)}")
    return {"cases_checked": len(cases), "by_type": dict(Counter(c["case_type"] for c in cases)),
            "failures": {k: (v[:20] + ([f"... {len(v) - 20} more"] if len(v) > 20 else [])) for k, v in failures.items()},
            "failure_counts": {k: len(v) for k, v in failures.items()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="validate data/cases/catalog.jsonl")
    parser.add_argument("--sources", nargs="*", help="limit the build to these sources (for development)")
    args = parser.parse_args()
    if args.check:
        result = check()
        coverage = json.loads((CASES / "coverage.json").read_text())
        coverage["check"] = result
        (CASES / "coverage.json").write_text(json.dumps(coverage, indent=1) + "\n")
        write_summary(coverage)
        print(json.dumps(result, indent=1))
        raise SystemExit(1 if result["failure_counts"] else 0)
    build(args.sources)


if __name__ == "__main__":
    main()
