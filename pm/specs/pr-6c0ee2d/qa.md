# QA Spec: pr-6c0ee2d — `pm/architecture.md` state + prompt awareness

The PR adds an optional, hand-written project document, `pm/architecture.md`.
It holds the project's Axiomatic Design FRs, DPs, Design Matrix, coupling
debt, provenance and change log. When the file exists, every Claude session pm
launches for planning, implementation, bug-fixing and review is told about it.
Each session gets:

- a **Project Architecture** block: guidance for its role, then the document
  between `--- begin <pointer> ---` / `--- end <pointer> ---` lines; and
- a **File Structural Debt, Don't Just Comment It** rule: run
  `pm pr list --plan improvements`, then `pm pr note add <id>` or
  `pm pr add … --plan improvements`, and cite that PR id in the code comment.

Without the file, every prompt is exactly what it was before the PR.

User-facing surfaces that build these prompts:

| Surface | Prompt | How a user sees what the session was told |
|---|---|---|
| `pm prompt <pr-id>` | impl (incl. bug-fix flow for `--plan bugs` PRs) | printed to stdout |
| `pm pr start` (CLI or TUI `s`) | impl | the prompt handed to the launched `claude` |
| `pm pr review` (CLI / TUI review, review loop) | review / review-loop (incl. bug-fix checklist) | the prompt handed to the launched `claude` |
| `pm plan add` / `plan breakdown` / `plan review` (pre- and post-load) / `plan import` (CLI or TUI plans pane `a`/`c`) | plan | printed when no `claude` is on PATH, otherwise handed to `claude` |
| `pm plan deps`, `pm plan fix` | (unchanged by design) | — |

fake-claude does **not** receive the prompt; its command line carries only
verdict arguments. To see what a launched session was told, put a
stand-in `claude` executable on PATH that records its arguments to a file and
then idles. pm passes the prompt as the last argument (`"$(cat <prompt file>)"`).
For an over-limit prompt it passes a short bootstrap that names a prompt file.

## 1. Requirements

**R1 — No document, no change.**
Given a project with no `pm/architecture.md`,
When the user prints or launches any impl, bug-fix, review, review-loop or plan session,
Then the prompt has no "Project Architecture" heading, no "File Structural Debt" rule and no `pm pr list --plan improvements` line.

**R2 — Impl awareness.**
Given an in-repo project (`pm/` inside the code repo) with a committed, small `pm/architecture.md`,
When the user prints the impl prompt for a PR (`pm prompt <id>`) or starts the PR,
Then the prompt contains, after the spec section and before the PR-notes handoff section:
- a `## Project Architecture (`pm/architecture.md`)` heading;
- impl guidance ("While implementing"), including a ready-to-run `pm pr note add <this PR's id> 'architecture: …'` command;
- the document verbatim between the begin/end lines, with no truncation marker;
- the File Structural Debt rule, with its four steps (`pm pr list --plan improvements`, `pm pr note add`, `pm pr add … --plan improvements --description …`, cite the id).

**R3 — Bug-fix impl awareness.**
Given the same project and a PR filed under `--plan bugs`,
When the user prints or starts that PR's impl prompt,
Then the Bug Fix Flow's "Fix" step also says to keep the fix inside the DP that owns the root cause and to file or append an `improvements` PR for a masking workaround. The Project Architecture block appears before the Bug Fix Flow.
Without the document, the Fix step reads exactly as before.

**R4 — Review awareness.**
Given the same project and a PR in review,
When the user launches a review (plain, or as a review-loop iteration),
Then the review prompt carries:
- a Project Architecture block with review guidance: new upward `*` coupling → **NEEDS_WORK**; a contested FR/DP boundary → **INPUT_REQUIRED**;
- the debt rule plus the review addendum: a workaround comment citing no improvements PR id → **NEEDS_WORK**; in review-loop mode the reviewer follows the rule itself;
- an extra bullet under the "Architectural review" step that points at Project Architecture.

For a bug PR, the Bug Fix Review Checklist gets one more bullet: root cause inside the owning DP, and any workaround cites an `improvements` PR id.

**R5 — Plan awareness.**
Given the same project,
When the user runs `pm plan add`, `plan breakdown`, `plan review` (before or after `plan load`) or `plan import` (CLI or the TUI plans pane),
Then the plan prompt carries:
- plan guidance ("While planning": map PRs to DPs, order so dependencies flow down, call out a new FR/DP in the plan file);
- the debt rule with the plan addendum (cite the improvements PR id in the plan);
- the document named by its **absolute path**. This holds even when the command runs from a subdirectory or with `-C`.

`pm plan deps` and `pm plan fix` stay unchanged.

**R6 — Standalone pm dir pointer.**
Given a standalone pm dir (`pm init --dir <elsewhere>`) holding `architecture.md`,
When the user prints or launches impl or review prompts from that pm dir,
Then the document is named by its absolute path, never by `pm/architecture.md`, because the code clone has no `pm/`.

**R7 — Oversized document.**
Given a `pm/architecture.md` far over the 16 000-byte excerpt budget (tens of KB up to several MB),
When any of the above prompts is built,
Then:
- the excerpt keeps the head (provenance, FRs/DPs, matrix) and the tail (newest change-log entry);
- a marker between them reads "architecture document truncated to fit the prompt size limit. Read the full text: `<pointer>`";
- the guidance and the debt rule are present in full;
- the prompt grows by roughly 16 KB plus the guidance, not by the document's size;
- the session launches normally.

**R8 — Robust reading.**
Given a `pm/architecture.md` that is whitespace-only, a directory, or full of non-UTF-8 bytes,
When a prompt is built,
Then whitespace-only and directory cases act like "no document" (R1). Bad bytes appear as replacement characters inside the block. No command fails or prints a traceback.

**R9 — The debt rule's commands work as written on a fresh project.**
Given a project with no `improvements` plan entry,
When an agent (or the user) runs the rule's commands verbatim,
Then:
- `pm pr list --plan improvements` succeeds (empty output at first);
- `pm pr add '<t>' --plan improvements --description '<d>'` creates a PR that is then listed under `--plan improvements`;
- `pm pr note add <id> '<text>'` attaches a note that shows on that PR (e.g. in the PR-notes section of its next prompt);
- the TUI keeps rendering with the plan-less "improvements" PR in it.

**R10 — The impl guidance's note command works.**
Given an impl prompt printed for PR X,
When the user runs the `pm pr note add X 'architecture: …'` line from it (placeholder filled in),
Then the note lands on PR X and appears in X's next prompt under PR Notes.

## 2. Setup

- Install pm from this branch per `pm/qa/instructions/tui-manual-test.md`: venv, `pip install -e .`, `PYTHONPATH=<clone>`, and `pm which` printing the clone.
- Throwaway project: `git init` + an empty commit, then `pm init --backend local --no-import`. Add a few PRs with `pm pr add`, one of them `--plan bugs`.
- Architecture document: the user writes `pm/architecture.md` in the recommended layout, with recognizable head and tail lines. Commit it so PR workdir clones contain it. The layout is: provenance line (date, commit, model); FRs; DPs mapped to files; a Design Matrix table; coupling debt; a change log with the newest entry last.
- Seeing launched prompts: a recording stand-in `claude` on PATH (see above). For plan prompts, a PATH with no `claude` makes pm print the prompt.
- TUI flows: `pm session`, driven with tmux send-keys / `pm tui view` per the instruction file.

## 3. Edge cases

- **E1** Document added or removed between two launches: the next prompt reflects the current file. Nothing is cached.
- **E2** Oversized doc with multi-byte UTF-8 near the cut points: no mojibake at the cut. The marker sits between head and tail.
- **E3** Review of a PR whose own branch edits `pm/architecture.md`: the inlined copy is the base project's (pre-PR) version. The PR's edits show up only in the diff.
- **E4** Document present but **not committed**: impl and review still inline the content. The `pm/architecture.md` pointer won't exist inside the PR workdir until it is committed (see Ambiguity 3).
- **E5** `pm -C <pm-dir>` / `PM_PROJECT` with cwd outside the project: plan prompts carry the block. Impl and review prompts resolve the project by walking up from cwd, so they leave out the block **and** session notes. This is pre-existing (it affects notes on master too) and filed as a separate bug, so it is not a failure of this PR. Record what you see.
- **E6** Many sessions launched at once while someone rewrites or deletes `pm/architecture.md`: each prompt has either a well-formed block (heading, begin and end lines, debt rule) or none. Nothing crashes, and no launch fails.
- **E7** Several agents follow the debt rule at the same moment against one project:
  - `project.yaml` stays valid;
  - every `pm pr add` and `pm pr note add` persists, with no lost updates;
  - same title + description dedupes to one PR (existing `pm pr add` behaviour);
  - different titles for the same problem may give duplicate improvements PRs. That comes from the rule's check-then-file race: record it, but it is not a failure.
- **E8** Running `pm pr add` (the debt rule) makes the new PR the project's active PR ("now active"). Watch what the TUI does with that when a plan session files from the base checkout.

## 4. Pass / fail criteria

Pass:
- Every Then above holds on the real surface: printed prompt, the prompt a launched session received, command output, TUI screen.
- Without the document, prompts match the same commands run without it (diff is empty).
- No traceback, non-zero exit or failed launch caused by the document's content or absence.

Fail:
- The block or rule is missing when the document exists, or present when it doesn't.
- The wrong pointer form: `pm/architecture.md` in plan prompts or for standalone pm dirs, or an absolute path in in-repo impl or review prompts.
- An oversized doc not bounded, guidance truncated, or the head or tail lost.
- A bug-fix block that ignores the document.
- `pm plan deps` / `plan fix` gaining the block.
- A debt-rule command that fails as written.
- Lost or corrupted `project.yaml` writes under concurrency.

E5 and the duplicate filings in E7 are observations to report, not failures.

## 5. Ambiguities (resolved)

1. **Is the debt rule gated on the document?** Yes. The PR's test line says prompts "stay clean when absent", so the rule appears only with the block.
2. **How to observe launched prompts without real Claude.** fake-claude never sees the prompt, so use a recording stand-in `claude` on PATH. That is the closest stand-in for "what the session was told". Plan prompts can also be read from the no-`claude` copy-paste output.
3. **Uncommitted document (E4).** The module docs say the file is committed. An uncommitted doc is a user setup gap, and the inlined excerpt still delivers it in full under budget. A dangling pointer for an uncommitted doc over budget is reported as an observation, not a failure.
4. **`-C` / `PM_PROJECT` (E5).** Impl and review prompts resolving the root from cwd is pre-existing behaviour shared with session notes. Filed separately and not held against this PR.
5. **Concurrent debt filings (E7).** The rule is advisory text, and pm's `pm pr add` already dedupes exact duplicates under the lock. Near-duplicate PRs from racing agents are expected. Lost writes or corruption are failures.
6. **`plan breakdown`.** It is still on master and wired here. If pr-30888b1 merges first, the command is gone; test whatever `plan` subcommands exist.

No unresolved ambiguities.
