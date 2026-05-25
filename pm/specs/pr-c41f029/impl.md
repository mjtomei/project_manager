# pr-c41f029 — Capture the originating tmux session at PR-actions-pane open, not at action-execution time

## Problem (grounded)

When a TUI action replaces a window (review-loop iteration, QA planning
window, watcher), pm wants to move the session that *initiated* the action
onto the new window so the user keeps following their own action. Today the
originating session is determined **late**, at action-execution time, by
`tmux.sessions_on_window(base, window_id)` (`pm_core/tmux.py:645`), which
queries each grouped session's *current* active window
(`tmux display -p #{window_id}`) and matches it against the old window id.
`switch_sessions_to_window()` (`pm_core/tmux.py:668`) then moves the matches.

Three call sites do this late detection:

- `pm_core/qa_loop.py:3030` — QA planning-phase window (re)creation
  (action `qa`).
- `pm_core/cli/pr.py:1143` — review-loop window (re)creation
  (action `review-loop`; only computed when `review_loop and fresh and
  existing`).
- `pm_core/cli/watcher.py:389` — watcher window recreation (project-level,
  not a per-PR picker action).

**Race:** between the user triggering the action from the PR-actions popup
(`pm _popup-picker`, `pm_core/cli/session.py:1671`) and the action actually
running `sessions_on_window`, the active window/session can change (popup
closed, another session navigated, old window already killed/recreated). The
match then returns the wrong session or none, so window-following targets the
wrong window or nobody. It also adds several tmux round-trips on the action's
critical path.

The invoking session **is** already known at popup-open time: the popup
shell resolves `#{session_name}` once when the popup opens and hands it to
`pm _popup-picker "$S" "$W"` (`pm_core/cli/session.py:60-62`); that value
flows unchanged to `_run_picker_command(cmd, session)`
(`pm_core/cli/session.py:1615`). It is simply discarded for the
window-following decision — the action re-detects instead.

Note: the dependency PR pr-291e891 ("action source metadata: session/window/
task") is still **pending**, so no action-context struct exists yet. This PR
introduces the minimal session field of that context and uses it for
window-following.

## Requirements

R1. **Capture once, at pane/picker open.** The invoking session must be
resolved when the PR-actions popup opens (already available as the `session`
arg threaded to `_run_picker_command`) and stored, not re-detected at
execution time.

R2. **Thread it to the action implementation.** The picker dispatch path
(both the `tui:` SIGUSR2-queue route and the direct-subprocess route in
`_run_picker_command`) must record the captured session for the action so the
implementation can read it back. Because the dispatch path crosses a SIGUSR2
queue file and/or a subprocess boundary (the review-loop relauncher shells
out to `pm pr review`), the captured session is carried through the existing
per-`(pr_id, action)` runtime-state record (`pm_core/runtime_state.py`) — the
same channel already used for `suppress_switch` (`request_suppress_switch` /
`consume_suppress_switch`). This is the "store it on the action context"
mechanism in the absence of pr-291e891.

R3. **`switch_sessions_to_window()` uses the captured session(s) directly.**
`switch_sessions_to_window` already accepts an explicit `sessions` list and
never calls `sessions_on_window`. The fix is at the *call sites*: when a
captured originating session is present, pass it straight to
`switch_sessions_to_window` and **skip** `sessions_on_window`. A new helper
`tmux.followers_for_window(base, window_id, captured)` centralizes the
"prefer captured, else detect" decision and makes it testable.

R4. **`sessions_on_window()` remains the fallback.** When no captured session
is available (CLI invocations, the project-level watcher, multi-client
ambiguity), the call sites fall back to `sessions_on_window` — preserving
today's behavior exactly.

## Design

### runtime_state (the captured-session channel)

Add, mirroring the existing `suppress_switch` helpers:

```python
def capture_origin_session(pr_id, action, session): ...   # set origin_session
def consume_origin_session(pr_id, action) -> str | None:  # read + clear
```

`capture_origin_session` writes `origin_session=<session>` via
`set_action_state(pr_id, action, None, origin_session=session)` — state
untouched, field merged into the action dict, persisting across the
launching/running transitions the action writes later (extras only modify
the keys passed; the suppress-invalidation branch at
`runtime_state.py:158-162` touches only `suppress_switch`).
`consume_origin_session` reads `origin_session`, and if present clears it
(`set_action_state(..., origin_session=None)`); a no-op when absent. The
empty-entry pruning at `runtime_state.py:175-178` keeps `origin_session` a
"meaningful" key so capture creates/keeps the entry and consume can prune it.

### tmux helper

```python
def followers_for_window(base, window_id, captured=None) -> list[str]:
    """Sessions to switch onto the freshly (re)created window.

    Prefer the explicitly-captured originating session(s) (resolved at
    picker/pane-open time); fall back to live detection via
    sessions_on_window only when none were captured."""
    if captured:
        items = captured if isinstance(captured, list) else [captured]
        return [s for s in items if s]
    return sessions_on_window(base, window_id)
```

### Capture points

- **Picker (the race source).** In `_run_picker_command(cmd, session)`,
  before dispatch, derive `(pr_id, action)` from `cmd` (reusing
  `_parse_tui_action` for `tui:` commands; a small parser for the direct
  `pr start|review|merge` forms) and call
  `runtime_state.capture_origin_session(pr_id, action, session)`. `session`
  is the popup-open-time value (R1). Covers both routes.

- **In-TUI dispatch (command bar + d/t keybindings).** For commands typed
  in the TUI or triggered by keys, the originating session is the attached
  client. Add `tmux.active_client_session(base)` returning the lone attached
  client's session, or `None` when zero or multiple clients are attached
  (ambiguous → fall back, R4). Capture (best-effort, additive) for the
  window-following actions (`review-loop`, `qa`) from `app.on_command_submitted`
  and the `zz d` / `t`/`z t`/`zz t` action methods. If `active_client_session`
  returns `None`, capture nothing — behavior is identical to today.
  Capture is **not** added to `_drain_command_queue` (the picker's `tui:`
  route is drained there and already captured at popup-open with the correct
  session; recapturing with the TUI's own session would clobber it).

### Consumers (use captured, else fall back)

- `qa_loop.py` planning phase: `captured = consume_origin_session(state.pr_id,
  "qa")`; for the replacement case use
  `followers_for_window(session, existing_win["id"], captured)`. For
  first-time creation **with** a captured session, switch that session
  explicitly (respecting `consume_suppress_switch`) instead of the generic
  `select_window`; first-time **without** capture keeps the existing
  `select_window` path.

- `cli/pr.py` review-loop: `captured = consume_origin_session(pr_id,
  "review-loop")` (only when `review_loop`); replace the
  `sessions_on_window` call with
  `followers_for_window(pm_session, existing["id"], captured)`.

- `cli/watcher.py`: route through `followers_for_window(pm_session,
  existing["id"], None)` — no per-PR picker context, documented fallback
  (R4). Pure refactor, no behavior change.

## Implicit Requirements

- The captured value must survive the action's own
  `set_action_state(..., "launching"/"running", ...)` writes between capture
  and consume. It does: extras are merged, not replaced (verified at
  `runtime_state.py:166-170`).
- The captured session name must be a real grouped-session name that
  `switch_sessions_to_window` can map to a `client_tty` via `list-clients`.
  The popup's `#{session_name}` is exactly that.
- `switch_sessions_to_window(sessions, session, window_name)` uses `session`
  only to locate the window by name and as the select-window prefix; passing
  base as `session` and a grouped session in `sessions` is already the
  established pattern and stays valid.
- Consume must clear the field so a later run of the same action does not
  inherit a stale session. `sweep_stale_states` on TUI restart already
  deletes in-flight entries, bounding any leak.

## Ambiguities (resolved)

- *Multi-client (collab) in-TUI dispatch* — which client originated a
  keypress is unknowable from inside the TUI event. Resolved: capture only
  when exactly one client is attached; otherwise fall back to
  `sessions_on_window` (which already moves every session sitting on the old
  window — the correct collab behavior).
- *First-time QA window creation with a captured session* — the pre-fix code
  uses `select_window` (acts on the focused client of `session`). Resolved:
  when a captured session exists, switch that session explicitly so a grouped
  client that opened the picker actually follows; keep `select_window` when
  there is no capture. Suppress-switch is still honored.
- *Watcher* — project-level, no picker action/pr_id. Resolved: fallback only.
- *Review-loop first iteration* — no existing window, so no
  `switch_sessions_to_window`; the popup spinner
  (`session.py:1499-1522`, `select_window(session, target)` with the
  captured popup session) already drives that switch. Captured value is
  consumed at the cli/pr.py site; later iterations, after the user is on the
  review window, detection is reliable. No extra threading through the
  relauncher subprocess is required for correctness.

## Edge Cases

- `consume_origin_session` on an action with no recorded entry → returns
  `None`, writes nothing (no empty-stub entry, per pruning logic).
- Popup dismissed with q/Esc → `request_suppress_switch` already set; QA's
  first-time captured-switch and the spinner both honor it.
- Direct route action with no parseable pr_id (e.g. malformed) → capture
  skipped; no crash (wrapped in try/except, logged at debug).
- `followers_for_window` with `captured=[]` (empty list) → treated as "no
  capture", falls back to detection.

## Tests

`tests/` (pytest), no live tmux:

1. `followers_for_window` prefers captured and does **not** call
   `sessions_on_window` when captured is present (monkeypatch
   `sessions_on_window` to raise); falls back to it when captured is
   `None`/empty.
2. `capture_origin_session` / `consume_origin_session` roundtrip via a temp
   runtime dir, including: survives an intervening
   `set_action_state(..., "running")`; consume clears it; consume on a
   missing entry returns `None`.
3. Race simulation: capture session `A` for `(pr, "qa")`; arrange a stub
   `sessions_on_window` that would return a *different* session `B` (the
   late/wrong detection) or `[]`; assert the value handed to
   `switch_sessions_to_window` is `[A]` (captured wins, detection skipped).
4. `_run_picker_command` (or the extracted `(pr_id, action)` parser) records
   the popup session under the right `(pr_id, action)` for representative
   `tui:` and direct commands.
5. `active_client_session` returns the lone client's session and `None` for
   zero/multiple attached clients (stub `list-clients` output).
