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
  review window, and focus is not later stolen when the launch completes (the
  suppress-switch flag is honored).

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

**Fail:**
- The popup stays on the spinner frame after the review window has opened.
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
