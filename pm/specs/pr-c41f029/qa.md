# QA Spec — pr-c41f029

**Title:** Bug: capture originating tmux session when the PR actions pane
opens, not at action-execution time

## Summary of the change under test

When a TUI action that creates or replaces a window runs (review-loop, QA
loop, and — via fallback only — the project watcher), pm tries to move the
tmux session that *initiated* the action onto the freshly (re)created window
so the user "follows" their action onto its new window.

Before this PR the originating session was discovered **late**, at
action-execution time, by querying every grouped session's current active
window (`tmux.sessions_on_window`) and matching it against the old window id.
Between the user triggering the action from the PR-actions popup/picker and
that query running, focus can move (the popup closed, another grouped session
navigated, the old window was already killed/recreated). The query then
returns the wrong session — or none — and the wrong session, or nobody, gets
switched to the new window. It also adds several tmux round-trips of latency
on the action's critical path.

The fix captures the invoking session **once**, at picker/pane-open time, and
threads it through to the window-following call sites:

- `runtime_state.capture_origin_session(pr_id, action, session)` records the
  session on the per-`(pr_id, action)` runtime-state record (same channel as
  `suppress_switch`); `consume_origin_session` reads-and-clears it.
- `tmux.followers_for_window(base, window_id, captured)` prefers the captured
  session(s) and **skips** `sessions_on_window` entirely; it falls back to
  `sessions_on_window` only when nothing was captured.
- `tmux.active_client_session(base)` returns the lone attached client session
  (or `None` when zero/multiple are attached → ambiguous).
- The **popup picker** path (`_run_picker_command`) captures the popup session
  at dispatch time for both `tui:` and direct `pr start|review|merge` routes.
- The **in-TUI dispatch** path (command bar / keybindings, in `tui/app.py`)
  captures the unambiguous attached client for `review-loop` and `qa`.
- Consumers: `qa_loop.run_qa_sync` (QA window) and
  `cli/pr._launch_review_window` (review-loop window) consume the captured
  session and call `followers_for_window`. The **watcher** is project-level
  (no per-PR picker action) so it passes `None` and always falls back.

### Division of responsibility (important for QA expectations)
- **QA loop is the primary beneficiary** of the CLI-level fix. The popup
  spinner intentionally does **not** switch for `action == "qa"`; it leaves
  the switch to `qa_loop`, which is where the late-detection race actually
  bit. On first-time QA window creation with a captured origin, `qa_loop`
  switches that exact session onto the new window (unless the popup spinner
  was dismissed with q/Esc → `suppress_switch`).
- **review-loop**: for the POPUP path, the spinner (`_wait_for_tui_command`,
  `action != "qa"`) already switches the captured popup session onto the
  review window. The captured value is also consumed at the top of
  `_launch_review_window` but is typically *unused on iteration 1* (no
  existing window yet); iteration 2+ with `--fresh` uses
  `followers_for_window` with the captured value to move watchers onto the
  rebuilt window.

### Out of scope (present in `git diff master...HEAD` but NOT this PR)
The diff also shows changes to `pr_merge`/`pr_close` (gh_ops chokepoint),
`fake_github.py`, `gh_ops.py`, `git_ops.py`, `paths.py`, `pr_sync.py`, and
their tests. Those come from a merged-in PR (pr-9603d04), not commit
`8fd7929e` (this PR). They are not under test here.

## Known reproducibility constraint
The *live* race is timing-dependent across grouped tmux sessions and is **not
deterministically reproducible headless**. The mechanism is covered by
`tests/test_origin_session_capture.py` (fails pre-fix, passes post-fix) plus a
deterministic repro under the impl captures. QA should therefore (a) run that
regression suite to assert the bug no longer reproduces, and (b) exercise the
user-visible window-following surface (popup → QA/review window appears and the
originating session follows) to validate integration.

---

## Requirements (Given / When / Then)

### R1 — QA loop window-following follows the originating session (popup)
- **Given** a user attached to a grouped pm tmux session, viewing the PR list,
  with a PR that has a workdir and fake-claude configured to emit a QA verdict,
- **When** the user opens the PR-actions popup for that PR and selects "QA
  loop" (or "QA fresh"),
- **Then** a QA window is created and the user's session is switched onto that
  new QA window (the originating session "follows" the action), and the QA
  loop runs to its scripted verdict.

### R2 — review-loop window-following follows the originating session (popup)
- **Given** a user attached to a grouped pm tmux session, viewing a PR, with
  fake-claude configured to emit a review verdict,
- **When** the user opens the PR-actions popup and selects "review loop",
- **Then** a review-loop window is created and the originating (popup) session
  is switched onto it.

### R3 — in-TUI dispatch (command bar / keybinding) captures the attached client
- **Given** a user attached to exactly one grouped pm tmux session in the TUI,
  with a PR selected,
- **When** the user starts a review-loop or QA loop via the in-TUI command bar
  or its keybinding (not the popup),
- **Then** the new action window is created and the attached client session is
  switched onto it.

### R4 — CLI / legacy invocation still works via fallback detection
- **Given** a QA loop or review-loop is triggered with **no** captured
  originating session (e.g. invoked directly via the CLI, or by the
  project-level watcher),
- **When** the action creates/recreates its window,
- **Then** the action falls back to live detection (`sessions_on_window`) to
  decide which watching sessions to switch, and a session currently watching
  the old window is moved onto the new window (no crash, behavior unchanged
  from before the PR).

### R5 — regression suite proves the bug is fixed
- **Given** the PR branch checked out,
- **When** the bundled regression suite `tests/test_origin_session_capture.py`
  is run,
- **Then** all tests pass (these tests fail on pre-fix code), including the
  race-simulation test asserting the captured session wins over late
  detection and that `sessions_on_window` is not called when a capture exists.

---

## Setup (folds into each requirement's Given)

- Install the editable clone so `pm which` resolves to the branch checkout
  (override `PYTHONPATH` per the TUI manual-test instruction; if `pm` is not
  on PATH in the container, `./install.sh --local` from the repo).
- Create a throwaway pm project (`pm init --backend local --no-import`) and
  add one or more PRs via the CLI. For loop scenarios, give the PR a workdir
  by starting it (`pm pr start`) or use the fake so the loop can run.
- Configure **fake-claude** (`pm fake-claude config set`) so QA/review loops
  reach a deterministic verdict (e.g. `{"review": {"verdicts": ["PASS"]}}`,
  `{"qa_planning": {...}}`) without real Claude.
- Start the test session from the project dir (`pm session 2>/dev/null ||
  true`; ignore the attach error). Drive/inspect via a *new pane inside the
  test tmux session*, never the worker's own session. Use
  `tmux capture-pane`, `pm tui view`, and `tmux send-keys` to drive.
- For a second/grouped client (concurrency scenarios), attach another session
  to the same tmux group (`tmux new-session -t <base>` style grouping) so
  multiple grouped sessions share the window set.

---

## Edge Cases (Given / When / Then)

### E1 — popup spinner dismissed (q/Esc) suppresses the switch even with a capture
- **Given** a user opens the QA-loop popup for a PR (capturing the originating
  session) and then dismisses the popup spinner with `q`/`Esc`,
- **When** the QA loop subsequently creates its window,
- **Then** the originating session is **not** switched onto the new window
  (the dismiss set `suppress_switch`, which takes precedence over the captured
  origin); the QA window is still created and the loop still runs.

### E2 — malformed / unrecognized picker command does not capture or crash
- **Given** the picker dispatch receives a command that is empty, garbage, an
  unknown `pr` subcommand, an unparseable `tui:` route, or a `pr start` with no
  pr-id token,
- **When** dispatch runs,
- **Then** no origin session is recorded for any `(pr_id, action)` key and the
  dispatch proceeds (or no-ops) without raising — the `if o_pr and o_action`
  guard skips capture.

### E3 — ambiguous in-TUI client → fall back to detection
- **Given** zero or multiple clients are attached to the grouped session when
  an in-TUI review-loop/QA command is dispatched,
- **When** the action runs,
- **Then** `active_client_session` returns `None`, nothing is captured, and the
  action falls back to live detection (no spurious switch to the wrong session,
  no crash).

### E4 — captured origin survives the action's own state transitions
- **Given** an origin session captured at popup-open,
- **When** the action writes its own `launching` → `running` state transitions
  (and the suppress_switch-invalidation logic runs) before consuming the
  origin,
- **Then** the captured `origin_session` is preserved across those writes and
  is the value consumed at execution time (it is not clobbered by the
  state-machine writes).

### E5 — consume clears the capture (no stale leak)
- **Given** an origin session was captured and then consumed once,
- **When** the same `(pr_id, action)` action runs again without a new capture
  (e.g. a later CLI-triggered iteration),
- **Then** consume returns `None` and the action falls back to detection — the
  prior run's captured session does not leak into the next run.

### E6 — concurrent triggers across grouped sessions / multiple PRs
- **Given** two grouped sessions (A and B) both attached, and the per-PR
  runtime-state file is the shared resource that capture writes and consume
  reads,
- **When** session A triggers a QA/review action on one PR while session B
  triggers an action concurrently (same PR different action, or a different
  PR), driven from two panes at once,
- **Then** each action follows its own originating session onto its own window
  — A's window switches A, B's switches B — with no cross-contamination of the
  captured `origin_session` between the distinct `(pr_id, action)` keys, no
  lost updates from the flock-guarded writes, and no crash. (For same `(pr_id,
  action)` triggered twice, last-writer-wins is acceptable — the second capture
  overwrites the first.)

---

## Pass / Fail Criteria

**Pass:**
- R1/R2/R3: after triggering the action from the named surface, the
  originating/attached session ends up viewing the new action window, and the
  loop runs to its scripted verdict.
- R4: CLI/watcher invocation creates the window and a watching session is moved
  onto it via fallback detection; no error.
- R5: `tests/test_origin_session_capture.py` passes in full on the branch; a
  spot-check confirms representative tests fail when reverted to pre-fix
  behavior (or simply that the suite is present and green).
- E1: window created but originating session NOT switched after dismiss.
- E2/E3: no capture recorded, no exception, action proceeds/falls back.
- E4/E5/E6: captured value behaves as specified; concurrent triggers each
  follow their own originator with no cross-talk or corruption of the
  runtime-state file.

**Fail:**
- The originating session is NOT moved onto the new window when a capture
  exists (R1–R3), or the *wrong* grouped session is moved.
- An unrelated/stale session is switched because late detection ran despite a
  capture being present.
- A malformed command or ambiguous-client situation crashes dispatch or
  records a spurious capture (E2/E3).
- The captured value is clobbered by the action's state writes (E4) or leaks
  into a subsequent run (E5).
- Concurrent triggers corrupt the runtime-state file, lose a capture, or cause
  a session to follow the wrong window (E6).
- The CLI/watcher fallback path regresses (window not created, or watching
  session not followed) (R4).

---

## Shared-resource inventory (for concurrency coverage)

1. **Per-PR runtime-state file** `~/.pm/runtime/<pr_id>.json` — written by
   `capture_origin_session` (popup / in-TUI dispatch) and read+cleared by
   `consume_origin_session` (qa_loop / review-loop launcher). flock-protected;
   actions are keyed by `(pr_id, action)` within the file. Concurrent writers:
   multiple grouped sessions triggering actions, plus the action's own state
   transitions racing the capture. Exercised by **E6** (and E4).
2. **tmux server / session group + window set** — `switch_sessions_to_window`,
   `select_window`, `active_client_session`, `sessions_on_window` all operate
   on the shared tmux server and the grouped session's shared window list.
   Exercised by R1–R4 and **E6**.
3. **SIGUSR2 command-queue file (TUI IPC)** — the `tui:` picker route enqueues
   the command for the TUI to drain; capture happens before enqueue. Exercised
   indirectly by R1/R2 (popup path) and E6.

---

## Ambiguities (resolved)

- **What window-following looks like to a user.** Resolved: "the originating
  session follows" = that tmux session's active window becomes the newly
  created action window. Verified via `tmux capture-pane` / `pm tui view` /
  `display -p '#{window_name}'` on the originating session.
- **Whether review-loop iteration 1 from the popup demonstrates the
  capture-consume path.** Resolved per PR notes: on iteration 1 there is no
  existing review window, so `_launch_review_window`'s consumed capture is
  typically unused and the spinner performs the switch. The capture→
  `followers_for_window` path is best demonstrated for **QA** (R1) and for
  **review-loop fresh iteration 2+** (window already exists, gets rebuilt).
  Scenarios target QA for the primary capture-follow assertion and treat
  review-loop popup as the spinner-driven follow.
- **Driving the popup headlessly.** Resolved: the worker may drive the real
  keybinding via `tmux send-keys` (prefix+P → pick), or invoke the picker
  dispatch the popup shell uses, whichever is reproducible in the container;
  both exercise the same capture seam. The instruction lets the worker choose.
- **Out-of-scope merged changes.** Resolved: `pr_merge`/`pr_close`/fake-github
  changes belong to pr-9603d04 and are excluded from this plan.

No unresolved ambiguities.
