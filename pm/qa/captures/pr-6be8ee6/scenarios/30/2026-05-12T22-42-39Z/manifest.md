---
pr: pr-6be8ee6
workdir: /tmp/pm-test-1778625652
captured_at: 2026-05-12T22:43:00Z
---

## Commands

```
# Setup (see scenario steps 1-4)
python3 -m venv /tmp/pm-venv && source /tmp/pm-venv/bin/activate
pip install -e /workspace
export PYTHONPATH=/workspace
TEST_DIR=/tmp/pm-test-1778625652
cd "$TEST_DIR" && pm session 2>/dev/null || true

# Drive empty QA pane, picker modal, scaffold artifact, refresh, regression Enter
pm tui send q       # open QA pane (Instructions(0)/Regression Tests(0)/Artifact Recipes(0))
pm tui send a       # open QACreatePickerScreen
pm tui send picker-smoke
pm tui send Down (x5)   # select Artifact recipe (scaffold)
pm tui send Enter   # launches `pm qa add-artifact picker-smoke`; pm/qa/artifacts/picker-smoke.md created
pm tui send q; pm tui send q   # refresh: Artifact Recipes (1) → picker-smoke

# Regression: create via CLI, then Enter to launch regression prompt
EDITOR=true pm qa add-regression smoke-reg
pm tui send q; pm tui send q
pm tui send Enter   # launches Claude with build_regression_test_prompt

# Recording (recipe: tmux-screen-recording.md)
tmux pipe-pane -t "$TARGET:0.0" -o "cat >> .../transcript.log"
tmux new-session -d -s pm-recorder -x 200 -y 50 \
  "asciinema rec --quiet .../recording.cast -c 'tmux attach -t $TARGET'"
# (re-drove picker against the recorder pane with name 'capture-demo')
```

## What this demonstrates

QA pane renders three labeled sections at zero, the `a` picker modal
opens with a Name input + six-row kind list, Escape cancels, empty
submit is a no-op, and submit with name + selection launches
`pm qa <mode>-<suffix> <name>` in a new pane. After a refresh, the
pane shows the new item under its category and the status counter
sums all three sections. `Enter` on a regression row launches a
Claude pane with the regression prompt template (referencing
`pm/qa/captures/regression/<test-id>/<timestamp>/`).

Drove from outside via `pm tui send`; transcript captures the
control sequences seen by the canonical pm pane while the recorder
session (different tmux session, same server) wrote the asciinema
cast. Note: during the recording leg, an extra `q` toggle landed in
the tech-tree view and a stray Enter spawned a meta session — the
"hard, evidence-bearing" picker→scaffold→file-created chain was
already verified in the steps prior to recording, so this is noted
rather than reshot.

## Files

- `transcript.log` — raw ANSI scrollback of the canonical pm pane
  during the scenario (contains the "Create QA file" picker frames,
  the picker-smoke / capture-demo entries, and the Smoke Reg row).
- `recording.cast` — asciinema replay of the recorder session
  attached to the canonical pm session while the picker and
  refresh were driven.
