# Spec: GitHub backend mock for regression tests (pr-9603d04)

## Description correction (2026-05-17)

The original task description treated the fake as a pure GitHub-API
simulator. That was an oversight: a regression test that runs `pm pr merge`
on the github backend exercises **two** halves —

1. the GitHub-API call (`gh pr merge`), and
2. the git plumbing that follows (`git fetch` / `git merge --ff-only` in the
   repo dir, via `_pull_after_merge`).

A pure in-memory fake covers (1) but leaves (2) needing a separately-mocked
git repo, so the merge-with-pull / post-merge-pull scenarios cannot run
end-to-end against the fake alone.

**Corrected requirement:** the fake must be backed by a **real (local) git
repo** so that the *git-affecting* `gh` operations produce real git state —
`gh pr create` ⇒ a branch exists; `gh pr merge` ⇒ the branch is actually
merged into base in the backing repo, so a downstream `git fetch` /
`git merge --ff-only` succeeds.

**Still pure-metadata (explicitly NOT git-backed for now):** operations that
do not affect git history — PR comments (`gh pr comment`), and any repo
admin / settings surface. These remain in-memory stubs; making them real is
deferred. Only the git-affecting operations need a working repo.

This is captured as **R8** below.

## Design probe

The "github backend" is not a single class. The surface that regression tests
need to drive is the set of `gh` CLI invocations:

- `pm_core/gh_ops.py` — all calls funnel through `run_gh()`: `pr create`,
  `pr view`, `pr list`, `pr ready`, `auth status`.
- `pm_core/pr_sync.py:sync_from_github` — direct `subprocess.run(["gh", "pr",
  "view", <num>, "--json", "state,isDraft,mergedAt"])`. This is *the* status
  polling path.
- `pm_core/cli/pr.py` — direct `subprocess.run` for `gh pr merge` (line ~1839)
  and `gh pr close` (line ~2624).
- `pm_core/git_ops.py:244` — `gh pr create` for *pm-state-sync* commits. This
  is **out of scope** ("invocations elsewhere that aren't on the backend hot
  path").

`backend.py:GitHubBackend` only exposes `is_merged` / `pr_instructions`; a
`Backend`-subclass fake would cover almost none of the path. Therefore a
**transport-level fake** is far less invasive: intercept `gh` at the
`run_gh()` chokepoint. The three direct `subprocess.run(["gh", ...])` calls on
the hot path are re-routed through `gh_ops.run_gh()` so a single chokepoint
covers everything. This is also a small code-quality consolidation.

## 1. Requirements (grounded)

- **R1 FakeGitHubBackend** (`pm_core/fake_github.py`): holds simulated remote
  state (a registry of fake PRs keyed by number) and interprets `gh` argv into
  operations on that state, returning `subprocess.CompletedProcess` objects.
  Covers `pr create [--draft]`, `pr view`, `pr list`, `pr ready`, `pr merge`,
  `pr close`, `auth status`.
- **R2 Injectable runner in `gh_ops`**: a module-level pluggable `gh` runner
  with `set_gh_runner()` and a `gh_runner()` context manager. `run_gh()`
  delegates to it when installed (and skips `_check_gh()`), else runs the real
  subprocess. Add a `timeout` param to `run_gh()` (preserves the 30s timeout
  `sync_from_github` currently uses).
- **R3 Route hot-path direct calls through `run_gh()`**: `sync_from_github`'s
  `pr view`, `cli/pr.py`'s `pr merge` and `pr close`. Behavior preserved
  (returncode/stdout/stderr, cwd, check=False, timeout).
- **R4 Scriptable responses**: `queue_response(match, returncode, stdout,
  stderr)` injects canned results consumed FIFO when a command matches —
  composing success / 4xx / 5xx / rate-limit / conflict / merged-elsewhere
  flows. Canned-response helpers for the common error shapes.
- **R5 Sync hook**: tests advance simulated remote state by mutating
  `backend.prs[n]` (e.g. `.state = "MERGED"`) then calling `sync_from_github`
  / `sync_prs`, which poll through the fake.
- **R6 Scenario helpers**: `create_draft_on_start`, `upgrade_on_done`,
  `merge_with_pull`, `sync_mid_flow`.
- **R7 Test fixture**: a `fake_github` pytest fixture (in `tests/conftest.py`)
  that installs the fake for the duration of a test, mirroring how a
  FakeClaudeSession fixture would swap the Claude session.
- **R8 Git-backed fake** (see *Description correction* above): the fake owns
  a real local git repo acting as the "remote". Git-affecting `gh`
  operations mutate it for real:
  - `gh pr create [--head <branch>]` ⇒ the head branch must exist in the
    backing repo (created/registered if absent).
  - `gh pr merge <ref>` ⇒ actually merge the head branch into the PR's base
    branch in the backing repo (so a clone's `git fetch` + `git merge
    --ff-only origin/<base>` fast-forwards cleanly).
  - `gh pr view` / `pr list` state stays consistent with the repo.
  Pure-metadata operations (`gh pr comment`, repo admin) are **not**
  git-backed — they remain in-memory stubs; promoting them is deferred.
  The fixture must provide both the backing repo and a clone/workdir so
  scenario tests can run the full merge-with-pull path without hand-mocking
  `git_ops`.

## 2. Implicit requirements

- The fake result object must be a real `subprocess.CompletedProcess` so
  existing callers (`.returncode`, `.stdout`, `.stderr`, `json.loads`) work
  unchanged.
- `pr view` accepts both a branch name and a PR number as the ref — gh_ops
  uses branch, sync_from_github uses number.
- `pr view --json` must emit exactly the requested fields (callers parse a
  fixed set: `state,url,number,title,mergedAt` and `state,isDraft,mergedAt`).
- `create_draft_pr` parses the PR number from the returned URL — the fake URL
  must end in `/pull/<number>`.
- Installing the fake must restore the previous runner on exit even on error.
- `_check_gh()` must be skipped while the fake is installed (no real `gh`).

## 3. Ambiguities (resolved)

- *Full Backend reimpl vs transport fake* → transport fake (see probe).
- *Match semantics for `queue_response`* → match against a space-joined prefix
  of the `gh` argv (e.g. `"pr merge"`), or a callable predicate. Consumed once.
- *git_ops `gh pr create`* → left alone; out of scope, not hot path.
- *gh CLI exact JSON shape* → fake emits the documented field names; tests
  only assert on fields pm actually reads.

No **[UNRESOLVED]** ambiguities.

## 4. Edge cases

- `queue_response` with returncode!=0 + `check=True` → `run_gh` raises
  `CalledProcessError`, same as the real path.
- `pr view` on an unknown ref → returncode 1, empty stdout (matches gh).
- `pr merge` on an already-merged PR → returncode 1 (gh behavior); the
  `is_pr_merged` fallback in `cli/pr.py` then succeeds.
- `pr ready` on a non-draft PR → still returncode 0 (idempotent).
- Concurrent runner installs → context manager nests via save/restore.
- **Git-backed (R8):** `gh pr merge` on a branch that conflicts with base in
  the backing repo → the real git merge fails; the fake should surface a
  conflict-shaped failure (consistent with `simulate_conflict`) rather than
  silently flipping state to MERGED.
- **Git-backed (R8):** `gh pr merge` on an already-merged branch → branch is
  already an ancestor of base; treat as merged-elsewhere (returncode 1, the
  `is_pr_merged` fallback then succeeds).

## 5. Implementation status

Initial commit landed the **pure-metadata transport fake** (R1–R7). R8
(git-backed repo) is the description correction and is **not yet
implemented** — tracked as the next step for this PR. Comment/admin
operations stay metadata-only by design.
