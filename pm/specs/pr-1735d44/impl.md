# pr-1735d44 — Consolidate window refocus

## Goal
Replace all `tmux.select_window` and `tmux.switch_sessions_to_window` refocus
call sites with a single unified `tmux.focus_window` that:
- accepts an explicit *originating* session (so async TUI commands focus the
  right user, not whoever happens to be focused later);
- finds every session in the group that is currently viewing the same window
  as the originating session ("co-viewers") and switches them all together
  to the target window.

## Requirements (grounded)

R1. **Add `tmux.focus_window(base, window, origin_session=None)`** in
    `pm_core/tmux.py`:
    - `base` — the base pm session (e.g. `pm-foo-c5a1006b`).
    - `window` — window id (`@N`) or name. Resolved via `find_window_by_name`
      when not an id; if not found return False.
    - `origin_session` — the session that originated the refocus (may be a
      grouped suffix `base~N`). Defaults to `$PM_ORIGIN_SESSION` env var, then
      falls back to `current_or_base_session(base)` for compatibility.
    - Compute the currently-attached window id of `origin_session`. Then call
      `sessions_on_window(base, that_id)` to find co-viewers. If origin is in
      that list (it normally will be), switch every co-viewer; otherwise still
      include origin so something happens. Switch each via select-window +
      switch-client (same machinery as `switch_sessions_to_window`).
    - Idempotent / safe if window already in front.

R2. **Replace all `select_window` refocus call sites** with `focus_window`:
    - `pm_core/cli/pr.py` (lines 832, 840, 1169, 1518)
    - `pm_core/cli/meta.py` (line 167)
    - `pm_core/cli/container.py` (line 169)
    - `pm_core/tui/pr_view.py` (lines 109, 162)
    - `pm_core/pane_layout.py` (line 635)
    - `pm_core/tui/qa_loop_ui.py` (line 83)
    - `pm_core/tui/pane_ops.py` (line 574)
    - `pm_core/tui/app.py` (line 827)
    - `pm_core/qa_loop.py` (line 2304)
    Note: task description also mentions `qa_status.py`, but that file no
    longer contains a refocus call — skip.

R3. **Replace `switch_sessions_to_window` call sites with `focus_window`**:
    - `pm_core/qa_loop.py` (line 2300)
    - `pm_core/cli/pr.py` (line 1310)
    - `pm_core/cli/watcher.py` (line 412)
    These currently pass an explicit `sessions_on_window(...)` list captured
    *before* the kill-and-recreate. Preserve that "snapshot before kill"
    semantic by giving `focus_window` an optional `co_viewers` override list:
    `focus_window(base, window, ..., co_viewers=sessions_on_review)`. When
    provided, skip the runtime co-viewer detection and just switch the
    pre-captured list.

R4. **Capture originating session at TUI command-launch time** — fix bug
    described in note 3 (2026-05-03). When the TUI launches a subprocess via
    `pr_view.run_command` (`pm_core/tui/pr_view.py:632`), set
    `PM_ORIGIN_SESSION` (and `PM_ORIGIN_WINDOW`) in the subprocess env to the
    TUI's own session and current window. Both sync and async paths
    (`_run_command_sync`, `_run_command_async`).
    - The TUI knows its session via `app._session_name` (base only); we need
      the actual current grouped session so co-viewer detection is correct.
      Use `tmux_mod.get_session_name()` (reads `$TMUX_PANE`) at command-launch
      time. Fall back to `app._session_name` if that returns empty.
    - The CLI side reads the env var inside `focus_window`; no changes needed
      to individual call sites.

R5. **Keep `select_window` and `switch_sessions_to_window` exported** for
    now so any non-refocus callers (none expected, but safer) don't break.
    Mark them as deprecated in their docstrings, or have `select_window`
    delegate to `focus_window` for the trivial case. Decision: just rewrite
    them as thin wrappers around `focus_window` — that way both names keep
    working but funnel through the same logic.

## Implicit requirements

- `focus_window` must work when the originating session is not attached
  (e.g. cron-driven watcher). `sessions_on_window` already handles that; if
  no co-viewers it returns []; we then have nothing to switch. Behaviour
  should match the current `switch_sessions_to_window` no-op.
- Must not regress the "fresh review" use case: the watcher and review-loop
  paths capture co-viewers *before* killing the old window. `co_viewers`
  override preserves this.
- The grouped-session env (`PM_ORIGIN_SESSION`) must not poison nested
  invocations — e.g. a CLI that itself spawns subprocesses. Acceptable: env
  inherits, but each refocus uses the same origin, which is correct.

## Edge cases

- **Origin session viewing a different window**: e.g. user fired `pr start`
  from window A, then switched to window B before the new window is created.
  Per note 3 the desired behaviour is to focus the *originating* session
  back to the new window — so we switch origin (and any session still on the
  origin's *original* window? no: at refocus time we look up origin's
  *current* window for co-viewers). This still focuses origin, which matches
  spec; co-viewers detected at refocus time are the right set.
- **Origin session has died** between launch and refocus: `display-message
  -t origin` will fail, sessions_on_window returns []. Fallback: switch the
  base session via the current behavior (call `select-window` against base).
- **Window-id strings vs names**: existing call sites pass either `index`,
  `id` (`@123`), or `name` interchangeably. `focus_window` must accept all
  three. tmux's `select-window -t base:<token>` accepts all three natively;
  the only place we need name resolution is when the caller passed a co_viewers
  override and we still need an index for select-window. Keep a small
  resolution helper: if it looks like an id (`@N`) use as-is; if numeric
  use as index; else name → look up via `find_window_by_name`.
- **`select_window` was used in `pane_layout._respawn_tui`** to switch the
  freshly-created TUI window into view. Origin session is whoever ran the
  respawn. Keep behavior identical — pass the session as both origin and
  base.

## Ambiguities

None unresolved. Coordination with pr-291e891 (action-source metadata) is
deferred — that PR is still pending; when it lands it can replace the env
var transport with the richer action-context structure. Document this in a
docstring comment so that PR's author sees the integration point.

## Test plan

Manual (per task description):
1. From TUI, refocus a PR window with another grouped session attached and
   viewing the same window — both should switch.
2. Same as 1 but with the second session viewing a different window —
   second session must NOT move.
3. From CLI (outside tmux/another session), trigger `pm pr review pr-X` for
   a PR whose window is being viewed in a TUI session — that TUI session
   should switch.
4. Async repro for note 3: from TUI in window A, hit `s` (start) for a PR.
   Quickly switch to window B. When the new PR window is created, focus
   should follow the originating user (back to the new PR window from
   wherever they ended up).

Code: extend an existing tmux test or add a small unit test for
`focus_window` argument resolution (id vs name vs index, env var pickup).
