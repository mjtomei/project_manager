# Spec: FakeClaudeSession (pr-abcf70f)

A scriptable Claude replacement for integration testing — emits realistic-looking
output then a chosen verdict, letting tests exercise verdict detection, review/QA
loop state machines, and verification transitions without real API calls.

## Requirements (grounded)

1. **Core engine — `pm_core/fake_claude.py`**
   - `run_fake_claude(verdict, preamble, preamble_delay, delay, body, body_lines,
     body_batch, body_delay, stream, char_delay)` writes to stdout in the order:
     preamble lines → generated body lines (batched, with inter-batch delay) →
     pre-verdict sleep → verdict block.
   - **Single-line verdicts** (`PASS`, `PASS_WITH_SUGGESTIONS`, `NEEDS_WORK`,
     `INPUT_REQUIRED`, `VERIFIED`): bare keyword on its own line.
   - **Block verdicts** (`FLAGGED`, `REFINED_STEPS`, `QA_PLAN`): `_START` marker,
     body (default placeholder when omitted), `_END` marker — each on its own line.
   - `--verdict` accepts the short name (`FLAGGED`) or the bare end marker
     (`FLAGGED_END`); both resolve to the same block via `_resolve_block_name`.
   - Output must be detectable by `pm_core.loop_shared.extract_verdict_from_content`
     with the keyword sets used by review/qa loops.

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
     for it (e.g. `review` → PASS/PASS_WITH_SUGGESTIONS/NEEDS_WORK/INPUT_REQUIRED;
     `qa_verification` → VERIFIED/FLAGGED; `qa_planning` → QA_PLAN; `impl`,
     `watcher`, `merge` → empty).
   - `validate_session_verdicts(session_type, verdicts)` returns error-string
     list (empty = valid).

5. **Session-file override — `pm_core/paths.py`**
   - `fake_claude_config(tag)` reads `<sessions_dir>/<tag>/fake-claude` JSON.
   - `set_fake_claude_config(tag, cfg)` validates per-type verdicts before writing,
     raises `ValueError` on invalid verdict / unknown session type.
   - `clear_fake_claude(tag)` removes the file.
   - `fake_claude_config_for_type(session_type, tag)` merges `_defaults`,
     per-type overrides, and propagates top-level `binary`. Returns `None` if
     `session_type` absent or no file. `_defaults` and `binary` keys are not
     validated as session types.

6. **Launcher integration — `pm_core/claude_launcher.py`**
   - `_pick_fake_verdict(verdicts)` does weighted random selection from the
     verdict→weight dict.
   - `_fake_claude_args(cfg)` builds the CLI args (verdict, preamble, delay,
     body_lines, …).
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
   - One file per verdict (`pass.txt`, `pass_with_suggestions.txt`,
     `needs_work.txt`, `input_required.txt`, `verified.txt`, `flagged.txt`,
     `refined_steps.txt`, `qa_plan.txt`); each contains the rendered output of
     the corresponding verdict for use in unit tests / golden comparisons.

8. **Tests — `tests/test_fake_claude.py`** covering:
   `_resolve_block_name`, single-line + block verdict output shape, preamble
   sizing & delay semantics, body-line batching, stream-mode equivalence,
   fixture content, integration with `extract_verdict_from_content`, the
   `bin/fake-claude` executable (subprocess), config round-trip / validation,
   `_pick_fake_verdict` / `_fake_claude_args`, and launcher substitution under
   each entry point.

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
- **PR #166 conflict (PASS_WITH_SUGGESTIONS removal):** This branch is 547
  commits behind master; #166 dropped `PASS_WITH_SUGGESTIONS` from the review
  verdict surface. On rebase, expect conflicts in `SESSION_TYPE_VERDICTS["review"]`,
  `SINGLE_LINE_VERDICTS`, `ALL_VERDICTS`, the fixture file
  `pass_with_suggestions.txt`, and the parametrized tests referencing it. Drop
  PASS_WITH_SUGGESTIONS during the rebase. (Tracked, not pre-resolved here.)
