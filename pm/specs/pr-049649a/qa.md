# QA spec — pr-049649a

Remove all-PR autostart and fail closed on malformed or targetless saved state.

This spec grounds the QA scenarios in the user-visible surfaces the diff
touches. Every requirement is written as a Given / When / Then story a person
could perform against a throwaway pm project; nothing here requires importing
internals.

## Context: what the user can see

- **CLI**: `pm autostart add|remove|clear|list|status` (sent to the running
  TUI over its command queue), and `pm autostart --help`.
- **TUI command bar** (`/`): `autostart add|remove|clear|list|status` and the
  now-rejected `all`.
- **TUI keys**: `A` (toggle selected PR as target; no selection = off),
  `O` (auto-sequence), `a` (runs popup), status bar auto-start label, `?`
  help, `pm tui keys`.
- **Merge-restart persistence**: `pm tui restart --breadcrumb` writes
  `~/.pm/autostart-resume.json` and the restarted TUI consumes it. A plain
  `pm tui restart` consumes whatever file is present without writing one.
- **Saved-state evidence**: the breadcrumb file, and its quarantined
  siblings `autostart-resume.rejected-<UTC stamp>[-N].json`.
- **Watcher**: the auto-start watcher's pane, and the prompt pm hands it
  (`<project>/pm/prompts/pm_prompt_*.txt`, referenced by the pane's command).
- **Status surfaces**: `pm autostart status` / `list` text and `--json`
  (`mode` is only `off` or `targets`; `--json` always carries `ok` — true on
  success, false with `error`/`message` on an owner-side failure — matching
  add/remove/clear/list), plus the runs popup.

## Requirements

### R1 — Explicit targets are the only authority

GIVEN a project with several pending PRs and a running TUI with auto-start off
WHEN the user adds two PRs as targets from the CLI (`pm autostart add A B`)
THEN the CLI reports `auto-start targets; targets: A, B`, the status bar shows
a target count, and only A, B and their unmerged dependency closures are ever
started — an unrelated eligible PR gains no tmux window and stays pending.

GIVEN the same project WHEN the user runs a scheduler pass / reloads the TUI
THEN nothing outside the target closures is launched.

### R2 — The `all` verb is rejected on every surface

GIVEN a running TUI with auto-start off
WHEN the user types `autostart all` in the command bar
THEN the log shows `Auto-start: all-PR autostart has been removed; add
explicit targets with \`autostart add PR_ID...\``, no target is added, no
scope is enabled, and the status stays `off`.

GIVEN the same TUI WHEN the user runs `pm autostart all` from the shell
THEN the CLI rejects it as an unknown command and exits non-zero; nothing is
sent to the TUI.

GIVEN a stale client that still sends the removed verb over the TUI's command
queue WHEN the TUI processes it THEN it replies non-ok with error
`all_mode_removed` and reports `mode: off` with no targets and no runs.

### R3 — No help, label, popup or status advertises all-PR mode

GIVEN the user is on the branch WHEN they read `pm autostart --help`,
`pm autostart add --help`, the TUI `?` help screen and `pm tui keys`
THEN none of them offers an `all` verb or a "whole backlog" mode, and the TUI
help says auto-start runs only the explicit targets and their dependency
closures.

GIVEN two targets WHEN the user looks at the status bar and opens the runs
popup (`a`) THEN the label shows a count (never `all`) and the popup title
reads `Auto-start runs — N target(s)` (never "backlog mode").

GIVEN auto-start off WHEN the user presses `A` with no PR selected THEN the
log says no PR is selected and to add explicit targets, and no mode is
enabled; WHEN auto-start is on and `A` is pressed with no selection THEN
auto-start turns off.

### R4 — A merge-restart round-trips an explicit target set exactly

GIVEN a TUI with targets T1 (wait-for-merge) and T2 (auto-merge) and a
shared dependency
WHEN the user runs `pm tui restart --breadcrumb` and the TUI comes back
THEN the log reports `Auto-start: resumed after merge restart → T1, T2`, the
restored target list and per-target policies are unchanged, only the closure
PRs are scheduled, and the unrelated PR is never started.

GIVEN that restored state WHEN the wait-for-merge chain reaches sign-off
THEN the target and its prerequisites stay unmerged and the status shows them
held for manual merge; a signed-off PR outside the targets is never merged.

GIVEN a target that merged while the TUI was down WHEN the TUI restarts
THEN the target is pruned, auto-start reports OFF, and no "resumed" line
claims a scope that no longer exists.

### R5 — Legacy saved state migrates only to its exact validated target

GIVEN a saved state from the older single-target writer
(`{"auto_start": true, "target": "<id>", "run_id": ...}`)
WHEN the TUI restarts THEN exactly that one target resumes (log notes
`(migrated legacy breadcrumb)`), and no other PR gains authority.

GIVEN a legacy target that does not exist in this project WHEN the TUI
restarts THEN auto-start stays off, the log names the missing id, and the
file is preserved as rejected evidence.

GIVEN legacy `auto_start`/`run_id` with no target WHEN the TUI restarts
THEN auto-start stays off with a "no target PRs" diagnostic — it never becomes
a whole-backlog run.

### R6 — Malformed saved state fails closed and preserves evidence

GIVEN a saved state whose `targets` is a mapping (the 2026-10-27 incident
shape: `{"auto_start": true, "all_mode": false, "targets": {...}}`)
WHEN the TUI restarts THEN auto-start stays off, the log shows an actionable
diagnostic ending in "Re-add targets with `pm autostart add PR_ID...`", no PR
(related or unrelated) is started, `autostart-resume.json` is gone and a
`autostart-resume.rejected-<stamp>.json` file holds the original bytes.

GIVEN the same incident WHEN the user then runs `pm autostart status`
THEN the output is `Auto-start: off` with no targets and no runs.

GIVEN saved state with `targets` as a string/null/number, a malformed record
(`wait_for_merge: "yes"`, empty or non-string `pr_id`), duplicate target ids,
`targets: []` together with an autostart request, `all_mode: true` (even with
otherwise valid targets), a non-boolean `all_mode`, or non-string `run_id`
WHEN the TUI restarts THEN in every case auto-start stays off, a diagnostic
names the problem, and the evidence is quarantined.

GIVEN a corrupt or truncated `autostart-resume.json` WHEN the TUI restarts
THEN auto-start stays off with an "unreadable" diagnostic, no PR starts, and
the bytes are preserved under a rejected name.

### R7 — Merge gates and loop state are evidence too

GIVEN saved state with a malformed `stop_before_merge` (not a list, or an id
that could never match — padded/empty) WHEN the TUI restarts THEN auto-start
stays off with a diagnostic naming the merge-gate set, so nothing can
auto-merge without the user's holds.

GIVEN saved state with a valid `stop_before_merge` list alongside a valid
target set WHEN the TUI restarts THEN the marks are folded into
`wait_for_merge` targets (a mark on an existing target holds it; a mark on a
non-target becomes a standalone wait target), so the saved hold survives and
nothing auto-merges.

GIVEN saved state with a valid `stop_before_merge` list alongside rejected
targets WHEN the TUI restarts THEN auto-start stays off and the quarantined
evidence still contains the original stop set (with no scheduler there is no
merge path to gate); nothing is enabled from the stop marks alone.

GIVEN saved state with a malformed review-loop record or history entry WHEN
the TUI restarts THEN startup does not fail; well-formed loop state is still
resumed and the rejection diagnostic is not painted over by the resume line.

### R8 — Watcher scope is fail-closed

GIVEN auto-start with no targets WHEN the user starts the auto-start watcher
THEN the prompt pm hands the watcher session says auto-start has no targets,
no PR is managed, and forbids starting/merging/fixing anything (observation
only), and that restriction overrides the prompt's general fix-what-you-can
sections.

GIVEN two explicit targets WHEN the watcher starts THEN its prompt names the
targets and the managed closure.

GIVEN a rejected saved state WHEN the watcher resumes after the restart
THEN it resumes with no targets and therefore observation-only scope; it never
inherits the saved target list.

### R9 — Concurrent callers never produce wildcard authority

GIVEN a running TUI and several shells WHEN the user runs `pm autostart add`,
`pm autostart remove`, `pm autostart status` and a rejected `all` at the same
time THEN every invocation gets its own reply, the final target set is exactly
the additive union of the successful adds minus removes, duplicate adds are
idempotent, and no status reply ever reports `all` or a wildcard scope.

GIVEN a scheduler pass in progress WHEN a target is removed mid-pass THEN no
PR that is no longer in scope is started.

GIVEN two projects sharing one `~/.pm` WHEN project A's saved state is present
and project B's TUI restarts THEN B rejects it (targets not found in this
project), stays off, and A's running auto-start is unaffected.

## Setup (cross-cutting)

1. Throwaway pm project(s) under the workdir: `pm init --backend local
   --no-import`, then several PRs including a dependency chain, at least one
   unrelated eligible PR, and one PR outside the targets that is signed off /
   merge-ready.
2. **Isolation is mandatory (2026-10-29 test-session-leak incident).**  Run
   every test command with `HOME=<fixture-home>` (so `pm_home()` is
   `<fixture-home>/.pm`, not the shared `~/.pm`) and `PM_TMUX_SOCKET=<unique
   socket path>` (pm's tmux wrapper routes every call there).  Do not inherit
   `TMUX`/`TMUX_PANE`, do not run global `tmux set-environment`, do not write
   the shared `~/.pm` breadcrumb/reply files, and never kill or reconfigure
   the user's real `pm-project_manager-*` session.  Verify fixture ownership
   (socket path, PM home, session name) before every destructive step and
   clean up only the dedicated socket/home.  If isolation cannot be
   established, report INPUT_REQUIRED instead of proceeding.
3. Run the TUI in the dedicated test tmux session (`pm session`), drive it
   with `pm tui send`, `pm autostart ...`, and `pm tui restart
   [--breadcrumb]`.
4. Fake the Claude sessions with `pm fake-claude config set` so no real model
   calls are made; use a no-verdict (`_all: {}`) config for panes that should
   stay open (watcher, impl).
5. Never run whole-backlog starts or merges against a live PM project; all
   fixtures are throwaway and merges are faked/no-op where possible.

## Edge cases

- `targets` as dict (incident), string, null, number, bool.
- `targets: []` with and without `auto_start`/`run_id`.
- Record with `wait_for_merge: "yes"`, `added_at: 5`, `source: []`, `pr_id: ""`.
- Duplicate target ids (string + record, record + record).
- `all_mode: true` with valid targets; `all_mode: "no"`/`1`/`null`.
- `auto_start: "false"` (string), `auto_start: false` with targets.
- `run_id: 5` / `[]` / `{}` / `true`.
- `target: null` + `auto_start: true` (historical all-mode shape).
- Legacy `target` alone with no `auto_start` (still migrates).
- Legacy target unknown to the project; legacy target merged during downtime.
- Corrupt/truncated JSON; valid JSON that is not an object.
- `stop_before_merge` as a mapping/string; ids padded with spaces/tabs/empty.
- Bare-string target entries and a legacy single `target` (both migrate
  fail-closed to `wait_for_merge`).
- Legacy record policy fields (`policy`/`merge_policy`) with auto vs
  unknown/empty/None values.
- Saved targets unknown to the project; saved targets with no PRs loaded.
- Two rapid rejections (distinct quarantine filenames, evidence not overwritten).
- `pm autostart all` from CLI, command bar, and the raw command queue.
- Removal racing a scheduler pass; two adds of the same PR at once.

## Pass / fail criteria

- **Pass**: every Then clause is observable on a user surface (pane render,
  log line, CLI output, reply JSON, status `mode`, files on disk) and matches
  the stated text/behavior; no PR outside an explicit target closure is
  started; no merge happens for a held or out-of-scope PR; every rejected
  saved state leaves auto-start off with an actionable diagnostic and the
  original bytes preserved.
- **Fail**: any path enables a scope with no explicit validated targets; a
  malformed or all-mode saved state is partially restored; evidence is
  deleted; a diagnostic is missing or not actionable; a held or signed-off PR
  merges; unrelated PRs start; the `all` verb succeeds anywhere; status/label/
  popup reports a mode other than off/targets.

## Ambiguities resolved

- **`all_mode: true` alongside valid targets** — reject everything rather
  than narrowing: a truthy all-mode is an explicit wildcard request.
- **`targets: []` alone** — not an error; simply no autostart data, no
  quarantine (nothing was requested).
- **Legacy target merged during downtime** — restore and prune (exact,
  validated target; completion is normal), and do not paint a "resumed" line
  when nothing remains.
- **Malformed `stop_before_merge`** — reject auto-start for that restore but
  still restore review-loop state; never guess holds.  Valid marks on a
  restored target set fold into `wait_for_merge` targets.
- **Legacy single/bare target policy** — the old shape cannot distinguish
  `O` from `A`, so it migrates fail-closed to `wait_for_merge` (no
  auto-merge authority is granted).
- **Rejected restore with review loops** — the rejection diagnostic stays on
  screen; the loop-resume line is recorded in the `L` log at non-sticky
  priority instead of painting over it.
- **Watcher prompt with no targets** — explicit observation-only block that
  states it overrides the generic fix instructions; an omitted scope argument
  keeps the legacy prompt unchanged.
- **`status --json` shape** — the `pm.autostart.status/1` document is
  unchanged; `ok` is an additive top-level field (note-33a61cb) so a captured
  status snapshot is self-describing. A status reply with `ok: false` is an
  owner-side failure, not an empty success.

No **[UNRESOLVED]** ambiguities.
