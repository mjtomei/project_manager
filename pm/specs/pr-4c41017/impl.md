# Spec: Refactor TechTree — split PR nodes into individual Textual widgets

PR: pr-4c41017 (#131) · Plan: tui-ux

## Problem / Goal

`pm_core/tui/tech_tree.py` `TechTree(Widget)` is a single monolithic widget
whose `render()` (lines 303–681) builds a full character grid for *every* PR
(~120) plus all edges and plan labels, then converts it to one Rich `Text`.

The review-loop poll timer (`pm_core/tui/review_loop_ui.py`
`_ensure_poll_timer`, 1.0 s interval) calls `_refresh_tech_tree`
(lines 464–472) every second whenever any loop runs *or* any PR is
in_progress/in_review/qa. That calls `tree.advance_animation()` +
`tree.refresh()`, which repaints the entire grid even though only the 2–3
active nodes' spinners changed. This is the ~20 % idle CPU the task targets.

Refactor into a compositional Textual architecture so spinner ticks repaint
only the active node widgets, edges cache across ticks, and layout is only
recomputed when inputs actually change.

## Validated Textual mechanics (prototyped against textual 8.2.5)

- `position: absolute` + `offset: x y` places a child at exact character
  coordinates inside its parent (confirmed: child `.region` == offset).
- A child with `position: absolute` is out of normal flow, so the parent does
  **not** auto-size to contain it. The container must be given an **explicit**
  `width`/`height` equal to the content extent for `TreeScroll` to scroll.
- Stacked full-size **transparent** containers composite correctly: each holds
  only its own absolutely-positioned children at global coordinates; setting
  `container.display = False` hides that container's children only.
- An opaque child widget painted over a lower-layer canvas hides the canvas
  beneath it and lets canvas content show in the gaps (layers `edges nodes`).
- Children must be passed via the `Widget(*children)` constructor and have
  their `offset` set in `on_mount` (setting offset in `__init__` before mount,
  or yielding pre-built widgets from a group instance's `compose`, was flaky).
- `ScrollableContainer.scroll_to_region(Region(x,y,w,h), ...)` scrolls to
  absolute child coordinates (works). `scroll_to_widget`/`scroll_visible` do
  **not** work reliably for absolutely-positioned nested widgets — keep using
  `scroll_to_region` with layout coordinates, as the current code already does.

## 1. Requirements (grounded)

### R1 — PR nodes as individual widgets
- New `PRNode(Widget)` in `tech_tree.py`. One instance per visible PR.
  `render()` produces the existing 5-line box (NODE_W=24 × NODE_H=5), moving
  the per-node drawing block (current lines 502–635: borders, id line w/
  auto-start `◎` marker, title line, status line w/ icon + loop marker +
  activity spinner + spec-pending `S` + agent_machine, plus marker/auto-start
  coloring) into `PRNode.render()`.
- Positioned `position: absolute`, `offset = (x, y)` where `x` is the layout
  `node_positions[pr_id][0]` and `y = row*(NODE_H+V_GAP)+1` (the existing
  `node_pos` math). Opaque background so it occludes the edge canvas.
- The 1 s poll path refreshes **only** active nodes. Add
  `TechTree.refresh_active_nodes()`; `_refresh_tech_tree` calls
  `tree.advance_animation()` then `tree.refresh_active_nodes()` (no whole-tree
  `refresh()`, no `_recompute`). Active = status in
  {in_progress, in_review, qa} with `workdir`, OR has a `_review_loops` entry,
  OR in `_merge_input_required_prs`. Each `PRNode.render()` reads live spinner
  state from the app each call, so refreshing one node re-renders just it.

### R2 — Plan groups as container widgets
- New `PlanGroup(Widget)` container, one per plan id (named plans + the
  `_standalone` pseudo-plan). Full-content-size, `position: absolute`,
  `offset (0,0)`, transparent background, holds that plan's `PRNode`s (global
  offsets) plus a `PlanLabel(Widget)` child for the plan's `── name ──` rule
  (current lines 637–646), positioned at the label row.
- Collapse/expand of a plan is `group.display = False/True`.
- **Resolved (see Ambiguities A1):** the user-facing *hide* action (`x`,
  `pr_view.py` `_hide_plan`) keeps its current semantics — recompute so hidden
  plans reflow away and appear as navigable one-line labels at the bottom.
  PlanGroup `display` toggling is the internal mechanism; it does not change
  the bottom-label UX. The idle-CPU goal is met by R1+R4 (the 1 s timer never
  recomputes), not by changing hide semantics.

### R3 — Edge rendering as a separate cached layer
- New `EdgeCanvas(Widget)` on a lower `layer: edges`, full content size,
  `offset (0,0)`. `render()` builds a char grid containing **only** the
  dependency arrows (current edge logic lines 353–495: edge collection,
  priority sort, fan-out exit/entry offset spreading, channel allocation,
  straight + elbow routing with `▶` heads). It caches its rendered `Text` and
  only rebuilds when the layout/dep set changes (rebuilt by `TechTree` on
  `_recompute`; never touched by the spinner timer).

### R4 — Layout computation caching
- `TechTree._recompute()` builds a signature of every input that affects
  `compute_tree_layout` output *and* node display, and skips the Sugiyama
  recompute + widget rebuild when the signature is unchanged. Signature =
  (`_hidden_plans` frozenset, `_status_filter`, `_hide_merged`, `_hide_closed`,
  `_sort_field`, viewport width, and per-PR tuple of
  (id, status, title, plan, gh_pr_number, spec_pending, agent_machine,
  workdir-bool, tuple(depends_on), sort timestamps)). Cache
  `(_layout_sig, TreeLayout)`. The 1 s timer already does not call
  `_recompute`; caching additionally makes background sync / reload no-ops when
  data is unchanged.

### R5 — Keyboard navigation simplification
- In `_rebuild`, precompute each visible node's grid neighbors
  (up/down/left/right) once, using the existing directional preference rules
  (same column → closest column → closest row for up/down; same row → closest
  column for left/right — current `on_key` lines 708–766). Store the neighbor
  pr_ids on the `PRNode` (`neighbor_up/down/left/right`), satisfying "each node
  knows its grid neighbors".
- `TechTree.on_key` (kept central on the focusable container) looks up the
  current node's neighbor for the pressed direction instead of running the
  candidate-finding loops. None → `_scroll_to_edge(direction)` (unchanged).
  `J/K` plan-jump, `enter` (PRSelected + edit), and hidden-label handling are
  preserved.

## 2. Implicit Requirements

- **Public/used API preserved** (greps of `tree.*` across `pm_core/tui`):
  attributes `_prs, _hidden_plans, _hide_closed, _hide_merged, _status_filter,
  _sort_field`; methods `_recompute, advance_animation, apply_project_settings,
  focus, get_plan_display_name, get_selected_plan, refresh, select_pr,
  update_plans, update_prs`; properties `selected_pr_id,
  selected_is_hidden_label`. `selected_pr_id` is also *assigned* in tests
  (`test_companion_pane.py`) — keep it settable or tolerate assignment.
- **Module-level exports preserved**: `STATUS_ICONS, STATUS_STYLES, STATUS_BG`
  (test_tech_tree_status.py asserts exact values & full status coverage),
  `STATUS_FILTER_CYCLE`, `VERDICT_MARKERS/STYLES`, `SPINNER_FRAMES`,
  `qa_pane_state` (test_tech_tree_qa_spinner.py), `PRSelected`, `NODE_W/H,
  H_GAP, V_GAP`, and re-exported `SORT_FIELDS/SORT_FIELD_KEYS`.
- **`tech_tree.py` stays in `test_closure_free_names.py`'s MODIFIED list** —
  no undefined free names in any function/closure after the rewrite.
- **`selected_index` semantics**: still an index into `_ordered_ids`
  (real ids + `_hidden:` virtual ids). Selection change refreshes only the old
  and new node widgets (not the whole tree) and re-scrolls via
  `_scroll_selected_into_view` (kept).
- **Empty states** (no PRs / filtered-empty / all-hidden / hidden-labels-only)
  currently returned from `render()`. With a child-widget tree there is no grid
  `render`; mount a single message `Static` (and, for hidden-labels-only, the
  bottom labels) covering these four branches (current lines 304–318, 683–694).
- **Explicit sizing**: set `TechTree.styles.width/height`, `EdgeCanvas` and
  each `PlanGroup` size, to the computed content extent (`get_content_width`
  /`get_content_height` math, lines 277–301) on every `_rebuild`. CSS
  `TechTree { height: auto; width: auto; padding: 1 2; }` → drop `auto`
  (auto can't measure absolute children); keep `padding: 1 2`. Node/edge/label
  offsets are relative to the padded content box, so they stay mutually
  aligned.
- **Wide-char handling** (cell_len padding, continuation cells) preserved in
  `PRNode.render()` for emoji like 🧪.
- **app references** (`app._review_loops, _merge_input_required_prs,
  _pane_idle_tracker`, `auto_start.is_enabled/get_target`) accessed from
  `PRNode` via `self.app` exactly as the current `render()` does via
  `self.app`.

## 3. Ambiguities

- **A1 [resolved]** "Collapse/expand becomes show/hide on a container instead
  of recomputing." Taken as the *internal* collapse mechanism. The existing
  user-facing `x` hide-plan UX (reflow + navigable bottom labels) is preserved
  because (a) changing it to leave blank gaps regresses UX and (b) the stated
  perf goal (idle CPU from the 1 s timer) is fully met by R1+R4 regardless,
  since the timer never recomputes or full-refreshes.
- **A2 [resolved]** Nodes focusable vs central key handling. Keep `on_key`
  central on the focusable `TechTree` container (preserves `PRSelected`
  message posting and avoids per-node focus churn); R5's "node knows its
  neighbors" is satisfied by storing neighbor ids on each `PRNode`.
- **A3 [resolved]** "Per-plan scrolling regions" (R2) — described as enabled,
  not required now. PlanGroup containers make it possible later; this PR keeps
  the single `TreeScroll` viewport and `scroll_to_region` navigation.
- **A4 [resolved]** Plan label ownership — placed inside its `PlanGroup` as a
  `PlanLabel` child (literal reading of "container holding its PR nodes + plan
  label") rather than on the edge canvas.
- **A5 [resolved] — cross-band edges.** Prototyping revealed a hard Textual
  constraint: a transparent container occludes lower layers across its *entire*
  region (even space cells). So a single global bottom `EdgeCanvas` cannot show
  through the `PlanGroup` containers that wrap nodes. The working composition is
  one `EdgeCanvas` *inside* each `PlanGroup` (group declares
  `layers: edges nodes`), drawing that band's arrows band-relative. Nodes are
  grouped by **band** (the contiguous row range a plan owns) rather than by raw
  `pr["plan"]`, because `_apply_plan_grouping` remaps rows by each PR's own
  plan. Consequence: when a PR `depends_on` a PR in a *different plan*, the two
  land in different bands and the dependency **arrow is not drawn across bands**
  (the old monolithic grid drew a long arrow crossing plan-label rows). This is
  an accepted trade-off — cross-plan dependencies are uncommon, the old
  cross-band arrows were visually ambiguous, and preserving them would defeat
  the per-group layering that requirements R2/R3 call for. Intra-plan edges
  (the overwhelming majority) render identically to before. Requirement R3
  ("dedicated EdgeCanvas widget … cache aggressively") is satisfied by the
  per-band `EdgeCanvas` instances (one cached arrow layer per group).

No **[UNRESOLVED]** ambiguities.

## 4. Edge Cases

- **Hidden-labels-only / no visible nodes**: mount message/bottom-label
  widgets; EdgeCanvas + PlanGroups empty or absent. `selected_index` may point
  at a `_hidden:` virtual id (no PRNode) — neighbor nav and scrolling for those
  use the existing hidden-label code paths.
- **Selection out of range** after filter/hide shrinks the list — clamp in
  `_recompute` (current lines 223–224).
- **Cross-plan dependency edges**: per the resolved ambiguity **A5**, edges are
  drawn by a per-band `EdgeCanvas` *inside* each `PlanGroup`, not a single
  global canvas. A dependency whose endpoints land in different plan bands is
  therefore **not** drawn (each band owns only its own edges) — an accepted
  trade-off. Intra-plan edges (the overwhelming majority) render identically to
  before. (Supersedes the earlier draft of this bullet, which assumed one
  global EdgeCanvas in global coords.)
- **Auto-start target `◎`** and **merge `⏸M`** markers: auto-start handled in
  `PRNode.render()`; merge-input marker is part of `_get_loop_marker` (moves to
  `PRNode`), and such PRs must be included in `refresh_active_nodes()`. The
  auto-start target is often a *pending* node (not "active"), and toggling
  auto-start changes no PR data, so auto-start `(enabled, target)` is part of
  the **layout signature** (`_auto_start_sig`) — toggling/repointing triggers a
  rebuild that paints or clears the `◎`. (Without this the marker would only
  appear on the next genuine PR-data change.)
- **Resize**: `app._recompute_tree_layout` (app.py 490–496) calls
  `tree._recompute()` + `refresh(layout=True)`; viewport width is part of the
  layout signature so a width change invalidates the cache and rebuilds.
- **Rapid `update_prs`** from background sync with identical data → signature
  unchanged → full no-op (R4 win).
- **0444 project.yaml / atomic writes**: unaffected (no file writes here).

## 5. Implementation outline

1. Add `PRNode`, `PlanGroup`, `PlanLabel`, `EdgeCanvas` widget classes in
   `tech_tree.py`; move drawing code into them. Keep all module constants.
2. Rework `TechTree` from a `render()` widget into a container that, on
   `_recompute` (signature-gated) → `_rebuild`: clears children, sizes itself
   + canvas + groups, mounts EdgeCanvas, mounts a PlanGroup per plan with its
   PRNodes + label, precomputes neighbor maps, mounts empty-state/bottom-label
   widgets as needed.
3. Replace `on_key` candidate loops with neighbor lookups; keep J/K/enter and
   `_scroll_*` helpers. Selection change refreshes only old+new nodes.
4. `_refresh_tech_tree` → advance_animation + `refresh_active_nodes()`.
5. Keep `qa_pane_state`, `_get_loop_marker` (on PRNode), and all public
   methods/attrs intact.
6. Tests: keep existing passing. Add `tests/test_tech_tree_widgets.py` using
   `App.run_test` to assert: (a) one `PRNode` mounted per visible PR with
   correct offset; (b) one `EdgeCanvas`; (c) PlanGroup per plan; (d) spinner
   tick refreshes only active nodes (no recompute) — assert `_recompute` not
   called / layout signature unchanged; (e) neighbor maps match the old
   directional rules on a small fixture; (f) layout cache: identical
   `update_prs` does not rebuild widgets.

## Verification
- `pytest tests/test_tech_tree_status.py tests/test_tech_tree_qa_spinner.py
  tests/test_tree_layout.py tests/test_closure_free_names.py
  tests/test_tech_tree_widgets.py`
- Launch the TUI, confirm: tree renders identically (nodes, edges, plan
  labels, selection box, markers/spinners), arrow + hjkl + J/K nav works,
  hide/show (`x`), filter (`f`), sort (`F`), toggle-merged (`X`) work, and a
  running loop animates spinners without full-tree repaint (idle CPU drop).

## QA focus — navigation lag
Verify nav lag is reduced versus master. Measured per-keystroke render cost
dropped from ~0.5–1.4 s (monolithic full-grid repaint) to ~0.26 s/key with the
widget split (selection change repaints only the old+new node).

**Important caveat — separate pre-existing bottleneck.** On large projects the
dominant nav cost is NOT the repaint: `pr_view.handle_pr_selected` calls
`store.locked_update` on *every* selection change, rewriting the entire
`project.yaml` (here 1 MB / 359 PRs) to persist `active_pr`. With pure-Python
YAML that dump alone is ~1.2 s, and the full lock+read+fsync round-trip
measures ~2.7 s/key — so end-to-end nav is ~3 s/key regardless of the repaint
fix. Measured: with the persistence write nav = ~3026 ms/key; with it mocked
out = ~259 ms/key.

**Update (2026-05-22):** the complementary disk-decouple PR **pr-b4b68f3**
("decouple TUI in-memory state from project.yaml via coalescing write queue",
commit 6003301e) has now **landed in master** and is merged into this branch.
The persistence write is no longer synchronous — it goes through
`store.WriteQueue`, so the ~2.7 s/key disk cost is off the keystroke path. QA
should therefore see *both* fixes together and measure end-to-end nav near the
~0.26 s/key repaint floor. Still test on a large `project.yaml`; if nav is
slow, attribute the lag correctly (repaint vs write-queue drain vs something
new).
