# Spec: FakeClaudeSession (pr-abcf70f)

A scriptable Claude replacement for integration testing — emits realistic-looking
output then a chosen verdict, letting tests exercise verdict detection, review/QA
loop state machines, and verification transitions without real API calls.

## Requirements (grounded)

1. **Core engine — `pm_core/fake_claude.py`**
   - `run_fake_claude(verdict, preamble, preamble_delay, delay, body, body_lines,
     body_batch, body_delay, stream, char_delay, hold)` writes to stdout in the
     order: preamble lines → generated body lines (batched, with inter-batch
     delay) → pre-verdict sleep → verdict block.
   - **Single-line verdicts** (`PASS`, `NEEDS_WORK`, `INPUT_REQUIRED`,
     `VERIFIED`, `READY`, `FINALIZE_DONE`, `FINALIZE_BLOCKED`): bare keyword on
     its own line.
   - **Block verdicts** (`FLAGGED`, `REFINED_STEPS`, `REFINER_REJECT`,
     `QA_PLAN`): `_START` marker, body (default placeholder when omitted),
     `_END` marker — each on its own line.
   - **No-verdict sessions** (`verdict` is `None` or `"NONE"`): emit preamble/body
     but no verdict block, then stay open per `hold` (see requirement 9) — models
     `impl`/`watcher`/`merge` interactive sessions.
   - `--verdict` accepts the short name (`FLAGGED`) or the bare end marker
     (`FLAGGED_END`); both resolve to the same block via `_resolve_block_name`.
   - Output must be detectable by `pm_core.loop_shared.match_verdict` (scanned
     line-by-line) with the keyword sets used by review/qa loops.

2. **CLI — `pm fake-claude`** (`pm_core/cli/fake_claude.py`)
   - Click command exposing all engine parameters; `--verdict` required, all
     others have sensible defaults matching the engine signature.

3. **Standalone executable — `bin/fake-claude`**
   - `argparse`-based, executable bit set, shebang `python3`.
   - Uses `parse_known_args` so Claude-specific flags (`--resume`, `--session-id`,
     `--model`, `--dangerously-skip-permissions`, `-p`, positional prompt) are
     silently ignored when invoked as a drop-in claude replacement.
   - `--verdict` optional with default `PASS` so the launcher can invoke without
     extra args.

4. **Per-session-type verdict catalogue** (`SESSION_TYPE_VERDICTS`)
   - Maps each verdict-emitting session to its actual verdict set. Audited
     against every verdict-extraction site (per the PR's forward-looking
     refactor request):
     - `review` → PASS/NEEDS_WORK/INPUT_REQUIRED
     - `qa_scenario` (worker) → PASS/NEEDS_WORK/INPUT_REQUIRED
     - `qa_concretize` (refiner) → REFINED_STEPS/REFINER_REJECT
     - `qa_verification` → VERIFIED/FLAGGED
     - `qa_planning` → QA_PLAN
     - `qa_finalize` → FINALIZE_DONE/FINALIZE_BLOCKED
     - `watcher` → READY/INPUT_REQUIRED
     - `impl`, `merge` → empty = no-verdict (interactive) sessions
   - Keys are **not** limited to `model_config.SESSION_TYPES`: `qa_concretize`
     and `qa_finalize` are QA-loop sub-steps with their own verdict surface, so
     they get their own fake-claude session type even though they share model
     resolution with the QA loop. `SESSION_TYPES ⊆ SESSION_TYPE_VERDICTS` still
     holds (the test checks one direction only).
   - `validate_session_verdicts(session_type, verdicts)` returns error-string
     list (empty = valid).

5. **Session-file override — `pm_core/paths.py`**
   - `fake_claude_config(tag)` reads `<sessions_dir>/<tag>/fake-claude` JSON.
   - `set_fake_claude_config(tag, cfg)` validates per-type verdicts before writing,
     raises `ValueError` on invalid verdict / unknown session type / `verdicts`
     placed inside the `_all` catch-all.
   - `clear_fake_claude(tag)` removes the file.
   - `fake_claude_config_for_type(session_type, tag)` merges `_defaults`,
     per-type overrides, and propagates top-level `binary`. `_defaults`,
     `binary`, and `_all` keys are not validated as session types.
   - **`_all` catch-all ("fake everything"):** when the config has an `_all`
     key, any session type without its own entry — and any call with
     `session_type=None` — falls back to `_all`, always treated as a
     **no-verdict** session (its `verdicts`, if any, are stripped/rejected).
     Explicit per-type entries still win. Without `_all`, an absent type or
     `None` session_type still returns `None` (real claude).

6. **Launcher integration — `pm_core/claude_launcher.py`**
   - `_pick_fake_verdict(verdicts)` does weighted random selection from the
     verdict→weight dict.
   - `_fake_claude_args(cfg)` builds the CLI args (verdict, preamble, delay,
     body_lines, `hold`, …). A config with empty/absent `verdicts` emits
     `--verdict NONE` (no-verdict session).
   - `watcher` and `impl` launch sites pass `session_type=` so they can be
     faked individually; `merge` already does. `_all` mode additionally fakes
     untyped/unlisted launches without needing each call site threaded.
   - **QA call sites pass `session_tag=state.session_tag`.** The QA
     orchestrator's cwd may be a QA workdir, so `build_claude_shell_cmd`'s
     cwd-derived `get_session_tag()` fallback would drift. `QALoopState.session_tag`
     (captured once from the tmux session name) is the authoritative,
     drift-proof tag, and is the dir pm's other per-session files live under.
     All six QA `build_claude_shell_cmd` calls thread it (concretize, scenario,
     scenario-0, verification, planning, finalize); `_build_concretize_cmd` and
     `_verify_single_scenario` gained a `session_tag` parameter to carry it.
   - QA call sites also pass the correct `session_type`: the refiner is
     `qa_concretize` (not `qa_scenario` — different verdict surface) and the
     finalize pane is `qa_finalize`.
   - `_fake_claude_config_for_type(session_type)` thin wrapper around
     `paths.fake_claude_config_for_type`.
   - `build_claude_shell_cmd(prompt, session_type=…)`: when fake config exists
     for the session type, returns a command invoking the fake binary directly
     (early-return; no real-claude wrapping). Otherwise unchanged.
   - `launch_claude`, `launch_claude_print`, `launch_claude_print_background`:
     when fake config exists, substitute the fake binary path; **must not raise
     `FileNotFoundError`** when `find_claude()` returns None but fake is
     configured (real claude not required).
   - `find_claude()` itself does not consult fake config — session_type is the
     trigger.

7. **Companion fixtures — `tests/fixtures/fake_claude/*.txt`**
   - One file per verdict — `pass.txt`, `needs_work.txt`, `input_required.txt`,
     `verified.txt`, `ready.txt`, `finalize_done.txt`, `finalize_blocked.txt`,
     `flagged.txt`, `refined_steps.txt`, `refiner_reject.txt`, `qa_plan.txt` —
     each containing the rendered output of the corresponding verdict for use
     in unit tests / golden comparisons. (`pass_with_suggestions.txt` was
     dropped with PR #166.)

8. **Tests — `tests/test_fake_claude.py`** covering:
   `_resolve_block_name`, single-line + block verdict output shape, no-verdict
   (`NONE`) output + `hold` semantics, preamble sizing & delay semantics,
   body-line batching, stream-mode equivalence, fixture content, integration
   with `loop_shared.match_verdict`, the `bin/fake-claude` executable
   (subprocess), config round-trip / validation, `_all` catch-all resolution,
   `_pick_fake_verdict` / `_fake_claude_args`, and launcher substitution under
   each entry point.

9. **No-verdict sessions & `hold` — staying open like a real session**
   - `impl`, `merge` (and any type matched only by `_all`) never emit a
     verdict. The fake writes preamble/body, then **does not exit** — a real
     interactive Claude session stays in its pane after a turn.
   - `run_fake_claude(hold=…)` / `--hold SECONDS`:
     - omitted (`None`) — block on stdin until EOF (the pane's tty closing
       when the window is killed). Default for live tmux launches.
     - `>= 0` — sleep that many seconds then exit (bounded form for tests;
       `0` exits immediately).
   - `hold` is ignored for verdict sessions (they exit after the verdict, as
     before).

## Implicit Requirements

- Preamble cycles through a fixed pool when `preamble > pool size` — no
  IndexError.
- `preamble_delay`/`body_delay` produce `len-1` sleeps (no sleep after last
  line/batch).
- Stream mode produces identical text to non-stream — only timing differs.
- Default-body for block verdicts must contain the keyword the detector keys on
  (e.g. "FAILED" for FLAGGED) so a tester who supplies no `--body` still gets
  realistic content.
- `bin/fake-claude` must be runnable from a checkout without installing the
  package — it inserts the repo root onto `sys.path`.

## Ambiguities (resolved)

- **What does "VERIFIED" count as?** Treated as a single-line verdict (matches
  `qa_verification`'s pass keyword), with `FLAGGED_END` as its block-style
  counterpart. Consistent with the QA verification loop's keyword set.
- **`--verdict` required on the CLI?** Required for `pm fake-claude` (Click);
  optional with default `PASS` on the standalone `bin/fake-claude` so it can be
  invoked as a drop-in claude replacement with no arguments.
- **Where does the binary path come from?** Default is `bin/fake-claude` in the
  repo (`_FAKE_CLAUDE_BIN`); a per-tag config can override via the top-level
  `binary` key.

## Edge Cases / Interactions

- Real claude not on PATH but fake is configured: launcher entry points must
  not raise (commits e8eae36, 449edb4, 44fe695 already address this).
- `impl` / `merge` session types never emit verdicts — config validation
  rejects verdicts for them. When no fake config matches, the launcher returns
  `None` so the real claude path is used.
- **PR #166 conflict (PASS_WITH_SUGGESTIONS removal):** RESOLVED. master was
  merged into the branch (merge commit fc3fde8). #166's removal of
  `PASS_WITH_SUGGESTIONS` was applied: dropped from `SINGLE_LINE_VERDICTS`,
  `SESSION_TYPE_VERDICTS["review"]` (now `PASS`/`NEEDS_WORK`/`INPUT_REQUIRED`),
  the `pm fake-claude` CLI docstring, the `pass_with_suggestions.txt` fixture
  (deleted), and the parametrized tests. The fake-claude files themselves did
  not conflict (new on this branch); merge conflicts were limited to
  `cli/__init__.py`, `cli/pr.py`, and `qa_loop.py` — all from master's
  unrelated refactors, resolved by threading `session_type=` into master's
  rewritten launch paths.
- **`loop_shared.extract_verdict_from_content` removed on master:** the
  verdict-detection tests now scan content line-by-line via
  `loop_shared.match_verdict`, matching how production detection works.

## Scope extensions beyond the original plan

These were added during review discussion; they go past the initial PR
description but are needed for FakeClaudeSession to faithfully model production.

1. **No-verdict mock mode + `_all` "fake everything".** The original plan
   covered only verdict-emitting sessions. Added: `verdict=None`/`"NONE"`
   no-verdict mode that stays open (`hold`), and the `_all` catch-all config
   key so untyped/unlisted launches are faked too (requirements 9 and 5).

2. **Full verdict-surface audit.** Per the PR's forward-looking refactor
   request, every verdict-extraction site was audited. Three drift gaps were
   closed: `watcher` (emits READY/INPUT_REQUIRED — was registered as
   no-verdict), `qa_concretize` (refiner emits REFINED_STEPS/REFINER_REJECT —
   was mis-typed as `qa_scenario`), `qa_finalize` (emits
   FINALIZE_DONE/FINALIZE_BLOCKED — had no session type). New verdicts added
   to the fake catalogue accordingly (requirement 4).

3. **`qa_concretize` / `qa_finalize` promoted to first-class session types.**
   Added to `model_config.SESSION_TYPES` and `_FALLBACK_TYPES` (→ `qa`), so
   the step refiner and finalize pane are **independently model-targetable**
   via `project.yaml` `model_config.session_models` / `session_effort` and
   `pm model set`. `_build_concretize_cmd` resolves with `qa_concretize`;
   `_run_qa_finalize_pane` gained a `project_data` parameter and now resolves
   a model with `qa_finalize` (previously used the CLI default). `cli/model.py`
   no longer hard-codes its own session-type list — it derives from
   `model_config.SESSION_TYPES`.

4. **`model_config` validation.** `validate_model_config(project_data)` checks
   that `session_models` / `session_effort` keys are known session types and
   that effort values are valid. `resolve_model_and_provider` silently ignores
   unknown keys, so a typo'd session type would otherwise never take effect;
   `pm model show` now surfaces these problems as warnings.

5. **`session_tag` threading for QA.** All six QA `build_claude_shell_cmd`
   call sites pass `session_tag=state.session_tag` (the drift-proof
   tmux-derived tag) instead of relying on `build_claude_shell_cmd`'s
   cwd-based `get_session_tag()` fallback, which drifts when the QA
   orchestrator's cwd is a QA workdir.
