# Spec: GitHub backend mock for regression tests (pr-9603d04)

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
