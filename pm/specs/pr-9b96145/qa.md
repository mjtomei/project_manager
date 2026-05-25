# QA spec — pr-9b96145

PR actions picker reports "merged or closed" for an OPEN PR when its
window display id desyncs; self-heal by re-linking `gh_pr_number`.

## Summary of behavior under test

The fix touches two user-facing surfaces, both on the **GitHub backend**:

1. **The TUI PR-actions picker** (opened with `prefix+P` from inside a
   PR window). When the invoking window is named `#N` but no tracked PR
   currently claims display id `#N` (its `gh_pr_number` was cleared, so
   its display id flipped back to `pr-xxx` while the window kept the
   `#N` name), the picker now:
   - attempts to **self-heal** by matching the window's GitHub PR back to
     a tracked PR *by branch* and backfilling `gh_pr_number` / `gh_pr`
     URL / `status`, then re-resolving and showing the PR's real actions;
   - if it still can't resolve, prints an **accurate** message ("No PR
     matches display id `<X>` (window may be stale or desynced).")
     instead of the misleading "No actions available (PR is merged or
     closed)." — the merged/closed message now appears *only* when a PR
     actually resolves but is in a terminal status.

2. **The `pm pr sync-github` CLI command**, which now first re-links any
   tracked PR that lost its `gh_pr_number` by branch-matching it to an
   open GitHub PR (reporting "Re-linked N PR(s): …"), then runs the
   normal status sync.

Both paths funnel through a new shared helper,
`backfill_gh_numbers_by_branch`, which reads `gh pr list` once and writes
project.yaml via `store.locked_update`.

## Test harness notes (how to drive without real GitHub)

- The behavior only triggers on a **github**-backend project, and the
  backfill reads GitHub via `gh pr list`. As of the merge of pr-9603d04
  (#208) into master/this branch, the repo now ships an **in-process
  fake-github facility**: `gh_ops.run_gh` consults
  `paths.fake_github_active()` and dispatches to a per-session fake
  *before* `_check_gh()`, so a freshly-spawned `pm` subprocess (picker or
  CLI) is served scripted `gh pr list` / `gh pr view` results with no real
  `gh` binary, auth, or network. Seed it from the user surface with
  `pm fake-github config set '{"git_backed":true,"prs":[{"head":"<branch>",
  "title":"…","state":"OPEN"}]}'` (per-session; `pm fake-github config
  show` reveals the auto-assigned PR numbers, which start at 1 in seed
  order — do NOT hardcode them). This facility replaces the previously
  documented hand-rolled `gh` shim and is the preferred driver for all
  scenarios.
- (Legacy fallback, only if the fake-github facility is unavailable in a
  given clone) stand in a **fake `gh` binary** first on `PATH` that
  answers `gh auth status` (exit 0) and `gh pr list --json …` (canned
  JSON: `number, headRefName, state, url, isDraft, title, body`), plus
  `gh pr view <n> --json state,isDraft,mergedAt` for the sync path.
  `fzf` is also absent, so the picker uses its numbered-list fallback.
- A throwaway project is set up per `tui-manual-test.md`. The project's
  `backend` must be `github`; setting that (and clearing/seeding a PR's
  `gh_pr_number` for the desync fixture) in `project.yaml` is acceptable
  *bootstrap* editing. After setup, drive everything through the TUI /
  CLI.
- The desync fixture: a tracked OPEN PR (e.g. `pr-ac58803`, branch
  `pm/feature-x`) with **no** `gh_pr_number`; a tmux window named `#214`
  (or `review-#214`); and a fake `gh pr list` that returns PR #214 with
  `headRefName: pm/feature-x`, `state: OPEN`.

## Requirements (Given / When / Then)

### R1 — Picker self-heals a desynced `#N` window and shows real actions
- **Given** a github-backend project with an OPEN PR whose
  `gh_pr_number` is currently unset, and a tmux window named `#N` for it,
  and GitHub reporting an open PR #N whose head branch matches that PR's
  branch,
- **When** the user opens the PR-actions picker from that `#N` window,
- **Then** the picker shows the PR's real actions (e.g. start / review),
  does **not** say "merged or closed", and project.yaml now has the PR's
  `gh_pr_number`, `gh_pr` URL, and a non-terminal status backfilled.

### R2 — Re-opening the healed picker is stable (idempotent)
- **Given** the same project right after a successful self-heal (the PR
  now has its `gh_pr_number` restored and the window is still `#N`),
- **When** the user opens the picker again from that window,
- **Then** the picker shows the same real actions with no error and no
  second re-link is needed (the window now resolves directly).

### R3 — Accurate "stale/desynced" message when nothing can be re-linked
- **Given** a github-backend project where the invoking window is `#N`
  but no tracked PR claims `#N` and GitHub returns no open PR that maps
  back to a tracked PR by branch,
- **When** the user opens the picker from that window,
- **Then** the picker reports that no PR matches display id `#N` and that
  the window may be stale/desynced — it does **not** claim the PR is
  merged or closed.

### R4 — Genuinely terminal PR still reports "merged or closed"
- **Given** a project with a PR that resolves to its window's display id
  `#N` and whose status is genuinely terminal (merged or closed),
- **When** the user opens the picker from that window,
- **Then** the picker reports "No actions available (PR is merged or
  closed)." and does **not** show the stale/desynced message.

### R5 — `pm pr sync-github` backfills a missing number by branch
- **Given** a github-backend project with a tracked PR that has a branch
  but no `gh_pr_number`, and an open GitHub PR whose head branch matches
  it,
- **When** the user runs `pm pr sync-github`,
- **Then** the command reports it re-linked the PR ("Re-linked 1 PR(s):
  `<pr-id>` (#N)"), exits 0, project.yaml has `gh_pr_number` / URL /
  status backfilled, and the normal status sync still runs.

### R6 — `pm pr sync-github` is a no-op (for backfill) when nothing matches
- **Given** a github-backend project with a tracked PR missing its
  number but no open GitHub PR matching its branch,
- **When** the user runs `pm pr sync-github`,
- **Then** the command does not report any re-link, leaves the PR's
  number unset, exits cleanly, and still performs the regular sync.

## Setup (cross-cutting)

1. Install pm from the clone (per `tui-manual-test.md`); confirm
   `pm which` points at the clone, not `/opt/pm-src`.
2. Create a throwaway git repo as the test project.
3. Put a fake `gh` on `PATH` that satisfies `gh auth status` and serves
   canned `gh pr list --json …` output for the scenario's fixture.
4. `pm init` the project, then set `backend: github` in project.yaml and
   seed PR fixtures (branch set; `gh_pr_number` cleared/seeded as the
   scenario requires). Bootstrap-only editing; everything afterward goes
   through TUI/CLI.
5. For picker scenarios, start a `pm session` and create the tmux window
   named to match the fixture (`#N` / `review-#N`).

## Edge cases & failure modes

- **Non-github backend with a stale `#N` window** → no heal attempted;
  picker shows the accurate not-found message; no crash. (R3 variant.)
- **`gh pr list` fails / returns empty** (network/gh error) → no re-link;
  picker falls through to the accurate not-found message and does not
  crash; `sync-github` reports no re-link and continues.
- **PR already has a `gh_pr_number`** → not a backfill candidate; even a
  same-branch GitHub PR with a *different* number must not overwrite the
  existing number.
- **Local `qa` status preserved** → a PR in local `qa` status that gets
  re-linked while GitHub reports it merely OPEN/ready keeps `qa` (a local
  refinement of `in_review`), not downgraded to `in_review`.
- **GitHub PR #N exists but its branch matches no tracked PR** → no link;
  accurate not-found message (R3).
- **Self-heal only fires for `#N`-form ids** → a vanished `pr-xxx` window
  (PR removed) is not "healed" via a GitHub number lookup; accurate
  not-found message.

## Concurrency / shared resources

Shared resources the diff touches:
- **`project.yaml`** — written by the picker self-heal *and* by
  `pm pr sync-github`, both via `store.locked_update`; also writable by
  any other concurrent pm command.
- **`gh pr list`** (read) — invoked once per heal/sync.

Concurrent-use scenario: two writers backfill project.yaml at the same
time — e.g. open the picker from a desynced `#N` window while
`pm pr sync-github` runs (or two desynced picker windows opened
simultaneously). Both must complete without corrupting project.yaml or
losing updates; all branch-matchable PRs end up correctly linked; YAML
remains valid and parseable; neither actor crashes.

## Pass/Fail criteria

- **Pass**: each requirement's Then is observed on the user's surface
  (picker render / command output / resulting project.yaml). Specifically
  the original bug no longer reproduces (R1: a desynced `#N` window for an
  OPEN PR yields real actions, not "merged or closed"), the two
  not-found vs. terminal messages are distinct and correct (R3/R4), the
  CLI backfill works and is reported (R5), and concurrent writers leave
  project.yaml valid and fully linked.
- **Fail**: picker shows "merged or closed" for an OPEN/desynced PR;
  no re-link occurs when a branch match exists; an existing
  `gh_pr_number` gets overwritten; `qa` status is downgraded on relink;
  any path crashes the picker or the CLI; concurrent writes corrupt or
  truncate project.yaml or drop a valid re-link.

## Ambiguities (resolved)

- **Driving the GitHub backend in QA** — resolved by the in-process
  fake-github facility (`pm fake-github config set`, merged from
  pr-9603d04), which serves scripted `gh pr list` / `gh pr view` from the
  user surface with no real `gh`/auth/network. This supersedes the earlier
  hand-rolled `gh` shim and unblocks the `pm pr sync-github` CLI scenario
  (formerly INPUT_REQUIRED/deferred). See the updated Test harness notes.
- **Invoking the picker** — the picker is reached via `prefix+P` in the
  TUI (the user surface). The hidden `_popup-picker` command is the
  underlying entry point; QA drives the user-facing keybinding where
  practical and treats the printed picker body as the observable surface.
- **Which actions count as "real actions"** — for an OPEN/in_review PR
  the picker offers actions such as start and review; the scenario
  asserts the presence of real action lines and the *absence* of the
  merged/closed text rather than an exact action set.
