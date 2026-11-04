# pr-3d3b3ce QA spec — `pm provider test --live` keeps router env values out of process arguments

Code under test (branch HEAD 1e6b49ac): `pm_core/router_route.py`
`_probe_shell_cmd(cfg, sid, *, container, env_out)` now returns a command that
names only the variables the probe unsets (`env -u NAME ...`, or no `env` word
at all when nothing is unset); the route's assignments go to `env_out`.
`live_probe` runs that command with `subprocess.run(..., env={**os.environ,
**assign})` and, for a container, adds `-e NAME` per assigned variable to
`podman exec` so the runtime reads the value from its own environment.
The only user surface is the CLI: `pm provider test <router> --live` (host
probe) and `pm provider test <router> --container --live` (throwaway pm
container, nested podman).  `pm provider add/edit/show` are the setup surface.
Nothing else (pane launches, `check_route`, the bridge) changed in code; the
test helper `_cmd_env` now also guards pane-launch builders against inlined
values.

Shared resources the probe touches: the process table (`/proc/<pid>/cmdline`,
world-readable — the leak surface), `~/.pm/providers.yaml` (read; edited under
`providers.yaml.lock`), the per-route host bridge dir/socket/`.lock` under
`~/.pm/route-bridge/<route>/` (container probes), the router's TCP port,
`~/.pm/hooks/<sid>.json` and `~/.claude/projects/*/<sid>.jsonl` (per session
id), throwaway containers `pm-route-test-<hex>` and `pm-route-test-*` /
`pm-route-probe-*` temp dirs, and the caller's environment (`os.environ`, read
but never mutated).

## 1. Requirements

R1. Host probe keeps values out of argv (the bug).
  Given a router provider whose `env` carries a synthetic canary in a
  secret-classified variable (`ANTHROPIC_CUSTOM_HEADERS: 'x-team-token:
  <canary>'`) and a non-secret extra (`ACME_TEAM`), a reachable router and a
  `claude` on PATH,
  When the user runs `pm provider test <router> --live`,
  Then the command prints `Preflight (host): OK`, a `Live prompt: exit=0 ...`
  line, `Models requested: <router model>`, a transcript path, a hook event and
  `Live: OK`, exits 0; and no process observed during the run (bash, env,
  claude) has the canary, `ACME_TEAM`'s value, or any `NAME=value` route
  assignment in its command line — only `env -u NAME` names.

R2. Host probe still delivers the route environment.
  Given the same setup,
  When the probe runs,
  Then the claude process receives `ANTHROPIC_BASE_URL` = the router's
  `api_base`, `ANTHROPIC_CUSTOM_HEADERS` byte-for-byte, the alias/subagent model
  pins (= router model), `CLAUDE_CODE_SUBAGENT_MODEL` + force flag,
  `CLAUDE_CODE_DISABLE_UNKNOWN_MODEL_WINDOW_ENFORCEMENT=1`,
  `PM_ROUTE_BASE_URL`, and the classifier model when configured; and the router
  sees the header on the request.

R3. Inherited/unset semantics unchanged.
  Given the user's shell exports a stray `ANTHROPIC_API_KEY`,
  `ANTHROPIC_AUTH_TOKEN`, its own `ANTHROPIC_BASE_URL`, a foreign
  `CLAUDE_CODE_SUBAGENT_MODEL`, and an unrelated variable,
  When the user runs the host live probe,
  Then claude sees no API key / auth token, sees the route's base URL and
  subagent pin (overriding the shell's), and still inherits the unrelated
  variable (PATH, HOME etc. intact) — same as before the fix.

R4. Container probe keeps values out of argv.
  Given the same provider, nested podman, and a stub/real claude that pm
  bind-mounts into the container,
  When the user runs `pm provider test <router> --container --live`,
  Then it prints `Creating throwaway container pm-route-test-...`,
  `Container route: OK (...)`, the live lines and `Live: OK`, exits 0; the
  host-side `podman exec` command line holds `-w /workspace`, one `-e NAME` per
  route variable, the container name and `bash -c '<ensure> && env -u ...
  claude -p ...'` — no values; no in-container process command line holds a
  value either.

R5. Container probe delivers the right environment, and only that.
  Given the same, plus an unrelated secret-looking variable exported only in
  the user's host shell,
  When the container probe runs,
  Then in-container claude sees `ANTHROPIC_BASE_URL` = the in-container
  forwarder URL (127.0.0.1, not the host router), the header intact, every
  route pin, and does NOT see the unrelated host-only variable; the router
  receives the header through the bridge; the throwaway container and its temp
  workdir are removed afterwards.

R6. Fail-closed and failure reporting unchanged.
  Given an unusable route (router down, missing launcher) or a probe that
  fails (claude non-zero exit, wrong model, missing transcript/hook event,
  timeout),
  When the user runs the live test,
  Then pm reports the same `Preflight: FAILED — ...` / `Live: FAILED — ...`
  messages as before and exits 1; no output line, process command line, or
  new file (outside providers.yaml) contains the canary.

R7. Regression test from the diff.
  Given the PR's `tests/test_router_route.py::TestProbeEnvTransport`,
  When run against the branch, Then it passes; When run against master's
  `pm_core/router_route.py`, Then it fails on the canary found in argv.

## 2. Setup (cross-cutting)

* Install pm from the PR clone (tui-manual-test.md Setup step 1:
  `pip install -e .` or `./install.sh --local`, `export PYTHONPATH=<clone>`,
  `pm which` shows the clone).
* Isolated `HOME` per scenario (`~/.pm`, `~/.claude` inside it) so the user's
  real providers.yaml, bridges and sessions are never touched.  For nested
  podman keep `XDG_DATA_HOME`/`XDG_CONFIG_HOME` pointing at the real user's
  podman store.
* Synthetic canary only, e.g. `CANARY-not-a-real-secret-<random>`.  Never use
  or print a real credential.
* Fake router: a small localhost HTTP server answering `POST /v1/messages`,
  logging (to a file) whether the `x-team-token` header equals the canary.
  Do not log the header value itself beyond the match result.
* Stub claude: an executable named `claude` on PATH (the container mounts the
  host's `claude` at /usr/local/bin/claude) that parses `--model` and
  `--session-id`, sends one request to `$ANTHROPIC_BASE_URL` with the header
  from `$ANTHROPIC_CUSTOM_HEADERS`, holds ~3 s so command lines can be sampled,
  writes `~/.claude/projects/<mangled cwd>/<sid>.jsonl` with
  `{"type":"assistant","message":{"model":<model>}}` and
  `~/.pm/hooks/<sid>.json` with `{"event_type":"Stop"}`, records the
  environment variables it was given (names + whether set + equality to the
  expected value — not raw secret values) to a file, and prints
  `{"result":"ok","is_error":false,"modelUsage":{<model>:{}}}`.
  The impl session's harness (captures `impl/pre-fix/provider-test-live/
  harness/`: `bin/claude`, `fake_router.py`, `observer.py`, `shim/env`) is a
  working reference.
* Observer: a separate process that samples `/proc/*/cmdline` (or
  `ps -eo pid,args`) every ~50 ms for the whole run and logs every process
  whose args contain `Reply with exactly` (the probe prompt) plus a
  `CANARY_IN_ARGV=YES/no` verdict.  Run it as a second local account when one
  is available (shows the cross-user exposure literally); otherwise the same
  user is equivalent because cmdline is mode 0444.  A short-lived `env`
  process may be missed by sampling; a PATH shim `env` that sleeps 2 s and
  execs `/usr/bin/env "$@"` makes it observable.
* Router provider config via the CLI where possible: `pm provider add acme
  --type router --api-base http://127.0.0.1:<port> --model
  work/claude-opus-5-5 --env 'ANTHROPIC_CUSTOM_HEADERS=x-team-token: <canary>'
  --env ACME_TEAM=blue` (do this before the observer starts; see A3).  Hand
  edits of providers.yaml only for shapes the CLI cannot express
  (`unset_env: []`, empty-string values, nonsense names).
* Container: `echo <image> > ~/.pm/settings/container-image` (e.g.
  `docker.io/library/python:3-slim` or the pm-dev image; it must have bash and
  python3) and a project with `nested_podman: true` when already inside a
  container.

## 3. Edge cases

E1. Values with shell metacharacters.  Given the header value contains spaces,
  `$HOME`, backticks, single and double quotes and `;`, When the host and
  container probes run, Then the router receives the literal value (no
  expansion/word-splitting) and no command line contains it.

E2. Empty-but-set value.  Given `env: {ACME_EMPTY: ""}`, When the probes
  run, Then claude sees `ACME_EMPTY` set and empty (host and container), not
  unset.

E3. Nothing to unset.  Given `unset_env: []` and a `classifier_model`
  (every routing variable assigned), When the host probe runs, Then the
  observer sees claude started directly by bash with no `env` process, the
  probe is `Live: OK`, and claude has the classifier model and header.

E4. Launcher.  Given `pm provider edit acme --launcher <recorder script>`
  (path containing a space), When the host probe runs, Then the launcher is
  run (shell-quoted path in the command line), receives the route env and the
  canary is in no command line.  Given the launcher path does not exist, Then
  the test fails at preflight with a setup problem and no probe process starts.

E5. Router down.  Given nothing listens on the port, Then `Preflight: FAILED
  — router not reachable at 127.0.0.1:<port>` (+ remedy), exit 1, the
  observer sees no probe process.

E6. Probe failure output.  Given stub claude exits 2 with stderr `upstream
  401`, Then `Live: FAILED — upstream 401`, exit 1, no canary in output.  Given
  it reports another model, Then `Live: FAILED — model mismatch: Claude
  requested <x>; expected only <model>`.  Given it writes no transcript/hook
  event, Then `Live: FAILED — missing evidence: ...`.

E7. Timeout.  Given stub claude hangs > 180 s, Then after ~180 s `Live:
  FAILED — timed out after 180s`, exit 1, no stub process left running, and the
  hung processes' command lines never held the canary.

E8. Nonsense variable name (hand edit, e.g. key `BAD=NAME`).  Then the test
  fails (non-zero) and neither output nor any command line contains that
  entry's value.  (Pre-existing nonsense input; a traceback is acceptable but
  must name no value — record which shape appears.)

E9. Concurrency.  Two routers (distinct canaries, distinct fake routers), four
  probes at once (each route host + container) plus a concurrent
  non-secret `pm provider edit`: all `Live: OK`, each router sees only its own
  canary, no command line holds either canary, two distinct throwaway
  containers both removed, exactly one host bridge process per route,
  providers.yaml still valid.

E10. Secret display adjacent check.  `pm provider show acme` lists
  `ANTHROPIC_CUSTOM_HEADERS=<redacted>` and `ACME_TEAM=blue` (unchanged).

## 4. Pass/Fail criteria

PASS: every Then above holds; the observer log for every scenario contains at
least one probe process (proves sampling worked) and zero
`CANARY_IN_ARGV=YES`; the router log shows the header matched for every
successful probe; CLI messages/exit codes match.

FAIL: any canary or route `NAME=value` in any probe-related command line
(host `bash -c`, `env`, claude, host `podman exec`, in-container `bash -c`); a
route variable missing/different in claude's environment vs. R2/R5; a
host-only variable reaching the container; a stray key/token reaching claude;
a changed failure message or exit code; a leftover container, temp dir with a
value, or orphan probe process; cross-route contamination under concurrency.
A pre-fix control run (master code) that does NOT show the leak means the
harness is blind — the scenario is then inconclusive, not a pass.

## 5. Ambiguities (resolved)

A1. Real claude and a real router need real credentials, which QA must never
  use.  Resolved: a stub `claude` on PATH (bind-mounted into the container by
  pm itself) and a fake localhost router stand in; the code under test (pm's
  command construction and transport) is exercised unchanged.

A2. "Other users can read it": the QA container may have no second account.
  Resolved: use one if available; otherwise sample as the same user and also
  record `/proc/<pid>/cmdline` mode 0444 vs `/proc/<pid>/environ` mode 0400 to
  show the value moved from world-readable to owner-only.

A3. `pm provider add/edit --env NAME=value` itself puts the value in the pm
  CLI's own argv for that command's lifetime.  That is the user typing a
  secret on a command line (also shell history), not the probe; out of this
  PR's scope.  Scenarios configure the provider before starting the observer,
  or hand-write providers.yaml.

A4. The probe timeout (180 s) has no CLI flag.  Resolved: E7 waits it out.

A5. The probe passes no `--effort` (before and after); not a regression.

A6. Docker runtime (`-u pm` difference) is out of scope; QA uses podman.

A7. Behaviour change accepted by impl (E4 in impl spec): values now live in
  the probe's bash environment too (e.g. a provider `env` setting `BASH_ENV`
  or `PATH` affects the probe shell), matching pane launches.  Not tested as a
  failure.

No [UNRESOLVED] items.
