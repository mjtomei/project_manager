---
pr: pr-6be8ee6
recipe: pm/qa/artifacts/cli-recording.md
workdir: /workspace
test_project: /workspace/pm-test-1778627512
captured_at: 2026-05-12T23:21:10+00:00
title: Scenario 35 — end-to-end bug-fix flow + QA scenario integration
description: Drive a tiny bug PR through the 5-step bug-fix flow (CP1) and a pm qa run scenario (CP2); verify the new pm/qa/captures/<pr-id>/{impl,scenarios}/ layout populates.
---

## Commands

```
# Setup
python3 -m venv /tmp/pm-venv && source /tmp/pm-venv/bin/activate
pip install -e /workspace
export PYTHONPATH=/workspace
pm which  # -> /workspace/pm_core ✓

TEST_DIR=/workspace/pm-test-$(date +%s)  # /workspace/pm-test-1778627512
mkdir -p $TEST_DIR && cd $TEST_DIR && git init -q

# Buggy module + commit
cat > buggy.py <<PY
def last_index(xs):
    return len(xs)  # off-by-one
PY
git add buggy.py && git commit -m "introduce buggy.py with off-by-one"

# Bug PR
pm init --backend local --no-import
pm pr add "Fix last_index off-by-one" --plan bugs  # -> pr-4724910
python3 -c "from pm_core.bug_fix_prompts import _is_bug_pr,_bug_fix_flow_block; \
  pr={'id':'pr-4724910','plan':'bugs'}; assert _is_bug_pr(pr); print(_bug_fix_flow_block(pr))"
# Confirmed: 5-step block emitted, pm/qa/captures/pr-4724910/impl/{pre-fix,post-fix} interpolated.

pm session  # creates pm tmux session in test dir

# CP1 — bug-fix flow steps
# Step 1: pre-fix repro + capture
CAPDIR_PRE=$TEST_DIR/pm/qa/captures/pr-4724910/impl/pre-fix
tmux -L scaffold new-session -d -s rec
tmux -L scaffold send-keys -t rec:0.0 \
  "cd $TEST_DIR && asciinema rec --quiet --overwrite $CAPDIR_PRE/recording.cast \
    -c 'bash -c \"set -x; cd $TEST_DIR; PYTHONPATH=$TEST_DIR python3 /tmp/repro.py\"' \
   |& tee $CAPDIR_PRE/transcript.log" Enter
# Result: pre-fix repro shows IndexError (last_index returns 3, xs[3] OOB)
# Wrote manifest.md per cli-recording.md template.

# Step 2: failing test
cat > test_buggy.py <<PY
from buggy import last_index
def test_last_index_returns_final_index():
    assert last_index([10,20,30]) == 2
PY
PYTHONPATH=$TEST_DIR python3 -m pytest test_buggy.py -x
# Output: FAILED test_buggy.py::test_last_index_returns_final_index - assert 3 == 2 ✓

# Step 3: fix + commit
sed -i 's/return len(xs)/return len(xs) - 1/' buggy.py
git add buggy.py test_buggy.py && git commit -m "fix off-by-one in last_index + test"

# Step 4: verify with test
PYTHONPATH=$TEST_DIR python3 -m pytest test_buggy.py -v
# Output: PASSED ✓

# Step 5: post-fix capture (asciinema, same /tmp/repro.py, into impl/post-fix/)
# Result: last_index([10,20,30]) = 2; xs[last_index(xs)] = 30, no IndexError ✓

# CP2 — QA scenario via pm qa run
EDITOR=true pm qa add-instruction my-test  # scaffold (no claude needed)
# pm pr spec pr-4724910 qa  failed: "Credit balance is too low"
# WORKAROUND: wrote pm/specs/pr-4724910/qa.md manually + EDITOR=true pm pr spec-approve pr-4724910
# In cmdshell window of pm session:
pm qa run my-test --pr pr-4724910
```

## What this demonstrates

Per pm/specs/pr-6be8ee6/qa.md §"End-to-end QA + bug-fix flow integration":

**Checkpoint 1** — bug-fix flow against a real, deterministic bug PR
produces pre-fix and post-fix captures under
`pm/qa/captures/pr-4724910/impl/{pre-fix,post-fix}/`. Each capture dir
contains manifest.md + recording.cast + transcript.log per the
cli-recording.md recipe.

**Checkpoint 2** — `pm qa run <instruction> --pr <pr>` drives a QA scenario
that lands captures under `pm/qa/captures/pr-4724910/scenarios/<n>/`,
specifically via `_write_scenario_capture_file` in
pm_core/qa_loop.py:1111-1130.

## Findings

### Checkpoint 1 — PASS

```
$ ls /workspace/pm-test-1778627512/pm/qa/captures/pr-4724910/impl/pre-fix/
manifest.md  recording.cast  transcript.log
$ ls /workspace/pm-test-1778627512/pm/qa/captures/pr-4724910/impl/post-fix/
manifest.md  recording.cast  transcript.log
$ grep -E "^recipe:|^pr:" .../impl/pre-fix/manifest.md
pr: pr-4724910
recipe: pm/qa/artifacts/cli-recording.md
$ grep -E "^recipe:|^pr:" .../impl/post-fix/manifest.md
pr: pr-4724910
recipe: pm/qa/artifacts/cli-recording.md
```

- pre-fix transcript shows the deterministic IndexError (line "+ python3 /tmp/repro.py" then "IndexError: list index out of range"). ✓
- post-fix transcript shows "last_index([10,20,30]) = 2" / "xs[last_index(xs)] = 30" — symptom gone. ✓
- Manifest `## Files

- manifest.md
- prompt.md
- recording.cast
- throwaway-captures/pr-4724910/impl/post-fix/manifest.md
- throwaway-captures/pr-4724910/impl/post-fix/recording.cast
- throwaway-captures/pr-4724910/impl/post-fix/transcript.log
- throwaway-captures/pr-4724910/impl/pre-fix/manifest.md
- throwaway-captures/pr-4724910/impl/pre-fix/recording.cast
- throwaway-captures/pr-4724910/impl/pre-fix/transcript.log
- throwaway-captures/pr-4724910/scenarios/1/prompt.md
- transcript.log

**Verdict: INPUT_REQUIRED**

Reason: Checkpoint 1 = PASS (impl/{pre-fix,post-fix} each contain manifest.md + recording.cast + transcript.log; manifests carry pr: and recipe: fields; transcripts show IndexError pre-fix and `last_index([10,20,30]) = 2` post-fix). Checkpoint 2 = FAIL as written: throwaway-project workdir's `pm/qa/captures/pr-4724910/scenarios/` dir was never created, and the inner QA scenario clone's scenarios/1/ dir contains only prompt.md (no manifest/recording/transcript). I could not unblock CP2 without separate fixes: (a) `pm pr spec ... qa` failed with 'Credit balance is too low' (worked around by writing qa.md manually); (b) the QA worker stalled mid-execution after refining steps — qa_loop typed 'run the tests' into the worker's input box but it was never submitted, verdict stayed empty, captures were never pushed back. Possibly related to the duplicate-verification fix area but I did not isolate it within this scenario. Flagging for human judgment.
