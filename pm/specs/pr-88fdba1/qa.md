# QA Spec: Fix shared push proxy using first-scenario workdir

## Requirements

### R1 — `_local_push` fetches from caller's clone, not `self.workdir`

`PushProxy._local_push` now accepts `caller_workdir: str | None`.  When a
`"workdir"` field is present in the request, the step-1 fetch command is:

```
git -C <target_repo> fetch --update-head-ok <caller_workdir> <refspec>
```

not `<self.workdir>`.  Without the fix, commits in any scenario other than
the first are invisible to the proxy — push reports "Everything up-to-date"
while the remote stays at the old HEAD.

### R2 — `_execute_read_cmd` uses caller's workdir as cwd

`PushProxy._execute_read_cmd` now runs `git fetch/pull` with
`cwd=caller_workdir or self.workdir`.  Before the fix, fetched changes always
landed in scenario 1's clone.

### R3 — `_execute_push` uses caller's workdir for non-local remotes

For real (non-local) remotes `git push` is run from `caller_workdir or
self.workdir`.  QA scenarios use local clones so this path is exercised only
when a non-local origin is involved, but correctness requires it.

### R4 — `_extract_target_branch` resolves HEAD from caller's workdir

When `git push origin` is issued without an explicit refspec, HEAD must be
resolved via `git rev-parse --abbrev-ref HEAD` in the caller's clone (not in
`self.workdir`).  `_extract_target_branch` now accepts `workdir: str | None`.

### R5 — Git wrapper bakes `HOST_WORKDIR` and adds `"workdir"` to request JSON

`_build_git_setup_script(has_push_proxy=True, host_workdir=<path>)` emits:

```sh
HOST_WORKDIR="/escaped/path"
```

and the JSON request line includes:

```
"workdir": "$escaped_workdir"
```

The `escaped_workdir` variable is computed with:

```sh
escaped_workdir=$(printf '%s' "$HOST_WORKDIR" | sed 's/\\/\\\\/g; s/"/\\"/g')
```

When `host_workdir` is absent/None, neither `HOST_WORKDIR` nor the `"workdir"`
field appear in the script (backward compatibility).

### R6 — Backward compatibility: requests without `"workdir"` fall back to `self.workdir`

`caller_workdir: str | None = request.get("workdir") or None` treats both the
absent key and the empty string as None, falling back to `self.workdir`.
Existing per-container proxy wrappers continue to work unchanged.

---

## Setup

- Python 3.11+ with `project_manager` installed in a venv (`pip install -e .`
  from the repo root).
- `git` available on PATH.
- No Docker, no network access, no Claude session required.
- Run from the working directory:
  `/home/mjtomei/.pm/workdirs/project-manager-828c8d0a/pm-pr-88fdba1-fix-shared-push-proxy-using-first-sc-d0f78a09`

---

## Edge Cases

### EC1 — Empty-string `"workdir"` treated as absent

`request.get("workdir") or None` coerces `""` to `None`.  The proxy falls back
to `self.workdir` rather than passing an empty string to `cwd=`.

### EC2 — `_extract_target_branch` with `workdir=None` (legacy)

When `caller_workdir` is `None`, `workdir or self.workdir` yields `self.workdir`
for all HEAD-resolution calls.

### EC3 — `_build_git_setup_script` with path containing spaces and quotes

`HOST_WORKDIR="/path/with spaces/and\"quote\""` must produce a script that
a POSIX shell accepts (`bash -n`) and a JSON decoder can parse from the
request line.

### EC4 — `HOST_WORKDIR` absent when `host_workdir` is not provided

Calling `_build_git_setup_script(has_push_proxy=True)` (no `host_workdir`)
must produce a script with no `HOST_WORKDIR` variable and no `"workdir"` key
in the request JSON — preserving the legacy no-workdir wire format.

### EC5 — `git push origin` (no refspec) from second scenario clone

When a container on the wrong-branch workdir pushes without an explicit
refspec, HEAD is resolved from the *caller's* clone.  The proxy must allow
the push if the caller's HEAD is on the allowed branch, even though
`self.workdir` may have a different HEAD.

---

## Pass/Fail Criteria

**Pass:**
- All 117 unit tests continue to pass (`pytest tests/test_push_proxy.py tests/test_container.py`).
- The `TestCallerWorkdir` class (6 tests) all pass — these directly verify R1–R2 and backward compat.
- The `test_host_workdir_*` tests (3 tests in `TestGitSetupScript`) all pass — these verify R5.
- In an integration test with real git repos, a commit made in scenario 2's clone reaches the target repo after a push request that includes `"workdir": <scenario2_clone>`.
- In an integration test, a fetch request with `"workdir": <scenario2_clone>` lands commits in scenario 2's clone, not scenario 1's.
- A push request with `"workdir": ""` (empty string) falls back to `self.workdir` and succeeds.
- `_build_git_setup_script` output with a path containing spaces passes `bash -n`.

**Fail:**
- Any existing test regresses.
- A push from scenario 2's clone still shows "Everything up-to-date" in an integration test (proxy still using `self.workdir`).
- A fetch from scenario 2 lands commits in scenario 1's clone instead.
- The `"workdir"` field appears in the wrapper script when `host_workdir` is not provided.
- Shell syntax error in the generated wrapper script.

---

## Ambiguities

### A1 — Does `_resolve_local_remote_url` need to use caller's workdir?

**Resolved: No.** All QA scenario clones have the same origin URL (the shared
PR workdir), so running this from `self.workdir` or the caller's workdir
returns the same answer.  The code calls `_resolve_local_remote_url(workdir,
remote)` where `workdir = caller_workdir or self.workdir`, which is correct.

### A2 — Does `ls-remote` need fixing?

**Resolved: No.** `ls-remote` is read-only and the result is workdir-independent.
The proxy now passes `caller_workdir` to `_execute_read_cmd` for `ls-remote`
too (it just sets `cwd` which is harmless for remote-URL ls-remote calls).

### A3 — Does the non-container tmux path need changes?

**Resolved: No.** When scenarios run in plain tmux windows, no git wrapper is
installed and no proxy runs.  `_build_git_setup_script` is never called in
that path.

### A4 — Does `start_push_proxy` need to change?

**Resolved: No.** Each container's wrapper bakes its own `HOST_WORKDIR` at
creation time.  The proxy subprocess needs no registry; it reads the workdir
from each incoming request.

---

## Mocks

This PR involves no Claude sessions, no tmux, and no real network calls.

**What remains unmocked:**
- `subprocess.run` — unit tests mock it; integration scenarios use real git
  processes to exercise the actual fetch/push logic end-to-end.
- Unix socket communication — real sockets are used (the proxy runs in a
  background thread in tests).
- Git repos — integration scenarios create real temporary repos with
  `git init`, `git commit`, etc.

**For all scenarios:** no external mocks are required beyond what `pytest`
and `unittest.mock.patch` already provide in the test suite.
