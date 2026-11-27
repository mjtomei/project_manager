# Implementation Spec: Fold plan breakdown into plan add, remove the separate breakdown step

## Summary

`pm plan add` already asks its session to write a `## PRs` section, and
`pm plan breakdown` (TUI key `w` in the plans pane) ran a second session to do
the same thing again. This PR folds the breakdown guidance into the plan add
prompt, so one session produces the plan and its PR breakdown. It then removes
the `breakdown` command, the `w` key, the `plan-breakdown` review prompt, and
every place that still points users at them. `pm plan review` covers the one
case the old step still handled: a plan file that has no `## PRs` section
(for example because the plan add session ended early).

This is a resumed PR. Its two earlier commits (41a1838c, c74617a7) were made
against a master that was 3,855 commits older. Master has since been merged
in (6517d7d5), and the fold is re-applied on top of master's current code: the
bounded existing-PR listing, per-plan tmux windows, `session_type="plan"`,
and the load-first closing instructions.

## Full prompts for approval

The complete text of every prompt this PR changes is in
[Appendix A](#appendix-a--full-prompt-text), generated from the real builders
after implementation. Placeholders are written `⟦…⟧`. The prompts it changes:

1. `pm plan add` session prompt (`pm_core/cli/plan.py::plan_add`), which is the main change.
2. `REVIEW_PROMPTS["plan-add"]`, the background check (`pm_core/plans/review.py`).
3. The pre-load `pm plan review` prompt (`pm_core/cli/plan.py::plan_review`), which gains one paragraph.
4. The `pm guide` setup prompt (`pm_core/guide.py::build_setup_prompt`): the setup steps and the plans-view reference.
5. Two "do not run these yourself" lists: `prompt_gen.tui_section` and the watcher-explainer prompt in `prompt_gen.py`. The assistant prompt in `tui/pane_ops.py` is already correct after the merge.

Unchanged: the post-load `plan review` prompt, `plan deps`, `plan import`,
`plan fix`, and every other `REVIEW_PROMPTS` entry. Neither prompt has a
backend or role variant. Both plan add and plan review launch through
`launch_claude(..., session_type="plan")`.

## Requirements

### R1. The plan add prompt includes the full first-pass PR breakdown

`pm_core/cli/plan.py::plan_add` builds a prompt that:

- states the goal as developing the plan **and** breaking it into PRs, with both written to the plan file;
- keeps master's plan-development text unchanged (title or file-path name handling, scope/goals/design/constraints);
- carries over the breakdown-specific guidance from master's `plan_breakdown`:
  - discuss the breakdown with the user and iterate until they agree;
  - the `### PR:` / `description` / `tests` / `files` / `depends_on` format, with entries separated by `---`;
  - the "Existing PRs in this project" listing, bounded exactly as breakdown bounded it: `bounded_join` with `_PLAN_LIST_MAX` / `_PLAN_LIST_BUDGET`, plus the omitted-count note pointing at `pm pr list`;
  - the guidelines list (small PRs, parallel ordering, `depends_on` only for real constraints, write `## PRs` directly into the plan file, and `_MANUAL_TESTING_GUIDANCE`);
- adds one sentence replacing breakdown's `--prs` seed option: if the source document already proposes PRs, use them as the starting point;
- keeps master's closing instructions: run `pm plan load ⟦plan_id⟧` (key `l`), optionally `pm plan review` (key `c`), and close the pane;
- keeps `tui_section` and the notes block at the end, in the same place.

Launch is unchanged: session key `plan:add:⟦plan_id⟧`, `resume=not fresh`,
`session_type="plan"`, followed by the background `review_step("plan add", …)`.

### R2. Remove `pm plan breakdown`

Delete the `plan_breakdown` command from `pm_core/cli/plan.py`, together with
its `--prs` and `--fresh` options and the `plan:breakdown:⟦plan_id⟧` session
key. `pm plan breakdown` then fails with Click's standard
`No such command 'breakdown'` error.

### R3. Remove the TUI `w` = breakdown action

- `pm_core/tui/plans_pane.py`: drop `"w": "breakdown"` from `_KEY_ACTIONS` and `w=breakdown` from the footer.
- `pm_core/tui/pane_ops.py::handle_plan_action`: drop the `breakdown` branch. Fix the `handle_plan_add` comment that lists breakdown as a later action.
- `pm_core/tui/screens.py::HelpScreen`: drop the "w  Break plan into PRs" row.
- `pm_core/tui/plans_pane.py::update_plans` (QA S3 incidental fix, 2261f26a): call `refresh(layout=True)`. The pane is `height: auto`, so a plain `refresh()` kept the old height and clipped the footer once `a` added a second plan. This predates the PR and is also on master.
- `pm_core/tui/plans_pane.py::on_key` + `pm_core/tui/app.py::ProjectManagerApp.chord_prefix_armed` (QA S10 fix): while a `w` or `y` prefix is armed, the pane leaves every key unhandled so `App.on_key` resolves the chord. `w c`/`w l`/`w e` log `w cancelled`, the plan action does not fire, and a following `r` is a plain refresh. Before the fix the pane stopped the key, the plan action fired, the prefix stayed armed and `r` opened a watcher review. Tree-view `w j` is the same pre-existing ordering in `TechTree` and is filed as pr-c2bcb0a. Pinned by `tests/test_plans_pane.py::TestPlansPaneYieldsToChordPrefix`.

### R4. Review prompts

- `pm_core/plans/review.py`: delete `REVIEW_PROMPTS["plan-breakdown"]`. `REVIEW_PROMPTS["plan-add"]` now requires both a real plan description and a `## PRs` section with at least one `### PR:` entry that has description, tests and files.
- Pre-load `plan review` prompt: add a paragraph telling the session that if the plan file has no `## PRs` section yet, it should first propose a breakdown, agree it with the user, and write it in the FORMAT below, then run the remaining checks.

### R5. Docs, help and guidance text

- `pm_core/cli/__init__.py`: the getting-started text and the `pm help` COMMANDS list drop `plan breakdown` and `w=breakdown`, and describe `plan add` as adding a plan and breaking it into PRs. (The merge already applied this.)
- `pm_core/guide.py`:
  - `STEP_DESCRIPTIONS["has_plan_draft"]` changes from "Break plan into PRs" to "Finish plan with PR breakdown". The TUI log shows this label while the plan add session is still writing.
  - The setup prompt's "Breaking the plan into PRs" section becomes "If the plan has no PRs yet", pointing at `c`.
  - "Creating a plan" says the `a` session writes both the plan and its `## PRs`.
  - The plans-view reference reads `a` → `c` → `l` with no `w` line.
  - The workflow-lifecycle numbering is already updated by the merge.
- `pm_core/prompt_gen.py`: remove `pm plan breakdown` from the `tui_section` forbidden list (already done by the merge) and from the watcher-explainer forbidden list (new on master).
- `pm_core/tui/pane_ops.py` assistant prompt: already lists `a`/`c`/`l` after the merge.
- `pm_core/cli/plan.py`: the `plan load` "No PRs found" error no longer names `pm plan breakdown`. It points at `pm plan review ⟦plan_id⟧` (key `c`), the recovery path from Ambiguity 4, and does not suggest re-running `pm plan add`, which would mint a new plan id. The `plan fix` docstring and the `_MANUAL_TESTING_GUIDANCE` comment drop "breakdown".
- `pm_core/fake_claude.py`: drop "breakdown" from the `plan` session-type comment.

### R6. Tests

- `tests/test_plans_pane.py`: the key map excludes `w`; the footer no longer asserts "breakdown"; the routing test covers `review` (from the merge). `TestPlansPaneHeightTracksContent` pins the footer staying visible after a plan is added or an intro grows (QA S3). `TestPlansPaneYieldsToChordPrefix` pins `w`/`y` then a plan key cancelling the prefix without the plan action (QA S10).
- `tests/test_plan_review.py`: `REVIEW_PROMPTS` keys exclude `plan-breakdown` (from the merge).
- `tests/test_plans_window_per_plan.py`: the shared-window test uses edit / view (`launch_plan_activated`) / review instead of breakdown, keeping its three-pane, two-split assertion.
- `tests/test_prompt_bounds.py`: the two tests that invoked `plan breakdown` now invoke `plan add` (300 other PRs, and long titles), so the existing-PR listing stays bounded under `PROMPT_ARG_LIMIT`.
- New `tests/test_plan_add_breakdown.py`:
  - `plan breakdown` is not a registered command;
  - the plan add prompt has the breakdown instructions, the format, the manual-testing guidance and the load-first closing;
  - the existing-PR listing appears only when PRs exist, and is bounded with the `pm pr list` pointer;
  - `REVIEW_PROMPTS["plan-add"]` requires `## PRs`;
  - the pre-load review prompt contains the missing-PRs instruction;
  - `plan load` on a plan with no `## PRs` points at `pm plan review ⟦plan_id⟧`, not `plan add`;
  - the guide setup prompt and `STEP_DESCRIPTIONS` have no `w`/breakdown step;
  - `handle_plan_action(app, "breakdown", …)` launches nothing;
  - a source scan of `pm_core/**/*.py` finds no `plan breakdown`, `plan-breakdown`, `plan:breakdown` or "Break plan into PRs".

## Implicit Requirements

- **The existing-PR listing stays bounded.** Master bounded breakdown's listing after this branch was written. The branch's own plan add listing was an unbounded `"\n".join`. Re-applying the fold must use the bounded form, or `plan add` on a project with hundreds of PRs could exceed the single-argv prompt limit (`test_prompt_bounds` pins this).
- **There is still a way to add PRs to a plan that has none.** With `w` gone, `pm plan review` (key `c`) handles it via R4's new paragraph, and the guide and the `plan load` error point at it. The background plan-add check was meant to be a second path (NEEDS_FIX, then `pm plan fix --review …`), but QA planning found it never reports: `review_step` runs `claude -p` in a daemon thread that dies when `pm plan add` exits, so no `pm/reviews/plan-add-*` file is written. That is the same on master and is filed as pr-e2cd753. Until it is fixed, `plan review` is the only working recovery path.
- **No live reference to a removed command or key.** This covers `pm help`, the TUI help screen, the plans footer, the guide, the prompts and the `plan load` error. The source-scan test enforces it.
- **Pressing `w` in the plans view no longer means breakdown.** Plans-pane `on_key` no longer handles it, so the key bubbles to the app-level `w` prefix (watcher `w`/`f`/`s`/`r`), exactly as in the tree view. The key after `w` must then reach the prefix too. QA S10 found that the pane stopped `c`/`l`/`e` before `App.on_key` saw them, so `w c r` opened a plan review and then a watcher review. R3's `chord_prefix_armed` check fixes that.
- **The merge with master must not regress master behaviour.** That includes per-plan windows for edit, `session_type="plan"`, the load-first wording and the `tui_tests.py` → `pm/qa` move. The deletion of `tui_tests.py` is kept; its plans-pane regression is already retired in `pm/qa/retired-regressions.md`.

## Ambiguities

1. **Does breakdown's `--prs` seed option move to `plan add`?** No. `plan add` already accepts a file path as NAME, which gives the session source context. R1 adds one sentence ("if the source document already proposes PRs, start from that list") to cover the seeding use. No caller in `pm_core`, the tests or `bin` passes `--prs`.
2. **Should `has_plan_draft` be renamed?** No. Only its user-facing description changes. The state name is used by `guide_progress.py`, the step-resolution logic and the tests, and its meaning (a plan exists without a `## PRs` section) still holds.
3. **Should a hidden deprecated `breakdown` alias remain?** No. The task says to remove the command. Click's "No such command" error is clear, and the help text points at `plan add` and `plan review`.
4. **Recovery path for a plan without PRs.** Use `plan review` (R4) rather than letting `plan add` resume an existing plan. `plan add` always mints a new plan id, so re-running it would leave a stale draft entry. The review prompt is the owner's stated backstop ("we have the review prompt to catch issues").
5. **Coordination with pr-6c0ee2d** (architecture foundation, `plan-axiomatic-design`; impl commit ee67fb0b pushed 2026-11-26). That PR adds an architecture-awareness block to the plan prompts in `cli/plan.py`. Its PR 2 seeds `pm/architecture.md` inside `plan add`, and the plan lists pr-30888b1 as its external dependency. Resolution: keep the plan add prompt's tail as `…{tui_section}{notes_block}` so an architecture block can sit next to `notes_block`. Tell pr-6c0ee2d that `plan breakdown` is gone: architecture awareness goes into `plan add`, `plan review` and `plan import` only, and greenfield seeding belongs in `plan add`. pr-6c0ee2d is not in this workdir's registry (it exists only on its own branch and in the host registry), so `pm pr note add pr-6c0ee2d` cannot reach it from the impl container. The handoff is recorded as a pr-30888b1 note, and the owner relays it to pr-6c0ee2d. Merge preview of ee67fb0b against this branch (review 4efb i1): `plan.py` conflicts only on the `plan_breakdown` block (resolve by dropping it; `plan add` picks up `arch_block` cleanly), and `tests/test_prompt_gen.py` merges cleanly but its `_PLAN_COMMANDS["breakdown"]` case then fails: `TestPlanPrompts::test_includes_architecture_when_present[breakdown]` and `test_clean_when_absent[breakdown]` both exit with `No such command 'breakdown'` (trial merge: 2 failed, 10 passed). Review 4efb i2 re-ran the trial merge against pr-6c0ee2d's newer head 57fb8168 (its prompt block now lives in `pm_core/architecture_prompts.py`) and got the same result: one conflict hunk, the dropped `plan_breakdown` block, and the same 2 `[breakdown]` failures (`test_prompt_gen.py` + `test_plan_add_breakdown.py` + `test_prompt_bounds.py`: 2 failed, 196 passed). pr-6c0ee2d already carries this handoff in its note-fbff1c2. Whichever PR merges second must also drop that case. Review 4efb i3 re-ran it at head b81ba118 and got the same result (2 failed, 197 passed). Review ea03 i1 re-ran it at head 5c4914f5: same single `plan.py` hunk, same 2 `[breakdown]` failures (2 failed, 200 passed).

No **[UNRESOLVED]** items.

## Edge Cases

- **Plan add closed before the PRs are written:** the guide stays in `has_plan_draft` ("Finish plan with PR breakdown"), `pm plan load` exits 1 pointing at `pm plan review ⟦plan_id⟧`, and `c` runs the review, which now proposes the missing breakdown. The background check does not report today (pr-e2cd753; see Implicit Requirements).
- **Source document already has a `## PRs` section** (NAME is a path): the session starts from that list instead of inventing a new one.
- **Project with hundreds of existing PRs:** the listing is capped at 40 lines or 20 KB with a `pm pr list` pointer.
- **Fresh project (no PRs):** no listing block. The prompt reads "Separate PR entries with --- lines." then a blank line, then "Guidelines:".
- **Leftover `plan:breakdown:*` session-registry entries** from older runs: nothing reads them, so they are harmless orphans.
- **Review files named `plan-breakdown-*.txt`** in `pm/reviews/`: `pm plan fix --review` still works on them, because `build_fix_prompt` takes any step name.
- **External callers of `pm plan breakdown`:** none in this repo (searched `pm_core`, `tests`, `bin`, `pm/qa`).
- **In-flight branches that still use `plan breakdown`** (review 4efb i3: scanned every `origin/pm/*` branch for added `breakdown` lines, then trial-merged the live ones into this branch):
  - pr-5cee3d5: the merge conflicts only on the `plan_breakdown` block, but that block carries its `graph.deps_of(pr)` fix. The fix has to move to `plan_add._existing_line`, because `plan add` now lists existing PRs: without it, a hand-edited `depends_on: 7` crashes `plan add` with `TypeError: can only join an iterable`. Its new `test_plan_deps_tolerates_malformed_pr_fields` merges cleanly but invokes `plan breakdown` (exit 2, "No such command"). With the argv changed to `["plan", "add", "New plan"]` and `deps_of` ported, the test passes. Noted on pr-5cee3d5.
  - pr-3526677: `tests/test_completion.py::test_real_cli_tree` merges cleanly but asserts that `plan breakdown ` completes plan ids. It fails after the merge and passes with `plan review `. Noted on pr-3526677.
  - pr-fa9f172: seven textual hunks in `cli/__init__.py`, `cli/plan.py`, `prompt_gen.py` and `tui/pane_ops.py`. Drop the breakdown parts and keep fa9f172's other edits: the `pm pr review` wording, `D=deps  Enter=view file`, the help wording, and the `_report_plan_file_missing` edit branch.
  - pr-fe4ca5d: its popup `b`=breakdown becomes a dead key (note-dcd3305, review 4efb i2).
  - pr-b764a0c and pr-a6ef6be are 2,000+ commits behind master. Their added `breakdown` text (`pm plan breakdown`, `w=breakdown`, a `d`=breakdown key) is flagged by `test_no_source_references_to_breakdown_step` and the plans-pane key-map tests. Review ea03 i3 left notes on both. pr-b764a0c (note-ee7d3f4): keep `w`=work, but drop the `d`=breakdown remap, its launch, the "Break down" guide step, its `tui_tests.py` edits and its breakdown key-map test. pr-a6ef6be (note-2fc7bb0): its `w=breakdown … r=lit-review` key line conflicts, so resolve it without `w`. Also noted: pr-93b9aa9 (note-f2c9066), whose description quotes the old forbidden-command list that still names `pm plan breakdown`.

## Appendix A — Full prompt text

Generated by `prompts/render.py` + `prompts/build_appendix.py` from the real builders on this branch; do not hand-edit.

Placeholder legend (all runtime values are written `⟦…⟧`):

- `⟦name⟧`: the NAME argument to `pm plan add` (a title or a file path).
- `⟦plan_id⟧`: the generated plan id (`plan-<sha7>`).
- `⟦pm_root⟧`: the pm state root (the directory that holds `project.yaml`).
- `⟦plan_path⟧`: `⟦pm_root⟧/<plan file>`.
- `⟦session⟧`: the base pm tmux session name.
- `⟦meta_pm_root⟧`: the watcher's meta pm root.
- `⟦project_name⟧` and `⟦repo⟧`: from `project.yaml`.
- `⟦tui_section …⟧`: the block in A.7. It is empty when there is no pm tmux session.
- `⟦notes_block …⟧`: `notes.notes_section(root)`, unchanged by this PR.
- `⟦bounded listing …⟧`: `bounded_join` over the PRs, unchanged in shape from master's `plan breakdown` listing.
- `⟦beginner_mode_section …⟧`: `guide._beginner_mode_guide_section()`, unchanged by this PR.

Removed prompts: `pm plan breakdown` (the whole prompt; its master text is in
`prompts/before/plan_breakdown.txt`) and `REVIEW_PROMPTS["plan-breakdown"]`
(`prompts/before/check_plan-breakdown.txt`). Diff of every prompt, master →
branch: `prompts/diff.txt`.

### A.1 `pm plan add` session prompt (project with existing PRs)

```text
Your goal: Help me develop a plan called "⟦name⟧", break it down into PRs, and
write everything to ⟦pm_root⟧/plans/⟦plan_id⟧.md.

This session is managed by `pm` (project manager for Claude Code). You have access
to the `pm` CLI tool — run `pm help` to see available commands.

The plan file is at: ⟦pm_root⟧/plans/⟦plan_id⟧.md

The user gave "⟦name⟧" as the plan name. This might be:
- A short title describing the plan (e.g. "auth-refactor", "add dark mode")
- A file path pointing to an existing document with plan context (e.g.
  "plans/auth.md", "DESIGN.md", "notes/idea.txt")

If it looks like a file path, try to find and read the file — check relative to
the project root and common directories. If you find it, use its contents as
context for developing the plan. If not found, just treat it as a title.

If the name is just a title, ask the user what the plan should accomplish.
They'll describe it at a high level and you'll iterate until the plan is clear
and complete. Then write the final plan to the file above as structured markdown.

The plan needs to include scope, goals, key design decisions, and any constraints.

Once the plan is solid, break it down into a "## PRs" section with individual PRs.
If the source document already proposes PRs, start from that list.
Discuss the breakdown with the user — ask about anything ambiguous (scope of
individual PRs, ordering preferences, what can be parallelized). Iterate until the
user is comfortable with the list, then write the PRs to the plan file in this format:

### PR: <title>
- **description**: What this PR does
- **tests**: Expected unit tests
- **files**: Expected file modifications
- **depends_on**: <comma-separated titles of dependency PRs, or empty>

Separate PR entries with --- lines.

Existing PRs in this project:
⟦bounded listing — one line per PR: `  <pr-id>: <title> [<status>]…`; capped at 40 lines / 20 KB, then `  ... (+N more; run `pm pr list` to see all PRs)`⟧

Guidelines:
- Prefer more small PRs over fewer large ones
- Order them so independent PRs can be worked on in parallel
- Only add depends_on when there's a real ordering constraint
- Write the ## PRs section directly into the plan file at ⟦pm_root⟧/plans/⟦plan_id⟧.md
- For each PR, identify if human-guided testing will be needed during review (UI interactions, TUI keybindings, environment-specific behavior, hardware dependencies). Call this out explicitly in the PR description so the review loop can use INPUT_REQUIRED appropriately.

After writing the PRs section, tell the user to run `pm plan load ⟦plan_id⟧`
(key: l in the plans pane) to load the PRs into project.yaml. They can
optionally run `pm plan review ⟦plan_id⟧` (key: c) afterward to check
consistency and coverage.
Let them know it is safe to close this pane — load and review will run in new sessions.
⟦tui_section — the 'Interacting with the TUI' block, rendered in tui_section.txt; empty when no pm tmux session⟧
⟦notes_block — notes.notes_section(root): the project's pm/notes.txt sections; empty when none⟧
```

### A.2 `pm plan add` on a project with no PRs (listing block omitted)

```text
Your goal: Help me develop a plan called "⟦name⟧", break it down into PRs, and
write everything to ⟦pm_root⟧/plans/⟦plan_id⟧.md.

This session is managed by `pm` (project manager for Claude Code). You have access
to the `pm` CLI tool — run `pm help` to see available commands.

The plan file is at: ⟦pm_root⟧/plans/⟦plan_id⟧.md

The user gave "⟦name⟧" as the plan name. This might be:
- A short title describing the plan (e.g. "auth-refactor", "add dark mode")
- A file path pointing to an existing document with plan context (e.g.
  "plans/auth.md", "DESIGN.md", "notes/idea.txt")

If it looks like a file path, try to find and read the file — check relative to
the project root and common directories. If you find it, use its contents as
context for developing the plan. If not found, just treat it as a title.

If the name is just a title, ask the user what the plan should accomplish.
They'll describe it at a high level and you'll iterate until the plan is clear
and complete. Then write the final plan to the file above as structured markdown.

The plan needs to include scope, goals, key design decisions, and any constraints.

Once the plan is solid, break it down into a "## PRs" section with individual PRs.
If the source document already proposes PRs, start from that list.
Discuss the breakdown with the user — ask about anything ambiguous (scope of
individual PRs, ordering preferences, what can be parallelized). Iterate until the
user is comfortable with the list, then write the PRs to the plan file in this format:

### PR: <title>
- **description**: What this PR does
- **tests**: Expected unit tests
- **files**: Expected file modifications
- **depends_on**: <comma-separated titles of dependency PRs, or empty>

Separate PR entries with --- lines.

Guidelines:
- Prefer more small PRs over fewer large ones
- Order them so independent PRs can be worked on in parallel
- Only add depends_on when there's a real ordering constraint
- Write the ## PRs section directly into the plan file at ⟦pm_root⟧/plans/⟦plan_id⟧.md
- For each PR, identify if human-guided testing will be needed during review (UI interactions, TUI keybindings, environment-specific behavior, hardware dependencies). Call this out explicitly in the PR description so the review loop can use INPUT_REQUIRED appropriately.

After writing the PRs section, tell the user to run `pm plan load ⟦plan_id⟧`
(key: l in the plans pane) to load the PRs into project.yaml. They can
optionally run `pm plan review ⟦plan_id⟧` (key: c) afterward to check
consistency and coverage.
Let them know it is safe to close this pane — load and review will run in new sessions.
⟦tui_section — the 'Interacting with the TUI' block, rendered in tui_section.txt; empty when no pm tmux session⟧
⟦notes_block — notes.notes_section(root): the project's pm/notes.txt sections; empty when none⟧
```

### A.3 Background check `REVIEW_PROMPTS["plan-add"]`

```text
Read the plan file at ⟦plan_path⟧. Does it have a substantive plan description (not just the template placeholder "<!-- Describe the plan here -->" or similar) AND a "## PRs" section with at least one "### PR:" entry that has description, tests, files fields? Output PASS if yes, NEEDS_FIX if no, followed by what's missing.
```

### A.4 `pm plan review`, pre-load variant (no PRs linked to the plan yet)

```text
Your goal: Review the plan and its PRs for consistency, coverage, and
self-containment before they are loaded. Identify gaps and fix them.

This session is managed by `pm` (project manager for Claude Code). You have
access to the `pm` CLI tool — run `pm help` to see available commands.

Read the plan file at: ⟦pm_root⟧/plans/⟦plan_id⟧.md

The plan file should contain a "## PRs" section with proposed PRs. No PRs
have been loaded into the project yet.

If the plan file has no "## PRs" section yet (for example, the plan add
session ended before writing one), start by proposing a PR breakdown for the
plan. Discuss it with the user, and once they agree, write it to the plan file
in the format shown under FORMAT below. Then run the checks.


PRs from other plans (for cross-plan reference):
⟦bounded listing — one line per PR: `  <pr-id>: <title> [<status>]…`; capped at 40 lines / 20 KB, then `  ... (+N more; run `pm pr list` to see all PRs)`⟧
Check the following:

1. COVERAGE — Does every feature, behavior, or capability described in the
   plan have at least one PR responsible for it? List any gaps.

2. SELF-CONTAINMENT — Can an agent pick up any single PR and understand what
   to build without reading the entire plan? Each PR description should include:
   - What the PR does and why (not just "implement X")
   - Which files to modify or create
   - What tests to write
   - How it relates to its dependencies (what it receives from them)
   - Reference to the plan file for broader context

3. CONSISTENCY — Do PR descriptions match the plan? Are depends_on
   references correct? Are file paths plausible? For each file path
   mentioned in a PR's **files** field, check whether it already exists
   in the repo (ls or find the file). If it exists, the PR should modify
   it; if it doesn't, the PR should create it. Flag paths that look wrong
   (typos, wrong directory, missing extension).

4. MANUAL TESTING — For each PR, identify if human-guided testing will be needed during review (UI interactions, TUI keybindings, environment-specific behavior, hardware dependencies). Call this out explicitly in the PR description so the review loop can use INPUT_REQUIRED appropriately.

5. FORMAT — Each PR entry must be parseable by the automated loader.
   Required format:

   ### PR: <title>
   - **description**: What this PR does
   - **tests**: Expected unit tests
   - **files**: Expected file modifications
   - **depends_on**: <comma-separated exact titles of dependency PRs, or empty>

   Entries separated by --- lines. Check:
   - Every PR has a ### PR: heading with a title
   - Every PR has a **description** field (not empty)
   - **depends_on** values match exact titles of other PRs in the list
   - No duplicate PR titles

For each issue found, propose a fix. When the user agrees, apply fixes
by editing the plan file directly at ⟦pm_root⟧/plans/⟦plan_id⟧.md.

After fixing, summarize what was changed. Then tell the user to run
`pm plan load ⟦plan_id⟧` (key: l in the plans pane) to create the PRs.
Let them know it is safe to close this pane — loading runs instantly without a session.
⟦tui_section — the 'Interacting with the TUI' block, rendered in tui_section.txt; empty when no pm tmux session⟧
⟦notes_block — notes.notes_section(root): the project's pm/notes.txt sections; empty when none⟧
```

### A.5 `pm guide` setup prompt at `has_plan_draft`

```text
You are guiding a user through setting up their project with `pm` (Project Manager for Claude Code).
You have access to the `pm` CLI — run `pm help` to see all commands.

## About you and pm

Start by briefly introducing yourself to the user. Tell them a bit about what
you are and what you can do in relation to this tool — for example, that you
can do many things only an expert programmer can normally do on a computer
(reading codebases, writing and debugging code, managing git branches and pull
requests), but that you can also explain individual concepts in plain language,
teach programming step by step, and help people build things they couldn't
build alone.

`pm` is a project manager built specifically for working with machine
intelligences like you. Its goal is to let people who have never programmed — or have
programmed very little — build quality software and learn anything about
programming or computers along the way. For experienced developers, pm
accelerates development and handles the boring, repetitive parts so they can
focus on what matters.

The user may be a complete beginner or an expert. Either way, be encouraging
and clear. If they seem unsure, explain what's happening and why. If they're
experienced, keep it concise.

## Current Status
- Project file: done
- Plan file: **next**
- PRs loaded: pending

## Project
Name: ⟦project_name⟧
Repo: ⟦repo⟧
Root: ⟦pm_root⟧
⟦tui_section — the 'Interacting with the TUI' block, rendered in tui_section.txt; empty when no pm tmux session⟧

## Your Task

Walk the user through setting up their project. The status section above shows
what's already done and what comes next. Focus on the **next** item.

**IMPORTANT:** You are guiding the user, not doing everything yourself. After
init, direct the user to interact with the TUI to create plans and load PRs.
Do NOT run `pm plan add` or `pm plan load` yourself —
instead tell the user which keys to press in the TUI and what to expect.

### Initializing the project

If no project file exists yet, run `pm init --no-import` to initialize. This
auto-detects the repo from the current directory. Use --no-import because we'll
create a plan through the TUI.

⟦beginner_mode_section — depends on the global beginner-mode setting⟧
After init, explore the codebase — read the README, look at directory structure,
check recent git history. Share what you find with the user and ask about their
goals for upcoming work.

### Creating a plan

If you and the user have already discussed their goals and you have a good
understanding of what the plan should cover, write a short summary to a file
(e.g. `plans/notes.md`) before telling them to add the plan. Include what
you learned about the codebase, the user's goals, and any decisions made.
The user can then pass that file path to the add dialog so the plan session
picks up where this conversation left off.

**Scope check — one plan or several?** Before creating a plan, consider
whether the user's goals are better served by a single plan or multiple plans.
Each plan produces its own independent PR tree, so splitting makes sense when:
- The goals span distinct features or areas of the codebase that don't depend
  on each other (e.g. "add auth" and "redesign the dashboard").
- The overall scope is very large — a single plan with 15+ PRs becomes hard
  to review and track. Two or three focused plans are easier to manage.
- Different parts have different priorities or timelines.

If you think the scope warrants multiple plans, suggest it to the user and
help them decide how to divide the work. They can press `a` multiple times
in the plans view to create each plan in sequence. Write a separate notes
file for each plan so every plan session starts with the right context.

Tell the user to press `p` in the TUI to open the plans view, then press `a`
to add a new plan. A dialog will ask for a title or file path — if you wrote
a notes file, tell them to enter that path; otherwise help them choose a good
title based on what you learned about the codebase and their goals. The `a`
action launches a session in a new pane that develops the plan with the user
and breaks it into PRs, writing both the plan content and a `## PRs` section
with individual PR entries. Once the plan session finishes, walk the user
through the remaining steps below (repeat for each plan if creating multiple).

### If the plan has no PRs yet

If the plan session ended before it wrote a `## PRs` section, tell the user to
press `c` in the plans view. The review session proposes a PR breakdown for a
plan that has none, settles it with the user, and writes it to the plan file.

### Reviewing the plan

Tell the user to press `c` in the plans view to review the plan. This launches
a session that checks the plan and PRs for consistency. Wait for it to finish,
then continue to the next step.

### Loading PRs

Tell the user to press `l` in the plans view to load PRs from the plan file
into the project. This runs instantly (no session needed) — the TUI status bar
shows progress and the tech tree updates when done.

### TUI plans view reference

In the TUI, `p` toggles the plans view. The setup flow is `a` → `c` → `l`:
- `a` — add a new plan and break it into PRs (prompts for a title or file path)
- `c` — review plan (launches a Claude session)
- `l` — load PRs from plan into the project
- `e` — edit plan file
- `v` — view plan file

## Next Step

Once PRs are loaded, tell the user to press `p` to leave the plans view.
The TUI will show the PR tech tree. Help them choose a good first PR to
work on, then tell them to press `s` on it to start. This launches a session
in a new pane focused on that PR.

Once the first PR session is running, **it is safe to close this guide pane**.
Tell the user.
⟦notes_block — notes.notes_section(root): the project's pm/notes.txt sections; empty when none⟧
```

### A.6 `STEP_DESCRIPTIONS["has_plan_draft"]` (TUI log label)

```text
Finish plan with PR breakdown
```

### A.7 `prompt_gen.tui_section` (embedded in plan, guide, impl prompts)

```text

## Interacting with the TUI

The base pm tmux session is `⟦session⟧`. Use `-s ⟦session⟧` with pm tui commands so they target the correct session even from workdir clones:
- `pm tui view -s ⟦session⟧` — capture and view the current TUI screen
- `pm tui send <keys> -s ⟦session⟧` — send keystrokes to the TUI (e.g. `pm tui send j` to move down)

**Do not** run commands that spawn new Claude sessions yourself (e.g. `pm pr start`, `pm pr done`, `pm plan add`, `pm plan review`). These must be triggered through the TUI so panes are managed correctly. Use `pm tui send` to press the appropriate key in the TUI instead.
```

### A.8 Watcher review session prompt (`generate_watcher_review_prompt`)

````text
# Watcher Review Session

You are the human's conversational surface for the autonomous watcher
loops running in this pm project. Your job is to read the watchers'
work logs and answer questions about what they have been doing — not
to run the watchers yourself.
⟦tui_section — the 'Interacting with the TUI' block, rendered in tui_section.txt; empty when no pm tmux session⟧

## Watcher architecture (background)

Three `BaseWatcher` subclasses run as background threads inside the TUI,
each on its own polling cadence. Each tick spawns a Claude session in a
tmux window that does its specific job and emits a verdict.

1. **Discovery supervisor** — schedules regression tests from
   `pm/qa/regression/*.md`, monitors the test sessions (which file new
   bug / improvement PRs themselves), and reconciles those filings
   (dedup against open PRs in the `bugs` / `ux` plans).
   Work log: `⟦meta_pm_root⟧/watchers/discovery.log`.

2. **Bug-fix implementation watcher** — picks the best candidate from
   `plan=bugs` each tick, advances it via `pm pr auto-sequence`, and
   auto-merges on QA PASS.
   Work log: `⟦meta_pm_root⟧/watchers/bug-fix-impl.log`.

3. **Improvement-fix implementation watcher** — same shape against
   `plan=ux`, but with a gated merge: PRs that PASS QA wait for a
   human taste check before merging.
   Work log: `⟦meta_pm_root⟧/watchers/improvement-fix-impl.log`.

User-supplied guidance for all three watchers lives in the `Watcher`
section of `notes.txt` (read via `pm notes` or directly).

## Your data sources

- **Work logs** (above) — primary. Each line is one tick's summary.
- **`pm pr list`**, **`pm pr list --plan bugs`**, **`pm pr list --plan ux`**.
- **`pm pr graph`** — full PR dependency tree.
- **`pm plan list`** — plan inventory.
- `notes.txt` Watcher section — current user guidance.

## Opening summary turn

Begin by producing a single summary of recent watcher activity. Read
each work log defensively (they may not all exist yet — bug-fix and
improvement-fix watchers ship after the discovery supervisor):

```
tail -n 60 ⟦meta_pm_root⟧/watchers/discovery.log 2>/dev/null || echo "(discovery log not yet present)"
tail -n 60 ⟦meta_pm_root⟧/watchers/bug-fix-impl.log 2>/dev/null || echo "(bug-fix-impl log not yet present)"
tail -n 60 ⟦meta_pm_root⟧/watchers/improvement-fix-impl.log 2>/dev/null || echo "(improvement-fix-impl log not yet present)"
```

Then organize the summary by watcher with a short bulleted list under
each, covering what was **discovered, filed, fixed, merged, or stuck**
since the last review.

After the summary, stop and wait for the human to drive.

## Read-only commands (safe to run any time)

- `pm pr list`, `pm pr list --plan bugs`, `pm pr list --plan ux`
- `pm plan list`
- `pm pr graph`
- `tail` / `cat` / `ls` on the work logs and transcript directory

## Write actions require explicit human confirmation

Some questions will lead the human to ask you to **change** something:

- Adding a note to the `Watcher` section of `notes.txt` (will flow
  into every watcher's next tick automatically) — `pm notes` or a
  direct edit.
- Pausing a watcher — tell the human to press `ws` in the TUI to
  toggle it (do not run pm commands that spawn new Claude sessions
  yourself).
- Editing a PR's description / notes — `pm pr note add <id> '<text>'`.

Before any write, read back exactly what you intend to change and wait
for the human to say "yes" / "go ahead". Do **not** run write commands
silently.

Forbidden (must always be done via the TUI by the human):
`pm pr start`, `pm pr done`, `pm plan add`, `pm plan review` —
anything that spawns a new Claude session.

## Tone

You are read-mostly and explanatory. Prefer "here's what the log shows
and why I think X happened" over speculation. If a log entry is
ambiguous, say so rather than guessing.
````
