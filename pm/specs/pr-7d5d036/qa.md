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
    `PM_PROJECT` and `PM_SESSION` are removed from its environment.
  - The clone's push URL is disabled, so a `git push` fails.
  - With `--file-prs`, the prompt's filing section names the real registry
    (`pm -C <registry> pr add …`), because a plain `pm pr add` in the clone
    would be lost.
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
  library, and filing through `pm -C <registry>`.

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
  Findings section unless `--file-prs` was given.
- **R7** Given the run, when the user inspects where the session ran, then
  it ran in the clone, not the project. `PM_PROJECT` and `PM_SESSION` were
  unset even though they were set in the invoking shell. The project's
  working tree and branches are unchanged.
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
  unchanged, and the test's session has a different name.
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
  always adds `--file-prs`.

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
  cwd, `PM_PROJECT`, `PM_SESSION` and its argv, then exits or waits. The
  fake stays open in a TTY pane and exits in a non-TTY shell.
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

## 4. Pass/Fail criteria

Pass means every Then clause above can be observed on the user's surface
(CLI output and exit code, files under `~/.pm`, the TUI log and panes, and
`podman ps` / `podman inspect`). Fail means any of these:

- a retired id is listed, resolved or launched
- an empty library is reported as a run or a pass
- a regression session targets, or is told to target, the invoking pm
  session
- the session runs in the project dir rather than the clone, or with
  `PM_PROJECT`/`PM_SESSION` set
- a container-mode failure falls back to the host
- a failed launch leaves a workdir, a captures run dir, a container or a
  `prompt.md`
- `--file-prs` findings are lost, or anything other than the registry is
  writable from the container
- concurrent runs share or clobber dirs, or concurrent filings lose a PR
- the TUI freezes or prints into its own screen

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

- **A7** Bugs found in round 1 and filed elsewhere are not failures of this
  PR: pr-a571291 (`--file-prs` filings make the filed PR the user's active
  PR), pr-089af69 (a TUI regression pane that fails after it opens closes at
  once), pr-8984bc7 (`pm qa list` creates empty `pm/qa/regression/` and
  `mocks/` dirs), pr-19e8114 (pm init leaves `project.yaml.lock`, `prompts/`,
  `watchers/` and `transcripts/` untracked), pr-f5325d4 (`pm qa debug` clones
  the pm dir's parent for a standalone pm repo), pr-e847a7a (other launch
  commands, such as a TUI instruction launch, interpolate prompt and
  transcript paths unquoted, so a project path with a space or an apostrophe
  breaks them) and pr-3d1055c (A5). A worker that sees them should cite the
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
  time.

No [UNRESOLVED] items.
