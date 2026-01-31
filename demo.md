# pm demo walkthrough

This walks through using `pm` to manage the project-manager project itself.

## Prerequisites

```bash
# Install pm
./install.sh

# Make sure ~/.local/bin is on your PATH
export PATH="$HOME/.local/bin:$PATH"

# Verify
pm help
```

## 1. Create the PM repo

The PM repo is separate from the source code. It holds only project state.

```bash
# From anywhere — this creates a new directory
pm init git@github.com:org/project-manager.git --name project-manager --base-branch master

# It creates project-manager-pm/ with a git repo inside
cd project-manager-pm
```

## 2. Add a plan

```bash
pm plan add "Build the Project Manager tool"
```

This creates `plans/plan-001.md` — edit it to describe the plan:

```bash
cat plans/plan-001.md
# Edit it with your editor if you want
```

## 3. Add PRs with dependencies

```bash
# Layer 0: no dependencies, can all be worked in parallel
pm pr add "Core data model and YAML store" --plan plan-001
pm pr add "Dependency graph logic" --plan plan-001
pm pr add "Git and GitHub operations" --plan plan-001

# Layer 1: depends on the foundations
pm pr add "CLI commands" --plan plan-001 --depends-on "pr-001,pr-002,pr-003"
pm pr add "Prompt generation with guardrails" --plan plan-001 --depends-on pr-001

# Layer 2+
pm pr add "TUI tech tree widget" --plan plan-001 --depends-on pr-002
pm pr add "TUI detail panel and command bar" --plan plan-001 --depends-on pr-006
pm pr add "TUI app shell and background sync" --plan plan-001 --depends-on "pr-004,pr-007"
```

## 4. View the graph

```bash
pm pr graph
```

You should see a layered dependency tree with status icons.

## 5. See what's ready

```bash
pm pr ready
```

Should show pr-001, pr-002, pr-003 — they have no dependencies.

## 6. List everything

```bash
pm pr list
```

Shows all PRs with status, dependencies, and which machine is working on them.

## 7. Start a PR

```bash
pm pr start pr-001
```

This will:
- Clone the target repo into `~/.pm-workdirs/project-manager/pr-001/`
- Create branch `pm/pr-001-core-data-model`
- Mark it `in_progress` with your hostname
- Print a Claude Code prompt with context, guardrails, and instructions

Copy that prompt into a Claude Code session in the workdir.

## 8. Start parallel work

On the same or different machine:

```bash
pm pr start pr-002
pm pr start pr-003
```

Each gets its own workdir and branch. `pm pr list` shows all three in_progress.

## 9. Mark work done

After Claude finishes and pushes a PR:

```bash
pm pr done pr-001
```

Marks it `in_review`.

## 10. Sync merges from GitHub

After PRs get reviewed and merged on GitHub:

```bash
pm pr sync
```

This checks GitHub for merged PRs, updates their status, and shows you
which PRs are now unblocked.

## 11. Get a prompt without starting

If you already have a workdir set up:

```bash
pm prompt pr-004
```

Just prints the prompt — useful for re-running or pasting into a new session.

## 12. Add a second plan

```bash
pm plan add "Harden and polish for real use"
pm pr add "Add unit tests" --plan plan-002 --depends-on "pr-001,pr-002"
pm pr add "Error handling" --plan plan-002 --depends-on pr-004
pm pr add "Shell completion" --plan plan-002 --depends-on pr-004
```

Now `pm pr graph` shows a bigger tree spanning both plans.

## 13. Clean up

After a PR is merged and you don't need the workdir:

```bash
pm pr cleanup pr-001
```

## 14. Use plan review to decompose with Claude

```bash
pm plan review plan-002
```

This prints a prompt you can paste into Claude. Claude outputs YAML-formatted
PRs with dependencies that you can then add with `pm pr add`.

## Tips

- **From anywhere**: use `pm -C /path/to/pm-repo` or `export PM_PROJECT=/path/to/pm-repo`
- **Multi-machine**: push the PM repo to GitHub, clone on other machines
- **All mutations auto-commit**: every `pm` command that changes state commits and pushes
- **Check `pm pr ready`** after each sync to see what's unblocked
