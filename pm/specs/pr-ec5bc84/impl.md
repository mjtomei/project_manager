# pr-ec5bc84 — Use native session logs and remove the pm/transcripts indirection

## Summary

Every PM role launch that needs its verdict collected later (impl, review,
review-loop iterations, sign-off router, merge resolution window, watchers,
QA scenario workers) currently passes `--transcript <path>` to a child CLI.
The child's `claude_launcher.build_claude_shell_cmd(transcript=...)` invents
a session UUID and writes a **symlink** at that path pointing at Claude's
native JSONL (`~/.claude/projects/<mangled-cwd>/<sid>.jsonl`). The parent
then *derives the session identity from the symlink*
(`session_id_from_transcript`) and polls the symlink for verdicts.
Completion callbacks and sweeps replace symlinks with copies
(`finalize_transcript`).

The paths are canonical and reused — `pm/transcripts/<run>/impl-<pr>.jsonl`,
`signoff-<pr>.jsonl`, `review-<pr>-i<N>.jsonl`, `merge-<pr>.jsonl`,
`review-<pr>.jsonl`, `<watcher>-i<N>.jsonl` — so the identity a reader gets
is whatever attempt last rewrote the alias. #241's incident: loop A's late
completion (`review_loop_ui._on_complete_from_thread`) froze every
`review-<pr>-*` symlink in the run dir, including loop B's live
`review-<pr>-i1.jsonl` (iteration restarted at 1 after a sign-off return);
B kept polling a frozen copy and never saw its NEEDS_WORK. Sign-off returns
also overwrite/delete the reused paths, losing earlier history from the run
dir although Claude retains the native sessions (this install sets
`cleanupPeriodDays: 365000`).

This PR removes the alias entirely. A launch records **its own identity**
(project/PR, phase, run, loop, iteration, attempt → native session id and
native log path) in one tiny append-only ledger, and collectors read the
native log of the exact session they launched. Nothing is copied, frozen,
archived or deleted; native retention governs history.

## Design (one small common resolver)

### `pm_core/session_log.py` (new)

- **Location:** `runtime_state._runtime_dir() / "sessions" / <subject>.jsonl`,
  i.e. `~/.pm/runtime/<pm-session>/sessions/<subject>.jsonl`. This reuses the
  existing per-pm-session runtime scope (S93: two clones of one project do
  not share it) and the test suite's autouse runtime-dir isolation
  (`tests/conftest.py::_isolated_runtime_state`). `<subject>` is the PR id, or
  `watcher-<type>` for watchers (they have no PR). `pr_cleanup` deletes only
  `<pr>.json`, never the ledger; runtime sweeps iterate only top-level `*.json`.
- **Format:** append-only JSON lines, written under `flock` with `O_APPEND`;
  never rewritten, truncated or deleted by pm. Events:
  - `launch`: `v, event, at, subject, phase, session_id, cwd, log, run, loop,
    iteration, attempt, head, base` (+ `legacy` path or `adopted_from` run when
    the record was adopted rather than launched).
  - `retire`: `session_id, reason` — marks a session as no longer the current
    run of its phase (sign-off bounce) without touching any log.
- **API (all small):**
  - `SessionLaunch(subject, phase, run_id="", loop_id="", iteration=None,
    attempt=None, head="", base="")` — the identity a caller hands the launcher.
  - `register(launch, session_id, cwd) -> SessionRecord` (log =
    `claude_launcher.transcript_path_for(cwd, sid)`).
  - `records(subject)`, `find(subject, *, phase, run_id, loop_id, iteration,
    include_retired)`, `latest(...)`, `by_session(subject, sid)`.
  - `retire(subject, sid, reason)`; `adopt(launch, sid, log)` — append a
    launch event naming an *existing* session under a new driver identity
    (no copy), keeping the cwd its own launch recorded and naming that
    launch's run in `adopted_from` (`unrecorded` when pm never recorded it).
    Legacy and cross-run sign-off adoptions call `register(..., log=,
    legacy=/adopted_from=)` directly.
  - `log_path(record)` → the recorded native path, else the session-id lookup
    `~/.claude/projects/*/<sid>.jsonl` (the existing pr-488b748 band-aid, keyed by
    the known id — never a history scan); `log_state(record)` →
    `present | missing`; `missing_message(record)` — an accurate report that
    names the session, the expected path and Claude's configured
    `cleanupPeriodDays` (read-only from Claude settings; pm never changes it);
    `missing_suffix(record)` appends it to a collector's give-up message only
    when the log is missing.
  - **Bounded read-only legacy reader** `legacy_session(root, run_id, name,
    subject)` for `pm/transcripts/<run>/<name>` (`auto-sequence` maps to
    `auto-sequence/<pr>/`): a symlink yields its target's session id + native
    path; a frozen copy yields the session id from its content and, when the
    native log is gone, the copy itself as the log (only remaining evidence);
    a `.head` sidecar yields `head`/`base`. `resolve(subject, phase, run_id, ...,
    legacy_name=, root=)` returns the latest matching ledger record and, only
    when the ledger has none, adopts the legacy entry once (appending an
    adopted record) so later reads are ledger-only. Legacy files are never
    modified, moved or deleted.
  - `artifacts_dir()` → `<runtime>/launch-artifacts/` for failed-launch
    stdout/stderr artifacts (previously `pm/transcripts/<run>/launch-artifacts/`).

### Launch boundary (`pm_core/claude_launcher.py`)

- `build_claude_shell_cmd(..., launch: SessionLaunch | None = None)` replaces
  `transcript=`. With `launch`, it uses the caller's `session_id` when given
  (pre-generated by a collector that must know the exact attempt), else a
  fresh uuid4; never `--resume`; registers the record with the cwd Claude
  actually runs in (container launches pass `/workspace`, so the log is the
  host `~/.claude/projects/-workspace/<sid>.jsonl` the mounted config writes).
  No symlink, no `pm/transcripts` directory.
- Removed: `finalize_transcript`, `pane_runs_transcript` (→
  `pane_session_id(pane_id) -> str | None`, the `--session-id/--resume` id in
  the pane's start command). Kept: `transcript_path_for`,
  `pane_transcript_path`, `session_id_from_transcript` (parses a native path;
  still reads a pre-upgrade symlink read-only).

### CLI handoff

- Hidden options on `pm pr start`, `pm pr review`, `pm pr merge`,
  `pm pr signoff`, `pm watcher`: `--run-id RUN` and (review, watcher)
  `--session-id SID`. The child passes them into `SessionLaunch`.
- Hidden legacy `--transcript PATH` stays accepted for one transition (an
  old-code TUI that has not re-exec'd yet may still spawn a new-code child):
  it is only parsed to derive the run id (`<run>` = parent dir name;
  `.../auto-sequence/<pr>/...` → `auto-sequence`). **Nothing is written at
  PATH.** The old parent then fails to read a symlink and treats the attempt
  like any failed/unknown launch; after the merge restart the new TUI finds
  the launch in the ledger (see restart adoption below).

## Requirements

### R1 — Launches register their own identity; no new writes to pm/transcripts

Producers that passed `transcript=`/`--transcript` and now pass
`SessionLaunch`/`--run-id`:

| Producer | Phase / identity |
|---|---|
| `cli/pr.py::pr_start` (impl) | `impl`, run |
| `cli/pr.py::_launch_review_window` (`pm pr review`) | `review`, run, loop, iteration, attempt, caller sid |
| `cli/pr.py::_launch_merge_window` / `_finalize_merge` | `merge`, run (finalize no longer copies) |
| `signoff.py::launch_signoff_window` | `signoff`, run, `head`/`base` (replaces the `.head` stamp) |
| `cli/watcher.py::_create_watcher_window` | subject `watcher-<type>`, `watcher`, run, loop, iteration, caller sid |
| `qa_loop.py::_build_scenario_run_cmd` (+ relaunch) | `qa`, loop (QA loop id), iteration = scenario index, caller sid |

Callers that chose the path now pass the run id: `tui/auto_start._start_pr_quiet`,
`tui/pr_view.start_pr/review_pr`, `tui/review_loop_ui` merge command,
`tui/signoff_ui._launch_quiet`, `review_loop._launch_review_window`,
`watchers/*::build_launch_cmd`, `cli/pr.py` auto-sequence (run `auto-sequence`).
Directory creation is removed from `auto_start._ensure_run`,
`consume_breadcrumb`, `review_loop_ui._start_loop`, `signoff_ui._launch`,
`cli/pr.py::pr_auto_sequence`, `cli/watcher.py` (3 sites). `get_transcript_dir`
becomes `get_run_id` (same run-id rules: active auto-start run, else a
per-TUI `manual-<hex>`).

### R2 — Collectors read the exact session

- **Review loop** (`review_loop.py`): each attempt pre-generates its sid,
  launches `pm pr review ... --session-id S --run-id R`, then requires the
  ledger record for `S` (missing → retryable `ReviewLaunchError("launch
  registered no session")`, artifact kept) and polls `log_path(record)`.
  `_discover_iteration` treats only ledger records of **this loop**
  (`loop_id`, `iteration`) as "ours"; `_is_historical_session` uses
  `last_session_id`, `stale_pane_session_id` and this loop's earlier-iteration
  records (no directory glob). `stale_session_id` (which guarded the shared
  symlink) is no longer consulted except for legacy adoption. Follow-up
  (`_wait_for_follow_up_verdict`) polls the iteration's own session
  (`state.last_session_id`). In-flight wait (`_wait_for_launching_window`)
  keys on the latest attempt record's log existence. Loop ids widen from 4 to
  8 hex so a PR's loops cannot collide on `(loop_id, iteration)`.
- **TUI idle/verdict tracking** (`review_loop_ui` impl/merge/manual-review
  passes; `cli/pr.py::_check_impl_idle`): resolve the pane's own session
  (`pane_session_id`); register the tracker only when that session's ledger
  record has the expected phase and this driver's run (preserving the S79
  "another driver's pane" guard). When the pane shows no session id, use the
  run's latest record of that phase (prior semantics).
- **Sign-off** (`signoff.py`): `step_signoff(..., run_id=...)`; the current
  run is the latest non-retired `signoff` record of `(pr, run)`;
  `signoff_transcript_verdict`, `signoff_launched_sha/base` read that record;
  `retire_signoff_run` kills the window and appends `retire` (logs kept), so a
  consumed verdict cannot be replayed and the earlier session stays
  discoverable. `signoff_ui._adopt_orphaned_run` adopts the live sign-off
  pane's session from another auto-start run by appending an adopted record
  (never from a `manual-*` run or the CLI `auto-sequence` driver's run — a
  live driver of its own, which the pre-upgrade layout kept out of reach).
- **Auto-sequence** (`cli/pr.py`): `_check_review_verdict` reads the latest
  `review` record (by iteration) of run `auto-sequence`; numbering continues
  after the highest recorded (or legacy) iteration.
- **Watchers** (`watcher_base.py`): per-iteration pre-generated sid; poll and
  follow-up read that session's record.
- **QA scenarios**: `scenario.transcript_path` is the native path for the
  pre-generated `scenario.session_id`; the resume snapshot already persists
  both (existing runtime metadata reused).

### R3 — No copy/freeze/archive service

Remove `finalize_transcript` and every caller: `review_loop_ui._on_complete_from_thread`
(the #241 finalizer), `auto_start._finalize_all_transcripts` /
`_live_read_transcripts` / `_disable`, `watcher_ui._on_complete_from_thread`,
`cli/watcher.py::_run_user_watcher_loop`, `cli/pr.py::_finalize_merge`.
A late completion therefore cannot freeze or retarget anything: it touches
no log and no alias exists.

### R4 — Missing/pruned logs reported accurately

A record whose log is absent reads as "no verdict yet" and never falls back
to another session or a canonical file. Where a collector gives up (retry
exhausted, verdict expected from a dead pane, history listing) the message is
`missing_message(record)`: the review loop's and watchers' "pane disappeared"
(KILLED) reports append it via `missing_suffix` when the attempt's session
left no log. `pm pr sessions <pr>` / `pm watcher sessions
[type]` list ledger rows with `present`/`missing` status (read-only history
reader; prompts that pointed agents at `transcripts/auto-sequence/...` and the
watcher-review "Per-test transcripts" dir point at these commands instead).

### R5 — Safe upgrade (bounded, read-only)

- Breadcrumb review loops: new breadcrumbs save `run_id`; a legacy record's
  `_transcript_dir` maps to `run_id = basename` and is kept as
  `state.legacy_transcript_dir` for one read-only adoption of the in-flight
  `review-<pr>-i<N>.jsonl` (skipping a link whose sid is the saved
  `stale_session_id`). `_loop_record_fields` accepts both, fail-closed on types.
- Sign-off / impl / merge / manual review / auto-sequence: `session_log.resolve`
  adopts the run's legacy canonical link once when the ledger has nothing for
  that phase+run. `signoff_ui._adopt_orphaned_run` additionally recognises a
  legacy link of another run whose sid is the live pane's.
- QA resume: an old symlink `transcript_path` keeps working (symlinks are read
  through); a relaunch uses the native path.
- Old-code parent / new-code child: legacy `--transcript` → run id only.
- Nothing deletes or rewrites `pm/transcripts` (legacy copies may be the only
  remaining evidence); `.gitignore` keeps ignoring it.

## Implicit requirements

1. Parent and child resolve the same runtime scope (`runtime_state._scope()`:
   the tmux session of the pane, else the clone's session) — the same
   assumption the review-loop launch lease already relies on.
2. A record is registered when the command is built (before the window
   exists). A launch that fails afterwards leaves a record whose log never
   appears: `missing`, never a verdict. Collectors that pre-generate a sid
   only trust records with *their* sid.
3. Appends are atomic per line (single `write` under `LOCK_EX`); readers
   tolerate a torn/garbled last line by skipping unparsable lines.
4. Exact-session reads re-read the native file every poll (appended turns
   stay visible) — nothing ever snapshots it.
5. Verdict policy is unchanged: same verdict sets, same `find_verdict_turn`,
   same sign-off binding (HEAD/base now come from the record).
6. Manual merge/spec gates and `wait_for_merge` are untouched.
7. Coordination with #237 (pr-8020495 action history): it records
   `session_id`/`transcript` per action; after this PR `transcript` should be
   the native path and identity the session id. Note left on that PR; no
   history feature is added here.

## Ambiguities (resolved)

1. **Where the mapping lives.** Options: project.yaml (git-tracked, shared
   across hosts — wrong for host-local paths), the per-PR runtime JSON (swept
   and deleted by cleanup — not durable), a new tree in the repo (recreates
   the problem). Chosen: append-only ledger beside the runtime JSON.
2. **Who generates the session id.** Collectors that wait on one specific
   attempt (review loop, watcher loop, QA scenario) pre-generate it; other
   launches let the launcher generate it and are found by phase+run (+pane sid).
3. **Run ids.** Kept as a record field (driver scope for sign-off, S79 guard)
   with the old values (`autostart-*`, `manual-*`, `auto-sequence`,
   `watcher-*`); they no longer name directories (`valid_run_id` stays as
   fail-closed validation of saved state).
4. **Launch-failure artifacts** are execution stdout/stderr, not transcripts:
   kept, relocated to `<runtime>/launch-artifacts/`.
5. **QA planner/concretize/verifier/finalize** already use pre-generated
   sids + `transcript_path_for` with ids persisted in QA state; unchanged
   (only scenario workers used PM symlinks).
6. **Legacy `--transcript`** accepted but write-free (above) rather than
   removed (would break an old parent mid-restart) or honoured (would recreate
   the tree).

## Edge cases

- Fresh review loop after a sign-off REVIEW return restarts at iteration 1
  under a new loop id: its records never match the old loop's.
- Late completion of an obsolete loop (#241): no finalization exists; the
  newer loop's later NEEDS_WORK is read from its own native log.
- Concurrent PRs: per-subject ledgers; records carry the PR.
- Sign-off returns (IMPL/REVIEW/REQA): each new router run is a new record;
  the bounced one is `retire`d, both remain listed with their logs.
- TUI restart: loops resume from `loop_id`+`iteration` (+ legacy dir once);
  sign-off resumes from the restored run id; orphan sign-off panes adopt by sid.
- Human follow-up in the existing pane (INPUT_REQUIRED): the follow-up wait
  polls the same session's log; appended answers are visible.
- Pruned native log: `missing` + message; no verdict, no substitution.
- Fake Claude writes its JSONL at the native path for the session id it is
  given — unchanged.
- `CLAUDE_CONFIG_DIR`: pm's native path computation is unchanged (out of
  scope); the session-id lookup fallback covers slug drift.

## Verification plan

- Repro `$CAP/impl/pre-fix/` against an origin/master worktree: obsolete
  loop completion freezes the newer loop's live link and hides its later
  NEEDS_WORK (`repro.py --expect bug`); post-fix the same scenario via the new
  API shows the verdict and an unchanged native log, and no `pm/transcripts`
  tree (`--expect fixed`).
- Unit/integration tests (isolated HOME, runtime dir, tmux socket):
  ledger + resolver + legacy adoption; review-loop exact-session discovery,
  restart at iteration 1, obsolete completion, follow-up; sign-off
  record/retire/return cycles and orphan adoption; impl/merge tracking S79
  guard; auto-sequence numbering; watchers; QA scenario native path; CLI
  `--transcript` legacy mapping writes nothing; breadcrumb round trip.
- Full suite once on the final tree vs the master baseline.
