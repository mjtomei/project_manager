# Spec: TUI command for PR resource cleanup (pr-f8abc94)

## Goal

Add two ways to tear down all live resources for a PR (across implementation, review,
and QA phases) from the TUI:

1. **Dedicated key** on the selected PR — one keystroke + confirmation, cleans
   everything for that PR.
2. **Prefix modifier** — a key prefix applied before any other PR action so the
   action runs against a freshly cleaned slate (cleanup-then-X).

Both paths invoke the same underlying cleanup primitive.

## What "cleanup" does

For a given PR (`pr_id`, `display_id` from `pm_core.cli.helpers._pr_display_id`):

1. **Tmux windows** — kill via `pm_core.cli.helpers.kill_pr_windows(session, pr)`,
   which already covers `{display_id}`, `review-{display_id}`, `merge-{display_id}`,
   `qa-{display_id}`, and any `qa-{display_id}-s{N}` scenario windows. Killing the
   parent window also kills any panes inside it (planner / status / verify /
   concretize / review-claude / review-diff are panes within these windows, not
   separate windows — verified by reading `qa_loop.py:879-1429` and
   `review_loop.py:110-216`).
2. **Docker containers** — remove every container whose name matches the QA
   prefix for this PR across **all** loop ids:
   - `pm-qa-{pr_id}-` (legacy)
   - `pm-{session_tag}-qa-{pr_id}-` (session-tagged)

   The existing `container.cleanup_qa_containers(pr_id, loop_id)` requires a
   loop id; we need a variant that drops the loop-id constraint. Implement as
   a new helper `container.cleanup_pr_containers(pr_id, session_tag=None)`
   modelled on `cleanup_qa_containers` but using the looser prefix.
   `remove_container()` already calls `stop_push_proxy()`, so push-proxy
   sockets fall out for free (push_proxy.py:766, container.py:873).
3. **Pane registry entries** — remove registry windows whose names match the
   PR's window names. Read with `pane_registry.load_registry(session)`, then
   remove the window keys via `locked_read_modify_write` on
   `pane_registry.registry_path(session)`. Add a helper
   `pane_registry.unregister_windows(session, window_names)`.
4. **Push-proxy sockets** — handled transitively by `remove_container()`. No
   separate step needed unless containers are missing but a stale proxy
   socket remains; for safety also call `push_proxy.stop_push_proxy()` for
   each container name we discover but skip errors.

The cleanup primitive lives in a new module `pm_core/pr_cleanup.py` exposing:

```python
def cleanup_pr_resources(session: str, pr: dict, session_tag: str | None) -> dict:
    """Returns {"windows": [...], "containers": [...], "registry_windows": [...]}."""
```

It is also exposed via the CLI as a new flag on `pm pr cleanup`:
`pm pr cleanup --resources <pr_id>` (does not delete the workdir; only kills
windows / containers / registry / sockets). The existing workdir cleanup remains
the default behavior of `pm pr cleanup`.

## TUI integration

### Dedicated key

Use **`K`** (uppercase) bound on the selected PR. `K` is currently unbound
(verified against the BINDINGS list at `pm_core/tui/app.py:123-157`) and
maps mnemonically to "Kill resources". On press:

1. Resolve selected PR via `TechTree.selected_pr_id`.
2. Open a `ConfirmCleanupScreen` modal (new, in `tui/screens.py`) following
   the existing `ModalScreen` pattern (e.g. `MergeLockScreen`,
   `PlanPickerScreen`). Bindings: `y` confirm, `n`/`Esc` cancel. Body shows
   the PR id and a short list of what will be removed.
3. On confirm, run `pr_cleanup.cleanup_pr_resources(...)` in a worker
   (cleanup performs subprocess calls to `docker`/`tmux` and may take
   seconds), then `app.log_message()` a one-line summary like
   `Cleaned pr-001: 3 windows, 2 containers, 1 registry entry`.

### Prefix modifier

Add **`k`** (lowercase) as a new prefix key, modelled on the existing `z` and
`w` prefixes (`pm_core/tui/app.py:160-213`). Sequence:

1. Press `k` → enter `_k_mode = True`, log `[bold]k …[/] [dim](cleanup-then: s=start d=review t=qa)[/]`,
   start a 2-second auto-cancel timer.
2. Next key dispatches: `s` → cleanup then start, `d` → cleanup then review,
   `t` → cleanup then QA, `S` → cleanup then start+companion. Any other key
   cancels.
3. The cleanup half runs without an additional confirmation modal (the user
   already opted in by pressing `k`), but the log line announces what was
   cleaned before the follow-up action launches.

The follow-up action invokes the same code paths as the bare keys
(`action_start_pr`, `action_done_pr`, `action_start_qa_on_pr`) after the
cleanup worker completes. To preserve order, the worker awaits cleanup before
calling the follow-up action via `app.call_from_thread(...)`.

`k` mode interacts with `z` mode: pressing `k` while `z`/`zz` is buffered
clears the `z` count first (matches existing `w` prefix behavior).

### Command bar

`/pr cleanup --resources <pr_id>` already works once the CLI flag is in place
(routed through the standard `run_command` path in `pr_view.handle_command_submitted`).
No special prefix syntax is added to the command bar — the keybinding
prefix covers the "modifier" requirement; the command bar uses the explicit
flag.

## Implicit requirements

- The cleanup must be safe to run when the PR has no live resources (tmux
  window missing, no containers, empty registry). All helpers already
  no-op gracefully; we just must not raise.
- Concurrent guard: cleanup must respect `app._inflight_pr_action` like other
  PR actions. Set `_inflight_pr_action = "pr cleanup"` while running and
  clear in a `finally`.
- The session name comes from `pm_core.loop_shared.get_pm_session()` (used
  elsewhere in `pr_view.py:94-96`).
- `session_tag` for container matching: read from project config the same
  way QA does (`container.qa_container_name` callers use the project's
  session tag — locate via `pm_core.store` project metadata or the existing
  `_session_tag()` helper in `qa_loop.py` if exported; otherwise pass
  `None` to fall back to the legacy prefix only).
- The registry window-removal helper must use `locked_read_modify_write` so
  it doesn't race the live writers (qa_loop, review_loop, claude_launcher).
- After cleanup, trigger a TUI refresh (`trigger_tui_refresh()` from
  `pr_view`) so any state derived from the registry/windows is re-read.

## Edge cases

- **Active QA loop watcher** — A QA loop watcher process may still be running
  in the background even after windows die. The watcher detects vanished
  windows and exits on its own (verified at `qa_loop.py:1496` polling loop on
  `s.window_name`), so cleanup doesn't need to send signals.
- **Merged PR** — Cleanup is allowed regardless of PR status (no status
  guard). The existing workdir-cleanup version already cleans `in_review`
  and warns for other statuses; the resources variant should make no status
  judgment.
- **Push-proxy shared across scenarios** — Per `push_proxy.py:14-15`, multiple
  scenario containers may share a single proxy socket. Removing all
  containers for a PR also tears down the shared proxy as the last
  container exits — `remove_container` already handles this.
- **Grouped tmux sessions** (`session~N` form) — `pane_registry` already
  strips the `~N` suffix via `base_session_name`. Window names are unique
  per base session, so killing by name across the base session is correct.
  We use `get_pm_session()` for the session arg to `tmux` operations,
  matching how the rest of the TUI does it.
- **Cleanup-then-X with X failing the launch** — If the follow-up action
  (e.g. `pr start`) fails after cleanup succeeded, the user is left with
  no resources. This is acceptable: the log line will show the cleanup
  succeeded and the follow-up failure surfaces normally via
  `run_command`'s error path.

## Ambiguities

None unresolved. Resolved-with-judgment items:

- **Specific keys**: `K` (dedicated) and `k` (prefix). Both currently free;
  mnemonic; capital/lowercase pair mirrors `s`/`S` and `g`/`G` pattern.
- **Command-bar prefix syntax**: skipped in favor of the explicit
  `pr cleanup --resources` flag; adding new modifier syntax to the command
  bar is more invasive than warranted by the description's "any TUI
  command" phrasing — the keybinding prefix already satisfies that.
- **What the description's "scenario/planner/status/verify/concretize"
  windows refer to**: these are panes inside the QA windows, not separate
  tmux windows. Killing the QA windows kills them transitively. Likewise
  "review-claude/review-diff" are panes inside `review-{display_id}`.

## Files to touch

- `pm_core/pr_cleanup.py` (new) — orchestration
- `pm_core/container.py` — add `cleanup_pr_containers(pr_id, session_tag)`
- `pm_core/pane_registry.py` — add `unregister_windows(session, window_names)`
- `pm_core/cli/pr.py` — add `--resources` flag to `pr cleanup`
- `pm_core/tui/app.py` — add `K` binding, `k` prefix mode, `action_cleanup_pr`,
  prefix dispatch in `on_key`
- `pm_core/tui/screens.py` — add `ConfirmCleanupScreen` modal
- `pm_core/tui/pr_view.py` — add `cleanup_pr(app)` and the
  cleanup-then-action helpers
- Tests: extend coverage in `tests/` mirroring existing CLI/TUI test patterns
