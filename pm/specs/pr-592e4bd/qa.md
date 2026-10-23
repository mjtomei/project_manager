# pr-592e4bd — QA spec: route QA refiners/workers through a host account router

Grounding: `pm/specs/pr-592e4bd/impl.md` (R1–R7), diff `master...HEAD`
(`pm_core/worker_route.py`, `pm_core/route_bridge.py`, `pm_core/providers.py`
router type, `pm_core/claude_launcher.py` launcher boundary,
`pm_core/qa_loop.py` gates / stall watch / `qa_interactive`,
`pm_core/cli/provider.py`, `pm_core/cli/model.py`, `pm_core/container.py`
env-by-name).

## 1. Requirements (Given / When / Then)

### Route definition and visibility
- **RQ1** Given a host with a router listening on `127.0.0.1:<port>`,
  When the user adds a provider with `pm provider add <route> --type router
  --api-base http://127.0.0.1:<port> --model work/claude-opus-5-5
  [--credentials-file F] [--launcher L] [--refresh-command C]`,
  Then it is saved in `~/.pm/providers.yaml` without a connectivity check,
  and `pm provider list` shows type=router, URL, model, launcher, the
  credentials file *path* and its expiry (never token contents).
- **RQ2** Given the router provider, When the user runs
  `pm model set qa_concretize provider:<route> --effort high --project` and
  the same for `qa_scenario`, Then `pm model show` lists a "Routes" section
  naming exactly those two session types with `route=<route>
  model=work/claude-opus-5-5 effort=high via=…`; `qa_interactive`,
  `qa_planning`, `qa_verification`, `qa_finalize`, `review`, `impl`, … are
  not in it.
- **RQ3** Given the route configured, When the user runs
  `pm provider test <route>`, Then the preflight prints OK (router
  reachable, credentials not expired, launcher executable if set); with
  `--live` it sends one harmless tools-disabled prompt and reports the
  reply, the requested model(s) (all `work/…`), the transcript path and its
  models, and the hook event (Stop); exit 0.
- **RQ3a** Given a live probe whose cwd contains characters other than
  letters/digits (e.g. a `mkdtemp` suffix ending in `_`, as in supervisor
  smoke `host-work-route-smoke-20261022T194946Z`, session
  `f87c899f-…`, where Claude wrote `-tmp-pm-route-probe-020ea4s-/`),
  When `pm provider test <route> --live` runs, Then it finds the transcript
  Claude actually wrote (all non-alphanumerics mangled to `-`) and reports
  its path and models. When the transcript or the pm hook event is
  genuinely absent, Then the result is `Live: FAILED — missing evidence:
  …` naming the expected path(s) and exit 1, never `Live: OK` with
  `Transcript: (none)`.
- **RQ4** Given container mode is available, When the user runs
  `pm provider test <route> --container [--live]`, Then a throwaway
  container is created with the bridge socket mount, the in-container
  route reports OK (127.0.0.1 in container → host socket → router), the
  live probe (if requested) reaches the router with the `work/` model, and
  the throwaway container is removed afterwards (also on failure).

### Routed QA launches (host / tmux mode)
- **RQ5** Given a project whose refiner and worker types are on the route
  and a reachable router, When the user starts QA on a PR from the TUI,
  Then each scenario's refiner and worker run real Claude pointed at the
  router (every request the router sees uses the `work/` model, including
  background/title calls), with `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN`
  absent from their environment, and the QA status line names the refiner
  and worker routes; normal hooks fire and transcripts appear in
  `~/.claude/projects/<mangled-cwd>/<session-id>.jsonl`; verdicts are
  collected as usual.
- **RQ6** Given the same project, When QA starts, Then scenario 0 (the
  interactive QA session), the planner, verifier and finalizer launch with
  plain `claude` on the main account (no `ANTHROPIC_BASE_URL` to the
  router, no `work/` model, no `env -u`), and review / impl / sign-off
  launches are likewise unchanged.
- **RQ7** Given a route with `launcher: <path>` and host (non-container)
  QA, When a worker/refiner launches, Then that executable replaces
  `claude` in the command, with the router env still prefixed (the
  launcher cannot fall back to the main account endpoint by itself).

### Routed QA launches (container mode)
- **RQ8** Given container mode (slirp4netns) and a router only on the
  host loopback, When QA starts, Then each QA container is created with
  the bridge dir bind-mounted at `/run/pm-route` (no published ports, no
  network change), the worker/refiner command first ensures the
  in-container forwarder and then runs plain `claude` against
  `http://127.0.0.1:<port>` inside the container, and the router sees the
  `work/` model; containers for unrouted runs get no such mount.

### Failure, recovery and no-fallback
- **RQ9** Given the router is down (or sign-in expired, or launcher
  missing, or provider not configured on this host), When QA reaches a
  refiner/worker initial launch, Then that launch waits with a status line
  "Scenario N refiner|worker waiting — <problem>; <remedy>", no verdict is
  recorded, nothing is launched on the main account; When the router comes
  back, Then within ~15 s the line changes to "… available — launching"
  and the session starts.
- **RQ10** Given QA waiting on the route, When the user stops QA, Then the
  loop stops promptly and the scenario carries the reason "stopped while
  waiting for the work route" (not a PASS/FAIL/INPUT_REQUIRED verdict):
  no per-scenario verdict and no `verdict.md` for it; the overall QA
  result is INPUT_REQUIRED because a scenario is unverdicted (fixed in
  0b1edfca after QA s3).
- **RQ11** Given more scenarios than the concurrency cap, When the route
  fails while scenarios are queued, Then queued scenarios stay queued
  ("Queued scenario launch deferred — …"), other running scenarios keep
  reporting verdicts, and once the route recovers the queue drains by
  itself even if no other verdict event happens.
- **RQ12** Given a running routed worker whose window dies while the route
  is down, When the loop notices, Then relaunch is deferred ("relaunch
  deferred — …") without consuming a retry; after recovery it relaunches
  with the same routed command.
- **RQ13** Given a routed worker/refiner mid-run, When the router goes away
  and the session idles without a verdict, Then the status shows
  "… stalled — <problem>; <remedy>", the usual verdict reminder is not
  sent, and when the router returns the session is nudged ("The model
  route is available again…"); the nudge is actually *submitted* (not left
  typed in the prompt box — fixed in c5d7d64f after QA s4), a new request
  reaches the router, and the session finishes with its verdict.
- **RQ14** Given a QA run in container mode was interrupted (TUI restart),
  When QA resumes, Then adopted live panes keep running, and relaunches of
  dead/queued workers are gated against the adopted container's mount; a
  container created without the mount is reported with the remedy
  "restart QA for this PR so its containers are recreated…".

### Credential hygiene
- **RQ15** Given any of the above flows, When the user inspects generated
  commands, QA logs (`pm.worker_route`, `pm.qa_loop`, `pm.container`),
  pane scrollback, `pm provider list`/`test` output and captures, Then no
  token/secret value appears (only paths, URLs, model names); container
  create passes env vars as `-e NAME` and a failed `podman create` error
  does not contain their values.

### Fixed in scope during QA (pre-existing on master or found in QA)
- **RQ16** Given container mode and a route that fails while a scenario
  is queued, When the queued launch reaches the refiner or worker route
  gate and is deferred, Then the container created for that launch is
  removed (no `pm-qa-…-sN` container left running, its push proxy gone);
  after the route recovers the scenario relaunches in a freshly created
  container whose `/workspace` mount is the new clone (53419df2).
- **RQ17** Given `qa-max-scenarios` below the scenario count, When the
  initial capped launch or a queued launch runs, Then the QA status
  dashboard keeps counting every scenario and shows the not-yet-launched
  ones as "queued", not "pending" or missing (b97c0e3d).
- **RQ18** Given a project whose root contains its own `pm_core/`
  package, When container QA starts, Then each container's push proxy
  comes up (no "did not become ready within 3s") (dbb88ea8).
- **RQ19** Given a PR with more than one QA snapshot (a run superseded by
  a fresh start, a stopped run's late write, an older orphan beside a
  newer run that completed while the TUI was down, a newer run whose
  planner produced no scenarios, a newer run with fewer scenarios than an
  older run's queued tail), When the TUI restarts and resumes incomplete
  QA, Then it resumes the newest *run* (ordered by its first scenario
  index / persisted `scenario_start`, then unfinished, then mtime), a
  completed newer run's result is processed rather than dropped, and
  superseded snapshots are cleared unless a live loop elsewhere owns them
  (60574f28, aea1fb8a, review loop acdb i1–i3).
- **RQ20** Given a routed refiner or worker whose turn ended on a Claude
  Code API error (e.g. "API Error: Connection dropped" or a 4xx/5xx from
  the router) while the router already answers again, When its idle
  notification arrives without a verdict, Then the session is resumed with
  the route nudge (submitted), the status reads "<what>: turn ended on
  \"<error>\" and work route '<route>' answers again — resumed", and it
  finishes with its verdict. Each error record is resumed at most once and
  a session at most 3 times; after that the usual idle reminder applies
  (no endless loop). An *unrouted* (main-account) worker's API error is
  never answered with a route nudge and never mentions "work route
  'None'"; it gets the usual reminder (7c401141, review 8a99 i1).
- **RQ21** Given a routed worker that used up resumes (or was stalled)
  and whose window then dies, When it is relaunched, Then the new session
  has a fresh resume budget and no later "recovered — resumed" message
  refers to the dead pane (review 8a99 i1).
- **RQ22** Given a route that failed, recovered, and fails again with the
  same problem, When a queued or initial launch is deferred the second
  time, Then the TUI shows the deferral again (not only the pm log)
  (7c401141).
- **RQ23** Given a running QA (container mode, possibly mid-snapshot
  write), When the user starts QA afresh (`z t`) or stops it, Then the
  stopped loop announces no "relaunch deferred" / "retry n/10" for the
  windows the new run kills (1b6e2c68), the old run's `qa_resume.json` is
  gone at once and is not rewritten by the stopped thread, and a TUI
  restart at any point during the new run's planning or execution resumes
  only the new run (or nothing), never the superseded one, and records no
  stale "Recovered completed QA" note naming the old workdir (ea78b9d1,
  review 8a99 i2 lock). The next run's numbering follows the launched-index
  rule in the harness notes (never-launched queued indices may be reused),
  not "above the stopped run's last planned index". The pm log line for a reused shared push proxy is
  plain text (no NUL; `grep` does not report "binary file matches")
  (c23a2021).
- **RQ24** Given a QA run with PASS verification on (routed real-Claude
  workers, verifier on main/fake), When the pm sends a message into a
  Claude pane (route nudge, verdict-format reminder, flagged-verification
  follow-up to the worker, re-verification request to the verifier), Then
  it is submitted (a new turn starts; nothing is left typed in the prompt
  box). When the target pane dies around that send, Then the QA run
  goes on and does not end in "QA thread crashed" or "verification thread
  crashed":
  a reminder to a vanished worker leads to the usual relaunch (through the
  route gate), a flag follow-up to a vanished worker window settles the
  scenario INPUT_REQUIRED ("window gone during PASS verification…"), a
  re-verify request to a vanished verifier runs the check in a fresh
  verifier pane, and a verifier that dies while re-verifying ends that
  wait (no hang, finalize runs) (887a0b18, ff2c2474). Known and filed
  separately: a verifier death mid-check counts as FLAGGED against the
  worker (pr-04dfffb). When only the worker *pane* dies and the refiner
  (host pane 0) or verifier pane is still in the window, the flag
  follow-up must not land in either: QA S15 found it typed into the
  refiner via the `find_claude_pane` first-pane fallback, and a dead
  worker whose relaunch was route-deferred taken for that refiner (never
  relaunched); fixed in 32961096. A relaunched worker must be a new
  pane in the scenario's own window, never the surviving refiner and
  never a second window of the same name (S15/S16 saw the relaunch
  re-find the old window by name and record the refiner as the
  worker; fixed in 296c08a7). The settled reason is the scenario's
  verdict reason (qa_status.json / dashboard); the pm log line is
  "Cannot send follow-up to scenario N — window gone, marking
  INPUT_REQUIRED". Resuming a snapshot written by older pm (dead worker
  saved as `pane_id: null`) still hits the fallback: pr-d1d0139.
- **RQ25** Given a routed worker or refiner stalled on a route outage (or
  idle on an API-error turn), When its pane dies before the route answers
  again and the nudge can be sent, Then no "… recovered — resumed" or
  "… — resumed" status appears for it (the pm log says "pane … gone — not
  resumed"); the only follow-up is the usual dead-window relaunch through
  the route gate (QA5 planner fix 5432f736; review 590d i3 observation).
- **RQ26** Given container-mode QA on a PR, whose scenario containers
  share one host push proxy per (session, PR), When the PR's last QA
  container is removed and a new one is created right away (a fresh start
  `z t` over a running run, a queued launch deferred at the route gate and
  relaunched after recovery, stop then start, parallel scenario creates),
  Then within a few seconds exactly one push-proxy daemon serves the PR's
  socket path: a replaced daemon exits by itself ("Push proxy socket
  removed, exiting") and never removes the newer socket; parallel creates
  log one "Push proxy subprocess started" per socket (the others "Reusing
  live shared push proxy", plain text); a `git push` of the allowed branch
  from inside every live scenario container goes through the proxy and a
  push to another branch is refused; and repeated start/stop cycles leave
  no accumulating proxy processes. A second PR's proxy is never touched
  (75649ae4, review b62f i1 8a3d3412, i2 130e8ab9).
- **RQ27** Given a QA run (host or container mode, initial or queued
  launch) whose refiner has produced its steps, When the worker pane
  cannot be split off the refiner, Then no "Launched scenario N" line is
  logged for that attempt. The scenario is never left looking like a
  running worker. If the refiner window was already closed (TUI PR
  cleanup `Y`, a fresh-start sweep, or the user closing it), the pm log
  has a plain warning "Scenario N: refiner pane %X is gone (window
  closed) — worker not launched" with no Traceback (a2ff954c). If the
  refiner pane is still alive (the split was refused, e.g. tmux "no
  space for new pane" in a window shrunk to two lines), the warning
  "Failed to split scenario pane for scenario N — closing refiner pane
  %X so the worker is relaunched" carries its traceback, whose last
  line names tmux's reason (`pm_core.tmux.TmuxCommandError: ... tmux:
  no space for new pane`, 2314f1a8), and that refiner pane is closed
  (ded27fcd). A closed refiner skips the worker route gate: no "worker
  waiting — work route …" line or TUI notice for it, even when its
  container is being removed (2314f1a8, S20). In both cases a *running* loop
  then takes the dead-worker path: "Scenario N window died — retry
  1/10", gated on the route ("relaunch deferred — …" with no retry spent
  while the route is down). The worker is relaunched in a fresh
  `qa-<pr>-sN` window (container mode: the same container, still
  running). The refiner is never polled, reminded or nudged as if it
  were the worker, and never yields a verdict for the scenario. Only
  the relaunched worker's verdict counts. Sibling scenarios launched in
  parallel, and another PR's run, are unaffected. A *stopping* loop
  (`zz t`/`z t`) relaunches nothing and announces no retry or deferral.
- **RQ28** Given an all-PASS QA run (host or container mode, routed
  workers), When it finishes, Then the finalizer runs on main Claude and
  the TUI reads "QA complete: PASS [finalize: FINALIZE_DONE]" (pm log
  "QA complete for <pr>: PASS (finalize=FINALIZE_DONE)"), whatever
  `qa-verify-pass` is set to. With verification off no verifier pane
  opens, and the pm log has no "QA finalize: skipping — PASS verdicts
  [...] have not been verified yet" (ee3d0644, found in S21). The run
  follows `qa-verify-pass` as its verdict poll read it when it started
  ("PASS verdict verification is enabled/disabled" log line). Changing
  the setting mid-run neither adds verifiers to that run nor skips its
  finalize: started off and switched on, later PASSes stay unverified
  and finalize still runs; started on and switched off, later PASSes are
  still verified before finalize (3ce6 i2, 54ff5a68). A run started
  after the change, for example another PR, uses the new value. A
  resumed run (TUI restart) reads the setting again when its poll
  restarts. If a PASS was accepted unverified before the restart and
  verification is on now, the resumed run must still finalize. It may
  verify that PASS first or trust it. It must never end with
  `finalize=None` because of that gate. Planner code reading (QA9): a
  scenario that already has a verdict is dropped from the resumed poll
  without verification, so the gate may skip finalize in this case.
  The scenario that exercises it decides.
- **RQ29** Given a QA run that is stopped (`zz t`) or superseded by a
  fresh start (`z t`) while workers are mid-turn or after the last
  verdict, When the stopped loop winds down, Then it spawns no finalizer.
  The pm log says "QA finalize: skipped for <pr> — QA was stopped" and
  has no "QA finalize: polling pane=…" from the old loop. After `z t`,
  the new run's `qa-<pr>` window holds only its own planner, and the
  "Planner pane: %X" it logs is that planner session, not a finalizer.
  A second PR's QA window and finalizer are untouched (2ff602fc, found
  in S22). Pre-existing and out of scope (impl.md §5 item 21): a stop
  that arrives *during* the finalizer poll leaves that finalizer pane in
  the stopped run's own window until the next run's window cleanup.
  Record it as an observation. Ordering (S25): `z t` does not wait for the
  old loop. The old loop sees the stop at its next poll tick, while the new
  run starts planning at once, so its "skipped … QA was stopped" line can
  come before or after the new run's "Planner pane:" line. In S25 it came
  2 s after. Assert that the line exists and that no finalizer spawns. Do
  not assert where it falls relative to the planner line. Router-log
  Thens: Claude's own startup `GET /api/hello` (no model, 404) from routed
  sessions is not a `/v1/messages` request.
- **RQ30** Given a TUI session where nothing else keeps the shared poll
  timer alive (no other active PR has a workdir, no review loop or
  watcher running), When a QA run finishes (a PR's first `t` run, a
  `zz t` self-driving run, or a run resumed after a TUI restart), Then
  the TUI processes the finish within a few seconds, not at the next
  300 s background sync: the "QA PASS for <pr> — press i to sign off" /
  "QA NEEDS_WORK … returning to review" / "QA INPUT_REQUIRED …" message
  and the lifecycle transition follow the pm "QA complete for <pr>"
  line, the run's `qa_resume.json` is removed, one QA note is recorded,
  and the popup action picker's qa row reads `[done <VERDICT>]` (the
  second processing tick, which also drops the finished loop). A
  `zz t` pass that needs another pass restarts QA at once. With two
  PRs, the first to finish is processed while the other still runs, and
  the second is processed fully after the first has gone. After every
  finished run is processed, a TUI restart resumes or recovers nothing
  and records no second note (89414241 found in S24, review 433b i1
  fb7af748).
  RQ30 clarification (S27, 2026-10-23): the "no other active PR has a
  workdir" condition only holds until a PR's first QA run starts. QA
  itself persists `prs[].workdir`: `run_qa_sync` calls
  `_ensure_workdir` (qa_loop.py ~4212) before planning, and the PR is
  then in status `qa`. On disk, every PR that has been QA'd has a workdir
  from then on. The timer, however, reads the TUI's cached `app._data`.
  It starts whenever a `_load_state` (`_update_display` →
  `ensure_animation_timer`) sees an active PR with a workdir: another
  PR's `start_qa`, a reload or a TUI restart. A persisted workdir on
  disk therefore does not show that the timer was alive. Only the cache
  at that moment decides. Live data, S27 (head 023d9cf6 vs a scratch
  tree with 89414241 and fb7af748 reverted, same flow): two PRs started
  0.6 s / 3.6 s apart, each finishing about 1 s before the TUI "QA PASS"
  line, in BOTH trees. A run resumed after a TUI restart was processed
  1 s after its "QA complete" in BOTH trees. So the two-PR and resume
  stories do not discriminate the fixes: B's `start_qa` reload caches
  A's workdir, and the restarted TUI loads the resumed PR's workdir. The
  discriminating case remains a single PR's first run with no other
  active PR workdir in the cache (S24). Whether the
  `_resume_incomplete_qa` timer start matters when the cache has no
  workdir (for example a workdir cleared during the run) was not
  exercised. Do not count these stories as coverage of that path. After
  any QA run, the "no other active PR has a workdir" Given for a later
  story is false on disk unless that PR leaves the active statuses or
  its workdir is cleared (`pm pr cleanup`).

- **RQ31** Given a QA run whose finish the TUI processes (RQ30), When
  the verdict is NEEDS_WORK (plain `t` or `zz t`), Then the PR's
  tech-tree box shows `in_review` at once, together with the "QA
  NEEDS_WORK for <pr> — returning to review" line, not at the next 300 s
  background sync (f57c500c, found in S26: 111 s live). With `zz t` the
  self-driving review loop then starts on main Claude (never the work
  route). When a `zz t` pass is PASS but below `qa-pass-count`, Then the
  log line shows "QA PASS for <pr> (N/M consecutive) — restarting QA"
  for about `CONFIRM_HOLD_SECONDS` (3 s) before start_qa's own messages
  replace it (991addf9), also while another PR's sticky line (for
  example a review loop "INPUT_REQUIRED … interact with Claude in the
  review pane", sticky 30 s) is showing (0697e450, review 1298 i1). Two
  held lines arriving together (two PRs' passes finishing in the same
  tick) are each shown in turn, not one replacing the other. Every
  message, shown or deferred, is in the `L` command log. The final pass
  (N = M) reads "… press i to sign off" with no restart.

- **RQ32** Given a PR in `qa` whose node also carries review-loop or
  merge state from this TUI process, When its QA panes are active (a
  scenario mid-turn) or waiting (a QA pane on a permission prompt), Then
  the node shows the live QA marker (spinner / `⏸`), not a *finished*
  review loop's badge (`⟳N✓`, `⟳N⏸`, …) (9cc2fb6b, found in S29). A
  *running* review loop's marker (`⟳N`+spinner, `⏸N`+spinner,
  `⏹N`+spinner) still wins over QA. A merge INPUT_REQUIRED marker
  (`⏸M`+spinner) is not cleared by live QA (review 4f28 i1, 84662f7f;
  the 9cc2fb6b render-time clearing dropped it). Once QA is idle (all
  scenarios finished, e.g. after QA PASS while the PR is still `qa`) the
  finished loop's badge returns: known limitation kept on purpose
  (impl.md §5 item 24(a), cf. pr-97614ed), so record "● qa ⟳1⏸" after
  QA PASS as expected, not a failure. In `sign_off` the badge stays
  hidden (b290ebcb, unchanged). Each node shows only its own PR's state;
  a second PR's QA or loop never changes it. `_review_loops` and
  `_merge_input_required_prs` are TUI-process memory, so a TUI restart
  drops finished badges and `⏸M` (expected).

- **RQ33** Given a PR whose QA run has scenario panes mid-turn (or a
  `zz t` pass that restarts QA), When the run is replaced in the TUI (a
  fresh start `z t`, or the self-driving restart), Then the replaced
  run's scenario panes stop counting for the PR's node and picker: while
  the new run is planning the picker's qa row reads `qa [open]` with no
  `[working]`/`[idle]` badge from the old run's dead panes, and once the
  new run finishes (e.g. QA PASS) the node stops spinning within a poll
  tick or two and shows the idle state (`● qa`, or the finished loop
  badge `● qa ⟳1⏸` of RQ32 / item 24(a)), not a spinner kept until a
  TUI restart. The new run's own panes still spin while they work.
  Another PR's QA panes and markers are never dropped by this
  (94f36a18, found in S30; impl.md §5 item 26). Observation only, filed
  as pr-b2db183: qa panes already left in `~/.pm/runtime/<pr>.json` by a
  killed TUI survive a restart and show `[working]` in the next run's
  picker row until that run completes.
- **RQ34** Given auto-start on with a transcript run directory, When
  auto-start turns off (the user turns it off, removes its last target,
  or the last target completes and auto-start reports "all targets
  complete — auto-start OFF"), Then sessions that are still live keep
  being read: a merge window waiting on INPUT_REQUIRED (`⏸M`) still has
  its later MERGED detected (`⏸M` clears, "✓ Merged", PR merged), a
  running review loop still sees its iteration verdict, and an impl or
  review pane still has its idle/active state tracked. Their transcript
  files in the run directory stay links to Claude's live transcript (pm
  log "transcript: … is still read live — not finalized"); finished
  sessions, including an idle sign-off whose pane is still open, are
  archived as regular files as before. QA runs of other PRs in the same
  TUI (their routed workers, verdicts and markers) are unaffected
  (c97aaf9c, found in S31; impl.md §5 item 25). Out of scope, filed as
  pr-237d610: copies frozen by an earlier pm, and a merge window left by
  an earlier TUI process, are not repaired.

## 2. Setup

- Install pm from this PR's clone (`./install.sh --local` or venv per
  `tui-manual-test.md`), confirm `pm which` points at the clone.
- Throwaway project per `tui-manual-test.md` with one PR and a short spec;
  for container mode set `nested_podman: true` and `pm container enable`.
- **Stub router** (no real work account in QA containers — tokens must not
  be copied there): a small Python HTTP server on `127.0.0.1:<port>` that
  speaks the Anthropic Messages API (non-streaming and SSE), records each
  request's `model`, whether an auth header was present and the path, to a
  JSONL log, and returns canned text chosen from the request: a refiner
  prompt (contains `REFINED_STEPS_START`) gets
  `REFINED_STEPS_START … REFINED_STEPS_END`; a scenario-worker prompt gets
  a final line `PASS`; anything else gets `ok`. It may reject (HTTP 400)
  any model lacking the `work/` prefix to make a main-account fallback
  visible. The stub can be made to pause (to emulate long thinking gaps),
  to stop listening (router down) and to restart on the same port.
- Fake-claude config (`pm fake-claude config set`) for `qa_planning`
  (scripted `QA_PLAN` body with 2–3 scenarios), `qa_verification`,
  `qa_finalize` so the loop is deterministic, **with no entry and no `_all`
  for `qa_concretize`/`qa_scenario`** — fake sessions skip the route gate,
  so routed roles must run real `claude` against the stub router. Scenario
  0 is launched with session type `qa_scenario` for fake purposes, so it
  will be real Claude as well; that is expected (it should go to the main
  account, not the stub).
- Credentials-file fixture: a JSON file with `claudeAiOauth.expiresAt`
  (ms) far in the future, or in the past for the expiry case; never a real
  token.
- Set the concurrency cap (global setting `qa-max-scenarios`) to 1 for
  queue scenarios.
- **Lessons from the first QA run (2026-10-22):**
  - Use a scratch `HOME` (the host `~/.claude` may be bind-mounted rw) with
    `PM_HOST_HOME` unset. Never copy `~/.claude/.credentials.json` into it
    (forks the rotating refresh token and logs the real account out); give
    real Claude a dummy `apiKeyHelper` in the scratch `settings.json`
    instead (routed launches unset `ANTHROPIC_API_KEY`, so without a helper
    Claude reports "Not logged in"). pm hooks are installed by `pm session`.
  - The sandbox's `/etc/containers/containers.conf` sets `netns=host`, so
    in-container `127.0.0.1:<port>` would reach the host directly and the
    bridge would be bypassed. For container-route QA put
    `[containers] netns="slirp4netns"` in the scratch
    `~/.config/containers/containers.conf` and confirm with `podman inspect`.
  - Overlay fs reuses socket inode numbers; compare birth time, not inode,
    when checking whether the bridge socket was recreated.
  - fake-claude `qa_scenario` entries must use `{"verdicts":[...]}`, not a
    bare list.
  - Starting QA again on the same PR continues scenario numbering (4–6,
    7–9, …); marker-based holds in the stub router must target the real
    index (or match on prompt text, not number).
  - Numbering continues from the earlier runs' highest *launched* index
    (`_next_scenario_offset` counts `s-N` clone dirs), not the highest
    *planned* one. Queued scenarios that a stopped or superseded run never
    launched get no clone, so the next run may reuse their indices (impl.md
    §5 item 9: "an older run's queued tail can exceed a newer run's
    numbers — old 1-6 at cap 2, new 3-5"). Do not assert `scenario_start` >
    the previous run's last planned index. Assert `scenario_start` = the
    highest launched index of earlier runs + 1, and that the reused indices
    carry no artifacts, windows or containers from the older run (S14,
    2026-10-23: stopped run 18–21 launched only 18/19, next run started at
    20).
  - Optional: export `ANTHROPIC_BASE_URL` to a second "main" stub and a
    dummy `ANTHROPIC_API_KEY` in the user environment to make main-account
    traffic visible: unrouted roles must reach the main stub with that key,
    routed roles must reach only the router stub and never with that key.
  - `pm model set <type> <model>` without `--effort` applies the
    `medium` default; pass `--effort high` explicitly.
  - Out of scope (pr-3c7ce04): a pane idle on "Login expired · Please run
    /login" is not detected by the route stall watch (it only rechecks the
    router).
  - Second-pass handoff: prior captures live under the PR capture root
    `scenarios/1..6` (1,2,5,6 independently verified; 3/4 produced fixes
    0b1edfca/c5d7d64f, since reviewed). Reuse/adapt their fixture scripts
    (stand-in-only `apiKeyHelper`: `scenarios/5/scripts`) but write to NEW
    scenario capture paths; inspect hardcoded output paths first and never
    overwrite prior captures. Put fake-claude on the scratch HOME's PATH.
  - Clean up fixtures by the exact PIDs / argv / socket paths you started;
    broad `ps | awk` / `pkill -f` matching killed a QA executor.
  - Probe/bridge sources (worker_route.py, route_bridge.py,
    cli/provider.py, container.py) are unchanged since the real
    host + rootless-container work-account smoke with underscore cwd
    (`host-work-route-smoke-20261022T195845Z`) and still match a4cec139;
    later product changes are in qa_loop.py (0b1edfca, c5d7d64f,
    b97c0e3d, acdb i3/i4), push_proxy.py (dbb88ea8) and
    tui/qa_loop_ui.py resume selection (60574f28, aea1fb8a, acdb i1–i3).
  - Out of scope, filed: pr-8f8ae78 (worker launch after a dead refiner
    pane logs Launched but creates no pane and burns a retry), pr-09f01da
    (in-container pm shim imports a shadow project pm_core, so *faked*
    workers break in shadow projects — RQ18 checks use real/routed
    workers or a project without fake workers), pr-1139060 (-sN orphan
    sweep matching another PR's window), pr-173e11e (live probe leaves an
    empty temp dir), pr-3c7ce04 (login-expired pane).
  - Third pass (S11+), delta-only per supervisor handoff: review acdb i5
    PASS at 53419df2; QA2 S7/S8 independently verified PASS; S9/S10
    exercised every story and ended NEEDS_WORK only for their own code
    changes. Unchanged coverage kept as evidence, not rerun: RQ1–RQ4,
    RQ9/RQ10 startup-failure matrix and E1–E3/E7 (S7/S8), bridge/transport
    RQ8/E4–E6 and the real work-account host+container smoke
    (host-work-route-smoke-20261022T195845Z, sources hash-checked).
    Fresh live verification needed: RQ16 at BOTH gates (refiner gate:
    route lost between container create and refiner launch; worker gate:
    route lost after the refiner replies), RQ19 restart selection
    (queued-tail overlap, older unfinished orphan vs newer run completed
    while the TUI was down, empty-plan newer run, live-owner kept), and
    light re-observation of RQ17/RQ18 plus RQ12/RQ14 gating on adopted
    runs. Reuse driver scripts from capture scenarios/9 and /10; key
    waits on the fresh run's loop id / terminal state, not on counts of
    completion lines.
  - Fourth pass (S13+), delta-only: S11/S12 held their stories and ended
    NEEDS_WORK only for their own code changes (1b6e2c68, 7c401141,
    ea78b9d1, c23a2021) plus review 8a99 i1/i2 (ea6b9e17, e47dc12d).
    Everything else stays as evidence (S7–S12 captures). Review 8a99 i3
    PASS on e47dc12d (3446 tests, independent mutation checks,
    captures review-8a99-i3). Already live post-fix and not rerun: RQ20
    routed resume incl. exact route-recovers-before-idle timing and RQ22
    repeat deferral (S11 post-fix/race, r2), RQ23 1b6e2c68/ea78b9d1
    stories (S12 story1/4). Fresh live verification only for the delta:
    RQ20 unrouted side + cap, RQ21 (ea6b9e17), RQ23 supersede-vs-write
    race and restart (e47dc12d), c23a2021 log line. Run in a scratch
    session only — never restart the production TUI or resume its held
    runs. Reuse scenarios/11 and /12 scripts after reading their
    Deviations (separate PR-id vs capture-dir variables, abort when
    selection fails; bounded fresh-run waits, no self-matching pgrep);
    render terminal video with VFR ffmpeg. To provoke an API-error turn on a healthy
    route, make the stub router answer the messages endpoint with a
    non-retryable error (HTTP 400/529 body in Anthropic error shape) or
    drop the connection for a chosen number of requests while still
    listening (preflight stays healthy); Claude's idle notification comes
    about a minute after the error turn. For the unrouted case point
    `ANTHROPIC_BASE_URL` at the "main" stub and make it fail the same way.
    TUI restart = kill -9 the pid in `~/.pm/tui-<session>.pid`, then
    `pm session </dev/null`. Out of scope, filed: pr-0f85376 (finalization
    INTERRUPTED when a completed run is recovered after a dead driver).
  - Fifth pass (S15+), delta-only: S13/S14 held their stories. The only
    later product changes are review 590d i1/i2 (887a0b18 `_send_submitted`
    for every pane message, reminder failure no longer crashes the QA
    thread; ff2c2474 verification pane races). Fresh live verification only
    for RQ24, in host and container mode. Drive the verifier with a
    fake-claude scripted sequence for `qa_verification` (e.g.
    `{"sequence": ["FLAGGED_END", "VERIFIED"]}` with a `delay` long enough
    to kill panes while it works) and keep workers routed real Claude on
    the stub router so that follow-ups go into a real prompt box. Kill
    single panes by the pane id shown in the pm log/`tmux list-panes`, not
    whole windows, unless the story says window. Set
    `qa-verdict-reminder-timeout` low for the reminder story and make the
    stub answer the worker without a verdict line.
    QA5 handoff harness lessons (S13/S14 REPORTs): use the exact TUI/pm
    log path from those reports; their env.sh clears variables, so pass
    values as positional args; never copy rotating OAuth credentials;
    scratch containers on slirp4netns; no `pgrep -f` self-matching and
    no `kill -0` completion waits on zombies; convert recordings with VFR.
    Kept as-is (do not strengthen): S14 numbering clarification 590a39ab.
    Known separately: #245 queued-startup ownership, pr-04dfffb.
    QA5 clarifications (supervisor, before S15/S16 refinement):
    (1) `podman inspect` Config.Env of a QA container legitimately holds
    the values passed by name (`-e NAME`, values via the runtime process
    env) -- that is the intended delivery (RQ15, S14 evidence). The
    no-secret check covers generated argv/commands, pm logs, pane output
    and captures; if container env is inspected, record a count only,
    never require absence and never copy values into captures.
    (2) Dead-window container cleanup with two PRs running the same `-sN`
    indices can hit the known orphan-sweep collision pr-1139060 (#241).
    A lingering dead-window container, or a sweep that touches the other
    PR's same-`sN` container, is attributed to pr-1139060 and recorded as
    an observation, not a new pr-592e4bd requirement. Pane-loss and
    recovery checks (no crash or hang, INPUT_REQUIRED or a relaunch
    through the route gate, no misdirected message, no false "resumed")
    stay as required.
  - Sixth pass (S17+), delta-only: S15/S16 held their stories and ended
    NEEDS_WORK only for their own code changes (32961096, 296c08a7,
    75649ae4), all reviewed sound in review b62f i1. The only product
    changes since are push_proxy.py (b62f i1 8a3d3412 stop lock, i2
    130e8ab9 daemon socket ownership); probe/bridge/launcher sources and
    qa_loop.py logic are unchanged. Fresh live verification only for
    RQ26, in container mode (host mode has no push proxy). Keep routed
    workers real Claude on the stub router so the route gate is real
    (RQ16 deferral path); push checks may be run by the tester from
    inside a scenario container (`git push` of the PR branch and of a
    disallowed branch), as a worker would. Count proxy daemons by the
    exact socket path in their argv (`ps -o pid,lstart,args`), never by
    `pgrep -f` patterns that match the shell running the check; compare
    socket birth time, not inode (overlay fs). Out of scope, filed:
    pr-748e708 (impl/review containers from a separate `pm pr start`
    process share the QA proxy key, and per-process refs mean QA teardown
    can stop a proxy an impl container still uses): record as an
    observation only.
  - Seventh pass (S19+), delta-only: S17/S18 held their RQ26 stories.
    The only product changes since are qa_loop.py `_split_worker_pane`
    (a2ff954c from S17, review ab29 i2 ded27fcd). Fresh live
    verification is needed only for RQ27, in host and container mode.
    Initial and queued launches use the same code path. Keep refiners
    and workers routed real Claude on the stub router, so the refiner
    can be held at the stub (control file) until the split moment.
    - To make tmux refuse the split while the refiner is alive, run
      `tmux resize-window -t <pm session>:qa-<pr>-sN -y 2` on the held
      refiner's window (this sets that window's window-size to manual
      only), then release the refiner. Checked on tmux 3.4: a 2-line
      window gives "no space for new pane", rc 1. The relaunch opens
      a new window at normal size.
    - The closed-window case is the user (or `Y`) closing the
      `qa-<pr>-sN` window while its refiner is held. The refiner then
      reports a pane death, the planner draft steps are used, and the
      split hits a gone pane.
    - Retry backoff is `_SCENARIO_RETRY_BASE * 2**n`. Key waits on the
      log lines, not on fixed sleeps.
    - Reuse the S15/S16/S17 harness scripts (stub.py, stubctl.sh,
      env.sh, seed_home.sh). Write to new capture dirs.
    - pr-8f8ae78 covers this same path. a2ff954c fixes its false
      "Launched" line. Still open there, and by design here: the
      retry the relaunch spends and the blocking backoff sleep. Record
      "retry 1/10" as expected, not a failure.
    - Out of scope, already filed: pr-1139060, pr-748e708.
  - Eighth pass (S21+), final acceptance on the current head. S19 (host)
    and S20 (container) held RQ27. S20's only code change 2314f1a8
    (TmuxCommandError naming tmux's stderr for every failing tmux
    command run with check; closed refiner skips the worker route gate)
    was replayed live post-fix in both modes (S19 replay on d9338561, S20
    post-fix) and reviewed in 6c6f i1. Probe, bridge, launcher, provider
    and container sources are unchanged since a4cec139, the commit the
    real work-account host and container smoke ran on. qa_loop.py,
    push_proxy.py and TUI resume have had about 26 fixes since the S7/S8
    core matrix (b6cec11a). Each fix was checked live on its own, but
    never all together. This pass is therefore a consolidated end-to-end
    regression on the current head. It does not re-probe single fixes in
    isolation. Run one long host-mode run and one long two-PR
    container-mode run. Each covers, in one session: the role split (stub
    request log plus the main stub), routing visibility, transcripts and
    hooks, a startup outage with automatic recovery, a mid-run outage
    with queued, stalled and dead workers, a PASS-verification round trip
    with a flag follow-up, stop and fresh start, and a TUI restart with
    resume. Container mode adds the bridge, the push proxy and the no-secret
    checks. Reuse the S15–S20 harness (stub.py, stubctl.sh, env.sh,
    seed_home.sh, the verifier main stub from S15). Write to new capture
    dirs. Treat any Then that fails as a regression in the combined head.
    Known items stay observations: pr-1139060, pr-748e708, pr-8f8ae78
    (retry 1/10 on a failed split), pr-04dfffb, pr-d1d0139, pr-3c7ce04,
    pr-0f85376, pr-09f01da, pr-3201ea8.
  - Ninth pass (S24+), delta-only. S21–S23 held on the combined head.
    S21 and S22 ended NEEDS_WORK only for their own fixes: ee3d0644
    (finalize ran with verification off), 2ff602fc (a stopped run spawned
    no finalizer). Review 3ce6 i1 found both sound. Review 3ce6 i2
    (54ff5a68) changed the finalize gate to use the poll's
    `qa-verify-pass` reading. That last change has never run live. All
    three are in `_run_qa_finalize_pane`. Fresh live verification is
    needed only for RQ28 and RQ29, in host mode. The finalize logic is
    the same in both modes, and S23 already held container-mode finalize
    on 2ff602fc. Keep refiners and workers as routed real Claude on the
    stub router, held per (PR, scenario, role) from the control file, so
    PASS timing is controlled. Fake `qa_planning`, a `qa_verification`
    VERIFIED with a delay long enough to see the verifier pane, and
    `qa_finalize` FINALIZE_DONE. A fake finalizer is enough. The fix
    decides whether a finalizer launches, not what it does.
    `qa-verify-pass` is a global setting (`pm set qa-verify-pass on|off`),
    shared by every run in the session. Read the TUI "QA complete: …
    [finalize: …]" line and the pm "QA complete for <pr>: … (finalize=…)"
    line, not only qa_status.json. Reuse the S21/S22 harness scripts
    (stub.py, stubctl.sh, env.sh, seed_home.sh) and write to NEW capture
    dirs. S23 spec slip, kept as is: the resume log line counts every
    restored scenario ("3 scenario(s), 1 queued" for 2 live and 1
    queued). Known items stay observations: pr-1139060, pr-0f85376 (a
    finalization INTERRUPTED on a dead-driver recovery), pr-04dfffb,
    pr-8f8ae78.
  - Tenth pass (S26+), delta-only. S24 and S25 held RQ28 and RQ29 with
    no product change other than 89414241 (S24: start the TUI poll timer
    when a QA run is registered), and review 433b i1 fb7af748 (keep the
    timer until the finished run's second tick). Both are in the TUI
    poll timer only. The QA loop, routing, finalize and container code
    are unchanged, so fresh live verification is needed only for RQ30,
    in host mode (the timer does not depend on the mode). The failure
    only shows when nothing else keeps the timer alive. Use PRs that have
    never had QA (no `workdir` in project.yaml), no other PR in progress
    with a workdir, no review loop and no watcher, and check that before
    each story. A PR's first QA run itself persists its workdir (see the
    RQ30 clarification), so this holds only for the first run in a
    fresh project. Record disk state and the cached-state reload points
    separately. Measure the gap between the pm "QA complete for <pr>"
    line and the TUI message, the `qa_resume.json` removal and the
    picker `[done …]` badge. Pre-fix the gap was about 95 s (up to
    300 s). Pass is a few seconds. Keep refiners and workers routed real
    Claude on the stub router, held per (PR, scenario, role), so finish
    times are controlled. The stub needs a worker reply ending in
    NEEDS_WORK or INPUT_REQUIRED for the non-PASS stories. Fake
    `qa_planning` and `qa_finalize`. Verification can stay off. Reuse
    the S24/S25 harness scripts and write to new capture dirs. Known
    items stay observations: pr-0f85376, pr-1139060, pr-04dfffb.
    QA10 handoff (supervisor, 2026-10-23): 89414241 and fb7af748 were
    independently PASSed at 624f2112. The production root TUI still runs
    old master: restart and load the candidate only in a scratch TUI
    session (kill -9 the scratch pid in `~/.pm/tui-<session>.pid`, then
    `pm session </dev/null`). Other production QA stays held. Make no
    production setting or model changes. Recording: copy the renderer
    from the S24 scripts (`/pm-captures/scenarios/24/scripts`): ffmpeg
    `-vsync vfr` with a 1/100 time base, keeping the .cast and GIF,
    then frame-count, duration and decode checks. The S25 scripts use
    `-vsync vfr -enc_time_base 1/100 -video_track_timescale 100`. Never
    reuse an older default-CFR render line. It duplicates frames for
    hours. S24 REPORT: the first story's original .cast is missing (logs
    and screens present), later stories are recorded. Check that every
    story's .cast exists before rendering.
  - Eleventh pass (S28+), delta-only. S26/S27 held RQ30. The only
    product changes since are the S26 TUI fixes f57c500c (repaint after
    a QA NEEDS_WORK transition) and 991addf9 + 0697e450 (held and forced
    zz t "restarting QA" line), reviewed in 1298 i1/i2 (impl.md §5 item
    23). They are in `_on_qa_complete` only, so fresh live verification
    is needed only for RQ31, in host mode. Keep refiners and workers
    routed real Claude on the stub router, held per (PR, scenario,
    role), so finish times are controlled; the worker reply decides the
    verdict (pass / needs_work / input_required, as extended in S26).
    `qa-pass-count` is the file `~/.pm/settings/qa-pass-count` in the
    scratch HOME (`pm set` does not know it). A sticky line from another
    PR is easiest from a `zz d` review loop whose fake `review` session
    emits INPUT_REQUIRED. Measure what the TUI log line shows from the
    TUI pane capture and the .cast (frame times), not only from `L`,
    because the bug was a line recorded in `L` but never painted. The
    tech-tree box status is read from the TUI pane, compared with
    project.yaml. Reuse the S26 harness and write to new capture dirs.
    Scratch TUI session only; no production settings or model changes.
    Known items stay observations: pr-0f85376, pr-1139060, pr-04dfffb.
  - Twelfth pass (S30+), delta-only. S28/S29 held RQ31. The only
    product changes since are tree-node marker precedence in
    `pm_core/tui/tech_tree.py` (9cc2fb6b from S29, replayed live there
    for the masked-spinner case only; review 4f28 i1 84662f7f moved it
    into `_get_loop_marker(qa_live=)` and never ran live). Fresh live
    verification is needed only for RQ32, in host mode (rendering does
    not depend on the mode). Read markers from the TUI pane capture and
    the .cast frames (spinner frames change every tick, so assert the
    marker family, not one glyph). A finished loop: `zz d` on an
    in_review PR with a fake `review` session (use `idle_once_after`,
    impl.md §5 item 24(b)), then `z d`. A running loop: start QA with
    `t` while that loop is still running (start_qa does not refuse it).
    QA `waiting`: workers run without the session's
    dangerously-skip-permissions file and the stub router answers a
    worker turn with a Bash `tool_use`, so real Claude shows a
    permission prompt; if that cannot be produced, record it and keep
    the active-state Thens. `⏸M` needs a merge window INPUT_REQUIRED
    (`merge-<id>` window, transcript `merge-<pr>.jsonl`) on an in_review
    or sign_off PR, discovered by the TUI, before QA starts on that PR;
    reach it through `pm pr merge` with a main-checkout update that
    needs input. If no user flow reaches it, say so in the REPORT and
    rely on `test_merge_input_marker_survives_live_qa`; do not inject
    TUI state. Reuse the S28/S29 harness and write to new capture dirs.
    Scratch TUI session only; no production settings or model changes.
    Known items stay observations: pr-97614ed, pr-89296d3 note-18c906b
    (Ctrl+C in a review pane never ends an INPUT_REQUIRED wait; use
    `z d`), pr-0f85376, pr-1139060.
  - Thirteenth pass (S32+), delta-only. S30/S31 held RQ32 and ended
    NEEDS_WORK only for their own fixes: 94f36a18 (`poll_qa_state` drops
    a replaced run's `qa:<pr>:s*` tracker keys; RQ33) and c97aaf9c
    (`_finalize_all_transcripts` keeps transcripts a reader still polls
    when auto-start turns off; RQ34). Review 03a7 i1 found both sound;
    c3d3f978 is test-only. Each fix was replayed live only by the
    scenario that found it, so fresh live verification is needed only
    for RQ33 and RQ34, in host mode (neither depends on the mode). Keep
    refiners and workers routed real Claude on the stub router, held per
    (PR, scenario, role) from the control file, so mid-turn and finish
    times are controlled. For RQ34 the `⏸M` path follows the S31 recipe
    (vanilla project with a `file://` origin, auto-start target, fake
    review/QA PASS and a sign-off that merges, the main checkout diverged
    by an unpushed commit so the fast-forward fails and the `merge-<id>`
    window opens with its transcript; the merge prompt is real Claude on
    the main stub, answering INPUT_REQUIRED first and MERGED after the
    user replies). Auto-start is turned off before the MERGED reply.
    Check transcript files in the auto-start run directory with
    `ls -l`/`stat` (symlink vs regular file) before and after the turn
    off. Read markers and log lines from the TUI pane capture and the
    .cast, and from `L`/pm logs. Reuse the S30/S31 harness and write to
    new capture dirs. Scratch TUI session only; no production settings or
    model changes. Known items stay observations: pr-b2db183, pr-237d610,
    pr-97614ed, pr-89296d3 note-18c906b, pr-0f85376, pr-1139060.

## 3. Edge cases

- **E1** Given `--type router` with `--api-key`, When adding, Then refused
  with "A router holds its own credentials…"; without `--model`, refused.
- **E2** Given `qa_scenario` set to `provider:nosuch` (not in
  providers.yaml), When QA launches a worker or the user runs
  `pm provider test nosuch`, Then it is refused with a "not configured"
  problem and the remedy names configuring the provider or moving both
  routed types back to a model — never a silent launch on built-in claude.
- **E3** Given credentials `expiresAt` within 2 min and a
  `refresh_command` that extends it, When preflight runs, Then refresh runs
  once and launch proceeds; if refresh doesn't help, the expiry problem and
  sign-in remedy are shown; refresh isn't retried within 5 min.
- **E4** Given a stub that pauses >10 s mid-stream, When a container worker
  streams through the bridge, Then the response completes (no EOF at the
  connect timeout).
- **E5** Given a project directory (cwd / `/workspace`) containing its own
  `pm_core` package, When the bridge starts on host or ensure runs in the
  container, Then the bridge still works (runs the file isolated).
- **E6** Given the host bridge process killed while containers run, When
  the next routed launch/check happens, Then the bridge restarts at the
  same socket path and existing containers reach it through their mount.
- **E7** Given the bridge dir replaced by a symlink (or not owned by the
  user), When preflight runs, Then it refuses (no mount to an unsafe path).
- **E8** Given a PR-level `model` override or `PM_MODEL`, When QA
  launches workers, Then the override wins consistently for initial,
  queued, retry and resumed launches (explicit user choice, no gate).
- **E9** Given only `qa_scenario` set to a plain model (legacy config, no
  `qa_interactive`), When s0 launches, Then s0 keeps that plain model; if
  `qa_scenario` is a router provider, s0 does not follow it.
- **E9a** Given a pm-managed session whose cwd contains `_` (or spaces,
  `+`, …), When pm computes its transcript path (hook pollers, s0/planner
  transcript symlinks, live probe), Then it matches the directory real
  Claude writes (`-` for every non-alphanumeric character).
- **E10** Given `ANTHROPIC_API_KEY` exported in the user's environment,
  When a routed session starts, Then the key is not visible to that
  claude process, but unrouted sessions keep it.

## 4. Pass / fail criteria

Pass: every Then above observed on the user surface (CLI output, TUI
status line / pane, stub-router request log, transcripts, hook output,
`podman inspect`, pm logs). In particular: the stub sees only `work/`
models and only from refiner/worker sessions; s0/planner/verifier/finalizer
never hit the stub; route failures never produce a verdict or a launch on
the main endpoint, and recover automatically; no secret values in any
artifact.

Fail: any routed request reaching the main endpoint or a non-`work/`
model, any unrouted role hitting the router, a verdict recorded because of
a route outage, the verdict loop stalling for other scenarios while one
waits, a queue that never drains after recovery, a leaked throwaway
container, a token value in output/logs, or hooks/transcripts missing for
routed sessions.

## 5. Ambiguities (resolved)

- *Real work account in QA.* Not available in scenario containers (tokens
  stay on the host; supervisor already ran the real host + container smoke,
  impl.md §5). Scenarios use a stub router that mimics the `work/`-prefix
  contract; real end-to-end transport (bridge, slirp4netns, claude, hooks,
  transcripts) is still exercised.
- *How to exercise gates with fake-claude.* Fake sessions bypass the gate
  by design, so routed roles run real `claude` against the stub; other
  roles may be faked.
- *Config changes mid-run.* Route/model config takes effect on the next
  QA run (impl.md §3) and is not tested as a live switch. The one live
  switch that is tested is `qa-verify-pass` (RQ28): a running loop keeps
  the value its poll read at start.
- *Launcher in container mode.* Containers never use the launcher (always
  `claude` + bridge).
