# pr-98b2a95: per-plan dedicated windows

## Bug
`pm_core/tui/pane_ops.py` defines `PLANS_WINDOW_NAME = "plans"` (line 535) and
`_ensure_plans_window` always finds-or-creates that single window. Every plan
action (`edit`, `breakdown`, `review`, `load`-via-pane, plus `plan add` and
plan-activated `less`) routes through `_launch_in_plans_window`, so two plans
fight over one tmux window — pressing `c` (review) on plan A then on plan B
clobbers A's pane.

## Requirements
1. Window name is plan-scoped: `plans-<plan-id>` per plan. (Slash-form rejected:
   tmux treats `/` in window names fine but it complicates `select-window`
   targeting since `:` separates session from window — keep simple `-`.)
2. `_ensure_plans_window`, `_focus_plans_window`, `_launch_in_plans_window`
   accept a `plan_id` parameter and build the per-plan window name.
3. `handle_plan_action` (line 587) passes `plan_id` through every call site.
4. `handle_plan_add` (line 611) — plan add does not yet have a plan id; treat
   as cross-plan (fallback `plans` window) since multiple `plan add` runs in
   parallel are explicitly mentioned in the PR promise.
   - **Resolution:** the PR description for pr-a353c3d cites "plan add on two
     plans at the same time" as the parallelism case. To honor that, `plan add`
     also needs a unique window. Since there's no plan id yet, use
     `plans-add-<short-uuid>` so concurrent `plan add` invocations don't
     collide.
5. `handle_plan_action("deps", ...)` — cross-plan; uses fallback `plans-deps`
   window (single window, but distinct from per-plan windows).
6. `launch_plan_activated` (line 624) — has plan_id; uses per-plan window.
7. None-plan_id fallback: window name `plans` (current behavior preserved).

## Implicit Requirements
- Existing `_KEY_ACTIONS` mapping (plans_pane.py:148) stays unchanged.
- `tmux_mod.find_window_by_name` / `select_window` already work with arbitrary
  string names — no tmux helper changes needed.
- `tests/test_tui_imports.py::test_handle_plan_action` asserts signature
  `["app", "action", "plan_id"]` — unchanged (plan_id still last).

## Edge Cases
- Pre-existing test `test_handler_routes_match_key_actions` already fails on
  master because it greps for `launch_pane(` but code uses
  `_launch_in_plans_window(`. Fix the regex while in the file (drive-by, but
  the test is directly about this function and was broken by pr-a353c3d).
- Plan removal: no current cleanup logic kills the per-plan window. Out of
  scope — existing `plans` window also wasn't cleaned up. Note in PR.
- Window with stale role pane: `launch_pane` already handles re-using a pane
  for the same role; per-plan window means plan-A and plan-B no longer share
  role names in the same window.

## Reproduction
Unit test: monkeypatch `tmux_mod.in_tmux`, `get_session_name`,
`find_window_by_name`, `new_window_get_pane`, and `launch_pane` to record
calls; invoke `handle_plan_action(app, "review", "plan-A")` then
`handle_plan_action(app, "review", "plan-B")`; assert two distinct window
names were ensured.

## Ambiguities
None unresolved.
