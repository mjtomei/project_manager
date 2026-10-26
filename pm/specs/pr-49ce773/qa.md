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
  `gh_pr_number`. A window named `pr-abc` still resolves after the PR gets
  `#12`; a window named `#193` cannot resolve after that number is removed
  from project.yaml and must show the lookup-failure notice.
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
   Give some PRs `gh_pr_number` so display ids are `#N`. For R9's missing-number
   case, remove the number explicitly in this throwaway project while retaining
   its `#N` window; the real historical #193 entry now has its number restored.
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
6. Harness traps from earlier rounds (all observed live):
   - The container ships no fzf, and apt only offers 0.29. Install the
     fzf 0.56.3 release binary (linux arm64/amd64) to `/usr/local/bin`.
     For the no-fzf story, move `/usr/local/bin/fzf` aside and restore it
     afterwards — the prefix+P popup shell takes PATH from the tmux server,
     so a per-shell PATH strip does not reach it.
   - `pm/project.yaml` is 0444 in a fresh project. Set status with
     `pm pr edit --status`; to change other fields, `chmod u+w` first (or
     write a temp file and `mv -f` it over the original).
   - `pm pr start` refuses unless the PR is in the committed project.yaml,
     so `git add -A && git commit` after bootstrapping statuses.
   - No vi/nano is installed and EDITOR is unset, so the `e` (tui:edit)
     pane exits at once. Install nano and
     `tmux set-environment -g EDITOR nano` if the story needs `e`.
   - To add `gh_pr_number` to an existing PR, REPLACE its
     `gh_pr_number: null` line; appending a second key is silently
     overridden by the null below it (YAML last-wins).
   - A real prefix+P works by attaching an outer client:
     `tmux -u -L rec new-session -d -s rec -x 160 -y 45 "env -u TMUX tmux attach -t <base>~1"`,
     then `tmux -L rec send-keys -t rec C-b P`.
   - Pre-existing on master, not this PR: Enter/double-click on a live
     action row used to close the popup without dispatching (fixed here by
     the `--expect` key-line handling); the popup shell failure handler
     adds a second dismissal after the picker's own error pause; and `e`
     opens the edit pane as a split of the client's current window rather
     than the invoking window.

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

R9. **Given** a window named `pr-abc` for a PR that has since gained
`gh_pr_number: 12`, **When** the picker opens there, **Then** it resolves to the
PR and shows its actions under `#12`, with no duplicate nav entry.
**Given** a window named `#193` whose PR has since lost `gh_pr_number` and no
other PR has that number, **When** the picker opens there, **Then** the id is
unresolvable: the row reads `Could not load actions for #193.` (never
"merged"), a warning appears in the pm log with the failed id, project root,
loaded PR count and a bounded sample of local/display-id pairs (plus omitted
count), and nav keys reach other PRs.

R10. **Given** the nav list holds only one PR and it is merged (home), **When**
the user presses Enter or action keys, **Then** popup stays open; q/Esc closes.

R11. **Given** no live PR has windows and the picker is opened from a non-PR
window (only merged/closed PRs have retained windows), **When** it opens,
**Then** it prints `No active PR windows open.` and exits after a keypress.

R12. **Given** fzf is not on PATH, **When** the picker opens on a merged home PR,
**Then** it prints the header and `No actions — PR is merged.` and waits for a
keypress before exiting (no instant flash-exit); on a live PR the numbered menu
works as before.

R13. **Given** the no-fzf numbered menu is waiting on a live PR, **When** that
PR becomes merged or closed before a number or shortcut is submitted, **Then**
no command runs; the current terminal-status notice is printed and waits for
dismissal. A selection on a still-live PR continues to dispatch normally.

## Edge cases

E1. **Given** a closed PR (status `closed`) is home, **When** opened, **Then**
notice reads `No actions — PR is closed.`.
E2. **Given** the PR on screen gains `gh_pr_number` while open, **When** the user
navigates, **Then** header shows the new `#N` id and the PR is listed once.
E3. **Given** all navigable PRs get merged while the popup is open from a non-PR
window, **When** the user presses nav keys, **Then** the popup shows a notice for
the current PR and stays open; q/Esc quits.
E4. **Given** a merged PR becomes live again (status back to in_review) while
open, **When** user navigates, **Then** it reappears in the nav list — also
when the list had collapsed to a single entry (h/l still reload then, though
the nav hint is hidden).
E5. **Given** a qa-scenario-only window (`qa-#N-s1`) is the PR's only window,
**Then** the PR counts as navigable and its qa row is `[open]`.
E6. **Given** project.yaml is momentarily unparsable while the popup is open,
**When** the user navigates, **Then** the popup keeps the complete last-good
snapshot (warning in log), does not crash, and navigation still works within
that snapshot. Repeat with a missing `prs` field and `prs: null`, `false`,
`0`, an empty string or a mapping: these must not replace the last-good list.
An explicit `prs: []` is a valid empty project: the list collapses to the
pinned home, whose header and notice name the invoking window id (`#12`) —
with no PR entry left there is no display id — and `d` is not in its expect
set. While such a malformed snapshot is on disk the TUI's background sync
must not log a traceback (a PR entry with a status but no `id` used to raise
`KeyError: 'id'` in `pm_core/tui/sync.py`); the popup's own log lines and the
captures must stay traceback-free. Cover the shapes that reach
`pr_sync.sync_prs`/`sync_from_github` too, with a workdir present so the
sync is not skipped: an id-less entry whose status is `merged`, and one with
a non-empty `depends_on`, each used to raise `KeyError: 'id'` through
`graph.ready_prs` after the `do_normal_sync` guards. The sync log must stay
traceback-free for both backends, and such entries must not appear in the
"ready" set. Failed dispatch refreshes must
show an explicit "Could not refresh PR actions; no action was run" notice in
both fzf and the numbered fallback (reopen the latter after repair). The notice
is two non-actionable rows (the second is "Repair project.yaml and retry.")
so neither is clipped by the 80-column popup.
Repeat with syntactically valid YAML containing a PR mapping
with `status` but no `id`, including a numbered home PR whose `gh_pr_number`
still resolves its display id. Also try null, empty and non-string local ids;
none may replace the last-good snapshot or be used in a command. Include quoted,
backslash-containing and whitespace-containing IDs. Opening the popup with
malformed initial data must show `Could not load PR actions: ...`, log the
failure and wait for dismissal without a traceback; the message must name
the rejected entry (its 1-based position plus the offending `id`,
`gh_pr_number` and `status`, with control characters escaped) so a bad entry
in a large project is locatable. After repairing
the file, the next nav key reloads normally. While refresh is failing, shortcut,
Enter-on-action, fresh/loop chord and no-fzf selections must not dispatch cached
actions. Repair the file with
the selected PR merged/closed; the next fzf action attempt shows its notice
without dispatch. Also try `title: null` and numeric titles (including `0`)
on a live PR: navigation remains usable and titles render as blank/text rather
than crashing; zero must render as `0`, not blank. Repeat valid-YAML partial
writes with a missing, null, empty or truncated status (`merg`): the picker must
reject the snapshot, not normalize it to actionable pending. Exercise navigation,
fzf dispatch and the no-fzf selection, then repair to merged and verify its
notice. Also use YAML-escaped control characters (NUL/newline/escape) in
`gh_pr_number`: reject the snapshot before fzf launches, retain the last-good
view on reload, and show the readable error on initial load, without a traceback.
Repeat title rendering with YAML multiline titles and escaped newline, carriage
return, tab, NUL and escape characters. The title remains a single printable,
non-actionable row (controls replaced with spaces); Enter on that row is a no-op,
even if a title continuation resembles an action. The stored title is unchanged.
Known limitation (review 8d08 i1, non-blocking): a tmux `list-windows` error is
indistinguishable from an empty window list, so a transient tmux error can
briefly show fewer nav entries; it self-heals on the next key. Do not file it
as a regression unless it persists or loses project.yaml state.
E7. **Given** the home PR's windows are all closed while the popup is open,
**When** user presses home, **Then** home PR still shown.
E8. **Given** a live PR is shown, **When** the user moves to an action row and
presses Enter (or double-clicks it), **Then** that action is dispatched (it
used to close the popup without running anything — S2 refiner note).
E9. **Given** a live PR is shown with the cursor on the PR title row (where fzf
starts), **When** the user presses Enter (or double-clicks the title row),
**Then** nothing is dispatched and the popup stays open on the same PR; only
q/Esc quits (review 6b78 i3 — this used to close the popup).

E10. **Given** navigation order A, B, C, the popup opened from the TUI and
now displaying B, **When** B becomes closed and C gains a GitHub number while
its local-id window remains, then next is pressed, **Then** C is shown under
its new number rather than skipped in favour of A. Repeat in the other
direction with A gaining the number and prev pressed; A must be reached.

E11. **Given** the popup displays A as #12, **When** another actor removes
A's GitHub number and assigns #12 to B before action dispatch, **Then** the
pending action still targets A's local ID, never B. Repeat with shortcut,
Enter-on-action, fresh/loop chords and the no-fzf menu. If A itself was removed,
no command runs and a lookup-failure notice is shown.
Repeat with a partial repair that assigns #12 to B while A still has #12
(also try integer `12` versus string `"12"`). The ambiguous snapshot must be
rejected, all pending action routes must refuse dispatch, and navigation must
retain the last-good list until repair. Duplicate local IDs must be rejected too.
Opening on either kind of duplicate snapshot shows a readable error and waits
for dismissal. Historical display-number duplicates where every matching PR is
merged/closed remain permitted and actionless; they must not block navigation
to unrelated live PRs. Also open from the TUI on live A=#12 with an earlier
closed B=#13, then mark A merged and assign B #12. Shortcut, Enter, fresh/loop,
no-fzf selection and navigation must show A's merged notice, not B's closed
notice. With no live destinations left, repeat next/prev: A's notice stays
accurate. Remove A's number and reopen A; navigation reaches A and dispatch
still targets A's local ID. A collision between live and terminal PRs still fails
closed. Repair unsafe duplicates, then navigate and dispatch normally.
Also remove/reassign A's number while its popup is open, then press `0`:
home must remain A under its current local/display ID, not become B or an
unresolvable old-number entry. From a non-PR window, next/prev must step from
A's identity in both directions, not from the new owner of its former number.
When A's only window was named for the removed number and no window matches
A's remaining display or local id, A is not navigable from a non-PR window
(impl.md: a removed `gh_pr_number` is not recovered — there is no persisted
window→PR association). The header count shrinks accordingly; assert the
reached PRs are the surviving neighbours in both directions and that no
action ever targets the new owner. Opening the picker from A's own window
still pins A when the window name matches A's local id.
Repeat starting from an unresolved `#12` home: repair it to resolve to A, reload
with `0`, next or prev, then remove A's number (with and without assigning it to
B). `0` must still return to A under its local ID, and an action there must target
A, not B. A home first resolved during refresh needs the same identity retention
as one resolved when the popup opened.
Also open from closed home H=#13 with live A=#12 and C=#14, navigate to A,
then change H to #12 and A to merged. Previous reaches H, next reaches C,
and home reaches H; repeat after a pending action first retains A's merged
notice. H's closed notice and A's merged notice must not overwrite each other,
and wraparound/home navigation still reaches C and dispatches its actions.
Finally, open from #13 whose local ID is the legacy numeric string `12`;
remove that PR while another live PR owns GitHub #12. Home must show the missing
local `12` notice with no actions, not reinterpret it as GitHub #12. Navigation
may explicitly reach the other live PR and dispatch there.

E12. **Given** the popup body cannot run pm (e.g. `pm` is missing from the
tmux server's PATH, or pm exits non-zero without its own pause), **When** the
user presses prefix+P, **Then** the popup prints `pm popup failed (exit N).`
with the command's real exit status and `Press any key to close...`, stays
open until a key is pressed, and then closes — no instant flash-close and no
`Illegal option` error (tmux 3.2 runs popup bodies under `/bin/sh`/dash).
After the picker's own error pause the handler may ask for a second
dismissal; that is pre-existing and not a regression.

## Concurrent use / shared resources

Shared resources: `pm/project.yaml` (read on each nav/dispatch, written by other
pm commands), the tmux session's window list (read on refresh; windows created
by dispatched actions), the pane registry / active-window map (●/○ markers per
client session), the pm log file (warnings).
- C1. Two popups open simultaneously from different windows (A's and M's, or two
  clients/grouped sessions) while a third actor edits statuses and creates/kills
  windows: each popup's nav list/count reflects the change on its next key, none
  crash/exit, and dispatch from one popup doesn't corrupt the other's view.
  When another client changes its selected window, the next navigation reload
  moves the corresponding open-circle indicator to that window's action row.
- C2. Rapid nav keypresses while project.yaml is being rewritten in a loop: no
  traceback, index never out of range, header id always matches rows.
- C3. Two clients attached to grouped sessions (e.g. `<base>~1`, `<base>~2`):
  an action dispatched from client 1's popup switches/creates the window in
  client 1's session only — client 2 (even if it was the most recently active
  client) keeps its current window (master #240: popup exports
  PM_POPUP_SESSION and dispatches via _session_pm_argv; this PR adds the
  guard that it is honoured only while that session exists).  Re-run after
  the master merge, plus one live action dispatch from a PR window.
  Open the two popups one after the other, not in the same instant (known
  race, pr-b511dcf).  When the dispatched action is the start fast path for
  a PR that already has a window, the popup's confirmation line must name
  the grouped session the window was actually switched in (e.g.
  `<base>~1`), not the bare base session (fix 9d687e29).  Drive this with
  `s`/Enter on a start row (or `z s`), never `e`.
- C4. Type-ahead while the picker reloads (impl QA check 9, fix 634c82da):
  with ≥2 navigable PRs, send nav keys in pairs ~10 ms apart (the second
  lands while the picker reloads between fzf runs).  The popup never closes,
  every captured frame shows a `PR Actions —` header (no empty-popup flash
  between relaunches), and the header/(i/n) end on the PR the key count
  predicts.  Then dispatch an action: the stale picker frame is cleared
  before the command's output appears.
- C5. Post-master-merge dispatch path (sign-off SIGNOFF_IMPL, merge
  37637456): both the picker's direct route and the `pm>` command popup
  (`_popup-cmd`) now run `_session_pm_argv(session, ...)` with
  PM_POPUP_SESSION exported.  A live action dispatched from a PR window
  (cwd = PR workdir) must obey the tmux session's fake-claude config.
  Observed live (S24): that gate is fixed, but popup/picker/dispatch log
  lines from a PR-workdir window still key off cwd and land in
  `~/.pm/debug/pm-pr-<id>-…-<hash>.log` rather than the session-tag log.
  Treat the log location as the known pr-f98ac63 gap, not a regression of
  this PR; the pane behaviour (fake-claude honoured, right window) is what
  this scenario must hold. After a client's grouped session goes away, a
  later popup on another client must still dispatch into that other
  client's session.

## Before/after evidence of the original symptom (sign-off request)

B1. **Given** a project where a merged PR with retained windows (like #238)
comes first in project.yaml order and a live PR (like #193, in_review) has
open windows, **When** the user opens prefix+P from the TUI window on the
base-branch (master 4dcbff73) build, **Then** the popup prints `No actions
available (PR is merged or closed).` and exits on a keypress; opening it on
the live PR and pressing next onto the merged entry and next again exits too.
**When** the same steps run on this branch, **Then** the popup lands on the
live PR, the merged PR is not in the list, opening it from the merged PR's
own window shows `No actions — PR is merged.` with working nav, and nothing
exits except q/Esc or a dispatched action.

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
