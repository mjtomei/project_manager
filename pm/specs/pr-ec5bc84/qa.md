# QA spec — pr-ec5bc84: native session logs replace pm/transcripts

## What changed (user-visible view)

Before this PR, every pm-launched Claude session whose verdict pm collects
(impl, review / review-loop iterations, sign-off router, merge-resolution
window, watcher iterations, QA scenario workers) got a PM-owned alias under
`pm/transcripts/<run>/<canonical-name>.jsonl`: a symlink to Claude's native
JSONL, later "finalized" into a frozen copy. Canonical names were reused
across loops and sign-off returns, so a reader got whatever attempt last
rewrote the alias. Bug #241: an obsolete review loop's late completion froze
the *newer* loop's live `review-<pr>-i1.jsonl`, and the newer loop never saw
its NEEDS_WORK.

After this PR:

- Each launch records its own identity (PR or `watcher-<type>`, phase, run,
  loop, iteration, attempt, sign-off HEAD/base) with its native session id and
  native log path in an append-only ledger
  `~/.pm/runtime/<pm-session>/sessions/<subject>.jsonl`.
- Collectors read the native log of the exact session they launched.
  Nothing is symlinked, copied, frozen, archived or deleted. No new
  `pm/transcripts` entries are ever created.
- New read-only CLI: `pm pr sessions <pr> [--phase P] [--json]` and
  `pm watcher sessions [TYPE] [--json]` list recorded sessions with
  `log[present|missing]`, retired/adopted flags.
- Missing/pruned native logs are reported accurately (naming the session,
  expected path, and Claude's configured `cleanupPeriodDays`, read from
  `$CLAUDE_CONFIG_DIR` or `~/.claude`), never treated as a verdict, never
  substituted by another session.
- Pre-upgrade `pm/transcripts` entries (symlinks, frozen copies, `.head`
  stamps, `auto-sequence/<pr>/` dir, breadcrumb `_transcript_dir`) are
  adopted once, read-only. They are never modified or deleted.
- Hidden `--transcript PATH` stays accepted on `pm pr start/review/merge/
  signoff` and `pm watcher` (an old-code parent mid-upgrade) but only names
  the run id. Nothing is written at PATH.
- Failed-launch stdout/stderr artifacts move to
  `~/.pm/runtime/<pm-session>/launch-artifacts/`.
- Review loop ids widen from 4 to 8 hex characters.

## Setup (cross-cutting)

1. Follow `pm/qa/instructions/tui-manual-test.md`: install pm from this
   branch's clone (`./install.sh --local` or an editable venv), set
   `PYTHONPATH` to the clone, and confirm with `pm which`.
2. Isolate all state: a scratch `HOME` (which gives a private `~/.pm`,
   `~/.claude`), a private tmux server (`TMUX_TMPDIR` or `-L` socket), and a
   throwaway git project with `pm init --backend local --no-import`. Never
   touch the host's `~/.pm`, `~/.claude/settings.json`, live tmux server or
   the live installation's `pm/transcripts`.
3. Drive Claude with fake-claude (`pm fake-claude config set ...`). Scripted
   verdict lists advance once per launch of that session type, across loops,
   so `{"review": {"verdicts": ["NEEDS_WORK","PASS","NEEDS_WORK","PASS"]}}`
   gives loop A i1/i2 and loop B i1/i2.
4. To skip the QA stage where QA is not the focus:
   `pm project set skip-qa on` (sign-off then follows the review PASS).
5. Optionally write `~/.claude/settings.json` with a known
   `cleanupPeriodDays` (e.g. 30) in the scratch HOME so retention reporting
   is checkable. Record its checksum before the test.
6. For upgrade scenarios, a second venv/worktree at `master` produces genuine
   pre-upgrade state (`pm/transcripts/...`, old breadcrumbs).

## Requirements

### R1 — Launches record their own identity; nothing is written under pm/transcripts

- **R1.1** Given a fresh project with fake Claude, when the user starts a PR
  (`pm pr start`, TUI `s`, auto-start or `pm pr auto-sequence`), then
  `pm pr sessions <pr>` lists one `impl` row with its run, a session id and
  `log[present]=` a path under `~/.claude/projects/.../<sid>.jsonl`, and
  `<project>/pm/transcripts` does not exist.
- **R1.2** Given a PR in review, when a review loop runs N iterations, then
  `pm pr sessions <pr> --phase review` lists one row per attempt with
  `loop=<8-hex>`, `i1..iN`, `attempt=`, each session distinct, each log
  present and holding that iteration's verdict.
- **R1.3** Given a PR entering sign-off, when the router launches, then a
  `signoff` row appears with `head=<sha-prefix>` matching the PR's HEAD at
  launch.
- **R1.4** Given a merge whose post-merge pull fails with a resolve window,
  when the merge window launches, then a `merge` row is recorded. When a
  merge window already exists and the user merges again, then no new
  `merge` row is recorded (existing-window fast path).
- **R1.5** Given a watcher run (`pm watcher --max-iterations N`,
  `pm watcher start <type>`, TUI watcher), when iterations complete, then the
  startup output names `pm watcher sessions <type> (run <id>)`, and
  `pm watcher sessions <type>` lists one `watcher` row per iteration with run,
  loop, iteration, session and present log.
- **R1.6** Given a QA loop with K scenarios, when the scenario workers
  launch, then K `qa` rows (iteration = scenario index, loop = QA loop id)
  appear, each with its own session and native log.
- **R1.7** Given an old-code parent passes `--transcript <dir>/<run>/x.jsonl`
  to a new-code child, when the child launches, then nothing exists at that
  path (no file, no symlink, no new directory) and the recorded row's run is
  `<run>` (`auto-sequence` for `.../auto-sequence/<pr>/x.jsonl`).

### R2 — Collectors read the exact session

- **R2.1** Given a review loop whose fresh restart (after a sign-off REVIEW
  return) begins again at iteration 1, when the new loop's iteration 1
  emits NEEDS_WORK, then the loop records NEEDS_WORK for that iteration (not
  the old loop's PASS) and proceeds to iteration 2.
- **R2.2** Given the CLI auto-sequence after NEEDS_WORK or a sign-off return,
  when the next tick runs, then review numbering continues after the highest
  recorded iteration of run `auto-sequence` and the verdict read is that
  iteration's own.
- **R2.3** Given a sign-off run bounced by SIGNOFF_REVIEW / SIGNOFF_IMPL /
  SIGNOFF_REQA, when the PR re-enters sign-off, then a fresh router session is
  launched (the earlier verdict is not replayed), the earlier session is
  listed as `retired`, and both logs remain present.
- **R2.4** Given an impl pane launched by another driver (CLI auto-sequence)
  for a PR the TUI also tracks, when that pane goes idle, then the TUI does
  not advance the PR on it (S79 guard), and vice versa.
- **R2.5** Given a review that paused at INPUT_REQUIRED, when the same
  session later appends an answer turn (human follow-up in the existing
  pane), then the loop reads that appended verdict from the same session's
  log.

### R3 — No copy/freeze/archive

- **R3.1** Given a loop/driver completes, is disabled, or the TUI quits,
  when the user inspects native logs and the project dir, then no symlinks
  or copies were made; native logs remain byte-identical to what the
  session wrote; later appends to a native log are visible to the next
  reader.
- **R3.2 (bug #241)** Given loop B (fresh, iteration 1) is live and obsolete
  loop A's completion fires late, when B's session appends NEEDS_WORK, then
  B sees NEEDS_WORK and B's native log is unchanged by A's completion. The
  diff's reproduction test
  `tests/test_native_session_lifecycle.py::test_obsolete_loop_completion_cannot_freeze_or_retarget_newer_log`
  passes on the branch. The captured `repro.py` reports the bug on master
  (`--expect bug`) and fixed on the branch (`--expect fixed`).

### R4 — Missing logs reported accurately

- **R4.1** Given a recorded session whose native log was deleted (simulating
  Claude retention pruning), when the user runs `pm pr sessions`, then that
  row shows `log[missing]` and `--json` shows `"log_state": "missing"`. Other
  rows are unaffected.
- **R4.2** Given a review attempt whose pane dies before writing any log,
  when the loop gives up on it, then the reported reason says the pane
  disappeared and the session's native log is missing at `<path>`, citing
  `cleanupPeriodDays=<configured>` (or "Claude's default cleanupPeriodDays"
  when unset), and that pm keeps no copy and won't substitute another
  session. No verdict is fabricated.
- **R4.3** Given `CLAUDE_CONFIG_DIR` points at a dir with a different
  `cleanupPeriodDays`, when a missing-log message is produced, then it cites
  that dir's value, not `~/.claude`'s. Neither settings file is modified.

### R5 — Safe upgrade

- **R5.1** Given a project with a pre-upgrade `pm/transcripts` tree created
  by master pm (auto-sequence review iterations, a run-dir `signoff-<pr>.jsonl`
  + `.head`, an `impl-<pr>.jsonl` link), when the branch pm continues
  driving the PR, then the legacy sessions are adopted once (rows marked
  `adopted from <legacy path>`), numbering continues after the legacy
  iteration, and the whole legacy tree is unchanged (same file list, link
  targets, contents, mtimes). No new entries are created under it.
- **R5.2** Given a legacy frozen copy whose native log is gone, when it is
  adopted, then the copy itself is listed as the log (only remaining
  evidence) and stays in place.
- **R5.3** Given a TUI review loop in flight under master (breadcrumb with
  `_transcript_dir`), when the TUI restarts under the branch code, then the
  loop resumes with the same loop id and iteration, adopts the in-flight
  session instead of launching a duplicate review window, and collects its
  verdict.

## Edge cases

- **E1** Given `pm pr sessions` on a PR with no launches, or on an unknown
  id, when run, then it prints `No recorded sessions for <id>.` and exits 0.
  `--json` prints `[]`.
- **E2** Given a torn/garbled line in a ledger (crash mid-write), when sessions
  are listed or a collector reads, then other rows still appear and the next
  append starts on a fresh line.
- **E3** Given two PRs with the same run and iteration numbers, when both
  loops run concurrently, then each PR's sessions list holds only its own rows
  and each loop's verdicts come from its own sessions.
- **E4** Given a QA loop launching several scenario workers at once (parallel
  appends to one PR ledger), when they all launch, then every scenario has
  exactly one well-formed `qa` row. No line is interleaved or lost.
- **E5** Given TUI restart while a sign-off router runs under the old
  auto-start run, when auto-start is re-armed, then the live router's session
  is adopted into the new run (listed `adopted from run autostart-…`, old
  record retired) and its verdict is recorded. A `manual-*` or
  `auto-sequence` run's router is never adopted.
- **E6** Given a review launch that fails (e.g. container mode enabled with
  no usable container runtime), when the loop retries/gives up, then failure
  artifacts land under `~/.pm/runtime/<session>/launch-artifacts/`, not under
  `pm/transcripts`. Retries are bounded and the message is actionable.
- **E7** Given manual merge gate / wait_for_merge, when the PR reaches
  SIGNOFF_MERGE, then it waits for a manual merge (`g` / `pm pr merge`), and
  `pm pr merge` without a fresh sign-off still refuses.

## Pass/Fail criteria

PASS when every Then above is observed on the user surface (TUI pane
renders, CLI output, files on disk in the isolated HOME/project), and:

- `pm/transcripts` is never created in a fresh project. In an upgraded
  project it is byte-for-byte unchanged (file list + `ls -l` + sha256 of
  regular files + `readlink` of links, before vs after).
- Every collected verdict matches the fake's scripted verdict for that
  launch.
- `~/.claude/settings.json` (and `$CLAUDE_CONFIG_DIR/settings.json`) checksums
  are unchanged.
- The diff's reproduction test passes on the branch.

FAIL on any of: a verdict attributed to the wrong session/loop/PR; a hidden
verdict (loop hangs or times out while the session's log holds the verdict); a
new file/link under `pm/transcripts`; a modified/deleted legacy file; a
missing log reported as present or as a verdict; a duplicate review/sign-off
window for one iteration after restart; a ledger row lost or corrupted under
concurrency; a traceback in any CLI/TUI surface.

## Ambiguities (resolved)

1. **Human follow-up with fake Claude.** fake-claude does not answer typed
   input. Resolved: after typing a reply into the existing review pane (the
   human surface), simulate Claude's answer by appending an assistant turn
   (e.g. `PASS`) to that session's native log, at the path `pm pr sessions`
   prints, and emitting the idle hook as fake-claude does. The behaviour under
   test is that the collector re-reads the same session's log.
2. **Simulating Claude retention pruning.** Resolved: delete the native
   JSONL in the scratch HOME. That is what pruning does.
3. **Unknown PR id for `pm pr sessions`.** The code prints "No recorded
   sessions" rather than erroring. Accepted as the intended read-only
   behaviour.
4. **Where the reproduction lives.** The diff's reproduction test is
   `tests/test_native_session_lifecycle.py::test_obsolete_loop_completion_cannot_freeze_or_retarget_newer_log`.
   The standalone `repro.py` is in the PR captures
   (`$CAP/impl/pre-fix/stale-finalizer/repro.py`). If captures are not
   mounted, the test plus the user-surface lifecycle scenario suffice.
5. **Producing pre-upgrade state.** Resolved: generate it with genuine
   master-code pm (separate venv/worktree) in the same isolated HOME/project,
   then switch to the branch code. Hand-crafted legacy trees are a fallback
   only.
6. **"Do not alter the running host".** All scenarios run in isolated
   containers with scratch HOME/tmux. Nothing targets the live installation.

No unresolved ambiguities.
