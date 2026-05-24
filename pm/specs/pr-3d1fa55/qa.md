# QA Spec: pr-3d1fa55 — terminal-status PRs keep their tmux windows when finalized outside pm merge flow

## Background

A PR that reaches a terminal status (`merged` or `closed`) by any path
*other than* pm's interactive merge flow used to keep all of its tmux windows
open — the impl window (`<display_id>`), `review-<display_id>`,
`merge-<display_id>`, the QA loop window `qa-<display_id>`, and every
`qa-<display_id>-sN` scenario window. Window teardown was only a side effect
of the `pm pr merge` / picker merge action.

The fix makes window teardown a function of the PR's *status*: a self-healing
sweep (`_reclaim_terminal_pr_windows`) runs on every TUI reload/sync
(`do_normal_sync`, the periodic + manual `r` path) and unconditionally at the
end of `startup_github_sync`. For any PR whose status is terminal and whose
windows still exist, it calls `cleanup_pr_resources` — which tears down the
windows plus QA containers, push-proxy sockets, pane-registry entries, and the
per-PR runtime-state file. PRs that are mid merge-propagation
(`app._merge_propagation_phase`) are skipped so an active merge-resolve window
is not aborted.

`display_id` is `#<gh_number>` for GitHub-backed PRs, else the local `pr-<id>`.
For a `local` backend test project it is the `pr-<id>`.

## Requirements

### R1 — Merged-via-edit reclaim (the headline bug)
- **Given** a running pm TUI for a project with a PR that has live windows
  (impl + review/QA windows from having been worked on), and the PR's status
  is flipped to `merged` via `pm pr edit --status merged` (so the merged
  status is loaded into the TUI's in-memory data before any transition can be
  observed — the "masked transition").
- **When** the TUI performs its next reload/sync (periodic background sync or
  the user pressing `r`).
- **Then** all of that PR's tmux windows — impl, `review-`, `merge-`, `qa-`,
  and every `qa-…-sN` scenario window — are gone, and no orphaned windows
  remain for that PR.

### R2 — Closed-via-edit reclaim
- **Given** a running pm TUI with a PR that has live windows, status flipped to
  `closed` via `pm pr edit --status closed`.
- **When** the TUI reloads/syncs.
- **Then** the PR's windows are reclaimed (the transition path never handled
  `closed` before this fix).

### R3 — Startup-sync reclaim for GitHub-invisible terminal PRs
- **Given** a project where a PR was content-merged with diverged SHAs and
  marked `merged` (invisible to GitHub — sync reports no updates), its windows
  still present, and the user (re)starts the TUI.
- **When** the startup GitHub sync runs and reports "up to date" / no updates.
- **Then** the merged PR's windows are still reclaimed on that startup reload,
  not deferred.

### R4 — Active/non-terminal PRs unaffected
- **Given** a running pm TUI with a non-terminal PR (`in_progress`,
  `in_review`, `qa`, `pending`) that has live windows.
- **When** the TUI reloads/syncs (repeatedly).
- **Then** that PR's windows remain open and untouched.

### R5 — Full resource reclaim, not just windows
- **Given** a terminal-status PR that had not only windows but other live
  resources (QA container, push-proxy socket, pane-registry entries, runtime
  state).
- **When** the sweep reclaims it on reload/sync.
- **Then** the windows are closed AND the associated containers/sockets/
  registry entries/runtime-state are cleaned up (parity with the merge-flow
  teardown).

### R6 — Idempotent / self-healing across repeated syncs
- **Given** a terminal-status PR whose windows have already been reclaimed.
- **When** subsequent reloads/syncs run.
- **Then** no error is raised and no redundant teardown work occurs (the sweep
  is a cheap no-op once the windows are gone).

## Setup

- Use the **TUI Manual Testing** instruction to stand up a throwaway `local`
  backend project, confirm `pm which` points at the editable clone (not
  `/opt/pm-src`), and start a pm session.
- Create one or more PRs via `pm pr add`. To get realistic live windows
  beyond the impl window, drive the review and/or QA loops with the bundled
  **fake-claude** stand-in (config a deterministic verdict) so `review-` and
  `qa-`/`qa-…-sN` windows actually exist. The impl window alone is enough to
  demonstrate the core reclaim; the broader window set strengthens R1/R5.
- Bootstrap-only project.yaml edits are allowed to seed initial PR status; all
  status transitions under test must go through `pm pr edit` / TUI surfaces.
- Drive and observe the TUI from *outside* via `pm tui send` / `pm tui view`
  and `tmux list-windows -t <session>`; do not attach interactively.

## Edge Cases

- **Terminal PR with no live windows** — sweep is a cheap no-op; no error.
- **Mid merge-propagation guard** — a PR flipped to `merged` while pm's
  two-step merge propagation is still resolving conflicts in its live `merge-`
  window must NOT have that window torn down by the sweep (it is in
  `app._merge_propagation_phase`). Reclaimed normally once propagation
  completes or on the next TUI restart. (Hard to drive purely from the user
  surface without inducing a real merge conflict; the diff carries a unit
  test, `test_merged_pr_mid_propagation_is_not_reclaimed`.)
- **No tmux session / `_session_name` unset** — guarded no-op.
- **`tmux list_windows` failure** — logged; sweep returns without crashing the
  sync loop.
- **Concurrent external edit + manual refresh** — a PR marked terminal from a
  separate process while a periodic background sync and a manual `r` refresh
  race must end with the windows reclaimed exactly once and no crash.

## Pass/Fail Criteria

- **PASS**: After a terminal status is reached by any path (edit, content-merge
  /startup-invisible, sync-detected), the next TUI reload/sync leaves zero
  windows for that PR (impl/review/merge/qa/qa-sN) and cleans associated
  resources; non-terminal PRs keep their windows; repeated syncs neither error
  nor re-tear-down; the diff's regression tests pass.
- **FAIL**: Any orphaned window remains for a terminal PR after a
  reload/sync; an active PR loses its windows; the sweep crashes the sync loop;
  associated resources (containers/sockets/registry/runtime-state) are left
  behind; or a mid-propagation merge window is torn down.

## Ambiguities (resolved)

- **How to realistically create the multiple window types as a user?** Resolved
  by driving the impl/review/QA loops via fake-claude per the TUI instruction,
  rather than fabricating tmux windows by hand. The impl window is created by
  starting the PR; `review-`/`qa-` windows by running the corresponding loops.
- **Which reload path to assert against?** Both the periodic/manual
  `do_normal_sync` path (R1/R2/R4) and the `startup_github_sync` path (R3) are
  in scope; they are distinct chokepoints in the diff.
- **Mid-propagation guard driveability.** Resolved as primarily a code-path
  concern covered by the diff's unit test; QA exercises it best-effort via the
  user surface but treats the active-PR-unaffected check (R4) as the
  load-bearing user-observable guard.
