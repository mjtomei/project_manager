# QA Spec: Add running tasks pane to TUI with window switching and grouping

## 1. Requirements

### 1.1 Tasks Pane Display
- Pressing `T` in the TUI toggles between the tasks pane and the normal tech-tree view.
- The tasks pane lists all tmux windows in the current session (excluding the `main` window) grouped by type in this order: Implementation → Review → QA → Watcher → Other.
- Each group header shows `GroupName (count)` in bold underline, followed by a divider line.
- Each task entry shows: selection indicator (`▶` if selected, else blank), expand/collapse arrow (`▸`/`▼` for multi-window, blank otherwise), PR display ID and title (truncated to fit width), then status/loop markers.
- The "watcher" window appears in the Watcher group.
- Implementation windows (`#128`, `pr-abc`) appear in the Implementation group.
- Review/merge windows appear in the Review group.
- QA main windows appear in the QA group.
- QA scenario windows (`qa-#128-s1`) are sub-windows of the QA entry, not separate entries.
- Status markers shown: PR status icon, review loop marker (spinner + iteration + verdict), QA loop marker, sub-window count `+N` when collapsed.
- Running watcher shows spinner + "active"; input-required watcher shows "INPUT_REQ".
- Empty pane (no windows) shows a friendly "No running tasks" message with hints.
- Footer always shows: `Enter=switch  Space=expand  T=back`.

### 1.2 Navigation
- `j` / `↓`: move selection to next task (skips headers).
- `k` / `↑`: move selection to previous task (skips headers).
- `J`: jump to first item in the next group.
- `K`: jump to first item in the previous group.
- Selection wraps: j at last item stays at last; k at first item stays at first.
- Scrolling: selected item always scrolls into view.

### 1.3 Expand/Collapse of Multi-Window Tasks
- `Space` or `→` / `l`: toggle expand/collapse on the selected entry if it has sub-windows.
- `←` / `h`: collapse the selected entry (no-op if already collapsed or no sub-windows); resets selection to the parent entry.
- Expanding reveals sub-window rows (indented, `└ scenario N` label).
- Collapsing hides sub-window rows.
- Expand/collapse state is preserved across polls (page does not reset to collapsed on refresh).

### 1.4 Window Switching
- `Enter` on a main or sub entry fires `TaskWindowSwitch` which calls `tmux select-window` on the correct session.
- Uses `current_or_base_session` to resolve grouped sessions.
- Success: log message "Switched to '<name>'"; failure: "Window '<name>' not found".

### 1.5 PR Actions from Tasks Pane
- When tasks pane is active, `_get_active_pr_id()` returns the PR ID from the selected task entry.
- The following actions work: `s` (start PR), `S` (start PR companion), `d` (done/review), `g` (merge), `G` (merge companion), `t` (start QA), `c` (launch Claude).
- Actions not in the allowed set are blocked (logged as "not supported") when tasks view is visible.
- Review loop keybindings (`zz d`, `zzz d`) also respect `_get_active_pr_id()`.

### 1.6 Mobile Mode Integration
- When terminal width drops below `MOBILE_WIDTH_THRESHOLD` (120 cols), the TUI automatically switches to the tasks pane.
- The previously-active view (normal / plans / qa) is saved in `_pre_mobile_view`.
- When width is restored to ≥ 120 cols, the previously-active view is restored.
- Mobile transition fires both on initial mount (`_check_mobile_transition` in `on_mount`) and on resize.
- Entering mobile mode while already in tasks pane is a no-op (does not overwrite `_pre_mobile_view`).

### 1.7 Polling & Live Updates
- Tasks pane polls every 2 seconds while visible (`_start_tasks_poll` → `_poll_tasks`).
- Polling stops when navigating away from tasks pane (`_stop_tasks_poll`).
- New windows appearing in tmux should show up within ~2 s.
- Removed windows should disappear within ~2 s.
- Spinner animation advances on each poll (`advance_animation`).

### 1.8 Help Screen
- `?` while in tasks pane shows tasks-specific keybindings (Tasks Navigation section first, then PR Actions section).
- `?` from the main tree view shows `T=Toggle running tasks` in the View section.

### 1.9 View Exclusivity
- Exactly one of: tree, guide, plans, qa, tasks is visible at any time.
- Switching from tasks to any other view hides tasks container and stops the poll timer.
- Switching to any other view from any view correctly sets `_tasks_visible = False`.

## 2. Setup

Follow the `tui-manual-test.md` instruction:

1. Install pm into a venv from the PR branch:
   ```
   python3 -m venv /tmp/pm-venv && source /tmp/pm-venv/bin/activate
   pip install -e /home/mjtomei/project_manager
   ```
2. Create a throwaway project:
   ```
   TEST_DIR=<workdir>/pm-test-tasks-$(date +%s)
   mkdir -p "$TEST_DIR" && cd "$TEST_DIR"
   git init
   pm init --backend local --no-import
   pm pr add "Add login feature"
   pm pr add "Fix database migration"
   pm pr add "Refactor auth module"
   ```
3. Start the session:
   ```
   cd "$TEST_DIR" && pm session 2>/dev/null || true
   ```
4. Note the session name (printed by `pm session` or visible in `tmux ls`).
5. To simulate tasks running: manually create named windows in the session using
   `tmux new-window -t <session> -n "review-#1"` etc. (or use `pm start` on a PR).

## 3. Edge Cases

- **Empty pane**: No tmux windows other than `main` → "No running tasks." message displayed.
- **Watcher window present**: Named `watcher` → appears in Watcher group with spinner when `watcher_infos` indicates running.
- **Input-required watcher**: `watcher_infos` returns `input_required=True` → shows "INPUT_REQ" marker.
- **Multiple QA scenario windows**: `qa-#128-s1`, `qa-#128-s2`, `qa-#128-s3` → collapsed to one QA entry with `+3` marker; expand shows `└ scenario 1/2/3`.
- **Unknown window names**: Windows not matching any pattern → "Other" group.
- **Poll preserves expansion**: Expand an entry, wait 2–4 s, verify it stays expanded.
- **Selection clamping**: If selected item is removed by a poll, selection jumps to the first selectable item.
- **Group jump at boundary**: `J` at last group stays; `K` at first group stays.
- **Mobile mode while in plans/qa**: Entering mobile mode from plans/qa saves that view and restores it on exit.
- **Rapid T toggle**: T → T quickly should not leave the poll timer running or leak state.
- **No PR match**: Window name `review-#999` where PR #999 is not in project data → entry shows display ID but no title.
- **Width exactly at threshold (120)**: Should be treated as non-mobile (condition is `< MOBILE_WIDTH_THRESHOLD`).
- **Tasks pane while guide is active**: Guide mode sets `_tasks_visible = False`; T should have no effect (guide takes precedence).

## 4. Pass/Fail Criteria

**PASS** for a scenario if:
- All described behaviors are observable in the TUI as specified.
- No crashes, tracebacks, or hung timers observed.
- Log messages (via `pm tui view` or tmux capture) confirm expected actions.

**FAIL** if:
- Any described behavior is absent or incorrect (wrong group, missing marker, wrong window switched to).
- A crash or unhandled exception occurs.
- Poll timer continues running after navigating away (check for CPU usage or repeated log entries).
- Mobile transition does not fire or restores wrong view.
- PR actions use wrong PR ID (tree selection instead of tasks pane selection).

**INPUT_REQUIRED** if:
- The behavior cannot be fully verified without real tmux windows or a real running PR process.

## 5. Ambiguities

| Ambiguity | Resolution |
|---|---|
| Does mobile mode activate at exactly 120 or below 120? | `< MOBILE_WIDTH_THRESHOLD` (strict less-than), so 120 is non-mobile. |
| Which PR actions are allowed in tasks view? | Code allows: `start_pr`, `start_pr_companion`, `done_pr`, `merge_pr`, `merge_pr_companion`, `start_qa_on_pr`, `launch_claude`. |
| Does `T` work while guide mode is active? | `toggle_tasks` calls `_show_tasks_view` which sets `_current_guide_step = None`. Guide is exited. Treat as allowed (per code). |
| What happens if tasks view is entered while plans/qa poll is active? | `_show_tasks_view` calls `_show_tasks_view` directly; other views' polls are stopped separately in `action_toggle_tasks` path via `_show_tasks_view`. |
| Does `T` (toggle) work as a prefix for watcher chord (w → wf/ww/ws)? | `T` is the tasks toggle, `w` is the watcher prefix. No conflict. `t` (lowercase) is start QA. |

## 6. Mocks

### tmux (partially mocked)
- **Contract**: Simulate `list_windows` returning a controlled set of named windows. Do not mock `select_window` — let it call real tmux (or verify via log message). If no real tmux session exists, mock `select_window` to always return `True`.
- **Scripted responses**: Initial: `[{id: "@1", index: "0", name: "main"}, {id: "@2", index: "1", name: "#128"}, {id: "@3", index: "2", name: "review-#128"}, {id: "@4", index: "3", name: "qa-#128"}, {id: "@5", index: "4", name: "qa-#128-s1"}, {id: "@6", index: "5", name: "qa-#128-s2"}, {id: "@7", index: "6", name: "watcher"}]`.
- **Remains unmocked**: The actual tmux session used for testing (scenario agents should use `pm session` to create a real session and manually add windows to it, rather than mocking the tmux calls in code).

### watcher_infos
- **Contract**: Simulate `watcher_manager.list_watchers()` returning watcher status.
- **Scripted responses**: `[{"window_name": "watcher", "running": True, "input_required": False}]` for active watcher; `[{"window_name": "watcher", "running": True, "input_required": True}]` for input-required watcher.
- **Remains unmocked**: The actual watcher process is not required for display testing; inject fake data via the pane's `update_tasks` call if testing display in isolation.
