# QA spec — pr-49ce773: popup picker must not exit / misattribute on no-action PRs

Surface under test: the prefix+P PR-actions popup (`pm _popup-picker <session> <window>`),
driven in a real tmux session with fzf, against a throwaway pm project.

Changed behavior (pm_core/cli/session.py `popup_picker_cmd` and helpers):
- No early "No actions available (PR is merged or closed)." exit. An actionless PR
  renders the normal picker header + one notice row; only q/Esc closes the popup.
- Notice copy: `No actions — PR is <merged|closed>.` for terminal PRs;
  `Could not load actions for <id>.` (plus a pm-log warning) when the window's PR
  id resolves to nothing.
- Nav list (h/l/←/→, 0 = home) holds non-merged/closed PRs with ≥1 open window,
  plus the home PR (invoking window's PR) whatever its status.
- Window ids resolve to PRs by display id, then local id / `#N` against
  `gh_pr_number` (window named `pr-abc` after the PR got `#12`, or vice versa).
- project.yaml + tmux window list reload on every nav key and right before any
  action dispatch; a PR merged mid-popup loses its actions and drops out of
  navigation (stays on screen until navigated away, unless home).
- Without fzf: an actionless PR prints header + notice and waits for a keypress.

## Setup

1. Install pm from this branch (`./install.sh --local` or editable venv with
   PYTHONPATH pointing at the clone; `pm which` must print the clone).
2. Throwaway project per `pm/qa/instructions/tui-manual-test.md`: `pm init
   --backend local --no-import`, add ≥4 PRs. Bootstrap statuses in project.yaml:
   two live PRs (e.g. A=in_review, B=qa), one merged PR M, optionally one closed C.
   Give some PRs `gh_pr_number` so display ids are `#N`.
3. Start `pm session` (attach failure is fine). Create tmux windows named after the
   PRs' display ids to simulate open PR windows: A (`#240`, `review-#240`), B
   (`qa-#242-s1` to exercise qa-scenario suffix), M (`#238`, `review-#238` — the
   "retained windows after merge" case), plus a non-PR window (the TUI window).
4. Open the picker by running `pm _popup-picker <session> <window-name>` inside a
   tmux window (or prefix+P in an attached client); drive with send-keys,
   observe with capture-pane. Mid-run state changes: `pm pr edit --status` or
   editing `status` in project.yaml (the latter models external merges / `pm pr
   sync`).
5. Live harness known to work (from impl note): scratch HOME with
   `~/.pm/pane-registry/<session>.json` = `{}`, project dir as cwd,
   `PM_TMUX_SOCKET` scratch socket, PYTHONPATH unset.

Action windows: start=`<id>`, review=`review-<id>`, qa=`qa-<id>[-sN]`,
signoff=`signoff-<id>`, merge=`merge-<id>`. Shortcut keys: s start, e edit,
d review, t qa, i signoff, g merge, z chord (z s/d/t/i fresh, zz d/t loop).

## Requirements

R1. **Given** live A and B have windows and merged M has retained windows,
**When** the user opens the picker from A's window, **Then** the header reads
`PR Actions — <A> (1/2)` with shortcut hints and `h/l: prev/next PR   0: home`;
A's action rows are listed; M is not counted.

R2. **Given** R1's popup, **When** the user presses next, next, prev, then home,
**Then** the header cycles A(1/2) → B(2/2) → A (wrap) → B → A; M never appears;
the popup never closes.

R3. **Given** the same project, **When** the user opens the picker from a non-PR
window (TUI), **Then** it lands on the first live PR in project.yaml order, not
M; nav hint shows `h/l: prev/next PR` without `0: home`.

R4. **Given** the same project, **When** the user opens the picker from M's own
window, **Then** header `PR Actions — <M> (i/3)`, only `q/Esc: quit` + nav hint
(no shortcut/chord hints), a single row `No actions — PR is merged.`.

R5. **Given** R4's popup, **When** the user presses s/e/d/t/i/g, z then s,
Enter, or double-clicks the notice row, **Then** nothing launches (no new tmux
window, no command run) and the popup stays open on M.

R6. **Given** R4's popup, **When** the user navigates next/prev (including
wraparound) to A or B, **Then** the target shows its actions and full hints;
pressing an action key there runs it (window created/selected) and the popup
closes normally; home returns to M with its notice.

R7. **Given** the picker open on A (opened from TUI), **When** B is marked merged
externally and the user presses next, **Then** B is skipped, the count shrinks
(e.g. `(1/1)` collapses to no count/nav hint, or n−1), no crash or exit.

R8. **Given** the picker open on A, **When** A is marked merged externally and
the user presses an action key (or Enter on an action row, or a z-chord second
key), **Then** nothing launches; A re-renders with `No actions — PR is merged.`;
next then reaches B whose actions work; navigating away from A drops A from the
list (unless A is home).

R9. **Given** a window named `#193` whose PR has since lost `gh_pr_number` (or a
window named `pr-abc` for a PR that has since gained `gh_pr_number: 12`),
**When** the picker opens there, **Then** it resolves to the PR and shows its
actions under its current display id (no duplicate nav entry); if the id truly
matches no PR, the row reads `Could not load actions for #193.` (never
"merged"), a warning appears in the pm log, and nav keys reach other PRs.

R10. **Given** the nav list holds only one PR and it is merged (home), **When**
the user presses Enter or action keys, **Then** popup stays open; q/Esc closes.

R11. **Given** no live PR has windows and the picker is opened from a non-PR
window (only merged/closed PRs have retained windows), **When** it opens,
**Then** it prints `No active PR windows open.` and exits after a keypress.

R12. **Given** fzf is not on PATH, **When** the picker opens on a merged home PR,
**Then** it prints the header and `No actions — PR is merged.` and waits for a
keypress before exiting (no instant flash-exit); on a live PR the numbered menu
works as before.

## Edge cases

E1. **Given** a closed PR (status `closed`) is home, **When** opened, **Then**
notice reads `No actions — PR is closed.`.
E2. **Given** the PR on screen gains `gh_pr_number` while open, **When** the user
navigates, **Then** header shows the new `#N` id and the PR is listed once.
E3. **Given** all navigable PRs get merged while the popup is open from a non-PR
window, **When** the user presses nav keys, **Then** the popup shows a notice for
the current PR and stays open; q/Esc quits.
E4. **Given** a merged PR becomes live again (status back to in_review) while
open, **When** user navigates, **Then** it reappears in the nav list.
E5. **Given** a qa-scenario-only window (`qa-#N-s1`) is the PR's only window,
**Then** the PR counts as navigable and its qa row is `[open]`.
E6. **Given** project.yaml is momentarily unparsable while the popup is open,
**When** the user navigates, **Then** the popup keeps prior state (warning in
log), does not crash.
E7. **Given** the home PR's windows are all closed while the popup is open,
**When** user presses home, **Then** home PR still shown.

## Concurrent use / shared resources

Shared resources: `pm/project.yaml` (read on each nav/dispatch, written by other
pm commands), the tmux session's window list (read on refresh; windows created
by dispatched actions), the pane registry / active-window map (●/○ markers per
client session), the pm log file (warnings).
- C1. Two popups open simultaneously from different windows (A's and M's, or two
  clients/grouped sessions) while a third actor edits statuses and creates/kills
  windows: each popup's nav list/count reflects the change on its next key, none
  crash/exit, and dispatch from one popup doesn't corrupt the other's view.
- C2. Rapid nav keypresses while project.yaml is being rewritten in a loop: no
  traceback, index never out of range, header id always matches rows.

## Pass/Fail criteria

Pass: every Then above observed in captured pane output; the popup only ever
closes via q/Esc or a successful action dispatch (or R11/R12 documented
exits); no Python traceback in the pane or pm log; no launched command/window
for a merged/closed PR; header id, `(i/n)` and rows always agree; misleading
"PR is merged or closed" copy never shown for a non-terminal/unresolvable PR.

Fail: popup exits on a keypress other than q/Esc/valid action; any traceback;
merged PR in nav list when not home; action dispatched for a terminal PR; stale
count/index (e.g. `(3/2)`, header naming a different PR than the rows).

## Ambiguities (resolved)

- Unresolvable home window id stays in nav list with "Could not load" notice
  (impl spec decision) rather than landing elsewhere.
- A PR merged while displayed stays on screen with its notice until the user
  navigates off it; then it drops out (unless home). Treated as correct.
- Editing project.yaml status by hand mid-run is acceptable in QA here: it is the
  real-world trigger (external merge / `pm pr sync`), and the impl note endorses
  it. `pm pr edit --status` may be used too where supported.
- Single-PR nav list shows no `(i/n)` and no nav hint — expected.
