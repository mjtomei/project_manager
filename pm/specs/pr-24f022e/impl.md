# pr-24f022e — popup-dispatched pm commands must run the session's pm_core

## 1. Requirements

R1. **Picker direct route.** `_run_picker_command(cmd, session)` (pm_core/cli/session.py,
non-`tui:` branch) currently spawns `[sys.executable, "-m", "pm_core.wrapper", *shlex.split(cmd)]`
in the popup's cwd. It must spawn a child whose code is the tmux session's pm_core:
`~/.pm/sessions/<tag>/override` if set, else the pm_core under the session's persisted
`pm_root` (`<pm_root>/../pm_core`, the same rule `wrapper._pm_core_from_pm_root` uses and
the same file `_resolve_root_from_session(session)` reads), regardless of what the cwd
contains.

R2. **prefix+M runner.** `_popup-cmd` (`popup_cmd_cmd`) builds the same `-m pm_core.wrapper`
argv and runs it through `_run_with_abort_keys`. Same fix as R1. Its `tui:` re-route
(`pr qa`, `review-loop`) is unchanged.

R3. **Never load the child's entry point from cwd.** `python -m` (and `-c`) put the cwd/''
first on `sys.path`, so a workdir's `pm_core/wrapper.py` is imported before any fix can run.
Python here is 3.10 (`requires-python >=3.10`), so `python -P` isn't available. Instead the
dispatcher runs `python -c <bootstrap> <import_root> <session_tag> <args…>`. The bootstrap
drops the `''` entry that `-c` prepends, puts `<import_root>` first on `sys.path`, imports
`pm_core.wrapper` from it, and calls a new `wrapper.main_for_session(tag)`.
`<import_root>` is the dispatcher's own pm_core parent (`Path(pm_core.__file__).parent.parent`).
The dispatcher is an IPC command, so it already runs session-resolved code, and that code
is guaranteed to contain `main_for_session`.

R4. **`wrapper.main_for_session(session_tag)`** resolves code from the given tag only:
override(tag) → pm_root(tag) → no cwd walk → keep the dispatcher's code
(`chosen_via=dispatcher`). It shares the sys.path insert / pm_core module purge / log /
`_mark_tmux_session` steps with `main()`. Its log line includes `chosen_via=` and the tag.

R5. **`wrapper.main()` is unchanged** for every other caller: ad-hoc CLI, agents in workdirs,
QA clone overrides, IPC commands, and TUI-spawned subprocesses. The only refactor is
extracting shared helpers, with no behavior change. The new entry point is reachable only
through the bootstrap that the two popup dispatchers build. No env var is added, so nothing
leaks to grandchildren.

R6. **Keep cwd and PM_PROJECT.** The child keeps the popup's cwd (no `cwd=` passed) and
inherits `PM_PROJECT=<session root>`, which both popups already export. Only code
resolution changes.

## 2. Implicit requirements

- The child's argv as seen by click must be exactly the user's args. The bootstrap strips
  its two leading args before `pm_core.cli.main` runs, and sets `sys.argv[0]` to the
  wrapper's path so the log's `argv0=` names the file that ran.
- When pm_root/override selects a root different from the bootstrap root, the existing purge
  of `pm_core*` from `sys.modules` reloads everything from the selected root. That is the
  same mechanism `main()` uses.
- `PM_IN_TMUX_SESSION` must still be set (via `_mark_tmux_session`), so `pr merge`
  keeps defaulting `--resolve-window` under tmux.
- Existing tests that mock `subprocess.run` in `_run_picker_command` keep working. They
  check only capture/echo behavior.

## 3. Ambiguities (resolved)

- *Override for the session tag?* Yes. Override has priority over pm_root for the same tag,
  which keeps `main`'s priority order. A `pm meta`/QA session's tmux session tag is the tag
  its override is keyed to. Overrides keyed to the *cwd's* tag (QA clone overrides) are
  ignored for popup children, because the cwd must not pick the code.
- *Session pm_root has no pm_core source (ordinary user repo)?* Run the dispatcher's own
  code (installed pm), never cwd_walk. Logged as `chosen_via=dispatcher`.
- *Is the session tag empty or unparsable (session name without `pm-`)?* Same as above:
  dispatcher code. Both popups exit earlier if the session has no registry anyway.

## 4. Edge cases

- `PYTHONPATH` with a pm_core dir (e.g. `/opt/pm-src` in review containers): the bootstrap
  inserts its root at index 0, ahead of PYTHONPATH, and the selected root is inserted ahead
  of that.
- `PYTHONSAFEPATH` set (3.11+): `-c` prepends nothing. The bootstrap removes `sys.path[0]`
  only if it is `''`.
- Audit of other direct dispatches in session.py: `_schedule_rebalance` (`-c` importing
  `pm_core.pane_layout`) runs on session reconnect, not from a popup, so it is out of scope.
  `_popup-show` runs only `tmux display-popup` and the fzf/`tmux` helpers run no pm code.
  The `tui:` route goes through TUI IPC and is out of scope. #206 (spinner cwd-walk) is
  separate.
- Running the same commands directly in a shell in the workdir still uses `main()` →
  cwd_walk (R5), which the tests cover.

## 5. Tests

- E2E: the fake session root (pm/ + pm_core symlink to the repo) is registered as
  `~/.pm/sessions/<tag>/pm_root` under a tmp HOME. The decoy workdir is a git repo whose
  `pm_core/wrapper.py` and `pm_core/cli/__init__.py` print `DECOY`. From the decoy cwd,
  `_run_picker_command` and `_popup-cmd` (CliRunner, non-tty path) produce no DECOY output,
  and the child's debug log shows `chosen_via=pm_root selected_root=<session root>`. Both
  tests fail on pre-fix code.
- Control: `python -m pm_core.wrapper` (plain `main`) from the decoy cwd still runs the decoy.
