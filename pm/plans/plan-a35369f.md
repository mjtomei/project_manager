# Container git access: alternatives and hardening

## Context

On 2026-10-27 at 16:15:36 UTC a read-only review subagent of #241 (pr-1139060) ran `git push origin --mir` against a throwaway bare repo it had just created in a temp directory, to check how git parses options. Two gaps turned that local experiment into a production change:

1. The in-container `git` wrapper forwards every push/fetch/pull/ls-remote to the host proxy, whichever repository the command runs in (pr-8cdbe60, filed 2026-10-12). The proxy replayed the command in #241's workdir against the real GitHub origin, using the user's credentials.
2. The proxy's broad-push check matches only the exact strings `--all`, `--mirror` and `--tags`, so git's abbreviation of `--mirror` was accepted.

Effect: GitHub `master` was force-rewound from `450a6362` to `c0765071`, 223 branches were deleted and 71 open PRs were auto-closed. Everything was restored the same day from GitHub's activity log, and the PRs were reopened. Evidence and backups are in `~/.pm/backups/incident-2026-10-27/`.

What the incident showed:
- The wrapper's scope was wrong. Anything an agent ran inside the container that looked like a remote command was executed with production credentials.
- Deny-list validation of git arguments is fragile: git accepts many spellings of the same option.
- The host-side git runs inside a repository the container can write to.
- The proxy's credential can do anything the user can.
- Nothing on GitHub limited the damage. This is now addressed by ruleset 25978556 (see below).

## Constraints

- Nested QA scenarios: scenario containers run their own pm projects and need git access of their own. This is the main reason we may keep a custom proxy rather than adopting off-the-shelf credential forwarding.
- The fake_github test backend and local-path origins must keep working.
- Several containers can share a proxy per session and PR (see pr-748e708 / #255 for the keying problems).
- Tests for this area run only against sandboxed local remotes, never a network remote.

## Existing work in scope

- pr-8cdbe60: scope the wrapper to `/workspace`, catch abbreviated broad pushes, and add incident regression tests. Its scope was extended by note-fcae10a in the #249 workdir project. This is the immediate fix; land it first.
- pr-1139060 (#241): rejects abbreviations of the program-executing options and disables hooks for host-side git.
- pr-748e708 (#255): proxy keying; impl and QA containers fight over one socket.
- pr-d82e0f1: workdir clones whose fetch URL is local are rejected by the proxy.

## GitHub guardrail

Ruleset 25978556, "All branches: no force pushes or deletions", applied 2026-10-27, enforcement active, no bypass actors. No bypass is possible yet, because the proxy pushes with the user's own identity. Once agent pushes use a separate identity, the user's account can be added as a bypass actor.

Maintenance procedure for a deliberate history rewrite or a branch cleanup:
1. Pause auto-start and any session that pushes.
2. Disable the ruleset: `gh api -X PUT repos/mjtomei/project_manager/rulesets/25978556 -f enforcement=disabled`.
3. Make the change.
4. Re-enable it with `enforcement=active`.
5. Resume.

## PRs

### PR: Decide between hardening the container git proxy and an alternative
- **description**: Spike producing a decision doc. Compare four options. (a) Keep the proxy, hardened per this plan. (b) A host-owned staging repository: the proxy imports only the commit to publish from the workdir and pushes it from a repository and configuration the container cannot touch. (c) A separate least-privilege identity for agent pushes, such as a GitHub App installation token or a fine-grained token for a machine account, combined with rulesets only the human identity can bypass. (d) Existing tooling for container credential forwarding, or server-side per-ref policy through a local mirror. Score each option on: nested QA scenarios, fake_github tests, local-path origins, sharing a proxy between sessions, performance, and blast radius if an agent misbehaves or a container is compromised. Recommend one option and list the migration PRs.
- **tests**: None (spike). Reviewed as a doc.
- **files**: pm/docs/container-git-access-options.md
- **depends_on**:

### PR: Red-team regression suite for the container git wrapper and push proxy
- **description**: A pytest suite that drives the real in-container wrapper script and PushProxy against a sandboxed local bare remote. A fixture fails the run if any configured remote is a network URL. Cases: replay the incident's commands (~/.pm/debug/default.log, 11:15:30-11:15:38 local, 2026-10-27); confirm commands issued outside /workspace are never forwarded; and add one case per hardening PR in this plan. Every case checks the remote's actual refs after the attempt (only the allowed branch may change), not just the proxy's exit code. Also add a prompt for an agent-driven red-team session that may only target the sandbox and turns each new finding into a test case. It runs in the normal test command.
- **tests**: The suite itself.
- **files**: tests/test_container_git_redteam.py, tests/fixtures/
- **depends_on**:

### PR: Push proxy accepts only an allow-listed command grammar
- **description**: Replace the deny-lists (_check_dangerous_flags and the broad-push flag set) with an allow-list. Push accepts only the origin remote, one refspec whose destination is the allowed branch, and a small fixed set of harmless flags. Fetch, pull and ls-remote accept only the origin remote and a fixed set of flags. Anything else is rejected, including any abbreviation git would expand. Build the host-side command from the parsed request rather than passing the container's arguments through. Remove the deny-list code once the red-team suite passes.
- **tests**: Red-team suite cases for every rejected form, plus the existing proxy tests.
- **files**: pm_core/push_proxy.py, pm_core/container.py
- **depends_on**: Red-team regression suite for the container git wrapper and push proxy

### PR: Isolate host-side proxy git from container-writable repository settings
- **description**: The proxy runs git on the host inside the PR workdir, which the container can modify. #241 stops hooks from running; extend that so no repository-level setting in the workdir can change what the host-side git executes, which remote it talks to, or which refs it updates. For example, run the push from a host-owned repository with fixed configuration and import only the commit being published. Document what is trusted from the workdir: only commit objects.
- **tests**: Red-team suite cases that plant repository settings in the sandbox workdir and assert the host-side git ignores them.
- **files**: pm_core/push_proxy.py
- **depends_on**: Red-team regression suite for the container git wrapper and push proxy

### PR: Separate least-privilege GitHub identity for agent pushes
- **description**: Agent pushes currently use the user's own GitHub credentials, so a proxy failure can do anything the user can, and rulesets cannot exempt the user without also exempting agents. Give agent pushes their own identity, limited to this repository, as chosen by the decision doc. Add the user's account as a bypass actor on ruleset 25978556, so maintenance no longer needs the disable/enable procedure. Document setup and token rotation.
- **tests**: A sandbox test that the proxy uses the agent credential and never the user's credential helper.
- **files**: pm_core/push_proxy.py, docs
- **depends_on**: Decide between hardening the container git proxy and an alternative

### PR: Push proxy audit log and ref-change alarm
- **description**: Record every forwarded command in a dedicated, non-rotating-by-default log: session, container, PR, the caller's repository, arguments and result. The incident's TUI log had already rotated away within a day. After every push, compare the remote's refs with the expected change. If anything other than the allowed branch changed, stop that proxy, alert in the TUI, and print the before/after refs needed for recovery.
- **tests**: Sandbox test where an unexpected ref change stops the proxy and raises the alert.
- **files**: pm_core/push_proxy.py, pm_core/tui
- **depends_on**: Red-team regression suite for the container git wrapper and push proxy

### PR: pm works with GitHub rulesets that block force pushes and branch deletions
- **description**: With ruleset 25978556 active, `pm pr close` (gh pr close --delete-branch) closes the PR but cannot delete the branch, and currently prints a misleading "Could not close GitHub PR" warning. Default to keeping the remote branch when a ruleset blocks deletion, and say why. Add a pm doctor/status check that warns when the repo has no such ruleset. Document the maintenance procedure from this plan in the user docs.
- **tests**: Unit tests with fake_github simulating a deletion-blocking ruleset.
- **files**: pm_core/cli/pr.py, pm_core/gh_ops.py, pm_core/fake_github.py, docs
- **depends_on**:
