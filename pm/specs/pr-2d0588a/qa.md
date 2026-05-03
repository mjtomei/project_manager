# QA Spec: Tmux Popup PR Switcher and Prefix-Key PM Command Runner

## Requirements (key behaviors to verify)

### R1 — prefix+P PR action picker
- Opens a tmux display-popup with an fzf-style picker scoped to the PR of the current window.
- One non-selectable PR header line plus one row per `_LIST_ACTIONS` action: `start`, `review`, `qa`, `merge`. `edit` and `review-loop` are shortcut-only (no rows).
- Phase indicator `●` highlights the row matching `_current_window_phase(window_name)`:
  - bare PR window (display-id only) → `start`
  - `review-#NN` → `review`
  - `qa-#NN` → `qa`
  - `merge-#NN` → `merge`
  - From a non-PR window the picker shows a "Switch to a PR window" hint and exits.
- Top-level shortcuts (single key, fzf `--expect`): `s`=start, `e`=edit, `d`=review, `t`=qa, `g`=merge.
- Chord prefixes `z` / `zz`:
  - `z d` = `pr review --fresh`
  - `zz d` = review-loop start (always supersedes any running loop)
  - `z t` = `pr qa fresh`
  - `zz t` = `pr qa loop`
  - `q`/`Esc` inside the chord prompt returns to fzf picker; `q`/`Esc` in fzf dismisses popup.
- Open windows annotated `[open]`. Runtime-state badges folded onto rows: `[loop iN]` (folded onto `review`), `[done VERDICT]`, `[idle]`/`[wait]`/`[working]`/`[gone]`.
- fzf UX: filter input disabled (no `> ` prompt; typing letters does not filter); two-line header with `--header-first`; `--height=100%` so picker stays visible behind spinner.
- Falls back to a numbered-list selector when fzf isn't installed, with a one-line hint.

### R2 — prefix+M command runner popup
- Opens display-popup with a `pm> ` prompt; user types a pm command, it runs inside the popup.
- If command opens a window (e.g. `pr start`), invoking session refocuses to it.
- On non-zero exit, popup stays open ("Press Enter to close..."); on success, closes immediately.
- Popup must not resize the surrounding TUI panes/window layout.

### R3 — TUI command bar enhancements
- `review-loop [start] [PR_ID]` — always starts a fresh loop (no toggle/cancel). If a loop is running, sets old loop's `stop_requested`, shows "Restarting review loop", launches new loop. The window-switch is not done here (popup spinner owns it for popup-routed; CLI does it for direct).
- `edit [PR_ID]` — selects PR, opens edit pane. Same as TUI `e` key.
- `pr qa [fresh|loop] [PR_ID]` — routes to `focus_or_start_qa` / `fresh_start_qa` / `start_or_stop_qa_loop`.

### R4 — Cross-process runtime state
- `~/.pm/runtime/{pr_id}.json` (flock) records action state. Picker reads it for badges.
- `review_loop_ui` writes on start, every iteration (with iteration N + verdict), completion.
- `PaneIdleTracker` mirrors impl (`start`) and qa (`qa`) state from hook events.
- `pr_view` `edit` writes brief `done` so spinner exits without polling.

### R5 — Stale-entry sweep on TUI mount
- `sweep_stale_states` runs in `app.on_mount`. Clears in-flight states from prior TUI processes; preserves terminal `done`/`failed`. Verify: start review-loop → see `[loop iN]` in picker → restart TUI → loop badge gone, `[done VERDICT]` survives.

### R6 — Post-enqueue spinner
- After a `tui:`-routed selection, popup shows Braille spinner with action label and state (queued → running → ...).
- Header line printed: `── starting fresh: ACTION for PR ──` for fresh actions.
- Fresh-window-aware: when target window already exists, spinner shows `rebuilding window…` and waits for window-id change (kill+recreate) before switching.
- `q`/`Q`/`Esc` dismisses popup overlay immediately. The queued command still runs to completion in the TUI, but the would-be window switch is suppressed for that action only (action-scoped flag via `request_suppress_switch` / `consume_suppress_switch`).
- `select_window` is performed by the popup itself (not the TUI), unless suppressed.
- Skipped entirely for `edit`.

### R7 — SIGUSR2 + queue-file IPC
- TUI on mount creates `~/.pm/tui-{session}.cmd-queue` and registers SIGUSR2 handler.
- `trigger_tui_command(session, cmd)` appends to the queue under flock and `os.kill(tui_pid, SIGUSR2)`.
- Command runs even when command bar isn't focused or another widget has focus.
- Multiple rapid enqueues from concurrent popup invocations all run in order.

### R8 — Session resolution & non-pm guard
- "Not a pm session" detection uses pane-registry file (display-popup doesn't propagate `PM_TMUX_SOCKET` reliably). Verify works in non-shared, `--global`, `--group` shared sessions; shows "Not a pm session" from a non-pm tmux session.
- Inside the popup, `tmux display-message -p '#{session_name}'` and `'#{window_name}'` are evaluated from the popup shell (not via display-popup arg substitution). pm log shows resolved values in popup-picker invocation log line.

## Setup
- Use `tui-manual-test.md` setup (venv install, throwaway project, `pm session`).
- Most scenarios drive interaction via `tmux send-keys -t <session>:...` from outside the session and inspect with `pm tui view` and `tmux capture-pane`.
- Use `tmux send-keys -t <session> 'C-b' P` to deliver prefix+P from the test runner.
- Inspect `~/.pm/runtime/<pr_id>.json`, `~/.pm/tui-<session>.cmd-queue`, and `pm log` for IPC and state verification.

## Edge Cases / Failure Modes
- All PRs merged/closed → "No PRs with available actions" / non-PR window hint.
- tmux <3.2 → display-popup fails gracefully (don't blow up TUI).
- Popup invoked from non-pm tmux session → "Not a pm session".
- Concurrent enqueues from two simultaneous popup invocations → queue preserves order, all execute.
- Spinner dismissed mid-run → action completes; window switch suppressed for that action only; subsequent unrelated picker invocations still switch normally.
- Stale review window present when `zz d` re-issued → spinner waits ("rebuilding window…") for new window-id; doesn't switch to about-to-be-killed window.
- TUI restart while loop running → loop dies, picker badge cleared, terminal `[done VERDICT]` preserved.
- review-loop "start" first ever may be a no-op (window created lazily by iteration 1); re-running afterwards focuses correctly.

## Pass/Fail Criteria
- **Pass**: Each requirement above demonstrably works under manual inspection (popup opens, correct rows/shortcuts/chords, badges accurate, IPC delivers commands, spinner behaves, dismissal suppresses switch action-scoped, non-pm guard fires, no TUI pane resize).
- **Fail**: Any of: popup resizes TUI; wrong phase indicator; chord doesn't route correctly; queued command doesn't run; multiple enqueues lose ordering; spinner switches to about-to-be-killed window for fresh actions; dismissal fails to suppress switch (or suppresses unrelated future switches); stale runtime entries persist across TUI restart; non-pm-session guard misfires/fails to fire.

## Ambiguities
None unresolved. Note: earlier QA notes reference an `l` shortcut and `prefix+C`; the current design uses chord `zz d` for review-loop and `prefix+M` for command runner, and `t`/`z t`/`zz t` for QA variants (changed from `a`).

## Mocks
No mocks needed. This PR is tmux/IPC integration; tests must run real tmux popups, real fzf, real signal delivery, and real runtime-state files. Claude sessions launched by `pr start`/`qa`/`review` should NOT be exercised end-to-end — scenarios verify routing/launch (window appears, queue drained, runtime_state updated) rather than waiting on Claude. If a scenario needs a "running review-loop" fixture, write the runtime-state JSON directly with `set_action_state(pr_id, "review", "running", iteration=N)` rather than launching a real loop.
