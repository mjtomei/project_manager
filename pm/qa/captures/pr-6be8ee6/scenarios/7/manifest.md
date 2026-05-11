---
title: "QA scenario 7 — qa-finalize wiring + run_qa_sync suffix"
description: "Asciinema cast of scenario 7 runtime evidence: QALoopState.finalize_verdict default, build_qa_finalize_prompt content, _run_qa_finalize_pane None-paths, and run_qa_sync suffix wiring (source + isolated suffix-format test)."
pr: pr-6be8ee6
workdir: /workspace
captured_at: 2026-05-11
recipe: none (pure-Python scenario; cast generated via `asciinema rec --command`)
---

## What this demonstrates

The recording (`recording.cast`) runs the four scenario assertions back-to-back
under asciinema. Each step's stdout is visible in the cast:

1. **`QALoopState.finalize_verdict` defaults to `None`** —
   `python3 -c "...QALoopState(pr_id='pr-6be8ee6')..."` prints
   `finalize_verdict = None` and the `assert s.finalize_verdict is None`
   passes.

2. **`build_qa_finalize_prompt` content** — calling with the documented
   keyword-only signature (`pr_id, pr_title, branch, pr_workdir,
   scenario_worktrees, overall_verdict`; tuples are
   `(scenario_index, verdict, worktree_path)`) and the three scenarios
   `[(1,"PASS","/tmp/wt-1"), (2,"NEEDS_WORK","/tmp/wt-2"), (3,None,None)]`
   produces a prompt (`len = 1353`) that contains all expected needles:
   pr id, title, branch, workdir, per-scenario lines, `"(none)"` for the
   third row, `FINALIZE_DONE` / `FINALIZE_BLOCKED`, and the
   `"on its own line"` instruction. Calling with `scenario_worktrees=[]`
   yields `"(no scenarios ran)"`.

3. **`_run_qa_finalize_pane` None-paths** — both early returns produce
   `None`:
   - Falsy `workdir_path` (`""` and `None`) → `None` without touching tmux.
   - Real workdir but missing tmux session/window → `None`.

4. **`run_qa_sync` wiring (source + isolated suffix test)** —
   - `pm_core/qa_loop.py:2778` assigns `state.finalize_verdict =
     _run_qa_finalize_pane(...)` inside `try/except Exception:` that
     `_log.exception(...)`s and continues (lines 2776–2783).
   - `pm_core/qa_loop.py:2790–2794` builds `finalize_suffix` only when
     `state.finalize_verdict` is truthy, and weaves it into
     `state.latest_output = f"QA complete: {state.latest_verdict}{finalize_suffix} — ..."`.
   - The isolated reproduction sets `finalize_verdict = "DONE"` and asserts
     `"[finalize: DONE]"` appears in the composed message; with
     `finalize_verdict` left at `None` the suffix is absent. Both
     assertions pass.

Per spec §6, the full `run_qa_sync` end-to-end drive (live tmux session +
scenario windows + Claude session launches) is **not exercised**. Steps
2778/2790–2794 are confirmed by direct source inspection (visible in the
cast via `grep`/`sed` output) plus the isolated suffix-format test, which
together prove the wiring claims.

## Bugs filed

None — all assertions passed and no incidental issues observed.
