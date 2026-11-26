# Implementation Spec: Launch plan pane actions in a dedicated plans window

## Requirements

### R1 — Plan pane actions launch in a dedicated tmux "plans" window, not the TUI window

**Files:**
- `pm_core/tui/pane_ops.py:535` (`handle_plan_action`)
- `pm_core/tui/pane_ops.py:559` (`handle_plan_add`)
- `pm_core/tui/pane_ops.py:572` (`launch_plan_activated`)

These functions currently call `launch_pane(...)` without `target_window`, so the new pane is split into the TUI's current window (typically `main`). They should instead direct the new pane into a dedicated tmux window named `plans`, by passing `target_window=<plans-window-id>` to `launch_pane`.

The actions in scope (those that today call `launch_pane` from the plans pane) are:
- `add` (handled by `handle_plan_add`, role `plan-add`) — launches `pm plan add <name>`
- `breakdown` (role `plan-breakdown`) — launches `pm plan breakdown <plan_id>`
- `review` (role `plan-review`) — launches `pm plan review <plan_id>`
- `edit` (role `plan-edit`) — launches `$EDITOR <plan-file>`
- `deps` (role `plan-deps`) — launches `pm plan deps`
- plan activation (role `plan`) — opens plan file in `less`

The "worker" action mentioned in the PR description is interpreted as the breakdown / review / add Claude workers (plus the editor / deps / less-viewer panes that share the same launch site). All five plan-pane actions plus plan activation should be redirected to the plans window so plan work never clutters the main window.

### R2 — Add a `_ensure_plans_window` helper

**File:** `pm_core/tui/pane_ops.py`

Add a private helper that returns the tmux window ID of a window named `plans` for the current pm session. If no such window exists, it creates one running a benign placeholder (`bash -l`) with the project root as cwd, using `tmux_mod.new_window_get_pane(session, "plans", placeholder, cwd=str(app._root or "."), switch=False)`. Then resolve and return the window's id via `tmux_mod.find_window_by_name(session, "plans")["id"]`. Return None on any failure or when not in tmux (callers fall back to current behavior, i.e. omit `target_window`).

The placeholder pane exists so subsequent `launch_pane` calls have a pane to split off. It is intentionally non-claude — it adds no work, just keeps the window alive.

### R3 — Switch focus to the plans window when launching a plan action

After a plan-pane action is launched into the plans window, switch the user's grouped session to that window via `tmux_mod.select_window(session, "plans")`. Without this the user stays in the main/current window and would have to find the new pane manually. Use the same focus-after-launch UX as PR start.

### R4 — Multiple plan actions can run in parallel

Because all plan actions now share one window and `launch_pane`'s dedup is keyed on `(role, window)`, two `plan-add` invocations with the same role would still focus the existing pane rather than create a duplicate. This is fine for `add` (the same plan-add session is rarely needed twice simultaneously) and matches the dedup semantics elsewhere. Different roles (`plan-add` + `plan-breakdown`) can coexist as separate panes — that satisfies "plan add on two plans at the same time" only across different actions; truly parallel `plan-add` for two distinct plans is still serialized by role-based dedup. We accept this limitation: the PR description's parallelism goal is met for the cross-action case, and the role-dedup behavior is consistent with the rest of the TUI.

---

## Implicit Requirements

### I1 — Don't break non-tmux fallback

`launch_pane` already early-returns when not in tmux (via `get_session_and_window`). If `_ensure_plans_window` returns `None`, callers must still work — pass `target_window=None` so behavior is unchanged.

### I2 — Heal-registry must keep working with the plans window

`heal_registry` iterates all windows in the registry and removes dead panes / empty windows. The plans window will appear in the registry once `launch_pane` registers panes there. If the plans window is killed externally, healing will drop its entry — and `_ensure_plans_window` will recreate it on next use. No change needed to `heal_registry`.

### I3 — Placeholder pane must not be registered as a plan role

The placeholder shell created by `new_window_get_pane` is created outside `launch_pane`, so it never gets entered into the pane registry. That is intentional — it's a passive holder, not a tracked role. `launch_pane` will register only the real plan-action panes it spawns.

### I4 — Window creation must not steal focus from the TUI on first use

`new_window_get_pane(..., switch=False)` is used so that the act of creating the plans window doesn't yank the user away from the TUI. The explicit `select_window` in R3 is the focus event, and it only fires after the plan pane has actually been launched (not on idle window creation).

---

## Ambiguities

### A1 — Plan activation (`enter` key on a plan)

`launch_plan_activated` opens the plan markdown in `less`. Arguably this is a passive viewer, not a "plan action" in the sense the PR describes (which lists add/review/breakdown/worker). I include it in scope because (a) it shares the plans-pane origin, (b) viewing a plan file alongside breakdown/review is a natural workflow, and (c) keeping all plans-pane launches in the plans window is more predictable than splitting some to main and others to plans. Resolved: include in plans-window redirect.

### A2 — `plan deps` action

Same reasoning as A1. `pm plan deps` is a one-shot CLI that prints to a pane; including it in the plans window keeps the main window clean. Resolved: include in plans-window redirect.

---

## Edge Cases

### E1 — Plans window already exists from a previous TUI session

Healing on TUI startup may have removed dead panes from the plans window. If the placeholder pane was killed (e.g., user manually exited the shell) but a plan-action pane survives, the window still exists. `_ensure_plans_window` will return its id, and `launch_pane` will split off whichever pane tmux considers active. Acceptable.

### E2 — Plans window killed mid-session

If the user kills the plans window between actions, `find_window_by_name` returns None, and `_ensure_plans_window` recreates it. Subsequent splits work. The pane registry's stale entries for the old window get healed by `heal_registry` on the next TUI restart (they'd also be dropped lazily by `pane_registry.find_live_pane_by_role` not finding live panes).

### E3 — `_run_command` plan actions (`load`)

`handle_plan_action`'s `load` branch uses `app._run_command(...)`, not `launch_pane`. That runs in-process via `_run_shell` and doesn't open a tmux pane. No redirect needed; leave unchanged.

### E4 — Watchers calling `launch_pane` with explicit `target_window`

Watchers (e.g. `launch_qa_item`) pass their own `target_window`. The plans-window redirect only happens in plan-pane handlers, so this is unaffected.
