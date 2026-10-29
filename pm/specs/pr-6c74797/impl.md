# Implementation spec — pr-6c74797

**Bug:** implementation prompts must leave the review handoff to PM instead of
driving the live TUI.

**Status:** documentation only. No product source has been changed. Product
implementation, review and QA wait for explicit user approval of this package.

**Mode requested:** DeepSeek 1017/high for implementation; Opus 5.5/xhigh
sign-off; manual `wait_for_merge`. (Recorded here, not acted on.)

---

## 1. Requirements (grounded in code)

### R1 — Replace the completion/handoff line in all four backend variants

`pm_core/backend.py` generates the `## Workflow` block of an implementation
prompt. There are three backend classes and four rendered variants:

| Variant | Class / method | Current handoff line |
| --- | --- | --- |
| local | `LocalBackend.pr_instructions` — `pm_core/backend.py:50-58` | line 54 |
| vanilla | `VanillaBackend.pr_instructions` — `pm_core/backend.py:74-82` | line 78 |
| GitHub with an existing draft | `GitHubBackend.pr_instructions` (draft branch) — `pm_core/backend.py:90-97` | line 96 |
| GitHub fallback (no draft) | `GitHubBackend.pr_instructions` (fallback branch) — `pm_core/backend.py:98-104` | line 103 |

Every current line tells the agent to press `d` in the TUI or run
`pm pr review <id>` from the base pm directory. Replace each with the exact
proposed sentence:

> When implementation is complete, report completion and wait. PM handles the transition to review.

Preserve the surrounding bullets verbatim:

- local: branch line, `Commit as you go`, merge-after-sign-off restriction.
- vanilla: branch line, `Commit and push as you go: git push origin …`,
  merge-after-sign-off restriction.
- GitHub draft: branch + draft-PR URL line, `Commit and push as you go:
  git push origin …`.
- GitHub fallback: branch line, `Commit and push as you go: git push -u origin
  …`, `Create a PR when ready: gh pr create …`.

The fallback `gh pr create` line stays: it is part of the existing
commit/push/PR policy for the case where draft-PR creation failed, and it does
not start a review. See A3.

### R2 — Reconcile the `## Tips` sentence

`pm_core/prompt_gen.py:411` (inside `generate_prompt`'s `_assemble`):

> This workdir is a clone managed by pm. The base pm state (project.yaml, PR
> status) lives in a separate directory and is not automatically synced with
> this clone. Commands like `pm pr start` and `pm pr review` should be run from
> the base directory, not here — your session for {pr_id} is already running.

It repeats the bad instruction ("`pm pr review` should be run from the base
directory"). Proposed replacement (one line, same position):

> This workdir is a clone managed by pm. The base pm state (project.yaml, PR
> status) lives in a separate directory and is not automatically synced with
> this clone. PR-state commands like `pm pr start` run from the base pm
> directory, not here — your session for {pr_id} is already running, and PM
> handles the transition to review.

This keeps the workdir/state guidance, drops the review instruction, and
reinforces the handoff. See A1 for the alternative (delete only the
`pm pr review` clause).

### R3 — Inspect the assembled prompt, including the TUI section, for
contradictions; propose any additional change explicitly

`pm_core/prompt_gen.py:95-113` (`tui_section`) currently ends with:

> **Do not** run commands that spawn new Claude sessions yourself (e.g.
> `pm pr start`, `pm pr done`, `pm plan add`, `pm plan breakdown`,
> `pm plan review`). These must be triggered through the TUI so panes are
> managed correctly. Use `pm tui send` to press the appropriate key in the TUI
> instead.

Two problems for an implementation session:

1. `pm pr review` is missing from the forbidden-command list even though it
   spawns a Claude review window.
2. The section actively teaches `pm tui send` as the way to press keys, which
   is exactly how an implementation agent drives the live TUI to start review.

**Proposed additional change (needs explicit approval — see A2):** add an
opt-in parameter to `tui_section` and use it only from `generate_prompt`:

```python
def tui_section(session_name: str, handoff_to_pm: bool = False) -> str:
    ...
    handoff = "" if not handoff_to_pm else """
**Do not start the review yourself.** Don't press `d`, don't use `pm tui send`
to start a review, and don't run `pm pr review`. When implementation is
complete, report completion and wait. PM handles the transition to review.
"""
    return f"""...{handoff}"""
```

`generate_prompt` (currently line 371) calls
`tui_section(session_name, handoff_to_pm=True)`. Every other call site keeps
the default (`False`), so review, sign-off, QA, plan, guide and watcher
prompts are byte-identical. This matters: `generate_watcher_prompt`
legitimately tells the watcher to run `pm tui send … zz d` to start a review
loop (`pm_core/prompt_gen.py:1546-1548`), and a global prohibition would
contradict it.

### R4 — Autostart-disabled completion path

Autostart is a TUI scheduler property, not an input to `generate_prompt`
(there is no autostart parameter anywhere in `pm_core/prompt_gen.py`). The
prompt is therefore identical with autostart on or off. With autostart
disabled the idle→review transition in
`pm_core/tui/review_loop_ui.py:1353-1355` is skipped, so the PR stays
`in_progress` until the user presses `d` / runs `pm pr review`. With autostart
enabled the TUI performs the transition for in-scope PRs. In both cases the
agent does nothing after reporting completion. See
`prompts/autostart-disabled.md`.

### R5 — Verification (after approval)

Generated prompts across all four variants must leave advancement to PM and
contain no instruction to press `d` or invoke `pm pr review` for completion.
Verification must use isolated fixtures only — never the real TUI. Details in
§6.

---

## 2. Implicit requirements

1. **No new mechanism.** "Report completion and wait" is just the agent
   ending its turn with a summary; the existing idle detector / user keypress
   remains the transition trigger. No new phase, flag, controller or
   completion protocol.
2. **Preserve spec gates.** `format_spec_for_prompt` /
   `spec_generation_preamble` are untouched, so `[UNRESOLVED]` ambiguity waits
   and `review_spec` approval still work.
3. **Preserve merge restrictions.** The `pm pr merge … never push or merge
   into <base>` bullets stay in local/vanilla; GitHub variants never had them
   and keep their existing text.
4. **Preserve commit/push policy.** Only the handoff bullet changes.
5. **Preserve the TUI section for non-implementation prompts.** The scoped
   flag must not alter review/sign-off/QA/watcher/plan/guide output.
6. **Preserve file-backed bootstrap delivery.** `fit_prompt` bounds and the
   launcher's file fallback are untouched; the new text is ~120 bytes per
   variant.
7. **Preserve ordinary manual user commands.** The human-facing guide
   (`pm_core/guide.py:421`), README and CLI help still document `d` /
   `pm pr review` for the user. Only agent-facing implementation prompt text
   changes.
8. **Preserve drafts and GitHub URL.** The draft-PR URL bullet and
   `gh pr create` fallback remain.
9. **Preserve PR notes / sign-off return blocks.** Those can contain
   user-authored text that mentions `pm pr review`; they are not rewritten.
10. **No containerization work.** The scoped flag works with
    `session_name=None` (no TUI block at all), which is the container/CLI
    path; no new container behavior.

---

## 3. Proposed wording (exact)

### 3.1 `pm_core/backend.py`

Local (`:54`) and vanilla (`:78`), including the trailing `\n`:

```python
f"- When implementation is complete, report completion and wait. PM handles the transition to review.\n"
```

GitHub draft (`:96`), no trailing `\n` (current shape):

```python
f"- When implementation is complete, report completion and wait. PM handles the transition to review."
```

GitHub fallback (`:103`):

```python
f"- When implementation is complete, report completion and wait. PM handles the transition to review."
```

### 3.2 `pm_core/prompt_gen.py` Tips line (`:411`)

```
- This workdir is a clone managed by pm. The base pm state (project.yaml, PR status) lives in a separate directory and is not automatically synced with this clone. PR-state commands like `pm pr start` run from the base pm directory, not here — your session for {pr_id} is already running, and PM handles the transition to review.
```

### 3.3 `pm_core/prompt_gen.py` TUI handoff paragraph (opt-in, implementation
sessions only)

```
**Do not start the review yourself.** Don't press `d`, don't use `pm tui send`
to start a review, and don't run `pm pr review`. When implementation is
complete, report completion and wait. PM handles the transition to review.
```

---

## 4. Ambiguities and proposed resolutions

### A1 — How to "remove or reconcile" the Tips sentence

Options: (a) delete only the `and \`pm pr review\`` clause, leaving
`Commands like \`pm pr start\` should be run from the base directory…`;
(b) rewrite as in §3.2.

**Proposed: (b).** It keeps the state-sync guidance, removes the review
instruction, and states the handoff once more. (a) is smaller but still says
"commands … should be run from the base directory" in a prompt that forbids
the agent from running session-spawning commands.

### A2 — The TUI section change

Options: (a) no TUI change; (b) scoped opt-in paragraph (§3.3); (c) global
change to `tui_section`.

**Proposed: (b).** (a) leaves `pm tui send` taught to implementation agents
next to a Workflow bullet that says to wait — the contradiction the task asks
us to inspect. (c) would contradict the watcher prompt's legitimate
`pm tui send … zz d` instruction and change 21 other call sites. (b) touches
exactly one call site and is invisible elsewhere. **This is the additional
wording change requiring explicit user approval.**

### A3 — Keep the GitHub-fallback `gh pr create` line?

**Proposed: keep.** It exists because draft-PR creation can fail; without it
the fallback backend would leave the agent with no PR at all. It is not a
review handoff and is part of existing push policy. If the user wants agents
to stop creating PRs entirely, that is a separate policy change.

### A4 — What "report completion" means

**Proposed:** the agent writes its normal completion summary in its pane and
ends the turn. No file, marker or command is added. The PM idle detector
(`pm_core/tui/review_loop_ui.py:_poll_impl_idle`) or the user's `d` key is the
transition. This preserves "must not imply completion while tests/background
work are still running": the sentence is conditional on *implementation being
complete*, and the existing bug-fix flow's verify steps remain above it.

### A5 — Autostart-disabled rendering

**Proposed:** document that the prompt is byte-identical (no autostart input
exists) and describe the disabled-path behavior; include one full rendering
plus the description in `prompts/autostart-disabled.md`. See R4.

### A6 — Should the exact sentence also mention `d` / `pm pr review`?

**Proposed: no** in the Workflow bullet — use the user's exact wording. The
explicit prohibitions live in the TUI paragraph for TUI sessions; non-TUI
(container) sessions have no TUI to drive, so the Workflow bullet is enough.

### A7 — Test placement

**Proposed:** new `tests/test_impl_prompt_handoff.py` with focused tests for
the four backend variants, `generate_prompt` with/without a session name, and
`tui_section` scoping. Existing tests (`tests/test_github_draft_pr.py`,
`tests/test_pr_notes.py`, `tests/test_bug_fix_flow_prompts.py`,
`tests/test_watcher_loop.py`) should keep passing unchanged; none asserts the
old handoff text (verified by grep).

### A8 — Docs / help text

**Proposed:** no changes. `pm_core/guide.py`, README and CLI help describe
what the *human* can do; the bug is agent-facing prompt text.

---

## 5. Edge cases

- **`session_name=None`** (container / `pm prompt`): no TUI section; new
  Workflow bullet and Tips line still render.
- **GitHub draft URL present:** URL bullet preserved; only the handoff bullet
  changes.
- **GitHub fallback:** `gh pr create` preserved; handoff bullet changes.
- **Unknown backend name:** `get_backend` falls back to `VanillaBackend`; gets
  the vanilla text.
- **Other `tui_section` callers** (review, sign-off, QA, watcher, plan, guide,
  cluster, meta): default `handoff_to_pm=False`, output unchanged.
- **Watcher prompt** still instructs `pm tui send … zz d`; unaffected.
- **PR notes / sign-off return text** may still contain `pm pr review` if a
  human wrote it; not rewritten (instruction-shaped user text is inlined
  whole by design).
- **Prompt size:** +~120 bytes per variant; nowhere near `PROMPT_ARG_LIMIT`.
- **Bug-fix flow:** unchanged; its verify steps remain before the handoff.
- **Autostart enabled but PR out of scope:** the TUI will not auto-transition;
  the prompt still says PM handles it, which is correct (PM/user decides).

---

## 6. Verification plan (after approval)

1. **Failing test first.** Add tests that fail on current `HEAD`:
   - each `pr_instructions` variant contains the new sentence;
   - none contains `` press `d` `` or `pm pr review <id>`;
   - branch / push / draft URL / `gh pr create` / merge bullets preserved;
   - `generate_prompt(..., session_name=...)` has the TUI handoff paragraph
     and the new Workflow bullet; `session_name=None` has no TUI section and
     still has the Workflow bullet;
   - `tui_section("s")` (default) is unchanged and does not contain the new
     prohibition; `tui_section("s", handoff_to_pm=True)` does.
2. **Fix** with the edits in §3.
3. **Run related suites:** `tests/test_impl_prompt_handoff.py`,
   `tests/test_github_draft_pr.py`, `tests/test_pr_notes.py`,
   `tests/test_bug_fix_flow_prompts.py`, `tests/test_watcher_loop.py`,
   `tests/test_signoff_integration.py`. Use `pytest<9` per container recipe.
4. **Render check (isolated fixture, no TUI):** render the four variants with
   the fixture below and diff against the approved files in `prompts/`;
   assert no completion instruction to press `d` / run `pm pr review`.
5. **Bug-fix captures:** pre-fix render under `$CAP/impl/pre-fix/` (a script
   capture is the repro — no real TUI interaction), post-fix render under
   `$CAP/impl/post-fix/`.
6. **Do not** press `d`, run `pm pr review`, open review windows, or send keys
   to the real TUI for any of this.

### Render fixture used for this package

- PR id `pr-fixture`, plan `bugs`, title
  `Fixture bug: example handoff`, branch
  `pm/pr-fixture-bug-fixture-example-handoff`, status `in_progress`,
  no dependencies, no PR notes, no `workdir`, no spec.
- Project: name `fixture`, base branch `master`.
- Four configs: `local`; `vanilla`; `github` with
  `gh_pr=https://github.com/example/repo/pull/42` / `gh_pr_number=42`;
  `github` with `gh_pr=None`.
- `session_name=pm-project_manager-00000000` for the TUI renders;
  `session_name=None` for the container renders.
- Rendered from a scratch copy of `pm_core` with the §3 edits applied; the
  product tree was not modified.

---

## 7. Non-goals

- No new controller/phase/completion mechanism.
- No change to review iteration focus semantics.
- No containerization changes (`#278`, `pr-efab0ce` cover isolation).
- No change to autostart, idle detection, review-loop launching or merge
  gating.
- No rewrite of user-authored PR notes or sign-off returns.
- No change to human-facing docs/help.

---

## 8. Review package

Read the whole proposed prompts (TUI + container variants for all four
backends):

- [prompt-changes.md](prompt-changes.md) — before/after text and focused diff.
- [prompts/local-tui.md](prompts/local-tui.md)
- [prompts/vanilla-tui.md](prompts/vanilla-tui.md)
- [prompts/github-draft-tui.md](prompts/github-draft-tui.md)
- [prompts/github-fallback-tui.md](prompts/github-fallback-tui.md)
- [prompts/local-container.md](prompts/local-container.md)
- [prompts/vanilla-container.md](prompts/vanilla-container.md)
- [prompts/github-draft-container.md](prompts/github-draft-container.md)
- [prompts/github-fallback-container.md](prompts/github-fallback-container.md)
- [prompts/autostart-disabled.md](prompts/autostart-disabled.md) — identical
  rendering plus the disabled completion path.

**Approval requested for:** (1) the four backend replacements, (2) the Tips
rewrite, and (3) the scoped TUI handoff paragraph. Nothing will be implemented
until you approve.
