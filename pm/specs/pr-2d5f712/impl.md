# Spec — pr-2d5f712: Sign-off step (dedicated window + lifecycle status + verdict router)

## Scope boundary (what this PR does / does NOT do)

This PR makes **sign-off a first-class lifecycle step** between `qa` and `merged`:
a new `sign_off` status, a dedicated tmux window (Claude pane + evidence pane),
a comprehensive-review prompt, a routing-verdict vocabulary, and the thin pm-side
executor that performs the routed hop.

**Explicitly deferred to other PRs (do NOT build here):**
- The improvement-watcher / auto-run / loop-guard / plan auto-start watcher and the
  *removal* of the old auto-merge / taste-check gates → **pr-ff9b728** ("the old paths
  are removed (cleanup lives in pr-ff9b728)"). This PR *adds* the replacement path;
  the old TUI auto-merge gates are left intact so existing QA flows keep working until
  pr-ff9b728 redirects/removes them.
- The human-facing behavior-report / dashboard surface shown in the window →
  **pr-8e693f6**. Here the non-Claude pane is a plain evidence-summary shell pane.
- Richer reason-strings (pr-b59f0c7) and the structured evidence model (pr-06a96fa)
  are *soft* alignment only — build against today's verdict+capture model.

## 1. Requirements (grounded in code)

### R1 — New lifecycle status `sign_off`
Today the enum is `{pending, in_progress, in_review, qa, merged, closed}`.
Add `sign_off` (logically between `qa` and `merged`). Sites that must change:

- `pm_core/pr_utils.py:5` `PRStatus` Literal and `:7` `VALID_PR_STATES` (canonical;
  `store._validate_pr_statuses` and `is_valid_pr_status`/`normalize_pr_status` all key off this).
- `pm_core/cli/pr.py:314` `--status` `click.Choice([...])` for `pr edit`.
- `pm_core/cli/pr.py:169` hard-coded `valid_statuses` set in `_apply_pr_edit()` (NOT imported — must edit literally).
- `pm_core/cli/helpers.py:262` `PR_STATUS_ICONS` (CLI rendering) — add `"sign_off"`.
- `pm_core/cli/helpers.py:438` `_record_status_timestamp` — add a `signed_off_at` timestamp on entry to `sign_off`.
- `pm_core/tui/tech_tree.py:27` `STATUS_ICONS`, `:79` `STATUS_STYLES`, `:90` `STATUS_BG`,
  `:101` `STATUS_FILTER_CYCLE` — add `sign_off` to each.
- `pm_core/tui/tree_layout.py:95` `has_active` set — add `"sign_off"` so a signing-off PR
  sorts as active (it is a working step like `qa`).
- `pm_core/pr_sync.py:193` merge-eligibility set and `:328` GitHub-sync "preserve qa"
  branch — treat `sign_off` like `qa` (eligible for is_merged detection; preserved on
  github OPEN sync as a local refinement).
- Color/marker choice: icon `◆` / style `bold blue` / bg `on #000033` / CLI icon `✔️`
  (distinct from `qa` magenta and `merged` green). Insert `sign_off` after `qa` in
  `STATUS_FILTER_CYCLE`.

### R2 — Dedicated sign-off window
New module `pm_core/signoff.py` with `launch_signoff_window(data, pr_entry, *, fresh, background, transcript, session_name)` mirroring
`pm_core/cli/pr.py:_launch_review_window` (1102–1326):
- window name `signoff-<display_id>` (via `_pr_display_id`).
- existing-window fast path (switch if not fresh; on fresh, capture `sessions_on_window`,
  `home_window.park_if_on`, `kill_window`).
- two panes: **evidence pane** (left) running an evidence-summary shell command, then
  `split_pane_at(evidence_pane, "h", claude_cmd, background=True)` for the **Claude pane** (right).
- register panes via `pane_registry.register_pane` with roles `signoff-evidence`,
  `signoff-claude`; reset `user_modified`; `switch_sessions_to_window` for captured sessions;
  `pane_layout.rebalance`.
- container wrapping mirrors review (`wrap_claude_cmd`, `remove_container`, captures bind-mount
  via `session_tag`); transcript symlink via `build_claude_shell_cmd(transcript=...)`.
- model resolution via `resolve_model_and_provider("signoff", ...)` (falls back through
  model_config defaults; add a `"signoff"` session_type — verify resolver tolerates unknown
  types and defaults gracefully; if it requires registration, register `signoff`).
- CLI entry `pm pr signoff [PR_ID] [--fresh] [--background] [--transcript ...]` in
  `pm_core/cli/pr.py` registered on the `pr` group, calling `signoff.launch_signoff_window`.

### R3 — Comprehensive review prompt
`prompt_gen.generate_signoff_prompt(data, pr_id, *, session_name, transcript=...)`:
- PR title/description/notes, plan context, the **full diff vs master** (backend-aware base,
  same as review: `base_branch` local vs `origin/<base_branch>`).
- **Every scenario + every step**: per-scenario verdict + reason from `qa_status.json`
  (read via `qa_status` / the captures `scenarios/<n>/verdict.md`), the scenario titles/foci.
- **Cross-stage evidence aggregation**: instruct the agent to read the WHOLE per-PR captures
  dir — `$(pm qa captures-path <pr-id>)` → `impl/` (repro/verify, "primary evidence" for bug
  fixes) AND `scenarios/<n>/`. Mention the harness-run regression provenance (Phase 10: fails
  at pre-fix parent sha, passes at fix sha) as part of the record (provenance is from the
  harness, not a session-written file).
- **Two evaluations**: (1) BDD — does captured behavior support the diff's claims;
  (2) meta-QA / anti-shortcut — was the QA itself rigorous (thin evidence, a scenario that
  drove a mock instead of the real path, an obvious uncovered edge case). Note this builds on
  the per-scenario quality supervisor (pr-98f670e) and is the PR-level pass.
- **Router-only contract**: never edit code; all fixes happen in impl/qa so they re-pass
  review+qa. Conservative bias: on genuine ambiguity emit `SIGNOFF_BLOCKED`.
- **Audit trail**: instruct the agent to record every classification + chosen hop via
  `pm pr note add <pr-id> '...'` so an autonomous merge is inspectable.
- **Emit exactly one routing verdict line** from the vocabulary in R4 (so pm can poll it,
  same mechanic as qa-finalize's `FINALIZE_DONE`/`FINALIZE_BLOCKED`).

### R4 — Verdict router (vocabulary + executor)
Routing-verdict constants in `pm_core/signoff.py`:
- `SIGNOFF_MERGE`   — verified PASS → merge (or gate).
- `SIGNOFF_REQA`    — PASS unverified (harness problem, e.g. verifier-cwd) OR misframed
                      scenario (INPUT_REQUIRED) → re-qa; do NOT bounce to impl.
- `SIGNOFF_REVIEW`  — a code change happened during QA (scenario fixed it itself) → back
                      through review AND qa.
- `SIGNOFF_IMPL`    — real gap (INPUT_REQUIRED) → back to implementation.
- `SIGNOFF_BLOCKED` — escalate/hold: genuine ambiguity, impossible/out-of-scope, or an
                      assumed-missing feature for which the agent filed a blocking PR.
`SIGNOFF_VERDICTS = (MERGE, REQA, REVIEW, IMPL, BLOCKED)`.

The four INPUT_REQUIRED sub-cases from the description are handled in the PROMPT and collapse
onto this vocabulary: misframed→REQA(+note); real gap→IMPL(+note); assumed-missing→agent files
new PR + `depends_on` via `pm pr add` then BLOCKED (block) or REQA (scope expanded — agent's
call); nice-to-have→agent files new PR then MERGE (defer) or IMPL (include if trivial);
impossible/out-of-scope→note + MERGE or BLOCKED. `pm pr add` creates a *pending* PR (no Claude
session) so the agent may run it; it must not run session-spawning commands.

Executor (SUPERSEDED — see R5/R10/R11 for the implemented shape). The original
single `act_on_signoff_verdict(..., autonomous, launch)` executor was **removed**
when autonomy was dropped (R5) and replaced by a decision/side-effect split (R10
§3): a pure `decide_signoff_hop(verdict) -> {ready_to_merge, qa, review, impl,
blocked, unknown}` (no state change, safe anywhere) plus `apply_signoff_hop(root,
pr_id, hop)` (the `sign_off → qa/in_review/in_progress` transition, auto-sequence
only). The mapping each verdict drives is:
- `SIGNOFF_MERGE` → `ready_to_merge` recommendation; PR stays `sign_off`, sign-off
  never merges (the merge decision belongs to pr-ff9b728). No `autonomous` branch.
- `SIGNOFF_REQA` → `sign_off → qa`, relaunch QA (`_launch_qa_detached`).
- `SIGNOFF_REVIEW` → `sign_off → in_review`, relaunch a review-loop iteration.
- `SIGNOFF_IMPL` → `sign_off → in_progress`, relaunch impl (`pr_start` background).
- `SIGNOFF_BLOCKED` → stay in `sign_off`, echo "paused: sign_off_blocked".
Status writes use `store.locked_update` + `_record_status_timestamp`, guarded on the
current status being `sign_off` (mirrors existing transition helpers); a bounce hop
also consumes the recorded verdict (`pr.pop("signoff")`) so a later re-entry can't
re-adopt a spent verdict and loop. The wiring lives in the auto-sequence
`sign_off` branch (R6), not in a standalone executor.

### R5 — Autonomy: REMOVED (orchestrator note-942fa37)
Autonomy was removed from this PR. Sign-off **always gates at merge**:
`SIGNOFF_MERGE` is always a recommendation (`decide_signoff_hop` returns
`"ready_to_merge"`; the PR stays in `sign_off`; sign-off never merges). The
`is_signoff_autonomous` reader, the `project.sign_off_autonomous` flag, the
per-plan seam, and the `autonomous`/`held` branching are all deleted. The
actual auto-merge-vs-hold decision belongs to the plan auto-start watcher
(pr-ff9b728) per its per-plan config.

### R7 — Per-step acceptance criteria (orchestrator note-0357619)
Sign-off must know the *purpose + acceptance criteria of EACH lifecycle step*
(impl / review / qa) and check each individually — not just generic checks. The
`generate_signoff_prompt` includes a "Per-step acceptance criteria" section that,
for each step, states its purpose, its acceptance criteria, and the routing
verdict a shortfall maps to (impl gap → `SIGNOFF_IMPL`; un-re-reviewed code →
`SIGNOFF_REVIEW`; thin/misframed/unverified QA → `SIGNOFF_REQA`). The reviewer
reports a per-step verdict and routes on the first step that fell short.

### R8 — Bug-PR capture gate: REMOVED (orchestrator note-942fa37)
The deterministic capture gate was removed to reduce complexity.
`bug_fix_capture_status`, `_dir_has_content`, the `bug_captures_ok` param, the
`SIGNOFF_MERGE → IMPL` override, and the prompt's PRE-FIX/POST-FIX
present/MISSING injection + mandatory-route rule are all deleted. The router's
general per-step review still reads `$CAP/impl/pre-fix/` and `$CAP/impl/post-fix/`
and judges whether the repro/verify evidence genuinely demonstrates the fix (no
hardcoded gate). The HTML report (#226 / pr-8e693f6) still RENDERS the pre/post-fix
captures (display only); the cross-PR note on pr-8e693f6 covers that.

### R9 — Re-runnable on merged: DEFERRED (orchestrator note, corrected)
An earlier orchestrator note (note-6f7abcd) asked for sign-off to be re-runnable
on already-merged PRs (re-open merged work to roll out process updates). This was
**corrected/withdrawn** — that capability is deferred to **pr-8015c1d**. For this
PR, sign-off only covers the normal forward lifecycle (qa → sign_off → merge, or
a bounce within a not-yet-merged PR). Process updates are handled by creating NEW
PRs, not by re-opening merged ones. `pm pr signoff` therefore rejects `merged`
PRs (entry from `qa`/`sign_off` only). The pre/post-fix capture gate (R8,
note-0357619) still applies.

### R10 — Routing refinements (orchestrator note-1a982f3, then note-942fa37)
1. **Capture gate** was first clarified as presence-only and then **removed
   entirely** (see R8) per note-942fa37.
2. **Per-plan autonomy seam** — **removed** along with all autonomy (see R5).
3. **Invariant: verdict → action ONLY under auto-sequence, for ALL hops** — KEPT.
   The routing is split into a pure DECISION (`decide_signoff_hop`, no state
   change, safe anywhere) and a SIDE-EFFECT (`apply_signoff_hop`, the
   sign_off → qa/in_review/in_progress transition). Only the auto-sequence
   sign_off branch calls `apply_signoff_hop`; manual `pm pr signoff`
   decides/recommends but never mutates.

### R11 — Verdict record + adoption (orchestrator note-511d725 §1)
The router records its verdict durably on the PR as
`pr["signoff"] = {verdict, sha, ts, origin}` (`sha` = the workdir HEAD it was
computed against; `origin` ∈ {`manual`, `auto-sequence`}).
- `signoff.record_signoff_verdict(root, pr_id, verdict, sha, origin)` writes it;
  `fresh_recorded_verdict(pr, current_sha)` returns the verdict iff the record's
  sha == current HEAD (fresh); `head_sha(workdir)` reads HEAD.
- The router self-records via hidden `pm pr signoff-record <id> <VERDICT>
  --origin <origin>` (a separate hyphenated command — `pm pr signoff record`
  would be parsed by click as `signoff` with `pr_id="record"`; the prompt
  instructs it; `origin` is threaded
  manual/auto-sequence through `pr_signoff` → `launch_signoff_window` →
  `generate_signoff_prompt`). Recording NEVER acts.
- **Auto-sequence ADOPTS** a fresh recorded verdict (sha == HEAD) instead of
  relaunching — picking up a hand-triggered run's verdict with no wasted re-run.
  If no fresh record, it reads the running window's transcript; on a verdict it
  records it (origin `auto-sequence`) then acts. Stale/absent → relaunch/running.
- Invariant preserved: only the auto-sequence branch calls `apply_signoff_hop`,
  so a manual run records but never acts; its verdict is adopted later.

### R12 — Sign-off display (orchestrator note-511d725 §2–4)
- **Running animation (§2):** a `sign_off` node with a workdir and no recorded
  verdict shows the spinner (`SPINNER_FRAMES` / `_anim_frame`, the same mechanism
  as review/qa), via a `sign_off` branch in `TechTreeNode.render`. Once a verdict
  is recorded the spinner is replaced by the verdict icon.
- **Verdict icons (§3):** `signoff.SIGNOFF_VERDICT_ICONS` / `SIGNOFF_VERDICT_STYLES`
  (single source of truth, re-exported by `tech_tree`) give each verdict a distinct
  marker; the `sign_off` status icon is `◆` (`STATUS_ICONS`). `qa_status._VERDICT_COLORS`
  also carries the sign-off verdicts.
- **`pm pr list` (§4):** `format_pr_line` appends the latest recorded verdict icon
  inside the status bracket for a `sign_off` PR (`[sign_off ⇤]`), consistent with
  the TUI.

### R6 — Transition wiring (qa-finalize → sign_off; sign_off → next hop)
Primary autonomous driver = the auto-sequence state machine (`pr_auto_sequence`,
`pm_core/cli/pr.py:2761`):
- `status == "qa"`, `overall == "PASS"` branch (`:2883`): instead of `echo "ready_to_merge"`,
  transition `qa → sign_off`, launch the sign-off window detached (background, transcript under
  the auto-seq dir for verdict polling), and echo `advanced: sign_off`.
- New `status == "sign_off"` branch: read the sign-off verdict via a new
  `_check_signoff_verdict(tdir, pr_id)` (mirrors `_check_review_verdict` — scan the auto-seq
  transcript with `extract_verdict_from_transcript(..., SIGNOFF_VERDICTS)`):
  - First ADOPT a fresh recorded verdict (R11: `fresh_recorded_verdict`, sha == HEAD);
    else read the running window's transcript and, on a verdict, record it
    (`origin auto-sequence`) before acting.
  - no verdict (record stale/absent AND transcript empty) → relaunch window if its
    tmux window is gone (echo `advanced: sign_off_relaunched`), else `running: sign_off`.
  - `SIGNOFF_MERGE` → always a recommendation (autonomy removed, R5): echo
    `ready_to_merge`; the PR stays in `sign_off`. Auto-sequence never merges
    (documented "stop before merge" contract); the autonomous-merge-vs-hold decision
    is deferred to pr-ff9b728's plan watcher.
  - `SIGNOFF_REQA` → `sign_off → qa`, `_launch_qa_detached`, echo `sign_off: re-qa`.
  - `SIGNOFF_REVIEW` → `sign_off → in_review`, launch fresh review-loop iteration, echo `sign_off: returning to review`.
  - `SIGNOFF_IMPL` → `sign_off → in_progress`, relaunch impl, echo `sign_off: returning to impl`.
  - `SIGNOFF_BLOCKED` → echo `paused: sign_off_blocked`.

The TUI `_on_qa_complete` auto-merge path (`qa_loop_ui.py:494`) is **left unchanged** this PR
(it is one of the "old paths" pr-ff9b728 redirects). Sign-off is reachable via `pm pr signoff`
and the auto-sequence. This keeps the large existing QA-flow test/QA surface stable.

## 2. Implicit Requirements
- Adding `sign_off` to `VALID_PR_STATES` is mandatory or `store._validate_pr_statuses`
  silently resets it to `pending` on every load.
- `STATUS_ICONS`/`STATUS_STYLES`/`STATUS_BG` use `.get(status, default)`, so a missing key
  won't crash — but the tree would render a generic marker; all three plus `STATUS_FILTER_CYCLE`
  must include `sign_off` for correct rendering and the filter cycle to reach it.
- The sign-off window requires a PR `workdir` (for the diff/captures + Claude cwd); reuse
  `_ensure_workdir` like review does.
- Verdict polling reuses `poll_for_verdict` + `extract_verdict_from_transcript`
  (`pm_core/qa_loop.py`) and the transcript-symlink seam in `build_claude_shell_cmd`.
- The evidence pane command must `shell_quote` all user-controlled values (PR title) — same
  apostrophe hazard documented in `_launch_review_window`.
- `pm pr add` for filing follow-up PRs must set `depends_on`; verify the CLI supports a
  `--depends-on`/equivalent or that the agent edits it via `pm pr edit`.

## 3. Ambiguities (resolved)
- **A1 — Does sign-off route all QA outcomes or only PASS?** Resolved: only after a QA **PASS +
  successful finalize** (the "qa-finalize → sign_off" transition). QA `NEEDS_WORK`/`INPUT_REQUIRED`
  still bounce at the QA level as today (nothing to sign off on). The router's own NEEDS_WORK/
  INPUT_REQUIRED outcomes are sign-off **downgrades** of a QA PASS based on comprehensive review
  (e.g. a scenario silently committed a fix → REVIEW; meta-QA finds a real gap → IMPL). This
  reconciles "qa-finalize → sign_off" with the router handling all three verdicts, and minimizes
  behavioral risk.
- **A2 — Agent vs pm executes the hop?** Resolved: agent emits one structured routing verdict +
  records audit notes (router-only, never edits/merges); pm polls the verdict and executes the
  hop (status transition / relaunch / merge-in-autonomous). Mirrors qa-finalize exactly →
  inspectable + unit-testable.
- **A3 — Flag location/default.** Resolved: `project.sign_off_autonomous`, default False (gated),
  matching `skip_qa`.
- **A4 — Second pane content.** Resolved: a plain evidence-summary shell pane (captures listing +
  per-scenario verdicts + diff stat); the rich report surface is pr-8e693f6.
- **A5 — Whether to redirect the TUI auto-merge path now.** Resolved: no — left to pr-ff9b728's
  cleanup; sign-off is wired via the command + auto-sequence to avoid destabilizing the existing
  TUI QA flows.

No **[UNRESOLVED]** ambiguities.

## 4. Edge Cases
- A PR manually edited to `sign_off` then `pm pr signoff` run with no QA artifacts: prompt
  degrades gracefully (evidence aggregation notes "no captures found"); router can still produce
  a verdict (likely BLOCKED/REQA).
- Re-running `pm pr signoff` without `--fresh` switches to the existing window (no duplicate),
  like review.
- `SIGNOFF_REQA`/`REVIEW`/`IMPL` must guard the status write on `status == "sign_off"` so a
  concurrent sync that already moved the PR (e.g. merged externally) doesn't get clobbered.
- pr_sync: a `sign_off` PR merged externally on GitHub must still be detected (hence adding
  `sign_off` to the eligibility set) and preserved as a local refinement on OPEN sync.
- Container mode: the sign-off container's `/pm-captures` must point at the same per-PR captures
  dir (session_tag bind-mount) so the agent reads impl + scenario captures from inside the pane.
- Conservative bias is enforced by the prompt (ambiguity → BLOCKED), not by pm — pm faithfully
  executes whatever single verdict the agent emits; absence of a verdict = `running`/relaunch,
  never an implicit merge.
