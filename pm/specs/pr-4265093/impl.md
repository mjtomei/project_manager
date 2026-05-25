# Spec: Bug — leaked containers exhaust the podman keyring, breaking container QA

PR: pr-4265093 (#227)

## Problem (root cause, as diagnosed during #225 QA)

pm does not reliably reap finished PRs' containers. Under load, dozens of
`pm-*` containers (impl + qa + review across many PRs) stay **running**. Each
running rootless-podman container holds session keys in the namespaced-root
(uid 100000) keyring. That keyring has a hard quota (observed 200/200 keys,
14000/20000 bytes). Once full, `runc`/`crun` cannot join a session keyring and
every new `podman run`/`podman exec` fails:

    runc: exec failed: unable to start container process: unable to join
    session keyring: unable to create session key: disk quota exceeded

QA launches each scenario worker via `podman exec`/`podman run` into a
per-scenario container, so once the ceiling is hit, workers cannot start and
QA silently degrades on **every** PR — containers show "Up" but nothing runs.

Pruning **stopped** containers does NOT help: the 200 keys are held by the
**running** containers (`podman container prune` took 128→79 with keyring
still 200/200). The real fix is reaping the running orphans.

## Relevant code (grounded)

- `pm_core/container.py`
  - `_run_runtime(*args, check, timeout)` — single chokepoint for every
    runtime subprocess; logs rc/stderr (`container.py:347`).
  - `create_container(...)` (`:577`) — `podman run -d ... bash -c <setup>`
    (`:885`) then a readiness-probe loop doing `podman exec ... test -f
    sentinel` (`:898`). Both the run and the exec are exactly where a full
    keyring first bites. On setup timeout it raises a generic
    `ContainerError("...setup timed out... memory pressure (try stopping
    unused containers with 'pm session cleanup')")` (`:910`). **Note: `pm
    session cleanup` does not exist** — only `pm session kill` and `pm
    container cleanup`. That message is misleading (incidental fix).
  - Container name shapes (all embed `pr_id`):
    - impl:   `pm-{tag}-impl-{pr_id}`            (`pr.py:1024`, label `impl-{id}`)
    - review: `pm-{tag}-review-{pr_id}`          (`pr.py:1210`, label `review-{id}`)
    - qa:     `pm-{tag}-qa-{pr_id}-{loop_id}-s{N}` (`qa_container_name`, `:565`)
    - legacy (no tag): same without the `{tag}-` segment.
  - Existing cleanup helpers:
    - `cleanup_qa_containers(pr_id, loop_id, ...)` (`:1156`)
    - `cleanup_pr_containers(pr_id, ...)` (`:1193`) — all loops for one PR.
    - `cleanup_orphaned_qa_containers(session, pr_id, ...)` (`:1237`) — only
      QA containers, only for ONE pr_id, only checks tmux **windows in one
      session**; called at QA-run start (`qa_loop.py:3039`). Does not consider
      PR merged/closed, does not cover impl/review, does not cross sessions or
      reap stopped containers whose PR is terminal.
    - `cleanup_session_containers(session_tag)` (`:1295`) — on `pm session
      kill` (`session.py:606`).
    - `cleanup_all_containers()` (`:1324`) — nuke all pm containers.
  - `remove_container(name)` (`:1003`) — `rm -f` + waits until gone, also
    stops the push proxy.
- `pm_core/cli/container.py:269` — `pm container cleanup [--pr]` removes ALL
  pm containers (optionally name-substring-filtered). Blunt; not orphan-aware.
- `pm_core/store.py` — `load(root, validate=False)` and `get_pr(data, id)`
  (`:548`); PR statuses in `pm_core/pr_utils.py`:
  `{pending,in_progress,in_review,qa,merged,closed}` — **terminal =
  {merged, closed}**.
- `pm_core/tmux.py` — `list_windows(session)` (`:377`),
  `session_exists(name)` (`:47`).
- QA concurrency: `qa-max-scenarios` global setting caps the **per-loop**
  initial batch (`qa_loop.py:3231`, default 0 = unlimited); queued scenarios
  launch as earlier ones finish. There is **no global** bound across PRs.

## 1. Requirements (restated, grounded)

R1. **Reap orphaned containers (running AND stopped).** Add a general reaper
    that lists every `pm-*` container (`ps -a`), maps each to its `pr_id` via
    the name, and removes it when it is orphaned, where orphaned means:
    (a) the PR is merged/closed, or no longer present in project.yaml; or
    (b) the owning tmux session/window is gone.
    Must cover impl, review, and qa containers, across all PRs and (best
    effort) all sessions — not just the current PR's QA windows.

R2. **Run the reaper on the relevant lifecycle hooks and periodically.**
    - At QA-run start (replace/augment the narrow
      `cleanup_orphaned_qa_containers` call at `qa_loop.py:3039` with the
      broad reaper so a new run cleans up *other* finished PRs too).
    - On session teardown (already removes own-session containers via
      `cleanup_session_containers`; additionally reap cross-session orphans).
    - Expose it as a CLI command so an operator/automation can run it
      between runs.

R3. **Bound concurrent containers.** Before launching QA scenario containers,
    enforce a configurable ceiling on the number of *running* pm containers.
    When the ceiling would be exceeded: reap orphans first; if still at/over
    the ceiling, do not blindly launch into a doomed keyring — surface a clear
    error/queue rather than silently degrading.

R4. **Surface a clear error on keyring/quota exhaustion** instead of the
    generic "memory pressure" timeout. Detect the keyring signature in
    runtime stderr (`session keyring`, `disk quota exceeded`,
    `unable to create session key`) at the `podman run`/`podman exec`
    chokepoints and raise/log an actionable `ContainerError` naming the cause
    and the remedy (reap orphans; raise the keyring quota).

R5. **Keyring quota visibility (safety margin).** Provide a read-only
    diagnostic of current keyring usage (parse `/proc/key-users` for the
    podman subuid) so pm can warn when near the ceiling before launch and so
    `pm container status` can show headroom. Do **not** mutate sysctl
    (`kernel.keys.maxkeys`/`maxbytes`) automatically — that needs root and is
    environment policy; document it in the actionable error instead.

## 2. Implicit Requirements

- IR1. Reaping must be **conservative**: never remove a container whose PR is
  still active (pending/in_progress/in_review/qa) AND whose window/session is
  live. When PR status can't be determined (no project root, parse failure),
  fall back to the tmux-liveness check only; if that's also indeterminate,
  **skip** (don't remove) — a false reap kills a live worker.
- IR2. Name parsing must handle both session-tagged and legacy names and not
  choke on unexpected shapes (skip, don't crash).
- IR3. The reaper and the bound must be **best-effort and non-fatal**: a
  runtime/list failure returns 0 and logs, never aborts the QA run (mirrors
  `cleanup_orphaned_qa_containers`' `except: return 0`).
- IR4. Keyring detection must be runtime-agnostic-safe: only meaningful for
  podman; for docker the signature won't appear, so detection is a no-op.
- IR5. Reaping must remove the push proxy too — already handled because the
  reaper goes through `remove_container`.
- IR6. Determining "session gone": a container's session_tag is embedded in
  the name; map it to the tmux session and check `session_exists` /
  `list_windows`. If we can't resolve the session name from the tag, treat
  tmux-liveness as indeterminate (per IR1).

## 3. Ambiguities (resolved)

- A1. *Global bound value & mechanism.* Resolved: add a configurable global
  setting `qa-max-containers` (default 0 = unlimited, preserving today's
  behavior so we don't regress large fan-out on docker where there's no
  keyring). The QA container launcher counts running `pm-*` containers; if a
  positive cap is set and would be exceeded, it reaps orphans, then caps the
  batch it launches (remaining scenarios queue via the existing queue
  machinery) and, if still at the cap with nothing reapable, records a clear
  error. Keyring-aware headroom (R5) provides the safety even when the count
  cap is left at 0.
- A2. *Replace vs augment `cleanup_orphaned_qa_containers`.* Resolved:
  keep the function (callers/tests depend on it) but have the QA-start hook
  also call the new broad reaper. The broad reaper subsumes its behavior for
  QA names and adds impl/review + PR-status awareness.
- A3. *CLI surface.* Resolved: add `pm container reap` (orphan-aware,
  dry-run-capable) rather than changing `pm container cleanup`'s existing
  nuke-all semantics, which other flows/tests rely on.
- A4. *Mutating keyring sysctl.* Resolved: no. Read-only diagnostic +
  actionable message only (R5).
- A5. *Which "session" for liveness in the reaper.* Resolved: derive the
  tmux session name from the embedded session_tag using the same convention
  pm uses elsewhere; when unavailable, use PR-status as the sole signal.

No **[UNRESOLVED]** ambiguities.

## 4. Edge Cases

- E1. Interactive Scenario 0 container should not be reaped while its PR is
  still in QA and its window is live — covered by IR1 (active PR + live
  window ⇒ keep).
- E2. A PR that merged while QA was mid-flight: its containers become
  reapable immediately (status terminal) — desired; that's the leak this
  fixes. Don't race a still-finalizing window: terminal status is the gate,
  and finalize windows are short-lived; acceptable.
- E3. Legacy (untagged) container whose session can't be derived: rely on
  PR-status; if PR missing from yaml ⇒ orphan.
- E4. Container for a `pr_id` not in this project's yaml at all (e.g. a
  different repo's session sharing the host): conservative — only reap when we
  positively know it's terminal/absent *and* this is the right project;
  otherwise skip. (Reaper scopes name parse to the loaded project's PRs;
  unknown pr_ids are left alone unless their tmux session is provably gone.)
- E5. Docker runtime: keyring detection no-ops; reaper + bound still apply
  (harmless, keeps behavior uniform).
- E6. Concurrent reaper invocations (two QA runs starting at once): each goes
  through `remove_container` which tolerates a removal already in flight
  (`:1015`); double-remove is safe.

## 5. Testability / repro note

The literal keyring-exhaustion symptom requires ~200 real running rootless
containers on a host with the default `keys.maxkeys` quota — not reproducible
as a unit test or in this sandbox. The fix is codified with unit tests over
mocked `_run_runtime`/project state:
- reaper removes terminal-PR and dead-session containers, keeps active ones;
- keyring-signature detection turns a runtime failure into the specific
  `ContainerError`;
- `qa-max-containers` bound caps/queues launches.
The end-to-end keyring behavior is documented in a PR note rather than a
flaky live capture.

## 6. Implementation plan

1. `container.py`:
   - `reap_orphaned_containers(project_root=None, *, dry_run=False) -> list[tuple[name, reason]]`:
     list `pm-*` via `ps -a`, parse `pr_id`/`session_tag`, decide orphan via
     PR-status (load yaml) + tmux liveness, `remove_container` each (unless
     dry_run). Best-effort, never raises.
   - `_parse_container_name(name) -> (kind, pr_id, session_tag, scenario)`.
   - `keyring_usage() -> dict|None`: parse `/proc/key-users`, return
     `{used, max, bytes_used, bytes_max}` for the relevant uid, else None.
   - `_is_keyring_exhaustion(stderr) -> bool` and raise a specific
     `ContainerError` from `create_container` when `podman run`/probe stderr
     matches; fix the misleading `pm session cleanup` message.
   - `running_container_count() -> int` helper for the bound.
2. `cli/container.py`: add `pm container reap [--dry-run]`; surface keyring
   headroom in `pm container status`.
3. `qa_loop.py`: at QA-start call `reap_orphaned_containers`; enforce
   `qa-max-containers` against `running_container_count()` before the launch
   batch.
4. `cli/session.py`: on kill, also reap cross-session orphans.
5. Tests in `tests/test_container.py` (+ qa_loop where wiring is testable).
