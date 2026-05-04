# Implementation Spec — pr-cfe24ea

## Requirements

Add three picker shortcuts that open a split pane in the *launching window*
of the prefix+P picker, each acting on the highlighted PR:

1. **`c`** — shell pane in the PR's workdir.
2. **`i`** — view `pm/specs/<pr_id>/impl.md`.
3. **`Q`** — view `pm/specs/<pr_id>/qa.md`.

The picker dispatches via `pm_core/cli/session.py::popup_picker_cmd`, which
already routes existing shortcuts (`s/e/d/t/g`) through
`_run_picker_command`. The new shortcuts won't go through `_label_to_cmd`
(which is built from `_ALL_ACTIONS` for windowed phase actions); they
will dispatch to a new helper that performs the split.

### Code anchors

- `pm_core/cli/session.py:1641` — `_SHORTCUT_KEYS` table.
- `pm_core/cli/session.py:1682` — `_make_fzf_cmd`; binds non-expect alphas
  to `ignore`.
- `pm_core/cli/session.py:1707..1810` — chord state machine and dispatch.
- `pm_core/cli/session.py:1529` — `popup_picker_cmd(session, window_name)`;
  `window_name` is the *name* (not id) of the window that launched the
  picker (set by `_POPUP_PICKER_BODY`).
- `pm_core/tmux.py:77` — `split_pane(session, direction, cmd, window=None)`
  already supports a window target via `session:window` syntax. Will
  reuse this rather than calling tmux directly.
- `pm_core/pane_registry.py:174` — `register_pane(session, window_id, …)`;
  `window` arg is the tmux window id (e.g. `@5`).
- `pm_core/spec_gen.py:67` — `spec_file_path(root, pr_id, phase)` returns
  `<root>/specs/<pr_id>/<phase>.md`. Used to resolve impl/qa paths.
- `pm_core/cli/pr.py:642` — existing `pm pr spec-path` already exposes
  the path; reusing the underlying `spec_gen.spec_file_path` is simpler
  and avoids subprocess overhead in the dispatch.
- Workdir lookup: PR's `workdir` field, same field used by `pr_cd` at
  `pm_core/cli/pr.py:484`.

## Implicit Requirements

- `c`, `i`, `Q` must be **excluded from the `--bind=*:ignore` set** in
  `_make_fzf_cmd`, i.e. they must appear in the `expect` list, otherwise
  fzf will swallow them silently.
- Must avoid collision with: `q` (abort), `s/e/d/t/g` (action shortcuts),
  `z` (chord prefix), `h/l/0` (PR navigation). `c`, `i`, `Q` clear all.
- The popup process must exit promptly after launching the split, so the
  display-popup overlay closes — same pattern as existing shortcuts.
- Split is performed against the *launching window* (resolved by name in
  the picker session `base`), not the popup itself (the popup is in
  another transient session/pane).
- For the spec viewers, the workdir is *not* required — specs live under
  the project pm-root regardless of PR state.
- The popup runs inside the project root (env var `PM_PROJECT` is set
  earlier in `popup_picker_cmd`); resolve `root = saved_root or
  state_root()` the same way for spec paths.

## Ambiguities & Resolutions

- **Spec lookup root.** `spec_gen.get_spec` checks the PR workdir first
  then the local pm-root; raw path lookup uses only one of them. For
  the viewer pane we want the canonical merged-back path
  (`spec_gen.spec_file_path(root, …)`) when the workdir copy is missing,
  but prefer the workdir copy when present so an in-flight PR's
  freshly-generated spec is visible. Resolution: try
  `<workdir>/pm/specs/<pr_id>/<phase>.md` first, fall back to
  `spec_file_path(root, …)`. Mirrors `get_spec`'s lookup order.
- **Split direction.** Spec says "horizontal when current pane is wider
  than tall". The picker doesn't know the current pane's geometry
  (popup runs detached). Resolution: omit the explicit `-h`/`-v` and
  let tmux pick its default (which uses split on the *active pane* —
  but we're targeting the window, not a specific pane, so tmux uses
  the active pane within the window). Use `direction='h'` consistently
  via `split_pane` since horizontal is the more common useful split for
  reading specs and shell next to existing panes; this matches how
  most layouts in the project look. (Acceptable per spec: "Tmux's
  default split is acceptable too.")
- **Pane registry role values.** Use `pr-shell`, `pr-impl-spec`,
  `pr-qa-spec` per the task description.
- **Pane cleanup.** Tmux already kills panes when their parent window
  closes; the registry entry becomes stale but is cleaned by the
  existing window-removal sweep. No extra plumbing needed.
- **Use `pm pr cd <pr_id>` vs raw `cd <workdir>`.** `pm pr cd` does
  `os.execvp(SHELL)` after chdir, which is fine for an interactive
  pane but adds a startup banner the user doesn't need every time.
  Resolution: pass `bash -c 'cd <workdir>; exec $SHELL'` directly —
  one less subprocess hop, cleaner shell startup. Falls back to
  `/bin/bash` if `$SHELL` is unset in the new pane.

## Edge Cases

- **No workdir for shell.** Show "PR has no workdir; start it first" in
  the popup briefly via `_wait_dismiss`, no pane created. Mirrors
  existing error-popup pattern.
- **Spec file missing.** Show "No <phase> spec for <pr_id> — run
  'pm pr spec <pr_id> <phase>' first." No empty pane.
- **`glow` not installed.** Use shell short-circuit:
  `(command -v glow >/dev/null && glow -p PATH) || less -R PATH ||
  { cat PATH; read; }`. Silent fallthrough.
- **Picker invoked from a non-PR window with no `home_pr`.** The picker
  still navigates among PRs that have open windows. The new shortcuts
  act on `_picked_pr` (whatever is highlighted/navigated), so they
  work fine even when the launching window isn't a PR window. The
  split lands in the launching window (e.g. the main TUI window), as
  the task description allows: "Works whether the picker was opened
  from an impl window, review window, QA window, or the main TUI
  window — same pane gets created in whichever window the picker
  fired in."
- **Path quoting.** Workdir / spec paths may contain spaces. Use
  `shlex.quote` when interpolating into the shell command.
- **fzf abort behavior.** Existing `q` abort path unchanged; new keys
  return from the chord state machine via the main-state break.

## Files Changed

- `pm_core/cli/session.py` — add `_PANE_SHORTCUT_KEYS`, dispatch helper
  `_open_pane_in_window`, integration into the chord state machine, and
  expect-list / shortcut hint updates.

No changes needed in `pm_core/cli/pr.py` — `spec_gen.spec_file_path`
already exists and `pm pr spec-path` is unchanged.
