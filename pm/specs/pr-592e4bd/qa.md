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
  worker (pr-04dfffb). Open question for QA: when only the worker *pane*
  dies and the verifier pane is still in the window, the flag follow-up
  falls back to the window's first pane (`find_claude_pane`) and must
  not land in the verifier pane.
- **RQ25** Given a routed worker or refiner stalled on a route outage (or
  idle on an API-error turn), When its pane dies before the route answers
  again and the nudge can be sent, Then no "… recovered — resumed" or
  "… — resumed" status appears for it (the pm log says "pane … gone — not
  resumed"); the only follow-up is the usual dead-window relaunch through
  the route gate (QA5 planner fix 5432f736; review 590d i3 observation).

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
- *Config changes mid-run.* Take effect on the next QA run (impl.md §3);
  not tested as a live switch.
- *Launcher in container mode.* Containers never use the launcher (always
  `claude` + bridge).
