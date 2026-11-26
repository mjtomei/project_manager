# Prompt changes — before / after

Every instruction changed by this proposal, with the exact current and
proposed text. Nothing here has been applied to product source.

Contents:

1. [Instruction inventory](#1-instruction-inventory)
2. [Backend Workflow bullets (4 variants)](#2-backend-workflow-bullets)
3. [Tips sentence](#3-tips-sentence)
4. [TUI section](#4-tui-section)
5. [Focused source diff](#5-focused-source-diff)
6. [Rendered before / after](#6-rendered-before--after)

---

## 1. Instruction inventory

| # | Instruction (assembled impl prompt) | Source | Disposition |
| --- | --- | --- | --- |
| 1 | `When ready for review: press d …` | `backend.py` local `:54` | **replaced** |
| 2 | `When ready for review: press d …` | `backend.py` vanilla `:78` | **replaced** |
| 3 | `When ready for review: press d …` | `backend.py` GitHub draft `:96` | **replaced** |
| 4 | `Then mark it done: press d …` | `backend.py` GitHub fallback `:103` | **replaced** |
| 5 | `Commands like pm pr start and pm pr review should be run from the base directory…` | `prompt_gen.py` Tips `:411` | **reworded** |
| 6 | `Do not run commands that spawn new Claude sessions yourself … Use pm tui send to press the appropriate key` | `prompt_gen.py` `tui_section` `:109-112` | **reconciled** by an opt-in paragraph; list unchanged |
| 7 | Merge-after-sign-off restriction | `backend.py` local/vanilla | unchanged |
| 8 | Commit / push / draft-PR / `gh pr create` policy | `backend.py` all variants | unchanged |
| 9 | Spec gate (`[UNRESOLVED]`, `review_spec`) | `spec_gen.py` | unchanged |
| 10 | Bug Fix Flow steps 1–5 | `bug_fix_prompts.py` | unchanged |
| 11 | PR Notes — Handoff Channel | `prompt_gen.py` `_pr_notes_handoff_block` | unchanged |
| 12 | Incidental Bugs (`pm pr add …`) | `prompt_gen.py` `_OUT_OF_SCOPE_BUGS_BLOCK` | unchanged |
| 13 | Beginner guidance / Pane Cleanup (off by default) | `prompt_gen.py` | unchanged |

After the change, the assembled implementation prompt contains **no
instruction** to press `d` or run `pm pr review`. The only remaining
occurrences are explicit prohibitions in the TUI section and the unchanged
human-facing docs/help (outside the prompt).

---

## 2. Backend Workflow bullets

### 2.1 Local — `pm_core/backend.py:50-58`

Before:

```
- You're on branch `{branch}`
- Commit as you go
- When ready for review: press `d` in the TUI or run `pm pr review {pr_id}` from the base pm directory (not from this workdir)
- Merging happens after sign-off (`pm pr merge {pr_id}` from the base pm directory publishes only a signed-off candidate); never push or merge into `{base_branch}` yourself
```

After:

```
- You're on branch `{branch}`
- Commit as you go
- When implementation is complete, report completion and wait. PM handles the transition to review.
- Merging happens after sign-off (`pm pr merge {pr_id}` from the base pm directory publishes only a signed-off candidate); never push or merge into `{base_branch}` yourself
```

### 2.2 Vanilla — `pm_core/backend.py:74-82`

Before:

```
- You're on branch `{branch}`
- Commit and push as you go: `git push origin {branch}`
- When ready for review: press `d` in the TUI or run `pm pr review {pr_id}` from the base pm directory (not from this workdir)
- Merging happens after sign-off (`pm pr merge {pr_id}` from the base pm directory publishes only a signed-off candidate); never push or merge into `{base_branch}` yourself
```

After:

```
- You're on branch `{branch}`
- Commit and push as you go: `git push origin {branch}`
- When implementation is complete, report completion and wait. PM handles the transition to review.
- Merging happens after sign-off (`pm pr merge {pr_id}` from the base pm directory publishes only a signed-off candidate); never push or merge into `{base_branch}` yourself
```

### 2.3 GitHub with an existing draft — `pm_core/backend.py:90-97`

Before:

```
- You're on branch `{branch}` with a draft PR: {gh_pr_url}
- Commit and push as you go: `git push origin {branch}`
- When ready for review: press `d` in the TUI or run `pm pr review {pr_id}` from the base pm directory (not from this workdir)
```

After:

```
- You're on branch `{branch}` with a draft PR: {gh_pr_url}
- Commit and push as you go: `git push origin {branch}`
- When implementation is complete, report completion and wait. PM handles the transition to review.
```

### 2.4 GitHub fallback — `pm_core/backend.py:98-104`

Before:

```
- You're on branch `{branch}`
- Commit and push as you go: `git push -u origin {branch}`
- Create a PR when ready: `gh pr create --title "{title}" --base {base_branch}`
- Then mark it done: press `d` in the TUI or run `pm pr review {pr_id}` from the base pm directory (not from this workdir)
```

After:

```
- You're on branch `{branch}`
- Commit and push as you go: `git push -u origin {branch}`
- Create a PR when ready: `gh pr create --title "{title}" --base {base_branch}`
- When implementation is complete, report completion and wait. PM handles the transition to review.
```

---

## 3. Tips sentence

`pm_core/prompt_gen.py:411` (inside `generate_prompt`'s `_assemble`).

Before:

> - This workdir is a clone managed by pm. The base pm state (project.yaml, PR
>   status) lives in a separate directory and is not automatically synced with
>   this clone. Commands like `pm pr start` and `pm pr review` should be run
>   from the base directory, not here — your session for {pr_id} is already
>   running.

After:

> - This workdir is a clone managed by pm. The base pm state (project.yaml, PR
>   status) lives in a separate directory and is not automatically synced with
>   this clone. PR-state commands like `pm pr start` run from the base pm
>   directory, not here — your session for {pr_id} is already running, and PM
>   handles the transition to review.

Why reword rather than delete the whole bullet: the first two sentences are
necessary workdir/state guidance (the clone is not synced with the base pm
state). The third sentence was the instruction that drove agents to run
`pm pr review` from the base directory. Alternative (A1 in `impl.md`): delete
only the `and \`pm pr review\`` clause.

---

## 4. TUI section

`pm_core/prompt_gen.py:95-113` (`tui_section`). The existing paragraph is kept
verbatim; an opt-in paragraph is appended for implementation sessions only.

Existing (unchanged):

```
**Do not** run commands that spawn new Claude sessions yourself (e.g. `pm pr start`,
`pm pr done`, `pm plan add`, `pm plan breakdown`, `pm plan review`). These must be
triggered through the TUI so panes are managed correctly. Use `pm tui send` to press
the appropriate key in the TUI instead.
```

Added (only when `handoff_to_pm=True`, i.e. `generate_prompt` with a session):

```
**Do not start the review yourself.** Don't press `d`, don't use `pm tui send`
to start a review, and don't run `pm pr review`. When implementation is
complete, report completion and wait. PM handles the transition to review.
```

Scope:

- `generate_prompt` (`:378`) passes `handoff_to_pm=True`.
- All other callers use the default `False` and render byte-identically:
  `generate_review_prompt`, `generate_signoff_prompt`,
  `generate_merge_prompt`, `generate_watcher_prompt`,
  `generate_discovery_supervisor_prompt`,
  `generate_bug_fix_impl_prompt`, `generate_improvement_fix_impl_prompt`,
  `generate_qa_planner_prompt`, `generate_qa_interactive_prompt`,
  `generate_qa_child_prompt`, `generate_standalone_qa_prompt`,
  `generate_watcher_review_prompt`, `guide.py`, `cli/plan.py`,
  `cli/cluster.py`, `tui/pane_ops.py`.
- This matters because `generate_watcher_prompt` deliberately tells the
  watcher to run `pm tui send … zz d` (`prompt_gen.py:1546-1548`). A global
  prohibition would contradict it.

---

## 5. Focused source diff

```diff
--- pm_core/backend.py
+++ pm_core/backend.py
@@ -51,7 +51,7 @@
         return (
             f"- You're on branch `{branch}`\n"
             f"- Commit as you go\n"
-            f"- When ready for review: press `d` in the TUI or run `pm pr review {pr_id}` from the base pm directory (not from this workdir)\n"
+            f"- When implementation is complete, report completion and wait. PM handles the transition to review.\n"
             f"- Merging happens after sign-off (`pm pr merge {pr_id}` from the base pm "
             f"directory publishes only a signed-off candidate); never push or merge "
             f"into `{base_branch}` yourself"
@@ -75,7 +75,7 @@
         return (
             f"- You're on branch `{branch}`\n"
             f"- Commit and push as you go: `git push origin {branch}`\n"
-            f"- When ready for review: press `d` in the TUI or run `pm pr review {pr_id}` from the base pm directory (not from this workdir)\n"
+            f"- When implementation is complete, report completion and wait. PM handles the transition to review.\n"
             f"- Merging happens after sign-off (`pm pr merge {pr_id}` from the base pm "
             f"directory publishes only a signed-off candidate); never push or merge "
             f"into `{base_branch}` yourself"
@@ -93,14 +93,14 @@
             return (
                 f"- You're on branch `{branch}` with a draft PR: {gh_pr_url}\n"
                 f"- Commit and push as you go: `git push origin {branch}`\n"
-                f"- When ready for review: press `d` in the TUI or run `pm pr review {pr_id}` from the base pm directory (not from this workdir)"
+                f"- When implementation is complete, report completion and wait. PM handles the transition to review."
             )
         # Fallback for when draft PR wasn't created (e.g., push failed)
         return (
             f"- You're on branch `{branch}`\n"
             f"- Commit and push as you go: `git push -u origin {branch}`\n"
             f"- Create a PR when ready: `gh pr create --title \"{title}\" --base {base_branch}`\n"
-            f"- Then mark it done: press `d` in the TUI or run `pm pr review {pr_id}` from the base pm directory (not from this workdir)"
+            f"- When implementation is complete, report completion and wait. PM handles the transition to review."
         )
```

```diff
--- pm_core/prompt_gen.py
+++ pm_core/prompt_gen.py
@@ -92,12 +92,22 @@
 """
 
 
-def tui_section(session_name: str) -> str:
+def tui_section(session_name: str, handoff_to_pm: bool = False) -> str:
     """Build a TUI interaction section for prompts running in a tmux session.
 
     Used by prompt_gen internally and by other modules (guide, plan, meta)
     that construct prompts for Claude sessions running alongside the TUI.
+
+    ``handoff_to_pm`` adds the implementation-session handoff rule: the
+    session must not start review itself (not by pressing ``d``, not via
+    ``pm tui send``, not by running ``pm pr review``).  Controllers such as
+    the watcher keep the default and may still start reviews.
     """
+    handoff = "" if not handoff_to_pm else """
+**Do not start the review yourself.** Don't press `d`, don't use `pm tui send`
+to start a review, and don't run `pm pr review`. When implementation is
+complete, report completion and wait. PM handles the transition to review.
+"""
     return f"""
 ## Interacting with the TUI
 
@@ -110,7 +120,7 @@
 `pm pr done`, `pm plan add`, `pm plan breakdown`, `pm plan review`). These must be \
 triggered through the TUI so panes are managed correctly. Use `pm tui send` to press \
 the appropriate key in the TUI instead.
-"""
+{handoff}"""
 
 
 def _signoff_return_block(pr: dict, for_signoff: bool = False) -> str:
@@ -368,7 +378,8 @@
     except FileNotFoundError:
         pass
 
-    tui_block = tui_section(session_name) if session_name else ""
+    tui_block = (tui_section(session_name, handoff_to_pm=True)
+                 if session_name else "")
 
     # Include PR notes (addendums added after work began).  The sign-off
     # return block is instruction text (the operative handoff), so it is
@@ -408,7 +419,7 @@
 ## Tips
 - This session may be resuming after a restart. Check `git status` and `git log` to see if previous work exists on this branch — if so, continue from there. The directory may contain uncommitted implementation work from a previous session.
 - Before referencing existing code (imports, function calls, class usage), read the source to verify the interface.
-- This workdir is a clone managed by pm. The base pm state (project.yaml, PR status) lives in a separate directory and is not automatically synced with this clone. Commands like `pm pr start` and `pm pr review` should be run from the base directory, not here — your session for {pr_id} is already running.
+- This workdir is a clone managed by pm. The base pm state (project.yaml, PR status) lives in a separate directory and is not automatically synced with this clone. PR-state commands like `pm pr start` run from the base pm directory, not here — your session for {pr_id} is already running, and PM handles the transition to review.
 {_remote_sync_tip(data, branch)}
 {_base_branch_sync_tip(data, base_branch)}
```

---

## 6. Rendered before / after

Rendered from a scratch copy of `pm_core` with the §5 edits applied, using the
fixture described in `impl.md` §6. The product tree was not modified.

### 6.1 Tips (identical in all four variants)

Before:

```
- This workdir is a clone managed by pm. The base pm state (project.yaml, PR status) lives in a separate directory and is not automatically synced with this clone. Commands like `pm pr start` and `pm pr review` should be run from the base directory, not here — your session for pr-fixture is already running.
```

After:

```
- This workdir is a clone managed by pm. The base pm state (project.yaml, PR status) lives in a separate directory and is not automatically synced with this clone. PR-state commands like `pm pr start` run from the base pm directory, not here — your session for pr-fixture is already running, and PM handles the transition to review.
```

### 6.2 Workflow — local

Before:

```
## Workflow
- You're on branch `pm/pr-fixture-bug-fixture-example-handoff`
- Commit as you go
- When ready for review: press `d` in the TUI or run `pm pr review pr-fixture` from the base pm directory (not from this workdir)
- Merging happens after sign-off (`pm pr merge pr-fixture` from the base pm directory publishes only a signed-off candidate); never push or merge into `master` yourself
```

After:

```
## Workflow
- You're on branch `pm/pr-fixture-bug-fixture-example-handoff`
- Commit as you go
- When implementation is complete, report completion and wait. PM handles the transition to review.
- Merging happens after sign-off (`pm pr merge pr-fixture` from the base pm directory publishes only a signed-off candidate); never push or merge into `master` yourself
```

### 6.3 Workflow — vanilla

Before:

```
## Workflow
- You're on branch `pm/pr-fixture-bug-fixture-example-handoff`
- Commit and push as you go: `git push origin pm/pr-fixture-bug-fixture-example-handoff`
- When ready for review: press `d` in the TUI or run `pm pr review pr-fixture` from the base pm directory (not from this workdir)
- Merging happens after sign-off (`pm pr merge pr-fixture` from the base pm directory publishes only a signed-off candidate); never push or merge into `master` yourself
```

After:

```
## Workflow
- You're on branch `pm/pr-fixture-bug-fixture-example-handoff`
- Commit and push as you go: `git push origin pm/pr-fixture-bug-fixture-example-handoff`
- When implementation is complete, report completion and wait. PM handles the transition to review.
- Merging happens after sign-off (`pm pr merge pr-fixture` from the base pm directory publishes only a signed-off candidate); never push or merge into `master` yourself
```

### 6.4 Workflow — GitHub with draft

Before:

```
## Workflow
- You're on branch `pm/pr-fixture-bug-fixture-example-handoff` with a draft PR: https://github.com/example/repo/pull/42
- Commit and push as you go: `git push origin pm/pr-fixture-bug-fixture-example-handoff`
- When ready for review: press `d` in the TUI or run `pm pr review pr-fixture` from the base pm directory (not from this workdir)
```

After:

```
## Workflow
- You're on branch `pm/pr-fixture-bug-fixture-example-handoff` with a draft PR: https://github.com/example/repo/pull/42
- Commit and push as you go: `git push origin pm/pr-fixture-bug-fixture-example-handoff`
- When implementation is complete, report completion and wait. PM handles the transition to review.
```

### 6.5 Workflow — GitHub fallback

Before:

```
## Workflow
- You're on branch `pm/pr-fixture-bug-fixture-example-handoff`
- Commit and push as you go: `git push -u origin pm/pr-fixture-bug-fixture-example-handoff`
- Create a PR when ready: `gh pr create --title "Fixture bug: example handoff" --base master`
- Then mark it done: press `d` in the TUI or run `pm pr review pr-fixture` from the base pm directory (not from this workdir)
```

After:

```
## Workflow
- You're on branch `pm/pr-fixture-bug-fixture-example-handoff`
- Commit and push as you go: `git push -u origin pm/pr-fixture-bug-fixture-example-handoff`
- Create a PR when ready: `gh pr create --title "Fixture bug: example handoff" --base master`
- When implementation is complete, report completion and wait. PM handles the transition to review.
```

### 6.6 TUI section — implementation session (all four variants)

Before (ends at):

```
**Do not** run commands that spawn new Claude sessions yourself (e.g. `pm pr start`, `pm pr done`, `pm plan add`, `pm plan breakdown`, `pm plan review`). These must be triggered through the TUI so panes are managed correctly. Use `pm tui send` to press the appropriate key in the TUI instead.
```

After (same paragraph, plus):

```
**Do not start the review yourself.** Don't press `d`, don't use `pm tui send`
to start a review, and don't run `pm pr review`. When implementation is
complete, report completion and wait. PM handles the transition to review.
```

### 6.7 Container / non-TUI session

No TUI section is rendered at all (`session_name=None`). The only completion
instruction is the Workflow bullet:

```
- When implementation is complete, report completion and wait. PM handles the transition to review.
```

Full renders: `prompts/*-container.md`.
