# Refactor for code quality

Improve code quality across the pm tool by splitting oversized files, eliminating
duplicate code, extracting shared abstractions, and expanding both unit and
Claude-based TUI test coverage. The cluster/ subpackage is out of scope.

## Scope

- **Split large files**: cli.py (4,603 lines), tui/app.py (2,230 lines),
  tech_tree.py (901 lines), pane_layout.py (614 lines)
- **Deduplicate code**: `_extract_field()`, `_find_git_root()`, GitHub repo name
  extraction, TUI Message classes
- **Expand unit tests**: Target modules with <50% coverage (graph.py 19%,
  detail_panel.py 15%, review.py 14%, notes.py 48%, git_ops.py 47%,
  tmux.py 32%, claude_launcher.py 34%)
- **Add Claude-based TUI tests**: Cover untested functionality (detail panel
  content, status filter cycling, merged toggle, sync/refresh from TUI,
  meta session launch)
- **Out of scope**: cluster/ subpackage, bridge.py/bridge_client.py, wrapper.py

## Goals

1. No file in pm_core/ exceeds ~500 lines (excluding tui_tests.py which is data)
2. Zero duplicated utility functions across modules
3. Shared abstractions for common TUI patterns (Message classes)
4. Unit test coverage improves from 25% to ≥50% on targeted modules
5. Claude-based TUI tests cover all major TUI features

## Key design decisions

### cli.py split strategy

Convert `pm_core/cli.py` (4,603 lines) into a `pm_core/cli/` subpackage. Split
by Click command group into separate modules, each registering its commands on
the main `cli` group. Shared helpers go into `cli/helpers.py`.

| New file | Contents | ~Lines |
|----------|----------|--------|
| `cli/__init__.py` | `cli` group, `main`, `init`, `push`, `set`, `_check`, `help`, `getting-started`, `which`, `prompt`, plus imports of all submodules to trigger registration. Re-exports `cli` and `main` for backward compatibility (`from pm_core.cli import cli`). | ~530 |
| `cli/pr.py` | `pr` group: add, edit, select, cd, list, graph, ready, start, done, sync, sync-github, import-github, cleanup, close. Includes `_launch_review_window` helper added for code review pane during `pr done`. | ~940 |
| `cli/plan.py` | `plan` group: add, list, breakdown, review, deps, load, fixes, fix, import, `_run_plan_import`, `_import_github_prs` | ~775 |
| `cli/session.py` | `session` group, `_register_tmux_bindings`, `_session_start`, internal pane/window commands (`_pane-exited`, `_pane-closed`, `_pane-opened`, `_pane-switch`, `_window-resized`, `rebalance`), session registry commands (`_save-session`, `_clear-session`). Pane-exited now passes pane_id and window to multi-window registry. | ~560 |
| `cli/tui.py` | `tui` group: view, history, send, keys, clear-history, capture, frames, clear-frames, test, plus frame/history helpers, internal `_tui` launcher | ~570 |
| `cli/guide.py` | `guide` group, `_run_guide`, `notes` command | ~300 |
| `cli/meta.py` | `meta` command, `_detect_pm_install`, `_build_meta_prompt`, `_meta_workdir` | ~335 |
| `cli/cluster.py` | `cluster` group: auto, explore | ~220 |
| `cli/helpers.py` | `HelpGroup`, `load_and_sync`, `save_and_push`, `trigger_tui_refresh`, `_pr_id_sort_key`, `_pr_display_id`, `_resolve_pr_id`, `_infer_pr_id`, `_workdirs_dir`, `_resolve_repo_id`, `state_root` | ~250 |

Each `cli/*.py` submodule imports `cli` from `pm_core.cli` (the `__init__.py`)
and registers its group/commands. The `__init__.py` imports all submodules at
the bottom to trigger registration. External imports like
`from pm_core.cli import cli` and `from pm_core.cli import main` continue to
work because `__init__.py` defines and exports both names.

### tui/app.py split strategy

Extract modal screens, helper classes, and pane management into separate files.
app.py is now 2,230 lines (grown from 1,713 due to shared-session, assist,
multi-window registry healing, z-modifier fresh restart, and sticky logging):

| New file | Contents | ~Lines |
|----------|----------|--------|
| `tui/app.py` (trimmed) | `ProjectManagerApp` core class, z-modifier key handling (`_consume_z`), sticky log messages | ~950 |
| `tui/screens.py` | `WelcomeScreen`, `ConnectScreen`, `HelpScreen`, `PlanPickerScreen`, `PlanAddScreen` | ~500 |
| `tui/widgets.py` | `TreeScroll`, `StatusBar`, `LogLine` | ~100 |
| `tui/pane_ops.py` | Pane launch/kill/rebalance/zoom (with `fresh` param for pane recreation), `_heal_registry` for multi-window registry repair | ~560 |
| `tui/_shell.py` | Shell command helpers (`_run_shell`, `_run_shell_async`) extracted from app.py top-level | ~60 |

### tech_tree.py split strategy

Extract the layout algorithm and rendering logic:

| New file | Contents | ~Lines |
|----------|----------|--------|
| `tui/tech_tree.py` (trimmed) | `TechTree` widget, message classes, keyboard handling | ~570 |
| `tui/tree_layout.py` | Tree layout algorithm (node positioning, column assignment, edge routing) | ~330 |

### pane_layout.py split strategy

This file is now 614 lines after the multi-window pane registry refactor
(registry format changed from flat `panes` list to per-window `windows` dict).
Extract the registry I/O into its own module:

| New file | Contents | ~Lines |
|----------|----------|--------|
| `pane_layout.py` (trimmed) | Layout algorithm (`_layout_node`, `compute_layout`, `_checksum`), `rebalance`, mobile detection, lifecycle handlers (`handle_pane_exited`, `handle_any_pane_closed`, `handle_pane_opened`, `check_user_modified`) | ~340 |
| `pane_registry.py` | Registry CRUD: `registry_dir`, `registry_path`, `load_registry` (with old→new format migration), `save_registry`, `register_pane`, `unregister_pane`, `kill_and_unregister`, `find_live_pane_by_role` (with optional window scoping), `_get_window_data`, `_iter_all_panes`, `_reconcile_registry` (per-window dead pane cleanup) | ~280 |

### Code deduplication

1. **`_extract_field()`** — duplicated identically in `plan_parser.py` and
   `tui/detail_panel.py`. Move to `plan_parser.py` as the single source,
   import in `detail_panel.py`.

2. **`_find_git_root()`** — duplicated in `wrapper.py` and `paths.py`.
   Consolidate into `git_ops.py` (natural home for git operations), update
   both callers to import from there.

3. **GitHub repo name extraction** — duplicated in `wrapper.py` and `paths.py`.
   Consolidate into `git_ops.py`, update callers.

4. **TUI Message class pattern** — `PlanSelected`/`PlanActivated`,
   `TestSelected`/`TestActivated`, `PRSelected`/`PRActivated` all follow the
   same boilerplate. Create a generic factory or base in `tui/__init__.py`:
   ```python
   def item_message(name: str, field: str) -> type[Message]:
       """Create a Selected/Activated message class with a single ID field."""
   ```
   Replace the boilerplate in all three widget files.

### Unit test additions

Add tests targeting modules with low coverage. Focus on pure logic that can be
tested without subprocess/tmux mocking:

- **graph.py** (19%) — `build_adjacency`, `topological_sort`, `ready_prs`, `blocked_prs`, `compute_layers`
- **review.py** (14%) — `build_fix_prompt` output format, `review_step` with mocked subprocess, `parse_review_file`
- **notes.py** (48%) — notes file resolution, splash text generation
- **detail_panel.py** (15%) — `_pr_display_id`, plan section extraction (after dedup fix)
- **git_ops.py** (47%) — `run_git` with mocked subprocess, branch name parsing

### Claude-based TUI test additions

New tests to add to `tui_tests.py`, following the existing format with Background,
Available Tools, Test Procedure, Expected Behavior, and Reporting sections:

1. **Detail Panel Content Test** — Verify the detail panel shows correct PR info
   (title, status, branch, deps, plan context) and updates when navigating
   between PRs. Tests `detail_panel.py` rendering logic.

2. **Status Filter & Merged Toggle Test** — Test the F key (cycle status filters:
   all → pending → in_progress → done) and X key (toggle merged PR visibility).
   Verify the tech tree updates to show only matching PRs after each filter change.

3. **Sync Refresh Test** — Test that pressing 'r' triggers a sync, verify the
   log line updates with sync results, and confirm PR statuses update in the
   tree if any PRs were merged upstream.

4. **Meta Session Launch Test** — Test the 'm' key to launch a meta session.
   Verify a new pane is created with the correct role, the meta prompt is
   passed to Claude, and the pane registry is updated.

5. **TUI Log Viewer Test** — Test the 'L' key to open the log file in a pane.
   Verify the log pane shows recent TUI activity, test scrolling, and verify
   the pane can be killed and relaunched.

## Constraints

- All existing tests must continue to pass after each PR
- No behavioral changes — this is purely structural refactoring + test additions
- Import paths from `pm_core.cli` used externally (e.g., `from pm_core.cli import cli`,
  `from pm_core.cli import main`) must continue to work — `cli/__init__.py` re-exports both
- TUI test prompts must follow the existing format in `tui_tests.py`
- Each PR should be independently mergeable (no PR depends on all others)

## PRs

### PR: Convert cli.py to cli/ package and extract shared helpers
- **description**: Convert the monolithic pm_core/cli.py (4,603 lines) into a pm_core/cli/ subpackage. Create cli/__init__.py with the `cli` Click group, `main` entry point, and the core commands (init, push, set, help, getting-started, which, prompt) — these stay in __init__.py. Move HelpGroup, load_and_sync, save_and_push, trigger_tui_refresh, _pr_id_sort_key, _pr_display_id, _resolve_pr_id, _infer_pr_id, _workdirs_dir, _resolve_repo_id, and state_root into cli/helpers.py. The __init__.py re-exports `cli` and `main` at module level so that `from pm_core.cli import cli` and `from pm_core.cli import main` continue to work (used by tests, __main__.py, and wrapper.py). This is the foundation for the next PR which splits all command groups into submodules. See `pm/plans/plan-e4fa5cb.md` for the overall split strategy and target line counts.
- **tests**: Run `pytest tests/` — all existing tests pass. Verify `from pm_core.cli import cli` and `from pm_core.cli import main` still work. Add unit tests for _resolve_pr_id (valid/invalid IDs, prefix matching) and _infer_pr_id (active PR, branch-based inference) in tests/test_pr_utils.py or a new test file.
- **files**: pm_core/cli.py (delete), pm_core/cli/__init__.py (create — cli group, main, core commands, plus all remaining command groups temporarily until the next PR splits them out), pm_core/cli/helpers.py (create — ~250 lines of shared utilities)
- **depends_on**:

---

### PR: Split all CLI command groups into cli/ submodules
- **description**: Complete the cli/ package split by moving all remaining command groups out of cli/__init__.py into dedicated submodules. Each submodule imports `cli` from `pm_core.cli` and registers its commands; the __init__.py imports all submodules at the bottom to trigger registration. Submodules to create: (1) cli/pr.py (~940 lines) — `pr` group: add, edit, select, cd, list, graph, ready, start, done, sync, sync-github, import-github, cleanup, close, plus `_launch_review_window` helper for code review pane. (2) cli/plan.py (~775 lines) — `plan` group: add, list, breakdown, review, deps, load, fixes, fix, import, plus _run_plan_import and _import_github_prs. (3) cli/session.py (~560 lines) — `session` group, `_register_tmux_bindings`, `_session_start`, internal pane/window commands (`_pane-exited`, `_pane-closed`, `_pane-opened`, `_window-resized`, `_pane-switch`, `rebalance`), session registry commands (`_save-session`, `_clear-session`). Note: pane-exited now passes pane_id and window for multi-window registry support. (4) cli/tui.py (~570 lines) — `tui` group: view, history, send, keys, clear-history, capture, frames, clear-frames, test, plus frame/history helpers and internal _tui launcher. (5) cli/guide.py (~300 lines) — guide group, _run_guide, notes command. (6) cli/meta.py (~335 lines) — meta command, _detect_pm_install, _build_meta_prompt, _meta_workdir. (7) cli/cluster.py (~220 lines) — cluster group: auto, explore. All submodules import shared helpers from `pm_core.cli.helpers`. After this PR, cli/__init__.py is trimmed to ~530 lines (init, push, set, help, getting-started, which, prompt, plus submodule imports). See `pm/plans/plan-e4fa5cb.md` for the full cli/ split strategy table.
- **tests**: Run `pytest tests/` — all existing tests pass unchanged. Key test files exercising moved code: test_pr_utils.py, test_pr_sync.py, test_bugs.py, test_plan_parser.py, test_store_validation.py, test_session_registry.py, test_pane_layout.py.
- **files**: pm_core/cli/__init__.py (modify — remove all command groups, add submodule imports at bottom), pm_core/cli/pr.py (create), pm_core/cli/plan.py (create), pm_core/cli/session.py (create), pm_core/cli/tui.py (create), pm_core/cli/guide.py (create), pm_core/cli/meta.py (create), pm_core/cli/cluster.py (create)
- **depends_on**: Convert cli.py to cli/ package and extract shared helpers

---

### PR: Split app.py into screens, widgets, and pane_ops
- **description**: Reduce tui/app.py from 2,230 lines to ~950 by extracting four categories of code into new modules: (1) tui/screens.py (~500 lines) — move WelcomeScreen, ConnectScreen, HelpScreen, PlanPickerScreen, PlanAddScreen. (2) tui/widgets.py (~100 lines) — move TreeScroll, StatusBar, LogLine. (3) tui/pane_ops.py (~560 lines) — extract pane launch (`_launch_pane` with `fresh` param for pane recreation), kill, rebalance, zoom logic, and `_heal_registry` (multi-window registry repair) from ProjectManagerApp into standalone functions. (4) tui/_shell.py (~60 lines) — extract `_run_shell` and `_run_shell_async` helpers. The app delegates to pane_ops functions, passing the app instance or necessary state as parameters. After this PR, app.py contains ProjectManagerApp core lifecycle, event handling, z-modifier key handling (`_consume_z`), and sticky log messages. See `pm/plans/plan-e4fa5cb.md` for the tui/app.py split strategy.
- **tests**: Run `pytest tests/` — all existing tests pass unchanged (including tests/test_shared_sessions.py which tests ConnectScreen, and tests/test_plans_pane.py which imports ProjectManagerApp). Add import smoke tests in tests/test_tui_imports.py verifying: all screen classes importable from tui.screens, all widget classes from tui.widgets, pane_ops functions have expected signatures, _shell helpers importable, and `from pm_core.tui.app import ProjectManagerApp` still works.
- **files**: pm_core/tui/app.py (modify — remove screen/widget/pane classes and methods, add imports), pm_core/tui/screens.py (create — ~500 lines), pm_core/tui/widgets.py (create — ~100 lines), pm_core/tui/pane_ops.py (create — ~560 lines), pm_core/tui/_shell.py (create — ~60 lines), tests/test_tui_imports.py (create)
- **depends_on**:

---

### PR: Extract tree layout and abstract TUI message factory
- **description**: Two related changes to tui/ code, combined because both modify tech_tree.py: (1) Move the tree layout algorithm (node positioning, column assignment, edge routing) from tech_tree.py into a new tui/tree_layout.py (~330 lines). TechTree widget calls layout functions and retains rendering + keyboard handling. Reduces tech_tree.py from 901 to ~570 lines. (2) Create a generic message factory function `item_message(name, field)` in tui/__init__.py that generates Selected/Activated message class pairs with a single ID field. Replace the boilerplate PlanSelected/PlanActivated in plans_pane.py, TestSelected/TestActivated in tests_pane.py, and PRSelected/PRActivated in tech_tree.py with factory-generated classes. See `pm/plans/plan-e4fa5cb.md` for the tech_tree.py split strategy and message factory design.
- **tests**: Run `pytest tests/` — existing tests (test_tech_tree_status.py) pass. Add unit tests for layout algorithm in tests/test_tree_layout.py (node positions for linear chains, fan-out graphs, diamond dependencies; edge routing avoids overlaps). Add unit tests for the message factory (correct class names, handler_name property, field accessibility).
- **files**: pm_core/tui/tech_tree.py (modify — remove layout code and message boilerplate), pm_core/tui/tree_layout.py (create — ~330 lines), pm_core/tui/__init__.py (modify — add item_message factory), pm_core/tui/plans_pane.py (modify — replace message classes), pm_core/tui/tests_pane.py (modify — replace message classes), tests/test_tree_layout.py (create)
- **depends_on**:

---

### PR: Extract pane registry I/O from pane_layout.py
- **description**: Move registry CRUD and lookup functions from pane_layout.py (now 614 lines after multi-window registry refactor) into a new pane_registry.py. Functions to move: `registry_dir`, `registry_path`, `load_registry` (includes old→new format migration), `save_registry`, `register_pane` (per-window), `unregister_pane` (searches all windows), `kill_and_unregister`, `find_live_pane_by_role` (with optional `window` scoping), `_get_window_data`, `_iter_all_panes`, `_reconcile_registry` (per-window dead pane cleanup). pane_layout.py keeps the layout algorithm (`_layout_node`, `compute_layout`, `_checksum`), `rebalance`, mobile detection, and lifecycle event handlers (`handle_pane_exited`, `handle_any_pane_closed`, `handle_pane_opened`, `check_user_modified`) which orchestrate both registry and layout operations. The lifecycle handlers import from pane_registry. Update all callers across the codebase (cli/__init__.py or cli/session.py, tui/app.py or tui/pane_ops.py — whichever exists at the time) to import from pane_registry instead. See `pm/plans/plan-e4fa5cb.md` for the pane_layout.py split strategy.
- **tests**: Run `pytest tests/` — existing tests (test_pane_layout.py, test_session_registry.py) pass. Note: test_pane_layout.py now has substantial registry tests from the multi-window refactor. Verify those still pass with the new import paths. Add tests for: register_pane creates per-window registry entries, unregister_pane removes entries across windows, find_live_pane_by_role with and without window scoping, load_registry old-format migration, load_registry handles missing file, _get_window_data creates entries on demand, _iter_all_panes yields from all windows, kill_and_unregister combines kill+cleanup. Add to test_session_registry.py or create tests/test_pane_registry.py.
- **files**: pm_core/pane_layout.py (modify — remove registry functions, ~340 lines remaining), pm_core/pane_registry.py (create — ~280 lines)
- **depends_on**:

---

### PR: Deduplicate _extract_field and consolidate git root helpers
- **description**: (1) Remove the duplicate _extract_field from tui/detail_panel.py (line 43) and import it from plan_parser.py (line 79) instead — both implementations are identical. (2) Move _find_git_root from paths.py (line 68) and wrapper.py (line 17) into git_ops.py as a single get_git_root function. (3) Move the duplicate GitHub repo name extraction from paths.py (line 87) and wrapper.py (line 31) into git_ops.py. Update all callers. See `pm/plans/plan-e4fa5cb.md` for the deduplication strategy.
- **tests**: Run `pytest tests/` — all existing tests pass. The moved functions have zero direct unit tests, so add: (1) _extract_field import from plan_parser works and returns correct results, (2) git_ops.get_git_root finds .git dir, handles missing, traverses parents, (3) git_ops.get_github_repo_name with HTTPS/SSH URLs, (4) import smoke tests confirming detail_panel.py, paths.py, and wrapper.py successfully import the shared versions. Add to existing test files or create test_dedup.py.
- **files**: pm_core/tui/detail_panel.py (modify — remove _extract_field, add import), pm_core/plan_parser.py (modify — make _extract_field public or importable), pm_core/git_ops.py (modify — add get_git_root and get_github_repo_name), pm_core/wrapper.py (modify — remove duplicates, import from git_ops), pm_core/paths.py (modify — remove duplicates, import from git_ops)
- **depends_on**:

---

### PR: Add unit tests for low-coverage modules
- **description**: Add comprehensive unit tests for the seven lowest-coverage modules to raise each above 50%. Pure logic modules (no mocking needed): graph.py (currently 19%) — test build_adjacency with empty/linear/diamond graphs, topological_sort ordering, ready_prs/blocked_prs with various dependency states, compute_layers layering. review.py (currently 14%) — test build_fix_prompt output format, review_step with mocked subprocess, parse_review_file parsing. notes.py (currently 48%) — test notes file resolution with/without pm dir, splash text generation. Modules requiring mocked subprocess: git_ops.py (currently 47%) — test run_git (success, failure, timeout), branch name parsing, remote URL extraction, and the new get_git_root/get_github_repo_name from the dedup PR. detail_panel.py (currently 15%) — test plan section extraction using _extract_field (now imported from plan_parser after the dedup PR lands) and PR display formatting. tmux.py (currently 32%) — test session/window/pane helper functions with mocked subprocess (session_exists, create_session, new_window, split_pane, get_pane_geometries, current_or_base_session). claude_launcher.py (currently 34%) — test build_claude_shell_cmd output, find_claude/find_editor with mocked shutil.which, load_session/save_session/clear_session round-trip with tmp files. This depends on the dedup PR so that detail_panel and git_ops tests target the post-dedup code. See `pm/plans/plan-e4fa5cb.md` for coverage targets.
- **tests**: New test files: tests/test_graph.py, tests/test_review.py, tests/test_notes.py, tests/test_git_ops.py, tests/test_detail_panel.py, tests/test_tmux.py, tests/test_claude_launcher.py. Run with `pytest tests/test_graph.py tests/test_review.py tests/test_notes.py tests/test_git_ops.py tests/test_detail_panel.py tests/test_tmux.py tests/test_claude_launcher.py`.
- **files**: tests/test_graph.py (create), tests/test_review.py (create), tests/test_notes.py (create), tests/test_git_ops.py (create), tests/test_detail_panel.py (create), tests/test_tmux.py (create), tests/test_claude_launcher.py (create)
- **depends_on**: Deduplicate _extract_field and consolidate git root helpers

---

### PR: Add Claude-based TUI tests for detail panel, filters, sync, meta, and log viewer
- **description**: Add five new Claude-based TUI test prompts to tui_tests.py (which currently has 13 tests including the recently added multi-window-registry and window-resize tests) following the existing format (Background, Available Tools, Test Procedure, Expected Behavior, Reporting sections): (1) Detail Panel Content Test — verify the detail panel shows correct PR info (title, status, branch, deps, plan context) and updates when navigating between PRs, (2) Status Filter & Merged Toggle Test — test F key cycles through status filters (all → pending → in_progress → done) and X key toggles merged PR visibility, verify tech tree updates accordingly, (3) Sync Refresh Test — test r key triggers sync, verify log line updates and PR statuses change if PRs were merged upstream, (4) Meta Session Launch Test — test m key launches a meta pane, verify pane registry and correct role, (5) TUI Log Viewer Test — test L key opens log pane, verify content and pane lifecycle. Register all five in the ALL_TESTS dict at the bottom of the file, bringing the total to 18 tests. The multi-window registry format is now the standard — new test fixtures should use the `{"windows": {...}}` format, not the old flat `{"panes": [...]}` format. See `pm/plans/plan-e4fa5cb.md` for test descriptions.
- **tests**: Verify with `pm tui test --list` that all 5 new tests appear (total should be 18). Run individual tests with `pm tui test <test-name>`.
- **files**: pm_core/tui_tests.py (modify — add 5 test prompt strings and register in ALL_TESTS)
- **depends_on**:

---
