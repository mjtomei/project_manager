# Spec: pr-c1f8086 — popup spinner watches wrong window from workdir cwd

## Requirements

1. **Fix root resolution in `_wait_for_tui_command`** (pm_core/cli/session.py:1247).
   When invoked from a pane whose cwd is inside a PR workdir, the function
   currently calls `state_root()` → `store.find_project_root()`, which walks
   up from cwd and lands on the workdir's stale clone-time `project.yaml`.
   That yaml may be missing `gh_pr_number`, so `_pr_display_id` returns
   `pr-<short-hash>` instead of `#<gh-num>`. The launcher subprocess uses
   the master yaml and creates a window named `<action>-#NNN`, so the
   spinner's `target_window` never matches and the spinner spins forever.

   Fix: prefer the session's persisted pm root via
   `_resolve_root_from_session(session)`, falling back to `state_root()`
   only if no session record exists. Mirrors the pattern at
   session.py:1668-1670 (`popup_picker_cmd`).

   Replacement (session.py:1247-1248):
   ```python
   saved_root = _resolve_root_from_session(session)
   root = saved_root if saved_root is not None else state_root()
   data = store.load(root)
   ```

## Implicit Requirements

- `_resolve_root_from_session` is defined later in the same file
  (session.py:1626). Python resolves names at call time, not definition
  order, so calling it from `_wait_for_tui_command` (1217) is fine — same
  pattern is already used elsewhere in the file.
- `session` param of `_wait_for_tui_command` is the tmux session name
  (already passed at session.py:1605 as `base`). `_resolve_root_from_session`
  applies `pane_registry.base_session_name` internally, so passing either
  the base or a derived session name is safe.
- The existing `try/except` around root resolution (1246-1256) must still
  catch failures from `store.load`. The new `_resolve_root_from_session`
  call should remain inside or before the try; it returns `None`/`Path`
  and shouldn't raise under normal use, so placing it just before the
  try is acceptable, matching the picker pattern.

## Ambiguities

None unresolved. The fix is explicitly described and one-line.

## Edge Cases

- **Session has no persisted pm_root** (started outside the pm session
  flow): `_resolve_root_from_session` returns `None`, falls back to
  `state_root()` — preserves current behavior.
- **`PM_PROJECT` env is set**: `state_root()` honors it via click context;
  the saved-root path takes precedence, which is the correct behavior
  because the session record is the authoritative project root.
- **Running outside any workdir** (cwd already at master root): saved
  root equals cwd-walk root; no behavioral change.
- **Other in-process callers of `state_root()`**: out of scope per task
  description; no follow-up audit performed here.
