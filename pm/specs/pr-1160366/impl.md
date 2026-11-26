# Spec: PR pr-1160366 — Markdown format primitives

Code lives under `pm_core/review/` (walker primitives only). NOTE: an existing `pm_core/review.py` module (post-step plan-command review logic) already occupied this name, an unrelated "review" concept. Rather than share the package, this PR moves the plan-related top-level modules into a new `pm_core/plans/` package so `pm_core/review/` is owned cleanly by the litreview walker:

- `pm_core/plan_parser.py` → `pm_core/plans/parser.py`
- `pm_core/review.py` (post-step plan-command review) → `pm_core/plans/review.py`
- `tests/test_review.py` → `tests/test_plan_review.py`

All importers updated accordingly (`pm_core/cli/plan.py`, `pm_core/guide.py`, `pm_core/tui/{app,watcher_ui}.py`, and the moved tests). `pm_core/review/` then contains only `__init__.py` (walker docstring) plus the new primitives `md_parser.py` / `md_writer.py`. Both `pm_core.review` and `pm_core.plans` are added to `pyproject.toml`'s package list.

## Requirements

1. **`pm_core/review/md_parser.py`**
   - `parse_response_blocks(text) -> list[ResponseBlock]` — extract every fenced HTML comment whose body's first non-blank line is `proposed-change`. Body parsed as YAML (so pipe-blocks for `before` / `after` / `suggested-rationale` / `human-*` work natively). Returned record includes the block's byte range in the source so writers can rewrite it in place.
   - `parse_interaction_log(block) -> list[InteractionEvent]` — split the `interactions:` list out of a parsed block. Each event is `{event, at, ...}`.
   - `parse_audit_doc(text) -> AuditDoc` — parses `CITATION_AUDIT_CYCLE_N.md` canonical format: `## <cluster>` sections containing `### <citation header>` entries with labeled subsections (`**Tier:**`, `**Doc passage as currently written:**`, `**What the source actually says:**`, `**Verdict:**`, `**Substantive change proposed:**`, optional `**Flag:**`, optional `**Surfaced citations:**` list). Entries are separated by `---` rules.
   - `parse_response_doc(text) -> ResponseDoc` — top-level wrapper that returns the response file's preamble text + list of response blocks. Each block carries its `provenance` (`reviewer-comment` | `audit-entry`).
   - `parse_state(text) -> StateFile` — YAML parse of `STATE.md` (`current-cycle`, `current-phase`, `mode`, `last-transition`).
   - `parse_focus(text) -> FocusFile` — YAML parse of `UI_FOCUS.md` (`view`, `cycle`, `target?`, `timestamp`).

2. **`pm_core/review/md_writer.py`**
   - `update_response_block(path, change_id, updates)` — atomic in-place rewrite of one block's YAML fields. Read file → find block (by `id`) → merge updates → re-serialize block body → write whole file via temp-file + `os.replace`. Preserves bytes outside the block.
   - `append_interaction(path, change_id, event)` — concurrency-safe append to that block's `interactions:` list. Uses `fcntl.flock(LOCK_EX)` on the file during read-modify-write so two walker clients can't lose an event.
   - `append_note(path, section, body, *, timestamp=None)` — concurrency-safe append to `NOTES.md` with a timestamp under the named section. Creates the section if missing.
   - `update_state(path, state)` — atomic write of the full state file.
   - `update_focus(path, focus)` — atomic write of the full focus file. Always stamps `timestamp` (now-UTC) if caller doesn't supply one.

3. **Atomicity & concurrency**
   - All writes go to a per-write temp file (`tempfile.mkstemp`, fsync'd) and `os.replace()` for atomicity.
   - Every read-modify-write path holds an exclusive flock on a sibling `<path>.lock` during its read-modify-write window — `append_interaction`, `append_note`, *and* `update_response_block` (which merges into an existing block, so it must read before it writes). This is the spec's "concurrency-safe appends." Pure overwrites (`update_state`, `update_focus`) take no lock; they are atomic via rename only and are last-writer-wins.

4. **Tests** (`tests/review/`)
   - `test_md_parser.py`, `test_md_writer.py`
   - Fixtures: `tests/review/fixtures/{response_cycle.md, audit_cycle.md, state.md, focus.md, notes.md}`
   - Coverage per Task: response-block round-trip; interaction-log append concurrency (two threads); canonical-format audit-doc parsing; response-doc parsing with mixed-provenance changes; state-file phase transition; focus-file timestamp ordering; notes append preserves prior content.

## Implicit requirements

- The block body is YAML; the comment fence is `<!-- proposed-change` opener, `-->` closer on its own line. The YAML body sits between them — no `---` document marker, since it's already framed.
- `interactions:` field is an empty placeholder when first written by the response session. Parser tolerates both an empty value and a missing-key absence (treat as `[]`).
- Writer never deletes user-edited content outside the target block. Block rewrite preserves leading/trailing whitespace around the comment fence.
- Audit doc parsing is line-oriented and tolerant: legacy doc cluster headers and free-form prose between entries do not break parsing; we only extract the entries we recognize.
- `parse_state` / `parse_focus` accept YAML with `#` comments (the plan's example state file uses inline comments).
- `update_focus` writes `timestamp` last so the SSE watcher sees a consistent file.

## Ambiguities (resolved)

- **Interactions log location.** Plan says interactions are a field on the response block (`interactions:`). Resolved: store as a YAML list inside the block body. No separate `INTERACTIONS.md` file.
- **Audit canonical format vs legacy.** Plan PR 4 / Non-goals: legacy four `CITATION_AUDIT_*.md` files are out of scope. Parser targets only the canonical format; legacy file shape is not required to parse.
- **Notes section schema.** Plan: "section-tagged, append-only with timestamps." Resolved: `## <Section>` headers, each appended entry is preceded by `[<ISO-8601 timestamp>]` on its own line followed by free-text body, separated from prior entries by a blank line.
- **State file format.** YAML, not YAML-frontmatter. Plan example shows raw YAML with inline `#` comments. Same for focus.
- **Block id format.** Free-form string. The walker can use `change-<n>` but the parser/writer doesn't constrain it.

## Edge cases

- Multiple response blocks in one file → parsed in document order; updater finds by id, not by order.
- Block with no `interactions:` key → treated as empty list; `append_interaction` adds the key.
- File missing entirely → callers read the path themselves; `parse_state` / `parse_focus` take *text* (not a path), so empty/blank input parses to a `StateFile` / `FocusFile` with all-`None` fields. `update_*` create the file. `append_note` creates `NOTES.md` and the section if missing.
- Two concurrent `append_interaction` calls → flock serializes them; both events land.
- YAML pipe-block `before:` / `after:` preserves trailing newline. The block dumper registers a per-value `str` representer that selects literal `|` style only for multi-line strings (a blanket `default_style='|'` would wreck short scalars), and a `None` representer that emits bare keys (`human-verdict:`) instead of `null` to match the response session's convention.
- Empty `surfaced-citations:` list in an audit entry → entry parses with `surfaced_citations = []`.
- Partial/in-progress `CITATION_AUDIT_CYCLE_N.md` (live audit-browse reads it while the audit loop is still writing, per note-987b0a0) → `parse_audit_doc` never raises and skips any entry that has not yet been written through its last required field. Canonical field order is Tier → Doc passage → source says → Verdict → Substantive change proposed → [Flag] → [Surfaced], so the gate requires both `**Verdict:**` and `**Substantive change proposed:**` to be present; a mid-write trailing entry (even one already past `**Verdict:**`) is dropped rather than surfaced half-populated.
