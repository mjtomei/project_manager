# pm QA library

Every project that uses `pm` gets a `pm/qa/` directory with four
subdirectories of Markdown-with-frontmatter files. They feed prompts,
the TUI, and the CLI; nothing here is project-internal magic — drop a
file in the right directory and `pm` picks it up the next time it
generates a prompt or refreshes the QA pane.

## The four directories

| Directory | Purpose |
|---|---|
| `pm/qa/instructions/` | Reusable test-environment procedures (e.g. "spin up a throwaway project, drive the TUI from another pane"). Referenced by QA scenarios in their `INSTRUCTION:` field. |
| `pm/qa/regression/`   | Migrated TUI regression tests. Run via `pm tui test <id>`. Lives alongside instructions but called out separately because it has its own runner. |
| `pm/qa/artifacts/`    | *Recipes for capturing reviewable evidence* — screen recordings, command logs, screenshots — that demonstrate either a bug or new PR behavior to a human reviewer. |
| `pm/qa/mocks/`        | Shared mock definitions injected verbatim into every QA scenario prompt so all scenarios use the same contracts for external dependencies. |

There is also a runtime sibling, `pm/qa/captures/<pr-id>/`, which is
written by impl and QA sessions during a PR — see
[Captures](#captures) below.

## File format (instructions / regression / artifacts)

Each `.md` file is YAML frontmatter followed by Markdown body:

```markdown
---
title: TUI Manual Testing
description: Test TUI changes against a throwaway project in the workdir
tags: [tui, manual]
---
## Setup

…body of the recipe…
```

### Frontmatter fields

| Field | Type | Required | Used by |
|---|---|---|---|
| `title` | string | recommended | TUI QA pane, `pm qa list`, planner prompts. Falls back to titleized filename. |
| `description` | string | recommended | Same surfaces as `title`; rendered as a one-liner under the entry. |
| `tags` | list[string] | optional | Free-form, intended for future filtering. Not yet used in selection logic. |

The filename stem (`tui-manual-test.md` → `tui-manual-test`) is the
ID. References in scenarios use the bare stem or `<dir>/<stem>.md`;
`qa_instructions.resolve_instruction_ref` does fuzzy matching across
`instructions/`, `regression/`, and `artifacts/`.

### What goes in the body

Body shape is convention-only — readers (humans, the QA planner, and
sessions launched on a recipe) read it directly. The author is free to
structure it however the recipe needs, but conventions for each
category:

- **instructions/** — numbered Setup steps, then "Test Steps", then
  "Expected Behavior" / "Reporting" if applicable. Concrete commands
  the reader can copy and run.
- **regression/** — see [Regression tests](#regression-tests).
- **artifacts/** — see [Artifact recipes](#artifact-recipes).

## Regression tests

Files under `pm/qa/regression/` are Claude-driven TUI regression
tests. The body of each `.md` file is **literally a Claude prompt** —
the runner reads it, prepends a small "Session Context" header that
tells Claude how to drive the TUI (`pm tui view`, `pm tui send`),
optionally appends a bug-filing or bug-fixing addendum, and launches
Claude with the assembled prompt. Claude then exercises the running
TUI and reports back.

### Running

```
pm tui test --list                # list available tests
pm tui test pane-layout           # run one
pm tui test pane-layout --file-bugs   # run + open bug PRs for any failures
pm tui test pane-layout --fix-bugs    # run + attempt fixes for any failures
```

`pm tui test` requires an already-running `pm` tmux session — the test
drives the existing TUI rather than spinning up its own.

### Authoring a Claude regression test

1. `pm qa add-instruction <name>` creates a stub in
   `pm/qa/instructions/`. **Move it to `pm/qa/regression/`** if it's
   meant for the regression runner. (There's no `pm qa
   add-regression`; regression tests are an evolved sibling of
   instructions.)
2. Edit the body to read like instructions to a smart, careful tester
   who has never used the feature before. Phrasing convention:
   *"You are pretending to be a brand-new user who has never used pm
   before. … Open the TUI. Verify X. Press Y. Report any bugs."*
3. Use `pm tui send` / `pm tui view` examples in the body so Claude
   knows the available driving primitives. The runner already
   provides these in the prepended Session Context, so you don't have
   to re-explain them — just rely on them.
4. End with a reporting section describing what Claude should output
   (a structured pass/fail per scenario, plus observations).
5. Iterate by running `pm tui test <name>` and reading the report;
   refine the prompt until Claude's reports are crisp and accurate.

### Authoring tips

- Existing tests (`pane-layout`, `init-empty`, etc.) are good style
  references — read a couple before writing your first.
- Keep each test focused on one feature or interaction; long tests
  cost more tokens and produce noisier reports.
- `<test_cwd>` is a documentation placeholder some tests use to mean
  "a fresh empty repo". The runner does **not** substitute it
  programmatically — write your test so Claude treats the placeholder
  as instruction to set up its own scratch directory.

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
that a human reviewer can replay or read.

## Captures

A *capture* is the artifact a recipe produces. Captures live under
`pm/qa/captures/<pr-id>/`, organized by which session created them:

```
pm/qa/captures/<pr-id>/
├── impl/
│   ├── pre-fix/
│   │   ├── recording.cast        # the recording (whatever the recipe produces)
│   │   ├── transcript.log        # optional fallback / supplement
│   │   └── manifest.md           # author-written notes (see below)
│   └── post-fix/
│       └── …
└── scenarios/
    ├── 1/
    │   └── …
    └── 2/
        └── …
```

When a phase needs more than one capture (e.g. two distinct pre-fix
demonstrations), use sub-subdirs: `impl/pre-fix/<short-name>/`.

### Manifest

`manifest.md` rides alongside each capture so a reviewer can read what
they're looking at without replaying. **Nothing in pm reads
manifests** — they're purely human-facing. The convention:

```markdown
---
pr: <pr-id>
workdir: <absolute path the capture came from>
captured_at: <ISO date>
recipe: pm/qa/artifacts/<recipe-filename>.md
---

## Commands

```
<copy-pasteable commands the reviewer can re-run>
```

## What this demonstrates

<one paragraph: what to look for in playback>

## Pre-fix vs post-fix

<which state the capture is from; if both, name both files>
```

Recipes may add their own frontmatter fields (e.g.
`tmux_session`, `test_project`) when relevant — pick what helps the
reviewer reproduce the capture.

## Where each surface reads what

| Surface | What it shows / consumes |
|---|---|
| TUI QA pane (`q`) | All four categories listed by `qa_instructions.list_all` (Instructions, Regression Tests, Artifact Recipes; mocks live in their own pane via `pm qa mocks`). Reads `title`, `description` for display. |
| `pm qa list` | Same three sections as the QA pane. |
| `pm qa show <id>` | Full body of one file; auto-detects category. |
| `pm qa edit <id>` | Opens the file in `$EDITOR`; auto-detects category. |
| `pm qa add-instruction <name>` | Scaffolds a stub in `pm/qa/instructions/`. |
| `pm qa add-artifact <name>` | Scaffolds a stub in `pm/qa/artifacts/`. |
| `pm qa author-instruction <name>` | Same as above, but launches a guided Claude session that uses this document to interview the author. |
| `pm qa author-artifact <name>` | Guided authoring for an artifact recipe. |
| `pm qa docs` | Prints this document. |
| QA planner prompt | `instruction_summary_for_prompt` renders `### Instructions` and `### Artifact Recipes`. Recipes are referenced by filename in the scenario `INSTRUCTION:` field. |
| Scenario 0 prompt | Same library summary, scoped to the interactive session. |
| Bug-fix flow prompt | Points sessions at `pm/qa/instructions/` and `pm/qa/artifacts/` by directory; sessions discover specific files themselves. Captures go under `pm/qa/captures/<pr-id>/impl/pre-fix/` and `…/post-fix/`. |
| Bug-fix review checklist | Tells reviewers to read captures under `pm/qa/captures/<pr-id>/impl/`. |

## Authoring tips

- One sharp `description` (≤ 80 chars) saves more time than a long
  body — that's what people skim in lists.
- For artifact recipes, the manifest format section is the most
  load-bearing part: that's what reviewers will see, so make it
  unambiguous.
- Keep recipes generic across projects when possible. Reference
  project-internal paths only when there's no other way.
- Existing recipes are good style references —
  `pm qa show tui-manual-test`, `pm qa show tmux-screen-recording`,
  `pm qa show cli-recording`.
