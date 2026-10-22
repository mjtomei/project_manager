# QA Spec: pr-8409c64 — `zz d` review-loop popup spinner never switches to the review window

## Background

The pm tmux TUI exposes a popup picker (fzf-based). From the picker a user can
press the chord `zz d` on a PR to start/restart a **review loop**. This routes
`tui:review-loop start <pr>` to the running TUI and then shows a popup
**spinner** (`_wait_for_tui_command` in `pm_core/cli/session.py`) while the
review window is (re)created. Once the `review-<display_id>` window appears, the
spinner is supposed to **switch the invoking session's focus to that window**
and dismiss the popup.

### The bug

The spinner resolved the PR's `display_id` from `state_root()`, which is derived
from the popup process's **current working directory** (`PM_PROJECT` /
cwd-walk). The popup inherits the cwd of the pane it was launched from. When
that pane's cwd is **not** the pm project that owns the PR — e.g. a scratch
shell, a directory with no `project.yaml`, or a *different* pm project / workdir
clone — `state_root()` loads the wrong (or no) `project.yaml`, the `pr_id` is
not found, and `display_id` stays `None`. With `display_id = None`, the target
window name is `None`, so the spinner watches **nothing**: it never observes the
review window, never fires the focus switch, and spins forever on the
"starting"/"running" frame. This breaks **all three** acceptance cases (no
review window open, review window with a running loop, review window with a
terminal loop) identically, because the failure is upstream of any
window/state logic.

### The fix

`_wait_for_tui_command` now resolves the root from the **session**
(`_resolve_root_from_session(session)`, the same way the popup picker resolves
its listing) and only falls back to `state_root()` when session metadata is
absent. This makes `display_id` resolve correctly regardless of the launching
pane's cwd, so `target_window` is set, the review window is observed, and the
switch fires.

## Requirements

### R1 — Fresh review-loop from a foreign-cwd window switches focus (no window open)
- **Given** a pm session whose project owns a PR, with **no** `review-<id>`
  window currently open, and the user's active pane sits in a window whose
  working directory is **outside** the PR's project (a scratch dir or a
  different pm project).
- **When** the user opens the popup picker on that PR and presses the
  review-loop chord (`zz d`).
- **Then** a `review-<display_id>` window is created, the session's active
  window switches to it, and the popup spinner dismisses (it does **not** stay
  on the "starting"/"running" frame).

### R2 — Restart review-loop with a review window already open + running loop (foreign cwd)
- **Given** the same foreign-cwd starting pane, but a `review-<id>` window is
  already open and currently running a review loop.
- **When** the user invokes the review-loop chord (`zz d`) again on that PR.
- **Then** focus lands on the (rebuilt) `review-<display_id>` window and the
  spinner dismisses; it never holds the "rebuilding"/"starting" frame
  indefinitely.

### R3 — Restart review-loop with a review window already open + terminal loop (foreign cwd)
- **Given** the same foreign-cwd starting pane, with a `review-<id>` window
  already open whose loop has finished (terminal verdict, e.g. PASS/NEEDS_WORK).
- **When** the user invokes the review-loop chord (`zz d`) again on that PR.
- **Then** focus lands on the rebuilt `review-<display_id>` window and the
  spinner dismisses.

### R4 — Nominal path from the project's own window still works (fallback regression guard)
- **Given** a pm session whose active pane sits in the project's own
  directory (the normal case, where `state_root()` would have resolved
  correctly anyway).
- **When** the user invokes the review-loop chord on a PR.
- **Then** focus still lands on `review-<display_id>` and the spinner dismisses
  — the session-based resolution and the `state_root()` fallback must not
  regress the previously-working path.

### R5 — User can dismiss the spinner without switching focus (suppress-switch)
- **Given** the review-loop spinner is showing in the popup.
- **When** the user presses `q` or `Esc`.
- **Then** the popup closes immediately, the session does **not** switch to the
  review window, and focus is not later stolen when the launch completes.
  Assert this on the surface (active window). For review-loop the spinner is
  the only switcher, so once it exits nothing switches. No later
  `consume_suppress_switch` call is involved, so do not assert one.

### R6 — QA `t`, newly launched QA window: live switch AND popup dismissal
Added 2026-10-22 (user report: `t` switched the client to the QA window but the
picker popup stayed open over it). Per the project owner (2026-10-22), this
variant is **not** proven fixed by code inspection or the unit tests in
`tests/test_spinner_review_loop_switch.py`; it must be shown live, and the
original context is unknown, so every cell of the context matrix below is
tested rather than guessed.
- **Given** a PR with **no** `qa-<display_id>` window open, a client attached
  to the session (a grouped `pm-<tag>~N` client session, as a real user has),
  and that client's active pane in one of the contexts **C1–C4** below.
- **When** the user opens the popup picker on that PR from that pane and
  presses `t` (`tui:pr qa <pr>`, non-fresh).
- **Then**, asserted **separately** for each context (one failing assertion
  fails the cell even if the others hold):
  - **(a) focus** — the *originating* client's window becomes
    `qa-<display_id>` (`tmux list-clients -F '#{client_name} #{session_name}
    #{window_name}'` or `display-message -p -t <client-session>
    '#{window_name}'`; not the base session's active window, which can differ).
  - **(b) dismissal** — once that window exists, the `pm _popup-picker`
    process has exited and the popup overlay is gone from the client's screen,
    with no extra `q`/`Esc`/Enter, while the QA run is still non-terminal.
    Record the picker pid and its exit time alongside the runtime_state `qa`
    entry, and the spinner log line `spinner exit: reason=window_open
    target=qa-<display_id>` (must NOT be `reason=terminal_state`).
  - **(c) QA continues** — after the popup is gone the run keeps going:
    `qa-<display_id>` still alive, scenario windows `qa-<display_id>-sN`
    appear/progress afterwards, and the run's `qa_status.json`
    (`~/.pm/workdirs/qa/<pr_id>-*/`) has no `overall` yet. Do not require a
    runtime_state `qa` entry: QA mirrors one only through pane registration
    and otherwise writes it only at `done`.

### R7 — QA `t` with an existing QA window/run: live switch AND popup dismissal
- **Given** the same attached client and contexts **C1–C4**, with a QA run
  already open for the PR (`qa-<display_id>` and `qa-<display_id>-sN`
  windows, run `running`), the client sitting on some other window.
- **When** the user presses `t` on that PR in the picker.
- **Then**, asserted separately per context: (a) the originating client lands
  on the QA window; (b) the picker process/overlay is gone promptly
  (`reason=window_open`), without a keypress and without waiting for the run;
  (c) the existing run is neither stopped nor restarted — same QA window ids,
  same run/loop id, scenario windows untouched, state still `running`.

### R6/R7 context matrix
Run R6 and R7 in every context (8 cells). The popup inherits the pane's cwd
(via `_popup-show -d`), but its environment comes from the tmux **global +
client-session** environment, not the pane shell. So set or unset
`PM_PROJECT` with `tmux set-environment -t <client-session> PM_PROJECT <root>/pm`
or `-r PM_PROJECT`, check `-g` as well, and confirm with a probe popup:
- **C1 — TUI/root, `PM_PROJECT` unset**: pane cwd = the session's project root
  (the TUI/main window or a shell `cd`'d there); `unset PM_PROJECT`.
- **C2 — TUI/root, `PM_PROJECT` set** to the session's pm dir.
- **C3 — PR workdir, `PM_PROJECT` unset**: pane cwd = another PR's workdir
  clone whose `pm/project.yaml` is a stale branch copy. Make the staleness
  real: the target PR is absent from that copy, or (github/`#N` form) lacks
  the `gh_pr_number` it has on the session root.
- **C4 — PR workdir, `PM_PROJECT` set** to the session's pm dir (what a
  session started with `PM_PROJECT` forwards into its panes).

As a control, run C1–C4 on the pre-fix code (`origin/master` pm_core) too and
record which cells reproduced "switched but popup stayed open". Expected:
C3 reproduces pre-fix. If any cell fails post-fix, or a pre-fix failure shows
up in a cell where the old lookup was already correct (C1/C2/C4), that is a
**distinct remaining cause**: diagnose it from the spinner log
(`~/.pm/debug/<tag>.log`, `PM_SPINNER_TRACE=1`) and fix it on this PR or file
it as a separate bug — do not count the cell as passing.

Out of scope: `z t` (fresh QA) from a non-QA window moving the originating
client to the new `qa-<id>` window. For `qa` the spinner deliberately never
selects a window, and following the invoker needs origin-session capture,
which pr-c41f029 owns (see impl.md EC6). Do not fail this PR's cells on
that behavior.

### R8 — A failed launch still surfaces its error
- **Given** an action whose launch fails (runtime_state reaches `failed`, or a
  terminal verdict of ERROR/KILLED, without its window appearing).
- **When** it is invoked from the picker.
- **Then** the popup shows `✗ <action>: failed (...)` and waits for
  `q`/`Esc`/Enter — it must not silently close as if it had succeeded.

## Setup

Common setup for every requirement (per `tui-manual-test.md`):
1. Install the PR's pm into a venv with `PYTHONPATH` pointing at the clone;
   confirm with `pm which`.
2. Create a throwaway git project, `pm init --backend local --no-import`, and
   add at least one PR with `pm pr add`. Note the generated `pr-<hash>` id; its
   review window will be named `review-pr-<hash>` (or `review-#N` if a GitHub
   number is set).
3. Drive the review loop deterministically with **fake-claude**
   (`pm fake-claude config set`) so the loop reaches a verdict without a real
   model — e.g. `{"_all": {}, "review": {"verdicts": ["PASS"]}}` or a scripted
   `["NEEDS_WORK", "PASS"]` sequence for the running-loop case.
4. Start the session from the project dir: `pm session 2>/dev/null || true`
   (the attach failure with no tty is expected; the session is created).
5. Drive/inspect the TUI from **outside** via `pm tui send`,
   `pm tui view`, and `tmux capture-pane`; run pm commands inside a new pane of
   the test session, never in the worker's own shell.

**Establishing the "foreign cwd" condition (R1–R3):** create a second directory
that is either not a pm project at all, or a separate `pm init` project that
does **not** contain the PR. Open a window/pane in the test session whose
working directory is that directory, and invoke the popup picker / chord from
there. This reproduces the bug condition the fix addresses. (Pre-fix: spinner
spins forever, no switch. Post-fix: switch fires.)

## Edge Cases

### E1 — Foreign cwd has a different pm project that lacks the PR
- **Given** the launching pane's cwd is a *valid but different* pm project whose
  `project.yaml` does not contain the PR id.
- **When** the user invokes the review-loop chord on the PR.
- **Then** the switch still fires (session-resolution ignores the foreign
  project.yaml). Pre-fix this would load the wrong project and leave
  `display_id = None`.

### E2 — Launching pane cwd has no project.yaml at all
- **Given** the launching pane's cwd is a plain scratch dir (no project.yaml
  anywhere up the tree), so `state_root()` would raise.
- **When** the user invokes the review-loop chord on the PR.
- **Then** the spinner still resolves the PR via the session and switches
  focus; it does not crash or spin forever.

### E3 — PR with a GitHub number (display id `#N`)
- **Given** a PR whose `gh_pr_number` is set, so its review window is
  `review-#N`.
- **When** the user invokes the review-loop chord from a foreign-cwd window.
- **Then** focus lands on `review-#N`.

### E4 — Concurrent invocations against the shared review window / runtime state
- **Given** two panes (or two attached sessions in the group) both targeting the
  same PR.
- **When** both invoke the review-loop chord at nearly the same time.
- **Then** no spinner is left spinning forever; the active window ends on
  `review-<display_id>`; the shared runtime_state entry and the single review
  window converge to a consistent state (no orphaned/duplicate review windows
  that strand a spinner).
- Spec facts for writing E4 Thens (QA S8 round 2 found these Thens false as
  written; all are by design, not product bugs):
  - Launches serialise on `_review_window_launch_lock`
    (`~/.pm/workdirs/.review-launch-<pm-session>-<pr_id>.lock`). The later
    launch supersedes the earlier one, so exactly one `review-<display_id>`
    survives. The superseded launch still uses up one fake-claude review
    verdict slot, so to see NEEDS_WORK→PASS on the surviving loop, configure
    a 3-entry sequence such as `[NEEDS_WORK, NEEDS_WORK, PASS]`.
  - For a concurrent QA `t`, the spinner trace has **no** `select_window`
    line, because the QA launch selects `qa-<id>` itself. Assert
    `reason=window_open` and the client's window, not a spinner select.
  - While QA is running, runtime_state has no `qa` entry. One appears only at
    `done`, so check `qa_status.json` for liveness instead.

### E5 — Spinner dismissed mid-flight, then loop completes
- **Given** the spinner is up and the user presses `q`/`Esc` before the review
  window appears.
- **When** the launch later completes and the review window opens.
- **Then** focus is **not** auto-stolen (suppress-switch honored), confirming
  the dismiss path still works after the root-resolution change.

## Pass/Fail Criteria

**Pass:**
- After invoking `zz d` from any window (foreign-cwd or project-cwd), the
  session's active window becomes `review-<display_id>` and the popup closes,
  for all three states (no window / running loop / terminal loop).
- The spinner never remains on the "starting"/"running"/"rebuilding" frame once
  the review window has opened.
- The bundled reproduction test `tests/test_spinner_review_loop_switch.py`
  passes on this branch (and demonstrably fails when the fix is reverted).
- `q`/`Esc` closes the popup without switching, and the launch does not later
  steal focus.
- QA `t` (R6 new window, R7 existing window) in every context C1–C4: the
  originating client is on `qa-<display_id>`, AND the picker process/overlay
  is gone (`reason=window_open`) while QA keeps running — each asserted live
  and separately; unit tests alone do not satisfy this.
- A failed launch shows its error and waits for dismissal.

**Fail:**
- The popup stays on the spinner frame after the review (or QA) window has
  opened, in any R6/R7 context cell, or the QA run is stopped/restarted by `t`.
- Focus never moves to `review-<display_id>` (active window stays on the
  launching window).
- The spinner crashes, or a regression breaks the nominal project-cwd path or
  the `q`/`Esc` dismiss path.

## Ambiguities

- **How to reliably reproduce the "foreign cwd" condition in a real TUI.**
  Resolved: the cleanest user-faithful repro is to open a window/pane whose cwd
  is a directory other than the PR's project (a scratch dir with no
  project.yaml, or a second pm project lacking the PR) and invoke the chord
  from there. This matches the PR's stated symptom ("from another window") and
  the verified root cause (cwd-based `state_root()` resolution). The home
  window (cwd = project) would NOT have reproduced the bug, so scenarios must
  deliberately drive from a foreign-cwd pane to exercise the fix.
- **The PR task premise says "the spinner is watching the right window / NOT the
  cwd-yaml case."** Resolved per the implementer's verified note: that premise
  is inaccurate — the actual root cause IS a cwd-root-resolution gap, just in a
  different code path than #206. Scenarios are written against the verified
  behavior (foreign-cwd repro), not the original premise.
- **Whether driving the popup spinner end-to-end through real tmux is feasible
  for every scenario.** Resolved: scenarios should drive the real TUI surface
  (popup + chord + window switch) and capture the active-window transition;
  the bundled unit test serves as the deterministic pre-fix/post-fix anchor in
  one scenario.
