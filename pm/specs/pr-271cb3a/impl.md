# Spec — pr-271cb3a Discovery supervisor watcher

## Requirements (grounded)

1. **New `DiscoverySupervisorWatcher` class** in `pm_core/watchers/discovery_supervisor.py`,
   subclassing `pm_core.watcher_base.BaseWatcher` (mirror of
   `pm_core/watchers/auto_start_watcher.py`). Must define
   - `WATCHER_TYPE = "discovery"`
   - `DISPLAY_NAME = "Discovery Supervisor"`
   - `WINDOW_NAME = "discovery"`
   - `DEFAULT_INTERVAL = 1800` (30 min, longer than auto-start's 120s)
   - `VERDICTS = ("READY", "INPUT_REQUIRED")`
   - Implementations of `generate_prompt`, `build_launch_cmd`, `parse_verdict`.

2. **Register** the new watcher in `pm_core/watchers/__init__.py` (`WATCHER_REGISTRY`)
   so `pm watcher start discovery` and `pm watcher list` discover it.

3. **New `generate_discovery_supervisor_prompt()`** in `pm_core/prompt_gen.py`,
   paralleling `generate_watcher_prompt()` (lines 579-829). Must:
   - Accept `data, session_name, iteration, loop_id, meta_pm_root` args.
   - Pull general+watcher notes via `notes.notes_for_prompt(root, "watcher")`.
   - Render the per-tick instructions (see (5)).

4. **Wire CLI**: extend `pm_core/cli/watcher.py::_create_watcher_window` (or refactor)
   so `pm watcher --iteration N --watcher-type discovery ...` launches the discovery
   tmux window. Also extend `_create_watcher_window` to dispatch on watcher type when
   building the prompt and choosing the window name. The discovery watcher's
   `build_launch_cmd` will pass `--watcher-type discovery`.

5. **Per-tick prompt content**: instruct Claude to
   - Read `pm/watchers/discovery.log` for recent context (recent runs, recent filings,
     recent dedup decisions).
   - List regression tests via `ls pm/qa/regression/*.md` (mirrors
     `qa_instructions.list_all()`), and decide which (if any) is due to run.
   - Check if any regression launched on the previous tick is still in flight by
     inspecting the watcher's tmux window for live qa-item panes. (`tmux list-panes`)
   - If a test is due and no in-flight conflicts, launch it via
     `pm qa launch regression:<id> --target-window discovery` (new CLI shim — see (6)).
   - When prior in-flight tests have completed, scan recent PRs in `plan=bugs` and
     `plan=ux` (`pm pr list --plan bugs|ux --json`) for filings that may be duplicates;
     dedup by title/description, merging via `pm pr note <id>` or close-and-merge.
   - Append a one-line work-log entry to `pm/watchers/discovery.log`.
   - Emit `READY` (continue watching) or `INPUT_REQUIRED` (ambiguous dedup, missing
     plan, etc.).

6. **New CLI shim `pm qa launch <item_id> [--target-window NAME]`** in
   `pm_core/cli/qa.py`. The existing `launch_qa_item()` requires a TUI `app` instance;
   the watcher Claude runs in its own tmux window outside the TUI process. The shim
   reuses `qa_instructions.get_instruction()`, `claude_launcher.build_claude_shell_cmd()`,
   and `tmux.new_window_get_pane()` to spawn the regression QA Claude in the named
   window (or current window if omitted). Mirrors `_REGRESSION_FILING_ADDENDUM` for
   regression-category items. This is the headless equivalent of `launch_qa_item`.

7. **Work-log file** at `pm/watchers/discovery.log`. Created lazily by the
   tick prompt's first append; the directory `pm/watchers/` should be created if
   missing (the supervisor prompt or the watcher class can `mkdir -p`).

8. **Reuses framework primitives** (no changes to `BaseWatcher`):
   - Subprocess invocation per tick via `BaseWatcher._run_iteration` →
     `build_launch_cmd` → `pm watcher --iteration ...`.
   - READY / INPUT_REQUIRED verdict extraction via `loop_shared.match_verdict`.
   - Notes injection via `notes.notes_for_prompt(root, "watcher")`.

## Implicit requirements

- `_create_watcher_window` currently hard-codes `AutoStartWatcher.WINDOW_NAME` and
  `generate_watcher_prompt`. Must be generalized to dispatch on `--watcher-type`.
- The discovery watcher's `build_launch_cmd` must include `--watcher-type discovery`
  flag so the wrapper routes to the right window/prompt.
- Need a `--watcher-type` Click option on `watcher_cmd` (currently absent).
- The model-config session type `"watcher"` (`pm_core/cli/model.py` line 7) should
  apply to discovery as well; no change required.
- The discovery supervisor uses the `Watcher` notes section per the task; no new
  notes section is added.

## Ambiguities (resolved)

- **Window name**: chose `"discovery"` (not `"watcher"`) so it can coexist with
  the auto-start watcher window.
- **Default interval**: 30 min (1800s) per task description.
- **CLI surface for launching regressions from the watcher**: added
  `pm qa launch <item_id>` shim (see (6)) since `launch_qa_item` requires the TUI
  app object.
- **Log location**: `pm/watchers/discovery.log` (under the project's pm dir).

## Edge cases

- Tick fires while a previously-launched regression Claude is still running in the
  discovery window. Resolution: prompt instructs Claude to detect via
  `tmux list-panes -t <session>:discovery` and skip launching new ones until the
  old pane is gone.
- Watcher window is named `discovery` but the launched qa-item pane lives in the
  same window; this is intentional per pr-97ddabf (target_window param).
- `pm/watchers/` directory missing on first run — created by the launch shim or
  prompt's `mkdir -p`.
- Notes section may be absent (`FileNotFoundError`); handled like in
  `generate_watcher_prompt`.
