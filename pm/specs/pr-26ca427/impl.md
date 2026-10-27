# Spec: popup picker says "No project.yaml found"

## Background

`tmux display-popup` does not inherit `pane_current_path` unless `-d` is passed.
The popup runs `pm _popup-picker` / `pm _popup-cmd`, which call `state_root()`
→ `store.find_project_root()` (pm_core/store.py:40), which walks up from
`os.getcwd()` looking for `project.yaml`. When the popup's cwd is tmux's
server-side default (often `/` or `$HOME`), the walk finds nothing and the
handler at session.py:1534-1536 prints "No project.yaml found.".

A second failure mode: a deleted workdir (post-`pm pr merge` cleanup) leaves
panes with a non-existent cwd. `os.getcwd()` itself raises FileNotFoundError,
which the same handler catches.

## Requirements

1. **Pass `-d <pane_current_path>` to `tmux display-popup`** so the popup's
   shell starts in the launching pane's cwd.
   - Code path: `pm_core/cli/session.py:711` `popup_show_cmd`.
   - **Already implemented** in commit bd98cd3 (lines 747-762). No change
     needed.

2. **Resolve project root from session metadata, not cwd**, in
   `_popup-picker` and `_popup-cmd`:
   - Persist the project root when `pm session` starts.
   - In the popup commands, prefer the persisted root over cwd-walking.
   - Fall back to `state_root()` if no persisted root exists.

## Implementation plan

### Persistence

Store the project root as a one-line file at
`~/.pm/sessions/<session-tag>/pm_root`. This sits next to the existing
`override` / `debug` files (pm_core/paths.py:68-78).

Add helpers to `pm_core/paths.py`:
- `set_session_pm_root(session_tag: str, root: Path) -> None`
- `get_session_pm_root(session_tag: str) -> Path | None` — returns None if
  the file doesn't exist, the path inside is empty, or the path no longer
  exists on disk (handles the case where the project itself was moved/
  deleted; let the popup gracefully fall back).

### Write site

In `pm_core/cli/session.py:_session_start` after line 268, when
`has_project` is true, persist the root:
```python
if has_project:
    tag = get_session_tag(start_path=root)
    if tag:
        set_session_pm_root(tag, root)
```

The `start_dir` join branch (line 283) does not have a local root, so it's
skipped — joiners will fall back to cwd-walking, which is fine since the
`-d` fix already makes the popup cwd valid for them too.

### Read site

In `popup_picker_cmd` (session.py:1503) and `popup_cmd_cmd` (session.py:1838),
derive the session tag from the `session` argument (the session name is
`pm-<tag>`), then resolve `root` via session metadata first:

```python
def _resolve_root_from_session(session: str) -> Path | None:
    base = pane_registry.base_session_name(session)
    tag = base.removeprefix("pm-")
    if tag == base:
        return None
    return get_session_pm_root(tag)
```

In `popup_picker_cmd`, replace lines 1531-1536:
```python
saved_root = _resolve_root_from_session(session)
try:
    root = saved_root if saved_root else state_root()
    data = store.load(root)
except FileNotFoundError:
    click.echo("No project.yaml found.")
    _pause_and_exit(1)
```

`popup_cmd_cmd` does not call `state_root()` directly today — it just shells
out to `pm <user-command>`. To make those subcommands inherit the session
root, set `_project_override` (helpers.set_project_override) before reading
the user input, OR set `PM_PROJECT` env var before the subprocess. Use the
env-var route since the user command runs in a separate process via
`pm_core.wrapper`. Check `pm_core.wrapper` honors `PM_PROJECT`. (Today it
does — `find_project_root` is called by the subcommand, which honors
`PM_PROJECT` via `_project_override` set in `cli()` callback.)

Actually, looking at the code flow: `pm_core.wrapper` invokes the CLI which
calls `set_project_override` based on `--C` flag or `PM_PROJECT` env. We
should check for `PM_PROJECT`; if not, the wrapper still walks cwd. Setting
`PM_PROJECT` in the env before `subprocess.run` is the simplest fix:

```python
saved_root = _resolve_root_from_session(session)
env = os.environ.copy()
if saved_root:
    env["PM_PROJECT"] = str(saved_root)
rc = _run_with_abort_keys(full_cmd, env=env)
```

Need to verify `_run_with_abort_keys` accepts `env` (or threads it through).

## Implicit Requirements

- The session tag derived from `pm-<tag>` must match the tag used to persist
  the root. Both come from `get_session_tag()` so this holds as long as
  `_session_name_for_cwd` continues to use `f"pm-{tag}"` (it does — see
  session.py:288).
- `set_session_pm_root` must not crash if the sessions dir cannot be
  created (already handled — `session_dir` calls `mkdir(exist_ok=True)`).
- Persisting on every session start is fine — it's a single-line file
  write, no harm if redundant.

## Edge Cases

- **Joining another user's session (`--dir`):** the joiner's `start_dir`
  isn't necessarily a pm repo root; current code handles that by skipping
  the persistence write. The popup still works because the -d fix is in
  place. If the joiner's pane cwd is also outside any pm repo, the popup
  picker still fails, but that's a separate issue out of scope here.
- **Project moved/deleted after persistence:** `get_session_pm_root` checks
  existence and returns None, falling back to `state_root()`, which will
  raise FileNotFoundError → "No project.yaml found." (correct message in
  that case).
- **Session tag changes (rare — repo path hash changes):** old `pm_root`
  lingers but is unreachable since the new tag has its own file. Cleanup
  is via `clear_session()` which already removes the whole session dir.

## Ambiguities

None blocking.
