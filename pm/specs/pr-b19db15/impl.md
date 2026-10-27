# Impl Spec — pr-b19db15

**Bug**: generated background-job waits can match themselves and stall completed work.

Two independent reproductions (both *improvised worker commands*, not checked-in
PM polling loops):

1. **#229 QA round 2 scenario 10** — `until ! pgrep -f "dl-agg/agg|ffmpeg -loglevel"`
   matched the waiting shell's own command line after both renderers had
   finished; the worker stalled ~8 minutes.
2. **#249 S74 / review round 3 iteration 1** — a bare `wait` blocked on a
   deliberately persistent reaper child after the finite snapshot had finished;
   separately, `until ! pgrep -f "pytest ..."` matched its own shell after the
   suite finished.

Root cause is *guidance*, not product code: the recipes prescribe synchronous
rendering but do not say how to wait safely when a worker backgrounds a job.
Workers improvise process-name polling (self-matching) or bare `wait` (blocks on
every child).

## Requirements

R1. **Reusable, safe wait helper.** Add a checked-in helper
`pm/qa/artifacts/wait-for-job.sh` that:
   - starts one command as a single background job and captures its PID
     (`$!`) — the *actual job handle*;
   - waits only on that captured PID (never bare `wait`, never
     `pgrep -f` / `pkill -f` process-name polling);
   - enforces a bounded timeout and reports expiry as failure (kills only the
     job's own process group, leaving unrelated jobs alone);
   - returns the job's real exit status;
   - preserves pipeline failure status for `-c` commands (`bash -o pipefail`);
   - treats a finished-but-unreaped (zombie) job as complete (reaped via
     `wait "$pid"`), never as live work;
   - validates the expected artifact before success: exists, regular file,
     non-empty, *fresh for this run* (not a stale leftover), plus an optional
     `--validate` command (e.g. `ffprobe`) that is itself bounded by the same
     `--timeout`, so a hanging validator fails the check instead of stalling
     the helper;
   - if the helper itself is signalled (Ctrl-C, or a supervisor killing the
     waiting shell), terminates the job's own process group — escalating to
     SIGKILL after a short grace period (`WAIT_FOR_JOB_KILL_GRACE`, default
     5s) — and reports the interruption (exit 130) — a killed wait must not
     masquerade as a job failure, nor leave a renderer running behind it;
   - emits actionable diagnostics on every failure path.

R2. **Recipe guidance.** `pm/qa/artifacts/tmux-screen-recording.md` and
`pm/qa/artifacts/cli-recording.md` must use the helper for the agg→ffmpeg
render step, with a bounded timeout, ffprobe validation of the mp4, and a short
explanation of why process-name polling and bare `wait` are wrong. A leftover
file alone must not count as a completed render.

R3. **Shared background-job guidance in prompts.** Add one shared prompt block
(`_background_jobs_block` in `pm_core/prompt_gen.py`) injected into:
   - `generate_qa_child_prompt` (QA scenario workers that produce artifacts),
   - `generate_review_prompt` (covers normal review and review loop; review/test
     execution),
   - `generate_prompt` (impl sessions that run suites).
   The block states: capture the handle, wait on that PID, bound the wait,
   check exit status, preserve pipeline status (`pipefail`), require a fresh
   artifact, and never equate killing a wait with a passing result. The QA
   child prompt also explains that recipes ship helpers beside them, so a
   worker sets `RECIPE_DIR` to the recipe's directory rather than assuming
   the repo root is the cwd.

R4. **Artifact-completion verification.** `_build_verification_prompt` in
`pm_core/qa_loop.py` must tell the verifier that presence alone is not enough:
the artifact must be fresh (produced by this run), non-empty, and valid where a
validator exists; a stale leftover or a killed wait is not a pass.

R5. **Install the helper beside recipes.** `_install_artifact_files` in
`pm_core/qa_loop.py` must copy sibling `*.sh` helpers from
`pm/qa/artifacts/` into the scenario's `qa-artifacts/` dir, so the recipe text
can refer to the helper next to the recipe it was copied with. Repo-root
invocation (`pm/qa/artifacts/wait-for-job.sh`) remains valid for impl/review
sessions.

R6. **Regression coverage.** New `tests/test_qa_artifact_wait_for_job.py`
covering at minimum:
   - completed renderer while a decoy shell contains the renderer pattern →
     helper returns 0 promptly and leaves the decoy alive (self-match bug);
   - renderer failure (non-zero exit, even with an artifact present) → failure;
   - timeout → failure, job killed, diagnostic mentions timeout;
   - stale pre-existing artifact + job that does not rewrite it → failure;
   - missing/empty artifact and failed `--validate` → failure; a hanging
     `--validate` is killed at the bound (exit 4) and a failing stage in the
     validator pipeline is not masked;
   - pipeline failure preserved (`false | true` → non-zero);
   - persistent observer child alongside a finite job → helper completes and
     leaves the observer alive (bare-`wait` deadlock);
   - unreaped zombie sibling does not stall the helper;
   - signal-killed job → failure with its status; a signalled helper → exit
     130, the job is terminated, and the diagnostic says "interrupted";
   - a job that ignores SIGTERM → the interrupted helper still exits 130
     within `KILL_GRACE` and the job's group is gone;
   - the `-- CMD [ARG...]` (non-`-c`) form runs the command and reports its
     status;
   - the shared background-job block reaches the impl, review (incl. review
     loop) and QA-child prompts, and the QA-child prompt explains `RECIPE_DIR`;
   - recipe/helper content assertions (helper referenced, `--timeout`,
     `--artifact`, `pipefail`; helper copied by `_install_artifact_files`).

R7. **Evidence.** Exercise the prescribed workflow in a real render-like
scenario and save pre-fix and post-fix captures under
`$(pm qa captures-path pr-b19db15)/impl/{pre-fix,post-fix}/`, with manifests.
Pre-fix must show the self-matching loop stalling (bounded externally) and/or a
stale artifact accepted. Post-fix must show success, renderer failure, and
timeout outcomes.

## Implicit requirements

- **No product polling loop.** There is no checked-in `pgrep` loop to fix; the
  change is guidance + a helper. The helper must not introduce a new
  process-name poll.
- **Compatibility.** The helper runs under `bash` in the QA container and in
  host sessions. It may rely on GNU coreutils (`timeout`, `stat`) — already
  present in the image; fail loudly if `timeout` is missing.
- **Process-group safety.** A timeout must not kill the calling shell, a
  deliberately persistent observer, or unrelated jobs. `timeout` (without
  `--foreground`) puts the job in its own group and signals only that group.
- **No silent success.** Every non-zero job status, timeout, stale/missing
  artifact, or failed validation must exit non-zero with a message.
- **Prompt budget.** The new block is small static text; `fit_prompt` still
  handles over-limit prompts. Do not add unbounded enumerations.
- **Recipe portability.** Recipes are copied to `<scratch>/qa-artifacts/`; the
  helper must be usable both there and from the repo root. Recipe text defines
  `RECIPE_DIR` (the directory of the recipe being read) and falls back to
  `pm/qa/artifacts`.
- **No new `claude -p` usage** (session rule).

## Ambiguities and resolutions

A1. *Where does the helper live?* → `pm/qa/artifacts/wait-for-job.sh`. The
artifacts loader only globs `*.md`, so the `.sh` is ignored by `pm qa list`;
`_install_artifact_files` copies it beside the recipes.

A2. *Which prompts get the shared block?* → QA child, review (covers review
loop), and impl. Scenario 0 (interactive) is left alone to keep the change
small; it does not produce artifact captures and is user-driven.

A3. *Do we update `web-ui-recording.md`?* → No helper adoption there: its
ffmpeg step (webm→H.264) runs synchronously in the foreground, so there is no
background wait to replace, and the task names the two recording recipes.
Incidental hardening (review loop i4):
its unbounded `until curl ...; do sleep; done` readiness poll — and the
matching `until tmux ls ...` poll in `tmux-screen-recording.md` — now carry a
deadline and an actionable failure, because an unbounded poll stalls a worker
forever when the server/session never comes up, the same stall class this PR
fixes. Asserted by `TestRecipes::test_readiness_waits_are_bounded`.

A4. *Timeout default?* → No default; `--timeout` is required. The recording
recipes use 1800 s (a long TUI encode is explicitly expected to take several
minutes).

A5. *Freshness definition?* → A pre-existing artifact must be rewritten by the
run (size+mtime signature changes); a newly created artifact must exist,
non-empty, and have mtime ≥ run start. Same-second creation is accepted.

A6. *Where do the `test_qa_loop.py` assertions live?* → In the new
`tests/test_qa_artifact_wait_for_job.py` (classes `TestRecipes`,
`TestVerifierFreshness`), so the whole feature's coverage is in one file. The
verifier's FLAGGED rule is asserted there too, not only the prose paragraph.

## Edge cases

- Job exits 0 but never touches a pre-existing artifact → stale → fail (R1/R2).
- Job exits non-zero *after* writing a valid artifact → fail (exit status wins).
- Job exits 124 on its own (rare) → only classified as timeout when elapsed ≥
  the bound; otherwise reported as job failure 124.
- Job killed by a signal → reported as failure with status.
- Helper itself signalled (TERM/INT/HUP) → the job's process group is
  terminated, the helper exits 130 and says "interrupted" — never a bogus job
  status, never an orphaned renderer. A job (or the shell running it) that
  ignores SIGTERM is SIGKILLed once `KILL_GRACE` expires, so the interrupt
  path is explicitly bounded instead of depending on `timeout`'s own
  `--kill-after`.
- `--validate` command fails → artifact invalid → fail.
- `--validate` command hangs → killed at the `--timeout` bound, reported as a
  failed validation (exit 4), never an unbounded wait (review loop i6).
- Artifact path is a directory / symlink to nothing → fail as not a regular
  file.
- A persistent observer/reaper started by the caller survives both success and
  timeout (different process group).
- A zombie child (already exited, unreaped) must not be treated as live work.
- Recipe render script: an unreadable GIF (ffprobe prints nothing) falls back
  to the even-rounding filter instead of aborting under `set -e` before
  ffmpeg — `read` carries `|| true`; asserted by
  `TestRenderScript::test_unreadable_gif_falls_back_to_even_rounding`.
- `timeout` missing → usage failure (exit 2) with an actionable message.
- `-c` with extra positional args → usage error.
- Pipe: `pytest ... | tail` under pipefail → non-zero on test failure.

## Files

| File | Change |
|---|---|
| `pm/qa/artifacts/wait-for-job.sh` | **new** helper (executable) |
| `pm/qa/artifacts/tmux-screen-recording.md` | render via helper + completion rules |
| `pm/qa/artifacts/cli-recording.md` | render via helper + completion rules |
| `pm/qa/artifacts/web-ui-recording.md` | readiness poll bounded (review loop i4) |
| `pm_core/prompt_gen.py` | `_background_jobs_block` + injection |
| `pm_core/qa_loop.py` | copy `*.sh` helpers; freshness in verifier prompt and the FLAGGED rule |
| `pm_core/docs/qa_library.md` | document helper / background-job rule |
| `tests/test_qa_artifact_wait_for_job.py` | **new** regression tests (helper + recipe + verifier) |
| `pm/specs/pr-b19db15/impl.md` | this spec |

## Verification plan

1. Pre-fix repro capture: bounded `until ! pgrep -f "<pattern>"` loop with a
   decoy shell and a finished renderer — shows it never terminates; a stale
   artifact accepted.
2. Failing tests: new test file fails on pre-fix (helper absent / behavior
   missing).
3. Implement helper + guidance.
4. Run the new tests and the related suites (`test_qa_loop.py`,
   `test_qa_instructions.py`, `test_bug_fix_flow_prompts.py`,
   `test_prompt_bounds.py`, `test_qa_artifact_web_ui_recording.py`).
5. Post-fix capture: real ffmpeg renderer through the helper — success (with
   decoy shell), failure, and timeout, with manifests.
