# Implementation spec — pr-1cb6e15

`pm pr review` silently regresses `qa` (and `sign_off`) → `in_review`

## Requirements (grounded in code)

**R1 — `qa` is inspection, not a phase transition.**
`pm_core/cli/pr.py::pr_review()` currently guards only `merged`, `in_review`
and `pending` (lines ~1544-1560) and then falls through to the `apply()` at
~1580-1586 that writes `status = "in_review"` and a status timestamp. For a PR
in `qa` this must instead:
- skip the GitHub "mark ready" call (`gh_ops.mark_pr_ready`, ~1570-1577),
- skip `store.locked_update` / `_record_status_timestamp` entirely,
- not call `_launch_review_window()` (which would remove/launch a container,
  generate a review prompt and start a second Claude agent),
- focus the PR's existing `review-<display>` tmux window when it exists,
- print a single informative line saying the PR is in QA and the status was
  not changed.

**R2 — `sign_off` gets the same treatment.**
Same branch for `status == "sign_off"`. This is the production incident: the
sign-off driver (`pm_core/signoff.py`, `pm_core/tui/signoff_ui.py`) refuses to
collect a verdict unless the PR is still `sign_off`, so a picker/CLI
`pr review` that demotes the PR strands the router's original verdict.

**R3 — every later phase is terminal for review.**
`merged` is already refused. `closed` is not guarded today and would be
resurrected to `in_review`; refuse it like `merged` (nonzero exit, no state
change). `pending` keeps its existing refusal.

**R4 — inspection is side-effect free.**
Add `_focus_review_window(pr_entry) -> str | None` next to
`_launch_review_window()`. It:
- resolves the pm session exactly as `_launch_review_window` does
  (`_get_pm_session()` + `session_exists`), so popup invocations keep their
  `PM_POPUP_SESSION` targeting through `tmux_mod.select_window`,
- computes the window name from `_pr_display_id(pr_entry)` (`review-#42` /
  `review-pr-001`),
- calls `tmux_mod.select_window()` when the window exists and returns its name,
- returns `None` (without creating anything) when there is no window.
It must not touch project.yaml, `signoff`, `signoff_return`
(`awaiting`/`launch_claim`), `integration`, timestamps, containers, runtime
state or the pane registry, and must not call `clear_return_awaiting` (which
`_launch_review_window` does at its tail).

**R5 — explicit fresh review is distinguished from inspection.**
`--fresh` (and `--review-loop`, which implies fresh) is an explicit request
for a new review session, not inspection. On a `qa`/`sign_off` PR it is
refused with a nonzero exit and a message naming the phase and pointing at
plain `pm pr review` for inspection. Rationale: honouring it would start a
second agent against a PR whose current phase owns the branch (and, for
sign-off, could move HEAD out from under the running router). This keeps the
QA/sign-off gates intact rather than bypassing them.

**R6 — `--no-window` on a later phase is a no-op.**
Auto-review uses `pr review --no-window` to perform the `in_progress →
in_review` transition only. On `qa`/`sign_off` it must return without a
status write or window, printing a short "status unchanged" line.

**R7 — existing phases unchanged.**
`in_progress` still transitions to `in_review`, upgrades a GitHub draft and
launches the window; `in_review` still prints "already in_review" and
launches/refocuses via `_launch_review_window` (including clearing a sign-off
REVIEW return, which is intentional there); `pending`/`merged` messages stay.

**R8 — regression tests.**
Add `tests/test_pr.py` (the file does not exist yet) with CLI tests that fail
on the pre-fix code:
- `qa` and `sign_off`: status/timestamps/sign-off records unchanged,
  `_focus_review_window` called, `_launch_review_window` and
  `mark_pr_ready` not called,
- missing review window: no launch, "no review window" message,
- `--fresh` / `--review-loop` on `qa`/`sign_off`: nonzero, no state change,
- `--no-window` on `qa`: no launch, no change,
- `in_review` and `in_progress` still behave as before,
- `merged` / `closed` refused,
- direct `_focus_review_window` unit tests (focus existing, never create).

**R9 — TUI `d` and picker `d` surface the message.**
- Picker direct route: `pm_core/cli/session.py::_run_picker_command()` runs
  `pm pr review <id>` and echoes captured stdout verbatim, so the inspection
  line must go to **stdout** on the success path.
- TUI `d` (`pm_core/tui/pr_view.py::review_pr`) has a non-fresh fast path that
  switches to an existing window itself (no subprocess, no state change). When
  it does spawn `pm pr review`, `_run_command_async` logs only the **last**
  stdout line — so the inspection message must be a single line that is also
  the last thing printed. `_focus_review_window` therefore prints nothing;
  `pr_review` emits exactly one composed line (window-focused vs.
  no-window-found).

**R10 — live sign-off exactly-once.**
While a sign-off is mid-flight (launch stamped, router transcript carrying
`SIGNOFF_MERGE`), opening the review through the real CLI and the picker
direct dispatch must leave `status == "sign_off"` and must not disturb the
`signoff`/`signoff_return`/`integration` records. The subsequent
`signoff.step_signoff()` tick must adopt the **original** verdict exactly
once (`ready_to_merge`, one recorded `pr["signoff"]`), and a repeat tick must
not re-route or duplicate it. No auto-merge is performed.

## Implicit requirements

- `_focus_review_window` must be a no-op outside tmux (mirrors
  `_launch_review_window`'s `has_tmux() and in_tmux()` guard); the CLI still
  exits 0 and says the status was unchanged.
- The inspection branch must run **before** the GitHub mark-ready block, so a
  `qa`/`sign_off` PR never upgrades its draft or calls the network.
- The inspection branch must not call `trigger_tui_refresh()`: nothing on disk
  changed, and a spurious reload can race a concurrent QA/sign-off write.
- `pr_entry` may be keyed by GitHub number (`#42`/`42`); messages must use
  `_pr_display_id(pr_entry)` for the display name, matching the rest of the
  command.
- The refusal message for `fresh` must be on **stderr** (error path) so the
  picker shows `pm error: ...` and waits for dismissal; the inspection message
  is on stdout.
- `--review-loop` is always passed with `--fresh` by
  `pm_core/review_loop.py::_launch_review_window`, so both flags must be
  checked.
- Don't weaken the gates: the change only affects `pr_review`'s status write;
  `apply_signoff_hop`, `qa_loop_ui`'s `qa → in_review` NEEDS_WORK transition,
  and the merge gate are untouched.

## Ambiguities and resolutions

1. **What should `--fresh` do on a `qa`/`sign_off` PR?**
   *Resolution:* refuse it (nonzero exit). It is the only option that both
   distinguishes an explicit fresh review from inspection and guarantees the
   running phase is never given a second agent or a HEAD change. Plain
   `pm pr review` remains the inspection path; a genuine re-review happens
   after QA NEEDS_WORK / a sign-off bounce returns the PR to `in_review`.
2. **If no review window exists on a later-phase PR, should we create one?**
   *Resolution:* no. Creating one runs `_launch_review_window`, which starts a
   review agent and can clear a sign-off return claim — exactly the state
   churn the task forbids. Print "no review window to open; status unchanged
   (no new review started)".
3. **Is `closed` in scope?**
   *Resolution:* yes, as a terminal refusal (like `merged`). It is a later
   phase and today it is silently resurrected to `in_review`.
4. **Should the TUI's own `review_pr` fast path print the new message?**
   *Resolution:* no change needed. It already focuses an existing window
   without a subprocess and without touching state; the message only matters
   on the spawned-CLI path, which now emits it.

## Edge cases / interactions

- **Open sign-off return** (`signoff_return.awaiting == "review"`) belongs to
  a PR in `in_review`, not `qa`/`sign_off` (`apply_signoff_hop` sets the
  status), so the new branch cannot swallow a REVIEW relaunch. The inspection
  helper never calls `clear_return_awaiting` anyway.
- **Concurrent TUI auto-start**: `_auto_start_review_loops` only targets
  `in_review`; `_auto_review_idle_prs` only transitions idle `in_progress`
  PRs. Neither calls review on `qa`/`sign_off`.
- **Picker `zz d`** maps to `tui:review-loop start`, which does not go through
  `pr_review` directly; a user-initiated loop on a later-phase PR is a
  separate surface (the loop's first iteration calls
  `pr review --fresh --review-loop` and is now refused, which stops the loop
  before it starts an agent).
- **GitHub backend**: no `mark_pr_ready` on inspection, so no network call and
  no draft→ready side effect.
- **PR keyed by gh number**: `_focus_review_window` uses `_pr_display_id`, so
  `review-#42` is found whether the caller passed `#42`, `42`, or `pr-001`.
- **`pm pr review` with no id** keeps its `in_progress`-only inference; a
  later-phase PR is reached by explicit id (or the picker/TUI selection).
- **`--transcript`** (TUI passes it) is ignored on the inspection path: no
  session is started, so no transcript symlink is written.

## Files to change

- `pm_core/cli/pr.py` — add `_REVIEW_INSPECTION_PHASES`,
  `_focus_review_window()`, and the new branch in `pr_review()`; guard
  `closed`.
- `tests/test_pr.py` — new regression suite.
- (No change) `pm_core/cli/session.py`, `pm_core/tui/pr_view.py`,
  `pm_core/signoff.py`, `pm_core/tui/qa_loop_ui.py`, `pm_core/tui/signoff_ui.py`.
