# QA Spec: Add `parent` field to plan schema (pr-6ca8113)

## Requirements

### R1: `parent` field on plan entries
Plan entries in project.yaml gain an optional `parent` key. Value is either a valid
plan ID string or `null` (root plan). Created via `make_plan_entry()` in `store.py`.

### R2: All plan creation paths use `make_plan_entry`
Every code path that creates a plan entry dict must use `store.make_plan_entry()`,
which includes `parent: None` by default. Affected paths:
1. `pm_core/cli/plan.py:66` — `plan_add` command
2. `pm_core/cli/plan.py:723` — `_run_plan_import` function
3. `pm_core/cli/cluster.py:129` — cluster auto-creation
4. `pm_core/tui/watcher_ui.py:62` — watcher plan auto-creation

### R3: Validation in `store.load(validate=True)`
`_validate_plans()` is called during `load()` when `validate=True`. It performs:
- **Status normalization**: invalid/missing plan statuses silently fixed to `"draft"`.
  Valid statuses: `{"draft", "active", "done"}`.
- **Parent backfill**: plans missing the `parent` key get `parent: None` added in-memory.
- **Parent reference check**: `parent` must be `None` or reference an existing plan ID.
  Invalid references raise `PlanValidationError`.
- **Cycle detection**: walks parent chains with a visited set. Any cycle raises
  `PlanValidationError`.

### R4: `validate=False` skips plan validation
Consistent with PR status validation — when `validate=False`, no plan validation
runs, no backfill, no error on bad references.

### R5: TUI PlanPickerScreen — "New plan" option removed
The plan picker modal (opened by `M` key) no longer offers "New plan..." as an option.
The `_new` tuple/input-mode code path is removed from `screens.py` and `pr_view.py`.
The `M` key still works to open the picker with existing plans + "No plan (standalone)".

### R6: `make_plan_entry` helper
New `store.make_plan_entry(plan_id, name, file, *, status="draft", parent=None)` returns
a standardized plan dict. All creation paths now use it.

### R7: Tests in `tests/test_store.py`
17 tests covering status validation, parent validation, cycle detection, and edge cases.

## Setup

- Python environment with `pm_core` installed (`pip install -e .`)
- For unit tests: `pytest tests/test_store.py`
- For TUI manual tests: follow `tui-manual-test.md` instruction — create throwaway
  project in workdir, initialize with `pm init --backend local --no-import`, add plans
  and PRs via CLI

## Edge Cases

1. **Empty/null plans list**: `plans: []` or `plans: null` — validation is a no-op
2. **Self-referencing parent**: `plan-001` with `parent: plan-001` — caught by cycle detection
3. **Deep hierarchy chains**: A->B->C->D (D is root) — valid, no cycle
4. **Multiple roots**: Multiple plans with `parent: null` — valid
5. **Missing parent key (backward compat)**: Old plans without `parent` field treated as root
6. **Missing status key**: Normalized to `"draft"`
7. **Plan picker with no plans**: Only shows "No plan (standalone)" option
8. **`validate=False` with bad data**: Invalid parent and bad status pass through unchanged

## Pass/Fail Criteria

### Pass
- All 17 existing tests in `tests/test_store.py` pass
- All plan creation paths produce entries with `parent` key (via `make_plan_entry`)
- `store.load()` on the real `pm/project.yaml` in this branch succeeds (backward compat)
- Plans with valid parent references load without error
- Plans with invalid parent references raise `PlanValidationError`
- Cycles of any length raise `PlanValidationError`
- `validate=False` skips all plan validation
- TUI `M` key opens plan picker without "New plan..." option
- TUI `M` key still allows selecting existing plans and "No plan (standalone)"

### Fail
- Any test in `test_store.py` fails
- A plan creation path produces a dict without `parent` key
- `store.load()` crashes on existing project.yaml files that lack `parent` fields
- Invalid parent references silently pass when `validate=True`
- Cycles are not detected
- TUI plan picker still shows "New plan..." option or input field

## Ambiguities

### A1: Should `make_plan_entry` enforce valid status values?
**Resolution**: No. `make_plan_entry` just constructs a dict. Validation happens in
`_validate_plans()` during `load()`. This keeps creation simple and validation centralized.

### A2: Is the "New plan" removal in PlanPickerScreen a regression or intentional?
**Resolution**: Intentional per PR notes — "removed new plan option from plan picker in
tui (M key), please verify in qa that M key still works and new plan option is gone."
Plan creation now happens exclusively through `pm plan add` CLI (or future `--parent`
option in a follow-up PR).

### A3: Does backward compat extend to plans with unknown extra keys?
**Resolution**: Yes by default — YAML loading ignores unknown keys. The validator only
checks `status`, `parent`, and `id`. Extra keys pass through.

## Mocks

No external dependencies require mocking for this PR. All changes are to in-process
YAML loading/validation logic and TUI widget composition. Tests use `tmp_path` fixtures
with hand-written YAML. TUI manual tests run against a real local project — no network,
Claude sessions, or git operations are involved in the core functionality under test.
