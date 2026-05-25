# Spec: pr-8d8b360 — merge-conflict resolution pushes a local master merge on the GitHub backend

## Problem (grounded)

`prompt_gen.generate_merge_prompt` (`pm_core/prompt_gen.py:451`) builds the prompt for
the Claude "merge resolution" window launched by `_launch_merge_window`
(`pm_core/cli/pr.py:1447`). The standard merge-conflict variant lives at
`pm_core/prompt_gen.py:558-623`.

Flow on the GitHub backend (`pm_core/cli/pr.py:1823-1881`):
- `pm pr merge` runs `gh pr merge <#> --merge` in the PR **workdir** (which is checked
  out on the **PR branch**, never on `master`).
- If `gh pr merge` fails (not mergeable / conflict), it calls `_launch_merge_window(...)`
  with `cwd` defaulting to the PR workdir (still on the PR branch).
- The window's prompt currently (github branch, `prompt_gen.py:569-576` + the shared
  `else` steps `593-600`) instructs:
  - Goal (shared, line 612): "Resolve the merge conflict so that `master` contains the
    merged result of both branches."
  - Step 2 (line 597): "ensure `master` includes changes from `branch`"
  - Step 4 (line 599): "Push the merged `master` to origin"

  Run from the PR-branch workdir, this drives the agent to check out master, merge the
  branch into master locally, and `git push origin master` — bypassing GitHub. GitHub
  never records the merge (PR stays OPEN) and master gets a local-committer merge commit.

The `local` backend branch (`prompt_gen.py:559-568`, steps `586-592`) is correct: it
commits the merge on master in the workdir with NO push (origin is a local non-bare
repo). Leave it untouched.

The `vanilla` (else) backend (`prompt_gen.py:577-584`) legitimately does a local
master merge + `git push origin master` — `pm pr merge`'s vanilla path
(`pm_core/cli/pr.py:1993-2008`) checks out master, merges the branch, and pushes master
to origin. So pushing master to origin is correct for vanilla and must stay.

The bug is specific to the **github** backend reusing the vanilla framing.

## Requirements (restated)

1. **R1** — Split the github backend out of the shared non-local prompt branch so it gets
   its own direction/steps/verdict text. The github prompt must instruct:
   - Merge `base_branch` (master) **INTO** the PR branch in the workdir, resolving conflicts there.
   - Push the **PR branch** to origin.
   - Re-run the GitHub merge: `gh pr merge <#> --merge`.
   - It must NOT instruct merging into master locally or `git push origin master`.
   - It must NOT instruct the agent to pull `base_branch` into the local repo — pm does
     that automatically (see Finalize below). The agent works only in the PR-branch workdir.
2. **R2** — Update the github MERGED verdict description and the failure-framing line
   ("The merge of `branch` into `master` failed") to match the new direction (the failure
   is the GitHub merge; success = branch pushed + GitHub merge completed).
3. **R3** — Leave the `local` backend prompt unchanged.
4. **R4** — Leave the `vanilla` (else) backend prompt unchanged (its push-master behavior
   is correct for that backend).
5. **R5** — Tests: github-backend prompt asserts merging master into the branch, pushing
   the branch, and `gh pr merge` — and asserts it does NOT instruct `git push origin master`.
   Local-backend prompt assertions unchanged (no push). Add a vanilla assertion that it
   still pushes master (regression guard).

## Implicit requirements

- The github prompt needs the GitHub PR number for `gh pr merge <#>`. Source it from
  `pr.get("gh_pr_number")` (the merge window is only launched on the github path when
  `gh_pr_number` is truthy — `pr.py:1828`). Guard with a `<PR#>` placeholder fallback so
  the prompt never crashes if it is missing.
- **Finalize (corrected):** after the merge window emits MERGED,
  `review_loop_ui._finalize_detected_merge` (`review_loop_ui.py:705`) re-runs
  `pm pr merge --propagation-only`. On the github backend, `--propagation-only`
  **skips `gh pr merge`** (`pr.py:1831-1834`) and goes straight to `_pull_after_merge`,
  which pulls `origin/{base_branch}` into the **main repo dir** (not the workdir —
  `pr.py:1555-1556`), then `_finalize_merge`. Consequences:
  - Step 5 (agent runs `gh pr merge`) is **load-bearing**, not idempotent decoration:
    pm will not run the GitHub merge itself on the propagation re-attempt, so if the agent
    skips it the PR stays OPEN on GitHub while pm marks it merged.
  - The local-repo pull is **pm's job, not the agent's**. The prompt must NOT tell the
    agent to pull master into the local repo — the agent's cwd is the PR-branch workdir
    and "the local repo" would misdirect it onto the workdir. The github prompt instead
    states pm pulls the merged base into the main checkout automatically.
  - No code change to the re-attempt path is required.

## Ambiguities

- "Fix the GitHub/vanilla branch" in the task scope: resolved to **github only**. The
  expected behavior is GitHub-specific (`gh pr merge`); vanilla has no `gh` and correctly
  pushes master. "GitHub/vanilla" referred to the combined `else` code branch, not to
  changing vanilla's semantics. Acceptance criteria only call out github + local prompts.
- Whether pm should auto re-invoke `gh pr merge` in finalize vs. relying on the agent:
  resolved to **both, idempotently** — prompt instructs the agent (per acceptance) and the
  existing re-attempt also runs it (`is_pr_merged` makes the second call a no-op success).

## Edge cases

- `gh_pr_number` missing → placeholder `<PR#>` in the command; prompt still coherent.
- Re-entry after partial resolution (branch already merged on GitHub): re-run `pm pr merge`
  sees `is_pr_merged` True and finalizes — unchanged.
- `pull_from_workdir` / `pull_from_origin` variants (`prompt_gen.py:497-556`) are separate
  and untouched.
