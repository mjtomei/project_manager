# Implementation Spec — pr-cfe24ea

## Requirements

Add four picker shortcuts to the prefix+P picker and matching CLI commands,
so the same pane operations work from prefix+P, prefix+M (popup-cmd) and a
shell inside a pm session.  Each opens a split pane in the *current* window
for the selected PR:

1. **`c`** — shell in the PR's workdir. CLI: `pm pr shell <pr_id>`.
2. **`o`** — view the impl spec (`pm/specs/<pr_id>/impl.md`).
   CLI: `pm pr view-spec <pr_id> [--kind impl]`.
3. **`u`** — view the QA spec (`pm/specs/<pr_id>/qa.md`).
   CLI: `pm pr view-spec <pr_id> --kind qa`.
4. **`y`** — view the PR diff against its base branch (the review window's
   diff-pane content). CLI: `pm pr view-diff <pr_id>`.

Key history: the task suggested `i`/`Q`/`D`; the branch later moved to
lowercase one-handed keys (`u`, `y`).  Master has since bound `i` to
**sign-off** (phase shortcut, also `z i` = fresh sign-off), so impl-spec
moved to `o` during the 2026-11-02 master integration.  `o` is unused in
every chord state; the pane keys avoid `q` (quit), the phase shortcuts
`s/e/d/t/i/g`, `z` (chord) and `h/l/0` (navigation).

### CLI parity (one code path)

- All three commands go through `pr.py::_run_pr_pane_action(pr_id, kind)`:
  `state_root()` → `store.load` → `_require_pr` (which uses
  `_resolve_pr_id`), so pm ids (`pr-f5b7eef`), `#193` and `193` all work and
  an unknown id prints `_require_pr`'s error.
- The picker does **not** open panes in-process: `c/o/u/y` dispatch the CLI
  command through `_run_picker_command` (`pr shell <pm-id>`,
  `pr view-spec <pm-id> --kind impl|qa`, `pr view-diff <pm-id>`), using the
  resolved pm id.  prefix+M runs the same commands, and so does a typed
  shell.  Table: `session.py::_PANE_SHORTCUT_KEYS` / `_PANE_ACTION_CMDS`.
- **In a pm session** (`_get_current_pm_session()` is not None — the
  caller's tmux session is, or is grouped with, a `pm-` session): open a
  pane in the caller's current window via `_open_pane_for_pr`.
  **Anywhere else** (no tmux, or a non-pm tmux session): print instead —
  `view-spec` prints the file, `view-diff` runs the diff pipeline without
  pager/exec (exit status propagates), `shell` execs `$SHELL` in the workdir
  (as `pm pr cd`).  `_get_pm_session()` is not used for this test: outside
  tmux it falls back to the cwd project's session name, which would make a
  plain shell try to split panes.

### Current window (the launching client/window)

`_caller_window_id()`:
- from a pane: the window of `$TMUX_PANE`;
- from a popup (no pane): the popup dispatchers export the opening client's
  session as `PM_POPUP_SESSION`; `tmux_mod.get_session_name()` returns it and
  the target is `=<session>:` (exact name), i.e. that client's current
  window — the one the popup was opened over.  This matters for grouped
  views (`pm-x~2`): the base session's current window can be a different
  one.

All tmux calls go through `tmux_mod._tmux_cmd` / `tmux_mod` helpers, so they
honour the server-scoped `PM_TMUX_SOCKET` targeting.  (#278 / pr-073910f,
per-session tmux servers, is not merged yet; when it lands, re-check these
calls against its interfaces during integration.)

### Shared pane opener

`pr.py::_open_pane_for_pr(session, window_id, kind, cmd, cwd=None)`:
- queries the window's active pane id + size; splits that pane with
  `tmux_mod.split_pane_at` (`-c <workdir>` for the shell);
- direction: side by side (`h`) when the active pane is *physically* wider
  than tall, stacked (`v`) otherwise — `pane_layout.split_direction(w, h)`,
  the same `w >= 2h` rule `preferred_split_direction` uses for windows
  (terminal cells are ~2x taller than wide);
- registers the pane under the base session with role `pr-shell`,
  `pr-impl-spec`, `pr-qa-spec` or `pr-diff`; rebalances via
  `pane_layout.register_and_rebalance` unless the window was already
  `user_modified` (hand-arranged), in which case it only registers;
- runs the command under the TUI's pane-exit trap
  (`pm _pane-exited <base> <window> <generation> $TMUX_PANE`), with the
  command as a child `bash -c` so the trailing `exec` of the shell/diff panes
  cannot replace the trapping shell.  Pane close → unregister + rebalance.
  Closing the parent window kills the pane (tmux) and fires the trap.
  (`tui.pane_ops._wrap_pane_cmd` is equivalent but importing it pulls in
  Textual, so the CLI has its own small wrapper.)

### Pane commands

- **shell:** `cd <workdir> && exec "${SHELL:-/bin/bash}"`.  Raw `cd`
  rather than `pm pr cd`: no banner, and no re-resolution of the project
  from the pane's cwd.
- **spec viewer (read-only):** `export LESSSECURE=1; { glow -p F } ||
  { less -R F } || { cat F; printf '\n[press any key to close]'; read -r -n 1 -s; }`,
  each step guarded by `command -v`, so a missing `glow` falls through to
  `less` silently and a missing `less` to `cat` + keypress.  `LESSSECURE=1`
  disables less's editor/shell/pipe/log commands; `glow -p` pages through
  less too.  View only — no edit mode.
- **diff:** `_build_diff_cmd`, the single builder also used by
  `_launch_review_window` for the review window's diff pane — byte-identical
  to master's former inline pipeline (header, `git status`, change summary,
  full diff of `origin/<base>...HEAD`, or `<base>...HEAD` for the `local`
  backend; piped to `less -R`, or `cat` + two blank rows when less is
  missing; then `exec $SHELL`).

### Spec lookup

`_resolve_spec_path`: the workdir copy `<workdir>/pm/specs/<id>/<phase>.md`
first, then `spec_gen.spec_file_path(state_root(), id, phase)` — the same
order as `spec_gen.get_spec`.  An empty (whitespace-only) file counts as
missing, as it does for `get_spec`.

## Edge Cases

- **No workdir:** only `shell` requires it (`PR <id> has no workdir; start it
  first.` / `Workdir for <id> does not exist: <path>`).  Specs don't.  The
  diff viewer falls back to the PR branch in the project repo
  (`_resolve_repo_dir`): `refs/remotes/origin/<branch>`, then
  `refs/heads/<branch>` (`local` backend: heads only), shown without the
  `git status` block (it would describe the project repo).  No branch ref
  either → `No diff for <id>: it has no workdir and branch '<branch>' is not
  in <repo>; start the PR first.`
- **Spec missing/empty:** `No <phase> spec for <id> — run 'pm pr spec <id>
  <phase>' first.`, exit 1, no pane.  From the picker the error shows in the
  popup (`_run_picker_command` prints stderr and waits for dismiss).
- **Window not resolvable / split fails** (e.g. tmux "no space for new
  pane"): clear error, exit 1.
- **Picker, PR changed while open:** a pane key refreshes first (same
  `_refresh_selected` used by phase actions); a PR that vanished or a failed
  refresh runs nothing and the rows explain why.
- **Picker, merged/closed PR:** no phase actions, but the read-only pane keys
  stay available (the CLI serves them for any status, and parity across the
  three entry points was the goal).  Enter remains ignored; the keys are
  advertised in the header (`pane: c=shell  o=impl-spec  u=qa-spec  y=diff`).
  An unresolvable PR gets no pane keys.
- **Picker without fzf:** the numbered fallback accepts the pane keys too
  (`Panes: …`; prompt `Pane key:` when the PR has no phase actions).
- **Mobile-width windows:** the layout manager zooms the new pane (existing
  rebalance behaviour), which suits a narrow client.
- **Paths:** workdir/spec paths and titles are `shell_quote`d.

## Files Changed

- `pm_core/cli/pr.py` — `pm pr shell`, `pm pr view-spec`, `pm pr view-diff`;
  `_run_pr_pane_action`, `_pr_pane_command`, `_print_pr_pane_content`,
  `_open_pane_for_pr`, `_caller_window_id`, `_pane_exit_trap_cmd`, builders
  (`_build_diff_cmd` with `head_ref`, `_build_spec_viewer_cmd`,
  `_build_shell_at_workdir_cmd`), `_resolve_spec_path`, `_diff_cmd_for_pr`;
  `_launch_review_window` uses `_build_diff_cmd`.
- `pm_core/cli/session.py` — `_PANE_SHORTCUT_KEYS` / `_PANE_ACTION_CMDS`;
  picker header line, `--expect` keys, dispatch through `cmd_to_run`,
  `_refresh_selected` (shared with `_still_has_action`), no-fzf fallback.
- `pm_core/pane_layout.py` — `split_direction(width, height)` extracted from
  `preferred_split_direction`.
- Click registers the commands on the `pr` group, so they appear in
  `pm pr --help`; no change to `pm_core/cli/__init__.py` is needed.

## Tests

- `tests/test_popup_picker.py::TestPickerPaneKeys` — each key dispatches its
  CLI command with the pm id; header/expect; `i` still runs sign-off; merged
  PR keeps pane keys only; unresolvable PR has none; refresh-before-dispatch;
  no-fzf fallback.
- `tests/test_pr_pane_actions.py` — id forms; stdout mode for all four;
  missing/empty spec; workdir-first lookup; workdir-less diff fallback;
  in-session dispatch; caller-window resolution (pane and popup); opener
  direction/role/trap/hand-arranged; trap survives `exec`; viewer
  fall-through with stub `glow`/`less` and `LESSSECURE`; diff command
  byte-identical to master's review pipeline; real isolated tmux server
  (private socket + HOME): shell pane cwd = workdir + registry role + exit
  trap, stacked spec pane with the cat fallback closing on a key, and a
  popup in a grouped view landing in that view's window with the diff.
- `tests/test_review_window_quoting.py` — the review window's diff pane
  command equals `pm pr view-diff`'s.

## Out of scope

- Live refresh of the diff pane; spec editing.
