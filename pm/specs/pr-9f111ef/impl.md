# pr-9f111ef — Natural prompt suite and continuation cases

Spec for the first PR of `pm/plans/plan-doc-eval.md`: build the case catalog
(whole-document briefs, continuation cases, PM natural-prompt cases) and a
coverage report over the collected corpus.

## Starting point (verified)

- `experiments/plan-writing/collect.py` collects 25 sources from
  `sources.json` into `data/` (gitignored): per-source manifests,
  `data/corpus.jsonl` (18,963 records: `id`, `source`, `identity`, `url`,
  `text_path`, `raw_path`, `sha256`, `split_group`, `duplicate_group`,
  `canonical_id`, ...), text under `data/text/<source>/<id>.txt`, raw files
  (git checkouts or `data/raw/<source>/<key>.raw`). The snapshot was copied from
  `/opt/pm-src/experiments/plan-writing/data/` into the working `data/`.
- Git sources use sparse checkouts limited to the document folders, so process
  files outside them (Go `README.md`, Rust `0000-template.md`/`README.md`) are
  absent. Some process files are themselves corpus documents (PEP 1/12, Go
  `design/TEMPLATE.md`, KEP `NNNN-kep-template/README.md`, Cockroach
  `docs/RFCS/README.md`, Rust goals `TEMPLATE.md`, Oxide RFD 1).
- Web text is `BeautifulSoup.get_text("\n")`, so headings are lost in the text
  files; raw HTML is retained. PDFs are `pdftotext -layout` output.
- `pm/docs/plan-session-sources-2026-10-19.md` maps 32 plan files to Claude/Codex
  conversation records with line references. Claude histories are mounted under
  `$HOME/.claude/projects` (the map's `/home/matt/.claude/projects` prefix);
  all 13 referenced Claude records are present. The Codex record (plan-delivery)
  is not mounted.
- Network: GitHub API is unauthenticated (60 req/h) but github.com issue/PR HTML
  embeds the opening body as JSON and is fetchable; IETF datatracker API,
  rfc-index.xml, Oxide RFD API (`rfd-api.shared.oxide.computer/rfd`),
  discuss.python.org JSON, NASA/NAS pages are reachable.

## 1. Requirements

R1. **Extend collection to purpose-stating context** (`sources.json`, new
`context.py`). Each briefable source gets a `context` block in `sources.json`
naming its collectors; `context.py` fetches and caches items into
`data/context/<source>.jsonl` (+ status file), each item recording `id`, `kind`,
`url`, `retrieved_at`, `sha256`, `text`, `applies_to` (document ids or the whole
source) and fetch notes. Per source:
- go-proposals: tracking issue `golang/go#N` (number from the `design/N-*.md`
  filename, else the header "Discussion at" link); process = proposal
  `README.md` (sparse extended) + `design/TEMPLATE.md`.
- rust-rfcs: review thread `rust-lang/rfcs#N` (filename number / header
  "RFC PR"), tracking issue from header "Rust Issue"; process = `README.md`,
  `0000-template.md` (sparse extended).
- rust-goals: goal tracking issue (`rust-lang/rust-project-goals#N` from the
  metadata table), period index entry (the goal's line in
  `src/<period>/README.md`/`goals.md` slate), process = `TEMPLATE.md` +
  `how_to/propose_a_goal.md`.
- kubernetes-keps: `kep.yaml` metadata (pre-decision fields only), tracking
  issue `kubernetes/enhancements#<kep-number>`; process = KEP template README.
- python-peps: PEP header fields (pre-decision subset), first post of a
  discuss.python.org `Discussions-To` thread; process = PEP 1 and PEP 12.
- cockroach-rfcs: header metadata, review thread from header "RFC PR"; process
  = `docs/RFCS/README.md`.
- ietf-rfcs and quic-drafts: rfc-index.xml entry (title, authors, date, draft
  name, stream, area, WG, publication category, obsoletes/updates; never the
  abstract), WG charter revision in effect at publication (datatracker charter
  history + `www.ietf.org/charter/charter-ietf-<wg>-<rev>.txt`), WG milestones
  whose docs include the RFC's draft (current + history).
- oxide-rfds: RFD API index entry (title, authors, labels); process = RFD 1.
- chromium-designs / chromiumos-designs: index entry (link text, enclosing
  section headings, description text in the same list item) + index preamble.
- nasa-mission-concepts: index entry (h3 title, group heading) + study call per
  group: ROSES-18 C.30 PMCS amendments 64/71 for the "Completed 2020" group;
  the decadal survey letter of request/statement of task for the
  "Decadal Survey-Requested" group. nasa-luvoir / nasa-lynx: NASA
  "Establishment of Large Astrophysics Mission Concept Studies" (2015-11-30).
- All other sources: no context collector; continuation cases only.

R2. **Briefs** (`cases.py`). For every document with document-specific context,
assemble a brief = request line (per-source template in `sources.json`) +
labelled context items, each sentence-filtered against the document body.
Provenance lists every context item used (id, kind, url, retrieved_at, sha256,
sentences kept/dropped). Shared process documents are attached by reference
(`attachments`), not pasted into the brief.

R3. **Continuation cases** for every document with usable section structure:
prefix = document text up to a heading start offset; reference = that section
(heading through the next heading of the same or shallower level); instruction
asks for the next section. Stored as offsets into the document text plus its
sha256.

R4. **PM natural-prompt cases** from the mapped conversation records: the
conversation excerpt preceding the plan write/edit event, human turns separated
from injected/assistant/tool records; baseline = current `pm/plans/<plan>.md`
(path + sha256) plus the content written at the event when recoverable. Plans
whose records are missing or not located are listed, not fabricated.

R5. **Catalog + coverage report.** `data/cases/catalog.jsonl` (one case per
line) and `data/cases/coverage.json`; a committed summary
`experiments/plan-writing/reports/case-coverage.md` + `.json` with counts by
source × case type, dropped documents (neither brief nor sections) listed by
id/identity, and PM case status.

R6. **Tests** (`tests/test_plan_writing_cases.py`) on synthetic fixtures, plus
a catalog validator (`cases.py --check`) run on the real catalog and also
invoked by a test that skips when `data/cases` is absent. Checks: no brief
shares an 8-token passage with its document body; every case has provenance
and split group; continuation prefixes end at a detected heading start and the
reference never appears in generator input; PM cases point at an existing
conversation record line; every corpus document appears in the coverage report
exactly once.

## 2. Implicit requirements

- Briefs and generator inputs are built only through one function per case type
  (`generator_input(case)`), which never reads reference spans; tests target it.
- Leak filter: normalized lowercase word tokens; any context sentence sharing an
  8-gram with the body is dropped. Body = document text minus a recognised
  metadata header (PEP field list, Rust/Cockroach `- Field:` list, Go
  Author/Last updated/Discussion lines, rust-goals metadata table) and minus the
  title heading line. Self-links to the document (its URL/path) are removed.
- Only opening posts of issues/PRs/threads are used (the request), not later
  comments that review the finished document. Post-decision fields (PEP
  Status/Resolution, KEP status/stage/milestones, RFC current-status, RFD state)
  are excluded so briefs do not reveal outcomes.
- Split groups: start from the corpus `split_group`; IETF RFCs regroup by WG
  (`ietf-<wg>`, so QUIC RFCs join `ietf-quic` with quic-drafts) and non-WG RFCs
  by stream; then union duplicate groups (same sha256) so duplicates never span
  groups. Every case of a document carries the document's final group; PM cases
  use `pm-plans`.
- Fetching is cached, polite (≤3 workers, retry/backoff on 429/5xx) and
  resumable; failures are recorded per item, never silently dropped.
- Catalog and briefs live under gitignored `data/`; only the code, manifest,
  tests and coverage summary are committed. PM conversation excerpts are private
  and stay in `data/pm/`.
- Case modules are stdlib-only (HTML headings via `html.parser`) so tests run
  without bs4; `context.py` may use bs4 like `collect.py`.

## 3. Ambiguities and resolutions

- *What counts as "recoverable context"?* Any document-specific item (issue,
  thread, metadata record, index entry, charter milestone naming its draft,
  study-call group). Shared process documents alone do not qualify. Each brief
  records `context_strength`: `rich` when it contains request text (issue/PR/
  thread body, study call, milestone or charter), `thin` when only index or
  metadata fields survive. Downstream sampling decides whether thin briefs are
  used.
- *Is a title "document body"?* Titles from metadata/index records are context
  (they identify the request); the title heading line is excluded from the body
  for the leak check. All other brief text must pass the 8-gram filter.
- *Templates vs leak check.* Templates predate documents and are identical for
  every document of a source, so they are attachments with their own provenance
  and are not part of the brief text checked for leakage. A process document is
  never attached to itself.
- *How many continuation cases per document?* All boundaries are recorded in
  coverage; up to 3 cases per document are emitted (early/middle/late among
  eligible boundaries, deterministic), eligible when prefix ≥ 100 words and
  reference 30–4000 words. Configurable.
- *Should the next heading be revealed?* No — the heading is part of the
  reference; the instruction only asks for the next section.
- *Brief assembly by LLM?* No. This PR does not run models (no usage estimate
  is required by its description); briefs are deterministic assemblies.
- *PM excerpt window.* From the session start (or the previous plan write event
  in the same session) to the event line; human turns are user text messages
  that are not tool results, meta/command wrappers, compaction summaries or pm
  injected prompts. Each PM case records the window, counts, and
  `needs_review: true` because the map is not proof of assent.
- *plan-doc-eval.md and plans not in the map* (plan-doc-eval, and plans whose
  map row says not located): listed as `no_located_history`; plan-delivery as
  `history_not_mounted` (Codex). plan-b6aac3d is untracked and absent here.
- *Supplementary KEP docs* (non-README files in a KEP dir) get briefs from the
  same kep.yaml/issue, framed as a supporting document named by its filename.

## 4. Edge cases

- Documents that are themselves issues (fpga-proposals chisel issues) or
  process files: normal continuation handling; no self-attachment.
- Empty texts (3) and texts with no detectable headings: dropped from
  continuation; dropped entirely if also without a brief, and listed.
- Numbered-heading detection (RFC text, PDFs) must reject TOC lines (dot
  leaders/trailing page numbers), page headers/footers and numbered lists; a
  monotonic numbering check filters false positives.
- Markdown headings inside fenced code blocks are ignored; RST adornment
  underlines must be at least as long as the title.
- Duplicate documents (same sha256) share split group; each still gets cases.
- Issue pages that 404/redirect (transferred issues) are recorded as fetch
  failures and the brief falls back to remaining items.
- Charter revisions approved after publication are not used (no post-hoc
  charter); RFCs then keep index/milestone context only.
