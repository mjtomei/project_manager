# pr-2680fbf — QA uses standard regression scenarios (implementation spec)

Status: draft for owner review (review_spec=true). No product code changes
before approval. Complete new/changed prompt texts are in
[`prompts.md`](prompts.md) in this directory; they are part of what is being
approved.

## 0. Summary and dependency boundary

Today a QA scenario is `INSTRUCTION` (setup) + `ARTIFACT` (drive/capture)
picked per run (`pm_core/qa_loop.py:parse_qa_plan`, `prompt_gen.generate_qa_planner_prompt`),
and `pm/qa/regression/*.md` is a separate free-form prompt library that the
planner is never shown (`instruction_summary_for_prompt(root)` is called
without `include_regression`). This PR makes a **standard regression** — a
durable flow definition that references existing setup/capture recipes — the
normal driver of a QA scenario:

1. The planner binds each scenario to `REGRESSION: <id>` (reuse), or
   `NEW_REGRESSION: <id>` + `GAP:` (author), or — narrowly — `PROBE:`.
2. A new **regression author** session (one per QA run, host, PR workdir)
   writes/extends definitions and commits them on the PR branch; the
   orchestrator validates the commit deterministically.
3. The existing planner handoff publishes the branch; bindings are resolved
   from the published head (`state.planner_head`), files are installed into
   each scenario's scratch dir, and the scenario runs through the unchanged
   container/tmux concretizer → worker → verifier → finalize path with the
   regression's flow plus the scenario's PR-specific Thens.
4. Evidence stays in the external captures store; the orchestrator writes
   the binding identity (definition/recipe blob revisions, target revision,
   run id, container, artifact list) next to the scenario and an index entry
   under `captures/regression/<id>/runs/`.

**pr-7d5d036 (IN_PROGRESS, no code yet at 1f407574)** owns removing the
legacy corpus from active discovery, the empty-library case in CLI/TUI/docs,
and stripping live-PM targeting from the standalone regression launch
(`regression_prompts.build_regression_test_prompt`, `pm qa regression`,
`pm qa launch regression:`, `tui/pane_ops.launch_qa_item`). This PR:

- implements the QA-loop binding/authoring/evidence work on current master
  without touching those launch surfaces;
- after pr-7d5d036 merges, integrates it and then makes the standalone launch
  path it leaves consume the shared resolver/driver block (R9) and
  reconciles `pm_core/docs/qa_library.md` (R10);
- keeps review/QA held until that integration (PR note 2026-11-01).

If pr-7d5d036's launch path cannot accept R9 without building a second
runner, stop and ask rather than add one.

## 1. Requirements (grounded)

### R1 — Shared regression template and reference contract
- New packaged file `pm_core/docs/regression_template.md`: the single source
  of the template (prompts.md §T). Used by the authoring prompt (inlined
  whole), `pm qa add-regression` (stub), interactive `pm qa author-regression`
  (`qa_authoring._CATEGORY_BLURB["regression"]` + doc), and the docs.
- Frontmatter: `title`, `description`, `surface` (non-empty strings);
  `setup` (≥1 id in `pm/qa/instructions/`); `capture` (≥1 id in
  `pm/qa/artifacts/`); optional `mocks` (ids in `pm/qa/mocks/`); optional
  `tags`; unknown keys allowed. Refs are `<id>` or `<dir>/<id>.md` and must
  match a file **exactly** (no difflib fuzz — durable bindings must not
  silently rebind after a rename).
- Body: `## Given`, `## When`, `## Then` in order, each non-empty; `## Then`
  has ≥1 bullet. Later sections (e.g. `## Notes`) allowed.
- Id = filename stem, `^[a-z0-9][a-z0-9-]{0,63}$`.
- New module `pm_core/qa_regression.py`:
  - `QATree` readers: `GitTree(repo, rev, prefix="pm/qa")` (reads blobs via
    `git show`/`ls-tree`, exposes blob shas) and `FsTree(qa_dir)`.
  - `parse_regression(tree, id) -> RegressionDef` with `.problems: list[str]`
    (empty = bindable). `list_regressions(tree)`.
  - `qa_tree_for_pr(pr_workdir, rev, pm_root)`: `GitTree` when the PR
    repo tracks `pm/qa` (internal pm dir, `store.is_internal_pm_dir`), else
    `FsTree(pm_root/qa)` with `authoring_supported=False`.
  - `regression_summary_for_prompt(tree)` (prompts.md §P), including the
    empty-library and not-bindable sections.
  - `install_bound_files(tree, reg, scratch_path, scratch_dir)` → copies the
    definition and its recipes to `<scratch>/qa-regression/{regression,instructions,artifacts,mocks}/`
    from the tree (not from the base `pm_root`), returns agent-visible paths.
  - Run-record writer (R7).
- Whatever "active library" rule pr-7d5d036 introduces (deletion, move, or a
  frontmatter flag) is applied in `list_regressions` so retired entries are
  never offered or bound.

### R2 — Plan format and parsing (`qa_loop.parse_qa_plan`)
- New per-scenario fields: `REGRESSION:`, `NEW_REGRESSION:`, `GAP:`,
  `PROBE:`. Values beginning with `<` (template placeholders) or
  `none`/`n/a`/`-` are ignored. Add all four to the `STEPS` lookahead so a
  field after STEPS is not swallowed.
- `QAScenario` gains: `binding` (`"regression"|"new_regression"|"probe"|"unbound"`),
  `regression_id`, `new_regression_id`, `regression_gap`, `probe_reason`,
  `regression_origin` (`reused|created|extended|reused_by_author`),
  `regression_rev`, `regression_recipes` (list of `{path, rev}`),
  `regression_def_path`, `regression_def_text`, `run_id`. All round-trip
  through `_scenario_to_resume_dict` / `_scenario_from_resume_dict`.
- Precedence when a planner emits more than one: REGRESSION > NEW_REGRESSION
  > PROBE (logged). Bound scenarios ignore `INSTRUCTION`/`ARTIFACT`
  (logged); probes keep today's INSTRUCTION/ARTIFACT handling.
- `INSTRUCTION:` resolution is restricted to `instructions/` (today
  `resolve_instruction_ref` also matches `regression/`); a regression id
  there is ignored with a warning.
- No binding field at all → `binding="unbound"`, run like a probe, and
  recorded as such (status, scenario.json, QA note). Not a plan problem
  (`qa_plan_problem` is for truncation; rejecting would stall the planner).

### R3 — Planner prompt (`prompt_gen.generate_qa_planner_prompt`)
Full text: prompts.md §1. The regression listing is built from the PR
workdir's **committed** branch head (`qa_tree_for_pr`), not the base
`store.find_project_root()` library, because that is what scenario clones
run. Instruction/artifact recipes stay listed as building blocks. Preference
order REGRESSION → NEW_REGRESSION → PROBE; planner must not write regression
files; sign-off/PR-note coverage findings are addressed via binding; bug-fix
PRs bind their reproduction scenario. Template/output-format examples use
placeholders only.

### R4 — Regression authoring phase (new)
- New session type `qa_regression_author`: `model_config.SESSION_TYPES`,
  `_FALLBACK_TYPES[...] = "qa"`, `fake_claude.SESSION_TYPE_VERDICTS`
  (`("REGRESSION_AUTHOR",)` with `BLOCK_VERDICTS["REGRESSION_AUTHOR"]`),
  `qa_loop._QA_SESSION_TYPES` (so `check_qa_providers` covers it), any
  model-screen/role labels.
- New module `pm_core/regression_author.py`: `build_regression_author_prompt`
  (prompts.md §2), `build_author_fixup_message` (§2b),
  `parse_author_block(text) -> dict[request_id, AuthorResult]`,
  `validate_author_results(...)`.
- Orchestration `qa_loop._run_regression_authoring(state, ...)`, between the
  spec gate and Phase 1.25 handoff, only when the plan has NEW_REGRESSION
  requests:
  1. Group requests by id (one request per distinct `NEW_REGRESSION` id,
     carrying every scenario bound to it). If `authoring_supported` is false
     (standalone pm dir), block those scenarios without launching an author.
  2. Record `pre_author_head`; open one author pane split from the planner
     pane in the `qa-<pr>` window, cwd = PR workdir (host, same trust and
     placement as the planner), register with `pane_layout` as `qa-author`.
  3. Poll with the hook/transcript `poll_for_verdict` for
     `REGRESSION_AUTHOR_END`, honoring `state.stop_requested`, the terminal
     PR-status guard used by the planner loop, a workspace-trust watch, and a
     deadline (`_AUTHOR_TIMEOUT = 45 min`).
  4. Validate (deterministic, against `GitTree(workdir, post_author_head)`):
     - every changed path in `pre_author_head..post_author_head` is under
       `pm/qa/regression|instructions|artifacts/` — otherwise all
       results from this author are rejected (the existing
       `_planner_code_changes` additionally forces NEEDS_WORK for non-`pm/`
       paths);
     - `created`: id valid, absent at pre, present at post; `extended`:
       present at both and changed, every prior `## Then` bullet and every
       prior `setup`/`capture` ref still present (whitespace-normalized) —
       an extension cannot weaken assertions; `reused`/`reused_by_author`:
       present, valid, unchanged in range;
     - the definition validates (R1) at post head;
     - no uncommitted/untracked changes under the reported paths
       (`git status --porcelain -- <paths>`) — committed only;
     - every request has exactly one result; `blocked` needs a reason.
  5. On problems, send `build_author_fixup_message` to the same pane via
     `_send_submitted` and re-poll for a newer block (≤ `_AUTHOR_MAX_FIXUPS
     = 2`). Remaining problems → the affected scenarios are blocked.
  6. Bind: request results set `binding="regression"`, `regression_id`,
     `regression_origin`; blocked/invalid → scenario verdict
     `INPUT_REQUIRED`, reason `regression authoring failed: <reason>`, never
     launched.
  7. `state.authored_regressions` (persisted in the resume snapshot):
     `[{request, id, result, commit, paths, scenarios}]`; `state.recipes_changed`.
- The author **commits, does not push**; `_publish_planner_head` then
  publishes, so `state.planner_head` includes the authored commit and every
  scenario clone starts from it. pm never commits on the author's behalf.

### R5 — Binding resolution and launch
- After handoff, `_resolve_bindings(state, workdir_path, pm_root)` resolves
  every `binding="regression"` scenario against
  `qa_tree_for_pr(workdir, state.planner_head)`: unknown id → blocked
  `regression <id> not found on the PR branch at <sha>`; invalid → blocked
  `regression <id> does not meet the template: <problems>`. Valid → sets
  `regression_rev` (blob sha), `regression_recipes` (path + blob sha),
  `regression_def_text`, `artifact_paths` := capture recipe paths (so the
  existing verifier artifact check applies), `regression_origin` defaults
  to `reused`.
- Blocked scenarios keep `INPUT_REQUIRED` + reason and are excluded from the
  launch batch and the queue (the poll loop already treats a windowless
  scenario with a verdict as final and `setdefault`s its reason).
- `_launch_scenarios_in_containers` / `_launch_scenarios_in_tmux` /
  queued + relaunch paths: for bound scenarios call `install_bound_files`
  (instead of `_install_instruction_file`/`_install_artifact_files`), pass
  `regression_def_text` to the concretizer (prompts.md §4), assign
  `scenario.run_id = f"{loop_id}-s{index}-{UTC yyyymmddThhmmssZ}"` once at
  first launch (kept on retry/relaunch/resume).
- Worker prompt `generate_qa_child_prompt` gains the Regression Driver and
  bound capture sections (prompts.md §3). Probe/unbound scenarios keep
  today's prompt unchanged.
- Container mode is unchanged: the runtime check before planning still
  fails the run with ERROR before any author/agent launches, and container
  create/exec failures still raise `ContainerLaunchError` (no host fallback).

### R6 — Fit check and assertion preservation
- Planner checks fit using the listing (surface, setup, capture) and the
  file. Concretizer (prompts.md §4) receives the definition whole, rejects a
  non-fitting binding with `regression <id> does not fit: <why>` (existing
  `REFINER_REJECT` → `INPUT_REQUIRED` path), refines only the PR overlay,
  must keep every planned PR Then, and does not restate the regression's
  own Thens or setup.
- Worker checks regression Thens and PR Thens separately (one result line
  each). Verifier (prompts.md §5) receives the definition whole and FLAGs a
  PASS whose regression flow, Thens, targeting, or capture identity is
  missing or substituted.

### R7 — Evidence and records (captures stay outside Git)
- Worker manifests add `regression`, `regression_rev`, `run_id`,
  `target_revision`, `test_project` (prompts.md §3).
- `_persist_scenario_verdicts` adds to `scenarios/<n>/scenario.json`:
  `binding: {kind, regression_id, origin, regression_rev, recipes,
  definition_path ("pm/qa/regression/<id>.md"), target_revision
  (planner_head), branch, run_id, loop_id, container_name or null (host),
  probe_reason, gap, authored_commit}` and `artifacts` (relative paths +
  mtimes under `scenarios/<n>/`, excluding pm-written files).
- For bound scenarios it also writes (idempotently, overwrite per run id)
  `captures/regression/<id>/runs/<run_id>.json` = `{run_id, pr_id, scenario,
  verdict, verified, regression_rev, recipes, target_revision, origin,
  captures_dir, artifacts, recorded_at}` — the regression's history index
  across PR runs (and standalone runs after R9).
- `qa_status.json` gets a per-scenario `binding` label; `qa_status.py`
  renders it as a dim line under the title (e.g. `regression: foo (created)`,
  `probe`, `unbound`).
- QA note / `latest_output` gain `regression_bindings_suffix(state)`
  (e.g. ` — regressions: reused a, b; created c; probes 1; unbound 0`),
  leaving `qa_outcome_detail`'s per-scenario format unchanged.

### R8 — Handoff/finalization
- Finalize prompt (prompts.md §6): drop the stale "push captures" wording
  (captures are not committed), add a goal confirming authored/extended
  definitions are on `origin/<branch>`; `build_qa_finalize_prompt` gains
  `authored_regressions`.
- Authoring alone never sets a scenario verdict other than `INPUT_REQUIRED`
  on failure; PASS still comes only from a worker verdict (+ verifier when
  enabled). Aggregation in `_execute_and_finalize` is unchanged.

### R9 — Standalone/discovery reuse (after pr-7d5d036 integration)
The standalone launch path pr-7d5d036 leaves must, for a template-valid
definition: resolve recipes through `qa_regression` (fail closed on an
invalid definition — no free-form fallback for template files), include the
same Regression Driver text (minus PR overlay), save captures under
`captures/regression/<id>/<run>/`, and write the same run record. Exact
wiring is decided after reading pr-7d5d036's code.

### R10 — CLI, docs
- `pm qa add-regression` stub = template skeleton; `pm qa list` marks
  non-bindable regressions with their first problem; `pm qa run <regression-id>
  --pr X` builds a `binding="regression"` scenario (steps: "as defined; no
  PR-specific Thens") instead of using it as an instruction.
- `pm_core/docs/qa_library.md` (after integration): regression section
  describes the template, binding, authoring, evidence; update the "Where
  each surface reads what" rows (planner, author, worker, verifier,
  finalize). `qa_loop` module docstring updated.

## 2. Implicit requirements
- **Resolve from the PR branch, not the base project.** `run_qa_sync`'s
  `pm_root` is the TUI's base project (`app._root`); authored definitions
  exist only on the PR branch. Listing, validation, installation and blob
  identities all use `GitTree(pr_workdir, planner_head)`.
- **Committed state only.** Uncommitted edits in the PR workdir are ignored
  by construction (git tree reads), satisfying "no uncommitted planner
  output".
- **Authoring precedes handoff**, so scenario clones (`create_scenario_workdir(...,
  expected_head=state.planner_head)`) contain the authored commit.
- **Author does not execute anything** (prompt + no execution tooling
  needed): it runs on the host like the planner, so it must not run PR code
  or recipes there.
- **Resume**: new scenario/state fields persisted; authoring is pre-launch,
  so like planning it is not resumable mid-phase (a restart during
  authoring restarts QA as today; the committed definitions persist and are
  reused).
- **Fake-claude**: new type must validate in `pm fake-claude config set`;
  to exercise authoring deterministically the fake gains optional
  per-iteration `files` (`{relpath: content}`, written in cwd) and `commit`
  (message; runs `git add <those paths> && git commit`). Fake-driven
  evidence is labelled simulated.
- **Prompt delivery**: definitions/steps/template are inlined whole (no
  truncation); listings of ids/paths may be bounded with omission markers
  naming `pm qa list` (`prompt_bounds`).
- **Logging** via `_log` for each binding decision, ignored field and
  validation failure.

## 3. Ambiguities and proposed resolutions
1. **Who authors?** A separate author session (one per run, processing all
   requests sequentially in one context), not the planner inline: keeps the
   planner lean, gives pr-51586d2 its injection point, avoids git races, and
   shares context across requests. *Alternative:* one author per request
   (more cost, parallel races) or planner-inline (no distinct prompt).
2. **Where does the author run?** Host, PR workdir — same as the planner,
   which already commits `pm/` files there; container mode continues to
   govern scenario execution. Mitigation: author is told not to execute
   anything; validation is deterministic. *Alternative:* author in a
   container with push proxy — safer boundary but needs fetch-back before
   handoff; I'd defer unless you want it now.
3. **Who commits?** The author; pm verifies and fails closed rather than
   committing for it.
4. **Exact vs fuzzy refs.** Exact (case-sensitive stem or `<dir>/<id>.md`)
   for REGRESSION and template refs; unknown → blocked, not ignored.
5. **Planner omits binding.** `unbound`, runs as probe, visible in records;
   not rejected.
6. **PR-specific Thens.** Not persisted on reuse; the author writes durable
   Thens only for created/extended definitions.
7. **Worker edits a definition.** Allowed only as a fix → NEEDS_WORK (back
   through review, fresh QA evidence next run).
8. **`mocks:` field.** Optional explicit refs to existing `pm/qa/mocks/`
   files, installed like recipes; no selection/authoring automation
   (pr-51586d2). pr-51586d2's "no mocks injection for existing-regression
   scenarios" concerns its diff-scoped catalogue, not mocks a definition
   itself declares; flag to that PR via a note.
9. **Discovery reuse proof.** Acceptance "later reuse" is demonstrated by a
   later QA run; standalone/discovery reuse is wired per R9 once
   pr-7d5d036's path exists.
10. **Standalone pm dirs** (pm repo not inside the PR's repo): REGRESSION
    reuse resolves from `pm_root/qa`; NEW_REGRESSION is blocked with a
    clear reason and the planner is told not to use it.
11. **Recipe edits by the author** that other regressions reference: allowed
    if compatible; recorded in `recipes_changed` and the QA note; other
    regressions are not re-run here (bounded).
12. **Authored definition when the run then fails/blocks.** Stays committed
    on the branch (durable, unverified); records show no verified run; the
    next run reuses it rather than re-authoring.
13. **TUI status line** for binding: included (small); drop if you prefer
    zero TUI changes.

## 4. Edge cases
- Two NEW_REGRESSION ids that are the same flow → author returns
  `reused_by_author` for one, both bind to the same id.
- NEW_REGRESSION id already exists → author is told; it extends/reuses or
  picks a free id.
- REGRESSION id exists on base but not on a stale PR branch → blocked with
  the branch sha; the planner never saw it because the listing is
  branch-based.
- The PR's own diff edits `pm/qa/**` → bindings use the PR's versions (the
  point of testing at `planner_head`).
- Concurrency cap: blocked scenarios never enter the queue; queued bound
  scenarios install at launch time.
- `pm qa run` reuses a fixed loop id and scenario index 1, so its
  `scenarios/1/` captures dir is reused; `run_id` includes a timestamp and
  the run record lists artifacts with mtimes so stale files are detectable.
- Verification disabled (`qa-verify-pass` off) → records carry
  `verified: false`.
- Held INPUT_REQUIRED runs: follow-up verification uses the same binding.
- Author pane dies / trust prompt / timeout / stop / PR merged mid-author:
  requests blocked (or run stopped for stop/merge), never PASS.
- Author `git add -A` sweeping unrelated planner files → path check rejects.
- No captures root (no session tag) → records skipped with a warning
  (existing `captures_dir` behaviour).
- Empty library + `PROBE` overuse: visible in QA note suffix; no hard gate
  (auditor pr-f4dc8a2 is the static check).

## 5. Implementation order
1. `qa_regression.py`, `regression_template.md`, unit tests.
2. Plan parsing + QAScenario/resume fields.
3. Planner prompt.
4. Session type + `regression_author.py` + authoring orchestration +
   fake-claude `files`/`commit`.
5. Binding resolution, install, concretizer/worker/verifier prompts.
6. Records, status, QA note suffix, finalize prompt.
7. CLI (`add-regression`, `list`, `run`).
8. After pr-7d5d036 merges: integrate master, R9, docs (R10), full suite
   once after final edits.

## 6. Tests and acceptance
Automated (pytest): template validation (each rule), GitTree/FsTree reads
and blob shas, exact refs, listing/empty/not-bindable text; plan parsing
(fields, precedence, placeholders, STEPS boundary, INSTRUCTION no longer
matching regressions); author block parsing and validation against real
temp git repos (created/extended/reused/blocked, weakened extension,
uncommitted, non-`pm/qa` path, missing result); authoring orchestration
with a patched pane (fixup round, timeout, stop); binding resolution
(unknown, invalid, valid, standalone pm dir); prompt content for planner,
author, worker, concretizer, verifier, finalize; records written and
idempotent; resume round-trip; `pm qa run <regression>`; session-type
registration; fake-claude `files`/`commit`.

Acceptance (QA phase, after pr-7d5d036 integration), in a disposable pm
test project built by the existing `tui-manual-test` setup recipe, honoring
the configured container mode (nested podman per that recipe):
1. Empty library / no fit: fake planner emits NEW_REGRESSION; fake author
   writes + commits a template file; check the commit on the test PR branch,
   the published head, the bound scenario, `prompt.md` driver block, scenario
   container, `scenario.json` binding + run record. Labelled simulated.
2. Later reuse: second run, planner emits REGRESSION for that id; no author
   pane; `origin: reused`; new run id/record; no new definition file.
3. Existing-scenario reuse with a pre-existing definition.
4. Failure: author reports `created` for an uncommitted or invalid file →
   scenario INPUT_REQUIRED `regression authoring failed`, overall not PASS;
   container runtime down → ERROR before any author launches.
5. **Needs your decision:** one bounded real-model run (≤2 scenarios: one
   created, one reused; then a reuse run) so a real author, worker and
   verifier produce independently checked evidence. Without it, the
   real-model path is first exercised when this PR's code drives QA after
   merge.

## 7. Out of scope
Mock selection/authoring (pr-51586d2); corpus port (pr-c77561b); historical
QA backfill; auditor (pr-f4dc8a2); sign-off prompt/report (pr-5f4f595 —
consumes the records here); bug-fix/impl prompt changes; Phase 7 coverage
gates; discovery cadence changes; any new runner/sandbox/recipe framework.
