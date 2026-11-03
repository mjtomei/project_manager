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
or presses `?`, THEN both render the command-bar section under the same
shared heading (`Command bar (press /):`) with each form's CLI and TUI
equivalent (including `pr qa fresh` = `z t`, `pr qa loop` = `zz t`, and
the `--fresh` / `--loop` note). The `?` screen is
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
THEN the advertised expected states are `in_review`/`sign_off` (`qa` is
still accepted for a record that predates the setting, but it is not
advertised, so the list cannot contradict the sentence) and the text says
sign-off runs after review, not after QA. (Corrected in 6a82 i8.)

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

### Later review-loop fixes (recorded after the first QA run)

These extend the requirements above; the first QA pass ran before the
commits named.

R24. **Plans-view file actions name the listing command when the file is
missing.** GIVEN a plan whose `file` is absent, empty, or points at a
missing path, WHEN the user presses Enter or `e` in the plans view (or
`v`), THEN the log names the remedy (`pm plan list`) instead of silently
doing nothing; an empty `file` never opens the editor on the project root.

R25. **Command-bar completion returns focus to the active view.** GIVEN
the tree, plans, or QA view, WHEN the user submits a command (including
`help`), THEN focus returns to that view's pane after any screen closes,
so the next navigation key moves that view's selection instead of being
typed into the command bar. The same holds after a command-bar refusal
(unknown PR id, autostart error, invalid syntax), not only after a screen
closes. (Commits 692008f3 and 6a82 i2/i7: the QA view previously focused
the hidden tech tree, and the autostart / not-found paths left the bar
focused.)

R26. **Retired commands are not named by live surfaces.** GIVEN the
installed checkout, WHEN the user reads `pm help`, `pm tui keys`, or a
generated prompt, THEN no line names `pm tui test` or `pm pr done`;
`pm qa regression` names `pm/qa/regression/`. WHEN a TUI launcher finds no
`claude` on PATH, THEN it logs "install Claude Code first" (not a bare
not-found) and leaves the TUI responsive.

R27. **Concurrent `pm pr start` of one PR is serialized.** GIVEN two
operators starting the same pending PR at the same instant, WHEN both run
`pm pr start <id>`, THEN exactly one clone/workdir/window is created,
neither prints an unhandled traceback, the loser reuses the started PR,
and `pm pr list` shows one `in_progress` record; a concurrent start of a
different PR is not blocked by the per-PR lock. (Commit a22c1f18.)

### Review-loop 6a82 fixes (recorded after scenarios 1–15)

These extend the requirements above; scenarios 1–15 ran before the commits
named.

R28. **Command-bar `--help` opens the same screen as `help`.** GIVEN a
running TUI, WHEN the user submits a command containing `--help` or `-h`
(e.g. `pr qa --help`, `pr start -h`), THEN the HelpScreen opens instead of
one truncated log line or an "unknown option" error. The check is
tokenized: a flag inside a quoted argument (`pr note add <id> 'mention
--help here'`) is passed through literally and does not open help. An
unmatched quote is a syntax error ("Invalid command syntax … check the
quoting"), not a help request; the TUI stays responsive and no PR action
is left stuck as "Busy". (Commit 6a82 i7/i8/i9.)

R29. **Autostart owner refusals name the way to get an owner.** GIVEN no pm
tmux session (or a stale/unreadable pidfile), WHEN the user runs
`pm autostart add <id>` from a plain shell, THEN the message names
`pm session` (not only "restart the TUI"); WHEN the id is unknown or
already merged/closed, THEN it names `pm pr list`. The same remedies appear
from the command-bar `autostart add` path. (Commit 6a82 i6/i8.)

R30. **Scaffolder, dependency, and terminal-PR refusals name the next
command.** GIVEN a project, WHEN `pm qa add-instruction` /
`add-regression` / `add-artifact` / `author-*` / `pm qa mocks add` is given
a name that already exists, THEN the refusal names `pm qa edit <id>` (or
`pm qa mocks edit <id>`) or choosing another name; WHEN `pm pr add` /
`pm pr edit` is given an unknown `--depends-on` id, THEN it names
`pm pr list`; WHEN `pm qa launch` is given an id without `category:id`,
THEN it names `pm qa list`; WHEN `pm pr cd` targets a merged/closed PR with
no workdir, THEN it names `pm pr show <id>` (not the `pm pr start` that
would refuse), while a non-terminal PR still names `pm pr start <id>`
(TUI `s`). (Commit 6a82 i5/i6/i9.)

R31. **`help` is an alias on every group, including under Click <8.2.**
GIVEN a checkout whose `click>=8.0` resolves to 8.1.x, WHEN the user runs
`pm project help`, `pm model help`, `pm watcher help`, `pm qa help`, or
`pm pr signoff help`, THEN each renders its group help and exits 0 — never
`Error: No such command '--help'`. The same holds under the current Click.
For a group with a hidden no-subcommand run form (`pm watcher`,
`pm pr signoff`) the usage line differs by Click version: `COMMAND` on
8.1.x, `[COMMAND]` on 8.2+; within each version `help` is byte-identical
to `--help`. That difference is not a defect. (Commits 9e10f888, 6a82 i2;
scenario 18.)

R32. **`review-loop stop` is refused with the real cancel path.** GIVEN a
running TUI, WHEN the user submits `review-loop stop <id>` (or `cancel` /
`off`) in the command bar, THEN no loop starts and the log says the command
has no stop form, naming Ctrl+R (restart the TUI) or Ctrl+C in the review
pane — not "PR not found: stop". (Commit 6a82 i7.)

R33. **Plan remedies and corrected summaries.** GIVEN a plan whose file is
missing/empty, WHEN the user presses Enter, `e`, or `v` in the plans view,
THEN the log names `pm plan list` and an empty file never opens the editor
on the project root. GIVEN a standalone PR with no plan, WHEN the user
presses `v`, THEN the log names `M` and `pm pr edit <id> --plan <plan-id>`.
`pm pr edit --help` names title, description, dependencies, status, plan
and the interactive editor; `pm session --help` says the notes pane is
on-demand (`n`), not part of the layout; `pm help` and `pm getting-started`
describe `pm session` as starting the TUI with notes opened by `n`, not a
"notes editor". (Commits 6a82 i7/i10.)

R34. **Picker chords name their fzf requirement.** GIVEN the TUI, WHEN the
user opens `?` or runs `pm tui keys`, THEN both say the `z`/`zz` picker
chords require fzf; `pm tui keys` also names the no-fzf fallback (a
numbered menu with no chords), and with fzf absent the picker really is a
numbered menu that ignores the chord keys. (Commit 6a82 i1; the `?` row
names the requirement, `pm tui keys` names the fallback.)

R35. **A command-bar command's failure still names the remedy.** GIVEN a
running TUI, WHEN the user submits an ordinary CLI command through the
command bar (`<command> [args]` row) that fails with a multi-line
diagnostic, THEN the single line the bar logs is the corrective one. A
remedy printed before trailing context (`pr add X --depends-on bogus`
prints "Available PRs: …" after the remedy; `pr note edit/delete` prints
"Available notes:" and the note lines after it) must not be the line that
is dropped, and user text with brackets must render literally. A successful
multi-line result must at least log a line that identifies the result (the
bar shows one line by design). The command-bar table already documents that
the `pm` prefix is omitted; submitting `pm pr list` should leave the
operator with a correction, not only Click's "No such command 'pm'".

## Edge Cases

E13. **Quoted help flag** — `pr note add <id> 'see --help'` must add the
note with that literal text, not open the HelpScreen (R28).

E14. **Unmatched quote** — `pr note add <id> don't forget` logs the
syntax-error remedy; a following `pr start <id>` is accepted, proving the
in-flight guard was cleared (R28).

E15. **Concurrent same-name scaffolder** — two `pm qa add-instruction
<same-name>` invocations at once leave one valid instruction file; any
loser names `pm qa edit`, and no invocation leaves a truncated/corrupt
file or traceback.

E16. **Concurrent autostart requests** — two plain shells run
`pm autostart add` for the same PR and for different PRs at once while the
TUI runs: each target lands exactly once in `pm autostart list`, no reply
is lost or corrupted, and neither invocation prints a traceback. With no
TUI, both name `pm session` and exit 2 without touching the target set.

E17. **`review-loop stop` against a live loop** — the refusal is a no-op
for the running loop: its review window/process is untouched (same window
id, still listed) while the command bar answers with the cancel path
(R32).

E18. **Multi-line failure from the command bar** — `pr add X --depends-on
bogus` and `pr note edit <id> bogus 'x'` end their stderr with context
lines, so the bar's last-line rule can hide the `pm pr list` /
`pm pr note list <id>` remedy; `pr note list <id>` and `plan list` show
only their last row (R35).

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

E9. **`pm pr signoff help` under older Click (8.1.x)** — confirmed
reproduced while planning: with Click 8.1.7 (allowed by the project's
`click>=8.0`) and the PR checkout on `PYTHONPATH`,
`pm pr signoff help` prints `Error: No such command '--help'.`; `pm watcher
help` fails the same way, while `pm pr help` / `pm plan help` (which
register a real `help` command) work. Under Click 8.5 all three work. If
a scenario reproduces this, it is a real defect in the help alias.

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

## Run history (as of 2026-11-03)

Scenarios 1–18 have run against this branch. Scenario titles and verdicts
(see the PR notes for the detailed errata and captures):

- 1–5: CLI help discoverability; wrong-state/not-found remedies; TUI QA
  modes and command-bar help; concurrent QA/review remedies; plan name
  (1–4 PASS, 5 NEEDS_WORK, fixed in b8ed).
- 6–9: help renderers (INPUT_REQUIRED, CLI half verified); watcher /
  backend / prompt surfaces (PASS); sign-off + skip_qa (PASS); concurrent
  CLI actors on one PR (NEEDS_WORK, fixed by the start lock in a22c1f18).
- 10–15: concurrent starts (PASS); CLI QA-mode hint (PASS); TUI help /
  focus (PASS); command-bar identifiers / modes / fresh / loop / Busy
  (PASS); `improvements` naming (PASS); top-level help + Click versions +
  launcher remedy (NEEDS_WORK, fixed in 9e10f888).
- 16–18: command-bar `--help` / quoting / focus (PASS); CLI refusals for
  scaffolds, dependencies, QA ids and terminal PRs (PASS); autostart owner
  refusals and group `help` aliases on Click 8.1.7/8.5.0 (PASS).
- 19 (plans-view and standalone-PR plan remedies) was launched but its
  run was interrupted by the workdir/runner recovery; no verdict was
  recorded. Scenario 20 from that run ("Concurrent actors on shared state,
  library files, and the command bar") was queued but never launched.

The next plan therefore starts at scenario 20 and covers: the unrun
concurrency edge cases E15/E16/E17, the command-bar CLI passthrough
(R35/E18), fresh restarts on start/review/signoff (R2/R3), and the
single-instruction QA path (`pm qa run`) plus the `pm qa`/launch remedies.

