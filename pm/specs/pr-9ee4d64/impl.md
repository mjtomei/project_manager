# pr-9ee4d64 — Run transcripts must not be overwritten across sign-off returns

## Summary

An auto-start run directory (`pm/transcripts/<autostart-run>/`) keeps one
transcript per (step, PR): `impl-<pr>.jsonl`, `signoff-<pr>.jsonl`,
`review-<pr>-i<N>.jsonl`, `review-<pr>.jsonl`, `merge-<pr>.jsonl`. Those
paths are *canonical, reusable* names: every new attempt for the same
step/PR writes the same path. `build_claude_shell_cmd` unlinks the old
symlink before creating the new one, and `finalize_transcript` unlinks a
symlink and replaces it with a copy. Two consequences:

1. **Archive loss.** A sign-off return (SIGNOFF_IMPL / SIGNOFF_REVIEW /
   SIGNOFF_REQA) within one auto-start run re-runs impl, restarts the
   review loop at iteration 1, and re-runs sign-off, all writing the same
   canonical paths. The run archive keeps only the post-return sessions;
   the router transcript that made the return decision and the pre-return
   impl/review are gone from the run dir (only `~/.claude/projects/...`
   survives).
2. **Live-collector freeze.** A superseded review loop's completion
   callback finalizes every `review-<pr>-*.jsonl` in the dir without
   checking ownership. When a newer loop has reused the path, the obsolete
   callback replaces the newer loop's *live* symlink with an early copy;
   the collector then polls a frozen file and never sees the verdict the
   live session appends later (2026-10-28, PR #241 / #248 S11).

The fix makes every attempt's transcript an immutable archive entry, makes
finalization ownership-checked, and never deletes history.

## Requirements

### R1 — Immutable per-attempt / per-loop / per-session archives

Every launched Claude session that writes a pm transcript must leave a
durable, uniquely named artifact in the run dir that no later attempt can
overwrite or delete.

Grounded code paths:

- `pm_core/claude_launcher.py::build_claude_shell_cmd` (lines ~929–942)
  is the single place a transcript symlink is created. It currently does
  `transcript_path.unlink()` then `symlink_to(target)`.
- `pm_core/claude_launcher.py::finalize_transcript` (line ~1135) replaces
  a symlink with a copy.
- `pm_core/signoff.py::retire_signoff_run` (line ~975) unlinks the
  sign-off transcript and its `.head` stamp.
- Review-loop iteration paths are built inline as
  `f"{transcript_dir}/review-{pr_id}-i{iteration}.jsonl"` in
  `pm_core/review_loop.py` (lines 237, 276, 342).

Required behaviour:

- Before `build_claude_shell_cmd` replaces an existing transcript path,
  it **archives** the outgoing transcript under
  `<transcript-dir>/archive/<stem>.<session-id>.jsonl` (symlink → native
  file, or the finalized regular file), by creating the entry no-clobber
  and then removing the outgoing path. Archives are never overwritten.
- `finalize_transcript` writes an immutable archive copy keyed by the
  session id before it freezes the canonical path.
- Review-loop iteration transcripts are named per loop:
  `review-<pr>-<loop_id>-i<N>.jsonl`. A new loop (including a
  sign-off REVIEW return, which constructs a fresh `ReviewLoopState` with
  a new `loop_id` and iteration reset to 1) therefore never shares a path
  with an earlier loop. This is the structural ownership guarantee.
- `retire_signoff_run` archives the sign-off transcript instead of
  unlinking it; it still removes the `.head` launch stamp so a consumed
  verdict cannot be replayed.

### R2 — Ownership-checked finalization

A finalization must never freeze, replace, unlink, or redirect a
transcript that belongs to another attempt.

Grounded code paths:

- `pm_core/tui/review_loop_ui.py::_on_complete_from_thread` (lines
  ~302–315) finalizes every `review-<pr>-*.jsonl` in the run dir before
  the supersede check.
- `pm_core/tui/watcher_ui.py::_on_complete_from_thread` and
  `pm_core/cli/watcher.py` finalize every `.jsonl` symlink in their dir.
- `pm_core/tui/auto_start.py::_finalize_all_transcripts` (line ~372)
  finalizes every `.jsonl` symlink in the run dir on auto-start disable.
- `pm_core/cli/pr.py::_finalize_merge` (line ~1934) finalizes the merge
  transcript.

Required behaviour:

- `finalize_transcript(path, *, session_id=None)` reads the symlink
  target once. If `session_id` is supplied and the target's session id
  differs, it returns without touching the path. It re-reads the link
  immediately before replacement; if the link now points elsewhere, it
  leaves it alone (closes the replace-between-read-and-freeze race).
- Review-loop completion finalizes only the loop's own
  `review-<pr>-<loop_id>-i*` paths, and passes the session id recorded for
  each iteration when available.
- The bulk sweeps (`_finalize_all_transcripts`, watcher completion) skip
  transcripts whose session is still live: running review loops
  (`app._review_loops[pr].running`), running watcher loops
  (`app._watcher_manager.list_watchers()`), and live
  impl/review/signoff/merge tmux windows. A disable must not freeze a
  collector that is still polling.  This matters because the TUI
  auto-start watcher and the review loops share one run directory.
- `_finalize_all_transcripts` also finalizes symlinks already sitting in
  `archive/` so archived sessions survive Claude transcript pruning.

### R3 — Current collectors see later appended verdicts

- The live canonical path for the *current* attempt must remain a symlink
  to the native JSONL until that attempt finishes, so
  `find_verdict_turn` / `poll_for_verdict` / `wait_for_follow_up_verdict`
  (which re-read the path on every check) observe appended turns.
- A superseded attempt's callback must not turn the current path into a
  copy (R2).
- Review loops poll their own loop-scoped path (R1), which no other loop
  replaces.

### R4 — Keep both complete original sessions

Across multiple sign-off returns, iteration resets, TUI restart and late
completion, both the pre-return and post-return sessions must remain
available in the run dir:

- archive-on-replace preserves impl/signoff/review-single/merge attempts;
- loop-scoped review names preserve each loop's iterations;
- restart adoption (`review_loop._adopt_in_flight_review`,
  `_wait_for_follow_up_verdict`) resolves the loop-scoped path from the
  restored `state.loop_id`, with a fallback to the legacy
  `review-<pr>-i<N>.jsonl` for a loop restored from a pre-upgrade
  breadcrumb.

### R5 — Never invent a verdict or delete history

- No code path synthesizes a verdict from an archive.
- Retire/archive operations rename or copy; they never truncate or
  unlink a transcript whose content is the only copy. The `.head` stamp
  may still be removed (it is launch metadata, not history).
- Bulk finalization only copies; it never removes a target.

## Implicit requirements

1. **No half-written archives.** An archive entry is created whole
   (a symlink, a hard link, or an exclusively-created copy that is removed
   if it fails part way), so a concurrent reader never sees a truncated
   entry. Archive-on-replace deliberately does *not* use `rename`: it
   creates the entry no-clobber and then removes the outgoing path, so an
   existing immutable entry is never overwritten (see
   `_move_into_archive`). A failure at either step leaves the outgoing
   session recoverable (the entry, the canonical, or the native JSONL).
2. **Idempotency.** Archiving an already-archived session must not create
   duplicate or truncated entries. Archive names are keyed by session id;
   an existing archive is never overwritten.
3. **No reader changes for canonical paths.** impl/signoff/merge readers
   (`_check_impl_idle`, `signoff_transcript_verdict`,
   `signoff_launched_sha`, `_adopt_orphaned_run`, merge verdict polling)
   keep using the canonical path; only the review-loop iteration path
   changes and every one of its consumers is updated.
4. **Restart compatibility.** A TUI restart restores `loop_id`,
   `iteration`, and `_transcript_dir` from the breadcrumb
   (`auto_start.consume_breadcrumb`). Loop-scoped names must reproduce the
   same path after restart; a legacy in-flight iteration must still be
   adoptable.
5. **Run-dir scans must not pick up archives.** Archive files live in a
   subdirectory (`<run>/archive/`), so `tdir.iterdir()` scans
   (`_check_review_verdict`, `_adopt_orphaned_run`'s stamp glob,
   finalize sweeps) do not treat archives as current.
6. **Symlink chains resolve live.** The canonical path may point at an
   archived attempt or at the native JSONL; readers follow the chain, so
   appends remain visible until the attempt is frozen.
7. **Container launches.** `build_claude_shell_cmd` computes the symlink
   target from `cwd` (a container launch passes `/workspace`, so the
   target is the host `~/.claude/projects/-workspace/<sid>.jsonl` that the
   container's Claude writes). Archiving operates on the host transcript
   path the caller passed, never on a container path.

## Design

### `pm_core/claude_launcher.py`

- Add `TRANSCRIPT_ARCHIVE_DIR = "archive"`.
- Add `_session_id_of_path(target: Path) -> str | None` (path-only
  variant of `session_id_from_transcript`; `session_id_from_transcript`
  now delegates to it).
- Add `archive_transcript(path) -> Path | None`:
  - missing → `None`;
  - compute archive name: `<stem>.<sid>.jsonl` for a symlink whose target
    is a UUID-named JSONL, else `<stem>.<mtime_ns>-<size>.jsonl` for a
    frozen file, else `<stem>.<random-12-hex>.jsonl` for a symlink whose
    target is not UUID-named;
  - `archive_dir.mkdir(parents=True, exist_ok=True)`;
  - if the archive already exists, do not overwrite (if it is a symlink
    to the same target, drop only the redundant canonical link);
  - otherwise `_move_into_archive` creates the entry no-clobber — a
    symlink to the same absolute target for a symlink, a hard link for a
    regular file, an exclusively-created copy when the filesystem refuses
    links — and only then removes `path`. Never `rename`: that would
    clobber an immutable entry.
- `build_claude_shell_cmd`: before creating the new symlink, call
  `archive_transcript(transcript_path)` when the path exists / is a
  symlink; log the archive.
- `finalize_transcript(path, *, session_id=None) -> bool`:
  - not a symlink → `False`;
  - `raw = os.readlink(path)`; `target = Path(raw)`;
  - `sid = _session_id_of_path(target)`;
  - `if session_id and sid and sid != session_id: return False`;
  - `if not target.exists(): return False`;
  - write/refresh the immutable archive entry (copy) via a shared helper
    (`_freeze_archive_copy`: copy beside the entry, then `os.replace`, so
    a crash can never leave the archive without a session copy);
  - re-read `os.readlink(path)`; if it != `raw`, return `False`;
  - `shutil.copy2` to a unique temp beside the path, then `os.replace`
    (atomic; a failed copy leaves the live link untouched);
  - return `True`.
- Add `finalize_transcript_dir(directory, *, skip=None) -> int`: finalize
  every top-level `*.jsonl` symlink and every `archive/*.jsonl` symlink.
  `skip` is an optional predicate on a file name; a name it accepts is
  left live (its session may still be writing).  Archive entries are
  never skipped.

### `pm_core/review_loop.py`

- Add `iteration_transcript(transcript_dir, pr_id, loop_id, iteration)`.
- Add `resolve_iteration_transcript(...)`: loop-scoped path if it exists,
  else the legacy `review-<pr>-i<N>.jsonl` when that is a *link* (the
  pre-upgrade loop's in-flight iteration), else the loop-scoped path (for
  a new launch).  A frozen regular-file legacy transcript is a completed
  earlier loop's iteration and is never reused.
- `run_review_loop_sync`: record
  `state.iteration_sessions[iteration] = session_id_from_transcript(path)`
  after each iteration (launched or adopted) when a session id resolves,
  using `resolve_iteration_transcript` to find the path that iteration
  actually used.
- `_run_iteration_with_retry` (the launch-retry path merged from master):
  resolves its iteration transcript with `resolve_iteration_transcript`,
  so every retry attempt of one iteration writes the same loop-scoped path
  and a legacy in-flight iteration is still adopted under the old name.
- `_discover_iteration` / `_adopt_in_flight_review` /
  `_wait_for_follow_up_verdict`: use `resolve_iteration_transcript`.
- `_is_historical_session`: scans both the legacy
  `review-<pr>-i<N>.jsonl` names and this loop's
  `review-<pr>-<loop_id>-i<N>.jsonl` names, so a pane running an earlier
  iteration of this loop is still recognised as historical.
- Add `iteration_sessions: dict[int, str]` to `ReviewLoopState`.

### `pm_core/tui/review_loop_ui.py`

- `_on_complete_from_thread`: finalize only
  `review-<pr>-<loop_id>-i*.jsonl`, passing the recorded session id per
  iteration. Keep it before the supersede check (own work).  Also finalize
  the legacy `review-<pr>-i<N>.jsonl` of each iteration with a recorded
  session id (ownership-checked), so a loop that adopted a pre-upgrade
  in-flight iteration does not leave that transcript a permanent symlink.

### `pm_core/signoff.py`

- `retire_signoff_run`: `archive_transcript(transcript)` instead of
  `unlink`; keep removing the `.head` stamp.

### `pm_core/tui/auto_start.py`

- `_live_transcript_owners(app)` returns `(exact_names, prefixes)` of
  transcripts whose session may still be writing: every
  `review-<pr>-<loop_id>-i*` of a running review loop, every
  `<watcher-type>-i*` of a running watcher loop, and the canonical path
  of each live impl/review/sign-off/merge window (window names come from
  `autostart_state._window_names`).  A running loop also marks the legacy
  prefix `review-<pr>-i`: a loop restored from a pre-upgrade breadcrumb
  polls the legacy shared iteration name, and freezing it would hide the
  verdict it appends later.  Loop-scoped names can never match that
  prefix (the loop id is hex, so it never starts with `i`).
- `_live_transcript_skip(app)` wraps that as the `skip` predicate.
- `_finalize_all_transcripts`: call
  `finalize_transcript_dir(tdir, skip=_live_transcript_skip(app))`.

### `pm_core/tui/watcher_ui.py`, `pm_core/cli/watcher.py`

- Use `finalize_transcript_dir` (includes `archive/`).
- The TUI auto-start watcher shares its run directory with the
  auto-start review loops, so its completion sweep must pass the same
  `skip` predicate; otherwise a completing watcher freezes a loop that is
  still polling (the 2026-10-28 failure mode).  The CLI watcher uses a
  private `watcher-<token>` directory and needs no skip.

## Ambiguities (resolved)

1. **Unique names vs. archive-on-replace.** Renaming every canonical path
   would require a pointer-resolution layer for every reader. Chosen:
   archive-on-replace for shared canonical paths, loop-scoped names only
   where a path is provably reused across live loops (review iterations).
   This keeps every reader on its existing canonical path and still gives
   every session an immutable archive entry.
2. **Where archives live.** `<run>/archive/` (a subdirectory), so all
   existing top-level scans ignore them and `_adopt_orphaned_run`'s
   `*/signoff-*.head` glob is unaffected.
3. **Delete vs. archive on retire.** Archive; never delete. The `.head`
   stamp is still removed (launch metadata, not history) so a consumed
   verdict cannot be replayed.
4. **Ownership identity.** A loop-scoped filename is the identity for
   review iterations. For shared canonical paths the identity is the
   symlink target captured before the operation plus the re-read guard;
   callers that know their session id pass it.
5. **Legacy adoption after upgrade.** `resolve_iteration_transcript`
   falls back to the legacy name only while it is a symlink (the
   pre-upgrade in-flight iteration), so that iteration can still be
   adopted; a frozen legacy file is a finished earlier loop's iteration
   and a new launch always uses the loop-scoped name.

No **[UNRESOLVED]** ambiguities.

## Edge cases

- **Dangling outgoing symlink** (previous launch failed before Claude
  wrote): archived as a dangling link; harmless, and `finalize_transcript`
  no-ops because the target is missing.
- **Regular (frozen) outgoing path**: hard-linked (or copied) into the
  archive under an mtime/size key, then removed; never confused with a
  session-id archive.
- **Two launches racing on one path** (sign-off has a per-PR launch lock;
  impl `--fresh` is guarded): the entry is created no-clobber, so the
  second archiver finds the entry already there and drops only the
  redundant canonical link instead of overwriting it. One attempt's link
  becomes canonical; every session's content stays reachable (archive
  entry or native JSONL).
- **Bulk finalize while a loop is running** (auto-start disable): the
  sweep skips live loops/windows, so the collector keeps seeing appends;
  its own completion callback finalizes later.
- **Archive symlink already exists when freezing**: frozen in place if it
  points at the same target; otherwise left untouched (immutable).
- **Restart mid-iteration**: the resumed loop uses the restored
  `loop_id`, resolves the same loop-scoped path, and adopts the live
  pane/transcript; a legacy path falls back.
- **`_finalize_all_transcripts` recursion**: only `archive/` is
  descended; no unbounded recursion.
- **Auto-sequence CLI dir**: `transcripts/auto-sequence/<pr>/` uses the
  same helpers; its iteration numbering already continues after returns,
  and archive-on-replace protects any same-name relaunch (sign-off,
  impl).
- **QA transcripts**: produced via native `transcript_path_for` paths,
  not `build_claude_shell_cmd(transcript=...)`; unaffected.

## Verification

- New unit tests (31) in `tests/test_transcript_archive.py` covering:
  archive-on-replace, ownership-checked finalize, loop-scoped naming,
  retire preserving history, live-appends visibility, restart fallback
  (legacy fallback for a live link, loop-scoped preference when both
  names exist, a dangling loop-scoped link winning over a stale legacy
  file, and a frozen legacy file never reused — including end to end
  after a loop completion freezes an adopted legacy iteration),
  both pre-return sessions surviving two sign-off returns (R4),
  legacy-iteration live/finalize handling, the no-hardlink archive
  fallback, a dangling link and a failed copy left alone by finalize,
  the live-owner skips (running review loop, running watcher, live step
  windows) for both bulk sweeps, and a stub app's non-string
  `_session_name` never reaching tmux.  One more
  (`test_launches_loop_scoped_transcript_and_records_session`) lives in
  `tests/test_review_loop.py` because it drives `run_review_loop_sync`;
  `tests/test_breadcrumb_review_loop.py` gains an
  `iteration_sessions` round-trip test, asserts int-keyed restoration in
  the existing consume test, and pins that a malformed (non-object)
  `iteration_sessions` value does not abort the restore.
  The archive tests that exercise a pre-fix behaviour fail on the pre-fix
  tree (`git show 3699f71a:pm_core/claude_launcher.py`); the tests that
  call helpers introduced here can only fail by import on that tree, which
  is why `impl/{pre,post}-fix/transcript-archive/repro.py` (real helpers,
  pre-fix fallbacks) is the behavioural before/after evidence.
- Regression run of `tests/test_review_loop.py`,
  `tests/test_signoff.py`, `tests/test_signoff_integration.py`,
  `tests/test_workspace_trust.py`, `tests/test_tui_signoff_handoff.py`,
  `tests/test_claude_launcher.py`.
- Master integration (2026-10-28, merge of `origin/master` 4a74d880 into
  this branch): master's launch-retry/discovery refactor
  (`_run_iteration_with_retry`, `_discover_iteration`,
  `ReviewClosedError`, the retry-episode breadcrumb fields) is combined
  with this PR's loop-scoped naming.  All iteration-transcript path
  builders (`_run_iteration_with_retry`, `_discover_iteration`,
  `_wait_for_follow_up_verdict`, the adoption branch of
  `run_review_loop_sync`) resolve through `resolve_iteration_transcript`,
  and `_is_historical_session` also scans loop-scoped names.  The
  breadcrumb carries both the retry fields and `iteration_sessions`.
  Verified: 4515 passed / 1 skipped in the full suite; the only two
  failures (`test_push_proxy`) pass in isolation and on master and are
  load-related (push-proxy daemon startup), not caused by this PR.
- Manual repro (pre/post) recorded under
  `$CAP/impl/{pre-fix,post-fix}/` with `pm/qa/artifacts/cli-recording.md`.

## Review-loop hardening (2026-10-28, iterations 94dc / 8602)

Applied on top of the design above; keep them when editing the code.

- `build_claude_shell_cmd` clears the canonical path after the archive
  attempt (not only on archive failure).  `archive_transcript` can return
  an archive path while leaving the canonical link in place (the session's
  entry already existed, or the post-rename unlink failed); a following
  `symlink_to` would then raise `FileExistsError` and kill the launch.
- `_find_identical_archive` scopes its mtime+size match to the same stem;
  a directory-wide match could pair a different step's entry with this
  transcript, after which the canonical would be dropped unarchived.
- `_freeze_archive_copy` writes its temp file under a per-call unique name
  (pid + random suffix): a bulk sweep and a loop completion can finalize
  the same transcript from two threads of one process.
- `_move_into_archive` removes a partial copy when the no-hardlink
  fallback fails, so a truncated immutable entry cannot block later
  attempts.
- `retire_signoff_run` drops a leftover canonical *symlink* after
  archiving so a consumed verdict stays unreplayable; a regular file (the
  only copy of its content) is never removed.  A leftover regular file is
  caught by the missing-`.head` guard in `_step_signoff_locked`, which
  retires and relaunches rather than replaying it.
- `_live_transcript_owners` snapshots `app._review_loops` / `app._data`
  before iterating: the watcher-completion sweep calls it from a
  background thread while the TUI thread mutates those containers.
- Legacy iteration coverage (8602 i3): a running loop also marks the
  legacy `review-<pr>-i` prefix live, so a bulk sweep cannot freeze the
  iteration that a loop restored from a pre-upgrade breadcrumb is still
  polling; and loop completion finalizes the legacy
  `review-<pr>-i<N>.jsonl` of every iteration with a recorded session id
  (ownership-checked), so an adopted legacy iteration is frozen and
  archived instead of lingering as a link.
- `iteration_sessions` is persisted in the TUI breadcrumb (8602 i4) and
  restored by `consume_breadcrumb`, so the 8602-i3 guarantees survive a
  restart: a resumed loop still finalizes each iteration with its
  ownership check, and an iteration adopted under the legacy name before
  the restart is still frozen and archived on completion.
- The no-hardlink archive fallback creates the entry exclusively
  (`open(dest, "xb")`, 8602 i4) and only ever removes a partial copy of
  its own making.  `shutil.copy2` would have overwritten a concurrent
  entry, violating the "archives are never overwritten" invariant.
- `finalize_transcript` freezes via a unique temp copy followed by
  `os.replace` (8602 i4) instead of `unlink` + `copy2`: readers see
  either the live symlink or the complete copy, a failed copy leaves the
  link live, and no truncated canonical can be left behind.  That atomic
  copy is the shared `_copy_atomic` helper (review d468 i2), used by both
  `finalize_transcript` and `_freeze_archive_copy` instead of two
  hand-rolled copies.
- `_transcript_stem` / `transcript_archive_dir` are shared by
  `_archive_name`, `_find_identical_archive`, `archive_transcript`,
  `_freeze_archive_copy` and `finalize_transcript_dir` (8602 i4) instead
  of each re-deriving the stem / archive directory.
- `consume_breadcrumb` ignores a non-object `iteration_sessions` value
  (8602 i5): a hand-edited or truncated breadcrumb must not abort the
  restore of the remaining loops and auto-start state.  The
  loop-scoped-over-legacy precedence in `resolve_iteration_transcript`
  (including a dangling loop-scoped link, which is the current attempt
  before Claude writes its native JSONL) is now pinned by tests.
- `_live_transcript_owners` resolves the tmux session through
  `auto_start._app_session` (review d468 i1) instead of the raw
  `_session_name`: a stub app's attribute may be a non-string, which must
  never be handed to `tmux list-windows` from inside a bulk finalize.
- `resolve_iteration_transcript` falls back to the legacy iteration name
  only while that path is a symlink (review d468 i2).  A *frozen* legacy
  transcript is a completed iteration of an earlier loop — loop
  completion and the bulk sweeps both freeze it — so reusing it would
  hand a fresh loop (a REVIEW return) the shared name, reintroducing the
  cross-loop collision this PR removes and making the legacy name sticky
  for every later loop at that iteration.

## Known limitations (accepted)

- **Step windows are treated as live for the whole sweep.**  A disable
  while a step window is open leaves that step's canonical transcript a
  symlink (never frozen), because an idle-looking pane is not provably
  done.  It is archived on the next launch that reuses the path
  (`build_claude_shell_cmd`), so pre-return sessions are still preserved;
  only a final session whose path is never reused stays a link until
  Claude prunes it.  Distinguishing idle from running would need the pane
  idle tracker, which is TUI-only and not available for sign-off/merge.
- **`_finalize_merge` passes no session id.**  It has no launch-time
  session id to compare against; `finalize_transcript` still writes the
  sid-keyed archive copy first, so no content is lost if a newer merge
  run owns the path.
- **A running loop keeps legacy iteration links live for its whole run.**
  The legacy `review-<pr>-i*` prefix is marked live whenever a loop for
  that PR runs, because the loop may be polling an adopted pre-upgrade
  iteration.  A stale legacy link from an earlier loop is therefore
  frozen by a later sweep (or the loop's completion), not during the run.
