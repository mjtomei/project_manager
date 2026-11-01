# pr-7d5d036 — Retire legacy regression scenarios and reuse the container/recipe launch path

Spec generated 2026-11-01 against branch head `1f407574` (master `c1fcecc5`).
The current PR description governs; the 2026-05 notes on captures-in-Git and
the exhaustive instruction audit are superseded (user notes 2026-11-01).

## 1. Requirements (grounded)

### R1 — Remove the legacy definitions from the active library

- `pm/qa/regression/*.md` holds 20 old-style monolithic agent scenarios
  (command-dedup, guide-progress, help-keybindings, init-empty, init-github,
  init-local, launch-dedup, log-viewer, meta-launch, mobile-mode,
  multi-window-registry, pane-layout, plans-pane, pr-interaction,
  restart-dedup, session-resume, status-filter, sync-refresh,
  tech-tree-visual, window-resize).
- Discovery inputs are all `qa_instructions._list_dir(regression_dir(root))`
  (`list_regression_tests`, `list_all`, `get_instruction(..., "regression")`,
  `resolve_instruction_ref`) plus the discovery-supervisor prompt's
  `ls pm/qa/regression/*.md` (`prompt_gen.generate_discovery_supervisor_prompt`).
  Deleting the files with `git rm` removes them from every one of these. No
  code, test or fixture reads any of the 20 files (checked by grepping each
  stem: only unrelated widget ids such as `#plans-pane` match).
- Record a durable inventory: new `pm/qa/retired-regressions.md` (pm/qa root,
  so `_list_dir` never discovers it; same place as the historical
  `pm/qa/pr-d60d185.md`). It records the recovery revision
  `c1fcecc58b09695602043094b44c8d96ca66bfe0` (master; the files are
  byte-identical on this branch), every path with its blob SHA, title and
  description, recovery commands, and the explicit coverage-gap statement
  (removal is not equivalent coverage or a passing rerun).
- Hand off to the deferred port: a pm PR note on `pr-c77561b` pointing at the
  inventory and revision.

### R2 — Keep what must stay

Untouched: `tests/**` (unit/integration), `pm/qa/instructions/` (setup recipe
`tui-manual-test.md`), `pm/qa/artifacts/` (capture recipes), fakes
(`fake_claude`, `fake_github`), `pm/qa/pr-d60d185.md`, `pm/specs/**`,
`~/.pm/sessions/*/captures/**` (never touched), plan docs. The regression
*mechanism* stays: `pm qa add-regression`, `pm qa author-regression`, the QA
pane's Regression section, `regression_dir()`, the discovery watcher.

### R3 — Remove live-PM targeting from the regression launch surface; reuse the QA container/recipe path

Current launch surfaces and their stale targeting:

| Surface | Today |
|---|---|
| `pm qa regression <id>` (`cli/qa.py:qa_regression`) | `_find_tui_pane`; exits "No pm tmux session found" without a session; prompt says "You are testing against tmux session: X"; `launch_claude(cwd=None)` on the host in the caller's cwd. |
| `pm qa launch regression:<id>` (`cli/qa.py:qa_launch`, used by discovery) | Prompt targets `$PM_SESSION`/current session; host Claude in the project root. |
| TUI Enter on a regression item (`tui/pane_ops.launch_qa_item`) | Prompt targets the TUI's session + `$TMUX_PANE`; host Claude. |
| `pm qa standalone <id>` falls back to regression items | Host workdir + `tui_section(live session)`. |

Change:

- `pm qa regression <id> [--file-prs] [--branch B]` becomes the single
  regression launcher. It prepares a run with the primitives `pm qa debug`
  and the QA scenario path already use — `qa_loop.create_qa_workdir`,
  `qa_loop.create_scenario_workdir` (fresh `git clone --local` + empty
  scratch), `qa_loop._setup_clone_override`, `container.create_qa_container`,
  `claude_launcher.build_claude_shell_cmd`, `container.build_exec_cmd(cleanup=True)`
  — and runs the session in the foreground (`os.execvpe`, like
  `pm qa debug --foreground`). No new runner, sandbox or recipe mechanism.
  - Container mode enabled: `container_preflight_error()` is checked before
    anything is created; failure exits 1 with `container_unavailable_message`.
    Container creation failure releases only that container and exits 1 with
    `container_retry_remedy`. Never falls back to the host.
  - Container mode disabled: runs on the host in the clone (the documented
    non-container QA fallback), with `PM_PROJECT`/`PM_SESSION` scrubbed from
    the session environment so `pm` commands inside the disposable project
    cannot resolve to the user's project.
  - No pm session is required.
- Recipes: copy the project's `pm/qa/instructions/*.md` into
  `<scratch>/qa-instructions/` and `pm/qa/artifacts/*.md` into
  `<scratch>/qa-artifacts/` — the directories and convention the QA scenario
  path (`_install_instruction_file` / `_install_artifact_files`) uses.
- Prompt (`regression_prompts.build_regression_test_prompt`): the
  "Session Context / testing against tmux session" block is replaced by a
  Test Environment block (workdir clone at branch@sha, scratch dir, container
  or host), a statement that the target is a disposable project created with
  the setup recipes and never the user's project/session, the recipe paths,
  the exact per-run captures dir, then the unchanged test body and filing
  addendum. Prompt edits are limited to this targeting replacement.
- Captures: `paths.captures_dir("regression", session_tag=...)` →
  `~/.pm/sessions/<tag>/captures/regression/<test-id>/<run-id>/` (the
  documented layout). In container mode `create_qa_container(pr_id="regression")`
  mounts `captures/regression/` at `/pm-captures` with
  `PM_CAPTURES_PR=regression`, so the in-container path is
  `/pm-captures/<test-id>/<run-id>/`. The assembled prompt is saved there as
  `prompt.md` (mirrors `_write_scenario_capture_file(..., "prompt.md")`).
  The per-run directory and `prompt.md` are written only once the session
  command is built (container created), immediately before exec, so a run
  that never launched leaves no evidence of one. Never committed to Git.
- `pm qa launch regression:<id>` and the TUI regression launch run
  `pm -C <root> qa regression <id> --file-prs` in their pane/window (the TUI
  already launches `pm qa debug --foreground <id>` the same way), so all three
  surfaces share one environment builder and produce identical runs.
- `pm qa standalone <id>` refuses a regression id and points at
  `pm qa regression <id>`, so it is no longer a host/live-session path for
  regression tests. `pm qa run` / `pm qa debug` keep their regression
  fallback (both already use the QA workdir/container path).

### R4 — Empty library is handled honestly; references reconciled

- `pm qa regression <id>` with no definitions: exit 1, "No regression tests
  in the library (pm/qa/regression/ is empty)…" with the authoring commands.
  Unknown id with a non-empty library keeps "Unknown regression test".
- `pm qa list` regression section shows `(none)` plus the authoring hint.
- TUI QA pane already renders "Regression Tests (0)" with no items; Enter on
  an absent item logs "QA item not found". Unchanged.
- Discovery supervisor prompt: inventory with `2>/dev/null`; an empty
  listing means nothing is scheduled this tick (logged), never a run/PASS; a
  failed `pm qa launch` is recorded as not run. Step 4 describes the
  isolated launch instead of implying the test shares the watcher's session.
- Docs: `pm_core/docs/qa_library.md` — remove the `[!CAUTION]` callout (PR
  note), rewrite the Regression tests section for the isolated run, update the
  directory table, captures text and the surfaces table. CLI help
  (`cli/__init__.py`), `qa_instructions` module docstring, `qa_regression` /
  `qa_standalone` docstrings.

### R5 — Supersede old notes

No captures in Git (prompt and docs already say so; kept). No instruction
library audit. Nothing is ported.

## 2. Implicit requirements

- I1: `--file-prs` must still reach the project's real registry. Running in a
  clone, a bare `pm pr add` writes the clone's `project.yaml`, which is
  discarded — filings would be silently lost. The addendum therefore names
  the registry explicitly (`pm -C <registry> …`): the host pm dir in host
  mode; in container mode the project's pm state dir is bind-mounted rw at
  `/pm-project` **only when filing is requested** (the 2026-05-08 containment
  note lists filed PRs as an intended output; nothing else of the project is
  mounted). Needs an optional `extra_rw_mounts` on `create_qa_container`.
- I2: Regression runs must not push. `allowed_push_branch=None` → no push
  proxy.
- I3: The workdir/container naming must not collide with QA runs or with each
  other: workdir `~/.pm/workdirs/qa/regression-<id>-<run-id>/`, container
  `qa_container_name("regression-<id>", run_id, 0, session_tag)` (inside the
  `pm-<tag>-` prefix that `cleanup_session_containers` sweeps). Run id is a UTC
  timestamp plus a short random suffix.
- I4: QA-workdir scanners (`qa_run.json`, `qa_status.json`, resume files)
  must ignore regression runs — they write none of those files.
- I5: Session type stays `qa_regression` (already in the fake-claude
  catalogue), so fake-claude configs can drive regression sessions.
- I6: The pane launchers should fail visibly before spawning a pane for the
  common failures (unknown id / empty library / container runtime unusable):
  `pm qa launch` exits 1 with the message (the discovery session sees it); the
  TUI logs it. Shared helper `regression_launch_problem()`. An id must be one
  of the listed library stems (a path such as `../instructions/<x>` is an
  unknown id). The TUI runs the check in a worker thread
  (`asyncio.to_thread` under `app.run_worker`): with container mode enabled
  it runs `<runtime> info` (up to 10 s), which must not block the event loop.
- I7: Prompt-size: test bodies are inlined whole (existing behavior); the
  launcher's file-backed bootstrap covers oversized prompts.

## 3. Ambiguities (resolved)

- A1 — Branch under test: default to `project.base_branch` (fallback
  `master`); `--branch` overrides. Regression runs are not PR-bound and the
  discovery supervisor runs against the base branch. A clone failure exits 1
  with the git error.
- A2 — Foreground vs window: `pm qa regression` stays foreground/blocking as
  it was; the pane surfaces wrap it. No new `--window` mode.
- A3 — Filing from a container (see I1): mount the pm state dir only for
  `--file-prs`. Alternatives rejected: writing findings to captures and adding
  a host filing step (a new mechanism; changes the discovery workflow), or
  host-only filing (silently drops container findings).
- A4 — Where to record the inventory: `pm/qa/retired-regressions.md` (not
  discovered, beside the library) plus a PR note on `pr-c77561b`. It is
  project data, so the shipped `qa_library.md` does not mention it.
- A5 — Retired ids get no special "retired" error in code: the library
  mechanism is generic across projects. The empty-library/unknown messages are
  honest; the inventory file names the retired ids.
- A6 — Plan docs (`plan-delivery.md`, `plan-regression.md`) still describe
  porting the corpus. They are user-owned planning records; not edited here.
  Reported to the user instead.
- A7 — Tests: no regression scenario is run (none remain). Bounded checks are
  unit/CLI tests with fakes/mocks plus one real launch-preparation check.

No [UNRESOLVED] items.

## 4. Edge cases

- E1: Library dir absent after removal (Git does not track empty dirs):
  `regression_dir()` recreates it on demand; `ls … 2>/dev/null` in the
  discovery prompt prints nothing.
- E2: A `README.md` under `pm/qa/regression/` would be listed as a test — so
  the inventory lives at the pm/qa root.
- E3: Container mode enabled + runtime down: no workdir, clone or container is
  created (preflight first), exit 1. Pane launchers report it before spawning.
- E4: `create_qa_container` raising any exception: remove only that container,
  exit 1, nothing launched on the host. A clone or session-build failure
  likewise removes this run's own just-created QA workdir; no captures dir is
  created.
- E5: `pm qa regression` invoked from the TUI command bar has `PM_PROJECT` set;
  the host-mode session env scrubs it. In container mode only the provider env
  names are passed to `exec -e`.
- E6: No session tag (not in a git repo): `state_root()` already requires a
  pm project; the captures dir falls back per `captures_dir`; if `None`, exit 1
  rather than giving the session no captures location.
- E7: Fake-claude configs keyed on `qa_author` used to apply to TUI/headless
  regression launches; they now use `qa_regression` like the CLI did.
- E8: `pm qa run`/`pm qa debug` still resolve regression ids; with the library
  empty they report "Instruction not found".
- E9: Workdir clones from regression runs are left in place, like
  `pm qa debug`; the container is removed by the exec trap when the session
  exits.
- E10: Router providers. The session is built with `container=True`, so a
  router default provider starts the in-container bridge first and fails
  closed without it. Route-bridge mounts for regression containers are not
  added here; that belongs to the container-launch hardening PRs. Model routing
  is unchanged: no per-type model resolution, as before.
- E11: Host mode (container mode off) shares the user's tmux server, as QA
  host scenarios do. The prompt requires explicit `-s <session>` and forbids
  driving sessions the test did not start. Container mode is the boundary.

## 5. Verification (bounded)

- Unit/CLI: `tests/test_regression_prompts.py`, `tests/test_regression_launch.py`
  (real git clone, host + container wiring, fail-closed runtime/create,
  empty library, unknown id, bad branch, `pm qa launch`, TUI, standalone,
  `pm qa list`, discovery prompt, real `podman run` argv), plus
  `TestCreateQAContainer.test_passes_extra_rw_mounts`.
- One real host-mode launch with a stub `claude`: the process ran in the clone
  with `PM_PROJECT`/`PM_SESSION` unset, `prompt.md` was written to
  `captures/regression/demo/<run-id>/`, and the source project was left clean.
- Repo check: the 20 inventory ids are not listed, resolved or present; every
  blob matches at `c1fcecc5`; the instructions/artifacts recipes and fakes are
  unchanged against master. A real container run was not done because no
  pm-dev image was built in this environment.
