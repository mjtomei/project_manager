# Spec: Fix `pr select` not scrolling selected PR into view

## Requirements
1. After running `pr select <id>` from the command bar (or any programmatic
   selection change), the TechTree must scroll the newly-selected PR into
   view, just like keyboard navigation (`j`/`k`/`h`/`l`) does.
   - Code path: command bar → `pr_view.handle_command_submitted` →
     `_run_command_sync` (subprocess writes `active_pr` to project.yaml) →
     `app._load_state()` → `_update_display()` →
     `tech_tree.update_prs()` then `tech_tree.select_pr(active_pr)`
     (`tech_tree.py:141`).
   - `select_pr` already calls
     `self.call_after_refresh(self._scroll_selected_into_view)`
     (`tech_tree.py:160`), but the scroll is being clobbered.

## Root cause analysis
After `select_pr` schedules the scroll via `call_after_refresh`,
`_load_state` falls through to `_show_normal_view` (`app.py:561`) which
calls `self.query_one("#tech-tree", TechTree).focus()`. The command bar
previously had focus, so this is a focus *change*, not a no-op.

Textual's `focus()` synchronously calls `scroll_visible()` on the newly
focused widget, which scrolls each ancestor scroll container to bring
the widget's full region into view. Because the TechTree widget's region
spans the entire tall content area, the parent `#tree-container` ends up
scrolled to the top of the tree.

`call_after_refresh(_scroll_selected_into_view)` *should* fire after the
next render and override this, but in practice the focus-driven scroll
adjustment and the deferred `scroll_to_region` interleave such that the
parent container ends up at the top instead of at the selected node.
Keyboard nav doesn't hit this because focus is already on the tree —
no `scroll_visible` is triggered.

## Fix
Add a small `set_timer`-based fallback in `select_pr` so the scroll
re-runs after focus events have fully settled:

```python
self.call_after_refresh(self._scroll_selected_into_view)
# Programmatic selection (e.g. from command bar) often coincides with a
# focus change to the tree. focus() triggers scroll_visible on the
# parent container which can clobber scroll_to_region. Re-scroll after
# focus events settle.
self.set_timer(0.05, self._scroll_selected_into_view)
```

## Implicit Requirements
- Hidden plan groups must still expand when selecting a hidden PR
  (existing branch in `select_pr` handles this).
- The fallback timer must not cause visible jitter — `_scroll_selected_into_view`
  is idempotent (it scrolls to the same region), so a second call is a no-op
  if the first succeeded.

## Edge Cases
- Selecting the same PR that is already selected: `idx == selected_index`
  branch — no refresh, but `call_after_refresh` and timer still fire.
  `_scroll_selected_into_view` works regardless of selection change.
- Selecting a PR in a hidden plan: the unhide path already calls
  `_recompute()` and `refresh(layout=True)`. The set_timer fires after
  layout completes, so it works.
- Empty `_ordered_ids`: `_scroll_selected_into_view` early-returns.

## Reproduction strategy
The bug is a visual TUI regression involving Textual's internal focus +
scroll plumbing. Direct unit-test reproduction requires running an
actual Textual app via `App.run_test()`, which is fragile. Approach:
- Write a unit test that asserts `_scroll_selected_into_view` is invoked
  (e.g. via spy) when `select_pr` is called, AND that a fallback
  scheduling mechanism exists (so a focus-induced scroll-clobber is
  re-corrected).
- Record a manual repro in the PR description so the reviewer can
  validate the visual outcome.

## Ambiguities
None requiring user input.
