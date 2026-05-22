# Spec: pr-cfb0b3a — prompt sessions to use pm PR notes for cross-session handoff

## Goal (restated)

Teach Claude work-sessions that `pm pr note add <pr-id> '<text>'` is the
canonical channel for handing off context — both to the *next session on the
same PR* and to *a different PR* — and that pm PR notes are preferred over
GitHub PR comments / description edits for handoff. The guidance must reach
**containerized / non-TUI sessions**, which receive `session_name=None`.

## Relevant code

All work happens in `pm_core/prompt_gen.py`.

- `_OUT_OF_SCOPE_BUGS_BLOCK` (lines 15–30): module-level constant already
  mentioning `pm pr note add <pr-id>` for recording incidental fixes and
  `pm pr add` for filing a new bug PR. Included verbatim in the review and QA
  prompts (lines 310, 1525, 1851, 1908). **Cross-reference, do not duplicate.**
- `tui_section(session_name)` (line 33): TUI block. Callers gate it as
  `tui_block = tui_section(session_name) if session_name else ""` — this is the
  gating to avoid. Container sessions get `session_name=None` (confirmed:
  `pm_core/cli/pr.py:980,1170` pass `session_name=pm_session`, which is None for
  non-TUI/container starts), so anything inside `tui_block` is invisible to them.
- `_format_pr_notes(pr, workdir)` (line 54): renders existing notes as the
  `## PR Notes` section, injected into future sessions' prompts. This is the
  surfacing mechanism the guidance refers to. Returns `""` when there are no
  notes — so the *handoff guidance* must be a separate, always-present block,
  not piggy-backed on `pr_notes_block`.
- Target generators:
  - `generate_prompt` (impl, line 104) — body line 175, no `_OUT_OF_SCOPE` block.
  - `generate_review_prompt` (review, line 189) — appends `_OUT_OF_SCOPE` at
    line 310; has `pr_id`.
  - `generate_qa_planner_prompt` (line 1319) — `_OUT_OF_SCOPE` at 1525.
  - `generate_qa_interactive_prompt` (Scenario 0, line 1538) — ends `{tui_block}`.
  - `generate_qa_child_prompt` (line 1639) — `_OUT_OF_SCOPE` at 1851.
  - `generate_standalone_qa_prompt` (line 1856) — `_OUT_OF_SCOPE` at 1908; runs
    against master, has no single PR id.

## Implementation

Add a module-level helper next to `_OUT_OF_SCOPE_BUGS_BLOCK`:

```python
def _pr_notes_handoff_block(pr_id: str | None = None) -> str:
    this_pr = pr_id or "<this-pr-id>"
    return f"""
## PR Notes — Handoff Channel

`pm pr note add <pr-id> '<text>'` is the canonical way to hand off context
between sessions. A note persists on the target PR (in project.yaml) and is
injected into the prompt of every future session for that PR (the `## PR
Notes` section). Prefer pm PR notes over GitHub PR comments or description
edits for any handoff — GitHub comments are for external review
communication, not internal handoff. When the user says "leave a note" /
"add a note" / "notes" without qualification, they mean a pm PR note.

- **Same-PR, next session** — to leave context for whoever resumes this PR,
  run `pm pr note add {this_pr} '<text>'`.
- **Cross-PR** — when leaving work or context for a *different* PR to pick
  up, add the note to that PR's id: `pm pr note add <other-pr-id> '<text>'`.
  It attaches to that PR and surfaces in its sessions. If incidental work
  belongs to a PR that already exists, prefer a note on that PR over opening
  a brand-new one (see the Incidental Bugs guidance for recording incidental
  fixes).
"""
```

Insert the block (ungated) into each target generator:

- `generate_prompt`: append `{pr_notes_handoff_block}` to the f-string after
  `{bug_fix_block}` (line 175), with
  `pr_notes_handoff_block = _pr_notes_handoff_block(pr_id)`.
- `generate_review_prompt`: after line 310
  (`base += "\n" + _OUT_OF_SCOPE_BUGS_BLOCK`), add
  `base += "\n" + _pr_notes_handoff_block(pr_id)`.
- `generate_qa_planner_prompt`: add the block right after
  `{_OUT_OF_SCOPE_BUGS_BLOCK}` (line 1525), using `_pr_notes_handoff_block(pr_id)`.
- `generate_qa_interactive_prompt`: add after `{tui_block}` at the end (line
  1635), using `_pr_notes_handoff_block(pr_id)`.
- `generate_qa_child_prompt`: add after `{_OUT_OF_SCOPE_BUGS_BLOCK}` (line
  1851), using `_pr_notes_handoff_block(pr_id)`.
- `generate_standalone_qa_prompt`: add after `{_OUT_OF_SCOPE_BUGS_BLOCK}`
  (line 1908), using `_pr_notes_handoff_block()` (no PR id — renders the
  literal `<this-pr-id>` placeholder, which is correct for a no-PR run).

## Implicit Requirements

- The block must render even when `pr.notes` is empty (it is independent of
  `_format_pr_notes`). Verified by design: separate always-present block.
- Substituting the concrete `pr_id` into the same-PR example improves clarity
  but is not required for the cross-PR example, which always uses
  `<other-pr-id>`.
- Cross-referencing `_OUT_OF_SCOPE_BUGS_BLOCK` must not assume positional
  ("above") wording, since `generate_prompt` does not include that block. The
  reference is phrased as "the Incidental Bugs guidance" (soft reference).

## Ambiguities (resolved)

1. **Which generators get the block?** Acceptance names impl, review, QA, and
   container prompts. "Container" is not a separate generator — it is the
   impl/review/QA generators invoked with `session_name=None`. So covering the
   six generators above (with an ungated block) satisfies the container
   requirement automatically. Watcher/orchestrator prompts
   (`generate_bug_fix_impl_prompt`, `generate_improvement_fix_impl_prompt`,
   `generate_discovery_supervisor_prompt`, `generate_watcher_prompt`,
   `generate_watcher_review_prompt`) are **excluded**: they coordinate other
   sessions rather than producing handoffs, and `generate_watcher_review_prompt`
   already documents `pm pr note add`. `generate_merge_prompt` is a short-lived
   merge-fix session, also excluded.

2. **Heading collision with `## PR Notes`.** `_format_pr_notes` emits a `## PR
   Notes` heading. To avoid two identical headings, the handoff block uses
   `## PR Notes — Handoff Channel`.

## Edge Cases

- `generate_prompt` lacks `_OUT_OF_SCOPE_BUGS_BLOCK`; the soft cross-reference
  wording keeps the handoff block coherent there.
- Standalone QA has no PR id; `<this-pr-id>` placeholder is acceptable since the
  session is not tied to one PR but may still file cross-PR notes.

## Tests

Add to `tests/test_pr_notes.py`:
- impl/review/QA-planner/QA-child prompts contain the handoff heading, both
  `pm pr note add` directions (same-PR + `<other-pr-id>`), and the "prefer pm
  notes over GitHub" instruction.
- impl and review prompts contain the block **with `session_name=None`** (the
  container/non-TUI path) — i.e. the block is not gated on `session_name`.
- the same-PR example renders the concrete `pr_id`.
