# Implementation Spec: Add `parent` field to plan schema

## Requirements

### R1: Add optional `parent` field to plan entries in project.yaml
Plan entries in the `plans` list of project.yaml gain a new `parent` key. The value
is either a valid plan ID string (e.g. `"plan-cb4ef69"`) or `null` (root plan).

### R2: Set `parent: null` in new plan entries created by `store.py`
`init_project` in `pm_core/store.py:207-229` creates the initial `data` dict with
an empty `plans: []` list — no change needed there. However, every code path that
constructs a plan entry dict must include `"parent": None`.

Plan creation paths (all must include `parent`):
1. `pm_core/cli/plan.py:66-71` — `plan_add` command
2. `pm_core/cli/plan.py:728-733` — `_run_plan_import` function
3. `pm_core/cli/cluster.py:129` — cluster auto-creation
4. `pm_core/tui/pr_view.py:323` — TUI inline plan creation
5. `pm_core/tui/watcher_ui.py:62-67` — watcher plan auto-creation

### R3: Validate plans in `store.load()`
Add a `_validate_plans` step in `store.load()` (called when `validate=True`) that
checks every plan entry. Two validations:

**Status validation** — normalize invalid plan statuses to `"draft"`, mirroring the
PR status pattern in `_validate_pr_statuses`. Define `VALID_PLAN_STATUSES = {"draft"}`
in `store.py` (only value used in creation paths today; easy to extend later).
Auto-fix invalid values silently, same as PRs.

**Parent validation** — check every plan's `parent` field:
- `null` / `None` is valid (root plan)
- A string matching the `id` of another plan in the same `plans` list is valid
- Anything else raises a validation error

### R4: Cycle detection
A plan cannot be its own ancestor. If plan A has parent B, and B has parent A, that
is a cycle. The validation must detect cycles of any length and raise an error.

### R5: Tests in `tests/test_store.py`
Create a new test file `tests/test_store.py` with tests covering:
- Plans with valid parent IDs load correctly
- Plans with invalid parent IDs raise validation errors
- Plans with `null` parent are treated as root plans
- Cycle detection (direct self-reference, two-node cycle, longer chain)
- Invalid plan status normalized to `"draft"`
- Valid plan status left unchanged

## Implicit Requirements

### IR1: Backward compatibility with existing project.yaml files
Existing plan entries lack a `parent` field. The validator must treat a missing
`parent` key the same as `parent: null` — i.e. a root plan. It must NOT crash or
require migration.

### IR2: `validate=False` must skip parent validation
The existing `load(validate=False)` path skips PR status validation. Parent
validation must also be skipped when `validate=False`, consistent with the existing
pattern.

### IR3: No behavioral/UI changes
Per the task description: "This is the foundation — no UI or behavioral changes yet."
The plans pane (`plans_pane.py`), tech tree (`tech_tree.py`), TUI app enrichment
(`app.py:957-964`), and all prompt generation code must remain untouched.

### IR4: Serialization round-trip
`parent: null` must serialize cleanly through `yaml.dump` and `yaml.safe_load`.
YAML represents Python `None` as `null`, so this works by default. The field should
appear in the YAML output for new plans.

## Ambiguities

### A1: What exception type should invalid-parent validation raise?
**Resolution:** Use a new `PlanValidationError` exception class in `store.py`,
similar to the existing `ProjectYamlParseError`. This distinguishes schema errors
(unparseable YAML) from semantic errors (invalid references). Alternatively, could
reuse `ProjectYamlParseError` since it's already the "load failed" exception.
**Proposed:** Create a new `PlanValidationError(Exception)` in `store.py` for
clarity, keeping it consistent with the existing error pattern.

### A2: Should validation auto-fix invalid parents (like PR statuses) or raise?
PR status validation silently fixes invalid values to `"pending"`. Parent references
are structural — silently dropping them could create confusing behavior (a plan
suddenly becomes a root when it shouldn't be).
**Proposed:** Raise `PlanValidationError` for invalid parent references and cycles.
Do NOT silently fix.

### A3: Should the `parent` field be backfilled on existing plans during load?
Existing plans won't have a `parent` key. Should `load()` add `parent: None` to
them in memory (like timestamp backfill for PRs)?
**Proposed:** Yes — backfill `parent: None` on plans that lack the key during
validation. This ensures downstream code can always assume the field exists after
`load(validate=True)`. This is a non-destructive in-memory normalization (not
written back to disk unless `save()` is called).

### A4: What about plans whose parent is a plan that exists but was deleted/removed?
If a plan references a parent that was manually removed from project.yaml, validation
should catch it the same as any invalid reference.
**Proposed:** Already handled by R3 — parent must reference an existing plan ID.

## Edge Cases

### E1: Empty or null plans list
`plans: []` or `plans: null` — validation should be a no-op. Already handled by
the `data.get("plans") or []` pattern used throughout.

### E2: Plan referencing itself as parent
`plan-001` with `parent: plan-001` is the simplest cycle. Must be caught by cycle
detection.

### E3: Deep hierarchy chains
A chain like A->B->C->D (D is root) is valid. Validation must walk the chain to
check for cycles without assuming max depth. Use a visited-set approach.

### E4: Multiple roots
Multiple plans with `parent: null` is valid — there's no requirement for a single
root.

### E5: Orphaned subtrees
If plan B has parent A, and plan C has parent B, removing A from the plans list
makes B invalid (dangling parent). C's parent B still exists, so C is fine. The
validation only checks immediate parent references, not full subtree integrity.
