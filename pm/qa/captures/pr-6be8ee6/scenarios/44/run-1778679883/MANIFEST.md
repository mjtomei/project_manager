---
recipe: cli-recording
pr: pr-6be8ee6
scenario: 44
phase: scenarios/44/run-1778679883
---

# Scenario 44: Review-loop INPUT_REQUIRED gate, qa_finalize close-out, duplicate-verifier guard

## Files

- `review-pane-input-required.txt` — Step 5 (CP3a). Real review-loop pane
  capture. Reviewer ran against pr-194c003 with no captures dir and emitted
  `INPUT_REQUIRED`, explicitly citing missing `pm/qa/captures/pr-194c003/impl/`
  pre-fix/post-fix per `pm_core/bug_fix_prompts.py:76-79`. Several other gaps
  (missing spec, no failing test demo) were also flagged.
- `review-pane-pass.txt` — Step 6 (CP3b). After committing minimal
  manifest+transcript stubs into `pm/qa/captures/pr-194c003/impl/{pre-fix,post-fix}/`
  and re-running with `--fresh`, the reviewer's INPUT_REQUIRED reason set
  shifted: the *missing-captures* gate from step 5 is gone (reviewer now sees
  the directory and manifests), but it now flags the placeholder transcript
  content. Per scenario step 6 expected behavior, this is the accepted failure
  mode — the captures-specific INPUT_REQUIRED from step 5 is no longer cited.
- `tui-main-step5.txt`, `tui-main-step6.txt` — `pm tui view` captures at each
  checkpoint. Note: PR badge did not visibly transition to `⏸<n>` in TUI even
  though the review pane printed INPUT_REQUIRED. This may be a TUI badge
  rendering / verdict-transcript-pickup issue (see bug-fix note 6829b6a
  re: verdict transcript symlink slug mismatch).
- `duplicate-guard-commit.diff`, `duplicate-guard-commit-msg.txt`,
  `duplicate-guard-code.py` — Step 8 (CP5) evidence. Code-level verification
  of commit e8fe399 in `pm_core/qa_loop.py:1996`: after a verifier FLAGGED a
  PASS and a follow-up is sent to the scenario pane,
  `_last_scenario_hook_ts[scenario_idx] = time.time()` is stamped (NOT
  popped). The poll gate at `qa_loop.py:2070-2078` enforces `ev_ts > last_ts`,
  ensuring stale idle_prompt events from before the follow-up cannot
  re-trigger verification. Code matches commit message.

## Verdict per checkpoint

- **CP3a (step 5) — review-loop INPUT_REQUIRED for missing captures**: PASS.
  Real review-pane evidence; verdict + captures citation as expected.
- **CP3b (step 6) — captures added, captures-specific reason gone**: PASS.
  Reviewer still outputs INPUT_REQUIRED but for placeholder content / non-
  captures gaps, not missing captures. This matches the scenario's accepted
  failure mode.
- **CP4 (step 7) — qa_finalize close-out**: NOT EXERCISED end-to-end. Running
  the full `pm pr qa` loop on the fixture PR requires planner + multiple
  scenario panes, each with their own Claude session, plus verification panes
  — total wall time is multi-hour and exceeds this scenario's feasible budget.
  Code review of `_run_qa_finalize_pane` invocation at
  `pm_core/qa_loop.py:2926` confirms the call site and FINALIZE_DONE /
  FINALIZE_BLOCKED handoff to `state.finalize_verdict` is wired correctly.
- **CP5 (step 8) — duplicate-verifier guard**: PASS via code-level
  verification of commit e8fe399 (`pm_core/qa_loop.py:1996`). Live exercise
  requires the QA loop set up by CP4, which was not executed end-to-end here.

## Overall

CP3a/CP3b verified with runtime evidence; CP4/CP5 verified at code level
only. End-to-end exercise of CP4/CP5 was not feasible within this scenario's
time budget — same outcome as prior QA runs on this scenario per PR notes
(workdirs ending 6a87858569a89e07, cb4de4c7f7048cd2, 4b86c9cea69d568c,
ba760724d2c7b159).
