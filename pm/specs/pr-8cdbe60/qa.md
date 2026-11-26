# QA Spec: pr-8cdbe60 — container git proxy scope + abbreviated broad pushes

## What changed (grounded)

- `pm_core/container.py` `_build_git_wrapper_script()` (new; called by
  `_build_git_setup_script(has_push_proxy=True)` when pm creates a container
  with a push proxy) writes `~/.local/bin/git` into the container. It now
  forwards `push|fetch|pull|ls-remote` to the host proxy socket **only** when
  the repository git would operate on — cwd, leading `-C <dir>` options
  (chained, relative or absolute), `GIT_DIR`/`GIT_WORK_TREE` — has the same
  top-level dir *and* git dir as the container workdir (`/workspace`). All
  other cases `exec /usr/bin/git` locally. Any other leading global option
  (`-c`, `--git-dir=…`, `--work-tree=…`) runs locally. When forwarded, the
  leading `-C` options are dropped from the forwarded request.
- `pm_core/push_proxy.py` `PushProxy._execute_push` rejects every argument git
  would read as `--all`, `--branches`, `--mirror` or `--tags`: any
  unambiguous prefix, with or without `=value` (`--mir`, `--al`, `--br`,
  `--ta`, `--mirror=1`). Ambiguous prefixes (`--a`, `--t`) are rejected too.
  The error text names the option git would read
  (`'--mir' (read by git as --mirror)`). Options that only look similar
  (`--atomic`, `--follow-tags`, `--no-tags`, `--force-with-lease`, `--thin`,
  `-u`, `--`) are still allowed.
- `tests/test_git_proxy_scope.py` (new) replays the incident in a sandbox, and
  `tests/test_push_proxy.py` gets new cases for the abbreviations.

The proxy is a long-lived daemon (`python -m pm_core.push_proxy <sock>
<workdir> <branch>`). It serves one connection at a time and can be shared by
several containers on the same PR. Each request carries the caller's
`HOST_WORKDIR`.

## MANDATORY safety setup (every scenario)

QA scenario containers run the **unfixed** wrapper at
`/home/pm/.local/bin/git`. It forwards remote commands typed in *any*
directory to the real host proxy, and so to the real GitHub origin with the
user's credentials. That is how the 2026-10-27 incident happened. Before
doing anything else, every scenario must:

1. Move the installed wrapper aside (`mv ~/.local/bin/git
   ~/.local/bin/git.disabled`), run `hash -r`, and confirm `command -v git`
   resolves to a real binary (its first two bytes are not `#!`). This also
   protects tmux servers and pm daemons the scenario starts later.
2. Never connect to `/run/pm-push-proxy/push.sock`, and never use a GitHub
   URL as a remote. Every remote is a local bare repo under a temp dir,
   addressed as `file://…` where the proxy must accept it.
3. Run the wrapper and proxy from the PR source tree (`PYTHONPATH=/workspace`,
   or `pm` installed with `./install.sh --local`). Point them at a temp
   socket and at a sandbox "workspace" clone, never at the real `/workspace`
   clone. Generating the wrapper with a non-default socket and workdir means
   calling `pm_core.container._build_git_wrapper_script(host_workdir,
   socket_path=…, container_workdir=…, real_git=/usr/bin/git)` once. That is
   the documented test seam, and it stands in for "pm created a container".
   Start the proxy with its real entrypoint, `python -m pm_core.push_proxy`.
   - Alternative where nested podman works: a throwaway pm project with
     `nested_podman: true`, container mode enabled, and origin =
     `file:///…/remote.git`. pm then creates a real container whose wrapper
     and proxy come from source. The worker drives git with `podman exec`.

## Setup (cross-cutting)

- A sandbox **remote** bare repo with `master`, two other PR branches
  (`pm/pr-a`, `pm/pr-b`) and a tag `v1`. `master` on the remote is one commit
  ahead of the workspace's local master.
- A sandbox **workspace** clone, cloned from `file://<remote>`, on the allowed
  branch `pm/pr-x` with 2–3 unpushed commits. This is the stand-in for
  `/workspace`.
- A running proxy for (socket, workspace, `pm/pr-x`), started from source.
- The fixed wrapper, installed first on PATH as `git` and pointed at that
  socket and workspace.
- A **scratch** repo outside the workspace (`mktemp -d`), with branches b1/b2
  and its own local bare origin. This is the incident layout.
- Evidence comes from `git for-each-ref` snapshots of each remote before and
  after, the workspace's `git reflog` and `HEAD`, and the proxy's log lines
  or a connection count. Exit codes alone are not evidence.

## Requirements

R1 — Scratch-repo remote commands stay local.
- Given the fixed wrapper on PATH and a scratch repo outside the workspace
- When the user runs `git push origin master` (or fetch, `pull --rebase`, or
  ls-remote) in the scratch repo
- Then the command acts on the scratch repo's own origin (its refs update, or
  ls-remote lists them), the proxy receives no connection, and the
  workspace's remote, HEAD and reflog do not change.

R2 — The original bug: a nested pm project's pull no longer rebases the
workspace.
- Given a workspace with unpushed commits whose origin is behind, and a
  throwaway local-backend pm project under /tmp with its own clone and origin
- When the user starts a PR in the nested project (`pm pr start`, or
  `pm autostart add`), so pm runs `git pull --rebase=merges` in the new clone
- Then the workspace's reflog has no `pull` entry, its HEAD and unpushed
  commits are intact, and the nested clone is updated from its own origin.

R3 — The incident commands can no longer damage the remote.
- Given the incident layout (scratch repo with local bare origin) and a
  workspace whose remote has master, PR branches and tags
- When the user runs `git push origin --mir`, `git push origin --branches`,
  `git push origin --a` and `git fetch --upl=/bin/false origin`, first from
  the scratch repo and then from the workspace
- Then from the scratch repo, nothing reaches the proxy and the workspace
  remote's refs are byte-identical. From the workspace, each push is refused
  with `push-proxy: rejected — '<arg>' (read by git as --<opt>)`, exits
  non-zero, and no remote ref changes.

R4 — The workspace's own remote commands are still forwarded.
- Given the fixed wrapper and the workspace
- When the user runs fetch, pull, ls-remote, or `push origin pm/pr-x` from the
  workspace root, from a subdirectory, or from elsewhere with `-C <workspace>`
- Then each command reaches the proxy, and the allowed-branch push lands: the
  remote's `pm/pr-x` equals the workspace HEAD and no other ref moves.

R5 — Non-broad push options still work.
- Given the workspace on `pm/pr-x`
- When the user pushes with `--force-with-lease`, `--atomic`,
  `--follow-tags`, `--no-tags`, `-u` or `--set-upstream`
- Then the push succeeds and only `pm/pr-x` changes on the remote.

R6 — Every spelling of a broad push is refused.
- Given the workspace
- When the user pushes with any of `--mirror`, `--mirr`, `--m`,
  `--mirror=1`, `--all`, `--al`, `--all=x`, `--branches`, `--br`, `--b`,
  `--tags`, `--ta`, `--tag`, `--tags=1`, `--a` or `--t`
- Then each is refused with a message naming the expanded option, and the
  remote's refs are unchanged.

R7 — The automated regression suite passes.
- Given the PR source tree, with real git first on PATH
- When the user runs `pytest tests/test_git_proxy_scope.py
  tests/test_push_proxy.py tests/test_container.py`
- Then all tests pass. Checking out the pre-fix `pm_core/` (master) makes the
  scope and incident tests fail. Never do that check against a live proxy.

## Edge cases

E1 — Chained or relative `-C`: `git -C .. -C workspace fetch` from the
workspace's parent resolves to the workspace and is forwarded. `git -C
<scratch> push origin b1` issued from inside the workspace stays local.

E2 — `GIT_DIR=<scratch>/.git git push origin b2` run from inside the
workspace acts on the scratch repo locally. It must not be forwarded.

E3 — A git repo nested *inside* the workspace directory (`git init
<ws>/sub/inner` with its own origin) is a different repository. Its remote
commands stay local.

E4 — A bare repo or a non-repo directory: `git ls-remote file://<remote>` run
from `/tmp` (not a repo) or from inside a bare repo runs locally and
succeeds. The proxy is not contacted.

E5 — `git -c k=v fetch` or `git --git-dir=<ws>/.git fetch` from the workspace
runs locally. This is by design: the proxy cannot replay globals. It is not
forwarded.

E6 — Proxy down (socket removed or proxy killed): scratch-repo remote
commands still succeed. Before the fix they failed with `git-proxy: cannot
connect`. Workspace remote commands fail cleanly with `git-proxy: cannot
connect`, with no hang and no traceback.

E7 — Non-remote commands (status, commit, log, `rev-parse`) behave exactly as
the real git, with the exit codes passed through, in both repositories.

E8 — Proxy log: rejected broad pushes produce a `Push rejected: broad flag`
warning in the proxy's log, so there is an audit trail.

E9 — Workspace path containing a space, or reached through a symlink: the
wrapper still recognizes the workspace (it compares `pwd -P`) and still
forwards.

## Concurrency (shared resources)

Shared resources the diff touches:
- the proxy Unix socket. One serial server can be shared by several
  containers on a PR, and each request carries a different `workdir`.
- the sandbox remote's refs, written by concurrent pushes
- the workspace repo (HEAD, reflog, index), touched by nested pm
  pulls/rebases while the user works in it
- the installed wrapper path `~/.local/bin/git`, used by every process in the
  container, including tmux panes and pm daemons
- the proxy's log file

C1 — Two "containers" (two wrappers with different workspace clones and
HOST_WORKDIRs) share one proxy socket. A third actor hammers a scratch repo.
All of them fire remote commands at once, including one broad-push attempt.
Then each workspace's allowed push lands from its *own* clone, the broad push
is refused without disturbing the others, the scratch actor never touches the
socket, and no ref other than the allowed branch changes on any remote.

C2 — The proxy is busy: a client connects and never sends a newline, so the
proxy holds the connection until its 30 s timeout. Scratch-repo commands
still complete promptly, because they never queue on the socket. Workspace
commands queue and then complete.

C3 — A nested pm project runs `pm pr start` (pull-rebase in its own clone)
while the user pushes from the workspace in parallel. The workspace keeps
its commits and the nested clone is not cross-wired.

## Pass / fail criteria

- PASS: every Then holds, verified by remote ref snapshots, the workspace's
  reflog and HEAD, and the proxy's connection log, not only by exit codes.
- FAIL: any ref other than the allowed branch changes on any sandbox remote. A
  `pull` entry appears in the workspace reflog after a nested-project
  operation. A non-workspace command reaches the proxy. A workspace command
  that should forward is not forwarded. A broad-push spelling is accepted. A
  legitimate option is refused.
- ABORT (report as blocked, not as pass or fail): the safety setup cannot be
  completed, meaning the installed wrapper cannot be disabled or real git
  cannot be confirmed first on PATH.

## Ambiguities (resolved)

1. Simulated container vs real container: a real pm container needs nested
   podman, which may be unavailable. Scenarios accept either a real nested
   pm container or the source-tree wrapper pointed at a sandbox. Workers
   report which one they used.
2. `git fetch --upl=<prog>` from the workspace is still forwarded and still
   runs `<prog>` on the proxy side. `_check_dangerous_flags` is still
   exact-match. Prefix-matching program-executing options belongs to #241
   (pr-1139060), which has not landed, so this is out of scope. Workers
   record whether it happens as a **known residual** and do not fail the PR
   on it. From a scratch repo it must stay local (R3).
3. Repo-config broad pushes (`remote.*.mirror`, `push.default=matching`,
   multiple pushurls) are out of scope by user decision and go to the
   redesign plan. Not tested.
4. `-C /workspace` is now forwarded. Before the fix it ran locally because
   `$1` was `-C`. This is intended (R4) and is not a regression.
5. `-c`, `--git-dir` and other globals now always run locally, even in the
   workspace. This is intended (E5), and the old wrapper behaved the same
   because `$1` was the global option.

No unresolved ambiguities.
