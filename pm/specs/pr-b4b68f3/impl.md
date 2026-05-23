# Impl spec — pr-b4b68f3: decouple TUI in-memory state from project.yaml via a coalescing write queue

## Problem (grounded)

`pm_core/tui/pr_view.py:handle_pr_selected` (line 42) runs on the asyncio main
thread for **every** PR selection change. `TechTree._on_key`
(`pm_core/tui/tech_tree.py:789,798`) posts a `PRSelected` message on every
j/k/h/l move that changes selection; `ProjectManagerApp.on_prselected`
(`app.py:736`) forwards it to `handle_pr_selected`, which calls
`store.locked_update(...)` synchronously:

```
with _lock(root, timeout):        # flock on project.yaml.lock
    data = load(root)             # parse the full ~18k-line yaml
    fn(data)                      # set project.active_pr
    save(data, root)              # chmod + atomic rewrite + fsync of whole file
```

With ~330 PRs, each keypress blocks the event loop for hundreds of ms, so
Textual queues subsequent keys and processes them in a batch ("first press
lags, next few queue, results appear all at once").

## 1. Requirements (grounded in code)

- **R1 — Non-blocking selection.** `handle_pr_selected` must not perform file
  lock / yaml parse / yaml write on the main thread. Selection updates
  `app._data` in memory and returns immediately. (`pr_view.py:42-56`)
- **R2 — Coalesced single write.** After rapid navigation across N PRs,
  exactly one `active_pr` write reaches disk, holding the final selection — not
  one write per intermediate selection.
- **R3 — Flush on shutdown.** TUI teardown flushes pending writes before the
  process goes away. Relevant teardown paths:
  `ProjectManagerApp.on_unmount` (`app.py:1069`) for `app.exit()` (non-tmux),
  and `pane_ops.restart_app` (`pane_ops.py:694`, uses `os.execvp`, which does
  **not** fire `on_unmount`).
- **R4 — Conflict resolution.** Concurrent external edits to `project.yaml`
  from another pm process must not be clobbered: queued ops are re-applied on
  top of fresh on-disk state under the lock. This is exactly what
  `locked_update`'s closure API already gives us — the worker routes through it.
- **R5 — New plumbing.** Add a `WriteQueue` class to `pm_core/store.py` with
  `enqueue(key, fn)` and a drain mechanism. `locked_update` stays unchanged for
  one-shot CLI use. `ProjectManagerApp` owns a `WriteQueue`, starts its worker
  on mount, flushes on teardown.

## 2. Implicit requirements

- **I1 — Worker I/O off the event loop.** Coalescing reduces the *number* of
  writes, but a single `locked_update` is still hundreds of ms of blocking I/O.
  If the drain ran inline on the event loop it would reintroduce the stall (just
  less often). The worker must run `locked_update` via `asyncio.to_thread` so
  the blocking lock+parse+write happens on a thread, not the loop.
- **I2 — Thread-safe pending map.** Because the drain body runs in a worker
  thread (`to_thread`) while `enqueue` runs on the event-loop thread, the
  pending-ops map is touched from two threads and must be guarded by a
  `threading.Lock`.
- **I3 — In-memory is source of truth.** `handle_pr_selected` mutates
  `app._data` directly *and* enqueues the disk op. The two must set the same
  value so memory and the eventual disk state agree. The worker does **not**
  write its merged result back into `app._data` (see Ambiguity A2).
- **I4 — Graceful absence of a queue.** Code paths that call the routed
  functions outside a running app (unit tests, or before the worker starts) must
  still work. `handle_pr_selected`/`toggle_merged` fall back to a synchronous
  `locked_update` when `app._write_queue is None`.
- **I5 — Idempotent / safe flush.** `flush_sync()` must be callable from a
  synchronous shutdown context (no event loop guarantee) and be a no-op when the
  queue is empty.
- **I6 — Error containment.** A failed drain (`StoreLockTimeout`,
  `ProjectYamlParseError`) must not kill the worker task or crash teardown; it is
  logged and the worker keeps running. Matches existing `except
  (StoreLockTimeout, ProjectYamlParseError)` handling at the call sites.

## 3. Scope of routed mutation sites

The hot path is `handle_pr_selected` (fires on every cursor move). The acceptance
criteria are all about `active_pr`. I route the **fire-and-forget, high-frequency
project-settings writes** through the queue and leave **read-after-write,
one-shot** sites on `locked_update`:

Routed through `WriteQueue`:
- `pr_view.handle_pr_selected` — `project.active_pr` (key `("set","active_pr")`).
  THE fix.
- `pr_view.toggle_merged` — `project.hide_merged` (key `("set","hide_merged")`).
  Same shape: a project-level UI setting, no immediate `_load_state()` after.

Left on `locked_update` (deliberately — see Edge cases E1):
- `pr_view.handle_plan_pick` (3 sites), `qa_loop_ui`, `review_loop_ui`,
  `sync.py`, `watcher_ui` — each calls `app._load_state()` (or otherwise reads
  back) immediately after the write, so it needs the write to have landed
  synchronously, and none is on the per-keypress hot path. Routing these async
  would make the subsequent disk read observe stale state.
- All `pm_core/cli/*` paths — one-shot CLI processes, per R5.

## 4. Design

### `store.WriteQueue`

```python
class WriteQueue:
    def __init__(self, root, *, validate=True, timeout=LOCK_TIMEOUT_SECONDS,
                 debounce=0.1): ...
    def enqueue(self, key, fn):           # called on event loop; replaces same-key op
    async def run(self):                  # worker coroutine; debounce + to_thread drain
    def flush_sync(self):                 # synchronous drain for shutdown paths
    def _drain_once(self):                # swap pending under lock; one locked_update
```

- `_pending: dict[Hashable, Callable[[dict], None]]` guarded by
  `threading.Lock`. `enqueue` does `with lock: pending[key] = fn` (dict assignment
  on an existing key keeps insertion order → stable apply order), then sets an
  `asyncio.Event` to wake the worker.
- **Coalescing**: re-enqueuing an existing key replaces the closure, so 12 rapid
  `active_pr` enqueues collapse to one pending op with the final value.
- **Debounce (resetting)**: the worker waits for the event, then waits up to
  `debounce` seconds for the *next* enqueue; each new enqueue resets the timer.
  When the burst goes quiet for `debounce`, it drains once. Holding a key →
  continuous enqueues → no drain until release → a single write of the final
  value (satisfies R2 cleanly). Shutdown flush covers the "still holding at exit"
  corner.
- **Drain**: `_drain_once` atomically swaps out the pending dict, then calls
  `store.locked_update(root, apply)` where `apply(data)` runs every pending fn in
  order. `locked_update` re-reads disk under the lock first (R4). The worker
  invokes `_drain_once` via `await asyncio.to_thread(self._drain_once)` (I1);
  `flush_sync` invokes it directly (shutdown, blocking is fine).
- Errors from `_drain_once` are caught/logged in both the worker loop and
  `flush_sync` (I6).

### `ProjectManagerApp` wiring

- `__init__`: `self._write_queue = None`.
- `on_mount`: after `self._load_state()` sets `self._root`, create
  `self._write_queue = store.WriteQueue(self._root)` and start its worker with
  `self.run_worker(self._write_queue.run(), exclusive=False)` (guarded on
  `self._root is not None`).
- `on_unmount`: `if self._write_queue: self._write_queue.flush_sync()` (before
  the existing pidfile cleanup).
- `pane_ops.restart_app`: `app._write_queue.flush_sync()` before
  `stop_application_mode()` / `execvp` (R3 — execvp skips on_unmount).

### Call-site change (handle_pr_selected)

```python
if app._data.get("project", {}).get("active_pr") != pr_id:
    app._data.setdefault("project", {})["active_pr"] = pr_id   # in-memory now
    if getattr(app, "_write_queue", None) is not None:
        app._write_queue.enqueue(
            ("set", "active_pr"),
            lambda d: d.setdefault("project", {}).__setitem__("active_pr", pr_id),
        )
    else:
        try:
            app._data = store.locked_update(
                app._root,
                lambda d: d.setdefault("project", {}).__setitem__("active_pr", pr_id),
            )
        except (store.StoreLockTimeout, store.ProjectYamlParseError) as e:
            _log.warning("handle_pr_selected: %s", e)
```

`toggle_merged` gets the analogous treatment (it already mutates `tree._hide_merged`
in memory; route the `project.hide_merged` persist through the queue with a
fallback).

## 5. Ambiguities

- **A1 — Debounce window. [resolved]** Description says "debounce emerges
  naturally." A pure event-driven worker (no debounce) yields ≤2 writes per burst
  (one possibly in flight when the burst starts, one after). A *resetting*
  debounce yields exactly one write per burst, matching the acceptance wording
  "exactly one active_pr write reflects the final selection" and the verification
  "git diff shows a single active_pr change." → Use a resetting debounce, default
  0.1s. Persistence latency of ~100ms after the user stops moving is invisible
  (UI reads `app._data`, which is already updated).
- **A2 — Does the worker push merged data back into `app._data`? [resolved:
  no].** `locked_update` returns disk+queued-ops merged data. Writing that back
  into `app._data` races with concurrent in-memory mutations on the event loop
  and could momentarily clobber a just-set value. `app._data` is already
  refreshed from disk by `_background_sync` (5-min interval), `action_reload`
  (SIGUSR1), and manual refresh. So the worker persists only; it does not mutate
  `app._data`. This is the intended decoupling.
- **A3 — Flush on tmux "quit"? [resolved: no].** `pane_ops.quit_app` in tmux
  mode runs `detach-client` — the app process keeps running and the worker keeps
  draining, so no data is at risk and no flush is needed. The non-tmux branch
  calls `app.exit()`, which fires `on_unmount` (flush there). The real
  process-replacement risk is `restart_app`'s `execvp`, handled explicitly.

No **[UNRESOLVED]** ambiguities.

## 6. Edge cases

- **E1 — read-after-write sites.** Functions that `_load_state()` right after a
  write must keep synchronous `locked_update`, else the reload reads pre-write
  disk state. Hence the routing scope in §3.
- **E2 — Worker not yet started / no project.** `handle_pr_selected` can run
  before `on_mount` finishes (tests, early events) or with `_root is None`. The
  `_write_queue is None` fallback to synchronous `locked_update` covers it; if
  `_root` is also None the existing code already wouldn't persist.
- **E3 — Lock contention with the worker thread.** The worker holds the
  project.yaml flock only for the brief `_drain_once`; CLI processes and the
  worker contend on the same flock with the existing 2s timeout. Coalescing makes
  the worker grab the lock far less often than the pre-fix per-keypress path, so
  contention drops, not rises.
- **E4 — Rapid quit during a burst.** User holds a key then immediately
  restarts/quits. `flush_sync` drains whatever is pending (including a
  burst the resetting debounce never flushed), so the final selection persists
  (R3).
- **E5 — Exception in a queued fn.** Caught at drain level; logged; does not
  kill the worker (I6). The bad op is dropped from pending (already swapped out).
- **E6 — `to_thread` and Textual.** The drain only touches `store` + the
  filesystem, never Textual widgets, so running it on a thread is safe (no UI
  access off the main thread).

## 7. Test plan

- **Unit (store.WriteQueue)** in `tests/test_store_write_queue.py`:
  - coalescing: enqueue `("set","active_pr")` 12× with different values; run the
    worker; assert disk has exactly the final value and `save` was called once.
  - flush_sync drains pending synchronously and writes the final value.
  - conflict resolution: pre-seed an external edit on disk between enqueue and
    drain; assert the external field survives and the queued field is applied.
  - error containment: a queued fn that raises is logged and doesn't break the
    next successful drain.
- **Repro/regression (handle_pr_selected)**: a stub `app` with `_data`, `_root`,
  a real `WriteQueue`, and no-op `log_message`/`call_after_refresh`; simulate N
  selections; assert `store.save` is **not** called per selection (pre-fix: N
  saves → fails; post-fix: 0 inline saves, then 1 after flush). This is the
  codified bug repro.
- Run `tests/test_store*.py`, `tests/test_tui_extracted_modules.py`,
  `tests/test_tui_imports.py` for regressions.

## 8. Manual verification

Per `pm/qa/instructions/tui-manual-test.md` + `pm/qa/artifacts/tmux-screen-recording.md`:
seed a throwaway project with many PRs, hold j/k, observe pre-fix batching/lag vs
post-fix smooth nav, and confirm `git diff project.yaml` shows a single final
`active_pr:` change. Pre-fix capture → `$CAP/impl/pre-fix/`, post-fix →
`$CAP/impl/post-fix/`.
