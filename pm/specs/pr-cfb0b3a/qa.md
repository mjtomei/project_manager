# QA Spec — pr-cfb0b3a

**Title:** Improvement: prompt sessions to use pm PR notes for cross-session
handoff and prefer them over GitHub notes

## Summary of the change (what a user can observe)

The PR is primarily a *prompt-content* change layered on top of an existing,
already-working handoff mechanism (`pm pr note add`). What changed:

1. A new **ungated** "PR Notes — Handoff Channel" guidance block is injected
   into every session-prompt generator (impl, review, QA planner, QA
   interactive, QA scenario-child, watcher). Because it is ungated, it also
   reaches the container / non-TUI path (`session_name=None`) that omits the
   TUI section. The block tells sessions: `pm pr note add <pr-id> '<text>'` is
   the canonical handoff channel; it works same-PR (next session) and cross-PR
   (any target id); prefer it over GitHub PR comments/description edits;
   treat an unqualified "note" from the user as a pm PR note.
2. The same-PR example in the block is rendered with the *real* current PR id,
   not a placeholder.
3. The QA scenario-child prompt gained a "Your Verdict Is Final for This Run"
   block (no re-poll; hand off via a PR note instead). Review prompts must
   **not** carry this block (review loops re-run each iteration).
4. The QA scenario *refiner/concretizer* prompt gained a "This Decision Is
   Final — Hand Off via PR Notes" block, threaded with the real PR id (falls
   back to a `<pr-id>` placeholder when no id is supplied).
5. `store.py`: the `project.libyaml` flag default flipped from **on** to
   **off**. With the flag absent, project.yaml is now serialized with the
   byte-stable pure-Python dumper, so a save (e.g. adding a PR note) on any
   environment does not silently reformat/churn the whole file. This matters
   because PR notes live in the git-tracked project.yaml and travel between
   environments.

The user-facing surfaces that exercise all of this:
- `pm prompt [pr-id]` — prints the generated **impl** prompt (no
  `session_name`, i.e. the container/non-TUI path). The dry-run a user reads.
- `pm pr note add|list|edit|delete <pr-id> ...` — the handoff CRUD; writes
  project.yaml under a lock.
- `pm pr review [pr-id]` — launches/echoes the **review** prompt.
- `pm pr start [pr-id]` — launches/echoes the **impl** prompt for a session.
- The end-to-end loop: add a note, then regenerate the prompt and observe it
  in the rendered `## PR Notes` section.
- `git diff` / file bytes of project.yaml after a note write (byte stability).

## Requirements

### R1 — Same-PR handoff round-trips into the next session's prompt
**Given** a pm project with a PR and no notes yet,
**When** the user runs `pm pr note add <pr-id> '<text>'`,
**Then** the command reports success and `pm pr note list <pr-id>` shows the
note with a timestamp.

**Given** that PR now has a note,
**When** the user regenerates the session prompt for that PR (`pm prompt
<pr-id>`, i.e. what the next session receives),
**Then** the printed prompt contains a rendered `## PR Notes` section that
includes the handed-off text.

### R2 — The handoff-guidance block is present in the generated impl prompt, even on the container/non-TUI path
**Given** a pm project with a PR,
**When** the user runs `pm prompt <pr-id>` (which generates the impl prompt
with no `session_name`),
**Then** the printed prompt contains the "PR Notes — Handoff Channel"
guidance describing both handoff directions (same-PR with this PR's real id,
and cross-PR with another id) and the instruction to prefer pm PR notes over
GitHub comments,
**And** the TUI-interaction section is absent (confirming the guidance is not
gated behind the TUI/`session_name` block).

### R3 — Cross-PR handoff: a note targets any PR id and surfaces only there
**Given** a pm project with two PRs A and B,
**When** the user (working in any context/workdir) runs `pm pr note add <B>
'<text>'`,
**Then** `pm pr note list <B>` shows the note and `pm pr note list <A>` does
not.

**Given** the cross-PR note now exists on B,
**When** the user generates prompts for each PR (`pm prompt <B>` and `pm
prompt <A>`),
**Then** B's prompt shows the note under `## PR Notes` and A's prompt does
not.

### R4 — The review session prompt carries the handoff guidance but not the QA verdict-finality block
**Given** a pm project with a PR,
**When** the user starts (or previews) the review session for the PR (`pm pr
review <pr-id>`),
**Then** the review prompt contains the "PR Notes — Handoff Channel" guidance,
**And** it does not contain the QA "Your Verdict Is Final for This Run" block.

### R5 — Note CRUD persists through project.yaml and reflects in subsequent reads
**Given** a PR with one note,
**When** the user edits it (`pm pr note edit`) and then deletes it (`pm pr
note delete`),
**Then** `pm pr note list` reflects each change, and a regenerated prompt's
`## PR Notes` section updates accordingly (edited text appears; after delete
the rendered section is gone).

### R6 — Adding a note does not churn project.yaml (byte-stable default)
**Given** a pm project whose project.yaml has no `libyaml` flag set,
**When** the user adds a PR note (causing a project.yaml save),
**Then** the resulting file change is limited to the added note lines — the
rest of the file is not reformatted/rewritten (a `git diff` shows a small,
localized hunk, not a whole-file rewrite).

## Setup

- Establish a throwaway pm project per `tui-manual-test.md`: install pm into a
  venv from the clone, set `PYTHONPATH` to the clone (verify with `pm which`),
  `git init` a test dir, `pm init --backend local --no-import`, and add PRs
  with `pm pr add`. Note each generated `pr-...` id.
- For cross-PR scenarios, add at least two PRs.
- For byte-stability, ensure the test project.yaml has no `project.libyaml`
  key (a fresh `pm init` project), and commit it first so a `git diff` after a
  note write is meaningful.
- All subsequent state changes go through the `pm` CLI (do not hand-edit
  project.yaml after bootstrap).

## Edge Cases

### E1 — Adding a note to a non-existent PR id
**Given** a pm project,
**When** the user runs `pm pr note add <bogus-id> '<text>'`,
**Then** the command fails with a clear error and does not corrupt
project.yaml (project.yaml remains valid and other PRs/notes intact).

### E2 — Note text with shell/YAML-hostile content round-trips intact
**Given** a PR,
**When** the user adds a note whose text contains quotes, a colon, a leading
`#`, a `-` bullet-like prefix, and a multi-word phrase,
**Then** `pm pr note list` and the regenerated prompt's `## PR Notes` section
show the text exactly as entered, and project.yaml remains valid YAML
(reloads without error).

### E3 — A PR with no notes: guidance present, rendered notes section absent
**Given** a freshly created PR with no notes,
**When** the user runs `pm prompt <pr-id>`,
**Then** the prompt contains the "PR Notes — Handoff Channel" guidance
heading, but no rendered `## PR Notes` notes section (the always-present
handoff block must not be mistaken for, or duplicate, the per-PR notes
listing).

### E4 — Concurrent note writes from multiple actors do not lose notes
**Given** a pm project with one or more PRs,
**When** two or more actors run `pm pr note add` concurrently (mix of
same-PR and different-PR targets), driven from separate processes against the
same project.yaml,
**Then** every note persists (none lost or clobbered), project.yaml remains
valid YAML, and `pm pr note list` for each PR shows the full expected set —
the file lock serializes the writes.

### E5 — Workdir-local (uncommitted) note surfaces via the merge path
**Given** a PR with a note recorded in the PR's workdir copy of project.yaml,
**When** a prompt is generated with that workdir provided,
**Then** the workdir note appears in the `## PR Notes` section even if it is
not yet present in the main/base project.yaml (notes are merged from both,
deduped by id). *(Best-effort; this exercises the cross-session handoff path
where a session leaves a note before its PR merges.)*

## Pass/Fail Criteria

- **PASS** when: the handoff guidance (both directions + prefer-pm-over-GitHub)
  appears in the impl prompt via `pm prompt` and in the review prompt, even
  with no `session_name`/TUI section (R2, R4); a note added via `pm pr note
  add` round-trips into a subsequent prompt's `## PR Notes` section (R1, R5);
  cross-PR notes attach to and surface only on the targeted PR (R3); the
  review prompt omits the QA verdict-finality block (R4); adding a note
  produces a small, localized project.yaml diff with no whole-file churn (R6);
  hostile note text round-trips and project.yaml stays valid (E2); concurrent
  note writes lose nothing (E4); a no-notes PR shows guidance but no rendered
  notes section (E3); a bad target id errors cleanly without corrupting state
  (E1).
- **FAIL** when: the guidance is missing from any of those prompts; it is
  gated behind the TUI section (absent when `session_name`/TUI is absent); a
  note does not surface in the next prompt; a cross-PR note lands on the wrong
  PR or all PRs; the review prompt carries the QA verdict-finality block;
  adding a note rewrites/reformats the whole project.yaml; hostile text is
  mangled or breaks YAML; concurrent writes drop notes; or a bad id corrupts
  project.yaml.

## Ambiguities (resolved)

- **Which surface to read the QA-internal prompts (planner/child/refiner)
  from?** There is no user-facing dry-run for QA prompts (`pm prompt` only
  emits the impl prompt; review is reachable via `pm pr review`). Running a
  full nested QA loop just to inspect generated worker/refiner prompts is
  heavy and brittle for an isolated scenario. **Resolution:** QA scenarios
  focus verification on the robust user surfaces — the impl prompt (`pm
  prompt`) and the review prompt (`pm pr review`) — plus the end-to-end note
  handoff round-trip, which is the actual mechanism the QA-prompt guidance
  points sessions at. The QA-prompt and refiner-prompt finality wording is
  treated as covered by the unit tests in `tests/test_pr_notes.py`; QA does
  not spin up a live QA loop solely to grep those prompts.
- **"Reading the prompt" vs. grepping code.** Scenarios observe the printed
  output of real CLI commands (`pm prompt`, `pm pr note list`, `pm pr
  review`) — i.e. what a user/session actually consumes — rather than
  importing prompt-gen functions or searching source for string literals.
- **Note targeting scope.** Confirmed via code: `pm pr note add` takes an
  explicit `<pr-id>` and can target any PR, not just the active one — so the
  cross-PR direction is genuinely exercisable from one workdir.
