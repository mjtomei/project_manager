# Spec: Window-attached persistent Claude popup (pr-e5b4dd8)

## Requirements

1. **New tmux keybinding** that summons/dismisses a Claude popup attached to
   the current tmux window. Bound at the tmux level (a tmux prefix binding,
   *not* a TUI Textual binding) so it works from any pane in the window —
   including impl/review/QA panes — not only the TUI pane.

   Wire it into `_register_tmux_bindings` in `pm_core/cli/session.py:97`,
   alongside the existing `prefix+P`/`prefix+M` popup bindings registered by
   `_bind_popups()` (line 81). Use **`prefix + slash`** (`prefix /`) — `?`
   is tmux's built-in list-keys binding, and `prefix /` reads naturally as
   "search/ask" while not colliding with anything in
   `_register_tmux_bindings`.

   The binding invokes a new `pm _popup-diag` internal CLI command (added in
   `pm_core/cli/session.py` next to `_popup-show` at line 720).

2. **First press in a window** spawns a long-lived Claude session attached
   to that window. The session must:

   - Run **outside any container** — invoke the host `claude` binary via
     `pm_core.claude_launcher.find_claude` + `build_claude_shell_cmd`, the
     same path `pane_ops.launch_claude` (`pm_core/tui/pane_ops.py:312`)
     uses today. No docker/podman wrapping.
   - Live in a **separate tmux session** named
     `pm-diag-<base>-<window_short>` where `<base>` is the base pm session
     name (`pane_registry.base_session_name`) and `<window_short>` is the
     tmux window-id stripped of its leading `@`. Using a separate session
     (not a hidden pane in the current session) is what lets the popup
     dismiss/re-show without killing the Claude process: tmux popup `-E`
     just attaches and detaches; the session keeps running.
   - Be created via `tmux new-session -d -s <name> <claude-cmd>`
     (`pm_core.tmux.create_session`).
   - Use `build_claude_shell_cmd` with a diag-specific prompt that explains
     the session is running outside the container with host access, and
     names the originating pm session/window. Reuse the existing
     `tui_section(sess)` block so the user can still drive the TUI from the
     popup.

3. **Subsequent presses re-show the same session's popup** over the
   current window. Implementation: on every press, check whether the diag
   tmux session for the current window-id already exists
   (`tmux_mod.session_exists`). If yes, just open the popup attaching to
   it; do not create a new session. The Claude process and its scrollback
   persist because the tmux session was never killed.

   Dismissal: tmux's default popup behavior — `Esc`/`q`/`Ctrl-c` close the
   popup but leave the underlying tmux session alive. We use
   `display-popup -E "tmux attach-session -t <diag-session>"`; closing the
   popup detaches the popup's tmux client without killing the diag
   session.

4. **Window-attached identity (key: window-id)**. The diag session name is
   derived from the tmux window-id (e.g. `@7`), not the window name or
   index, because window names/indexes can change but window-ids are
   stable for the window's lifetime. The current window-id is resolved
   inside `_popup-diag` by calling `tmux display-message -p
   '#{window_id}'`. Each pm window therefore has its own diag session,
   summoned/dismissed independently.

5. **Persistent across window switches**. Because the diag session is a
   separate detached tmux session, switching pm windows does not affect
   it. Pressing `prefix /` again from the same window resolves the same
   `window-id` → same diag session name → same session reattached.

6. **Closing the host window terminates its diag session.** Wire a
   `window-unlinked` (or `pane-died` with appropriate filter — in practice
   `window-unlinked` is the right hook) tmux hook in
   `_register_tmux_bindings` that invokes `pm _diag-window-closed
   <session> <window_id>`. That command kills the diag session if it
   exists and removes the `window-id` from the state map.

7. **State map** at `~/.pm/sessions/<tag>/diag-panes.json` mapping
   tmux `window-id` → diag tmux session name. Stored under the existing
   `session_dir(tag)` directory (see `pm_core/paths.py:127`). Used so a pm
   restart can find pre-existing diag sessions and so cleanup
   (`_diag-window-closed`) can look up which session to kill given just a
   window-id. Note: the diag session name is fully derivable from the
   window-id, so the file is primarily a record-of-existence (which
   window-ids currently have a live diag session). Keep the field as
   `name` for forward-compatibility.

8. **`c` keybinding** in the TUI (`pm_core/tui/app.py:150`,
   `Binding("c", "launch_claude", ...)`) **becomes a deprecated alias** for
   the new popup binding. Per the task: "`c` becomes a deprecated alias /
   shortcut for opening the popup attached to the current window."

   Implementation: change `action_launch_claude` (`pm_core/tui/app.py:783`)
   to invoke the same popup show flow as `prefix /`. Easiest path: have it
   shell out to `tmux display-popup` directly via a small helper that
   shares logic with `_popup-diag`. Keep the existing
   `pane_ops.launch_claude` function in place but no longer reachable from
   the `c` binding (the task says the old fresh-pane behavior "stays
   accessible if there's a use case (probably not — the popup should
   subsume it)"). Conservative resolution: leave the function intact so
   future callers/tests still work, but rewire `c` to the popup. Don't
   delete it.

9. **Popup width/height**. Reuse the same dynamic-width logic as
   `_popup-show` (`pm_core/cli/session.py:720`) — 95% on narrow terminals
   (below `_get_mobile_width_threshold`), fixed 80 cols otherwise. Height
   should be tall — claude needs vertical space — so use `90%` (vs the
   `80%` picker / `50%` cmd popups).

10. **Test plan**. Manual verification (per task's Test section): open a
    TUI window, press `prefix /` → popup appears with Claude; type
    something; Esc to dismiss; switch window, `prefix /` → different
    session; switch back, `prefix /` → original session reappears with
    prior conversation; close the original window → diag session
    terminates.

    Plus a unit test (`tests/test_popup_diag.py` or extend
    `tests/test_claude_launcher.py`) covering: (a) diag session name is
    derived from window-id deterministically, (b) state map round-trips,
    (c) `_diag-window-closed` removes the entry and calls `kill_session`.

## Implicit Requirements

- **`prefix /` binding registration must be idempotent**, since
  `_register_tmux_bindings` is called on every reattach. tmux `bind-key`
  is idempotent by nature (rebinding silently overwrites), so this is
  free.
- **Cwd for the diag session**. The popup runs outside the container
  context, but Claude still needs a sensible cwd for its project
  directory. Use the originating pane's `pane_current_path` (the same
  approach `_popup-show` uses, lines 760-764) so transcripts and pm
  resolution work correctly. Falls back to `$HOME` if unavailable.
- **The diag tmux session must be on the same tmux server/socket** as the
  pm session. `pm_core.tmux.create_session` defaults to the default
  socket; pm's normal sessions also default there. No socket-path
  threading needed.
- **Skip-permissions flag** (`--dangerously-skip-permissions`) propagation:
  `build_claude_shell_cmd` reads it via `skip_permissions_enabled` keyed
  on the session tag. Pass the *originating* pm session_tag, not the diag
  session name, so the flag toggles consistently with the rest of pm.
- **Claude session resume across pm restarts.** If pm is restarted but the
  underlying tmux server is still running, the diag tmux session
  *survives* and `prefix /` rebinds to it cleanly (state map repopulated
  on first press if missing — name is derivable from window-id). If the
  tmux server itself is restarted, both pm and diag sessions die together
  and we start fresh.
- **`pm _popup-diag` must not block the calling tmux `run-shell`.** As
  with `_popup-show`, it spawns `tmux display-popup -E ...` via
  `subprocess.run` which returns when the popup closes. tmux's `run-shell`
  *does* allow this (display-popup completes when dismissed). This is the
  same pattern used by the existing popups — it works.

## Ambiguities

1. **Choice of binding key.** Task says "e.g. prefix+? or prefix+/ —
   bikeshed during impl." Resolved to `prefix /`: `?` is tmux's built-in
   list-keys help and overriding it would be hostile.

2. **Old TUI `c` behavior — keep accessible or remove?** Task says
   "Existing `c` behavior of spawning a fresh pane stays accessible if
   there's a use case (probably not — the popup should subsume it)."
   Resolved: rewire `c` to the new popup, but **leave
   `pane_ops.launch_claude` in place** (not deleted) — no harm, and
   removing it would break tests/imports. No new alias for the fresh-pane
   variant; if anyone wants it back, it's one rebind away.

3. **What does "outside any container" mean for the prompt's working
   directory?** The session is launched with `cwd =
   pane_current_path` of the originating pane. If pm is being driven from
   inside a container (the originating pane is in `/workspace`), that
   path may not exist on the host and the diag session would fail to
   `cd`. Resolved: fall back to the host's session pm_root (read via
   `paths.session_pm_root` at `pm_core/paths.py:240` — the file
   `~/.pm/sessions/<tag>/pm_root` exists for exactly this kind of
   container/host-path mapping), and finally to `$HOME` if neither
   resolves. The whole point of running outside the container is host
   access, so we *want* the host path.

4. **Containerized opt-in flag.** Task says "Provide a flag to opt into
   containerized mode if there's a future use case for that, but keep the
   default unboxed." Resolved: out of scope for the first pass.
   Containerized variant is explicitly listed in "Out of scope" too. We
   add a TODO comment in `_popup-diag` noting where to wire the flag.

## Edge Cases

- **Same window-id reused after a window is closed and a new one
  created** — tmux assigns monotonically increasing window-ids per
  server, so collisions don't happen unless the tmux server restarts. On
  server restart, both pm and diag sessions are gone, so we're safe.

- **Multiple pm sessions sharing a tmux server (different repos)** —
  diag-session names include the pm base session name, so they don't
  collide. State maps live under `~/.pm/sessions/<tag>/...` which is
  per-repo.

- **State map says session exists but tmux disagrees** (e.g. the diag
  session was killed manually). On `prefix /` press, check
  `tmux_mod.session_exists` *before* deciding whether to create. The
  state map is informational; tmux is the source of truth.

- **Popup is visible, user switches to a different tmux client** — tmux
  popups are per-client, so this is a non-issue: the popup belongs to
  the client that opened it. The diag tmux session keeps running
  regardless.

- **Window-close hook fires during normal tmux shutdown** — racing with
  `kill-session` on an already-dying server. Wrap the
  `_diag-window-closed` body in try/except and log-and-continue. tmux
  errors on missing targets are non-fatal here.

- **Claude binary not found on the host** — same handling as today's `c`
  binding: log a friendly message. In the popup context, "log" means
  print to stderr; the popup will display the error and stay open via
  the existing `read -n 1` failure-trap pattern from `_POPUP_PICKER_BODY`
  (lines 59-65).

- **`prefix /` pressed before `_register_tmux_bindings` ran on this
  server boot** — bindings are registered when pm session is created or
  reattached; if the user somehow presses the key on a foreign tmux
  server, tmux's default `prefix /` (no binding by default in tmux ≥3,
  but historically "find next") fires. Acceptable — pm-specific bindings
  are pm-specific.
