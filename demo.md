# pm demo walkthrough

This walks through using `pm` to manage the project-manager project itself.
The source repo is both the tool and the target codebase.

Since this is a GitHub repo, `pm` would auto-select the `github` backend,
which uses `gh pr view` to detect merges. This demo uses `--backend local`
instead so that merge detection works locally without creating real PRs.

## Install

```bash
# Set REPO to wherever you cloned project-manager
REPO=~/project-manager

cd $REPO
./install.sh --local
```

## 1. First-run help and repo detection

Before creating a PM directory, run `pm` from inside the target codebase to
see the help text and repo-specific setup guidance:

```bash
cd $REPO
pm
```

## 2. Initialize the PM directory

By default, `pm init` creates a `pm/` directory inside the current repo.
We pass `--backend local` to override the auto-detected `github` backend
so we can simulate merges locally (see step 10):

```bash
cd $REPO

pm init $REPO \
  --base-branch master \
  --backend local
```

Expected output:
- Creates `pm/` inside the repo
- Shows target repo, base branch, and backend
- Suggests using `pm push` to share changes

Verify the PM directory was created:

```bash
ls pm/
```

You should see `project.yaml` and `plans/`.

Inspect the project config:

```bash
cat pm/project.yaml
```

## 3. Add a plan

```bash
pm plan add "Build the Project Manager tool"
```

Check it was created:

```bash
pm plan list
cat pm/plans/plan-001.md
```

The plan file is a markdown stub — in a real workflow you'd fill it in
with goals, scope, and constraints before using `pm plan review` to
have Claude break it into PRs.

## 4. Add PRs with dependencies

Build a dependency graph in layers. PRs in the same layer can be worked
on in parallel:

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

Each PR gets an auto-generated branch name like `pm/pr-001-core-data-model-and-yaml-store`.

## 5. Explore the graph

```bash
pm pr graph
```

Shows the dependency tree with layer separators. All PRs start as `pending` (⏳).

```bash
pm pr list
```

Shows every PR with its status, dependencies, and assigned machine.

```bash
pm pr ready
```

Should show pr-001, pr-002, pr-003 — they have no unmerged dependencies.

## 6. See what a Claude prompt looks like

```bash
pm prompt pr-001
```

Shows the generated prompt including:
- PR title and plan context
- Task description (empty for now — you'd set it via `--description` on `pm pr add`)
- Guardrails (test-first, verify-before-import)
- Backend-specific instructions (local: commit, tell human to run `pm pr done`)

Try a PR with dependencies to see the dependency context section:

```bash
pm prompt pr-004
```

This one shows the depends-on PRs and their current status.

## 7. Start a PR

This clones the target repo into a workdir and creates a branch:

```bash
pm pr start pr-001
```

It will:
- Clone the target repo into `~/.pm-workdirs/project-manager-<hash>/<branch-slug>-<hash>/`
- Create branch `pm/pr-001-core-data-model-and-yaml-store`
- Mark pr-001 as `in_progress` with your hostname
- Print the full Claude prompt

The workdir path uses the target repo's root commit hash for project
isolation, and the base commit hash for branch isolation.

Note the workdir path from the output — you'll need it for step 10.

Check the status changed:

```bash
pm pr list
```

pr-001 should now show `in_progress` with your hostname.

## 8. Re-generate prompt for a started PR

In a real workflow, you might need to re-generate the prompt — for example,
to hand it to a second Claude session, or after updating the PR description.
`pm prompt` works without cloning:

```bash
pm prompt pr-001
```

## 9. Simulate work and mark done

In a real workflow, you'd open a Claude Code session in the workdir
and paste the prompt. For the demo, we'll just mark it done:

```bash
pm pr done pr-001
pm pr list
```

pr-001 is now `in_review` (👀).

## 10. Simulate a merge and sync

To exercise `pm pr sync`, we need the branch to be merged into master
in the workdir. The branch was just created from master so it has no
new commits yet — make a dummy commit, then merge it.

Use the workdir path printed by `pm pr start` in step 7:

```bash
# The glob matches the workdir created in step 7
cd ~/.pm-workdirs/project-manager-*/pm-pr-001-*

git checkout pm/pr-001-core-data-model-and-yaml-store
touch demo-file.txt && git add demo-file.txt && git commit -m "demo work"
git checkout master
git merge pm/pr-001-core-data-model-and-yaml-store
```

Now go back to the repo and sync:

```bash
cd $REPO
pm pr sync
```

Expected output:
- `✅ pr-001: merged`
- Lists newly ready PRs (those whose dependencies are now all merged)

Check what's now unblocked:

```bash
pm pr list
pm pr ready
```

pr-005 should now show as ready (its only dependency was pr-001).
pr-002 and pr-003 were already ready (no dependencies).
pr-004 is still blocked — it depends on pr-001, pr-002, and pr-003.

## 11. Push pm state

After making changes, use `pm push` to commit them:

```bash
pm push
```

With the `local` backend, this creates a `pm/sync-<timestamp>` branch
with the pm/ changes committed. Merge it to apply (use the branch name
from the output):

```bash
git merge pm/sync-<timestamp>
```

## 12. Start parallel work

Start multiple PRs at once — each gets its own workdir:

```bash
pm pr start pr-002
pm pr start pr-003
pm pr list
```

All started PRs should show `in_progress` with your hostname. Each has
its own workdir under `~/.pm-workdirs/project-manager-<hash>/`.

Check the workdir structure:

```bash
ls ~/.pm-workdirs/project-manager-*/
```

You should see separate directories for each branch, named
`<branch-slug>-<base-commit-hash>`.

## 13. Clean up a merged PR's workdir

After pr-001 was merged in step 10, its workdir is no longer needed:

```bash
pm pr cleanup pr-001
```

This removes the workdir and clears the path from project.yaml.

Verify:

```bash
ls ~/.pm-workdirs/project-manager-*/
pm pr list
```

pr-001's workdir is gone. The other two are still there.

## 14. Add a second plan with cross-plan dependencies

Plans are independent scopes of work, but PRs can depend on PRs from
any plan:

```bash
pm plan add "Harden and polish for real use"
pm pr add "Add unit tests" --plan plan-002 --depends-on "pr-001,pr-002"
pm pr add "Error handling" --plan plan-002 --depends-on pr-004
pm pr add "Shell completion" --plan plan-002 --depends-on pr-004
```

Check the expanded graph — it now spans both plans:

```bash
pm pr graph
pm plan list
pm pr list
```

## 15. Use plan review to decompose with Claude

```bash
pm plan review plan-002
```

This prints a prompt designed for pasting into a Claude session. It includes:
- The plan content (from `pm/plans/plan-002.md`)
- All existing PRs and their statuses (so Claude doesn't duplicate work)
- Output format instructions (YAML list of PRs with dependencies)

In a real workflow, you'd:
1. Edit `pm/plans/plan-002.md` to describe what "Harden and polish" means
2. Run `pm plan review plan-002` and paste the output to Claude
3. Claude outputs `pm pr add` commands which you paste back into the terminal

## 16. Working from other directories

`pm` auto-detects `pm/` walking up from cwd. You can also use `-C`:

```bash
cd /tmp
pm -C $REPO/pm pr list
pm -C $REPO/pm pr ready
```

Or set it once per shell session:

```bash
export PM_PROJECT=$REPO/pm
pm pr list
pm pr ready
```

## 17. Clean up the demo

```bash
cd $REPO
rm -rf pm/
rm -rf ~/.pm-workdirs/project-manager-*
```

## Tips

- **Mutations only write files** — no auto-commits. Use `pm push` to share.
- **`pm push`** creates a branch with pm/ changes (and pushes/creates PR for github backend)
- **`pm pr ready`** is the key command — run it after every sync
- **`pm pr start`** does the full setup: clone, branch, prompt generation
- **`pm prompt`** regenerates the prompt without cloning (for re-runs)
- **`--description`** on `pm pr add` fills in the Task section of the Claude prompt
- **Workdir naming**: `~/.pm-workdirs/<project>-<root-hash>/<branch>-<base-hash>/`
  ensures no collisions across projects or branches
- **Backends**: `local` for no remote, `vanilla` for git with remote, `github` for GitHub repos
