# QA Spec: pr-98b2a95 — per-plan dedicated tmux windows

## Background
Before this PR, all plan actions (`edit`, `breakdown`, `review`, `deps`,
`plan add`, plan-activated `less`) routed through a single hardcoded
tmux window named `plans`. Two simultaneous plan actions clobbered each
other. This PR makes the window name plan-scoped via
`_plans_window_name(plan_id)` (returns `plan_id` itself, or `"plans"`
fallback when None). Cross-plan `deps` rides a synthetic id `plan-deps`.
`plan add` precomputes the future plan id (sha256 of name) so the window
opened by add is reused by later actions on that plan. The window is
created with the action command as its sole pane (no `bash -l`
placeholder).

## Requirements
1. Two different plans receiving the same action (e.g. `c` review) must
   open distinct tmux windows named after each plan id.
2. The same plan receiving the same action twice must reuse the existing
   window (no duplicate windows).
3. Different actions on the same plan (edit then breakdown then review)
   share a single per-plan window, with each role placed in its own pane.
4. The `deps` cross-plan action uses a dedicated `plan-deps` window
   distinct from any real plan window.
5. `plan add` opens a window whose name is the deterministic future plan
   id (sha256-based). After the plan is created, subsequent actions on
   that plan target the same window.
6. New windows are created with the wrapped action command as the sole
   pane (no leftover `bash -l` placeholder).
7. Outside tmux, `_launch_in_plans_window` falls back to `launch_pane`
   in the current window.

## Setup
- Python venv with project deps; pytest available.
- For unit-level checks, run the new test file
  `tests/test_plans_window_per_plan.py`.
- For TUI manual-style verification, follow the `tui-manual-test.md`
  instructions: spin up a throwaway pm project, launch the TUI inside
  tmux, exercise plan actions and inspect tmux windows via
  `tmux list-windows`.

## Edge Cases
- `plan_id=None` route falls back to window name `"plans"`.
- `deps` synthetic id `plan-deps` doesn't collide with a real plan named
  `plan-deps` (acceptable known overlap, but verify deps still works).
- Reusing window: second invocation must call `launch_pane` with
  `target_window=<existing window id>` rather than creating a new window.
- `plan add` id matches `store.generate_plan_id(name, existing_ids)` —
  if collision, generate_plan_id chooses next; the pre-add window must
  match whatever the spawned `pm plan add` actually picks.

## Pass/Fail
- PASS: all five regression tests in
  `tests/test_plans_window_per_plan.py` pass; existing test suite still
  green; manual TUI demonstrates two plans get separate windows.
- FAIL: any regression test fails; or two distinct plans share a window;
  or `plan add` opens a window unrelated to the eventual plan id;
  or new windows still spawn a `bash -l` placeholder.

## Ambiguities
None unresolved.

## Mocks
None required at the spec level. Unit tests in the diff already
monkeypatch `pane_ops.tmux_mod` and `pane_ops.launch_pane`. Manual TUI
tests run against real tmux in an ephemeral project — no external
network/Claude calls are exercised by the affected code paths.
