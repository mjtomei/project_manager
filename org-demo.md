# Organizational Setup Demo

This demo shows how to set up and manage an open-source research lab using `pm`
and local git repos. It creates everything from scratch — no GitHub required.

Two repos are created:

1. **`open-lab-org`** — the organization repo (docs, members, checks, archive)
2. **`open-lab-org-pm`** — the PM repo managing organizational work

Every command below is runnable. Run from the scratchpad directory.

## Setup

```bash
# Set REPO to wherever you cloned project-manager
REPO=~/project-manager

cd $REPO
./install.sh
export PATH="$HOME/.local/bin:$PATH"

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
cd $WORK
```

## 3. Initialize the PM repo

```bash
pm init ./open-lab-org \
  --name open-lab-org \
  --base-branch main \
  --backend vanilla \
  --dir ./open-lab-org-pm
```

## 4. Add a plan

```bash
cd open-lab-org-pm
pm plan add "Bootstrap lab governance"
```

## 5. Add PRs with dependencies

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
`project.yaml`. Navigate there and simulate doing the work:

```bash
# The workdir path is printed by pm pr start and stored in project.yaml.
# Extract it with python for reliability:
WORKDIR=$(python3 -c "
import yaml
with open('project.yaml') as f:
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
(the vanilla backend checks `merge-base --is-ancestor` against the local
`main` ref):

```bash
git checkout main && git pull origin main
git checkout pm/pr-001-write-integrity-checks-framework
cd $WORK/open-lab-org-pm
```

Mark done and sync:

```bash
pm pr done pr-001
pm pr sync
```

## 8. Show newly unblocked PRs

```bash
pm pr ready
pm pr list
```

pr-003 (resource tracking) should now be ready since its only dependency
(pr-001) is merged. pr-004 is still blocked waiting on pr-002.

## 9. Clean up

```bash
pm pr cleanup pr-001
cd $WORK && rm -rf open-lab-org open-lab-org-pm
rm -rf ~/.pm-workdirs/open-lab-org-*
```
