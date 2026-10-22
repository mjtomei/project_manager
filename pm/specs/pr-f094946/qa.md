# pr-f094946 QA spec: background QA starts must not pull clients off the TUI

## Summary of the change

Before this PR, the QA loop selected the new `qa-<pr>` tmux window the first
time it created it, unless the popup's suppress-switch flag was set. The
select targets the attached client's session, including grouped `$SESS~N`
view sessions. So any QA run that pm started on its own (auto-start, review
PASS → QA, sign-off SIGNOFF_REQA, self-driving restart, `pm pr auto-sequence`
→ `pm pr qa-run-bg`) moved every attached client from the TUI window to
`qa-<pr>`.

Now `QALoopState.focus_on_create` defaults to False. Only the user's own
starts set it: `t` with no QA window, `z t`, and the first `zz t`. The
"replacement" path is unchanged. When a `qa-<pr>` window already exists and
some clients are viewing it, those clients follow the new window. Clients
anywhere else stay where they are.

## Setup (cross-cutting)

* Install pm from this branch (`./install.sh --local`, or the venv and
  `PYTHONPATH` override in `tui-manual-test.md`). `pm which` must point at
  the clone.
* A throwaway git project with `pm init --backend local --no-import`, a few
  PRs, and `pm session` started from it.
* `pm fake-claude config set` drives the impl, review, QA, and sign-off panes
  without real Claude. `{"_all": {}}`, plus review PASS and the QA planning,
  scenario, verification, and finalize verdicts, gives an impl → review PASS
  → QA pipeline.
* A client attached to the pm session and parked on the TUI window (`main`),
  for example `script -qfc "tmux attach -t <sess>" /dev/null` in the
  background or a recorder. For the grouped case, also attach a client to a
  grouped view session (`<sess>~N`) parked on the TUI window.
* Track the active window per client with `tmux list-clients -F
  '#{client_name} #{session_name} #{window_name}'`, polled throughout. Also
  read pm's debug log (`select_window: target=...` lines) under
  `~/.pm/sessions/<tag>/` or `~/.pm/logs`.

## Requirements

**R1: Auto-start QA leaves attached clients on the TUI (the original bug).**
Given a pm session with one client attached on the TUI window, fake-claude
configured, and a PR that will pass review,
When the user adds that PR to auto-start (`pm autostart add <pr>`, or the
TUI `autostart` command),
Then the impl, review, and QA windows appear in the background, a `qa-<pr>`
window is created, and the client stays on the TUI window the whole time.
The debug log has no `select_window: target=<sess>:qa-<pr>` line.

**R2: Grouped view sessions are not moved either.**
Given clients attached to the base session and to a grouped `<sess>~N`
session, both on the TUI window,
When auto-start launches QA for a PR,
Then neither client changes window, and no `select_window` line targets
`<sess>~N:qa-<pr>`.

**R3: The log pane opens in the TUI window after an auto-QA start.**
Given auto-start has just launched QA for a PR and the user's client is still
on the TUI window,
When the user presses `L` in the TUI,
Then the log pane opens in the TUI window, not in `qa-<pr>`, and the QA
planner pane in `qa-<pr>` is still the planner. The log pane is not
registered as `qa-planner`, and the QA loop goes on to produce scenarios.

**R4: Plain `t` still switches to a new QA window.**
Given a PR in review or QA with no `qa-<pr>` window, and the user on the TUI,
When the user presses `t` on that PR (or runs `/pr qa <pr>` from the command
bar),
Then the user's client is switched to the new `qa-<pr>` window.

**R5: Dismissing the popup spinner still keeps focus.**
Given the user starts QA from the popup or picker, which shows a spinner,
When the user dismisses the spinner with q/Esc before the window opens,
Then the QA window is created but the client is not switched to it. A later
`t` starts no second run (it focuses the existing window).

**R6: `z t` (fresh start) and the first `zz t` still switch on first
creation.**
Given no `qa-<pr>` window exists,
When the user presses `z t` (or `zz t`) on the PR,
Then the client is switched to the new `qa-<pr>` window.

**R7: Self-driving follow-up runs are focus-safe.**
Given `zz t` is running with a required pass count above 1, and the user has
moved back to the TUI window,
When a QA run PASSes and the self-driving loop restarts QA,
Then the user's client stays on the TUI. A client that was viewing
`qa-<pr>` when it was replaced follows the new `qa-<pr>` window.

**R8: Sign-off SIGNOFF_REQA → QA is focus-safe.**
Given auto-start has taken a PR through QA PASS to sign-off, and fake-claude
sign-off returns `SIGNOFF_REQA` first,
When sign-off routes the PR back to QA,
Then a new QA run starts and no client on the TUI is moved.

**R9: The CLI auto-sequence QA driver is focus-safe.**
Given a client attached on the TUI window and a PR whose review has passed,
When the user (or a watcher) runs `pm pr auto-sequence <pr>` and it spawns
the detached QA driver,
Then `qa-<pr>` is created and QA runs, and the attached client stays on its
window.

## Edge cases

**E1: Several PRs auto-start QA at once.**
Given auto-start targeting 2–3 independent PRs and several attached clients
(base and grouped),
When their QA windows are created close together,
Then no client moves at any point and every `qa-<pr>` window exists.

**E2: A user start racing a background start.**
Given auto-start is about to launch QA for PR A,
When the user presses `t` on a different PR B at about the same time,
Then only the user's own client moves, to `qa-B`. No client is taken to
`qa-A`, and the other attached clients stay put.

**E3: A popup suppress flag pending while a background start happens.**
Given the user asked to keep focus for a QA start (popup dismissed) and a
background start for the same PR runs first,
When the user's start runs,
Then the background start has not used up the flag, so the user's start
still does not switch.
Best effort. Hard to stage from the user's side, so a worker may use the
regression test as evidence for this case.

**E4: A background restart with nobody watching the old window.**
Given `qa-<pr>` exists and no client is viewing it,
When a background QA restart replaces it,
Then no client moves.

**E5: A merged or closed PR in `qa-run-bg`.**
The driver exits before creating a window (unchanged). No window is created
and no client moves.

## Pass/fail criteria

* **Pass:** Every Then holds when checked against the polled client/window
  list, the TUI capture, and the debug log. The reproduction test
  `tests/test_qa_background_focus.py` and `tests/test_qa_self_driving.py`
  pass.
* **Fail:** Any background-started QA moves any attached client (base or
  grouped) to a `qa-*` window. Or the log pane lands in a QA window, or gets
  registered as `qa-planner`. Or a user-initiated `t`, `z t`, or `zz t` no
  longer switches to a newly created QA window. Or popup dismissal no longer
  keeps focus.

## Ambiguities (resolved)

* **Self-driving follow-ups:** only the user's first `zz t` switches. Restarts
  and review → QA bounces are background starts (matches the impl spec).
* **`z t` when a `qa-<pr>` window already exists and the user is on the
  TUI:** unchanged from before. The replacement window does not switch a
  client that wasn't viewing the old one. Not a regression.
* **Background starts and the suppress flag:** a background start leaves the
  flag for the user start it was set for.
* **`pm pr qa` from a shell:** that CLI path tells the user to use the TUI.
  The command bar `/pr qa` is the user-initiated surface that goes through
  `focus_or_start_qa`.
