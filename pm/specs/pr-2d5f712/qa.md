# QA Spec — pr-2d5f712: Sign-off step (dedicated window + lifecycle status + verdict router)

This QA spec is written from the user's surface. It complements the
implementation spec at `impl.md`; here every requirement is a Given/When/Then
user story grounded in an observable surface (a CLI output line, a project.yaml
state change, a tmux pane render, a tech-tree node, a `pm pr list` row).

## What this PR delivers (user-visible summary)

Sign-off becomes a first-class lifecycle step between `qa` and `merged`:

- A new PR status **`sign_off`** with its own icon everywhere a status is shown
  (`pm pr list`, `pm status`, the static graph, the TUI tech tree).
- A command **`pm pr signoff [PR_ID]`** that moves a QA-passed PR into
  `sign_off` and opens a dedicated tmux window (an evidence pane + a Claude
  "router" pane).
- The Claude pane is a **router only** — it reviews every scenario/step and the
  cross-stage evidence, then emits one routing verdict
  (`SIGNOFF_MERGE/REQA/REVIEW/IMPL/BLOCKED`) and self-records it
  (`pm pr signoff-record`). It never edits code and never merges.
- The verdict is recorded durably on the PR as `pr["signoff"] = {verdict, sha,
  ts, origin}`.
- **Only the auto-sequence driver acts on a verdict** (the status transition /
  relaunch of the next step). A hand-triggered `pm pr signoff` records/recommends
  but never changes state.
- Auto-sequence **always gates at merge**: `SIGNOFF_MERGE` is a `ready_to_merge`
  recommendation; the PR stays in `sign_off` (the actual merge is decided
  elsewhere). Bounce verdicts move the PR back to `qa` / `in_review` /
  `in_progress`.

## Shared resources touched by the diff (concurrency inventory)

- **`project.yaml`** — `pr["status"]`, the `pr["signoff"]` verdict record, and
  status timestamps. Written by `pm pr edit`, `pm pr signoff`,
  `pm pr signoff-record`, the auto-sequence `apply_signoff_hop`, and `pr_sync`.
  All writers funnel through `store.locked_update`.
- **The `signoff-<id>` tmux window** — created by `pm pr signoff` (manual and
  background/auto), deduped by window name + pane-registry role
  (`signoff-evidence` / `signoff-claude`); torn down by `_retire_signoff_window`
  on a bounce or stale record.
- **The `signoff-<id>.jsonl` transcript** — one reused path under the
  auto-sequence dir; written by the Claude pane, read by
  `_check_signoff_verdict`, unlinked on retire.
- **The per-PR captures dir** (`pm qa captures-path <id>`) and the latest
  `qa_status.json` — read by both the evidence pane and the router prompt.

## 1. Requirements (Given / When / Then)

### R1 — `sign_off` is a recognized lifecycle status
- **Given** a PR in `qa`, **When** the user runs `pm pr edit <id> --status
  sign_off`, **Then** the command accepts it and a subsequent `pm pr list`
  shows the PR in `sign_off` (it is NOT silently reset to `pending` on the next
  load — `sign_off` is in the valid-states set).
- **Given** a PR in `sign_off`, **When** the user runs `pm status`, `pm pr
  list`, and views the TUI tech tree / static graph, **Then** each surface shows
  a distinct `sign_off` icon (CLI `✔️`, tech-tree `◆`/blue), not a `?`/generic
  marker.

### R2 — `pm pr signoff` transitions and opens the window
- **Given** a PR in `qa`, **When** the user runs `pm pr signoff <id>` inside the
  tmux session, **Then** the PR's status becomes `sign_off`, a `signed_off_at`
  timestamp is recorded, and a new `signoff-<id>` tmux window opens with two
  panes — a left **evidence** pane and a right **Claude router** pane.
- **Given** no PR id is supplied and exactly one PR is in `qa`/`sign_off`,
  **When** the user runs `pm pr signoff`, **Then** it auto-selects that PR and
  prints which one it picked.
- **Given** a PR already in `sign_off` with an open window, **When** the user
  runs `pm pr signoff <id>` again without `--fresh`, **Then** it switches focus
  to the existing window instead of creating a duplicate; **with `--fresh`** the
  old window is killed and a new one created.

### R3 — The evidence pane aggregates cross-stage evidence
- **Given** a `sign_off` PR whose captures dir holds `impl/` and `scenarios/<n>/`
  entries and a `qa_status.json`, **When** the sign-off window opens, **Then**
  the left evidence pane shows a captures listing (both `impl/` and
  `scenarios/`), the latest QA status, and the diff vs the base branch.
- **Given** a `sign_off` PR with no captures and no QA status, **When** the
  window opens, **Then** the evidence pane degrades gracefully (e.g. "(no
  captures found)" / "(no qa status)") rather than erroring.

### R4 — `pm pr signoff-record` durably records a verdict without acting
- **Given** a PR in `sign_off`, **When** the router pane runs `pm pr
  signoff-record <id> SIGNOFF_IMPL --origin manual`, **Then** the verdict is
  stored as `pr["signoff"] = {verdict, sha, ts, origin}` (sha = the workdir
  HEAD) and the PR's **status is unchanged** (still `sign_off`).
- **Given** any PR, **When** `pm pr signoff-record <id> NOT_A_VERDICT` is run,
  **Then** it errors and writes nothing.

### R5 — auto-sequence advances `qa` PASS into `sign_off`
- **Given** a PR in `qa` whose latest `qa_status.json` reports `overall: PASS`,
  **When** the user runs `pm pr auto-sequence <id>`, **Then** the PR transitions
  `qa → sign_off`, a sign-off window is launched in the background (focus not
  stolen), and the command prints `advanced: sign_off`.

### R6 — auto-sequence routes on the sign-off verdict (and only it acts)
- **Given** a `sign_off` PR whose router emitted `SIGNOFF_MERGE`, **When**
  `pm pr auto-sequence <id>` runs, **Then** it prints `ready_to_merge`, the PR
  **stays in `sign_off`** (it is NOT merged), and the verdict is recorded.
- **Given** a `sign_off` PR whose router emitted a bounce verdict, **When**
  `pm pr auto-sequence <id>` runs, **Then** the PR transitions to the mapped
  status and the next step is relaunched:
  - `SIGNOFF_REQA` → `qa` (prints `sign_off: re-qa`),
  - `SIGNOFF_REVIEW` → `in_review` (prints `sign_off: returning to review …`),
  - `SIGNOFF_IMPL` → `in_progress` (prints `sign_off: returning to impl`).
- **Given** a `sign_off` PR whose router emitted `SIGNOFF_BLOCKED`, **When**
  `pm pr auto-sequence <id>` runs, **Then** it prints `paused: sign_off_blocked`
  and the PR stays in `sign_off`.
- **Given** a `sign_off` PR whose router has **not** emitted a verdict yet (window
  open, transcript empty), **When** `pm pr auto-sequence <id>` runs, **Then** it
  prints `running: sign_off` (and does NOT transition).

### R7 — Verdict adoption (no wasted re-run) + manual-never-acts invariant
- **Given** a PR taken into `sign_off` by a manual `pm pr signoff` whose router
  recorded a verdict against the current HEAD, **When** an auto-sequence tick
  later runs on that PR, **Then** it **adopts** the fresh recorded verdict (sha
  == HEAD) and acts on it without relaunching a new router run. Conversely, the
  manual run itself never changed the PR's status — only the auto-sequence tick
  did.

### R8 — Stale record / bounce do not replay an old verdict
- **Given** a `sign_off` PR with a recorded verdict whose sha no longer matches
  HEAD (a commit landed since), **When** `pm pr auto-sequence <id>` runs,
  **Then** it does NOT act on the stale verdict — it retires the old window +
  transcript, clears the record, relaunches a fresh router, and prints
  `advanced: sign_off_relaunched`.
- **Given** a bounce (e.g. `SIGNOFF_REQA`) moved a PR from `sign_off` back to
  `qa`, **When** the PR later re-enters `sign_off` (after re-qa passes) and
  auto-sequence ticks, **Then** a genuine fresh router runs (the old
  window/transcript were retired) — the PR does NOT immediately re-bounce on the
  consumed verdict in a loop.

### R9 — Sign-off display surfaces (TUI + list)
- **Given** a `sign_off` PR with a workdir and no recorded verdict, **When** the
  TUI tech tree renders, **Then** the node animates the running spinner (same
  spinner used by review/qa) and the node is treated as active (sorted with the
  working PRs, animation timer kept alive).
- **Given** a `sign_off` PR with a recorded verdict, **When** the tech tree and
  `pm pr list` render, **Then** both show the verdict's distinct icon
  (`▲/↻/↩/⇤/⊘`) — in the list it appears inside the status bracket
  (e.g. `[sign_off ⇤]`) — consistently between the two surfaces.

### R10 — GitHub sync preserves `sign_off`
- **Given** a GitHub-backend project with a PR locally in `sign_off` whose
  GitHub PR is still OPEN, **When** a sync runs, **Then** the local `sign_off`
  status is preserved (treated as a local refinement of `in_review`, like `qa`);
  a `sign_off` PR whose branch was merged on GitHub is still detected as merged.

## 2. Setup (cross-cutting)

- Install the editable clone and confirm `pm which` points at it (not
  `/opt/pm-src`). Use `--backend local` projects for everything except R10.
- Drive Claude-spawning flows with **fake-claude** (`pm fake-claude config
  set`). The `signoff` session type accepts the five sign-off verdicts and
  defaults to `SIGNOFF_MERGE`. A scripted sequence
  (`{"signoff": {"verdicts": ["SIGNOFF_REQA"]}}`) makes the router emit the
  verdict you want; pair with `review`/`qa_*` verdicts to drive the whole
  pipeline through auto-sequence.
- To reach `sign_off` the user-faithful way: drive `pm pr auto-sequence <id>`
  repeatedly with a fake config that PASSes review and QA, so the PR naturally
  flows start → review → qa → sign_off. For tests that only need a PR sitting in
  `qa` with a PASS, the QA loop can be run to a `PASS` finalize (its
  `qa_status.json` is what auto-sequence and the evidence pane read).
- The router self-records via `pm pr signoff-record` — fake-claude only emits
  the verdict *line* in the transcript, so for the manual-record path a scenario
  drives `pm pr signoff-record` directly (this is exactly the command the router
  pane runs). Under auto-sequence the driver records the transcript verdict
  itself, so no manual record is needed there.
- Run pm commands inside a pane of the test tmux session, not your own session.

## 3. Edge Cases (Given / When / Then)

- **Wrong-status entry**: **Given** a PR in `pending`/`in_progress`/`in_review`,
  **When** `pm pr signoff <id>` runs, **Then** it errors ("sign-off runs after
  QA") and does not transition.
- **Merged entry rejected**: **Given** a `merged` PR, **When** `pm pr signoff
  <id>` runs, **Then** it errors ("already merged") — sign-off is not re-runnable
  on merged PRs in this PR.
- **No QA artifacts**: **Given** a PR manually edited to `sign_off` with no QA
  run, **When** the window opens, **Then** the evidence pane and prompt degrade
  ("no captures"/"no QA status") and the router can still produce a verdict.
- **Concurrent transition guard**: **Given** a `sign_off` PR being routed by
  auto-sequence, **When** a concurrent actor moves the PR out of `sign_off`
  (e.g. a sync marks it merged) between the verdict read and the write, **Then**
  the bounce transition is skipped (guarded on `status == "sign_off"`) and the
  external state is not clobbered.
- **No verdict + window gone**: **Given** a `sign_off` PR with no verdict and no
  live window, **When** auto-sequence ticks, **Then** it relaunches the window
  and prints `advanced: sign_off_relaunched`.

## 4. Pass/Fail Criteria

PASS when, across the surfaces above:
- `sign_off` is accepted, persisted, and rendered with its own icon everywhere a
  status appears.
- `pm pr signoff` transitions `qa → sign_off`, opens the two-pane window, dedups
  on re-run, and rejects wrong/merged statuses.
- `pm pr signoff-record` stores the verdict record and never changes status;
  invalid verdicts are rejected.
- auto-sequence advances `qa` PASS → `sign_off`; on a verdict it routes exactly
  as R6 (MERGE = recommendation, PR stays; bounces transition + relaunch; BLOCKED
  pauses; no verdict = running), adopts a fresh recorded verdict, and relaunches
  on a stale record without acting on it.
- A bounce never produces an infinite re-bounce loop (window/transcript retired).
- The TUI animates a running sign-off and shows the verdict icon once recorded;
  `pm pr list` matches.

FAIL on: a `sign_off` PR being reset to `pending`; a manual `pm pr signoff`
changing status to anything past `sign_off` or merging; auto-sequence merging a
PR (it must only recommend); a stale/consumed verdict being acted on (wrong-code
recommendation or infinite bounce); the window not deduping; the evidence pane
or prompt crashing on missing captures; a missing/`?` icon on any status surface.

## 5. Ambiguities (resolved)

- **Driving the router with fake-claude vs a real agent**: fake-claude emits only
  the verdict line, not the `pm pr signoff-record` call. Resolved: rely on the
  auto-sequence driver recording the transcript verdict (the production path for
  the auto flow), and drive `pm pr signoff-record` directly to exercise the
  manual-record + adoption path (that command is the exact surface the router
  uses). This stays faithful to real behavior.
- **Reaching a real `qa` PASS**: rather than hand-fabricating `qa_status.json`,
  prefer driving the actual pipeline via `pm pr auto-sequence` with a PASS fake
  config so `qa_status.json` is produced by the real QA loop. Hand-editing
  `project.yaml`/status is bootstrap-only (per the TUI testing instruction).
- **Merge actually happening**: by design sign-off never merges and auto-sequence
  stops at `ready_to_merge`; the actual merge belongs to a deferred PR
  (pr-ff9b728). QA verifies the PR *stays* in `sign_off` on a MERGE recommendation,
  not that it merges.

No **[UNRESOLVED]** ambiguities.
