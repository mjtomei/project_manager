# Spec: pr-8cdbe60 — container git proxy forwards remote commands from any repo

## Background (grounded)

- `pm_core/container.py` `_build_git_setup_script()` (~line 446) writes
  `~/.local/bin/git` into the container when a push proxy is attached. The
  wrapper forwards any invocation whose `$1` is `push|fetch|pull|ls-remote`
  to the host socket `/run/pm-push-proxy/push.sock`, with
  `"workdir": HOST_WORKDIR` baked in. The cwd is never inspected.
- `pm_core/push_proxy.py` `PushProxy._handle_connection` dispatches to
  `_execute_push` / `_execute_read_cmd`. Both run on the host in
  `caller_workdir or self.workdir`, using the user's credentials.
- `_execute_push` rejects broad pushes only when an arg exactly equals
  `--all`, `--mirror` or `--tags`. `_extract_target_branch` with a single
  positional (`git push origin --mir`) falls back to the workdir's HEAD
  branch. That is the allowed branch, so the push is accepted.
- Incident 2026-10-27 16:15:30Z (the transcript of session 14a2d740,
  subagent a42e1db1aa3bd6a93, is readable here). From
  `tmp=$(mktemp -d); cd $tmp/work` (a fresh repo whose origin is a local bare
  `$tmp/remote.git`), the subagent ran:
  1. `git push origin --mir` → forwarded. The proxy ran
     `git -C <#241 workdir> push origin --mir`. GitHub master was force-rewound
     and branches were deleted.
  2. `git push origin --branches` → forwarded. Its master push was rejected as
     non-fast-forward, but it was still accepted by the proxy.
  3. `git push origin --a` → forwarded. git itself rejected it ("ambiguous
     option: a (could be --all or --atomic)", rc 129).
  4. `git fetch --upl=/bin/false origin` → forwarded. It was accepted, because
     `_check_dangerous_flags` matches exactly. That gap belongs to #241.
- #241 (pr-1139060, branch `origin/pm/pr-1139060-…`, not merged) changes
  `_check_dangerous_flags` to prefix-match `_DANGEROUS_GIT_OPTIONS`. It has
  not landed on master (450a6362).

## Requirements

### R1: the wrapper forwards only for the container workdir's repository
In `pm_core/container.py`, the wrapper forwards `push|fetch|pull|ls-remote` to
the proxy only when the repository that git would operate on is the container
workdir (`_CONTAINER_WORKDIR`, `/workspace`). Otherwise it `exec`s the real
git, which runs locally against that repository's own remotes.
- Parse the leading global options. The only one allowed is `-C <dir>`, which
  can repeat. The first non-option word is the subcommand. If any other global
  option comes first (`-c`, `--git-dir`, `--work-tree`, `-p`, …), run the real
  git locally. The proxy cannot replay those options, and `-c` must never be
  carried to the host.
- Repository identity: `$REAL_GIT [-C …] rev-parse --show-toplevel
  --absolute-git-dir` must match both of these values for the container
  workdir:
  - the physical path (`cd "$WORKDIR" && pwd -P`), and
  - the git dir, computed in a subshell with `GIT_DIR`, `GIT_WORK_TREE` and
    `GIT_COMMON_DIR` unset.

  Matching both closes the `GIT_DIR=/tmp/x/.git git push` case: run from
  /workspace, the top-level directory would still look like /workspace. A
  hook that runs inside /workspace with `GIT_DIR=.git` still forwards. A bare
  repo, no repo, a nested repo under /workspace, or a failed probe all run
  locally.
- `git -C /workspace push …` is forwarded. Before this change, any `-C` form
  ran locally and failed without credentials. Forwarding it is what "honouring
  -C" means here: the decision follows the repository the command targets.
- To make this testable, the wrapper text moves into
  `_build_git_wrapper_script(host_workdir, *, socket_path, container_workdir,
  real_git)`. Its defaults are the container constants.
  `_build_git_setup_script` calls it, and its output is byte-for-byte the
  install script it already produces.

### R2: broad-push check matches abbreviations
In `pm_core/push_proxy.py`, add a module-level helper
`_long_option_match(arg, options)`. It returns the long option in `options`
that `arg` names under git's parse-options rules: an exact match or any
prefix, with or without `=value`, and only for `--`-prefixed args longer than
`--`. `_execute_push` uses it with
`_BROAD_PUSH_OPTIONS = ("--all", "--branches", "--mirror", "--tags")`.
`--branches` is git's alias of `--all`. An ambiguous prefix such as `--a`,
`--t` or `--b` is rejected too; git would refuse it anyway.
- #241 has not landed, so `_check_dangerous_flags` stays as it is to avoid a
  conflicting double edit. The helper's signature fits #241's loop, and a
  cross-PR note asks whichever PR merges second to route
  `_check_dangerous_flags` through it.

### R3: regression tests with a sandboxed local bare remote
In the new `tests/test_git_proxy_scope.py`, the wrapper comes from
`_build_git_wrapper_script` and points at a temp socket and a temp
"workspace". `PushProxy` comes from the source tree. The remote is a local
bare repo addressed as `file://…`, so the proxy's local-path-origin refusal
doesn't mask the push path.
- (a) Incident replay. Run the four incident commands, plus the full-name and
  `=value` spellings, through the wrapper:
  - from a scratch repo, as in the incident, and
  - from the workspace itself, so they do reach the proxy.

  After each run, compare the bare remote's `for-each-ref` snapshot with the
  one taken before. Nothing may change except `refs/heads/<allowed>`. A
  positive control pushes the allowed branch through the same path and checks
  that the remote ref moved.
- (b) Scratch-repo isolation. Run `push`, `fetch`, `pull --rebase` and
  `ls-remote` from a scratch repo outside the workspace, and `-C <scratch>`
  from inside it. Each must act on the scratch repo's own remote. The proxy
  must record zero connections, and the workspace's HEAD and reflog must not
  change. This is the original nested-pm repro: unpushed workspace commits
  must survive a `pull --rebase` run in another repo.
- Safety: every subprocess uses `/usr/bin/git` or a PATH whose `git` is the
  real binary. A fixture asserts that `shutil.which("git")` is not a pm
  wrapper, and HOME points to tmp. Nothing touches `/run/pm-push-proxy` or a
  network remote.

## Implicit requirements
- The proxy's own `subprocess.run(["git", …])` resolves through PATH. In this
  container that would be the live wrapper, so the tests put the real git
  first on PATH.
- The forwarded request still sends only the subcommand args. A `-C` prefix
  is dropped, which is correct because forwarding means the repository is the
  workdir, which the proxy addresses as `HOST_WORKDIR`.
- Existing `tests/test_container.py` wrapper assertions (shebang first,
  HOST_WORKDIR baked in, socket path) still pass.
- The wrapper stays POSIX `sh`. No bashisms: the container's `/bin/sh` may be
  dash.

## Ambiguities (resolved)
1. *Should `git -C /workspace push` now be forwarded?* Yes. See R1: the rule
   is the target repository, not the argv shape.
2. *Abbreviations that git finds ambiguous (`--a`, `--t`)?* Reject them in
   the proxy. This is fail-closed, costs nothing (git errors anyway), and
   needs no copy of git's option table.
3. *Share a helper with #241?* #241 hasn't landed, so add the helper here.
   Leave `_check_dangerous_flags` unchanged and leave cross-PR notes.
4. *Incident log source:* the host's `~/.pm/debug/default.log` isn't mounted
   here. The subagent transcript holds the same commands with their exact
   output, and those are what the tests replay.

## Edge cases / out of scope
- Repo-config-driven broad pushes are possible: `remote.origin.mirror=true`,
  `push.default=matching`, a `remote.origin.push` refspec of `refs/*:refs/*`,
  or multiple `pushurl`s. The incident's push also hit a local `pushurl`.
  These belong to the separate redesign plan ("isolation from repo
  settings"), so this PR doesn't address them.
- `--delete <allowed>` and `--prune` are unchanged.
- The `fetch --upl=…` prefix gap belongs to #241. The replay test checks only
  that the remote refs are unchanged for it.
- The installed wrappers in already-running containers are fixed only when
  those containers are recreated, because the wrapper is written at container
  setup.
