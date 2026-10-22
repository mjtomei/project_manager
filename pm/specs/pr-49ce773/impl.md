# pr-49ce773 — popup picker: no-action PRs must not exit / misattribute

## Requirements

1. **No early exit on empty lines** — `popup_picker_cmd` (`pm_core/cli/session.py`)
   currently does `if not lines: echo "No actions available (PR is merged or
   closed)."; _pause_and_exit(0)` right after the first `_resolve_for`.
   Remove it.  When the current PR has no actions, the fzf loop still runs
   with the normal header (`PR Actions — <id> (i/n)`, nav hint) and a single
   non-actionable notice row.  h/l/←/→/0 keep working.  (User want #4: one
   PR with no actions never exits the picker.)
2. **Accurate per-PR notice** — `_resolve_for` returns a notice for the
   no-actions case:
   - PR found, status in `_TERMINAL_STATUSES` → `No actions — PR is {status}.`
   - PR not found (lookup failure) → `Could not load actions for {pr_disp}.`
     plus `_log.warning(...)` with the id, the project root, and the
     display/local ids known, so the drift can be diagnosed.
   - PR found, non-terminal, but `_build_picker_lines` still empty
     (shouldn't happen) → same "Could not load" copy + warning.
3. **Merged/closed PRs never actionable** (user want #1) — already true via
   `_actions_for_status`; additionally, while an actionless PR is shown,
   shortcut keys (s/e/d/t/i/g) and the `z` chord are not in fzf's
   `--expect` list (so they're bound to `ignore`), and Enter on the notice
   row is bound to fzf `ignore` (with double-click) so it never exits.  This also closes a latent hole where
   `z s` on a merged PR would build a fresh-start command from
   `_MODIFIED_ACTION_CMDS` using `_picked_pr`.
4. **Nav list skips terminal PRs** (user want #2) — when building
   `nav_pr_ids`, PRs with status in `_TERMINAL_STATUSES` are excluded unless
   they are the home PR.  So opened from a non-PR window, nav_index 0
   lands on the first live PR.
5. **Home merged PR stays reachable** (user want #3) — opened from a merged
   PR's own window, home_pr is still in the nav list at its index, shown with
   `No actions — PR is merged.`, and nav keys reach the other PRs.
6. **Lookup-divergence removed** — extract the nav-list construction into a
   pure helper `_build_nav_entries(prs, home_window_id, open_windows)` that
   returns `(nav_pr_ids, pr_by_disp, home_pr)`; `_resolve_for` uses the
   resolved dict from `pr_by_disp` rather than an independent re-lookup.
   `_build_picker_lines` is given a one-element `[pr]` list so it can't
   diverge either.

7. **Navigation to/from retained merged entries never exits (note-40057f4)**
   — the user reported that after moving off the PR they opened from, the
   merged #238 (pr-ac10f03, windows still open) appeared in the list, and
   navigating away from it crashed/exited the picker.  No traceback was
   captured.  The old code fed fzf an *empty* item list for such an entry
   (`fzf_input_lines = []` after `_resolve_for` returned no lines), and any
   key other than a nav key then broke out of the loop (`_label_to_cmd`
   empty → `cmd_to_run=None` → `break` → `SystemExit(0)`); fzf's own
   no-match exit (rc 1) is likewise treated as abort.  Fixes: (a) merged
   entries are no longer in the nav list unless home (req 4); (b) every
   actionless entry renders a notice row, so fzf always has an item;
   (c) action keys/Enter are ignored for it and only q/Esc quits (req 3).
8. **Reload on navigation and before dispatch** — the popup used to load
   project.yaml once.  Add `_refresh_state()` (re-`store.load(root)` +
   `tmux_mod.list_windows(base)` + `_build_nav_entries`) and call it:
   - on every nav key (`_step_target`): step from the current PR within the
     *rebuilt* list; if the PR being left dropped out (merged/closed or lost
     its windows), step to its nearest surviving neighbour in the requested
     direction from the old order; `0` goes to home.
   - right before dispatching any action (shortcut, Enter on a row, or a
     `z`/`zz` chord key) via `_still_has_action(label)`: if the shown PR
     no longer has that action (merged/closed meanwhile), don't run
     anything — re-render it with its notice.
   After each reload the shown id is canonicalized (`_canonical_id`, via
   `_find_pr_for_window_id`) so a PR whose display id changed while open
   (`gh_pr_number` assigned: `pr-abc` → `#12`) is not listed twice.
   `_sync_index(shown, prev)` keeps `nav_index` consistent: a PR that is on
   screen but dropped out of the rebuilt list is re-inserted at its old
   position until the user navigates away, so the header `(i/n)` never
   names a different PR or indexes past the list.  `multi_pr`/`nav_hint`
   are recomputed every render since `n` can change.  A failed reload logs
   a warning and keeps the previous state.  h/l/←/→ (and 0 with a home
   PR) stay in `--expect` even when the list has one entry — unadvertised,
   they act as a reload, so a PR that is reopened or gains a window after
   the list collapsed to one entry is still reachable (QA E4; observed by
   the S3 refiner).

## Root cause audit (#193)

Within one invocation the nav list and `_resolve_for` both iterate the same
in-memory `prs` with `_pr_display_id`, so they can't diverge from each
other.  The divergence is between the **window name** and the
**project.yaml** entry: windows are named by `_pr_display_id` at creation
time (`pr.py` — `window_name = _pr_display_id(pr_entry)`), so if
`gh_pr_number` is later added (window `pr-xxx`, display `#N`) or lost
(window `#N`, display `pr-xxx`), `home_pr` from `_current_window_pr_id`
matches no PR.  `home_pr not in seen` then inserts the unmatched id at
position 0, `_build_picker_lines` hits `if not pr: return []`, and the
popup claims "merged or closed".  This is observed in git history:
pr-f5b7eef had `gh_pr_number: 193` at 37a927cd (status in_review) and the
field is absent in the current project.yaml.  `int` vs `str`
gh_pr_number doesn't matter (`f"#{gh}"` gives the same string).

Fix: resolve a window id to a PR by display id, else via the existing
`helpers._resolve_pr_id` (local `pr["id"]`, or `#N` against an int
`gh_pr_number`; a string `gh_pr_number` is already covered by the
display-id match).  Canonicalize home_pr to the PR's current display id.
`_build_nav_entries`' open-window check matches window names built from
both the display id and the local id.

## Implicit requirements

- `_label_to_cmd` must be empty for terminal PRs (already, via
  `_actions_for_status`).
- The `nav_index` lookup for `0` (home) must use the canonicalized home id.
- The fallback (no fzf) path has no navigation; with no actions it prints
  the header + notice and waits for dismissal (`_pause_and_exit(0)`), same
  as before but with accurate copy.
- When nav list ends up empty (only terminal PRs had windows, no home):
  keep the existing "No PR windows open." exit — there is nothing to
  navigate to.  Copy becomes "No active PR windows open." to be accurate.

## Ambiguities (resolved)

- *Should the unresolvable home id stay in the nav list?*  Yes — the user
  opened the popup from that window; showing "Could not load actions for
  #193." with nav keys working beats silently landing elsewhere.
- *Show shortcut hints for actionless PR?*  No — header shows `q/Esc: quit`
  and the nav hint only, so dead keys aren't advertised.
- *`[open]` / ●○ annotations for windows named under the other id form* —
  out of scope; only nav/lookup is fixed.

## Edge cases

- PR on screen merges while the picker is open: it stays on screen with
  `No actions — PR is merged.`; a pending action key re-renders instead of
  dispatching; the next nav key drops it (unless it's home).
- Every navigable PR merges while open (non-PR window): nav keys keep
  showing the current PR's notice; q/Esc quits — never an implicit exit.
- `z s` chord started before the PR merged: re-checked at the second key,
  no fresh-start command is built for the merged PR.
- QA scenario-only windows (`qa-#N-s1`) count as open windows for the nav
  list, matching `_build_picker_lines`' `[open]` matching.

- Single PR in nav list and it's actionless: no nav hint or `(i/n)`; h/l/0
  only reload (req 8); Enter is ignored; q/Esc quits.  No exit-on-keypress.
- Home PR is merged and also has open windows: appears once (dedup by
  canonical display id).
- Two windows for the same PR under both id forms: one nav entry.
- Navigating from an actionless PR to an actionable one restores the full
  expect list/hints on the next fzf launch (header recomputed per loop).
- Several clients attached (grouped `base~N` sessions), popup open on each:
  a direct dispatch (`pr start` / `pr review` …) must switch only the
  invoking client's session.  The popup has no `$TMUX_PANE`, and keys typed
  into a popup don't update tmux client activity, so the command's
  "current client" lookup picked the other client (QA scenario 5, also on
  master).  `_run_picker_command` passes `PM_CALLER_SESSION=<session>` and
  `tmux.get_session_name()` honours it when there is no pane — only while
  that session still exists (`has-session -t =<name>`, exact match), since
  anything the command spawns inherits the variable.
- Enter / double-click on an action row (pre-existing, also master): fzf
  prints an empty `--expect` key line first; `stdout.strip()` dropped it so
  the selected row was read as the key and nothing was dispatched.  Only
  the trailing newline is stripped now.  Enter on the PR title row (where
  fzf's cursor starts) has no command and is a no-op — it used to close
  the popup (S7 refiner); only q/Esc quits.
- Type-ahead closed the popup (QA scenario 8): a nav key typed while the
  picker reloads between fzf runs reached the next fzf before its rows
  loaded; fzf exits 1 ("no match") but still prints the `--expect` key, and
  the loop treated any non-zero exit as q/Esc.  fzf now runs with `--sync`
  (keys wait for the rows), exit 1 is handled as a keypress (a bare exit 1
  just relaunches), and only other non-zero codes (130 = q/Esc) quit.
  `--no-clear` keeps the last frame up between relaunches so each nav key
  no longer flashes an empty popup; the screen is cleared before a
  dispatch so command output and errors don't print over the stale frame.

## QA acceptance checks (carry into the QA spec)

Setup: a pm session with ≥2 live PRs (e.g. in_review #240, qa #242) with
open windows, and a merged PR (#238) whose old windows remain (edit its
status to `merged` in project.yaml, or merge then keep windows).  Drive
prefix+P (the `_popup-picker` popup) in a real tmux session with fzf.

1. **Given** popup opened from live #240's window, **When** pressing l / l
   / h / 0, **Then** the header cycles #240 (1/2) → #242 (2/2) → #240 (wrap)
   → #242 → #240 (home); #238 never appears; the popup never closes.
2. **Given** popup opened from non-PR window (TUI), **When** it opens,
   **Then** it lands on the first live PR, not merged #238.
3. **Given** popup opened from #238's own window, **When** it opens,
   **Then** header `PR Actions — #238 (1/3)`, row `No actions — PR is
   merged.`, only `q/Esc: quit` + nav hint; s/d/t/i/g/z/Enter do nothing
   and the popup stays open.
4. **Given** (3), **When** pressing h, then 0, then l, **Then** #242 (wrap),
   back to #238 with the notice, then #240 with its actions; pressing an
   action key on #240 runs it.
5. **Given** popup open on #240 (opened from TUI), **When** #242 is marked
   merged (`pm pr edit` / project.yaml) and l pressed, **Then** #242 is not
   shown and the header count shrinks; no crash/exit.
6. **Given** popup open on #240, **When** #240 is marked merged and s
   pressed, **Then** nothing launches; #240 re-renders with the merged
   notice; l then reaches #242 and its actions work.
7. **Given** a window named `#193` whose PR has no `gh_pr_number` in
   project.yaml, **When** the popup opens there, **Then** row reads `Could
   not load actions for #193.` (not "merged"), a warning is in the pm log,
   and nav keys reach other PRs.
8. **Given** only one PR in the nav list and it is merged (home), **When**
   pressing Enter or action keys, **Then** popup stays open; q/Esc closes.
9. **Given** the popup open with ≥2 navigable PRs, **When** nav keys are
   sent in pairs ~10 ms apart (the second lands while the picker reloads),
   **Then** the popup never closes and every frame shows a `PR Actions —`
   header.
