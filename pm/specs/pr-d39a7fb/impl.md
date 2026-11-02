# Spec: Improvement-Fix Implementation Watcher

## Requirements

1. **New watcher class** `ImprovementFixImplWatcher` in
   `pm_core/watchers/improvement_fix_impl_watcher.py`. Mirrors the structure of
   `pm_core/watchers/discovery_supervisor.py` (and the planned bug-fix-impl
   watcher described in pr-e3a711c, which is referenced in
   `pm_core/prompt_gen.py:1454-1485` but not yet checked in here):
   - `WATCHER_TYPE = "improvement-fix-impl"`
   - `DISPLAY_NAME = "Improvement-Fix Implementation Watcher"`
   - `WINDOW_NAME = "improvement-fix-impl"`
   - `DEFAULT_INTERVAL = 1800` (30 min — UX is taste-driven, longer than
     bug-fix cadence; see Edge Cases for rationale).
   - `VERDICTS = ("READY", "INPUT_REQUIRED")`, `KEYWORDS` likewise.
   - Constructor accepts `pm_root`, `meta_pm_root`, `state` like
     `DiscoverySupervisorWatcher`.
   - Implements `generate_prompt`, `build_launch_cmd`, `parse_verdict` with
     the same shape as discovery_supervisor.

2. **New prompt generator** `generate_improvement_fix_impl_prompt(data, …)` in
   `pm_core/prompt_gen.py`. Mirrors `generate_discovery_supervisor_prompt`
   (lines 832-973) with the following per-tick logic:
   - Inventory pending PRs in `plan=ux` via `pm pr list --plan ux`.
   - Cross-reference the work log at `<meta_pm_root>/watchers/improvement-fix-impl.log`
     to see what was last advanced.
   - Choose the best candidate this tick (taste-driven prioritization;
     see Implicit Requirements).
   - Run `pm pr auto-sequence <id>` and surface the resulting status line.
   - On `ready_to_merge` (QA PASS): **do not merge**. Log it as
     "held for human taste check" and move on. The PR's status
     remains as auto-sequence left it.
   - On `paused: input_required (...)` from auto-sequence: log and skip
     (the inner loop is already paused; do not escalate to
     INPUT_REQUIRED at the watcher level — same convention as the
     auto-start watcher in `prompt_gen.py:720-756`).
   - Append a one-line work-log entry with ISO timestamp, then emit
     `READY` or `INPUT_REQUIRED`.

3. **Registry** in `pm_core/watchers/__init__.py`: add
   `ImprovementFixImplWatcher` import and entry in `WATCHER_REGISTRY`.

4. **CLI dispatch** in `pm_core/cli/watcher.py:_create_watcher_window`
   (lines 251-263): branch on `watcher_type == "improvement-fix-impl"`
   to call the new prompt generator. Update `watcher_start` docstring
   list of available types.

5. **Work log path**: `pm/watchers/improvement-fix-impl.log` (relative
   to project root). The discovery watcher review prompt
   (`generate_watcher_review_prompt`, prompt_gen.py:1455) already
   references this exact path; this spec consumes that contract.

## Implicit Requirements

- **Taste-shaped prioritization** must be expressed as guidance in the
  prompt — there is no priority field on PRs (per the task's
  "no-priority-field pattern as pr-e3a711c"). The prompt instructs
  Claude to prefer:
  - PRs whose related code was touched recently (`git log`),
  - PRs whose notes contain user feedback signals (e.g., "user reported"),
  - PRs whose original filing contains confidence/clarity signals.
  - Avoid PRs whose dependencies are not all merged.
- **Subprocess per tick**: `BaseWatcher.run_iteration` already spawns a
  Claude subprocess via `build_launch_cmd`, so this is inherited
  automatically by mirroring `DiscoverySupervisorWatcher.build_launch_cmd`.
- **Notes injection**: `notes.notes_for_prompt(root, "watcher")`
  surfaces both the General/Local block and the prompt-type-specific
  Watcher block. Reuse the same call as the discovery prompt — user
  guidance for all three watchers shares the `Watcher` notes section.
- **No status field for "ready-for-merge"**: looking at
  `pm pr auto-sequence` (`pm_core/cli/pr.py:2814-2818`), QA PASS yields
  the textual status `ready_to_merge` but the PR's `status` field stays
  at `qa`. Therefore "advance to ready-for-merge and held" is satisfied
  by simply NOT invoking `pm pr merge` — there is nothing else to flip.
  (Confirmed: bug-fix watcher would call `pm pr merge` here; the
  improvement-fix watcher must skip that call.)
- **Window kill / recreate**: handled by
  `_create_watcher_window` already; nothing watcher-specific needed.

## Ambiguities

- **Cadence**: task says "longer than the bug-fix watcher". Bug-fix
  watcher's cadence is not in this branch; discovery is 1800s. I picked
  1800s for improvement-fix as a reasonable default — UX work is
  taste-driven and the bottleneck is the human merge throttle, so
  ticking faster than 30 minutes wastes Claude time. If pr-e3a711c
  lands with a faster bug-fix cadence (e.g., 600s), this can be raised
  later without code shape changes.
- **"ready-for-review" vs "ready-for-merge"**: task description says
  "After QA PASS, mark ready-for-review and stop". Reading in context
  with the rest of the description ("PRs that PASS QA are advanced to
  ready-for-merge and held for a human taste check"), I read
  "ready-for-review" as a typo for "ready-for-merge". The spec follows
  the consistent "ready-for-merge / human taste check / do not merge"
  framing, which matches the natural endpoint of `pm pr auto-sequence`.
- **Where the human merges from**: out of scope for this watcher. The
  watcher's responsibility ends when auto-sequence returns
  `ready_to_merge`. The TUI / human cadence handles the merge.

## Edge Cases

- **No pending UX PRs**: tick logs "no candidates" and emits READY.
- **Candidate has unmerged dependencies**: skip and log; pick the next.
- **Candidate is already in_review/qa**: just call auto-sequence on
  it — auto-sequence is idempotent (`pm_core/cli/pr.py:2696-2705`).
  This is the normal advancement path.
- **Multiple candidates at once**: advance only one PR per tick to
  keep the tick short and reduce coordination load. Parallelism is
  not a requirement.
- **Auto-sequence emits an unknown status**: log the raw line and
  emit READY (do not block the loop on a parsing failure).
- **TUI breadcrumb resume**: handled by existing
  `tui/auto_start.py:240-254` which iterates over
  `data.get("watchers", [])` and starts each by `type`. No code change
  needed there once the registry knows about the new type.
- **Discovery review prompt already references the work log path**
  (`prompt_gen.py:1455`): consistent with this spec.
