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

- Review-loop i5: two things the sweep still got wrong.
  (a) The `?` HelpScreen clipped every row at the 50-column container
  (`.help-row { height: 1 }` with natural width), so the new Command Bar
  section lost its CLI/TUI half exactly where the equivalents start —
  and the `y`/`w` rows added in i3 were cut too. `.help-row` is now
  `width: 100%; height: auto`, so long rows wrap; a Textual `run_test`
  assertion renders the screen and checks the tails of the longest rows.
  (b) `_next_step_for_status(..., "in_review")` and the `pr signoff`
  "no qa/sign_off PR" remedy named `pm pr qa <id>` as the way to *run*
  QA, but that CLI is diagnostic only (it prints the command-bar form and
  exits 1) — the remedy sent the operator in a circle. Both now name the
  action (`t` in the TUI, `pr qa <id>` in the command bar). Also added
  `[--companion]` to `pm pr merge`'s equivalent-forms line and table row
  (the flag is real), and replaced the `review-loop` table's "(TUI only)"
  with the actual one-iteration CLI form `pm pr review --review-loop`.
  Correction to the i4 note: the watcher already-running message does not
  itself name `ws` — it points at `pm watcher stop`, which names `ws` —
  because the `ws` chord toggles only the auto-start watcher while
  `start_watcher` accepts any type.

- Review-loop i6: applied the i4 display-id fix to the rest of the command
  bar. `edit #42` and `review-loop #42` still used `store.get_pr` (internal
  id only), so the same identifier the CLI accepts (`pr-001`, `42`, `#42`)
  failed there; all three branches now share `_resolve_command_bar_pr` and
  select the resolved internal id. The `?` HelpScreen's PR-action rows were
  brought in line with `pm tui keys`: `s`/`d`/`g` name their `z s`/`z d`/
  `zz d`/`G` modifiers and `Y` (cleanup workdir) is listed — they had
  drifted exactly where the two surfaces overlap. The Textual render test
  asserts those rows.

- Review-loop i7: final consistency pass. `command_surface` now names its
  section header (`COMMAND_BAR_HEADER`) instead of re-deriving it from the
  rendered text, and `HelpScreen` imports the module at top level (it has
  no imports, so there is no cycle to dodge). Wording: `pm pr qa` help no
  longer implies you must already be inside a session ("If no pm session is
  running, start one with `pm session`"); `pm pr merge` on a pending PR no
  longer repeats "start" twice; the TUI's "No watcher running" now names
  `ws` / `pm watcher start`; `pm tui keys`' summary matches its command-bar
  section; `HELP_TEXT`'s `pr start` line names the real `[--companion]`.
  Tests added: command-bar `help`/`?`/`commands` open the HelpScreen (the
  branch was previously untested), an unknown command-bar PR id names
  `pr list`, the CLI deliberately rejects `--fresh` on `qa`/`merge`, and
  `pm pr qa`'s own wrong-status refusal carries `pm pr start`.

- Review-loop i8: two remaining accuracy gaps in the help surfaces.
  (a) The command bar's "No PR specified for QA" remedy named the plain
  `t` key even for a `fresh`/`loop` request; it now reads the matching key
  (`z t` / `zz t`) from `command_surface.QA_MODES`, so the named TUI
  equivalent matches the mode the operator asked for. (b) `pm tui keys`
  was still a strict subset of the `?` screen: it omitted `x`, `X`, `f`,
  `F`, `v`, `M`, `H`, `m`, `C`, `/`, `ctrl+r` and the tmux `prefix P`/
  `prefix M`/`prefix R` bindings, which the `?` screen documents — the same
  two-list drift this PR is about. Both lists now cover the same direct
  bindings, and a test asserts `pm tui keys` names each of them. The QA
  command-bar dispatch also refuses a mode the parser accepts but no
  handler implements instead of silently starting a plain run, and the
  unused `textual` parameter was dropped from `qa_mode_lines`.

- Review-loop i9: the motivating failure's other surface. `pm pr qa fresh`
  (or `loop`) typed on the CLI used to answer `PR 'fresh' not found` — the
  same discoverability miss one surface over, now that the help documents
  the mode. `pr_qa` recognises a positional mode and names the command-bar
  form and TUI key instead of treating it as an id. The `--fresh` option
  help on `start`/`review`/`signoff` now opens with "Fresh restart:", the
  wording `command_surface` and the docstring tables already use (C3). A
  test asserts the positional-mode hint for both modes.

- Review-loop i10: three accuracy gaps that survived i1–i9.
  (a) `pm pr merge --help` said "Re-run `pm pr merge` to retry", which
  contradicts the sentence before it: a refusal calls
  `_return_to_signoff`, invalidating the approval, so re-running merge
  alone refuses again. The help now names the real path — fresh sign-off
  (`pm pr signoff --fresh <id>`, TUI `i`) then merge, with
  `--no-signoff-check` only to finalize an already-published merge. A test
  pins both halves.
  (b) `pm tui keys` still said `Enter Select/expand PR`; `TechTree` posts
  `PRSelected` then calls `action_edit_plan`, and the `?` screen already
  says "e / Enter Edit selected PR". It now reads "Edit selected PR (plans
  view: view plan file)", so the two surfaces agree. Test added.
  (c) The command-bar `help` branch pushed the HelpScreen without handing
  focus back to the active view. A bar keeps focus across a screen
  push/pop, so after closing help the next keystroke was typed into the
  command bar, unlike `?` and every other command-bar path. It now calls
  `app.action_unfocus_command()` first (which also handles the plans and QA
  views). Test added.

- Review-loop i11: the sweep's own remaining inaccuracies.
  (a) The shared table's catch-all row said the command bar accepts
  `<any pm command>` / `pm <command>`. It does not: `run_command` passes
  the typed tokens straight to `pm_core.wrapper`, so `pm pr list` fails
  with "No such command 'pm'". The command-bar column is now
  `<command> [args]` (CLI column keeps the `pm` prefix), with a comment and
  a test so the prefix cannot come back.
  (b) `pm getting-started`'s plans-view keys said `v=view`, but `v` is
  blocked in the plans view (`check_action`) and `Enter` is what opens the
  plan file; it also omitted `D=deps`. Now `... D=deps Enter=view file`,
  with a test.
  (c) `pr start`'s short help still said "print prompt"; it launches
  Claude (tmux window or blocking) — "clone, branch, launch Claude".
  (d) The `?` screen described `z` as "Modifier: kill existing before
  next", implying it applies to any action. `_consume_z` is read only by
  `s`/`S`/`d`/`t`, so the row now says "Prefix before s/S/d/t: restart
  instead of focus (zz d / zz t: loop)".
  (e) `pm tui keys` put the "Targets are additive" auto-start paragraph
  after the new command-bar section, disconnecting it from the Auto-start
  block; it now sits with that block.
  (f) Two shared-table rows exceeded the ~78-column budget (93 and 87);
  trimmed to 79 and 79 so narrow terminals wrap cleanly.

- Review-loop i12: accuracy of the sweep's own text, and the last of C3.
  (a) Correction to i11(d): `_consume_z` is *not* limited to `s`/`S`/`d`/`t`
  — `edit_plan`, `view_plan`, `launch_notes`, `view_log`, `launch_guide`
  and `launch_claude` read it too (and `launch_meta` consumes it without
  supporting fresh). The narrowed row hid working chords (`z e`, `z v`,
  `z n`, `z L`, `z H`, `z c`) and misstated the prefix. Both the `?` screen
  and `pm tui keys` now say "Prefix: restart the pane instead of focusing
  it (s S d t e v n L H c; zz d / zz t: loop)", and `pm tui keys` gained
  the `z` row it never had. Tests assert the row on both surfaces and that
  the old narrowed wording is gone.
  (b) `pm pr qa` exits 1 even when the PR is valid (it performs no action).
  That is the exact signal a driving Claude session reads as failure — the
  motivating failure mode — so the help now says so, with a test.
  (c) C3 said the `--fresh` help should say "fresh restart" consistently;
  `plan add`, `plan breakdown`, `plan review`, `guide` and `cluster
  explore` still said "Start a fresh session (don't resume)". All five now
  open with "Fresh restart: start a new session instead of resuming".
  (d) The CLI's positional-mode hint (`pm pr qa fresh`) and the
  command-bar's TUI-key lookup hardcoded `("fresh", "loop")` and their
  keys, duplicating the shared table. Both now derive from
  `command_surface.QA_MODIFIER_MODES` / `QA_MODE_KEYS` (added there), and
  the parametrized test reads the table too.
  (e) The stale-`ux` test only scanned `pm_core/**/*.py`; section D also
  lists `pm/plans/plan-regression.md` and `pm/docs/literature-review.md`.
  A second test scans both (allowing the explanatory line that names
  `plan=ux` *and* `improvements`).
  (f) C1's flag spellings reached the command bar but not the popup
  spinner: `pm _popup-cmd` routes any `pr qa …` through the TUI, and
  `_parse_tui_action` (session.py) only recognised the positional form.
  So `pr qa <id> --fresh` looked like a plain run and the spinner switched
  to the stale window the restart was about to kill — the race the
  `fresh` flag exists to prevent. `parse_qa_command` moved from
  `tui/pr_view.py` to `command_surface.py` (pure, no TUI deps) and
  `_parse_tui_action` now uses it; `pr_view` calls the shared copy. Test
  pins both spellings (and the rejected-command fallback).

- Review-loop i13: (a) `w` is a prefix, not a direct binding — both
  `pm tui keys` and the `?` HelpScreen now say "Watcher prefix: ww list,
  wf focus, ws start/stop, wr review" and list the undocumented `y`
  cleanup-then prefix (`ys`/`yd`/`yt`). (b) The duplicated `O`/`A` rows in
  `pm tui keys`' PR Actions block were dropped (the Auto-start block
  documents them). (c) `pm pr sync-github` / `pm pr import-github` no
  longer point at commands that cannot help on a non-GitHub backend; they
  name `pm pr merge <pr-id>` / `pm pr add <title>`. (d) The shared table's
  autostart TUI column says which key does which verb. (e) Dead assignment
  removed from the command-bar QA error path.

- Review-loop i14: (a) The *two-token* command-bar spelling
  `pm pr qa fresh <id>` (exactly what the help tells the operator to type
  in the command bar) still died on the CLI with Click's "Got unexpected
  extra argument (pr-001)" (exit 2) — the motivating failure one surface
  over. `_QaCommand.parse_args` keeps only the mode token when the rest
  are plain positionals, so `pr_qa` prints its corrective hint (exit 1);
  options (notably `--help`) are left to Click. Tests cover both modes and
  that `pm pr qa fresh --help` still shows help. (b) `R` (reload state from
  disk) was the one App binding neither help surface listed; both now do,
  with the parity test extended. (c) `pm pr merge`'s no-candidate remedy
  now names `pm pr list` instead of presuming the missing step is
  sign-off (the PR may be pending or merged). (d) The review, merge and
  sign-off window launchers said only "no workdir for <id>. Start the PR
  first."; each now names `pm pr start <id>` (TUI: s), matching the
  adjacent tmux remedies this PR already rewrote. Tests cover all three.

- Review-loop i15: two remedies whose *claims* did not match the code.
  (a) Correction to i14(c): the merge no-candidate message still said
  "sign-off comes first: `pm pr signoff <id>`" — the i14 note said the
  presumption was gone, but only the listing command had been added. A
  missing candidate may be pending (start first), in QA, or already
  merged, so the message now names `pm pr list` for the status and states
  sign-off as the *prerequisite* ("a PR must be signed off before it can
  merge"), which is true in every state. A test pins that "sign-off comes
  first" is gone. (b) The `pr signoff` wrong-status refusal said "sign-off
  runs after QA (expected qa or sign_off)" even on a `skip_qa` project,
  where there is no QA stage and `in_review` is a valid entry state: it
  now derives the expected list from `entry_statuses` and says "runs
  after review" under `skip_qa`. Tests cover both variants (the default
  wording is unchanged, so `tests/test_signoff.py` still pins it).

- Review-loop i16: the sweep's remaining un-remediated state errors, and
  the `skip_qa` sign-off inference they exposed.
  (a) `helpers._validate_tui_owner`'s "No TUI is running for session X"
  (surfaced verbatim by `pm autostart add …` outside a session) now names
  `pm session`, like every `pm tui *` refusal. `helpers.py` is in B3's
  enumerated file list; this path was missed. (b) `pm qa debug` outside a
  session said only "Run inside a pm tmux session"; it now names
  `pm session`. (c) `pr signoff`'s no-candidate message said "run QA
  first" in every project — under `skip_qa` sign-off follows review — and
  its bare-command inference filtered on sign_off/qa only, so a `skip_qa`
  project with an `in_review` PR reported "nothing to do" even though the
  status check already accepts `in_review` as an entry state. The filter
  now includes `in_review` under `skip_qa` (no new transition: the check
  below already allowed it) and the message names the real prerequisite
  ("pass QA" / "pass review"). (d) B3 asked the no-tmux `pm pr qa` path to
  name the TUI key `t`; it named only `pm session` and the command-bar
  form. It now prints the same `t` / `z t` / `zz t` line as the in-session
  path. Tests cover the no-TUI IPC message, the `qa debug` message, the
  skip_qa inference, both prerequisite wordings, and the valid `pm pr qa`
  path (command-bar form + TUI keys + exit 1).

- Review-loop i17: the last context-sensitive help rows, and the guard
  that was supposed to catch this class of drift. (a) The `?` screen's
  "Review Loop" / "QA Loop" sections (`zz d` / `zz t`) and its `z` prefix
  row were rendered in the plans and QA views, where `check_action` blocks
  the underlying tree actions (`review_pr` / `start_qa_on_pr`) — and in the
  QA view `d` is intercepted by `QAPane` as "debug item", so `zz d` there
  did the *wrong* thing, not nothing. Both are now tree-view only, like
  the other tree-only rows, with the negative-render test extended.
  (b) `pm pr merge --help` attached "(TUI: i)" to `pm pr signoff --fresh`,
  implying `i` performs a fresh restart; the sign-off group help says
  explicitly that no TUI key does. The sentence now names `i` as the
  router and says there is no fresh-restart key. (c) The stale-help guard
  in `test_help_text_only_names_real_commands` treated a token as a
  command name only when `isalpha()` — so every hyphenated command
  (`auto-sequence`, `fake-claude`, `spec-approve`, `build-base`, …) was
  silently skipped, and a rename would have passed. Any token that is not
  a placeholder (`<x>` / `[x]`), a flag (`--x`) or the capitalized
  description must now resolve. (d) Added a dispatch test for the command
  bar's QA branch: `pr qa fresh <id>`, `pr qa <id> --fresh` and
  `pr qa --fresh <id>` must all reach `fresh_start_qa`, and the `loop`
  spellings `start_or_stop_qa_loop`; the parser-equivalence tests alone
  did not pin the handler table.

  Observed while checking the `z` row, deliberately *not* changed here:
  the `z` prefix has no cancel timer (unlike `w` and `y`, which clear
  after 2 s), so a `z` that no action consumes stays armed across
  navigation and turns a later `s`/`d`/`t`/`e`/… into a destructive fresh
  restart; `i` (sign-off) does not consume `z` at all. That is pre-existing
  interaction behaviour, not part of this help/error sweep, and changing
  it (adding a timer, or clearing `z` on unrelated keys) is a UX decision
  with its own QA — worth a separate bug PR rather than a drive-by change
  in a docs-focused review.

- Review-loop i18: the popup spinner, the last two-token spelling, and the
  stop remedy for watcher types `ws` cannot toggle. (a) The picker's
  spinner (`pm _popup-cmd` → `_wait_for_tui_command`) parses the queued
  `tui:` command to decide which window to follow, but its state/window
  lookups are keyed by the internal id while the window name uses the
  display id (`qa-#42`). i4/i6 taught the command bar to accept `pr-001`,
  `42` and `#42`, so `pr qa #42 --fresh` started QA for the right PR while
  the spinner polled state for `#42` and matched no window — it sat until
  dismissed instead of following the rebuilt window. New
  `_resolve_spinner_ids()` maps the parsed id to `(internal id, display
  id)` before the lookups; same fix covers `review-loop #42`. (b)
  `_QaCommand` tolerated the two-token form only when the mode came first,
  so `pm pr qa pr-001 fresh` (the other command-bar spelling) still died on
  Click's `Got unexpected extra argument (fresh)` (exit 2). It now scans
  the argument list for the mode in either order and keeps the mode token
  so `pr_qa` prints its hint. (c) `pm watcher stop <type>` printed "press
  'ws'" for every type, but `ws` toggles only the auto-start watcher; it
  now names the requested type and says there is no TUI key for it. (d) The
  merge workdir refusal names `pm pr signoff <id>` (TUI: i) rather than
  only "re-run sign-off", and the `wf` chord's "No tmux session found"
  names `pm session`, matching the adjacent remedies. (e) The command
  bar's not-found remedy escapes the user-typed id, so a bracketed typo
  (`pr qa [x]`) no longer disappears from the message that names it.
  Tests added: spinner id resolution, the reversed two-token CLI form, the
  type-aware watcher-stop message, the merge workdir remedy, and the
  bracketed-id remedy.

- Review-loop i19: the last stale command reference in a help surface, and
  the remaining must-be-in-the-TUI refusals. (a) `pm tui keys`' auto-start
  paragraph said `autostart target X`; the group has no `target`
  subcommand (it is `autostart add`), so an operator copying the form got
  "No such command 'target'". It now says `autostart add X`, with a test.
  (b) `pm session home` ("Not inside a pm tmux session.") and `pm
  rebalance` ("Must be run from within a tmux session.") were the last
  outside-the-TUI refusals without the corrective command; both now name
  `pm session`, matching every other such error. Tests added. (c) The
  watcher already-running remedy pointed at bare `pm watcher stop`, which
  answers for the auto-start watcher; it now names the running type
  (`pm watcher stop <type>`), since `ws` toggles only auto-start. (d) The
  injected prompts (`prompt_gen.py` guidance block and watcher-review
  prompt, `pane_ops.py`) still listed `pm pr done`, a command that no
  longer exists (the step is `pm pr review`); the watcher-review key list
  also said `d` "marks it as done". Both corrected, with a test that the
  removed name cannot come back.

- Review-loop i20: help claims contradicted by the code, and two stale
  surfaces the sweep had not reached.
  (a) `pm pr signoff --help` and `pm pr merge --help` said there is no TUI
  key for a fresh sign-off ("CLI/command-bar only"). That is false: the PR
  action picker (prefix P) maps `z i` to `pr signoff --fresh`, and its
  header advertises "i=fresh signoff". Both helps now name the picker chord
  (the main-tree `i` remains the router), the shared table's signoff row
  reads "i / picker z i", and both `pm tui keys` and the `?` screen's
  `prefix P` row document the picker's `z s/d/t/i` / `zz d/t` chords.
  Tests pin the corrected text on both helps and the shared table.
  (b) `pm tui keys` said "Bare `autostart` only turns auto-start off". Bare
  `pm autostart` prints its help (it has no callback); disabling is `A` with
  no PR selected or `autostart clear`. Corrected, with a test that also runs
  the command to prove it does not disable anything.
  (c) `pm qa debug`'s window-creation failure said "make sure the pm
  session is running ('pm tui view')". `pm tui view` only reads an
  already-running TUI and fails for the same reason; the remedy now names
  `pm session`. (Its no-session refusal was fixed in i16; this is the
  other, window-creation path.) Test extended in
  `tests/test_container_fail_closed.py`.
  (d) `pm tui send --help`'s examples were from the old guide flow: `g`
  was labelled "launch guide" (it is Merge) and `x` "dismiss guide" (it is
  hide/show plan group). The guide is `H`. Examples corrected, and the
  block now uses `\b` so Click stops re-wrapping the list and examples
  into one run-on paragraph. `pm tui keys` also gained a "Help screen"
  section (Esc/? close, h discuss, j/k/J/K scroll) — the `?` screen's own
  bindings were documented only in its footer.
  (e) The tree's empty-state hints said "Press F to cycle filter", but `F`
  cycles the sort field and `f` cycles the status filter. Both messages
  (`No <status> PRs` and `No PRs to show`) now say `f`, and the existing
  widget test asserts the letter.

- Review-loop b8ed i1: the plan-name story's remaining live surface.
  QA marked "`improvements` is the one plan name across help, prompts, and
  watcher surfaces" NEEDS_WORK. The help and generated watcher prompts were
  clean, but `pm watcher list` — named in R22 alongside `pm watcher start
  --help` — printed only the display name, window and interval, so the
  improvement-fix watcher never read as driving `plan=improvements`.
  `BaseWatcher` gains a `DESCRIPTION` class attribute (set on all four
  built-ins) and `pm watcher list` prints it, naming the plan each watcher
  drives. A test asserts `plan=improvements` / `plan=bugs` and the absence
  of `plan=ux` in that output. Verified separately that every `--help`
  surface (152 leaf commands), the generated discovery / bug-fix /
  improvement prompts, and `pm tui keys` are free of `plan=ux`; the only
  remaining occurrences in a `pm prompt <id>` output are this PR's own
  description, notes and spec, which section D deliberately excludes as
  historical records.

- Review-loop e4f7 i1: the sweep's last un-remediated not-found refusals.
  (a) The model-settings modal (`pm_core/tui/model_screen.py`) rendered a
  bare "PR <id> not found" when its PR vanished from a reload while the
  modal was open — the last user-facing TUI not-found message without the
  listing command (spec review, plan file and QA item were fixed earlier).
  It now names `pr list` / TUI `r`, with a test.
  (b) `pm qa launch`'s "No tmux session detected." (reached when tmux is
  present but its session name cannot be resolved) said nothing about the
  command that creates one; it now names `pm session`, matching the
  `requires tmux` refusal immediately above it. Test added.
  (c) The `?` screen's `z` row comment claimed every alternate-view chord
  was blocked by `check_action`; the notes / log / guide chords still work
  there, so the comment (not the row — the row stays tree-only by design)
  was corrected to say what is actually blocked or intercepted.

- Review-loop e4f7 i2: renderer agreement and the last save-path refusal.
  (a) The `?` HelpScreen rendered its own "Command Bar" title while
  `pm tui keys` rendered the shared "Command bar (press /):" — the exact
  drift this PR exists to stop, and the literal mismatch QA scenario 6
  flagged. The screen now renders `command_surface.COMMAND_BAR_HEADER`
  (styled like its other section headings), so the three surfaces title
  the section identically. The duplicate "/ Open the command bar" row
  moved its "type help there for this screen" hint onto the Panes & Views
  `/` row instead of repeating the key twice.
  (b) The screen used to slice `command_bar_help_lines_textual()[1:]` to
  drop the header. That section helper is gone; `command_bar_rows_textual()`
  now returns the rows and flag note only, so a future change cannot
  silently drop a row from the screen. A test pins the rows helper (no
  header, first row is `pr start`).
  (c) `model_screen._apply`'s "Not saved: PR <id> not found" (the PR
  vanished between opening the modal and the locked save) now names
  `pr list` / TUI `r`, matching the render path fixed in e4f7 i1.
  (d) The improvement watcher's stale "UX is taste-driven" comment now
  says `improvements`.

- Review-loop e4f7 i3: two silent dead ends in the plans view, and the
  command-bar focus hand-off in the QA view.
  (a) `launch_plan_activated` (Enter) and `handle_plan_action("edit")`
  (`e`) returned silently when the selected plan's file was missing, so
  the key read as broken — a live plan in this project (`plan-b6aac3d`)
  has no file on disk. Both now log the same "Plan file not found — run
  `pm plan list`…" remedy as `view_plan` (`v`), via one shared
  `_report_plan_file_missing` helper. An empty `file` no longer resolves
  to the project root (which exists) and opens the editor on the whole
  project.
  (b) Every command-bar branch ended with "plans pane else tech-tree", so
  in the QA view focus landed on the hidden tree and the QA pane's keys
  (j/k, Enter, e, d, a) went dead until the view was re-entered. A shared
  `_refocus_active_view` (mirroring `action_unfocus_command`) handles all
  three views; six duplicated blocks collapse into it.
  (c) The `z` prefix row now names the `wr` watcher-review chord, which
  also honors `z` (fresh restart); the test that claims to name "every
  action it modifies" was missing it.

- Review-loop e4f7 i4: the last unescaped user-typed text in the command
  bar. `guard_pr_action` renders the raw in-flight command
  (`app._inflight_pr_action`) into the "Busy" remedy, so a bracketed token
  (`pr qa [x]`) was swallowed by Textual's markup parser and vanished from
  the very message that names it — the same class of bug the QA / not-found
  / edit remedies escaped elsewhere (i2, i18). It now goes through
  `command_surface.escape_markup`, with a `Content.from_markup` assertion
  that the bracketed command survives.

- Review-loop e4f7 i5: two stale surfaces the sweep had not reached.
  (a) `pm help`'s `pm qa regression` line still read
  "(replaces `pm tui test`)". `pm tui test` was removed (moved to
  `pm qa regression`), so the parenthetical read as a runnable command and
  answered "No such command" — the same class as the `pm pr done`
  references already removed from the injected prompts. It now names the
  directory (`pm/qa/regression/`), and a test asserts HELP_TEXT names
  neither `pm tui test` nor `pm pr done`.
  (b) The three TUI pane launchers (`launch_claude`, `launch_discuss`,
  `launch_watcher_review`) logged a bare "Claude CLI not found" and
  returned. Unlike the CLI launchers, which fall back to a copy-paste
  prompt, these left the key looking broken with no next step. Each now
  says "install Claude Code first", matching `claude_launcher`'s own
  "install it first", with a parametrized test.
  Full suite (minus the known markdown-module baseline): 5561 passed,
  1 skipped.

- Review-loop 6a82 i1: one help claim the picker's own code contradicts.
  Both `pm tui keys` and the `?` screen documented the PR-action picker's
  `z s/d/t/i fresh` / `zz d/t loop` chords unconditionally, but those
  chords exist only in the fzf picker. Without fzf the picker falls back
  to a numbered line menu (which prints its own "install fzf" tip) that
  has no chord handling — a `z` press is not a shortcut and just closes
  the popup. Both rows now say "requires fzf" and name the fallback, with
  a test asserting both surfaces (the same claim-versus-code drift this
  sweep exists to remove).
  Full suite (minus the known markdown-module baseline): 5563 passed,
  1 skipped.

- Review-loop 6a82 i2 (recorded here in i3; the i2 commit changed code and
  tests but not this spec): the last command-bar paths that did not hand
  focus back, and the last groups that did not accept the `help` alias.
  (a) The `autostart` branch focused the hidden tech-tree unconditionally,
  deadening the QA / plans pane keys until the view was re-entered, and the
  review-loop / `edit` not-found paths returned with the bar still focused,
  so the next keystroke was typed into it. All now use
  `_refocus_active_view` (the helper added in e4f7 i3), which mirrors
  `action_unfocus_command` for all three views. (b) `pm project` and
  `pm model` were defined as plain `click.Group`s and attached with
  `cli.add_command`, so they missed `HelpGroup` inheritance and answered
  "No such command 'help'"; both now use `cls=HelpGroup`. Tests: the
  QA-view focus hand-back for the autostart branch and both not-found
  paths, and a walk of every group asserting `pm <group> help` exits 0.
  Full suite (minus the known markdown-module baseline): 5567 passed,
  1 skipped.

- Review-loop 6a82 i3: documentation only. Recorded the i2 fixes above so
  the spec matches the shipped code, and re-verified the whole tree on the
  current checkout (see the count above). No source or test changes were
  needed this iteration.

- Review-loop 6a82 i4: two help claims the code contradicts, plus the
  last command-bar spelling that died on a bare Click error.
  (a) `pm pr review --help`'s new equivalent-forms block said `zz d`
  "start/stop the review loop", but `review_loop_ui.start_or_stop_loop`
  always starts a fresh loop (it supersedes a running one; its own
  docstring says the toggle was removed). The row now reads "start the
  review loop (supersedes a running one)", and the stale "start or stop
  loop" section comment above the function is corrected too. A test pins
  both halves.
  (b) `pm pr qa --fresh` / `--loop` — the *flag* spelling of a QA mode,
  the one a driving session is most likely to guess and the one the PR
  description asks to accept everywhere — still died on Click's
  `No such option '--fresh'` (exit 2), while the positional spellings
  already reached `pr_qa`'s corrective hint (i14/i18). `_QaCommand` now
  reads the shared `command_surface.QA_FLAG_MODES` map and keeps only the
  mode token in either position, so the flag form reaches the same hint
  naming the command-bar form and TUI key; the CLI still accepts no such
  flag (no QA runs, exit 1), which the help states. `--help` still wins:
  `pm pr qa --fresh --help` drops the flag and renders the help. The
  map is now public (`QA_FLAG_MODES`) so the command bar's parser and the
  CLI's tolerance cannot disagree about which flags exist.
  (c) `pm pr qa --help`'s inference sentence now matches `_infer_pr_id`:
  it also uses the active PR, not only the workdir and a single
  in_review/qa candidate.
  Full suite: 5584 passed, 1 skipped (with `markdown` installed; the
  prior iterations' "minus the known markdown-module baseline" caveat
  does not apply in this container).

- Review-loop 6a82 i5: the last dead-end refusals in the sweep's scope.
  (a) `view_plan` (`v`) on a standalone PR said only "No plan associated
  with this PR" — the documented key read as broken, the same class as the
  plan-file dead ends fixed in e4f7 i3. It now names the assign action:
  `M` (or `pm pr edit <id> --plan <plan-id>`).
  (b) The `C` key's "Not a shared session" named nothing; it now says how a
  session becomes shared (`pm session --global` / `--group <group>`), since
  there is no connect command to show in that state.
  (c) `_validate_tui_owner`'s stale-pidfile messages ("is not running",
  "unreadable", "not available (…)") said "restart the TUI" to callers that
  have no TUI — the pidfile is removed and these surface from `pm autostart
  …` in a plain shell. The dead-owner case now says "start it with `pm
  session`"; the two cases that can also be a live TUI with a clobbered
  file name both routes ("Ctrl+R in the TUI, or `pm session` if none is
  running"), matching `_missing_command_cap_result`'s wording.
  (d) `launch_qa_item`'s malformed-id refusal now names `pm qa list`, like
  its not-found sibling.
  (e) The two scaffolding "already exists" refusals (`_qa_add`'s shared
  implementation and `qa mocks add`) name the edit command (`pm qa edit
  <id>` / `pm qa mocks edit <id>`) or "choose another name" instead of
  stopping at the path. qa.py is in the spec's B list, and "already
  exists" is one of the error classes it covers.
  Tests added in `tests/test_command_surface.py` for all five; the
  related pidfile/QA/autostart files pass.

- Review-loop 6a82 i6: three sites i5's own class left behind.
  (a) `_signal_tui`'s stale-owner result — the race where the TUI was live
  at validation and gone by the signal — still said "restart the TUI",
  although the process is gone and its pidfile is removed. It now says
  "start it with `pm session`", matching the `_validate_tui_owner` messages
  i5 fixed on the other pidfile path.
  (b) The "has not finished starting up" message for a zero-length pidfile
  named only Ctrl+R; a file left empty by a TUI killed mid-claim stays that
  way forever and the caller may have no TUI. It now names both routes
  ("Ctrl+R in the TUI, or `pm session` if none is running"), like the
  adjacent messages.
  (c) `_qa_author` (`pm qa author-instruction|author-regression|
  author-artifact`) was the third "Already exists" scaffolder and still
  stopped at the path; it now names `pm qa edit <id>` or "choose another
  name", like `_qa_add` and `qa mocks add` (i5). `pm qa launch`'s
  malformed-id refusal gained `pm qa list`, matching the TUI sibling fixed
  in i5.
  Tests added in `tests/test_command_surface.py` for all four.

- Review-loop 6a82 i7: the command bar's unhandled parse, a removed
  spelling, and one more dead-end remedy.
  (a) `handle_command_submitted` parsed the typed command with
  `shlex.split` unguarded. An unmatched quote — the ordinary case is an
  apostrophe in a note (`pr note add pr-001 don't forget`) — raised
  `ValueError` out of the Textual message handler, which treats it as
  fatal: the TUI crashed. The popup runner (`pm _popup-cmd`) already
  answers "Invalid command syntax"; the command bar now does the same,
  names the quoting fix, hands focus back, and clears the in-flight guard
  the prefix loop may have set (otherwise every later PR action reports
  "Busy"). Tests cover both the message and the cleared guard.
  (b) `review-loop stop` (a spelling whose toggle was removed) fell
  through to the PR-id path and answered "PR not found: stop — see
  `pr list`", sending the operator to a listing command for a command
  that does not exist. The branch now refuses `stop` / `cancel` / `off`
  with the real cancel path (Ctrl+R, or Ctrl+C in the review pane) and
  still accepts the optional `start` token the picker's `zz d` chord
  queues. Tests cover both.
  (c) `pm pr cd` on a merged or closed PR whose workdir was cleaned up
  said "Create it with `pm pr start <id>`" — a command that refuses a
  terminal PR ("already merged"), the same dead-end class as the
  diagnostic-QA remedy removed earlier. The remedy is now status-aware:
  terminal PRs name `pm pr show <id>`; startable PRs keep the start
  remedy. Tests cover both.
  Full suite: 5603 passed, 1 skipped after the i7 edits (5594 before
  them; the nine new cases are the two quote tests, the three stop-token
  cases, the start-token case, and the three `pr cd` cases).

- Review-loop 6a82 i8: the last remedy-less `autostart` refusals, a
  self-contradicting expected-states list, and `--help` in the command bar.
  (a) `pm_core/cli/autostart.py` `_resolve_owner`'s three pidfile branches
  ("no pidfile", "stale pidfile", dead pid) said only "is not running" —
  a dead end for a caller with no TUI, although the same function's "no pm
  session" branch names `pm session` and `helpers._validate_tui_owner`
  names it for the identical conditions. All three now name `pm session`.
  `_validate`'s "unknown PR id(s)" / "already merged/closed" now name
  `pm pr list`; the TUI siblings in `pm_core/tui/auto_start.py`
  (`add_targets` / `remove_targets`, reached by the command bar's
  `autostart add`) carry the same remedy.
  (b) Under `skip_qa`, `pr_signoff`'s wrong-status refusal read
  "sign-off runs after review (expected qa, in_review, sign_off)" — the
  expected list contradicted the sentence, and the code comment claimed
  `qa` was dropped. `qa` stays accepted (a record can predate the
  setting) but the advertised list is now `in_review, sign_off`.
  (c) `--help` / `-h` in the command bar ran the command through the CLI
  and logged only the *last* stdout line (a multi-line help came out as
  one useless line), and `pr qa --help` — the command this PR exists to
  make discoverable — died as "unknown QA option '--help'". Both now open
  the same HelpScreen `help` does, before the in-flight guard. The check
  tokenizes with `split()` (not `shlex`), so a quoted `--help` inside a
  note's text is left alone; unquoted, Click treats it as its own eager
  flag, so this matches the CLI. (It also stops `plan add --help` from
  launching a Claude pane running `pm plan add --help`.)
  Tests added in `tests/test_command_surface.py` for all three (owner
  pidfile remedies, autostart unknown/terminal listings, the skip_qa
  expected list, three command-bar `--help` spellings, and the quoted-text
  non-match). Related files pass (622 + 275 cases).

- Review-loop 6a82 i9: the command-bar help check tokenized the wrong way,
  plus two `--depends-on` refusals that stopped at "Unknown PR IDs".
  (a) `handle_command_submitted`'s new `--help` / `-h` branch split the typed
  command on whitespace (`cmd.split()`), so a flag *word* inside a
  multi-word quoted argument opened the help screen instead of running the
  command: `pr note add pr-001 'mention -h as a flag'` and
  `pr add 'Fix -h handling'` never reached `run_command`.  It now tokenizes
  with `shlex` — the same splitter `run_command` uses to build the CLI's
  argv — so a quoted phrase stays one value, while a bare `--help` still
  matches.  An unmatched quote falls through to the existing "Invalid
  command syntax" path rather than opening help.  The quoted-text test is
  parametrized over the multi-word cases.
  (b) `pm pr add --depends-on` and `pm pr edit --depends-on` said only
  "Unknown PR IDs" (the edit path printed nothing else), unlike every other
  not-found refusal in the sweep — including the `pm autostart add` sibling
  fixed in i8.  Both now name `pm pr list`, with a test for each.
  Related files pass (168 in `tests/test_command_surface.py`, plus the
  pr_view / pidfile / autostart / pr-notes suites).

- Review-loop 6a82 i10: two summaries that described less than the command
  does.
  (a) `pm help` (both the COMMANDS line and the TUI / COMMAND BAR section
  added by this PR) and `pm getting-started` still promised "TUI + notes
  editor", but `_session_start` says the notes pane is no longer
  auto-started — it opens on demand with `n` (or `pm notes` in a pane).
  Both help surfaces now say what `pm session` starts and point at `n`;
  `needs_guide`'s stale "session startup starts the notes pane" rationale
  and `_session_start`'s docstring are corrected too. A test asserts
  neither surface says "notes editor", that `n` is named on both, and that
  `pm tui keys` still documents it.
  (b) `pm pr edit --help`'s summary stopped at "title, description,
  dependencies, or status", hiding `--plan` and the no-options interactive
  editor (the TUI `e` / Enter path); the `HELP_TEXT` line repeated the
  shortened list. Both name every field now, with a test.
  Full suite: 5617 passed, 1 skipped.

- Master integration (2026-11-04, SIGNOFF_IMPL r1 return): merged
  `origin/master@c3bac6ce` (#296; merge base `c1fcecc5`) into the branch.
  Conflicts resolved preserving both sides:
  (a) `pm/project.yaml` — `store.merge_3way(base, ours=master,
  theirs=branch)` over the index stages, then rebuilt as master's text with
  the branch's changed blocks (`pr-fa9f172`, `pr-3d1055c`) swapped in and
  its two new records (`pr-fc6c29e`, `pr-86152a8`) inserted after their
  predecessors. This keeps master's block order and avoids the ~2000-line
  rewrap `store.save` produces; content verified equal to the 3-way merge
  by id (619 PRs, 22 plans, all branch notes present).
  (b) `pm_core/cli/__init__.py` — kept master's "isolated QA run" wording
  for `pm qa regression` and the branch's `pm qa debug` / `pm qa launch`
  lines.
  (c) `pm_core/prompt_gen.py` — took master's #284 isolated-run prose (it
  supersedes the branch's older sentence, and names no plan) and kept the
  branch's `improvements` plan name in the reconcile step, where master
  still said `ux`.
  (d) `pm_core/tui/pr_view.py` — the fuzzy `pr select` / `plan select`
  dispatch runs *before* the branch's guarded `shlex.split` (so a query
  like `user's` cannot raise), and both hand focus back through the one
  helper.

  Semantic reconciliation beyond the conflict picks:
  - One focus helper: `ProjectManagerApp._focus_current_view` now delegates
    to `pr_view._refocus_active_view`, so master's Esc path and the
    command-bar branches cannot drift. The helper queries by id only (no
    `expect_type`) so the `SimpleNamespace` app doubles keep working.
  - Master's #136/#284 surface reached the shared table: `pr select
    <query>`, `plan select <query>` and `qa regression <test-id>` rows were
    added to `command_surface.COMMAND_BAR_COMMANDS` (so the `?` screen and
    `pm tui keys` both document them), and `pm tui keys` gained the `]`/`[`
    fuzzy-match cycle key. The parity test now asserts them, so the hand
    list that missed them cannot regress silently.
  - Two master tests asserted pre-sweep behavior and were updated to the
    PR's documented contract while preserving their intent:
    `test_fuzzy_select_tui.test_other_commands_keep_exact_resolution` now
    asserts the id is still refused exactly *and* that the listing remedy
    is named; `test_regression_launch`'s `--help` case became a dedicated
    test that the command bar opens the HelpScreen (never a pane) instead
    of pinning Click's "No such option".
  Full suite on the merged tree: 5867 passed, 1 skipped, 0 failed (with
  `markdown` installed); `tests/test_command_surface.py` re-run on the
  final tree: 176 passed.
