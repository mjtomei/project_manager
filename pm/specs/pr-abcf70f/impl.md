# Spec: FakeClaudeSession (pr-abcf70f)

A scriptable Claude replacement for integration testing — emits realistic-looking
output then a chosen verdict, letting tests exercise verdict detection, review/QA
loop state machines, and verification transitions without real API calls.

## Requirements (grounded)

1. **Core engine — `pm_core/fake_claude.py`**
   - `run_fake_claude(verdict, preamble, preamble_delay, delay, body, body_lines,
     body_batch, body_delay, stream, char_delay, hold, session_id)` writes to
     stdout in the order: preamble lines → generated body lines (batched, with
     inter-batch delay) → pre-verdict sleep → verdict block.
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
   - **Transcript + hook emission (requirement 10).** When `session_id` is
     given the engine also writes a Claude-format JSONL transcript and emits
     the `idle_prompt` hook event — the inputs production verdict detection
     actually reads (see requirement 10). Without a `session_id` it only
     writes to stdout.
   - The stdout verdict text must be detectable by
     `pm_core.loop_shared.match_verdict` (scanned line-by-line) — used by the
     watcher loops and `parse_review_verdict`, which operate on the
     transcript-derived assistant text.

2. **CLI — `pm fake-claude`** (`pm_core/cli/fake_claude.py`)
   - Click command exposing all engine parameters; `--verdict` required, all
     others have sensible defaults matching the engine signature.

3. **Standalone executable — `bin/fake-claude`**
   - `argparse`-based, executable bit set, shebang `python3`.
   - Uses `parse_known_args` so Claude-specific flags (`--resume`, `--model`,
     `--dangerously-skip-permissions`, `-p`, positional prompt) are silently
     ignored when invoked as a drop-in claude replacement. `--session-id` is a
     *recognised* flag (requirement 10) — the fake uses it to write the
     transcript and emit the hook event.
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
   - Also registers no-verdict (empty) entries for the non-loop interactive
     sessions — `plan`, `meta`, `guide`, `cluster`, `container`, `qa_author`,
     `qa_regression`, `discuss`, `watcher_review` — so they too can be faked
     selectively (see scope extension 6).
   - Every `model_config.SESSION_TYPES` entry appears here; the non-loop keys
     above are fake-claude-only (not model-targetable). The
     `SESSION_TYPES ⊆ SESSION_TYPE_VERDICTS` invariant holds.
   - `validate_session_verdicts(session_type, verdicts)` returns error-string
     list (empty = valid).

5. **Session-file override — `pm_core/paths.py`**
   - `fake_claude_config(tag)` reads `<sessions_dir>/<tag>/fake-claude` JSON.
   - `set_fake_claude_config(tag, cfg)` validates per-type verdicts before writing,
     raises `ValueError` on invalid verdict / unknown session type / `verdicts`
     placed inside the `_all` catch-all.
   - `clear_fake_claude(tag)` removes the file.
   - `fake_claude_config_for_type(session_type, tag)` merges `_defaults` with
     the per-type overrides. `_defaults` and `_all` keys are not validated as
     session types.
   - **`_all` catch-all ("fake everything"):** when the config has an `_all`
     key, any session type without its own entry — and any call with
     `session_type=None` — falls back to `_all`, always treated as a
     **no-verdict** session (its `verdicts`, if any, are stripped/rejected).
     Explicit per-type entries still win. Without `_all`, an absent type or
     `None` session_type still returns `None` (real claude).

6. **Launcher integration — `pm_core/claude_launcher.py`**
   - `_pick_fake_verdict(verdicts)` does weighted random selection from the
     verdict→weight dict.
   - **Scripted verdict sequences (per note-530ac2e).** The `verdicts` field
     is polymorphic: a dict (no `"sequence"` key) is weighted-random as before;
     a list, or a dict with a `"sequence"` list, is a scripted sequence used
     to drive multi-iteration loop scenarios (e.g. `NEEDS_WORK` on iter 1,
     `PASS` on iter 2). Scripted entries are bare verdict strings or dicts
     `{"verdict": "...", "body": "...", ...}` whose extra keys layer as
     per-iteration overrides on top of the type's base config. End-of-sequence
     clamps to the terminal entry by default (so the loop still completes);
     wrap is opt-in via `{"sequence": [...], "wrap": true}`. The cursor lives
     in a sidecar `<session_dir>/fake-claude.state` (`{"review": 1, ...}`),
     advanced atomically under `fcntl.flock` so concurrent panes of the same
     session-type do not both grab slot 0. `_advance_scripted_cursor` handles
     the file IO; `_resolve_fake_verdict` selects the form. `validate_session_verdicts`
     accepts all three shapes — the same error surface guards
     `set_fake_claude_config` for scripted configs. `peek_fake_verdicts(tag)`
     is a library helper that reports the next verdict each session-type
     would emit without advancing cursors.
   - `_fake_claude_args(cfg, session_type=, session_tag=)` builds the CLI
     args (verdict, preamble, delay, body_lines, `hold`, …). A config with
     empty/absent `verdicts` emits `--verdict NONE` (no-verdict session). All
     four launcher call sites pass `session_type` (and `session_tag` where
     available — `build_claude_shell_cmd`) so scripted-sequence cursors key
     correctly. Without a `session_type`, scripted sequences fall back to
     slot 0 (no persistence) — drift-free for CLI/test use.
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
   - **Binary resolution — bare name on PATH (identical host & container).**
     `_FAKE_CLAUDE_BIN` is the bare string `"fake-claude"`; the launcher emits
     it unqualified and lets PATH resolve it **at runtime in-context**, exactly
     as it does for the real `claude` binary. No absolute path is baked at
     build time, so the *same* command string works on the host and inside a
     container with no host→container translation. There is no per-tag `binary`
     config override (removed — see "Scope extensions" / requirement 6b).

6b. **Binary resolution — a `pm which` shim on PATH (host & container).**
   Because the fake is invoked by bare name, the only requirement is that a
   `fake-claude` resolving to the right binary is on PATH in both contexts.
   Rather than a fixed symlink, the on-PATH `fake-claude` is a tiny POSIX shim:

       #!/bin/sh
       core="$(pm which 2>/dev/null | tail -n1)" || exit 127
       exec "$(dirname "$core")/bin/fake-claude" "$@"

   `pm which` prints the active `pm_core` dir, and the wrapper resolves that the
   same way it resolves the running `pm` (session override → session `pm_root` →
   cwd-walk local `pm_core` → installed). So the shim runs the `bin/fake-claude`
   of **whichever pm install `pm which` selects** — including a `/workspace`
   checkout *under test* for a pm-on-pm QA run, not just the installed/mounted
   copy. This is the same in-context resolution everywhere.
   - **Host:** `install.sh --local` writes the shim to `~/.local/bin/fake-claude`
     (alongside the `pm` symlink), removed on `--uninstall`.
   - **Container:** `_build_git_setup_script` (run at every container start)
     writes the same shim to `~/.local/bin/fake-claude` (`~/.local/bin` is first
     on the image PATH — same dir the git-proxy wrapper uses). Doing it as a
     **runtime install** (not a Dockerfile PATH change) means no image rebuild
     is needed. Inside the container `pm which` typically resolves to the
     `/workspace` clone (pm-on-pm) or falls back to `/opt/pm-src`
     (`PYTHONPATH=/opt/pm-src`); either way the shim execs that tree's
     `bin/fake-claude`.
   - The resolved `bin/fake-claude` does
     `sys.path.insert(0, Path(__file__).resolve().parent.parent)` and is
     stdlib-only, so it imports `pm_core` and runs under the system `python3`
     (`#!/usr/bin/env python3`) with no install/venv/deps.
   - This removes the earlier host-path-rewrite hack: `build_claude_shell_cmd`
     no longer bakes `<pm_src>/bin/fake-claude`, so `build_exec_cmd` no longer
     needs `_rewrite_pm_src_path` (deleted). The fake command now reaches the
     container verbatim, the same way bare `claude` does, and the
     custom-`binary`-override gap is gone (the override was removed).

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
   each entry point. Also covers requirement 10: the JSONL transcript is
   readable by `extract_verdict_from_transcript` / `read_latest_assistant_text`
   (single-line + block verdicts), the `idle_prompt` hook event is written and
   refreshed, no `session_id` → no transcript/hook, and `bin/fake-claude
   --session-id` end-to-end via subprocess.

9. **No-verdict sessions & `hold` — staying open like a real session**
   - `impl`, `merge` (and any type matched only by `_all`) never emit a
     verdict. The fake writes preamble/body, then **does not exit** — a real
     interactive Claude session stays in its pane after a turn.
   - `run_fake_claude(hold=…)` / `--hold SECONDS`:
     - omitted (`None`) — block on stdin until EOF (the pane's tty closing
       when the window is killed). Default for live tmux launches.
     - `>= 0` — sleep that many seconds then exit (bounded form for tests;
       `0` exits immediately).
   - `hold` applies to verdict sessions too **when a `session_id` is set**
     (requirement 10): the pane must stay alive while the loop polls, then the
     loop kills it. A verdict session with **no** `session_id` (CLI /
     unit-test use) still exits immediately after the verdict.

10. **Claude-format transcript + hook event — faithful drop-in detection**
   - Production verdict detection (`loop_shared.poll_for_verdict`) is
     **hook-driven**: it blocks on an `idle_prompt` hook event, then reads the
     verdict from Claude's native JSONL transcript via
     `verdict_transcript.extract_verdict_from_transcript`. It does **not**
     scrape pane content (`extract_verdict_from_content` was removed on
     master). A fake that only writes stdout therefore cannot drive any loop
     that polls a tmux pane.
   - When `run_fake_claude` is given a `session_id` it:
     - writes a minimal Claude-format JSONL transcript to
       `~/.claude/projects/<mangled-cwd>/<session-id>.jsonl` (a `user` record
       as the latest-turn boundary + an `assistant` record whose `text`
       content is the fake's full stdout output). `_claude_transcript_path`
       mirrors `claude_launcher._claude_project_dir`;
       `verdict_transcript._read_transcript_text`'s session-id glob tolerates
       cwd-mangling drift.
     - emits the `idle_prompt` hook event to `~/.pm/hooks/<session-id>.json`
       (reusing `hook_receiver._write_event` so the format cannot drift), and
       **re-emits it every `_HOOK_REFRESH` (2 s)** while held open — a poller
       only acts on an event newer than its grace period (review 20 s, QA
       30 s), so a single emission would never satisfy it.
   - The launcher threads `session_id` into the fake **only via
     `build_claude_shell_cmd`** (the tmux-pane path the loops poll). The
     `--session-id` already generated for `transcript=` callers, or passed
     explicitly by QA call sites, is forwarded as `--session-id` to the fake.
     `launch_claude` / `launch_claude_print*` do not thread it — they are
     interactive / print-mode and are not verdict-polled (print mode reads
     stdout directly).
   - `bin/fake-claude` and `pm fake-claude` expose `--session-id`;
     `bin/fake-claude` now *recognises* it rather than discarding it via
     `parse_known_args`.

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
- **Where does the binary path come from?** `_FAKE_CLAUDE_BIN` is the bare
  name `"fake-claude"`, resolved from PATH at runtime — exactly like the real
  `claude` binary. The on-PATH `fake-claude` is a shim that resolves the actual
  binary via `pm which` (so the pm install under test is used, host or
  container); `install.sh` writes it on the host and
  `container._build_git_setup_script` writes it in the container (requirements
  6 and 6b). There is no per-tag `binary` override (removed).

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
- **`loop_shared.extract_verdict_from_content` removed on master:** pane
  scraping is gone. Production detection is now hook-driven —
  `poll_for_verdict` blocks on an `idle_prompt` hook event then reads the
  verdict from the JSONL transcript (`extract_verdict_from_transcript`). The
  fake therefore writes a transcript and emits the hook event (requirement
  10); `match_verdict` is still used by the watcher loops / `parse_review_verdict`,
  but on transcript-derived assistant text, not pane content.

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

6. **`session_type` threaded into non-loop launch sites.** Beyond the PR/QA
   loop, every other Claude launch now passes a `session_type` so it can be
   faked *selectively* (not just via the `_all` catch-all). New no-verdict
   session types — `plan`, `meta`, `guide`, `cluster`, `container`,
   `qa_author`, `qa_regression`, `discuss`, `watcher_review` — were added to
   `SESSION_TYPE_VERDICTS` (all empty: these are interactive, no-verdict
   sessions). Threaded sites: `cli/plan.py` (×6), `cli/meta.py`,
   `cli/guide.py` (×4), `cli/cluster.py`, `cli/container.py` (×2),
   `cli/qa.py` (×6 — author/regression/debug/launch/standalone),
   `tui/pane_ops.py` (×4). `launch_claude_in_tmux` gained a `session_type`
   parameter for the same reason. These extra keys are **not** in
   `model_config.SESSION_TYPES` — they are fake-claude routing only, not
   model-targetable (`SESSION_TYPES ⊆ SESSION_TYPE_VERDICTS` still holds).
