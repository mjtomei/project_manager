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
- A **bulk sweep never freezes a canonical transcript**.  Canonical
  names (`impl-<pr>.jsonl`, `signoff-<pr>.jsonl`, `merge-<pr>.jsonl`,
  `review-<pr>.jsonl`) point at the attempt that is live *now*; the TUI's
  idle poll, a running loop, a driver waiting on a verdict or a
  repo-update window may still be reading one after auto-start is off, and
  a frozen copy would never show what the session appends next.  Deciding
  "finished" from a pane or a window is exactly the guess that hid a later
  MERGED / PASS before (pr-592e4bd S31), so it is not attempted: a
  canonical is replaced, and the outgoing session archived, only when a
  new attempt launches on that path (review e757 i4, user decision).
  Owner-completion finalization is unaffected — a review loop freezing its
  own loop-scoped iterations and `_finalize_merge` freezing the merge
  transcript are not guesses; the owner is done and only touches its own
  paths.
- The bulk sweeps (`_finalize_all_transcripts`, watcher completion)
  therefore freeze **only** symlinks already sitting in `archive/`, so
  superseded sessions survive Claude transcript pruning.  Archive entries
  are immutable snapshots that nothing polls, so freezing one can never
  hide a later turn.
- `finalize_transcript_dir(directory, *, include_top_level=True)` exposes
  the split.  The CLI watcher passes the default for its private
  `watcher-<token>` dir: its process is exiting and nothing else reads
  that directory, so freezing its own iteration links is safe and is the
  only way those (never-reused) names survive pruning.  Every TUI sweep
  passes `include_top_level=False`.

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
    is a UUID-named JSONL, else `<stem>.<sha256(content)[:12]>.jsonl` for
    a frozen file, else `<stem>.<sha256(target)[:12]>.jsonl` for a symlink
    whose target is not UUID-named (deterministic, so re-archiving the
    same attempt reuses the entry; the key is the sha256 of the *absolute*
    target, so a relative link and its absolute form agree, and a content
    key cannot collide for two different sessions the way mtime + size
    can — review e757 i6);
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
  - `raw = os.readlink(path)`;
    `target = _absolute_link_target(path, raw)` — a relative link is
    resolved against the link's own directory, never the process CWD;
  - `sid = _session_id_of_path(target)`;
  - `if session_id and sid and sid != session_id: return False` (a target
    with no session id cannot be compared, so it is frozen as usual);
  - `if not target.exists(): return False`;
  - write/refresh the immutable archive entry (copy) via a shared helper
    (`_freeze_archive_copy`: copy beside the entry, then `os.replace`, so
    a crash can never leave the archive without a session copy);
  - `shutil.copy2` to a unique temp beside the path, re-check
    `os.readlink(path)` (a guard run *after* the copy), then `os.replace`
    (atomic; a failed copy leaves the live link untouched; a redirect
    during the copy discards the temp and leaves the new link live);
  - return `True`.
- Add `finalize_transcript_dir(directory, *, include_top_level=True)
  -> int`: finalize every `archive/*.jsonl` symlink, and the top-level
  `*.jsonl` symlinks only when `include_top_level` is true.  The TUI
  sweeps pass `False` — a canonical link may still be polled and must be
  left live — while the CLI watcher passes the default for its private,
  exiting-process directory (review e757 i4).

### `pm_core/review_loop.py`

- Add `iteration_transcript(transcript_dir, pr_id, loop_id, iteration)`.
- Add `resolve_iteration_transcript(..., *, allow_legacy=True)`:
  loop-scoped path if it exists, else the legacy
  `review-<pr>-i<N>.jsonl` when that is a *link* (the pre-upgrade loop's
  in-flight iteration), else the loop-scoped path (for a new launch).  A
  frozen regular-file legacy transcript is a completed earlier loop's
  iteration and is never reused.  `allow_legacy=False` is passed for a
  *new* iteration's launch (`run_review_loop_sync` sets it from the
  `adopt` decision): only a loop resuming an iteration that was already
  in flight can own a legacy link, so a fresh loop (a REVIEW return
  restarts at iteration 1) never launches over another loop's live link.
- `run_review_loop_sync`: record
  `state.iteration_sessions[iteration]` after each iteration (launched or
  adopted) when a session id resolves, using `resolve_iteration_transcript`
  to find the path that iteration actually used and the module's existing
  `_transcript_session_id` helper (the exception-safe wrapper around
  `session_id_from_transcript`) to read its id — no second import of the
  launcher in this function.
- `_run_iteration_with_retry` (the launch-retry path merged from master):
  resolves its iteration transcript with `resolve_iteration_transcript`,
  so every retry attempt of one iteration writes the same loop-scoped path
  and a legacy in-flight iteration is still adopted under the old name.
  It forwards `allow_legacy` to `_discover_iteration` as well: discovery
  and launch must name the same path, or a launch under the loop-scoped
  name would be rediscovered through another loop's live legacy link and
  its verdict adopted as this iteration's.
- `_discover_iteration` / `_adopt_in_flight_review` /
  `_wait_for_follow_up_verdict`: use `resolve_iteration_transcript`
  (`_adopt_in_flight_review` — the restart handoff — keeps the legacy
  fallback on).
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

- `_finalize_all_transcripts` (called only from `_disable`) calls
  `finalize_transcript_dir(tdir, include_top_level=False)`: it freezes
  the run dir's `archive/` entries and leaves every canonical link live.
  The former liveness machinery (`_live_transcript_owners`,
  `_live_read_transcripts`, `_live_transcript_skip`,
  `_LAZY_TRACKED_RE`) was deleted with it (review e757 i4): deciding
  "finished" from a pane or a window is the guess that broke S31, and
  leaving the canonical live is always safe for a reader.

### `pm_core/tui/watcher_ui.py`, `pm_core/cli/watcher.py`

- Both use `finalize_transcript_dir`.  The TUI auto-start watcher shares
  its run directory with the auto-start review loops and the step
  windows, so it passes `include_top_level=False`: a completing watcher
  freezes only the archive, never a canonical a loop, the idle poll or
  the sign-off driver may still be reading.  The CLI watcher uses a
  private `watcher-<token>` directory whose process is exiting and which
  nothing else reads, so it takes the default and freezes its own
  iteration links too (their names are never reused, so that freeze is
  the only way they survive pruning).

## Ambiguities (resolved)

1. **Unique names vs. archive-on-replace.** Renaming every canonical path
   would require a pointer-resolution layer for every reader. Chosen:
   archive-on-replace for shared canonical paths, loop-scoped names only
   where a path is provably reused across live loops (review iterations).
   This keeps every reader on its existing canonical path and still gives
   every *superseded* session an immutable archive entry.  The attempt
   that is live when a run ends stays a link until a new attempt reuses
   its path (review e757 i4); see Known limitations.
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
   pre-upgrade in-flight iteration) *and* the caller is resuming such an
   iteration (`allow_legacy`), so that iteration can still be adopted; a
   frozen legacy file is a finished earlier loop's iteration, and a new
   launch always uses the loop-scoped name.

No **[UNRESOLVED]** ambiguities.

## Edge cases

- **Dangling outgoing symlink** (previous launch failed before Claude
  wrote): archived as a dangling link; harmless, and `finalize_transcript`
  no-ops because the target is missing.
- **Regular (frozen) outgoing path**: hard-linked (or copied) into the
  archive under a content-hash key, then removed; never confused with a
  session-id archive.
- **Two launches racing on one path** (sign-off has a per-PR launch lock;
  impl `--fresh` is guarded): the entry is created no-clobber, so the
  second archiver finds the entry already there and drops only the
  redundant canonical link instead of overwriting it. One attempt's link
  becomes canonical; every session's content stays reachable (archive
  entry or native JSONL).
- **Bulk finalize while a loop is running** (auto-start disable): the
  sweep does not touch canonical links at all, so the collector keeps
  seeing appends; the loop's own completion callback finalizes its
  loop-scoped iterations later.
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
- **QA transcripts**: the QA loop's own verdict transcripts
  (finalize / verify) are native `transcript_path_for` paths passed as
  `session_id=`, so they never take the `transcript=` archive branch.  A
  scenario worker *does* get a `transcript=` symlink, but at
  `<qa-workdir>/transcript-s<N>.jsonl` — outside the run dir — so
  archive-on-replace writes to `<qa-workdir>/archive/` there and never
  touches the run archive under test.

## Verification

- New unit tests (36, after the e757-i4 rewrite and the e757-i6
  content-key fixes; 37 before e757 i4) in
  `tests/test_transcript_archive.py` covering:
  archive-on-replace, ownership-checked finalize, loop-scoped naming,
  retire preserving history, live-appends visibility, restart fallback
  (legacy fallback for a live link, loop-scoped preference when both
  names exist, a dangling loop-scoped link winning over a stale legacy
  file, and a frozen legacy file never reused — including end to end
  after a loop completion freezes an adopted legacy iteration),
  both pre-return sessions surviving two sign-off returns (R4),
  legacy-iteration live/finalize handling, the no-hardlink archive
  fallback, a relative link to a non-session-named target (the
  deterministic `<stem>.<sha256(target)[:12]>.jsonl` key, target made
  absolute, no duplicate entry on re-archive), a dangling link and a
  failed copy left alone by finalize, a redirect before and *during* the
  freeze copy, a fresh loop never launching over a live legacy link,
  and a legacy iteration link left live when no session id was recorded
  (review d468 i4), plus (review e757 i6) a frozen canonical whose size
  and mtime collide with a different session's archive entry never being
  treated as already archived, and two frozen sessions that collide on
  size and mtime both getting distinct entries.  Review e757 i4 replaces
  the old live-owner/skip tests with the new rule: a bulk sweep (disable
  and watcher completion) leaves every canonical link live — impl,
  sign-off, merge, review — and appends to the native JSONL stay visible
  through it, while `archive/` entries are frozen; the CLI watcher's
  private dir is frozen whole.
  `tests/test_autostart_transcript_finalize.py` (master's S31 file) is
  rewritten to the same rule: a live, a gone and a dead pane's canonical
  all stay live, and only the archive entry is frozen.  Losing the
  no-clobber archive create to a concurrent archiver is reported as
  success (review e757 i2).  One more
  (`test_launches_loop_scoped_transcript_and_records_session`) lives in
  `tests/test_review_loop.py` because it drives `run_review_loop_sync`;
  `tests/test_breadcrumb_review_loop.py` gains an
  `iteration_sessions` round-trip test, asserts int-keyed restoration in
  the existing consume test (an unparsable key and a non-string value are
  dropped), pins that a malformed (non-object) `iteration_sessions`
  value does not abort the restore, and (review d468 i5) that a missing,
  blank or null `loop_id` is regenerated at the widened width while a
  valid one is preserved (the regeneration tests fail on the pre-fix
  restore path).  Since the 2026-11-01 integration, a *wrong-typed*
  `loop_id` skips the whole record instead (fail-closed restore policy
  from pr-049649a, pinned in `tests/test_autostart_fail_closed.py`).
  `tests/test_review_launch_retry.py`: the fake that writes a transcript
  now links the path the launcher was given (not a hardcoded legacy
  name), and `test_retry_never_adopts_a_previous_runs_transcript` is
  driven from a *resumed* loop — the one case that still polls the legacy
  name — so the stale-session guard it pins stays exercised (review
  d468 i3).
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

## Review-loop hardening (2026-10-28/29, iterations 94dc / 8602 / d468)

Applied on top of the design above; keep them when editing the code.

- `build_claude_shell_cmd` clears the canonical path after the archive
  attempt (not only on archive failure).  `archive_transcript` can return
  an archive path while leaving the canonical link in place (the session's
  entry already existed, or the post-rename unlink failed); a following
  `symlink_to` would then raise `FileExistsError` and kill the launch.
- `_find_identical_archive` scopes its mtime+size match to the same stem;
  a directory-wide match could pair a different step's entry with this
  transcript, after which the canonical would be dropped unarchived.  The
  size+mtime match is now a pre-filter confirmed by content (review
  e757 i6), so two different sessions that happen to share both cannot
  be paired either.
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
- Legacy iteration coverage (8602 i3): loop completion finalizes the
  legacy `review-<pr>-i<N>.jsonl` of every iteration with a recorded
  session id (ownership-checked), so an adopted legacy iteration is
  frozen and archived instead of lingering as a link.  (The old
  live-owner prefix for that name is gone: a bulk sweep no longer freezes
  canonicals at all — review e757 i4.)
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
- `auto_start._app_session` filters a stub app's non-string
  `_session_name` before it can reach tmux (review d468 i1).  The bulk
  sweeps no longer query tmux at all (review e757 i4), but the helper is
  still the only safe way to read that attribute.
- `resolve_iteration_transcript` falls back to the legacy iteration name
  only while that path is a symlink (review d468 i2).  A *frozen* legacy
  transcript is a completed iteration of an earlier loop — the loop's own
  completion freezes it (a bulk sweep no longer touches a canonical link,
  review e757 i4) — so reusing it would hand a fresh loop (a REVIEW
  return) the shared name, reintroducing the cross-loop collision this PR
  removes and making the legacy name sticky for every later loop at that
  iteration.
- `qa.md` R7 now states that archive entry counts are a minimum (review
  d468 i3).  At that time the run-end disable sweep froze every canonical
  link, so a run with two returns ended with three `impl-<pr>` / three
  `signoff-<pr>` entries and no canonical link, and the "exactly two
  entries + `readlink` names the live attempt" reading only held at the
  post-return checkpoint.  That ambiguity produced a QA INPUT_REQUIRED that
  was a scenario-text conflict, not a code defect.  **Superseded by review
  e757 i4**: a sweep no longer freezes a canonical, so the same run now
  ends with *two* entries per step (every superseded attempt) plus the
  canonical link naming the third (live) attempt.  qa.md R7 was corrected
  to that count in review e757 i5.
- `resolve_iteration_transcript(..., allow_legacy=...)` (review d468 i3):
  the legacy fallback is now restricted to a loop *resuming* an iteration
  that was already in flight (`run_review_loop_sync` derives the flag from
  its `adopt` decision, and `_run_iteration_with_retry` forwards it to
  `_discover_iteration` so discovery and launch name the same path).
  Previously a fresh loop's launch could resolve to another loop's live
  legacy `review-<pr>-i<N>.jsonl` — the cross-loop collision R1 exists to
  prevent.  A resumed loop still adopts its legacy iteration, and the
  stale-session guard (`state.stale_session_id`) still rejects a verdict
  that a failed launch left behind.
- `finalize_transcript` re-checks the link **after** the freeze copy
  (review d468 i3): `_copy_atomic(..., guard=...)` runs the readlink check
  between the copy and `os.replace`, so a redirect that lands during a
  long copy is no longer missed.  The remaining window is the single
  `os.replace` call (see limitations).
- `_archive_name`'s non-session-named fallback key is now deterministic —
  `sha256(<absolute link target>)[:12]` (review d468 i3) instead of a
  random suffix, so re-archiving the same attempt reuses its entry
  (implicit requirement 2: no duplicates) and `_freeze_archive_copy` and
  `archive_transcript` agree on the name.
- `save_breadcrumb` copies `iteration_sessions` before serialising it and
  `review_loop_ui._on_complete_from_thread` snapshots it and guards its
  `iterdir()` scan (review d468 i3): the loop thread records a new
  iteration's session concurrently, and a dict resize or a vanished run
  dir must not abort the breadcrumb write or the completion mirror.
- `build_claude_shell_cmd`'s failed-archive comment now states the real
  trade-off (review d468 i3): R9 prefers replacing the canonical over
  stalling the launch, so a frozen regular file that could not be archived
  is the one copy a launch may drop; a symlink only loses its link.
- `ReviewLoopState.loop_id` is 8 hex chars (`secrets.token_hex(4)`, review
  d468 i4) instead of 4.  The loop id is the *ownership identity* in every
  loop-scoped iteration filename, and the loops it must distinguish are
  deliberately concurrent (a REVIEW return starts a new loop while the
  superseded one may still be winding down).  With 4 hex chars (65536
  values) two loops for one PR could share an iteration path — the exact
  cross-loop freeze this PR removes — so the guarantee is only structural
  up to a collision.  8 hex chars makes that negligible; the value stays
  opaque and hex-only, so it can never look like the `i<N>` iteration
  marker the legacy `review-<pr>-i<N>.jsonl` pattern and the
  loop-scoped prefix a completion scan strips are built around.  (No
  pattern *requires* the property — the separators already prevent a
  match — it just keeps the naming scheme unambiguous.)  Old breadcrumbs
  keep their 4-char ids: the value is opaque everywhere.
- Loop completion finalizes a *legacy* `review-<pr>-i<N>.jsonl` only when a
  session id is recorded for that iteration (review d468 i4).  The legacy
  name is shared with other loops, so without an id the ownership check
  cannot run and freezing it could clobber the live attempt; the
  loop-scoped paths need no id because they are structurally this loop's
  own.  `consume_breadcrumb` also drops a non-string/empty
  `iteration_sessions` value (a hand-edited breadcrumb must not silently
  disable the check).
- `consume_breadcrumb` regenerates a restored loop's `loop_id` when the
  breadcrumb's value is missing, blank or null (review d468 i5; since the
  2026-11-01 merge this lives in `_loop_record_fields`).  The id is the
  ownership identity in every loop-scoped iteration filename, so the
  restore path must not keep the old 4-hex default
  (`secrets.token_hex(2)`) that the i4 widening retired.  A *valid* id is
  preserved verbatim (a resumed loop must reproduce its loop-scoped
  path); a regenerated one still adopts a legacy in-flight iteration
  through `resolve_iteration_transcript`'s legacy fallback.  A
  *wrong-typed* id (an int, say) is malformed saved state: the record is
  skipped, per the fail-closed restore policy merged from pr-049649a.
- Cleanup (review e757 i1), no behaviour change: `run_review_loop_sync`
  reads an iteration's session id through the module's existing
  `_transcript_session_id` helper instead of importing
  `session_id_from_transcript` into the function.  `qa.md`
  R7 no longer asks for a `merge-<pr>.jsonl` on a clean local merge (none
  is written; assert the merge by PR status).
- `archive_transcript` reports a lost no-clobber create as success
  (review e757 i2).  If another archiver creates the entry between the
  existence check and `_move_into_archive`'s create, the session *is*
  preserved; returning `None` made `build_claude_shell_cmd` log
  "could not archive … replacing it" for a session that was archived.
  The entry is returned instead, so the launch's log matches what
  happened
  (`test_a_concurrent_archive_is_not_reported_as_a_failure`).
- The `include_signoff` split between the two bulk sweeps (merged from
  master) was pinned by a test in review e757 i2 and **removed in e757
  i4**: neither sweep freezes a canonical link any more, so both keep a
  live sign-off link and freeze only the archive
  (`test_both_sweeps_leave_a_signoff_link_live`).

## Master integration (2026-10-31, merge of `origin/master` eaf3372e)

The 2026-10-31 user-authorized restart merged current `origin/master`
(`eaf3372e`, #249) into this branch.  Conflicts were resolved in
`pm/project.yaml`, `pm_core/claude_launcher.py` and
`pm_core/tui/auto_start.py`; the combined behaviour is:

- `claude_launcher.finalize_transcript` keeps this PR's
  ownership-checked, archive-writing version (master's simple
  unlink+copy version is superseded), and master's new
  `pane_runs_transcript` helper is kept alongside it.
- Master's S31 fix (a disable must not freeze a transcript the idle
  tracker or a live pane still reads) is **superseded in review e757 i4**
  by a stronger rule: the bulk sweeps never freeze a canonical link, so
  no reader can lose one.  The liveness scan it added
  (`_live_read_transcripts` / `_live_transcript_skip` /
  `_live_transcript_owners`) was deleted with the guess.  S31's
  regression stays covered: `tests/test_autostart_transcript_finalize.py`
  keeps a live merge window's link readable across a disable and appends
  a later MERGED through it.
- `auto_start._adopt_return_review` (master's S79 fix: adopt the live
  review window a sign-off REVIEW return already launched) now creates
  the adopted link at the *loop-scoped* name for the new loop, not the
  legacy shared `review-<pr>-i1.jsonl`; the loop adopts it as its
  in-flight iteration.
- `review_loop._adopt_in_flight_review`'s in-flight-launch wait (master's
  S82/S133 fix) resolves the transcript through
  `resolve_iteration_transcript`, so it waits on the path the launch
  actually writes (loop-scoped, or a resumed loop's legacy link).
- Master's launch-retry/discovery refactor continues to resolve every
  iteration path through `resolve_iteration_transcript`; no new legacy
  path construction was introduced outside the auto-sequence CLI, whose
  private `auto-sequence/<pr>/` dir deliberately keeps monotonic legacy
  names.

Verified after integration: full suite **5240 passed / 1 skipped**
(`python3 -m pytest tests`, 7m04s, with the `markdown` package installed
for `test_markdown_render`).  The pre/post-fix repro
(`/pm-captures/impl/post-fix/transcript-archive/repro.py --expect fixed`)
still reports all three symptoms fixed at the integrated HEAD.  Two
master tests needed adapting to loop-scoped naming: the S79 adoption test
(`tests/test_return_driver_handoff.py`) now expects the adopted link at
`review-<pr>-<loop_id>-i1.jsonl`.  (The two live-owner unit tests in
`tests/test_transcript_archive.py` were removed in review e757 i4 with
the liveness machinery they pinned.)

## Master integration (2026-11-01, merge of `origin/master` 53bcbd72)

The second user-authorized integration merged `53bcbd72` (#267, plus the
already-in-master #272 and #280) into this branch.  Conflicts were in
`pm/project.yaml` and `pm_core/tui/auto_start.py`:

- **`pm/project.yaml`**: master reordered the PR list (e.g. `pr-7f74c77`
  moved near the end) and added new records (`pr-a3b86b7`, the #272/#280
  follow-ups).  Resolution keeps master's order and every master record,
  drops the stale duplicate `pr-7f74c77` block, keeps this branch's
  branch-only records (`pr-bab46cf`, `pr-bac971d`, `pr-9966785`) and the
  cross-PR note on `pr-22ea6a2`.  Result: 585 unique PRs = master's 582 +
  this branch's 3; master's order is a subsequence.
- **`auto_start.consume_breadcrumb`**: master's #267 refactored the review
  loop restore into `_loop_record_fields` with fail-closed field
  validation.  This PR's d468-i5 loop-id hardening is folded into that
  helper: a missing/blank/null `loop_id` is regenerated at
  `_generate_loop_id()`'s 8-hex width; a wrong-typed one now makes the
  record malformed and it is skipped (fail-closed policy wins over
  repair).  The `iteration_sessions` restore and its ownership checks are
  unchanged, and `_finalize_all_transcripts` auto-merged unchanged (its
  body was then simplified in review e757 i4 — see above).

Verified after this integration: full suite **5477 passed / 1 skipped**
(7m08s), and the post-fix repro still reports all three symptoms fixed.

## Known limitations (accepted)

- **A canonical transcript is only self-contained once it is superseded.**
  A bulk sweep never freezes a canonical link (review e757 i4, user
  decision: only a *new attempt on the same path* changes the link).  So
  the attempt that is live when the run ends stays a symlink to
  `~/.claude/projects/<sid>.jsonl`; if Claude prunes that native file the
  link dangles.  Every superseded attempt is archived on replace and the
  archive entries are frozen, so history survives; only the final attempt
  of each step relies on the native file.  Freezing the final attempt
  would require a definitive end-of-run signal (e.g. process shutdown),
  not a liveness guess.
- **`_finalize_merge` passes no session id.**  It has no launch-time
  session id to compare against; `finalize_transcript` still writes the
  sid-keyed archive copy first, so no content is lost if a newer merge
  run owns the path.
- **A legacy iteration link outlives a finished loop until completion.**
  A loop restored from a pre-upgrade breadcrumb polls the shared legacy
  `review-<pr>-i<N>.jsonl`; the loop's own completion freezes it (with the
  recorded session id) when the loop ends.  A stale legacy link from an
  earlier loop that this loop never adopts stays live: the TUI bulk sweeps
  pass `include_top_level=False` (review e757 i4), so no sweep freezes it,
  and its own loop's completion (or an explicit `finalize_transcript`) is
  the only thing that will.
- **A loop-scoped iteration link whose loop never reached completion stays
  live.**  Loop completion is what freezes a loop's own
  `review-<pr>-<loop_id>-i<N>.jsonl` files, and their names are never
  reused (a new loop gets a new id), so archive-on-replace never runs for
  them either.  If the TUI is killed before the loop's completion callback
  (a crash, a `kill -9`), those links stay symlinks to
  `~/.claude/projects` and a later prune can dangle them.  Freezing them in
  a bulk sweep would mean guessing that the loop is dead, which is the
  liveness rule review e757 i4 removed; the content remains in the native
  JSONL until it is pruned.
- **A completed TUI watcher's own iteration links stay live.**  The
  auto-start watcher shares the run dir with the review loops and the
  step windows, so its completion is a bulk sweep with
  `include_top_level=False` (review e757 i4): it freezes only `archive/`.
  Its own `<watcher-type>-i<N>.jsonl` links (e.g. `auto-start-i1.jsonl`)
  are therefore not self-contained when the watcher ends.  Unlike the
  loop-scoped iteration names they *are* reused — each new watcher run
  restarts at iteration 1 in the same dir — so the next run archives the
  outgoing sessions through archive-on-replace; until then their content
  stays in the native JSONL.  The CLI watcher is the exception: its
  private `watcher-<token>` dir is frozen whole (nothing else reads it).
- **Finalize's last check and `os.replace` are not atomic together.**  The
  readlink guard runs immediately before the replace, so the unguarded
  window is one `os.replace` call; POSIX has no compare-and-swap for a
  symlink, and the writer is a launching child process that shares no
  in-process lock.  A redirect landing inside that call would still be
  clobbered; the archive copy of the replaced session is written first,
  so no session content is lost either way.

## Review e757 i4 — the bulk sweeps stop guessing "finished"

User decision (2026-11-01) on the QA S16-story-3 / R5 INPUT_REQUIRED:
rather than refine the liveness rule, the bulk sweeps no longer freeze
canonical links at all.  The reasoning: a canonical name points at the
attempt that is live *now*, so a reader watching it should see that the
step is still not done; only a *new attempt on the same path* changes the
link (and archives the outgoing session first).

- `finalize_transcript_dir(directory, *, include_top_level=True)`:
  `archive/*.jsonl` links are always frozen; top-level `*.jsonl` links
  only when the caller owns the whole directory.  The `skip` predicate is
  gone.
- `auto_start._finalize_all_transcripts` → `include_top_level=False`,
  and `_live_transcript_owners` / `_live_read_transcripts` /
  `_live_transcript_skip` / `_LAZY_TRACKED_RE` /
  `_LAZY_TRACKED_WITH_SIGNOFF_RE` are deleted (147 lines).  The
  `include_signoff` split disappears with them.
- `watcher_ui._on_complete_from_thread` → `include_top_level=False`
  (it shares the auto-start run dir).
- `cli/watcher.py` keeps the default: its `watcher-<token>` dir is
  private and its process is exiting, so freezing its own iteration
  links is safe and is their only path to surviving pruning.
- Unchanged: archive-on-replace, ownership-checked
  `finalize_transcript`, loop-completion finalization of its own
  loop-scoped iterations (+ the ownership-checked legacy name), and
  `_finalize_merge`.
- Tests: `tests/test_transcript_archive.py` now has
  `test_disable_leaves_canonical_links_live`,
  `test_disable_freezes_archive_entries_only`,
  `test_watcher_completion_leaves_canonicals_live`,
  `test_both_sweeps_leave_a_signoff_link_live` and
  `test_cli_watcher_freezes_its_private_dir` in place of the live-owner
  tests.  `tests/test_autostart_transcript_finalize.py` (master's S31
  file) is rewritten to the same rule and still pins the S31 regression:
  a live merge link shows the later MERGED after a disable, and a gone or
  dead pane's link stays live too.
- Verified: full suite **5476 passed / 1 skipped** (7m07s, markdown
  installed); 889 passed across the archive/review-loop/breadcrumb/
  retry/handoff/auto-start/watcher/signoff/launcher suites; the post-fix
  repro still reports all three symptoms fixed.

Trade-off recorded above (Known limitations): only a *superseded* attempt
is self-contained in the run dir.  The attempt that is live when a run
ends stays a symlink to `~/.claude/projects`, so pruning can lose it;
freezing it would need a definitive end-of-run signal, not a guess.

## Review e757 i5 — spec text catches up with the e757-i4 sweep rule

No code change: the archive/finalize behaviour is exactly as e757 i4 left
it.  The review found five passages where the specs still described the
*pre*-e757-i4 rule, the same class of scenario-text drift that produced
the S10 confusion and the S16-story-3 INPUT_REQUIRED.

- `qa.md` R7's two-return count was self-contradictory: "three
  `impl-<pr>` / three `signoff-<pr>` entries … with the canonical names
  still links to the last attempt".  Under the e757-i4 rule the last
  attempt is *not* archived (its path is never reused during the run), so
  a two-return run ends with **two** entries per step — every superseded
  attempt — plus the canonical link naming the third (live) attempt.
  Corrected, and `test_two_sign_off_returns_keep_both_original_sessions`
  now asserts that exact entry set, so the number cannot drift again
  unnoticed.
- `impl.md`'s d468-i3 bullet stated the old sweep behaviour as current
  fact (the run-end disable sweep freezing every canonical, three entries
  and no canonical link).  Annotated as superseded by e757 i4 with the
  current count.
- `qa.md`'s Ambiguity 2 still framed a canonical link after a disable as
  a consequence of an *open step window* (the deleted liveness rule).
  Rewritten as the rule it now is: a bulk sweep never freezes a canonical
  link, whatever the pane or window state.
- `impl.md`'s Ambiguities #1 claimed archive-on-replace "gives every
  session an immutable archive entry"; only a *superseded* session has
  one until its path is reused (e757 i4).  Corrected.
- `impl.md`'s Known limitations gains the abandoned-loop case: a
  loop-scoped iteration link whose loop never reached completion (a TUI
  crash or `kill -9`) is never frozen, because its name is never reused
  and only the loop's own completion finalizes it.  Freezing it in a bulk
  sweep would be exactly the "the loop must be dead" guess e757 i4
  removed; the content stays in the native JSONL until pruning.

Verified: `tests/test_transcript_archive.py` 34 passed; 385 passed across
the archive / auto-start-finalize / breadcrumb / review-loop /
return-handoff / launch-retry / fail-closed suites; full suite **5476
passed / 1 skipped** (6m59s, `markdown` installed — without it the 12
`test_markdown_render` tests fail with `ModuleNotFoundError`, env-only and
unrelated).  The post-fix repro
(`/pm-captures/impl/post-fix/transcript-archive/repro.py --expect fixed`)
still reports all three symptoms fixed.

## Review e757 i6 — content-keyed archive identity, stale passages, a flaky test

Two identity fixes in the archive matcher and naming, plus docs, one test
assertion and one import move.  The archive/finalize flow is otherwise
unchanged.

- The d468-i2 bullet still said a frozen legacy `review-<pr>-i<N>.jsonl`
  is frozen by "loop completion and the bulk sweeps".  Under e757 i4 a
  bulk sweep no longer touches a canonical link, so only the loop's own
  completion freezes it.  Corrected.
- Known limitations said a stale legacy link "is left for its own loop's
  completion or a `finalize_transcript_dir` caller to handle".  Every TUI
  sweep passes `include_top_level=False`, and the only default caller is
  the CLI watcher's private `watcher-<token>` dir (which never holds a
  legacy review link), so no sweep will freeze it: its own loop's
  completion (or an explicit `finalize_transcript`) is the only thing
  that will.  Corrected.
- `_adopt_return_review` imports `iteration_transcript` with the rest of
  the `pm_core.review_loop` names instead of a second import statement.
- **Frozen-file identity is now content-based, not size+mtime.**  Two
  different sessions can share a byte size and a nanosecond mtime
  (same-length turns written within the filesystem's timestamp
  granularity), and size+mtime was used as identity in two places:
  - `_find_identical_archive` treated an entry with the same size+mtime
    as a copy of the frozen canonical, and `archive_transcript` *deletes*
    the canonical on a match — so a false match dropped the run dir's
    only copy of a session that was never archived (the exact loss R4
    forbids).  Size+mtime is now a cheap pre-filter and
    `filecmp.cmp(..., shallow=False)` confirms the bytes before a
    candidate is accepted.  New test
    `test_identical_size_and_mtime_do_not_make_a_match`.
  - `_archive_name` keyed a frozen file by `<mtime_ns>-<size>`, so a
    colliding second session's entry name already existed and
    `archive_transcript` returned the first session's entry without
    archiving the second (the caller then drops the frozen copy).  A
    frozen file is now keyed by `<sha256(content)[:12]>` (with a random
    fallback only when the file cannot be read), so the name cannot
    collide for two different sessions.  New test
    `test_two_frozen_sessions_with_the_same_size_and_mtime_both_archive`.

  Archive tests 34 -> 36.  Both new tests fail with the old size+mtime
  identity (the first on `archived != other`, the second on `a != b`).
- **Flaky test fixed (e757 i5 introduced it).**
  `test_two_sign_off_returns_keep_both_original_sessions` compared
  `sorted(actual archive names)` against an *unsorted* expected list
  (`[sid1, sid2]` in creation order), so it failed whenever the second
  session id sorted before the first — about half the time on a fresh
  temp dir, which is why some runs passed by luck.  The expected list is
  sorted too now; the test passed 20/20 consecutive runs after the fix,
  and the archive suite passed 10/10 consecutive full-file runs.  The
  archive content and counts were always correct — only the assertion was
  order-sensitive.

Verified: full suite **5478 passed / 1 skipped** (6m59s, `markdown`
installed — 5476 + the two new archive tests); 400 passed across the
archive / auto-start-finalize / breadcrumb / review-loop /
return-handoff / launch-retry / signoff / launcher suites; the archive
suite passed 8/8 consecutive runs; the post-fix repro
(`/pm-captures/impl/post-fix/transcript-archive/repro.py --expect fixed`)
still reports all three symptoms fixed, and the pre-fix repro on
`3699f71a` reports all three present.

## Review e757 i8 — the TUI watcher's own iteration links, documented and pinned

No behavioural change: the archive/finalize flow is exactly as e757 i4
left it.  Review found one undocumented consequence of that rule and no
code defects.

- **The auto-start watcher's own `<watcher-type>-i<N>.jsonl` links stay
  live after its completion.**  `watcher_ui._on_complete_from_thread`
  calls `finalize_transcript_dir(tdir, include_top_level=False)` because
  the watcher shares the run dir with the review loops and the step
  windows, so it freezes only `archive/`.  That is the e757-i4 rule, but
  the spec's Known limitations covered only canonical names and
  loop-scoped iteration names, so a QA reader could reasonably have
  expected the watcher's finished iterations to be frozen.  Unlike the
  loop-scoped names, these *are* reused (each watcher run restarts at
  iteration 1), so the next run archives the outgoing sessions via
  archive-on-replace.  Now a Known limitations bullet, and `qa.md` R5
  states that a live `auto-start-i<N>.jsonl` after a completion is not a
  failure (the CLI watcher's private `watcher-<token>` dir stays the
  exception: frozen whole).
- **Pinned by test.**  `test_watcher_completion_leaves_canonicals_live`
  now also links `auto-start-i2.jsonl` and asserts it stays live and that
  a later appended turn is visible through it, alongside the frozen
  archive entry.  No new test function (archive suite stays at 36).

Verified at the e757-i8 tree: `tests/test_transcript_archive.py` 36
passed (10/10 consecutive runs); 506 passed across the archive /
auto-start-finalize / breadcrumb / review-loop / return-handoff /
launch-retry / fail-closed / signoff / launcher suites; full suite
**5478 passed / 1 skipped** (7m08s, `markdown` installed); the post-fix
repro (`/pm-captures/impl/post-fix/transcript-archive/repro.py --expect
fixed`) still reports all three symptoms fixed.

## Review e757 i9 — stale source docstrings and two design bullets

No behavioural change: the archive/finalize flow is exactly as e757 i4
left it.  Two *source* docstrings and two design bullets still described
the pre-e757-i4 rule or a mechanism that no longer exists — the same
drift class that produced the S10 confusion and the S16-story-3
INPUT_REQUIRED, this time in code rather than in the QA text.

- `review_loop.resolve_iteration_transcript`'s docstring justified
  "a frozen legacy transcript is never reused" with "loop completion and
  the bulk sweeps both freeze it".  Since e757 i4 a bulk sweep never
  touches a canonical link, so only the loop's own completion freezes a
  legacy iteration transcript.  (e757 i6 corrected the same sentence in
  this spec; the docstring was missed.)
- `review_loop._generate_loop_id`'s docstring said the loop id's
  hex-only shape is what "the live-owner prefix matching relies on".
  That machinery was deleted in e757 i4.  The property is still worth
  stating (an opaque hex id can never look like the `i<N>` iteration
  marker), but nothing depends on it — the `-` separators already keep
  a loop-scoped name out of the legacy pattern — so it is described as a
  naming-scheme property rather than a load-bearing requirement.
- Design section, `finalize_transcript`: `target = Path(raw)` was wrong
  for a relative link (it would resolve against the process CWD).  The
  code uses `_absolute_link_target(path, raw)`, which resolves against
  the link's own directory; the bullet now says so.
- Design section, `archive_transcript`: the non-session-named link key is
  the sha256 of the *absolute* target (so a relative link and its
  absolute form map to one entry); the bullet now says that too.

No code defect found in this pass: archive-on-replace (no-clobber,
content/sid-keyed, never `rename`), ownership-checked finalize (readlink
at entry, guard after the copy before `os.replace`, archive copy written
first), loop-scoped iteration names with `allow_legacy` only for a
resumed in-flight iteration, `iteration_sessions` round-tripped through
the breadcrumb, retire-archives-without-deleting, and the e757-i4 rule
that bulk sweeps never freeze a canonical are consistent across every
caller.

Verified: `tests/test_transcript_archive.py` 36 passed; 281 passed across
the archive / review-loop / breadcrumb / launch-retry / return-handoff /
auto-start-finalize suites; full suite **5478 passed / 1 skipped**
(`markdown` installed); the post-fix repro
(`/pm-captures/impl/post-fix/transcript-archive/repro.py --expect fixed`)
still reports all three symptoms fixed.

## Review e757 i10 — the adopted REVIEW return is actually polled, not relaunched

One behavioural fix in a path this PR touches, plus one spec correction.

- **S79 adoption was silently broken** (pre-existing on master since the
  2026-10-27 `allow_recovery` gate in review-loop 385e i1, not introduced
  by this PR).  `auto_start._adopt_return_review` creates the loop-scoped
  iteration link from the return's live pane and starts a loop with a
  fresh `ReviewLoopState(iteration=1)`.  `run_review_loop_sync` treats
  iteration 1 as an adopt candidate, but `_adopt_in_flight_review` gates
  its recovery on `state.iteration_attempted or state.launch_attempts > 0`
  — both false for that fresh state — so `_discover_iteration` returned
  `launch`, `_adopt_in_flight_review` returned `None`, and the loop
  relaunched `--fresh`, killing the very window the adoption exists to
  preserve (two review launches for one return — the S79 bug).
  `_adopt_return_review` now sets `state.iteration_attempted = True`: the
  iteration *is* in flight (another driver launched it), and the link was
  created a moment ago from the return's live pane, so the fabrication
  guard (which protects against an *earlier run's* transcript for the same
  iteration number) does not apply.  Verified end to end: with the link
  and a live pane, the loop polls the adopted session (no
  `_run_claude_review` call); with a verdict already in the transcript it
  reads it directly.  Regression test
  `test_adopted_return_review_is_polled_not_relaunched` in
  `tests/test_return_driver_handoff.py` fails without the flag (it
  observes `None` from `_adopt_in_flight_review`) and passes with it.
- **Spec correction (QA transcripts edge case).** The line claimed QA
  transcripts are "produced via native `transcript_path_for` paths, not
  `build_claude_shell_cmd(transcript=...)`".  The QA loop's own verdict
  transcripts are native, but a scenario worker *does* get a
  `build_claude_shell_cmd(transcript=...)` symlink — at
  `<qa-workdir>/transcript-s<N>.jsonl`, outside the run dir — so a
  scenario relaunch archives its outgoing link under `<qa-workdir>/archive/`
  and never touches the run archive under test.  Corrected to say that.

Verified: 470 passed across the archive / auto-start-finalize / breadcrumb /
review-loop / return-handoff / launch-retry / fail-closed / signoff suites;
`tests/test_return_driver_handoff.py` 12 passed; the post-fix repro
(`/pm-captures/impl/post-fix/transcript-archive/repro.py --expect fixed`)
still reports all three symptoms fixed.  Full suite re-run after the
change: **5479 passed / 1 skipped** (7m19s, `markdown` installed —
5478 + the new regression test).
