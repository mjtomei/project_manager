# Spec: prefix+M scrollable shell popup with shared history + completion

> Revised 2026-11-02 after merging origin/master@81e5d7f4 into the branch
> (2705 commits). The first draft was written against a much older
> `session.py`. Revisions: dispatch goes through master's
> `_session_pm_argv`; history is keyed by the tmux session tag, not the
> cwd; tmux popups have no copy-mode, so the popup keeps its own
> scrollback; Esc dismisses at the prompt; TUI Tab completion ships here
> rather than in a follow-up. The "Corrections to the first draft" section
> lists what changed and why.

## Requirements (grounded)

1. **Long-lived popup loop.** `popup_cmd_cmd` (`pm_core/cli/session.py`,
   `@cli.command("_popup-cmd")`) keeps its preamble: the registry check,
   the `PM_POPUP_SESSION` export, and `PM_PROJECT` from
   `_resolve_root_from_session`. It then hands off to
   `pm_core.cli.popup_shell.PopupShell(tag, root, dispatch).run()`. The
   loop reads a line, dispatches it, shows a dim `(status)` line, records
   history and transcript, and re-prompts. It ends on:
   - a lone **Esc** at the prompt;
   - **Ctrl-D** on an empty line;
   - `exit` / `quit`.

   Empty lines are no-ops. Ctrl-C at the prompt prints `^C` and
   re-prompts. Errors no longer pause on `_wait_dismiss`, because the next
   prompt leaves the message on screen. `_wait_dismiss` stays only on the
   "Not a pm session." path.

2. **Up/Down/Ctrl-R recall.** stdlib `readline` (`set_auto_history(False)`;
   the shell adds lines itself). Before each prompt the shell compares the
   shared file's signature (inode, mtime_ns, size). When it changed,
   readline's history is rebuilt from it. A command typed in the TUI bar
   is therefore recallable at the popup's next prompt, and reopening is
   not needed. (While a client's popup is open, that client's keys go to
   the popup, so it cannot type in the TUI bar in the meantime.)

3. **Shared persistence:** `pm_core/command_history.py`. It is a new
   module; `paths.py` is left unchanged because #278 (pr-073910f)
   rewrites much of it.
   - `history_path(tag)` → `~/.pm/sessions/<tag>/command_history`: one
     command per line, newest last, at most `HISTORY_CAP` = 1000 lines.
   - `append_history(cmd, tag) -> bool` and
     `read_history(tag, limit=None)`. `normalize_command` flattens any
     embedded newline.
   - Writers take `fcntl.flock` on a sidecar `<file>.lock` that is never
     replaced. A trim rewrites the file with tempfile + `os.replace`
     under that lock. Locking the data file itself would let a writer
     that is waiting on the old inode append to the unlinked file after
     a trim, losing its line.
   - Reads are lock-free. They see the old or the new file and drop blank
     lines.
   - **Tag source:** `tag_for_session(name)` strips `~N` and `pm-` from
     the tmux session name:
     - The popup passes `_session_tag_from_name(base)`, the same key
       `_resolve_root_from_session` uses.
     - The TUI bar passes `app._session_name`.
     - It is never derived from the cwd. The popup's cwd is often a PR
       workdir that hashes to a different tag.
     - With no tag, nothing is persisted, and both surfaces keep history
       in memory.

4. **Tab completion:** `pm_core/cli/completion.py`, class `PmCompleter(root)`.
   - `complete_line(text_before_cursor) -> (word_start, matches)` does not
     depend on readline, so the popup and the TUI bar share it.
   - It walks Click's tree from `pm_core.cli.cli`, generically (no
     hardcoded verb lists):
     - descends through groups;
     - skips options, consuming the value of value-taking options;
     - counts positionals.
   - Candidates at the cursor:
     - **Group:** public subcommand names. `_x` and `hidden=True` commands
       are skipped. At top level, `review-loop` is added: it is the
       popup/TUI carve-out, not a Click command.
     - **`-…`:** option names. `--opt=val` completes the values for that
       option.
     - **Positional named `pr_id` / `identifier`:** PR IDs, i.e. every
       internal `pr-xxxxxxx` plus `#N` from `gh_pr_number`
       (`_resolve_pr_id` accepts `#N`).
     - **Positional named `plan_id`:** plan IDs.
     - **`click.Choice`:** its choices.
     - **`--depends-on` / `--pr`:** PR IDs. `--depends-on` is a
       comma-separated list, so its last element is the one completed.
     - **`--plan`:** plan IDs.
     - **`review-loop [start] <PR>`:** PR IDs.
   - IDs come from `store.load(root, validate=False)`. They reload on the
     next Tab when `project.yaml`'s signature changes, so a PR added while
     the popup is open completes. A malformed YAML keeps the previous IDs.
     Completion never raises.
   - Popup readline setup:
     - delimiters: whitespace only, so `pr-` and `#` stay inside the word;
     - `TAB: menu-complete` with `show-all-if-ambiguous` and
       `menu-complete-display-prefix`. The first Tab lists the candidates
       and inserts their common prefix; later Tabs cycle;
       Shift-Tab (`\e[Z`) cycles back.
   - Popup root: `saved_root`, else `state_root()`.

5. **Scrollback.**
   - **No native scrollback:** a tmux popup is a bare `struct screen` with
     no history, copy-mode or scroll. The popup therefore keeps a bounded
     per-session transcript, `~/.pm/sessions/<tag>/popup_scrollback.jsonl`:
     - one JSON line per command:
       `{"ts", "cmd", "output", "status"}`;
     - at most `TRANSCRIPT_MAX_ENTRIES` = 200 entries and
       `TRANSCRIPT_MAX_BYTES` = 1 MB, dropping the oldest entries first;
     - each output cut to its last `TRANSCRIPT_MAX_OUTPUT_CHARS` = 64k
       characters behind a `[... N earlier characters omitted ...]`
       marker;
     - same locking as the history file.
   - **On entry:** the tail that fits the popup's rows is rendered, with a
     dim `... N earlier lines (PgUp to scroll back)` hint, then the
     banner.
   - **Opening it:** **PgUp** (readline macro
     `"\e[5~": "\C-e\C-v\C-_\C-m"`) submits the line with a `\x1f`
     sentinel; `:scrollback` does the same without the sentinel.
   - **Viewing it:** the loop opens the whole transcript in
     `less -R +G -K` with `LESS`/`LESSOPEN` stripped, so a user's `-F -X`
     cannot make it exit at once. Without `less`, a built-in pager handles
     PgUp/PgDn, ↑/↓, g/G and q.
   - **Afterwards:** the screen is redrawn and the half-typed line
     restored via a one-shot `set_startup_hook`.
   - **`:clear`:** empties the transcript.
   - **What is stored:** popup-only words (`exit`, `quit`, `:scrollback`,
     `:clear`) go into neither the shared history nor the transcript.
   - **Capture:** `_run_with_abort_keys(cmd, capture=list)` runs the child
     with stdout/stderr on a private pty sized like the popup. The child
     still sees a terminal, so its behaviour is unchanged. Each chunk is
     relayed live and appended to `capture`. After exit, the pty is
     drained for at most 1 s (a background grandchild may hold it open).
   - **Cleaning:** `command_history.clean_output` keeps SGR colours and
     drops other escapes. A carriage return overwrites its line, so
     spinners collapse to their last frame.
   - Without a tty (tests), the child inherits stdout/stderr as before and
     no output is captured.

6. **TUI command bar history** (`pm_core/tui/command_bar.py`):
   - **On submit:** `command_history.append_history`. On failure, or with
     no session tag, the command is kept in memory.
   - **On focus**, and when a recall starts from the bottom: re-sync from
     the file when its signature changed.
   - **Up/Down:** walk the history. The half-typed line is saved as a
     draft, and Down past the newest entry restores it. The cursor goes to
     the end of the line.
   - **Blur / submit:** both reset the walk.
   - **Event handling:** `on_key` stops these key events, so the app's
     bindings never see them.

7. **TUI Tab completion** (shipped here; the change turned out small).
   - **Mechanism:** `on_key` intercepts `tab` / `shift+tab` and stops the
     event, so the Screen's `focus_next` binding never fires. It then
     calls the same `PmCompleter(app._root).complete_line` on the text
     before the cursor.
   - **One match:** insert it plus a space.
   - **Several matches:** insert the common prefix and list up to 12 in
     the log line via `app.log_message("Tab: …")`. Repeated Tab /
     Shift-Tab cycles while the line is unchanged since the last
     completion step.
   - **No match:** `app.bell()`.

8. **Abort behaviour is kept.** Esc / Ctrl-C during a running command
   still kills the child's process group (SIGINT → SIGTERM → SIGKILL). The
   result is a dim `(aborted)` status and a return to the prompt; the
   popup stays open.
   - **Lone Esc at the prompt:** readline in Python runs in callback mode,
     where `keyseq-timeout` does not apply, so a bare Esc would wait
     forever for the rest of a sequence. `_LoneEscWatcher` adds a 50 ms
     `SIGALRM` tick while `input()` runs (with `siginterrupt(False)`, so
     only `select` sees EINTR). Through ctypes it reads
     `rl_readline_state & RL_STATE_MULTIKEY`, `rl_key_sequence_length`
     and `rl_executing_keyseq`. When only Esc bytes have been pending for
     ≥100 ms with no further input, the handler raises `_Dismiss`. Python's
     readline loop runs the handler on EINTR and cleans up the line before
     `input()` re-raises.
   - **What it leaves alone:**
     - Arrow and Alt sequences, which arrive in one burst.
     - A paused `C-x` prefix.
     - Esc inside a Ctrl-R search, which only ends the search.
     - vi-mode users: the bindings target the emacs keymap only.
   - **Esc then Enter typed quickly** is bound to `accept-line`; otherwise
     readline treats it as M-C-m, which switches to vi editing mode.
   - **Fallback:** without ctypes symbols or with libedit, Ctrl-D / `exit`
     still close the popup.

9. **Routing and dispatch are preserved.** `_popup_dispatch(session, cmd,
   parts)` keeps the dispatch shape:
   - `pr qa…` and `review-loop` / `review loop…` → `_run_picker_command(
     "tui:…", session, wait_on_error=False)`. The status is
     `sent to the TUI` or `TUI not reached`.
   - Everything else runs `_session_pm_argv(session, parts)` (master's
     session-code dispatch, so the popup's cwd/workdir pm_core is never
     used) through `_run_with_abort_keys(…, capture=…)`. The status is
     `exit N`, `aborted` or none.
   - `_run_picker_command` gains `wait_on_error: bool = True` and now
     returns `bool` (handed off / exit 0). Existing callers are unchanged.

## Implicit Requirements

- **Per-session isolation:** history and transcript files live under
  `~/.pm/sessions/<tag>/` and are keyed only by the tmux session's tag.
  Grouped views (`pm-x~2`) resolve to the base tag. A popup opened from a
  PR workdir uses its session's files.
- **No new dependencies:** only stdlib `readline`, `pty`, `fcntl`,
  `ctypes`, plus the existing click/textual/yaml.
- **TTY gating:** readline, the Esc watcher, output capture and the pagers
  are active only when stdin and stdout are ttys. CliRunner and
  `test_popup_session_code` keep the non-tty path, where the child
  inherits fds.
- **Click introspection:** `cli.commands` and nested `Group.commands`.
  Hidden commands are filtered by both the `_` prefix and `hidden=True`.
- **Coordination:**
  - #195 (pr-cfe24ea) only adds picker pane shortcuts in `_popup-picker`;
    the popup command path does not overlap.
  - #278 (pr-073910f) moves tmux to per-session servers. This PR adds no
    tmux calls of its own, and keeping `paths.py` unchanged avoids a
    conflict there.
- **No prompt changes:** no Claude prompts are added or changed, so there
  is no "full prompts" section.

## Ambiguities (resolved)

- **Dedup of consecutive duplicates?** No. Every submitted line is
  appended verbatim, which is out of scope per the task (bash default).
- **Which project data does completion use when the popup runs in a
  workdir clone?** The session's persisted root
  (`_resolve_root_from_session`, falling back to `state_root()`). The TUI
  uses `app._root`.
- **What counts as a command for history?** Non-empty submitted lines
  (stripped), including ones that fail or are aborted, and lines with
  invalid quoting. The popup-only words are excluded.
- **TUI Up with half-typed text?** The text is kept as a draft and
  restored by Down past the newest entry. This replaces the first
  draft's "clobber".
- **Case sensitivity?** Case-sensitive. IDs are lowercase hex / `#N`.
- **Should Esc at the prompt dismiss?** Yes. The task's Test section
  says "dismiss with Esc"; see requirement 8 for how.
- **Large candidate lists** (hundreds of PRs, e.g. `pr edit ` + Tab)?
  readline asks "Display all N possibilities?" past
  `completion-query-items` (default 100), as bash does. A typed prefix
  narrows the list.

## Edge Cases

- **Popup opened before any session dir exists:** `paths.session_dir`
  creates it.
- **Two concurrent popups (two clients):** appends serialize on the
  sidecar lock. Each popup re-reads history before its next prompt and
  re-renders the transcript at open. Tested with 4 processes × 40 appends
  racing trims: exactly the cap remains, with no torn lines.
- **`store.load` raises:** the completer logs it and keeps the previous
  IDs (none at first). The popup never crashes over project.yaml.
- **TUI `up`/`down`/`tab` already bound?** The Screen binds
  `tab → focus_next`. Stopping the event in `CommandBar.on_key` keeps it
  from `App._on_key`, so no binding runs.
- **A command switches windows** (`pr start`, TUI-routed `review-loop`):
  the popup stays open over the new window until dismissed. Before, it
  closed when the one command finished; staying open is inherent to a
  long-lived popup.
- **Child leaves a background process holding the pty:** the drain stops
  after 1 s and the master is closed. Later writes from the grandchild
  get EIO, just as they would against the closed popup.
- **Huge output:** shown live in full. The transcript keeps the last 64k
  characters.
- **A dispatch raises:** the error is shown and recorded with status
  `error`, and the loop continues.
- **Session-code dispatch (`_session_pm_argv`):** unchanged. The popup
  passes the raw tmux session name (`pm-x~N`), as before.

## Corrections to the first draft

- "tmux popup terminals support copy-mode scrollback" was wrong: popups
  have no history. Replaced by the transcript and pager (requirement 5).
- History helpers in `paths.py` keyed by `get_session_tag(start_path=…)`:
  that key could differ from the session's tag (share-mode hash, GitHub
  name lookup) and fell back to the cwd. Moved to
  `pm_core/command_history.py` and keyed by the session name.
- `flock` on the data file plus `os.replace` trim could lose appends
  (wrong inode). Replaced with a sidecar lock.
- `#<gh_pr>` used the `gh_pr` URL field. It now uses `gh_pr_number`.
- Completion candidates were hardcoded verb lists. It now walks the Click
  tree.
- The popup loop used `sys` without importing it (NameError on open).
  Fixed during the master merge, which also switched dispatch to
  `_session_pm_argv`.
- Completion data was "loaded once per invocation". It now reloads on a
  `project.yaml` change.
- TUI Tab completion was deferred to a follow-up. It ships here.

## Out of scope (per task)

- A PTY shell with interactive subprocesses (editors). Children still get
  `stdin=DEVNULL`; the output pty is for capture only.
- Fuzzy search or dedup beyond Ctrl-R.
- Removing the `pr qa` / `review-loop` carve-outs (pr-438028c).

## File touches

- `pm_core/command_history.py` *(new)*: history and transcript
  persistence, `clean_output`.
- `pm_core/cli/completion.py` *(new)*: `PmCompleter`, `common_prefix`.
- `pm_core/cli/popup_shell.py` *(new)*: `PopupShell`, `DispatchResult`,
  `_LoneEscWatcher`, pagers.
- `pm_core/cli/session.py`: `popup_cmd_cmd` handoff, `_popup_dispatch`,
  `_run_with_abort_keys(capture=)`, `_open_output_pty`, `_write_all`,
  `_run_picker_command(wait_on_error=) -> bool`.
- `pm_core/tui/command_bar.py`: history recall, draft, Tab completion.
- Tests:
  - `tests/test_command_history.py`
  - `tests/test_completion.py`
  - `tests/test_popup_shell.py` (unit tests and pty end-to-end tests of
    the real `_popup-cmd`: Esc, Up, Tab, PgUp, Ctrl-C, capture/abort)
  - `tests/test_command_bar_history.py` (Textual pilot)
