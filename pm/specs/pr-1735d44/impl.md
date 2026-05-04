# pr-1735d44 — Consolidate window refocus

## Goal
Replace the two refocus paths (`tmux.select_window` and
`tmux.switch_sessions_to_window`) with a single `tmux.focus_window` that
follows the correct refocus rule (clarified in conversation 2026-05-04):

> Refocus must switch only:
>   (a) the attached tmux client that ran the command, OR
>   (b) sessions that were already viewing a window owned by a loop that
>       is being killed and recreated (review / watcher / qa).
>
> Sessions that happen to be on the same window for unrelated reasons
> are NOT dragged along just because they share focus with the origin.
> A TUI respawn must never force a focus change on any client.

## Requirements (grounded)

R1. **Add `tmux.focus_window(base, window, origin_session=None,
    co_viewers=None)`** in `pm_core/tmux.py`.
    - Default behaviour: switch *only* `origin_session`.
    - `origin_session` resolution: explicit arg → `$PM_ORIGIN_SESSION`
      env (set by the TUI when spawning subprocesses) →
      `most_recent_client_session(base)` (for in-process TUI callers
      like the `wf` chord and `_focus_plans_window`, which run in the
      single TUI process and have no subprocess env to thread) →
      `current_or_base_session(base)` for legacy non-TUI callers.
    - When `co_viewers` is provided, it *replaces* the origin set
      entirely. Used only by loop kill-and-recreate flows that
      snapshot watchers of the old window before killing it.
    - Window resolution accepts `@id`, numeric index, or name.

R2. **Capture the originating tmux client at TUI command launch** to
    fix the bug from PR notes 1 & 3: with multiple grouped sessions
    attached to a single TUI, the keystroke arrives in the same TUI
    process regardless of which client typed it. `$TMUX_PANE` in the
    TUI process is fixed at launch and identifies the *host* session,
    not the typing client.
    - New helper `tmux.most_recent_client_session(base)` queries
      `list-clients -F '#{client_activity} #{client_session}'`,
      filters to clients in the `base` group (`base` or `base~*`),
      and returns the session with the highest activity timestamp.
      That's the client whose input arrived most recently — i.e.
      the one that just pressed the key.
    - `pm_core/tui/pr_view.py:_origin_env(app)` calls it and writes
      `PM_ORIGIN_SESSION` (and `PM_ORIGIN_WINDOW`) into the
      subprocess env for both `_run_command_sync` and
      `_run_command_async`. Fallback chain: TUI's own session, then
      `app._session_name`.

R3. **Replace `select_window` call sites with `focus_window`** so they
    pick up the env-var-driven origin capture:
    - `pm_core/cli/pr.py` (4 sites)
    - `pm_core/cli/meta.py`
    - `pm_core/cli/container.py`
    - `pm_core/tui/pr_view.py` (2 sites — fast paths)
    - `pm_core/tui/qa_loop_ui.py`
    - `pm_core/tui/pane_ops.py` (plans window)
    - `pm_core/tui/app.py` (watcher focus from `wf` chord)
    - `pm_core/qa_loop.py` first-time creation path
    Behaviour: still single-session switch, but now correctly targets
    the originator (env-driven) instead of resolving lazily via
    `current_or_base_session` at call time.

R4. **Replace `switch_sessions_to_window` call sites with
    `focus_window(..., co_viewers=...)`**:
    - `pm_core/qa_loop.py:2300` (qa kill+recreate)
    - `pm_core/cli/pr.py:1310` (review --fresh)
    - `pm_core/cli/watcher.py:412` (watcher iteration recreate)
    Pure refactor; semantics identical.

R5. **`_respawn_tui` must not force focus** (`pm_core/pane_layout.py`).
    A TUI restart is not allowed to yank attached sessions away from
    whatever they were viewing. The previous `select_window(session,
    window)` call after creating a fresh TUI window is removed
    entirely.

R6. **Keep `select_window` and `switch_sessions_to_window` exported as
    thin wrappers** for back-compat.
    - `select_window(s, w)` → `focus_window(s, w)` (single-session
      default; legacy callers unaffected).
    - `switch_sessions_to_window(sessions, s, w)` → `focus_window(s,
      w, co_viewers=sessions)`.

## What this PR does NOT do

The first draft of `focus_window` auto-detected "co-viewers" — any
session in the group whose active window matched the origin's — and
switched them all together. That was wrong. Two reasons:

1. Two sessions sharing a window for unrelated reasons should not
   move together when one of them runs a command.
2. The TUI is itself a shared window by design; auto-pulling everyone
   on the TUI window is a regression, not a fix.

The auto-detection was removed. The only way multiple sessions move
together is the explicit `co_viewers=` snapshot used by loop
kill-and-recreate flows.

## Edge cases

- **Origin session has died** between launch and refocus: `select-window
  -t dead-sess:N` returns non-zero; `focus_window` returns False. The
  caller already echoes a generic message; no new handling needed.
- **Window id / index / name**: `_resolve_window_target` handles all
  three.
- **Most-recently-active client filter**: only sessions matching
  `base` or `base~*` are considered. Tmux clients attached to
  unrelated sessions on the same socket cannot become the origin.

## Test plan

Manual (`pm/qa/regression/window-refocus-coviewers.md`):
1. Multi-attached single-TUI: refocus switches only the originating
   client; other clients stay where they were.
2. Loop kill-and-recreate (`pr review --fresh`, watcher iteration,
   qa relaunch): sessions watching the old loop window all land on
   the new one.
3. TUI respawn does not move any client.

Code: `tests/test_tmux.py::TestFocusWindow` covers default-single-
session, explicit-vs-env origin, `co_viewers` override replacing
origin, and unknown window. `TestMostRecentClientSession` covers the
client-activity helper.

## Coordination

pr-291e891 (action-source metadata, pending) will introduce a richer
action-context structure. When it lands, the env-var transport here
can be replaced by passing the action context explicitly.
