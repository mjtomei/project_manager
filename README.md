# pm — Project Manager for Claude Code sessions

A CLI tool that manages a dependency graph of PRs derived from plans,
orchestrates parallel Claude Code sessions across machines, and tracks
progress through an interactive terminal dashboard.

## The idea

Development is changing. When you can spin up dozens of AI agents working
in parallel, the bottleneck shifts from writing code to managing complexity.
The developer's job becomes less about picking one small task and grinding
through it, and more about seeing the entire project, understanding what
matters, and directing attention where it counts.

`pm` is built around this shift. It gives every developer a shared tech
tree — a dependency graph of everything that needs to happen. You look at
the tree, see what's ready, and click the thing you want to work on next.
Your attention is your vote for what gets built. Everyone sees the same
graph. Everyone sees what's in progress, what's blocked, and what just
landed.

Think Civilization's tech tree, but for your codebase, and everyone on
the team shares it.

## Pluggable backends

The interfaces we use to work with code — pull requests, CI checks, merge
buttons — were designed for humans working at human speeds, one task at a
time. They won't be the interfaces we use forever. As machine intelligences
become real contributors to codebases, teams will build version control
workflows that suit both humans and machines: faster merge cycles,
machine-readable status, automated dependency resolution, interfaces that
can handle dozens of concurrent contributors without friction.

`pm` prepares for this by abstracting git hosting behind a minimal pluggable
interface. A backend needs exactly two methods: detect if a branch is merged,
and generate instructions for the agent doing the work. Today there are two:

- **vanilla** — pure git, no external tools. Merge detection via
  `git branch --merged`. Works with any git remote: self-hosted,
  Gitea, Forgejo, bare repos, local repos, anything.

- **github** — uses the `gh` CLI for PR creation and merge detection.
  Auto-selected when the target repo is on github.com.

The backend is auto-detected from the remote URL at `pm init` time.
Override with `--backend`. To add a new one, subclass `Backend` in
`pm_core/backend.py` and implement two methods.

## Architecture

**Two repos, cleanly separated:**

- **PM repo** — a dedicated git repo containing `project.yaml` and `plans/`.
  This is the source of truth for project state. Only PMs touch it directly.
  Auto-committed on every mutation, pushed for multi-machine sync.

- **Target repo** — the actual codebase where code PRs go. Contributors
  (human or AI) interact with it normally. They never touch the PM repo.

This separation means contributors can work however they want — through
PRs, direct pushes, or any other workflow — without interfering with
project management state. It also means the PM repo is access-controlled:
the people steering the project are the only ones who can change the plan.

## Install

```bash
git clone <this-repo>
cd project-manager
./install.sh
```

Add `~/.local/bin` to your PATH if it isn't already.

## Quick start

```bash
# From your target codebase repo:
pm

# This detects your repo and prints a tailored pm init command.
# Run it, then cd into the new PM repo.

# Add a plan and break it into PRs:
pm plan add "Add authentication"
pm pr add "Add user model" --plan plan-001
pm pr add "Auth middleware" --plan plan-001 --depends-on pr-001

# See the graph:
pm pr graph

# Start working:
pm pr start pr-001    # clones, branches, prints Claude prompt

# When done:
pm pr done pr-001     # marks in_review

# Check for merges:
pm pr sync            # detects merged branches, unblocks dependents
```

See [demo.md](demo.md) for a full walkthrough.

## Commands

```
pm init <repo-url>            Create PM repo for a target codebase
pm plan add <name>            Add a plan
pm plan list                  List plans
pm plan review <plan-id>      Generate prompt to decompose plan into PRs
pm pr add <title>             Add a PR  [--plan, --depends-on, --description]
pm pr list                    List PRs with status
pm pr graph                   Show dependency tree
pm pr ready                   Show PRs ready to start
pm pr start <pr-id>           Clone, branch, print Claude prompt
pm pr done <pr-id>            Mark PR as in_review
pm pr sync                    Check for merged PRs
pm pr cleanup <pr-id>         Remove workdir for merged PR
pm prompt <pr-id>             Print Claude prompt for a PR
pm tui                        Launch interactive dashboard
```

## Requirements

- Python 3.12+
- click, pyyaml, textual (installed via `pip install -r requirements.txt`)
- `gh` CLI only if using the github backend
