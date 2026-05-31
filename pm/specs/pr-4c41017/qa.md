# QA Spec: Refactor TechTree — split PR nodes into individual Textual widgets

PR: pr-4c41017 (#131) · Plan: tui-ux · Base: master

## Overview

The TechTree TUI widget was rewritten from a single monolithic `render()`
that painted the whole ~120-node grid every frame into a compositional tree
of Textual widgets: one `PRNode` per PR (absolute positioning), one
`PlanGroup` container per plan band, a cached `EdgeCanvas` per band for
dependency arrows, and a focusable `TechTree` container that owns layout,
caching, and navigation. Three perf mechanisms ride along: layout-signature
caching (skip recompute when inputs unchanged), per-active-node spinner
refresh on the 1 s poll, viewport band-culling on scroll, frame capture moved
off the event-loop thread, and a 1.5 s coalescing write-queue debounce.

This spec is grounded in observable TUI/CLI behavior. The widget split must be
**behavior-preserving**: a user navigating, filtering, sorting, hiding, and
watching loops run should see the same tree they saw on master — only faster
and without the idle-CPU full-tree repaint.

## Shared resources touched by the diff

- **The tech tree pane (`#tech-tree`)** — the single shared visual surface
  driven by keyboard nav, the 1 s review-loop poll timer, the 5-min background
  sync, programmatic selection (command bar / `select_pr`), SIGUSR1 reload, and
  resize. Multiple async drivers mutate/repaint it.
- **`pm/project.yaml`** — written through `store.WriteQueue` (debounce 1.5 s)
  on selection changes, flushed synchronously on exit; also read/written by
  CLI commands, background sync, and external SIGUSR1 reload. Single on-disk
  file with many concurrent writers.
- **`tmux capture-pane` frame capture** — now run on a worker thread with a
  single-flight `_capture_in_flight` guard; bursts of moves contend on it.
- **Review-loop state (`app._review_loops`) and the 1 s poll timer** — read by
  every active `PRNode.render()` and by `refresh_active_nodes()`.
- **Perf log `~/.pm/debug/<session>-perf.log`** — opt-in (`PM_PERF_DEBUG=1`).

## 1. Requirements (Given / When / Then)

### R1 — Tree renders identically to master
- **Given** a project with several PRs across multiple plans with a dependency
  chain, **When** the user opens the TUI, **Then** the tech tree shows one box
  per PR (id/#number line, title, status+icon), dependency arrows between
  dependent PRs, and `── plan name ──` rules separating plan groups — the same
  visual layout master produced.

### R2 — Keyboard grid navigation (arrows + hjkl)
- **Given** the tech tree is focused with a node selected, **When** the user
  presses up/down/left/right (or k/j/h/l), **Then** selection moves to the grid
  neighbor in that direction (preferring same column for up/down, same row for
  left/right), the newly selected node draws a double-line highlighted border,
  the previously selected node reverts to a single-line border, and the
  selected node scrolls into view.
- **Given** the selected node is at the top/bottom/left/right edge of the grid,
  **When** the user presses the key continuing past that edge, **Then** the
  viewport scrolls toward that edge and selection stays put (no wrap).

### R3 — Plan-jump navigation (J / K)
- **Given** a multi-plan tree with a node selected mid-plan, **When** the user
  presses `J`, **Then** selection jumps to the first PR of the next plan group
  and that plan's label scrolls to the top of the viewport.
- **Given** selection is on the last plan group, **When** the user presses `J`,
  **Then** selection moves to the visual bottom-most PR of that plan.
- **Given** selection is mid-plan, **When** the user presses `K`, **Then**
  selection jumps to the top PR of the current plan; pressing `K` again jumps
  to the previous plan group.

### R4 — Enter opens edit
- **Given** a PR node is selected, **When** the user presses Enter, **Then**
  the edit/plan action opens for that PR (same as the `e` action).

### R5 — Hide / show plan groups (x)
- **Given** a node in a plan group is selected, **When** the user presses `x`,
  **Then** that plan's PR nodes disappear from the grid, the remaining plans
  reflow upward, and a navigable `── plan name (hidden, N PRs) ──` label
  appears at the bottom of the tree.
- **Given** a hidden-plan label is selected, **When** the user presses `x`,
  **Then** the plan's nodes reappear in the grid and the tree reflows.

### R6 — Status filter (f)
- **Given** PRs span multiple statuses, **When** the user cycles the status
  filter with `f`, **Then** the grid shows only PRs matching the current filter
  status (and the layout reflows to those nodes); cycling back to "all" shows
  every PR again.

### R7 — Sort preserves the selected PR (F)
- **Given** a specific PR is selected, **When** the user cycles the sort field
  with `F`, **Then** the nodes reorder by the new sort field **and the cursor
  stays on the same PR** (not on whatever node now occupies the old index), and
  a sort-mode status message is shown.

### R8 — Toggle merged PRs (X)
- **Given** the project contains merged PRs, **When** the user presses `X`,
  **Then** merged PRs are hidden/shown accordingly and the grid reflows.

### R9 — Live spinners/markers on running work without full repaint
- **Given** one or more PRs are in progress / in review / qa with a running
  agent, or have an active review loop, **When** time passes (the 1 s poll
  ticks), **Then** the activity spinner / loop marker (`⟳N`, `⏸`, `⏸M`, verdict
  marker) animates on those nodes' status lines while the rest of the tree
  stays static — and idle CPU stays low (the poll no longer repaints the whole
  tree).

### R10 — Auto-start target marker (A)
- **Given** auto-start is enabled and points at a target PR, **When** the user
  toggles auto-start or it repoints, **Then** a `◎` marker appears on (or
  clears from) the target node's id line — even when the target is a pending
  (non-active) node.

### R11 — Programmatic selection scrolls to the PR
- **Given** the TUI is open, **When** the user selects a PR from the command
  bar / picker (or any non-keyboard path that calls select_pr), **Then** the
  cursor moves to that PR, scrolling it into view; if the PR is in a hidden
  plan, the plan auto-expands first.

### R12 — Navigation latency reduced on large projects
- **Given** a LARGE `project.yaml` (hundreds of PRs, ~1 MB), **When** the user
  holds/repeats j/k to navigate, **Then** each keystroke repaints promptly
  (sub-second, near the ~0.26 s repaint floor) rather than the ~3 s/key seen on
  master — selection keeps up with input, no multi-second freeze per key.

## 2. Setup

Use the **TUI Manual Testing** instruction (`tui-manual-test.md`):
1. Install the editable clone into a venv; confirm `pm which` points at the
   clone (not `/opt/pm-src`); set `PYTHONPATH` to the clone.
2. Create a throwaway git project, `pm init --backend local --no-import`.
3. Add PRs via `pm pr add ... --depends-on ...` to build a multi-plan tree
   with dependency chains. To get a mix of statuses (merged, in_review, qa,
   in_progress) for the initial fixture, edit `pm/project.yaml` once during
   bootstrap only; thereafter drive everything through the CLI/TUI.
4. For perf scenarios, generate a LARGE project (hundreds of PRs across
   several plans with dependencies) — scriptable with a loop of `pm pr add`.
5. Start with `pm session 2>/dev/null || true`; drive with `pm tui send` /
   `tmux send-keys`; observe with `pm tui view` / `tmux capture-pane`.
6. Run pm CLI for concurrent scenarios from a **new pane inside the test tmux
   session**, not the host shell.

## 3. Edge Cases (Given / When / Then)

### E1 — Empty / degenerate trees
- **Given** a freshly initialized project with no PRs, **When** the TUI opens,
  **Then** a "No PRs defined…" message shows (no crash, no stray boxes).
- **Given** a status filter that matches zero PRs, **When** the filter is
  applied, **Then** a "No <status> PRs…" message shows.
- **Given** every plan is hidden, **When** the user views the tree, **Then**
  the "All PRs hidden (N plan(s))…" message shows, and each hidden plan still
  appears as a navigable bottom label the user can select and unhide
  individually.

### E2 — Cross-plan dependency edges not drawn
- **Given** a PR that `depends_on` a PR in a *different* plan, **When** the user
  views the tree, **Then** intra-plan arrows render normally but the cross-plan
  arrow is **not** drawn (accepted per impl A5) — and crucially nothing crashes
  or mis-renders, and navigation between the two PRs still works.

### E3 — Selection clamped after the list shrinks
- **Given** a node near the bottom is selected, **When** a filter/hide removes
  enough nodes that the old index is out of range, **Then** selection clamps to
  a valid node (no crash, no blank selection).

### E4 — Resize
- **Given** the TUI is open on a multi-column tree, **When** the terminal/pane
  is resized (width change), **Then** the layout recomputes to the new width,
  nodes/edges/labels stay mutually aligned, and selection is preserved.

### E5 — Viewport culling on scroll
- **Given** a tree taller than the viewport, **When** the user scrolls (keyboard
  nav, J/K, or mouse wheel) so some plan bands leave the viewport, **Then**
  off-screen bands are not drawn but the scroll extent (scrollbar size) does
  not change, and scrolling back reveals the bands intact with correct content.

### E6 — Rapid identical data refresh is a no-op
- **Given** the tree is displayed, **When** a background sync delivers PR data
  identical to what is shown, **Then** the tree does not flicker/rebuild and
  selection/scroll position are preserved (layout-signature cache hit).

### E7 — Wide-character titles
- **Given** a PR whose title or status contains a wide/emoji char (e.g. 🧪),
  **When** its node renders, **Then** the box borders stay aligned (no
  off-by-one from the double-width cell).

### E8 — Frame-capture single-flight under burst
- **Given** the TUI runs inside tmux, **When** the user moves selection rapidly
  (each move triggers two capture requests), **Then** navigation never stalls
  for multiple seconds waiting on `tmux capture-pane`, and overlapping captures
  are dropped rather than queued.

## 4. Concurrent-use scenarios

### C1 — Navigate while a review loop / spinners animate
Two drivers on `#tech-tree`: the 1 s poll repainting active nodes and the user
navigating. Expect: spinners keep animating on active nodes, selection moves
crisply, no full-tree repaint, no lost keystrokes, no exception in the log.

### C2 — CLI mutation while navigating (write queue + reload)
A CLI command in another pane mutates a PR (e.g. `pm pr edit` / status change)
while the user navigates the TUI. Expect: the in-TUI selection write coalesces
through the 1.5 s write queue without per-key full-file rewrites; the external
change surfaces on the next reload/sync without clobbering the user's selection;
`project.yaml` stays valid (no corruption from concurrent writers).

### C3 — Background sync during navigation
The 5-min background sync (or a manually triggered sync) runs `update_prs`
while the user navigates. Expect: if data is unchanged the tree doesn't rebuild
(selection/scroll preserved); if data changed, the tree rebuilds once and
selection is preserved/clamped sensibly.

## 5. Pass/Fail Criteria

PASS when:
- The tree renders the same nodes, edges, plan labels, and selection styling as
  master (R1), and all navigation (R2/R3/R4), hide/show (R5), filter (R6), sort
  with cursor-preservation (R7), toggle-merged (R8), live markers (R9), and
  auto-start marker (R10) behave as their Then clauses describe.
- Programmatic selection scrolls and auto-expands hidden plans (R11).
- On a large project, per-key nav is sub-second with no multi-second freeze
  (R12); idle CPU does not spike from a 1 s full-tree repaint (R9).
- All edge cases (E1–E8) behave without crashes, misalignment, or stuck
  selection; concurrent scenarios (C1–C3) preserve selection and file integrity.

FAIL when:
- Any node/edge/label is missing, misaligned, duplicated, or mis-styled vs
  master; selection lands on the wrong PR after sort/filter/hide; a marker
  fails to appear/clear; the tree blanks out (e.g. a recompute that bails
  pre-mount leaving no children); navigation stalls for seconds per key; a
  background sync or concurrent CLI write corrupts `project.yaml` or throws;
  an exception appears in the TUI log during any flow.

## 6. Ambiguities (resolved)

- **A1** "Render identically" — interpreted as visual/behavioral equivalence of
  the user-facing tree (nodes, edges, plan labels, markers, selection), **with
  the documented exception** that cross-plan dependency arrows are intentionally
  no longer drawn (impl A5). QA treats a missing cross-plan arrow as expected,
  not a regression; a missing intra-plan arrow is a regression.
- **A2** Hide semantics — `x` keeps master's reflow + navigable bottom-label
  UX; the PlanGroup `display` toggle is internal. QA validates the bottom-label
  UX, not blank-gap collapse.
- **A3** Perf targets — the ~0.26 s/key repaint floor and ~3 s→sub-second
  improvement are directional; QA confirms the qualitative win (nav keeps up,
  no per-key multi-second freeze) on the real tmux surface, since headless
  `run_test` timing is unreliable (pilot.pause waits on the write-queue thread).
- **A4** "Idle CPU" — verified qualitatively: a running loop animates only the
  active nodes and the 1 s tick does not trigger a whole-tree repaint /
  recompute; exact CPU % is environment-dependent.

No **[UNRESOLVED]** ambiguities.
