# Impl spec — pr-9b96145

PR actions picker reports "merged or closed" for an OPEN PR when its
window display id desyncs; self-heal by re-linking `gh_pr_number`.

## Background (verified code paths)

- `_pr_display_id(pr)` (`pm_core/cli/helpers.py:256`) returns
  `#<gh_pr_number>` when `gh_pr_number` is set, else the local `pr["id"]`.
- `_current_window_pr_id(window_name)` (`pm_core/cli/session.py:978`)
  parses `#N` or `pr-xxx` out of a window name, stripping any
  `review-/merge-/qa-` prefix and `-sN` suffix.
- The picker command `popup_picker_cmd` (`session.py:1626`):
  - loads `data`, sets `prs`, `current_pr = _current_window_pr_id(...)`.
  - builds `nav_pr_ids` from PRs that have an open window
    (`_pr_has_open_window`, which formats `_ACTION_WINDOW_PATTERNS` with
    the PR's *current* display id) plus `home_pr = current_pr`.
  - `_resolve_for(disp)` → `_build_picker_lines(prs, disp, ...)`
    (`session.py:1057`) finds the PR by `_pr_display_id(p) == disp`;
    returns `[]` when no PR matches (`session.py:1087-1088`) **or** when
    the matched PR's status is terminal (`_actions_for_status` returns
    `[]` for merged/closed, `session.py:1092-1093`).
  - `if not lines:` (`session.py:1730-1733`) unconditionally prints
    "No actions available (PR is merged or closed)." — conflating the two
    causes above.
- Desync mechanism: a PR's `gh_pr_number` is cleared in project.yaml, so
  `_pr_display_id` flips from `#214` back to `pr-ac58803`, but its tmux
  windows are still named `#214` / `review-#214`. The picker resolves
  `current_pr = "#214"`, finds no PR with that display id, gets empty
  `lines`, and wrongly reports "merged or closed".
- `pm pr sync-github` → `pr_sync.sync_from_github` (`pr_sync.py:262`)
  **skips** PRs without `gh_pr_number` (`pr_sync.py:306-308`).
- `pm pr import-github` (`pr.py:2154`) **skips** entries already tracked
  by branch (`pr.py:2199-2201`). So neither command re-links a tracked PR
  that lost its number.
- `gh_ops.list_prs(workdir, state)` (`gh_ops.py:96`) returns dicts with
  `number, title, headRefName, state, url, body, isDraft`.
- `_gh_state_to_status(state, is_draft)` (`helpers.py:660`),
  `_record_status_timestamp` (`helpers.py:438`),
  `_resolve_repo_dir(root, data)` (`helpers.py:645`).

## Requirements (grounded)

### R1 — Shared branch-match backfill helper
New `backfill_gh_numbers_by_branch(root, data, repo_dir, *, save_state=True)`
in `pm_core/cli/helpers.py`. For each tracked PR that has a `branch` but
no `gh_pr_number`, look up an OPEN GitHub PR (`gh_ops.list_prs(repo_dir,
state="open")`) whose `headRefName` equals that branch and backfill
`gh_pr_number`, `gh_pr` (URL), and `status` (from `_gh_state_to_status`).
A local `qa` status is preserved when GitHub reports the PR OPEN+ready
(qa is a local refinement of in_review, mirroring `sync_from_github`).
Returns `list[(pr_id, gh_pr_number)]` of linked PRs. Persists via
`store.locked_update` when `save_state` else mutates `data` in place.

### R2 — Picker self-heal
In `popup_picker_cmd`, after computing `prs`/`current_pr`: if `current_pr`
is a `#N` display id that no tracked PR currently claims, attempt a
relink (new helper `_try_relink_window(root, data, current_pr)` →
github-backend-only; runs R1; returns True if a PR now resolves to `#N`).
On success, reload `data`/`prs` so the rest of the picker proceeds
normally and shows the real actions. Failures are swallowed/logged so the
picker never crashes.

### R3 — Accurate not-found messaging
At `session.py:1730`, distinguish the two empty-`lines` causes using
`_pr_display_id` re-resolution against the (possibly reloaded) `prs`:
- PR matches `current_pr` but has no actions → keep "No actions
  available (PR is merged or closed)."
- No PR matches `current_pr` → "No PR matches display id <X> (window may
  be stale or desynced)."

### R4 — sync-github backfill
`pm pr sync-github` (`pr.py:2117`) runs R1 first (reusing the matcher),
reports any re-linked PRs, reloads data, then runs the existing
`sync_from_github`. This lets `sync-github` backfill a missing
`gh_pr_number` on a tracked PR by branch match.

## Implicit requirements
- Self-heal only attempts on the github backend; vanilla backends skip.
- Self-heal only triggers for `#N`-form display ids (a `pr-xxx` window
  whose PR is gone cannot be healed via a GitHub number lookup).
- One network call (`list_prs`) per heal/sync; no per-PR `gh pr view`
  needed for backfill since `list_prs` already returns `headRefName`.
- The heal must verify `#N` actually resolves after backfill (the GH PR
  whose number is N must have a branch matching a tracked PR); if not,
  fall through to the accurate not-found message (R3).
- Branch match is authoritative for identity — backfilling by exact
  `headRefName` == local `branch` is safe and is the intended link.

## Ambiguities (resolved)
- *Which status to write on backfill?* Use GitHub's current state via
  `_gh_state_to_status`, but preserve a local `qa` status (consistent
  with `sync_from_github`). The PR was OPEN in the repro, so this yields
  `in_review`/`in_progress`, restoring real actions.
- *Scope of picker backfill — only `#N`'s PR or all missing?* Reuse the
  general branch matcher (backfills all missing-number PRs by branch).
  Harmless and beneficial; the heal then verifies `#N` resolves.
- *Extend sync-github vs. import-github?* Extend `sync-github` (acceptance
  text says "`pm pr sync-github` (or an equivalent command)"); it already
  loads data and is the natural home for "refresh from GitHub".

## Edge cases
- No GitHub backend → no heal, accurate not-found message (R3).
- GH PR #N exists but its branch matches no tracked PR → no link, R3 msg.
- Genuinely terminal PR (resolves to `#N`, status merged/closed) → empty
  `lines` via `_actions_for_status`, R3 keeps the merged/closed message.
- `list_prs` returns `[]` (network/gh failure) → no link, R3 msg; picker
  does not crash.
- PR already has `gh_pr_number` → not in `missing`, untouched.

## Tests
`tests/test_popup_picker.py`:
- not-found-with-backfill: window `#214`, local PR lacks number, mocked
  `list_prs` returns #214→branch; after heal the picker resolves and
  shows actions (no merged/closed message).
- not-found-no-match: `#999` with no matching GH PR → accurate "no PR
  matches display id" message, not merged/closed.
- genuinely-terminal: PR resolves to `#101` with status `merged` → still
  reports merged/closed.

`tests/test_pr_sync.py` (or helpers test):
- `backfill_gh_numbers_by_branch` links a tracked PR missing its number
  by branch match (number/url/status backfilled); preserves qa; no-op
  when nothing missing or no branch match.
- `pm pr sync-github` backfills a missing number by branch.
