# QA spec — pr-71e9ec7: review diff pane falls back to `cat` when `less` is absent

## Change under test
`pm pr review <id>` (and every path that reaches it: the TUI review action,
the review loop relauncher `pm pr review --fresh --review-loop`, and
`pm pr review` on a PR that is already `in_review`) opens a tmux window
`review-<display-id>`. The window has two panes: the **diff pane** and the
**Claude pane** (with both live, pm layout puts Claude on the left and the
diff on the right; identify the diff pane by its `=== Review:` header). The diff pane shows the header `=== Review: <id> — <title> ===`,
then `git status`, then `--- Change summary ---` (diffstat), then
`--- Full diff ---`, and finally `exec $SHELL`.
Before the fix, this output was piped to a bare `less -R`. Now it goes through
`if command -v less …; then less -R; else cat; fi`. The check runs inside the
pane's own shell when the pane runs.

## Setup
- Follow `pm/qa/instructions/tui-manual-test.md`. Install pm from this branch
  (editable install, `PYTHONPATH` pointing at the clone, and `pm which` confirming
  the clone). Create a throwaway git project, then run `pm init --backend local --no-import`
  with an initial commit on `master`. Use `pm pr add` and `pm pr start <id>` to get a
  workdir, commit a recognisable change there (a new file with a distinctive line),
  and run `pm session`.
- Use fake-claude so that the Claude pane does not call a real model:
  `pm fake-claude config set '{"_all": {}, "review": {"verdicts": ["PASS"]}}'`.
- **Less-absent host:** make `less` unresolvable for the tmux server *before*
  `pm session` starts the server, because panes inherit the server's environment.
  In a throwaway container you can uninstall or rename the `less` binary.
  Alternatively, start the session with a `PATH` built from symlinks that leave out `less`.
  Confirm this by running `command -v less` in a pane of the test session and
  checking that it prints nothing.
- **Less-present host:** the stock environment. Install `less` if the container
  lacks it.

## Requirements
1. **R1 — diff visible without less (the bug).**
   Given a pm session on a host where `less` is not on PATH, and a started PR
   with committed changes,
   When the user opens the review window for that PR,
   Then the diff pane shows the review header with the PR id and title, the git
   status, the `--- Change summary ---` diffstat that names the changed file, and
   `--- Full diff ---` with the distinctive added line. After the output an
   interactive shell prompt appears in the same pane. The pane does not show
   `less: command not found`.
2. **R2 — pane survives and is usable after fallback.**
   Given R1's review window,
   When the user types a command into the diff pane (for example `git log --oneline -1`),
   Then the command runs in the PR workdir and prints its output. The pane and the
   window stay open, and the Claude pane is still present.
3. **R3 — pager behaviour unchanged when less exists.**
   Given a pm session on a host with `less` installed,
   When the user opens the review window,
   Then the diff pane shows the output inside the `less` pager (a pager
   prompt or `(END)`, colour preserved). When the user quits the pager, a shell
   prompt is left in the pane, and the pane and window are not killed.
4. **R4 — every launch path gets the fallback.**
   Given a less-absent host,
   When the review window is opened in any of these ways: directly from the CLI;
   from the TUI review action; by re-running review on an already `in_review` PR
   with `--fresh`; or by a review-loop iteration that relaunches the window,
   Then each freshly created diff pane shows the full diff text, followed by a shell.
5. **R5 — the bug no longer reproduces in the regression test.**
   Given the branch checkout,
   When the review-window quoting test module is run,
   Then the less-stripped-PATH test and the stand-in-less test pass. The
   pre-existing tests for hostile titles also pass.

## Edge Cases
- **E1 — hostile PR title.** Given a PR titled with an apostrophe, `$(…)`,
  backticks and `;`, on a less-absent host, when its review window is opened,
  then the window is created and the header shows the title literally. No injected
  command runs, and the diff is shown, followed by a shell.
- **E2 — git failure mid-chain.** Given a project where the diff base can't be
  resolved (for example a vanilla/github backend with no `origin/<base>` ref, or
  a local backend whose base branch was deleted), when the review window is opened
  without less, then the header, the status, and git's error text are visible in the
  pane, followed by a usable shell. The pane is not blank and not killed.
- **E3 — large diff.** Given a diff that is much longer than the pane on a
  less-absent host, then the output scrolls past and the tail is visible. The
  beginning (header) is reachable through tmux copy-mode scrollback. This is
  accepted behaviour, the same as the sign-off precedent.
- **E4 — non-bash `$SHELL`.** Given `SHELL=/bin/sh` (dash) or zsh, when the
  review window opens on a less-absent host, then the diff still renders and
  `exec $SHELL` leaves that shell.
- **E5 — less appears/disappears between launches.** Given a review window
  opened without less, when less is installed and the review is re-opened with
  `--fresh`, then the new pane uses the pager. The reverse also holds. The
  decision is made per launch, at pane runtime, and is not cached.

## Concurrency
Shared resources: the tmux server/session (`pm-<tag>`), window names
`review-<id>`, the pane registry file for the session, each PR's workdir,
and `project.yaml` (status flip to `in_review`).
- **C1.** Given two started PRs on a less-absent host, when the user opens
  both review windows at the same time from two panes, then two distinct
  windows exist, and each diff pane shows its own PR's header and diff (not the
  other PR's). Both PRs become `in_review`. The pane registry lists the review
  panes of both windows.
- **C2.** Given a review window that is already open, when the user re-opens it
  with `--fresh` from two grouped sessions at once (or once while another
  session watches it), then exactly one `review-<id>` window remains. Its diff
  pane is populated, and the watching session follows it to the new window.

## Pass/Fail Criteria
- PASS: in every less-absent case the diff pane contains the header, the diffstat
  and the full diff text, and ends at a live shell prompt. In less-present cases
  the pager is used and quitting it leaves a shell. No window is missing, and no
  diff pane is blank or killed.
- FAIL: a blank diff pane that shows only a prompt, `less: command not found`, a
  missing review window, a pane that dies after its output, or the wrong PR's diff
  in a pane during concurrent launches.

## Ambiguities (resolved)
- *How should "less absent" be simulated?* The fallback is evaluated in the
  pane's shell, which inherits the tmux server's environment. So `less` must be
  missing for the tmux server itself, not only for the shell that runs `pm`.
  Resolved: remove or rename `less` in the throwaway container, or start the
  session with a stripped PATH.
- *Will the Claude pane interfere?* Resolved: fake-claude drives the Claude
  pane deterministically. This PR does not change the Claude pane.
- *Is broken-but-present `less` in scope?* No. `command -v` only checks
  resolvability, as decided in impl.md.

## Updates after QA run 1 (2026-10-12)
Consistency check against current code and PR notes:
- The cat fallback is now `cat; echo; echo` (8282a632). Two blank rows
  follow the diff so that a readline redraw when the pane widens (Claude pane
  exits, wider client attaches) cannot overwrite the last diff line (this was
  pr-e308f3f). Every less-absent check must also resize or widen the pane and
  confirm that the last `+` diff line is still visible.
- fake-claude verdict sessions with no session_id now stay open when stdin is
  a tty. So a manual `pm pr review` window keeps both panes, and the pane registry
  keeps its review-claude entry. Non-tty CLI use still exits immediately.
- `pane_current_command` of the diff pane is `bash`, not `less`, because less is
  a grandchild. To verify the pager, use the process tree or `(END)` on screen.
- The fake-claude scripted-verdict cursor persists across launches. Use weighted
  `{"PASS":100}` for non-loop launches, and switch to `["NEEDS_WORK","PASS"]`
  right before a review loop.
- The stock pm-dev container has no `less`. To get a less-present host, run
  `sudo apt-get install -y less`. This takes effect without restarting tmux.
- Run 1 verdicts: R1/R2/R3/R5 PASS. R4 and C1/C2 were NEEDS_WORK only because
  fixes landed mid-run (the padding and the tty hold). Run 2 re-verifies them on
  the fixed branch and adds E1, E2, E4 and E5, which run 1 did not cover.

## Run-2 scenarios (detail behind the short QA_PLAN lines)
- **S5 — every launch path plus edge cases, on a host without less.**
  Story A: open the review window four ways: CLI `pm pr review`, TUI `d`,
  `--fresh` on an `in_review` PR, and a `zz d` review loop with fake verdicts
  `["NEEDS_WORK","PASS"]` so the loop relaunches the window. For each window,
  check the header, diffstat, the distinctive `+` line, two blank rows, and a
  live shell. The Claude pane must stay open. Resize or widen the window and the
  last `+` line must survive. There must be no `less: command not found`.
  Story B (edge cases): E1 hostile title; E2 unresolvable diff base, where git's
  error is visible followed by a shell; E3 large diff, where the header is
  reachable in copy-mode; E4 `SHELL=/bin/sh`; E5 install less and run
  `--fresh`, which gives the pager, then remove less and run `--fresh`, which
  gives cat. Also re-run `tests/test_review_window_quoting.py` (R5).
- **S6 — concurrent launches, on a host without less.** Open review windows for
  two PRs at the same moment from two panes or clients. Each window has 2 panes
  with its own PR's diff, both PRs are `in_review`, and the registry lists all
  four panes. Then run two `--fresh` of one PR at once from grouped sessions:
  exactly one `review-<id>` window must remain, with a populated diff pane, and
  the watching session must follow it. pr-3f85ad7 (duplicate window race) is a
  known separate bug; record it, don't fail on it.
