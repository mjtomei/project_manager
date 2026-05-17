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
     `VERIFIED`): bare keyword on its own line.
   - **Block verdicts** (`FLAGGED`, `REFINED_STEPS`, `QA_PLAN`): `_START` marker,
     body (default placeholder when omitted), `_END` marker — each on its own line.
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
   - Maps each `pm_core.model_config.SESSION_TYPES` entry to the verdicts valid
     for it (e.g. `review` → PASS/NEEDS_WORK/INPUT_REQUIRED;
     `qa_verification` → VERIFIED/FLAGGED; `qa_planning` → QA_PLAN; `impl`,
     `watcher`, `merge` → empty = no-verdict sessions).
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
   - One file per verdict (`pass.txt`, `needs_work.txt`, `input_required.txt`,
     `verified.txt`, `flagged.txt`, `refined_steps.txt`, `qa_plan.txt`); each
     contains the rendered output of the corresponding verdict for use in unit
     tests / golden comparisons. (`pass_with_suggestions.txt` was dropped with
     PR #166.)

8. **Tests — `tests/test_fake_claude.py`** covering:
   `_resolve_block_name`, single-line + block verdict output shape, no-verdict
   (`NONE`) output + `hold` semantics, preamble sizing & delay semantics,
   body-line batching, stream-mode equivalence, fixture content, integration
   with `loop_shared.match_verdict`, the `bin/fake-claude` executable
   (subprocess), config round-trip / validation, `_all` catch-all resolution,
   `_pick_fake_verdict` / `_fake_claude_args`, and launcher substitution under
   each entry point.

9. **No-verdict sessions & `hold` — staying open like a real session**
   - `impl`, `watcher`, `merge` (and any type matched only by `_all`) never
     emit a verdict. The fake writes preamble/body, then **does not exit** —
     a real interactive Claude session stays in its pane after a turn.
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
- `impl` / `watcher` / `merge` session types never emit verdicts — config
  validation rejects verdicts for them; launcher returns `None` so the real
  claude path is used.
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
