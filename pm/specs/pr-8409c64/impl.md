# Spec: pr-8409c64 — `zz d` review-loop popup spinner never switches to the review window

## Summary of the bug (verified by repro)

When the review-loop popup spinner runs (`pm _popup-picker` → chord `zz d` →
`tui:review-loop start <pr>` → `_run_picker_command` → `_wait_for_tui_command`
in `pm_core/cli/session.py`), the spinner **resolves the PR's `display_id`
from `state_root()`**, which is cwd-/`_project_override`-based. When the popup
process's cwd (or `PM_PROJECT`) does not point at the pm project that owns
`<pr>`, `state_root()` loads the *wrong* `project.yaml`, the `pr_id` is not
found, and `display_id` stays `None`.

With `display_id is None`, `target_window` becomes `None`
(`_ACTION_WINDOW_PATTERNS["review-loop"].format(...)` is skipped), so
`_find_target_window_ids()` returns `[]` on **every** poll. `window_open`
is therefore never `True`, the terminal short-circuit never fires (the loop
stays `running`), and the spinner loops forever showing `running…` / the
"starting" frame. The window-switch (`tmux_mod.select_window`) is never
reached, so focus never moves to `review-<display_id>`.

This is the **same** failure for all three acceptance cases (no window /
running loop / terminal loop) because the cause is upstream of any
window/state logic: with `target_window=None` the spinner is watching
*nothing*.

### Repro evidence (`/tmp/pm-test-spinner`, local backend)

Spinner log line at start:
```
spinner: pr=pr-95325c4 action=review-loop fresh=True target_window=None
         initial_window_ids=[] initial_state=running
```
Then `spinner tick … cur_window_ids=[] … window_open=False` repeats forever,
even though `tmux list-windows` shows `@3 review-pr-95325c4` was created and
the TUI logged `set_action_state … review-loop … to=running`. After 30s the
spinner was still spinning and the active window was still `main`.

Confirmed root resolution mismatch:
- `_resolve_root_from_session(base)` → `/tmp/pm-test-spinner/pm` → display_id
  `pr-95325c4` ✓
- `state_root()` (cwd `/workspace`) → `/workspace/pm` → does **not** contain
  `pr-95325c4` → `display_id=None` ✗

### Why #206 (cwd-yaml) didn't cover this

#206 (pr-c1f8086) made `popup_picker_cmd` resolve its project root from
session metadata via `_resolve_root_from_session(session)` and set
`os.environ["PM_PROJECT"]` for *subprocesses*. But `_wait_for_tui_command`
runs **in the same process** and re-resolves the root with `state_root()`,
which reads the module-level `_project_override` (fixed at CLI init from the
env that existed *before* the picker set it) — not the env var or the session
metadata. So the picker's *listing* uses the right project while the spinner's
*display_id* resolution still uses cwd. `PM_PROJECT` is only forwarded into
the tmux session env (`session.py` ~437) when it was already set when
`pm session` started; otherwise it is absent and the cwd fallback wins.

## 1. Requirements (grounded)

- **R1** — `zz d` from a non-review window must land focus on
  `review-{display_id}` and dismiss the spinner, for (a) no review window
  open, (b) review window open with a running loop, (c) review window open
  with a terminal loop. Implemented in
  `pm_core/cli/session.py::_wait_for_tui_command`.
- **R2** — The spinner must not hold the "starting" frame after the review
  window has opened. The fix makes `target_window` resolvable so
  `_find_target_window_ids()` matches the created window and the existing
  `window_open` branch fires `tmux_mod.select_window(session, target_window)`.
- **R3** — Tests cover the new-window and existing-window cases (failing on
  pre-fix code, passing after).

## 2. Root-cause fix

In `_wait_for_tui_command`, resolve the project root the **same way the popup
picker does** — from the session via `_resolve_root_from_session(session)`
(defined in the same module) — and only fall back to `state_root()` when the
session lookup yields nothing. This makes `display_id`/`target_window`
resolution independent of the popup's cwd / `PM_PROJECT`, matching the
picker's own listing.

```python
saved_root = _resolve_root_from_session(session)
root = saved_root if saved_root is not None else state_root()
data = store.load(root)
```

This is the minimal change at the true root cause; the window-appearance and
suppress-switch logic downstream is already correct (verified: with a valid
`target_window`, the simulation and the real surface both switch).

## 3. Implicit Requirements

- **IR1** — `_resolve_root_from_session` must be callable from inside
  `_wait_for_tui_command`. It is module-level in `session.py`; the `session`
  argument passed in is already the base session name (caller passes
  `base = pane_registry.base_session_name(session)`), and
  `_resolve_root_from_session` itself normalizes via `base_session_name`, so
  passing the (already-base) session is safe.
- **IR2** — Behavior must be unchanged when the popup's cwd *does* point at
  the correct project (the common workdir-clone case): `_resolve_root_from_session`
  returns the persisted root (same project) and display_id resolves
  identically; if session metadata is missing it falls back to `state_root()`
  exactly as today.
- **IR3** — A `pr_id` genuinely absent from the resolved project still yields
  `display_id=None`/`target_window=None`; the spinner then relies on the
  terminal-state short-circuit (unchanged) rather than spinning forever only
  in that genuinely-not-found case. The fix specifically removes the
  *false-negative* (PR exists but in a different-cwd project).

## 4. Edge Cases

- **EC1 — qa / start / merge actions**: they also resolve `display_id` via the
  same block, so the fix benefits them too (QA `pr qa` from a foreign cwd had
  the same latent gap). No behavior change when cwd is correct.
- **EC2 — session metadata absent** (older sessions / never persisted):
  `_resolve_root_from_session` returns `None` → falls back to `state_root()`
  → identical to today's behavior (no regression).
- **EC3 — github-backed project** (`display_id = #N`): the window name is
  `review-#N`; tmux `select-window -t sess:review-#N` works (verified `#` in
  the target is literal). The fix is backend-agnostic — the failure was the
  same `target_window=None`, just with the `#N` form.

## 5. Ambiguities

None unresolved. The task description's claim "the spinner is watching the
right window; it just never fires the switch" is slightly inaccurate per the
repro: the spinner is watching *no* window (`target_window=None`). The fix
addresses the actual observed cause and satisfies all acceptance criteria.

## 6. Test plan

- Unit test in `tests/` driving `_wait_for_tui_command` with a patched
  `_resolve_root_from_session` returning a project that *contains* the PR,
  while `state_root()` returns one that does *not* (simulating a foreign
  popup cwd). Assert `tmux_mod.select_window(session, "review-<id>")` is
  called for: (a) window appears with no prior window, (b) prior window id
  replaced by a new id (existing-window/fresh case). On pre-fix code these
  fail (select_window never called; spinner would loop) because display_id
  resolves to None.
