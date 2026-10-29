# QA Spec: pr-9ee4d64 — run transcripts must not be overwritten across sign-off returns

## Summary

An auto-start run keeps one transcript per (step, PR) in
`pm/transcripts/<autostart-run>/`: `impl-<pr>.jsonl`,
`signoff-<pr>.jsonl`, `review-<pr>-<loop>-i<N>.jsonl`, `merge-<pr>.jsonl`.
Those names are canonical and reused by successive attempts. A sign-off
return (`SIGNOFF_IMPL` / `SIGNOFF_REVIEW` / `SIGNOFF_REQA`) re-runs a step
inside the same run, so the pre-return sessions used to be erased from the
run archive. Separately, a superseded review loop's completion callback
could freeze a newer loop's *live* transcript into an early copy, so the
new loop's collector never saw the verdict appended later (the 2026-10-28
#241 / #248 S11 failure).

The fix (see `impl.md`) makes every attempt an immutable entry under
`<run>/archive/<stem>.<session-id>.jsonl`, makes finalization
ownership-checked, names review iterations per loop, archives instead of
deleting on retire, and makes bulk sweeps skip transcripts whose session
may still be writing.

QA must confirm the user-visible archive behaviour on the real surfaces
(TUI auto-start, TUI per-PR auto-sequence, CLI `pm pr auto-sequence`, CLI
watcher), not the helper functions.

## Requirements (Given / When / Then)

### R1 — Reusing a canonical path preserves the outgoing session
- **Given** an auto-start run has driven a PR through implementation and
  review, so `pm/transcripts/<run>/impl-<pr>.jsonl` is a link to that
  implementation session.
- **When** sign-off routes the PR back to implementation and the rework
  session launches.
- **Then**
  - `impl-<pr>.jsonl` now resolves to a different (new) session id than
    before the return;
  - `pm/transcripts/<run>/archive/` contains an entry named after the
    pre-return session (`impl-<pr>.<old-sid>.jsonl`) whose content is that
    session;
  - both files are readable and nothing in the run dir was deleted.

### R2 — A returned router transcript is archived, and its verdict is not replayed
- **Given** the sign-off router has returned a PR (`SIGNOFF_IMPL` /
  `SIGNOFF_REVIEW` / `SIGNOFF_REQA`); its transcript is
  `signoff-<pr>.jsonl` and its launch stamp is `signoff-<pr>.head`.
- **When** the driver retires that router run for the return and the PR
  later re-enters sign-off.
- **Then**
  - the returning router session survives in `archive/` and its content
    (including the verdict keyword) is readable;
  - the launch stamp is gone, and the next sign-off entry launches a fresh
    router session (a new session id) instead of adopting the spent
    verdict — the PR does not re-bounce for the same reason;
  - verdict readers that scan the run dir do not pick up the archived copy
    (no false return, no duplicate/conflicting verdict).

### R3 — Review iterations are per-loop, so a REVIEW return keeps both loops
- **Given** a review loop has completed iteration(s) for a PR and sign-off
  returns the PR to review.
- **When** the fresh review loop starts and reaches iteration 1.
- **Then**
  - the new iteration's transcript is a distinct file named for the new
    loop, and the earlier loop's iteration files are untouched;
  - both loops' transcripts are present in the run dir (or its archive)
    with their own content;
  - the new loop's verdict is detected normally and the PR advances.

### R4 — A superseded loop cannot freeze the current loop's live transcript
- **Given** a review loop is running an iteration (its transcript is a live
  link to a session that is still writing), and the user restarts the loop
  (or a sign-off return starts a new loop for the same PR).
- **When** the superseded loop's completion runs while the new loop is
  still polling.
- **Then**
  - the new loop's transcript stays live (a link that still grows) and the
    verdict the session appends later is still detected — the loop reports
    its own verdict rather than "no verdict"/an early verdict;
  - the superseded loop's own transcript(s) are preserved (frozen copy
    and/or archive entry), never deleted;
  - no canonical file is missing, truncated, or replaced by a copy of a
    different session.

### R5 — Bulk sweeps leave work that is still writing alone
- **Given** auto-start is on, a review loop is mid-iteration and the
  auto-start watcher is running, and the same run dir holds finished step
  transcripts as links.
- **When** the user turns auto-start off (clears targets / toggles it off)
  or the watcher loop completes.
- **Then**
  - the running loop's transcript remains a live link and the loop still
    finishes with its verdict;
  - finished transcripts become self-contained copies (no longer links);
  - links already inside `archive/` are also frozen, so archived sessions
    survive Claude transcript pruning;
  - the sweep removes and truncates nothing.

### R6 — Restart mid-flight resumes on the same transcript
- **Given** a review loop or sign-off step is in flight in auto-start run R.
- **When** the user restarts the TUI (Ctrl+R / kill and relaunch) and
  auto-start resumes.
- **Then**
  - the resumed loop polls the same iteration transcript it was using and
    adopts the in-flight session;
  - on completion it finalizes only its own sessions (ownership-checked),
    so a newer session on a shared path is untouched;
  - sessions written before the restart remain available (archive entries),
    with no duplicate or overwritten entries;
  - a resumed loop whose in-flight iteration was adopted under the
    pre-upgrade legacy name still gets that file frozen and archived
    instead of leaving it a permanent link.

### R7 — Multiple returns and overlapping PRs in one run
- **Given** one auto-start run covers two PRs (a target and a dependency)
  and one of them is returned to implementation twice.
- **When** the run finishes both PRs.
- **Then**
  - the returned PR's archive holds both pre-return implementation
    sessions and both returning router sessions;
  - the other PR's transcripts are unaffected (no cross-PR file mixups);
  - merge transcripts for both PRs exist, and any superseded merge/impl/
    sign-off attempts are archived rather than lost;
  - every archive entry has a unique name; none was overwritten.

### R8 — CLI drivers keep history too
- **Given** a user drives a PR with repeated `pm pr auto-sequence` ticks
  and separately runs the CLI watcher (`pm watcher --max-iterations N`).
- **When** sign-off returns the PR under auto-sequence and the watcher loop
  reaches its iteration limit and exits.
- **Then**
  - `pm/transcripts/auto-sequence/<pr>/` keeps the pre-return implementation
    session in `archive/` and the rework session at the canonical name; the
    retired sign-off transcript is archived, not deleted;
  - the watcher's transcript dir shows its iteration transcripts frozen into
    self-contained copies on exit, including anything in its `archive/`;
  - the commands' output/log lines report the archive and finalize actions.

### R9 — A failed archive never blocks the workflow
- **Given** the run dir's `archive/` directory cannot be written
  (e.g. permissions).
- **When** a return relaunches a step that reuses a canonical transcript
  path.
- **Then**
  - the launch still happens and the workflow advances (no hang, no crash,
    no stuck window);
  - the canonical path is replaced by the new session;
  - a warning about the failed archive is logged;
  - the previous session remains recoverable from `~/.claude/projects`.

## Setup

Cross-cutting setup for every scenario:

- Use `tui-manual-test.md`: install pm from this branch into a venv, export
  `PYTHONPATH` to the clone, create a throwaway project with `pm init
  --backend local --no-import` and add PRs with `pm pr add`, start the pm
  session, and drive everything through the TUI / CLI.
- Configure the fake Claude stand-in with `pm fake-claude config set` before
  starting the run: `impl`/`merge` as no-verdict sessions, `review` as a
  scripted `PASS`, `signoff` as a scripted sequence (e.g. `SIGNOFF_IMPL`
  then `SIGNOFF_MERGE`; `SIGNOFF_REVIEW` for the review-return scenario),
  `watcher` as `READY`, and `_all: {}` for the rest. Scripted sequences emit
  one verdict per iteration.
- Use an auto-merge target (`A` / `pm autostart add <pr> --auto-merge`) when
  the scenario should run all the way to merge; use `--wait-for-merge` when
  the run should stop at sign-off.
- The transcript run dir is `pm/transcripts/<autostart-*|manual-*|auto-sequence|watcher-*>`
  under the throwaway project; inspect it with ordinary file tools (listing,
  `readlink`, reading JSONL). This is the user-facing archive under test.
- Evidence goes in the captures directory the scenario prompt names, using
  the assigned artifact recipe. Keep a `manifest.md` per capture.

## Edge cases

- **Dangling canonical link** (a previous launch died before Claude wrote its
  native JSONL): the next launch replaces it and the workflow advances; no
  crash and no `FileExistsError`.
- **Frozen canonical at return time** (a regular file, not a link): it is
  archived by rename — never deleted.
- **Same session already archived**: a second archiving attempt adds no
  duplicate entry and never overwrites the existing one.
- **A superseded callback arriving after the new loop archived the same
  path**: the newer entry is untouched and the live path is not replaced.
- **A stale pre-upgrade `review-<pr>-i1.jsonl` sitting next to loop-scoped
  files**: the new loop polls its own loop-scoped file, not the stale one;
  the stale file is not treated as the current verdict.
- **Two sweeps at once** (auto-start disable and watcher completion, or a
  loop completion) finalizing the same directory: no truncated or missing
  transcript; archive entries stay complete.
- **Malformed / truncated breadcrumb** (`iteration_sessions` not an object):
  the restart still restores the remaining loops and auto-start state rather
  than abandoning the run.
- **Archive subdirectory is not current**: sign-off/review readers and
  launch stamps never mistake an archived entry for the live transcript.
- **Merge finalize has no session id**: the archive copy is still written
  first, so a newer merge run cannot lose the old content.

## Pass/Fail criteria

**Pass** when, on every exercised surface:

- Every launched session that produced a transcript is still readable
  somewhere in the run dir (canonical file, archive entry, or link into
  `~/.claude/projects`) after any number of returns, restarts, iteration
  resets and sweeps — including the router session that made each return
  decision.
- The live canonical path for the current attempt keeps receiving appends
  until that attempt finishes, and the collector reports the verdict the
  session actually emitted (never an early copy's verdict, never an invented
  one).
- No operation deletes or truncates transcript history; archive entries are
  never overwritten and never duplicated.
- Workflows still advance: returns re-run the right step, PRs reach merge,
  restarts resume, and a failed archive does not block a launch.

**Fail** on any of:

- a pre-return impl / sign-off / review session missing from the run dir
  after a return (the original bug);
- a current loop's transcript frozen/replaced by a superseded callback, or
  its later verdict not detected;
- a running loop/watcher transcript frozen by a disable or a watcher
  completion;
- a retired router verdict replayed (PR re-bounces for the same reason), or
  an archived entry read as the current verdict;
- a launch blocked, window stuck, or crash caused by archive/finalize;
- duplicate or overwritten archive entries, or a truncated transcript.

## Ambiguities

Resolved without user input:

1. **What counts as "preserved"?** The run dir must contain a readable
   artifact for the session. An archive entry may be a symlink into
   `~/.claude/projects` while the run is live and a self-contained copy after
   a finalize sweep; both pass. The native JSONL existing alone does not
   count — the run archive must carry it.
2. **A step window left as a link after auto-start disable.** The
   implementation treats an open step window as possibly still writing, so a
   disable may leave that step's canonical transcript a link. Pass, provided
   the content is readable and it is archived when the path is next reused.
3. **Auto-sequence CLI iteration naming.** `pm pr auto-sequence` continues
   iteration numbering across a REVIEW return (unlike the TUI loop, which
   restarts at 1 with a new loop id). Both are acceptable; what matters is
   that no session is overwritten.
4. **QA transcripts.** Produced through native transcript paths, not the run
   dir; out of scope except that nothing in this change may break a QA run.

No **[UNRESOLVED]** ambiguities.

## Mocks

All Claude sessions are driven by `fake-claude` via
`pm fake-claude config set` (see `tui-manual-test.md`). No real model calls.
tmux, git, the filesystem and the pm TUI/CLI run for real. GitHub is not
needed — use a local backend project and local merges.
