# pr-1ae1d2d — QA spec: persisted QA evidence must name its PR and run

## 0. What this PR changes, in user terms

The QA orchestrator used to write per-scenario evidence into
`<captures>/<pr>/scenarios/<n>/` with nothing on disk saying *which PR* or
*which QA run* produced it, and nothing saying *which scenarios the run
owned*. A nested fake-Claude QA fixture driven inside an outer scenario
container, or an earlier verification run, could therefore leave records that
looked exactly like real coverage — and the sign-off report, dashboard and
merge gate had no way to tell them apart.

This PR adds:

- `scenario.json` stamped with `pr_id`, `run_id`, `schema`, `captured_at`.
- `qa_manifest.json` (plus a per-run copy at `qa_runs/<run_id>.json`) listing
  the scenarios the current run owns — the authoritative membership.
- `qa_status.json` carrying `run_id`.
- `pm qa evidence <pr>` — the reader that prints membership + anomalies.
- Quarantine of provably-foreign scenario directories into
  `scenarios/_foreign/` (a move, never a delete).
- Sign-off prompt / dashboard / merge gate bound to the manifest's run.

The routing half of the original bug (which PR owns the `/pm-captures` mount)
is #264/pr-1e9c117 and is **not** in scope here. That routing has since landed
on `origin/master` and this branch was merged with it (2026-10-29), so
`captures_dir` now **fails closed**: a nested project whose `PM_CAPTURES_PR`
is unset no longer receives the enclosing PR's mount. The evidence-side
defenses this PR adds must therefore hold for (a) records written before the
routing fix, (b) a running controller that still carries the old fail-open
routing, and (c) a captures tree that is damaged or hand-edited. See R8 for
how to reach the incident's write path on this branch.

## 1. Requirements (Given / When / Then)

### R1 — A completed QA run publishes run-bound evidence
- **GIVEN** a PR that has just been through a QA run to completion,
  **WHEN** the operator looks at that PR's captures directory,
  **THEN** the run's `scenarios/<n>/scenario.json` records name the PR id and
  the run id, `qa_status.json` names the same run id, `qa_manifest.json` lists
  exactly the scenarios that run ran (with their verdicts), and a per-run copy
  exists under `qa_runs/<run_id>.json`.

### R2 — `pm qa evidence` is the authoritative reader
- **GIVEN** a PR with a completed QA run,
  **WHEN** the operator runs `pm qa evidence <pr>`,
  **THEN** it prints the PR, the captures path, the owning QA run, the
  scenario membership with each verdict, and reports no membership anomalies.
- **GIVEN** a PR that has never been QA'd (no captures directory),
  **WHEN** the operator runs `pm qa evidence <pr>`,
  **THEN** the command still succeeds and reports that there is no captures
  dir / no evidence to audit, and it does **not** create a captures directory
  as a side effect.

### R3 — A run that launches nothing owns no evidence
- **GIVEN** a PR with no QA spec (so the run stops before any scenario
  launches),
  **WHEN** a QA run is started for it,
  **THEN** the run still binds itself to the PR but records an **empty**
  scenario membership, and `pm qa evidence` shows that run with
  `(none)` scenarios rather than listing the plan as coverage.

### R4 — Foreign records leave the scenario namespace
- **GIVEN** a PR's captures directory already contains scenario directories
  whose `scenario.json` names a *different* PR (a nested fixture, or a
  leftover from another project),
  **WHEN** a QA run for this PR starts,
  **THEN** those directories are moved to `scenarios/_foreign/<run>-<n>/`
  with their bytes intact, are no longer present under `scenarios/`, and are
  never listed as this PR's coverage.

### R5 — Same-PR history and legacy records are preserved, not moved
- **GIVEN** records from an earlier run of the *same* PR, and records with no
  PR/run identity at all (pre-fix/synthetic),
  **WHEN** the operator reads the evidence (`pm qa evidence`, sign-off prompt),
  **THEN** those directories stay where they are, are excluded from
  authoritative membership, and are reported as anomalies that distinguish
  "prior QA run", "unowned record", and "member with no provenance record".

### R6 — A clobbered current-run pointer is detected, not silently trusted
- **GIVEN** a foreign writer overwrote `qa_manifest.json` with a manifest
  naming another PR and run,
  **WHEN** the operator runs `pm qa evidence <pr>`,
  **THEN** membership is recovered from `qa_runs/<run_id>.json` and an
  anomaly names the foreign owner and says the current-run pointer was
  overwritten.

### R7 — Quarantine never overwrites or deletes
- **GIVEN** `scenarios/_foreign/<run>-<n>` already exists,
  **WHEN** another foreign directory at index `n` is quarantined,
  **THEN** the new record lands under a suffixed name and the existing one is
  untouched; no record is ever deleted.

### R8 — The original incident no longer reproduces
- **GIVEN** an outer QA run for a PR, and a second actor — a nested
  fake-Claude QA fixture / nested pm project — writing its own scenario
  records and manifest into that tree *while the outer run is live*.
  With #264's fail-closed routing on this branch, a nested project whose
  `PM_CAPTURES_PR` is unset can no longer reach the enclosing mount, so drive
  the incident's write path by having the fixture write
  `scenarios/<n>/scenario.json`, `verdict.md` and `qa_manifest.json` into the
  enclosing captures dir directly — the pre-fix controller's effect.
  Do **not** reproduce it by exporting `PM_CAPTURES_PR=<fixture PR id>`
  against a real captures tree: that marker makes `_captures_root_is_ours`
  treat the mount as the fixture's own, so the nested run would quarantine the
  enclosing PR's genuine records — the one thing this PR must never do.
  **WHEN** the outer run completes and the operator inspects the evidence,
  **THEN**:
  - the outer PR's membership is still the outer run's scenarios (recovered
    from `qa_runs/` even if the root pointer was overwritten),
  - the fixture's titles (`Smoke`, `s`, `Alpha check`, …) never appear as the
    PR's coverage in `pm qa evidence` or the sign-off material,
  - the fixture's directories are quarantined out of `scenarios/` (or at
    minimum flagged as foreign), with their bytes preserved,
  - the enclosing PR's genuine records are **not** moved out of `scenarios/`
    by the nested project,
  - the reproduction tests added in this diff pass:
    `pytest tests/test_captures_provenance.py -q`.

### R9 — Sign-off is told which run its evidence belongs to
- **GIVEN** a PR with a run manifest,
  **WHEN** the sign-off session is launched,
  **THEN** the prompt it receives names the QA run, states that scenario
  membership is the manifest's list (not whatever directories exist under
  `scenarios/`), and requires the report to carry
  `<meta name="pm-signoff-qa-run" content="<run>">`.
- **GIVEN** the live `qa_status.json` names a different run than the manifest,
  **WHEN** the sign-off prompt is generated,
  **THEN** it carries a warning naming both runs.
- **GIVEN** legacy evidence with no manifest,
  **WHEN** the prompt is generated,
  **THEN** it says membership is not run-bound and instructs the session to
  **omit** the run tag rather than invent one.

### R10 — The dashboard flags a report bound to a superseded run
- **GIVEN** a PR whose `report.html` names QA run A while the PR's current
  manifest names run B,
  **WHEN** the operator opens the behavior dashboard,
  **THEN** that PR's row shows a `⚠ QA run changed` marker whose tooltip
  names both runs.
- **GIVEN** a report naming the current run, or a legacy report with no run
  tag, or a PR with no manifest,
  **WHEN** the dashboard is opened,
  **THEN** no stale marker is shown.

### R11 — The merge gate refuses a superseded approval
- **GIVEN** a PR with a valid recorded approval whose `report.html` names QA
  run A, while the PR's current manifest names run B,
  **WHEN** the operator runs `pm pr merge <pr>`,
  **THEN** the merge is refused with a message naming both runs and telling
  the operator to re-run sign-off against the current run.
- **GIVEN** a report naming the current run, or a legacy report with no run
  tag,
  **WHEN** the gate is evaluated,
  **THEN** the run-binding check does not refuse it.

### R12 — Readers never mutate evidence
- **GIVEN** any of the reader surfaces (`pm qa evidence`, the merge gate,
  the dashboard, sign-off prompt generation),
  **WHEN** they are invoked against a PR with no captures directory,
  **THEN** no captures directory is created and no manifest is written.

## 2. Setup (user steps)

1. Install the branch's pm into a venv (`./install.sh --local` or
   `pip install -e .`) and make sure `pm which` points at this checkout, not a
   shadowing `/opt/pm-src`.
2. Create a throwaway git project under the workdir (or `/tmp`), `pm init`,
   and add at least two PRs (one "outer" PR under test, one "fixture" PR for a
   nested project).
3. Start a pm tmux session from the test project (`pm session`), and drive
   every pm command from a pane inside it (per `tui-manual-test.md`), so the
   session tag — and therefore the captures directory — resolves
   consistently.
4. Give the PR a QA spec (`pm/specs/<pr>/qa.md`) and a workdir
   (`pm pr start <pr>`) when a full QA run is needed.
5. Configure fake-claude for the session so QA runs reach verdicts without a
   real model, e.g. `qa_planning`, `qa_concretize`, `qa_scenario`,
   `qa_verification`, `qa_finalize` from
   `tests/fixtures/fake_claude/example-config.json`.
6. Keep every fixture record on a **throwaway** PR id. When a scenario needs
   the enclosing container's real `/pm-captures`, use a foreign PR id, save a
   copy of `qa_manifest.json` before writing anything, and restore it after
   capturing evidence.

## 3. Edge cases

- **Two runs racing for the same PR** (a stale controller and a fresh one):
  the last manifest write wins, each writer uses its own temp file so a reader
  never sees a half-written manifest, and the loser's `scenario.json` records
  still name their own run so they audit as `prior-run`, never as current
  membership.
- **Manifest file damaged/unparseable**: reported as damaged (not "absent");
  readers fall back to `qa_runs/` and never raise.
- **`qa_status.json` damaged or non-mapping**: the sign-off prompt still
  carries the run binding instead of crashing.
- **Non-canonical numeric directory names** (`scenarios/03`): not classified
  and never mapped to index 3, so quarantine cannot move the wrong directory.
- **Scenario 0 (interactive)**: stays in `qa_status.json` but is not a
  manifest member, so the prompt's membership-disagreement warning does not
  fire on a normal run.
- **Captures dir unresolvable** (no session tag, no mount): writers log and
  no-op; readers report "no captures dir".
- **Quarantine target already exists**: numeric suffix, nothing overwritten.
- **Foreign record at an index the current run also owns**: quarantined before
  launch, so the run's own `prompt.md`/`verdict.md` land in a clean directory.
- **Nested project on the shared mount with the marker unset**: it must not
  quarantine (that would move the enclosing PR's real evidence); its manifest
  write is tolerated because readers validate `pr_id` and recover from
  `qa_runs/`.

## 4. Pass / fail criteria

Pass = every Then clause above is observable on the named user surface, with
captured evidence (cast/mp4/manifest, CLI transcripts, dashboard screenshots)
under the scenario's captures directory, and the diff's reproduction tests
(`tests/test_captures_provenance.py`) pass.

Fail = any of:
- a synthetic/foreign record appears as the PR's coverage in
  `pm qa evidence`, the sign-off material, the dashboard or the merge gate;
- the enclosing PR's genuine records are moved or deleted by a nested actor;
- the dashboard/merge gate flag or refuse a legitimate (matching-run or
  legacy) report;
- a reader creates a captures directory or writes a manifest;
- a damaged manifest/status file crashes a reader instead of being reported;
- the reproduction test module fails.

## 5. Ambiguities (resolved)

- **A1 — How to produce two distinct QA runs for one PR.** `pm qa run`
  reuses a fixed run id (`cli-<pr>`), so two `pm qa run` invocations are the
  *same* run. The "superseded run" stories therefore use the TUI QA flow (a
  fresh run id per run) or an explicitly written report/manifest pair naming
  different runs. Resolved: scenarios say "a fresh QA run", and note the CLI
  path may reuse the id.
- **A2 — May a QA scenario write fixture records into the real
  `/pm-captures`?** The incident's damage is exactly that. Resolved: yes for
  the incident-reproduction scenario, but only with a foreign `pr_id`, a saved
  copy of the root manifest restored afterwards, and the understanding that
  quarantine (move, not delete) plus `qa_runs/` recovery make it safe.
  Other scenarios use a self-contained throwaway project whose captures land
  under the container's own `~/.pm`.
- **A3 — Which test counts as "the reproduction test"?** There is no single
  test named for the incident; the contract is pinned by
  `tests/test_captures_provenance.py` (root-pointer overwrite, shared-mount
  quarantine guard, foreign-member audit, quarantine move). Resolved: run the
  whole module and cite the specific tests by name.
- **A4 — Sign-off prompt observability.** The prompt is passed inline to the
  launched sign-off session, so a scenario observes it from the launched
  session's command/pane rather than a file. Resolved: the scenario names the
  launched sign-off session's prompt as the surface; the worker picks the
  mechanism.

No **[UNRESOLVED]** items.
