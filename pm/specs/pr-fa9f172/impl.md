# Implementation Spec — pr-fa9f172

Self-documenting + consistent pm commands: complete `--help`, actionable
errors, unified flags.

## Scope

Three changes plus a consistency sweep:

1. **Complete, accurate help** for every command/subcommand, including the
   command-bar and TUI-key equivalents where they exist.
2. **Self-documenting errors**: every wrong-state / already-running /
   must-use-the-TUI / not-found / needs-a-flag error names the exact
   corrective command (and TUI equivalent).
3. **Consistent flags/verbs** across `pr start` / `pr review` / `pr qa` /
   `pr merge` — `--fresh` where the behavior really matches.
4. Sweep the CLI + command-bar surface for stale/inaccurate text and
   reconcile the stale `plan=ux` name to the real plan id `improvements`.

Motivating failure: restarting QA requires the command-bar form
`pr qa fresh <id>` (TUI `z t`), but `pm pr qa --help` did not list the
`fresh` mode, so the restart path was undiscoverable.

Authoritative constraints from the PR note:

- `pm pr qa` (CLI) currently *validates and directs the user to the TUI*; it
  does not start QA. `pm qa run` is a separate, single-instruction interface.
- Do **not** resurrect removed review-loop `stop` / all-PR-autostart paths.
- Do **not** invent `--fresh` semantics merely for uniform spelling; add it
  only where behavior really matches.
- Preserve command authority, manual merge/spec gates, target isolation.
- Current plan ids (`improvements`), not stale `ux` references, are
  authoritative.

## Requirements (grounded in code)

### A. Complete and accurate `--help`

**A1. `pm pr qa` (`pm_core/cli/pr.py:2733`).** The docstring must list:
- the CLI behavior: validate a PR and print the exact command-bar / TUI form
  (it never starts QA itself);
- every command-bar mode the TUI supports (`pm_core/tui/pr_view.py:732-772`):
  - `pr qa [PR_ID]` — focus an existing run or start one (= TUI `t`)
  - `pr qa fresh [PR_ID]` — fresh restart (= TUI `z t`)
  - `pr qa loop [PR_ID]` — start/stop the QA loop (= TUI `zz t`)
- the accepted `--fresh` / `--loop` spellings in the command bar (see C1);
- the separate `pm qa run <instruction> --pr <id>` interface (single
  instruction, not the full loop).

Use Click's `\b` paragraph marker so the table is not re-wrapped.

**A2. `pr start` / `pr review` / `pr merge` / `pr signoff`.** Each docstring
adds a short equivalents table:
- `pr start`: CLI `pm pr start [--fresh] [--companion] <id>`; command bar
  `pr start [--fresh] [--companion] <id>`; TUI `s` / `z s` (fresh) /
  `S` (companion) / `z S`.
- `pr review`: CLI + command bar `pr review [--fresh] <id>`; TUI `d` /
  `z d` (fresh) / `zz d` (loop).
- `pr merge`: CLI + command bar `pr merge <id>`; TUI `g` / `G` (companion).
  State explicitly that merge has **no** `--fresh`: there is no session to
  restart, so each run re-evaluates the gate (and `pm pr merge` is the
  retry).
- `pr signoff` group: CLI `pm pr signoff [--fresh] [--background] <id>`
  (the hidden `run` subcommand is the routed form) and subcommands
  `record` / `integrate`; TUI `i`.

**A3. Top-level `HELP_TEXT` (`pm_core/cli/__init__.py:584`).** Add the
missing real commands so the summary is not stale:
`pm pr merge`, `pm pr qa`, `pm pr auto-sequence`, `pm pr spec`,
`pm pr spec-approve`, `pm pr spec-path`, `pm pr dashboard`, `pm qa debug`,
`pm qa launch`, `pm qa edit`, `pm project set`, `pm log`,
`pm session home|kill|mobile|name|tag`, `pm container build-base`,
`pm fake-claude`, `pm fake-github`, `pm setting`, `pm autostart clear`.
Also add a "TUI / command bar" section pointing at `?`, `pm tui keys`, and
`/`.

**A4. Command-bar help must match.**
- `pm_core/tui/screens.py` `HelpScreen` gains a "Command Bar" section
  listing the command-bar forms and their TUI-key equivalents.
- `pm tui keys` (`pm_core/cli/tui.py:264`) gains the same section and the
  missing real bindings (`i` sign-off, `z d`, `S`, `G`, `Y`, `o`, `V`, `w`).
- Typing `help`, `?`, or `commands` in the command bar opens the
  `HelpScreen` instead of shelling out to `pm help` (which currently logs
  only the last line — effectively no help).

A single shared source of truth, `pm_core/command_surface.py`, holds the
command-bar/CLI/TUI-equivalence table so the three renderers cannot drift.

### B. Self-documenting errors

Every user-facing wrong-state / already-running / must-use-the-TUI /
not-found / needs-a-flag error names the exact corrective command and, when
one exists, the TUI equivalent. Concretely:

**B1. TUI QA (`pm_core/tui/qa_loop_ui.py`).**
- `start_qa` "QA already running for {id}" →
  "QA already running for {id} — restart with `pr qa fresh {id}`
  (TUI: select the PR, press z t)."
- `start_or_stop_qa_loop` "… — z t to stop" → "… — zz t to stop"
  (currently names the wrong key; `z t` is fresh restart).
- `stop_qa` "No QA running for {id}" → "… — start with `pr qa {id}`
  (TUI: t)."
- held/INPUT_REQUIRED message gains the stop/restart remedies.
- `PR not found` → name `pr list` / TUI `r`.

**B2. TUI review loop / watcher (`review_loop_ui.py`, `watcher_ui.py`).**
`PR {id} not found` names `pr list`; "already running" names the stop path
(TUI `zz d`, or `pm watcher stop <type>`).

**B3. CLI `pm pr qa`.** Wrong-status error names the transition command
(`pm pr start <id>` for pending; `pm pr review <id>` for in_progress);
"no candidates" names `pm pr list`; no-tmux already names `pm session` and
the command-bar form, keep and add the TUI key `t`.

**B4. CLI lifecycle refusals (`pm_core/cli/pr.py`).** `pr start`,
`pr review`, `pr signoff`, `pr merge`: every "already merged" / wrong-status
/ pending refusal names the next command (`pm pr show`, `pm pr start`,
`pm pr review`, `pm pr signoff`, `pm pr qa`) and the TUI key where one
exists. `_closed_reopen_hint` already does this; keep it.

**B5. Not-found helpers and commands.** `_require_pr`
(`pm_core/cli/helpers.py:370`) adds `Run 'pm pr list'`; `_require_plan`
adds `Run 'pm plan list'`. `pr cd` / `qa captures-path` / `qa run` /
`qa show|edit` / `plan fix` / `provider show|remove` add the matching
listing command. `pm tui *` "No TUI pane found" adds `pm session`.

**B6. Command bar.** `PR not found: <id>` (`pm_core/tui/pr_view.py`) adds
"see `pr list` (TUI: r to refresh)".

Out of scope: argument-parser errors (`--dir requires --global`), internal
guard errors, and warnings that are not user actions.

### C. Consistent flags/verbs

**C1. `--fresh` in the command bar for `pr qa`.** `pr qa <id> --fresh` ≡
`pr qa fresh <id>` and `pr qa <id> --loop` ≡ `pr qa loop <id>`. The parser
accepts the flag anywhere in the argument list, and rejects an unknown flag
with a corrective message naming the accepted forms. Extract the parser into
a pure helper so it is unit-testable.

**C2. CLI.** `--fresh` remains on `pr start`, `pr review`, `pr signoff`,
`plan add`, `plan breakdown`, `plan review`, `guide`, `cluster explore`.
`pm pr qa` and `pm pr merge` do **not** gain `--fresh` (see Ambiguity 1).
Help for both says so explicitly so the absence is intentional, not a gap.

**C3. Verb/naming alignment.** Make help consistently say "fresh restart"
for the `--fresh` concept and use `pm pr signoff` (not `pm pr signoff run`)
in remedies. `pm qa run --help` states it is the single-instruction
interface, distinct from the full `pm pr qa` loop.

### D. Plan-name reconciliation (`ux` → `improvements`)

Change stale `plan=ux` / `--plan ux` / "`ux` plan" references to the real
plan id `improvements` in:
- `pm_core/prompt_gen.py` (all 12 sites; these are injected prompts),
- `pm_core/cli/watcher.py` (watcher list help),
- `pm_core/watchers/discovery_supervisor.py`,
- `pm_core/watchers/improvement_fix_impl_watcher.py`,
- `pm/plans/plan-regression.md`,
- `pm/docs/literature-review.md`.

Leave historical records untouched: `pm/specs/**` and
`pm/docs/adversarial-review/**`. Never touch `tui-ux` (a different, real
plan).

## Implicit Requirements

- **No import cycles.** `pm_core/command_surface.py` must import nothing
  from `pm_core.cli` or `pm_core.tui`; both sides import it.
- **Click formatting.** Multi-line tables must survive Click's wrapper;
  use `\b` in docstrings. Keep lines under ~78 columns for narrow terminals.
- **Textual markup safety.** HelpScreen labels use Textual markup;
  command-bar log lines must not contain `[`-sequences that parse as markup
  (PR ids do not, but escape user-supplied text where already done).
- **Behavior preserved.** No lifecycle change: no new status transitions,
  no new launch paths, no change to merge/spec gates or target isolation.
- **Exit codes unchanged** for existing error paths (1).
- **Help remains discoverable** via `pm <cmd> help`, `-h`, `--help`
  (HelpGroup alias behavior must keep working).
- **Tests must not require tmux or a live project** — use Click's
  `CliRunner` and pure helpers.

## Ambiguities and Resolutions

**1. Does `--fresh` belong on `pm pr qa` / `pm pr merge`? [RESOLVED]**
The task text says "accept `--fresh` everywhere", but the PR note says not
to invent semantics. `pm pr qa` is a diagnostic that never launches QA, and
`pm pr merge` has no resumable session to restart, so `--fresh` has no
behavior to select.
Resolution: `--fresh` is accepted where it already means "restart this
session" (`pr start`, `pr review`, `pr signoff`) and in the **command bar**
for `pr qa`, where `fresh` genuinely restarts the run. `pm pr qa --help`
and `pm pr merge --help` state that the CLI form has no `--fresh` and name
the command-bar/TUI route instead. Tests assert the command-bar equivalence
and the explicit absence on the CLI.

**2. What does "the command-bar help should match" mean? [RESOLVED]**
Resolution: a shared table (`pm_core/command_surface.py`) renders the same
forms in `pm pr qa --help`, the `?` HelpScreen, and `pm tui keys`; and
`help`/`?`/`commands` typed in the command bar open the HelpScreen. This
makes the command bar self-documenting rather than relying on `pm help`
output (which the command bar currently truncates to one line).

**3. How broad is the error sweep? [RESOLVED]**
Resolution: all user-facing state/launch/not-found errors in
`pm_core/cli/{pr,qa,plan,helpers,provider,tui,watcher}.py` and the TUI
QA/review/signoff/watcher modules, as enumerated in B. Argument-validation
and internal errors are left alone; changing them adds noise without a
corrective action.

**4. Which `ux` references are authoritative? [RESOLVED]**
`pm/project.yaml` has plan id `improvements` (active) and no `ux`; `tui-ux`
is a different plan. Resolution: rewrite live code/docs/prompts to
`improvements`; do not rewrite historical specs/reviews.

**5. Should `run` become visible under `pm pr signoff`? [RESOLVED]**
No: `_SignoffGroup` routes `pm pr signoff <id>` to it, and exposing a
second spelling would grow the surface. Instead the group docstring names
the routed form and `--fresh` so help is complete.

## Edge Cases

- **`pr qa` command bar with both a positional mode and a flag**
  (`pr qa fresh pr-001 --loop`): the flag wins only if unambiguous; a
  conflict is rejected with a corrective message naming the accepted forms.
- **`--fresh` before or after the PR id** (`pr qa --fresh pr-001`,
  `pr qa pr-001 --fresh`) both work.
- **Unknown command-bar flag** (`pr qa pr-001 --frosh`) is rejected, not
  silently ignored.
- **PR id that looks like a flag** — ids always start `pr-` or are numeric,
  so flag scanning must not treat a numeric GitHub PR number as a flag.
- **Command bar `help` with arguments** (`help pr`) opens the general
  HelpScreen; no per-topic help is invented.
- **`pm pr qa --help` on a terminal narrower than the table** — Click wraps
  lines; tests assert substrings (`fresh`, `loop`, `z t`, `zz t`) rather
  than exact layout.
- **`pm tui keys` and HelpScreen drift** — both read the shared table, so
  a single edit updates all surfaces; a test asserts both contain the QA
  forms.
- **TUI log markup** — the new remedy strings use backticks/plain text and
  no `[/...]` sequences.
- **Plan rename scope** — `tui-ux` and `plan-tui-ux` must not be rewritten;
  a test asserts `tui-ux` survives.

## Tests (new `tests/test_command_surface.py`)

1. `pm pr qa --help` contains `fresh`, `loop`, `z t`, `zz t`, and the
   command-bar forms; it does not claim the CLI starts QA.
2. `pm pr start --help`, `pm pr review --help`, `pm pr signoff --help`
   each contain `--fresh` and their TUI equivalents; `pm pr merge --help`
   names `g`/`G` and states there is no `--fresh`.
3. Every command's `--help` exits 0 (walk the Click tree), and each group's
   help lists every non-hidden subcommand.
4. `HELP_TEXT` mentions `pm pr merge`, `pm pr qa`, `pm pr auto-sequence`,
   and every `pm ...` path it names resolves in the Click tree (stale-help
   guard).
5. `pm tui keys` and the shared command-surface text both contain the QA
   forms.
6. Command-bar parser: `pr qa pr-001 --fresh` → (`fresh`, `pr-001`);
   `pr qa fresh pr-001` → same; `--loop`; flag before id; conflicting
   modes rejected; unknown flag rejected.
7. QA already-running message (via a fake app double, or by asserting the
   source constant) contains `pr qa fresh` and `z t`.
8. `_require_pr` / `_require_plan` error text contains `pm pr list` /
   `pm plan list`.
9. No live `plan=ux` references remain in the code/doc paths listed in D
   (allow historical `pm/specs/**`); `tui-ux` survives.

## Files

- `pm_core/command_surface.py` (new) — shared command-bar/CLI/TUI table.
- `pm_core/cli/pr.py` — `pr qa`/`start`/`review`/`merge`/`signoff` help +
  remedies.
- `pm_core/cli/__init__.py` — `HELP_TEXT` completion.
- `pm_core/cli/helpers.py` — not-found remedies.
- `pm_core/cli/qa.py` — not-found + single-instruction clarification.
- `pm_core/cli/plan.py`, `provider.py`, `tui.py`, `watcher.py`, `session.py`,
  `cluster.py` — remedies and `pm tui keys`.
- `pm_core/tui/pr_view.py` — command-bar parser (`--fresh`/`--loop`),
  `help`/`?` routing, not-found remedies.
- `pm_core/tui/screens.py` — Command Bar section in HelpScreen.
- `pm_core/tui/qa_loop_ui.py`, `review_loop_ui.py`, `watcher_ui.py` —
  actionable state messages.
- `pm_core/prompt_gen.py`, `pm_core/watchers/*.py` — `ux` → `improvements`.
- `pm/plans/plan-regression.md`, `pm/docs/literature-review.md` — same.
- `tests/test_command_surface.py` (new); `tests/test_log_message_force.py`
  and `tests/test_qa_background_focus.py` updated for the new QA messages.

## Implementation Notes (shipped)

- `pm_core/command_surface.py` holds `QA_MODES`, `COMMAND_BAR_COMMANDS` and
  `QA_FLAG_NOTE_LINES`; `pm pr qa --help`, the TUI `?` HelpScreen, and
  `pm tui keys` all render from it. `QA_FLAG_NOTE_LINES` documents the
  `pr qa <id> --fresh` / `--loop` flag spellings in all three surfaces
  (the positional table alone would have hidden them); the QA command-bar
  rows are derived from `QA_MODES` so the two tables cannot drift. The
  HelpScreen escapes `[` as `\[` so option brackets display.
- `pm pr qa` help is supplied via `@pr.command(help=_QA_HELP)` because a
  Python f-string cannot be a docstring (`__doc__` stays `None`).
- The command bar accepts `pr qa <id> --fresh` / `--loop` via the pure
  `parse_qa_command()` helper; conflicting modes and unknown options are
  rejected with the accepted forms named. Typing `help`, `?`, `commands`,
  or `help <topic>` in the command bar opens the HelpScreen.
- `pm pr merge` and CLI `pm pr qa` deliberately have no `--fresh`; both
  help texts say so and name the command-bar/TUI route.
- Existing exact-message assertions in `tests/test_log_message_force.py`
  and `tests/test_qa_background_focus.py` were updated to the new,
  corrective QA messages (prefix assertions plus the remedy).
- `pm tui keys` also gained the missing real bindings (`i`, `z d`, `S`,
  `G`, `Y`, `o`, `V`, `w`).
- Remaining user-facing TUI not-found messages that the first pass missed
  (spec review in `app.py`, plan file and QA item in `pane_ops.py`) now
  name `pr list` / `pm plan list` / `pm qa list`.
- Review-loop i2: `command_surface.escape_markup()` replaces the
  rich/textual `escape()` in the command-bar QA error — those only escape
  a bracket that opens a *recognised* tag, so `[PR_ID]` was swallowed and
  the corrective usage text vanished from the log line. `pr_view`'s QA
  modes are now derived from `command_surface.QA_MODES` (no second list to
  drift). `_SignoffGroup` inherits `HelpGroup` so `pm pr signoff help`
  works like every other command. `pm pr qa --help` states outright that
  the CLI has no `--fresh`/`--loop`. Review/merge/sign-off window tmux
  errors name `pm session`. The sibling regression description in
  `pm/plans/plan-regression.md` now matches the no-`--fresh`-on-CLI
  resolution.

- Review-loop i3: corrected inaccuracies the sweep itself had introduced
  or missed. `w` is a prefix, not a direct binding — both
  `pm tui keys` and the `?` HelpScreen now say `w` opens the watcher
  prefix (`ww` list, `wf` focus, `ws` start/stop, `wr` review) instead of
  claiming `w` focuses the watcher, and the undocumented `y` cleanup-then
  prefix (`ys`/`yd`/`yt`) is listed. The duplicated `O`/`A` rows in
  `pm tui keys`' PR Actions block were dropped (the dedicated Auto-start
  block already documents them). `pm pr sync-github` and
  `pm pr import-github` no longer point at commands that cannot help on a
  non-GitHub backend: they name `pm pr merge <pr-id>` and
  `pm pr add <title>`. The shared table's autostart TUI column now says
  which key does which verb (`O` add / `A` toggle / `a` runs). Dead
  assignment removed from the command-bar QA error path.

- Review-loop i4: fixed remedies that named a command which does not do the
  action they claim. The command bar's QA branch resolves the same PR
  identifiers as the CLI (`pr-001`, `42`, `#42`) instead of only the
  internal id, so the `pr qa #N` command the CLI prints works for a
  GitHub-backed PR (the spec's numeric-id edge case). `pm pr merge --help`
  no longer claims a merge starts no Claude session (it launches the
  post-merge repo-update window); it says there is no resumable session,
  so each run re-evaluates the gate. The review-loop "no loop running"
  remedy names the command-bar `review-loop <id>` form (TUI `zz d`), not
  plain `pm pr review`, which opens a one-shot review. The watcher
  already-running remedy no longer says `pm watcher stop` stops it (that
  command only prints guidance); it names `ws` and points at `pm watcher
  stop` for guidance. `pm watcher stop`'s own help now says "Explain how
  to stop a running watcher" instead of promising the action.
