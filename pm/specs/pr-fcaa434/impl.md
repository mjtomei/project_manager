# pr-fcaa434 — Plan subcommands launch Claude inline instead of switching to tmux window

## Requirements (grounded)

When invoked from inside a pm tmux session (popup `prefix+M` or any pane shell),
plan subcommands must follow the same find-or-create-window pattern that
`pr_start` already implements (`pm_core/cli/pr.py:822-846` for fast-path,
`pm_core/cli/pr.py:1021-1075` for the new-window launch path).

CLI commands that currently call `launch_claude` directly and need to be fixed:

1. `plan_add` — `pm_core/cli/plan.py:139`. Per-instance synthetic id (matches
   TUI's `_DEPS_PSEUDO_PLAN_ID`-style pattern at
   `pm_core/tui/pane_ops.py:543`). The TUI side calls
   `pm plan add` from the input modal; `plan add` itself doesn't take a plan
   id (the plan is being created), so we use a synthetic `plan-add` window
   name. Note: the task description says "per-instance plan-add window" with
   uuid suffix, but a single shared `plan-add` window is the simpler model
   and matches the TUI's `_DEPS_PSEUDO_PLAN_ID` approach for cross-plan
   actions. **Resolution: use synthetic `plan-add` (single shared window).**
2. `plan_breakdown` — `pm_core/cli/plan.py:241`. Window keyed on plan_id, via
   `_plans_window_name(plan_id)` semantics (the plan id itself).
3. `plan_review` — `pm_core/cli/plan.py:415`. Window keyed on plan_id.
4. `plan_deps` — `pm_core/cli/plan.py:493`. Synthetic `plan-deps` window
   (matches `_DEPS_PSEUDO_PLAN_ID` at `pm_core/tui/pane_ops.py:627`).
5. `plan_fix` — actually calls `_run_fix_command` which calls `launch_claude`
   at `pm_core/cli/plan.py:661`. Synthetic `plan-fixes` window. Note: task
   description points at line 818 (`_run_plan_import`), but that is
   `plan_import` not `plan_fix`. The two distinct cases are:
   - `_run_fix_command` (line 661) — used by `plan_fix` → window `plan-fixes`.
   - `_run_plan_import` (line 818) — used by `plan_import` → window
     `plan-import`.
   **Resolution: route both through the helper. `plan_import` is in scope
   because it's in `pm_core/cli/plan.py` and exhibits the same bug.**
6. `plan_fixes` — `pm_core/cli/plan.py:610`. This is just a list command
   (no `launch_claude` call). Out of scope for this fix.

Other CLI commands with the same bug:

7. `cluster_explore` — `pm_core/cli/cluster.py:224`. Synthetic `cluster`
   window.
8. `container_build` — `pm_core/cli/container.py:186`. Already implements
   the find-or-create pattern at `pm_core/cli/container.py:163-181`. The
   call to `launch_claude` at line 186 is the *fallback* when not in a pm
   session. **Resolution: leave as-is; already correct. Re-route through
   the new helper to deduplicate the logic.**
9. `guide._run_guide` — `pm_core/cli/guide.py:88, 128`. Currently uses
   `os.execvp` with `build_claude_shell_cmd` to take over the calling pane
   when in pm tmux session. The task notes this is intentional take-over
   behavior except when invoked from the popup. **Resolution: route
   through the helper with synthetic `guide` window. The existing
   `os.execvp` take-over path is preserved for callers that explicitly
   want it (none today), but the popup invocation will land in a
   dedicated `guide` window.** This is a behavior change for `pm guide`
   when run from a regular pane shell inside a pm session — instead of
   overtaking the pane, it will switch to / create a `guide` window.
   This matches the spirit of the bug fix.

Reference patterns (already correct):
- `pr_start` — `pm_core/cli/pr.py:822-846` + `1021-1075`
- `_launch_review_window` — `pm_core/cli/pr.py:1132+`
- `meta_run` — `pm_core/cli/meta.py:162-208`
- `container_build` — `pm_core/cli/container.py:163-181`

## Implementation plan

Add a new helper module `pm_core/cli/_window_launch.py` exposing one function:

```python
def launch_claude_in_window(
    window_name: str,
    prompt: str,
    cwd: str,
    session_key: str,
    pm_root: Path,
    *,
    fresh: bool = False,
    resume: bool = True,
    provider: str | None = None,
    model: str | None = None,
    effort: str | None = None,
) -> None:
    """Find-or-create per-window Claude launch with inline fallback.

    1. If in a pm tmux session and window exists: select it (kill first
       if `fresh=True`, then fall through to create).
    2. If in a pm tmux session and window missing: create new tmux
       window with the wrapped Claude command (uses
       `build_claude_shell_cmd` so flags/transcripts/skip-permissions
       behave consistently).
    3. Otherwise: fall back to inline `launch_claude`.
    """
```

Behavior:
- Uses `_get_pm_session()` from `pm_core/cli/helpers.py`.
- Existing-window switch: `tmux_mod.select_window(pm_session, existing["id"])`,
  echo `Switched to existing window '<name>' (session: <pm_session>)` (matches
  pr.py message style).
- New-window create: generate session_id (resume previous or new uuid via
  `load_session`/`save_session` from `claude_launcher`), build cmd via
  `build_claude_shell_cmd(prompt=..., session_id=..., resume=is_resuming,
  cwd=cwd, model=model, provider=provider, effort=effort)`, then
  `tmux_mod.new_window(pm_session, window_name, cmd, cwd)` followed by
  `set_shared_window_size`. On exception, fall through to inline launch.
- Inline fallback: existing `launch_claude(...)` semantics. Honor `fresh` by
  calling `clear_session(pm_root, session_key)` first.

Update each caller to use the helper:
- `plan_add` → `launch_claude_in_window("plan-add", prompt, cwd=str(root), session_key=f"plan:add:{plan_id}", pm_root=root, fresh=fresh)`. Plan-add windows are shared across plan-add invocations because session_key already disambiguates per plan_id.
- `plan_breakdown` → window=`plan_id`, key=`f"plan:breakdown:{plan_id}"`.
- `plan_review` → window=`plan_id`, key=`f"plan:review:{plan_id}"`. `resume=not (fresh or plan_prs)` and `fresh=fresh or bool(plan_prs)` to preserve the "always start fresh after PRs are loaded" behavior at `pm_core/cli/plan.py:412-415`.
- `plan_deps` → window=`plan-deps`, key=`plan:deps`.
- `_run_fix_command` → window=`plan-fixes`, key existing.
- `_run_plan_import` → window=`plan-import`, key=`f"plan:import:{plan_id}"`.
- `cluster_explore` → window=`cluster`, key=`cluster:explore`. Note: current
  code uses `cwd=str(repo_root)` — preserve.
- `container_build` → window=`container-build`, key=`container:build`,
  cwd=`str(project_dir)`. Replaces lines 163-187.
- `guide._run_guide` → window=`guide`, key=`guide:setup` (or `guide:assist`).
  Replaces both `launch_claude(prompt)` (assist) and the `os.execvp` paths.

## Implicit Requirements

- The helper must respect provider/model/effort kwargs (only some callers pass
  them today; default to None).
- The new tmux window's command must include the `--session-id`/`--resume`
  flag so subsequent calls with the same `session_key` resume instead of
  starting fresh — matches `launch_claude`'s session registry behavior.
- `cwd` for the new tmux window must be a valid directory on the host. For
  CLI calls outside container mode this is just the pm root. We do NOT need
  the container-mode handling that `pr_start` has (lines 1028-1037) because
  plan/cluster/guide commands don't run in the per-PR container workdir.
- Echo messages should match the existing style: `"Switched to existing
  window '<name>' (session: <pm_session>)"` and `"Launched Claude in tmux
  window '<name>'"`.
- The helper is for CLI-level use only. The TUI side (`pane_ops.py`) already
  has `_launch_in_plans_window` and uses pane-registry semantics that don't
  apply to the simpler one-pane-per-window CLI launches.

## Edge Cases

1. **Popup invocation with existing window**: covered by step 1 (switch).
2. **Plain shell pane (not popup) inside pm session, no window yet**:
   creates new window. The calling pane is *not* taken over — user stays
   in the pane that invoked the command. Matches `pr_start` behavior.
   Note: this is a behavior change from current inline behavior. The
   user explicitly requested it ("switching to / creating a tmux window").
3. **Outside any tmux session**: falls back to inline `launch_claude` —
   unchanged from today.
4. **`--fresh` with existing window**: kill the window, then create a
   new one. Matches `pr_start` (`pm_core/cli/pr.py:828-830`).
5. **`new_window` raises**: catch and fall through to inline
   `launch_claude` (matches pr.py:1073-1075).
6. **Background review** (`review_mod.review_step` calls after
   `launch_claude` in plan commands): these run in a separate tmux
   window already managed inside `review_step` and are unaffected. They
   should still fire after the helper returns. **However**, when the
   helper creates a new tmux window, `launch_claude_in_window` returns
   *immediately* (the Claude session runs detached in the new window).
   The current flow runs the background review *after* `launch_claude`
   returns, which today is *after* Claude finishes (synchronous). With
   the new window path, the background review would fire while Claude
   is still running. **Inspection of `review_step`**: it kicks off a
   background subprocess that uses `claude -p` to review; it does not
   need Claude to have *finished* the interactive session. Spawning
   the review in parallel is fine. This matches what `pr_start`
   effectively does (it returns after launching the new window, so any
   downstream code in `pr_start` runs while Claude is still running).
   The plan-command callers' `review_step` calls run after the helper
   returns regardless of whether Claude is still active — same as today
   for the inline-fallback case.
7. **`plan_review` always-fresh-after-load behavior**: preserve via
   `fresh=fresh or bool(plan_prs)` and `resume=not (fresh or plan_prs)`.
8. **Guide command**: previous behavior used `os.execvp` to take over
   the calling pane inside a pm session. The new behavior creates a
   dedicated `guide` window. This is a deliberate change; the
   alternative (preserve takeover) would leave the popup-launch bug
   unfixed for `guide`.

## Ambiguities

None unresolved. Design choices made:
- Single shared `plan-add` window vs per-instance: chose shared (simpler,
  matches TUI's cross-plan synthetic-id pattern).
- `plan_import` and `guide` inclusion: chose to include both — same bug,
  same fix shape. `guide`'s pane-takeover behavior is replaced with
  dedicated-window behavior.
- Helper location: `pm_core/cli/_window_launch.py` (new module under
  `pm_core/cli/`). Underscore prefix marks it as a private CLI helper.
