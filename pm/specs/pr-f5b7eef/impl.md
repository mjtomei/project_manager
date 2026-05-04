# Spec — pr-f5b7eef: dedicated `pr list` home tmux window + pluggable provider seam

## 1. Requirements (grounded in code)

### R1. Provider seam
New module `pm_core/home_window/__init__.py` exposing:
- `HomeWindowProvider` protocol: `name: str`, `ensure_window(session: str) -> str` (returns window name created or already present), `refresh(session: str) -> None`.
- `get_active_provider() -> HomeWindowProvider` — reads `home-window-provider` via `pm_core.paths.get_global_setting_value("home-window-provider", default="pr-list")`, dispatches through a small registry `{name: provider_instance}`.
- `ensure_and_park(session: str) -> str | None` — convenience used by kill-window callsites. Resolves provider, calls `ensure_window`, seeds the calling client's `last-window` to the home window so tmux's previous-window fallback lands there after the in-progress kill. Returns the home window name (or `None` when not in tmux / no session).

### R2. Default provider — pr-list
New module `pm_core/home_window/pr_list.py`:
- Class `PrListProvider` implementing the protocol.
- `ensure_window(session)`: if a window named `pm-home` already exists in `session` (via `tmux_mod.find_window_by_name`) → return its name. Otherwise create it with `tmux_mod.new_window(session, "pm-home", cmd, cwd, switch=False)` running a small Python loop that calls `pm_core.cli.pr.pr_list` internals directly (no shell `watch` dep).
- `refresh(session)`: signal the running loop to re-render immediately. Implementation: write a refresh sentinel file (e.g. `~/.pm/runtime/home-refresh-<session>`) that the loop's poll checks each tick — touching the file resets the next-poll timer. (Avoids tmux `respawn-pane`, which would kill state.) Falls back to no-op if the window doesn't exist.
- The loop body: read `state_root()`, `store.load()`, render the same lines as `pr.pr_list(timestamps=True, open_only=True)`, print with `clear` + body, sleep ~5s with sentinel-aware wake.

### R3. CLI command — `pm session home`
New subcommand on the `session` group in `pm_core/cli/session.py`:
```python
@session.command("home")
def session_home():
    """Ensure the home window exists and switch the calling client to it."""
```
- Resolves session via `_get_current_pm_session()` / `_get_pm_session()` (existing helpers in `pm_core/cli/helpers.py`).
- Calls `home_window.get_active_provider()`, then `provider.ensure_window(session)` to create-if-needed, then `provider.refresh(session)` to force immediate re-render.
- Switches the invoking client to the home window via `tmux_mod.select_window(session, window_name)`.

### R4. Auto-park on window kill
Audit and wire `home_window.ensure_and_park(session)` into the following kill sites where the user might be focused on the killed window:

| Site | File:line | Notes |
|---|---|---|
| Merge cleanup (kills impl/review/qa/merge windows) | `pm_core/cli/helpers.py:262 kill_pr_windows()` | Single park call before the loop — all four kills happen in sequence; one ensure-and-park covers them. |
| Picker / fresh-start kill | `pm_core/cli/pr.py:829` (impl window `--fresh`), `pm_core/cli/pr.py:1170` (review window `--fresh`) | Park before kill since user is currently on the window being killed. |
| QA stale window cleanup | `pm_core/qa_loop.py:333,336` | Wrap in a single park call. |
| Review-loop supersede | `pm_core/tui/review_loop_ui.py:81,136` (z d / zz d) | Park before each kill. |
| Merge window cleanup post-merge | `pm_core/tui/review_loop_ui.py:683` | Park before kill. |
| Watcher window recreate | `pm_core/cli/watcher.py:392` | **Skip** — runs in background, user not focused on watcher window during recreate. |

Park-before-kill sequence for the active client only (not all attached clients):
1. Resolve home window name via provider's `ensure_window`.
2. `tmux select-window -t <home>` then `select-window -l` on the *current* client to seed last-window without flicker, OR
3. After the kill, if the client landed on an unexpected window, `tmux select-window -t <home>` for the calling client only.

Implementation choice: do (3) — call `tmux_mod.select_window(session, home_name)` *after* `kill_window`, scoped via the existing `current_or_base_session` helper (which targets only the caller's grouped session). This avoids the pre-kill flicker risk and is simpler.

### R5. Setting
- Setting key: `home-window-provider`
- Default value: `"pr-list"`
- Read via `paths.get_global_setting_value("home-window-provider", "pr-list")`
- No CLI subcommand to set it in this PR; users edit `~/.pm/settings/home-window-provider` or it's set by future PRs.

### R6. Per-session lifetime
- The home window lives in the pm tmux session; multiple grouped (`base~N`) sessions share it (tmux windows are session-group-shared).
- Auto-park targets only the calling client (via `current_or_base_session`), so other attached clients aren't yanked.

## 2. Implicit Requirements

- **Idempotency**: `ensure_window` must be safe to call repeatedly; the second call returns the existing window's name without recreating.
- **Safe outside tmux**: `ensure_and_park` no-ops when not running inside tmux (`tmux_mod.in_tmux()` false) or when session resolution fails. Kill-window callers must not crash if home-window setup fails — wrap in try/except with logging.
- **Container compatibility**: The pr-list loop must work in pm's container mode. It uses Python directly (no `watch`), reads state via `store.load(state_root())`, and runs in the same cwd/env as the pm session. The `cwd` passed to `new_window` should match what other pm windows use — `Path.cwd()` or a state-root-derived path.
- **Loop robustness**: On store-load failure, the loop prints an error line and keeps polling rather than exiting, so the window stays alive.
- **Window-name collision**: If a user-created window happens to be named `pm-home`, `ensure_window` treats it as the home window. Acceptable — rare and user-induced.
- **No double-park**: `kill_pr_windows` kills 4+ windows in a loop; we call `ensure_and_park` once before the loop, not per kill.
- **Avoid park flicker for non-focus kills**: Several of the listed kill sites (e.g. `cli/pr.py:829`, watcher) kill a window the user *might not* be on. The post-kill `select_window` call to home would then yank them away from their current window. Mitigation: before parking, check `tmux_mod.get_window_id(session)` against the to-be-killed window id and skip parking if they don't match. This is what makes "auto-park on kill of the user's focused window" precise.

## 3. Ambiguities (resolved)

- **Window name** — Use `pm-home` (provider-overridable via `provider.window_name` attribute). Description says "default name `pm-home`".
- **Refresh mechanism** — Sentinel file polled by the loop. Simpler than IPC sockets; the 5s cadence already implies sub-second responsiveness isn't required, but a sentinel gives near-instant refresh on hotkey.
- **Pre-kill vs post-kill park** — Post-kill `select-window` on the current grouped session only. Avoids the flicker risk the description flags and is robust against tmux's last-window history quirks across multiple grouped sessions.
- **Where to register the provider** — Module-level dict in `pm_core/home_window/__init__.py`. The work-pane PR adds an entry alongside `pr-list`. No plugin-discovery machinery in this PR.
- **Should `pm session home` create the window if absent or only refresh** — Description says "First invocation: provider creates… Subsequent: refreshes immediately." So always ensure-then-refresh-then-switch. Implemented exactly that way.
- **Cwd for the home window** — Use `state_root()` (or its parent for internal-pm-dir layouts), matching where other pm windows operate. The loop only reads state, so cwd is mostly cosmetic.

## 4. Edge Cases

- **No tmux session**: `ensure_and_park` returns early; `pm session home` errors with a clear message ("not inside a pm tmux session").
- **Setting points at unknown provider**: Fall back to `pr-list` with a stderr warning. Don't crash kill-window paths.
- **Home window already focused**: `select_window` to the same window is a no-op — fine.
- **Killing the home window itself**: Treated like any window kill; `ensure_window` will recreate on next park or `pm session home` invocation.
- **Pm running outside a tmux server (CLI invocation from a non-tmux shell)**: All home-window calls no-op via `in_tmux()` check.
- **Concurrent refresh sentinels across grouped sessions**: One sentinel file per base session (`home-refresh-<base>`) — grouped sessions all share one home window so one sentinel suffices.
- **Loop process leaks after `pm session kill`**: Loop runs as a tmux pane child; killing the session terminates the pane, terminates the Python loop. No extra cleanup needed.
- **Review-loop supersede path kills review window while loop's `_poll_for_verdict` is blocked on it**: Park happens *before* kill, so the loop's PaneKilledError still fires; auto-park doesn't change termination semantics.
- **Picker `--fresh` paths kill the user's currently-focused impl/review window**: This is exactly the case auto-park is designed for. Include them.

## 5. File-by-file plan

1. `pm_core/home_window/__init__.py` (new) — protocol, registry, `get_active_provider`, `ensure_and_park`.
2. `pm_core/home_window/pr_list.py` (new) — `PrListProvider`, the polling loop entrypoint (callable as a module: `python -m pm_core.home_window.pr_list <session>`).
3. `pm_core/cli/session.py` — add `session_home` command.
4. `pm_core/cli/helpers.py` — wrap `kill_pr_windows` with a single pre-loop `ensure_and_park` call.
5. `pm_core/cli/pr.py` — park before lines 829 and 1170 (focus check first).
6. `pm_core/qa_loop.py` — park before the loop at 329 (focus check first).
7. `pm_core/tui/review_loop_ui.py` — park before kills at 81, 136, 683.
8. No changes to `pm_core/cli/watcher.py` (background, not user-focused).

No setting registration code is required beyond the implicit `paths.get_global_setting_value` call.
