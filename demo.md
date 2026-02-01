# pm demo walkthrough

This walks through using `pm` to manage the project_manager project itself.
The source repo is both the tool and the target codebase.

Since this is a GitHub repo, `pm` would auto-select the `github` backend,
which uses `gh pr view` to detect merges. This demo uses `--backend local`
instead so that merge detection works locally without creating real PRs.

## Install

```bash
# Set REPO to wherever you cloned project_manager
git clone https://github.com/mjtomei/project_manager.git
REPO=$(pwd)/project_manager

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

`pm init` auto-detects the repo URL and base branch from cwd. We only need
to override `--backend local` so we can simulate merges locally (step 10):

```bash
cd $REPO
pm init --backend local
```

Expected output:
- Creates `pm/` inside the repo
- Shows auto-detected target repo, base branch, and backend
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
on in parallel. Since there's only one plan, `--plan` is inferred
automatically. Each PR becomes the **active PR** when created:

```bash
# Layer 0: no dependencies, can all be worked in parallel
pm pr add "Core data model and YAML store"
pm pr add "Dependency graph logic"
pm pr add "Git and GitHub operations"

# Layer 1: depends on the foundations
pm pr add "CLI commands" --depends-on "pr-001,pr-002,pr-003"
pm pr add "Prompt generation with guardrails" --depends-on pr-001

# Layer 2+
pm pr add "TUI tech tree widget" --depends-on pr-002
pm pr add "TUI detail panel and command bar" --depends-on pr-006
pm pr add "TUI app shell and background sync" --depends-on "pr-004,pr-007"
```

Each PR gets an auto-generated branch name like `pm/pr-001-core-data-model-and-yaml-store`.
The last one created (pr-008) is now the active PR.

## 5. Explore the graph

```bash
pm pr graph
```

Shows the dependency tree with layer separators. All PRs start as `pending`.

```bash
pm pr list
```

Shows every PR with its status, dependencies, and assigned machine.
The active PR is marked with `*`.

```bash
pm pr ready
```

Should show pr-001, pr-002, pr-003 — they have no unmerged dependencies.

## 6. Set the active PR and see its prompt

Use `pm pr select` to focus on a specific PR:

```bash
pm pr select pr-001
pm pr list
```

pr-001 is now marked with `*`. Since it's the active PR, `pm prompt`
targets it automatically:

```bash
pm prompt
```

Shows the generated prompt including:
- PR title and plan context
- Task description (empty for now — you'd set it via `--description` on `pm pr add`)
- Guardrails (test-first, verify-before-import)
- Backend-specific instructions (local: commit, tell human to run `pm pr done`)

Try viewing a prompt for a PR with dependencies:

```bash
pm prompt pr-004
```

This one shows the depends-on PRs and their current status.

## 7. Start the active PR

Since pr-001 is the active PR and it's pending, `pm pr start` picks it up:

```bash
pm pr start
```

It will:
- Clone the target repo into `~/.pm-workdirs/project_manager-<hash>/<branch-slug>-<hash>/`
- Create branch `pm/pr-001-core-data-model-and-yaml-store`
- Mark pr-001 as `in_progress` with your hostname
- Print the full Claude prompt

Note the workdir path from the output — you'll need it for step 10.

Check the status changed:

```bash
pm pr list
```

pr-001 should now show `in_progress` with your hostname, still marked `*`.

## 8. Re-generate prompt for the active PR

In a real workflow, you might need to re-generate the prompt — for example,
to hand it to a second Claude session, or after updating the PR description.
The active PR means no argument needed:

```bash
pm prompt
```

## 9. Mark the active PR done

In a real workflow, you'd open a Claude Code session in the workdir
and paste the prompt. For the demo, we'll just mark it done. Since
pr-001 is active and in_progress, no argument needed:

```bash
pm pr done
pm pr list
```

pr-001 is now `in_review`.

## 10. Simulate a merge and sync

To exercise `pm pr sync`, we need the branch to be merged into master
in the workdir. The branch was just created from master so it has no
new commits yet — make a dummy commit, then merge it.

Use the workdir path printed by `pm pr start` in step 7:

```bash
# The glob matches the workdir created in step 7
cd ~/.pm-workdirs/project_manager-*/pm-pr-001-*

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
- `pr-001: merged`
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

Select and start multiple PRs — each gets its own workdir:

```bash
pm pr start pr-002
pm pr start pr-003
pm pr list
```

All started PRs should show `in_progress` with your hostname. pr-003 is
now the active PR (last started). Each has its own workdir under
`~/.pm-workdirs/project_manager-<hash>/`.

Check the workdir structure:

```bash
ls ~/.pm-workdirs/project_manager-*/
```

You should see separate directories for each branch, named
`<branch-slug>-<base-commit-hash>`.

## 13. Clean up a merged PR's workdir

After pr-001 was merged in step 10, its workdir is no longer needed.
Since it's the only merged PR with a workdir, no argument needed:

```bash
pm pr cleanup
```

This removes the workdir and clears the path from project.yaml.

Verify:

```bash
ls ~/.pm-workdirs/project_manager-*/
pm pr list
```

pr-001's workdir is gone. The other two are still there.

## 14. Add a second plan with cross-plan dependencies

Plans are independent scopes of work, but PRs can depend on PRs from
any plan. Note: with two plans, `--plan` must be specified explicitly:

```bash
pm plan add "Harden and polish for real use"
pm pr add "Add unit tests" --plan plan-002 --depends-on "pr-001,pr-002"
pm pr add "Error handling" --plan plan-002 --depends-on pr-004
pm pr add "Shell completion" --plan plan-002 --depends-on pr-004
```

pr-011 (Shell completion) is now the active PR.

Check the expanded graph — it now spans both plans:

```bash
pm pr graph
pm plan list
pm pr list
```

## 15. Use plan review to decompose with Claude

With two plans, specify which one to review:

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
rm -rf ~/.pm-workdirs/project_manager-*
```

## Tips

- **Active PR** — the last created or started PR. Used as default for most commands.
  Change it with `pm pr select <pr-id>`. Shown as `*` in `pm pr list`.
- **Most arguments are optional** — pm infers from active PR, cwd, or single matches
- **Mutations only write files** — no auto-commits. Use `pm push` to share.
- **`pm push`** creates a branch with pm/ changes (and pushes/creates PR for github backend)
- **`pm pr ready`** is the key command — run it after every sync
- **`pm pr start`** does the full setup: clone, branch, prompt generation
- **`pm prompt`** regenerates the prompt without cloning (for re-runs)
- **`pm pr done`** / **`pm prompt`** auto-select from cwd if you're inside a workdir
- **`--description`** on `pm pr add` fills in the Task section of the Claude prompt
- **Workdir naming**: `~/.pm-workdirs/<project>-<root-hash>/<branch>-<base-hash>/`
  ensures no collisions across projects or branches
- **Backends**: `local` for no remote, `vanilla` for git with remote, `github` for GitHub repos
- **Error messages** list available IDs when you specify one that doesn't exist
