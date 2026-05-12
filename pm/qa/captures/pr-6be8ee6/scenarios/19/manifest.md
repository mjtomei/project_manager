---
pr: pr-6be8ee6
workdir: /workspace
captured_at: 2026-05-12
recipe: pm/qa/artifacts/cli-recording.md
---

## Commands

```
bash /tmp/qa19_replay.sh
```

The replay script (sourced into the recording) performs:

```
source /tmp/pm-venv/bin/activate
export PYTHONPATH=/workspace
pm which
TEST_DIR=/tmp/pm-test-replay-$$ ; mkdir -p $TEST_DIR ; cd $TEST_DIR
git init -q
pm init --backend local --no-import
pm pr add 'Bug demo' --plan bugs --description 'something is broken'
pm pr add 'Feature demo' --plan features --description 'add a thing'
# read BUG_ID / FEAT_ID from the store
python3 -c "from pm_core import store, prompt_gen
from pm_core.cli.helpers import state_root
data = store.load(state_root())
for pr in data['prs']:
    print('===', pr['id'], pr.get('plan'), '===')
    print(prompt_gen.generate_prompt(data, pr['id']))" > impl_prompts.txt
# Grep the bug PR section for the Bug Fix Flow heading, 5 step labels,
# both capture paths, the stash/parent-checkout phrasing, and the
# pm/qa/instructions / pm/qa/artifacts references.
# Grep the feature PR section for "Bug Fix Flow" -> expect 0.
# Generate review prompts for both PRs and inspect the
# Bug Fix Review Checklist section.
```

## What this demonstrates

End-to-end verification of QA scenario 19 against PR pr-6be8ee6:

- The bug PR's impl prompt contains a `## Bug Fix Flow` section with
  the five bolded step labels (Manual repro on pre-fix code, Write a
  failing test, Fix, Verify with the test, Verify manually), and both
  `pm/qa/captures/<BUG_ID>/impl/pre-fix/` and `.../post-fix/` paths
  with the BUG_ID interpolated.
- Step 1 mentions stashing uncommitted changes / checking out the
  parent commit (for already-committed fixes) and references both
  `pm/qa/instructions/` (env-setup recipes) and `pm/qa/artifacts/`
  (capture recipes).
- The feature PR's impl prompt has zero occurrences of "Bug Fix Flow".
- The bug PR's review prompt has a `## Bug Fix Review Checklist`
  section that references `pm/qa/captures/<BUG_ID>/impl/`, uses
  `INPUT_REQUIRED` for missing captures, and contains no `NEEDS_WORK`
  inside that section.
- The feature PR's review prompt has no Bug Fix Review Checklist
  section.

The PR-id interpolation in the captured recording shows `pr-43bf914`
(the local id assigned to the throwaway "Bug demo" PR), which is the
expected behavior — the impl prompt uses the local PR id, not the
PR-6be8ee6 id of the PR being reviewed.

## Files

- `recording.cast` — asciinema replay of the full verification script
  (`asciinema play recording.cast`).
- `transcript.log` — plain-text capture of stdout+stderr from the
  same run; load-bearing artifact for grep/diff.
- `manifest.md` — this file.
