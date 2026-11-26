# QA Spec — pr-f5b7eef: dedicated `pr list` home tmux window + pluggable provider seam

## 1. Requirements to Exercise

### R1. `pm session home` command
- Inside a pm tmux session, `pm session home` creates a window named `pm-home` running `pm pr list -t --open`-equivalent content.
- Subsequent invocations refresh and re-focus (do not duplicate the window).
- Outside a pm tmux session, errors with `"Not inside a pm tmux session."` and exits non-zero.
- After the command, the calling client's active window is `pm-home`.

### R2. Home window content (pr-list provider)
- Header: `pm pr list -t --open    (updated HH:MM:SS)`.
- Lists only non-closed/non-merged PRs.
- Sorted by `updated_at`/`created_at` desc.
- Each line uses the same `format_pr_line` as `pm pr list -t --open` (same icons, deps, machine, active marker `*`, timestamp `[YYYY-MM-DD HH:MM]`).
- Re-renders ~every 5s automatically.
- A `pm session home` call wakes the loop early (sentinel touch).
- Loop survives transient `store.load` failures (returns an error line, keeps looping).

### R3. Auto-park on kill
For each kill site, the calling client should land on `pm-home` (not on tmux's last-window) after the kill:
- `pm pr start --fresh <pr-id>` when an impl window already exists → park then recreate. Final focus: new impl window (post-recreate switch).
- `pm pr merge` cleanup (kill_pr_windows kills impl/review/merge/qa/qa-scenario) → final focus: `pm-home`.
- Watcher recreate (`pm pr review-loop` cycling) → brief `pm-home`, then onto new watcher.
- QA stale-window cleanup (`_cleanup_stale_scenario_windows`) → final focus: `pm-home`.
- TUI review-loop supersede (`z d`/`zz d`) → brief `pm-home`, then onto fresh review.
- Post-merge merge-window cleanup → final focus: `pm-home`.

### R4. Cross-session park
With grouped sessions (`base` + `base~N`), if session B is the active viewer of a window killed by session A's action, B is also parked on `pm-home`.

### R5. Setting fallback
Setting `home-window-provider` defaults to `pr-list`. An unknown value prints a stderr warning and falls back to `pr-list`.

### R6. Idempotency / safety
- `ensure_window` returns the existing `pm-home` window without recreating if already present.
- Outside tmux, `park_if_on` and `ensure_home_window` are no-ops.
- The shared `format_pr_line` produces identical output between `pm pr list -t --open` and the home window body for the same PR.

## 2. Setup

Use `tui-manual-test.md` instruction. Override `PYTHONPATH` to the editable clone and confirm with `pm which`. Create a throwaway project with several PRs of varied statuses (some open: pending/in_progress/in_review/qa; some closed/merged) so list filtering and sort order are verifiable.

## 3. Edge Cases

- Running `pm session home` outside a pm tmux session → clean error, exit 1.
- Two consecutive `pm session home` invocations → still exactly one `pm-home` window.
- Setting `home-window-provider` to `does-not-exist` (write `~/.pm/settings/home-window-provider`) → stderr warning + fallback works.
- Killing a window the user is *not* on → no spurious focus changes for clients on other windows.
- `pm session home` while no PRs exist → renders header + "No open PRs.".

## 4. Pass/Fail Criteria

PASS:
- `pm-home` window appears with rendered PR list and `(updated HH:MM:SS)` header.
- After `pm pr merge`-style cleanup or `--fresh` kill where the client was on the doomed window, the client is on `pm-home` (or on the recreated successor when the path recreates).
- Format output for a given PR matches between `pm pr list -t --open` stdout and the home-window body line.
- Unknown setting prints fallback warning on stderr and works.

FAIL:
- After killing the focused window, client lands on a previous-window other than `pm-home`.
- `pm-home` window duplicated on repeat invocations.
- Loop dies on a transient store error.
- Format divergence between `pm pr list` and home window for same PR row.

## 5. Ambiguities

None unresolved. Resolved choices come from impl.md (cross-session park scope, sentinel-based refresh, pre-kill park).

## 6. Mocks

No external services need mocking. tmux, pm CLI, and the local store are exercised live in the throwaway project. `pm pr merge` requires a git remote / GitHub: scenarios should *simulate* the merge cleanup path by directly invoking the kill-window code path through the available CLI surfaces (`pm pr start --fresh`, watcher restart, or by manually calling `pm-core` from a Python REPL inside the tmux session) rather than by performing a real GitHub merge. Where a path can't be exercised via CLI alone (e.g. `kill_pr_windows`), use `python -c "from pm_core.cli.helpers import kill_pr_windows; ..."` against the throwaway project.
