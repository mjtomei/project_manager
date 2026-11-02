# QA Spec — pr-fa9f172

Self-documenting + consistent pm commands: complete `--help`, actionable
errors, unified flags.

The motivating failure: restarting QA requires the command-bar form
`pr qa fresh <id>` (TUI `z t`), but `pm pr qa --help` did not list the
`fresh` mode, so the restart path was undiscoverable. The PR makes the
surface self-documenting across three renderers (CLI help, `pm tui keys`,
the TUI `?` screen), turns wrong-state / already-running / not-found errors
into corrective instructions, makes the command bar accept `pr qa <id>
--fresh` as the equivalent of `pr qa fresh <id>`, and reconciles the stale
`plan=ux` name to the real plan id `improvements`.

## Setup (cross-cutting)

All scenarios start from a throwaway project, never the live pm session:

- Install the PR checkout into an isolated venv (or run with the repo's
  `pm_core` first on `PYTHONPATH`); confirm `pm which` points at the
  checkout.
- `HOME`, global settings, tmux socket/server, and the test project are
  isolated per scenario (the TUI instruction's setup steps 1–3).
- `pm init --backend local --no-import`, then `pm pr add` for the PRs a
  scenario needs. For state fixtures, bootstrap `pm/project.yaml` statuses
  once (the instruction's explicit exception); all subsequent changes go
  through `pm` / the TUI.
- For TUI scenarios: `pm session` creates the session; drive keys with
  `pm tui send`, read with `pm tui view` / `tmux capture-pane`. Use the
  bundled `fake-claude` stand-in when a review/QA loop must reach a verdict
  without real API calls.

## Requirements

### Help completeness and accuracy

R1. **QA restart is discoverable from the CLI.**
GIVEN a project with at least one PR, WHEN the user runs `pm pr qa --help`,
THEN the output lists every QA mode with its command-bar form and TUI key:
`pr qa [PR_ID]` = `t`, `pr qa fresh [PR_ID]` = `z t`, `pr qa loop [PR_ID]`
= `zz t`; it also states that `--fresh` / `--loop` are command-bar spellings
(`pr qa <id> --fresh` ≡ `pr qa fresh <id>`), that the CLI form is diagnostic
only (it never starts QA), that it exits 1 even on a valid PR, and that a
single instruction runs with `pm qa run <id> --pr <id>`.

R2. **Lifecycle commands show CLI / command-bar / TUI equivalents.**
GIVEN the same project, WHEN the user runs `pm pr start --help`,
`pm pr review --help`, `pm pr signoff --help`, and `pm pr merge --help`,
THEN each shows an equivalents block naming the CLI form, the command-bar
form, and the TUI keys (`s`/`z s`/`S`/`z S`; `d`/`z d`/`zz d`; `i`/picker
`z i`; `g`/`G`). `pm pr merge --help` explicitly says there is no `--fresh`
option and names the retry path (a fresh sign-off, then merge again).

R3. **Top-level help is current.**
GIVEN the same project, WHEN the user runs `pm --help` (or `pm help` /
`pm getting-started`), THEN the command list includes the real lifecycle
commands (`pm pr merge`, `pm pr qa`, `pm pr auto-sequence`, `pm pr spec*`,
`pm qa debug`, `pm qa launch`, `pm log`, `pm session`, `pm autostart clear`,
…), and a TUI / command-bar section points at `?`, `/`, `pm tui keys`, and
the QA restart/loop equivalents. The plans-view key row names `D=deps` and
`Enter=view file`, not the removed `v=view`.

R4. **`pm tui keys` and the `?` screen carry the same command-bar table.**
GIVEN a running TUI (for the `?` screen), WHEN the user runs `pm tui keys`
or presses `?`, THEN both render the command-bar section with each form's
CLI and TUI equivalent (including `pr qa fresh` = `z t`, `pr qa loop` =
`zz t`, and the `--fresh` / `--loop` note). The `?` screen is
context-sensitive: in the plans and QA views it omits tree-only actions
(`t`, `S`, `G`, `z`, `zz d`/`zz t`, `c`) and shows the view's own keys
(plans: `a e w c l D p`, Enter views the file; QA: Enter runs, `e` edits,
`d` debugs, `a` adds, `q` returns).

R5. **Command-bar help is real help.**
GIVEN a running TUI, WHEN the user types `help` (or `?`, `commands`,
`help <topic>`) in the command bar, THEN the HelpScreen opens (not a single
truncated log line); after closing it, the tree/plans pane has focus, so
the next arrow/j/k key moves the selection instead of being typed into the
command bar.

R6. **The `?` screen is not clipped.**
GIVEN a running TUI at a normal (including narrow) terminal size, WHEN the
user opens `?`, THEN long rows wrap and the right-hand half (the CLI/TUI
equivalents, `z`'s full chord list, the watcher/cleanup rows) is readable,
not cut at the container width.

### Consistent flags / modes

R7. **Command bar: flag spelling ≡ positional spelling.**
GIVEN a running TUI with an `in_review` PR, WHEN the user submits
`pr qa <id> --fresh` in the command bar, THEN QA restarts exactly as
`pr qa fresh <id>` does (existing QA windows killed and rebuilt, run state
reset), and `pr qa <id> --loop` starts/stops the loop exactly as
`pr qa loop <id>` does. The flag works before or after the id.

R8. **Bad modes are rejected with the accepted forms.**
GIVEN the same TUI, WHEN the user submits `pr qa <id> --frosh` or
`pr qa fresh <id> --loop`, THEN no QA run starts and the log names the
accepted forms (`--fresh`, `--loop`, positional `fresh`/`loop`) or the
conflict. User-typed bracket text in the message (e.g. `pr qa [x]`)
renders literally rather than being swallowed as markup.

R9. **No-id QA names the requested mode.**
GIVEN no PR selected, WHEN the user submits `pr qa fresh` (or
`pr qa --loop`), THEN the log names the mode the user asked for and its own
TUI key (`z t` for fresh, `zz t` for loop), not the plain `t` hint.

R10. **Command bar accepts CLI identifiers.**
GIVEN a GitHub-backed project where a PR's display id is `#42`, WHEN the
user submits `pr qa #42 --fresh`, `edit #42`, or `review-loop #42`, THEN
the command targets that PR (same as the CLI would); an unknown id logs
`PR not found: <id> — see pr list (TUI: r to refresh)`.

R11. **CLI two-token mode is a corrective hint, not a parse error.**
GIVEN the project, WHEN the user runs `pm pr qa fresh <id>` (or
`pm pr qa <id> fresh`) on the CLI, THEN the output explains that `fresh`
is a command-bar mode (open the command bar, type `pr qa fresh <id>`,
TUI `z t`) and exits 1 — it must not answer `PR 'fresh' not found` or
Click's "Got unexpected extra argument". `pm pr qa --help` and
`pm pr qa fresh --help` still show help.

R12. **`pm pr signoff help` behaves like every other group.**
GIVEN the project, WHEN the user runs `pm pr signoff help`, THEN the
sign-off group help renders (routed `run` form, `record`, `integrate`,
`--fresh`) and exits 0. `pm pr signoff --help` lists `record` and
`integrate`; `pm pr signoff --fresh <id>` routes to the run form.

### Self-documenting errors

R13. **Wrong-state lifecycle refusals name the next command.**
GIVEN PRs at each lifecycle state, WHEN the user runs a command that does
not fit that state, THEN the refusal names the exact command that moves it
forward and the TUI key:
- pending + `pr review` / `pr qa` / `pr merge` / `pr signoff` → `pm pr start <id>` (TUI `s`);
- in_progress + `pr qa` → `pm pr review <id>` (TUI `d`);
- in_review + `pr signoff` → run QA via the command bar / TUI `t` (not the diagnostic `pm pr qa`);
- qa + `pr merge` → `pm pr signoff <id>` (TUI `i`);
- sign_off + `pr start` → `pm pr merge <id>` (TUI `g`);
- merged + `pr start` / `pr review` / `pr qa` / `pr merge` → "Nothing to do — inspect it with `pm pr show <id>`";
- closed → reopen with `pm pr edit <id> --status pending`.

R14. **Not-found errors name the listing command.**
GIVEN a project, WHEN the user names an unknown PR, plan, QA item, mock,
provider, or note, THEN the error adds the matching listing command
(`pm pr list`, `pm plan list`, `pm qa list`, `pm qa mocks list`,
`pm provider list`, `pm pr note list <id>`).

R15. **Valid `pm pr qa` prints the action and exits 1.**
GIVEN an `in_review` PR, WHEN the user runs `pm pr qa <id>`, THEN it prints
the command-bar form (`pr qa <id>`) and the TUI keys (`t`, `z t`, `zz t`)
and exits 1 (it performs no action). With no pm session it also says to
start one with `pm session`.

R16. **skip_qa projects get skip_qa-aware refusals.**
GIVEN a project with `skip_qa: true`, WHEN the user runs `pm pr signoff`
with no id while an `in_review` PR exists, THEN it auto-selects that PR
instead of reporting "No PR is ready"; and WHEN it refuses a wrong status,
THEN the expected states are `qa`/`in_review`/`sign_off` and the text says
sign-off runs after review, not after QA.

R17. **TUI QA/review state messages carry the remedy.**
GIVEN a running QA for a PR, WHEN the user starts QA again (`t` or
`pr qa <id>`), THEN the log says it is already running and names the
restart (`pr qa fresh <id>`, TUI `z t`) and stop (`pr qa loop <id>`,
TUI `zz t`) forms. WHEN the user starts the loop, the confirmation says
`zz t` to stop (not `z t`). WHEN the user stops QA with no run, the log
names `pr qa <id>` (TUI `t`). A held run names the worker pane plus the
stop/restart forms.

R18. **TUI review-loop and watcher messages name working commands.**
GIVEN no review loop, WHEN the user asks to stop one (`zz d`), THEN the
message names `review-loop <id>` (command bar; TUI `zz d`) and clarifies a
plain `pm pr review <id>` is a one-shot review, not a loop. A missing
workdir names `pm pr start <id>` (TUI `s`). WHEN a watcher is already
running, the message points at `pm watcher stop <type>` as guidance, not as
the action that stops it.

R19. **tmux/workdir launch errors name `pm session` / `pm pr start`.**
GIVEN no pm tmux session, WHEN the user runs `pm pr qa` on a valid PR or
`pm watcher start`, THEN the error names `pm session`. A missing workdir in
the review / merge / sign-off / watcher window paths names
`pm pr start <id>` (TUI `s`).

R20. **Non-GitHub backends get a working remedy.**
GIVEN a local-backend project, WHEN the user runs `pm pr sync-github` or
`pm pr import-github`, THEN the error says the command is GitHub-only and
names the working path (`pm pr merge <pr-id>` / `pm pr add <title>`), not a
GitHub-only command.

R21. **Watcher stop explains rather than pretends.**
GIVEN the project, WHEN the user runs `pm watcher stop` (default
auto-start), THEN it explains that the TUI's `ws` toggles the auto-start
watcher and a CLI-started watcher stops with Ctrl+C. WHEN the user names
another type (`regression-loop`, `discovery`, …), it says only auto-start
has a TUI key and names Ctrl+C for that type. `pm watcher --help` calls
the subcommand "Explain how to stop a running watcher".

### Plan-name reconciliation

R22. **Live surfaces say `improvements`, never `ux`.**
GIVEN a project with the `bugs` and `improvements` plans, WHEN the user
runs `pm watcher start --help` / `pm watcher list`, or inspects a generated
implementation prompt (`pm prompt <id>`), or a launched discovery /
improvement watcher prompt, THEN the improvement-fix watcher is described
as driving `plan=improvements`; `pm pr list --plan improvements` lists the
improvements PRs; no live help/prompt references `plan=ux`. A real
`tui-ux` plan keeps its name.

R23. **Prompt texts use current commands.**
GIVEN a generated session prompt, WHEN the user reads it, THEN it forbids
`pm pr review` (not the removed `pm pr done`) alongside the other
TUI-managed launches.

## Edge Cases

E1. **`pm pr qa --help` on a narrow terminal** — Click may wrap the table;
the modes and keys must still be present (assert content, not layout).

E2. **`pr qa fresh` with a selection** — the selected PR is used; the mode
is honored.

E3. **`pr qa --fresh` with no selection** — hint names `z t`.

E4. **Unknown command-bar option vs. an id that starts with a digit** —
`pr qa 42 --fresh` must treat `42` as the PR id, not a flag; only
`-`/`--`-prefixed tokens are options.

E5. **Conflicting / repeated modes** — `pr qa fresh --loop` rejected;
`pr qa fresh fresh` is harmless (same mode).

E6. **`pm pr qa fresh --help`** — help wins over the mode token.

E7. **Markup in user text** — `pr qa [x]`, note text with `[work]`, and
paths with brackets render literally in the TUI log.

E8. **A `pm pr qa` on a valid PR always exits 1** — a driving agent must
not read that as a failed action and retry.

E9. **`pm pr signoff help` under older Click (8.1.x)** — observed to fail
with `No such command '--help'` while Click 8.5 succeeds (the repo allows
`click>=8.0`). Confirm with the scenario's installed `pm`; if it fails, it
is a real defect in the new help alias.

E10. **QA fresh while a run is already active** — must restart (kill and
rebuild), not report "already running"; the loop toggle (`zz t` /
`--loop`) must stop an active run.

E11. **Concurrent actors on the same PR's QA** — two tmux clients / two
`prefix P` pickers (or a picker plus a `t` keypress) start QA for the same
PR at once: exactly one run owns the PR; the other either focuses it or
gets the already-running remedy; every popup spinner follows the rebuilt
`qa-<display>` window (display ids such as `#42` included) and none is
stranded on "queued…".

E12. **Concurrent PR actions from one command bar** — a second PR action
submitted while one is in flight logs `Busy: … — wait for it to finish`
and does not start a second action.

## Pass/Fail Criteria

- **Pass:** every Then clause is observable on the user surface named:
  help text shows the documented modes/keys; errors name a command that
  exists and does what the text claims; the command-bar flag forms have the
  same effect as the positional forms; bad input is rejected without
  starting a run; the `?` screen and `pm tui keys` agree; no live surface
  says `plan=ux`; concurrent actors leave one coherent QA run and no stuck
  spinner.
- **Fail:** a help surface omits a real mode/flag, an error names a command
  that does not act (e.g. telling the user to stop QA with `z t`, or to
  start it with the diagnostic `pm pr qa`), a flag spelling silently starts
  the wrong kind of run, a corrective message is swallowed by markup, the
  `?` screen clips its right half, or concurrent starts produce two runs,
  a wrong-window focus, or a stuck spinner.
- Exit codes: help exits 0; refusals exit 1; `pm pr qa` (valid or not)
  exits 1; Click parse errors exit 2 only where the CLI genuinely has no
  such argument.

## Ambiguities (resolved)

1. **Does `--fresh` belong on CLI `pm pr qa` / `pm pr merge`?** No. The PR
   note forbids inventing semantics: `pm pr qa` is diagnostic (it starts
   nothing) and `pm pr merge` has no resumable session. `--fresh` stays on
   `pr start` / `pr review` / `pr signoff` and is a *command-bar* spelling
   for QA. Both help texts state the absence deliberately.
2. **"Command-bar help should match"** means a shared table rendered in
   `pm pr qa --help`, the `?` HelpScreen, and `pm tui keys`, plus
   `help`/`?`/`commands` in the command bar opening the HelpScreen.
3. **Plan name** — `pm/project.yaml` has `improvements` (active) and no
   `ux`; `tui-ux` is a different real plan and must survive. Historical
   specs/reviews are out of scope.
4. **Error sweep breadth** — user-facing state/launch/not-found errors
   only; argument-validation and internal guard errors are out of scope.
5. **`pm pr signoff run`** stays hidden; the group help documents the
   routed form instead of exposing a second spelling.

No **[UNRESOLVED]** ambiguities remain.
