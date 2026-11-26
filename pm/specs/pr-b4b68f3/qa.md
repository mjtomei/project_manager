# QA spec — pr-b4b68f3: decouple TUI in-memory state from project.yaml via a coalescing write queue

## Summary

The TUI used to persist `project.active_pr` to `project.yaml` synchronously on
every cursor move (`handle_pr_selected` → `store.locked_update`). With a large
PR set (~330) each keypress did a file lock + full-yaml parse + full rewrite,
blocking the asyncio event loop for hundreds of ms — so held j/k/h/l keys
batched and "results appeared all at once."

The fix introduces `store.WriteQueue`: a coalescing, debounced, off-event-loop
write queue. TUI mutations update `app._data` (in-memory source of truth)
immediately and enqueue a tagged disk op. A background worker debounces bursts,
then drains all pending ops in one `locked_update` (which re-reads disk under
the lock, so concurrent external edits are preserved). Shutdown/restart paths
flush the queue synchronously. `handle_pr_selected` and `toggle_merged` are
routed through the queue; read-after-write and CLI sites stay on `locked_update`.

## Shared resources touched (concurrency inventory)

- **`project.yaml`** — the on-disk state file. Written by: the TUI write-queue
  worker thread, `flush_sync` on shutdown/restart, the synchronous fallback
  path, every CLI `pm` invocation, and any other concurrent pm process. This is
  the central contended resource — must be exercised under concurrent writers.
- **`project.yaml.lock`** — the advisory flock guarding every read-modify-write.
  Worker thread, CLI processes, and external pm processes all contend on it with
  a 2s timeout.
- **`app._data`** — in-memory dict, mutated on the event-loop thread and read by
  all UI renders. Decoupled from disk by this PR.
- **`WriteQueue._pending`** — pending-ops map touched from the event-loop thread
  (`enqueue`) and the worker thread (`_drain_once` via `to_thread`); guarded by a
  `threading.Lock`.

## 1. Requirements (Given / When / Then)

### R1 — Selection is responsive under rapid navigation
- **Given** a pm TUI open on a project with a large PR set (~300+ PRs) so a
  full lock+parse+rewrite per keypress is measurably slow,
- **When** the user holds j/k (or h/l) to move the tech-tree selection rapidly
  across many PRs,
- **Then** the highlighted selection follows the input in real time — it does
  not freeze and then jump several positions at once — and the per-selection
  handling cost is dramatically lower than the pre-fix synchronous write
  (pre-fix baseline ~300ms+/keypress at this size; post-fix ~0).

### R2 — Rapid navigation coalesces to a single final disk write
- **Given** a pm TUI open on a project, with the current `active_pr` recorded in
  `project.yaml`,
- **When** the user rapidly navigates the selection across N PRs and then stops,
- **Then** after the debounce window `project.yaml` contains exactly one updated
  `active_pr` value — the final selected PR — not a sequence of intermediate
  writes (a `git diff` of `project.yaml` shows a single `active_pr:` change).

### R3 — In-memory selection is immediate and authoritative
- **Given** a pm TUI open on a project,
- **When** the user moves the selection to a PR,
- **Then** the UI reflects the new selection immediately (driven by `app._data`),
  before — and independently of — the disk write landing.

### R4 — Quitting flushes pending writes
- **Given** a pm TUI where the user has just changed the selection (a write is
  still pending in the queue / debounce window),
- **When** the user quits the TUI (non-tmux `app.exit()` path, firing
  `on_unmount`),
- **Then** the pending `active_pr` write is flushed to `project.yaml` before the
  process exits, and re-launching the TUI restores the selection on that PR (no
  lost mutation).

### R5 — Restart flushes pending writes
- **Given** a pm TUI where the user has just changed the selection,
- **When** the user triggers an in-place restart (`ctrl+r` → `restart_app`, which
  uses `execvp` and does **not** fire `on_unmount`),
- **Then** the pending write is flushed before the process is replaced, and the
  restarted TUI comes up on the final selected PR.

### R6 — Concurrent external edits are not clobbered
- **Given** a pm TUI open on a project with a pending queued write, **and** a
  separate pm process (or CLI command) edits a different part of `project.yaml`
  (e.g. adds a PR, changes another PR's status) at roughly the same time,
- **When** the queue worker drains,
- **Then** the drain re-reads fresh on-disk state under the lock and layers its
  queued ops on top, so both the external edit and the queued `active_pr`/
  `hide_merged` change are present in the final file — neither is lost.

### R7 — Toggle-merged is routed through the queue and persists
- **Given** a pm TUI open on a project with both merged and unmerged PRs,
- **When** the user toggles the "hide merged" filter (`X`),
- **Then** the tree immediately shows/hides merged PRs (in-memory), and after the
  debounce window `project.yaml`'s `project.hide_merged` reflects the toggled
  value; the setting survives a restart.

### R8 — CLI / one-shot writes still work synchronously
- **Given** no running TUI,
- **When** the user runs a `pm` CLI command that mutates project state (e.g.
  `pm pr add`, status changes, plan operations),
- **Then** the change is written to `project.yaml` synchronously and immediately
  visible to the next read — CLI paths are unaffected by the queue.

## 2. Setup (cross-cutting)

- Install the branch build into the container (`./install.sh --local` from the pm
  repo, or `pip install -e .` with `PYTHONPATH` pointed at the clone; confirm with
  `pm which`).
- Create a throwaway project (`git init`; `pm init --backend local --no-import`).
- For lag/coalescing scenarios, seed a **large** PR set (~300+; the bug report
  used ~330). Scripted `pm pr add` is slow at that volume; bootstrapping the PR
  list by writing `project.yaml` once before the first session is acceptable
  per the TUI-manual-test instruction's "edit project.yaml to bootstrap the
  fixture" allowance. After setup, drive all changes through pm/TUI.
- Start the session with `pm session` (ignore the no-TTY attach error) and drive
  the TUI from outside via `pm tui send` / `tmux send-keys`, capturing with the
  tmux-screen-recording recipe.
- A standalone timing harness already exists in this PR's captures
  (`impl/pre-fix/repro_prefix.py`, `impl/post-fix/repro_b4b68f3.py`) showing
  ~316ms/keypress → ~0ms over a 330-PR project; it can seed the measurement
  scenario.

## 3. Edge cases / failure modes (Given / When / Then)

### E1 — Holding a key continuously, then quitting mid-burst
- **Given** the user is still holding j/k at the moment they quit/restart (the
  resetting debounce never got a quiet window to drain),
- **When** the TUI tears down,
- **Then** `flush_sync` drains the still-pending op and the final selection
  persists.

### E2 — Worker not yet started / no queue present
- **Given** a selection event arrives before `on_mount` finished wiring the queue
  (or in a context with no queue, e.g. `_write_queue is None`),
- **When** `handle_pr_selected` runs,
- **Then** it falls back to a synchronous `locked_update` and the selection still
  persists (no crash, no lost write).

### E3 — A queued op raises
- **Given** a queued mutation closure that raises when applied,
- **When** the worker drains,
- **Then** the error is logged and contained — the worker keeps running and a
  subsequent valid op still drains successfully (the bad op does not wedge the
  queue or kill the worker task).

### E4 — Lock timeout / unparseable yaml during drain
- **Given** the lock is held long enough to time out, or the file is briefly
  unparseable,
- **When** the worker attempts a drain,
- **Then** the `StoreLockTimeout` / `ProjectYamlParseError` is caught and logged,
  the worker survives, and the next drain reapplies the still-pending ops (the
  pending state isn't silently discarded on failure — verify behavior).

### E5 — Distinct keys in the same burst
- **Given** both an `active_pr` change and a `hide_merged` toggle queued before a
  drain,
- **When** the worker drains,
- **Then** both are applied in a single `locked_update` (one disk write carrying
  both changes), in stable order.

### E6 — Disk vs memory divergence is acceptable and self-heals
- **Given** the worker persists to disk only and does not push merged data back
  into `app._data`,
- **When** an external edit changes a field the TUI also caches,
- **Then** the running TUI keeps showing its in-memory value until the next
  background-sync / reload, and that reload reconciles — no crash, no corrupted
  file. (Documents the intended A2 behavior; verify no lost-update of the
  user's own active_pr.)

## 4. Pass/Fail criteria

- **Pass** when, on the branch build: rapid navigation is smooth and selection
  tracks input in real time (R1); a burst of N selections produces exactly one
  final `active_pr` write to disk (R2); the measured per-selection cost drops
  dramatically vs. the pre-fix synchronous path (R1, measured); quit and restart
  both flush pending writes so no selection is lost and the next launch restores
  it (R4, R5); a concurrent external edit during a pending drain survives
  alongside the queued change (R6); toggle-merged persists and survives restart
  (R7); CLI writes remain synchronous and immediately visible (R8); failure
  modes are contained and logged without killing the worker or losing the final
  state (E1–E6).
- **Fail** when: selection batches/stalls under load; intermediate `active_pr`
  values get written (more than one disk write per burst, or a non-final value
  persisted); pending writes are lost on quit/restart; a concurrent external
  edit is clobbered; toggle-merged doesn't persist; a queued-op error wedges the
  queue or crashes the TUI; or CLI writes regress.

## 5. Ambiguities (resolved)

- **Measuring R1.** "Responsive" is subjective; the PR notes ask for a measured
  latency drop. Resolved: drive the running TUI under load via the tmux surface
  AND use the existing timing harness / instrument `handle_pr_selected` over a
  burst to assert a large drop plus exactly one final disk write. The
  user-facing assertion is "selection tracks input without batching"; the
  measurement backs it up.
- **Pre-fix comparison.** The repro must demonstrate the bug existed. Resolved:
  run the comparison against the pre-fix code (the master baseline or the
  `impl/pre-fix/` harness) to show batching/high per-keypress latency, then the
  branch build to show smooth nav and one coalesced write.
- **Debounce timing for R2.** Default debounce is 0.1s; the test must wait past
  the debounce window before asserting the single disk write. Resolved: allow a
  short settle (>debounce) before reading `project.yaml`.

No **[UNRESOLVED]** ambiguities.
