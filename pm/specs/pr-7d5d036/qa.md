# pr-7d5d036 — QA spec

Retire legacy regression scenarios and reuse the container/recipe launch path.

Generated 2026-11-01 against branch head `0c3acebe` (base `master`). The PR
description of 2026-11-01 governs; the older notes about committing captures
to Git and auditing the whole instruction library are superseded and are not
QA targets.

Revised 2026-11-02 at head `723929ed`, after QA round 1 (S1–S6). Since
`0c3acebe` the branch gained: the cross-device clone fix (`2f6c2fc9`, found
by S3/S4), one builder for every regression pane command (`723929ed`: the
TUI command bar and the default launch both produce
`pm -C <root> qa regression <args>` from the same place), and a shorter
`pm help` line for `pm qa regression`. R30–R33, E12–E16 and A7–A9 were added
for these; the earlier items are unchanged.

Revised 2026-11-02 (round 3) at head `ddd0ed30`, after QA round 2
(S7–S13). Round 2 passed everything except R28 (S12): a run launched from
a pane of the user's pm session kept `TMUX`/`TMUX_PANE`, so a `pm session`
the test started in its own project reused and rebalanced the user's
session. Since `a610bc87` the branch gained `634a4c05`: a host-mode run's
environment also drops `TMUX`, `TMUX_PANE`, `PM_POPUP_SESSION` and
`PM_IN_TMUX_SESSION`, and keeps `PM_TMUX_SOCKET`. Then `ddd0ed30` added
these: when `PM_TMUX_SOCKET` is set, the host-mode prompt names it and tells
the session to run plain `tmux` as `tmux -S <socket> …`; the docs describe
the dropped variables; the docs' minimal example no longer points at the
non-existent `throwaway-pm-test-project` recipe. R28 is reworded,
R34–R36, E17–E20 and A10–A12 are added, R4, R6, R7 and A7 are amended, and
the other items are unchanged.

Revised 2026-11-02 (round 4) at head `a3777520`, after QA round 3
(S14–S17). S15 and S17 passed. S14 failed R35: with `TMUX` scrubbed, a
run's `pm -C <registry> pr add` reloaded the TUI pm found from the cwd (the
test project's own TUI, or the first pm session with a TUI), never the
user's. `44f6e5fc` fixed it: outside a pm session, `_find_tui_pane` now
tries the `-C`/`PM_PROJECT` project's session before the cwd. S16 failed
R7/R34/E18: a run launched from a `pm session --global` session kept
`PM_SHARE_MODE`, so `pm tui view` in the test project showed the user's
TUI. `a7b2e4c4` added `PM_SHARE_MODE` to the scrubbed variables. That undid
R35 for share-mode sessions (the run now computes the plain tag, which
names no session), so review `a3777520` made the `-C` lookup fall back to
the live session that recorded that pm dir as its project
(`~/.pm/sessions/<tag>/pm_root`). The `-C` lookup is used by every `pm`
command run outside a pm session, not only by regression runs. R7, R34,
R35 and E18 are amended, R37–R39, E21–E23, A13 and A14 are added, A7 and A9
are extended, and the other items are unchanged.

Revised 2026-11-02 (round 5) at head `ad5fb106`. `pm_core` is unchanged
since `a3777520`; the later commits are QA notes and this spec. Round 4
(S18–S23) ran at `a3777520`. S18 (every launch surface from a
`--global` session), S19 (share-mode filings, R37/E21–E23), S20 (plain
multi-project `-C`/`PM_PROJECT`, R38) and S21 (container mode from a
`--global` TUI, R13/R15/R16/R21/A14) all passed live, with no fix. The run
then ended ERROR before S22 (R39 concurrency) and S23 (R36/R37 with a real
Claude) could start. A queued S22 launch hit a 10 s `podman inspect`
timeout while S21's container was being torn down, and the QA loop stopped
the whole run. That is a QA-loop problem, not this PR's, and is filed as
pr-7f0daef. S21 finished both stories, but its verdict never reached the
loop. Its notes, the S18–S20 notes and its A14 filing (pr-7ebc650) were
committed only in S21's clone, and have been recovered onto this branch.
R39 and the real-Claude share-mode path are therefore still unexercised.
R33 is amended: `pm qa launch` also adds `--file-prs`. A14, A7 and A9 are
extended. The other items are unchanged.

Revised 2026-11-02 (round 6) at head `b35f2804`, after the master
integration. The resumed round 5 run passed S23 (R39 and R26–R29 across a
`--global` session and a private-socket project) and S24 (R36/R37 with a
real Claude from a `--global` TUI), with no fix, so every requirement up to
R39 has now passed live at `a3777520`. Sign-off then sent the PR back for a
registry-only conflict. `7518aa8a` merged master@`5b352d16`; this PR's
`pm_core` files are unchanged by it, but master brought in pr-5ec411c
(Claude effort levels, per-provider `supported_efforts`, effort warnings
and dropping an ambient `CLAUDE_CODE_EFFORT_LEVEL` when pm passes
`--effort`) and pr-3d3b3ce (a router's env values stay out of probe argv).
Both touch `claude_launcher.build_claude_shell_cmd`, which every regression
run goes through. The next QA attempt ended ERROR at launch (`podman info`
timed out on the host, QA-loop infrastructure, not a scenario). Round 6
re-checks the core stories on the merged code and adds R40–R43, E24, E25
and A15 for how a regression run uses the user's provider configuration.
Planning found that the regression container path calls
`create_qa_container` without `route_mounts`, unlike the QA loop's scenario
containers, while `build_claude_shell_cmd(container=True)` with a router
provider prefixes the in-container bridge step that needs that mount (R41).
The other items are unchanged.

Revised 2026-11-02 (round 7) at head `efab12ab`. Round 6 (S25–S28) ran on
the merged code. S25, S26 and S27 passed with no fix. S28 failed R41: a
container-mode run on a router default died at the in-container bridge
step on the CLI and TUI Enter, because the regression container got no
route mount. `ef4f5c19` fixed it: before creating the container, the run
resolves the session's provider (`PM_PROVIDER`, the session provider file,
`pm provider default`), checks a router's settings
(`router_route.require_setup(container=True)`), starts or reuses the host
bridge and mounts its socket dir at `/run/pm-route`
(`router_route.container_mounts(strict=True)`), as a QA scenario container
on the route gets it. A `qa_regression` fake gets no mount. Review f51f
then made three user-visible changes. A provider refusal in container mode
prints "Container mode is enabled, but the regression session's provider
cannot launch it: <provider error with Remedy>" and "No session was
launched on the host.", without the container retry advice (`c5a5dd14`).
The container is named only once a create is attempted, so a provider
refusal touches no container (`2d1d19fd`). A pre-create failure that is
neither the runtime nor the provider says "Could not build the regression
session: …" (`bc940b76`, test only). The inventory now calls `c1fcecc5`
the revision the removal started from, and says every later master
revision before the removal holds the same blobs. Master has not moved
since `5b352d16`. The host-mode path is unchanged since round 6. R41 and
R42 are amended. R44–R48, E26–E29 and A16 are added, and A7 is extended.
The other items are unchanged.

## What changed, as a user sees it

- The 20 old regression scenarios under `pm/qa/regression/` are gone. The
  library is empty in this repo. `pm/qa/retired-regressions.md` lists them,
  with the Git revision (`c1fcecc58b09695602043094b44c8d96ca66bfe0`) and
  blob ids needed to recover them, and states the coverage gap this leaves.
- `pm qa regression <id> [--file-prs] [--branch B]` is now the only
  regression launcher. It no longer needs a running pm session or targets
  one. Each run gets its own QA workdir
  (`~/.pm/workdirs/qa/regression-<id>-<run-id>/`) holding a fresh clone of
  the project's base branch (or `--branch`) and a scratch dir. The setup
  recipes (`pm/qa/instructions/`) and capture recipes (`pm/qa/artifacts/`)
  are copied into the scratch dir. Captures go to
  `~/.pm/sessions/<tag>/captures/regression/<id>/<run-id>/`, where the runner
  saves the prompt as `prompt.md`.
  - Container mode enabled: the session runs in a QA container. The clone is
    at `/workspace`, scratch at `/scratch`, and only this run's captures dir
    is mounted, at `/pm-captures`. The project pm dir is mounted at
    `/pm-project` only with `--file-prs`, and in it only the registry is
    writable. If the runtime is unusable or the container can't be created,
    the run stops with an error. It never falls back to the host.
  - Container mode off: the session runs on the host in the clone.
    `PM_PROJECT`, `PM_SESSION`, `TMUX`, `TMUX_PANE`, `PM_POPUP_SESSION`,
    `PM_IN_TMUX_SESSION` and `PM_SHARE_MODE` are removed from its
    environment, so `pm` in the run behaves as it does outside tmux, in a
    plain (non-shared) mode. `PM_TMUX_SOCKET` is kept, since host
    mode still shares the user's tmux server. When it is set, the prompt
    names the socket and says to run plain `tmux` commands as
    `tmux -S <socket> …`, shell-quoted.
  - The clone's push URL is disabled, so a `git push` fails.
  - With `--file-prs`, the prompt's filing section names the real registry
    (`pm -C <registry> pr add …`), because a plain `pm pr add` in the clone
    would be lost. That filing reloads the TUI of the registry's own pm
    session, including a `pm session --global`/`--group` session.
  - `--session/-s` is still accepted but hidden and ignored, with a note on
    stderr.
- The TUI QA pane (Enter on a regression item), the TUI command bar
  (`qa regression …`) and `pm qa launch regression:<id>` all open a pane
  that runs `pm -C <root> qa regression <id> …`. Before opening the pane they
  check for the problems that would stop the run (empty library, unknown id,
  unusable container runtime) and report them instead.
- `pm qa standalone <regression-id>` now refuses and points at
  `pm qa regression`.
- `pm qa list` shows `(none — author one with 'pm qa author-regression
  <name>')` for an empty regression library.
- The discovery-supervisor prompt handles an empty library and records "not
  run" for a launch that failed. It finds in-flight tests by the pane's start
  command, and tells a run that started apart from one that failed during
  setup by whether the run's `prompt.md` exists.
- Docs (`pm qa docs`, `pm help`) describe the isolated run. The `[!CAUTION]`
  callout is gone.
- Any `pm` command run outside a pm session with `-C <pm dir>` or
  `PM_PROJECT` (a `pm pr add`, `pm pr note add` or other change that
  reloads the TUI, `pm tui view`/`send`, `pm autostart`) now targets that
  project's TUI: the session named by its tag, else the live session on the
  same tmux server that recorded that pm dir as its project (a shared
  session). Only if neither has a TUI does pm fall back, as before, to the
  cwd's session and then the first pm session with a TUI. Inside a pm
  session, that session still comes first, as on master.
- Every QA clone (regression runs, `pm qa debug`, and the PR QA loop's
  scenario workdirs) is now a plain local `git clone` of a path instead of
  `git clone --local`. On the same filesystem it still shares objects by
  hardlink; on a different filesystem from `~/.pm` (a project under
  `/scratch` or another mount) it copies instead of dying with "Invalid
  cross-device link".

## 1. Requirements (Given / When / Then)

### Retirement and recovery

- **R1** Given the PR branch of the pm repo, when the user lists the QA
  library, then the Regression Tests section shows 0 items with the
  authoring hint, the instruction (`TUI Manual Testing`), the three artifact
  recipes and the mocks are still listed, and `retired-regressions.md` does
  not appear as any library item.
- **R2** Given the empty library, when the user tries a retired id (for
  example `help-keybindings` or `init-local`) through `pm qa regression`,
  `pm qa show`, `pm qa standalone`, `pm qa run --pr` or
  `pm qa launch regression:<id>`, then each one refuses with an
  empty-library or not-found message and exit code 1. Nothing is launched,
  and no workdir or captures dir is created.
- **R3** Given the inventory file, when the user follows its recovery
  commands, then every one of the 20 listed files can be recovered at the
  recorded revision, each blob id matches the inventory, and a restored
  corpus shows up again in `pm qa list` (20 tests).
- **R4** Given the PR branch, when the user reads `pm qa docs` and
  `pm help`, then the Regression tests section has no CAUTION callout and
  describes the isolated run: the clone, the container-or-host rule, the
  disposable test project, captures with `prompt.md`, `--branch`, the empty
  library, and filing through `pm -C <registry>`. Round 3: it also says a
  host-mode run drops the variables that point `pm` at the user's project
  or session (`PM_PROJECT`, `PM_SESSION`, `TMUX`, `TMUX_PANE`, …), keeps
  `PM_TMUX_SOCKET` and names it in the prompt. The minimal example refers
  to "a setup recipe from the Recipes list above", not to a recipe that
  does not exist.

### `pm qa regression` (CLI, foreground)

- **R5** Given a disposable project with one authored regression test and
  container mode off, when the user runs `pm qa regression <id>` with no pm
  session running, then the run starts without asking for a session. Its
  header shows the target branch with a short commit, the clone path, `Runs
  in: host (container mode is off)` and the captures path
  (`…/captures/regression/<id>/<run-id>/`).
- **R6** Given that run, when the user opens the run's `prompt.md`, then it
  has a Test Environment section naming the clone and scratch dir, a Recipes
  section whose paths exist in the scratch dir (`qa-instructions/`,
  `qa-artifacts/`), and the run's captures dir, followed by the test body.
  It does not mention the user's tmux session or pane, and it has no Filing
  Findings section unless `--file-prs` was given. In host mode with
  `PM_TMUX_SOCKET` set, the Test Environment section names that socket and
  says to run plain `tmux` as `tmux -S <socket> …` (shell-quoted). With no
  `PM_TMUX_SOCKET`, or in container mode, there is no such note.
- **R7** Given the run, when the user inspects where the session ran, then
  it ran in the clone, not the project. `PM_PROJECT`, `PM_SESSION`, `TMUX`,
  `TMUX_PANE`, `PM_POPUP_SESSION`, `PM_IN_TMUX_SESSION` and `PM_SHARE_MODE`
  were unset even though they were set where the run was launched.
  `PM_TMUX_SOCKET` kept its value. The project's working tree and branches
  are unchanged. (Round 4: `PM_SHARE_MODE` added by `a7b2e4c4`.)
- **R8** Given the run's clone, when anything in it runs `git push`, then the
  push fails ("does not appear to be a git repository") and the upstream is
  unchanged. `git fetch` still works.
- **R9** Given a second branch in the project, when the user runs with
  `--branch <b>`, then the header and `prompt.md` name `<b>` and its commit,
  and the clone is checked out there.
- **R10** Given `--file-prs`, when the run starts, then `prompt.md` has a
  Filing Findings section whose commands all use `pm -C <registry>` (the
  host pm dir in host mode, `/pm-project` in a container). A PR filed with
  that command from inside the clone appears in the user's project. A plain
  `pm pr add` from the clone does not.
- **R11** Given `--session foo`, when the run starts, then stderr says
  `--session` is ignored and the run behaves as without it.
- **R12** Given a standalone pm repo (`pm init --dir`, with the code repo as
  a local checkout named by `project.repo`), when the user runs a regression
  test, then the clone is of the code repo, not the pm-state repo and not
  some unrelated parent directory.

### Container mode

- **R13** Given container mode enabled with an unusable runtime, when the
  user runs `pm qa regression <id>` or `pm qa launch regression:<id>`, then
  it exits 1 with "Container mode is enabled, but the container runtime is
  unavailable…" and both remedies. No session starts on the host, and no
  workdir, clone, captures dir or pane is created.
- **R14** Given a usable runtime but a container that can't be created (for
  example a missing image), when the user runs the test, then it exits 1
  with "…regression container could not be set up…", "No session was
  launched on the host" and the retry remedy. No container is left behind,
  the run's workdir is removed, and no captures run dir remains (no empty
  test dir either).
- **R15** Given a working QA container image (nested podman), when the user
  runs the test, then the header says `Runs in: container <name>`. Inside
  the container, `/workspace` is the clone, `/scratch` the scratch dir, and
  `/pm-captures` is only this run's captures dir, with no other runs' or
  tests' evidence visible. There is no `/pm-project` without `--file-prs`.
  The container is removed when the session exits.
- **R16** Given `--file-prs` in container mode, when the session files a
  finding with `pm -C /pm-project pr add`, then the PR appears in the host
  project. Writing to any other existing entry under `/pm-project` (plans,
  specs, the QA library, `.git`) fails as read-only.

### TUI

- **R17** Given a TUI on a project whose regression library is empty, when
  the user opens the QA pane, then it shows "Regression Tests (0)" with no
  items, and instructions and recipes are still listed.
- **R18** Given an authored test, when the user presses Enter on it, then a
  new pane runs `pm -C <root> qa regression <id> --file-prs` and shows the
  run header. The prompt doesn't name the TUI's session. The session runs as
  type `qa_regression`, so a fake-claude config keyed on `qa_regression` (not
  `qa_author`) drives it. The TUI's other panes are untouched.
- **R19** Given the TUI command bar, when the user types
  `qa regression <id> [--branch b] [--file-prs]`, then a pane opens running
  exactly those options and the TUI stays responsive (no 30 s freeze).
- **R20** Given the command bar, when the user types a malformed command (no
  id, an unknown option, `--branch` with no value, an unknown id,
  `--help`), then the TUI logs a one-line message with usage and opens no
  pane. `--help` output doesn't corrupt the TUI screen.
- **R21** Given container mode enabled with an unusable runtime, when the
  user presses Enter on a regression item, then the TUI logs the
  container-unavailable message, opens no pane, and stays navigable while
  the check runs.
- **R22** Given an instruction item, when the user presses Enter, then the
  instruction still launches as before: a Claude pane with session context,
  type `qa_author`.

### Headless launch and discovery

- **R23** Given a test, when a caller runs
  `pm qa launch regression:<id> --target-window discovery`, then a pane opens
  in that window and its start command contains `qa regression <id>`.
  Without `--target-window`, a new window opens.
- **R24** Given a launch whose setup fails after the pane opens (for example
  the base branch doesn't exist), when the pane exits, then no `prompt.md`
  newer than the launch exists for that test. The discovery prompt's
  `ls -t …/prompt.md` check therefore classifies it as not run.
- **R25** Given the discovery watcher on an empty library, when it ticks,
  then it records "regression library empty, nothing scheduled", launches
  nothing, and records nothing as run or passing. After a test is authored, a
  later tick launches it through `pm qa launch regression:<id>` into the
  discovery window.

### Concurrency (shared resources)

- **R26** Given one test, when two runs start at the same moment (CLI plus
  a pane, or two panes), then each gets its own run id, workdir, clone,
  captures dir, `prompt.md` and container name, and neither `prompt.md`
  names the other run's paths.
- **R27** Given two `--file-prs` runs plus the user, when all three add a PR
  to the registry at the same moment, then all three PRs are present,
  `project.yaml` is still valid, and no `.tmp` file is left behind.
- **R28** Given the user's live pm session for the project, when a
  regression run's session starts its own pm session in its disposable
  project, then the user's session windows, panes and pane registry are
  unchanged, and the test's session has a different name. This holds when
  the run was launched from a pane of the user's session (TUI Enter, the
  command bar, `pm qa launch`, or a shell in one of its panes) and the test
  starts its session from the run's own pane. pm's debug log shows no
  "reusing … grouped session: pm-<user tag>" and no rebalance of the
  user's session. (Round 2 S12 failed this. `634a4c05` fixed it.)
- **R29** Given two runs of the same test, when one fails during setup and
  the other runs, then the failing run's cleanup removes only its own
  workdir and captures dir, and the healthy run's directories are intact.

### Added in the round-2 revision

- **R30** Given a disposable project on a different filesystem from
  `~/.pm`, when the user runs a regression test from any surface, then the
  clone is created (by copying) and the run proceeds exactly as R5–R18
  describe. The fail-closed container paths (R13, R14) report their own
  container errors, not a clone error.
- **R31** Given a project on the same filesystem as `~/.pm`, when a run
  clones it, then the clone still shares the project's object files (link
  count above 1). The fix kept the fast path.
- **R32** Given the PR QA loop on a project PR, when it creates scenario
  workdirs, then each scenario clone checks out the PR branch and its
  `origin` is the real upstream, as before the clone change.
- **R33** Given the TUI command bar and the QA pane, when each launches the
  same test, then both panes run a command of the form
  `pm -C <root> qa regression <id> …` with the typed options in the typed
  order. The command bar adds no `--file-prs` the user didn't type; Enter
  always adds `--file-prs`, and so does `pm qa launch regression:<id>`
  (round 4 S18).

### Added in the round-3 revision

- **R34** Given the user's pm session (on the default tmux server or a
  private `PM_TMUX_SOCKET`), when a host-mode run is launched from each
  surface (CLI in a plain shell outside tmux, CLI in a pane of the session,
  TUI Enter, the command bar, `pm qa launch`, and the prefix+M `pm>` popup),
  then the session's recorded environment matches R7 on every surface. The
  run still targets the session's project. A fake-claude config keyed on
  `qa_regression` still drives the session. After the session exits, a
  TUI-launched pane is cleaned up as before: it leaves the pane registry and
  the layout rebalances.
- **R35** Given a `--file-prs` run launched from the user's TUI, when the
  session files a finding with the prompt's `pm -C <registry> pr add`, then
  the new PR shows in the user's TUI PR list within a few seconds, without
  the user pressing `r`. This must also hold when other pm sessions with a
  TUI (the test's own disposable-project session, or another project the
  user has open) share the tmux server and sort before the user's session.
  The early containment note says filed PRs "show up in their list
  immediately". Before `634a4c05` a TUI-launched run reached the user's TUI
  through `TMUX_PANE`. Without it, the reload went to the TUI of the
  session pm resolves from the clone cwd, or else the first pm session on
  the server that has a TUI (round 3 S14 failure). `44f6e5fc` fixed it by
  resolving the `-C` registry's session first. Round 4: this must also
  hold when the user's session is a `pm session --global` or `--group`
  one (R37).
- **R36** Given a real Claude session (not a stand-in) in host mode, on a
  private `PM_TMUX_SOCKET`, when it follows the prompt and a short authored
  test, then it creates its disposable project in the scratch dir, starts
  that project's pm session on the socket's server, drives and captures it
  with `tmux -S <socket>`, and writes its evidence to the run's captures
  dir. It leaves the user's session unchanged, and the default tmux server
  gets no session from it.

### Added in the round-4 revision

- **R37** Given the user's `pm session --global` (or `--group <g>`) session
  for a project, whose TUI lists its PRs, and a `--file-prs` regression run
  launched from it whose session has started its own pm session in a
  disposable project on the same shared server (named to sort first), when
  the run files a finding with the prompt's `pm -C <registry> pr add`, from
  the test project or from the clone, then the user's shared TUI shows the
  new PR within a few seconds without `r`, and the test project's TUI is
  not reloaded at that moment. The run's own environment still has no
  `PM_SHARE_MODE` (R7), and in the test project `pm session name` and
  `pm tui view` (no `-s`) give the test project's session, the same as a
  plain shell outside tmux with only that `PM_TMUX_SOCKET` exported.
  (`a7b2e4c4` + `a3777520`.)
- **R38** Given two projects A and B, each with a pm session and TUI on the
  same tmux server, with A's session sorting first, when the user runs a
  TUI-reloading `pm` command (`pm pr add`, `pm pr note add`) or
  `pm tui view` for B from a shell outside any pm session, with
  `pm -C <B pm dir>` or with `PM_PROJECT=<B pm dir>` exported, from a
  neutral directory or from inside A's checkout, then B's TUI is the one
  reloaded or shown, and A's TUI is untouched. Without `-C`/`PM_PROJECT`,
  the same command in A's checkout still targets A. Typed in a pane of
  A's pm session, a `-C B` command still reloads or shows A's TUI (the
  in-session-first order is unchanged from master); the change lands in
  B's registry either way.
- **R39** Given one shared server holding the user's shared session and
  two regression runs' test sessions, plus a second project in a separate
  share-mode or plain session, when both runs and the user file PRs into
  their registries at the same moment, then every PR lands in the right
  `project.yaml`, each user TUI ends up listing exactly its own project's
  new PRs without `r`, no test-project TUI and no other project's TUI logs
  a reload at filing time, and no `.tmp` file is left behind.

### Added in the round-6 revision

A regression run picks its provider the way master's regression launcher
did: `PM_PROVIDER`, then the session's provider file, then
`pm provider default`, then built-in claude. It does not read `pm model`
per-role settings (there is no `qa_regression` role) and passes no
`--effort`. That is unchanged from master and is not checked here (A15).

- **R40** Given container mode off and a default provider whose launch sets
  environment variables (a claude/local-type provider with an `--env`
  entry holding a secret-like value, or a router provider with a host
  `--launcher`), when the user runs a regression test from the CLI and from
  TUI Enter, then the session runs on that provider: its recorded
  environment has the provider's variables (a router's
  `ANTHROPIC_BASE_URL` included), the variables the provider unsets are
  absent, and it got the provider's `--model`. The R7 variables are still
  removed and `PM_TMUX_SOCKET` kept. No provider value appears in the run
  pane's start command, any process argv (`ps`), the run header,
  `prompt.md` or pm's command/debug logs. Names may appear.
- **R41** Given container mode on with a working QA image and a router
  default provider whose `api_base` is a host-local endpoint, when the user
  runs a regression test (CLI and TUI Enter), then the session in the
  container starts with `ANTHROPIC_BASE_URL` at the in-container forwarder
  and a request to it reaches the host endpoint, as a QA scenario container
  on that route does. The provider's values reach the container only
  through `-e NAME` on the runtime command line. The container mounts the
  route's host bridge dir (`~/.pm/route-bridge/<route>/`) at
  `/run/pm-route`, and the run starts that host bridge first if it is not
  running. A run whose session dies at the bridge step, or one that falls
  back to the host, fails this. (Round 7: S28 failed this, `ef4f5c19`
  fixed it. Check every launch surface: CLI, TUI Enter, the command bar and
  `pm qa launch`.)
- **R42** Given a default router provider whose settings cannot launch (no
  model, or an `api_base` with no port/host), when the user runs a
  regression test from the CLI (host and container mode), TUI Enter or
  `pm qa launch`, then the run stops with the provider's
  "provider '<name>': … Remedy: …" error and exit 1. No session starts on
  the host, and no container, workdir or captures dir is left behind. A TUI
  or `pm qa launch` pane that closes at once without showing it is
  pr-089af69: cite it. Round 7: in container mode the CLI message is
  "Container mode is enabled, but the regression session's provider cannot
  launch it: provider '<name>': … Remedy: …" then "No session was launched
  on the host.", with no "fix the container runtime/image" or
  "pm container disable" advice. It comes before any container is created
  or named: the runtime gets no create, run, rm or inspect call for it. In
  host mode the message is "Could not build the regression session:
  provider '<name>': … Remedy: …".
- **R43** Given R41 works, when two container-mode regression runs on the
  same router provider start at the same moment and one ends first, then
  both sessions reach the host endpoint through the one host bridge, and
  the survivor still reaches it after the other's container is removed.
  Two host-mode runs launched at once with different providers (one
  through `pm provider default`, one with `PM_PROVIDER` exported) each get
  only their own provider's variables and `--model`.

### Added in the round-7 revision

- **R44** Given container mode on and a router default whose host bridge
  cannot be set up (a leftover regular file, or a symlink, where the
  route's bridge dir `~/.pm/route-bridge/<route>` belongs), when the user
  runs a regression test, then it is refused as R42 describes for container
  mode, with "cannot set up the host route bridge: …" and the remedy to run
  `pm provider test <route> --container`. No container, workdir or captures
  dir exists afterwards, and the symlink's target is unchanged. Once the
  leftover is removed, the next run starts the bridge and runs (R41).
- **R45** Given container mode on, a router default and a `qa_regression`
  fake config, when the user runs a regression test, then a router whose
  settings can launch gets no `/run/pm-route` mount and the run starts no
  host bridge, and a router with no model is still refused as in R42.
- **R46** Given container mode on and no host bridge running for a router,
  when two regression runs on that router and the user's
  `pm provider test <route> --container` all start at the same moment, then
  exactly one host bridge process serves the route, both containers mount
  the same bridge dir, and each session's request reaches the endpoint.
  If that host bridge is killed while a run's container is still up, the
  next run on the route starts a new bridge, and the running container's
  next request reaches the endpoint through it without a restart. Runs on
  two different routers and on a non-router provider, started together
  (different `PM_PROVIDER` values), each mount only their own route's
  bridge dir (none for the non-router run) and reach only their own
  endpoint.
- **R47** Given container mode on with a QA image that has git, tmux and
  pm, and a real Claude on the host PATH, when the user runs a short
  `--file-prs` regression test from the TUI, then the session starts in the
  container without a workspace-trust prompt, creates its disposable
  project under `/scratch`, starts that project's pm session on the
  container's own tmux server, drives and captures it, writes evidence to
  `/pm-captures` (the run's host captures dir), and files a finding with
  `pm -C /pm-project pr add` that lands in the host registry. The user's
  session, windows and other registry content are unchanged, and the
  container is removed after `/exit`. If no real Claude can reach its API
  from a nested container, R47 is blocked.
- **R48** Given the final branch, when the user reads
  `pm/qa/retired-regressions.md` and follows its recovery commands at the
  named revision `c1fcecc5` and at master@`5b352d16`, then both give the
  same 20 blobs listed in the inventory. A retired id run with container
  mode on and a router default is refused with the library message before
  any host bridge or container starts.

## 2. Setup

- Install pm from the PR clone (`./install.sh --local` from the repo, or the
  venv steps in `tui-manual-test.md`). Confirm with `pm which`.
- Disposable project, following `tui-manual-test.md`: `git init`, at least
  one commit on the base branch, then `pm init --backend local --no-import`,
  and commit `pm/` so a clone sees the library. A bare upstream (`git init
  --bare`) set as `origin` makes the push and fetch checks meaningful.
- Author tests with `EDITOR=true pm qa add-regression <name>` and then edit
  the body. Commit them if a clone must see them; recipes are copied from the
  project root, not the clone.
- Session stand-ins. Use the fake-claude stand-in
  (`pm fake-claude config set '{"qa_regression": {}}'`), or a recording
  stand-in: an executable named `claude` placed earlier on PATH that logs its
  cwd, `PM_PROJECT`, `PM_SESSION`, `TMUX`, `TMUX_PANE`, `PM_TMUX_SOCKET`,
  `PM_POPUP_SESSION`, `PM_IN_TMUX_SESSION`, `PM_SHARE_MODE`, whether stdin
  is a TTY, and its argv, then exits, waits, or execs an interactive shell.
  The shell makes the run pane the session's real environment, so a QA
  worker can act as the session from it. The fake stays open in a TTY pane
  and exits in a non-TTY shell.
- Container mode: `pm container enable`. Make the runtime unusable with
  `pm container set runtime <missing-binary>`, and make creation fail with
  `pm container set image <missing-tag>`. For the working path, set
  `nested_podman: true` under `project:` in the disposable project (as
  `tui-manual-test.md` describes) and build or obtain the `pm-dev` image.
- Before and after snapshots of `~/.pm/workdirs/qa/`,
  `~/.pm/sessions/*/captures/regression/` and `podman ps -a` are the
  evidence for "nothing created" and "nothing left behind".

## 3. Edge cases

- **E1** `pm/qa/regression/` absent (Git doesn't track empty dirs): listing
  and launching still report an empty library, not a crash.
- **E2** Id containing a path (`../instructions/tui-manual-test`): reported
  as an unknown regression test, and the instruction file is never run.
- **E3** Library non-empty, unknown id: "Unknown regression test: <id>. Run
  'pm qa list'…"; nothing is created.
- **E4** `--branch` naming a missing branch: "Could not clone '<b>'…", exit
  1, the run's workdir is removed and no captures dir is created.
- **E5** Run outside any pm project: an error from `state_root`, exit 1.
- **E6** Project path containing a space with `--file-prs`: the filing
  command in `prompt.md` is quoted and works when pasted.
- **E7** `pm qa standalone <regression-id>` refuses; `pm qa standalone
  <instruction>` still works.
- **E8** Command-bar `qa regression --help` doesn't print into the TUI.
- **E9** A container session that tries to read `captures/regression/` as
  a whole, or another test's captures: not visible.
- **E10** A nested `pm qa regression` inside a regression container (a test
  of the runner itself): it gets no captures mount for its own run (it fails
  closed). Observe only if the container path works.
- **E11** Removing the only authored test returns every surface to the
  empty-library messages.
- **E12** Project checkout on a different filesystem from `~/.pm` (impl
  spec E13; QA round 1 S3/S4 failure). Every launch surface (CLI, TUI Enter,
  command bar, `pm qa launch`, discovery) clones and runs; a TUI pane no
  longer closes at once with "Invalid cross-device link".
- **E13** `pm qa debug` (and TUI `d` on a QA item) also clones with
  `create_scenario_workdir`. With a project on another filesystem it opens
  its debug session in a fresh clone. `pm qa debug` also looks up regression
  ids, so a retired id gives "Instruction not found" and creates nothing.
- **E14** A project path containing spaces or a single quote, or a branch
  name containing a single quote, typed in the command bar: the pane runs the
  test against the right project and branch, because the pane command is
  shell-quoted once by the shared builder and once by the pane wrapper.
- **E15** The hidden `--file-bugs` flag (the pre-PR spelling) still means
  `--file-prs`.
- **E16** A command-bar line with an unbalanced quote: the TUI must not crash.
  If it does, check whether any other command (e.g. `pr list "x`) crashes it
  the same way; that would be a pre-existing command-bar bug to file
  separately, not a failure of this PR.
- **E17** `PM_TMUX_SOCKET` whose path contains a space: the prompt's
  `tmux -S …` command is quoted and works when pasted into a shell.
- **E18** The user's session is a shared one (`pm session --global`), so its
  panes carry `PM_SHARE_MODE` and a shared `PM_TMUX_SOCKET`. A run launched
  from it still has to make `pm` behave as it does outside tmux (R7, R34).
  The oracle is a plain shell outside tmux with only that `PM_TMUX_SOCKET`
  exported: from the run's pane and from that shell, the same `pm session`
  plus `pm tui view` (no `-s`) sequence in a disposable project must give
  the same results. pm mixes `PM_SHARE_MODE` into the session-tag hash of
  every command except `pm session` (which clears it), which is why it was
  added to the scrub list (round 3 S16, `a7b2e4c4`). If the two shells
  differ, that is a finding against R7/R34. Panes of the test project's
  own session on the shared server do inherit `PM_SHARE_MODE` from that
  server's global environment; that is pre-existing (pr-50e1e3f), not a
  failure here.
- **E19** The prefix+M `pm>` popup sets `PM_POPUP_SESSION` and `PM_PROJECT`
  and runs typed commands in the popup with stdin from /dev/null (only
  `pr qa …` and `review-loop` are handed to the TUI). `qa regression <id>`
  typed there must run against the session's project with both variables
  scrubbed (R34). If the session gets no terminal input, that is how every
  popup command runs, and it was the same on master. It is not a failure of
  this PR: check `pm pr list --plan bugs` and file it once.
- **E20** Host-mode leftovers: the prompt does not ask the session to kill
  the pm sessions it started, so they can outlive the run on the user's
  server. Record them as evidence. Only a change to the user's own session
  fails (A2, A10).
- **E21** `-C`/`PM_PROJECT` names a project with no live session, or whose
  session's TUI has exited: the command still succeeds and writes the
  registry, prints no error, and its reload falls back to the cwd's
  session or the first pm session with a TUI (a harmless state reload).
  `pm -C <that dir> tui view` then shows that fallback TUI with its
  session name in the header (unchanged from master); record it. Once the
  project's TUI is back, the next command targets it again.
- **E22** The `-C` pm dir is given in another spelling (a relative path, a
  trailing slash, or a symlinked directory leading to the project), or the
  shared session was started from a symlinked path: the lookup still finds
  the project's session, because both sides are resolved.
- **E23** Another project's live session on the same shared server (the
  test project's, which recorded its own pm dir), or a dead session's
  leftover `~/.pm/sessions/<tag>/pm_root` naming the `-C` pm dir: neither
  is chosen. Only a live session whose recorded pm dir is the `-C` dir is.
- **E24** Ambient effort and provider effort: master now drops an inherited
  `CLAUDE_CODE_EFFORT_LEVEL` only when pm passes `--effort`. A regression
  run passes none, so with `CLAUDE_CODE_EFFORT_LEVEL` exported, or a
  default provider created with `--effort`, the session gets no `--effort`
  and the exported value passes through. Record what the session got; it
  matches master's regression launcher (A15).
- **E25** `PM_PROVIDER` exported where the run is launched is not in the
  scrubbed list: the run uses that provider, and `pm` commands inside the
  run (the test project's session) see it too. Record it; a provider
  variable leaking into the test project's own sessions is not a failure.
- **E26** Container mode, a missing image and a router that can launch:
  the host bridge starts before the create fails. The run reports the
  container error with the container retry advice (not the provider
  message), removes its container, workdir and captures dir, and leaves
  the host bridge running. The bridge is shared by design, so that is not
  a leftover.
- **E27** Container mode with an unusable runtime and a router that cannot
  launch: the runtime refusal (R13) comes first, and no bridge starts.
- **E28** A hand-edited default provider entry that is not a provider (an
  unknown `type`): in container mode it gets R42's provider message, and in
  host mode "Could not build the regression session: provider '<name>' … is
  not a valid entry …". Exit 1 both ways, and nothing is left behind.
- **E29** A router whose host `launcher` is not executable: host mode
  refuses it (launcher not executable, Remedy), and container mode ignores
  the launcher and runs plain `claude` in the container through the bridge.

## 4. Pass/Fail criteria

Pass means every Then clause above can be observed on the user's surface
(CLI output and exit code, files under `~/.pm`, the TUI log and panes, and
`podman ps` / `podman inspect`). Fail means any of these:

- a retired id is listed, resolved or launched
- an empty library is reported as a run or a pass
- a regression session targets, or is told to target, the invoking pm
  session
- the session runs in the project dir rather than the clone, or with
  any of the R7 variables set
- `pm` in a host-mode run resolves, reuses, rebalances or attaches the
  user's pm session (R28, E18)
- a `--file-prs` filing from a TUI-launched run doesn't reach the user's
  TUI list without a manual refresh (R35), including from a shared
  session (R37)
- a `pm -C`/`PM_PROJECT` command outside a pm session reloads or shows
  another project's TUI while the named project's TUI is running (R38)
- a container-mode failure falls back to the host
- a provider's variable value appears in a run's pane start command, a
  process argv, the header, `prompt.md` or pm's logs (R40, R41)
- a container-mode regression run on a router default provider starts a
  session that dies at the bridge step, instead of reaching the route or
  being refused up front (R41)
- a failed launch leaves a workdir, a captures run dir, a container or a
  `prompt.md`
- `--file-prs` findings are lost, or anything other than the registry is
  writable from the container
- concurrent runs share or clobber dirs, or concurrent filings lose a PR
- the TUI freezes or prints into its own screen
- a container-mode provider refusal gives container runtime advice, or
  creates, names, inspects or removes a container (R42, R44)
- two host bridges serve one route at once, or a restarted bridge does
  not reach a container that was already running (R46)

If the container-backed run (R15, R16, E9, E10) can't be exercised because
no QA image can be built in the environment, record those items as
**blocked**, not passed. The fail-closed paths (R13, R14) must still be
exercised.

## 5. Ambiguities (resolved)

- **A1** "Supported regression launch uses the intended container/test
  target". With the library empty in this repo, launches are exercised
  against a disposable project with a freshly authored test, driven by
  stand-in sessions (the fake, or a recording `claude`). No real Claude is
  needed except optionally for the discovery watcher.
- **A2** Host mode (container mode off) is a supported, documented fallback
  that shares the user's tmux server. The boundary there is the clone, the
  scrubbed environment and the prompt's rules. Only container mode is the
  hard boundary, so R28 checks behavior and not the impossibility of
  interference.
- **A3** Verifying where the session ran (R7) is done with a stand-in
  session's own record of its cwd and environment, which is what a user
  debugging the runner would do. It doesn't mean reading code.
- **A4** Discovery (R25) needs a model to follow the supervisor prompt.
  Use a real Claude for the watcher session only, with `qa_regression`
  faked. If that's impossible in the environment, R25 is blocked. R23 and
  R24 still cover the commands that prompt relies on.
- **A5** The `--plan ux` vs `improvements` mismatch between the discovery
  prompt and the filing addendum predates this PR and is already filed as
  pr-3d1055c. It is out of scope here.
- **A6** The plan docs (`plan-delivery`, `plan-regression`) that still
  describe a corpus port are user-owned records and are not checked.
- **A10** Host mode, round 3: `PM_TMUX_SOCKET` is deliberately kept (A2),
  so a test's pm session lands on the same server as the user's. On a
  shared session (E18) that server is the shared socket. Correct behavior
  is a distinct, test-named session that never touches the user's. Test
  sessions left after the run (E20) are evidence, not failures. Workdirs
  never being reaped is pr-c414c76.
- **A11** R36 uses a real Claude for the regression session, because the
  `tmux -S` note exists for a model that follows `tui-manual-test.md`'s
  plain `tmux` commands. Keep the test body short. Clear any fake-claude
  config for `qa_regression` and `_all` first. Unset the agent's
  `CLAUDECODE`/`CLAUDE_CODE_*` variables in the tmux global environment
  (round-2 S11 trap). If no real Claude can start in the environment, R36
  is blocked.
- **A12** R35 comes from the containment note's intended output 1 (filed
  PRs show up in the user's list immediately). It is in scope because
  `634a4c05` changed how a TUI-launched run finds the TUI. If R35 fails
  only when another pm session sorts first, check whether the same failure
  happens for a CLI run started from a plain shell. If it does, that part
  is pre-existing. Still report the TUI-launched case as NEEDS_WORK, since
  it worked before `634a4c05`.
- **A13** Round 4: the `-C` lookup (R38) changes which TUI a `pm` command
  outside a pm session reloads or shows: the named project's, where master
  used the cwd's session or the first pm session with a TUI. That is the
  intended reading of `-C`/`PM_PROJECT` and matches `_get_pm_session`.
  Inside a pm session the current session still wins (unchanged from
  master), so a `-C B` command typed in a pane of A's session reloads A's
  TUI; that is recorded, not failed. A reload is a state-only re-read, so
  the evidence for "which TUI was reloaded" is the TUI's own debug log
  (`action: reload (state only)` in `~/.pm/debug/<tag>.log`) and the
  `~/.pm/runtime/home-refresh-<session>` mtime, read per filing. A
  concurrent filing masks a missing reload (round 3 S14), so per-filing
  checks use solo filings.
- **A14** Container mode and R35/R37: a container run files with
  `pm -C /pm-project pr add` inside the container, which can't see the
  host tmux server or signal the host TUI, so the user's TUI shows the PR
  only after `r` or its 300 s sync. That predates the `-C` lookup and is
  not a failure of this PR. Round 4 S21 observed it and filed it as
  pr-7ebc650; don't file it again. Since the `-C` lookup now runs inside
  the container at filing time, the filing itself must still exit 0 with
  no traceback and land in the host registry (it did in S21).
- **A15** Round 6, providers. Master's regression launcher also used
  `build_claude_shell_cmd` with no model, provider or effort, so which
  provider a run uses (E25), and that `pm model` per-role settings and a
  provider's `effort` don't apply (E24), are unchanged and out of scope.
  What is in scope is that this PR's new paths carry the chosen provider
  correctly: host mode layers the provider env over the scrubbed
  environment (R40), and the new container path must handle a router the
  way the QA loop's scenario containers do, through
  `router_route.container_mounts` (R41). `pm qa debug`'s container path had
  the same missing mount on master; if a worker confirms it, file it once
  as a separate bug rather than failing this PR on it. Router stories need
  a recording stand-in, not the fake: the fake-claude branch of
  `build_claude_shell_cmd` drops the bridge prefix, so a `qa_regression`
  fake config hides R41. A host-local endpoint can be any small HTTP server
  that logs requests; nothing needs to answer like a real router.
- **A16** Round 7. The evidence that a provider refusal touched no
  container is the runtime's own call log: put a recording `podman`
  wrapper earlier on PATH that logs its argv and then runs the real
  podman. `podman events` does not show an `rm -f` or `inspect` of a
  container that does not exist. A provider refusal may leave a host bridge
  running from an earlier run, which is expected. The TUI and
  `pm qa launch` have no provider preflight, so their panes close at once
  on a provider refusal: that is pr-089af69. `pm qa debug`'s container path
  lacks the route mount (pr-a016b21), and TUI Enter on an instruction or
  artifact recipe with an unlaunchable default provider exits the TUI
  (pr-659c098). Cite these and don't file them again. R47 uses a real
  Claude because only a model shows whether the container-mode prompt
  (no socket note, `/scratch`, `/pm-captures`, `/pm-project`) can be
  followed, and whether the regression workdir is trusted. Stand-ins
  cannot show either.

- **A7** Bugs found in round 1 and filed elsewhere are not failures of this
  PR: pr-a571291 (`--file-prs` filings make the filed PR the user's active
  PR), pr-089af69 (a TUI regression pane that fails after it opens closes at
  once), pr-8984bc7 (`pm qa list` creates empty `pm/qa/regression/` and
  `mocks/` dirs), pr-19e8114 (pm init leaves `project.yaml.lock`, `prompts/`,
  `watchers/` and `transcripts/` untracked), pr-f5325d4 (`pm qa debug` clones
  the pm dir's parent for a standalone pm repo), pr-e847a7a (other launch
  commands, such as a TUI instruction launch, interpolate prompt and
  transcript paths unquoted, so a project path with a space or an apostrophe
  breaks them), pr-3d1055c (A5), pr-f51600e (an unbalanced quote on the
  command bar crashes the TUI, E16), pr-c414c76 (QA/regression workdirs are
  never reaped) and pr-f98ac63/pr-24f022e (prefix+P popup commands resolve
  the cwd's tag or pm_core). Round 4 adds pr-a589f09 (a prefix+M popup
  `qa regression` gets stdin from /dev/null, E19), pr-e6d0439 (the clone
  override is written under the `PM_SHARE_MODE` tag, which the wrapper
  never reads), pr-50e1e3f (`pm session --global`/`--group` leaves
  `PM_SHARE_MODE` in the shared server's global environment, so a test
  project's session on that server inherits it, E18), pr-60d2e79 (the
  pytest suite writes into the real `~/.pm`; don't run it during a story
  that diffs `~/.pm`) and pr-c3bf868 (a stale TUI pidfile can make a
  reload target a dead or wrong process). Round 5 adds pr-7ebc650 (A14:
  a container run's filing never reloads the host TUI), pr-7f0daef (one
  transient `podman inspect` timeout on a queued scenario's launch stops
  the whole QA run and drops an in-flight scenario's verdict; QA-loop
  infrastructure, not a scenario failure) and the pr-adfdce3 note (after a
  command-bar submit made from the QA view, focus stays on the hidden PR
  tree, so the next Enter opens pr-edit for the selected PR; press `q`
  twice first). A worker that sees them should cite the
  PR id and move on. Because of pr-e847a7a, E14's awkward project path is
  checked only on regression launches, which quote it.
- **A8** pr-e64ecb6 and pr-9ff8a1b report the cross-device clone failure
  this branch fixes. E12/E13 confirm the fix. Those PRs are closed after
  this one merges, not by QA.
- **A9** QA round 1 environment facts that shape setup (from PR notes): no
  `pm-dev` image exists and `pm container build` starts a Claude session, so
  container stories build a slim image (python:3.12-slim, git, pm's Python
  deps, a `/usr/local/bin/pm` shim, a uid-1000 `pm` user,
  `ENV PATH=/home/pm/.local/bin:…`) with `podman build --uts host`;
  `pm container set runtime` accepts only docker or podman; `/scratch` is a
  different filesystem from `~/.pm` and `/tmp` is the same one; projects
  must live outside `/workspace`; the `pm session` guide pane starts a host
  `claude` once; the TUI's qa-item dedup allows one TUI-launched run at a
  time. Round 2 added these: give a bare upstream as a `file://` URL (a
  plain path is "local-only" and the clone keeps the project as origin);
  `PM_PROJECT` is the `-C` envvar, so export it as the real `<proj>/pm`;
  `pm init --dir` must live outside any git repo; tmux 3.2a may not reap a
  pane that exits within about a second, so read the pane text; the TUI's
  `launch_pane` splits the session's current window, so select window 0
  before TUI Enter; a `pm session` for `/workspace` needs a seeded
  `pm fake-github` config when `gh` is missing. Round 3 added these: a
  `pm session --global` session lives on its own server at
  `/tmp/pm-sessions/pm-<share tag>`, and with no client attached its
  window should be resized (200x50) before TUI Enter; `--group` needs an
  existing Unix group (`id -gn`); a test project's bare `pm pr add` made
  before its session exists reloads some other TUI through the fallback
  (harmless, not R35; only the reload at the run's filing counts); filings
  move `active_pr` (pr-a571291); commit `pm/project.yaml.lock` in the
  fixture so `git status` stays clean; real Claude Code switches to the
  alternate screen, so read its tmux use from pipe-pane hooks (put them at
  `after-split-window[1]`; on tmux 3.2a `[0]` is pm's own hook) or from the
  Bash `tool_use` entries in `~/.claude/projects/<clone-slug>/*.jsonl`, and
  end it with `/exit` typed in its pane. Round 4 added these: a test
  project's TUI on a shared server logs to
  `~/.pm/debug/<name>-<share-mode hash>.log` (pr-50e1e3f), not to its
  session's hash, so find each TUI's log by the pid in its mount line; take
  reload baselines after any test-project `pm pr add` made before its
  session exists; after TUI Enter, press `q` to get the PR list back;
  `C-b d` sent to a run pane detaches the test session nested in it; end
  a TUI-launched run before a second TUI Enter (one at a time); name a test
  project `zz-*` when checking that `pm tui view` in it finds its own TUI
  (an `aaa-*` name would be the fallback's first pick and hide a missed
  lookup), and `aaa-*` when checking that a filing does not reload it; a
  PID-1 `sleep infinity` container needs a subreaper (`setsid python3
  reaper.py …`) for `pm session`, and the reaper must drain its children
  before it exits; the QA container has no `bc`; a test project with no
  PRs starts its TUI in guide mode, whose guide pane runs `claude`, so
  seed one PR first when a real Claude is on PATH.

No [UNRESOLVED] items.
