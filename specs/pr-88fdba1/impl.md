# Implementation Spec: Fix shared push proxy using first-scenario workdir

## Requirements

### R1 — Fix `_local_push` source workdir

**File:** `pm_core/push_proxy.py:323-392`
**Function:** `PushProxy._local_push`

Currently: `git -C target_repo fetch --update-head-ok self.workdir refspec` (line 338-339) uses `self.workdir` — the first scenario's clone — as the source for all containers sharing the proxy.

Fix: `_local_push` must use the requesting container's host-side clone path as the source, not `self.workdir`.

### R2 — Fix `_execute_read_cmd` working directory

**File:** `pm_core/push_proxy.py:394-422`
**Function:** `PushProxy._execute_read_cmd`

Currently: `subprocess.run(cmd, cwd=self.workdir, ...)` (line 409) runs `git fetch/pull` from `self.workdir`. For shared proxies, fetched changes land in the first scenario's clone only.

Fix: `_execute_read_cmd` must run `git fetch/pull` from the requesting container's host-side clone path.

### R3 — Fix `_execute_push` working directory for real remotes

**File:** `pm_core/push_proxy.py:260-321`
**Function:** `PushProxy._execute_push`

For non-local remotes (real GitHub URLs), `git push` runs from `self.workdir` (line 305-309). QA scenarios use `--local` clones so this path is not exercised today, but the fix should propagate the caller workdir here for correctness.

Fix: `_execute_push` uses caller's workdir for `git remote get-url` lookup and `git push` execution.

### R4 — Fix `_extract_target_branch` workdir for HEAD resolution

**File:** `pm_core/push_proxy.py:441-507`
**Function:** `PushProxy._extract_target_branch`

Uses `self.workdir` for `git rev-parse --abbrev-ref HEAD` (lines 483-490, 497-503). For shared proxies, this resolves HEAD from the first scenario's clone.

Fix: pass the effective workdir so HEAD is resolved from the correct clone.

### R5 — Include caller's host-side workdir in request JSON

**File:** `pm_core/container.py:229-276`
**Function:** `_build_git_setup_script`

The git wrapper script constructs the JSON request sent to the proxy socket. It must include the host-side clone path so the proxy can use it directly — no registry or lookup needed.

Fix: `_build_git_setup_script` accepts `host_workdir: str | None = None`; when provided, it bakes `HOST_WORKDIR="..."` as a literal into the wrapper and adds `"workdir": "$HOST_WORKDIR"` to the request JSON. Call site passes `host_workdir=str(workdir)`.

### R6 — Update module docstring

**File:** `pm_core/push_proxy.py:1-24`

The docstring still says "One proxy per container — no shared state, no routing" (line 16), which was invalidated by PR #135.

Fix: update to describe the shared-proxy model and the per-request workdir field.

---

## Implicit Requirements

### IR1 — Backward compatibility with legacy per-container proxies

Legacy proxies (no `session_tag`/`pr_id`) have `self.workdir` set correctly for the single container they serve. If a request has no `"workdir"` field (old wrapper), the proxy falls back to `self.workdir`.

### IR2 — Non-container execution path is unaffected

QA scenarios can also run in plain tmux windows via `_launch_scenarios_in_tmux` (no Docker). In that path `_build_git_setup_script` is never called, no wrapper is installed, and no proxy runs. Git commands execute directly in the clone directory. The `HOST_WORKDIR` changes are inert for this path.

The local/vanilla/github `Backend` types control PR submission and merge detection — they are orthogonal to whether containers are used. A project using `LocalBackend` or `VanillaBackend` that runs QA in containers is affected by this fix in the same way as a GitHub-backend project.

### IR3 — No cross-process state needed

The proxy runs as an independent subprocess. With the host workdir sent inline in each request, no shared file or in-memory registry is required. The proxy uses `request.get("workdir") or self.workdir` directly.

### IR3 — `_extract_target_branch` in shared proxy context

When called from `_execute_push`, this method uses `self.workdir` for `git rev-parse`. If a container pushes without an explicit refspec (`git push origin`), HEAD is resolved from the wrong clone. The method must accept an optional `workdir` parameter.

### IR4 — `_execute_push` also calls `_resolve_local_remote_url(self.workdir, remote)`

To check whether origin is a local path (line 299), the proxy reads `git remote get-url origin` from `self.workdir`. All QA scenario clones share the same origin URL (the PR workdir), so this returns the correct answer regardless of which clone it runs from. **No change needed** for the local-target detection, but the workdir used for `git push` in the non-local branch must still be corrected.

---

## Ambiguities

### A1 — How does the proxy identify the correct workdir? *(resolved)*

**Resolved:** The host-side clone path is baked into the wrapper script as `HOST_WORKDIR="..."` at container creation time. Every request includes `"workdir": "$HOST_WORKDIR"`. The proxy uses it directly — no registry, no lookup. No ambiguity remains.

### A2 — Does `_resolve_local_remote_url` need to use the caller's workdir?

**Resolution:** No. QA scenario clones all have the same origin URL (the PR workdir). Using `self.workdir` or the caller's workdir yields the same result. The existing code is correct.

### A3 — Should `ls-remote` be fixed?

**Resolution:** No. Per the task description, `ls-remote` is read-only and workdir-independent. No change needed.

---

## Edge Cases

### EC1 — Host path contains characters needing JSON or shell escaping

`HOST_WORKDIR` is a filesystem path like `/home/user/.pm/workdirs/qa/pr1-l1/s-0/repo`. Paths may contain spaces or special characters. The wrapper must escape the value for inclusion in the JSON literal. The existing `escaped=$(printf '%s' "$arg" | sed 's/\\/\\\\/g; s/"/\\"/g')` pattern already handles this and can be reused. Baking the path as a shell variable with double quotes handles spaces correctly.

### EC2 — `_extract_target_branch` called with `workdir=None`

When `caller_workdir` is `None` (legacy request, no `"workdir"` field), `_extract_target_branch` falls back to `self.workdir`. Consistent with the general fallback strategy.

### EC3 — Existing tests

Tests in `test_push_proxy.py` use `PushProxy(sock_path, "/tmp/fake-workdir", "pm/pr-123-feature")` directly and send requests without a `"workdir"` field. These must continue to pass unchanged (backward compat fallback to `self.workdir`).

### EC4 — Proxy reuse: no action needed in `start_push_proxy`

With the registry removed, `start_push_proxy` requires no changes beyond what already exists. Each container creation bakes its own workdir into its own wrapper script.

---

## Implementation Plan

1. **`push_proxy.py`**:
   - `_handle_connection`: extract `"workdir"` field from request as `caller_workdir`, pass to dispatch methods
   - `_execute_push(args, caller_workdir=None)`: use `caller_workdir or self.workdir`; pass to `_local_push` and `_extract_target_branch`
   - `_local_push(target_repo, branch, caller_workdir=None)`: use `caller_workdir or self.workdir` as fetch source
   - `_execute_read_cmd(cmd, args, caller_workdir=None)`: use `caller_workdir or self.workdir` as cwd
   - `_extract_target_branch(push_args, workdir=None)`: use `workdir or self.workdir` for `git rev-parse`
   - Update module docstring

2. **`container.py`**:
   - `_build_git_setup_script(has_push_proxy, host_workdir=None)`: bake `HOST_WORKDIR` literal into wrapper; add `"workdir"` field to request JSON
   - Call site at line 502: pass `host_workdir=str(workdir)`

3. **`tests/test_push_proxy.py`**:
   - Add `TestSharedProxyWorkdir` class testing that the `"workdir"` field in a request overrides `self.workdir` for `_local_push`, `_execute_read_cmd`, and `_execute_push`
   - Test backward compat (no `"workdir"` field → falls back to `self.workdir`)
