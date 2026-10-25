# pr-592e4bd — QA spec: route QA refiners/workers through a host account router

Grounding: `pm/specs/pr-592e4bd/impl.md` (R1–R7), diff `master...HEAD`
(`pm_core/worker_route.py`, `pm_core/route_bridge.py`, `pm_core/providers.py`
router type, `pm_core/claude_launcher.py` launcher boundary,
`pm_core/qa_loop.py` gates / stall watch / `qa_interactive`,
`pm_core/cli/provider.py`, `pm_core/cli/model.py`, `pm_core/container.py`
env-by-name).

Scope update (2026-10-24, impl.md header, R1/R5, items 40–41): the
refiner/worker-only split stays the project default, and a PR may now
put *every* role on the route (`model: provider:<route>`) or single
roles (`session_models: {<type>: …}`). Implementation, review and
sign-off containers use the same router bridge and fail closed. RQ2/RQ6
describe the project default; RQ39–RQ41 cover the PR-level routing.

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
- **RQ35** Given an impl, review or QA pane that went idle (`[idle]`),
  When the user types a new turn into it, Then its node and picker row
  read as working again within a few seconds, and idle again at the
  turn's next `idle_prompt` (af19cfcf; impl.md §5 item 27, which also
  records the ~60 s limitation for a prompt blocked by a user hook). Given
  a `~/.claude/settings.json` with user hooks, When pm (re)installs its
  hooks at `pm session`/TUI start, Then pm's `UserPromptSubmit` entry is
  appended next to the user's `UserPromptSubmit` hooks. Every user hook
  is kept byte-identical, including commands that only mention or also
  run pm's receiver (e.g. `echo 'pm_core.hook_receiver observed' >> log`,
  `python3 <receiver> user_prompt && notify-send …`). A user command on
  pm's Notification `idle_prompt`/`permission_prompt` matchers or on
  `Stop` is refused as a conflict and left in place (review loop a183
  i1). The receiver stores no prompt text and prints nothing.
  *Which panes* (reconciled after S36): "QA pane" means a scenario
  worker pane (`sc.pane_id`, tracker key `qa:<pr>:s<N>`), the only QA
  pane the node and picker have tracked since 162442ec. Refiner, s0,
  planner, verifier and finalizer panes are not tracked by design, so a
  turn typed into one changes neither node nor picker; that is not an
  RQ35 failure. S36's "typed refiner question reads as working" Then
  tested an untracked pane and is classified out of scope here, not
  waived: the refiner's `user_prompt` record and pane isolation are
  still required. Showing refiner turns on the node is a separate
  improvement (pr-eee7483). A Stop that replaced its
  `user_prompt` between two polls (a turn answered in under the poll
  interval) also counts as a new turn (ebf919e8, S35).
  *Timing* (S38): "within a few seconds" follows the TUI's poll cadence.
  Impl panes are polled every fifth 1 s tick, so a node change follows its
  hook event by up to one 5 s poll plus render and observation overhead. S38
  measured 0.8–4.2 s over 16 transitions sampled every 0.1 s, and one return
  that fell between 4.9 and 5.4 s with 0.5 s sampling. A scenario's "≤ 5 s"
  means "by the next impl poll", not a hard deadline. A transition that is
  materially later than one poll, or never comes, still needs investigating.
- **RQ36** Given two projects whose TUIs share one `~/.pm` (runtime
  mirror `~/.pm/runtime/<pr>.json`, QA run dirs `~/.pm/workdirs/qa`),
  When one project's TUI mounts, restarts or runs its resume scan, Then
  it never sweeps, resumes or deletes another project's runtime entries
  or `qa_resume.json` snapshots. When a project's TUI is killed with a
  run mid-turn and restarted while the other TUI keeps running, Then its
  restart logs `Resuming QA for <pr>`, its node spins again and its
  picker row reads `[working]` (93dca6ae mount sweep; a711f411 resume
  scan, impl.md §5 item 29, S39). The scan remembers PR ids it found to
  be another project's and forgets them whenever its own project.yaml
  changes (inode, mtime or size: a `git pull`/`store.save` replacement or
  an in-place rewrite by an editor under `pm edit`). So when a PR whose
  orphaned snapshot was already seen arrives in this project later (for
  example pulled from another clone of the same project, whose TUI died
  mid-run, with the PR in status `qa`), the next scan treats it like its
  own PR: it resumes the run once, keeps adopted live workers rather than
  starting second ones, and leaves it alone while another live TUI owns
  the snapshot (7968f576, cbf9941c; review loop 5e26 i1/i2). S41 ran it
  live (impl.md §5 item 30). The adopted run is driven in the session
  that holds its windows: its workers, finalizer and any relaunch stay in
  the other clone's session, and the adopting TUI collects verdicts and
  writes the one note. The adopted PR's node shows within seconds of the
  pull. A conflicted pull does not kill the TUI. Adoption is an atomic
  claim, so two TUIs never both adopt one run.
  *Load failures* (db1eb982, review loop 2b8a i1): a project.yaml that
  cannot be loaded for any reason (conflict markers, a plan whose parent
  or hierarchy does not validate after a merge, the file briefly absent
  during a checkout or rebase) never escapes the scan. The TUI and every
  QA loop it drives keep running, the pm log has one "QA resume scan
  skipped until project.yaml loads again: …" per file state (not one
  per 5 s scan), and the orphan is adopted on the first scan after the
  file loads again.
  *Provenance, not status* (59d15fea, review loop 2b8a i2, impl.md §5
  item 30(e)): a snapshot whose `session_tag` names another pm session
  (another clone) is never deleted by this TUI's "left QA" cleanup when
  this clone has the PR at a non-`qa` status, whether that session is up
  or gone. It is left until this project.yaml changes. The clone that
  launched the run resumes it after its own TUI restart. If a pull or
  edit brings the PR here in `qa`, this TUI adopts it, driven in the
  launching session if it is still up, else in this TUI's own session.
  A snapshot from this TUI's own session (or with no tag) whose PR has
  left QA here is still dropped and never revived. Accepted cost: a
  foreign snapshot whose PR really left QA stays until its own clone
  drops it.
- **RQ37** Given a TUI driving routed QA (own runs and adopted ones),
  When project.yaml cannot be loaded (conflict markers, plans that do
  not validate, or the file absent) while a run is in any phase or
  finishes, or while the user presses a QA key, Then (QA18 planner
  decision, 2026-10-24, extends RQ36 after review c1d4 i1/i2 made every
  keep-state handler survive invalid plans and a missing file):
  - *No run is ended by the load failure.* A run in planning (its
    periodic merge guard, `qa_loop.py` ~4537, and the post-planning
    spec-gate load ~4687) or in execution keeps going and is not ended
    "QA thread crashed" / ERROR. It continues once the file loads again.
  - *No result is lost.* A run that finishes during the failure keeps
    its result. Its lifecycle transition (NEEDS_WORK → `in_review`), its
    one QA note, a `zz t` restart or self-driving review loop, and the
    `[done <VERDICT>]` picker state are applied once the file loads
    again (processing may simply wait for it). The TUI never reports
    "returning to review", "restarting QA" or "press i to sign off" for
    a step that did not take effect without saying so. The snapshot
    stays until the result is recorded, so a TUI restart in between
    still recovers it once (no second note).
  - *Keys refuse cleanly.* `t`, `z t`, `zz t` and the other QA actions
    pressed during the failure show an `Error: …` line and start nothing
    (no `qa-<pr>` window without a loop). They work normally once the
    file loads.
  - The CLI is unchanged: `pm` commands print `Error: <reason>` and exit
    1, and a missing file still reads as "no project" where it did
    before.
  Code reading (QA18 planner) for the first two points: the planning
  guards call `store.load` unguarded, so the QA thread raises.
  `_on_qa_complete` → `_transition_pr_status` / `_record_qa_note`
  only log a warning, and `poll_qa_state` then clears the snapshot, so
  the PR stays `qa` with no note, and nothing retries. That was already
  true on master for conflict markers. Before c1d4 it was a TUI exit for
  invalid plans. The scenarios decide, with a pre-existing control.
  Decided live (S45/S46, fixes e11b952a … 195889a5, a9b966ec, 54c88ad8,
  e52e8fac; impl.md items 33, 34). Clarifications from those runs:
  the "QA resume scan skipped …" line appears only when the scan has an
  untracked snapshot to look at (an orphan), and once per file state
  *per TUI process*; a run already driven in memory reports the failure
  through its completion wait ("result kept until project.yaml loads
  again: …") instead. Release to "QA complete" takes ~90 s in the
  S41–S46 harness (worker idle ~60 s + fake finalizer), so a failure
  window meant to span a completion must outlast that.
  *One note per run across restarts* (review loop 7026 i1, ba5dd6e7,
  impl.md item 33(d)): once the transition and note are written, a
  follow-up that then fails (sign-off hand-off, `zz t` restart, review
  loop start, tree reload) keeps the snapshot for its retry. A TUI
  restart in that gap recovers the run once more; the restarted TUI must
  not write a second note for it (`_record_qa_note` skips a note with
  the same verdict that ends in this run's `(workdir: …)`; pm log "QA
  note for <pr> already recorded"), and the remaining follow-up is
  applied once. Distinct runs, including consecutive `zz t` passes with
  the same verdict, each keep their own note. A TUI started on an
  unloadable file clears only its own "project.yaml cannot be loaded"
  line when the file loads: a newer message on the log line is not
  blanked. Self-driving `zz t` state is TUI memory (documented
  limitation in `_resume_incomplete_qa`), so after a restart a recovered
  `zz t` pass is processed like a plain `t` run.
- **RQ38** Given a TUI driving routed QA, When another pm process holds
  the project lock for a long time (the user has `pm edit` open, which
  holds it "until you quit") while a run finishes, a follow-up is
  pending, or a review → QA hand-off waits, Then (QA19 planner decision,
  2026-10-24, same principle as RQ37) no result is lost: the transition,
  the one note and the follow-ups are applied once after the editor
  quits, and the snapshot stays until then. The TUI stays usable while
  it waits: its tree, spinners and keys keep responding (every TUI write
  waits up to `LOCK_TIMEOUT_SECONDS` = 2 s for the lock, and those
  writes run on the TUI's poll timer, so a retry on every 1 s tick could
  keep it busy). The pm log does not repeat a lock warning on every
  tick. Code reading (QA19 planner): `_transition_pr_status`,
  `_record_qa_note`, `start_signoff` and the pending hand-off treat
  `StoreLockTimeout` like a load failure and are retried on each poll
  tick, while `_completion_waits_for_project` checks only that the file
  loads, so each tick may block for 2 s. On master the same completion
  blocked once and lost its note. The scenarios decide, with a
  pre-existing control.
  Decided live (S48, 716d6ce1 + 006d7b4d; impl.md §5 item 38(a)/(b)):
  writes retried on the poll timer make one non-blocking lock attempt
  (`store.NO_WAIT`), say "waiting for project.yaml to be unlocked …"
  once per wait and land on the first tick after the editor quits. User
  keys and the CLI keep the 2 s wait. *One-shot hand-offs* (review loop
  679d i1, 64b41a91, item 38(c)): a hand-off that nothing retries keeps
  the 2 s wait instead. That is the skip_qa review PASS → sign-off
  hand-off (`_maybe_auto_merge`). So a pm process that holds the lock
  for a moment (a `pm pr note add` from a pane, a CLI write) does not
  lose it, and a hold past 2 s is reported once as `Error: …`. The TUI
  never shows a "waits" line that promises a retry nobody makes. That
  longer hold, or an unloadable file, still loses the skip_qa hand-off.
  This is pre-existing on master and filed as pr-7cf1fe4: record it as
  an observation, not a pr-592e4bd failure. The retried callers (the QA
  completion's sign-off follow-up, the scheduler pass `advance_all`)
  stay non-blocking. The "waits" line is said once per wait, not once
  per PR, so a later hand-off of the same PR (for example after a
  sign-off REQA round) that meets a held lock says so again (679d i4).
  Once the result is recorded and only a follow-up waits for an
  unloadable file, the completion line reads "QA <V> for <pr> recorded —
  follow-up waiting for project.yaml to load: …", not "… to load to
  record it" (S49 observation, 64b41a91).

### All-role and per-role routing (2026-10-24 scope update)
- **RQ39** Given a router provider and container mode, When a PR's
  `model: provider:<route>` selects the route for every role, Then its
  implementation, review, sign-off and every QA session (planner, s0,
  refiner, worker, verifier, finalizer) reach only the router with the
  `work/` model, and none reaches the main endpoint. Each impl, review and
  sign-off container is created with the route-bridge mount at
  `/run/pm-route`, with no published ports and no network change. Its
  command runs the in-container ensure step, then plain `claude` with the
  in-container router URL and `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN`
  unset. Hooks and transcripts work as for QA workers (c1c08d83). When a
  PR instead sets `session_models` exceptions (`model: <main or other
  provider>` plus `session_models: {signoff: provider:<route>}`, or the
  reverse), Then only the named role and its children
  (`qa_*` → `qa`, `signoff` → `review`) follow the exception. Every
  other role keeps the PR model or the project default. `PM_MODEL` still
  wins over both. s0 never follows a worker exception (f1865615, 0c577dd2,
  021f2810). In a second PR of the same TUI with no override, impl, review
  and sign-off containers get no bridge mount and stay on main. Review and
  sign-off relaunches remove their old session-tagged container
  (`pm-<tag>-review-<pr>`, `pm-<tag>-signoff-<pr>`) and create a fresh one.
  An impl relaunch that finds its container running *without* the mount
  (created before the route was selected) is refused with "running
  without the route socket mount. Remedy: end the session using it,
  remove it (… rm -f …) and launch again" (3748691e, c08c7627). The
  route bridge is shared by these containers and the QA containers of
  every PR. Each PR keeps one push proxy (RQ26). Host mode: impl/review/
  sign-off and host QA planner/s0/verifier/finalizer are not gated (impl.md
  §3). They start with the router env, so a down router shows an API error
  in the pane, never a main-account fallback.
- **RQ40** Given a role routed per RQ39 whose route is unavailable
  (router down, sign-in expired, provider missing from this host's
  providers.yaml), When the role is launched from the TUI, the CLI,
  auto-start or the review loop, Then nothing is launched on the main
  account and the user sees the reason and remedy:
  - `pm pr start`, `pm pr review` and `pm pr signoff` print it on stderr
    and exit 1. No window opens, the per-PR launch lock is released, and no
    container is left (57f04ee6).
  - The remedies for these roles say to launch the session again, or to
    move it off the route by removing "the PR's 'session_models' entry or
    'model' override" or with `pm model set <type> <model> --project`
    (c08c7627, 0c577dd2). They are not QA-worded ("QA launches the
    session automatically" appears only on QA gates).
  - The TUI sign-off driver shows "Sign-off launch failed for <pr>: work
    route … Remedy: …" as plain text. Brackets in the reason are kept, and
    a `[/…]` does not blank the line (5fbbedad).
  - An auto-start `pm pr start` failure shows "Auto-start: pm pr start
    <pr> failed: <last stderr line>", forced and held. It is shown once
    per reason per PR. An explicit re-arm (`A`, a target re-add,
    `autostart all`) says it again even when the failing PR is a
    dependency of the target. Once the route is back and a start goes
    through, the PR runs routed (d76cc9d5, d361858c, 620327fa).
  - A provider that is not configured gives one line from every CLI
    launch: `Error: … ; or change the model setting that selects it ('pm
    model show' lists them, PR overrides included)`, rc 1, no traceback.
    A QA run whose planner, s0, verifier or finalizer meets it shows
    "QA stopped: … then start QA again", not "QA thread crashed"
    (2d58dea4).
  - The review loop's error (`stderr[:500]`) contains the remedy.
- **RQ41** Given a hand-edited project.yaml model setting, When the user
  runs `pm model show`, `pm model set … --project` or `pm model unset …
  --project`, or launches any role, Then:
  - A blank block (`model_config:`, `session_models:` or
    `session_effort:` with every entry commented out) reads as empty.
    Launches use the defaults, `show` resolves every type, and `set` and
    `unset` fill or edit the block (05bfd6c5).
  - A blank or non-string entry, at project level
    (`model_config.session_models.signoff:` with no value) or PR level
    (`session_models: {signoff: }`), counts as absent. The parent type,
    then the PR model or global setting, applies. A blank effort level
    counts as absent too. `pm model show` reports each one under
    "Problems in project.yaml model settings" (97a77383, 52ec17f3).
  - A non-mapping `model_config` or block is reported by `pm model show`:
    "Effective config not shown: model_config is malformed", with PR
    overrides and problems still listed. A non-mapping PR
    `session_models` is ignored and flagged. An unknown type such as
    `sign_off` is flagged (0c577dd2, 7a437b79).
  - Launches with a malformed (non-mapping) block still fail with an
    error. They never silently fall back.
  - `pm model show` lists PR overrides (`model`, `session_models`) and a
    Routes section for every type that resolves to a route.
  - PR Routes lines (2a6b14d4, S55; review loop 6915 i1/i2): one line per
    distinct route a PR override selects, never one per effort. The label
    is "(all types)" when every PR session type follows that route, else
    the types it covers. The watcher is never listed. When the covered
    types resolve to different efforts (the project `session_effort`, or
    the global setting, since a PR has no effort of its own), the line names
    each non-majority effort with its types and ends "<majority>
    otherwise". Every type's effort on the line equals what that type's
    launch passes as `--effort`. With `PM_EFFORT` set every effort is the
    same and the line has a single `effort=`. With `PM_MODEL` set no PR
    line is printed (3a0c32e6).
  - *Open from code reading (QA23 planner, 2026-10-25), decided by S58:*
    `pm model show` builds every Routes line without container mode
    (`worker_route.describe(res)` with no `container=`), so it prints
    `via=host` even when container mode is on. Impl, review, sign-off and
    QA refiner/worker sessions then reach the router through the
    container bridge, and their QA launch lines say `via=container-bridge`.
    Planner, s0, verifier, finalizer and merge run on the host. The S55
    REPORT shows a `via=host` "(all types)" line in container mode. R7 makes
    route selection visible, so `pm model show` must not name a path a
    type does not use.
    *Decided by S58 (2026-10-25):* confirmed live and fixed (impl.md
    item 42(l)). In container mode, container-run types say
    `via=container-bridge` and host-run types say `via=host`. A PR routed
    for every type then has two lines, one per path. Host mode keeps one
    "(all types)" line.

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
  - Delta passes 2–13 (S7–S33) are complete. They are archived verbatim
    in [qa-passes-2-13.md](qa-passes-2-13.md). Read it before you write
    the next delta pass. It names the harness each pass reused (stub
    router and main stub `stub.py` holds, the two-PR container scripts,
    the scratch TUI with the VFR cast renderer, the `⏸M` merge recipe)
    and gotchas such as `env.sh` scrubbing variables, the
    `qa-pass-count` settings file and `file://` origins for proxied
    pushes. Captures are in
    `/pm-captures/scenarios/<N>/` (REPORT.md); `pm pr note list
    pr-592e4bd` holds per-scenario harness notes.
  - Fourteenth pass (S34+), delta-only. The only product changes
    since S33 are af19cfcf, aaf15356 and b8ebe2c3: pm's `UserPromptSubmit`
    hook (receiver `user_prompt`), coexist-append and hook-level merge
    with exact-invocation ownership, and `PaneIdleTracker` clearing idle
    on `user_prompt` (RQ35, impl.md §5 item 27). Earlier evidence stands:
    S32 (RQ33) and S33 (RQ34 transcript preservation) are not rerun. The
    exception is S33's one failed Then, a typed turn into an idle impl
    pane after auto-start is turned off, which is replayed because
    af19cfcf targets it. Affected surfaces that need live checks:
    hook install at `pm session`/TUI start in scratch HOMEs (upgrade,
    coexistence, conflicts, malformed entries, concurrent installs while
    Claude panes fire hooks); node and picker state on typed turns and on
    pm-sent turns (verdict reminder, route nudge, verification follow-up)
    for impl, review, s0 and routed QA panes; and hooks inside QA
    containers, which share the bind-mounted `settings.json`, receiver and
    `~/.pm/hooks`. Use scratch HOMEs and scratch TUI sessions only. Do not
    restart the host TUI, change host models or settings, or unpause other
    QA. Each capture dir must hold `recording.cast`, `recording.mp4` and
    `manifest.md` per the recipe before a verdict is given; earlier rounds
    omitted them. Known items stay observations: pr-0ac6f7a (a plain-string
    Notification/Stop entry crashes install), pr-b2db183, pr-237d610,
    pr-1139060.
  - Fifteenth pass (S37+), delta-only. Product changes since S34 are
    41ff0d3c (a live impl pane hides a finished loop's `⟳N` badge),
    ebf919e8 (a Stop newer than an observed `idle_prompt` reads as
    working), 93dca6ae (QA node spinner without a cached workdir, queued
    launches keep the run's tracker keys, the TUI mount sweep is limited
    to its own project's PRs) and the review-loop 3992 i1 render
    refactor of those markers (no behaviour change). S35/S36 Thens on
    those commits stand (captures `/pm-captures/scenarios/35`, `/36`;
    full suite 3537 passed on 88124d1b). One open evidence gap must be
    closed live, not inferred: S35 story 6 captured the merge window's
    `user_prompt` and the picker formatter reading `[working]`, but no
    visible picker popup during that interval. The required Then is a
    visible popup frame showing the merge row `[working]` during a held
    turn (stub holds the response, not a 0.1 s answer), recorded in
    `recording.cast`/`recording.mp4`. To also see `[idle]`, use a held
    nonterminal follow-up turn while the merge window stays open, and its
    next `idle_prompt`, then a separate terminal MERGED turn. A MERGED
    reply can make pm close/archive the merge window before any
    `idle_prompt`; the row disappearing then is correct finalization,
    not a missing `[idle]`. Same scratch-only limits as the fourteenth
    pass.
  - Sixteenth pass (S40+), delta-only. Product changes since the
    fifteenth pass: a711f411 and 7968f576. A TUI's restart-resume scan
    skips QA snapshots of PRs outside its own project and caches their ids
    until project.yaml changes (RQ36; impl.md §5 item 29).
    S39 verified it live, pre-fix and post-fix, in a scratch HOME with two
    projects (`/pm-captures/scenarios/39`, REPORT.md).
    - Its other Thens held on ace966c7: second-PR first-run spinner,
      queued-launch keys, mount sweep, and RQ33 supersede.
    - Full suite 3538 passed on a711f411 (`suite/full-suite.log`).
    - Delta to check: kill one project's TUI with a routed run mid-turn
      while the other project's TUI keeps running. Then restart it, in
      both directions: it must log `Resuming QA` and spin again, and the
      other project's runtime files must stay byte-identical.
    - Review loop 5e26 then changed the same scan (7968f576, plus the
      test-only cbf9941c): another project's PR ids are cached until
      project.yaml changes, so all of the above must be rerun on the
      current head, not inferred from S39. New surface (RQ36): two clones
      of one project (two sessions) where a PR added and QA'd in clone B,
      whose TUI then dies mid-turn, reaches clone A by `git pull` or an
      in-place `pm edit`. Clone A must ignore the orphan until then and
      resume it on its next scan afterwards. Exactly one TUI may drive it
      when clone B restarts at the same moment.
    - Also not covered live by S39: a long downtime (dozens of 5 s scans)
      of one TUI, both TUIs killed and restarted together, and a run whose
      result was written while its TUI was down (`Recovered completed QA`
      only in its own project's TUI).
    - Harness facts:
      - Plain `t` on a PR whose `qa-<pr>` window exists only focuses that
        window, so a re-run needs `z t`.
      - A wait for a run's end must match the TUI line `QA PASS for
        <pr>`. The superseded run logs its own `QA complete … INPUT_REQUIRED`.
      - A queued launch's refiner idles about 60 s before its worker
        launches.
    Same scratch-only limits as the fourteenth pass.
  - Seventeenth pass (S42+), delta-only. S41's live evidence on
    f22e6f4c/c8ab2f4c/ec227cf0 stands (`/pm-captures/scenarios/41`,
    REPORT.md). Product changes since then, never run live: db1eb982
    (scan survives every project.yaml load failure) and 59d15fea
    (another clone's snapshot is kept when this clone's status is stale;
    `qa_loop.launched_elsewhere`, `_live_other_session`). Review 5e15 i1
    passed 59d15fea. Live checks needed, two clones of one project in
    one scratch HOME and tmux server (S41 harness):
    - The S39-between-clones loss is gone: B's run, with B's TUI dead
      and A at a stale status for dozens of scans, is resumed by B's
      restart. A pre-fix replay on 59d15fea^ must show the loss, so the
      story discriminates.
    - The same run is adopted by A after a pull while B's session is up
      (driven in B's session) and while B's whole tmux session is gone
      (driven in A's).
    - A's own stale snapshot is still dropped.
    - Each load failure kind leaves A's TUI and its own routed QA
      running.
    Open from code reading; the scenarios decide:
    - (a) After B's session is gone, A drives the run in its own session.
      That session has no `qa-<pr>` window, and `_run_qa_finalize_pane`
      finds windows by name, so an all-PASS adopted run may end
      `finalize=None` (RQ28 says it must finalize). The snapshot keeps
      B's `session_tag`, so after A's TUI dies a restarted B session
      would drive the run in `pm-B` while its relaunched panes are in
      `pm-A`. Compare with one clone whose own session is killed and
      restarted, to tell whether this is pre-existing.
    - (b) The superseded-snapshot drop still decides on liveness only
      (`live_workdirs`, `resume_owned_elsewhere`). If both clones QA the
      same PR id, A's scan can drop B's older run as superseded once B's
      TUI dies, so B's restart has nothing to resume. That is the same
      loss through another path.
    Harness: copy `/pm-captures/scenarios/41/scripts` to the new
    capture dir and change S, the ports and the output paths. Render
    recordings with the current `/workspace/pm/qa/artifacts/`
    `cli-recording.md` / `tmux-screen-recording.md` `render_cast`
    (`-vsync vfr -enc_time_base 1/100 -video_track_timescale 100`,
    last frame held, atomic `.partial` rename). Do not use S41's
    `render_cast.sh` or the production copies in `/scratch/qa-artifacts`.
    Keep holds under Claude's ~360 s request timeout, and take release
    keys from the router log. Use `git pull --no-edit` and check its
    rc. Re-select the merge-base `active_pr` before committing in a
    clone whose TUI moved it.
  - Eighteenth pass (S45+), delta-only. S42–S44 ran live and each fixed
    bugs: bb39b92e, af2278e5, e0f74e2b, deb23fea, a4a45ffa and 67ea18e8.
    All their post-fix Thens held (REPORT.md in `/pm-captures/scenarios/
    42`, `43`, `44`), including the S44 story 4 replay on the combined
    head. The full suite passed 3573 tests on 67ea18e8. Product changes
    since then were never run live: review c1d4 i1 96555732
    (`PlanValidationError` subclasses `ProjectYamlParseError`) and i2
    129cf5d2 (`ProjectYamlMissingError`). Review c1d4 i3 passed on
    37c0c8f1 with 3577 tests (`/pm-captures/review-c1d4-i3`). The
    resume scan, sync and `_load_state` sites behave as before, since
    they already caught both. What changed is how the ~40 other
    keep-state handlers behave, so RQ37 is the delta. Earlier evidence
    stands, and S42–S44 are not rerun.
    - S45 runs host mode, one clone, in a scratch TUI. Each of the three
      failure kinds hits a run in planning, a run in execution, and
      completions (plain `t` NEEDS_WORK, PASS and INPUT_REQUIRED; `zz t`
      PASS below the count and NEEDS_WORK). QA keys are pressed during
      the failure. The pre-existing control is conflict markers on
      master behaviour.
    - S46 runs two clones (S41–S44 harness). An adopted run and B's own
      run finish while A's file is unloadable, and a TUI restart happens
      during the failure (invalid plans and conflict markers at a fresh
      start; S44 covered only the missing file).
    Harness: copy `/pm-captures/scenarios/44/scripts` and change S, the
    ports and the paths. Render with `pm/qa/artifacts` from this branch
    (`/workspace/pm/qa/artifacts`), never `/scratch/qa-artifacts`.
    Planners need to be slow enough for the failure to land during
    planning: a fake planner with a delay, or real Claude on the main
    stub with a hold. Same scratch-only limits as the fourteenth pass.
  - Nineteenth pass (S47+), delta-only. S45/S46 ran live, fixed the
    RQ37 bugs and replayed every story post-fix (REPORT.md in
    `/pm-captures/scenarios/45`, `46`; full suite 3622 passed). Their
    evidence stands and is not rerun. Product delta since then:
    ba5dd6e7 (review loop 7026 i1; i2/i3 PASS, suite 3624): one QA note
    per run when a TUI restart re-processes a completion whose follow-up
    was pending, and the load-error line cleared by its arrival number.
    Neither has run live. Live checks needed, host mode, scratch TUI,
    S45/S46 harness:
    - The gap itself: transition and note written, follow-up pending,
      snapshot kept, TUI killed -9 and restarted. Only the sign-off
      hand-off waits on the project lock (`start_signoff`'s
      `locked_update`), so a helper that takes the lock the instant the
      note lands, and leaves the file unloadable before releasing it,
      reaches the gap reliably. `start_qa` / review start / tree reload
      only `store.load`, so the gap there is a sub-millisecond race:
      attempt it with a bounded budget, report attempts, and count it
      only if the pm log proves the follow-up failed after the note.
      A pre-fix control on 5de77fe7 (ba5dd6e7^) must show the second
      note, so the story discriminates.
    - Distinct runs keep their notes (consecutive `zz t` PASS passes,
      a `z t` rerun, a run resumed mid-execution, a result recorded
      while the TUI was down), on two PRs at once.
    - Two clones: an adopted run in that gap when the adopting TUI dies
      and the launching clone restarts first. The kept snapshot names
      the launching session, whose project.yaml lacks the adopter's
      note, so the run may be recorded in both clones. The scenario
      decides.
    - RQ38 (`pm edit` held open) against a pre-existing control.
    - The load-error line: a TUI restarted on an unloadable file, its
      reason changing, a newer message after the 30 s sticky window,
      then the file loading, against a pre-fix control.
    Harness: copy `/pm-captures/scenarios/45/scripts` (one clone) or
    `/46/scripts` (two clones) and change S, ports and paths. Render
    with this branch's `/workspace/pm/qa/artifacts` `render_cast` (VFR,
    `-nostdin`), stop every recorder and wait until its cast stops
    growing before rendering, and never use `/scratch/qa-artifacts`.
    Same scratch-only limits as the fourteenth pass.
  - Twentieth pass (S50+), delta-only. S47–S49 ran live, fixed
    b740e188, 13eb925b, 716d6ce1, 006d7b4d and 3a3dcc3e, and replayed
    their stories post-fix, S49 also on the combined head (REPORT.md in
    `/pm-captures/scenarios/47`, `48`, `49`). That evidence stands and is
    not rerun. Review loop 679d ended PASS in i5 on 300aa1a3 with 3647
    tests (`/pm-captures/review-679d-i1` … `-i5`, each with README.md,
    full-suite.log and mutation-checks.log). i2–i5 changed only tests,
    spec and notes. The only product delta never run live is i1 64b41a91
    (RQ38 *One-shot hand-offs*):
    - (a) the skip_qa review PASS hand-off waits up to 2 s for the lock
      again;
    - (b) the retried sign-off callers stay non-blocking;
    - (c) the "waits" set is cleared on every outcome;
    - (d) the "recorded — follow-up waiting" completion line.
    Live checks needed:
    - S50, host, one clone, scratch TUI, S47/S48 harness:
      - a skip_qa auto-start review PASS whose hand-off meets a brief
        holder (under 2 s): it goes through, with no "waits" line. Then
        a hold past 2 s: one `Error:`, no "waits" line, the TUI stalls
        once for at most ~2 s, and the loss is pr-7cf1fe4 (observation);
      - a routed QA PASS hand-off with `pm edit` open, and again after a
        sign-off REQA round of the same PR: each hand-off says it waits
        exactly once, keys stay fast and nothing stalls;
      - a hand-off after a TUI restart (recovery or the scheduler pass)
        with `pm edit` open is handed off once, with one note;
      - a pre-fix control on ca8fa055 (64b41a91^), where the brief-holder
        skip_qa hand-off says "waits" and is lost, so the story
        discriminates.
    - S51, two clones, S49 harness: the recorded-result line on the
      cross-clone gap (adopted run, note written, sign-off hand-off
      fails on the lock and leaves conflict markers) and on a
      one-clone run, against a completion that meets the markers before
      its note ("… to load to record it"). One note per run across both
      clones. The pre-fix control on ca8fa055 shows the old wording.
    Harness: copy `/pm-captures/scenarios/47/scripts` or
    `/48/scripts` (one clone) or `/49/scripts` (two clones) and change
    S, ports and paths. A lock holder is any second pm process or a
    plain `flock` on `pm/project.yaml.lock`. Measure how long it holds
    the lock and the TUI key latency (S48 `keyprobe.py`, `wchanmon.py`).
    Render with this branch's `/workspace/pm/qa/artifacts` `render_cast`
    (VFR, `ffmpeg -nostdin`, atomic `.partial` → `recording.mp4`), stop
    every recorder and wait until its cast stops growing first, and
    never use `/scratch/qa-artifacts`. Known separate limitations stay
    observations: pr-7cf1fe4 (skip_qa hand-off lost past 2 s or on an
    unloadable file), pr-0f85376 (an interrupted finalizer is not
    re-run), pr-235f465, pr-43b14d2, pr-1139060. Same scratch-only
    limits as the fourteenth pass.
    Done: S50 (fixes 4fb42e06, e60c9927, f19831c2) and S51 (PASS on
    7887d772, no code change) ran live, with REPORT.md in
    `/pm-captures/scenarios/50` and `51`.
  - Twenty-first pass (S52+), delta-only, for the 2026-10-24 all-role
    scope update (RQ39–RQ41). None of these product commits has run in
    live QA:
    - c1c08d83: impl/review/sign-off containers on the route.
    - 9c42bb6e: tests only.
    - Review loop 350f i1–i3: c3c39382 flush re-arm and the one-shot
      parse `Error:` held; fbcb08b3 "Auto-start: starting" waits for a
      queued flush; 25015d25 test only.
    - Review loop e0e8 i1–i14: 3748691e, c08c7627, 0c577dd2, 021f2810,
      97a77383, 2d58dea4, 57f04ee6, d76cc9d5, d361858c, 5fbbedad,
      620327fa, 7a437b79, 52ec17f3, 05bfd6c5.
    - User commits f1865615 and 32df2893.
    Review e0e8 i15 passed on 104bf8fe with no code change: full suite
    3715 passed, plus focused tests and 4 mutations
    (`/pm-captures/review-e0e8-i15`). The only live evidence so far is
    review e0e8 i1, which ran in a routed review container
    (`/pm-captures/review-e0e8-i1/live-review-container-route.txt`).
    Earlier QA evidence stands and S1–S51 are not rerun.
    - S52: container mode, two PRs, real Claude for routed roles. One PR
      is routed for all roles, one has a sign-off exception, and an
      unrouted PR runs alongside both. The impl, review, QA and sign-off
      lifecycles share one bridge, with a bridge kill in the middle.
      Includes the review and sign-off relaunch and the unmounted impl
      container refusal.
    - S53: route failures for workflow roles in container mode (TUI keys,
      CLI, auto-start, review loop, sign-off driver), plus host-mode
      ungated roles and an unconfigured provider.
    - S54: model-setting robustness and per-role resolution, checked
      through the CLI and through which endpoint each launched role
      actually reaches, including s0 with a legacy plain `qa_scenario`.
    The stub router needs canned answers for review prompts (a `PASS`
    verdict line), sign-off prompts (a SIGNOFF verdict) and impl prompts
    (`ok`). The QA route gate skips fake sessions, but `wrap_claude_cmd`
    checks the route even for a fake impl/review/sign-off command, so a
    fake can drive the failure stories while real Claude proves the
    router traffic. Harness: copy `/pm-captures/scenarios/23/scripts` or
    `/36/scripts` (container, two PRs) or `/50/scripts` (host, scratch
    TUI) and change S, the ports and the paths. Render with this branch's
    `/workspace/pm/qa/artifacts` `render_cast`, and never use
    `/scratch/qa-artifacts`. Never copy real credentials. Known items stay
    observations: pr-7cf1fe4, pr-748e708 (an impl container and QA
    containers in separate pm processes share one push proxy key),
    pr-1139060. Same scratch-only limits as the fourteenth pass.
    Done: S53 (NEEDS_WORK, fixes 66404830) and S54 (PASS) ran live
    (REPORT.md in `/pm-captures/scenarios/53`, `54`). S52 never ran:
    in run a871abafdd8bbc20 its worker window died within seconds of
    every launch (10 relaunches, INPUT_REQUIRED by infrastructure; only
    the refiner output and `/pm-captures/scenarios/52/{scenario.json,
    prompt.md,verdict.md}` exist). Keep that directory as the record of
    the failed attempt. S53/S54 do not cover S52's Thens.
  - Twenty-second pass (S55+, native run a31ac0ae57566deb):
    - S55 carries S52 forward unchanged in intent (RQ39 three-PR
      concurrent lifecycle, bridge kill, review/sign-off relaunch,
      unmounted impl container refusal and replacement). It is adapted to
      the current head and writes to `/pm-captures/scenarios/55`. Harness:
      `/pm-captures/scenarios/53/scripts` (the S52 network pattern
      already applied: router stub on 127.0.0.1, main stub on 10.0.2.100,
      `cidr=10.1.2.0/24`). Build the base image without the Chromium
      smoke step if `pm container build-base` fails there (S53 setup).
      Since 66404830/14d72926, `pm model show` Routes has one line per
      route a PR override selects ("<pr> (all types) route=…", "<pr>
      (signoff) route=…"); "(all types)" with a project session_effort
      only since 2a6b14d4 (S55).
    - S56 is the delta for review loop 0f64 i1–i6 (14d72926, ac202207,
      1dc3e618, 6bd59adf, 690a9fe1, 3a0c32e6), none run live: PR Routes
      only for the types an override decides, never the watcher; a
      non-string or empty PR `model`; PR Routes deferring to `PM_MODEL`;
      the TUI command bar and review-loop ERROR text keeping brackets.
      Host mode, S54 harness (`/pm-captures/scenarios/54/scripts`).
      Done (run a31ac0ae57566deb): S55 NEEDS_WORK, the first live run of
      S52's Thens (every story Then held; the preflight Routes Then
      failed, fixed in 2a6b14d4 and rechecked live post-fix). S56 PASS on
      3a0c32e6, before 2a6b14d4, so its W/X two-line Routes Thens record
      the superseded grouping (REPORT.md in `/pm-captures/scenarios/55`,
      `56`).
  - Twenty-third pass (S57+), delta-only, QA23 planner 2026-10-25,
    recovered native planner after an E2BIG launch failure (pr-ace66e5).
    The only product change since run a31ac0ae57566deb is 2a6b14d4 (PR
    Routes grouped by route, differing efforts named on the line). S55
    rechecked it live only for "(all types)" lines in container mode
    (`story2/model-show-after-edit.txt`). Review loop 6915 i1 (test/spec)
    and i2 (PASS, no change, 3739 tests on 86b4e94d) added only tests and
    spec. Not yet live on 2a6b14d4: S56's W/X shapes (every type but one,
    mixed efforts), more than two efforts on one route, two routes on
    one PR, an unconfigured route next to a configured one, `PM_EFFORT`
    and `PM_MODEL`, and whether each named effort is what the launch
    really uses. All earlier evidence stands. S55 is the RQ39 record and
    S52 stays the record of its own failed attempt.
    Master is 26 commits ahead (review 6915 i2 trial merge). The only
    code there is `pm_core/cli/meta.py` (pr-7f90572), with no routing
    surface, so no merge smoke is planned.
    - S57: host mode, S56 harness (`/pm-captures/scenarios/56/scripts`,
      with its review class in stub.py). The S56 shapes are replayed with
      three project efforts in play. A second router provider runs on its
      own stub port so its traffic can be told apart. Launches of two PRs
      run at the same time, `pm model show` runs while they do, and a `pm
      edit` changes an override while sessions run.
    - S58: container mode, S55 harness (`/pm-captures/scenarios/55/
      scripts`, S52 network pattern, base image without the Chromium smoke
      step if needed). It decides the `via=` open point in RQ41: compare
      `pm model show` with the QA launch lines and with where each role
      really runs.
    Same scratch-only limits as the fourteenth pass. Render with this
    branch's `/workspace/pm/qa/artifacts` `render_cast`, never
    `/scratch/qa-artifacts`. Never copy real credentials.

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

With a PR-level override (RQ39) "routed" means the role's resolved
setting selects the route. For that PR the router may then see every
role, while another PR's unrouted roles must still reach only main.

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
