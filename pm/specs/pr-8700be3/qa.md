# pr-8700be3 — QA spec: compact, highlighted autostart status

Surfaces under test: `pm autostart status` (text, `--width`, `--color/--no-color`,
`--json`) served by the owner TUI over the request/reply channel, and the TUI
runs popup (key `a`).  Both now render through `pm_core/autostart_view.py` from
the `pm.autostart.status/1` dict built by `autostart_state.build_status`.

## 1. Requirements

R1 — Inherited policy stated once
- Given a wait-for-merge target with several unmerged prerequisites,
  When the user runs `pm autostart status`,
  Then the target header shows `[wait-for-merge]` once, its dependency rows show
  no `wait-for-merge ← <target>` label, and blocker reasons read
  `blocked on #N (status), …` with no hold annotation.
- Given a dependency shared by an auto-merge target and a wait-for-merge target,
  When the report is shown,
  Then under the auto-merge group that dep carries `[wait-for-merge ← #<wait target>]`
  (the meaningful exception) and `also needed by …` names the other target;
  under the wait group it carries no hold label.
- Given a dependency that has its own stop-before-merge mark,
  When the report is shown,
  Then its row shows `[stop-before-merge]` even under a target with a different policy.
- Given each target, Then its header always names its own policy
  (`auto-merge`, `stop-before-merge`, `wait-for-merge`).

R2 — Phase/progress once per PR
- Given a PR whose review loop is on iteration N with last verdict NEEDS_WORK,
  When the report is shown,
  Then the row shows one token `review #N` and the reason `last NEEDS_WORK`
  (no `running/review`, no `review iteration N`).
- Given a PR in QA with scenarios running, Then the row shows one
  `qa d/t PASS:k` (or `qa planning`) token and no repeated scenario count in the reason.
- Given any row, Then PR display id (`#N` when a GitHub number exists), pm id,
  state label, token, title and reason are all present.

R3 — Semantic highlighting
- Given a PR at review/QA INPUT_REQUIRED, a PR with a pending impl spec, a PR with
  a pending QA spec, and a signed-off PR held for manual merge,
  When the report is shown in a color terminal,
  Then those rows carry explicit labels `INPUT_REQUIRED`, `IMPL SPEC REVIEW`,
  `QA SPEC REVIEW`, `MANUAL MERGE` styled conspicuous red (white on red), and
  their reasons say what to do (`answer in the … window`, `press V`, `press g`).
- Given a still-running PR under a wait-for-merge target, Then its label is
  green `RUNNING`, not red; the wait policy is a magenta label only.
- Given a failed run, Then `FAILED` is red text without the red background.
- Given human-action PRs exist, Then the header reads `⚠ K need you: #a, #b, …`
  listing each such PR once, even if it appears under several targets.
- Given the same project, When the user compares CLI output with the popup,
  Then both list the same need-you PRs and the same red rows.

R4 — Width and wrapping
- Given a terminal ≥ 99 columns or redirected output, Then no line exceeds 99
  visible columns (including the header).
- Given a narrower terminal or `--width N`, Then lines fit N (clamped to 30..99),
  long titles/reasons/labels wrap onto indented continuation lines, nothing is
  truncated, and no line starts or ends with a `·` separator.
- Given titles with wide Unicode (CJK/emoji), Then wrapping counts display cells.
- Given the popup in a narrow terminal, When the terminal is resized,
  Then the popup re-wraps to the new width with the header also bounded.

R5 — Shared presentation, color control
- Given an interactive terminal, Then CLI output is colored.
- Given `NO_COLOR=1`, `TERM=dumb`, `--no-color`, or redirected/piped stdout,
  Then output has no ESC bytes.  `--color` forces color even when piped.
- Given `--json`, Then output is valid JSON with no ANSI, the original `reason`
  text is unchanged, and new additive fields `attention`, `attention_label`,
  `short_reason`, `blockers` are present per run.
- Given the popup, Then j/k selection, Enter/f window focus, the
  "no window" notice on the selected row, r refresh, Esc/q/a close still work;
  the selected row scrolls into view in a long list.

R6 — No behavior change
- Scheduling order, merge holds, policy changes (`add --…`, `remove`), merge via
  `g` / `pm pr merge`, and lifecycle transitions behave as on master; only text changes.

## 2. Setup

- Follow `pm/qa/instructions/tui-manual-test.md`: install pm from this branch,
  `PYTHONPATH` pointed at the clone, throwaway git project, `pm init --backend local
  --no-import`, `pm session` (tmux; ignore attach error).
- Configure fake-claude (`pm fake-claude config set`) so review/QA/sign-off sessions
  reach deterministic verdicts (NEEDS_WORK with delay for "running review",
  INPUT_REQUIRED for human waits, SIGNOFF_MERGE for manual-merge waits).
- Spec-review waits: set the global `spec-mode` to `prompt` so generated specs
  pause for approval, or (bootstrap only) set `spec_pending: {phase: impl|qa}` on a PR
  in `pm/project.yaml` before starting the session.
- Use GitHub-number-less local PRs or set `gh_pr_number` at bootstrap if `#N`
  display ids are wanted.
- Create several targets: one `--wait-for-merge` chain, one `--auto-merge` target
  sharing a dep with it, one `--stop-before-merge` target with a stop-marked dep.
- Run CLI commands from a separate pane of the test tmux session; inspect the popup
  via `pm tui view` / tmux capture; for color checks use `script`/a tmux pane and
  `cat -v` to see SGR codes.
- Reference rendering of a full mixed report: `tests/autostart_mixed_fixture.py`
  (for comparison only; scenarios should produce state through pm).

## 3. Edge Cases

- Given auto-start off (no targets), When status is run, Then "auto-start off"
  message, no crash, no ANSI when piped.
- Given `autostart all` (backlog) mode, Then rows are flat and blocker reasons keep
  hold annotations (no group implies them).
- Given `--width 10`, Then width clamps to 30; `--width 500` → 99; `--width 0` → terminal default.
- Given an unbreakable token longer than the width (long branch/title word),
  Then it is hard-split, never overflows.
- Given no owner TUI running, Then `pm autostart status` fails with the same
  error/exit code as master (no traceback).
- Given a dep blocked by a missing/closed PR, Then it shows `(missing)` / `(closed)`.
- Given a wait-held dep that is signed off, When the user merges it,
  Then its MANUAL MERGE row disappears, need-you count drops, and the newly
  unblocked dependent starts (unchanged scheduling).
- Given an INPUT_REQUIRED PR, When the user answers and the loop resumes,
  Then the row returns to RUNNING (not red) on the next refresh.
- Given a selected row with no window, When Enter/f is pressed, Then a notice appears
  on that row and wraps within width.

## 4. Pass/Fail Criteria

Pass: every Then above observable in CLI output / popup captures; widths measured
on plain text ≤ requested width; ESC-free plain/JSON; CLI and popup need-you lists
identical; red only on human-wait rows; scheduling/merge outcomes identical to master.
Fail: any repeated inherited policy on dep rows within its own group, duplicated
phase/progress text, a running PR shown red, a human wait not red or missing its
text label, a line over width or truncated content, ANSI in redirected/JSON
output, CLI/TUI disagreement, broken popup navigation, or any change in
scheduling/merge behavior.

## 5. Ambiguities (resolved)

- Human-action set includes PERMISSION and DECISION NEEDED besides the three
  required kinds (impl spec decision); tested where reachable.
- Stop-before-merge target that is signed off counts as MANUAL MERGE (needs `g`).
- JSON `reason` intentionally unchanged; compact text lives in `short_reason`.
- `--width` beyond 99 is clamped to 99 (the requirement's cap), below 30 to 30.
- Target headers in the CLI now name `auto-merge` too (shared label set with the popup).
