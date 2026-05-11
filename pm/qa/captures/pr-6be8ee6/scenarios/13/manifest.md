# Scenario 13 — QA planner artifact block + parse_qa_plan + _install_artifact_files

## Summary

E2E pytest covering the four surfaces named in the scenario focus:

1. `generate_qa_planner_prompt` includes the "Artifact Recipes" guidance
   block and the `ARTIFACT:` SCENARIO-template line when
   `pm/qa/artifacts/` is non-empty (real repo library).
2. The same block is omitted when `pm/qa/artifacts/` is absent
   (isolated `tmp_path` with only `pm/qa/instructions/`).
3. `parse_qa_plan` correctly handles ARTIFACT values:
   - comma-separated valid recipes (both kept),
   - one valid + one bogus (bogus dropped, warning logged),
   - cross-category reference (`tui-manual-test.md` lives in
     `instructions/`, dropped because the resolver returns category
     `"instructions"` not `"artifacts"`, warning logged),
   - `none` short-circuit (empty `artifact_paths`, no warning).
4. `_install_artifact_files` copies each referenced recipe into
   `scratch_path/qa-artifacts/` and rewrites `scenario.artifact_paths`
   to absolute `{scratch_dir}/qa-artifacts/{file}` strings.
5. `generate_qa_child_prompt` renders the `## Artifact Capture Recipes`
   section (plural for >1 path), bullets each absolute path, includes
   the `pm/qa/captures/<pr_id>/scenarios/<n>/` save dir, and emits the
   `git add / commit / push` plus rebase-on-conflict lines.

## Result

`5 passed in 0.05s` — see `pytest.log` and the recorded run in
`run.cast`.

## Files

- `test_qa_artifact_e2e.py` — pytest file under test (also at
  `/tmp/test_qa_artifact_e2e.py` during the run).
- `pytest.log` — tee'd stdout of `pytest -xvs`.
- `run.cast` — asciinema recording of the same pytest invocation.
  Replay with `asciinema play run.cast`.
- `prompt.md` — the scenario prompt this run executed under
  (committed at scenario launch).

## Notes / quirks worth flagging

- `pm.qa_loop` logger has `propagate = False` (set by
  `pm_core.paths.configure_logger`), so pytest's `caplog` fixture
  cannot see its records via the root logger. The test attaches its
  own `logging.Handler` directly to the `pm.qa_loop` logger to capture
  the two expected warnings (bogus recipe + cross-category reference).
- `find_project_root` returns the `pm/` subdir, not the repo root, so
  the planner test patches it to `Path("/workspace/pm")`. Worth keeping
  in mind for any future tests that exercise prompt_gen against a
  fake project layout.
- The rebase-on-conflict line in the artifact block wraps a newline
  between `--rebase` and `origin` (the f-string lays the branch on the
  next line). Assertions accept that form rather than collapsing to a
  single line.
