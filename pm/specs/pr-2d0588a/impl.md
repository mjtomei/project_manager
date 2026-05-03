# Implementation Spec: Tmux Popup PR Switcher and Prefix-Key PM Command Runner

## Requirements

### R1: PR Action Picker Popup (prefix+P)

Register a tmux prefix key binding (prefix+P) in `_register_tmux_bindings()` (`pm_core/cli/session.py`) that opens a `tmux display-popup` containing an action-based PR picker.

**Action-based design**: Instead of discovering existing tmux windows, the picker loads all PRs from `project.yaml` and shows available actions for the PR of the current window, based on status. This is more robust than window tracking — the pm commands themselves handle window creation/switching.

**PR discovery**: Use `store.load(state_root())` to load all PRs. The picker is **scoped to the current window's PR** only — it determines the active PR by parsing `#{window_name}` and shows only that PR's actions. From a non-PR window the picker shows a "Switch to a PR window" hint and exits.

**Available actions** (all returned for any non-terminal status; merged/closed PRs have no actions):
- start, edit, review, qa, merge (top-level)
- review-loop, qa-fresh, qa-loop, review-fresh (chord-only variants)

The action representing the *current window's phase* is marked with a `●` indicator (so sitting in the impl pane of an `in_review` PR highlights `start`, not `review`). If the action's tmux window is already open, the line is annotated with `[open]`. Live runtime status (`[loop iN]`, `[done VERDICT]`, `[idle]`/`[wait]`/`[working]`/`[gone]`) is folded into the relevant row from the shared runtime-state file. Shortcut-only actions (edit, review-loop) do not get their own list row — review-loop's `[loop iN]` badge is folded into the review row.

**Display format**: One header line (non-selectable) showing display ID, status, and title; one selectable line per action below (only `_LIST_ACTIONS` rows render):
```
  #158  (in_progress)  Add popup picker
  ● start
    review             [loop i3]
    qa
    merge
```

**Shortcut keys** (fzf `--expect`): `s`=start, `e`=edit, `d`=review, `t`=qa, `g`=merge — matching the TUI's PR-action key bindings. `q`/`Esc` quits.

**Chord modifiers** (mirror the TUI's `z`/`zz` chord behaviour): `z` is appended to fzf `--expect`. After fzf returns with `z`, the picker reads 1-2 follow-up keys in cbreak mode to resolve a `fresh`/`loop` variant — `z d` = `pr review --fresh`, `zz d` = `tui:review-loop start`, `z a` = `tui:pr qa fresh`, `zz a` = `tui:pr qa loop`. Review-loop is reachable via the chord only (it shares the `review-{display_id}` window with `pr review`, so giving it its own row would be redundant). The chord prompt clears the line on cancel.

**Command execution**: On selection:
- Direct CLI commands (start, review, merge): run `pm pr <action> <pr_id>` as subprocess
- TUI-routed commands (edit, qa, review-loop): enqueue via `trigger_tui_command()` (SIGUSR2 + per-session queue file)

**Popup lifecycle**: The popup opens, runs the picker, and closes on selection or Escape. It must not resize or reflow the underlying window/pane layout.

### R2: PM Command Runner Popup (prefix+M)

Register a tmux prefix key binding (prefix+M) in `_register_tmux_bindings()` that opens a `tmux display-popup` with an interactive prompt where the user types a pm command.

**Command execution**: The popup runs `pm _popup-cmd #{session_name}` which:
1. Displays a `pm> ` prompt
2. Accepts a pm command (e.g., `pr list`, `pr start pr-001`)
3. Executes `pm <command>` in the popup
4. On error, keeps popup open for user to read output

**Refocus behavior**: If the executed command creates a new tmux window (e.g., `pm pr start`), the invoking session should switch to that window. Since the command runs inside the popup (which is part of the same tmux session group), the existing `select_window()` mechanism will handle this automatically.

**Popup lifecycle**: Same as R1 — opens, runs, closes without affecting the TUI layout.

### R3: TUI Command Bar Enhancement (review-loop PR_ID)

Extend `handle_command_submitted` in `pm_core/tui/pr_view.py` to accept `review-loop [start] [PR_ID]`. The optional `PR_ID` selects the PR in the tree before acting; the optional `start` keyword is accepted for symmetry with the picker's command template but is now redundant since the only behavior is "start fresh".

`review_loop_ui.start_or_stop_loop` (the function that handles both `zz d` from the TUI and the popup's `review-loop` chord) was changed to **always start a fresh loop**. If a loop is already running for the same PR, its `stop_requested` flag is set (so its background thread exits at the next iteration boundary) and a new loop replaces it in `app._review_loops`. Cancelling a loop is done via TUI restart (which sweeps the in-memory loop registry on remount) or by Ctrl+C in the loop's review pane — `zz d` no longer cancels. The `stop` subcommand was dropped from the command-bar handler.

The window-switch on start is *not* performed here — the popup spinner owns it (it polls for the `review-{display_id}` window to appear and honors a `suppress_switch` flag set when the user dismisses the spinner with q/Esc). (The `strict` variant from the original PR notes was dropped in commit b9c9b54.)

Also accept `edit [PR_ID]`: selects the PR (when given) and invokes `pane_ops.edit_plan(app)` — same effect as the `e` key. Used by the picker's edit action.

Also accept `pr qa [fresh|loop] [PR_ID]`: parses an optional `fresh` or `loop` modifier and dispatches to `qa_loop_ui.fresh_start_qa` / `start_or_stop_qa_loop` / `focus_or_start_qa` accordingly. Mirrors the TUI's `t` / `z t` / `zz t` chord variants and powers the picker's `z a` / `zz a` chord.

### R4: Cross-Process Runtime State (`pm_core/runtime_state.py`)

A flock-protected JSON file per PR at `~/.pm/runtime/{pr_id}.json` records per-action live state so external processes (popup picker, post-enqueue spinner) can observe what the TUI is doing. Schema described in module docstring; valid `state` values are `queued`/`launching`/`running`/`idle`/`waiting`/`done`/`failed`. There is no explicit "gone" state — pane disappearance and stale-entry sweeps clear entries entirely; the live tmux window list is the authoritative liveness signal.

Mirrors:
- `review_loop_ui` writes on loop start, every iteration (with `iteration` and `verdict`), and completion.
- `PaneIdleTracker.register/unregister` and the pane-gone path mirror impl panes (key=pr_id → action `start`), QA scenarios (key=`qa:<pr_id>:s<N>` → action `qa`), merge windows (key=`merge:<pr_id>` → action `merge`), and non-loop review windows (key=`review:<pr_id>` → action `review`). The pane-gone path clears the entry rather than recording a state.
- `qa_loop_ui` writes `done` with `verdict` on QA loop completion (after the scenario panes are unregistered) so the picker shows `[done VERDICT]` on the qa row across invocations.
- `review_loop_ui._poll_impl_idle` polls the non-loop review pane's transcript for verdicts (`LGTM`/`NEEDS_WORK`/`INPUT_REQUIRED`) and writes `done` with `verdict` on the `review` action.  Loop iterations skip this pass; their per-iteration verdict lives under the `review-loop` action and folds onto the review row via `_SHORTCUT_FOLD_INTO`.
- `pr_view`'s `review_pr` passes `--transcript {tdir}/review-{pr_id}.jsonl` to `pm pr review` so the non-loop review session has a hook transcript symlink to poll.
- `pr_view`'s `edit` handler does not need a runtime_state mirror — the popup spinner returns early for `edit` (no window-appearance signal exists since edit opens in the current window).

`derive_action_status(pr_id, action)` cross-references the latest hook event (`hook_events.read_event(session_id)`) so callers see fresh idle/waiting transitions without requiring the TUI to record every hook event.

### R5: Stale-Entry Sweep on TUI Mount

`runtime_state.sweep_stale_states(reason)` is called from `app.on_mount` alongside the SIGUSR1/SIGUSR2 handler install. It deletes any action entry still in an in-flight state (`queued`/`launching`/`running`/`idle`/`waiting`) — those belong to a previous TUI process and aren't live anymore. Terminal states (`done` / `failed`) are preserved so post-mortem info like the last review-loop verdict survives restart.

### R6: Post-Enqueue Spinner With Fresh-Window Awareness

After enqueueing a `tui:` command, the popup runs `_wait_for_tui_command(session, tui_cmd)` which:

- Polls `runtime_state` and `tmux list-windows` until the action's target window appears.
- For "fresh" actions (`review-loop start`, `pr qa fresh`, `pr qa loop` — every iteration of these recreates the window), `_parse_tui_action` returns `fresh=True`. The spinner snapshots the original window-id at the start and waits for either a different id under the same name or a disappearance-then-reappearance, so a stale window snapshot doesn't trigger an immediate switch to the about-to-be-killed window. Spinner label switches to `rebuilding window…` during that wait.
- Animates a Braille spinner; prints a header line so the launch state is visible behind the picker.
- Polls `stdin` in cbreak mode so `q`/`Q`/`Esc` dismiss the popup immediately. Dismissal also calls `runtime_state.request_suppress_switch(pr_id, action)`; the spinner-driven `select_window` and `qa_loop_ui.focus_or_start_qa` both call `consume_suppress_switch` and skip the focus-steal in that case.
- On window appearance, the popup itself calls `tmux_mod.select_window(session, target_window)` (unless suppressed). This keeps the switch consistent with `pr review`'s direct-CLI switch and avoids the previous race in which `pr_view` switched before iteration 1 had created the window.
- Skipped entirely for `edit` (no window to wait for; current-window pane).

The spinner uses `--height=100%` on fzf so the picker contents stay visible after fzf exits and the spinner renders below them in the same popup pane.

### R7: Picker / Spinner UX

- Only `start`/`review`/`qa`/`merge` get rows in the picker (`_LIST_ACTIONS`); `edit` and `review-loop` are shortcut/chord-only. `review-loop`'s `[loop iN]` status badge is folded into the `review` row via `_SHORTCUT_FOLD_INTO`.
- Phase indicator (`●`) is computed from `_current_window_phase(window_name)` (not the PR's status), so it reflects where the user *is* — sitting in the impl window of an `in_review` PR highlights `start`.
- `q`/`Esc` inside the chord prompt returns to the fzf picker (so dismissing a chord doesn't dismiss the popup); `q`/`Esc` in fzf itself dismisses the popup. `popup_picker_cmd` ends with an explicit `raise SystemExit(0)` after dispatching so `display-popup -E` tears the overlay down promptly after the spinner switches windows.
- Picker shortcut for `qa` is `t` to mirror the TUI's `t` binding (was previously `a`).
- fzf input is fully suppressed: `--no-input` on fzf 0.59+ (detected via `_fzf_supports_no_input`) and a per-key `--bind a:ignore,b:ignore,...` over every alphanumeric not in `--expect` regardless of fzf version, so unsupported keystrokes (`j`, `k`, etc.) never echo into the popup.

### R8: zz d / z d Always Start Fresh

`zz d` (review-loop start, both TUI and picker) is no longer a toggle. Pressing it while a loop is running for the same PR supersedes the running loop: `existing.stop_requested = True` (cooperative bail) plus `tmux kill-window review-{display_id}` (forces the iteration's `_poll_for_verdict` to bail with `PaneKilledError` since that poll doesn't itself check `stop_requested`), then `_start_loop(..., superseded=True)` spawns a new loop. The supersede status message is `Fresh review loop started for ... loop=<id>`.

`z d` was previously "stop loop OR fresh done"; it now always combines both — kill any running loop (same supersede mechanism) **and** open a fresh review window via `pr_view.review_pr(app, fresh=True)`. Rationale: cancelling a loop is now done via TUI restart (which sweeps the in-memory `_review_loops` and the runtime_state file) or by Ctrl+C in the loop's review pane, not via the chord. The `stop` subcommand on the `review-loop` command-bar handler is removed.

To prevent the killed loop's terminal `verdict=KILLED` from clobbering the fresh loop's `running` entry in `runtime_state`, both `_on_iteration_from_thread` and `_on_complete_from_thread` consult `_is_active_loop(state)` — a `state.loop_id` vs. the currently-recorded `loop_id` comparison — and skip the write if they don't match.

### R9: 'done' → 'review' Internal Rename

User-facing terminology was already "Review" (binding label, picker action), but several internal symbols still said "done". Renamed:

- `pr_view.done_pr` → `pr_view.review_pr`
- `App.action_done_pr` → `App.action_review_pr` (binding `d` now references `review_pr`)
- `review_loop_ui.stop_loop_or_fresh_done` → `stop_loop_or_fresh_review`

`check_action()` lists, `tests/test_qa_pane.py`'s blocked-action set, the help screen row, and the QA-regression docs were updated. The CLI command `pm pr review` was already correctly named.

A separate improvement PR (`pr-6e23bbb`) is filed for the analogous `start` → `implement` rename, which is bigger because it touches the public `pm pr start` CLI.

## Implicit Requirements

### IR1: Picker Uses pm CLI Internally

The `tmux display-popup` runs `pm _popup-picker #{session_name} #{window_name}`. This keeps logic in Python while running in the popup shell. The picker loads project state via `store.load()` and runs pm commands via subprocess or TUI routing.

### IR2: Session Name Resolution in Popup Context

Inside a tmux popup, `#{session_name}` resolves to the session that launched the popup. The scripts use this to validate the pm session and route commands correctly.

### IR3: Socket Path Propagation

For shared sessions using `PM_TMUX_SOCKET`, the popup inherits the environment of the invoking pane. The `pm` CLI picks up `PM_TMUX_SOCKET` from the environment.

### IR4: TUI Routing for QA and Review Loops

QA (`pr qa`) and review loops require the TUI's Textual app context.
Routing happens via a SIGUSR2 + per-session command-queue file IPC,
following the SIGUSR1 reload pattern added in commit 9c30b38:

- TUI on mount: writes `~/.pm/tui-{session}.cmd-queue` (initially empty)
  and registers a SIGUSR2 handler that drains the queue file line-by-line
  and dispatches each line through the same path as
  `CommandSubmitted` (`handle_command_submitted`).
- External callers (`trigger_tui_command(session, cmd)` in
  `pm_core/cli/helpers.py`): append the command line to the queue file
  under a file lock, then `os.kill(tui_pid, SIGUSR2)`.
- The queue model means the picker (and any future caller) can enqueue
  multiple commands at once and they run in order without needing
  `tmux send-keys` or focus-dependent timing.

This replaces the earlier brittle `send-keys '/' → sleep → -l "<cmd>"
→ Enter` approach where literal text could leak to whichever widget
held focus before Textual finished focusing the command bar (observed
as `r`/`e` etc. firing as TUI key bindings — refresh, edit-pane —
instead of being typed into the command bar).

### IR5: fzf Dependency

- Use fzf if available for rich fuzzy-find interaction
- Fall back to a simple numbered-list selector if fzf is not present
- Show a one-line hint when using the fallback

### IR6: Bindings Are Global

`_register_tmux_bindings()` registers bindings globally. The popup scripts gracefully handle being invoked from non-pm sessions (show "Not a pm session" and exit).

## Ambiguities

### A1: Exact Key Bindings

**Resolution**: `prefix+P` for the PR action picker (mnemonic: PR/Pick), `prefix+M` for the command runner (mnemonic: coMmand). Avoids `prefix+C` which conflicts with tmux's default `new-window`.

### A2: Popup Size

**Resolution**: PR picker: 80 columns wide, 80% height. Command runner: 80 columns wide, 50% height.

### A3: Current Window Detection for Default PR

**Resolution**: Parse `#{window_name}` of the invoking window. Strip prefixes (`review-`, `qa-`, `merge-`) to get the base PR display ID.

### A4: Command Runner Output Visibility

**Resolution**: On error (non-zero exit), keep popup open with "Press Enter to close..." prompt. On success, popup closes immediately.

## Edge Cases

### E1: No Actionable PRs

If all PRs are merged/closed, show "No PRs with available actions." and exit.

### E2: Non-PM Session Invocation

Show "Not a pm session." and exit.

### E3: TUI Pane Not Found for Routed Commands

If QA or review-loop is selected but the TUI pane can't be found, show an error and keep the popup open.

### E4: display-popup and Tmux Version

`tmux display-popup` requires tmux 3.2+. Should gracefully fail on older tmux.

## Implementation Plan

### Files Modified

1. **`pm_core/cli/session.py`** — New popup commands and action logic:
   - `_PR_ACTIONS` dict mapping status → available actions
   - `_actions_for_status()` — lookup actions for a status
   - `_current_window_pr_id()` — extract PR display ID from window name
   - `_build_picker_lines()` — format PR+action lines for picker
   - `_run_picker_command()` — execute direct CLI or TUI-routed command
   - `popup_picker_cmd` — `pm _popup-picker` CLI command
   - `popup_cmd_cmd` — `pm _popup-cmd` CLI command
   - Two `bind-key` calls in `_register_tmux_bindings()`

2. **`pm_core/tui/pr_view.py`** — Enhanced `handle_command_submitted()`:
   - `review-loop [start|stop] [PR_ID]`: select PR in tree, then start (idempotent) or stop. The window switch is *not* performed here — the popup spinner (`_wait_for_tui_command`) owns the switch so it can honor the `suppress_switch` flag set when the user dismisses the spinner with q/Esc.
   - `edit [PR_ID]`: select PR (if given) and run `pane_ops.edit_plan(app)`. No runtime_state write needed — the popup spinner (`_wait_for_tui_command`) returns early for `action == "edit"`.
   - `pr qa [fresh|loop] [PR_ID]`: route to `qa_loop_ui.focus_or_start_qa` (default), `fresh_start_qa` (`fresh`), or `start_or_stop_qa_loop` (`loop`). Mirrors the TUI `t`/`z t`/`zz t` chord variants; used by the picker's `z a` / `zz a` chord.

3. **`tests/test_popup_picker.py`** — Tests for action-based picker logic

### Architecture

```
prefix+P → display-popup 'pm _popup-picker $(tmux display-message ...)'
                ↓
         Load PRs from project.yaml
                ↓
         Build action lines per PR status
                ↓
         fzf (or fallback numbered list)
                ↓
         On selection:
           ├─ Direct: pm pr start/review/merge PR_ID (subprocess)
           └─ TUI:    trigger_tui_command(session, "pr qa PR_ID")
                      ├─ append cmd to ~/.pm/tui-{session}.cmd-queue
                      └─ os.kill(tui_pid, SIGUSR2)
                           ↓
                    TUI SIGUSR2 handler drains queue → dispatches
                    each line through handle_command_submitted

prefix+M → display-popup 'pm _popup-cmd #{session_name}'
                ↓
         pm> prompt → user types command → subprocess → exit
```
