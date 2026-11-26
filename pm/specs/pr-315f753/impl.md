# Implementation Spec — pr-315f753

## Root Cause (confirmed in task)

`pm_core/cli/pr.py:_launch_review_window` (line 1242) builds a header string
`f"Review: {display_id} — {title}"` and interpolates it raw into a
single-quoted shell `echo` at line 1253:

```python
diff_cmd = (
    f"cd '{workdir}'"
    f" && {{ echo '=== {header} ==='"
    ...
```

A title containing `'` (apostrophe) terminates the surrounding single-quote
early. The remainder of the title is then parsed as additional shell tokens.
Depending on contents:
- Some break the `&&` chain and exit the pane shell. With tmux's default
  `remain-on-exit off`, the window closes before `find_window_by_name` /
  `new_window_get_pane` can return its id → silent `click.echo` failure
  (stdout captured by review_loop) → "Review window not found after launch".
- Others produce a syntax error that doesn't kill the chain cleanly; the
  window opens but the diff pane content is garbled.

`workdir` is also interpolated unsafely (`cd '{workdir}'`) — same class of
bug for any path containing an apostrophe.

## Requirements

1. **R1 — Apostrophe-safe titles in diff_cmd.** `pm_core/cli/pr.py:1251-1264`
   must use `shlex.quote` on every user-controlled value
   (`workdir`, `header`/`title`) when building `diff_cmd`. After fix, a PR
   with a title like `Bug: pm pr start <new-pr> doesn't open` opens its
   review window and the diff pane renders correctly.

2. **R2 — Shell-meta-safe titles.** Same fix must cover dollar signs,
   backticks, parentheses, double-quotes, semicolons. `shlex.quote` handles
   all of these by enclosing in single quotes and escaping internal
   apostrophes.

3. **R3 — Diagnostic logging.** When `tmux_mod.new_window_get_pane` returns
   `None` at `pr.py:1275-1277`, emit a `_log.warning` with `window_name`,
   `pm_session`, and a hint pointing reviewers at unquoted user strings in
   the diff_cmd. Today the failure prints to a captured stdout and is
   invisible.

4. **R4 — Canonical helper.** Add `pm_core/shell.py` with at least a
   `shell_quote` re-export of `shlex.quote` so future shell-cmd
   construction has a single import surface. Use it in pr.py to make the
   intent explicit.

5. **R5 — Regression test.** A test that constructs a `diff_cmd` for a PR
   title containing apostrophes and shell metacharacters and verifies the
   resulting command string is syntactically valid (e.g. via
   `subprocess.run(['bash', '-n', '-c', diff_cmd])` or by asserting the
   relevant fragments are properly quoted). Optionally also a test asserting
   the warning log fires when `new_window_get_pane` returns `None`.

## Implicit Requirements

- Pre-existing call sites (`merge_cmd`, `claude_cmd` from
  `build_claude_shell_cmd`, etc.) already either pass through subprocess
  argv (no shell) or are constructed by other code paths. The audit
  confirms: only the diff_cmd in `_launch_review_window` interpolates
  user-controlled `title` into a shell string. `prompt_gen.py` uses titles
  in plain prompt text (not shell), so quoting is not required there.
- The header text shown in the diff pane should still display the
  apostrophe naturally (e.g. `=== Review: pr-001 — pr start <new-pr> ===`),
  not show shell-escaping artifacts. `shlex.quote` produces
  `'Review: pr-001 — pr start <new-pr>'` — once `echo` runs that, the user
  sees the unescaped string.
- `_log.warning` already imported via helpers; no new logger setup needed.

## Ambiguities

- **Scope of guardrail helper.** The task suggests a `build_shell_cmd(parts)`
  combinator. Given only one caller needs it today, I'll ship a minimal
  `pm_core/shell.py` with `shell_quote = shlex.quote` and a docstring
  noting the rule, deferring `build_shell_cmd` until a second caller
  appears. This matches the "no premature abstraction" guidance.
- **Lint rule.** Task mentions an "optional" grep-based lint rule. I will
  not add one — too much surface for too little signal, and the helper +
  test cover the regression risk.

## Edge Cases

- Title containing only ASCII letters: `shlex.quote` returns the string
  unchanged-ish (still wraps in `''` if it contains spaces). The diff_cmd
  remains valid.
- Empty title: `shlex.quote('')` returns `"''"`, valid.
- Title containing newline: `shlex.quote` handles by single-quoting; echo
  prints the literal newline character — minor cosmetic, not a bug.
- Workdir with apostrophe: now also safe via `shlex.quote(workdir)`.
- `display_id` is generated internally (e.g. `pr-001`) — safe in practice
  but quoting it costs nothing.

## Plan of work

1. Add `pm_core/shell.py` with `shell_quote`.
2. Edit `pm_core/cli/pr.py`:
   - Import `shell_quote`.
   - Rewrite `diff_cmd` to use `shell_quote(workdir)` and quote the entire
     header echo argument.
   - Add `_log.warning(...)` when `new_window_get_pane` returns None.
3. Add regression test: `tests/test_pr_review_window_quoting.py` — assert
   that constructing the diff_cmd with a hostile title produces a
   syntactically valid bash command.
4. Run targeted test, then full suite if quick.
