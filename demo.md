# pm demo walkthrough

This walks through using `pm` to manage the project-manager project itself.
Uses the vanilla backend — no GitHub CLI required.

## Install

```bash
./install.sh

# Make sure ~/.local/bin is on your PATH
export PATH="$HOME/.local/bin:$PATH"
```

## 1. Get repo-specific setup instructions

From the project-manager source repo, run:

```bash
pm
```

Since there's no PM repo yet, this prints the help message. At the bottom
it detects your git repo and prints the exact `pm init` command with your
remote URL, branch, and auto-detected backend pre-filled. Run that command.

Then `cd` into the PM repo directory it created.

## 2. Add a plan

```bash
pm plan add "Build the Project Manager tool"
```

This creates `plans/plan-001.md`. Edit it to describe the plan:

```bash
cat plans/plan-001.md
```

Check it was tracked:

```bash
pm plan list
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

## 4. Explore the graph

```bash
# Dependency tree
pm pr graph

# All PRs with status
pm pr list

# What can be started right now
pm pr ready
```

`pr ready` should show pr-001, pr-002, pr-003 — they have no dependencies.

## 5. See what a Claude prompt looks like

```bash
pm prompt pr-001
```

Shows the generated prompt with context, dependency status, guardrails,
and instructions. With the vanilla backend, instructions tell Claude to
push the branch and let the human handle the merge.

## 6. Simulate a PR lifecycle

Since we don't have the real target repo to clone, we can still exercise
the state transitions:

```bash
# Mark pr-001 as done (normally you'd run pm pr start first)
pm pr done pr-001

# Check status changed
pm pr list
```

pr-001 is now `in_review`. To simulate a merge, edit project.yaml and
set pr-001's status to `merged`, then check what's unblocked:

```bash
# After editing project.yaml:
pm pr ready
```

With a real repo and workdir, `pm pr sync` would detect the merge
automatically via `git branch --merged`.

## 7. Add a second plan

```bash
pm plan add "Harden and polish for real use"
pm pr add "Add unit tests" --plan plan-002 --depends-on "pr-001,pr-002"
pm pr add "Error handling" --plan plan-002 --depends-on pr-004
pm pr add "Shell completion" --plan plan-002 --depends-on pr-004
```

Check the expanded graph:

```bash
pm pr graph
pm pr list
```

## 8. Use plan review to decompose with Claude

```bash
pm plan review plan-002
```

This prints a prompt designed for Claude to break the plan into PRs with
dependencies in YAML format. You'd paste Claude's output back as
`pm pr add` commands.

## 9. Check ready PRs across plans

```bash
pm pr ready
```

Shows all PRs across both plans whose dependencies are satisfied.

## 10. Working from other directories

You don't need to stay in the PM repo. From anywhere:

```bash
# One-off
pm -C /path/to/project-manager-pm pr list

# Or set it once per shell
export PM_PROJECT=/path/to/project-manager-pm
pm pr list
pm pr graph
```

## Tips

- **All mutations auto-commit** to the PM repo's git history
- **Multi-machine**: push the PM repo to a remote, clone on other machines
- **`pm pr ready`** is the key command — run it after every sync to see what's actionable
- **`pm pr start`** does the full setup: clone, branch, prompt generation
- **`pm prompt`** regenerates the prompt without cloning (for re-runs)
- **Backends**: vanilla is auto-detected for non-GitHub URLs; use `--backend github` to override
