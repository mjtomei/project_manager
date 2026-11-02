# pr-3d3b3ce — keep router env values out of `pm provider test --live` argv

Bug found at #249 (pr-592e4bd) sign-off.  Since merged #282 the code lives in
`pm_core/router_route.py` / `tests/test_router_route.py` (the old
`worker_route` names are gone).  Confirmed on master@c1fcecc5: the probe still
inlines every value.

## Current behaviour (root cause)

`router_route._probe_shell_cmd(cfg, session_id, *, container)` builds

    {prefix}env -u A -u B NAME1='value1' NAME2='value2' {exe} -p 'Reply with exactly: ok' --model ... --tools '' --output-format json --session-id <sid>

from `launch_parts()` (router env, plus `ANTHROPIC_BASE_URL` rewritten to the
in-container forwarder for containers) and `providers.launch_env()` (subagent
pin, `PM_ROUTE_BASE_URL`, unset list).  `router_route.live_probe()` then runs

* host: `subprocess.run(["bash", "-c", cmd], ...)`
* container: `subprocess.run([runtime, "exec", "-w", "/workspace", NAME, "bash", "-c", cmd], ...)`

so every value of the router's `env_vars()` — including ones pm itself
classifies as secret (`providers.is_secret_env_var`: KEY / TOKEN / SECRET /
PASSWORD / CREDENTIAL / AUTH / HEADER), e.g. `env: {ANTHROPIC_CUSTOM_HEADERS:
'x-team-token: …'}` — is in a process argv.  Process arguments are readable by
every local user (`/proc/<pid>/cmdline`, `ps`) and are recorded by execve
auditing (auditd EXECVE records, eBPF process monitors).  Exposure:

* container probe: the host-side `podman exec … bash -c '…value…'` process
  holds the value in its argv for the whole probe (up to the 180 s timeout);
  the in-container `bash -c` does too, inside the container.
* host probe: `bash -c '…'` and then `env … NAME=value …` carry it at execve
  (bash execs the single command, env then execs claude), so `ps` sees it for
  a short window and any execve audit log keeps it.

Every pane launch already avoids this (`claude_launcher.build_claude_shell_cmd`
`env_out=`; values reach the pane through `paths.write_env_file` /
`tmux._wrap_cmd_env`, the container runtime gets `-e NAME` only —
`container.build_exec_cmd`, `container._run_runtime(env=...)`).

## 1. Requirements

R1. **No env value in the probe argv.** `_probe_shell_cmd` must not interpolate
    any value of the launch environment (`launch_parts` env after
    `launch_env`) into the command string.  The string keeps only the names of
    the variables the probe unsets (`env -u NAME`), as a pane launch's does.
    It hands the values to its caller through a required `env_out` dict,
    mirroring `build_claude_shell_cmd(env_out=...)`.  Required (no default),
    so no caller can silently drop the route env (which would run the probe
    on whatever account the caller's environment carries).

R2. **Host probe transport.** `live_probe` (no `container_name`) runs
    `["bash", "-c", cmd]` with `env={**os.environ, **assign}` on
    `subprocess.run`, so claude sees exactly what it saw before: the caller's
    environment, minus the unset names (`env -u` in the command), plus the
    route's assignments.

R3. **Container probe transport.** `live_probe(container_name=...)` runs
    `[runtime, "exec", "-w", "/workspace", "-e", NAME1, "-e", NAME2, …,
    container_name, "bash", "-c", cmd]` with
    `env={**os.environ, **assign}`: the runtime reads each value from its own
    environment (podman and docker both resolve a bare `-e NAME` from the
    caller's environment), exactly the convention of `build_exec_cmd` and
    `_run_runtime(env=...)`.  The in-container command keeps its
    `python3 -I …/route_bridge.py ensure … &&` prefix and its `env -u` names.

R4. **Regression tests** in `tests/test_router_route.py`, next to the
    existing `_probe_shell_cmd` tests (`TestClassifierRoute
    .test_live_probe_cmd_*`, `TestSubagentPin.test_live_probe_cmd_is_pinned`):
    a router entry carrying a synthetic canary in a secret-classified variable
    (`ANTHROPIC_CUSTOM_HEADERS`) plus a non-secret `env` entry; for host and
    container the canary (and every other assigned value) is absent from the
    command and from the argv `live_probe` passes to `subprocess.run`, and
    present in the `env=` it passes; the container argv carries `-e NAME` for
    each assigned name and nothing else from the route.  The tests must fail
    on pre-fix code for the leak itself (canary found in argv).

R5. Existing probe tests keep their meaning: they read the probe's
    environment from `env_out` (the `Launch`/`_cmd_env`/`_sourced` helpers
    already support a command with an attached `.env`) instead of parsing
    `NAME=value` words.

## 2. Implicit requirements

I1. **Same effective environment for claude.**  Before: claude got
    `os.environ` − unset + assign.  After: bash gets `os.environ` + assign,
    `env -u` drops the unset names, claude gets the same set.  `assign` and
    `unset` are disjoint (`launch_env` filters), so no assignment is undone
    by `env -u`.  Inherited values the route overrides (a caller's own
    `ANTHROPIC_BASE_URL`, an inherited subagent pin or classifier pin from a
    routed caller) are overridden by the dict merge, as by `env NAME=value`
    before.  Inherited values the probe unsets (`ANTHROPIC_API_KEY`,
    `ANTHROPIC_AUTH_TOKEN`, routing variables the selection does not set)
    stay unset for claude.  Covered by the existing host test
    `test_live_probe_cmd_unsets_what_launches_unset` and a new end-to-end
    host test that runs the real `live_probe` with a stub claude.

I2. **Model routing unchanged.**  `--model <cfg.model>`, the alias pins
    (`ANTHROPIC_DEFAULT_*_MODEL`), the subagent pin + FORCE, the classifier
    model, `CLAUDE_CODE_DISABLE_UNKNOWN_MODEL_WINDOW_ENFORCEMENT` and
    `PM_ROUTE_BASE_URL` all still reach claude (now via env).  The probe
    passes no `--effort` before or after (it checks the route, not a role's
    effort); this PR does not add one.

I3. **No new on-disk copy.**  The probe is a direct child process, not a tmux
    pane, so `subprocess.run(env=...)` is the protected transport — no env
    file is needed.  Consequently there is nothing to clean up on a failed
    probe (timeout, runtime missing, non-zero exit): no temp file holding a
    value is ever created.

I4. **No value in errors or logs.**  `live_probe` already reports only
    stdout/stderr-derived text; `subprocess.TimeoutExpired` is caught and its
    `cmd` (now value-free anyway) is not printed; an uncaught
    `FileNotFoundError` for a missing runtime names only the executable.
    Nothing logs the probe argv.  After the fix the argv holds no values, so
    a future log line of it would not leak either.

I5. **No widened credentials or permissions.**  The host runtime process now
    carries the route's values in its environment (as a container pane's
    runtime already does) — `/proc/<pid>/environ` is readable only by the
    same uid (and root), unlike `cmdline`.  Only the assigned names are
    forwarded into the container (`-e NAME`); the rest of the host
    environment is not.  Nothing is added to `podman create`.

I6. **Fail-closed behaviour unchanged.**  `launch_parts` still raises
    `RouteSetupError` for unusable settings before anything runs;
    `check_route` preflight and the CLI flow (`_test_router`) are untouched.

## 3. Ambiguities (resolved)

A1. *Keep `env -u NAME` in the argv, or drop unset names from the subprocess
    env instead?*  Keep `env -u` (the task's stated fix, and what pane
    launches do).  In the container case it is required anyway: the exec'd
    process starts from the container's own environment, which the host
    `env=` cannot remove from.  Names are not secret.

A2. *Return a tuple vs `env_out`.*  `env_out` (required keyword), matching
    `build_claude_shell_cmd`'s established contract and the test helpers that
    already understand a command with an attached env.

A3. *Use `container._run_runtime` for the container probe?*  No: it takes an
    int timeout, inherits stdin, raises/propagates differently and logs
    stdout/stderr at ERROR on every non-zero exit (a failed probe is a normal
    diagnostic outcome).  The probe keeps its own `subprocess.run` (stdin
    closed, timeout caught) and adopts `_run_runtime`'s env convention
    (`{**os.environ, **env}` + `-e NAME`).

A4. *Docker `-u pm`.*  `build_exec_cmd` adds `-u pm` for docker; the probe
    never did.  Out of scope (not part of this leak); unchanged.

## 4. Edge cases

E1. **Empty values** (`env: {FOO: ""}`): `{**os.environ, "FOO": ""}` sets
    FOO empty; podman/docker resolve a bare `-e FOO` via LookupEnv, so an
    empty-but-set value is forwarded as empty, as it was with `FOO=''`.

E2. **No unset names** (a router with `unset_env: []` and a classifier model
    assigns every routing variable): the command then has no `env` word at
    all (pane-launch shape), `exe` runs directly.

E3. **Host launcher** (`launcher:` set): `exe` is the shlex-quoted launcher
    path; unchanged, now run with the env from the subprocess.

E4. **Values the shell itself interprets.**  Moving assignments from
    `env NAME=value` into bash's environment means bash (and, in a container,
    the `ensure` step — run as `python3 -I`, which ignores `PYTHON*`) sees
    them too, e.g. a provider `env` that sets `PATH` or `BASH_ENV`.  This is
    the same as a pane launch (its shell sources the env file before running
    the command) and providers.yaml is the user's own file; accepted.

E5. **Variable names pm cannot pass through an environment** (a key
    containing `=`, possible only by hand-editing providers.yaml):
    `subprocess` raises `ValueError("illegal environment variable name")`,
    which names no value.  Pre-existing nonsense input; pane launches do not
    handle it either.  Not handled specially.

E6. **Concurrent probes / threads**: no global state is touched
    (`os.environ` is not mutated; the merged dict is per call).

E7. **Timeout**: `subprocess.run` kills the direct child (host: bash, which
    has exec'd into env → claude; container: the host `podman exec`).  The
    CLI removes the throwaway container in its `finally`.  Unchanged.

## 5. Verification plan

* Pre-fix capture (`$CAP/impl/pre-fix/`): isolated HOME with a router entry
  holding a synthetic canary in `ANTHROPIC_CUSTOM_HEADERS`; (a) the task's
  `_probe_shell_cmd` print, (b) `live_probe` on the host and through a
  container runtime, observed from a separate process via `ps -eo args`
  (a shim holds the execve'd argv for 2 s so the observer reliably samples
  it) — canary visible.
* Failing regression test(s) on pre-fix code, passing after.
* Real transport check post-fix: `podman exec -e NAME` with the value only
  in the runtime's environment reaches the in-container process (nested
  podman 3.4.4), and the host probe's stub claude receives every assignment.
* `tests/test_router_route.py` + related suites (`test_providers*`,
  `test_container*`, `test_claude_launcher*`, CLI provider tests), then the
  full suite once after the final edit.
* Post-fix capture (`$CAP/impl/post-fix/`): same steps — canary absent from
  every argv, present only where it should be (claude's environment).
