# Hierarchical plans

Plans today are a flat list. PRs belong to plans, but plans can't belong to other
plans. This makes it hard to manage large projects with many interacting pieces —
you end up with either one giant plan or many disconnected small plans with no
way to see how they relate.

This plan adds parent-child relationships to plans, mirroring how PRs already
relate to plans. A parent plan contains summaries of its children and acts as the
"project-level" view. Child plans contain the detailed PR breakdowns. The hierarchy
is mutable — plans and PRs can be moved between parents — and review is
hierarchy-aware, checking both summary accuracy and cross-level consistency.

## Scope

- Add optional `parent` field to plan entries in project.yaml
- Extend plan markdown format with a `## Plans` section for child plan summaries
- Update the TUI plans pane to render hierarchy as a tree
- Make `plan review` hierarchy-aware (parent context for child reviews, summary
  accuracy checks for parent reviews)
- Add commands to mutate the hierarchy: reparent plans, move PRs between plans
- Add integrity checks after mutations to ensure parent summaries stay accurate
- Show plan hierarchy context in the PR tech tree view (plan group labels
  reflect hierarchy)
- Add a "collapse all leaf plans" action so users can see the hierarchy overview,
  then selectively expand the plan they want to drill into

## Goals

1. **Project-level view**: Users can see and interact with the project as a whole
   through a top-level plan that summarizes all major workstreams.
2. **Scalable decomposition**: Large projects split naturally into a tree of plans
   without losing coherence — each level summarizes the one below it.
3. **Mutable organization**: Plans and PRs can be reorganized as understanding
   evolves. Reparenting and moving are first-class operations, not manual YAML edits.
4. **Cross-level review**: Review of child plans is informed by parent context.
   Review of parent plans verifies that child summaries are accurate and complete.
5. **Refactoring safety**: Moving PRs or plans between parents triggers integrity
   checks so summaries and dependency graphs don't silently drift.

## Key design decisions

### 1. `parent` field on plan entries (like `pr.plan`)

Add an optional `parent` field to plan entries in project.yaml. A plan with no
parent is a root plan. This is the same pattern PRs already use to belong to plans.

```yaml
plans:
- id: plan-top
  name: Project overview
  file: plans/plan-top.md
  status: active
  parent: null          # root plan
- id: plan-auth
  name: Auth refactor
  file: plans/plan-auth.md
  status: active
  parent: plan-top      # child of plan-top
```

### 2. `## Plans` section in parent plan files

Parent plan files get a `## Plans` section (analogous to `## PRs`) listing child
plans with summaries. These summaries are the key artifact that review validates.

```markdown
## Plans

### Plan: Auth refactor
- **summary**: Migrate from session tokens to JWT, update all middleware
- **status**: active
- **id**: plan-auth

---

### Plan: API v2
- **summary**: New versioned API with breaking changes isolated behind /v2
- **status**: draft
- **id**: plan-api-v2
```

### 3. Hierarchy-aware review

- **Child plan review**: Receives the parent plan file as context. The parent
  already contains sibling summaries in its `## Plans` section, so no separate
  sibling data is needed. The reviewer checks alignment with parent goals and
  flags work that might belong in a sibling.
- **Parent plan review**: Receives a list of child plans (ID, name, status, file
  path) with instructions to read child files as needed — not the full content
  of every child plan in the prompt. The reviewer checks that `## Plans`
  summaries are accurate, flags missing children and coverage gaps.

### 4. Tree rendering in TUI

The plans pane renders hierarchy with indentation. Root plans at the left edge,
children indented with tree-drawing characters. Collapsed parents show aggregate
PR counts. Expand/collapse with a key binding.

### 5. Hierarchy in PR tech tree view

The tech tree already groups PRs by plan with plan label rows. With hierarchy,
plan group labels should show their position in the tree (e.g. indented or
prefixed with the parent plan name). A "collapse all leaf plans" action (`C`)
collapses every leaf-level plan group into its label row, giving the user a
birds-eye view of the hierarchy. From there they can selectively expand (`Enter`
or `space`) the one plan they want to drill into. This is the primary way users
will navigate large hierarchical projects in the PR view.

### 6. Mutation commands with integrity checks

`pm plan reparent` moves a plan to a new parent (or to root). `pm pr move` moves
a PR to a different plan. Both trigger a check on affected parent plans to flag
summaries that need updating. The user can then run `pm plan review` on the
parent to reconcile.

## Constraints

- **Backward compatible**: Plans without `parent` are root plans. Existing
  project.yaml files work without migration.
- **No forced depth**: The hierarchy can be any depth, but the common case is
  2 levels (project plan + workstream plans). Don't over-engineer for deep trees.
- **Summaries are authored, not generated**: The `## Plans` section is written by
  the plan author (human or Claude). Review checks accuracy but doesn't
  auto-generate summaries — that would defeat the purpose of having a curated
  high-level view.
- **Acyclic**: A plan cannot be its own ancestor. Reparent must validate this.

## PRs

### PR: Add `parent` field to plan schema
- **description**: Add optional `parent` field to plan entries in project.yaml. Update `store.py` to include `parent: null` in new plan entries. Add validation in `store.load()` that `parent` references a valid plan ID (or null). Update `init_project` and any plan creation paths to set `parent`. This is the foundation — no UI or behavioral changes yet.
- **tests**: Test that plans with valid parent IDs load correctly. Test that plans with invalid parent IDs raise validation errors. Test that plans with null parent are treated as root plans. Test cycle detection (a plan cannot be its own ancestor).
- **files**: pm_core/store.py, tests/test_store.py
- **depends_on**:

---

### PR: Add hierarchy traversal helpers to store
- **description**: Add functions to store.py for navigating the plan tree: `get_children(data, plan_id)` returns direct children, `get_ancestors(data, plan_id)` returns the ancestor chain, `get_subtree(data, plan_id)` returns all descendants, `get_root_plans(data)` returns plans with no parent, `is_ancestor(data, ancestor_id, descendant_id)` for cycle checks. These are pure data helpers with no side effects.
- **tests**: Test each helper with a 3-level hierarchy. Test edge cases: root plans, leaf plans, empty project. Test `is_ancestor` with direct parent, grandparent, non-ancestor, and self.
- **files**: pm_core/store.py, tests/test_store.py
- **depends_on**: Add `parent` field to plan schema

---

### PR: Plan parser support for `## Plans` section
- **description**: Extend `plan_parser.py` to parse a `## Plans` section from parent plan markdown files. Add `parse_plan_children()` function that extracts child plan blocks (similar to `parse_plan_prs()`). Each block has: title, summary, status, id. Add `extract_field()` support for the summary field. This is parsing only — no load/write behavior.
- **tests**: Test parsing a plan file with `## Plans` section containing multiple children. Test parsing a plan with both `## Plans` and `## PRs` sections. Test parsing a plan with no `## Plans` section (returns empty list). Test field extraction for summary, status, id.
- **files**: pm_core/plan_parser.py, tests/test_plan_parser.py
- **depends_on**:

---

### PR: `pm plan add --parent` option
- **description**: Add `--parent` option to `pm plan add` command. When specified, sets the `parent` field on the new plan entry. Validates that the parent plan exists. The Claude session prompt for plan development should include the parent plan's content as context so the child plan is developed with awareness of the parent's goals and scope.
- **tests**: Test that `pm plan add --parent plan-top` creates a plan with correct parent field. Test that `--parent` with nonexistent plan ID raises an error. Test that omitting `--parent` creates a root plan (parent: null).
- **files**: pm_core/cli/plan.py, tests/test_plan_cli.py
- **depends_on**: Add `parent` field to plan schema

---

### PR: `pm plan load` handles `## Plans` section
- **description**: Extend `pm plan load` to process the `## Plans` section in parent plan files. For each child plan block: if a plan with matching ID already exists, update its name and status; if not, create a new plan entry with the parent set. This mirrors how `## PRs` blocks create PR entries. Also update the child plan's markdown file header if it was just created. Does not recurse — loading a parent plan creates/links children but does not load their PRs.
- **tests**: Test loading a parent plan creates child plan entries with correct parent field. Test loading when child plans already exist updates metadata without duplicating. Test that child plan markdown files are created when missing.
- **files**: pm_core/cli/plan.py, pm_core/plan_parser.py, tests/test_plan_cli.py
- **depends_on**: Plan parser support for `## Plans` section, Add `parent` field to plan schema

---

### PR: TUI plans pane tree rendering
- **description**: Update `PlansPane` to render plans as a tree. Root plans render at the left edge; children indent with tree characters (├── and └──). Show aggregate PR count for parent plans (sum of own + descendants' PRs). Add expand/collapse toggle: collapsed parents show as a single line with child count; expanded parents show their children below. Persist expand/collapse state in the widget. **Human-guided testing needed**: tree rendering with various hierarchy depths, expand/collapse keyboard interaction, visual alignment of tree characters.
- **tests**: Test that `update_plans()` with hierarchical data produces correct tree ordering. Test expand/collapse state toggling. Test aggregate PR count calculation. Test rendering with 1-level, 2-level, and 3-level hierarchies. Test that flat plans (no parent) render identically to current behavior.
- **files**: pm_core/tui/plans_pane.py, pm_core/tui/app.py, tests/test_plans_pane.py
- **depends_on**: Add hierarchy traversal helpers to store

---

### PR: Plan review: parent context for child reviews
- **description**: When reviewing a child plan (one with a `parent` field), include the parent plan's content in the review prompt. The parent plan already contains the `## Plans` section with sibling summaries, so no separate sibling data is needed — the parent file is sufficient context. The review prompt should instruct Claude to: check that the child plan's work aligns with the parent's goals, flag work that might belong in a sibling (referencing the parent's summaries), and anticipate cross-cutting issues.
- **tests**: Test that child plan review prompt includes parent plan file content. Test that no separate sibling plan data is injected (parent file covers it). Test that root plan review does not include parent context.
- **files**: pm_core/cli/plan.py, pm_core/review.py, tests/test_plan_review.py
- **depends_on**: Add hierarchy traversal helpers to store

---

### PR: Plan review: summary accuracy checking for parent plans
- **description**: When reviewing a parent plan (one that has children), the review prompt lists child plans by ID, name, status, and file path — with instructions on how to read them (e.g. `Read the file at pm/plans/plan-auth.md`). It does NOT include full child plan content in the prompt. The reviewer is instructed to read child plan files as needed to verify that the `## Plans` summaries are still accurate. The prompt should instruct Claude to flag: summaries that no longer match the child's actual scope, children in project.yaml missing from the `## Plans` section, status mismatches, and coverage gaps where parent goals aren't addressed by any child. Suggest specific edits to the `## Plans` section.
- **tests**: Test that parent plan review prompt lists child plans with file paths. Test that full child plan content is NOT embedded in the prompt. Test that review instructions reference reading child files.
- **files**: pm_core/cli/plan.py, pm_core/review.py, tests/test_plan_review.py
- **depends_on**: Plan parser support for `## Plans` section, Plan review: parent context for child reviews

---

### PR: `pm plan reparent` command
- **description**: Add `pm plan reparent <plan-id> [--parent <new-parent-id>]` command. Moves a plan to a new parent, or to root if `--parent` is omitted. Validates: target parent exists, no cycle would be created (plan cannot become its own ancestor), plan is not already under the target parent. After reparenting, prints a warning listing affected parent plans whose `## Plans` sections may need updating, and suggests running `pm plan review` on them. **Human-guided testing needed**: verify reparent with TUI refresh, check that plans pane reflects new hierarchy.
- **tests**: Test reparenting a child to a different parent. Test reparenting to root (clearing parent). Test cycle detection rejects self-parenting and indirect cycles. Test error on nonexistent target parent. Test warning message lists affected plans.
- **files**: pm_core/cli/plan.py, tests/test_plan_cli.py
- **depends_on**: Add hierarchy traversal helpers to store

---

### PR: `pm pr move` with cross-plan integrity checks
- **description**: Add `pm pr move <pr-id> --plan <target-plan-id>` command (or enhance existing `pm pr edit --plan`). Moves a PR to a different plan. After moving, checks whether the PR's dependencies are still satisfiable (warns if depends_on PRs are in unrelated plans). Prints a warning listing affected plans whose summaries or PR coverage may need review. Also supports moving a PR to a plan in a different subtree of the hierarchy. **Human-guided testing needed**: verify PR moves reflect correctly in TUI tech tree and plans pane.
- **tests**: Test moving a PR between plans in same subtree. Test moving a PR to an unrelated plan. Test dependency warning when depends_on PR is in a different subtree. Test error on nonexistent target plan.
- **files**: pm_core/cli/pr.py, pm_core/cli/plan.py, tests/test_pr_cli.py
- **depends_on**: Add hierarchy traversal helpers to store

---

### PR: Tech tree hierarchical plan group labels
- **description**: Update plan group labels in the tech tree to reflect hierarchy. When PRs are grouped by plan, and the plan has a parent, prefix the plan label with its ancestry path (e.g. "Project overview > Auth refactor") or indent it under its parent group. This gives users hierarchy context without leaving the PR view. The tree layout engine (`tree_layout.py`) should order plan groups so that children appear after their parents. **Human-guided testing needed**: verify label rendering with nested hierarchies, check that label scrolling and plan-jump navigation (`{`/`}` keys) still work correctly with hierarchical labels.
- **tests**: Test that plan group labels include parent context when hierarchy exists. Test label ordering follows hierarchy (parent groups before children). Test that flat plans (no hierarchy) render labels identically to current behavior. Test plan-jump navigation across hierarchical groups.
- **files**: pm_core/tui/tech_tree.py, pm_core/tui/tree_layout.py, tests/test_tech_tree.py
- **depends_on**: Add hierarchy traversal helpers to store

---

### PR: Tech tree collapse-all-leaves action
- **description**: Add a `C` keybinding in the tech tree that collapses all leaf-level plan groups (plans with no children — the ones containing PRs). This gives a birds-eye view showing only the plan hierarchy labels. The user can then selectively expand individual plan groups with `Enter` or `space` to drill into the PRs they care about. Add an `E` keybinding to expand all groups back. Update the footer to show `C`=collapse-all and `E`=expand-all. **Human-guided testing needed**: full interaction flow — collapse all, navigate between collapsed groups, expand one, verify PRs appear, expand all restores full view.
- **tests**: Test that `C` collapses all leaf plan groups. Test that collapsed groups show as label-only rows. Test that `Enter`/`space` on a collapsed group expands it. Test that `E` expands all groups. Test that navigation between collapsed groups works correctly.
- **files**: pm_core/tui/tech_tree.py, pm_core/tui/tree_layout.py, tests/test_tech_tree.py
- **depends_on**: Tech tree hierarchical plan group labels

---

### PR: TUI hierarchy mutation shortcuts
- **description**: Add keyboard shortcuts in the plans pane for hierarchy mutation. `R` to reparent the selected plan (opens a selection modal for target parent), `M` to move PRs (switches to PR selection within the plan, then target plan selection). These shortcuts launch the underlying CLI commands via pane operations. Update the footer to show new shortcuts. **Human-guided testing needed**: full interactive flow of reparent and move via TUI, modal selection UX, footer display.
- **tests**: Test that `R` key fires the correct PlanAction. Test that `M` key fires the correct PlanAction. Test footer rendering includes new shortcuts.
- **files**: pm_core/tui/plans_pane.py, pm_core/tui/app.py, pm_core/tui/pane_ops.py, tests/test_plans_pane.py
- **depends_on**: TUI plans pane tree rendering, `pm plan reparent` command, `pm pr move` with cross-plan integrity checks
