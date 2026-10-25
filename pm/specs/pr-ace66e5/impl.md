# pr-ace66e5 — Audit prompt builders for unbounded enumeration

## Context

`claude` receives a session prompt as a single `argv` entry. Linux caps one
argument at `MAX_ARG_STRLEN` (128 KiB / 131072 bytes, including the
terminating NUL); exceeding it makes `execve` fail with `E2BIG`
(`OSError [Errno 7] Argument list too long`). The plan-review builder was
fixed in `pm_core/cli/plan.py` (commit 11fc933f) with a conditional fallback
to a brief PR listing above `_PROMPT_ARG_LIMIT = 120_000`.

Two things the existing fix does **not** cover:

1. Every other builder that enumerates a collection into the prompt with no
   bound on element count or total size.
2. The `pm/prompts/<file>` + `"$(cat file)"` delivery trick. Command
   substitution still expands to one oversized `argv` entry, so it does not
   avoid `E2BIG` — it only avoids tmux's ~16 KB command-length limit.

Live evidence in the PR notes: review 131175 B, sign-off 144144 B, QA planner
134900 B; PR notes were ~83.5 KB of each prompt (101 notes) and the impl spec
49 KB. Archiving the spec manually cannot bring sign-off or the planner under
the limit because the notes alone exceed it.

## 1. Requirements (grounded in code)

### R1 — Shared size-aware prompt helpers (new module)

Add `pm_core/prompt_bounds.py` as the single source of truth for prompt-size
limits and bounding helpers:

- `PROMPT_ARG_LIMIT = 120_000` (byte limit with headroom under
  `MAX_ARG_STRLEN`).
- `MAX_ARG_STRLEN = 131_072`.
- Shared per-block budgets (single source of truth):
  `PR_NOTES_BUDGET = 35_000`, `SPEC_BUDGET = 30_000`,
  `SESSION_NOTES_BUDGET = 8_000`, `QA_CHILD_STEPS_BUDGET = 20_000`,
  `CONCRETIZE_INSTRUCTION_BUDGET = 20_000`, `MOCKS_BUDGET = 12_000`,
  `PLAN_CONTEXT_MAX_SIBLINGS = 25`, `LIBRARY_ITEMS_MAX = 20`,
  `LIBRARY_LIST_BUDGET = 6_000`, `LIBRARY_TOTAL_BUDGET = 12_000`,
  `PLAN_LIST_BUDGET = 20_000`, `QA_SCENARIOS_MAX = 40`,
  `INTEGRATION_MAX_PATHS = 20`,
  `ARTIFACT_PATHS_MAX = 20`, `WATCHER_MANAGED_MAX = 40`,
  `MERGE_ERROR_MAX_LINES = 60`, `DEPS_MAX = 40`.
  (Iterations 2-4 added `PLAN_LIST_BUDGET`, `LIBRARY_LIST_BUDGET` and
  `LIBRARY_TOTAL_BUDGET` as the probes found count caps that did not bound
  their listings; the plan-builder-local budgets —
  `_PLAN_BRIEF_BUDGET`, `_PLAN_FILE_BUDGET`, `_PLAN_FILES_BUDGET`,
  `_PLAN_DESC_CHARS` — stay in `pm_core/cli/plan.py` next to their only
  users.)
- `prompt_bytes(text) -> int` — `len(text.encode("utf-8"))`; measures bytes,
  not characters (multi-byte text matters).
- `bounded_join(items, formatter, *, max_items=None, max_bytes=None,
  keep="oldest"|"newest", separator="\n", omitted_note=None) -> str` — format
  and join items, stopping before `max_items`/`max_bytes` is exceeded; append
  an explicit omission note when items were dropped. `keep="newest"` iterates
  in reverse and restores order, so recent handoff notes survive.
- `bounded_text(text, *, max_bytes, pointer, label) -> str` — return text
  unchanged when it fits; otherwise head + explicit truncation marker + tail
  (tail keeps verdicts/end-of-file content) + a pointer to the full source.
- `bounded_lines(text, *, max_lines, head_ratio=0.25, marker=...) -> str` —
  head/tail line truncation (mirrors the existing verification-prompt
  behaviour) for transcripts and error output.
- `PromptTooLargeError(RuntimeError)` — raised when a prompt cannot be made
  argv-safe and no file-backed fallback is possible.
- `prompt_fits(prompt, limit=PROMPT_ARG_LIMIT) -> bool`.

`pm_core/cli/plan.py` keeps `_PROMPT_ARG_LIMIT` as an alias of
`PROMPT_ARG_LIMIT` so existing call sites/tests keep importing it.

### R2 — PR notes bounding (`prompt_gen._format_pr_notes`, line 96)

Today the function merges main + workdir notes, sorts by `created_at`, and
joins **every** note's full text. It feeds impl, review, sign-off, QA
planner, QA interactive, and QA child prompts.

Change: add a byte budget (`_PR_NOTES_BUDGET = PR_NOTES_BUDGET = 35_000`).
When the full rendering fits, return it unchanged. When it does not, keep the
newest notes in full within the budget and reduce older notes to a one-line
summary; end with an explicit marker naming the count omitted and the command
to read everything (`pm pr note list <pr-id>`). Never silently drop notes —
the summary line stays for every note until the hard budget is reached, and
the marker reports the remainder.

### R3 — Spec bounding (`spec_gen.format_spec_for_prompt`, line 683)

Today it inlines the whole spec file (49 KB observed). It feeds impl, review,
sign-off, and QA planner prompts.

Change: bound the spec text with `bounded_text` (`SPEC_BUDGET = 30_000`),
head+tail truncation with a marker pointing at the full spec
(`pm pr spec <pr-id> <phase>` and the spec file path). The "MISSING spec"
and staleness guidance text stays intact. `_build_spec_prompt` (line 134)
inlines the prior impl spec when generating a QA spec — bound it the same way.

### R3b — Session notes (`notes.notes_for_prompt`, line 320; `notes.notes_section`, line 285)

User-authored `notes.txt` sections are inlined whole by `notes_for_prompt`
(impl/review/signoff/QA/merge/watcher prompts) and `notes_section` (plan and
guide prompts). Bound each block with `bounded_text`
(`SESSION_NOTES_BUDGET = 8_000`), pointing at the notes file / `pm notes`.

### R4 — Sibling-PR plan context (`generate_review_prompt` line 258,
`generate_signoff_prompt` line 465)

Both build one line per sibling PR in the plan. Unbounded count and title
length. Change: cap at 25 siblings (one-line each) and append
`... (+N more; run \`pm pr list --plan <plan>\`)`.

### R5 — QA scenarios block (`_signoff_qa_scenarios_block`, line 366)

Enumerates every scenario's verdict + `verdict_reason` from the latest
`qa_status.json`. Change: cap at 40 scenarios and truncate each reason to 200
characters; append an omission marker pointing at the captures dir /
`pm qa show`.

### R6 — Integration block (`_signoff_integration_block`, line 403)

Joins `overlap` and `conflicts` path lists. Change: cap each at 20 paths with
`(+N more)`.

### R7 — QA instruction library (`qa_instructions.instruction_summary_for_prompt`, line 276)

One bullet per instruction/regression/artifact item. Change: cap at 20 items
per category with `... (+N more; run \`pm qa list\`)`. Also bound
`mocks_for_prompt` (line 311), which inlines full mock bodies: cap total
bytes with `bounded_text`.

### R8 — QA concretization prompt (`qa_loop._build_concretization_prompt`, line 1505)

Inlines the full `instruction_content` file. Change: bound with `bounded_text`
(`_CONCRETIZE_INSTRUCTION_BUDGET = 30_000`) pointing at the instruction path.

### R9 — QA finalize prompt (`qa_finalize_prompt.build_qa_finalize_prompt`, line 20)

One line per scenario worktree. Change: cap at 40 lines with `(+N more)`.

### R10 — QA child prompt (`generate_qa_child_prompt`, line 2078)

Inlines `scenario.steps` and one bullet per `artifact_paths` entry. Change:
bound steps with `bounded_text` and cap artifact bullets at 20 with
`(+N more)`.

### R11 — Verification prompt (`qa_loop._build_verification_prompt`, line 3072)

Already head/tail-truncates inlined pane output. Add a cap on
`artifact_names` bullets (20) and use `bounded_lines` for consistency. The
`pane_output_path` on-demand form stays preferred.

### R12 — Plan prompts (`pm_core/cli/plan.py`)

- `plan_review`: the existing fallback only shrinks the plan's own PR list.
  `other_prs_context` (line 317) still joins **every** PR from other plans.
  Bound it to 40 one-line entries with `(+N more; run \`pm pr list\`)`, and
  make the over-limit check cover the total prompt including it. Re-point the
  fallback's "run `pm pr show <id>`" text to commands that exist (see R16).
- `plan_breakdown`: `existing_context` (line 193) joins every existing PR.
  Bound to 40 one-line entries with an omission note.
- `plan_deps`: `pr_list_str` (line 498) inlines every PR's description and
  `plan_context` (line 502) reads every plan file's full text. Bound the PR
  list to 40 entries and each plan file with `bounded_text`, pointing at the
  plan path for full text.

### R13 — Merge prompt error output (`generate_merge_prompt`, line 928)

Inlines `error_output` verbatim. Change: bound with `bounded_lines`
(head 40 / tail 20 lines) plus a marker telling the session to re-run the
failed update or read the full output on disk.

### R14 — Watcher auto-start scope (`generate_watcher_prompt`, line 1084)

`managed_list` joins every managed PR id. Change: cap the displayed set at 40
ids with `(+N more)`; the scope semantics (the actual set used for decisions)
are unaffected.

### R15 — Launcher guard (`pm_core/claude_launcher.py`)

Defense in depth for builders we did not audit and for future ones. In
`build_claude_shell_cmd`, `launch_claude`, `launch_claude_print`, and
`launch_claude_print_background`:

- Measure `prompt_bytes(prompt)` when a prompt is actually passed (not on
  `--resume`, which sends none).
- If over `PROMPT_ARG_LIMIT`:
  - Write the **complete** prompt to a file (reuse the existing
    `<host_dir>/pm/prompts/pm_prompt_<session_id>.txt` mechanism; for
    direct/print launches without a host dir, use a temp file).
  - Pass a short bootstrap as the argv prompt instead of `"$(cat file)"`:
    e.g. `"Your complete instructions are in <path>. Read that file first and
    follow it exactly; it is your full task prompt."`
  - Log a warning naming the size and the file path.
- If no writable location exists for the file, raise `PromptTooLargeError`
  with the measured size, the limit, and remediation guidance — never let a
  raw `E2BIG` escape and never silently truncate.
- Under the limit, behaviour is unchanged (`"$(cat file)"` for shell commands,
  quoted prompt for direct launches).
- Fake-claude sessions pass no prompt in argv, so the guard is a no-op there.

### R16 — Fix the broken on-demand pointer

The plan-review fallback (and a watcher prompt) tell the session to run
`pm pr show <id>`, but no such command exists (`pm_core/cli/pr.py` registers
`list`, `graph`, `spec`, `note …`, but not `show`). Add a read-only
`pm pr show <pr-id>` command that prints the PR's display id, title, status,
branch, plan, dependencies, description, tests, files, and notes (using the
same resolution/formatting helpers as `pr_list`/`pr_note_list`). Update the
existing pointers to use it. This makes the "fetch detail on demand" fallback
actually work.

## 2. Implicit Requirements

- **No silent loss.** Every degraded block must name what was omitted and a
  working command/path to read it. The PR notes explicitly forbid silently
  truncating required evidence or instructions.
- **Preserve full instructions on the fallback path.** The launcher guard must
  deliver the complete prompt via a readable file + bootstrap, matching the
  prior recoveries' pattern.
- **Budget coordination.** Per-block budgets must leave headroom for static
  prompt text. Target allocations: PR notes ≤ 40 KB, spec ≤ 40 KB, static +
  other collections ≤ 25 KB, leaving ≥ 15 KB under 120 KB. Builders whose
  static text is large (sign-off ~12 KB) must still fit.
- **Container mode.** Prompt-file writes must honour the existing `cwd` /
  `write_dir` split: write on the host path (`write_dir`), reference the
  container-visible path (`cwd`). The bootstrap must reference the same
  path the `$(cat …)` form used.
- **Resume launches.** No prompt is passed when resuming; the guard must not
  fire or write files there.
- **Fake-claude.** Prompt argv is absent for fake sessions; keep that path
  untouched.
- **Backward compatibility.** `_PROMPT_ARG_LIMIT` stays importable from
  `pm_core.cli.plan`; existing tests keep passing; helper defaults are
  deterministic (no randomness, no time-based budgets).
- **Bounded outputs are stable.** The same input must yield the same prompt
  (tests and prompt-file diffs depend on it).
- **UTF-8 correctness.** All size checks use encoded bytes; truncation must
  not split a multi-byte character (truncate on character boundaries after
  measuring bytes, or accept a small overshoot and verify the final size).

## 3. Ambiguities

### A1 — Bound vs. preserve ("do not silently truncate")
The task offers "cap count, summarize, or fetch detail on demand" while the
PR notes forbid silent truncation. **Resolution:** do all three — cap counts,
summarize older elements with an explicit omission marker, and point at a
working command/path for the full detail; additionally keep the launcher's
file-backed bootstrap so an over-limit prompt still delivers its complete
instructions. No detail is lost without an explicit pointer.

### A2 — How to keep PR notes within budget without dropping active requirements
Notes are the cross-session handoff channel; older notes may still contain
active requirements. **Resolution:** keep the newest notes in full first
(they supersede older ones), reduce older notes to a first-line summary, and
always name the omitted count + `pm pr note list <pr-id>`. Requirements near
the top of each note survive in the summary.

### A3 — Which delivery mechanism for over-limit prompts
Command substitution (`$(cat file)`) still yields one oversized argv entry.
**Resolution:** bootstrap delivery — write the full prompt to a file and pass
a short "read this file and follow it" prompt as argv. Raise a clear error if
no writable location exists.

### A4 — `pm pr show` does not exist
**Resolution:** add the read-only command (R16) rather than weaken the
fallback text. It is small, read-only, and makes every "fetch detail on
demand" pointer valid.

### A5 — Should single large documents (spec, notes.txt sections, error output) be bounded?
The task frames the bug as collections, but the observed E2BIGs were driven
by single documents (spec 49 KB). **Resolution:** bound them too, with
pointers, because they are the same failure class and the task says "any
place a collection … or total size" is unbounded.

### A6 — Truncation shape for specs
Head-only truncation loses the end (edge cases, pass/fail criteria).
**Resolution:** head + tail truncation with an explicit marker in the middle,
pointing at the full file/command. The tail preserves the closing criteria.

### A7 — Exact byte budgets
**Resolution:** centralize defaults in `prompt_bounds.py`
(`PR_NOTES_BUDGET`, `SPEC_BUDGET`, etc.) so they are tunable in one place and
documented. Tests assert against `PROMPT_ARG_LIMIT`, not the individual
budgets.

*No [UNRESOLVED] ambiguities remain.*

## 4. Edge Cases

- **Already within budget:** full detail is preserved; no markers appear.
- **Empty collection:** no marker, no trailing separator.
- **Single element:** no "(+N more)" note.
- **Multi-byte text:** a note/spec with emoji or CJK characters can exceed the
  byte budget while looking short; size checks use encoded bytes. Truncation
  must land on a valid character boundary.
- **Exactly at the limit:** the guard treats `>` as over-limit (consistent with
  the existing plan.py check); `== limit` is allowed.
- **No writable host dir:** `build_claude_shell_cmd` previously fell back to a
  quoted literal. For an over-limit prompt this must raise
  `PromptTooLargeError`, not quote the literal (which would `E2BIG`).
- **Container cwd vs host write_dir:** bootstrap path must be the path Claude
  sees at runtime (`cwd`-based), while the file lands on the host
  (`write_dir`).
- **`cwd=None` direct launches:** write the fallback prompt to a temp file
  (`tempfile.mkdtemp`/`NamedTemporaryFile`), pass its absolute path in the
  bootstrap, and remove it after the process exits.
- **Retry-on-failure path in `launch_claude`:** a failed resume retries with a
  fresh session and the same prompt; apply the same guard to the retry.
- **`launch_claude_print`/`_background`:** the prompt is appended as
  `["-p", prompt]`; guard both. For fake sessions the prompt is not appended.
- **Prompt-file cleanup:** the existing `; rm -f <file>` runs after Claude
  exits; keep it for both `$(cat …)` and bootstrap forms. Temp files from
  direct launches are removed in a `finally`.
- **Concurrent launches:** keep the unique filename (`pm_prompt_<session_id>`)
  so parallel panes never share a prompt file.
- **Non-Linux hosts:** the guard is a byte threshold, not a platform-specific
  check; 120 KB stays safely under macOS's 256 KB `MAX_ARG_STRLEN` analogue.
- **`_format_pr_notes` merge/dedup:** bounding happens after merge/dedup, so a
  workdir copy that wins dedup is what gets bounded.
- **Sign-off return block:** appended after the notes block; its size is
  bounded by the note count (one block per PR) and stays outside the notes
  budget; total is still checked.
- **Builders returning empty strings:** bounding helpers return `""` for empty
  input without adding markers.
- **Existing tests that assert exact prompt text:** summaries/markers only
  appear over budget; small fixtures are unchanged.

## 5. Files

- `pm_core/prompt_bounds.py` (new)
- `pm_core/prompt_gen.py`
- `pm_core/spec_gen.py`
- `pm_core/qa_instructions.py`
- `pm_core/qa_loop.py`
- `pm_core/qa_finalize_prompt.py`
- `pm_core/claude_launcher.py`
- `pm_core/cli/plan.py`
- `pm_core/cli/pr.py`
- `pm_core/notes.py` (if the notes block needs a size bound)
- `pm_core/signoff.py` (if the integration/return joins need bounds)

## 6. Tests

New `tests/test_prompt_bounds.py` plus additions to existing prompt tests:

- Helper unit tests: `prompt_bytes` counts UTF-8 bytes; `bounded_join`
  honours `max_items`/`max_bytes`, appends the omission note, and `keep`
  order; `bounded_text` head+tail; `bounded_lines`; `PromptTooLargeError`.
- Builder tests with a many-element collection (e.g. 200 PR notes at ~2 KB,
  200 sibling PRs, 100 QA scenarios, 100 instruction-library items, 100
  artifact paths, 50 plan PRs, a 200 KB spec) asserting
  `len(prompt.encode()) <= PROMPT_ARG_LIMIT` **and** that the prompt names
  the omission + pointer.
- Launcher guard tests: `build_claude_shell_cmd` with an over-limit prompt
  produces a bootstrap referencing the written file (not `$(cat …)`); with no
  writable dir raises `PromptTooLargeError`; under-limit behaviour unchanged;
  resume path untouched.
- `pm pr show` CLI test: prints the requested PR's description/notes and
  errors on an unknown id.
- Regression: existing prompt tests (`test_bug_fix_flow_prompts.py`,
  `test_plan_review.py`, `test_claude_launcher.py`,
  `test_regression_prompts.py`) stay green.

## 7. Review-loop follow-ups (iteration 1)

The implementation landed in 518b130d; review found five refinements, all
within this spec's intent (no requirement changed):

- **R9 pointer.** The finalize marker named `pm qa status`, which does not
  exist (violating the "name a working command/path" requirement that R16
  exists to enforce). It now resolves the QA run's `qa_status.json` via
  `latest_qa_status_path` (whose directory also holds `qa_resume.json`, the
  only place each scenario's worktree path is recorded), falling back to the
  run-directory glob when no run exists yet.
- **R7 pointer.** The mocks marker pointed at `pm qa list`, which lists
  instructions / regression tests / artifact recipes but **not** mocks; it now
  names `pm qa mocks list`. (§20 corrects this a second time: `pm qa mocks
  list` prints ids/titles/descriptions only, so it cannot be the reader the
  marker's "Read the full text:" sentence promises.)
- **§5 signoff.py.** `format_signoff_return` still joined the integration
  `conflicts` / `overlap` path lists unbounded — the same class of bug R6
  fixes in `_signoff_integration_block`, and it feeds impl / review / QA
  prompts via `_signoff_return_block`. Both are now bounded with
  `INTEGRATION_MAX_PATHS`.
- **R2 newline.** The under-budget PR-notes path dropped the trailing newline
  the pre-PR builder emitted (the bounded path kept it). Both paths now
  terminate the section.
- **R2 marker.** `_render_pr_notes_bounded`'s upgrade path did not reserve the
  marker's bytes, so newest-notes-in-full could fill the budget exactly and
  force the "older notes are abbreviated" marker to be dropped — the
  abbreviations would then be unexplained. The reserve is now applied before
  upgrading.

## 8. Review-loop follow-ups (iteration 2)

Iteration 2 measured the builders against this repo's **real** `pm/project.yaml`
(483 PRs, 619 notes, 22 plan files / ~500 KB, descriptions up to 11 KB) rather
than synthetic fixtures, which surfaced two builders the audit still left
unbounded. Both were fixed; the per-block budgets this spec prescribed were
correct but insufficient on their own, because a per-item cap does not bound
the **product** of cap × item size, and a per-file budget does not bound the
number of files.

- **`plan_deps` (R12) — measured 312,155 bytes** (2.6× the limit; the launcher
  guard kept it from `E2BIG`, but the builder was still unbounded). Two
  independent causes:
  - `pr_list_str` inlined each PR's **full** description under a count cap of
    40; real descriptions reach 11 KB, so the cap allowed ~440 KB.
  - `plan_context` bounded each plan file to 20 KB but not the total: 22 plans
    × 20 KB = 440 KB (277,519 bytes measured).
  Fixed with `_PLAN_DESC_CHARS = 300` per-description truncation (with a
  marker naming `pm pr show <id>`) and an aggregate `_PLAN_FILES_BUDGET =
  30_000` shared across plan files, with `_PLAN_FILE_MIN_SLICE` so a plan is
  listed as omitted rather than emitting a marker that does not fit its slice.
  Re-measured on the real project: **47,015 bytes**.
- **`_run_fix_command` (`pm plan fix`) — ~500 KB**, not covered by R12: it
  concatenated **every** plan file's full text into `build_fix_prompt`. Now
  bounded with `_PLAN_FILES_BUDGET` and a pointer at the plan files. Measured
  on the real project: **31,159 bytes**.
- **R6 / §5 integration markers named nothing.** `(+N more)` says what was
  dropped but not where to read it, which the spec's own "no silent loss"
  requirement forbids (the same defect iteration 1 fixed for R7 and R9). New
  `integration.integration_pointer(pr_id)` names `$CAP/<pr-id>/integration.json`,
  falling back to `pm pr show <pr-id>`; both `_signoff_integration_block` and
  `format_signoff_return` use it. `pm pr show` now prints the integration
  record (and the full-record path) so that fallback is not a dead end.
- **R11 dead parameters.** `_build_verification_prompt` passed `pointer=` /
  `label=` to `bounded_lines` without `max_bytes`; `bounded_lines` only applies
  the byte bound when both are set, so both were silently ignored and a single
  enormous line defeated the line count. Added
  `_VERIFICATION_MAX_PANE_BYTES = 60_000` so the bound is real and the pointer
  reaches the prompt.

Verification: `tests/test_prompt_bounds.py` 53 cases (6 new, all
failing-then-passing). Full suite 3410 passed, 1 pre-existing failure
(`test_hook_events::test_installer_writes_standalone_receiver` — pr-4bde874,
fails whenever `PM_HOST_HOME` is set).

## 9. Review-loop follow-ups (iteration 3)

Iteration 3 probed the builders with **pathological item sizes** rather than
pathological counts, which is the same defect class iteration 2 found for
descriptions — a count cap does not bound `cap × item size`, and iteration 2
only fixed the *description* half of it. The count-capped one-line listings
still inlined user-authored **titles** unbounded: 25 sibling PRs with long
titles measured 180 KB in the review prompt (247 KB total) and 180 KB in the
sign-off prompt (277 KB total) — both over `PROMPT_ARG_LIMIT`, so the launcher
guard had to fire for builders this PR set out to bound.

- **R4 / R12 listings now carry a byte budget.** New shared
  `PLAN_LIST_BUDGET = 20_000` in `prompt_bounds.py` (used by
  `bounded_join`'s `max_bytes`, which until now no production caller passed)
  bounds the sibling-PR blocks (`generate_review_prompt`,
  `generate_signoff_prompt`), the dependency block (`generate_prompt`), and the
  plan builders' PR listings (`plan_review`'s other-PR context,
  `plan_breakdown`'s existing-PR context, `plan_deps`'s PR list). Real listings
  in this repo run 0.4-14.5 KB, so the budget only bites on pathological
  titles — every real prompt measured byte-identical before and after
  (`/pm-captures/review-4e41-i3/`).
- **R12 plan-review fallback cascade was a no-op at ≤40 PRs.** The fallback
  capped the brief listing at `_PLAN_LIST_MAX = 40`, but a plan with 40 or
  fewer PRs and long titles produced the same oversized listing in both the
  first and the "minimal" pass. The brief listing now goes through
  `_brief_list()` with `_PLAN_BRIEF_BUDGET = 40_000` — deliberately generous
  and *uncapped by count*, so the fallback still lists every PR one line each
  exactly as before the audit (all 22 real plans produce byte-identical
  `pm plan review` output) — and the second safety net re-runs it with a
  quarter of the budget so the cascade actually shrinks.
- **R15 container path split.** `_materialize_oversized_prompt` accepted
  `write_dir` but returned a bootstrap naming *that* path, contradicting the
  spec's container edge case ("write on the host path, reference the
  container-visible path"): a container caller (`write_dir=<host>`,
  `cwd=/workspace`) would have handed claude an unreadable path. It now writes
  to `write_dir` and names `cwd`, falling back to `cwd` when `write_dir` is
  unusable — the same split `build_claude_shell_cmd` uses.
- **`bounded_lines` silently ignored `max_bytes` without `pointer`** (the trap
  iteration 2 recorded): a future caller passing `max_bytes` alone got no byte
  bound at all. The byte bound now always applies, with a generic pointer
  fallback.

Verification: `tests/test_prompt_bounds.py` 60 cases (7 new). Full suite 3417
passed, 1 pre-existing failure (`test_hook_events::
test_installer_writes_standalone_receiver` — pr-4bde874, fails whenever
`PM_HOST_HOME` is set). Evidence: `/pm-captures/review-4e41-i3/`
(`full-suite-i3.txt`, `prompt-bounds-tests-i3.txt`, `baseline-*.txt` /
`after*-*.txt` real-data measurements).

## 10. Review-loop follow-ups (iteration 4)

Iteration 4 re-ran the i2/i3 probes (real project, then pathological counts,
then pathological item sizes) and probed the one dimension none of them had
covered — the *sum* of the blocks. Two gaps, both the same theme: a bound that
is correct per item but not for the whole prompt.

- **`instruction_summary_for_prompt` (R7) was count-capped but not
  byte-bounded.** It caps each category at `LIBRARY_ITEMS_MAX = 20` but
  inlines each item's user-authored frontmatter `description` verbatim, so 20
  items with multi-KB descriptions measured **303,973 bytes** — over
  `PROMPT_ARG_LIMIT` on their own — and the QA planner prompt built from them
  measured **212,671 bytes**. The library is user-authored free text and
  already at the 20-item cap in this repo (20 regression tests), so neither
  the count cap nor the real-data size (3.1 KB today) bounds it.
  Fixed with a new `LIBRARY_LIST_BUDGET = 6_000` per category plus an
  aggregate `LIBRARY_TOTAL_BUDGET = 12_000` on the joined block (a per-category
  budget alone would let three categories multiply it — the plan-file lesson
  from iteration 2). Both markers name `pm qa list`, which lists every item.
  Real library output is byte-identical (3,101 / 747 bytes); the pathological
  case drops to 12,000 bytes and the planner prompt to 20,295 bytes.
- **`build_regression_test_prompt` inlines its test body unbounded**
  (considered, deliberately not bounded). The body *is* the prompt — the test
  session executes it — so truncating it would silently corrupt the test
  rather than abbreviate a listing. Real bodies run 7-12 KB, so a bound would
  never bite in practice and truncation is the wrong degradation.
  Correction (iteration 5): the guard does **not** deliver an over-limit body
  intact on this path. `pm_core/tui/pane_ops.py` launches both the regression
  and the non-regression QA-instruction panes through
  `build_claude_shell_cmd(prompt=..., session_type="qa_author")` with no `cwd`
  and no `write_dir`, so there is no host dir to write the prompt into and the
  guard **raises** `PromptTooLargeError` (§4's "no writable host dir" case)
  instead of falling back to a file. That is still the right degradation — an
  explicit error beats a truncated test — but it is a hard pane-launch failure,
  not the file-backed delivery claimed above, and it is the same no-`cwd`
  situation that made `guide.build_assist_prompt` a hard failure until this
  iteration bounded its plan listing.
- **`get_spec_mocks_section`'s legacy fallback** extracts a `## Mocks` section
  from the QA spec unbounded. It has no production caller (only
  `tests/test_spec_gen.py`); the live path is `qa_instructions.mocks_for_prompt`,
  which is bounded. Left as-is to keep this PR scoped to reachable builders.

- **The per-block budgets did not compose (R1/R4/R15, §2 "Budget
  coordination").** Every block was bounded *individually*, but nothing
  checked their **sum** against the builder's static text. Probing every
  collection at its own budget simultaneously (400 PR notes, a 200 KB spec,
  200 QA scenarios, 200 long-title siblings, a 40 KB description, a 60 KB
  notes.txt) measured **review 136,261 B, sign-off 158,350 B and the QA
  planner 130,755 B — all over `PROMPT_ARG_LIMIT`**, so the launcher guard had
  to fire for exactly the builders this PR exists to bound. The spec's §2
  estimate that sign-off's static text is "~12 KB" was wrong: it is ~19 KB
  (and ~47 KB once the always-inlined description and plan context are
  counted), so no per-block constant can make the sum fit.
  Fixed with a new shared `fit_prompt(render, blocks)` in `prompt_bounds.py`:
  the builder keeps its own static text and block placement, and when the
  render exceeds the limit the largest blocks are abbreviated (head+tail,
  each with a marker naming a command that reads the full text) until it
  fits. `generate_prompt`, `generate_review_prompt`,
  `generate_signoff_prompt` and `generate_qa_planner_prompt` now assemble
  through it, with the PR description, PR notes, spec, plan context, session
  notes, QA library summary and QA scenario summary as the shrinkable blocks.
  Blocks are never shrunk below 2 KB, and if the static text alone is over
  the limit the render is returned unchanged for the launcher's file-backed
  bootstrap to carry intact. Real prompts are unchanged: the sweep over all
  483 real PRs still measures impl 75,143 / review 77,613 / sign-off 92,162 /
  qa_planner 80,649, and a full-text diff for three real PRs x four builders
  shows the only difference is the spec truncation marker wording below —
  every real listing sits far under the budgets, so the fit path only runs
  when a PR is large in several dimensions at once. After: 119,700 B for each
  of review / sign-off / planner.
- **`generate_qa_interactive_prompt` (Scenario 0) and
  `generate_qa_child_prompt` are not wired through `fit_prompt`**: under the
  same pathological inputs they measure 42,051 B and 65,464 B — well under
  the limit, and they inline fewer blocks than the four builders above.
- **Marker wording.** The spec truncation marker read "Implementation Spec
  spec truncated" (`label=f"{label} spec"` where `label` was already
  "Implementation Spec"); it now reads "Implementation Spec truncated". The
  block size is unchanged (`bounded_text` keeps head+tail within the budget),
  so only the marker's bytes shift between the slices.

Verification: `tests/test_prompt_bounds.py` 72 cases (12 new: 4 `fit_prompt`
unit tests, 5 budget-coordination tests — the 4 builder ones fail without the
fix at 121-158 KB — and 3 for the library bound above). Full suite 3429 passed, 1 pre-existing failure
(`test_hook_events::test_installer_writes_standalone_receiver` — pr-4bde874,
fails whenever `PM_HOST_HOME` is set). Evidence: `/pm-captures/review-4e41-i4/`.

## 11. Review-loop follow-ups (iteration 5)

Iteration 5 swept every *reachable* prompt builder the audit never touched
(not just the four wired through `fit_prompt`) under one pathological fixture,
and re-checked the "name a working pointer" requirement in the environment the
pointer is read in. Two gaps, both the same class as earlier iterations: a
listing with no bound at all (R4/R12), and a marker naming a location that does
not exist where the session runs (R6/§8).

- **`guide.build_assist_prompt` inlined the plan list with no bound at all**
  — no count cap, no byte budget, the one listing the audit missed entirely
  (R4/R12 bound the sibling-PR, dependency, existing-PR and other-plan lists,
  but `pm guide`'s "Current plans:" block kept joining every plan name
  verbatim). 200 plans with long names measured **228,293 B** (1.9x
  `PROMPT_ARG_LIMIT`), and the test fixture's 200 x 4 KB names measured
  805,371 B — 6.7x `MAX_ARG_STRLEN`. The guide pane is launched with no `cwd`,
  so `build_claude_shell_cmd` has no writable location and the launcher guard
  **raises** `PromptTooLargeError` rather than degrading, i.e. this builder was
  a hard launch failure, not just an oversized prompt. Now bounded with the
  shared `PLAN_LIST_MAX` (new in `prompt_bounds.py`; `pm_core/cli/plan.py`'s
  local `_PLAN_LIST_MAX` is now an alias of it) plus `PLAN_LIST_BUDGET`, with
  the marker naming `pm plan list`. Re-measured: **29,693 B**.
- **`integration.integration_pointer` named the host captures path.** It
  built the path from `integration_json_path` (`captures_root()`, i.e.
  `~/.pm/sessions/<tag>/captures/<pr>/integration.json`) and is what the
  abbreviated overlap/conflict markers name. Those markers reach impl, review
  and QA-planner prompts via `signoff.format_signoff_return`, and all three run
  inside containers, where the captures dir is bind-mounted at `/pm-captures`
  and the host path does not exist — a pointer the session cannot follow, the
  exact defect iteration 1 fixed for the R7/R9 markers. Reachable: the
  project.yaml record keeps up to `_YAML_LIST_LIMIT` (40) paths while
  `INTEGRATION_MAX_PATHS` is 20, so a record with 21-40 paths fires the marker.
  It now resolves through `captures_dir` (the resolver that knows about the
  container mount), falling back to `pm pr show`; on the host the result is
  unchanged. Evidence: `/pm-captures/review-4e41-i5/`.

Checked and deliberately unchanged: `bounded_join`'s `keep="newest"` has no
production caller (the PR-notes bound is implemented separately in
`_render_pr_notes_bounded`), but R1 specifies it and it is covered by a unit
test; `generate_merge_prompt` uses `bounded_lines`'s default 0.25 head ratio
(15 head / 45 tail for 60 lines) rather than R13's "head 40 / tail 20" — the
tail is where git prints the failure, so tail-heavy is the better degradation
and it matches the verification prompt's ratio.


## 12. Review-loop follow-ups (iteration 6)

Iteration 6 continued iteration 5's method — check each omission marker in the
environment the session actually reads it in — and re-swept the one remaining
join over a collection that had no bound. Three of the four findings are the
same host-path/placeholder class the earlier iterations kept hitting; none of
the per-block budgets or the launcher guard changed.

- **`_signoff_qa_scenarios_block`'s marker named a host-only path.** It named
  `latest_qa_status_path(pr_id)` — the live `qa_status.json` under the *host*
  `~/.pm/workdirs/qa/<pr>-*/`. Sign-off runs inside a container
  (`signoff.py`: `_claude_cwd = _CONTAINER_WORKDIR`, host workdir as
  `write_dir`), and the container mounts only the workdir, `~/.claude`,
  `~/.pm/hooks`, the pm source and the captures dir — `~/.pm/workdirs` does not
  exist there, so the marker was unreadable, the same defect iteration 5 fixed
  for `integration_pointer`. Reachable whenever a QA run has more than
  `QA_SCENARIOS_MAX` (40) scenarios. It now resolves through `captures_dir`
  (the container-aware resolver) to the per-scenario verdicts
  `qa_loop._persist_scenario_verdicts` writes at
  `$CAP/scenarios/<n>/verdict.md` + `scenario.json` — the structured record
  exists precisely so the sign-off agent does not need the ephemeral
  `qa_status.json` — falling back to `pm qa captures-path <pr-id>`. On the
  host the path is the same captures dir the prompt's own evidence step
  already tells the reviewer to use (`CAP="$(pm qa captures-path <pr-id>)"`).
- **`_render_pr_notes_bounded`'s markers used a literal `<pr-id>`.**
  `run `pm pr note list <pr-id>`` is not directly runnable, and the same block
  already carries the concrete id from `fit_prompt`'s pointer (`pm pr note
  list <pr-id>`), so the two forms disagreed inside one prompt section. The
  function now takes the PR id and interpolates it. Real prompts change only
  by that: a full-text diff for 3 PRs x 4 builders shows the notes marker line
  and +3 bytes on the builders that abbreviate notes, nothing else.
- **`generate_watcher_prompt`'s `target_list` was the last unbounded join.**
  It sat directly beside `managed_list`, which R14 bounds, and was built from
  the same user-set collection: `", ".join(f"**{t}**" for t in targets)` with
  no count cap and no byte budget. Now bounded by `WATCHER_MANAGED_MAX` with a
  marker naming `pm autostart list` (the command that lists targets). Both
  lists are display-only — the scope the watcher acts on still comes from
  `managed_ids`.
- **`mocks_for_prompt` passed an `omitted_note` to `bounded_join` with no
  `max_items`/`max_bytes`,** so the note could never fire (dead code that read
  as if a per-mock marker existed). Removed; the aggregate `bounded_text` owns
  the degradation and its marker names the mock reader (§20).

Verification: `tests/test_prompt_bounds.py` 80 cases (4 new, all
failing-then-passing: the container-mount and `captures-path`-fallback markers,
the concrete PR id, and the bounded target list). Real-data sweep over all 483
PRs x 4 builders: impl 75,146 / review 77,616 / sign-off 92,165 / planner
80,652 B — all under `PROMPT_ARG_LIMIT`, the +3 B being the notes marker's
concrete id. Full suite 3366 passed, 55 failed + 17 errors — a failure set
byte-identical to `origin/master` in this sandbox (all environmental: the
sandbox git shim forwards pull/push to a host workdir, so
`test_signoff_integration` / `test_merge_publish` cannot reach a real remote).
Evidence: `/pm-captures/review-4e41-i6/`.

## 13. Review-loop follow-ups (iteration 7)

Iteration 7 re-ran the i5/i6 method (check every omission marker where the
session actually reads it) plus an independent sweep of **every reachable
builder** — not just the four wired through `fit_prompt` — with pathological
inputs on each dimension (count, item size, single-document size). Three
findings; no per-block budget, shared helper or launcher path changed.

- **`build_qa_finalize_prompt` was the last count-capped listing with no byte
  budget.** It caps the per-scenario worktree listing at 40 entries but bounds
  neither the line length nor the total: 40 worktree paths of ~4 KB (the
  `PATH_MAX` ceiling, since the paths are user-visible filesystem paths) built
  a **162,870-byte** prompt. Every other listing the audit touched got a byte
  budget in i3/i4 for exactly this reason (a count cap does not bound
  `cap × item size`), so this one was an inconsistency as well as a gap. Now
  bounded with the shared `PLAN_LIST_BUDGET`, with the existing marker naming
  the run's `qa_status.json` / `qa_resume.json`; that prompt drops to 17,423 B,
  and real listings (short paths) are byte-identical. A single path longer
  than the whole budget keeps no lines and emits only the marker, which names
  where every scenario is recorded — the same degradation the other bounded
  listings use.
- **`_render_pr_notes_bounded`'s "older notes are abbreviated" marker was
  wrong when *nothing* was abbreviated in full.** A single note larger than
  the whole budget cannot be upgraded, so `remaining` runs out at the first
  (newest) note and every line stays a summary — yet the marker told the
  session only the *older* notes had been abbreviated, so the newest handoff
  (the most important one) read as if it were the full text. The marker now
  says "notes are abbreviated" when zero notes were upgraded and keeps the
  "older notes" wording otherwise. Real prompts are unchanged (in this repo
  the upgrade path always upgrades at least the newest note).
- **`format_signoff_return` resolved its pointer eagerly.** It called
  `integration.integration_pointer()` before checking whether either path list
  was actually abbreviated, and that pointer goes through
  `paths.captures_dir()`, which **creates** `~/.pm/sessions/<tag>/captures/
  <pr-id>/` as a side effect — so merely *building* an impl / review / QA
  prompt for a PR with an integration record touched the filesystem. The
  pointer is now resolved inside the `omitted_note` callable, so it runs only
  when something was really dropped (matching `_signoff_integration_block` and
  `_signoff_qa_scenarios_block`, which were already lazy).

Checked and deliberately unchanged:

- **Single user-authored fields (PR / scenario titles, project name) are still
  inlined unbounded.** They are not collections, and they are handled: when
  the static text alone is over the limit `fit_prompt` returns the render
  unchanged and the launcher writes the complete prompt to a file and passes a
  short bootstrap, so nothing is lost. Bounding them would mean truncating the
  one line that names what the session is working on.
- **`generate_watcher_prompt`'s managed-PR list truncates at 40 while the
  block's "only PRs in the managed set above" instruction refers to it.** The
  list is a display of a set pm itself enforces (the watcher acts by running
  `pm` commands), the marker signals the abbreviation with `(+N more; ...)`,
  and no command prints the exact managed set (`pm autostart status` lists
  targets and their *pending* dependencies only), so no marker change would be
  more accurate.
- **`PromptTooLargeError` is raised but never caught.** It only escapes when
  there is no writable location at all (`build_claude_shell_cmd` with no
  `cwd`/`write_dir`, e.g. a >120 KB QA instruction body launched from the QA
  pane or `pm qa launch`); every other over-limit prompt is delivered via the
  file-backed bootstrap. Surfacing it as a pane/CLI message rather than an
  uncaught traceback is caller-side error handling outside this PR's scope.

Verification: `tests/test_prompt_bounds.py` 86 cases (6 new, 3 of them
failing-then-passing — the finalize byte bound, the marker accuracy and the
lazy pointer; the other 3 guard the unchanged paths). Full suite re-run after
the edits; failure set compared against an `origin/master` baseline in the
same sandbox (see the PR note for the counts).

## 14. Review-loop follow-ups (iteration 8)

Iteration 8 re-ran the i7 sweep independently — every reachable builder, on
each dimension (count, item size, single-document size) — and then split the
remaining over-limit results by whether the *item* can actually be that long.
Two listings were still count-capped with no byte budget; the rest are
bounded by something other than the budget.

- **The integration overlap/conflict listings (R6 / §5) were count-capped
  only.** `INTEGRATION_MAX_PATHS = 20` bounds the count, but the items are
  filesystem paths, whose length is bounded only by `PATH_MAX` — so 20 of
  them measured **199,920 bytes** in the sign-off prompt and 200,114 with 40
  (the YAML record's own `_YAML_LIST_LIMIT`). This is the cap-times-item-size
  defect i3/i7 fixed for every other listing, and it is worse here than
  elsewhere because `_signoff_integration_block` is part of the builder's
  **static text**, not one of `fit_prompt`'s shrinkable blocks — so the
  launcher guard had to fire for a builder this PR exists to bound. New
  shared `INTEGRATION_LIST_BUDGET = 8_000` on all four sites: both lists in
  `_signoff_integration_block` and both in `signoff.format_signoff_return`
  (the block the impl / review / QA-planner prompts inline via
  `_signoff_return_block`). The omission markers already name the full record
  (`integration.integration_pointer`, R6/§12). Re-measured: **47,752 bytes**;
  a 20 × 200 B record (the realistic shape) is byte-identical at 28,920.
- **The QA child prompt's artifact listing was count-capped only.** It
  inlines full paths (`{scratch}/qa-artifacts/<name>`), not basenames, so
  `ARTIFACT_PATHS_MAX = 20` does not bound it: 20 paths of ~4 KB measured
  **108,490 bytes** (the same reasoning i7 used for the finalize worktree
  paths, which are the same shape). New `ARTIFACT_PATHS_BUDGET = 8_000`;
  re-measured **31,934 bytes**.

Checked and deliberately unchanged:

- **`_build_verification_prompt`'s recipe bullets** are count-capped only
  (`ARTIFACT_PATHS_MAX`) but carry `Path(p).name` — basenames, so the item is
  bounded by the filesystem's `NAME_MAX` (255) and 20 of them cannot exceed
  ~5 KB. A byte budget there could never fire, which is the dead-parameter
  defect §12 removed from `mocks_for_prompt`; the count cap does bound it.
- **`build_regression_test_prompt`** (the test body *is* the prompt) and the
  watcher managed/target lists (PR ids and short target names, 40 items)
  remain as recorded in §10 and §13.

Verification: `tests/test_prompt_bounds.py` 89 cases (3 new, all
failing-then-passing — the sign-off integration list, the sign-off-return
block, and the QA child artifact list; each measured 108-200 KB before the
fix). Real-data sweep unchanged. Evidence:
`/pm-captures/review-4e41-i8/` (`sweep.py`, `sweep-after-i8.txt`,
`integration-paths-before-after.txt`).

## 15. Review-loop follow-ups (iteration 9)

Iteration 9 re-ran the i7/i8 sweep independently, but with **realistic per-item
maxima** instead of unbounded synthetic strings (a real file name is capped by
`NAME_MAX` 255, a real absolute path by `PATH_MAX` 4096, the largest real PR
description in this repo is ~11 KB). Under those inputs every reachable
builder is under `PROMPT_ARG_LIMIT`; the only exception is
`build_regression_test_prompt` (the test body *is* the prompt, §10/§14). The
sweep also confirmed the two i8 classifications: `_build_verification_prompt`'s
recipe bullets (basenames) and the finalize/QA-child path listings (paths)
behave as recorded.

One defect, in the markers themselves: **the comma-separated omission markers
rendered with a double space.** `bounded_join` appends the marker *after*
`separator`, and the four markers passed with `separator=", "` also began with
a space, so an abbreviated listing read
```... f19.py`,  (+10 more; run `pm pr show pr-x`)``` — one stray space in the
prompt text the session reads. The redundant leading space is gone from
`_signoff_integration_block` (both lists), `signoff._integ_note` (both lists)
and `generate_watcher_prompt`'s managed/target lists. The `"\n"`-separated
markers are unaffected: their leading indentation is deliberate (it aligns the
note with the two-space-indented listing in the plan builders).

Checked and deliberately unchanged:

- **`integration.summary()`** truncates a `CONFLICT` record's path list to five
  files with a bare ` ...`. It is bounded, and in its only prompt use
  (`_signoff_integration_block`'s "Result:" line) the bounded *and pointed*
  path lists follow immediately, so nothing is dropped without a pointer. Its
  other callers are CLI displays.
- **The `_X = X` constant aliases** in `prompt_gen.py` (and the `PLAN_LIST_MAX`
  alias in `cli/plan.py`) keep the builders' local names stable; no test
  references them. Left as-is.

Verification: `tests/test_prompt_bounds.py` 90 cases (1 new,
failing-then-passing: the marker spacing). Real-data sweep over 80 PRs × 4
builders is byte-identical before and after (the fix only touches abbreviated
listings, which this repo's real data never triggers). Full suite failure set
byte-identical to an `origin/master` worktree baseline in this sandbox
(54 failed / 17 errors / 3376 passed vs 54 / 17 / 3287 — the delta is this
PR's new tests). Evidence: `/pm-captures/review-4e41-i9/`.

## 16. Review-loop follow-ups (iteration 10)

Iteration 10 re-ran the i7-i9 method independently — every reachable builder,
on each dimension (count, item size, single-document size, and the sum of the
blocks) — with the launcher guard's own path exercised end to end. No builder
is over `PROMPT_ARG_LIMIT` under realistic maxima, and no unbounded join
remains: `bug_fix_prompts.py`, `regression_prompts.py`, `qa_authoring.py`,
`cli/meta.py` and `cli/container.py` contain no collection joins at all, and
the watcher / discovery / standalone-QA / merge / finalize / verification /
QA-child / guide builders measured 4-92 KB under maximal inputs.

One defect, in the fallback `fit_prompt` documents but did not implement.

- **`fit_prompt` truncated blocks even when it could not make the prompt
  fit.** Its docstring (and the i4 test comment) promise that when the static
  text alone is over the limit the *render is returned unchanged*, because the
  launcher's file-backed bootstrap carries the complete prompt either way — so
  nothing is lost. The loop instead shrank every block towards `min_bytes`
  (2 KB) and returned that render: a prompt of 10,000 B static text + a
  4,000-byte block came back at 12,000 B (still over the 5,000-byte limit it
  was tested against) with the block halved and a truncation marker where the
  text had been. The abbreviation bought nothing — the result was over the
  limit anyway and is delivered by the bootstrap regardless — so the detail
  was lost for no reason, which is the failure mode the module exists to
  avoid. The same happened when the blocks *could* be shrunk but not enough
  (e.g. 118 KB static + two 20 KB blocks against a 120 KB limit: the loop
  reached 122 KB and returned that, discarding two blocks to no effect).
  `fit_prompt` now keeps the untouched render and returns it whenever the loop
  cannot reach the limit; the shrink path is unchanged for prompts that do
  fit afterwards, so every real prompt and every budget-coordination test is
  byte-identical.

Verification: `tests/test_prompt_bounds.py` 92 cases (2 new, both
failing-then-passing: the unfittable render and the partial-shrink render).
Real-data builders are unaffected — the fix only changes what is returned when
the prompt is over the limit, which no real PR produces. Independent sweep of
every reachable builder with realistic per-item maxima (PATH_MAX paths,
NAME_MAX basenames, 11 KB descriptions, 200 KB single documents) measured
max 92 KB (`_build_verification_prompt`) against the 120 KB limit. The
launcher's bootstrap was exercised end to end again: a 125,011-byte prompt
arrives as a 203-byte argv, the child reads the complete file, and the file is
removed after the command. Full suite: 3389 passed / 44 failed / 17 errors, and
the five environmental files that account for every failure
(`test_signoff_integration`, `test_merge_publish`, `test_hook_events`, the
flaky `test_git_ops::test_keeps_unpushed_merge`, `test_popup_session_code`)
give 43 failed / 84 passed / 17 errors on both this branch and an
`origin/master` worktree in the same sandbox — identical, and none
prompt-related. Evidence: `/pm-captures/review-4e41-i10/`.

## 17. Review-loop follow-ups (iteration 11)

Iteration 11 re-checked each omission marker against what the session can
actually do with it — the i5/i6 method — and found one marker that named no
usable reader at all: the session-notes marker (R3b, `notes.notes_section` /
`notes.notes_for_prompt`, and the `session_notes` / `qa_notes` blocks the four
`fit_prompt` builders pass).

- **The session-notes marker pointed at `pm notes`, which cannot read notes.**
  `pm notes` opens the interactive section editor (`pm_core/cli/guide.py`,
  `notes_cmd` → `run_watched_editor`) and, on first use, a splash that waits
  for a raw-mode keypress. A session following "Read the full text: `pm notes`"
  gets an editor (or a blocked read) and no text — the truncation was
  unrecoverable in practice, which is the silent loss R3b exists to prevent.
- **The file path beside it was a host absolute path.** `f"file: {root /
  NOTES_FILENAME}"` resolves through `store.find_project_root()` in the pm
  process that *builds* the prompt (the host), while the sessions these blocks
  feed — impl, review, QA planner — run inside a container where the workdir is
  mounted at `/workspace` and the host path does not exist. So both halves of
  the marker failed in the common case (the same host-vs-container split i5
  fixed for `integration_pointer` and i6 for the QA-scenario marker).

Fixed with a shared `notes.notes_pointer()` in `pm_core/notes.py`, naming the
notes *files* relative to the project root — `` `pm/notes.txt` and
`pm/notes-local.txt` in the project root `` — which resolves both on the host
and in the container. This matches the precedent `spec_gen` already sets for
its own paths (`file_path.relative_to(root.parent)`, with the same
container-mount comment). The four `fit_prompt` block pointers
(`session_notes` x3, `qa_notes`) now call the helper instead of hard-coding
`` `pm notes` ``, so the block-level and block-internal markers agree.

Deliberately unchanged: the two pre-existing human-facing mentions of
`pm notes` in `generate_watcher_review_prompt` ("read via `pm notes` or
directly"; "`pm notes` or a direct edit") — that session is a chat-driven
human surface, and both already offer the direct-edit alternative. Also
unchanged: the truncated-scenario-steps marker ("the QA plan in the QA planner
transcript"). `qa_loop` does hold the planner's `transcript_path`
(`_run_qa_loop`), but the child/concretization builders are not passed it, so
naming it would mean threading a new argument through both for a degradation
that needs a >20 KB single scenario's steps. The marker is vague, not wrong —
the transcript is reachable (`~/.claude` is mounted in the container) and the
scenario's title and focus are inlined in full.

Verification: `tests/test_prompt_bounds.py` 93 cases (1 new,
failing-then-passing on `assert "`pm notes`" not in block`). A marker sweep
over the four builders with pathological inputs now finds no absolute host path
in any marker. Real prompts are byte-identical (this repo's `notes.txt` is
211 B, far under the 8 KB budget, so the marker never fires here). Full suite
failure set unchanged from the i10 baseline.

## 18. Sign-off return: integration merge (SIGNOFF_IMPL)

Sign-off routed the PR back to impl with `SIGNOFF_IMPL` — not for a code
defect, but because the integration check against `master` @ `c0ba037b3bb6`
conflicted in `pm/project.yaml`. Both sides had appended new PR entries to the
registry (the file's only changed path on both sides; every code path merged
cleanly), so pm only permits an implementation return.

Resolved by merging `c0ba037b` into this branch and keeping **all four** new
entries, in the `created_at` order the file already uses:

| entry | side | created_at |
| --- | --- | --- |
| `pr-7d68898` | master | 2026-10-24T22:07:19 |
| `pr-a42a4f8` | this branch | 2026-10-24T22:28:40 |
| `pr-a591cbf` | master | 2026-10-25T00:07:20 |
| `pr-e7ee94d` | this branch | 2026-10-25T00:26:43 |

Each entry is byte-identical to its source side, and each side's *other*
`project.yaml` edits are preserved (this branch's notes on `pr-ace66e5` /
`pr-0368986`, master's status updates). No requirement in this spec changed and
no prompt builder was touched by the merge.

Verification: `pm/project.yaml` parses (487 PRs, each of the four present
exactly once); `tests/test_prompt_bounds.py` 93 passed; the four prompt suites
named in §6 (`test_bug_fix_flow_prompts`, `test_plan_review`,
`test_claude_launcher`, `test_regression_prompts`) 86 passed; the full suite
failure set is byte-identical to an `origin/master` worktree baseline in this
sandbox (59 failures/errors — all `test_signoff_integration` /
`test_merge_publish` / `test_hook_events`, all environmental, none
prompt-related).

## 19. Review-loop follow-ups (review loop 2ac8)

The PR was re-reviewed on the integrated branch (loop `2ac8`). Iteration 1
changed no production behaviour: it added the launcher-guard tests R15/§6 asks
for *as wired into* `launch_claude` / `launch_claude_print` /
`launch_claude_print_background` (the bootstrap argv, the prompt file's
lifetime, and the resume path writing nothing), and documented in
`bounded_text` the marker-overshoot postcondition `bounded_join` already
documented.

Iteration 2 found one behaviour defect, in `_render_pr_notes_bounded` (R2):

- **The newest note was not kept in full when the notes overflowed.** The
  function has two paths. When *every* note's one-line summary fits the budget
  it keeps all summaries and upgrades the newest notes to full text while the
  left-over room allows (the path §13 tightened the marker wording for). When
  the summaries do *not* fit it dropped the oldest summaries — and upgraded
  **nothing**, so the newest handoff arrived as a 200-char preview while
  hundreds of older previews survived. That inverts the ordering R2/A2
  prescribe ("keep the newest notes in full first; reduce older notes to a
  first-line summary") and the function's own docstring. Reachable: the branch
  needs the merged notes' one-line summaries to exceed 34,767 B (the 35,000 B
  budget minus the 13-byte header and the 220-byte marker reserve). A summary
  is 200 characters of *text* plus a timestamp, so its size depends on the
  script: 229 B for ASCII (flips at 152 notes) but 629 B for CJK (flips at 56
  notes) — and this repo already has PRs with 56 notes. (`pr-0b87a97`'s block
  measures 34,612 B, but that is the *fits* path inlining the newest notes'
  full text; its summaries total only 12,848 B, so it is not near the flip.)
  Fixed: the overflow path now upgrades the newest note to full text first and
  drops more of the oldest summaries to pay for it (skipping the upgrade only
  when the note is larger than the whole budget, in which case it stays a
  summary as before). The marker now also names the abbreviated count
  ("N older note(s) omitted and M abbreviated"), so a session reading previews
  is not left thinking they are verbatim — the same "marker must describe what
  the session is reading" rule §13 applied to the other path.
  Real prompts are unchanged: all 487 PRs' note blocks hash identically before
  and after (every real block is in the fits path).

  The other path is left as designed: when every note's summary *does* fit, it
  keeps all of them (its docstring's "every note stays represented") and spends
  whatever room is left on full text for the newest notes. A very long newest
  note can therefore still arrive as a summary — the marker says so (§13) and
  names the reader. Every real PR in this repo keeps its newest note in full
  (checked across all 487).

Checked and deliberately unchanged in this loop:

- **Single user-authored documents inlined outside `fit_prompt`.**
  `spec_gen._build_spec_prompt` inlines the PR description (real maximum 11 KB;
  measured max prompt over all 487 PRs × 2 phases is 38,209 B) and
  `plans.review.build_fix_prompt` inlines the review findings. Both are single
  documents, not collections, and both are delivered intact by the launcher's
  file-backed bootstrap if they ever exceed the limit.
- **`generate_watcher_prompt`'s managed/target lists** stay count-capped only
  (`WATCHER_MANAGED_MAX`). Auto-start targets are validated PR ids
  (`cli/autostart.py::_validate`), so 40 of them cannot approach the limit.
- **`prompt_gen`'s `_X = X` budget aliases** (and `cli/plan.py`'s
  `_PLAN_LIST_MAX`) remain: they are local names for the shared constants, no
  external caller imports them, and no value differs.

Filed rather than fixed (out of a prompt-bounding PR's scope): building a
prompt can still create `~/.pm/sessions/<tag>/captures/<pr-id>/` when an
omission marker *fires*, because the two pointer helpers resolve through
`paths.captures_dir()`, whose last resort creates the directory (and whose
`sessions_dir()` call creates `~/.pm/sessions/`). Making "building a prompt
never touches the filesystem" hold unconditionally needs the resolver split
into a non-creating resolution plus a separate create step — see the filed bug
PR.

## 20. Review-loop follow-ups (review loop 2ac8, iteration 3)

Iteration 3 re-ran the i5/i6/i7 method — check every omission marker against
what the session can actually do with it — over the *per-line* truncations the
audit introduced, not just the whole-block ones. Two markers described the
block they abbreviated inaccurately; both fixes are marker-text only, and no
budget, helper or launcher path changed.

- **The mocks marker named a command that does not return the text it
  promises.** `mocks_for_prompt`'s aggregate `bounded_text` marker read
  "Read the full text: `pm qa mocks list` (mock definitions under
  `pm/qa/mocks/`)". §7 changed that pointer from `pm qa list` (which does not
  list mocks) to `pm qa mocks list`, but `pm qa mocks list`
  (`pm_core/cli/qa.py::qa_mocks_list`) prints **ids, titles and descriptions
  only** — the bodies this bound cut are reachable through `pm qa mocks show
  <mock-id>` (`qa_mocks_show` prints the body) or the `pm/qa/mocks/` files the
  marker's parenthetical also names. QA scenario 7 recorded this as an
  observation ("worth a follow-up if the marker should name `pm qa mocks
  show`"); it is the same "name a *working* reader for the full detail"
  requirement (R7/A1) §7 enforced for the other three markers. The pointer is
  now `` `pm qa mocks show <mock-id>` (all definitions: `pm/qa/mocks/`) ``.
  The other three markers (`pm qa list`, `pm pr note list <id>`, `pm pr spec
  <id> qa`) already print the full text their builders omitted.
- **Truncated QA-scenario lines said nothing.** `_signoff_qa_scenarios_block`
  caps each scenario's title at 120 characters and its `verdict_reason` at
  `QA_SCENARIO_REASON_CHARS` (200) *per line*, but only the count cap had a
  marker: a QA run with fewer than `QA_SCENARIOS_MAX` (40) scenarios but long
  reasons showed 200-character previews with no note, so the sign-off session
  read abbreviated verdicts as if they were verbatim. That is the same
  "the marker must describe what the session is reading" rule §13 (the notes
  marker) and §19 (the overflow path's abbreviated count) apply, and the
  plan-deps description cap already carries such a note
  (`pm plan deps`: "Descriptions above are abbreviated ... run `pm pr show
  <id>`"). The block now appends, only when a line was really cut:
  "_(Scenario titles and reasons above are abbreviated to fit the prompt size
  limit; read `$CAP/scenarios/<n>/verdict.md` for the full verdicts.)_". It
  names `$CAP` — which this prompt's own evidence checklist defines — rather
  than resolving a path through `captures_dir`, because that resolver creates
  the captures directory as a side effect (§19's filed bug) and this note
  fires on a much weaker condition than the >40-scenario marker.

Verification: `tests/test_prompt_bounds.py` 102 cases (2 new, both
failing-then-passing — verified by stashing the source edits: the mocks marker
did not name a body-printing reader, and the truncated-scenario note was
absent; a third test guards the unchanged path, that short lines get no note).
Related suites (`test_prompt_bounds`, `test_bug_fix_flow_prompts`,
`test_plan_review`, `test_claude_launcher`, `test_regression_prompts`,
`test_spec_gen`, `test_signoff`, `test_qa_instructions`) 362 passed. Real-data
sweep over all 488 real PRs x 4 builders is byte-identical to §19's numbers
(impl 75,146 / review 77,616 / sign-off 92,165 / planner 80,652 B, max
`pr-0b87a97`): neither marker fires on this repo's data, and both only fire
when content was really abbreviated. Evidence: `/pm-captures/review-2ac8-i3/`.

## 21. Review-loop follow-ups (review loop 2ac8, iteration 4)

Iteration 4 re-ran the i7-i11 method (sweep every reachable builder, check
every omission marker in the environment the session reads it in) and then
audited the *delivery* paths rather than the builders. One gap, in the last
argv-entry prompt path this module owns.

- **`launch_bridge_in_tmux` had no size guard.** R15's guard covers
  `build_claude_shell_cmd`, `launch_claude`, `launch_claude_print` and
  `launch_claude_print_background`, but `pm cluster explore --bridged`
  (`pm_core/cli/cluster.py`) delivers its prompt through a fifth path in the
  same module: `launch_bridge_in_tmux` embeds the prompt in a shell command
  (`python3 -m pm_core.bridge <sock> --cwd '<cwd>' --prompt '<escaped>'`) run
  in a tmux pane, so the prompt is one argv entry to the bridge process and
  the pane's shell fails with a raw `Argument list too long` above
  `MAX_ARG_STRLEN` — exactly the field failure this PR exists to remove, in
  the module the guard lives in. Verified in this sandbox: `/bin/true` with a
  131,100-byte argument exits 126 with "Argument list too long"; 130,000 bytes
  still succeeds. No current caller passes a large prompt (the cluster-explore
  prompt is fixed text plus a temp-file path), so the practical risk today is
  nil — but the guard's stated purpose is "defense in depth for builders we
  did not audit and for future ones", and this path was unguarded.

  Fixed the same way as the other three: above `PROMPT_ARG_LIMIT` the complete
  prompt is written to a file (`_materialize_oversized_prompt`, which honours
  the host `write_dir` / container `cwd` split) and passed as
  `--prompt-file <path>`; the bridge reads it for its first turn and removes
  it, since the file is a one-shot handoff from the launcher. Under the limit
  the command is byte-identical to before (`--prompt '<escaped>'`).

Checked and deliberately unchanged in this iteration:

- **`pm_core/bridge.py`'s turn loop.** It sends each turn to `claude -p` over
  **stdin** (`--input-format stream-json`), not argv, so the bridge's *session*
  has no argv-size exposure — only the launcher's initial handoff did, which
  is the part fixed above.
- **`_materialize_oversized_prompt` vs the inline logic in
  `build_claude_shell_cmd`.** The two build the same file + bootstrap; the
  shell-command form additionally needs the file to be removed *after claude
  exits* (`; rm -f` in the same command string), which the helper's
  "caller deletes the returned path" contract cannot express. Left as-is.
- **The PR-notes *fits* path prefers "every note represented" over "newest in
  full".** When every note's one-line summary fits the budget, that path keeps
  all of them and spends the leftover room on full text for the newest notes
  (newest first); a note too big for the leftover room therefore still arrives
  as a 200-character preview, with the marker saying so and naming
  `pm pr note list`. A property probe over note counts (1-1000), note sizes
  (10 B-5 KB) and ASCII/CJK text found this is the only case where a note that
  *could* fit the budget is not upgraded: e.g. 150 short notes plus one 30 KB
  newest note, or 50 CJK notes whose 200-character summaries already total
  31 KB of the 35 KB budget. §19 records the same trade-off; the marker covers
  it, and on this repo's data (all 488 PRs) the newest note is always in full,
  so it is left as designed.
- The other deliberate decisions recorded in §10, §14, §19 and §20
  (`build_regression_test_prompt`'s body, single user-authored documents,
  the watcher managed/target lists, the `_X = X` budget aliases,
  `PromptTooLargeError` being uncaught at pane/CLI call sites → pr-a42a4f8).

Verification: `tests/test_prompt_bounds.py` 107 cases (5 new) and
`tests/test_claude_launcher.py` 37 cases (2 new) — 6 of the new ones
failing-then-passing, verified by stashing the two source edits (the oversized
bridge prompt was passed as a 150 KB shell argument, and `--prompt-file` was
not parsed at all). The whole path was exercised end to
end in this sandbox with a stub `claude` on `PATH`: the launcher's command
string delivers a 150,016-byte prompt intact to the bridge's first turn
(`delivered bytes: 150016 | matches full prompt: True`) and the prompt file is
gone afterwards. Real-data sweep over all 488 real PRs × 4 builders is
byte-identical to §19's numbers (impl 75,146 / review 77,616 / sign-off 92,165
/ planner 80,652 B, max `pr-0b87a97`); a full-text diff of those 4 builders ×
7 real PRs against an `origin/master` worktree shows only the intended
differences (the 25-sibling plan-context cap, the 35 KB PR-notes budget and
their markers). Full-suite failure set compared against an `origin/master`
worktree baseline in the same sandbox. Evidence: `/pm-captures/review-2ac8-i4/`.

## 22. Review-loop follow-ups (review loop 2ac8, iteration 5)

Iteration 5 re-ran the i7-i11 method (sweep every reachable builder, then check
what each omission marker tells the session) and found one marker that
over-counted its own abbreviations.

- **`_render_pr_notes_bounded`'s overflow marker called verbatim notes
  "abbreviated".** The marker reads "N older note(s) omitted and M abbreviated"
  — the wording §19/i2 introduced so a session reading previews knows they are
  previews — but M was computed as "every kept line but the upgraded newest". A
  note short enough to survive `summary_line` unchanged
  (`_PR_NOTE_SUMMARY_CHARS` = 200) renders *identically* as a summary and in
  full, so those kept lines are the note's complete text, and the marker still
  counted them as abbreviated. Repro: 400 notes of 100 characters (every
  summary == its full line) renders `... (143 older note(s) omitted and 256
  abbreviated to fit the prompt size limit ...)` while all 257 kept lines are
  verbatim; a mixed block (the newest 100 notes short, the older 300 long)
  claimed 233 against 134 lines really cut. Reachable exactly when the merged
  one-line summaries overflow the budget — the ~150-note (~56-note CJK) branch
  §19/i2 measured for this path, since the notes that trigger it are the short
  ones with small summaries. M is now the number of kept lines that really
  differ from their note's full text, and the "and M abbreviated" clause is
  dropped when that count is zero.

  The *fits* path's fixed wording ("older notes are abbreviated" / "notes are
  abbreviated", §13/§19) is entailed whenever it fires — entering that path
  requires the full rendering to exceed the budget while the summaries fit, so
  at least one kept line is a real preview. A property sweep of both paths
  (2 scripts × 10 note counts × 11 note sizes × 3 short/long mixes, ASCII and
  CJK) now finds no marker that misdescribes the block, no claimed count that
  differs from the real one, no over-budget block, no newest note left as a
  preview when it had room, and no non-determinism.

- **The new `pm pr show` and the existing `pm pr note list` printed a note with
  the same three lines of formatting.** Both are on-demand readers for the
  PR-notes block, so a divergence between them would be a marker that lies. The
  snippet now lives in `cli/pr.py::_note_line`, used by both (output unchanged;
  both commands re-run against a throwaway project).

- **`fit_prompt`'s docstring named only one of the two reasons it returns the
  untouched render** ("the static text alone is over it"). The loop also returns
  it when the blocks cannot give up enough while staying at `min_bytes` — the
  behaviour §16/i10 implemented ("the same happened when the blocks *could* be
  shrunk but not enough"). Docstring only; no behaviour change.

Checked and deliberately unchanged: the `pm pr note list <pr-id>` marker's
concrete id (§12), the `$CAP`-based truncated-scenario note (§20), and the
trade-offs recorded in §10, §14, §19, §20 and §21.

Verification: `tests/test_prompt_bounds.py` 109 cases (2 new, both
failing-then-passing — the verbatim case failed on `assert "abbreviated" not in
block` with "256 abbreviated" in the text, the mixed case on
`assert 233 == 134`) and `tests/test_claude_launcher.py` 37 cases; the related
suites (`test_plan_review`, `test_bug_fix_flow_prompts`,
`test_regression_prompts`, `test_spec_gen`, `test_signoff`,
`test_qa_instructions`) 371 passed together.

Independent re-verification this iteration (not a re-read of §19-§21):

1. Real-data sweep over all 488 PRs × 4 builders — no builder over
   `PROMPT_ARG_LIMIT` (max impl 45,883 / review 47,305 / sign-off 61,576 /
   planner 50,315 B). The absolute sizes are lower than §19's host numbers
   because this sandbox has no `~/.pm/workdirs` clones for the builders to merge
   workdir notes from, so the meaningful comparison is branch vs `origin/master`
   *in the same sandbox*: 205 PRs byte-identical across all four builders, and
   the only PRs where the branch is larger are `pr-ace66e5` and `pr-0368986`
   (this PR's own project.yaml notes); every other difference is an intended
   cap. A capped PR (`pr-8e693f6`) diffs against master only in the PR-notes
   block (newest full, older abbreviated, marker naming
   `pm pr note list pr-8e693f6`) and the 25-sibling plan-context block (marker
   naming `pm pr list --plan plan-regression`).
2. Pathological fixture that maxes every collection at once (40 KB description,
   400 notes, 200 KB impl + QA specs, 400 long-title siblings, 25 plans with
   100 KB files, 60 KB `notes.txt`, 200 items per QA library category with 3 KB
   descriptions, 5 mocks with 80 KB bodies, 40 × PATH_MAX worktrees, 500 long
   lines of pane output, 50 artifacts): every reachable builder is under the
   limit — the four `fit_prompt` builders land at 117,189 / 119,700 / 119,700 /
   119,700 B, QA interactive 44,748, QA child 75,773, concretization 49,465,
   verification 91,506, finalize 21,653, merge 29,574, watcher 17,305,
   watcher-review 3,691, library 6,239, mocks 12,000, guide 18,820, notes 8,000.
3. The launcher bridge path (§21) re-exercised end to end with a stub `claude`
   on `PATH`: a 324-byte launcher command delivered a 150,016-byte prompt
   intact to the bridge's first turn and removed the file (one-shot handoff).
4. Every omission marker re-checked against a *registered* command
   (`pm pr show`, `pm pr note list`, `pm pr spec`, `pm pr graph`,
   `pm pr list --plan`, `pm qa list`, `pm qa mocks show`, `pm qa captures-path`,
   `pm plan list`, `pm autostart list`), with the two prompt-side readers
   smoke-tested in a throwaway project: `pm pr show` prints description, notes
   and the integration record (so the integration marker's fallback is not a
   dead end) and `pm pr note list` prints the notes.
5. Mutation checks: making `pm_core.bridge` ignore `--prompt-file` fails 3 of
   the bridge tests, and dropping the guard from `launch_bridge_in_tmux` fails
   its over-limit test — the §21 tests fail for the right reason.
6. Full-suite failure set identical to an `origin/master` worktree baseline run
   with the same environment in this sandbox (1 failure — the documented
   environmental `test_hook_events::test_installer_writes_standalone_receiver`,
   pr-4bde874; 3478 vs 3367 passed, the delta being this PR's new tests). The
   `markdown` dependency pyproject declares was installed into a scratch
   `PYTHONPATH` target for both runs, so `test_markdown_render` passes on both.

Evidence: `/pm-captures/review-2ac8-i5/` (`sweep.py`, `sweep_master.py`,
`sizes-branch.txt` / `sizes-master.txt`, `pathological.py` + `.txt`,
`full-suite-branch.txt`, `full-suite-master.txt`).
