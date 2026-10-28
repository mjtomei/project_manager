# Implementation spec — pr-c3bf868

Bug: stale TUI pidfile lets picker / reload IPC silently target a dead or
wrong process.

## Code map (current, pre-fix)

| Concern | Location |
| --- | --- |
| Pidfile path + signal helpers | `pm_core/cli/helpers.py` — `_tui_pidfile_for_session` (L484), `trigger_tui_reload` (L490), `trigger_tui_command` (L549) |
| Queue path | `pm_core/cli/helpers.py` — `_tui_command_queue_for_session` (L543) |
| TUI writes pidfile + installs handlers | `pm_core/tui/app.py` — `_reload_pidfile` (L1270), `_command_queue_file` (L1278), `_install_reload_signal` (L1284), `on_unmount` (L1396) |
| TUI mount order | `pm_core/tui/app.py` — `on_mount` (L486); session name resolved at L~495, `_install_reload_signal()` at L~512 |
| TUI process entry | `pm_core/cli/tui.py` — `tui_cmd` (`pm _tui`, L~26); redirects **stderr** to `~/.pm/debug/tui-stderr.log`, stdout stays on the pane |
| Exec restart | `pm_core/tui/pane_ops.py` — `restart_app` (L~739) sets `SIG_IGN` for SIGUSR1/2 across `execvp` |
| Picker dispatch | `pm_core/cli/session.py` — `_run_picker_command` (L~1848), `_wait_for_tui_command` (L1485) |
| Other pidfile reader | `pm_core/cli/autostart.py` — `_resolve_owner` (L65) reads the file with `int(...)` |

Facts established from history: the numeric pidfile and the SIGUSR1
handler were introduced in the **same** commit (`9c30b38a`), so a numeric
pidfile proves SIGUSR1 support. SIGUSR2 was added later, which is exactly
the version-skew failure in the report.

## Requirements (grounded)

R1. **Versioned descriptor.** The TUI writes JSON
    `{"version":1,"pid":<pid>,"started_at":<iso>,"starttime":<proc starttime>,
    "session":<name>,"caps":["sigusr1","sigusr2"]}` instead of a bare pid.
    `starttime` is `/proc/<pid>/stat` field 22 (jiffies since boot) — a
    PID-reuse-proof identity token. `started_at` is informational.
    Implemented in a new neutral module `pm_core/tui_pidfile.py` so both
    `pm_core/cli/helpers.py` and `pm_core/tui/app.py` can use it without an
    import cycle.

R2. **Capability gate.** `trigger_tui_reload` requires cap `sigusr1`;
    `trigger_tui_command` requires `sigusr2`. A missing cap means the
    signal is **never sent**; the caller gets a reason it can surface.
    Legacy numeric pidfiles are parsed as a descriptor with
    `caps={"sigusr1"}, legacy=True` (see Ambiguity A1).

R3. **Publish capabilities only after handlers are ready.** The pidfile is
    created at claim time with `caps: []`; `caps` are rewritten (atomically)
    only after `loop.add_signal_handler` succeeded for each signal. A caller
    that reads the file in between sees no caps and refuses to signal.

R4. **TUI-side takeover.** Before installing handlers the TUI claims the
    pidfile atomically (`O_CREAT|O_EXCL`):
    - file absent → create ours;
    - file present, parses to a **live** PID whose `/proc/<pid>/cmdline`
      is a pm TUI → refuse to start with a clear message and exit non-zero
      (`TuiPidfileConflict`);
    - file present, PID is our own PID (exec restart) → take over;
    - file present but stale/unreadable/PID dead/PID reused/non-TUI cmdline
      → unlink and take over.

R5. **Caller-side identity validation.** Before signaling, validate:
    liveness (`kill(pid,0)`), not a zombie, `starttime` matches the
    descriptor, and `/proc/<pid>/cmdline` has an exact `_tui` argv element
    plus a pm entry-point element (an argv element whose basename is `pm`,
    or any `pm_core` / `pm_core.*` module — see E15). Any failure → no signal, remove the stale pidfile
    (only if unchanged since read), return False with a reason.
    Where `os.pidfd_open` and `signal.pidfd_send_signal` exist (Linux
    5.3+/py3.9+), the signal is *delivered through the pidfd*, not
    `os.kill(pid)`: a bare kill re-resolves the PID number and could hit a
    recycled process, while a pidfd names one exact process and fails with
    `ESRCH` once it is gone. The descriptor's `starttime` is re-checked
    after the pidfd is opened (and the pidfd is closed afterwards). Without
    pidfd support the code falls back to `os.kill`. If procfs is
    unavailable, degrade to liveness only (documented).

R6. **Picker aborts.** `_run_picker_command` uses a new
    `submit_tui_command()` returning a `TuiIpcResult(ok, reason, message)`
    and prints `message` + `_wait_dismiss()` on failure. Additionally
    `_wait_for_tui_command` re-checks owner identity while spinning and
    aborts after ~3 s of continuous invalidity (covers "TUI killed after the
    signal was sent" and the original infinite `queued…` spinner).

R7. **No-op bootstrap.** `pm _tui` installs no-op SIGUSR1/SIGUSR2 handlers
    as the very first thing (before the claim, before Textual starts), so a
    signal arriving during startup can never take the default-terminate
    action. `restart_app`'s `SIG_IGN` across `execvp` stays.

R8. **Tests** (see `## Tests`).

## Implicit requirements

I1. `pm_core/cli/autostart.py::_resolve_owner` must read the JSON
    descriptor (it currently does `int(pidfile.read_text())`; after the
    change every pidfile is JSON and autostart would report every TUI as
    "stale pidfile"). It keeps its `kill(pid,0)` + zombie semantics so
    existing autostart tests (which write bare numeric pidfiles) still pass;
    the shared reader handles both formats. Its dispatch
    (`_request`) calls `submit_tui_command` rather than the bool
    `trigger_tui_command`, so the specific failure reason (missing
    capability, stale pidfile, ...) reaches the user instead of a generic
    "could not signal the TUI" — autostart is the other consumer of the
    SIGUSR2 path and would otherwise hide the "restart the TUI" fix.

I2. `on_unmount` must not delete a successor's pidfile: unlink only when
    the file still names our pid **and** our `starttime` (exec restarts and
    respawns can overlap). The command queue is shared with a successor, so
    it is removed only when the pidfile does not name a different process
    (`TuiPidfileClaim.owned_by_other`).

I3. The command queue file must exist before caps are published (a caller
    that sees `sigusr2` must not race a missing queue). Order in
    `_install_reload_signal`: claim → create queue → install handlers →
    publish caps. On the caller side the order is the mirror image: the
    line is appended *before* the signal (signaling first could drain an
    empty queue), and `_unqueue_line` removes it again under the same
    `flock` when the signal fails, so a failure the user is told about is
    not applied by some later drain. The rollback matches *whole lines by
    value*, wherever they sit in the file (not just at the tail), so a
    concurrent caller appending after ours cannot pin our failed command
    into the queue; every other line is kept byte-for-byte.

    The append reaches the kernel *inside* that `flock`: the drain reads
    and truncates the queue under the same lock, so a line still sitting
    in Python's write buffer at `LOCK_UN` would land in the file after a
    concurrent drain truncated it — silently dropping a command the
    caller was told was queued, with a healthy TUI so the spinner's owner
    check never aborts it. The append is therefore *unbuffered*
    (`open(queue, "ab", buffering=0)`), which makes that structural
    rather than a `flush()`-before-`LOCK_UN` obligation. Unbuffered is
    also what makes the partial-write rollback below work: when a
    buffered writer's flush fails CPython keeps the unwritten remainder
    in its buffer, so a `truncate` rollback re-raises from its own flush
    and leaves the half-line behind (and a later `close` would re-append
    the remainder). With a raw file the rollback is a plain `ftruncate`.

    One command is exactly one line on both sides of that protocol: the
    writer (`_queue_line`) replaces every character `str.splitlines`
    treats as a boundary (`\r`, `\x0b`, `\x0c`, `\x1c`-`\x1e`, `\x85`,
    U+2028, U+2029) with a space, and appends the line as UTF-8 *bytes*.
    Without that, a `\r` inside a command would make the drain see two
    commands while the `b"\n"`-splitting rollback saw one (so a reported
    failure could never be taken back), and a non-UTF-8 caller locale
    would make the written bytes differ from the rollback's UTF-8 target.
    The drain reads UTF-8 with `errors="replace"` so a garbled queue can
    never raise out of a signal handler.

    A *partial* line is rolled back too: `_unqueue_line` matches whole
    lines, so it cannot take back a short write (ENOSPC / quota, which
    the kernel is allowed to do) and a later drain would run a truncated
    command the caller was told was not applied. A short raw write that
    the kernel lets us finish is completed (the same loop
    `tui_pidfile._write_all` uses for the descriptor); a write that
    fails records the file's end and truncates back to it — under the
    same lock, best effort, since the write itself just failed.
    That end must be read *under* the `flock` (`os.fstat(f.fileno()).st_size`),
    not from `f.tell()`: append mode pins the stream position at
    `open()` time, so a line another caller appends between our open and
    our lock is not reflected there, and truncating to it would delete a
    command that caller was told was queued (or, after a concurrent
    drain shrank the file, extend it with NULs).

I4. `trigger_tui_reload` keeps its fire-and-forget behavior and its
    `refresh_home` side effect (existing tests assert the kick). It now
    returns `True` only when SIGUSR1 was actually delivered and `False`
    otherwise; every existing caller ignores the return value, so the
    signature change is backwards compatible.

I5. Backwards compatibility for an *older CLI* reading a JSON pidfile:
    `int()` fails → it logs and does nothing. Safe (no signal), acceptable.

I6. `_canonical_session` / `~N` grouped-session normalization must be
    preserved on both sides (callers already normalize; the TUI stores the
    `~`-stripped name).

I7. The TUI session name must be resolvable before `app.run()` for the
    pre-run claim. Factor the existing `on_mount` logic into
    `current_session_name()` in `app.py` and reuse it in `pm_core/cli/tui.py`.
    It resolves through `pm_core.tmux.get_session_name()` (pane-targeted),
    not a bare `display-message -p` — see E17.

I8. When the launcher claimed a pidfile, `on_mount` must use that claim's
    session name (`_session_for_claim`) rather than asking tmux again: a
    second `display-message` that fails (or returns a renamed session)
    would make `_reload_pidfile()` point somewhere else, so the claimed
    descriptor would never be published — it would sit at `caps: []` for
    the life of the TUI and every caller would report "has not finished
    starting up". It also guarantees `claim.path == pidfile` in
    `_install_reload_signal`, so the launcher's claim is never re-claimed.

## Ambiguities (resolved)

A1. *Legacy numeric pidfiles: empty caps or `{"sigusr1"}`?* The task text
    says "old TUIs implicitly have an empty caps list", but the numeric
    pidfile and the SIGUSR1 handler shipped in one commit — a numeric
    pidfile is positive evidence of SIGUSR1 support. **Resolution:** parse
    legacy files as `caps={"sigusr1"}, legacy=True`. Reload keeps working
    against a pre-upgrade TUI (no user-visible regression); SIGUSR2 — the
    mode-1 killer — is refused with the "predates the cmd-queue feature"
    message. Identity checks still apply, so PID reuse is still caught.

A2. *How is "exclusive ownership" made atomic without a lock file?*
    **Resolution:** `O_CREAT|O_EXCL` on the pidfile itself; on
    `FileExistsError` re-read and either refuse (live TUI) or unlink+retry.
    Two TUIs racing to start: one wins `O_EXCL`; the loser re-reads, sees a
    live pm TUI (or a just-created descriptor) and refuses. No litter, no
    stale-lock pathology. An *empty* file is ambiguous — the peer may be
    between its `O_EXCL` create and its first write — so the claim waits
    `_CLAIM_EMPTY_RETRIES` × `_CLAIM_RETRY_S` (2 × 50 ms) for the peer to
    publish before treating it as stale. That wait is keyed on the file
    being empty, not on the attempt number: the unlink/takeover rounds
    have their own attempt budget (`_CLAIM_MAX_ATTEMPTS`), so a peer's
    just-created file always gets the full wait even after earlier stale
    rounds. A non-empty unparsable file
    (corrupt/undecodable) is unlinked immediately. (Without the wait, a
    loser could delete the winner's just-created file and both TUIs would
    run, each `publish` overwriting the other's descriptor.)
    Running out of attempts is **not** a conflict: every exhaustion path
    is "the file never named a live TUI, but we could not remove it" (a
    live sibling raises `TuiPidfileConflict` on the round that observes
    it), so it raises `TuiPidfileUnavailable` — an `OSError` subclass —
    and the TUI runs without external IPC (see E13).

A3. *Where does the "clear error" go?* `pm _tui` redirects stderr to
    `tui-stderr.log`, so a stderr print is not visible in the pane.
    **Resolution:** the claim runs in `tui_cmd` **before** `app.run()`, and
    the conflict message is printed to stdout (the pane) and logged through
    the pm logger. A conflict detected later (defensive path inside
    `on_mount`) additionally calls `self.exit(return_code=2, message=...)`
    and `tui_cmd` re-prints `app._startup_error` to stdout after `run()`.

A4. *How long is "continuously invalid" for the spinner abort?* **Resolution:**
    3 s (`_TUI_GONE_GRACE_S`), checked at most once per second; long enough
    to ride out an exec/Ctrl+R restart, short enough to not strand the user.

A5. *Should a JSON descriptor with `caps: []` (TUI starting) be retried
    rather than errored?* **Resolution:** return False with reason
    `starting` and a message that names both possibilities — the TUI is
    still starting up (retry in a moment) or the handler install failed and
    the capabilities were never published (restart the TUI with Ctrl+R).
    The picker pops a dismissable message; the user re-runs the action. No
    blocking retry loop in the picker. The same both-possibilities wording
    is used for the other `starting` case — a zero-length pidfile (E3):
    a TUI killed between its `O_EXCL` create and its first write leaves
    the file empty for good, so "try again in a moment" alone would be a
    dead end and the message also names "restart the TUI (Ctrl+R)".

No **[UNRESOLVED]** items.

## Incidental fixes on this branch

These are outside the pidfile/IPC bug itself but were found while
implementing and QA-ing it, and ship here (each has a PR note):

- `pm_core/tui/pane_ops.py::heal_registry` resolved "the window" with
  `get_window_id(session)` — the session's *active* window. A TUI whose
  pane lives in any other window (a hand-started `pm _tui`, or the winner
  of the startup race) never re-registered its pane; the registry then
  lost the `tui` role entry and `_find_tui_pane` (`pm tui view`,
  `pm autostart`, …) reported "No TUI pane found" against a live TUI that
  owned the pidfile. It now resolves the window from `$TMUX_PANE`
  (`pane_window_id`), with the session window as a fallback. Fixed in QA
  commit `a2616b0d`; tests in `tests/test_pane_layout.py`
  (`TestHealRegistryOwnWindow`).
- `pm_core/qa_loop.py::_proc_stat_fields` / `resume_owned_elsewhere`: the
  same non-UTF-8 `comm` and out-of-range-PID crash class as E16, on the
  QA resume path (see E16 and test 29/32).

## Edge cases

E1. **PID is ours on exec restart.** `claim` must short-circuit on
    `desc.pid == os.getpid()` before the cmdline check (the pre-exec
    descriptor's `starttime` is identical, since exec keeps the process).
E2. **Zombie pidfile owner.** `kill(pid,0)` succeeds for a zombie; treat as
    dead (existing `_is_zombie` logic moves into the shared module). The
    same applies to a target that becomes a zombie *after* validation:
    both `os.kill` and `pidfd_send_signal` "succeed" against an unreaped
    process and then discard the signal, so `_signal_tui` re-checks
    `is_zombie` immediately before sending and reports
    `"process is a zombie"` (a stale-signal reason: the pidfile is
    removed and, for a queued command, the line is rolled back) rather
    than claiming a delivery nothing can handle.
E3. **Unreadable/empty pidfile.** Treated as "no TUI"; unlink only if the
    content is unchanged since the read (do not delete a just-created file).
    Undecodable bytes (`UnicodeDecodeError`) count as unreadable rather
    than propagating: a half-written pidfile must never crash the startup
    claim or the picker. A file that is present but unreadable is reported
    as `stale_pidfile` and removed; a missing one is `no_pidfile`. In the
    startup claim a *zero-length* file is retried briefly first (a peer may
    be mid-claim) and only then treated as stale (A2). The *caller* side
    applies the same reasoning: a zero-length file is reported as
    `starting` and is **never** unlinked, because deleting a peer's
    just-created file would let a second TUI claim the session while the
    first is still starting — the exact race A2 closes from the writing
    side. Both sides key on `raw == ""`, not `not raw.strip()`: the claim
    writes a whole JSON descriptor in one go, so whitespace-only content
    is corruption (unreadable → removed), never the mid-claim window, and
    a whitespace-only file must not be reported as "starting up" forever.
    The same "never crash on corruption" rule bounds the parsed values:
    `pid` must be a decimal integer in `1..2**31-1` (a C `int`, which is
    what `os.kill` takes — a larger value raises `OverflowError`, not
    `OSError`, out of the startup claim, the picker, and autostart) and
    string fields are gated on `str.isdecimal`, not `str.isdigit`
    (`"²".isdigit()` is true but `int()` refuses it, so a superscript
    digit in `pid` or `starttime` used to raise `ValueError` out of
    `parse_pidfile` itself). Both are rejected as unreadable, so the
    file is reported `stale_pidfile` and removed; `pid_alive` is also
    total for out-of-range input as defence in depth.
E4. **Permission denied** (`EPERM`) on signal → return False with a message;
    do **not** delete the pidfile (the process is alive, just not ours).
E5. **Legacy live TUI + `trigger_tui_reload`** → signals SIGUSR1 (A1).
E6. **Legacy live TUI + `trigger_tui_command`** → no signal, message
    "predates the command-queue feature; restart the TUI (Ctrl+R)".
E7. **`session=None`** in `trigger_tui_reload` → unchanged resolution path;
    on any failure it logs and returns.
E8. **Not in tmux** (`pm _tui` run directly): no session name → no claim,
    no pidfile (unchanged).
E9. **Queue append fails** → False (unchanged).
E10. **TUI restarts while the picker spins** → pidfile briefly absent;
    the 3 s grace prevents a false abort.
E11. **autostart with a JSON pidfile** → works via the shared reader.
E12. **A future signal** can be added safely: no-op guard + caps list.
E13. **~/.pm unwritable.** Claim I/O errors (`OSError`) are distinct from
    `TuiPidfileConflict`: the TUI logs a warning and keeps running without
    external IPC (previous behavior for a pidfile write failure), rather
    than refusing to start. `publish` failures are logged and swallowed.
    The same rule covers the claim *giving up*: a stale pidfile it cannot
    unlink (read-only `~/.pm`, a file owned by someone else) exhausts the
    attempt budget without ever naming a live TUI, so it raises
    `TuiPidfileUnavailable` (an `OSError`, not a conflict) and the TUI
    runs without external IPC. Callers then read the leftover file as
    stale and report/remove it, so the failure is visible in the CLI
    instead of killing the TUI.
E14. **Startup refusal must not clean up the sibling's files.** `on_unmount`
    removes the pidfile and queue only when this process holds the claim;
    a refused second TUI never unlinks files it does not own. If a
    successor has taken the pidfile over, the queue is left in place for
    it (it is the shared, session-keyed queue). A successor that is
    *between* its `O_EXCL` create and its first write shows up as an
    empty pidfile; that counts as "owned by another process" too
    (`TuiPidfileClaim.owned_by_other`), because the file can only be
    there if someone else created it after our release, and the queue it
    is about to use is the shared one.
E15. **TUI entry-point names.** The cmdline marker accepts an exact `_tui`
    argv element plus an entry point: an argv element whose basename is
    `pm`, or a `pm_core` / `pm_core.*` module — the shapes produced by the
    console script, the container's `pm` shim, and `python -m` fallbacks.
    Accepting any `pm_core.*` module (not an enumerated list) means a
    future entry-point rename (the planned `wrapper.py` -> `bootstrap.py`)
    cannot make callers classify a live TUI as "a different program" and
    delete its pidfile. Matching is per-element, never a substring of the
    joined command line.
E16. **The target process's own `/proc` entry can be non-UTF-8.**
    `/proc/<pid>/stat` carries `comm` — 16 bytes the process chooses
    itself — and a recycled PID is precisely the case where the file
    names an arbitrary unrelated process. A strict `read_text` raises
    `UnicodeDecodeError`, which escaped `proc_starttime` / `is_zombie`
    and therefore the *startup claim* (`pm _tui` crashed with a
    traceback instead of taking the stale pidfile over, and every retry
    did the same), `submit_tui_command` (the picker and `pm autostart`
    tracebacked instead of reporting `stale_pidfile`) and
    `autostart._resolve_owner`. Same class as the undecodable-pidfile
    case in E3: identity checks must never raise. `_proc_stat_fields`
    now decodes with `errors="replace"` (only the state char and the
    numeric fields after the final `)`, both ASCII, are used). The
    identical latent bug in `pm_core/qa_loop.py::_proc_stat_fields`
    (the QA resume snapshot's recorded owner PID) is fixed the same way
    — see the PR note for that incidental fix. The same "a corrupt
    snapshot must never raise" rule covers `resume_owned_elsewhere`'s
    `os.kill(pid, 0)`: an out-of-range `owner_pid` raises
    `OverflowError`, not `OSError`, and such a pid cannot exist, so it
    now reads as orphaned (resumable) instead of escaping the TUI's
    resume path.

E17. **The pidfile key must be *our* pane's session, not tmux's "current
    client".** The pidfile is keyed by session name, and with I8 the
    launcher's claim makes that name authoritative for the life of the
    TUI. `display-message -p "#{session_name}"` with no `-t` resolves
    against the most recently active client, so when a second client is
    attached to another pm session the TUI would claim *that* session's
    pidfile — and every caller, which resolves the session from
    `$TMUX_PANE` (`_find_tui_pane` -> `tmux.get_session_name`), would
    find no pidfile and silently lose IPC (autostart then reports
    `owner_unavailable`). `current_session_name()` therefore delegates to
    `tmux.get_session_name()`, which targets `$TMUX_PANE` — the same
    pitfall the popup bodies already pin `$S` for
    (`pm_core/cli/session.py`, `_pin_popup_body`).

E18. **An empty argv is a known non-TUI, not "unknown".** A process can
    have a zero-length `/proc/<pid>/cmdline` — a kernel thread
    (`mm == NULL`), or a zombie (already caught by `is_zombie`). The
    read used to return `None` for that, which `identity_problem` reads
    as "procfs unavailable, skip the cmdline check", so a stale pidfile
    whose recycled PID happened to name such a process looked like a
    live TUI: `claim_tui_pidfile` refused to start (`pm _tui` would not
    run until the file was deleted by hand) and
    `trigger_tui_reload` / `submit_tui_command` would have signaled it.
    `proc_cmdline` now returns `[]` for an empty read — positive evidence
    of a non-TUI — and keeps `None` for "cannot tell" (no procfs, read
    failed), which still degrades to liveness. This is the same class as
    E3/E16: an identity check must never misclassify an unrelated
    process as the TUI.

E19. **An empty argv is also what `execve` serves.** For the few hundred
    microseconds between `exec_mmap` and the new argv being installed,
    `/proc/<pid>/cmdline` reads zero-length (measured 0.2–3.6 ms on a
    loaded box; `comm` already shows the new binary). `restart_app`
    re-execs the TUI *in place*, keeping its PID, so E18's "empty argv is
    positive evidence of a non-TUI" would misclassify a live, restarting
    TUI as a foreign process: `_validate_tui_owner` would delete the live
    TUI's pidfile and report "not available (pid belongs to a different
    program); restart the TUI" for every caller that fires during a
    Ctrl+R restart, and `claim_tui_pidfile` would let a second TUI take
    the session over while the restarting one is still coming up — that
    one then refuses to start and its pane dies, breaking the
    single-TUI guarantee (A2/R4). So an empty read is re-polled for a
    bounded grace (`_EMPTY_CMDLINE_GRACE_S` = 100 ms, 10 ms steps)
    before it is believed: the exec window closes in milliseconds, while
    a kernel thread's argv never fills in, so E18's protection is kept
    and its cost is one bounded wait on a rare path. `identity_problem`
    goes through `_settled_cmdline`; `proc_cmdline` stays a pure read.
    A non-empty argv and `None` ("cannot tell") are returned
    immediately, so the ordinary path is unchanged.

E20. **"Cannot tell" can also mean "it just exited".** `proc_cmdline`
    returns `None` both when procfs is unavailable and when the read
    fails — and the read fails exactly when `/proc/<pid>` has gone away,
    i.e. when the process was reaped between `identity_problem`'s
    liveness check and its argv read. `identity_problem` skips the argv
    check on `None`, so a dead owner could be reported as "no problem":
    `claim_tui_pidfile` then raised `TuiPidfileConflict` against a *dead*
    TUI ("refusing to start a second TUI — stop pid N if it is not
    visible") and `pm _tui` could not start until the stale file was
    deleted by hand — the same failure class E18/E19 close, in the
    opposite direction. Liveness is therefore re-checked when the argv
    read was `None`; off-procfs platforms still report the pid alive, so
    they keep degrading to the liveness check and nothing changes there.
    (`submit_tui_command` / `trigger_tui_reload` were already safe here:
    `_signal_tui` re-checks and reports `process is not running`.)

## Tests

New `tests/test_tui_pidfile.py` (shared module + helper + app integration)
and additions to `tests/test_popup_picker.py` / a spinner test:

1. claim takes over a dead-PID pidfile; descriptor rewritten (pid ours,
   caps empty).
2. claim refuses when a live fake TUI (argv `…/pm _tui`) owns the session.
3. claim takes over when the recorded PID is alive but its cmdline is not a
   TUI (PID reuse).
4. claim allows `pid == os.getpid()` (exec restart).
5. `publish` rewrites caps atomically; `release` leaves a successor's
   descriptor alone.
6. `trigger_tui_command`: missing file → False; dead pid → False + file
   removed; starttime mismatch → False + file removed + process untouched;
   non-TUI cmdline → False + file removed; legacy → False with "predates"
   and process untouched; JSON `caps=[]` → False "starting up"; full caps →
   True, queue line written, child's SIGUSR2 handler fires.
7. `trigger_tui_reload`: legacy → child SIGUSR1 handler fires; JSON without
   `sigusr1` → False, child survives; dead pid → False + cleanup.
8. no-op guard: install guards, `os.kill(os.getpid(), SIGUSR2)`, still
   alive. Runs in a **child process** (a regression used to kill the whole
   pytest run instead of failing one test).
8a. pidfd delivery: `_signal_tui` uses `signal.pidfd_send_signal` (not
    `os.kill`) when a pidfd is available; refuses when the starttime no
    longer matches after the pidfd is opened; falls back to `os.kill`.
8b. undecodable (invalid-UTF-8) pidfile: `read_pidfile_text` returns
    `None` instead of raising; claim takes over and `submit_tui_command`
    reports `stale_pidfile` and removes it.
9. `_install_reload_signal` publishes both caps only after handlers are
   installed, and the queue file already exists when each handler is
   registered (I3 — captured inside the fake loop; verified to fail if
   the queue creation is moved after `publish`).
10. picker: `submit_tui_command` failure → message echoed, spinner not
    entered.
11. spinner: `tui_owner_problem` continuously failing → aborts with a
    message instead of spinning (patched grace, pipe stdin).
12. claim retry (A2): an empty file nobody writes is taken over; an empty
    file a peer fills in within the retry window raises
    `TuiPidfileConflict` and the peer's descriptor survives; an empty file
    is still waited for after two stale-file unlink rounds (the wait is
    keyed on content, not on the attempt number).
13. identity: a zombie owner is reported as `process is a zombie`;
    `tui_owner_problem` distinguishes `unreadable pidfile` from
    `no pidfile`.
14. descriptor parsing rejects `pid` values that `int()` would coerce
    (bool/float/null) while still accepting a numeric string; the
    `_install_reload_signal` conflict path sets `_startup_error`, exits
    with code 2, and never publishes or releases a pidfile it does not
    own.
15. `on_unmount` with an owned claim removes both the pidfile and the
    queue; when the pidfile names a successor it removes neither; when
    it is empty (a successor mid-claim) it also removes neither
    (`owned_by_other` is true for that window).
16. `submit_tui_command` when `_signal_tui` reports `permission denied`
    returns `signal_error` and leaves the pidfile in place (E4); reload
    with no pidfile returns False.
17. reload against a `caps=[]` descriptor (starting) → False and the
    pidfile is kept; reload against a descriptor missing `sigusr1` also
    keeps the pidfile.
18. `pm autostart` surfaces `submit_tui_command`'s message verbatim (the
    `owner_unavailable` failure carries "restart the TUI (Ctrl+R)", not a
    generic "could not signal the TUI").
19. empty pidfile on the caller side → reason `starting`, file kept,
    `tui_owner_problem` reports `empty pidfile` (mirrors A2/E3).
20. a failed signal after the queue append takes the line back
    (`_unqueue_line`), so a reported failure is not applied by a later
    drain. The rollback matches whole lines by value, so a later line
    another caller appended after ours is kept byte-for-byte and ours is
    still removed (two identical submissions are indistinguishable, so at
    most one copy is rolled back). A later command that merely *ends*
    with ours (`pm qa pr-1` ends with `qa pr-1`) is never sliced, and a
    line the TUI already drained makes the rollback a no-op.
21. a target that becomes a zombie between validation and the signal:
    `_signal_tui` returns `"process is a zombie"` without sending, and
    `submit_tui_command` reports `stale_pidfile`, removes the pidfile and
    rolls the queued line back (E2).
22. the claim's descriptor write fails (ENOSPC / short write): the empty
    file created by `O_EXCL` is removed before the error propagates, so
    callers are not told "has not finished starting up" for the whole
    life of the TUI; `_write_all` retries a short `os.write` instead of
    leaving a truncated descriptor. The conflict message names the
    pidfile path and pid (the only way out when procfs is unavailable and
    a recycled PID refuses startup, or when the owning process has no
    visible pane).
23. an unwritable command queue (E9) returns `queue_error`, keeps the
    pidfile, and never signals the TUI.
24. `pm _tui` launcher wiring (A3): a claim conflict is printed on stdout
    and exits 2 before the app is constructed; a successful claim is
    handed to `ProjectManagerApp(pidfile_claim=...)`; an `OSError` claim
    failure still starts the app without IPC; a conflict raised inside
    `on_mount` (`_startup_error`) is re-printed on stdout and exits 2.
25. a whitespace-only pidfile is `unreadable pidfile` (not `starting`),
    so `submit_tui_command` returns `stale_pidfile`, removes it, and
    `tui_owner_problem` agrees (E3: only a zero-length file is the
    mid-claim window).
26. `on_mount` takes its session name from the launcher's claim
    (`_session_for_claim`) so the published descriptor is the claimed one;
    without a claim it falls back to `current_session_name()` (I8).
27. the queued command is exactly one line for both sides of the
    protocol (I3): a command containing `\r`, `\x0b` and U+2028 is
    written as a single `\n`-terminated line whose `splitlines()` length
    is 1 and whose content is the sanitized command (pre-fix it drained
    as four commands while the rollback saw one); and a non-ASCII
    command is rolled back byte-for-byte, proving the writer and
    `_unqueue_line` agree on UTF-8 regardless of the caller's locale.
28. corrupt pidfile *values* never raise (E3): `parse_pidfile` rejects a
    `pid` outside `1..2**31-1` (legacy and JSON) and a string that
    `str.isdigit()` accepts but `int()` refuses (such as `"²"`) in `pid`
    or `starttime`; a huge-PID pidfile is then taken over by
    `claim_tui_pidfile` and reported `stale_pidfile` + removed by
    `submit_tui_command` instead of raising `OverflowError`/`ValueError`,
    and `pid_alive` / `identity_problem` stay total for out-of-range
    input. (Pre-fix these raised out of the startup claim, the picker,
    and autostart — the same class of crash E3 already closed for
    undecodable bytes.)
29. a recycled PID whose `/proc/<pid>/stat` `comm` is not valid UTF-8
    (E16): `proc_starttime` / `is_zombie` / `identity_problem` return
    values instead of raising, `claim_tui_pidfile` takes the stale file
    over (so `pm _tui` starts), and `submit_tui_command` reports
    `stale_pidfile` and removes it; the QA resume path
    (`qa_loop.resume_owned_elsewhere` / `_proc_start_time`) likewise
    reports "not our owner" instead of raising. All five tests were
    verified to fail against the pre-fix strict decode.
30. `current_session_name()` resolves through the pane-targeted
    `tmux.get_session_name()` (E17): it strips the `~N` group suffix,
    never issues a bare `display-message -p`, and returns `None` outside
    tmux or when the tmux lookup fails. Verified to fail against the
    pre-fix bare-query implementation (which returns `None`/the wrong
    session under the same monkeypatches).
31. a stale pidfile the claim cannot unlink (E13/A2) exhausts the
    attempt budget and raises `TuiPidfileUnavailable`, an `OSError` that
    is *not* a `TuiPidfileConflict`, naming the pidfile path — so the
    launcher and `_install_reload_signal` log it and run without
    external IPC instead of refusing to start. Verified to fail against
    the pre-fix `TuiPidfileConflict` raise.
32. an out-of-range `owner_pid` in a QA resume snapshot (E16) reads as
    orphaned instead of raising `OverflowError` out of
    `resume_owned_elsewhere`. Verified to fail against the pre-fix
    `os.kill` call.
33. an empty argv (E18): `proc_cmdline` returns `[]` (not `None`) for a
    process whose `/proc/<pid>/cmdline` is empty (a not-yet-reaped
    zombie), `identity_problem` reports "pid belongs to a different
    program" instead of skipping the check, `claim_tui_pidfile` takes a
    stale pidfile over instead of refusing to start, and
    `submit_tui_command` reports `stale_pidfile`, removes the file and
    never signals the unrelated process. All four verified to fail
    against the pre-fix `return None`.
34. the queued line reaches the file *under* the append `flock` (I3): a
    spy on `fcntl.flock` records the queue's bytes at `LOCK_UN`, and the
    test asserts they already contain the command. Verified to fail
    before the `f.flush()` (`b''` at `LOCK_UN`; the line only appeared
    when the `with` block closed the file afterwards). With the unbuffered
    append this now holds structurally.
35. a short write to the queue (I3) leaves no partial line: a fake `open`
    writes five bytes of the command and then raises `ENOSPC`, and the
    test asserts the queue still holds exactly its pre-append bytes.
    Verified to fail before the truncate-back (`b'pr qa fresh
    pr-9\nrevie'` left in the file, which a later drain would have run
    as the command `revie`).
36. the truncate-back target is the size *under* the lock (I3): the same
    failing `open` also appends another caller's line between our open
    and our `flock`, and the test asserts that line survives the
    rollback. Verified to fail when the target comes from `f.tell()`
    (captured at open): the concurrent caller's line was truncated away,
    so a command it was told was queued would never be applied.
37. the realistic short write — bytes accepted, *then* `ENOSPC` (I3): a
    fake `open` honours `buffering` the way the builtin does and wraps a
    raw layer that accepts five bytes and then fails forever, so a
    buffered append fails from `flush`/`close` (not from `write`) and
    keeps the unwritten remainder. The test asserts the queue still
    holds exactly its pre-append bytes. Verified to fail against the
    buffered append: `truncate` re-raised from its own flush and the file
    kept `b'pr qa fresh pr-9\nrevie'`. This is why the append is
    unbuffered.
38. a short raw write that then succeeds (I3) is completed by the append
    loop rather than reported as a failure, so the whole line lands.
39. the `execve` window (E19): a `proc_cmdline` that reads empty once and
    then a TUI argv must not be read as "a different program" — so
    `identity_problem` reports no problem, `claim_tui_pidfile` raises the
    conflict (instead of stealing the restarting TUI's pidfile) and
    `submit_tui_command` succeeds and leaves the pidfile in place. The
    first three were verified to fail against a direct `proc_cmdline`
    read. A *permanently* empty argv is still rejected after the bounded
    grace (that test passes both ways by design: it pins that the grace
    does not weaken E18).
40. an owner that was *reaped* between the liveness check and the argv
    read (E20): with `proc_cmdline` returning `None` ("cannot tell") and
    `pid_alive` flipping to `False` on the second call,
    `identity_problem` reports `process is not running` instead of "no
    problem", and `claim_tui_pidfile` takes the stale pidfile over
    instead of raising `TuiPidfileConflict` — pre-fix it refused to
    start (`pm _tui` could not run until the file was deleted by hand),
    which both tests were verified to reproduce. A third test pins that
    a *live* process with a "cannot tell" cmdline still degrades to the
    liveness check (the off-procfs path), so the new re-check cannot
    turn every non-Linux platform into "stale pidfile".

The dispatch helpers share one reader, `helpers._read_tui_owner()`, which
returns `(pidfile, raw, descriptor, problem)` and never modifies anything;
`_validate_tui_owner` adds the stale-file cleanup and `tui_owner_problem`
(polled by the picker spinner) is a thin wrapper over it, so the two paths
cannot drift apart.
