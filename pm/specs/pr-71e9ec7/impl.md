# pr-71e9ec7 — review diff pane: fall back to `cat` when `less` is absent

## Requirements
1. `pm_core/cli/pr.py:_launch_review_window` builds `diff_cmd` (the left
   pane of the review window), ending `...; }} | less -R; exec $SHELL`.
   Replace the bare `| less -R` with the guard used by pr-2d5f712
   (commit 771d84b3, signoff evidence pane):
   `| if command -v less >/dev/null 2>&1; then less -R; else cat; fi`.
   When `less` is absent the header/status/diffstat/diff are printed with `cat`
   to the pane's scrollback, and then `exec $SHELL` leaves an interactive shell.
2. A regression test in `tests/test_review_window_quoting.py` runs the
   captured `diff_cmd` (with the trailing `exec $SHELL` removed) under bash
   with PATH stripped of `less`, against a real git repo, and asserts the
   output contains the header/diff text. This test fails on the pre-fix code
   because the output is empty and the shell prints "less: command not found".

## Implicit Requirements
- The guard must be evaluated at pane run time, inside the pane's shell (the
  container or host where the pane runs), not at Python build time. The diff
  pane runs on the host; the claude pane may be containerised. A
  `shutil.which` check in Python would test the wrong environment if these
  ever diverge, so the guard stays in shell.
- The command must still pass `bash -n` for hostile titles (existing tests).
- When `less` is present, behaviour is unchanged (`less -R`, so quitting the
  pager does not kill the pane).

## Ambiguities
- Note: `signoff._evidence_pane_cmd` no longer exists on master (the evidence
  pane was removed in f907a1d5). The guard text is taken from 771d84b3
  verbatim. Resolved: inline the guard in pr.py. No shared helper, because
  there is only one call site.
- With `cat`, a long diff scrolls past. Resolved: acceptable. tmux
  copy-mode scrollback is available, and this matches the sign-off precedent.

## Edge Cases
- `less` exists but is not executable or is broken: out of scope.
  `command -v` only checks resolvability.
- Non-bash `$SHELL` running the pane command: `command -v` and `if/then/fi`
  are POSIX, so this is fine in sh/dash/zsh.
- The git commands fail (for example, a missing `origin/<base>`): the `&&`
  chain inside the braces stops early, the partial output still reaches the
  pager or `cat`, and the result is unchanged from the old behaviour.
