---
pr: pr-6be8ee6
workdir: /workspace
captured_at: 2026-05-11
recipe: pm/qa/artifacts/cli-recording.md
---

## Commands

```
python -m pytest tests/test_qa_finalize_wiring.py -v
```

## What this demonstrates

Scenario 14 exercises the QA finalize wiring landed in this PR:
`QALoopState.finalize_verdict` default, `build_qa_finalize_prompt`
content (all input fields plus both `FINALIZE_DONE` / `FINALIZE_BLOCKED`
verdict tokens rendered as list items, empty-scenario and None-field
rendering paths), and `_run_qa_finalize_pane`'s three None-return
paths (missing workdir, missing tmux window, unverified PASS gate).
Test (h) and (i) verify the `run_qa_sync` wiring of
`state.finalize_verdict` and the `[finalize: …]` suffix in
`state.latest_output` — see manifest notes below for why these two
are textual-assertion fallbacks rather than full integration tests.

All 9 tests pass.

## Sub-test fidelity

- (a)-(g): direct unit tests, no monkeypatching beyond
  `tmux.find_window_by_name` in (f). Drive the real code under test.
- (h) `test_run_qa_sync_finalize_suffix_in_latest_output`: **textual
  assertion fallback**. A full integration would require monkeypatching
  >12 helpers (store/load, get_pm_session, `_launch_scenarios_*`,
  `_poll_tmux_verdicts`, `_persist_scenario_verdicts`, `_write_status_file`,
  `create_qa_workdir`, `_get_qa_spec`, both tmux helpers, plus state
  pre-population) and still touches paths that can't be cleanly patched.
  The fallback reads `pm_core/qa_loop.py` lines 2908-2927 and asserts
  the slice contains `state.finalize_verdict = _run_qa_finalize_pane(`,
  the `f" [finalize: {state.finalize_verdict}]"` f-string, and the
  `if state.finalize_verdict:` guard.
- (i) `test_run_qa_sync_swallows_finalize_exception`: **textual
  assertion fallback** for the same reason. Asserts the
  `try / _run_qa_finalize_pane / except Exception / _log.exception`
  block exists at lines 2903-2914.

## Files

- `recording.cast` — asciinema replay of the pytest run (captured via
  the tmux scaffold no-TTY workaround from the cli-recording recipe).
- `transcript.log` — plain-text pytest output for grep / diff.
- `manifest.md` — this file.
