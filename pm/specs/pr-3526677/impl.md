# Spec: prefix+M scrollable shell popup with shared history + completion

## Requirements (grounded)

1. **Long-lived popup loop.** `popup_cmd_cmd` in `pm_core/cli/session.py:1867`
   currently does a single `input("pm> ")`, dispatches one command via
   `_run_with_abort_keys` (1924) or `_run_picker_command` (1472), and
   exits. Replace with a `while True:` loop that reads, dispatches,
   prints output, and re-prompts until the user dismisses with Ctrl-D.
   The tmux popup itself stays open for the duration; existing
   `_wait_dismiss` calls become no-ops in the loop case (the loop *is*
   the wait).

2. **Up/Down/Ctrl-R recall.** Use Python's stdlib `readline` module
   inside the popup's input loop. `readline` gives Up/Down arrow history
   walk, Ctrl-R reverse-search, and basic line editing for free. Hook
   `readline.read_history_file` on entry and
   `readline.append_history_file` after each `input()` call.

3. **Shared persistence.** Single newline-separated file at
   `~/.pm/sessions/<tag>/command_history`. Tag is resolved via
   `pm_core.paths.get_session_tag` (already used to build session_dir).
   Both popup and TUI command bar read on mount and append on submit.
   Add helpers in `pm_core/paths.py`:
   - `command_history_file(tag=None) -> Path | None`
   - `append_command_history(cmd, tag=None)` — locks, appends, trims if
     >`HISTORY_CAP` (1000) lines.
   - `read_command_history(tag=None, limit=200) -> list[str]`
   File-locking with `fcntl.flock` keyed on the file itself; reads are
   lock-free (a partial read on race is acceptable — last line may be
   missed, history isn't authoritative).

4. **Tab completion.** Build `pm_core/cli/completion.py` with a single
   `PmCompleter` class that takes a `saved_root: Path | None`:
   - Top-level token: completes against
     `pm_core.cli.session.cli.commands.keys()` (Click's command tree).
   - After `pr`, `pr edit`, `pr review`, `pr show`, `pr qa`,
     `review-loop start`: completes PR IDs from
     `store.load(saved_root)['prs']` — both internal `pr-xxxxxx` IDs
     and `#<gh_pr>` for entries that have a `gh_pr` field.
   - After `plan` subcommands or `--plan=`: completes plan IDs from
     `data['plans']`.
   - After `--depends-on=`/`--depends-on `: completes PR IDs.
   - Loaded once per popup invocation (the popup's lifetime is short
     enough that PRs added during that session can be picked up by
     manually re-opening; an in-loop refresh after every command runs
     `store.load` again — cheap, bounded by the pm root).
   Wire into readline via `readline.set_completer` and
   `readline.parse_and_bind('tab: complete')`. Set
   `readline.set_completer_delims(' \t\n')` so `pr-` and `#` are part
   of the token.

5. **Scrollback.** tmux popup terminals support copy-mode scrollback
   already (mouse-wheel or tmux's prefix `[`). The popup buffer is
   simply the rendered terminal — no in-process ring buffer needed.
   Don't use the alternate screen / curses; just print normally.
   Page Up/Down inside the popup is a tmux concern — document that the
   user enters copy-mode; do not try to implement custom paging that
   conflicts with tmux's.

6. **TUI command bar history.** Extend `pm_core/tui/command_bar.py`:
   - On submit (`on_input_submitted`), call
     `paths.append_command_history(command)` before clearing `value`.
   - On focus, load history into `self._history` (list[str]).
   - On `Up`/`Down` keys when bar has focus, walk `self._history` and
     set `self.value`. Override `on_key` (currently only logs).

7. **Tab completion in TUI.** Textual's `Input` doesn't expose readline.
   Implementing fuzzy popup completion in Textual is non-trivial.
   **Defer to follow-up PR** per the spec's explicit out-of-scope
   clause ("If wiring it into Textual is non-trivial, ship the
   popup-side completer in this PR and follow up with the TUI bar").
   Note left in PR description.

8. **Preserve abort behavior.** `_run_with_abort_keys` stays — the loop
   calls it per command. Esc / Ctrl-C aborts the *running* command and
   returns control to the prompt (does not exit the popup). Ctrl-D at
   the prompt exits the popup. Empty Enter is a no-op (re-prompt).

9. **Preserve TUI routing.** The `tui:`-prefixed routing for `pr qa`
   and `review-loop` (lines 1903–1907) still dispatches via
   `_run_picker_command`. After it returns, the popup loop continues.

## Implicit Requirements

- **Tag resolution from popup**: popup runs with `cwd` possibly outside
  the repo, but `_resolve_root_from_session(session)` already returns
  the persisted root. The session_tag for the history file should match
  the *base* tmux session's tag, not the popup's cwd-derived one. Use
  `pane_registry.base_session_name(session)` then look up its
  session_tag. Fallback chain:
  1. `get_session_tag(start_path=saved_root)` if saved_root exists.
  2. Else `get_session_tag()` (cwd-based).
  3. Else skip history persistence (still allow the popup to function
     in-memory for the loop's lifetime).

- **TTY assumptions**: `readline` requires a real tty. The popup is run
  via tmux `display-popup -E` which gives a pty — confirmed. Tests run
  non-interactively; gate readline initialization on
  `sys.stdin.isatty()`.

- **History file growth**: cap at 1000 lines (constant in paths.py).
  Trim is "read all, keep last 1000, atomic-replace via tempfile +
  os.replace" under flock.

- **Concurrent appends**: `fcntl.flock(f, LOCK_EX)` on append — small
  appends complete fast; lock contention is negligible. Reads do not
  lock (acceptable race: last byte may be a partial line; we filter
  empty lines on read).

- **Click command introspection**: `cli.commands` returns the dict of
  registered subcommands. Public ones only — filter out names starting
  with `_` (hidden internal commands like `_popup-cmd`).

- **Completion delimiter set**: default readline delims include `-`
  and `#`; we override with just whitespace so `pr-abc123` and `#42`
  are single tokens.

## Ambiguities (resolved)

- **History dedup of consecutive duplicates?** The task says "out of
  scope: dedup beyond Ctrl-R". Resolution: append every submit verbatim,
  no dedup (matches bash default `HISTCONTROL=` unset).

- **Where does PR ID list come from when popup runs in a workdir
  clone?** `_resolve_root_from_session` already returns the base pm
  root from the session registry — the same path used for `PM_PROJECT`.
  Use it for both completion and history tag.

- **What counts as a "command" for history?** Only non-empty submitted
  lines (after `.strip()`). Aborted commands (Esc) still count if a
  line was submitted; the user typed it.

- **TUI bar history walk: clobber current text?** Yes — that's the
  standard readline UX. If the user has typed text and presses Up,
  it's replaced. (Bash saves the current line as a "scratch" entry;
  too much complexity for this PR — skip.)

- **Completion case sensitivity?** Case-sensitive; PR IDs are lowercase
  hex — matches user typing patterns.

## Edge Cases

- **Popup opened before any session_dir exists**: `session_dir()`
  creates it eagerly via `mkdir(parents=True, exist_ok=True)` (paths.py
  :137). Safe.

- **Two concurrent popups from two clients**: both use the same
  history file. flock serializes appends. After popup A submits,
  popup B's next reads the appended line on next prompt only if we
  reload — the loop reloads history *only* on entry by default; for
  this PR, accept that cross-popup visibility requires re-opening or
  pressing Up after a small delay (readline's history is in-memory).
  Refresh on every prompt by calling `readline.clear_history()` +
  `read_history_file` adds noticeable lag for large files; defer.

- **History file from a different pm version with stale entries**:
  fine — it's just a list of strings.

- **`store.load` raises `ProjectYamlParseError`**: completer catches
  and returns no completions silently (don't crash the popup over a
  malformed project.yaml).

- **TUI bar Up arrow already used by Textual `Input`?** Default `Input`
  doesn't bind Up/Down. Confirm by overriding `on_key` and consuming
  the event with `event.stop()` only when we handle history.

- **Existing popup uses `_wait_dismiss` after errors** (line 1918) so
  the user can read the error before the popup auto-closes. In the
  long-lived loop, the prompt itself is the wait — error output stays
  on screen until the user types another command or Ctrl-D's out. No
  separate `_wait_dismiss` needed inside the loop. Keep it for the
  pre-loop "Not a pm session" path (line 1878).

- **`pr qa` / `review-loop` TUI routing** ends the picker dispatch in
  a separate code path (`_run_picker_command`) which itself signals the
  TUI. After it returns, the popup loop should *continue*, not exit —
  user may want to dispatch more commands.

## Out of scope (per task)

- PTY-based interactive subprocess (no editors in popup).
- Fuzzy / dedup history.
- Tab completion in TUI command bar (follow-up PR).
- In-loop refresh of completion data after every dispatch (loaded
  once per popup invocation).

## File touches (planned)

- `pm_core/cli/session.py` — rewrite `popup_cmd_cmd` body as a loop;
  init readline + completer.
- `pm_core/cli/completion.py` *(new)* — `PmCompleter`.
- `pm_core/paths.py` — add `command_history_file`,
  `append_command_history`, `read_command_history`.
- `pm_core/tui/command_bar.py` — wire history append on submit,
  Up/Down recall on key.
- Tests: `tests/test_command_history.py` covering append/read/trim
  and concurrent-append flock behavior.
