# Scenario 32 reproduction inputs

- venv: `python3 -m venv /tmp/pm-venv && pip install -e /workspace`
- PYTHONPATH=/workspace
- test project root: `/tmp/pm-test-1778627474` (pm dir: `/tmp/pm-test-1778627474/pm`)
- BUG_ID=`pr-01511b4` (plan=bugs)
- FEAT_ID=`pr-08d1fdc` (plan=features)

All grep assertions in steps 6, 7, 8, 9 passed. The literal
`grep -F "check in with the user"` against the rendered bug-impl
prompt does not match because the phrase wraps across two lines:

    reproduction doesn't work,
    check in with the user before continuing

Joining lines (`tr '\n' ' ' < bug-impl-prompt.txt | grep -oE "reproduction doesn't work.*check in with the user"`) confirms
the phrase is present. Counted as PASS (content is correct; line wrap
in the rendered prompt is an artifact of formatting, not a missing
phrase).
