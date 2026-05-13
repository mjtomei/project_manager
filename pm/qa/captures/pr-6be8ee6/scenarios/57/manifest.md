---
pr: pr-6be8ee6
scenario: 57
workdir: /workspace
captured_at: 2026-05-13
recipe: pm/qa/artifacts/cli-recording.md
---

## What this demonstrates

End-to-end bug-fix flow over a throwaway pm test project at
`/scratch/pm-test-1778707340`, with a freshly created `plan: bugs` PR
(`pr-9279294: Fix off-by-one in last_index`).

### Triple 1 — bug-fix impl flow (PASS)

Followed the 5 steps printed by `pm prompt pr-9279294`:

1. Reproduced the bug on pre-fix code by running a small Python repro via
   asciinema (cli-recording.md recipe). Capture saved under
   `pm/qa/captures/pr-9279294/impl/pre-fix/` in the test project; copies are
   under `pre-fix/` here.
2. Wrote a failing pytest (`test_helper.py`) that asserts the in-bounds
   result; it fails on the pre-fix commit (asserts `3 == 2`).
3. Committed the one-line fix (`return len(xs) - 1`).
4. Re-ran the test on the fix commit — passes.
5. Re-ran the same repro asciinema on the fixed code. Capture under
   `post-fix/`.

Pre/post-fix transcripts demonstrate the symptom (returns `3`, IndexError
marker printed) flipping to the fixed behavior (returns `2`, `xs[2] == 30`).

### Triple 2 — TUI QA-loop integration (INPUT_REQUIRED)

Launched `pm tui` inside the test session (grouped tmux session `~1`),
focused the new PR, and triggered `fresh_start_qa` (`z t`). The TUI spawned:

- `qa-pr-9279294` (planner pane)
- `qa-pr-9279294-s0` (interactive scenario pane)

The planner ran, produced a `QA_PLAN_END`-terminated plan with 4 scenarios
(reproduction, adjacent sizes, bundled test run, empty-list edge case), and
saved it to `pm/specs/pr-9279294/qa.md`. After triggering `zz t` to start
the QA loop, the TUI status reported:

  QA INPUT_REQUIRED for pr-9279294 — paused for human input

The planner's response contained an env-level concern ("remote push was
rejected by the workdir's push-proxy policy") that the loop interpreted as
INPUT_REQUIRED, so no scenarios beyond s-0 were spawned and no
`pm/qa/captures/<pr-id>/scenarios/<n>/` directory was produced inside the
qa workdir. The throwaway test project has no git remote, so the workdir
push always fails — the gating behavior is environment-dependent.

The captured `tui-pane.log`, `planner-pane.log`, and `scenario-s0-pane.log`
show the panes at the time the verdict was decided.

## Files

- `pre-fix/recording.cast` — asciinema of the repro on the buggy commit.
- `pre-fix/transcript.log` — plain-text version of the same run.
- `pre-fix/manifest.md` — original capture manifest from the test project.
- `post-fix/recording.cast` — asciinema of the repro on the fix commit.
- `post-fix/transcript.log` — plain-text version of the same run.
- `post-fix/manifest.md` — original capture manifest.
- `tui-pane.log` — pm tui main pane at end of run (QA INPUT_REQUIRED).
- `planner-pane.log` — QA planner pane (plan produced, then idle).
- `scenario-s0-pane.log` — interactive scenario pane.
- `prompt.md` — original scenario prompt.

## Notes

The triple-1 PASS is the load-bearing observation that the bug-fix prompt
flow + the new `pm/qa/captures/<pr-id>/impl/{pre-fix,post-fix}/` layout work
end-to-end against a real PR.

Triple-2 is blocked by the QA-loop's INPUT_REQUIRED gating in the
no-remote environment. Prior scenarios on this PR (scenarios 50, 51, etc.
per the activity log) have hit the same gate.
