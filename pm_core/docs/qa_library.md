# pm QA library

Every project that uses `pm` gets a `pm/qa/` directory with four
subdirectories of Markdown-with-frontmatter files. They feed prompts,
the TUI, and the CLI.

## The four directories

| Directory | Purpose |
|---|---|
| `pm/qa/instructions/` | Reusable test-environment procedures — anything a QA scenario needs to set up before it can exercise the code (seed a database, start a dev server, prepare fixture data, log in a test user, etc.). Referenced by QA scenarios in their `INSTRUCTION:` field. |
| `pm/qa/regression/`   | Claude-driven test scenarios run via `pm qa regression <id>`. Each file is a natural-language prompt; the runner launches Claude with it in an isolated QA run (a QA container when container mode is enabled), where it exercises a disposable test project built from the setup recipes and reports back. The directory may be empty. |
| `pm/qa/artifacts/`    | Recipes for capturing concrete evidence of behavior — recordings, logs, screenshots — that unambiguously confirm what happened. |
| `pm/qa/mocks/`        | Shared mock definitions injected verbatim into every QA scenario prompt so all scenarios use the same contracts for external dependencies. |

There is also a per-PR captures directory written by impl, QA, and
regression sessions; it lives at
`~/.pm/sessions/<session-tag>/captures/<pr-id>/` on the host (resolve
via `pm qa captures-path <pr-id>`) and is bind-mounted to `/pm-captures`
inside scenario containers. Captures are not part of the project
repo — see [Captures](#captures) below.

## Authoring

There are commands available for authoring new files in Claude sessions:

```
pm qa author-instruction <name>     # new instruction
pm qa author-regression <name>      # new regression test
pm qa author-artifact <name>        # new artifact recipe
```

Each loads this document and walks the user through drafting the file
at the right path. If you'd rather just edit a stub yourself, the
`pm qa add-instruction` / `add-regression` / `add-artifact` siblings
scaffold a stub and open `$EDITOR`.

## File format (instructions / regression / artifacts)

Each `.md` file is YAML frontmatter followed by Markdown body:

```text
---
title: Login flow setup
description: Seed a test user and log them in before scenarios run
---
## Setup

…body of the recipe…
```

### Frontmatter fields

| Field | Type | Required | Used by |
|---|---|---|---|
| `title` | string | yes | `pm` TUI QA pane, `pm qa list`, planner prompts. |
| `description` | string | yes | Same surfaces as `title`; rendered as a one-liner under the entry. |

The filename stem (`login-flow-setup.md` → `login-flow-setup`) is the
ID. References in scenarios use the bare stem or `<dir>/<stem>.md`;
fuzzy matching across `instructions/`, `regression/`, and `artifacts/`
means small typos still resolve.

### What goes in the body

Body shape is convention-only — readers (humans, the QA planner, and
sessions launched on a recipe) read it directly. Conventions per
category are described in the dedicated sections:

- [Instructions](#instructions)
- [Regression tests](#regression-tests)
- [Artifact recipes](#artifact-recipes)

## Instructions

Files under `pm/qa/instructions/` are reusable procedures referenced
by QA scenarios (and by impl sessions for bug reproduction). Typical
body shape:

- Setup steps the agent follows to bring up the environment. 
- Optional Test Steps / Expected Behavior / Reporting sections when
  the instruction also prescribes what the scenario should do once
  the environment is up.

Reference an instruction from a QA scenario by its filename stem in
the `INSTRUCTION:` field.

A minimal example:

```text
---
title: Throwaway pm test project
description: Spin up a scratch project with a few PRs to drive the TUI against
---
## Setup

1. Create a fresh scratch directory and `git init` it.
2. Run `pm init --backend local --no-import`.
3. Add a few PRs with `pm pr add` so the tree has something to render.
4. Start a session with `pm session` from the scratch directory.

## Test Steps

Use `pm tui send` / `pm tui view` to drive the TUI. Cover at least one
navigation and one action keybinding for the area you're testing.
```

## Regression tests

Files under `pm/qa/regression/` are Claude-driven regression tests.
The body of each `.md` file is **literally a Claude prompt**. The
runner reads it, optionally appends a findings-filing addendum, and
launches Claude in an isolated environment to exercise whatever the
test prescribes and report back.

Each run is isolated the same way a QA scenario is. The runner creates
a QA workdir for the run, `~/.pm/workdirs/qa/regression-<id>-<run-id>/`.
It holds a fresh clone of the project at the base branch (`--branch`
picks another) and an empty scratch dir. The runner copies the
project's setup recipes (`pm/qa/instructions/`) and capture recipes
(`pm/qa/artifacts/`) into the scratch dir and names them in the prompt.

- **Container mode enabled**: the session runs in a QA container. The
  clone is at `/workspace`, scratch at `/scratch`, and this run's
  captures dir at `/pm-captures` (only that directory is mounted, not
  other runs' captures). If the container runtime is unusable or the container
  cannot be created, the run stops with an error. It never falls back
  to the host.
- **Container mode off**: the session runs on the host in the clone,
  which is the same fallback QA scenarios use. Its environment drops the
  variables that point `pm` at your project or pm session (`PM_PROJECT`,
  `PM_SESSION`, `TMUX`, `TMUX_PANE`, `PM_TMUX_SOCKET` and the like), so
  `pm` in the run behaves as it does outside tmux and it carries no
  ambient pointer to the user's tmux server. The prompt says that
  `$TMUX` is unset (so a plain `tmux` reaches the default server) and
  that the run must use the socket `pm session --print-connect` prints
  for the session it starts itself.

The test target is a **disposable project** the session creates in the
scratch dir with a setup recipe, then drives and captures with the
capture recipes. It is never your own pm project or a pm/tmux session
the test did not start, and no running pm session is required. The test
body brings up whatever surface it exercises (spawning a pane, starting
a server, invoking a CLI, etc.). The run's container is removed when the
session exits. The workdir is left for inspection, as with `pm qa debug`.

### Running

```
pm qa list                          # list available tests
pm qa regression <id>               # run one (foreground)
pm qa regression <id> --file-prs    # run + open PRs for any findings
pm qa regression <id> --branch <b>  # clone <b> instead of the base branch
```

Pressing Enter on a regression test in the TUI QA pane and
`pm qa launch regression:<id>` (used by the discovery supervisor) run
`pm qa regression <id> --file-prs` in a new pane, so every surface
produces the same isolated run. `qa regression <id> …` typed in the TUI
command bar also runs in a pane, with the options you typed.

Regression tests don't fix bugs themselves and don't mutate the
project's source. The runner disables the push URL of the clone's
`origin`, so a stray `git push` fails rather than publishing the clone.
The only writes that escape the ephemeral env are:

- **Captures**, durable on the host but not committed to the repo, under
  `~/.pm/sessions/<tag>/captures/regression/<test-id>/<run-id>/`. The
  runner creates the directory, saves the assembled prompt there as
  `prompt.md`, and names it in the prompt.
- **Filed PRs**, only when `--file-prs` is set. Findings are filed into
  the project's registry with `pm -C <registry> pr add` (bugs go to
  `--plan bugs`, improvements to `--plan improvements`). In container
  mode the project's pm directory is mounted at `/pm-project` for this,
  and only when filing is requested. Everything already in it except
  `project.yaml` and its lock is mounted read-only, so the session can
  file PRs but not change specs, plans or the QA library. The actual fix
  is left to a normal bug-fix PR session.

The library can be empty. Then `pm qa list` shows no regression tests,
`pm qa regression` reports that the library is empty, and the discovery
supervisor schedules nothing. An empty library is never reported as a
run or a pass.

A minimal example:

```text
---
title: TUI startup renders PR tree
description: Verify the TUI comes up and the dependency tree displays
---
You are a careful tester. Create a disposable pm project in the
scratch dir with a setup recipe from the Recipes list above, start
a `pm session` from it, and verify:

- The TUI renders without error.
- All PRs you added appear, with dependency edges in the right
  direction.
- Pressing `j` / `k` moves the selection between PR cards.
- Pressing `?` opens the help screen and `escape` closes it.

## Reporting

For each check, report PASS or FAIL with one line of evidence (a
keystroke sequence, a quoted line of output). End with an overall
PASS/FAIL.
```

## Artifact recipes

Each file under `pm/qa/artifacts/` is a *recipe for capturing
evidence*. The recipe explains:

- **When to use** it (which kinds of behavior it captures).
- **What this recipe produces** (the file shapes — recording, log,
  manifest).
- **Capture commands** (concrete, copy-pasteable).
- **Manifest format** the recipe expects authors to write alongside
  the capture.

A recipe is *not* a test that runs automatically. It's a procedure a
session follows to produce a capture under
`~/.pm/sessions/<tag>/captures/<pr-id>/...` (resolve via
`pm qa captures-path <pr-id>`) that downstream consumers (humans
replaying, agents parsing) can use to confirm what happened.

Reference an artifact recipe from a QA scenario by its filename stem
in the `ARTIFACT:` field (comma-separated when a scenario uses more
than one recipe).

A minimal example:

```text
---
title: stdout transcript
description: Capture a copy of a command's stdout/stderr alongside its exit code
---
## When to use

A scenario runs a single command end-to-end and the value is the
exact bytes it wrote, not an animation of the run. Common case:
exercising a CLI flag and proving the output line-for-line.

## What this recipe produces

In `<capture-dir>/`:
- `output.log` — combined stdout/stderr of the command.
- `exit-code` — single line, the command's exit status.
- `manifest.md` — the usual frontmatter + commands + what it shows.

## Capture

Run the command with redirected output:

    {cmd} > output.log 2>&1
    echo $? > exit-code

## Manifest format

Standard manifest frontmatter — `pr`, `workdir`, `captured_at`,
`recipe` — plus a `command:` field naming the exact invocation. Body
has `## Commands` (the wrapped command) and `## What this
demonstrates` (what to look for in `output.log`).
```

## Captures

A *capture* is the artifact a recipe produces. Captures live outside
the project repo, under `~/.pm/sessions/<session-tag>/captures/` on
the host — they are durable but **not** committed to git. Use
`pm qa captures-path <pr-id>` to resolve the per-PR directory.
Regression captures don't have a PR id. The regression runner creates
each run's directory under `captures/regression/` and names it in the
test's prompt.

Captures are organized by which kind of session produced them:

```
~/.pm/sessions/<session-tag>/captures/
├── <pr-id>/                   # captures bound to a PR
│   ├── impl/
│   │   ├── pre-fix/
│   │   │   ├── recording.cast
│   │   │   ├── transcript.log     # optional fallback / supplement
│   │   │   └── manifest.md
│   │   └── post-fix/
│   │       └── …
│   └── scenarios/
│       ├── 1/
│       │   └── …
│       └── 2/
│           └── …
└── regression/                # captures from regression tests (no PR)
    └── <test-id>/
        └── <run-id>/          # <UTC timestamp>-<suffix>
            ├── prompt.md      # written by the runner
            ├── recording.cast
            └── manifest.md
```

PR-scoped captures group runs by phase (`impl/pre-fix`, `impl/post-fix`,
`scenarios/<n>`). Regression captures use a `<test-id>/<run-id>/`
layout because regression tests aren't bound to a PR and may run
repeatedly over time; the timestamp keeps a history.

When a phase needs more than one capture (two distinct pre-fix
demonstrations, multiple captures within one scenario), give each its
own named subdirectory under the phase, e.g.
`impl/pre-fix/<short-name>/`.

### Manifest

`manifest.md` rides alongside each capture and records what produced
the capture, so the capture isn't just an opaque blob. The convention:

```text
---
pr: <pr-id, or "regression" for regression captures>
workdir: <absolute path the capture came from>
captured_at: <ISO timestamp>
recipe: pm/qa/artifacts/<recipe-filename>.md
---

## Commands

```
<copy-pasteable commands to reproduce>
```

## What this demonstrates

<one paragraph: what to look for in playback>
```

Recipes may add their own frontmatter fields (e.g. `tmux_session`,
`test_project`) when relevant.

## Mocks

Files under `pm/qa/mocks/` are **shared mock contracts** — Markdown
descriptions of how an external dependency should behave when QA
scenarios stand in for it. They are not code. The body of each file
spells out what the mock simulates (e.g. "Claude API session
returning scripted responses"), what those scripted responses look
like, and what remains real. The runner injects every mock body
verbatim into every QA scenario prompt, so all parallel scenario
agents implement consistent stand-ins rather than each devising their
own.

A mock file maps to whatever code your scenarios end up writing to
honor the contract — patches, fakes, in-memory replacements, etc.
The mock file is the single source of truth for the contract; the
implementation is the scenario's responsibility.

CLI:

```
pm qa mocks list                    # list all mock contracts
pm qa mocks show <id>               # print one
pm qa mocks add <name>              # scaffold a new one in $EDITOR
pm qa mocks edit <id>               # edit an existing one in $EDITOR
pm qa mocks prompt                  # print the block injected into scenario prompts
```

Reference a mock from a QA scenario by its filename stem in the
`MOCKS:` field (comma-separated for multiple).

## Where each surface reads what

| Surface | What it shows / consumes |
|---|---|
| `pm` TUI QA pane (`q`) | Three categories listed inline (Instructions, Regression Tests, Artifact Recipes); mocks have their own CLI surface via `pm qa mocks`. Reads `title`, `description` for display. |
| `pm qa list` | Same three sections as the QA pane. |
| `pm qa show <id>` | Full body of one file; auto-detects category. |
| `pm qa edit <id>` | Opens the file in `$EDITOR`; auto-detects category. |
| `pm qa add-instruction <name>` | Scaffolds a stub in `pm/qa/instructions/`. |
| `pm qa add-regression <name>` | Scaffolds a stub in `pm/qa/regression/`. |
| `pm qa add-artifact <name>` | Scaffolds a stub in `pm/qa/artifacts/`. |
| `pm qa author-instruction <name>` | Same as add-instruction, but launches a guided Claude session that uses this document to interview the author. |
| `pm qa author-regression <name>` | Guided authoring for a regression test. |
| `pm qa author-artifact <name>` | Guided authoring for an artifact recipe. |
| `pm qa regression <id>` | Runs one regression test in an isolated QA workdir (a QA container when container mode is enabled) against a disposable test project; see [Regression tests](#regression-tests). The TUI QA pane (Enter) and `pm qa launch regression:<id>` run the same command in a pane. |
| Discovery supervisor prompt | Lists `pm/qa/regression/*.md` and launches due tests with `pm qa launch regression:<id>`. An empty library schedules nothing. A test whose pane exits before the runner wrote the run's `prompt.md` failed during setup and is recorded as not run. |
| `pm qa docs` | Prints this document. |
| QA planner prompt | `instruction_summary_for_prompt` renders `### Instructions` and `### Artifact Recipes`. Instructions are referenced from a scenario by filename in the `INSTRUCTION:` field; artifact recipes are referenced in the `ARTIFACT:` field (comma-separated for multiple). |
| Scenario 0 prompt | Same library summary, scoped to the interactive session. |
| Bug-fix flow prompt | Points sessions at `pm/qa/instructions/` and `pm/qa/artifacts/` by directory; sessions discover specific files themselves. Captures go under `$(pm qa captures-path <pr-id>)/impl/pre-fix/` and `…/post-fix/`. |
| Bug-fix review checklist | Tells reviewers to read captures under `$(pm qa captures-path <pr-id>)/impl/`. |
| `pm qa mocks list/show/add/edit` | CLI for `pm/qa/mocks/`. |
| `pm qa mocks prompt` | Prints the block injected into every QA scenario prompt. |

## Authoring tips

- For artifact recipes, the manifest format section is the most
  load-bearing part — make it unambiguous so captures aren't opaque.
- Recipes can reference your project's own paths and tooling freely —
  the QA library is per-project. Only extract something into a recipe
  if you'll reuse it across multiple scenarios or PRs.
- `pm qa list` shows existing recipes; `pm qa show <id>` prints any
  one of them. Browse a few before authoring something new — the
  fastest way to learn the shape is to read what's already there.
