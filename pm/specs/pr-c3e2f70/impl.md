# Impl spec — pr-c3e2f70: short briefs for review/QA waiting on INPUT_REQUIRED

Status: **awaiting user review** (do not implement until approved).

Prompt artifacts (review these with the spec):

- [`brief_prompt.md`](brief_prompt.md) — the complete candidate prompt text,
  including every composed instruction.
- [`brief_prompt_example.md`](brief_prompt_example.md) — a representative
  rendered prompt (composed eligibility payload + real PR context) and its
  example short brief.

## Problem (grounded)

A review or QA loop that ends a turn with `INPUT_REQUIRED` pauses until a human
answers it in the loop pane. The state exists, but the age does not, and no
surface tells the user what the question is without reconstructing it from the
pane/notes.

- **Review wait.** `ReviewLoopState.input_required`
  (`pm_core/review_loop.py:85`) is set while the loop polls the existing review
  pane for a follow-up verdict (`review_loop.py:380-395`). The loop stays
  `running` and the TUI keeps it in `app._review_loops`, but nothing records
  *when* the wait started.
- **QA whole-run wait.** A finished QA run whose overall verdict is
  `INPUT_REQUIRED` is a terminal wait: the scenarios stay open for inspection
  and the user must answer/decide (`pm_core/qa_loop.py:4332-4334`, plus the
  early-return paths at `qa_loop.py:4048,4148,4176`). The run leaves
  `app._qa_loops` one tick after completion; its verdict survives in
  `runtime_state` as a `qa` action with `state: done`
  (`pm_core/tui/qa_loop_ui.py:374-384`), and `collect_status_inputs`
  synthesizes a `recorded` entry from it
  (`pm_core/tui/auto_start.py:1097-1104`). No timestamp of the wait is kept.
- **Existing status surface.** `build_status`
  (`pm_core/autostart_state.py:551`) already reports the waiting state per PR:
  `run.review.input_required`, `run.qa.verdict`, `run.phase`, `run.status`,
  `run.window`, and the reason strings in `_derive`
  (`autostart_state.py:473-525`). `pm autostart status --json`
  (`pm_core/cli/autostart.py:368-392`) exposes that dict; the watcher prompt
  already tells the watcher to run `pm pr list`, capture panes, etc.
- **No brief exists.** Nothing reads the PR description/notes/discussion and
  prepares a short, plain-language summary of the question and options.

## Requirements (grounded in code)

- **R1 — Record the review wait age.** Add `input_required_since: str = ""` to
  `ReviewLoopState` (`review_loop.py:71-85`). Set it to a UTC ISO timestamp
  when `state.input_required = True` (`review_loop.py:383`); clear it when the
  follow-up verdict is consumed (`review_loop.py:389`). Do not overwrite an
  existing value on re-entry (restart/adoption re-runs the same wait).
- **R2 — Record the QA wait age.** Add `input_required_since: str = ""` to
  `QALoopState` (`qa_loop.py:185-239`). A helper marks the whole-run
  `INPUT_REQUIRED` verdict and stamps the time only if empty; call it at the
  five whole-run sites (`qa_loop.py:4048,4094,4148,4176,4334`). Persist it in
  `qa_resume.json` (`_write_resume_file`, `qa_loop.py:872`) and restore it in
  `build_resume_state` (`qa_loop.py:1023`).
- **R3 — Carry the age through the existing status.** `review_progress_input`
  and `qa_progress_input` (`autostart_state.py:819-840`) expose
  `input_required_since` (and the evidence locator: review `transcript_dir`,
  QA `workdir`). `build_status` adds `input_required_since` to each run's
  `review`/`qa` sub-dicts. These are additive fields on the existing
  `pm.autostart.status/1` dict; the schema string does not change.
- **R4 — Compute eligibility deterministically.** A new
  `pm_core/input_brief.py` derives, from the status runs + PR records, the list
  of briefs that are due: review `input_required` or QA overall
  `INPUT_REQUIRED`, wait age ≥ 300 s, PR status `in_review`/`qa`, phase
  `review`/`qa` (this excludes sign-off and merge approval waits). Each entry
  carries the PR identifier, `gh_pr` URL, window name, evidence path,
  fingerprint, existing brief note id (if any), and `needs_brief`.
  `build_status` returns this list as the additive `input_briefs` field.
- **R5 — Brief generation prompt.** Extend `generate_watcher_prompt`
  (`pm_core/prompt_gen.py:1404`) with one new section, copied **verbatim** from
  [`brief_prompt.md`](brief_prompt.md). It tells the watcher to read
  `pm autostart status --json` → `input_briefs`, and for each entry with
  `needs_brief: true` to read `pm pr show` / `pm pr note list` / the loop pane
  or evidence file and write a ~150-word plain-language brief answering the
  three generic questions, with the PR identifier and a link to the original
  question/evidence. The options discussion weighs the simplest sufficient
  approach, maintenance/code quality, user impact, and delivery. Estimates may
  only come from observed project history.
- **R6 — Store the brief on an existing note surface.** The brief is a PR note
  (`pm pr note add` / `pm pr note edit`, `pm_core/cli/pr.py:3292-3375`). Its
  first line is a parseable marker
  (`[input-brief] pr=… phase=… wait-since=… fp=…`), and it ends with a fixed
  "recommendation only" line. PR notes are already rendered by
  `pm pr show` / `pm pr note list` and injected into later session prompts, so
  the brief is reused for the intervention discussion that follows.
- **R7 — No duplicate unchanged brief.** `needs_brief` is false when a
  `[input-brief]` note already exists for the same `wait-since` and
  fingerprint (review: `review:<iteration>`; QA: `qa:<verdict>:<done>/<total>`).
  A new wait (different `wait-since`) gets a new note; a changed fingerprint
  within the same wait refreshes the existing note via `pm pr note edit`.
- **R8 — Preserve state and gates.** The only mutation is the note write.
  `pm pr note add/edit` updates `updated_at` (via `_record_status_timestamp`,
  `pm_core/cli/helpers.py:446`) and nothing else. The prompt forbids sending
  keys to the loop pane, answering the question, restarting the loop, changing
  PR status, or running sign-off/merge commands. Brief generation never
  changes the watcher's verdict (always `READY`).
- **R9 — Restart survival.** The review wait age is saved/restored in the TUI
  breadcrumb (`save_breadcrumb`/`consume_breadcrumb`,
  `pm_core/tui/auto_start.py:161-299`); on restore without a saved value it is
  derived from the last `INPUT_REQUIRED` history entry. The QA wait age is
  mirrored on the `done` runtime_state write (`qa_loop_ui.py:381`) and read
  back in `collect_status_inputs` for the `recorded` case (falling back to the
  action's `updated_at`).
- **R10 — Tests.** See "Tests" below.

## Implicit requirements

- **I1 — No new session or model invocation.** The brief is written by the
  existing auto-start watcher session (one per ~120 s iteration). No new
  `claude -p`, no new watcher type, no new pane.
- **I2 — Backward-compatible status.** `input_required_since` and
  `input_briefs` are additive; existing consumers (`status_rows`,
  `format_text`, the runs popup) ignore them. Missing timestamps never raise.
- **I3 — One clock, UTC.** All new timestamps are UTC ISO with an offset;
  parsing tolerates absent/malformed values by treating the wait as
  ineligible.
- **I4 — Deterministic eligibility.** Python decides *whether* a brief is due
  and *whether* it is unchanged; the LLM only writes the prose. This keeps QA
  reproducible and keeps the prompt from encoding status logic.
- **I5 — Concurrent-safe writes.** The note write goes through the existing
  `store.locked_update` path in `pm pr note`; the watcher never edits
  `project.yaml` directly.
- **I6 — Reviewed text ships verbatim.** The prompt section lives in
  `prompt_gen.py` as a module constant equal to the reviewed text in
  `brief_prompt.md`; a test asserts its key clauses (threshold, exclusions,
  marker, recommendation-only line).
- **I7 — The waiting loop is untouched.** No `tmux send-keys` into the review
  or QA window, no pane kills, no status transitions.

## Ambiguities and resolutions

- **A1 — Where does the brief live?** PR note (chosen) vs `report.html`
  (sign-off-owned; would confuse the verdict meta and the gate) vs a new
  `pm/briefs/` file (new surface). **Resolution:** PR note — it is the
  documented handoff surface, appears in `pm pr show` / `pm pr note list`, and
  is injected into later prompts, which is exactly the "reuse it for
  intervention discussions" requirement. Tradeoff accepted: notes are
  git-tracked and consume a bounded slice of the prompt notes budget (~150
  words).
- **A2 — Who generates it?** A dedicated `pm brief` session would add pane
  management and a new lifecycle; the review/QA pane is blocked on the user
  and must not be disturbed. **Resolution:** the existing auto-start watcher
  session (prompt-only change). It already runs periodically, already handles
  loop `INPUT_REQUIRED`, and needs no new process.
- **A3 — Which PRs are eligible?** Deriving loop state independently of the
  scheduler would duplicate state readers. **Resolution:** eligibility is the
  auto-start status scope (`runs`). With auto-start off (mode `off`) there are
  no runs and therefore no briefs; manual-only loops are out of scope. This
  keeps the feature on existing surfaces, as the task asks.
- **A4 — Where does the age come from?** Review history has naive local
  timestamps that are replaced when a follow-up arrives; QA has no single
  timestamp. **Resolution:** an explicit `input_required_since` on both states,
  stamped when the wait begins, preserved across restarts. "Existing waiting
  state" is still the source; the age is added to it.
- **A5 — Is a finished (recorded) QA run a wait?** Yes: overall
  `INPUT_REQUIRED` means the user must act (answer or re-run). **Resolution:**
  include it; the age comes from the mirrored `input_required_since` (fallback:
  the `done` action's `updated_at`).
- **A6 — What counts as "the same unchanged brief"?** Per PR would hide a new
  question; per question text is fuzzy. **Resolution:** per wait
  (`wait-since`) plus a deterministic fingerprint (review iteration; QA
  verdict + scenario counts). The prompt additionally allows a refresh when
  the watcher judges the question materially changed.
- **A7 — Waits with no parseable age.** **Resolution:** skip them (do not
  guess); debug-log the malformed value. A brief without a real age would
  violate the 5-minute rule.
- **A8 — Configurable threshold?** **Resolution:** fixed 300 s constant
  (`input_brief.BRIEF_THRESHOLD_SECONDS`); no setting, no per-PR override.
- **A9 — New UI?** **Resolution:** none. The note is the user surface; the
  status JSON carries eligibility for the watcher.
- **A10 — Multiple eligible PRs in one iteration.** **Resolution:** brief all
  of them, each short; unchanged ones cost only the status read.
- **A11 — Eligibility in Python or in the prompt?** The prompt could read
  `runs` and apply the 5-minute rule and dedup itself. **Resolution:** Python
  (`input_brief.build_input_briefs`) decides eligibility and `needs_brief`;
  the prompt only writes prose. Reasons: the validation must show that
  shorter waits and sign-off/merge waits produce nothing (a deterministic
  filter, not model judgment); dedup must not depend on the model re-reading
  notes; and the prompt stays short. The status JSON remains the existing
  surface the watcher reads.

## Edge cases

- **E1 — Review loop restarts during the wait.** Breadcrumb restore keeps
  `input_required_since`; re-entering the wait does not overwrite it, so the
  age (and dedup) survive a TUI restart.
- **E2 — User answers between status and note write.** The note records the
  question as it stood; the next status has no entry, so no further briefs.
  The note stays as accurate history.
- **E3 — QA resumes after a TUI restart.** `qa_resume.json` restores the age;
  a finished run uses the runtime_state mirror. A restart does not reset the
  5-minute clock.
- **E4 — PR advances while a brief is written.** Eligibility is computed at
  status build; the note write is idempotent and changes no state. The brief
  may describe a wait that just ended — acceptable, and the marker's
  `wait-since` makes that visible.
- **E5 — Hand-edited/malformed notes.** The marker parser tolerates missing
  fields and non-string text; a malformed note is treated as "no brief".
- **E6 — Several briefs on one PR.** The newest note matching the current
  `wait-since` is the one refreshed; older briefs remain history.
- **E7 — No TUI owner / auto-start off.** `pm autostart status --json` fails or
  returns no runs; the watcher skips briefs and emits `READY`. It never
  guesses eligibility.
- **E8 — Two watchers running.** Both may see `needs_brief` on the same
  iteration and append a note. `pm pr note add` is append-only; a duplicate
  brief is harmless and the marker prevents repeats after the first write.
  (No new locking is added.)
- **E9 — Sign-off/merge approval waits.** `SIGNOFF_BLOCKED`, a stale
  sign-off, and merge-window `INPUT_REQUIRED` are excluded by the
  status/phase filter even if some loop state carries a timestamp.
- **E10 — Clock skew / naive timestamps.** Unparseable or future timestamps
  are ineligible; no negative ages.

## Implementation plan (after approval)

| File | Change |
|---|---|
| `pm_core/input_brief.py` (new) | `BRIEF_MARKER`, `BRIEF_THRESHOLD_SECONDS=300`, `parse_brief_marker()`, `latest_brief(notes)`, `brief_fingerprint(run)`, `build_input_briefs(runs, pr_map, review_loops, qa_loops, now)` |
| `pm_core/review_loop.py` | `ReviewLoopState.input_required_since`; stamp/clear around the follow-up wait; never overwrite on re-entry |
| `pm_core/qa_loop.py` | `QALoopState.input_required_since`; `_mark_input_required(state)` at the five whole-run sites; persist/restore in `qa_resume.json` |
| `pm_core/tui/qa_loop_ui.py` | mirror `input_required_since` on the `done` runtime_state write |
| `pm_core/tui/auto_start.py` | breadcrumb save/restore of the review age (with history fallback); recorded-QA entry reads the age from runtime_state |
| `pm_core/autostart_state.py` | summaries expose `input_required_since` (+ evidence dirs); run sub-dicts expose it; `build_status` adds `input_briefs` |
| `pm_core/prompt_gen.py` | new "Input-Required Briefs" section (verbatim from `brief_prompt.md`), renumber the following sections |
| `tests/test_input_brief.py` (new) + existing test files | see below |

The watcher prompt section is inserted after "Surface Issues Needing Human
Input" as section 4; the following sections renumber (4→5, 5→6, 6→7). No test
asserts the section numbers (they assert titles).

## Prompt artifacts

- Complete prompt text: [`brief_prompt.md`](brief_prompt.md).
- Rendered example + example brief:
  [`brief_prompt_example.md`](brief_prompt_example.md).

## Tests

- `tests/test_input_brief.py`
  - marker parse/format round-trip; malformed notes tolerated;
  - threshold: 299 s → ineligible, 300 s → eligible, 301 s → eligible;
  - review wait and QA whole-run wait both eligible; QA running / other
    verdicts ineligible;
  - `sign_off`/`merge` phases and statuses ineligible;
  - dedup: same wait+fp → `needs_brief` false; same wait+new fp → true with
    `note_id`; new wait → true with `note_id` null;
  - entry fields (`display_id`, `gh_pr`, `window`, `evidence`).
- `tests/test_autostart_state.py` (or the existing status test module):
  `build_status` exposes `input_required_since` and `input_briefs`; existing
  status output/tests unchanged.
- `tests/test_review_loop.py`: stamp on `INPUT_REQUIRED`, clear on follow-up,
  preserved on re-entry/restart.
- `tests/test_qa_loop.py`: stamp once; resume round-trip.
- `tests/test_auto_start.py`: breadcrumb round-trip of the review age.
- `tests/test_watcher_loop.py`: the prompt contains the brief section, the
  5-minute threshold, `input_briefs`, the marker, the recommendation-only
  line, and the sign-off/merge exclusion.

## Validation (QA scenarios, after implementation)

1. **Review wait.** A review loop waiting on `INPUT_REQUIRED` with a 6-minute
   `input_required_since` appears in `pm autostart status --json` →
   `input_briefs` with `needs_brief: true`; the watcher writes a
   `[input-brief] …` PR note; the next status reports `needs_brief: false`
   and no second note is added.
2. **QA whole-run wait.** The same for a finished QA run whose overall verdict
   is `INPUT_REQUIRED` (both the live and the recorded/restart paths).
3. **Negative.** A 4-minute wait and a sign-off/merge approval wait produce no
   `input_briefs` entry and no note.
4. **Quality.** The brief is ~150 words, plain language, names the PR and links
   the question/evidence, and summarizes the options/tradeoffs accurately.
5. **Gates.** After brief generation the PR status, sign-off record, QA
   verdict, and loop panes are unchanged; no keys were sent to the loop pane;
   the watcher's verdict remains `READY`.

## Non-goals

- No resolved/unresolved classification, decision workflow, or answer capture.
- No answering the question, resuming loops, waiving QA, or authorizing merges.
- No new watcher type, pane, CLI session, or configurable threshold.
- No briefs for sign-off/merge approval waits, implementation waits, or
  manual loops outside the auto-start status scope.
