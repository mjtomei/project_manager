# Spec — Fuzzy select for `pr select` and `plan select`

PR: `pr-6aa74c6` (#136) · Branch: `pm/pr-6aa74c6-fuzzy-select-for-pr-and-plan-commands`
Plan: `tui-ux`

## Restart context (2026-11-02)

- The branch head before restart was `a874eeae`. It is kept as the local branch
  `pm/pr-6aa74c6-pre-restart-a874eeae`.
- `origin/master@81e5d7f4` (3411 commits) was merged in as `bacb887f`. Two files
  conflicted, and both were resolved by keeping both sides:
  - `app.py`: master's `V`/`Y`/`o` bindings and `check_action` list, plus `]`/`[`.
  - `pr_view.py`: the fuzzy handlers sit before master's `review-loop` parsing.
- The dirty `pm/project.yaml` holds live host state for this PR: status,
  model/effort, workdir and the restart note. It was spliced onto master's
  registry for this PR's record only, and left uncommitted.
- Historical evidence: QA on 2026-03-14 passed 15/16 scenarios. The one
  NEEDS_WORK was "Help screen documents bracket cycling keys". The `bf747084`
  fix added the help row, but under the current Textual 8.2.7 markup it renders
  as `] / [[/]  Cycle fuzzy match results`, and everything after the `]` is bold.
  `[bold][[/]` is not an escape in Textual, so the finding is still open on the
  merged head (see R6).

## Requirements (grounded in code)

### R1 — `pr select <query>` fuzzy-ranks PRs in-process

- Entry point: `pm_core/tui/pr_view.py:handle_command_submitted`. This covers
  the `/` command bar and the SIGUSR2 command queue
  (`app._drain_command_queue`). `pr select …` is intercepted before any
  subprocess dispatch, so it no longer shells out to `pm pr select`.
- Scoring lives in `pm_core/tui/fuzzy_select.py:score_pr`. Weights combine
  additively:

  | Match | Weight |
  |---|---|
  | Exact ID (raw `pr-…`, display `#N`, or bare `N` equal to `gh_pr_number`) | 1000 |
  | ID prefix (raw or display), only when not exact | 500 |
  | Title substring | 200 |
  | Description substring | 100 |
  | Plan name or plan id substring | 50 |

  Matching is case-insensitive substring matching. A query that is empty or
  only whitespace scores 0 everywhere.
- The best match wins. Because 200 + 100 + 50 = 350 and 500 + 350 < 1000, an
  exact ID match always outranks every non-exact match. A prefix match always
  outranks any combination of title, description and plan matches.
- Tie-break (R4): proximity to the tree cursor, measured in the tree's
  navigation order.

### R2 — `plan select <query>` fuzzy-ranks plans and jumps to the plan's first PR

- New command handled in the same place as R1.
- `fuzzy_select.py:score_plan` weights: exact plan id 1000, id prefix 500,
  name substring 200.
- The best-ranked plan is the target. A collapsed plan group (`x`) is
  expanded. The cursor moves to the plan's first PR in tree navigation order
  (`TechTree._ordered_ids`), not in `project.yaml` order.
- If the best-ranked plan has no PRs at all, the TUI logs
  `Plan '<name>' has no PRs`, clears the result list, and does not move. If all
  its PRs are hidden by filters, it logs `Plan '<name>': all N PRs hidden by
  filters` instead, with the same effect. It does not silently jump to a
  lower-ranked plan. This keeps the QA-accepted "Plan select with no PRs in
  matched plan" behavior.
- The cycling list holds every matched plan that has at least one PR shown by
  the current filters, in rank order. The target plan is first.
- Messages name the landing PR by display id (`Plan: <id>: <name> → #N`, and
  `Match k/n: <id>: <name> → #N` when cycling), the same way `pr select` does.

### R3 — One shared, retained result list cycled with `]` / `[`

- App state in `pm_core/tui/app.py:__init__`:
  - `_fuzzy_results`: local ids, either PR ids or plan ids.
  - `_fuzzy_index`
  - `_fuzzy_kind`: `"pr"` or `"plan"`.
- Each successful `pr select` or `plan select` replaces the list, whichever
  command ran last. A command that fails (no match, empty plan) clears the
  list, so stale cycling cannot continue after a failed new search. A usage
  error (empty query) leaves the list untouched, because no match command ran.
- `Binding("right_square_bracket", "fuzzy_next")` and
  `Binding("left_square_bracket", "fuzzy_prev")` are bound on the app. They
  wrap around and move the cursor to each result in rank order. The log shows
  `Match k/n: …`.
- The PR list stores PR ids. The plan list stores plan ids, and each step
  resolves the plan's first visible PR at that moment (expanding the group if
  collapsed). This way a plan step never expands unrelated plans ahead of time,
  and it stays correct after reloads.
- An entry that is no longer navigable is skipped in the cycling direction.
  That covers a PR that was deleted or is now filtered, and a plan with no
  visible PRs. If none are navigable, the TUI logs a message and stays put.
- With no list, it logs `No match results to cycle (use /pr select or /plan select)`.
- Both keys are in the `check_action` command-bar block, so typing `[`/`]` in
  the command bar never cycles.

### R4 — Tie-break by cursor proximity in tree order

- The previous code compared a `project.yaml` list index with
  `tree.selected_index`, which is an index into `_ordered_ids`. Those are two
  different index spaces.
- New `TechTree.pr_nav_positions()` maps each PR id to its index in
  `_ordered_ids`. A PR inside a collapsed plan maps to the index of that plan's
  `_hidden:<plan>` label. A PR with no position sorts after all positioned PRs.
- Plans use the same index space. `TechTree.plan_nav_positions()` maps each
  plan to the navigation index of its first shown PR (where `plan select`
  would land), or of its `_hidden:<plan>` label when collapsed. Plan ties
  break by distance from `tree.selected_index`. A plan with no shown PR has
  no position, so it loses a tie to any plan the cursor can reach. The tree
  orders plan groups by id, so this is the visual order, not the order of the
  plans in `project.yaml` (review-loop 8e9c i1 replaced a plans-list-index
  tie-break that measured distance in `project.yaml` order).

### R5 — Selecting a PR selects it the way the rest of the TUI does

- Before this PR, `/pr select <id>` ran `pm pr select <id>`. That set
  `project.active_pr`, and `_follow_active_pr` then moved the cursor.
  Keyboard navigation also persists `active_pr` (`pr_view.handle_pr_selected`).
- The in-process select and each cycle step must also persist `active_pr`
  through the same in-memory update plus coalescing write queue. To do that,
  extract `pr_view.persist_active_pr(app, pr_id)` from `handle_pr_selected`.
  Without it, a fuzzy select would leave `active_pr` on the old PR: a TUI
  restart would snap back, and CLI defaults would target a PR the cursor is
  not on.
- The cursor only moves to PRs present in the tree. Matches hidden by the
  status filter (`f`), hide-merged (`X`) or hidden-closed are excluded from the
  navigable result list and reported as a count (`… N hidden by filters`). The
  user's filter settings are never changed.
- An exact ID match is authoritative. If the query exactly matches one or more
  PRs and every one of them is hidden by filters, the TUI logs `<id> is hidden
  by the current filters (X: merged, f: status filter)`, clears the list, and
  does not move. It never lands on a different PR that merely mentions the id
  in its description, because that would point the next `s`/`d`/`g` at the
  wrong PR.

### R6 — Help screen and keybinding documentation

- `pm_core/tui/screens.py:HelpScreen` (tree section) gets three rows:
  - `]` / `[` cycle fuzzy match results
  - `/pr select <query>`
  - `/plan select <query>`
- The bracket row uses Textual-valid markup: `[bold]][/] / [bold]\[[/]`. A test
  renders every help-row string through `textual.content.Content.from_markup`
  and asserts that the bracket row's plain text contains `] / [` and that the
  bold spans cover only the two key characters.
- `pm/qa/regression/help-keybindings.md` (the regression instruction that
  checks every help row) lists the three new rows and adds a safe step for
  select plus `]`/`[`.
- `pm_core/cli/__init__.py` help text (`pm pr select <pr-id>  Set the active
  PR`) describes the CLI, which stays exact-id. It is unchanged.

## Implicit requirements

- I1 — No destructive targeting expansion. Fuzzy resolution is used only by
  `pr select`, `plan select` and the cycle keys. `pr start/review/merge/qa`,
  `edit <id>`, `review-loop <id>`, `autostart …`, the popup `pm>` prompt, the
  picker and the CLI `pm pr select` keep exact resolution. The handlers never
  start, merge, close or edit anything; they only move the cursor and persist
  `active_pr`.
- I2 — Stable local identities. Results and cycling store local pm ids, never
  display ids. Display ids (`#N`) are only matched and shown. Two PRs that
  share a `gh_pr_number` both score as exact. Both stay in the list in
  proximity order, and cycling reaches each one.
- I3 — Exact-ID behavior is preserved. A query that `_resolve_pr_id` would
  resolve exactly (`pr-xxxx`, `#N`, `N`) always ranks that PR first, so it gets
  the same target as the old CLI path.
- I4 — Query parsing must not crash on unbalanced quotes. `pr select user's`
  must work. The select commands are recognised and their query taken before
  the generic `shlex.split(cmd)`. Quoted queries (`pr select "spec gen"`) are
  unquoted when shlex can parse them; otherwise the raw remainder is used.
  Inner whitespace runs are collapsed to one space.
- I5 — Markup safety. Titles, plan names and queries are user text, and
  `LogLine` is a Textual `Static` that parses markup. Messages escape every `[`
  with the existing `pm_core.tui.model_screen.escape`. Without this, `[WIP]`
  disappears and `[/x]` raises.
- I6 — Data robustness. `title`, `description`, plan `name` or `plan` may be
  missing or `None`. Entries without a usable id are ignored, as in
  `usable_prs`.
- I7 — View switching. The select commands and cycle keys switch from the
  plans or QA view to the tree view only when they actually navigate. On a
  usage error or no match, the current view stays and focus goes back to that
  view's widget (plans pane, QA pane, or tree) through
  `ProjectManagerApp._focus_current_view()`. Esc in the command bar
  (`action_unfocus_command`) uses the same helper (review-loop 0402 i1).
  master's other command branches return focus to the plans pane or the tree
  only, never the QA pane. That is the pre-existing bug pr-adfdce3, which
  has a note to reuse this helper.
- I8 — Filter predicate parity. "Shown by the current filters" uses the same
  predicate as `tree_layout.compute_tree_layout`. It is factored into
  `tree_layout.passes_status_filter(pr, status_filter, hide_merged,
  hide_closed)` and used by both, so they cannot drift.
- I9 — Key order behind a command-bar Enter. This was a QA S7 incidental fix
  (`d6b2c29e`) for a pre-existing race; it is not fuzzy-select logic.
  - The race: Textual submits an `Input` only after the Enter has bubbled
    back up to the App, where Input's `enter` binding runs. Under a stream of
    reloads, the App could meanwhile forward the next key to the still
    focused bar, so `/pr select spec` Enter `]` submitted `pr select spec]`.
  - The fix: `ProjectManagerApp.on_event` holds terminal (non-forwarded)
    `Key` events that arrive while a command-bar Enter is in flight.
    `on_command_submitted` replays them in order with `call_later`, after
    the command's own focus change. A replayed Enter that goes to the bar
    again starts a new hold. `HELD_KEYS_TIMEOUT` (3 s) releases the keys if
    no `CommandSubmitted` arrives.
  - `CommandBar` posts `CommandSubmitted` for an empty command too, so an
    empty Enter also releases the hold. The app ignores the empty command.

## Ambiguities (resolved)

1. Cycling keys. The task suggests `n`/`N`, but `n` is Notes. Resolution: keep
   `]` / `[`, which are unbound on master and were accepted by QA.
2. Fuzzy means substring matching. The task defines the weights per
   "substring", so the whole query is one case-insensitive substring. No
   subsequence or token matching is added.
3. Hidden matches. Resolution: exclude them from navigation and report a count.
   Revealing them would silently change persisted filter settings
   (`hide_merged` is per project).
4. Failed new match clears the old list. Resolution: yes. "The result list …
   stays active until a new fuzzy match command is run, replacing the previous
   list." A failed command is a new match with an empty result.
5. `active_pr` persistence. Resolution: persist, for parity with both keyboard
   navigation and the pre-PR `pm pr select` path (R5).
6. Plan select when the best plan is empty. Resolution: report it and do not
   fall through to the next plan (R2).
7. The CLI and popup prompt are out of scope. `pm pr select` (CLI) and the tmux
   `pm>` popup keep exact semantics, and `pm plan select` is not added to the
   CLI. The task is a TUI command feature, and scripts rely on exact CLI
   resolution.
8. The `_standalone` pseudo-plan is not a plan entry and is not matched by
   `plan select`. PRs without a plan are still found by `pr select`.

No **[UNRESOLVED]** items.

## Edge cases

- `pr select` or `plan select` with no query logs `Usage: …`. The list and the
  view are unchanged.
- No PRs or plans in the project: `No PRs available` / `No plans available`.
- Query with brackets or quotes (`[WIP]`, `user's`): no crash, and the text is
  echoed escaped.
- The selected PR is in a collapsed plan: `select_pr` expands it (existing
  behavior).
- The plan is collapsed and `plan select` targets it: it is expanded, then its
  first PR is selected.
- A data reload between select and cycle: ids are re-resolved, and missing or
  filtered entries are skipped.
- Duplicate PR ids in `project.yaml` (master currently has a duplicated
  `pr-049649a`): candidates are de-duplicated by id, and the first entry wins.
- Bare numeric query `136`: an exact `gh_pr_number` match. It is not a prefix
  match on display ids, so `13` does not match `#136`. `#13` does match it as a
  prefix.
- The command arrives via the SIGUSR2 queue while the user is typing:
  `_drain_command_queue` already restores command-bar focus.

## Known pre-existing issues (filed, out of scope)

QA found these on this branch. They are not caused by fuzzy select, and none
of them blocks this PR.

- pr-bda8833: hiding a plan with `x` moves the cursor but leaves `active_pr`
  on the hidden PR (QA S4).
- pr-dd3682f: `sync.background_sync` and `do_normal_sync` reload
  `project.yaml` without the write-queue flush that `_load_state` does. A
  pending `active_pr` from navigation, fuzzy select or `]`/`[` can therefore
  be read back stale, and the cursor snaps back (QA S4 refiner note).
- pr-291ed27: `_followed_active_pr` is not updated on navigation. Its fix now
  belongs in `pr_view.persist_active_pr`, and it should land after
  pr-dd3682f.

## Test plan

- Unit (`tests/test_fuzzy_select.py`):
  - Weights, including bare-number and duplicate-gh exact matches.
  - Exact-ID dominance.
  - `None` fields and an empty query.
  - Tree-order tie-break via `positions`.
  - Plan scoring and plan tie-break.
  - `passes_status_filter` parity with `compute_tree_layout`.
- App-level (Textual `run_test` pilot on a disposable temp project, no tmux):
  - `pr select spec` moves the cursor and persists `active_pr`.
  - Exact `#N`, `N` and `pr-…` queries are honored.
  - `plan select` expands a collapsed group and lands on the first PR in tree
    order.
  - `]`/`[` cycle and wrap. `plan select` results cycle per plan.
  - A new search replaces the list. A failed search clears it.
  - Filtered PRs are skipped and counted.
  - From the plans view the TUI switches to the tree. A no-match from the plans
    view stays in plans.
  - `[`/`]` typed in the command bar do not cycle.
  - Unbalanced-quote and bracket queries work.
  - I9: a `]` posted right behind a command-bar Enter cycles after the
    select instead of joining the query. Keys held behind an empty Enter
    are replayed into the bar.
  - Esc in the command bar focuses the plans pane, the QA pane or the tree
    (`_focus_current_view`).
- Help screen markup test (R6).
- Full suite once after the final edits, using the container recipe
  (`env -u PM_HOST_HOME PATH=/usr/bin:/bin`, `pytest<9`).
