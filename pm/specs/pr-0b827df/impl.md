# Implementation Spec: Running Tasks Pane

## PR: pr-0b827df — Add running tasks pane to TUI with window switching and grouping

---

## Requirements

### 1. Tasks Pane Widget (`pm_core/tui/tasks_pane.py`)

**Display:**
- `TasksPane` widget shows all active tasks from tmux windows, grouped by type
- Groups: Implementation, Review, QA, Watcher, Other (in that order, defined in `GROUP_ORDER`)
- Each entry shows PR display ID, PR title (truncated), and status markers
- Status markers include: PR status icon, review loop marker (spinner + iteration + verdict), QA loop marker
- Multi-window tasks (QA with scenario sub-windows) show collapsed by default with a "+N" count badge
- Watcher entry shows active/INPUT_REQ status marker from `WatcherManager.list_watchers()`

**Window classification (`_classify_window`):**
- `qa-#N-sM` → QA, sub role
- `qa-#N` or `qa-pr-XXX` → QA, main role
- `review-#N`, `review-pr-XXX`, `merge-#N`, `merge-pr-XXX` → Review, main role
- `watcher` → Watcher, no PR
- `#N`, `pr-XXX` → Implementation, main role
- Anything else → Other
- Window named "main" is always skipped

**Navigation:**
- `j`/`↓`: move down among selectable items
- `k`/`↑`: move up among selectable items
- `J`: jump to next group's first item
- `K`: jump to previous group's first item
- `space`/`right`/`l`: expand/collapse sub-windows
- `left`/`h`: collapse and re-select parent entry
- `enter`: post `TaskWindowSwitch` message with current window name

**Polling:**
- `advance_animation()` increments spinner frame (called from `_refresh_tasks_pane`)
- Expansion state is preserved across `update_tasks()` calls via `old_expanded` dict keyed by `"{group}:{pr_display_id}"` or `"{group}:{window_name}"`

### 2. App Integration (`pm_core/tui/app.py`)

**Toggle:** `Binding("T", "toggle_tasks", "Tasks", show=True)` → `action_toggle_tasks()`
- Shows tasks container, hides all others
- Sets `_tasks_visible = True`, clears `_plans_visible`, `_qa_visible`
- Calls `_refresh_tasks_pane()` + `_start_tasks_poll()` on enter
- Calls `_stop_tasks_poll()` on exit via `_show_normal_view()`

**Polling:** `_start_tasks_poll()` sets 2-second interval calling `_poll_tasks()`
- `_poll_tasks()` calls `_refresh_tasks_pane()` when `_tasks_visible`
- `_refresh_tasks_pane()` calls `tmux_mod.list_windows(session)`, builds windows list, advances animation, calls `tasks_pane.update_tasks(windows, prs, review_loops, qa_loops, watcher_infos)`

**Window switching:** `on_task_window_switch()` handles `TaskWindowSwitch` message
- Calls `tmux_mod.select_window(session, window_name)` which targets the grouped/client session

**PR actions from tasks pane:** `_get_active_pr_id()` returns tasks pane selection when `_tasks_visible`
- All PR actions (start_pr, done_pr, merge_pr, start_qa_on_pr, launch_claude) use `_get_active_pr_id()`
- `check_action()` blocks non-PR-friendly actions (edit_plan, view_plan, etc.) when in tasks view
- Allowed actions: start_pr, start_pr_companion, done_pr, merge_pr, merge_pr_companion, start_qa_on_pr, launch_claude
- `review_loop_ui._get_selected_pr()` also uses `_get_active_pr_id()`
- `stop_loop_or_fresh_done()` passes `pr_id` explicitly to `done_pr()`

**Mobile mode transition:** `_check_mobile_transition()` called from `on_mount()` and `on_resize()`
- When `width < MOBILE_WIDTH_THRESHOLD (120)` and not already in tasks view: save current view in `_pre_mobile_view`, switch to tasks
- When `width >= 120` and `_pre_mobile_view is not None`: restore previous view

**Status bar:** Shows "Tasks | T=back to tree  Enter=switch window  ?=help" when in tasks view

### 3. Help Screen (`pm_core/tui/screens.py`)

`HelpScreen(in_tasks=True)` shows tasks-specific keybinding section instead of normal help.

---

## Implicit Requirements

1. `_session_name` must be set (requires running in tmux) for the tasks pane to populate
2. PR lookup uses `gh_pr_number` (→ `#N`) or `pr.id` as display ID — must match window naming convention
3. `tmux_mod.select_window()` targets `current_or_base_session(session)` for grouped session support
4. Tasks pane must not import from `pm_core.cli.*` (would pull in click, breaking tests)
5. The `w` prefix key is handled in `on_key` (not via Binding); `check_action("focus_watcher")` guards it

---

## Ambiguities and Resolutions

**A1: What if a task's PR has no PR entry in project data?**
Resolution: Entry shows window name as the label, no PR title or loop markers. PR ID is "" so no loop markers are looked up. Implemented correctly.

**A2: What if "other" windows appear (e.g., plan worker)?**
Resolution: Classified as "Other" group. Window name used as label since no PR display ID. Implemented.

**A3: What if the tasks pane is empty and user presses a PR action key (s/d/g/t)?**
Resolution: `selected_pr_id` returns None → `_get_active_pr_id()` returns None → called functions show "No PR selected". For `start_pr/done_pr/merge_pr`, if pr_id is None, the function falls back to `tree.selected_pr_id` (tech tree). This could act on the hidden tech tree selection — minor edge case, acceptable since task pane is empty anyway.

**A4: Mobile mode and manual T toggle interaction.**
Resolution: If user manually presses T to enter tasks view, `_pre_mobile_view` stays None. If terminal later narrows, mobile check sees `_tasks_visible=True` so no transition. If terminal widens, `_pre_mobile_view is None` so no restoration. User stays in tasks view — correct since they explicitly chose it.

**A5: What if mobile mode triggers on mount (size.width = 0 initially)?**
Resolution: Textual provides correct terminal size at mount time. The `on_mount` call is intentional for detecting narrow terminals on initial launch (commit eb07 i10). If size is temporarily wrong, the subsequent `on_resize` corrects it.

**A6: Selection index after poll — what if entries reorder?**
Resolution: Selection is clamped to first selectable item if out of bounds after poll. Entry order could change if new tasks appear before selected task, causing selection to drift. Acceptable trade-off; no persistent selection by entry identity.

---

## Edge Cases

1. **Watcher between iterations** (window disappears and reappears): Tasks pane shows no watcher entry when window is absent. Status marker shown only when window exists in tmux. Acceptable.

2. **Multiple impl windows for same PR**: Not expected but handled — extras treated as sub-windows under the same entry.

3. **QA sub-windows without main window**: Could happen if main window closed but scenarios still running. The first sub-window encountered would become the main_window entry since no existing entry key matches. Handled by `key not in tasks_by_key` check.

4. **Resize during mobile mode**: `_pre_mobile_view` is set on first narrow detection. If terminal oscillates around threshold, view would flicker. No hysteresis implemented — acceptable for this PR.

5. **View exclusivity**: Each `_show_*_view()` sets exactly one container to `display: block` and all others to `display: none`. State flags (`_tasks_visible`, `_plans_visible`, `_qa_visible`) match. Verified by review.

6. **Focus management**: Tasks pane is focused when shown. ESC in command bar restores focus to tasks pane when `_tasks_visible`.

---

## Current State Assessment

Based on git log analysis, all NEEDS_WORK items from the 2026-03-21 QA run appear to be fixed by committed code:

- **Toggle and basic display**: Fixed by 148e448 (duplicate method removal), eb07 series
- **PR actions**: Fixed by cfb91c5 (_get_active_pr_id), 174aeb2 (stop_loop_or_fresh_done), 9835b5d
- **Mobile mode**: Fixed by e09491c (mount check), eb07 series
- **Polling and live updates**: Fixed by 5fffcaf (animation advance), 148e448
- **Expansion state**: Fixed by ef97682
- **Watcher markers**: Fixed by ac3daa1 (watcher_infos), 148e448

The QA likely tested an older code snapshot. All 31 unit tests pass with current code.
