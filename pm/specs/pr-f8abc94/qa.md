# QA Spec: TUI command for PR resource cleanup (pr-f8abc94)

## Requirements

The PR adds a single cleanup primitive (`pm_core/pr_cleanup.py::cleanup_pr_resources`)
exposed three ways:

1. **CLI**: `pm pr cleanup <pr_id> --resources` — prints summary and refreshes TUI.
   - `--resources` without a `pr_id` exits non-zero with a usage error.
   - Unknown `pr_id` exits non-zero with "PR not found".
   - Existing workdir cleanup behavior is unchanged when `--resources` is omitted.
2. **TUI dedicated key `Y`** — opens `ConfirmCleanupScreen` modal listing what will
   be removed, then runs cleanup on confirm. `n`/`Esc` cancels and logs "Cleanup cancelled".
3. **TUI prefix `y`** — enters y-mode (logs `y … (cleanup-then: s=start d=review t=qa)`),
   2-second auto-cancel timer, then dispatches:
   - `y s` → cleanup, then start PR (`start_pr`)
   - `y d` → cleanup, then review (`done_pr`)
   - `y t` → cleanup, then QA (`focus_or_start_qa`)
   - any other key cancels with "y cancelled"
   - `Esc` while in y-mode also cancels.

The cleanup primitive itself:
- Kills tmux windows via `kill_pr_windows(session, pr)` (impl, review-, merge-, qa-, qa-…-sN).
- Removes Docker containers matching `pm-qa-{pr_id}-` and `pm-{session_tag}-qa-{pr_id}-`
  via the new `container.cleanup_pr_containers`.
- Removes pane registry entries for the PR's window names via the new
  `pane_registry.unregister_windows`.
- Best-effort `push_proxy.stop_push_proxy()` for each removed container.
- Returns a summary dict; `format_summary` produces a human readable string.
- Safe to call when nothing exists ("nothing to clean").

## Setup

Use the `tui-manual-test.md` instruction to set up a throwaway pm project and tmux
session. Add 2–3 PRs so a non-empty target exists.

## Edge Cases & Failure Modes

- Cleanup invoked when **nothing exists** for the PR — should print "nothing to clean"
  with no errors.
- `Y` modal cancellation paths (`n`, `Esc`).
- y-prefix auto-cancel after 2s (no second key) — log clears.
- y-prefix followed by an invalid key — logs cancellation.
- y-prefix while a `z` count is buffered — should still enter y-mode cleanly.
- `Y` with no PR selected (empty tree) — logs "No PR selected".
- CLI `--resources` without pr_id; with a bogus pr_id.
- Cleanup runs on a PR that has only **some** of: tmux window, container, registry
  entry — summary lists only the categories actually cleaned.
- Verifying that **non-target** PR resources are untouched (PR isolation).

## Pass/Fail Criteria

PASS:
- All three entry points (CLI flag, `Y` key, `y` prefix) invoke the same cleanup and
  the summary reflects what was actually removed.
- Confirmation modal appears for `Y` and not for `y` prefix.
- Idempotent: a second cleanup on the same PR reports "nothing to clean".
- y-prefix follow-up action runs after the cleanup logs.
- No tracebacks or unexpected log errors.
- Other PRs' tmux windows / containers are untouched.

FAIL:
- Cleanup tears down resources for the wrong PR.
- `Y` skips the modal, or `y` prefix presents a modal.
- Crashes on empty/missing state.
- y-mode never auto-cancels and locks input.
- CLI `--resources` deletes the workdir (it must not — that path is the existing default).

## Ambiguities

None unresolved. Implementation details (key bindings, modal style) are spelled
out in the impl spec and the diff agrees.

## Mocks

No mocks defined. Tests run against a real throwaway tmux session and the local
docker (or absent docker — cleanup_pr_containers tolerates a non-zero `ps` exit).
For scenarios where we just want to verify code paths without resources existing,
the "nothing to clean" path is itself a real test of the no-op behavior.
