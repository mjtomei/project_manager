# pm demo walkthrough

This walks through using `pm` to manage the project-manager project itself.
The source repo at `/home/matt/claude-work/project-manager` is both the
tool and the target codebase. Uses the vanilla backend — no GitHub CLI required.

Every command below is runnable.

## Install

```bash
cd /home/matt/claude-work/project-manager
./install.sh
export PATH="$HOME/.local/bin:$PATH"
```

## 1. Initialize the PM repo

From the project-manager source repo, run `pm` to see help with
repo-specific guidance. Then create the PM repo using the local path
as the target:

```bash
pm init /home/matt/claude-work/project-manager --base-branch master --backend vanilla
```

This creates `project-manager-pm/` next to the source repo. cd into it:

```bash
cd project-manager-pm
```

## 2. Add a plan

```bash
pm plan add "Build the Project Manager tool"
```

Check it:

```bash
pm plan list
cat plans/plan-001.md
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
pm pr graph
pm pr list
pm pr ready
```

`pr ready` should show pr-001, pr-002, pr-003 — they have no dependencies.

## 5. See what a Claude prompt looks like

```bash
pm prompt pr-001
```

Shows the generated prompt with context, guardrails, and vanilla
backend instructions (push branch, let human handle merge).

## 6. Start a PR

This clones the target repo into a workdir and creates a branch:

```bash
pm pr start pr-001
```

It will:
- Clone `/home/matt/claude-work/project-manager` into `~/.pm-workdirs/project-manager/pr-001/`
- Create branch `pm/pr-001-core-data-model`
- Mark pr-001 as `in_progress` with your hostname
- Print the Claude prompt

Check the status changed:

```bash
pm pr list
```

## 7. Simulate work and mark done

In a real workflow, you'd open a Claude Code session in the workdir
and paste the prompt. For the demo, we'll just mark it done:

```bash
pm pr done pr-001
pm pr list
```

pr-001 is now `in_review`.

## 8. Simulate a merge and sync

To exercise `pm pr sync`, we need the branch to be merged into master
in the workdir. The branch was just created from master so it has no
new commits yet — make a dummy commit, then merge it:

```bash
cd ~/.pm-workdirs/project-manager/pr-001
git checkout pm/pr-001-core-data-model
touch demo-file.txt && git add demo-file.txt && git commit -m "demo work"
git checkout master
git merge pm/pr-001-core-data-model
```

Now go back to the PM repo and sync:

```bash
cd -
pm pr sync
```

pm detects that pr-001's branch is merged into master and updates
its status. Check what's now unblocked:

```bash
pm pr list
pm pr ready
```

pr-002 should now show as ready (it had no deps). pr-003 is still
blocked because it depends on both pr-001 and pr-002.

## 9. Start parallel work

Start multiple PRs at once — each gets its own workdir:

```bash
pm pr start pr-002
pm pr start pr-003
pm pr list
```

All three should show different workdirs and `in_progress` status.

## 10. Add a second plan

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

## 11. Use plan review to decompose with Claude

```bash
pm plan review plan-002
```

This prints a prompt designed for Claude to break the plan into PRs.
You'd paste Claude's output back as `pm pr add` commands.

## 12. Working from other directories

You don't need to stay in the PM repo:

```bash
# One-off from the source repo
cd /home/matt/claude-work/project-manager
pm -C /home/matt/claude-work/project-manager-pm pr list

# Or set it once per shell
export PM_PROJECT=/home/matt/claude-work/project-manager-pm
pm pr list
pm pr graph
pm pr ready
```

## 13. Clean up workdirs

After a PR is merged and you're done with the workdir:

```bash
pm pr cleanup pr-001
```

## Tips

- **All mutations auto-commit** to the PM repo's git history
- **Multi-machine**: push the PM repo to a remote, clone on other machines
- **`pm pr ready`** is the key command — run it after every sync
- **`pm pr start`** does the full setup: clone, branch, prompt generation
- **`pm prompt`** regenerates the prompt without cloning (for re-runs)
- **Backends**: vanilla is auto-detected for non-GitHub URLs; use `--backend github` to override
