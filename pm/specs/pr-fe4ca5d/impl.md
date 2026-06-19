# Spec: prefix-key plan picker popup

## Requirements

1. **New popup launched from a prefix binding**, parallel to the PR
   picker at `pm_core/cli/session.py:1526` (`popup_picker_cmd`).
   - Add a new kind to `_POPUP_KINDS` (session.py:74) and a new body
     constant analogous to `_POPUP_PICKER_BODY` (session.py:59) that
     invokes `pm _popup-plans <S>`.
   - Add a binding in `_bind_popups()` (session.py:81). Use **prefix+L**
     (mnemonic "pLans"; uppercase to mirror the existing `P`, `M`, `R`
     prefixes and avoid colliding with tmux's lowercase defaults). The
     binding calls `pm _popup-show plans`, reusing the dynamic-width
     dispatcher at `popup_show_cmd` (session.py:720).

2. **One row per plan, no per-action subrows.** Row format:
   `<plan-id>: <name> [<status>] (<n PRs, m merged, k pending>)`
   computed from `data["prs"]` filtered by `pr.get("plan") == plan_id`.
   Status comes from `plan.get("status", "draft")`. Read counts
   directly off project.yaml — `_pr_display_id`-based filtering is not
   needed (we count entries, not display ids).

3. **Single-key shortcuts** mirroring the PR picker's `_SHORTCUT_KEYS`
   table (session.py:1641). For plans:
   - `r` — review  → `plan review <id>`
   - `b` — breakdown → `plan breakdown <id>`
   - `e` — edit → `plan edit <id>` (open plan file in `$EDITOR`; see
     ambiguity #1)
   - `v` — view → `less <plan_file>` (read-only)
   - `d` — deps → `plan deps`
   - `l` — load → `plan load <id>`
   - `f` — fix → `plan fix` (fixes apply across plans, see #2)
   - Enter — default action: review.
   - `q`/`Esc` — dismiss.

4. **Navigation:** `j`/`k` and Up/Down highlight rows. fzf handles both
   keys natively when `--bind=j:down,k:up` is added; without that,
   only Up/Down are wired by default. We add the j/k binds explicitly.

5. **Filter:** `/` opens fzf's search prompt. fzf supports this via the
   `change-prompt`/`toggle-search` actions, but the simpler path is to
   leave fzf in normal interactive mode (default `/` opens search) when
   `--no-input` is **off**. The PR picker disables input to suppress
   echo of unrecognized keys; for plans we likewise disable input but
   bind `/` to `show-input` so the user can opt into filtering. Fall
   back to substring match in the numbered renderer.

6. **Vertical scrolling when overflow.** fzf handles this natively via
   `--height=100%` with more entries than visible rows; the highlighted
   row scrolls into view. Single-key actions act on whichever row is
   currently highlighted (`fzf` returns it on `--expect`).

7. **Horizontal scrolling.** fzf truncates long lines with `~` by
   default; the `--no-hscroll`/default behavior shows ellipsis when
   overflow occurs. Numbered fallback truncates with `…` to terminal
   width.

8. **Reuse popup scaffolding:**
   - `_resolve_root_from_session` (session.py:1512) for project root.
   - `_run_picker_command` (session.py:1472) for dispatch — the `tui:`
     prefix routes through `trigger_tui_command` to the TUI command bar.
   - `_fzf_supports_no_input` (session.py:1138).
   - `_wait_dismiss` (session.py:1436) for error/info pause.
   - `_make_fzf_cmd`-style binding of unused alpha keys to `ignore`.

9. **Action dispatch.** Per the PR description, this PR depends on
   pr-fcaa434 (plan subcommands manage their own tmux windows). Until
   that lands, dispatching `pm plan review <id>` directly would launch
   Claude inline in the popup pane. To avoid that, route plan actions
   through the TUI command bar (`tui:plan review <id>`), which already
   has tmux-aware launchers via `pane_ops.handle_plan_action`
   (`pm_core/tui/pane_ops.py:630`). The popup's `_run_picker_command`
   already supports `tui:` prefixes.

   The TUI's `handle_command_submitted` (`pm_core/tui/pr_view.py:529`)
   currently doesn't dispatch `plan review`/`plan breakdown`/`plan edit`/
   `plan deps`/`plan load`/`plan fix`. **Add a small router there** that
   maps these commands to `pane_ops.handle_plan_action` with the
   matching action name and plan_id. `plan add` is already handled
   (pr_view.py:679); we leave it alone.

10. **Bind via `_bind_popups`.** Add a third `bind-key` call invoking
    `pm _popup-show plans`. The popup body queries tmux for session
    name and dispatches to `pm _popup-plans "$S"`.

## Implicit Requirements

- The popup must work from any pane (PR window, plans window, or
  unrelated shell), so unlike the PR picker it does not need a
  current-window context.
- The selected highlight must persist while the user scrolls, and the
  shortcut keys must dispatch against whichever plan is highlighted at
  the moment of the keypress — `fzf --expect` returns the currently
  highlighted entry alongside the key, so this falls out for free.
- `pm _popup-plans` must set `PM_PROJECT` so subprocess `pm` calls
  resolve the right project (mirrors `popup_picker_cmd`).
- `view` and `edit` actions cannot route through the TUI's existing
  `handle_plan_action` directly — `view` has no entry there. Add a new
  action key `"view"` to `pane_ops.handle_plan_action` that opens the
  plan file with `less` in a per-plan window (mirrors
  `launch_plan_activated` at pane_ops.py:674).
- `fix` similarly has no entry. Route it the same way the TUI runs
  cross-plan actions: a synthetic plan id (e.g. `_FIX_PSEUDO_PLAN_ID =
  "plan-fix"`) and `_launch_in_plans_window(... f"pm plan fix", "plan-fix")`.

## Ambiguities

1. **`plan edit` semantics.** The PR description says `pm plan edit
   <id>` *or open the plan file*. There is no `pm plan edit` CLI
   subcommand. Resolution: open the plan file in `$EDITOR` via
   `pane_ops.handle_plan_action(app, "edit", plan_id)`, which already
   does this (pane_ops.py:632–639). The popup sends `tui:plan edit
   <id>` and the new TUI router calls `handle_plan_action`.

2. **`plan fix` semantics.** `pm plan fix <review_path>` (plan.py:669)
   takes a review path — it's not parameterized by plan id. The popup
   uses the highlighted plan as context but the underlying CLI doesn't.
   Resolution: dispatch `plan fix` (no args) and let the existing
   command pick the most recent review. The popup's `f` shortcut is
   thus plan-agnostic but available alongside the others.

3. **Binding key.** Description says "prefix+L or prefix+B — bikeshed".
   Resolution: pick **prefix+L** (uppercase). Mnemonic "pLans"; matches
   the existing `P`/`M`/`R` capitalized convention and doesn't shadow
   any default tmux binding we already use.

4. **Default action on Enter.** Description says "review". Resolution:
   Enter on a row dispatches `plan review <id>`.

5. **Cross-plan actions (`d` deps, `f` fix) when no plan list exists.**
   Resolution: still allow these from the popup — they don't need a
   highlighted plan. If the plan list is empty, render an empty popup
   with the cross-plan actions shown in the header so the user can
   still press `d`/`f`.

## Edge Cases

- **No plans in project.yaml.** Show the popup with a "No plans" message
  but allow `d`/`f` for the cross-plan actions, plus `q` to dismiss.
- **fzf not installed.** Numbered fallback list, with shortcut hints,
  same `input("Select [1-N] or shortcut key: ")` pattern as the PR
  picker fallback (session.py:1820+).
- **TUI not running.** `trigger_tui_command` returns False; the popup
  prints "Could not reach the TUI" via `_run_picker_command`'s existing
  branch (session.py:1485) and pauses. This is a known limitation
  documented at the call site.
- **PR window patterns / current_pr context.** Not applicable — the
  plan popup has no concept of "home plan". No `0` binding, no `h/l`
  cross-plan navigation chord (`b` is breakdown, `l` is load, both used).
- **Long plan names.** fzf truncates; the numbered fallback truncates
  with `…` to fit terminal width (best-effort: 80 cols default).
- **Plan with no PRs loaded.** Counts show `(0 PRs)`.

## Implementation Plan

1. `pm_core/cli/session.py`:
   - Add `_POPUP_PLANS_BODY` constant.
   - Add `"plans": ("80%", _POPUP_PLANS_BODY)` to `_POPUP_KINDS`.
   - Add `bind-key prefix L → run-shell 'pm _popup-show plans'` in
     `_bind_popups`.
   - Add `popup_plans_cmd` (`@cli.command("_popup-plans", hidden=True)`)
     that loads plans, builds rows with PR counts, runs fzf with the
     plan-shortcut `--expect` set and j/k binds, and dispatches via
     `_run_picker_command(f"tui:plan {action} {plan_id}", session)`.

2. `pm_core/tui/pr_view.py`:
   - Extend `handle_command_submitted` to recognize `plan review|
     breakdown|edit|view|load|fix|deps [<id>]` and dispatch to
     `pane_ops.handle_plan_action`.

3. `pm_core/tui/pane_ops.py`:
   - Add `view` action branch to `handle_plan_action` that runs
     `less <plan_file>` in the per-plan window.
   - Add `fix` action branch (cross-plan, synthetic id) that runs
     `pm plan fix` in its own window.

## Test Plan

- `pm session start` (or attach to existing); press prefix+L → popup
  appears with plan list.
- Highlight a plan, press `r` → existing plan-review window for that
  plan is selected (or a new one created); popup closes.
- Add many plans (≥ visible rows), scroll to one off-screen, press `r`
  → action runs against the highlighted plan.
- Press `/`, type a substring, Enter → narrows; pressing `r` after
  filter still works.
- With no fzf on PATH (`PATH=/usr/bin:/bin`), the numbered fallback
  appears and shortcuts dispatch correctly.
- Press `d` → `pm plan deps` opens; press `f` → `pm plan fix` opens.
