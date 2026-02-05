# Organizational Setup Demo

This demo shows how to set up and manage an open-source research lab using `pm`
and local git repos. It creates everything from scratch — no GitHub required.

One repo is created:

1. **`open-lab-org`** — the organization repo (docs, members, checks, archive, and `pm/` for project management)

Every command below is runnable. Run from the scratchpad directory.

## Setup

```bash
# Set REPO to wherever you cloned project-manager
REPO=~/project-manager

cd $REPO
./install.sh --local

WORK=$(mktemp -d)/org-demo
mkdir -p $WORK
cd $WORK
```

## 1. Create the organization repo

```bash
mkdir open-lab-org && cd open-lab-org
git init -b main
mkdir -p docs members checks archive
```

## 2. Seed initial governance docs

```bash
cat > CONTRIBUTING.md << 'EOF'
# Contributing to Open Lab

Welcome! This document describes how to contribute to the lab.

## Process
1. Check the project board for available work
2. Claim a task and create a branch
3. Submit your work for review
4. Address feedback and merge

## Standards
- All code must pass integrity checks
- Documentation is required for new processes
- Be respectful and constructive
EOF

cat > docs/governance.md << 'EOF'
# Lab Governance

## Decision Making
- Proposals require two approvals
- Vetoes must include an alternative proposal
- Monthly review of all active initiatives

## Roles
- **Lead**: Sets direction, resolves disputes
- **Member**: Full voting rights, can propose initiatives
- **Contributor**: Can submit work, no voting rights
EOF

cat > docs/onboarding.md << 'EOF'
# Onboarding Guide

## First Week
1. Read governance.md and CONTRIBUTING.md
2. Set up your development environment
3. Introduce yourself in the member directory
4. Shadow a current member on a task

## First Month
- Complete one small contribution
- Attend a governance meeting
- Write up your onboarding experience
EOF

git add -A && git commit -m "Initial org structure with governance docs"
```

## 3. Initialize the PM directory

```bash
pm init . \
  --name open-lab-org \
  --base-branch main \
  --backend local
```

This creates `pm/` inside the org repo.

## 4. Create a plan with Claude

```bash
pm plan add "Bootstrap lab governance"
```

This launches Claude directly to develop the plan. In a real workflow you'd
discuss the plan with Claude and have it write the plan file. For this
demo, the stub is fine. (If Claude CLI isn't installed, it prints the prompt.)

## 5. Break the plan into PRs

Launch Claude to decompose the plan into PRs:

```bash
pm plan review
```

Claude writes a `## PRs` section to the plan file. Then load them with
`pm plan load`. For this demo, simulate by running commands manually:

Layer 0 — foundational work (no dependencies):

```bash
pm pr add "Write integrity checks framework" \
  --plan plan-001 \
  --description "Create the checks/ framework: a runner script and example check."

pm pr add "Add member directory templates" \
  --plan plan-001 \
  --description "Create member profile template and README in members/."
```

Layer 1 — depends on layer 0:

```bash
pm pr add "Write resource tracking structure" \
  --plan plan-001 \
  --depends-on pr-001 \
  --description "Create docs/resources/ with tracking templates. Needs checks framework first."

pm pr add "Set up recognition criteria" \
  --plan plan-001 \
  --depends-on "pr-001,pr-002" \
  --description "Create docs/recognition.md defining how contributions are recognized. Needs both checks and member directory."
```

Review the dependency graph with Claude:

```bash
pm plan deps
```

Claude opens interactively to review. If it finds issues it runs
`pm pr edit` commands. In this demo the graph is correct.

## 6. View the dependency structure

```bash
pm pr graph
pm pr ready
pm pr list
```

## 7. Start a PR, do the work, finish, merge, sync

```bash
pm pr start pr-001
```

`pm pr start` prints the workdir path — grab it from the output or from
`pm/project.yaml`. Navigate there and simulate doing the work:

```bash
# The workdir path is printed by pm pr start and stored in pm/project.yaml.
# Extract it with python for reliability:
WORKDIR=$(python3 -c "
import yaml
with open('pm/project.yaml') as f:
    data = yaml.safe_load(f)
for pr in data['prs']:
    if pr['id'] == 'pr-001' and pr.get('workdir'):
        print(pr['workdir'])
        break
")
cd "$WORKDIR"

mkdir -p checks
cat > checks/run-checks.sh << 'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail
echo "Running integrity checks..."
for check in checks/check-*.sh; do
  [ -f "$check" ] && bash "$check"
done
echo "All checks passed."
SCRIPT
chmod +x checks/run-checks.sh

cat > checks/check-docs-exist.sh << 'SCRIPT'
#!/usr/bin/env bash
for f in CONTRIBUTING.md docs/governance.md docs/onboarding.md; do
  [ -f "$f" ] || { echo "FAIL: $f missing"; exit 1; }
done
echo "PASS: core docs exist"
SCRIPT

git add -A && git commit -m "Add integrity checks framework"
```

Push the branch back to the org repo and merge:

```bash
git push origin pm/pr-001-write-integrity-checks-framework
cd $WORK/open-lab-org
git merge pm/pr-001-write-integrity-checks-framework
cd "$WORKDIR"
```

Update the workdir's local main so `pm pr sync` can detect the merge
(the local backend checks `merge-base --is-ancestor` against the local
`main` ref):

```bash
git checkout main && git pull origin main
git checkout pm/pr-001-write-integrity-checks-framework
cd $WORK/open-lab-org
```

Mark done and sync:

```bash
pm pr done pr-001
pm pr sync
```

## 8. Push pm state

Commit the pm/ changes:

```bash
pm push
# Use the branch name from the output:
git merge pm/sync-<timestamp>
```

## 9. Show newly unblocked PRs

```bash
pm pr ready
pm pr list
```

pr-003 (resource tracking) should now be ready since its only dependency
(pr-001) is merged. pr-004 is still blocked waiting on pr-002.

## 10. Clean up

```bash
pm pr cleanup pr-001
cd $WORK && rm -rf open-lab-org
rm -rf ~/.pm/workdirs/open-lab-org-*
```
