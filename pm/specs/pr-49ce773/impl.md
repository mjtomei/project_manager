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
     known local/display-id pairs, so the drift can be diagnosed. Bound the
     sample to 20 PRs and include the loaded total and omitted count to avoid
     dumping the whole project on each navigation reload.
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
   returns `(nav_pr_ids, pr_by_disp, home_pr)` in display form. The popup
   converts these entries to stable local-identity navigation keys and indexes
   all PRs by local ID; `_resolve_for` uses that index, never a display-number
   re-lookup. Display numbers are derived only when rendering. This keeps a
   retained selected terminal PR distinct from a terminal home sharing its
   number. `_build_picker_lines` receives a one-element `[pr]` list.

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
     direction from the old order, matching stable local identities so a
     simultaneous GitHub-number assignment does not skip it; `0` goes to home.
   - right before dispatching any action (shortcut, Enter on a row, a
     `z`/`zz` chord key, or a no-fzf numbered/shortcut selection) via
     `_still_has_action(label)`: if the shown PR
     no longer has that action (merged/closed meanwhile), don't run
     anything — re-render it with its notice. If refresh fails, refuse the
     action rather than dispatch from the stale snapshot; navigation may still
     use the last-good snapshot and a later key can retry after repair. Both
     fzf and the numbered fallback show an explicit refresh-failure/refusal
     notice; without fzf the user reopens the picker after repair.
   After each reload presentation derives the current display ID from the
   selected local identity, so changing `gh_pr_number` does not duplicate or
   redirect the selection. Only initially unresolved home window identifiers
   use `_find_pr_for_window_id`; once pinned, home is looked up by exact local
   ID, even for legacy numeric IDs after deletion. It must never fall through
   to another PR's GitHub number.
   `_sync_index(shown, prev)` keeps `nav_index` consistent: a PR that is on
   screen but dropped out of the rebuilt list is re-inserted at its old
   position until the user navigates away, so the header `(i/n)` never
   names a different PR or indexes past the list.  `multi_pr`/`nav_hint`
   are recomputed every render since `n` can change.  A failed reload logs
   a warning and keeps the complete previous state: build the replacement
   window maps and navigation inside the error handler before assigning any
   state, including when YAML parses but a PR entry is malformed. Require an
   explicit list-valued `prs` field: missing/null/false/zero/string/mapping
   values are invalid rather than an empty snapshot; `prs: []` is valid.
   Load without the store's status-repair normalization and require a raw status from
   `VALID_PR_STATES`: missing/truncated statuses must not become actionable
   `pending` entries during a partial write. Reject non-printable display IDs
   (including NUL, newline and terminal escapes in `gh_pr_number`) before they
   reach fzf arguments or rows. Apply these checks to initial load as well as
   refresh. Validate that every entry has a command-safe string local `id`
   before building navigation
   (`[A-Za-z0-9][A-Za-z0-9_.-]*`, covering generated and legacy IDs):
   `gh_pr_number` alone can provide a display id but cannot support dispatch.
   Local IDs must be unique across the snapshot. Canonical display IDs must
   also be unique whenever any matching entry is non-terminal. Historical
   terminal-only duplicates (present in project.yaml) are safe to keep because
   they have no actions. When the selected PR becomes terminal and shares a
   display number with another terminal record, render the already-resolved local
   identity, not the first display-number match. Retain that identity through
   repeated navigation when no live destinations remain, so the status notice
   stays accurate and a later repair/reopen can recover the selected PR.
   A partial number reassignment that leaves two PRs
   displaying the same `#N` (including int/string equivalents) with either live
   is ambiguous: reject it before publication, retain the last-good navigation
   state and refuse pending actions until repair. Duplicate local IDs are
   always unsafe because command dispatch cannot distinguish those records.
   Malformed initial data must show a logged, readable error and wait for
   dismissal rather than raising a traceback. There is no last-good snapshot
   on initial load.
   Pending actions retain the selected local ID across refresh, even if its
   GitHub number is removed or reassigned to another PR. If that local ID is
   gone, refuse dispatch and show a lookup-failure notice; never retarget the
   action to the new owner of the old display number.
   Preserve the resolved home PR's local identity across reloads, and use the
   previous snapshot's local identities to locate the current PR and its old
   neighbours when stepping. Number removal/reassignment must not make `0`
   return to a different PR or make next/prev step from the new number owner.
   An initially unresolved home window id remains eligible for later repair.
   Pin its local identity on the first successful refresh that resolves it, even
   when that refresh navigates away from home, so later number removal or
   reassignment cannot create a ghost home or redirect `0` to another PR.
   Refresh the caller/other-session active-window indicators in the same
   transaction as the window-name map so navigation redraws current dots.
   Query all attached session/window pairs in one tmux `list-sessions` call
   rather than adding one subprocess per grouped session on each keypress.
   Index QA window suffix boundaries once per snapshot so matching scenario
   windows does not rescan all windows for every PR on every keypress.
   Index local PR identities in the same snapshot and use set membership when
   scanning former neighbours, so a bulk removal/replacement of navigable PRs
   does not perform a full PR/list scan for every old entry.
   h/l/←/→ (and 0 with a home PR) stay in `--expect` even when the list has
   one entry — unadvertised,
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
popup claims "merged or closed". The original audit reported a snapshot
without pr-f5b7eef's number; the preserved history confirms
`gh_pr_number: 193` at 37a927cd (status in_review), and both 8016b42f and
the current post-integration project.yaml have that number with status merged.
Thus the missing-number path explains the lookup-failure symptom, but those
commits do not independently establish the exact original #193 snapshot.
QA must create the missing-number state explicitly rather than rely on that
historical entry still being broken. `int` vs `str` gh_pr_number doesn't
matter (`f"#{gh}"` gives the same string).

Fix: resolve a window id to a PR by display id, else via the existing
`helpers._resolve_pr_id` (local `pr["id"]`, or `#N` against an int
`gh_pr_number`; a string `gh_pr_number` is already covered by the
display-id match).  Canonicalize home_pr to the PR's current display id.
`_build_nav_entries`' open-window check matches window names built from
both the display id and the local id. This does not recover a removed
`gh_pr_number`: a window named `#193` with no remaining PR carrying that
number must show the lookup-failure notice, not another PR's actions.

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
- A null or numeric title loaded from YAML must not crash rendering: coerce
  presentation titles to text (only null renders blank, zero renders `0`)
  before truncation. Replace non-printable title characters with spaces in the
  bounded display prefix, not the full unbounded title: fzf's row stream must
  contain exactly one non-actionable title row, never continuations that resemble actions
  or terminal control sequences. Preserve the original title in project data.
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
  master).  Master #240 (pr-24f022e) fixed the same bug in parallel:
  `popup_picker_cmd` exports `PM_POPUP_SESSION=<session>` into
  `os.environ` at popup start, `tmux.get_session_name()` honours it when
  there is no pane, and direct dispatch runs `_session_pm_argv(session,
  …)` (the session's pm code, not the cwd's — which also fixes the
  wrong-session-tag issue pr-f98ac63).  This PR's earlier
  `PM_CALLER_SESSION` was dropped when merging master so only one
  mechanism remains; what is kept from it is the stale guard:
  `PM_POPUP_SESSION` is honoured only while that session still exists
  (`has-session -t =<name>`, exact match), since anything the popup
  spawns inherits the variable.
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
