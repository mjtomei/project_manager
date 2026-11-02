# QA Spec — Fuzzy select for `pr select` and `plan select` (pr-6aa74c6, #136)

Branch `pm/pr-6aa74c6-fuzzy-select-for-pr-and-plan-commands` at `a7602942`
(implementation `32a6bfb8` plus review-loop 8e9c i1/i2), based on
`origin/master@81e5d7f4`. The two newer master commits only touch the
registry. Implementation spec: `pm/specs/pr-6aa74c6/impl.md`.

Code under test:
- `pm_core/tui/fuzzy_select.py` (scoring and ranking).
- `pm_core/tui/fuzzy_select_cmd.py` (command handlers and `]`/`[` cycling).
- `pm_core/tui/pr_view.py`: `pr select` / `plan select` are taken from the
  command bar before generic dispatch, and `persist_active_pr` is extracted.
- `pm_core/tui/app.py`: `]` / `[` bindings, which are blocked while the
  command bar has focus.
- `pm_core/tui/tech_tree.py` (navigation positions, plan first-PR, filter
  checks).
- `pm_core/tui/tree_layout.py` (the shared status-filter predicate).
- `pm_core/tui/screens.py` (help rows).
- `pm/qa/regression/help-keybindings.md` (step 15).

## User-facing surfaces

1. **TUI command bar** (`/`): `pr select <query>`, `plan select <query>`. The
   fuzzy behaviour lives only here.
2. **TUI keys** `]` (next match) and `[` (previous match), active in the tree,
   plans and QA views.
3. **TUI log line**: the `Selected: …`, `Plan: …`, `Match k/n: …`, `No … matches`,
   `… hidden by filters` and `Usage: …` messages.
4. **Persisted selection**: `project.active_pr` in `pm/project.yaml`. It shows
   as ` *` in `pm pr list`, as `Active PR:` in `pm status`, as the default
   target of CLI commands that omit a PR id, and as the TUI's position after a
   restart.
5. **Unchanged exact-id surfaces**:
   - CLI `pm pr select <id>`.
   - The tmux `pm>` command popup, which runs the CLI.
   - Command-bar commands that run something (`pr start`, `pr review`,
     `pr qa`, `pr merge`, `edit <id>`, `review-loop <id>`).
6. **Help screen** (`?`), tree-navigation section.

## Shared resources inventory (for concurrency coverage)

| Resource | Writers / readers |
|---|---|
| `pm/project.yaml` → `project.active_pr` | Written by the TUI write queue (fuzzy select, every `]`/`[` step, arrow keys) and by the CLI (`pm pr select`, `pm pr add`, `pm pr start`). The TUI follows external changes. |
| `pm/project.yaml` → `prs[]`, `plans[]` | CLI `pm pr add/edit/close`, `pm plan add`. The TUI reloads them. The retained result list refers to these ids. |
| Project store lock (`locked_update`) | Contended by the TUI write queue and concurrent CLI writers. |
| TUI in-memory result list (one per TUI) | Shared by `pr select`, `plan select`, `]`, `[`. |
| TUI command bar + SIGUSR2 command queue (`tui-<session>.cmd-queue`) | Users type in the bar. External `pm autostart …`, the picker and popup routes inject commands through the same handler. |
| TUI tree view state | Collapsed plans (`x`), status filter (`f`), hide-merged (`X`, persisted as `project.hide_merged`), sort (`F`). These decide what select and cycling can reach. |
| TUI log line | Fuzzy messages compete with background and auto-start messages. |
| tmux session / TUI pane | Driven by `pm tui send` and `pm tui view`. |

## Setup (cross-cutting)

Follow `pm/qa/instructions/tui-manual-test.md`:
- Install pm from the PR clone into a venv. Set `PYTHONPATH` to the clone and
  confirm with `pm which`.
- Create a throwaway git repo and run `pm init --backend local --no-import`.
- Start `pm session` and drive it with `pm tui send` / `pm tui view`. Record it
  with the tmux screen recording recipe.

Fixture used by most scenarios. Build it with pm CLI commands (`pm plan add`,
`pm pr add --plan … --description … --depends-on …`):
- At least three plans with distinct names, for example "Watchers",
  "Spec generation" and "TUI polish". `pm plan add` registers the plan before
  it tries to launch Claude. If Claude would launch, use the fake-claude config
  or run with no Claude binary on PATH; the plan prints a prompt and exits.
- Within one plan, the PR added first should depend on a PR added later. That
  makes "first in tree order" (the plan group's top-left, dependency root)
  differ from "first in project.yaml".
- One shared word ("spec") spread across fields:
  - in two or more PR titles;
  - in one PR's description only;
  - in one PR whose plan name contains it but whose title and description
    don't.
  - One PR with "spec" in both its title and description, so it outranks
    title-only matches.
- At least one PR with no plan (standalone).
- A PR whose title contains Textual markup characters, for example
  `[WIP] user's spec cleanup`.
- At least one PR whose description mentions another PR's raw id.
- For display-id stories, a few PRs with `gh_pr_number` set (for example 125
  and 136). The local backend never assigns one, so this is a bootstrap-only
  edit to `pm/project.yaml`, allowed by the instruction. The same applies to
  any initial `status` mix (merged, closed, in_review). After bootstrap, all
  changes go through pm CLI or TUI.

## Requirements (Given / When / Then)

### PR select

- **R1 Title match.**
  - Given the tree view with several PRs and "spec" in two or more titles.
  - When the user runs `/pr select spec`.
  - Then:
    - the tree cursor is on the highest-scoring PR;
    - the log reads `Selected: <display-id> <title> [N matches]`, where N
      counts every visible PR that matches in any field;
    - shortly afterwards `pm pr list` marks that PR with ` *` and
      `pm status` names it as the active PR.
- **R2 Field weighting and combination.**
  - Given PRs where "spec" appears in title+description, in the title only, in
    the description only, and only in the plan name.
  - When the user runs `/pr select spec` and steps through results with `]`.
  - Then the order is:
    1. title+description (300);
    2. the title-only PRs (200);
    3. the description-only PR (100);
    4. the plan-name-only PR (50).

    PRs with the same score appear in cursor-proximity order.
- **R3 ID prefix beats text matches.**
  - Given one PR id begins with a short hex string that also appears in
    another PR's title.
  - When the user runs `/pr select <that prefix>`, for example `pr-94`.
  - Then the PR whose id has that prefix is selected first.
- **R4 Exact id is authoritative.**
  - Given PR B's description (or title) mentions PR A's raw id.
  - When the user runs `/pr select <A's raw id>`.
  - Then the cursor lands on A, never on B. B can still appear later in the
    cycle list.
- **R5 Display ids.**
  - Given PRs with GitHub numbers (#125, #136).
  - When the user runs `/pr select #136`, then `/pr select 136`, then
    `/pr select #13`.
  - Then:
    - `#136` and `136` both land on the PR numbered 136, as exact matches;
    - `#13` is a prefix match on #136 (and on any other #13x);
    - a bare `13` is **not** a display-id prefix match. It matches only if
      "13" appears in a title, description or plan name.
- **R6 Case and quoting.**
  - Given a PR titled "Spec Generation Pipeline".
  - When the user runs `/pr select SPEC GEN`, `/pr select "spec   generation"`,
    and `/pr select user's`.
  - Then:
    - matching ignores case;
    - quotes are removed;
    - runs of inner whitespace collapse to one space;
    - an unbalanced apostrophe neither errors nor crashes, and it matches
      the `user's` title.
- **R7 Markup safety.**
  - Given a PR titled `[WIP] user's spec cleanup`.
  - When the user selects it (`/pr select wip` or `/pr select [WIP]`).
  - Then the log shows the literal `[WIP]` and the TUI does not crash or
    swallow text. A query containing `[/x]` returns a no-match message in
    which the brackets are visible, and nothing raises.
- **R8 Tie-break by cursor proximity.**
  - Given several PRs that score equally for a query (the same word in the
    title only), spread across the tree.
  - When the user puts the cursor near one of them and runs the select.
  - Then the tied PR nearest the cursor in tree navigation order wins. If the
    PR under the cursor is itself tied, the cursor does not move. Moving the
    cursor elsewhere and repeating the same query picks a different tied PR.
- **R9 No match / usage.**
  - `/pr select zzzqqq` logs `No PR matches for 'zzzqqq'`. The cursor does not
    move and the previous result list is cleared.
  - `/pr select` with no query logs `Usage: pr select <query>`. The cursor
    does not move and the previous result list is kept.

### Plan select

- **R10 Name match lands on the plan's first PR.**
  - Given the "Watchers" plan, whose tree-first PR is not its project.yaml-first
    PR.
  - When the user runs `/plan select watch`.
  - Then:
    - the cursor is on the plan group's first PR in tree order (top-left
      node, the dependency root);
    - the log reads `Plan: <plan-id>: Watchers → <display-id>`, with
      ` [K matches]` when K > 1 plans match;
    - `active_pr` is persisted as that PR.
- **R11 Collapsed plan.**
  - Given the "Watchers" group is collapsed (`x`).
  - When the user runs `/plan select watch`.
  - Then the group expands and the cursor is on its first PR. Other collapsed
    plans stay collapsed.
- **R12 Plan id exact and prefix.**
  - `/plan select <exact plan id>` selects that plan, even when the query is
    also a name substring of another plan.
  - `/plan select plan-` (a prefix of every id) ties all plans, and the tie
    goes to the plan whose landing PR is nearest the cursor.
- **R13 Sort order respected.**
  - Given the user changed the sort field (`F`) so the plan's top PR changes.
  - When the user runs `/plan select` for that plan.
  - Then the cursor lands on the PR that is now first in that plan's group.
- **R14 Empty plan does not fall through.**
  - Given the best-scoring plan has no PRs. For example, the query is that
    plan's exact id, and another plan with PRs also matches the query because
    its name contains that id ("Follow-up to plan-xxxx").
  - When the user runs `/plan select <query>`.
  - Then:
    - the log reads `Plan '<id>: <name>' has no PRs`;
    - the cursor stays put and the result list is cleared;
    - it does not jump to the lower-ranked plan.
  - When an empty plan and a populated plan tie on score (both names contain
    the query), the populated plan wins. A plan with nothing to land on loses
    ties.
- **R15 Standalone PRs.** `plan select` never matches the implicit standalone
  group. PRs without a plan are still found by `pr select`.

### Result cycling

- **R16 Forward, back, wrap.**
  - After a `pr select` with N > 1 results:
    - `]` moves to result 2 and logs `Match 2/N: <display-id> <title>`;
    - `[` returns to result 1;
    - `[` from result 1 wraps to N;
    - `]` from N wraps to 1.
  - Each step updates `active_pr`.
- **R17 Plan cycling.**
  - After a `plan select` with K > 1 plans, `]` / `[` step plan by plan.
  - Each step:
    - lands on that plan's first visible PR;
    - expands the plan if it was collapsed after the select;
    - logs `Match k/K: <plan-id>: <name> → <display-id>`.
- **R18 One shared list.** A `plan select` after a `pr select` replaces the
  list, and `]` then cycles plans. A `pr select` after that replaces it again.
- **R19 No list.** In a fresh TUI, or right after a select that matched
  nothing, `]` logs `No match results to cycle (use /pr select or /plan select)`
  and the cursor does not move.
- **R20 Manual moves.** After the user moves the cursor with arrow keys, `]`
  continues from the list position, not from the cursor.
- **R21 Keys are text in the command bar.** Typing `[` or `]` inside the
  command bar inserts the character and does not cycle.

### Views, filters and integration

- **R22 View switching.**
  - From the plans view (`p`) or the QA view (`q`), a successful `pr select`,
    `plan select` or `]` / `[` switches to the tree view on the target PR.
  - A no-match or usage error keeps the current view, and focus returns to it:
    keys such as j/k act in that view, not in the command bar.
- **R23 Filtered matches are not navigated.**
  - Matches hidden by the status filter (`f`), hide-merged (`X`) or the default
    closed-hiding are left out of the cursor targets and counted:
    `[N matches, M hidden by filters]`.
  - If all matches are hidden, the log says so and the cursor does not move.
  - The user's filter settings are never changed by a select.
- **R24 Hidden exact id.**
  - Given the exactly-named PR is hidden by filters (for example merged with
    `X` on).
  - When the user runs `/pr select <its id>`.
  - Then the log reads `<id> <title> is hidden by the current filters (X: merged, f: status filter)`,
    the cursor does not move, and the list is cleared. The cursor never lands
    on another PR that only mentions the id.
- **R25 Cycling skips stale entries.** After a select, if one result is closed,
  filtered out or its plan is emptied, `]` / `[` skip it. If none remain
  reachable, the log says so and the cursor stays.
- **R26 The selection is real.** After a fuzzy select (or a cycle step):
  - a read-only CLI command that defaults to the active PR uses the PR under
    the cursor. `pm prompt` with no id, run from the project root, generates
    the prompt for that PR. `pm pr list` (` *`) and `pm status` agree;
  - restarting the TUI brings the cursor back to that PR.
- **R27 No widening of fuzzy targeting.**
  - These stay exact:
    - CLI `pm pr select spec`: an error, nothing changes;
    - `pm>` popup `pr select spec`: the same error, nothing changes;
    - command bar `pr start spec`, `edit spec` and `review-loop spec`:
      not-found errors, nothing starts.
  - `pm pr select <exact id>`, from the CLI or the popup, still moves the TUI
    cursor.
  - No `pm plan select` CLI command exists.
- **R28 Help.**
  - `?` shows these rows in the tree-navigation section:
    - `] / [  Cycle fuzzy match results`, reading exactly `] / [`, with only the
      two key characters bold and no stray `[/]`;
    - `/pr select <query>  Fuzzy-find PR`;
    - `/plan select <query>  Fuzzy-find plan`.
  - At a small terminal size, the rows can be reached by scrolling.

### Concurrency

- **R29 Concurrent CLI writers.**
  - Given a second actor running CLI commands against the same project
    (`pm pr edit` titles and descriptions, `pm pr add`, `pm pr edit --status closed`,
    `pm pr select <exact>`).
  - When the TUI user keeps running fuzzy selects and cycling.
  - Then:
    - no write from either side is lost;
    - at rest, the TUI cursor and `active_pr` agree;
    - edited titles show in later `Match` messages;
    - closed PRs are skipped by cycling;
    - the TUI does not crash.
  - While the second actor only edits titles and descriptions, the cursor
    never jumps back to an earlier match on its own.
- **R30 External CLI select after a fuzzy select.**
  - Given the user did a fuzzy select.
  - When another actor runs `pm pr select <exact other id>`.
  - Then the TUI cursor follows to that PR. The fuzzy list is not replaced, so
    `]` continues through the old matches.
- **R31 Queued external commands during typing.**
  - Given the user is part-way through typing `/pr select …`.
  - When external read-only queue commands arrive (`pm autostart status`,
    `pm autostart list`).
  - Then the typed text is intact, the command bar keeps focus, and pressing
    Enter runs the select correctly.

## Edge cases

- A project with no PRs logs `No PRs available`. A project with no plans logs
  `No plans available`. Neither crashes.
- `pr selectfoo` is not a select command. It goes to the normal dispatch and
  errors as an unknown command.
- Extra whitespace (`plan   select   watch`) is accepted.
- A PR whose plan id has no plan entry, or whose title or description is
  missing, does not crash ranking.
- A collapsed plan that contains the best `pr select` match is expanded to
  reveal it.
- All of a plan's PRs are hidden by filters: `Plan '<id>: <name>': all N PRs hidden by filters (…)`,
  with no move and the list cleared.
- `]` / `[` pressed while the help modal is open:
  - help stays open and nothing crashes;
  - the cursor behind the modal should not move;
  - if it does, compare with an existing app key such as `F`. A leak that only
    the new keys show is a failure of this PR. A leak every app key shows is a
    pre-existing bug, to be filed separately.
- A command-bar `pr add` (or CLI `pm pr add`) after a select moves the cursor to
  the new PR (the existing active-PR follow). The old list stays, and `]`
  goes back to the old matches.

## Pass / fail criteria

- **PASS**:
  - every Then above is observed on the TUI screen, the log line, or
    `pm pr list` / `pm status` output;
  - no traceback in the TUI pane or `tui-stderr.log`;
  - recordings and transcripts are captured.
- **FAIL**, any of:
  - the cursor lands on a different PR than the ranking rules imply;
  - an exact id loses to a non-exact match;
  - the cursor lands on a hidden or wrong PR when the exact id is filtered;
  - cycling order, wrap or replacement is wrong;
  - a failed search leaves a stale list cycling;
  - `active_pr` is not persisted, or disagrees with the cursor at rest;
  - a crash, a markup error, or text swallowed from the log;
  - `[` / `]` typed in the command bar cycle;
  - an unexpected view switch on error;
  - a fuzzy match reaches any command other than the two select commands and
    the cycle keys;
  - the help row renders with stray `[/]` or wrong bolding;
  - lost writes or cursor snap-back under concurrent CLI writers.
- Behaviour that is pre-existing and unrelated to this PR (also present on
  master) is reported as a separate bug, not as a failure of this PR.

## Ambiguities (resolved)

1. **Cycling keys.** The PR description suggests "n/N or similar", but `n` is
   Notes. `]` / `[` are used, as in impl spec ambiguity 1, already accepted by
   the earlier QA.
2. **Fuzzy means case-insensitive substring of the whole query.** There is no
   subsequence or typo tolerance: `/pr select spc` does not match "spec".
   QA does not fail the PR for missing typo-tolerance.
3. **Plan tie-break distance.** Distance is measured from the cursor to each
   tied plan's landing PR (its first PR in tree order), not "the plan
   containing the cursor wins". This is impl R4 (review-loop 8e9c i1). QA
   checks for consistency with that rule.
4. **Hidden matches.** They are counted, not revealed, and filters are never
   changed by a select.
5. **A failed new select clears the list. A usage error (empty query) does
   not.**
6. **CLI and popup stay exact-id.** `pm pr select` and the `pm>` popup keep
   exact semantics, and there is no `pm plan select` CLI. This is a deliberate
   scope decision (impl ambiguity 7), so a fuzzy query there is expected to
   fail with "not found".
7. **External selection doesn't replace the list.** Only a new `pr select` or
   `plan select` replaces it. A CLI `pm pr select`, `pm pr add` or arrow-key
   move moves the cursor but keeps the list.
8. **`pm tui keys`.** This curated CLI summary is not part of R28. It already
   leaves out several tree keys (`x`, `X`, `f`, `F`). Whether `]` / `[` appear
   there is recorded as an observation, not a failure.

No **[UNRESOLVED]** items.
