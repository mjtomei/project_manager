# pm demo walkthrough

This walks through using `pm` to manage the project-manager project itself.
The source repo is both the tool and the target codebase. It uses the vanilla
git backend and doesn't require the Github CLI.

## Install

```bash
# Set REPO to wherever you cloned project-manager
REPO=~/project-manager

cd $REPO
./install.sh --local
```

## 1. First-run help and repo detection

Before creating a PM repo, run `pm` from inside the target codebase to
see the help text and repo-specific setup guidance:

```bash
cd $REPO
pm
```

Since no PM repo exists yet, this prints the full help text followed by
detected repo information and a suggested `pm init` command. The backend
(vanilla or github) is auto-detected from the remote URL.

Also try the explicit help variants — all three should produce the same output:

```bash
pm help
pm -h
```

## 2. Initialize the PM repo

Use the init command suggested by the help output, or run this directly.
The `--dir` flag places the PM repo next to (not inside) the source repo:

```bash
PM_REPO=${REPO}-pm

pm init $REPO \
  --base-branch master \
  --backend vanilla \
  --dir $PM_REPO
```

Expected output:
- Creates a new git repo at the PM repo path
- Shows target repo, base branch, and backend
- Suggests how to add a remote for multi-machine sync

Verify the PM repo was created:

```bash
cd $PM_REPO
ls
```

You should see `project.yaml` and `plans/`. Check that it's a git repo
with an initial commit:

```bash
git log --oneline
```

Inspect the project config:

```bash
cat project.yaml
```

## 3. Add a plan

```bash
pm plan add "Build the Project Manager tool"
```

Check it was created:

```bash
pm plan list
cat plans/plan-001.md
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
- Backend-specific instructions (vanilla: push branch, tell human to run `pm pr done`)

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

Now go back to the PM repo and sync:

```bash
cd $PM_REPO
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

## 11. Start parallel work

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

## 12. Clean up a merged PR's workdir

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

## 13. Add a second plan with cross-plan dependencies

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

## 14. Use plan review to decompose with Claude

```bash
pm plan review plan-002
```

This prints a prompt designed for pasting into a Claude session. It includes:
- The plan content (from `plans/plan-002.md`)
- All existing PRs and their statuses (so Claude doesn't duplicate work)
- Output format instructions (YAML list of PRs with dependencies)

In a real workflow, you'd:
1. Edit `plans/plan-002.md` to describe what "Harden and polish" means
2. Run `pm plan review plan-002` and paste the output to Claude
3. Claude outputs `pm pr add` commands which you paste back into the terminal

## 15. Working from other directories

You don't have to stay in the PM repo. Use `-C` or `PM_PROJECT`:

```bash
# One-off from the target source repo
cd $REPO
pm -C $PM_REPO pr list
pm -C $PM_REPO pr ready
pm -C $PM_REPO pr graph
```

Or set it once per shell session:

```bash
export PM_PROJECT=$PM_REPO
pm pr list
pm pr ready
```

## 16. Verify auto-commit history

Every mutation to project state is auto-committed in the PM repo's git history:

```bash
cd $PM_REPO
git log --oneline
```

You should see commits for every `pm plan add`, `pm pr add`, `pm pr start`,
`pm pr done`, `pm pr sync`, and `pm pr cleanup` command you ran.

## 17. Clean up the demo

```bash
rm -rf $PM_REPO
rm -rf ~/.pm-workdirs/project-manager-*
```

## Tips

- **All mutations auto-commit** to the PM repo's git history
- **Multi-machine**: push the PM repo to a remote, clone on other machines
- **`pm pr ready`** is the key command — run it after every sync
- **`pm pr start`** does the full setup: clone, branch, prompt generation
- **`pm prompt`** regenerates the prompt without cloning (for re-runs)
- **`--description`** on `pm pr add` fills in the Task section of the Claude prompt
- **Workdir naming**: `~/.pm-workdirs/<project>-<root-hash>/<branch>-<base-hash>/`
  ensures no collisions across projects or branches
- **Backends**: vanilla is auto-detected for non-GitHub URLs; use `--backend github` to override
