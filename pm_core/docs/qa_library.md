# pm QA library

Every project that uses `pm` gets a `pm/qa/` directory with four
subdirectories of Markdown-with-frontmatter files. They feed prompts,
the TUI, and the CLI.

## The four directories

| Directory | Purpose |
|---|---|
| `pm/qa/instructions/` | Reusable test-environment procedures — anything a QA scenario needs to set up before it can exercise the code (seed a database, start a dev server, prepare fixture data, log in a test user, etc.). Referenced by QA scenarios in their `INSTRUCTION:` field. |
| `pm/qa/regression/`   | Claude-driven test scenarios run via `pm tui test <id>`. Each file is a natural-language prompt; the runner launches Claude with the prompt to exercise the project end-to-end and report back. |
| `pm/qa/artifacts/`    | Recipes for capturing concrete evidence of behavior — recordings, logs, screenshots — that unambiguously confirm what happened. |
| `pm/qa/mocks/`        | Shared mock definitions injected verbatim into every QA scenario prompt so all scenarios use the same contracts for external dependencies. |

There is also a runtime sibling, `pm/qa/captures/`, written by impl,
QA, and regression sessions — see [Captures](#captures) below.

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

```markdown
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

```markdown
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

> [!CAUTION]
> This section describes the runner's behavior **after pr-7d5d036
> lands**. Until then, the runner hardcodes "testing against the pm
> tmux session" into every prompt and bails out if no `pm` session is
> running — see pr-7d5d036 for the actual current state.

Files under `pm/qa/regression/` are Claude-driven regression tests.
The body of each `.md` file is **literally a Claude prompt**. The
runner reads it, optionally appends a bug-filing or bug-fixing
addendum, and launches Claude in an isolated environment to exercise
whatever the test prescribes and report back.

Each test runs in its own ephemeral environment, the same way QA
scenarios do — nothing the test does affects unrelated state, and
runs are reproducible across machines and containers. The test body
is responsible for bringing up whatever surface it needs to exercise
(spawning a pane, starting a server, invoking a CLI, etc.) and for
tearing down or simply letting the ephemeral environment vanish at
the end.

### Running

```
pm tui test --list                # list available tests
pm tui test <id>                  # run one
pm tui test <id> --file-bugs      # run + open bug PRs for any failures
```

Regression tests don't fix bugs themselves and don't mutate the
project's source. The only writes that escape the ephemeral env are
the captures committed under `pm/qa/captures/regression/...` and, when
`--file-bugs` is set, bug PRs filed via `pm pr add` (which lands them
in `pm/project.yaml` on master with reproduction steps and a pointer
to the relevant capture). The actual fix is left to a normal bug-fix
PR session.

A minimal example:

```markdown
---
title: TUI startup renders PR tree
description: Verify the TUI comes up and the dependency tree displays
---
You are a careful tester. Open a fresh scratch project (see the
`throwaway-pm-test-project` instruction), start a `pm session`, and
verify:

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
session follows to produce a `pm/qa/captures/<pr-id>/...` artifact
that downstream consumers (humans replaying, agents parsing) can use
to confirm what happened.

A minimal example:

```markdown
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

Use the standard manifest layout, with a `command:` field in the
frontmatter naming the exact invocation, and a `## What this
demonstrates` section explaining what to look for.
```

## Captures

A *capture* is the artifact a recipe produces. Captures are organized
by which kind of session produced them:

```
pm/qa/captures/
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
        └── <run-timestamp>/
            ├── recording.cast
            └── manifest.md
```

PR-scoped captures group runs by phase (`impl/pre-fix`, `impl/post-fix`,
`scenarios/<n>`). Regression captures use a `<test-id>/<run-timestamp>/`
layout because regression tests aren't bound to a PR and may run
repeatedly over time; the timestamp keeps a history.

### Version control for regression captures

Regression captures are checked into git so behavior diffs are
visible across runs. Large files may eventually need a different
storage strategy (e.g. `git-lfs`); for now, treat that as future
work and just commit.

When a phase needs more than one capture (two distinct pre-fix
demonstrations, multiple captures within one scenario), give each its
own named subdirectory under the phase, e.g.
`impl/pre-fix/<short-name>/`.

### Manifest

`manifest.md` rides alongside each capture and records what produced
the capture, so the capture isn't just an opaque blob. The convention:

```markdown
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
| `pm qa docs` | Prints this document. |
| QA planner prompt | `instruction_summary_for_prompt` renders `### Instructions` and `### Artifact Recipes`. Recipes are referenced by filename in the scenario `INSTRUCTION:` field. |
| Scenario 0 prompt | Same library summary, scoped to the interactive session. |
| Bug-fix flow prompt | Points sessions at `pm/qa/instructions/` and `pm/qa/artifacts/` by directory; sessions discover specific files themselves. Captures go under `pm/qa/captures/<pr-id>/impl/pre-fix/` and `…/post-fix/`. |
| Bug-fix review checklist | Tells reviewers to read captures under `pm/qa/captures/<pr-id>/impl/`. |
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
