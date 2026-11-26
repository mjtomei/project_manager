# Spec — pr-f5b7eef: dedicated `pr list` home tmux window + pluggable provider seam

## 1. Requirements (grounded in code)

### R1. Provider seam
New module `pm_core/home_window/__init__.py` exposing:
- `HomeWindowProvider` protocol: `name: str`, `window_name: str`, `ensure_window(session: str) -> str` (returns window name created or already present), `refresh(session: str) -> None`.
- Module-level `_REGISTRY: dict[str, HomeWindowProvider]` and `register(provider)`.
- `get_active_provider() -> HomeWindowProvider` — reads `home-window-provider` via `pm_core.paths.get_global_setting_value("home-window-provider", default="pr-list")`. Falls back to `pr-list` with a stderr warning if the setting names an unknown provider. The default `PrListProvider` is lazy-registered on first call.
- `ensure_home_window(session) -> str | None` — for batch callers that want to do the focus check / park sequencing themselves.
- `park_if_on(session, target_window_id) -> list[str]` — the workhorse called by every kill site. Cross-session aware: enumerates *every* grouped session whose active window is `target_window_id` (via `tmux.sessions_on_window(base, target_window_id)`) and selects `pm-home` on each one before the kill. Returns the list of grouped sessions parked (empty if none were on the target).
- `park(session, home_window=None)` — manual park helper for the rare batch case.

### R2. Default provider — pr-list
New module `pm_core/home_window/pr_list.py`:
- Class `PrListProvider` implementing the protocol (`name="pr-list"`, `window_name="pm-home"`).
- `ensure_window(session)`: if a window named `pm-home` already exists in `session` (via `tmux_mod.find_window_by_name`) → return its name. Otherwise resolve the project root via `store.find_project_root()` (with `Path.cwd()` fallback) and create the window with `tmux_mod.new_window(session, "pm-home", cmd, project_root, switch=False)` running `<sys.executable> -m pm_core.home_window.pr_list --session <name>`. Calls `set_shared_window_size` for shared-mode parity.
- `refresh(session)`: touches a per-base-session sentinel file at `pm_home() / "runtime" / f"home-refresh-{base}"` that the loop polls each tick. Falls back to silent no-op on OSError.
- Loop body (`_loop_main`): clears screen via ANSI, renders `_render_once()`, sleeps up to `POLL_SECONDS` (5s) but wakes early when the sentinel mtime advances. Seeds `last_mtime` from any pre-existing sentinel so a stale sentinel doesn't double-render on startup. Catches all render-time exceptions so the long-lived window survives transient bugs.
- `_render_once()` reads `store.find_project_root()` + `store.load()`, filters to non-closed/non-merged PRs, sorts by `updated_at`/`created_at` desc, and renders the same lines as `pr.pr_list(timestamps=True, open_only=True)` plus a `pm pr list -t --open    (updated HH:MM:SS)` header. On store-load failure it returns an error line so the loop keeps running.

### R3. CLI command — `pm session home`
New subcommand on the `session` group in `pm_core/cli/session.py`:
- Resolves session via `_get_pm_session()` from `pm_core/cli/helpers.py`. Errors with `"Not inside a pm tmux session."` when none.
- Calls `home_window.get_active_provider()`, then `provider.ensure_window(session)` to create-if-needed, then `provider.refresh(session)` to force immediate re-render.
- Switches the invoking client to the home window via `tmux_mod.select_window(session, window_name)`.

### R4. Park-before-kill at every relevant kill site
Park happens *before* `tmux.kill_window`. The killed window is no longer the client's active window by the time tmux processes the kill, so tmux's previous-window fallback never fires — the parked client stays on `pm-home`. The seam is `home_window.park_if_on(session, win_id)` (cross-session aware via `sessions_on_window`).

| Site | File | Recreate? | Behavior after park |
|---|---|---|---|
| Merge cleanup (impl/review/merge/qa/qa-scenario windows) | `pm_core/cli/helpers.py` `kill_pr_windows` | no | Sessions stay on `pm-home`. Per-target `park_if_on` so cross-session kills are handled per-window. |
| Picker `--fresh` impl-window kill | `pm_core/cli/pr.py` near impl-fast-path | yes (the rest of `start` recreates the impl window with `switch=True`) | Sessions briefly on `pm-home`, then natural impl-window switch. |
| Picker `--fresh` review-window kill | `pm_core/cli/pr.py` review-fast-path | yes (review_loop path also calls `switch_sessions_to_window` for the review_loop case) | Sessions briefly on `pm-home`, then onto new review window. |
| QA stale-window cleanup | `pm_core/qa_loop.py` `_kill_qa_windows` | varies by caller | Sessions land on `pm-home`; if a recreate follows in the caller, that path's switch logic runs. |
| Review-loop supersede (`z d`, `zz d`) | `pm_core/tui/review_loop_ui.py` two sites | yes (`_start_loop` / `pr_view.review_pr` recreates and switches) | Brief `pm-home`, then onto fresh review window. |
| Post-merge merge-window cleanup | `pm_core/tui/review_loop_ui.py` cleanup helper | no | Stays on `pm-home`. |
| Watcher window recreate | `pm_core/cli/watcher.py` `_create_watcher_window` | yes (followed by `switch_sessions_to_window` to the new watcher) | Brief `pm-home`, then onto new watcher window. |

#### Why park even when the loop recreates the window
Two reasons, both motivated by the gap between kill and recreate:

1. **Failure safety**: if recreate fails partway, the parked client stays on `pm-home` instead of falling back to tmux's previous-window history (which can be a window in another client's view).
2. **Shared-window protection**: between the kill and the post-recreate `switch_sessions_to_window`, tmux's previous-window fallback would put the client on whatever shared window it most recently visited. Stray input or a resize there could perturb that shared view. Parking sits the client on `pm-home` for the gap; the post-recreate switch then pulls them onto the new window — same end state, but with no shared-window detour.

#### Cross-session correctness
A kill triggered from session A may target a window whose currently-active viewer is session B (a different grouped session). `park_if_on` uses `tmux.sessions_on_window(base, target_window_id)` to enumerate *all* grouped sessions whose active window matches and selects `pm-home` on each, so B is parked even though A initiated the kill. Without this, B would fall back to its own previous-window history — the exact behavior the home-window concept is designed to eliminate.

`select_window` in `pm_core/tmux.py` routes through `current_or_base_session` and doesn't accept an explicit grouped-session target, so `park_if_on` issues `tmux select-window -t <session>:<index>` directly per session.

### R5. Setting
- Setting key: `home-window-provider`
- Default value: `"pr-list"`
- Read via `paths.get_global_setting_value("home-window-provider", "pr-list")`
- No CLI subcommand to set it in this PR; users edit `~/.pm/settings/home-window-provider` or it's set by future PRs (e.g. work-pane).

### R6. Per-session lifetime
- The home window lives in the pm tmux session; multiple grouped (`base~N`) sessions share it (tmux windows are session-group-shared).
- Park targets every grouped session on the doomed window (cross-session correctness, R4) but does not touch grouped sessions that are on other windows.

## 2. Implicit Requirements

- **Idempotency**: `ensure_window` returns the existing window's name on repeat calls without recreating.
- **Safe outside tmux**: `park_if_on` and `ensure_home_window` no-op when not in tmux (`tmux_mod.in_tmux()` false), session is missing, or the session doesn't exist. Internal failures are caught with `_log.exception`.
- **Container compatibility**: pr-list loop uses pure Python (no `watch`), reads state via `store.load(store.find_project_root())`, and is invoked with `sys.executable` so containerized installs hit the right venv. Cwd is the project root.
- **Loop robustness**: render-time exceptions are caught; loop survives transient `store.load` failures.
- **Window-name collision**: a pre-existing user window named `pm-home` is treated as the home window. Acceptable — rare and user-induced.
- **Sentinel cleanup**: stale sentinel mtime is read at loop start so initial render doesn't double-fire.

## 3. Ambiguities (resolved)

- **Window name** — `pm-home`, exposed as `provider.window_name` so the work-pane provider can override.
- **Refresh mechanism** — Per-base-session sentinel file polled by the loop with 250ms granularity. Avoids tmux `respawn-pane` (which loses state) and IPC sockets (overkill).
- **Pre-kill vs post-kill park** — **Pre-kill**. Selecting `pm-home` before `kill_window` means the doomed window isn't the active window when tmux processes the kill, so tmux's previous-window fallback never fires. (Post-kill park was considered but leaves a brief window where tmux already moved focus to a previous window.)
- **Where to register the provider** — Module-level dict in `pm_core/home_window/__init__.py`. The work-pane PR adds an entry alongside `pr-list`. No plugin-discovery machinery.
- **Should `pm session home` create or only refresh** — Always ensure-then-refresh-then-switch.
- **Cwd for the home window** — `store.find_project_root()` (with `Path.cwd()` fallback). The loop only reads state, so cwd is cosmetic but kept aligned with other pm windows.
- **Cross-session park scope** — Park *every* grouped session whose active window matches the target, not just the calling client. The original spec said "calling client only" to avoid yanking other views, but that left the very bug we're trying to fix (other client falls back to a shared window) in place. Parking every session-on-target-window addresses the bug; sessions on *other* windows are untouched.

## 4. Edge Cases

- **No tmux session**: `park_if_on` no-ops; `pm session home` errors with `"Not inside a pm tmux session."`.
- **Unknown provider in setting**: Fall back to `pr-list` with stderr warning.
- **Home window already focused**: `select-window` to the same window is a no-op.
- **Home window itself killed**: Treated like any window; `ensure_window` recreates on next park or `pm session home`.
- **Outside tmux entirely**: All home-window calls no-op via `in_tmux()` check.
- **Concurrent refresh across grouped sessions**: One sentinel file per base session — grouped sessions share one home window.
- **Loop process leak after session kill**: Loop runs as a tmux pane child; killing the session terminates the pane and the Python loop. No extra cleanup needed.
- **Review-loop supersede with `_poll_for_verdict` blocked**: Park before kill doesn't change termination semantics — `_poll_for_verdict` still hits PaneKilledError when the review window is killed.
- **Loop recreate fails**: Parked clients stay on `pm-home` instead of falling back to a shared window (per R4 rationale).

## 5. File-by-file plan

1. `pm_core/home_window/__init__.py` (new) — protocol, registry, `get_active_provider`, `ensure_home_window`, `park_if_on` (cross-session), `park`.
2. `pm_core/home_window/pr_list.py` (new) — `PrListProvider`, sentinel-based refresh, `_render_once`, `_loop_main`, `python -m` entrypoint.
3. `pm_core/cli/session.py` — `session home` subcommand.
4. `pm_core/cli/helpers.py` — `kill_pr_windows` calls `park_if_on` per target before each `kill_window`.
5. `pm_core/cli/pr.py` — `park_if_on` before the impl `--fresh` and review `--fresh` kills.
6. `pm_core/qa_loop.py` — `park_if_on` before each QA window kill in `_kill_qa_windows`.
7. `pm_core/tui/review_loop_ui.py` — `park_if_on` before the `z d`, `zz d`, and post-merge merge-window kills.
8. `pm_core/cli/watcher.py` — `park_if_on` before the watcher recreate's kill. The existing `switch_sessions_to_window` after recreate naturally pulls parked sessions onto the new window — no exclusion needed.

No setting registration code is required beyond the implicit `paths.get_global_setting_value` call.
