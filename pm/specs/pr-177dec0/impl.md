# Implementation Spec: Fix pr select not scrolling selected PR into view

## Requirements

### R1: Programmatic PR selection must scroll the TechTree to the selected node

When `select_pr()` is called programmatically (e.g., from the command bar's `pr select`
command or from `_update_display()` on reload), the `TreeScroll` container must scroll
to bring the selected PR node into view, exactly as keyboard navigation (j/k) does.

**Relevant code paths:**
- `pm_core/tui/tech_tree.py:select_pr()` (line 121) — the method that sets
  `selected_index` and schedules `_scroll_selected_into_view` via
  `call_after_refresh`.
- `pm_core/tui/tech_tree.py:_scroll_selected_into_view()` (line 905) — the
  method that computes the node region and calls `container.scroll_to_region()`.
- `pm_core/tui/app.py:_update_display()` (line 572) — calls `tree.update_prs()`
  then `tree.select_pr()`.
- `pm_core/tui/app.py:action_reload()` (line 868) — calls `_load_state()` and
  then `self.refresh(layout=True)` on the App.
- `pm_core/tui/pr_view.py:_run_command_sync()` (line 493) — runs CLI subprocess,
  then calls `app._load_state()`.

### R2: The scroll position must clear overlaid UI elements

The selected PR must not be hidden behind the command bar, log line, or scroll bar
at the bottom of the viewport. The existing `bottom_padding = 4` in
`_scroll_selected_into_view` (line 939) and `spacing=Spacing(bottom=2)` (line 949)
already handle this for keyboard navigation.

## Root Cause Analysis

### Double-reload race condition

When `pr select` is executed via the command bar:

1. `_run_command_sync()` blocks the event loop with `subprocess.run()` (line 497).
2. The CLI subprocess updates `project.yaml` and calls `trigger_tui_refresh()`,
   which sends an "R" keystroke to the TUI pane via tmux
   (`pm_core/cli/helpers.py:310`).
3. After the subprocess exits, `_run_command_sync()` calls `app._load_state()`
   (line 516), which calls `_update_display()` → `tree.update_prs()` →
   `tree.select_pr()` → `call_after_refresh(_scroll_selected_into_view)`.
4. The event loop resumes and processes the pending layout/refresh, then
   fires the `_scroll_selected_into_view` callback — **scroll is set correctly**.
5. The buffered "R" keystroke is then processed, triggering `action_reload()`.
6. `action_reload()` calls `_load_state()` again (second reload), then calls
   `self.refresh(layout=True)` **on the App** (line 890).
7. The App's `refresh(layout=True)` triggers a full layout pass that runs
   **after** the second `_scroll_selected_into_view` callback was already
   scheduled. This layout pass may reset the scroll position set in step 4.
8. The second `_scroll_selected_into_view` fires, but it runs via
   Textual's `InvokeLater` → `Screen._callbacks` mechanism, which only
   fires when the screen is fully idle (no `_layout_required`,
   `_scroll_required`, `_repaint_required`, or `_dirty_widgets` — see
   `screen.py:_on_idle()` line 1165). If the App's `refresh(layout=True)`
   from step 6 generates cascading layout/repaint work, the callback may
   be repeatedly deferred or fire with stale container dimensions.

### Why keyboard navigation is unaffected

Keyboard navigation (`on_key()`, line 653) calls `self.refresh()` (repaint
only, no layout) and then `call_after_refresh(_scroll_selected_into_view)`.
There is no `update_prs()`, no `_recompute()`, no `refresh(layout=True)`, and
no double-reload. The simpler refresh cycle makes `call_after_refresh`
reliable.

## Implicit Requirements

### IR1: Normal reloads must still scroll to the active PR

When the user presses "R" (manual reload) or when auto-sync reloads state,
`_update_display()` calls `select_pr()` which should scroll to the active PR.
The fix must not break this behavior.

### IR2: The fix must not cause visual flicker

Scheduling multiple scroll callbacks or using timers should not cause the
viewport to jump between positions visibly.

### IR3: The fix must not break collapsed-plan expansion

`select_pr()` automatically expands collapsed plan groups to show the
selected PR (lines 125-134). The scroll must happen after this expansion.

## Ambiguities

### A1: Should `select_pr()` scroll even when the index hasn't changed?

**Current behavior:** `call_after_refresh(_scroll_selected_into_view)` is
called unconditionally (line 140), but `self.refresh()` is only called when
`idx != self.selected_index` (line 139). If the index hasn't changed,
there may not be a pending refresh for the callback to fire after.

**Resolution:** Always call `self.refresh()` in `select_pr()`. This ensures
there's always a pending refresh/repaint, making `call_after_refresh`
reliable. This is safe because `refresh()` is lightweight (just marks
the widget for repaint).

### A2: Should the App-level `refresh(layout=True)` in `action_reload()` be removed?

**Current behavior:** `action_reload()` at line 890 calls
`self.refresh(layout=True)` on the App after `_load_state()`. This triggers
a full App layout pass.

**Resolution:** Remove it. `_load_state()` already calls
`_update_display()` which calls `update_prs()` → `refresh(layout=True)` on
the TechTree, and `_show_normal_view()` which sets display styles. The
App-level layout is unnecessary and creates the timing issue described above.

### A3: Should `trigger_tui_refresh()` be suppressed for commands run from the TUI?

**Current behavior:** The CLI's `pr_select()` always calls
`trigger_tui_refresh()`, even when invoked via `_run_command_sync()` from
the TUI itself. This causes a redundant double-reload.

**Resolution:** Don't suppress `trigger_tui_refresh()`. It's useful for
cases where the CLI is run externally (not from the TUI). Instead, make the
TUI robust against the double-reload via Changes 1 and 3 (always-refresh
in `select_pr()` and removing the App-level `refresh(layout=True)` from
`action_reload()`). The overhead of a second `_load_state()` call is
minimal.

## Edge Cases

### E1: PR is in a collapsed plan group

`select_pr()` already handles this by expanding the hidden plan group
(lines 131-134). The scroll should work correctly after expansion because
`_recompute()` and `refresh(layout=True)` are called.

### E2: PR is filtered out by status filter

If the active PR has a status that's filtered out (e.g., "merged" when
hide-merged is on), it won't be in `_ordered_ids`. `select_pr()` won't
scroll because the PR doesn't exist in the tree. This is existing behavior
and should not change.

### E3: Tree has only one or two PRs (no scrolling needed)

When the tree content fits within the viewport, `scroll_to_region()` may
be a no-op. This is correct behavior.

### E4: Rapid successive `pr select` commands

If the user runs multiple `pr select` commands quickly, each one triggers
a reload cycle. The last selection should win because each `select_pr()`
call updates `selected_index` and schedules a new scroll callback.

## Implementation Plan

### Change 1: Make `select_pr()` always refresh (tech_tree.py)

In `select_pr()`, always call `self.refresh()` regardless of whether
`selected_index` changed. This ensures `call_after_refresh` has a pending
refresh to fire after.

### Change 2: Remove App-level `refresh(layout=True)` from `action_reload()` (app.py)

Remove the `self.refresh(layout=True)` at line 890 of `action_reload()`.
`_load_state()` already handles all necessary refreshes via
`_update_display()`. This eliminates the extra layout pass that can
interfere with the scroll callback scheduled by `select_pr()`.
