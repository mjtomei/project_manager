# Carried-forward QA scenarios — pr-0b87a97, round 6 S27–S30

These scenario definitions are preserved verbatim from commit
`935d99ab0a260493083b24b81594c6d01602af54` (qa.md §11). They PASSED and were independently
VERIFIED on e17d5671 (run pr-0b87a97-1528f33320623871, evidence index
`shepherd-20261012/qa-round-6-evidence-index.json`) and are carried
forward, not re-run, under ambiguities 15 and 17 of [qa.md](qa.md). The
round-6 preamble, shared-resource list and S26 stay in qa.md §11.

### S27 — CLI/command bar, validation, owners, typing, prefixes, pulls
Covers R2, R8, R9, R11–R13, R23, R29, R30, R32 (policy flip), R33, R34,
R37 (pulling status bar), R38 (deferred drop, prefix/error clears).
- GIVEN PRs A, B, C pending and M merged before the session (with
  `gh_pr_number` set), WHEN the user runs `pm autostart add A B` and
  re-adds A as `pr-…`, `#N` and `N`, THEN every command exits 0; `list` /
  `list --json` show exactly A and B, stop-before-merge, with added_at and
  source; re-adds report "already a target" with no second A window; the
  TUI shows ◎ on both with a readable confirmation.
- WHEN `add A --auto-merge` then `add A` (no flag), THEN the first reports
  policy_changed (was stop-before-merge) and the second keeps auto-merge.
- WHEN `add A nosuch`, `add M`, `add`, `remove nosuch`, `remove C`, each
  with and without `--json`, THEN the first four exit 1 `unknown_pr` /
  `terminal_pr` / usage with the list unchanged; `remove C` is ok
  `not_target`.
- GIVEN A and B targets and a tree filter, WHEN the user presses `r` and a
  background sync runs, THEN during "pulling" the status bar keeps
  `AUTO ×2`, the filter segment and WCH (if watchers run).
- GIVEN the user has just pressed `w` (and separately `y`, and `z`) so a
  prefix hint is showing, WHEN another pane runs `pm autostart remove A`
  inside the 2 s prefix window and the prefix then auto-cancels (repeat:
  user presses Esc), THEN "removed A (1 remaining)" is readable for its
  full hold after the hint clears (not blanked by the prefix timer).
- GIVEN an error message showing in the log line (e.g. a refused action),
  WHEN a CLI `add` lands before its auto-clear, THEN the "targets +=" line
  is not erased when the error's timer fires.
- WHEN the user runs `clear`, and within 3 s moves in the tree and types
  `autostart list` (and separately bare `autostart`) in the command bar,
  THEN the command-bar answer stays on screen; no stale "Selected: X"
  replaces it when the hold ends. "Auto-start: OFF" was readable; C never
  starts afterwards; A's window is kept.
- GIVEN the TUI, WHEN the user drives the command bar (`autostart target
  C`, `add B`, `list`, `remove C`, bare `autostart` on and off, `autostart
  all`) and `A` on a never-stop-marked non-target, a target, and nothing
  selected, THEN `target` is additive, bare-when-off prints usage, only
  `all` enables backlog mode with a readable "ON (all…)" line, and `A` adds
  auto-merge / removes only that PR / says "No PR selected".
- GIVEN half of `autostart add B` typed in the command bar, WHEN another
  pane runs `pm autostart status --json`, then `add C`, then an external
  `pm pr edit` triggers a reload, and the user finishes typing and presses
  Enter after each interruption (repeat with the interruption after one
  character), THEN the bar keeps focus and text, cursor at the end with
  nothing selected; the submitted command is the full text and B is added;
  no keystroke acted as a tree hotkey.
- GIVEN each owner: no session; killed TUI with stale pidfile; zombie
  (killed, unreaped) TUI; `-s nonexistent`, WHEN `status --json` and `add
  A` run, THEN each exits 2 `owner_unavailable` immediately, and a command
  refused for a zombie owner is not applied by the next TUI.
- GIVEN a directory outside any pm project, WHEN `add A --json` and
  `remove A --json` run, THEN each exits 1 with `no_project` JSON;
  `status --json` there exits 0 from a pane inside a running pm session
  and exits 2 `owner_unavailable` with no session.
- GIVEN the TUI held suspended, WHEN a command runs with `--timeout 2`,
  THEN it exits 2 `owner_timeout` saying it may still be applied; after
  resume the state is consistent and the command was applied at most once.

### S28 — Shared dependency under concurrent CLI, keys and merges
Covers R3–R6, R22, R24, R36, R37 (confirmations vs spinner), R38 (held
queue, sync clears), E1, E3, E4, E6, E9.
- GIVEN a diamond X→D←Y, independent Z and chain T2→T1, all pending, WHEN
  two shells add X and Y at the same instant, THEN both exit 0 with their
  own replies; D is launched exactly once and Z never starts; status lists
  D once with needed_by [X, Y], X/Y "blocked on D", and the popup lists D
  under both with "also needed by" the other.
- GIVEN D running, WHEN at the same moment one shell removes X, another
  re-adds Y and adds T2, a third fires 10 parallel `status --json`, and the
  user presses `O` on T1, THEN every command gets its own valid reply (no
  timeouts); the target set is {Y, T2, T1}; D keeps running with needed_by
  [Y]; T1 runs once and T2 waits on T1; ◎ marks and popup match the CLI;
  no PR has two windows; the cursor stays where the user put it.
- GIVEN D finished, WHEN the user merges D with `g` while a CLI `remove Y`
  races the merge (repeat with `add Y`), THEN the outcome is consistent (Y
  removed, or pruned and started exactly once); "removed Y (N remaining)"
  (or "targets +=") is readable after the spinner and in `L`; X is not
  started; no traceback.
- GIVEN a slowed `g` merge of a target W spinning, WHEN the user runs `pm
  autostart remove` on a non-target Q, and separately `pm autostart clear`
  during another slowed merge, THEN "Q not a target" and then "target W
  merged — removed" are each readable in turn (neither replaced in one
  frame), likewise "Auto-start: OFF", and all are in `L` (re-add targets
  afterwards to continue).
- GIVEN Y advancing, WHEN Y is merged by hand while a background or manual
  GitHub/refresh sync finishes right after, THEN "target Y merged — removed
  (N remaining)" is readable for its full hold (the sync's own result line
  clear does not cut it short) and is in `L`; T1/T2 keep advancing.
- WHEN T1 and then T2 merge, THEN the last prune line says "all targets
  complete — auto-start OFF", the mode is off, the popup is empty, and Z
  never starts.

### S29 — Merge policies, sign-off gate, finished QA, skip-QA (scoped)
Covers R7, R14/R37 (policy tags), R21, R32, R36, E2, E8, ambiguities 4 and
12. Post-sign-off and transient paints are asserted in the ambiguity-12
tolerant form.
- GIVEN independent S and U, WHEN S is added with the default policy (and
  with `O`) and U with `--auto-merge` (and with `A` on a never-stop-marked
  PR), THEN list/status show stop_before_merge for S and auto_merge for U,
  and the popup headers read `[stop-before-merge]` and `[auto-merge]`.
- WHEN both pass review and QA, THEN S is held with a "sign off / press g"
  reason; U's merge is refused by the sign-off gate (no SIGNOFF_MERGE) and
  status says merge blocked by sign-off gate / awaiting sign-off; `pm pr
  list` shows neither merged; nothing passes `--no-signoff-check` (debug
  log and merge commands).
- WHEN the user signs U off through `pm pr auto-sequence` from another
  pane, THEN `status --json` shows `signoff.fresh` true for U at once and no
  row in the TUI, status or open popup still says "awaiting sign-off"; U
  then merges through `pm pr merge` with the gate passing (scheduler, or
  the user's `g` per pr-7c32e44); U leaves the target set with a readable
  "target U merged — removed" line that is also in `L`.
- WHEN several scheduler passes and a sync/reload happen, THEN no new QA
  run starts for S or U.
- WHEN `add S` (no flag), `add S --auto-merge`, then `remove S` + `add S`,
  THEN policies change only as flagged, `policy_changed` names the previous
  policy, and the stop mark survives remove/re-add.
- GIVEN stop-before-merge D needed by auto-merge Q, WHEN D is
  merge-ready, THEN D is not auto-merged, Q waits on D, Q's header says
  `[auto-merge]` and D's row carries only the stop mark.
- GIVEN skip-QA enabled, WHEN an auto-merge and a stop-before-merge target
  pass review, THEN (via `status --json`, popup, `L`, `pm pr list`) the
  status says "QA skipped (skip_qa); awaiting sign-off", the auto-merge
  target is not merged without a fresh SIGNOFF_MERGE, and the stop target
  stops.

### S30 — Restart adoption, CLI during restart, typing after restart
Covers R19, R20, R26, R27, R33, R34, ambiguities 7–8, 14.
- GIVEN A (stop, QA in flight), B (auto-merge, review iteration running),
  C (waiting on D, D impl running), WHEN the user runs `pm tui restart
  --breadcrumb`, THEN `list --json` shows A, B, C with the same policies;
  `tmux list-windows -F '#{window_id} #{window_name}'` is identical before
  and after; A's QA continues without re-planning and B's review keeps its
  window; the resume summary is readable; the popup shows the same runs
  and policy tags.
- WHEN during the restart one shell runs `status --json` and another `add
  Z`, followed later by an unrelated `status`, THEN each initial command
  succeeds or exits 2 within `--timeout`; Z is applied exactly once right
  after startup, not by the later command; the TUI pane survives.
- GIVEN the user typing `autostart li` in the command bar right after the
  restart, WHEN the deferred startup queue (Z) drains and the user types
  `st` and Enter, THEN the bar kept focus and text with nothing selected,
  and the submitted command is `autostart list` with Z in its output.
- GIVEN a queue left by a TUI that died more than 60 s ago, WHEN a new TUI
  starts, THEN that command is not applied.
- GIVEN the popup open, WHEN the user presses Ctrl+R, and separately runs
  `pm tui restart`, THEN the TUI restarts (popup does not swallow it) and
  targets are dropped by design.
- GIVEN a legacy single-target breadcrumb produced by the master build
  (override → /opt/pm-src, `O`, override back, `pm tui restart
  --breadcrumb`), WHEN the new build consumes it, THEN that PR is the only
  target with stop-before-merge, and no windows are duplicated.

