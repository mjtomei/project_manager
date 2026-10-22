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
  waiting for the work route" (not a PASS/FAIL/INPUT_REQUIRED verdict).
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
  route is available again…") and finishes with its verdict.
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
