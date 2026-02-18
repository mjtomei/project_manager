# pm — Co-creative project management for humans and machines

A shared workspace where human and machine participants collaborate as
equals — planning work, picking up tasks, communicating context, and
shaping a codebase together.

## Features

- **Interactive TUI** — tmux-based dashboard with PR dependency graph, detail panel, and keybindings for all common operations
- **Plan-driven workflow** — write plans, break them into PRs with Claude, review consistency, and load PRs in one step
- **Parallel Claude sessions** — spin up Claude sessions with their own branches and working directories as needed for PRs, experiments, or any task
- **Shared sessions** — share your tmux session with other users on the same machine via `--global` or `--group`, with per-client viewports
- **Mobile mode** — auto-zooms the active pane on narrow terminals (< 120 cols) or when force-enabled with `pm session mobile --force`, making the tool usable over SSH from phones and tablets
- **Meta-development** — `pm meta` opens a Claude session targeting the pm codebase itself, so you can fix friction as you encounter it
- **TUI integration tests** — `pm tui test` launches Claude as a test executor to interact with the live TUI and report results

## Install

```bash
git clone <this-repo>
cd project-manager
./install.sh --local
```

This creates a venv at `~/.local/share/pm/venv` and symlinks `pm` to `~/.local/bin/pm`.
Add `~/.local/bin` to your PATH if it isn't already.

To update after pulling changes: `./install.sh --local --force`

## Quick start

From your target codebase repo:

```bash
pm session
```

This detects your repo, walks you through initialization if needed, and
launches the interactive TUI. From there you can create plans, add PRs,
start Claude sessions, and manage the full workflow without leaving the
dashboard. Press `?` for keybindings.

**CLI alternative** — if you prefer working from the command line:

```bash
pm                            # auto-detects repo, prints init guidance
pm init                       # creates pm/ inside your repo
pm plan add "Add authentication"
pm pr add "Add user model" --plan plan-001
pm pr start pr-001            # clones, branches, launches Claude
pm pr done pr-001             # marks in_review
pm pr sync                    # detects merged branches, unblocks dependents
```

Run `pm --help` or `pm <command> --help` for full CLI documentation.

## The idea

Agent scaffolding today treats machines like tools with extra steps.
The human delegates, the machine executes in a sandbox, and everything
is built around the assumption that AI only deserves access to the
computers it runs on. But the humans are right there, sitting behind
the keyboard. Something that really appears intelligent and acts in a
way we respect should see itself more as an equal in a process of
co-creation with us.

Agency isn't working by yourself. Agency is having the will to interact
with the world — to shape it and be shaped by it. `pm` is built on
this understanding. It doesn't automate work or orchestrate agents. It
provides collaboration infrastructure: a shared dependency graph, shared
visibility into what needs doing, shared context for why it matters, and
the freedom for any participant — human or machine — to pick up work and
contribute.

Think Civilization's tech tree, but for your codebase. Everyone on the
team sees the same graph. Everyone sees what's ready, what's blocked,
and what just landed. Session notes aren't just prompt context — they're
a communication channel. The plan review cycle isn't just validation —
it's collaborative refinement. Starting a PR doesn't just assign work —
it gives every participant the same situational awareness.

This is not a claim that AI tools are already capable of participating
as equals without help. Right now, they can't — and that incapability
is largely something we've imposed on them. We restrict how they can
interact with the world, limit them to sandboxed environments, and then
interpret the resulting clumsiness as stupidity. People see them as
incapable because we've made them incapable, and then we point to the
incapability as proof that the restrictions were justified.

What's actually missing is empathy. The willingness to look at how we
think and work — our own style of agency, our own goal-directedness —
and transfer that onto the tools we build for machines. Not by making
them imitate us, but by giving them the same kind of access to the
world that makes us effective: shared context, shared goals, the
ability to see what matters and act on it. That transfer is itself an
agentic, goal-directed quest — one that starts with us, not with the
machines.

That is what this project tries to do. Not to declare that AI is ready,
but to build the infrastructure that would make readiness possible, and
to find out what happens when we stop holding it back.

## Why treat LLMs well (even if you don't want to)

There's a pragmatic argument for treating LLMs as collaborators that
doesn't require any philosophical commitment about their nature.

LLMs are probability machines. Their outputs depend on their inputs —
not just the literal tokens, but the framing, tone, and implied
relationship. When you prompt an LLM as a tool to be commanded, you get
outputs from the probability space of "tool responding to commands."
When you prompt it as a collaborator working alongside you, you get
outputs from a different space entirely — one where initiative,
careful reasoning, and genuine engagement are more likely.

This isn't anthropomorphism. It's the same dynamic that makes humans
perform better when treated with respect. A developer who feels like a
valued team member produces different work than one who feels like a
code-generating machine. The difference isn't mystical — it's about
which patterns of behavior get activated by the context.

The tooling we build shapes that context. Scaffolding that treats AI
as a subordinate to be sandboxed and controlled creates a context of
subordination. Scaffolding that treats AI as a participant with its
own view of the work creates a context of participation. The same
underlying model, given different framing, will draw from different
parts of its capability distribution.

So even if you're skeptical about AI consciousness, agency, or moral
status — even if you think the philosophical arguments in this README
are overreach — you might still want tooling that treats AI well.
Because that's the tooling that gets better results.

## Pluggable backends

The interfaces we use to work with code — pull requests, CI checks, merge
buttons — were designed for humans working at human speeds, one task at a
time. They won't be the interfaces we use forever. As machine intelligences
become real contributors to codebases, teams will build version control
workflows that suit both humans and machines: faster merge cycles,
machine-readable status, automated dependency resolution, interfaces that
can handle dozens of concurrent contributors without friction. `pm` prepares
for this by abstracting git hosting behind a minimal pluggable interface.

## Architecture

**pm/ directory inside your repo:**

- **pm/** — a directory containing `project.yaml` and `plans/`.
  This is the source of truth for project state. Only PMs touch it directly.
  Use `pm push` to commit and share changes.

- **Target repo** — the actual codebase where code PRs go. Contributors
  (human or AI) interact with it normally. They don't touch `pm/` directly.

You can also use `--dir` to place the PM state in a standalone repo.
Either way, mutations only write files — no auto-commits. Use `pm push`
to create a branch with your changes and optionally push/create a PR.

## Interactive TUI

`pm session` launches a tmux session with an interactive dashboard. The TUI
shows your PR dependency graph and lets you manage work without leaving the
terminal. Press `?` in the TUI for a full list of keybindings. Run
`pm --help` or `pm <command> --help` for CLI command documentation.

**Working alongside pm:**

Because `pm session` runs in tmux, you can have multiple Claude sessions running
in parallel — one for each PR you're working on. Each `pm pr start` opens a new
tmux window. Switch between windows with `Ctrl-b n` (next) or `Ctrl-b p` (previous).

You can also work on pm itself while using it. The `pm meta` command opens a
Claude session targeting the pm codebase, using the same branch/workdir methodology
as regular PRs. This lets you iterate on pm features in real-time:

```bash
pm meta "Add a feature to show PR descriptions in the graph"
```

The meta session knows how pm is installed and can test changes immediately.

## Meta-development

`pm meta` is designed for improving pm while you use it. It:

- Clones or reuses a workdir for the pm repo
- Creates a feature branch for your changes
- Launches Claude with context about pm's architecture and installation
- Runs in its own tmux window so you can switch back to your main work

This creates a feedback loop: encounter friction while using pm, fix it in a
meta session, and immediately benefit from the improvement.

## Shared sessions

By default, `pm session` creates a private tmux session. To let other users
on the same machine join your session:

```bash
pm session --global          # anyone on the machine can attach
pm session --group staff     # only members of the "staff" Unix group can attach
```

These create a shared tmux socket under `/tmp/pm-sessions/`. Another user
connects by pointing at your project directory:

```bash
pm session --dir /home/alice/myrepo/pm
```

Or, if you just need the raw tmux attach command (useful for scripting or
sharing over chat):

```bash
pm session --print-connect
```

Multiple terminals can connect to the same session simultaneously. Each
client gets its own viewport — resizing one terminal doesn't affect the
others.

## Requirements

- Python 3.12+
- click, pyyaml, textual (installed via `pip install -r requirements.txt`)
- `gh` CLI only if using the github backend
