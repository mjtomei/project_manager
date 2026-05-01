# Spec — pr-4702a11: pm rc mobile voice document viewer and editor

## 1. Requirements (grounded in code)

### 1.1 New CLI: `pm rc start <path> [--port N]` (pm-session only)

- New file `pm_core/cli/rc.py` defining a `@cli.group("rc")` Click group.
- Wire registration in `pm_core/cli/__init__.py` by appending `rc` to the
  bottom-of-file submodule import list (line 671), matching how `pr`,
  `plan`, `qa`, etc. self-register on the `cli` group.
- `pm rc start`:
  - Requires that the caller is inside a pm tmux session. Use
    `pm_core.cli.helpers._get_current_pm_session()` (helpers.py:623). If it
    returns `None`, error with a clear "pm rc start must be run inside a pm
    session" message and `SystemExit(1)`. Mirrors the contract used by
    other in-session commands.
  - Validates `<path>`: must exist, be a regular file. Resolve to absolute
    path via `Path(path).resolve()` so the server stores a stable path
    even after pane chdir.
  - `--port N` (int, optional). If given, the server binds to that port
    and errors clearly if it's in use ("port N is already in use").
    Without `--port`, picks a free port via
    `socket.socket(); s.bind(("", 0)); port = s.getsockname()[1]`.
  - Determines the LAN-bind IP at startup. Uses a UDP-connect trick
    (`s.connect(("8.8.8.8", 80)); s.getsockname()[0]`) with `127.0.0.1` as
    fallback. Logs a clear "LAN-only, no auth — anyone on this network can
    read/write the file" warning to stderr.
  - Starts the FastAPI server as a **detached background daemon**
    (`subprocess.Popen(..., start_new_session=True, stdout/stderr` to a log
    file under `~/.pm/rc-logs/<pid>.log`). The server process executes
    `python -m pm_core.rc.server --path <path> --port N --host <ip>` (a
    new module `pm_core/rc/server.py` exposing a `main()` entry).
  - Opens a new tmux window in the current pm session via
    `pm_core.tmux.new_window_get_pane(pm_session, window_name="rc",
    cmd=<claude-cmd>, cwd=<dir-of-path>, switch=True)` (tmux.py:156).
  - The Claude pane is launched with `build_claude_shell_cmd`
    (claude_launcher.py:304), passing a system prompt (the rc-driver
    prompt described in task §"rc-driver system prompt"). The prompt is
    written via the prompt-file mechanism already supported by
    `build_claude_shell_cmd`. Working directory is the directory
    containing `<path>` so `pm rc <subcommand>` invocations use the
    surrounding project context.
  - Registers the Claude pane under role `rc-driver` and the server's
    *PID* under a synthetic registry entry with role `rc-server` in the
    same window. We extend the registry "pane" dict (which already
    accepts arbitrary keys via `register_pane`'s `cmd` param;
    pane_registry.py:174) by writing a non-tmux entry with `id` =
    `rc-server-<pid>` and additional `port` and `host` fields. We do this
    via direct `locked_read_modify_write` rather than `register_pane` to
    avoid corrupting layout (an `rc-server` "pane" must not enter
    `rebalance`'s desired_order).
  - Important: `pane_layout.rebalance` filters by `live_ids` from tmux
    (pane_layout.py:402-407). A non-tmux pane id won't be in `live_ids`
    so it will be naturally excluded from layout. Reconciliation
    (`_reconcile_registry`, pane_registry.py:264) however drops panes not
    in tmux. To prevent the rc-server entry from being garbage-collected
    by reconciliation, it lives outside the per-window `panes` list:
    add a top-level `data["rc_servers"]` dict keyed by window id, each
    holding `{"pid": int, "port": int, "host": str, "path": str}`.
    `pm rc stop`/cleanup hooks read this.
  - Prints to stdout: `Viewer: http://<lan-ip>:<port>/` and the path.
- The `--port` collision check is performed by the parent pm process
  attempting `s.bind((host, port))` before launching the daemon, then
  closing and passing the port to the daemon. (Race-y but matches the
  user-facing test "errors clearly if it's in use".)

### 1.2 FastAPI server (`pm_core/rc/server.py`)

- New package `pm_core/rc/` (`__init__.py` empty).
- Module-level state (single-process server, in-memory):
  - `path: Path` — resolved absolute file path.
  - `lock: threading.Lock` — guards all mutations.
  - `version: int` — bumped on every accept (file write).
  - `selection: tuple[int,int] | None`.
  - `proposal: str | None`.
  - `viewport: dict | None` — `{"top": int, "bottom": int}`.
  - `subscribers: list[queue.Queue]` — for SSE fan-out.
- File text is read fresh on each `/api/doc` and `/api/accept`. This
  avoids drift with external edits and avoids holding stale text through
  the lifetime of the server.
- Endpoints (per task spec). Every mutating endpoint, after committing:
  builds a state-event dict and pushes it onto every subscriber queue.
  After accept, additionally pushes a doc event.
- SSE handler (`/api/events`): creates a `queue.Queue`, adds it to
  `subscribers`, sends an initial `state` event with current snapshot,
  then loops reading from the queue and yielding `event: ...\ndata:
  json...\n\n` strings. On disconnect, removes itself from subscribers.
  Implemented via FastAPI's `StreamingResponse` with `media_type="text/event-stream"`.
- Auto-focus on `/api/select`: `viewport.top = max(1, start - 3)`. The
  server cannot know the device's viewport height, so it does not set
  `bottom`; the client reports `bottom` back via `/api/viewport`.
- `/api/accept` writes the proposal back into the file. Implementation:
  `lines = path.read_text().splitlines(keepends=True)` then replace the
  inclusive 1-indexed range with `proposal` (split into lines, preserving
  a trailing newline if the original range had one), then
  `path.write_text(...)`. Bumps `version`, clears `proposal`, clears
  `selection`. Broadcasts state and doc events.
- All endpoints return `{"ok": true, ...}` JSON; errors return
  HTTP 400 with `{"error": "..."}` JSON.
- Bound host: 0.0.0.0 by default so any interface on the LAN can reach
  it (matches the "binds to the LAN IP so other devices can reach it"
  test). Uvicorn started programmatically (`uvicorn.run(app, host=...,
  port=...)`).

### 1.3 Webapp (`pm_core/rc/templates/viewer.html`)

- Single self-contained HTML file. No build step. Inline CSS + JS.
- On load:
  - `fetch('/api/doc')` for initial snapshot, render text.
  - Open `EventSource('/api/events')`, attach `onmessage` (state events)
    and `addEventListener('doc', ...)` for doc events.
  - On `error`: close, schedule reconnect with exponential backoff
    (250ms doubling, capped at 4s).
  - `document.addEventListener('visibilitychange', ...)`: when visible,
    fetch `/api/doc` to fully re-sync.
- Markdown rendering: include a tiny markdown renderer (or use
  `marked.min.js` from a CDN). Since we must not assume internet, use a
  minimal in-page markdown→HTML function that handles headings, bold,
  italics, lists, code blocks. Selection highlighting is line-based, so
  the renderer must preserve line→DOM mapping (each top-level block
  carries `data-line-start`/`data-line-end`).
- Selection rendered via a translucent yellow background overlay on the
  affected line range.
- Proposal rendered as an inline diff strip after the selection block:
  red strikethrough for selected lines, green for proposal lines.
- Touch scrolling is native browser behavior (default).
- Viewport reporting: a debounced (150ms) `IntersectionObserver` or
  scroll handler computes the topmost and bottommost visible line and
  POSTs `/api/viewport` with `{top, bottom}`.
- `/api/focus` response handling: the server returns the new viewport;
  the client scrolls so the line with `data-line-start === top_line` is
  at the top edge.

### 1.4 Claude-driving CLI subcommands

All subcommands of `pm rc <verb>` (in `pm_core/cli/rc.py`):
- Look up the rc-server entry for the current pm session by reading
  `data["rc_servers"]` from the registry. If multiple exist (multiple
  windows), pick the one in the *current window* via `$TMUX_PANE`-derived
  window id. If none, error.
- HTTP calls hit `http://127.0.0.1:<port>` (loopback is safe from the
  Claude pane on the host).
- Implementation uses `urllib.request` (stdlib only, no `requests`
  dep — pyproject lists no http client).
- Subcommands:
  - `pm rc select <start> [end]` → POST `/api/select`.
  - `pm rc focus <top_line>` → POST `/api/focus`.
  - `pm rc propose` → reads stdin → POST `/api/propose`.
  - `pm rc accept` → POST `/api/accept`.
  - `pm rc reject` → POST `/api/reject`.
  - `pm rc status` → GET `/api/doc` and prints path, viewport, selection,
    short proposal preview (first ~80 chars). Output is plain text aimed
    at being read by Claude in its tool result.

### 1.5 Cleanup

- The rc-driver pane closing should terminate the server. Because the
  server is a **separate process** unrelated to the pane PTY, we hook
  cleanup into the existing pane-exit path
  (`pane_layout.handle_pane_exited`, pane_layout.py:507). Add a check:
  when an unregistered/registered pane exits, look up
  `data["rc_servers"][window]` and, if the exiting pane was the
  rc-driver in that window (or no rc-driver remains), `os.kill(pid,
  SIGTERM)` and remove the entry.
  - Implementation: extend `handle_pane_exited` to call a new
    `pm_core.rc.cleanup.maybe_kill_server(session, window)` helper that
    encapsulates the logic. This avoids growing pane_layout's surface.

### 1.6 Tests (`tests/test_rc.py`)

- `pm rc start` outside a pm session → exits 1 with clear error.
- `--port` collision: bind a socket to a port, then assert
  `pm rc start --port <that>` exits with "in use".
- `--port` not given: server picks any free port.
- Server endpoint unit tests using FastAPI's `TestClient`:
  - `select` sets selection and viewport.top = start-3 (clamped to 1).
  - `focus` sets viewport.top, leaves selection.
  - `propose` errors 400 without selection.
  - `accept` writes proposal to disk, increments version, clears state.
  - `reject` clears proposal, preserves selection.
- SSE: connect a client to `/api/events`, mutate selection, assert event
  received. Use `TestClient.stream`.
- Multiple SSE clients: both receive events; `/api/viewport` last-write-
  wins reflected in stored viewport.
- Tmux integration tests are out of scope (consistent with how
  test_companion_pane.py mocks tmux); window/registry assertions verify
  correct calls to `tmux_mod.new_window_get_pane` and
  `pane_registry.locked_read_modify_write`.

## 2. Implicit Requirements

- `fastapi` and `uvicorn` are not currently in `pyproject.toml`'s
  `dependencies`. Adding them adds heavyweight installs to every pm
  user. Resolution: add them under a new optional extra
  `pm[rc]` and have `pm rc start` print a clear install hint
  (`pip install 'pm[rc]'`) when imports fail. Tests for endpoint
  behavior gate on FastAPI being importable
  (`pytest.importorskip("fastapi")`).
- `pm rc <verb>` non-`start` commands must work even when not inside a
  pm session, but only need the loopback URL — they read it from the
  registry. They still require they're in a tmux pane that maps to a pm
  session, so the registry can be located.
- The rc-driver Claude session needs a system prompt distinct from
  normal pm prompts. We do **not** use `build_claude_shell_cmd`'s
  prompt argument (which is treated as the *first user message*).
  Instead pass the system prompt via Claude's
  `--append-system-prompt` flag — this requires building the cmd
  manually around `build_claude_shell_cmd`'s output, OR adding the
  flag in a thin wrapper. Decision: build the command manually in
  `pm_core/cli/rc.py` (`claude --dangerously-skip-permissions
  --append-system-prompt @<file>`), bypassing `build_claude_shell_cmd`,
  to avoid leaking rc-specific concerns into the shared launcher.
- `viewer.html` must render correctly when served over LAN to a real
  phone — the page must not load any third-party CDN resources (LAN
  only network may have no internet). All JS/CSS inline.

## 3. Ambiguities (Resolved)

- **`/api/doc` `text` on update event**: Spec says state events omit
  `text`, but on accept a follow-up `event: doc` carries the new text.
  Resolution: emit two events on accept — first `state` (with new
  version, cleared selection/proposal), then `doc` carrying the full
  new text. Clients use the `doc` event to refresh DOM; `state` events
  alone never refresh text.
- **Registry shape for rc-server**: introduce a top-level `rc_servers`
  dict keyed by window id (see §1.1) rather than encoding rc-server as
  a fake pane, so reconciliation doesn't drop it.
- **Multiple rc windows in one session**: the spec implies one rc
  window at a time, but doesn't forbid more. Resolution: allow many;
  every `pm rc start` opens a new window with its own port, and
  subcommands resolve via current window id. Adding a second
  `pm rc start` for the same path issues a warning but is permitted.
- **`pm rc status` output format**: plain text, one item per line:
  `path: ...`, `viewport: top=.. bottom=..`, `selection: 12-15`,
  `proposal: "<first 80 chars>…"`. Designed to be readable by Claude
  via tool output.

## 4. Edge Cases

- **External edits to the file** while a session is open: `/api/doc`
  always re-reads from disk, so external edits show up on the next
  fetch. SSE doesn't auto-emit on external change (no inotify); user
  must reload or trigger a state change. Acceptable for v1.
- **Selection range past end of file**: `/api/select` validates
  `1 <= start <= end <= total_lines` and returns 400 otherwise.
- **Proposal contains trailing newline / not**: accept normalizes by
  re-splitting on `\n` and rejoining; preserves a trailing newline iff
  the replaced range ended with one.
- **Server crash**: rc-driver pane survives but all `pm rc <verb>`
  calls fail. The CLI prints a hint pointing at `~/.pm/rc-logs/<pid>.log`.
- **Reconnection storms** from many clients: SSE subscriber list grows
  unbounded if disconnects aren't observed. Mitigation: each subscriber
  enqueue uses `put_nowait`; if the queue is full (size>100) the
  subscriber is dropped on the next tick.
- **Closing tmux window vs. closing pane**: `handle_pane_exited` runs
  per pane. The cleanup helper checks for "rc-driver no longer alive"
  rather than "pane just exited had role rc-driver", so killing the
  whole window cleans up correctly.
- **`pm rc start` from a pm session that was created for a different
  workdir**: works — registry is per-pm-session, not per-workdir.
- **LAN IP changes** (laptop moves networks): printed URL becomes
  stale. Out of scope for v1; user re-runs `pm rc start`.

## 5. Out of Scope (explicit)

- Auth / TLS — explicit from task spec.
- Persistent state across server restarts — in-memory only.
- Concurrent edit conflict resolution beyond version field — clients
  see last-writer-wins.
- Inotify / file watching for external edits.
- Mobile-specific PWA install metadata.
