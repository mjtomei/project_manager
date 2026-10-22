# pr-9f111ef QA spec — Natural prompt suite and continuation cases

The user surface of this PR is a set of command-line steps run from
`experiments/plan-writing/` plus the case-access API an evaluation harness
consumes:

- `python3 context.py [--sources S ...] [--workers N]` — fetch the context that
  states each document's purpose into `data/context/<source>.{jsonl,status.json,dates.json}`,
  caching every fetched page under `data/context/raw/<host>/`.
- `python3 cases.py [--sources S ...]` — build `data/cases/catalog.jsonl`,
  `data/cases/coverage.json`, PM excerpts/baselines under `data/pm/`, and (full
  builds only) the committed `reports/case-coverage.{md,json}`.
- `python3 cases.py --check` — validate the built catalog; prints a JSON
  result (`cases_checked`, `by_type`, `failures`, `failure_counts`) and exits 1
  when any failure is counted.
- `cases.generator_input(case)` / `cases.reference_text(case)` — the only way a
  harness obtains what a generator may see, and the withheld reference.

## Setup (cross-cutting)

1. Work in a clone of the PR branch. Create a scratch venv with `bs4`, `pyyaml`,
   `pytest`; `unset PYTHONPATH` (container python lacks bs4). Install
   `poppler-utils` (pdftotext) if missing.
2. Seed `experiments/plan-writing/data/` from the collected corpus snapshot:
   `/opt/pm-src/experiments/plan-writing/data/` in containers (host:
   `/home/matt/claude-work/project-manager/experiments/plan-writing/data/`).
   It holds `corpus.jsonl` (18,963 records), `manifests/`, `text/`, `raw/`,
   `checkouts/`. Do not commit `data/`.
3. If the PR workdir's built `data/{context,cases,pm}` (and the fetch cache
   `data/context/raw/`) is reachable, it may be copied in to save fetch time;
   otherwise run `context.py` for the sources a scenario needs (network
   required; small sources: nasa-mission-concepts, nasa-luvoir, nasa-lynx,
   oxide-rfds, chromiumos-designs, quic-drafts, go-proposals, cockroach-rfcs).
4. PM cases read Claude histories at `$HOME/.claude/projects` (override with
   `PM_CLAUDE_PROJECTS`) and the map `pm/docs/plan-session-sources-2026-10-19.md`.
   The Codex history behind plan-delivery is not mounted; that is expected.

## 1. Requirements

R1 Context collection.
Given the corpus snapshot and network access,
When the user runs `context.py --sources <briefable sources>`,
Then each source gets `<source>.jsonl` (items with id, kind, url,
retrieved_at, sha256, text, applies_to, written stamp), `<source>.status.json`
(item counts, documents_with_items, documents_dated, by_kind, by_written,
errors) and `<source>.dates.json` (document date and basis), and a summary line
per source is printed.

R2 Context reruns are cached.
Given a completed `context.py` run,
When the user reruns it for the same sources,
Then it finishes far faster without refetching, the jsonl output keeps
the same item ids and sha256s, and no existing file under `data/context/raw/`
(including `raw/pdf/` copies) is rewritten (b769b725).

R3 Full catalog build.
Given context for some or all briefable sources,
When the user runs `cases.py` with no `--sources`,
Then `data/cases/catalog.jsonl` holds whole_document, continuation and pm_plan
cases; `coverage.json` and `reports/case-coverage.{md,json}` are rewritten; the
printed totals match the report.

R4 Briefs never quote the document.
Given a built catalog,
When the user (or harness) reads any whole_document case's generator input,
Then the brief shares no 8-token passage with the document body (title line
and recognised metadata header excepted) — including passages wrapped across
lines/pieces of a pasted draft in an issue/PR/thread post, which is truncated —
does not link the document's own URL/path (a removed self link keeps its link
text, leaves no dangling `[x](`, `(` or `<>`, and keeps sentence punctuation),
and process documents appear only as attachments with version
provenance (never attached to the document itself).

R5 Briefs only use context written before the document.
Given a built catalog,
When the user inspects brief provenance for go-proposals, cockroach-rfcs,
python-peps, kubernetes-keps, IETF/QUIC and rust sources,
Then no brief item is stamped `after` (Rust/Cockroach PR opening posts, Rust
tracking issues, milestones, Chromium preamble, Oxide RFD 1 never appear);
`dated` items (Go/PEP/KEP/Cockroach issues and threads) appear only when
written on or before the document date; PEP briefs draw on every discourse
thread named in Discussions-To or Post-History, in slugged, slugless
(`/t/<id>`) and post (`/t/<slug>/<id>/<post>`) forms, resolving to the topic id
rather than the post number (7c552b45); a brief counts as rich only when its
request items carry real words (bullets/punctuation-only pieces do not count); `identity` index items carry only
identifying fields (no RFC publication date/category/obsoletes, no RFD labels,
no index descriptions); attachment versions are committed on or before the
document date.

R6 IETF charter in force.
Given IETF/QUIC context,
When the user inspects a brief carrying a WG charter item,
Then the charter is the highest revision known to exist by the source draft's
-00 submission, revision 00 never appears, a group's first-event revision is
used only when a later event dates it, and RFCs whose first draft predates
datable events carry no charter.

R7 Every case records provenance and split group.
Given a built catalog,
When the user reads any case,
Then it has non-empty `provenance` and `split_group`; IETF RFCs group by WG
(`ietf-<wg>`; QUIC RFCs share `ietf-quic` with quic-drafts), duplicate
documents (same sha256) share a group, PM cases use `pm-plans`.

R8 Continuation cases.
Given a built catalog,
When the harness obtains a continuation case's generator input,
Then the prefix ends exactly at a detected heading start, the instruction asks
for the next section without revealing its heading, `reference_text` returns
that section (heading through the next same-or-shallower heading), the
reference is absent from the generator input, and each document yields at most
3 cases meeting the length limits (prefix ≥100 words, reference 30–4000 words).
Documents with briefs carry both case types.

R9 PM natural-prompt cases.
Given the Claude histories mounted and the plan-session map,
When the user builds the catalog,
Then each recovered plan yields a `pm:<plan>` case whose provenance names an
existing conversation record line that matches the plan write/edit event;
generator input is the excerpt (human/assistant/source_file turns, oldest
session first) and never the baseline; `reference_text` returns the
build-time baseline snapshot; each case records task_kind (new/edit/reformat),
human-turn fidelity applicability, source files and source gaps; plans without
located history are listed with status (not_located, history_not_mounted,
not_in_map), never fabricated.

R10 Coverage report accounts for every document.
Given a full build,
When the user reads `reports/case-coverage.md`/`.json`,
Then per-source rows sum to the 18,963 corpus documents, every document
appears exactly once in coverage, dropped documents are listed with a reason
(empty text / no headings / no eligible boundary + no context / no collector),
the PM table and the "Context written after the document" table are present.

R11 Validation.
Given a freshly built catalog,
When the user runs `cases.py --check`,
Then it prints `failure_counts` empty and exits 0.

## 2. Edge cases / failure modes

E1 Building without bs4: `cases.py` (build) exits with an argparse error
saying building needs bs4; `cases.py --check` without bs4 reports
`boundary_method_differs_from_build` rather than false boundary failures.

E2 Unknown or collector-less source: `context.py --sources linux-docs` (or a
typo) errors listing "Sources without context collectors".

E3 Stale inputs: after a corpus text file, a context item, a PM excerpt or a
baseline snapshot changes, `generator_input`/`reference_text` raise a
ValueError naming the case, and `--check` reports `stale_generator_input`,
`stale_reference` or `brief_item_missing_from_context`, exiting 1. Restoring
the file makes `--check` clean again.

E4 Partial build: `cases.py --sources X` writes a catalog/coverage for X only,
marks `partial_sources`, prints that the committed reports are left unchanged,
and `--check` validates only those sources and also leaves reports unchanged.
A following full build restores the full catalog and report.

E5 Missing histories: with `PM_CLAUDE_PROJECTS` pointed at an empty directory,
the build completes, PM plans are listed as not recovered (no pm_plan cases
with fabricated content), and `--check` stays clean.

E6 Fetch failures: unreachable hosts or 404s are recorded in
`status.json` `errors` and cached as metadata (404/410/451), the run
completes, and briefs fall back to the remaining items.

E7 Documents with neither context nor usable sections drop out and are listed
in the report with a reason; empty texts are dropped.

E8 `--check` before any catalog exists (fresh data/ with corpus only) fails
with a non-zero exit rather than reporting clean.

## 3. Concurrency (shared resources)

Shared on-disk resources: `data/context/raw/<host>/` fetch cache (written by
every context.py worker/process, read by later runs);
`data/context/<source>.{jsonl,status,dates}`; `data/cases/catalog.jsonl` and
`coverage.json` (rewritten by every build, read by the harness, and
read-modified-written by `--check`, which stores its result under `check`);
`reports/case-coverage.*` (committed; rewritten by full builds and by `--check`
on a full catalog, never on a partial one); `data/pm/{conversations,baselines,drafts}`;
`$HOME/.claude/projects` (read-only input).

C1 Two `context.py` processes over overlapping sources sharing the cache both
complete; outputs match a serial run; every cache metadata file is valid JSON.

C2 `--check` run while a build rewrites the catalog either validates a
complete catalog or fails loudly (non-zero exit / error), never reports clean
on a truncated catalog; a `--check` after the build completes is clean.

C3 Several harness workers reading generator inputs and references for
different case types in parallel get identical results to a serial read.

C5 Two `--check` runs at once over the same catalog both report the same
result; coverage.json stays valid JSON and the committed reports match a
serial `--check`.

C4 A partial and a full build racing: afterwards the committed reports are not
overwritten with partial data, and `--check` either passes on a consistent
catalog/coverage pair or flags the mismatch.

## 4. Pass/Fail criteria

Pass: every Then above observable from command output, generated files, or the
harness API; `--check` clean after a clean build. Fail: any brief with an
8-token body passage or self-link, any `after`-stamped or post-dated item in a
brief, a continuation prefix not ending at a heading or containing its
reference, a PM case without an existing record line or with baseline text in
its input, coverage missing/duplicating documents, a crash instead of a
recorded fetch error, a silent clean `--check` over stale or truncated data, or
committed reports overwritten by a partial build.

## 5. Ambiguities (resolved)

- Network: scenarios rebuild context only for small sources unless the PR
  workdir's cache is reachable; ietf-rfcs (9,841 docs) is exercised through
  quic-drafts and the committed report rather than a full uncached refetch.
- A full `cases.py` build covers all 18,963 documents even when context exists
  only for some sources; documents in context-less sources get continuation
  cases only. Coverage totals then differ from the committed report (fewer
  briefs) — that is expected; the committed report reflects the full build in
  the PR workdir.
- Exact counts (e.g. 55,204 cases, 3,094 rich briefs) depend on the full
  context store and cache dates; scenarios assert invariants and internal
  consistency, not those numbers, unless the full PR-workdir data is copied in.
- Concurrent writers (C2/C4) are not locked by design; the requirement is that
  the outcome is detected, not that it is prevented.

No unresolved ambiguities.
