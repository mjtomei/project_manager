# QA Spec: GitHub backend mock for regression tests (pr-9603d04)

## Context / who the "user" is

This PR adds a scriptable, deterministic fake GitHub backend
(`FakeGitHubBackend` / `FakeGitHubRepo` in `pm_core/fake_github.py`) so
regression tests can drive pm's github-backend code paths — PR create, status
sync, mark-ready, merge, post-merge pull, close — without hitting the real
GitHub API. It is the GitHub-side sibling of pr-abcf70f (FakeClaudeSession).

To make a single interception point possible, the PR **also refactors real
production code**: every direct `subprocess.run(["gh", ...])` call in pm is now
routed through the one chokepoint `gh_ops.run_gh()`, which gained a pluggable
transport (`set_gh_runner` / `gh_runner` context manager) and a `timeout`
param. Affected real paths:

- `pr_sync.sync_from_github` — the github status-polling path (now
  `gh_ops.get_pr_state`).
- `cli/pr.py` `pr_merge` — `gh pr merge` (now `gh_ops.merge_pr`).
- `cli/pr.py` `pr_close` — `gh pr close` (now `gh_ops.close_pr`).
- `git_ops.push_pm_branch` — the pm-state-sync `gh pr create`.
- `gh_ops.create_draft_pr` — gained **orphaned-PR recovery**: when
  `gh pr create` fails with "already exists", it now looks up the existing PR
  for the branch and returns it instead of `None`.

**The consumer of the fake is a regression-test author / the regression
runner.** The fake can be installed two ways:

1. **In-process** via `gh_ops.set_gh_runner` (or the `installed()` context
   manager / `fake_github` & `fake_github_repo` pytest fixtures). This is the
   multi-threaded-test / regression-runner consumption shape and the route
   used by scenarios 1–6.
2. **Out-of-process, per session (R9, added after the initial spec)** via
   `pm fake-github config set` — mirroring fake-claude. State lives at
   `~/.pm/sessions/<tag>/fake-github/` (`state.json` PR registry +
   `remote.git/` backing repo). `gh_ops.run_gh` consults
   `paths.fake_github_active()` when no in-process runner is set and dispatches
   via `fake_github.dispatch_session`. This makes a freshly-spawned
   `pm pr sync-github` / `pm pr merge` / `pm pr close` / `pm push` subprocess
   (or TUI pane) serve `gh` from the fake instead of real GitHub — so the
   github backend is now drivable from a **real CLI pane**, not only in-process.
   Caveats: predicate/callable scripts are in-process only (out-of-process
   scripts are string-match only); out-of-process dispatch assumes serial `gh`
   calls per session; and the git-plumbing half of merge-with-pull needs the
   consumer repo's origin pointed at the fake's `remote.git` + real git
   (push-proxy note in impl.md) — full pm-driven pull is pr-7d5d036's job.

The user-observable surface under test is therefore: driving pm's
github-backend operations (in-process functions **or** real `pm pr ...` /
`pm push` / `pm fake-github` CLI against the out-of-process fake) and observing
real outcomes (PR records, pm PR status changes in `project.yaml`, real git
state in the backing repo and a consumer clone, and `gh`-shaped error output).
This is exactly how the regression runner (pr-7d5d036) will consume it.

## Shared resources touched by the diff (concurrency targets)

- **`gh_ops._GH_RUNNER`** — a single module-global transport pointer.
  Installed/restored by `installed()` / `gh_runner`. Accessed by every caller.
- **`FakeGitHubBackend.prs` registry + `_next_number`** — mutable in-memory PR
  state; PR numbers are minted from a single counter.
- **`FakeGitHubRepo` on-disk git repo** — one real local git repo acting as
  the remote; merges, branch creation, clones and fetches all hit this single
  path.
- **`_scripts` FIFO queue** — scripted/canned responses consumed in order.
- **`calls` list** — every gh argv recorded for assertions.

## 1. Requirements (Given / When / Then)

### R1 — Draft PR creation routes through the fake
- **Given** a test has installed the fake as the gh transport,
- **When** the author drives pm's draft-PR creation (the `pm pr start` path,
  `gh_ops.create_draft_pr` / `create_pr`),
- **Then** a PR is registered in the fake with the supplied title/body/base,
  marked draft (or not, for `create_pr`), and the returned URL ends in
  `/pull/<n>` with the parsed number matching.

### R2 — Status polling observes simulated remote state
- **Given** a github-backend pm project whose PR has a `gh_pr_number`, and the
  fake serving that PR,
- **When** the author runs the status sync (`pr_sync.sync_from_github`),
- **Then** the pm PR status reflects the fake's PR state: a still-draft PR
  stays in-progress; a draft→ready transition yields `in_review`; a merge
  yields the PR listed as merged.

### R3 — Mark-ready (draft → ready) routes through the fake
- **Given** a draft PR in the fake,
- **When** the author marks it ready (`gh_ops.mark_pr_ready`),
- **Then** the operation succeeds and the fake PR is no longer a draft.

### R4 — Merge + post-merge pull works against a git-backed remote
- **Given** a git-backed fake (`with_git_repo` / `fake_github_repo`) and a
  draft PR whose head branch exists as a real branch on the backing repo, and
  a consumer clone of that repo,
- **When** the author merges the PR (`gh_ops.merge_pr`) and the consumer
  fetches and fast-forwards its base branch (the `_pull_after_merge` shape),
- **Then** the merge succeeds, the backing repo's base branch advances so the
  head is an ancestor of base, the consumer `git fetch` + `git merge --ff-only`
  succeeds, and the branch's marker file is present in the consumer workdir.

### R5 — Close routes through the fake
- **Given** an open PR in the fake,
- **When** the author closes it (`gh_ops.close_pr`, with/without delete-branch),
- **Then** the operation succeeds and the fake PR state becomes CLOSED (a
  merged PR is not flipped to CLOSED).

### R6 — Scriptable failures compose realistic flows
- **Given** the fake with a queued canned failure (rate-limit/5xx/conflict/404
  or a predicate match),
- **When** the matching gh operation runs,
- **Then** it returns the scripted returncode/stderr in the documented
  gh-shaped form, consumed FIFO (`times` controls repetition; exhausted
  scripts fall through to normal dispatch); `check=True` surfaces a non-zero
  result as `CalledProcessError`.

### R7 — Orphaned-PR recovery in create_draft_pr (real behavior change)
- **Given** a branch that already has a PR (a prior create succeeded but the
  number was never persisted),
- **When** the author re-runs draft-PR creation and `gh pr create` fails with
  "already exists",
- **Then** `create_draft_pr` recovers by looking up the existing PR and
  returns its url/number (not `None`); a non-"already exists" failure still
  returns `None`.

### R8 — Every gh operation flows through the one chokepoint
- **Given** the fake installed,
- **When** the author drives any pm github operation, including the
  pm-state-sync `gh pr create` (`--head` with no `--base`) from
  `git_ops.push_pm_branch`,
- **Then** it is intercepted by the fake (recorded in `calls`) rather than
  invoking real `gh`, and the `gh`-installed/authenticated check is skipped
  (`auth status` succeeds without a real gh).

### R9 — Transport install/restore is safe
- **Given** the fake installed via `installed()` / `gh_runner`,
- **When** the context exits — including via an exception, or nested installs,
- **Then** the previously installed transport is restored (None when none was
  set; the outer fake when nested).

## 2. Setup

- Obtain a working `pm` in the container with `./install.sh --local` from the
  pm repo, or `pip install -e .` (per `tui-manual-test.md`). Confirm with
  `pm which`.
- For status-sync requirements, create a throwaway github-backend pm project:
  `pm init --backend github` (or a minimal `project.yaml` with
  `backend: github` and a PR carrying `gh_pr_number`). Bootstrap-only
  project.yaml edits are acceptable to set `gh_pr_number`/status.
- The fake is driven in-process: the worker writes a small Python driver or
  pytest module that installs the fake (`backend.installed()` /
  `fake_github` / `fake_github_repo` fixtures) and calls the real pm functions
  (`gh_ops.*`, `pr_sync.sync_from_github`). Capture by running that driver /
  `pytest` under the CLI-recording recipe.
- For git-backed requirements, the fake's backing repo and a consumer clone
  come from `with_git_repo` / `FakeGitHubRepo.clone`; the consumer pull must
  use the real git binary (`fake_github.REAL_GIT`) to bypass pm's push-proxy
  git wrapper.

## 3. Edge cases / failure modes

- **Unknown ref**: `pr view` / `pr merge` / `pr close` / `pr ready` on a
  non-existent number or branch returns returncode 1 with a 404-shaped stderr
  (and `get_pr_status` → `None`, `is_pr_merged` → `False`).
- **Merge already-merged (merged-elsewhere)**: a second `merge_pr` exits
  non-zero ("already merged"); pm's `is_pr_merged` fallback in `pr_merge` then
  recognizes the merged state and proceeds to the pull half.
- **Real git merge conflict**: two PRs editing the same file — the first
  merges; the second `merge_pr` fails with a conflict-shaped stderr, the
  backing repo's base is left unchanged (merge aborted), and the PR state
  stays OPEN (not silently flipped to MERGED).
- **Rate-limit/5xx during sync**: a scripted 403/502 on `pr view` makes
  `sync_from_github` log a warning and skip that PR without crashing; once the
  script is exhausted the next poll succeeds.
- **`pr create --head` with no `--base`**: base defaults to the fake's default
  branch (the git_ops pm-state-sync shape).
- **`merge()`/`add_pr(state="MERGED")` helper on git-backed fake**: performs a
  real merge; an unmergeable head raises `RuntimeError` (the helper is the
  happy path; conflict *handling* is via `gh pr merge` / `simulate_conflict`).
- **Empty / unsupported argv**: empty command, unsupported `gh` subcommand, or
  unsupported `gh pr <sub>` return returncode 1 with a `fake-gh:` message.

## 4. Concurrency

- **Two actors creating PRs through one fake** → each gets a distinct PR
  number from the shared counter; no number reuse or lost registrations.
- **Two actors merging different PRs into one git-backed remote** → the
  backing repo stays consistent: non-conflicting merges both land and advance
  base; conflicting merges surface a conflict for the loser while the winner's
  state is intact (no repo corruption / dangling merge state).
- **Concurrent install/restore of the global transport** → nested
  `installed()` contexts (and concurrent install/restore) leave
  `gh_ops._GH_RUNNER` correctly restored to its prior value, with no actor
  leaking its fake into another's teardown.
- **Concurrent scripted-response consumption** → a queued response is consumed
  by at most one matching call (FIFO), not double-served.
- **Concurrent sync poll + remote-state mutation** (`sync_mid_flow` flipping
  state while a poll runs) → the poll observes a coherent state (OPEN, MERGED,
  or CLOSED) and never a half-written record.

## 5. Pass/Fail criteria

PASS when, with the fake installed, the real pm github-backend functions
behave end-to-end as in the Then clauses above: PRs are created/marked-ready/
merged/closed against the fake; `sync_from_github` updates pm PR status to
match advancing remote state; the git-backed merge-with-pull leaves a consumer
clone fast-forwardable with the merged content present; scripted failures
produce the documented gh-shaped returncode/stderr and trigger pm's matching
error handling (orphan recovery, is_pr_merged fallback, sync skip); the global
transport is always restored; and concurrent actors do not corrupt the shared
PR registry, counter, backing repo, or transport pointer.

FAIL on: a gh operation reaching the real `gh` while the fake is installed; a
created PR not parseable to a `/pull/<n>` url; sync not reflecting remote
state; a git-backed merge that does not advance base or whose consumer pull
cannot fast-forward; a conflict silently flipping state to MERGED or
corrupting the repo; scripted error shapes that don't trigger pm's handlers;
the transport not restored after a context exit/exception; or any
non-deterministic / order-dependent corruption under concurrency.

## 6. Ambiguities (resolved)

- **Subprocess-level installer for the github fake — RESOLVED by R9 (post-spec
  update).** The initial spec said the github fake was in-process only and that
  spawning `pm pr ...` subprocesses would bypass it. That is no longer true:
  commit 4589a41/ab85e48 added an out-of-process per-session installer
  (`pm fake-github config set/show/clear`) that mirrors fake-claude. `run_gh`
  consults `paths.fake_github_active()` and dispatches to the on-disk fake when
  no in-process runner is set. So both consumption shapes are now valid: (a)
  in-process function drivers (scenarios 1–6), and (b) real CLI panes against
  the session fake (scenarios 7+). The git-plumbing half of merge-with-pull is
  still pr-7d5d036's responsibility (consumer origin must point at the fake's
  `remote.git`).
- **Consumer pull vs pm's wrapped git.** `_pull_after_merge` runs git through
  pm's push-proxy wrapper, which would proxy `git fetch` away from the local
  fake remote. Resolution (per impl.md): exercise the consumer pull directly
  with `REAL_GIT` against the `FakeGitHubRepo` path; the full pm-driven pull is
  the regression runner's responsibility.
- **Match semantics for scripted responses**: space-joined argv prefix or a
  predicate; consumed FIFO. Resolved per impl.md.

No **[UNRESOLVED]** ambiguities.
