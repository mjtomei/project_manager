# pr-1ae1d2d — persisted QA evidence must carry PR/run identity

## 0. Bug, restated in code terms

A live QA run for `pr-0b87a97` produced scenarios 1–5, but the enclosing
`captures/pr-0b87a97/scenarios/` directory also contained **synthetic PASS
records** (titles `Smoke`, `s`, `s1`, `s2`, `Alpha check`, `Beta check`) —
written by a nested fake-Claude QA fixture driven *inside* one of the outer
scenario containers, and by earlier implementation-verification runs. Records
1/2/5/6 were refreshed during the live fixture tests; 3/4 were left over. The
outer driver rewrites its own records on completion, which masked the
overwrite but did not remove the orphan (6) and does not prove isolation.

Why the current code allows this:

1. **No provenance.** `qa_loop._persist_scenario_verdicts`
   (`pm_core/qa_loop.py:1915`) writes `scenarios/<n>/scenario.json` with only
   `index/title/focus/steps/verdict/reason`. `verdict.md` and `prompt.md` are
   written by `_write_scenario_capture_file` (`pm_core/qa_loop.py:1877`).
   Nothing on disk says *which PR* or *which QA run* produced a record, so a
   record from a different project or an earlier run is byte-identical in
   shape to real coverage.
2. **No authoritative membership.** There is no manifest of "the scenarios
   this run owns". Every consumer that wants scenario membership either reads
   the live `qa_status.json` in the ephemeral QA workdir
   (`paths.latest_qa_status_path`, used by the sign-off prompt at
   `pm_core/prompt_gen.py:641`) or — in the sign-off agent's case — walks
   `$CAP/scenarios/<n>/` directly, where orphan and foreign directories are
   indistinguishable from this run's evidence.
3. **Nothing removes or marks orphans.** A scenario index can be reused
   across runs because `_next_scenario_offset` (`pm_core/qa_loop.py:253`)
   scans *workdirs* (`~/.pm/workdirs/qa/<pr>-*/s-*`), so synthetic records
   that never had a workdir never bump the offset. A new run can therefore
   land on an index whose directory still holds foreign files.

**Relationship to #264 / pr-1e9c117 (do not duplicate).** That PR (commit
`2739187c`, plus `f20f156e` for the whitespace-stripped owner match) makes
`captures_dir` fail closed when `PM_CAPTURES_PR` is absent/empty/mismatched,
i.e. it *prevents* the nested write when the marker is missing. **It has
since landed on `origin/master`**, so the mount is no longer handed to any
PR with an unset marker:

```python
mount_pr = (os.environ.get(CAPTURES_PR_ENV) or "").strip()
if mount.is_dir() and mount_pr and mount_pr == pr_id:
    return mount
```

The incident's *write* path is therefore closed for anything running this
`paths.py`. What remains live — and is what this PR owns — is: an older
running controller that still carries the fail-open routing, a fixture
writing before the fix, and legacy pre-fix records already on disk. This PR
does **not** modify that routing rule (its `paths.py` diff is only the
additive `create=False` reader mode); it defends on the evidence side (the
`_captures_root_is_ours` quarantine guard, below). The two compose: routing
stops the write; provenance makes any write that still happens detectable and
non-authoritative.

Merge note (updated 2026-10-29): this branch was cut from a pre-#264
`master`. It has now been merged with `origin/master@4a74d880` (the 2026-10-29
restart). Two files conflicted:

- `paths.captures_dir`'s **docstring** — reconciled by keeping the branch's
  `create=False` reader paragraph *and* master's fail-closed "Returns None …
  not owned by *pr_id*" wording. The routing code auto-resolved to master's
  fail-closed form (the branch never touched those lines); the branch keeps
  only its additive `create` parameter.
- `pm_core/qa_loop.py` — master had rewritten the same regions this PR
  touches. Resolution:
  - `_write_status_file` now carries **both** master's `waiting_for_input`
    parameter and this PR's `run_id`; every call site (including master's new
    `_write_status()` closure and the hold/reopen writes) passes
    `run_id=state.loop_id`.
  - `_execute_and_finalize` keeps master's hold/follow-up loop verbatim; this
    PR's `_persist_scenario_verdicts(..., overall=…)` and the post-persist
    `_sync_captures_evidence` were re-inserted after the loop's final-status
    write, so the completion re-sync runs on every iteration (including a
    reopened held run).
  - All four early-exit `_sync_captures_evidence(..., scenarios=[])` calls and
    the two start-of-run syncs (`run_qa_sync`, `resume_qa_sync`) survived
    unchanged.

No behavioural loss on either side: master's hold logic and this PR's evidence
provenance are orthogonal and compose.

## 1. Requirements

### R1 — Provenance module
Add `pm_core/captures.py`, the single source of truth for persisted evidence
provenance. It must expose:

- `MANIFEST_NAME = "qa_manifest.json"`, `RUNS_DIR_NAME = "qa_runs"`,
  `SCENARIO_RECORD_NAME = "scenario.json"`, `FOREIGN_DIR_NAME = "_foreign"`,
  `SCHEMA = 1`.
- `manifest_path(captures_root) -> Path`,
  `scenario_record_path(captures_root, index) -> Path`.
- `write_manifest(captures_root, *, pr_id, run_id, scenarios, overall="",
  started_at=None) -> Path | None` — atomic (`<name>.tmp` + `rename`), best
  effort (log and return `None` on `OSError`), never raises.
- `read_manifest(captures_root, *, pr_id=None, run_id=None) -> dict | None` —
  parses and validates; a manifest whose `pr_id` does not match the
  requested PR is never trusted (a nested fixture can write one into the
  wrong tree). Resolution: the root pointer, then
  `qa_runs/<run_id>.json`, then the newest `qa_runs/*.json` naming the PR —
  so a fixture overwriting the root pointer cannot destroy the PR's own
  membership.
- `write_scenario_record(captures_root, index, record, *, pr_id, run_id)` —
  stamps `schema`, `pr_id`, `run_id`, `captured_at` onto the record and
  writes `scenario.json` atomically.
- `audit(captures_root, *, pr_id, run_id) -> EvidenceAudit` — the authoritative
  view described in R5/R6.
- `quarantine_foreign(captures_root, *, pr_id, run_id) -> list[Path]` — R5.

The module has no tmux/git/store dependencies so it is unit-testable.

### R2 — `scenario.json` carries PR + run identity
`_persist_scenario_verdicts` (`pm_core/qa_loop.py:1915`) writes the per-scenario
record through `captures.write_scenario_record`, so the persisted record
contains:

```json
{"schema": 1, "pr_id": "pr-…", "run_id": "<state.loop_id>", "captured_at": "…",
 "index": 3, "title": "…", "focus": "…", "steps": ["…"],
 "verdict": "PASS", "reason": "…"}
```

`state.loop_id` (`pm_core/qa_loop.py:187`, `secrets.token_hex(8)`) is the QA
run id; it is already the `~/.pm/workdirs/qa/<pr>-<run_id>/` suffix and
survives a resume (`build_resume_state`, `pm_core/qa_loop.py:977`). It is the
"real run ID" the report must be bound to.

Existing keys and their order/shape are preserved so the sign-off agent's
current reading of `scenario.json` keeps working; new keys are additive.

### R3 — Per-run manifest at the captures root
`$CAP/qa_manifest.json` records the run that currently owns this PR's QA
evidence:

```json
{"schema": 1, "pr_id": "pr-…", "run_id": "<loop id>", "started_at": "…",
 "updated_at": "…", "overall": "PASS" | "",
 "scenarios": [{"index": 1, "title": "…", "verdict": "PASS"}, …]}
```

Written (atomically, overwriting the previous run's manifest) by the QA
orchestrator at two points. **Every run also keeps a copy at
`$CAP/qa_runs/<run_id>.json`**: the root file is a "current run" pointer
that a nested fixture writing into the enclosing tree can overwrite, and the
per-run copy is what makes the PR's own membership recoverable afterwards
(observed in the repro: the fixture clobbers the pointer and the outer run's
manifest still resolves).

- **Execution start**, in `run_qa_sync`'s launch path
  (`_sync_captures_evidence(state)` just after the initial
  `_write_status_file` and before the first scenario prompt is written) —
  so `prompt.md` directories are covered even if the run dies before any
  verdict is persisted. Scenario 0 (interactive) is **not** a member.
  `resume_qa_sync` runs the same sync before re-entering the poll phase: a
  TUI restart must not skip the start-of-run quarantine, because queued
  scenarios launch from there and their `prompt.md` must not land on another
  project's record. `loop_id` survives the restart, so a resume re-asserts
  the same run.
- **Completion**, in `_execute_and_finalize`, after
  `_persist_scenario_verdicts` (which also publishes the final membership),
  with final verdicts and `overall` (`state.latest_verdict`).
- **Early exits that produce no scenarios** (planner trust-blocked, QA spec
  missing, planner handoff failed): an empty-membership manifest still
  records that this run owns nothing, so an older run's directories cannot
  pass as its coverage.  `_sync_captures_evidence` therefore takes a
  `scenarios` override and those exits pass `[]` — a run that planned but
  never launched a scenario must not list its plan as membership (the audit
  would otherwise report each planned scenario as "manifest member whose
  evidence is missing").  Every exit after a plan was accepted but before
  any launch follows this rule, not just the first two.

`$CAP/integration.json` (`pm_core/integration.py:399`) is untouched.

### R4 — `qa_status.json` carries the run id
`_write_status_file` (`pm_core/qa_loop.py:738`) gains an optional `run_id`
parameter (default `""`) and emits `"run_id": …` beside `pr_id`. Every call
site inside `qa_loop` passes `state.loop_id`. The default keeps the ~10 test
call sites and any external caller working.

### R5 — Foreign records leave the scenario namespace
`captures.quarantine_foreign` moves — never deletes — a `scenarios/<n>/`
directory into `scenarios/_foreign/<run_id>-<n>/` when its `scenario.json`
**explicitly names a different `pr_id`**. That is the only unambiguous case:
a nested fixture's record is provably not this PR's evidence.

- Same-PR records from an earlier run are legitimate history and stay put.
- Records with no `scenario.json`, or one lacking `pr_id` (all pre-fix
  records, including the synthetic ones already on disk), are *not* moved —
  they are reported as `unowned` by `audit` and excluded from authoritative
  membership. Moving them would risk discarding genuine legacy evidence, and
  the PR note requires existing captures be preserved.
- Quarantine runs at execution start **and** at completion, because the
  observed contamination is written by a fixture *during* the outer run.
- A pre-existing `_foreign/<run_id>-<n>` is not overwritten; a numeric
  suffix is appended.
- An empty `pr_id` quarantines nothing: "a different `pr_id`" is only
  defined relative to the PR we are, so without one every identity-carrying
  record would look foreign — and a move is not undoable by the caller that
  made the mistake. (`write_manifest` likewise writes nothing without a
  `pr_id`/`run_id`.)

### R6 — Authoritative membership + audit surface
`captures.audit` returns, for a `(captures_root, pr_id, run_id)`:

- `manifest`: the validated manifest or `None`.
- `members`: the manifest's scenario entries (authoritative membership).
- `dirs`: every `scenarios/<n>/` directory on disk, classified as
  - `current` — `scenario.json` names this `pr_id` and this `run_id`;
  - `prior-run` — names this `pr_id` and a different run id;
  - `foreign` — names a different `pr_id`;
  - `unowned` — no record, or a record with no `pr_id` (legacy/pre-fix).
- `orphans`: directories not present in `members`.
- `anomalies`: human-readable one-liners for foreign/unowned/orphan dirs, a
  manifest/`qa_status.json` run-id disagreement, a root `qa_manifest.json`
  that is missing, unreadable (damaged JSON — reported as damaged, not as
  absent: the audit must say what is actually on disk), unusable, or names
  another PR while the membership came from `qa_runs/` (the fixture-clobber
  signature — the audit is the surface that has to show it), and a
  **manifest member with no evidence directory**
  (its evidence was destroyed or never captured — sign-off must see missing
  evidence, not a synthetic record). A member whose directory exists but
  holds no provenance record is reported as a member without a record, not as
  "not bound to a QA run" — the audit must not contradict the membership it
  just printed — and the wording distinguishes a launched scenario that never
  produced a verdict (only `prompt.md`) from a record that exists but carries
  no PR/run identity (legacy/pre-fix, or the incident's synthetic fixture
  records).

New CLI command `pm qa evidence <pr_id>` (`pm_core/cli/qa.py`, beside
`captures-path`) prints the audit: PR, run id, manifest scenario list, and
each anomaly. It resolves the captures dir through `paths.captures_dir` (so it
works on the host and inside a container) and exits 0 for any existing PR —
including when no captures dir exists, which is reported as the audit's "no
captures dir" anomaly rather than a command failure, so a sign-off session
does not abort on "nothing captured yet". It is a *reader*, it never writes.
This is the surface a sign-off session (or a QA scenario) uses instead of
listing arbitrary directories.

### R7 — Sign-off prompt binds to the run
`pm_core/prompt_gen.py`:

- `_signoff_qa_scenarios_parts` (`:641`) reads the manifest for the PR —
  resolving it under the **pm session's** captures tag (threaded from
  `generate_signoff_prompt`'s `session_name`, `pm-<tag>` -> `<tag>`, exactly
  as `qa_loop` derives `QALoopState.session_tag`), because prompt generation
  can run with a cwd whose own tag drifts (a workdir clone) and a real
  manifest must not then be reported as "not run-bound" — and:
  - adds `QA run: <run_id>` to the inlined `head` (never truncated — it is
    pm-generated evidence, like the overall verdict and QA error);
  - when the manifest's scenario indices differ from `qa_status.json`'s,
    adds a one-line warning naming both sets (this is the "a later run
    replaced this evidence" case);
  - states that membership is the manifest's scenarios, "not whatever
    directories exist under `$CAP/scenarios/`"; when the manifest lists no
    scenarios (a run that launched nothing), says plainly that the run
    captured no coverage rather than rendering "the 0 scenario(s)";
  - when no manifest exists (legacy), says so in one line so the session knows
    membership is not run-bound.  That line only promises "the scenarios
    listed below" when a per-scenario listing really follows the head: on the
    no-`qa_status.json` path there is none, so the wording says the evidence
    cannot be enumerated instead of pointing at an absent listing.
- The evidence checklist (`:924-926`) gains, under the `CAP=…` bullet:
  - `$CAP/qa_manifest.json` — "the authoritative record of which QA run and
    which scenarios own this PR's evidence";
  - the rule that only scenarios listed in the manifest are this run's
    coverage, that `$CAP/scenarios/<n>/` directories outside it (and any
    whose `scenario.json` names another `pr_id`/`run_id`) are stale/foreign
    and **must not be cited as coverage**, and that a missing demonstration
    for a manifest scenario is a `SIGNOFF_REQA` (the existing rule, now
    anchored to real membership).
- The dashboard-contract block (`:986-1000`) adds a required meta tag:
  `<meta name="pm-signoff-qa-run" content="<the QA run id you reviewed>">`,
  documented as binding the report's scenario membership to that run. The
  contract also says to omit the tag when the QA block reports no run-bound
  manifest (legacy evidence) rather than invent one — including when the
  block still names a run from `qa_status.json`, which is not the tag's
  value — the session would otherwise bind its own report to a run that
  does not exist and the merge gate would refuse it.

### R8 — Dashboard flags a report bound to another run
`pm_core/behavior_report.py`:

- `_DashRow` gains `qa_run: str`, `qa_current_run: str` and
  `qa_run_stale: bool` (the current run id is carried so the marker's
  `title` can name both runs).
- `gather_dashboard_rows` (`:126`) reads `pm-signoff-qa-run` via
  `extract_signoff_meta` and the current manifest via
  `captures.read_manifest(captures_root_dir / pr_id, pr_id=pr_id)`; the row is
  stale when both exist and the ids differ.
- `render_dashboard_html` renders a visible `⚠ QA run changed` marker (with a
  `title` naming both run ids) next to the verdict for stale rows, so a report
  built from superseded evidence is not read as current coverage.

### R9 — Merge gate refuses a report bound to another run
`signoff.merge_gate_refusal` (`pm_core/signoff.py:336`) gains a check beside
the existing `report_hash` check: when the PR has a manifest and the
`report.html` carries `pm-signoff-qa-run` naming a different run id, refuse
with a message telling the operator to re-run sign-off. A report with no
`pm-signoff-qa-run` tag (legacy) is **not** refused — no new hard requirement
is introduced for pre-existing reports.

### R10 — Tests
`tests/test_captures_provenance.py` (new):

- manifest round-trip, atomic write, and rejection of a manifest whose
  `pr_id` differs;
- `write_scenario_record` stamps `schema/pr_id/run_id/captured_at` and keeps
  the existing keys;
- `audit` classification for current / prior-run / foreign / unowned and
  orphan detection;
- `quarantine_foreign` moves only foreign dirs, preserves bytes, does not
  overwrite an existing quarantine target, and leaves prior-run/unowned dirs;
- `_persist_scenario_verdicts` stamps `pr_id`/`run_id` from the state;
- `_write_status_file` emits `run_id` (and omits it when not supplied);
- sign-off prompt contains the run id, the manifest bullet and the
  `pm-signoff-qa-run` contract, and warns on a manifest/status mismatch;
- dashboard row is stale exactly when report run ≠ manifest run;
- `merge_gate_refusal` refuses a mismatched report run and allows a missing
  tag;
- `pm qa evidence` output lists members and anomalies.
- `paths.captures_dir` / `paths.captures_root` reader mode (`create=False`):
  an existing dir is returned, a missing one is not created;
- the sign-off head refers to "the scenarios listed below" only when a
  listing really follows it;
- `_execute_and_finalize` re-syncs the evidence (quarantine + manifest) after
  persisting the verdicts, carrying the final `overall` — and still does so
  when the per-scenario persistence raised;
- `run_qa_sync` records an empty membership at every post-planning early exit
  (QA spec missing, planner handoff failed) — those two live in
  `tests/test_qa_planner_handoff.py`, next to the planning harness they drive.

## 2. Implicit requirements

- **Best effort, never fatal.** Every new writer is wrapped so an `OSError`
  (read-only mount, missing captures dir, concurrent rename) logs and
  returns rather than aborting a QA run or a sign-off. `captures_dir` may
  return `None`.
- **Atomic writes.** Manifest and scenario records use `write tmp` + `rename`
  (the pattern `_write_status_file` already uses) so a reader never sees a
  half-written manifest.
- **Host/container split.** The manifest is written by the *host* QA
  orchestrator into the host captures dir that is bind-mounted at
  `/pm-captures`; sessions in containers read it as `$CAP/qa_manifest.json`.
  Nothing may inline a host-absolute path into a prompt.
- **Resume.** `loop_id` survives a TUI restart (`build_resume_state`), so a
  resumed run keeps the same run id and its manifest stays valid.
- **Legacy compatibility.** No manifest → today's behaviour, with an explicit
  one-line notice in the prompt. No `pm-signoff-qa-run` tag → the merge gate
  and dashboard do not refuse/flag. Records without `pr_id`/`run_id` remain
  readable.
- **Prompt budget.** All prompt additions are static text or one inlined line;
  they stay well inside `PROMPT_ARG_LIMIT` (120 KB) and the QA listing handed
  to `fit_prompt` is unchanged in shape.
- **No duplication of #264.** `pm_core/paths.py`'s *routing* rule (which PR
  owns the mount) is not modified — only the additive `create=False` reader
  mode on `captures_dir`/`captures_root`.
  `tests/test_captures_dir_mount.py` is not modified.
- **Preserve existing captures.** Nothing is deleted; quarantine is a move,
  and only for provably-foreign records.

## 3. Ambiguities (resolved)

- **A1 — where the manifest lives.** `$CAP/qa_manifest.json`, beside
  `report.html` and `integration.json`, not inside `scenarios/` (that
  namespace is per-scenario directories and is walked by agents).
  Resolution: captures root.
- **A2 — one manifest or per-run files.** A single root manifest alone is not
  enough: the incident's foreign writer *is* a nested fixture writing into
  the enclosing tree, so it can clobber the root pointer. Resolution: write
  both — the root `qa_manifest.json` is the current-run pointer, and
  `qa_runs/<run_id>.json` keeps each run's membership recoverable. Readers
  prefer the root, then the run's copy, then the newest matching run.
- **A3 — should unowned (pre-fix) records be quarantined?** They are the ones
  actually on disk from the incident, but they may also be genuine legacy
  evidence from a real earlier run of the same PR. Resolution: do not move;
  report them as `unowned` anomalies and exclude them from authoritative
  membership (which comes from the manifest). Only an explicit foreign
  `pr_id` triggers a move.
- **A4 — how strict is the merge gate?** A hard requirement would break every
  report written before this change and could loop sign-off if the agent
  forgets the tag. Resolution: mismatch-only refusal, gated on a manifest
  existing.
- **A5 — is scenario 0 a member?** No: it is the interactive exploratory
  window, has no verdict and writes no `scenarios/0/` evidence. It stays in
  `qa_status.json` (display contract) but not in the manifest.
- **A6 — a manifest written by a nested fixture.** Readers pass the expected
  `pr_id`; a manifest naming another PR is treated as absent. Resolution:
  validate on read.
- **A7 — `run_id` for legacy `qa_status.json`.** Older status files have none;
  the prompt falls back to the manifest, then to "not run-bound".

No **[UNRESOLVED]** items.

## 4. Edge cases

- **No scenarios ran** (`state.scenarios == []`): the manifest is still
  written with `"scenarios": []` — it binds the run and records that it owns
  no evidence, which is exactly the fact a later report must not invent
  around.
- **Manifest missing but scenario dirs present** (legacy PR): prompt says
  membership is not run-bound; `pm qa evidence` lists every dir as `unowned`;
  the dashboard does not flag; the merge gate allows.
- **`captures_dir` returns `None`** (no session tag, no mount): writers log
  and no-op; readers report "no captures dir".
- **Foreign record at an index the current run also owns**: quarantine runs
  *before* launch, so the current run writes into a clean directory. If a
  fixture writes during the run, the completion rewrite restores
  `scenario.json`/`verdict.md` ownership and quarantine moves any remaining
  foreign-only index (e.g. the observed orphan 6) out of `scenarios/`.
- **Two runs racing** (a stale controller and a new one): last manifest write
  wins; the loser's `scenario.json` records still name their own run id, so
  they audit as `prior-run` and are never counted as the current run's
  membership.
- **Quarantine target already exists**: `_foreign/<run_id>-<n>` collides →
  append `-1`, `-2`, … rather than overwrite.
- **`scenario.json` unreadable / not JSON**: classify `unowned`, never raise.
- **Index 0 directory** (does not normally exist): treated like any other
  non-member dir (orphan) — it is not in the manifest.
- **Sign-off re-run against a new QA run**: the previous report still carries
  the old `pm-signoff-qa-run`; the dashboard flags it and the merge gate
  refuses until the report is regenerated for the new run.
- **A nested project resolving the *enclosing* PR's mount** (a controller
  predating #264 leaves `PM_CAPTURES_PR` unset, so a fixture's
  `captures_dir` returns `/pm-captures`): the fixture must not *quarantine*.
  Quarantine is a move, and from the fixture's point of view the enclosing
  PR's real records name "another" `pr_id` — running it there would move the
  enclosing PR's evidence out of `scenarios/`. `_sync_captures_evidence`
  therefore quarantines only a captures root that is provably this PR's (not
  the shared mount, or a mount marked with this PR's `PM_CAPTURES_PR`); the
  manifest write still happens, because it is recoverable via `qa_runs/`.
  The marker is compared with surrounding whitespace stripped, matching the
  mount decision `paths.captures_dir` makes after #264/pr-1e9c117 (a trailing
  newline from a shell `export` still grants the mount there, so the guard
  must agree — otherwise it would refuse to quarantine a tree that
  `captures_dir` handed us as this PR's, silently disabling R5 for exactly
  the container case).
- **Scenario 0 in the manifest-vs-status membership check**: `qa_status.json`
  lists the interactive scenario 0 (display contract, A5) but the manifest
  never does, so the prompt's disagreement warning compares the listings
  with index 0 excluded — otherwise it would fire on every normal run.
- **Two runs publishing the manifest concurrently** (a stale controller and a
  fresh one): each writer uses its own temp file (`<name>.<pid>.<rand>.tmp`)
  before `os.replace`, so the intended last-write-wins cannot become a
  half-written file, and readers still fall back to `qa_runs/<run_id>.json`
  if a pointer is unreadable.
- **Non-canonical numeric directory names** (`scenarios/03`): indices are
  only accepted when `str(int(name)) == name`. Every helper turns an index
  back into a path, so treating `03` as index 3 would make
  `quarantine_foreign` move `scenarios/3` — a different directory — on
  `03`'s record. pm only ever writes `str(index)`, so such a directory is
  left alone (and is not classified).
- **A manifest member whose only record is from a prior run**: reported as
  "manifest member whose record is from prior QA run X — this run's evidence
  for it is missing", not merely as history.
- **The root pointer clobbered but membership recovered**: the audit keeps
  reporting the recovered membership (that is the point of `qa_runs/`) and
  adds an anomaly naming the foreign owner, so `pm qa evidence` shows both
  the truth and the tampering instead of silently presenting recovered data.

## 5. Implementation notes (files touched)

- `pm_core/captures.py` — new module (R1, R5, R6).
- `pm_core/qa_loop.py` — `_write_status_file` `run_id` (R4);
  `_persist_scenario_verdicts` stamping + manifest + completion quarantine
  (R2, R3, R5); `_sync_captures_evidence` start-of-run/completion sync (R3,
  R5) with the shared-mount quarantine guard; `_execute_and_finalize`
  completion sync; `resume_qa_sync` start sync; pass `run_id` at every
  `_write_status_file` call site.
- `pm_core/paths.py` — `captures_dir(create=False)` and
  `captures_root(create=False)` so readers (prompt builders, `pm qa
  evidence`, the merge gate) never create a captures dir as a side effect.
- `pm_core/prompt_gen.py` — QA head/listing run binding, evidence checklist,
  report meta contract (R7).
- `pm_core/behavior_report.py` — dashboard stale-run marker (R8).
- `pm_core/signoff.py` — merge-gate run binding (R9).
- `pm_core/cli/qa.py` — `pm qa evidence` (R6).
- `tests/test_captures_provenance.py` — new tests (R10); existing
  `tests/test_prompt_bounds.py` / `tests/test_behavior_report.py` /
  `tests/test_signoff.py` assertions updated only where the new text is
  asserted verbatim.
