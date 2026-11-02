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
