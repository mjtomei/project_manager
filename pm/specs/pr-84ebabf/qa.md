# QA Spec: pr-84ebabf — provider secrets must not reach logged commands or tmux pane commands

## Scope under test (user-visible surfaces this PR owns)

The bug: a provider configured in `~/.pm/providers.yaml` with an `api_key`
(literal or `${VAR}` reference) had its resolved value interpolated into the
shell command pm hands to tmux. That command string is (a) written at INFO to
`~/.pm/debug/<session-tag>.log` by `log_shell_command`, (b) kept by tmux as
`#{pane_start_command}`, and (c) stored in the pane registry
(`~/.pm/pane-registry/<session>.json`). A real Anthropic key was found in both
debug logs and a QA recording.

The fix: `build_claude_shell_cmd()` no longer interpolates provider env values.
It returns them via `env_out`, and every launch surface transports them through
the launched process's environment:

* host tmux panes: a `0600` file under `~/.pm/run/` that the pane command
  sources and deletes (`sh -c 'set -a; . file; set +a; rm -f file; <cmd>'`), a
  leading `cd '<dir>' && ` kept outside the wrapper;
* foreground launches (`pm guide`, `pm qa debug -f`, `pm qa standalone`,
  `pm meta`): `execvpe` / `Popen(env=...)`;
* container exec: `-e NAME` only (the value is read by the runtime client from
  the pane's environment);
* `launch_claude_in_tmux` (`send_keys`): the same env file, sourced by the
  typed command;
* `launch_claude`'s debug env dump now logs variable *names* only.

Surfaces a user drives:

1. `pm provider add` / `pm provider list` / `pm provider default` — provider
   configuration (`~/.pm/providers.yaml`).
2. `pm model set <session_type> provider:<name>` (global or `--project`) —
   choosing a provider for impl / review / signoff / qa_* / watcher / merge /
   guide.
3. `pm pr start`, `pm pr review`, `pm pr signoff` — host tmux windows
   (`new_window`, `new_window_get_pane`, `split_pane_at`).
4. TUI panes — discuss, watcher-review, qa-item (`tui/pane_ops.launch_pane` →
   `split_pane`, inside a `bash -c 'trap "pm _pane-exited ..." EXIT; ...'`
   wrapper).
5. QA loop — planner / concretize / scenario / verification / finalize panes,
   several created concurrently (`pm pr qa`, `pm qa run`); plus `pm qa debug`,
   `pm qa standalone`, `pm qa launch`.
6. `pm watcher start` — per-iteration watcher panes.
7. `pm guide`, `pm meta` — foreground / exec-based launches.
8. Container mode — the runtime `exec` command carries `-e NAME` and the
   container process still receives the value.
9. Observation surfaces the user reads: `pm log` / `~/.pm/debug/<tag>.log`,
   `tmux list-panes -F '#{pane_start_command}'`, `tmux show-environment`,
   the pane registry JSON, `ps`, the launched process's environment.

**Out of scope (owned by #249, do not fail this PR for it):** `create_container`
still puts `-e NAME=value` on the `podman/docker run` argv (container.py:779).
A container-mode scenario may observe that and should report it as
pre-existing, not as a regression of this PR.

## Requirements (Given / When / Then)

### R1 — A claude-type provider with a `${VAR}` api_key never puts the value in a launch command
* GIVEN a provider `mainstub` (type `claude`, `api_key: ${PM_QA_CANARY}`) whose
  variable is exported in the environment pm runs in, selected for impl
  sessions.
* WHEN the user starts a PR implementation session.
* THEN the impl pane starts and runs; `#{pane_start_command}` for that pane
  contains no canary and no `ANTHROPIC_API_KEY=` assignment; the debug log line
  for the launch contains no canary; the pane registry entry for the pane
  contains no canary.

### R2 — …and the value still reaches the launched process
* GIVEN the same launch.
* WHEN the user inspects the running session's environment (the pane's child
  process environment, or anything the session itself reports).
* THEN `ANTHROPIC_API_KEY` equals the canary, i.e. the session is
  authenticated with the configured provider key. The transport must not
  silently drop it (the superseded `tmux -e NAME` transport did exactly that on
  tmux 3.2 for new-window / split-window).

### R3 — Literal api_key values behave the same
* GIVEN a provider whose `api_key` is a literal canary string (not a `${VAR}`
  reference).
* WHEN the user starts an implementation session and then a review session.
* THEN neither pane's `#{pane_start_command}`, nor the debug log, nor
  `ps -ef`, nor the pane registry shows the canary, while both panes' processes
  still have it in their environment.

### R4 — The env handoff file is private and short-lived
* GIVEN a launch that carries provider env.
* WHEN the user looks at `~/.pm/run/` before the pane's command has started.
* THEN the handoff file exists with mode `0600` inside a `0700` directory, and
  after the pane's command has started the file is gone (the pane removed it
  before running the session). Nothing under `~/.pm/run/` contains a value that
  is still needed.

### R5 — TUI panes get the same treatment (nested wrappers)
* GIVEN a running pm TUI session with a provider selected for discuss /
  watcher-review / qa sessions.
* WHEN the user launches a discuss pane and a watcher-review pane from the TUI.
* THEN both panes start and render normally (the pane-exit trap still fires and
  the layout rebalances when one is closed); no canary appears in either
  pane's `#{pane_start_command}`, in the debug log, or in the pane registry,
  while each pane's process environment carries the canary.

### R6 — QA loop panes, created concurrently, each get their own value
* GIVEN a PR in QA with two *different* providers configured: one for
  `qa_scenario` and one for `qa_finalize`, each with a distinct canary key.
* WHEN the user runs the QA loop so that planner, concretize, scenario and
  finalize panes are created (several of them concurrently).
* THEN every pane's `#{pane_start_command}` and every debug-log line is free of
  both canaries; the scenario panes' processes carry canary A, the finalize
  panes' processes carry canary B; no pane carries the other provider's value.

### R7 — Container-mode launches pass the key by name only
* GIVEN container mode enabled and a provider override for impl sessions.
* WHEN the user starts an implementation session that runs inside a container.
* THEN the pane's start command shows the runtime `exec` with `-e
  ANTHROPIC_API_KEY` and no value; the container's claude process reports
  `ANTHROPIC_API_KEY` equal to the canary; the debug log and pane registry are
  clean.

### R8 — Foreground / exec launches keep secrets out of argv
* GIVEN a provider override for guide / qa_author / meta sessions and no
  tmux window for that launch (or `--foreground`).
* WHEN the user runs the foreground launch (`pm guide` inside a pm session,
  `pm qa debug <id> --foreground`, `pm qa standalone` with no tmux session,
  `pm meta`).
* THEN the session starts; `ps -ef` shows no canary in any argv while it runs;
  the process environment carries the canary; the debug log carries no canary.

### R9 — Sign-off window
* GIVEN a PR in `sign_off`/`qa` with a provider override.
* WHEN the user launches the sign-off window.
* THEN the sign-off pane starts, its start command and the debug log carry no
  canary, and its process environment does.

### R10 — The reported regression tests pass
* GIVEN the branch checked out with its test suite.
* WHEN the developer runs the provider-env regression tests added by this PR
  (`tests/test_provider_integration.py`, `tests/test_tmux.py` incl. the
  real-tmux `TestProviderEnvReachesRealPane`, `tests/test_claude_launcher.py`,
  `tests/test_container.py`).
* THEN they all pass, including the canary-based cases that fail on the
  pre-fix code.

## Setup

Cross-cutting setup for every scenario (user steps):

1. Install pm from the branch under test into a venv (`pip install -e .`),
   export `PYTHONPATH` so the editable clone wins over any `/opt/pm-src`.
2. Create a throwaway git project, `pm init --backend local --no-import`, add
   one or two PRs. Enable nested podman in `project.yaml` only for the
   container scenario.
3. Use a **synthetic canary** as the credential — never a real key:
   `PM_QA_CANARY=canary-84ebabf-do-not-use` (a second distinct one, e.g.
   `canary-84ebabf-finalize`, for the two-provider concurrency scenario).
4. Register providers with `pm provider add … --skip-check` (the endpoint need
   not exist; the fake-claude stand-in does the work) and select them with
   `pm model set <session_type> provider:<name>` (global or `--project`).
5. Configure fake-claude for the session types the scenario drives
   (`pm fake-claude config set …`) so sessions run deterministically without a
   real API, per the TUI manual-testing instruction.
6. Start the pm session (`pm session`) and drive launches from inside it.
7. Collect evidence from: `pm log` / `~/.pm/debug/<tag>.log`,
   `tmux list-panes -a -F '#{pane_id} #{pane_start_command}'`,
   `tmux show-environment -g` and `-t <session>`,
   `~/.pm/pane-registry/*.json`, `ps -ef`, `~/.pm/run/`, and the pane's child
   process environment (`/proc/<pid>/environ` of the process the pane spawned).

## Edge cases and failure modes

* GIVEN no provider configured (built-in claude) WHEN the user starts a
  session THEN the pane command has no `sh -c` env wrapper, no `~/.pm/run/env-*`
  file is created, and the session behaves exactly as before this PR.
* GIVEN a provider whose `api_key` is `${SOME_UNSET_VAR}` WHEN the user starts a
  session THEN the value is transported as empty (same as the pre-fix empty
  assignment), nothing leaks, and the session starts.
* GIVEN a provider key containing spaces, single quotes, `$`, `=`, and a
  newline WHEN the user starts a session THEN the value round-trips exactly
  into the process environment (no truncation, no shell expansion) and does not
  appear in any command string.
* GIVEN a local provider (`ANTHROPIC_API_KEY` empty, `ANTHROPIC_AUTH_TOKEN`
  `ollama`) WHEN the user starts a session THEN both values arrive via the
  environment and neither appears in the command.
* GIVEN an OpenAI-type provider (`OPENAI_API_KEY`, `OPENAI_BASE_URL`) WHEN the
  user starts a session THEN the same invariants hold (this is the
  "keep openai the same" requirement).
* GIVEN the PR workdir path contains a space WHEN the user starts an
  implementation session with a provider THEN the pane starts in that
  directory and pm still recovers the session id/transcript from the pane's
  start command (the `cd` prefix must remain outside the wrapper).
* GIVEN the PR workdir path contains an apostrophe WHEN the user starts an
  implementation session with a provider THEN the pane still starts in the
  right directory and pm still tracks the session (transcript/idle detection).
  This is a plausible regression of the wrapper's `cd` hoisting.
* GIVEN a pane that is killed before its command runs (leaving its env file
  behind) WHEN the user launches another session more than 24 h later THEN the
  stale file is swept; before that it is only readable by the owner.
* GIVEN a tmux failure while creating a pane WHEN the launch fails THEN no env
  file is left behind and the user sees the usual error.
* GIVEN a launch with provider env WHEN the user later runs a plain shell
  command in the same pane THEN the provider variables are not present in that
  interactive shell (the source happened in a subshell).
* GIVEN several panes launched at the same moment (QA loop, TUI double
  launch) WHEN the user inspects `~/.pm/run/` and each pane's environment THEN
  each pane got exactly its own values and no file is shared or clobbered.

## Pass / Fail criteria

* **Pass:** for every launched pane, the canary is absent from
  `#{pane_start_command}`, from `~/.pm/debug/<tag>.log`, from the pane
  registry, from `ps` argv, and from `tmux show-environment`; and the canary
  *is* present in the launched session process's environment (so the session
  is actually authenticated). Panes start, render and (where the flow has one)
  reach their verdict.
* **Fail:** any canary appears in a command string, log line, registry entry,
  tmux environment, or argv; or a pane launches *without* the configured
  provider's value in its environment (silently unauthenticated — the tmux 3.2
  failure mode this PR's review caught); or a pane fails to start, starts in
  the wrong directory, or pm can no longer recover the session/transcript.
* Pre-existing `create_container` `-e NAME=value` argv (#249) is reported as an
  observation, not a failure.

## Ambiguities resolved

* **Which provider env values must be hidden?** All of them, not just
  `api_key`: `ANTHROPIC_BASE_URL`/`MODEL`, `ANTHROPIC_AUTH_TOKEN`,
  `OPENAI_*`. The requirement is stated as "no provider env value in the
  command".
* **Is redacting the log enough?** No. The tmux `pane_start_command` copy and
  the argv are equally exposed, so scenarios assert on all surfaces.
* **How does the value reach the process?** Via the process environment only
  (env file / `execvpe` / `-e NAME`). Scenarios therefore always check *both*
  the absence of the value in metadata *and* its presence in the process env —
  either alone can pass on a broken implementation.
* **`tmux -e NAME`?** Rejected by the implementation because tmux 3.2 resolves a
  bare name from the server/session environment, not the client's, for
  `new-window`/`split-window`. QA therefore must not assume the tmux server
  environment is populated — it must be empty of the canary.
* **Real credentials in evidence?** Never. Only synthetic canaries.

No **[UNRESOLVED]** ambiguities.

## QA round 2 — sign-off follow-up (2026-10-27)

Sign-off returned `SIGNOFF_REQA` twice (notes at HEAD `75d0bc30`). Scenarios 1–5
and the five recorded scenario 6 stories remain valid; scenario 6 is locked, so
this round adds scenarios 7–9 to record the missing evidence.

Required evidence (sign-off note-a17dac1), synthetic canaries only:

1. **OpenAI-type provider + fake-claude.** The fake process's
   `/proc/<pid>/environ` has `OPENAI_API_KEY` and `OPENAI_BASE_URL` exactly;
   neither value appears in `#{pane_start_command}`, `pm log`, the pane
   registry, `ps -ef` argv, or `tmux show-environment -g`/`-t`; no `env-*.sh`
   is left in `~/.pm/run/`.
2. **OpenAI + real claude.** The `pm log` launch line and
   `#{pane_start_command}` show `--model openai:<model>`, the `cd` prefix stays
   outside the `sh -c` wrapper, and no key appears; `/proc/<claude pid>/environ`
   has the `OPENAI_*` values.
3. **Unset `${VAR}` key.** The process env has `ANTHROPIC_API_KEY=` (empty) and
   the session starts without error.
4. **Pane killed before its command runs.** Its `env-*.sh` stays behind with
   mode `0600` (in a `0700` directory) until the 24 h sweep.

Drivability caveats carried from the scenario 6 concretizer (still true at
HEAD `75d0bc30`):

* A workdir containing an apostrophe cannot be driven with real claude (the
  unquoted `$(cat <path>)` prompt reference fails with `sh: Syntax error`); use
  fake-claude there.
* A workdir containing a space empties the prompt under real claude; use
  fake-claude, or record the workdir with `pm pr start --workdir` and observe
  only cwd / start-command / TUI tracking.
* `pm pr start --workdir <new>` is ignored for an `in_progress` PR; set it back
  to `pending` (`pm pr edit <id> --status pending`) before re-recording a
  workdir.
* fake-claude returns before the `--model` flag is added, so model-flag
  assertions need a non-fake launch.
* The TUI `s` action builds `--transcript {tdir}/...` unquoted; use a plain
  project root for TUI launches.
* The `tmux -e NAME` transport was replaced by the 0600 env file in review
  b1c1 i1; the "Rejected by the implementation" bullet above already reflects
  the current code. `create_container` `-e NAME=value` remains #249's scope.

No **[UNRESOLVED]** ambiguities.
