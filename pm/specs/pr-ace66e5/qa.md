# QA spec — pr-ace66e5: Audit prompt builders for unbounded enumeration

Grounded in `pm/specs/pr-ace66e5/impl.md` (requirements R1–R16 plus the
review-loop follow-ups in §7–§17, which supersede §1 where they differ) and
the diff against master:

- `pm_core/prompt_bounds.py` (new) — `PROMPT_ARG_LIMIT`, budgets,
  `bounded_join` / `bounded_text` / `bounded_lines` / `fit_prompt`,
  `PromptTooLargeError`.
- `pm_core/claude_launcher.py` — file-backed bootstrap guard in
  `build_claude_shell_cmd`, `launch_claude`, `launch_claude_print[_background]`.
- `pm_core/prompt_gen.py`, `pm_core/spec_gen.py`, `pm_core/notes.py`,
  `pm_core/signoff.py`, `pm_core/integration.py`, `pm_core/qa_instructions.py`,
  `pm_core/qa_loop.py`, `pm_core/qa_finalize_prompt.py`, `pm_core/guide.py`,
  `pm_core/cli/plan.py`, `pm_core/cli/pr.py` (`pm pr show`).

## 0. The bug being fixed

`claude` receives a session prompt as **one `argv` entry**. Linux caps a
single argument at `MAX_ARG_STRLEN` (131 072 B), so an oversized prompt makes
`execve` fail with `OSError [Errno 7] Argument list too long`. Field
reproductions (PR notes):

- `pm plan review` inlined 39 PR descriptions (~150 KB) → E2BIG.
- QA planner prompt 149 760 B on #229 → planner window exited before
  discovery, QA reported "Could not find planner pane", zero scenarios.
- On #249 review 131 175 B / sign-off 144 144 B / QA planner 134 900 B.

The old `<workdir>/pm/prompts/<f>.txt` + `"$(cat file)"` trick does **not**
help: command substitution still expands to one oversized argv entry.

Fix, in two halves:

1. **Bounded builders** — every place that enumerated a collection (or
   inlined a single large document) into a prompt now caps count *and* bytes,
   summarises older elements, and appends an omission marker naming a command
   or path that returns the omitted text. `fit_prompt` composes the per-block
   budgets so their *sum* plus static text also fits.
2. **Launcher guard (defense in depth)** — when a prompt is still over the
   limit, the *complete* prompt is written to a file and a short bootstrap
   argv ("your complete instructions are in <file>") is passed instead; with
   no writable location it raises `PromptTooLargeError` with the measured
   size instead of a raw `E2BIG`.

**Reproduction test in the diff:** `tests/test_prompt_bounds.py` (93 cases),
notably `TestBudgetCoordination` (the four builders that E2BIG'd, with every
block at its budget, now fit), `TestLauncherGuard`
(`test_shell_cmd_uses_bootstrap_over_limit`, `test_shell_cmd_no_writable_dir_raises`),
and `TestPlanPromptBounding` / `TestPlanDepsAndFixBounding`.

## 1. Requirements (Given / When / Then)

### A. Plan commands (the original E2BIG)

- **R1 — `pm plan review` on a big plan.** Given a plan with ~40 loaded PRs
  whose descriptions are several KB each, When the user reviews the plan,
  Then the command completes without `Argument list too long`, the prompt the
  session is handed is well under 128 KiB, and where descriptions were
  dropped the prompt says the list is abbreviated and names
  `pm pr show <id>`.
- **R2 — `pm plan review`'s on-demand reader exists.** Given that prompt,
  When the user runs `pm pr show <id>` for an abbreviated PR, Then the full
  description (and tests/files/notes) is printed — the fallback is not a dead
  end.
- **R3 — `pm plan deps` on a big project.** Given 40+ PRs with large
  descriptions *and* 20+ plan files totalling ~500 KB, When the user runs
  `pm plan deps`, Then the prompt stays under the limit, per-PR descriptions
  are abbreviated with a `pm pr show` pointer, and the plan-file context is
  bounded with a pointer at the plan paths.
- **R4 — `pm plan breakdown` / `pm plan fix`.** Given the same project, When
  the user runs plan breakdown (existing-PR listing) and applies a review fix
  (which concatenates every plan file), Then neither prompt exceeds the limit
  and each names where the full text lives.
- **R5 — Plans with many PRs but no huge descriptions still review in
  full.** Given a plan whose PRs have ordinary descriptions but which exceeds
  the limit only in aggregate, When the user reviews it, Then the fallback
  still lists every PR (one line each) rather than truncating mid-list.

### B. PR session prompts (impl / review / sign-off)

- **R6 — PR notes.** Given a PR with ~60 notes of a few KB each, When the
  user prints/generates its session prompt, Then the prompt is under the
  limit, the *newest* notes are present verbatim, older notes are reduced to
  one-line summaries, and a marker names `pm pr note list <pr-id>` — which
  prints every note in full.
- **R7 — Spec, session notes, deps, sibling PRs.** Given a PR with a ~50 KB
  implementation spec, a large `pm/notes.txt`, many dependencies, and many
  sibling PRs with long titles in the same plan, When the session prompt is
  generated, Then each block is bounded, and the markers name `pm pr spec
  <pr-id> impl`, `pm/notes.txt` / `pm/notes-local.txt`, `pm pr graph`, and
  `pm pr list --plan <plan>` respectively. The session-notes marker must name
  a *readable file*, not `pm notes` (which opens an interactive editor and
  yields no text).
- **R8 — Review and sign-off panes.** Given a PR with heavy history and a
  workdir, When the user opens the review window and then the sign-off
  window, Then both panes start their session (no `Argument list too long`),
  and each session receives a complete prompt: the review verdict list and
  the sign-off routing verdicts are intact, and every abbreviated block names
  a readable source.
- **R9 — Sign-off QA + integration blocks.** Given a QA run with many
  scenarios (long verdict reasons) and an integration record with many
  overlap/conflict paths, When the sign-off prompt is built, Then the
  scenario listing and both path listings are bounded with markers naming the
  captures dir / `pm qa captures-path` / the integration record, and
  `pm pr show <pr-id>` prints the integration record so the fallback works.

### C. QA prompts (the field failure)

- **R10 — QA instruction library.** Given a QA library with many
  instructions/regressions/artifacts whose frontmatter descriptions are
  multi-KB, When the QA planner prompt is built, Then it stays under the
  limit and its marker names `pm qa list`, which lists the whole library.
- **R11 — Mocks.** Given large mock definitions, When the mocks block is
  injected, Then it is bounded and its marker names `pm qa mocks list` (which
  lists mocks — `pm qa list` does not).
- **R12 — Planner pane starts.** Given that project, When the user starts the
  QA loop for a PR, Then the planner pane launches and its session receives
  the complete planner instructions (task, scenario format, QA_PLAN markers)
  within the argv limit — the field symptom was the planner window dying
  before discovery with zero scenarios.
- **R13 — QA child / concretization / verification prompts.** Given a
  scenario referencing a very large instruction file, a scenario with very
  long steps, and a scenario whose pane output is a huge transcript, When the
  loop runs those steps, Then each prompt is bounded and each marker points
  at the instruction file, the QA plan, or the transcript.

### D. Launcher guard

- **R14 — Over-limit prompt is delivered intact.** Given a prompt that cannot
  be bounded (a QA regression test whose *body is the prompt*) larger than
  128 KiB, When the user runs it, Then the session starts, the argv it
  receives is small and names a file, that file contains the *complete*
  prompt (every instruction preserved — no truncation), and the file is
  removed once the session exits.
- **R15 — No writable location.** Given the same oversized prompt on a launch
  path with no writable directory, When the user runs it, Then the failure
  names the prompt size and the 120 000-byte limit — it is never
  `OSError [Errno 7] Argument list too long`, and the prompt is never
  silently truncated. (The raw traceback presentation of that error is
  tracked separately as pr-a42a4f8 and is out of scope here.)
- **R16 — Under-limit launches unchanged.** Given an ordinary prompt, When
  any session launches, Then behaviour is as before (no bootstrap, no temp
  file left behind).

### E. New command and no-regression

- **R17 — `pm pr show`.** Given a PR, When the user runs `pm pr show <pr-id>`,
  Then it prints id/title/status/plan/branch/workdir/GitHub, dependencies,
  and the description, tests, files and notes sections; with an integration
  record it also prints target/base/status, the overlap and conflict path
  lists, and where the full record lives. An unknown id errors clearly.
- **R18 — Small projects are untouched.** Given a project with one PR, a
  short description, one note, no big spec and small notes, When the user
  prints its prompt, Then it is a few KB, contains the full description and
  note verbatim, and contains **no** truncation/omission markers.
- **R19 — Deterministic output.** Given the same project state, When a prompt
  is generated twice, Then the two are byte-identical.

### F. Concurrency

- **R20 — Parallel launches.** Given two (or more) sessions launched at
  nearly the same time from the same project, When both start, Then each
  receives its own prompt (no cross-contamination), the prompt files under
  `<workdir>/pm/prompts/` are distinct, neither launch deletes the other's
  file while it is in use, and no prompt file is left behind after the
  sessions exit.

## 2. Setup (user steps)

1. Install pm from the PR's clone (`./install.sh --local` or
   `pip install -e .` from the repo), then `export PYTHONPATH=<clone>` so
   `pm which` points at the clone, not a preinstalled copy.
2. Create a throwaway project: `mkdir -p $TEST_DIR && cd $TEST_DIR &&
   git init && pm init --backend local --no-import`.
3. Build the *large* fixture through the CLI so the state is one a real old
   project would have:
   - a plan: `pm plan import --name "Big plan"` creates the plan file, then
     write a `## PRs` section with ~40 `### PR:` entries whose
     `**description**` fields are a few KB each, then `pm plan load <plan-id>`;
   - extra plans so plan-file context is large (a few hundred KB total);
   - notes: a loop of `pm pr note add <pr-id> "<a few KB of text>"` to reach
     ~100 KB on one PR;
   - a large `pm/notes.txt` section (the file the notes editor writes);
   - a large `pm/specs/<pr-id>/impl.md`;
   - sibling PRs in the same plan with long titles;
   - a QA library: many files under `pm/qa/instructions|regression|artifacts`
     with long frontmatter descriptions, plus large `pm/qa/mocks/*`.
   Seeding with shell loops over `pm` CLI commands is fine; hand-editing
   `pm/project.yaml` is bootstrap-only and should be avoided except to set a
   status the CLI cannot reach directly (e.g. moving a PR to `qa` for the
   sign-off step).
4. Start the pm tmux session from a shell whose PATH already includes the
   stand-in `claude` directory, so panes inherit it: `pm session` (ignore the
   attach failure — no TTY).
5. **Stand-in claude.** Where a scenario must observe what a *session* was
   handed, put an executable `claude` early on PATH that records its argv
   (count, total bytes, and the last argument — which for the `$(cat file)`
   form *is* the whole prompt) and, when the last argument names a file,
   copies that file. Exit 0. This is the same idea as the bundled
   `fake-claude` (see the TUI instruction) but it preserves the prompt, which
   `fake-claude` does not (it drops the prompt from argv entirely).
   `fake-claude` remains the right tool when the scenario only needs a loop
   to reach a verdict.

## 3. Edge cases

- **Empty / single-element collections** — no marker, no stray separator.
- **Multi-byte text** — emoji/CJK notes must not be cut mid-character and
  must be measured in bytes.
- **Exactly at the limit** — `>` is over-limit; `==` is allowed.
- **Container sessions** — markers that name a path must name one the
  *session* can open: project-relative (`pm/notes.txt`), a bind-mount
  (`/pm-captures/...`), or a command. A host-absolute path under the user's
  home is a broken pointer inside a container.
- **Markers must be actionable** — `pm notes` (interactive editor),
  `pm qa status` and `pm qa list` (does not list mocks) were all named by
  markers in earlier revisions and were dead ends.
- **Resume launches** — no prompt is passed on resume; the guard must not
  fire or write a file.
- **Repeated generation** — building a prompt must not create the PR's
  captures directory as a side effect.
- **A single note bigger than the whole notes budget** — every note becomes a
  summary and the marker must say notes are abbreviated (not "older notes").

## 4. Pass / Fail

Pass when, for every scenario:

- no command or pane shows `Argument list too long` / `OSError [Errno 7]`;
- every prompt a session is handed is ≤ `PROMPT_ARG_LIMIT` (120 000 B) —
  measured on the argv the session actually received;
- no marker appears when nothing was omitted (small fixtures keep full
  detail, and remain byte-identical across runs);
- every marker names a command or path that, when the user runs/opens it,
  returns the omitted text (checked by actually running/opening it);
- the complete instruction text survives on the bootstrap path (measured
  against the original body, not a summary).

Fail on any silent loss (a block shorter than the source with no marker), any
marker that is a dead end, any prompt over the limit, or any behaviour change
for small projects.

## 5. Ambiguities (resolved)

- **A1 — Which claude?** Real Claude is not available to QA. Resolved: use a
  recording stand-in on PATH (or `fake-claude` for verdicts). The stand-in
  records the *same* argv the real binary would get, which is exactly what
  the E2BIG failure is about.
- **A2 — Bounded vs preserved.** Resolved by the impl (A1–A3 of impl.md): cap
  + summarise + actionable pointer, plus file-backed delivery for prompts
  that cannot be bounded. Scenarios assert both halves.
- **A3 — How big is "big enough"?** Any fixture that would have exceeded
  128 KiB before the fix (e.g. 40 × 4 KB descriptions ≈ 160 KB; 60 × 2 KB
  notes ≈ 124 KB) is sufficient. Do not chase exact budget constants.
- **A4 — `PromptTooLargeError` traceback.** Uncaught at the QA-pane call
  sites; filed as pr-a42a4f8. Out of scope: assert only that the *typed*
  error with size/limit is reported and that no raw E2BIG appears.
- **A5 — Which builders are reachable from the CLI.** `pm prompt`,
  `pm plan review|deps|breakdown|fix`, `pm pr show`, `pm qa list|mocks list`,
  `pm qa regression`, `pm qa launch`, the review/sign-off panes and the QA
  loop cover every requirement above except the watcher and merge-error
  blocks (R13/R14 of impl.md), which have no cheap user surface and are
  covered by `tests/test_prompt_bounds.py` (`TestMergeAndWatcherBounding`).

*No [UNRESOLVED] ambiguities.*

## 6. Shared setup notes for scenario workers

- Fixture size matters more than fixture realism: a project that would have
  produced a 150 KB prompt before this PR is the point.
- Measure prompts in **bytes** (`wc -c`), on the argv the session received or
  on the printed prompt — never on character counts.
- When a command prints the prompt because no `claude` is on PATH
  (`pm plan review|deps|breakdown|fix`, `pm prompt`), that printed text *is*
  the prompt under test; keep the stand-in off PATH for those checks.

## 7. Coverage status (planner pass 2, 2026-10-24)

Re-checked against HEAD (`5cee545e`): `tests/test_prompt_bounds.py` holds 93
cases as stated, and the markers, `notes.notes_pointer()`,
`integration.integration_pointer()` and `pm pr show` match R1–R20 as written.
No requirement contradicts the implementation and no [UNRESOLVED] ambiguity
remains, so §§0–6 are unchanged.

Run state at this pass (QA loop `cbc3808772a8a908`, session tag
`project_manager-5b29c418`): scenarios 1–3 and 5 were planned and captured;
scenario 4 ("The QA planner prompt — the one that failed in the field") and
scenario 6 ("Several sessions launched at once share the prompt-file directory
safely") were planned but produced no evidence. The fresh scenarios below
(7–11) re-cover those two surfaces — 7 for the planner, 9 for concurrent
launches — and add the QA child/verification prompts (R13), the bounding
edges, and the side-effect/resume properties the review loop fixed.
