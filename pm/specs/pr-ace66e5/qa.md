# QA spec — pr-ace66e5: Audit prompt builders for unbounded enumeration

Grounded in `pm/specs/pr-ace66e5/impl.md` (requirements R1–R16 plus the
review-loop follow-ups in §7–§34, which supersede §1 where they differ) and
the diff against master at HEAD `8d0548d5`.

- `pm_core/prompt_bounds.py` (new) — `PROMPT_ARG_LIMIT`, budgets,
  `bounded_join` / `bounded_text` / `bounded_lines` / `fit_prompt`,
  `PromptTooLargeError`.
- `pm_core/claude_launcher.py` — file-backed bootstrap guard in
  `build_claude_shell_cmd`, `launch_claude`, `launch_claude_print[_background]`,
  `launch_bridge_in_tmux` (`--prompt-file`).
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

Fix, in two layers:

1. **Bounded accumulation.** Only two kinds of content are ever shortened
   (policy §31):
   - **PR notes** — the newest notes are kept in full and older ones reduced
     to one-line summaries, with a marker naming `pm pr note list <pr-id>`.
   - **Pure enumerations** — sibling/dependency listings, the QA scenario
     *verdict* listing, integration overlap/conflict path lists, QA finalize
     worktree listings, QA child artifact paths, verification pane output,
     plan-builder PR listings, merge error output, watcher managed/target
     lists. Each omission marker names a command or path that returns the
     full list.
   Everything instruction-shaped is **inlined whole and never truncated**:
   implementation/QA specs, PR descriptions, session notes, the QA
   instruction library, mock bodies, QA scenario steps, concretization
   instruction files, plan files, and the sign-off return block. `fit_prompt`
   composes the remaining bounded blocks so their sum plus static text can
   still fit when possible; it never cuts instruction text.

2. **Launcher guard (now the primary delivery mechanism).** When a prompt is
   over the limit — which is expected for instruction-heavy prompts — the
   *complete* prompt is written to a file and a short bootstrap argv ("your
   complete instructions are in <file>") is passed instead. The file is
   removed after the session exits. With no writable location the launch
   raises `PromptTooLargeError` carrying the measured size and the limit,
   never a raw `E2BIG`, and never a truncated prompt.

**Reproduction tests in the diff:** `tests/test_prompt_bounds.py` (141
cases) and `tests/test_claude_launcher.py` (37), notably
`TestLauncherGuard` / `TestLauncherWiring` (bootstrap argv, file lifetime,
resume writes nothing, no-writable-dir raises), the plan-prompt tests
(`pm plan review` inlines every description; `pm plan deps`/`fix` whole
plan files; `pm plan review` with no cwd delivers by temp file), and
`TestBudgetCoordination` (bounded blocks compose with static text).

## 1. Requirements (Given / When / Then)

### A. Plan commands (the original E2BIG)

- **R1 — `pm plan review` on a big plan.** Given a plan with ~40 loaded PRs
  whose descriptions/tests/files are several KB each, When the user reviews
  the plan, Then the command completes without `Argument list too long`, and
  the session receives **every PR's full description, tests and files** —
  no brief one-line fallback and no "list is abbreviated" note. If the
  resulting prompt exceeds the argv limit, the session is handed a short
  bootstrap argv naming a file that contains the complete prompt.
- **R2 — `pm pr show <id>` is a real reader.** Given a prompt that abbreviates
  a PR listing (a `pm plan deps` description excerpt, an integration marker),
  When the user runs `pm pr show <id>`, Then the full description, tests,
  files and notes are printed — the pointer is not a dead end.
- **R3 — `pm plan deps` on a big project.** Given 40+ PRs with large
  descriptions *and* many plan files totalling hundreds of KB, When the user
  runs `pm plan deps`, Then the command completes, every plan file is
  inlined **whole**, long per-PR descriptions are abbreviated to a short
  excerpt with a note naming `pm pr show <id>` (only when a kept line was
  actually cut), the PR listing itself is bounded with a `pm pr list` marker,
  and an over-limit prompt is delivered by file.
- **R4 — `pm plan breakdown` / `pm plan fix`.** Given the same project, When
  the user runs plan breakdown (existing-PR listing) and applies a review fix
  (which concatenates every plan file), Then neither command fails with E2BIG,
  every plan file and finding is inlined whole, and an over-limit prompt is
  delivered by file.
- **R5 — Plans with many PRs still review in full.** Given a plan whose PRs
  have ordinary descriptions but which exceeds the limit only in aggregate,
  When the user reviews it, Then every PR is listed with its description
  rather than replaced by a truncated or brief listing.

### B. PR session prompts (impl / review / sign-off)

- **R6 — PR notes.** Given a PR with ~60 notes of a few KB each, When the
  user prints/generates its session prompt, Then the *newest* notes are
  present verbatim, older notes are reduced to one-line summaries, and a
  marker names `pm pr note list <pr-id>` — which prints every note in full.
  A note short enough to survive summarisation unchanged must not be counted
  as "abbreviated".
- **R7 — Spec, session notes, deps, sibling PRs.** Given a PR with a ~50 KB
  (or 200 KB) implementation spec, a large `pm/notes.txt`, many dependencies,
  and many sibling PRs with long titles in the same plan, When the session
  prompt is generated, Then the spec and session notes are inlined **whole**
  (no truncation marker on them), the dependency and sibling listings are
  bounded with markers naming `pm pr graph` and `pm pr list --plan <plan>`,
  and an over-limit prompt is delivered by file.
- **R8 — Review and sign-off panes.** Given a PR with heavy history and a
  workdir, When the user opens the review window and then the sign-off
  window, Then both panes start their session (no `Argument list too long`),
  and each session receives the complete prompt: the review verdict list and
  the sign-off routing verdicts are intact, the sign-off QA **error** is
  never cut, and every abbreviated enumeration names a readable source.
- **R9 — Sign-off QA + integration blocks.** Given a QA run with many
  scenarios (long verdict reasons) and an integration record with many
  overlap/conflict paths, When the sign-off prompt is built, Then the
  scenario verdict *listing* is bounded with a marker naming
  `$CAP/scenarios/<n>/verdict.md`, the overall QA verdict and error stay
  whole, the integration path lists are bounded with a marker naming
  `$(pm qa captures-path <pr-id>)/integration.json` or `pm pr show <pr-id>`,
  and `pm pr show` prints the integration record with its real path totals.

### C. QA prompts (the field failure)

- **R10 — QA instruction library.** Given a QA library with many
  instructions/regressions/artifacts whose frontmatter descriptions are
  multi-KB, When the QA planner prompt is built, Then every library entry is
  inlined **whole** (never count-capped or truncated), and if the prompt
  exceeds the argv limit the planner session receives it intact by file.
- **R11 — Mocks.** Given large mock definitions, When the mocks block is
  built, Then every mock body is inlined whole. (`pm qa mocks prompt` is the
  only production surface that injects mocks today; mocks are not injected
  into scenario prompts — recorded in PR notes 2026-10-25.)
- **R12 — Planner pane starts.** Given that project, When the user starts the
  QA loop for a PR, Then the planner pane launches and its session receives
  the complete planner instructions (task, scenario format, `QA_PLAN_START` /
  `QA_PLAN_END`, "Number scenarios starting from 1.") — the field symptom was
  the planner window dying before discovery with zero scenarios.
- **R13 — QA child / concretization / verification prompts.** Given a
  scenario referencing a very large instruction file, a scenario with very
  long steps, and a scenario whose pane output is a huge transcript, When the
  loop runs those steps, Then the instruction file and scenario steps are
  inlined whole, and the bounded enumerations (artifact paths, verification
  pane output, recipe bullets) carry markers naming a reader for the full
  text.

### D. Launcher guard

- **R14 — Over-limit prompt is delivered intact.** Given a prompt larger than
  the argv limit (an instruction-heavy prompt, or a QA regression test whose
  *body is the prompt*), When the user launches it, Then the session starts,
  the argv it receives is small and names a file, that file contains the
  *complete* prompt (every instruction preserved — no truncation), and the
  file is removed once the session exits.
- **R15 — No writable location.** Given the same oversized prompt on a launch
  path with no writable directory, When the user runs it, Then the failure
  names the prompt size and the 120 000-byte limit — it is never
  `OSError [Errno 7] Argument list too long`, and the prompt is never
  silently truncated. (The raw traceback presentation of that error is
  tracked separately as pr-a42a4f8 and is out of scope here.)
- **R16 — Under-limit launches unchanged.** Given an ordinary prompt, When
  any session launches, Then behaviour is as before (no bootstrap, no temp
  file left behind). The plan commands and `pm prompt` still print the prompt
  when no `claude` is on PATH.

### E. New command and no-regression

- **R17 — `pm pr show`.** Given a PR, When the user runs `pm pr show <pr-id>`,
  Then it prints id/title/status/plan/branch/workdir/GitHub, dependencies,
  and the description, tests, files and notes sections; with a sign-off
  return it prints the verdict, reason and return record; with an integration
  record it prints target/base/status, the overlap and conflict path lists
  with their real totals (and `(+N more)` when the yaml copy is capped), and
  where the full record lives. Null fields render as a placeholder, never the
  literal `None`. An unknown id errors clearly.
- **R18 — Small projects are untouched.** Given a project with one PR, a
  short description, one note, no big spec and small notes, When the user
  prints its prompt, Then it is a few KB, contains the full description and
  note verbatim, and contains **no** truncation/omission markers.
- **R19 — Deterministic output.** Given the same project state, When a prompt
  is generated twice, Then the two are byte-identical.
- **R20 — Parallel launches.** Given two (or more) sessions launched at
  nearly the same time from the same project, When both start, Then each
  receives its own prompt (no cross-contamination), any prompt files are
  distinct, neither launch deletes the other's file while it is in use, and
  no prompt file is left behind after the sessions exit.

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
   - extra plans so the plan-file context is large (a few hundred KB total);
   - notes: a loop of `pm pr note add <pr-id> "<a few KB of text>"` to reach
     ~100 KB on one PR;
   - a large `pm/notes.txt` section (the file the notes editor writes);
   - a large `pm/specs/<pr-id>/impl.md` (well over 120 KB to force the
     launcher path);
   - sibling PRs in the same plan with long titles;
   - a QA library: many files under `pm/qa/instructions|regression|artifacts`
     with long frontmatter descriptions, plus large `pm/qa/mocks/*`.
   Seeding with shell loops over `pm` CLI commands is fine; hand-editing
   `pm/project.yaml` is bootstrap-only and should be avoided except to set a
   status the CLI cannot reach directly (e.g. moving a PR to `qa` for the
   sign-off step).
4. **Stand-in claude.** Where a scenario must observe what a *session* was
   handed, put an executable `claude` early on PATH that records its argv
   (count, total bytes, and the last argument) and, when the last argument
   names a file, copies that file. Exit 0. This is the same idea as the
   bundled `fake-claude` but it preserves the prompt, which `fake-claude`
   does not (it drops the prompt from argv entirely).
5. **Two traps (verified in QA scenario 11, 2026-10-25):**
   - **tmux panes do not inherit a custom PATH.** The pane shell's rc puts
     `/home/pm/.local/bin` first, so a recording stand-in on PATH is invisible
     to panes and the real CLI would run. Pane flows must use the bundled
     fake instead: `pm fake-claude config set --tag <tag> '{"_all": {}}'`
     (absolute `_FAKE_CLAUDE_BIN`, no PATH needed). Clear it
     (`pm fake-claude config clear`) before a story that needs the real
     argv recorded. The PATH stand-in is only usable from a plain shell
     (`env PATH=/tmp/standbin:$PATH ...`).
   - **`pm pr start` only resumes on the non-tmux fallback.** With a pm tmux
     session running for the project, it opens a window whose command always
     carries the prompt; kill the pm session (`pm session kill`) for the
     resume story.
   - `pm pr start` requires `pm/project.yaml` committed on the base branch
     (`pm push`, then merge the `pm/sync-*` branch), else it exits with
     "not committed on master yet".

## 3. Edge cases

- **Instruction text is never truncated.** A spec, PR description, session
  note, library entry, mock body, scenario steps, plan file or sign-off
  return must appear whole; a prompt over the limit goes out by file instead.
- **Only enumerations and PR notes carry omission markers.** A marker on an
  instruction-shaped block is a failure, not a pass.
- **Empty / single-element collections** — no marker, no stray separator.
- **Multi-byte text** — emoji/CJK prompts must round-trip through the file
  handoff (UTF-8), not just fit the byte budget; measured in bytes.
- **Exactly at the limit** — `>` is over-limit; `==` is allowed.
- **Container sessions** — markers that name a path must name one the
  *session* can open: project-relative (`pm/notes.txt`), a bind-mount
  (`$CAP/...`, `/pm-captures/...`), or a command. A host-absolute path under
  the user's home is a broken pointer inside a container.
- **Markers must be actionable** — `pm notes` (interactive editor),
  `pm qa status` and `pm qa list` (does not list mocks) were all named by
  markers in earlier revisions and were dead ends.
- **Resume launches** — no prompt is passed on resume; the guard must not
  fire or write a file. A failed resume retried as a fresh session must
  bootstrap normally.
- **Repeated generation** — building a prompt must not create the PR's
  captures directory as a side effect (filed as pr-155f3e3 when an omission
  marker fires and resolves a captures path).
- **A single note bigger than the whole notes budget** — every note becomes a
  summary and the marker must say notes are abbreviated (not "older notes").

## 4. Pass / Fail

Pass when, for every scenario:

- no command or pane shows `Argument list too long` / `OSError [Errno 7]`;
- the argv entry the session actually receives is ≤ `PROMPT_ARG_LIMIT`
  (120 000 B) — when the prompt itself is larger, the argv is a short
  bootstrap and the named file holds the complete prompt;
- instruction-shaped text is byte-identical to its source (spec, description,
  session notes, library entry, mock body, scenario steps, plan file,
  sign-off return), never shortened;
- every enumeration/notes marker names a command or path that, when the user
  runs/opens it, returns the omitted text (checked by actually running or
  opening it);
- no marker appears when nothing was omitted (small fixtures keep full
  detail, and remain byte-identical across runs).

Fail on any silent loss (a block shorter than the source with no marker, or a
marker on instruction text), any marker that is a dead end, any prompt passed
as one over-limit argv entry, or any behaviour change for small projects.

## 5. Ambiguities (resolved)

- **A1 — Which claude?** Real Claude is not available to QA. Resolved: use a
  recording stand-in on PATH from a plain shell, or the bundled `fake-claude`
  for pane flows. The stand-in records the *same* argv the real binary would
  get, which is exactly what the E2BIG failure is about.
- **A2 — Bounded vs preserved.** Resolved by impl §31: bound accumulation
  (PR notes, pure enumerations) only; never truncate instruction text; carry
  the overflow with the launcher's file-backed delivery. Scenarios assert
  both halves.
- **A3 — How big is "big enough"?** Any fixture that would have exceeded
  128 KiB before the fix (e.g. 40 × 4 KB descriptions ≈ 160 KB; 60 × 2 KB
  notes ≈ 124 KB; a >120 KB spec) is sufficient. Do not chase exact budget
  constants.
- **A4 — `PromptTooLargeError` traceback.** Uncaught at the QA-pane call
  sites; filed as pr-a42a4f8. Out of scope: assert only that the *typed*
  error with size/limit is reported and that no raw E2BIG appears.
- **A5 — Which builders are reachable from the CLI.** `pm prompt`,
  `pm plan review|deps|breakdown|fix`, `pm pr show`, `pm qa list|mocks list|
  mocks prompt`, `pm qa regression`, `pm qa launch`, the review/sign-off
  panes and the QA loop cover every requirement above except the watcher and
  merge-error blocks (R13/R14 of impl.md), which have no cheap user surface
  and are covered by `tests/test_prompt_bounds.py`.
- **A6 — Which prompts may exceed the argv limit?** Under §31,
  instruction-heavy prompts (this repo's own impl/review/sign-off prompts
  with the 120 KB+ spec inlined, `pm plan review` on a big plan, `pm plan
  deps` with many plan files) legitimately exceed it and are delivered by
  file. That is the intended behaviour, not a failure; the pass condition is
  the *argv* size plus complete file contents.

*No [UNRESOLVED] ambiguities.*

## 6. Shared setup notes for scenario workers

- Fixture size matters more than fixture realism: a project that would have
  produced a 150 KB prompt before this PR is the point.
- Measure prompts in **bytes** (`wc -c`), on the argv the session received or
  on the printed prompt — never on character counts.
- When a command prints the prompt because no `claude` is on PATH
  (`pm plan review|deps|breakdown|fix`, `pm prompt`), that printed text *is*
  the full prompt under test; keep the stand-in off PATH for those checks.
  When a stand-in *is* on PATH and the prompt is over the limit, its last
  argument is the short bootstrap and the file it names is the prompt.

## 7. Coverage status (planner pass 3, 2026-10-25)

Re-checked against HEAD (`8d0548d5`). Since planner pass 2 (`5cee545e`) the
implementation changed materially, and §§0–6 above were rewritten to match:

- **§31 policy change (`74d0916e`)** — bounds now cut accumulation only,
  never instructions. `SPEC_BUDGET`, `SESSION_NOTES_BUDGET`,
  `QA_CHILD_STEPS_BUDGET`, `CONCRETIZE_INSTRUCTION_BUDGET`, `MOCKS_BUDGET`
  and the library budgets are gone; the four `fit_prompt` builders keep only
  PR notes and enumeration blocks. Superseded R1/R3/R5/R7/R10/R11/R13.
- **4029 i1** — the sign-off QA error is no longer shrinkable with the
  verdict listing.
- **4029 i2** — `pm plan review`'s brief fallback was deleted; the plan's own
  PRs are always inlined whole and over-limit prompts go out by file.
- **4029 i3** — `pm pr show` renders null return-integration fields as a
  placeholder; plan-builder and container-split delivery paths are tested.
- Earlier 240e iterations (return record in `pm pr show`, integration path
  totals, UTF-8 file handoff, malformed-note tolerance, concretization
  marker) are folded into R13/R17.

`tests/test_prompt_bounds.py` holds 141 cases and `test_claude_launcher.py`
37, as stated. No requirement contradicts the implementation and no
[UNRESOLVED] ambiguity remains.

Run state: scenarios 1–11 ran against the pre-§31 code (QA run at
2026-10-25T00:44Z passed the planner prompt, QA loop prompts, concurrency,
bounding edges, and no-side-effect/resume/`pm pr show` stories). Scenarios 12+
re-cover the surfaces the §31 policy and 4029 iterations changed: plan
review/deps whole-text delivery, instruction preservation, the launcher's
file-backed delivery across launch paths (including no-cwd and container
split), the sign-off QA error, the return record, and `pm pr show` as the
reader for every marker.
