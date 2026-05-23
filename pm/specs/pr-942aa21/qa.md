# QA Spec for PR pr-942aa21: Add spec generation step between PR phases

## Requirements

1. **Spec generation CLI** (`pm pr spec <pr_id> <phase>`) — generates or displays specs for impl/qa phases. Without phase arg, lists all existing specs. With `--regenerate`, overwrites existing spec.

2. **Spec save CLI** (`pm pr spec-save <pr_id> <phase>`) — registers a spec file written by a Claude session at the canonical path `<pm-root>/specs/<pr-id>/<phase>.md` into project.yaml.

3. **Spec approve CLI** (`pm pr spec-approve <pr_id>`) — opens pending spec in `$EDITOR` for review; saving approves, emptying rejects. Clears `spec_pending` from the PR entry.

4. **Spec mode system** — global setting `spec-mode` (auto/review/prompt) controls whether specs pause for review. Per-PR `review_spec: true` overrides to review mode. `AMBIGUITY_FLAG` in prompt mode triggers review.

5. **Spec preamble injection** — when no spec exists for a phase, `spec_generation_preamble()` injects a "Step 0" into the Claude prompt instructing it to generate the spec first and call `pm pr spec-save`. When a spec exists, `format_spec_for_prompt()` includes it as context.

6. **Push proxy** (`pm_core/push_proxy.py`) — new host-side daemon per container. Listens on a Unix socket mounted into the container. Validates push targets against `allowed_push_branch`. Handles local-path origins (git clone --local) via fetch-based push. Supports push/fetch/pull/ls-remote commands.

7. **Container git wrapper** — shell script installed at `/usr/local/bin/git` inside containers. Intercepts push/fetch/pull/ls-remote, forwards to push proxy via Unix socket. All other git commands pass through to `/usr/bin/git`.

8. **QA scenarios use clones instead of worktrees** — `create_scenario_workdir()` now does `git clone --local` instead of `git worktree add`. Scenarios push fixes directly to the PR branch via the push proxy.

9. **Removed cherry-pick merge-back** — `_merge_scenario_commits()` and `made_changes` tracking removed. Scenarios now push directly.

10. **Scenario retry with backoff** — dead scenario windows are relaunched up to `_SCENARIO_MAX_RETRIES=10` times with exponential backoff starting at `_SCENARIO_RETRY_BASE=5` seconds.

11. **Scenario numbering offset** — `_next_scenario_offset()` scans previous QA runs to continue numbering, avoiding collisions across runs. Planner prompt uses `scenario_start` parameter.

12. **TUI: V key for spec review** — `action_review_spec` finds the oldest pending spec and launches `pm pr spec-approve` in a pane.

13. **TUI: /pr qa command** — routes to `qa_loop_ui.focus_or_start_qa()` instead of CLI. Status transition to "qa" when starting from "in_review".

14. **TUI: command bar race condition fix** — keystrokes between `/` press and command bar focus are buffered and replayed, preventing them from triggering TUI keybindings.

15. **Scenario 0 runs on host** — always runs without container, giving full access to host tools and git credentials.

16. **Planner false-positive fix** — plan parsing now requires real (non-placeholder) scenarios before accepting, avoiding false match on the prompt template's own `QA_PLAN_END` marker.

## Setup

- Use the TUI manual testing instruction: create a throwaway project in `/tmp` with `backend: local`, a mix of PR statuses, and the spec-mode setting configured.
- For push proxy and container tests: need Docker available and `container-mode` enabled in pm settings.
- For spec CLI tests: can run directly against the test project.

## Edge Cases

1. **Spec file exists but is empty** — `get_spec()` should return None; `spec-save` should reject.
2. **Spec file path stored but file deleted** — `get_spec()` should return None gracefully.
3. **Invalid phase argument** — both `pr spec` and `pr spec-save` should reject with error message.
4. **No project root found** — `set_spec()` with no root should warn and return None.
5. **Push to unauthorized branch** — push proxy must reject with clear error.
6. **Push proxy socket removed externally** — proxy daemon thread should detect and exit.
7. **Malformed JSON request to push proxy** — should return error response, not crash.
8. **Local-path origin chain** — `resolve_real_origin()` must follow chain to find real remote URL.
9. **Scenario window dies repeatedly** — retry count exhausted, scenario gets INPUT_REQUIRED verdict.
10. **Planner outputs placeholder scenarios** — parser should reject and keep polling.
11. **`review_spec: true` on PR** — should override global auto mode to review mode.
12. **AMBIGUITY_FLAG in prompt mode** — should set `spec_pending` and `needs_review=True`.
13. **Multiple pending specs** — `oldest_pending_spec_pr()` should return the one with earliest `generated_at`.
14. **Concurrent scenario pushes** — prompt tells scenarios to `git pull --rebase` on push failure.
15. **Container ready sentinel** — `create_container` polls for `/tmp/.pm-ready` up to 5 seconds.
16. **Keystroke buffer race** — typing `/commit` fast should deliver all characters to command bar.

## Pass/Fail Criteria

- **PASS**: All spec CLI commands work correctly (generate, save, approve, view). Spec content is properly injected into downstream prompts. Push proxy correctly allows/denies pushes. QA scenarios launch in clones (not worktrees), can push fixes, and retry on failure. TUI keybindings (V, /pr qa) work. No regressions in existing QA loop functionality.
- **NEEDS_WORK**: Any spec CLI command fails or produces incorrect output. Push proxy allows unauthorized pushes or blocks valid ones. Scenario clones don't check out the correct branch. Retry logic doesn't trigger on window death. Spec preamble appears when spec already exists (or vice versa).
- **FAIL**: Crashes, data corruption in project.yaml, push proxy leaks credentials into container, or complete loss of QA loop functionality.

## Ambiguities & Resolutions

1. **Should unit tests be run as part of QA?** — Yes. The PR includes extensive unit tests (`test_spec_gen.py`, `test_push_proxy.py`, updated `test_container.py`, `test_qa_loop.py`). Running `pytest` on these files verifies the core logic before manual/integration testing.

2. **Is the "review" spec mode testable without a real editor?** — The `pm pr spec-approve` command uses `click.edit()` which opens `$EDITOR`. For automated testing, we can set `EDITOR=cat` or similar to verify the flow without interactive editing. Manual verification is more appropriate.

3. **Does push proxy need end-to-end testing with a real GitHub remote?** — For QA purposes, testing against a local git repo (the test project) is sufficient to verify the proxy mechanics. The push proxy's `resolve_real_origin()` chain-following can be tested with local-path origins.

4. **Merge window excluded from containerization** — The diff shows merge launch no longer calls `wrap_claude_cmd`. This is intentional per the comment: "Merge runs on the host — it needs to push to master and modify the main repo, which the branch-scoped push proxy would block." This is correct behavior, not a regression.

5. **Scenario 0 always on host** — The diff removes all container logic for Scenario 0. The comment says "Scenario 0 always runs on the host so the user has full access to host tools, git credentials, and the TUI session." This is a deliberate design choice.
