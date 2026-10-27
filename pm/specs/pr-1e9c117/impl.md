# pr-1e9c117 — fail-closed capture routing for the `/pm-captures` mount

Bug: `paths.captures_dir()` uses the `/pm-captures` bind-mount for **any**
`pr_id` when `PM_CAPTURES_PR` is unset. A throwaway pm project driven inside a
scenario container (harness mistake, `PM_CAPTURES_PR` unset) wrote its own
`scenarios/<n>/{prompt.md,scenario.json,verdict.md}` into the enclosing PR's
real captures dir, destroying evidence (pr-b53bfe2 QA S4, quarantined to
`scenarios/4/contamination`).

## 1. Requirements

R1. **Fail closed.** `pm_core.paths.captures_dir()` returns
    `CONTAINER_CAPTURES_MOUNT` (`"/pm-captures"`) only when the mount's owner
    marker `CAPTURES_PR_ENV` (`"PM_CAPTURES_PR"`) is present, non-empty and
    equal to `pr_id`. The current condition
    (`pm_core/paths.py:129`, `if mount.is_dir() and (not mount_pr or mount_pr == pr_id)`)
    drops the `not mount_pr` fail-open branch.

R2. **Host fallback on absent/empty/mismatched marker.** When the marker is
    absent, empty/whitespace-only, or names a different PR, resolution
    continues to step 3: create and return
    `~/.pm/sessions/<tag>/captures/<pr_id>` when a session tag resolves, else
    return `None` (unchanged).

R3. **Matching owner preserved.** `PM_CAPTURES_PR == pr_id` still returns the
    mount even when the host path does not exist — this is how in-container
    workers for the PR find their captures (`container.create_container` sets
    both the `-v <host>:/pm-captures` mount and `-e PM_CAPTURES_PR=<pr>`,
    `pm_core/container.py:683-696`).

R4. **Host-first precedence preserved.** An existing host path still wins over
    the mount (step 1 of the docstring), so the host never routes into
    `/pm-captures`; the change only affects the fall-through.

R5. **Docstring truth.** `captures_dir`'s docstring currently documents the
    fail-open behaviour ("when it is unset any PR may use the mount") —
    rewrite step 2 to state the owner check and why it fails closed.
    `pm qa captures-path`'s docstring (`pm_core/cli/qa.py:~193-200`) also
    explains the mount by "the host-side `~/.pm` location isn't visible from
    inside the container"; add the owner-marker condition so it does not
    promise the mount unconditionally.

R6. **Tests.** Update `tests/test_captures_dir_mount.py`:
    - matching owner → mount (keep);
    - different owner → host path, mount untouched (keep);
    - absent owner → host path (flip the old
      `test_mount_without_pr_env_keeps_old_behaviour`, which asserts the bug);
    - empty and whitespace-only owner → host path;
    - nested-throwaway fixture: outer PR owns the mount, nested project's PR
      with a *different session tag* lands in its own captures dir, and the
      mount stays empty;
    - fail-closed with no resolvable tag → `None` (not the mount);
    - host fallback with no mount → host path created (regression guard).

R7. **No collateral change.** `captures_root`, `qa_loop`,
    `_write_scenario_capture_file`, `cli/qa.py` resolution flow and
    `container.create_container` are unchanged; they already route through
    `captures_dir`.

## 2. Implicit requirements

- `captures_dir` may now return `None` in one more situation (marker set to a
  different PR and no tag). Callers already handle `None`:
  `qa_loop._write_scenario_capture_file` warns and returns `None`
  (`pm_core/qa_loop.py:1898-1902`); `pm qa captures-path` errors out
  (`pm_core/cli/qa.py:211-215`); `qa_loop.py:3362` and `container.py:687`
  guard on `None`/exceptions.
- `container.create_container` runs on the host, where `/pm-captures` is
  normally absent; nested-container QA (host itself a container with the outer
  PR's marker) must still be able to mount an inner PR's *own* dir — R2 gives
  it the inner host path.
- The fix must not write into the real `/pm-captures` while reproducing or
  testing; repro uses a private mount namespace (`unshare -rm`) or temp dirs,
  never the live evidence dir.
- Container workers for the owning PR keep working because `create_container`
  sets the marker alongside the mount; the failure mode for a marker-less
  container is a container-local `~/.pm` path (recoverable), never
  overwriting host evidence (unrecoverable).

## 3. Ambiguities (resolved)

- **A1 — old containers created without the marker.** The prior change
  (237179d7) deliberately kept them working ("when it is unset any PR may use
  the mount", asserted by `test_mount_without_pr_env_keeps_old_behaviour`).
  The PR note explicitly overrides that: fail closed. A container created by
  an older pm now writes to its own container-local host path instead of the
  mount. Resolution: fail closed; note the trade-off in the code comment.
- **A2 — empty / whitespace marker.** Treated as absent (fail closed), and the
  marker is stripped before comparison so a trailing newline from a shell
  export still matches. No other normalisation.
- **A3 — marker matches but the host path also exists.** Unchanged: the
  existing host path wins (step 1). Not part of the bug.
- **A4 — `captures_root()`.** It never consults the mount; no change.
- **A5 — logging on mismatch.** Nested throwaway projects mismatch
  legitimately, so a warning would be noise; no new logging. (No module
  logger exists in `paths.py`.)

No **[UNRESOLVED]** items.

## 4. Edge cases

- `pr_id == ""`: a non-empty marker can never equal it, so the mount is never
  returned; falls through to host resolution/`None`.
- Marker names another PR and no session tag resolves (`session_tag=""` or a
  non-git cwd): returns `None` where it used to return the mount. Callers
  degrade gracefully (warning / CLI error).
- Marker matches but the mount is missing: host path (unchanged).
- Mount missing entirely: host path created (unchanged).
- Nested container creation: outer container has marker=outer-PR; an inner
  `create_container` for inner-PR resolves the inner host path (R2) and sets
  its own `-e PM_CAPTURES_PR=inner-PR`, so the inner container's
  `/pm-captures` is the inner PR's dir.
- Historical specs (`pm/specs/pr-0b87a97/impl.md` item 21, `qa.md`) describe
  the old "unset keeps old behaviour" contract; they are records of a prior
  change and are left untouched. This spec is the current contract.

## 5. Implementation notes

- `pm_core/paths.py`: replace the mount condition with
  `mount_pr = (os.environ.get(CAPTURES_PR_ENV) or "").strip()` and
  `if mount.is_dir() and mount_pr and mount_pr == pr_id:`. Update the
  docstring step 2.
- `pm_core/cli/qa.py`: docstring sentence about the mount.
- `tests/test_captures_dir_mount.py`: rewrite the unset test, add the cases
  in R6.

## 6. Implementation record (2739187c)

- Fix as above; tests rewritten to 12 cases in
  `tests/test_captures_dir_mount.py` (5 fail on the pre-fix tree because the
  mount is returned instead of the host path; all 12 pass post-fix).
- Full suite: 3747 passed, 1 skipped. The 60 failures in `test_git_ops`,
  `test_merge_publish`, `test_signoff_integration` and `test_hook_events` are
  identical on the pre-fix tree (environment: the sandbox's git, not this
  change).
- Evidence (`$(pm qa captures-path pr-1e9c117)`):
  - `impl/pre-fix/nested-throwaway-overwrites-mount/` — recording + manifest
    of the incident reproduced against a pre-fix tree copy (bd21fabf).
  - `impl/pre-fix/failing-tests-on-prefix.txt` — pre-fix test run.
  - `impl/post-fix/nested-throwaway-fails-closed/` — recording + manifest of
    the same repro post-fix, including the owning-PR positive control.
- The repro binds a sandbox over `/pm-captures` inside `unshare -rm`, so the
  live evidence dir was never written by the nested project.

## 7. Review-loop follow-up

- Docstring truth (R5) was only partially done in 2739187c: the closing
  sentence of `captures_dir` still said it returns `None` only when "no tag
  can be derived AND the bind-mount isn't present". After the fail-closed
  change it also returns `None` when the mount exists but is not owned by
  *pr_id*. Reworded to state both conditions; no behaviour change.
