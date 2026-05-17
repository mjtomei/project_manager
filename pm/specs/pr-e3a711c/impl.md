# Spec: Bug-fix implementation watcher (pr-e3a711c)

## Requirements

1. **New watcher class** `BugFixImplWatcher` in `pm_core/watchers/bug_fix_impl_watcher.py`,
   subclass of `BaseWatcher` mirroring `auto_start_watcher.py` and
   `discovery_supervisor.py`. Class attrs:
   - `WATCHER_TYPE = "bug-fix-impl"`
   - `DISPLAY_NAME = "Bug-Fix Implementation Watcher"`
   - `WINDOW_NAME = "bug-fix-impl"`
   - `DEFAULT_INTERVAL = 300` (5 min — bug fixes need reasonably frequent ticks
     but each tick spawns multiple subprocesses; tighter than discovery's 30 min)
   - `VERDICTS = KEYWORDS = ("READY", "INPUT_REQUIRED")`
   - Implements `generate_prompt`, `build_launch_cmd`, `parse_verdict`.

2. **New prompt generator** `generate_bug_fix_impl_prompt(data, session_name,
   iteration, loop_id, meta_pm_root)` in `pm_core/prompt_gen.py`. The prompt
   instructs the Claude tick to:
   - Read recent entries of `<meta_pm_root>/watchers/bug-fix-impl.log`
   - Run `pm pr list --plan bugs` to inventory bug PRs
   - Count in-flight (status in {`in_progress`, `in_review`, `qa`}); if ≥ 2,
     do nothing this tick.
   - If under cap, score pending bug PRs by severity (description signals),
     recurrence (work-log mentions), age. Pick best one.
   - Run `pm pr auto-sequence <id>` for the chosen PR (uses pr-e58459b
     command at `pm_core/cli/pr.py:2692`).
   - For each in-flight bug PR, run `pm pr auto-sequence <id>` to advance.
     If the line says `ready_to_merge` or `ready_to_merge (skip_qa)`, run
     `pm pr merge <id>` (auto-merge — distinguishes from improvement-fix
     watcher which would not auto-merge).
   - Detect stuck PRs (e.g. paused: input_required, repeated NEEDS_WORK
     across iterations) → emit `INPUT_REQUIRED` if it requires human triage,
     or note in log otherwise.
   - Append a one-line work-log entry at the end of each tick.
   - Emits `READY` or `INPUT_REQUIRED`.
   - Includes `tui_section()`, `notes_for_prompt(root, "watcher")`
     (General + Watcher specific blocks).

3. **Registry update** in `pm_core/watchers/__init__.py` adds
   `BugFixImplWatcher` to `WATCHER_REGISTRY` so `pm watcher start bug-fix-impl`
   and `pm watcher list` discover it.

4. **CLI plumbing** in `pm_core/cli/watcher.py`:
   - Update `_create_watcher_window`'s prompt-selection branch to call
     `generate_bug_fix_impl_prompt` when `watcher_type == "bug-fix-impl"`.
   - Update the `start` command's docstring to mention the new type.

5. **Work log** at `pm/watchers/bug-fix-impl.log` (relative to project root).
   Created lazily by the prompt's `mkdir -p` + `touch` step.

## Implicit Requirements

- The watcher must not depend on a "pool" config — `plan=bugs` is the pool.
  Filtering is via `pm pr list --plan bugs`.
- Concurrency cap default = 2 in-flight bug PRs (mentioned by description).
  Hardcoded into the prompt; not configurable via project.yaml in this PR.
- `pm pr auto-sequence` is idempotent and advances by one phase per
  invocation, so the watcher invokes it on each in-flight PR every tick.
- The watcher sub-process must inherit `--watcher-type bug-fix-impl` flag
  through `build_launch_cmd` so `_create_watcher_window` picks the right
  prompt generator.
- `parse_verdict` follows the same scan-from-end-of-output pattern as the
  other two watchers, defaulting to `READY` if no verdict is found.
- Auto-merge: prompt instructs `pm pr merge <id>` only on `ready_to_merge`
  status (verbatim line from `auto-sequence`). Skip-qa case
  (`ready_to_merge (skip_qa)`) also triggers merge.

## Ambiguities (resolved)

- **Stuck-PR detection threshold**: prompt-defined heuristic — escalate via
  `INPUT_REQUIRED` after 3 consecutive NEEDS_WORK iterations on the same
  bug PR (visible from log); otherwise just note in log.
- **Concurrency cap location**: hardcoded constant `2` in the prompt body
  for now — no project.yaml field. The Watcher notes section can override
  the cap with user guidance.
- **Auto-merge command**: use `pm pr merge <id>` (no `--background`
  needed; the watcher tick is short and merge is fast). If merge needs
  conflict resolution it will surface as a follow-up tick.
- **Default interval**: 5 minutes. Discovery uses 30 min (low cadence,
  long-running tests); auto-start uses 2 min (active monitoring); bug-fix
  impl is in between — tick should be frequent enough to keep auto-sequence
  flowing on chosen PRs but not so frequent it spawns redundant work.

## Edge Cases

- No pending bug PRs and no in-flight: tick does nothing, emits READY,
  logs "idle: no work this tick".
- Cap reached: tick advances in-flight PRs via `auto-sequence` but does
  not pick a new one.
- `pm pr list --plan bugs` returns zero rows: watcher is a no-op until a
  bug PR is filed.
- Bug PR with `paused: input_required (review|qa)`: surfaced via log,
  watcher emits READY (the loop pane already paused that branch — same
  policy as auto-start watcher).
- `auto-sequence` returns `ready_to_merge`: watcher invokes `pm pr merge`,
  expects `merged` on next tick's `pm pr list` output.
- Repeated reproduce-step failures (from pr-30588a7's bug-fix flow):
  detected via review-loop transcript verdicts in
  `transcripts/auto-sequence/<pr-id>/review-*.jsonl`. Prompt instructs
  reading the log/transcript directory if multiple NEEDS_WORK seen.
