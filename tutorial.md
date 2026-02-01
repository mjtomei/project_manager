# pm tutorial — Build something real

This tutorial walks you through using `pm` to plan, build, and ship a
real feature for the project-manager project itself: a mobile web
dashboard. By the end you'll be comfortable using `pm` on your own repos.

Unlike `demo.md` (which exercises every command mechanically), this
tutorial follows the actual workflow: explore, plan, decompose, build,
merge, repeat.

## Prerequisites

```bash
# Set REPO to wherever you cloned project-manager
REPO=~/claude-work/project-manager

cd $REPO
./install.sh
export PATH="$HOME/.local/bin:$PATH"
```

You'll also need:
- Python 3.12+
- A machine you can reach over the network (localhost works for local testing)

---

## Phase 1: Explore the codebase

Before planning anything, understand what exists. Open a Claude Code
session in the repo and ask it open-ended questions:

```bash
cd $REPO
claude
```

Suggested prompts to paste into the Claude session:

> Read through this codebase and tell me what it does, how it's
> structured, and what's missing or rough. Be specific.

> What would make this tool more useful day-to-day? What's the biggest
> gap between what it does now and what the README promises?

> If I wanted to check project status from my phone, what would need
> to exist?

Take notes on what Claude finds. The goal is to develop your own opinion
about what to build next. If you already have an idea for your own repo,
skip to Phase 2 and substitute your project — the workflow is identical.

If you don't have a specific idea, continue with this tutorial's project:
a mobile web dashboard for `pm`.

---

## Phase 2: Initialize the PM repo

```bash
cd $REPO
pm
```

This detects the repo and suggests an init command. Run it:

```bash
PM_REPO=${REPO}-pm

pm init $REPO \
  --base-branch master \
  --backend vanilla \
  --dir $PM_REPO

cd $PM_REPO
```

Verify:

```bash
pm plan list
git log --oneline
```

Empty plans, one init commit. This is your project management state —
separate from the codebase, version-controlled, auto-committed on
every change.

---

## Phase 3: Write a plan

A plan is a high-level goal. Write it in prose — Claude will help
decompose it into PRs later.

```bash
pm plan add "Mobile web dashboard for pm"
```

Now edit the plan file to describe what you want:

```bash
$EDITOR plans/plan-001.md
```

Write something like:

```markdown
# Mobile web dashboard for pm

A lightweight web interface that shows project status from any device.
Optimized for phone screens. Designed to be self-hosted by individuals.

## Goals
- Read-only dashboard: see the tech tree, PR statuses, what's ready
- Works on mobile browsers over cellular connections
- Runs as a single process alongside pm on any machine
- Per-device authentication via pre-shared keys (no accounts, no passwords)

## Non-goals (for now)
- No write operations from the web UI (use the CLI for mutations)
- No real-time updates (refresh to poll)
- No multi-user access control (single-owner tool)

## Technical direction
- Python (Flask or similar) since pm is already Python
- Static HTML + minimal JS, no build step, no framework
- Auth via device keys: generate a key, install it on your phone,
  requests without a valid key get rejected
- Serve over HTTPS even locally (self-signed cert is fine for now)
```

Save and check that the plan is tracked:

```bash
pm plan list
git log --oneline
```

The plan file edit isn't auto-committed (only `pm` commands auto-commit),
so commit it yourself:

```bash
git add plans/plan-001.md && git commit -m "plan-001: flesh out mobile dashboard plan"
```

---

## Phase 4: Decompose the plan into PRs

Ask Claude to break the plan into a dependency graph:

```bash
pm plan review plan-001
```

This prints a prompt. Paste it into a Claude session. Claude will output
a YAML list of PRs with dependencies. Review it, adjust, then translate
into `pm pr add` commands.

Or, if you want to set up the tree yourself, here's a reasonable
decomposition:

```bash
# Layer 0: foundations (no dependencies, all parallel)
pm pr add "Web server skeleton with Flask" \
  --plan plan-001 \
  --description "Minimal Flask app that serves a health check endpoint. Project structure, requirements, entry point."

pm pr add "Device key auth system" \
  --plan plan-001 \
  --description "Generate per-device keys via CLI. Middleware that rejects requests without a valid key cookie. Key install flow for mobile browsers."

pm pr add "Data API for pm state" \
  --plan plan-001 \
  --description "Read-only JSON API that exposes project state: plans, PRs, graph, ready list. Reads from project.yaml, no mutations."

# Layer 1: depends on foundations
pm pr add "Dashboard page — tech tree view" \
  --plan plan-001 \
  --depends-on "pr-001,pr-003" \
  --description "HTML page showing the dependency graph as a visual tech tree. Mobile-first layout. Status icons, dependency lines. Polls the data API on refresh."

pm pr add "Dashboard page — PR detail and status" \
  --plan plan-001 \
  --depends-on "pr-001,pr-003" \
  --description "PR list view with filters (ready, in_progress, blocked). Tap a PR to see details: description, dependencies, assigned machine, workdir."

pm pr add "HTTPS and self-signed certs" \
  --plan plan-001 \
  --depends-on pr-001 \
  --description "Auto-generate self-signed cert on first run. Serve over HTTPS. Document how to trust the cert on iOS/Android."

# Layer 2: integration
pm pr add "Auth integration and key install flow" \
  --plan plan-001 \
  --depends-on "pr-002,pr-004,pr-006" \
  --description "Wire auth middleware into all routes. Build the key install page: user visits a URL with the key token, it sets a secure cookie. Test the full flow on a phone."

pm pr add "Local deployment and testing" \
  --plan plan-001 \
  --depends-on "pr-004,pr-005,pr-007" \
  --description "End-to-end test: start the server, load the dashboard on desktop and mobile, verify auth blocks unauthorized access. Document how to run it."

# Layer 3: ship it
pm pr add "Public deployment on remote host" \
  --plan plan-001 \
  --depends-on pr-008 \
  --description "Deploy to an EC2 instance (or any remote host). Systemd unit file. Verify it works over cellular with device key auth. Document the deploy process."
```

Now look at what you've built:

```bash
pm pr graph
pm pr list
pm pr ready
```

You should see a layered dependency tree with pr-001, pr-002, pr-003
ready to start (no dependencies).

---

## Phase 5: Start building

Pick a ready PR and start it:

```bash
pm pr start pr-001
```

This clones the repo, creates a branch, and prints a Claude prompt.
Open a Claude Code session in the workdir:

```bash
# Use the workdir path from the pr start output
cd ~/.pm-workdirs/project-manager-*/pm-pr-001-*
claude
```

Paste the prompt. Let Claude build it. Review the code. When you're
satisfied:

```bash
# From the workdir, push the branch
git add -A && git commit -m "web server skeleton" && git push -u origin pm/pr-001-web-server-skeleton-with-flask
```

Then mark it done:

```bash
cd $PM_REPO
pm pr done pr-001
```

Start the other layer-0 PRs in parallel — each gets its own workdir
and its own Claude session:

```bash
pm pr start pr-002
pm pr start pr-003
```

Check status:

```bash
pm pr list
```

Three PRs in progress, the rest waiting.

---

## Phase 6: Merge and unblock

When a PR's branch is merged into master (either locally or via your
git host), sync to detect it:

```bash
# After merging pr-001's branch into master in any workdir:
pm pr sync
```

This detects the merge and shows which PRs are now unblocked:

```bash
pm pr ready
```

Layer 1 PRs that depended only on merged PRs are now ready. Start them.

Repeat: start → build → done → merge → sync → ready → start.

---

## Phase 7: Test locally

Once pr-008 (local deployment and testing) is merged, you should have
a working dashboard. Test it:

```bash
# From the workdir where the server code lives
python -m pm_web.server --pm-repo $PM_REPO --port 8443

# On your machine, open https://localhost:8443
# You should be redirected to the key install page
```

Generate a device key and install it on your phone:

```bash
# This would be part of the device key auth PR
python -m pm_web.keygen
# Outputs a URL like https://<host>:8443/auth/install?key=<token>
# Open that URL on your phone to install the key
```

Verify:
- Dashboard loads on your phone's browser
- Tech tree shows current project state
- Requests without the device key are rejected
- Refreshing shows updated status

---

## Phase 8: Deploy publicly

Once pr-009 (public deployment) is merged, deploy to your remote host:

```bash
pm pr start pr-009
# Follow the Claude prompt to set up deployment
```

The deployment should:
1. Copy the server to your EC2 instance
2. Set up a systemd service
3. Open the HTTPS port
4. Generate a device key for your phone
5. Test over cellular

<!--
## Future: Deploy via omerta_mesh

When omerta_mesh is available, deployment changes significantly.
Instead of exposing a port on a public cloud instance, you'll:

1. Install omerta_mesh on your server and phone
2. Both devices join your mesh network (no public IP needed)
3. The pm web dashboard binds to the mesh interface
4. Your phone accesses it via the mesh address
5. Device key auth still applies — mesh provides the transport,
   keys provide the application-layer auth

This means:
- No cloud hosting required — run the dashboard on your laptop,
  home server, or any machine on your mesh
- No DNS, no port forwarding, no certificates from a CA
- The mesh encrypts transport; device keys authenticate the user
- Anyone can host services for themselves without the internet's
  current gatekeepers

The pm plan for this would look like:

    pm plan add "Deploy pm dashboard via omerta_mesh"
    pm pr add "omerta_mesh transport layer" --plan plan-002 --depends-on pr-008
    pm pr add "Mesh service discovery" --plan plan-002 --depends-on pr-010
    pm pr add "Remove HTTPS/cert machinery" --plan plan-002 --depends-on pr-010
    pm pr add "Mobile mesh client setup guide" --plan plan-002 --depends-on "pr-011,pr-012"

The key insight: once individuals can create their own network
infrastructure, the deployment story for personal tools becomes
"run it anywhere, access it from everywhere." No servers in the
middle. No accounts. Just your devices, your mesh, your keys.
-->

---

## Phase 9: Clean up and review

Check the final state:

```bash
cd $PM_REPO
pm pr list
pm pr graph
git log --oneline
```

Every step of the project is recorded in the PM repo's git history.
Every PR, every status change, every merge detection.

Clean up workdirs for merged PRs:

```bash
pm pr cleanup pr-001
pm pr cleanup pr-002
# ... etc for all merged PRs
```

---

## What you've learned

By this point you've used every part of the `pm` workflow:

1. **Explore** — Used Claude to understand a codebase before planning
2. **Plan** — Created a plan document describing a goal in prose
3. **Decompose** — Broke the plan into a dependency graph of PRs
   (manually or with `pm plan review` + Claude)
4. **Visualize** — Used `pm pr graph` and `pm pr ready` to see the
   tech tree and decide what to work on
5. **Execute** — Used `pm pr start` to set up workdirs with Claude
   prompts, ran parallel Claude sessions
6. **Track** — Used `pm pr done` and `pm pr sync` to track progress
   and unblock downstream work
7. **Ship** — Went from plan to deployed, tested feature
8. **Audit** — Used the PM repo's git history as a record of decisions

Now do it on your own repo. Run `pm` from your project directory and
follow the guidance it prints.
