---
title: Scenario 11 — Push proxy bypasses PR workdir on direct upstream push
description: Verify ba57e94 — when a target repo has a real upstream resolvable via resolve_real_origin, _local_push pushes directly from the caller's clone and leaves the PR workdir untouched; the legacy fetch-into-target path runs only as a fallback.
---

## Verdict

PASS — all 4 functional steps succeeded plus asciinema capture.

## Environment

- Host: Linux 061c104c55bf 6.17.0-1014-nvidia (aarch64)
- git: 2.34.1
- python: 3.10.12
- Source: /workspace (PR branch pm/pr-6be8ee6-bug-fix-flow-surface-tui-qa-repro-instructions-in-)
- PR workdir referenced in scenario spec: /home/matt/.pm/workdirs/project-manager-828c8d0a/pm-pr-6be8ee6-bug-fix-flow-surface-tui-qa-repro-in-e802a472 (host-only path — this QA was executed in the isolated /workspace clone of the same branch, which is identical at HEAD)
- Commit under test: ba57e943f193da0ecea3518df847277c08fc2d0f ("qa: push proxy bypasses PR workdir when real upstream exists")

## Step 1 — pytest

```
grep -c '^    def test_' tests/test_push_proxy.py     # → 50
python3 -m pytest tests/test_push_proxy.py -q          # → 50 passed in 76.55s
```

`test_local_push_with_upstream_bypasses_pr_workdir` is defined at
`tests/test_push_proxy.py:458` and is included in the 50 passing tests.
No pre-existing stdin failure surfaced in this run. Full log:
`pytest.log`.

## Step 2 — code inspection of `pm_core/push_proxy.py:_local_push` (lines 338–424)

Captured via `sed -n '338,424p' pm_core/push_proxy.py` → `local_push_source.log`.

- (a) `resolve_real_origin(target_repo)` is called at line 384, after
  `source = caller_workdir or self.workdir` (line 363), `src_ref`
  (lines 367–377), and `refspec` (line 380) are resolved.
- (b) When `real_url` is truthy, the proxy runs
  `git -C <source> push <real_url> <refspec>` at line 386 and returns
  the result. No `git -C <target_repo> …` invocation is reachable on
  that branch.
- (c) The legacy fetch-into-target path
  `git -C <target_repo> fetch --update-head-ok <source> <refspec>`
  starts at line 407 and runs only when `real_url` is falsy.

## Step 3 — integration test: upstream-present path

Script: `it_upstream.py`. Output: `it-upstream.log`.

Fixture layout (under `/tmp/proxy-it-up-<ts>/`):
- `real-upstream.git` — bare repo, represents github (terminal real URL).
- `upstream.git` — bare local mirror with `origin = file://…/real-upstream.git`.
  The `file://` scheme makes `resolve_real_origin` treat upstream.git's
  origin as a real URL and terminate there.
- `pr-workdir` — clone of `upstream.git`, branch `pm/pr-test-feature` pushed.
- `caller` — clone of `pr-workdir`, adds a new commit on the feature branch.

Direct invocation: `proxy._local_push(target_repo=pr-workdir,
branch="pm/pr-test-feature", caller_workdir=caller)`.

Assertions (all passed):

- (a) `result["exit_code"] == 0`. Stderr from real git:
  `To file:///…/real-upstream.git  * [new branch]  pm/pr-test-feature -> pm/pr-test-feature`.
- (b) `git -C pr-workdir status --porcelain` after the push: empty —
  no phantom staged deletions/modifications.
- (c) `git -C pr-workdir rev-parse HEAD` unchanged from baseline
  (`bd6f5ed6…` pre and post).
- (d) `git -C real-upstream.git rev-parse refs/heads/pm/pr-test-feature`
  equals caller's new commit SHA (`4d120a1c…`).

`PATH` is prepended with `/usr/bin` for the duration of the call so the
proxy's `subprocess.run([\"git\", …])` resolves to `/usr/bin/git` and
not to the outer QA push-proxy wrapper at `/home/pm/.local/bin/git`.

## Step 4 — integration test: fallback (no upstream) path

Script: `it_fallback.py`. Output: `it-fallback.log`. The fixture
follows the spec's alternative: a `git init` pr-workdir with no
`origin` remote, plus a caller clone. `resolve_real_origin` would
return `None` naturally on this fixture, but to be explicit the test
also patches `pm_core.push_proxy.resolve_real_origin` to `None` so the
fallback branch is exercised deterministically.

Assertions (all passed):

- (a) `result["exit_code"] == 0`. Stderr from real git:
  `From /…/caller2  3fdff64..f7d876d  pm/pr-test-feature -> pm/pr-test-feature`.
- (b) `git -C pr-workdir-nolocal rev-parse refs/heads/pm/pr-test-feature`
  equals caller's new commit SHA (`f7d876dd…`) — legacy fetch path
  updated the branch ref as expected.
- (c) Worktree/index staleness: in this fixture HEAD was on `master`
  before the push, so `git status` showed no phantom changes — but
  this is fixture-specific, not a contradiction of the documented
  fallback behavior (stale worktree on the feature branch).

## Step 5 — asciinema capture

`recording.cast` covers steps 1–4 in a single bash run
(`/tmp/scenario11_demo.sh`, contents preserved in `transcript.log`).
Recorded inside a `tmux -L s11` pane to provide asciinema a TTY (per
the no-TTY workaround in `pm/qa/artifacts/cli-recording.md`).

## Files

- `pytest.log` — full `python3 -m pytest tests/test_push_proxy.py -q` output (50 passed).
- `local_push_source.log` — `sed -n '338,424p' pm_core/push_proxy.py`.
- `it_upstream.py` — step 3 script (upstream-present path).
- `it-upstream.log` — step 3 script output (all assertions passed).
- `it_fallback.py` — step 4 script (fallback path).
- `it-fallback.log` — step 4 script output (all assertions passed).
- `recording.cast` — asciinema replay of the full step-1-through-4 script.
- `transcript.log` — plain-text trace (`set -x`) of the same script.
- `manifest.md` — this file.
