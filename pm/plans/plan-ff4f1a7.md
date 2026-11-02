# Doc review — Adversarial review as a first-class pm feature

## Scope

Add an adversarial review process to pm, **scoped to plans and specs only**. PRs already have cooperative adversarial coverage via the existing review loop; this plan does not duplicate that. The adversary runs **during plan generation and during spec generation**, in an **iterative loop** with three human-involvement modes (mirroring today's `spec-mode`). It runs in its **own tmux pane**, uses the existing pane-registry infrastructure, and writes into a persistent **question queue** in which both questions *and* responses are first-class, addressable, revisitable records.

Plan generation and spec generation prompts are updated to produce **user stories** alongside scope/goals, and each PR / spec section is required to link to the user stories it delivers. The adversary uses these user stories as one of its standing lenses.

This plan is deliberately scoped to what's useful with the current plan/PR-centric pm architecture. It does **not** rearchitect pm around a question graph as the source of truth — that's the longer-term vision captured in `pm-question-graph-philosophy.md` and `paper-review-tool-plan.md`. Here we build the queue (questions + responses), the adversary runner with iteration and modes, inspection prompts, CLI surface, TUI surface, and a `pm tts` output layer for hands-and-eyes-free use.

## Goals

1. Plan generation and spec generation both trigger the same adversary loop, in a separate pane, iterating until Claude determines "enough."
2. Three human-involvement modes (`auto` / `prompt` / `review`), configured globally and overridable per plan/PR — symmetric with today's `spec-mode`.
3. Plan generation produces **user stories** as a required section; each PR ties to the story/stories it delivers. Spec generation enumerates user actions step-by-step. The adversary uses user-story coverage as an inspection lens.
4. Three adversarial prompt families — **internal**, **external** (with web search producing specific contradictions, not citation dumps), and **cross-reference** — writing into a shared queue.
5. First-class **questions and responses** in the queue. Both are addressable, persistent, revisitable, and challengeable. Responses can be superseded; old responses remain browsable.
6. Humans contribute reviews in any format (text / file / stdin / voice transcript) via `pm questions add`; extraction is confirmed before writing.
7. TUI visibility: badges for open questions on plans/PRs; a pane to browse questions and their response history.
8. `pm tts on/off` togglable from inside any pm session, using Claude Code's built-in `/voice` for STT and a pm-provided TTS output layer for hands-and-eyes-free use.

## Distinction from existing pm flows

- **`pm guide`** (existing) is forward-looking — "what should I do next to set up / advance this project?" It runs *with* the user.
- The new adversary is **generation-time only**, triggered from within `pm plan add` and the Step-0 spec generation inside `pm pr impl` / `pm pr qa`. There is no standalone `pm inspect` command; to re-run the adversary against an existing plan or spec, re-trigger its generation flow (e.g., edit and re-run `pm plan review` which will launch the adversary on any unresolved-questions delta).
- Today's `plan review` / `pr review` perform cooperative consistency/coverage checks. `pm pr review` specifically is the adversarial coverage for PRs/implementation. This plan's adversary loop is scoped to plans and specs and does not duplicate either.

## Key design decisions

### Storage

- Questions: one YAML per question under `pm/questions/q-<shortid>.yaml`.
- Responses: one YAML per response under `pm/questions/responses/r-<shortid>.yaml` — separate files so a question's response history can grow without rewriting the question record, and so responses are addressable on their own.

### Question record (v1)
```yaml
id: q-abc123
content: "..."
source:
  kind: internal | external | cross_ref | human
  prompt: <prompt name>
  reviewer: <name or email>
targets:
  - {kind: plan|spec, ref: "plan-001" | "spec:pr-003"}
user_stories: ["<story id or slug>", ...]  # which stories this question challenges
severity: high | medium | low
category: counterargument | contradiction | unsupported_claim | ambiguity | missing_test | edge_case | scope | story_coverage | plan_compression | deliverable | fastest_path | other
state: open | accepted | needs_user_input | dismissed | deferred | resolved | superseded
created_at: <iso>
updated_at: <iso>
response_ids: [r-..., r-...]       # ordered; latest is "standing"
parent: q-xyz789                    # if spawned from another question or challenging a specific response
challenges_response: r-...          # set when this question is a challenge to a specific response
resolution:
  # INVARIANT: state=resolved ⇒ response_ref is set.
  # change_refs and notes are recorded on the response itself, not here.
  response_ref: r-...
  verified_by: <name>                                      # null until a human verifies
  verification_notes: "..."
```

### Response record (v1)
```yaml
id: r-def456
question_id: q-abc123
text: "..."
actor: human | claude
source:
  kind: internal | external | cross_ref | human
  prompt: <prompt name>
  reviewer: <name>
state: standing | superseded | challenged
created_at: <iso>
updated_at: <iso>
superseded_by: r-...                # if this response was replaced
challenged_by: [q-...]              # follow-up questions targeting this response
links:
  - {kind: commit | pr | plan_diff, ref: "..."}  # changes the response cites
```

### Severity priority (default sort)
Unaddressed counterarguments > internal contradictions > unsupported claims > user-story coverage gaps > deliverable/fastest-path concerns > plan-compression suggestions > ambiguities > scope issues. `(severity, category)` tuple sort; no numeric composite in this plan. Deliverable/fastest-path sit high because failing to identify a shippable slice tends to sink plans more reliably than any individual ambiguity.

### Three adversary modes (`adversary-mode`)

Symmetric with `spec-mode`; global setting, per-plan/per-PR override supported. Authority over resolution is the gradient:

- **`auto`** — system **must** resolve every accepted question itself. No escalation to the human. Self-resolutions land as `state: resolved, verified_by: null` (the needs-verify pool) so a human can audit in batch later without being interrupted mid-loop. Inspection/generator prompts are given mode-aware instructions: "you must produce a resolution for every accepted question — no escalation."
- **`prompt`** (default) — system **should** resolve, but **may** escalate a question to the human if it judges its own resolution weak. Escalation is explicit: Claude writes a proposed response, flips the question to `state: needs_user_input`, and the loop pauses on it. User responds → proposed response is either accepted (→ `resolved`) or edited → loop continues. Prompt text: "produce a resolution, but flag to the user if confidence is low."
- **`review`** — loop pauses after every adversarial round for human triage before the generator revises. Claude may still self-propose resolutions; the human triages them.

### Iteration and termination

One round = adversary inspects → writes new questions → generator addresses accepted ones (revises artifact and/or writes responses) → adversary re-inspects existing + response state. Loop continues until one of:

- Adversary produces zero new questions above a severity threshold this round.
- Two consecutive rounds produce only dismissed-or-deferred questions (nothing accepted).
- Hard round cap (default 5, configurable).
- Human explicitly says "done" in `review` mode.

Termination reason is logged to the target's adversary-history record so you can see why a loop stopped.

### Separate adversary pane

Generator stays in its existing pane (`plan-add`, `impl`, etc.). Adversary launches into a sibling pane with new role `"adversary"` via `launch_pane` / `pane_registry` — deduped by role, so re-invoking against the same target focuses the existing adversary pane instead of spawning multiples. TUI splits the window so both panes are visible during a live loop.

### Prompts

Built dynamically by Python in `pm_core/adversary/prompts.py`, following the same pattern as `_build_spec_prompt()` in `pm_core/spec_gen.py` and `REVIEW_PROMPTS` formatting in `pm_core/review.py`. Each prompt is assembled at call time from:

1. A **mode-aware preamble** (auto / prompt / review — controls whether the adversary must self-resolve, may escalate, or stays question-only).
2. The **category brief** for that prompt family (internal / external / cross_ref for inspection, plus ingest_human for parsing freeform human reviews) — the list of what to look for, kept as a Python constant so it stays grep-able and editable without touching code flow.
3. The **target artifact** embedded inline (plan text, spec text).
4. **Project-specific context**: relevant sections from `pm/notes.txt`, the parent plan for a spec target, existing specs for a plan target, and (for cross_ref) all other plans and specs in the project.
5. The **response schema** the adversary must emit questions in, so the output drops straight into the queue.

No loose markdown prompt files — everything lives in Python functions so it composes with project state the same way the rest of pm's prompts do. All three inspection prompts use **user stories** as a standing lens alongside their category-specific checks.

#### What each adversary is asked to find

**Internal inspection** — given the target plan or spec plus its immediate project context. The adversary produces both *challenges* (what's wrong) and *suggestions* (concrete proposals for how to improve), phrased as questions with a proposed direction embedded:

- Unsupported claims — assertions without cited justification, test coverage, or stated rationale.
- Internal contradictions — two statements that can't both be true; invariants declared in one section silently broken in another.
- Ambiguities — terms used inconsistently; references with unclear antecedent; quantifiers without scope.
- Missing tests — behavior claimed with no corresponding test planned.
- Unhandled edge cases described in prose — empty input, concurrent access, failure modes, partial failure, resource exhaustion, authorization boundaries.
- User-story coverage — stories with no delivering PR; PRs with no story linkage; partial coverage.
- Scope drift — PRs delivering more or less than their stated story.
- Termination/error semantics — what happens on failure; documented consistently.
- **Plan compression** — what could be cut or deferred? Which PRs are nice-to-have vs essential? Are any PRs whose absence wouldn't meaningfully change the user-visible outcome? The adversary is instructed to propose concrete cuts or deferrals, not just ask abstractly ("PRs 3, 5, and 7 look deferrable because … — do they need to be in this plan at all?").
- **Deliverable identification** — what is the minimum useful thing this plan produces end-to-end? Which subset of PRs constitutes a shippable first milestone that exercises the core user story? Adversary names the minimum set, not just asks the user to find it.
- **Fastest path to significant value** — what ordering gets the user a working, demo-able slice soonest? Which PRs block the first valuable deliverable, and can any of them be simplified, stubbed, or reordered to land sooner?

(Spec-vs-implementation drift is explicitly **not** the adversary's job — `pm pr review` covers that.)

**External adversarial** — with web search, constrained to produce concrete contradictions, not citation dumps:
- Specific published counterarguments — "X argues Y, which contradicts the plan's claim Z because…"
- Competing approaches the plan doesn't acknowledge — alternative architectures, framings, or tools.
- Prior art the plan duplicates — existing tools/libraries/papers; how is this different, is reuse considered.
- Missing user stories from the problem space — needs of comparable-system users that this plan ignores.
- Domain conventions violated — standard patterns in security, accessibility, API design, concurrency departed from without reason.
- Known failure modes in similar systems — well-documented problems inherited from the approach's class.

**Cross-reference** — across plans and specs within the project:
- Contradictions across plans — plan A claims X; plan B claims not-X.
- Plan ↔ spec drift — story S in a plan mapped to a PR whose spec enumerates user actions that don't actually deliver S.
- User-story overlap — stories in different plans covering the same ground; duplicated work or intentional.
- Term drift — same term used with different meanings across plans/specs.
- Declared-dependency sanity — `depends_on` edges between PRs that are incoherent given the plan/spec content (e.g., PR-B's spec assumes a behavior PR-A's spec never promises).

### Plan- and spec-generation prompt updates

- Plan generation (`pm plan add` prompt in `cli/plan.py`): require a `## User stories` section before `## PRs`. Each story: one sentence, actor-first. Each PR description must name which story/stories it delivers.
- Spec generation (`pm_core/spec_gen.py` `_build_spec_prompt`): require each spec to enumerate the user actions step-by-step that should work after the PR lands, linked to the relevant user story.

### Response lifecycle

- A response is written against a specific question. Multiple responses per question are allowed; the latest `state: standing` response is the "current" answer.
- Revising a response does not overwrite — it writes a new response and marks the old one `superseded_by: r-new`.
- A response can be **challenged** by a new question (`q.challenges_response: r-...`), making "did the response dodge the challenge" literal: the challenge is a first-class question visible in the queue and in the response's `challenged_by` list.

### Resolution, verification, and who can resolve

**Invariant**: a question reaches a terminal state only via `resolved` (with a response attached) or `dismissed` (with a reason). The response is always the artifact that explains how the challenge was addressed.

- `pm questions respond <qid> <text> [--link-change <ref>]` — writes a response; `--link-change` records a cited change in the response's `links`. Notes are just response text.
- `pm questions resolve <qid> --response <r-id>` — marks the question resolved, pointing at an existing response. Single path, no sugar flags. If you want to resolve fresh, you run `respond` then `resolve`.
- `pm questions dismiss <qid> --reason "..."` — the other terminal state; reason required.

Resolve produces `state: resolved`, `resolution.response_ref: r-...`, `verified_by: null` — pending verification.

- **Humans** can resolve via the two-step flow above.
- **Automated sessions** resolve per mode: `auto` always self-resolves (no escalation); `prompt` may escalate via `state: needs_user_input` when confidence is low; `review` self-proposes resolutions that the human triages.
- `pm questions verify <qid>` confirms that the resolution actually addressed the challenge, or `--reopen`s the question if not. The adversary treats unverified resolutions as *provisional* in the next round — if new evidence or a follow-up challenge surfaces, the unverified resolution can be re-raised automatically without waiting for the human.

### Universality (code + text projects)

Inspection prompts branch by project type (inferred from presence of plans/specs/PRs vs. document targets). The question / response lifecycle and the three modes are identical either way.

## Voice input and TTS output

A side feature of this plan, orthogonal to adversarial review but shipped alongside because the hands-and-eyes-free flow benefits from the queue's pull-model questions.

Voice is a **per-session toggle**, not a new session type. The user is already in some pm Claude Code session (impl / review / plan-add / guide / …) and turns voice on or off for *that* session, the same way `/rc` is invoked from inside any session.

- **Input**: Claude Code's built-in `/voice` — user runs it inside any session. pm adds nothing for input.
- **Output**: `pm tts on` / `pm tts off` — pm's contribution. Starts or stops a background post-processor that reads Claude's prose aloud while suppressing chrome, tool calls, and code.

### Signal sources

Claude Code has **no streaming-delta hook**, so per-token speech requires reading the terminal. The daemon combines three signals:

- **Tmux pane capture** (primary text source) — polls `tmux capture-pane -p -J -e -t <pane_id>` every ~200ms, strips ANSI, diffs against the prior snapshot.
- **Claude Code hooks** (primary structural signal) — `PreToolUse` / `PostToolUse` drive a suppression state machine around tool regions; `Notification` pauses TTS during permission dialogs; `Stop` / `SubagentStop` flush the sentence buffer at turn end; `UserPromptSubmit` resets stale state. Registered via a hook config the daemon installs on the bound session at `pm tts on` and removes at `pm tts off`.
- **Session JSONL tail** — fallback / confirmation. JSONL at `~/.claude/projects/<encoded-cwd>/*.jsonl` is per-complete-message (verified live), so it's too coarse to drive TTS on its own but useful as belt-and-suspenders if a hook is missed.

### Post-processing pipeline

1. **Region selection** — find the input-box top border (`╭─╮` pattern) and treat everything below as UI chrome; ignore it.
2. **Stability filter** — a line is eligible only after appearing in ≥3 consecutive snapshots. Kills spinners, transient popups, and still-streaming lines.
3. **Hook-driven suppression** — while `PreToolUse` is open (no matching `PostToolUse`) or `Notification` fired for a pending permission, emit nothing regardless of pane content.
4. **Line-level filters** (backup to hooks) — drop lines starting with `⏺` / `⎿`; lines ≥50% box-drawing chars; fenced code blocks; diff patterns (`+++`, `---`, `@@`); shell-prompt markers; file-path-only content; below-minimum-length lines; configurable chrome regexes.
5. **Sentence-boundary flush** — surviving prose accumulates into a sentence buffer; flush on sentence terminator (`.`, `?`, `!` + whitespace), paragraph break, or `Stop` / `SubagentStop` hook. Queue throttled so TTS doesn't fall minutes behind if Claude pauses.
6. **Tool-activity cues (optional)** — separate channel; `PreToolUse` triggers a short spoken announcement ("editing questions.py") if the cues flag is on.

Latency target: speech begins within ~1s of a sentence appearing on screen.

### Config, backends, and mobile

- User-tunable via `~/.pm/tts.toml`: poll interval, stability threshold, min-line-length, suppression patterns, backend, cues on/off. Heuristics are brittle against future Claude Code TUI changes; user-side config means tweaks don't require a pm update.
- TTS backend pluggable — `say` (macOS) and `piper` (Linux, local) by default; overridable via env var. No cloud requirement.
- **Mobile**: `/rc` is invoked manually from inside any session the user wants to reach from their phone. No `pm mobile` command is added. `/voice` not working over SSH is accepted; no phone-mic-to-host audio path exists, not worked around here.

## Step-by-step flows

### Flow A — Plan generation (`pm plan add "foo"`)

1. Plan-add session starts in `plan-add` pane and drafts the plan, producing `## User stories` and `## PRs` sections (new requirement).
2. Once the first `## PRs` block is written, the plan-add session triggers the adversary loop against the plan. The adversary runner launches an `adversary` pane, runs internal + external + cross-ref inspection prompts, and writes questions into the queue targeted at the plan, each linked to the user stories it challenges.
3. Round handling by `adversary-mode`:
   - `auto` / `prompt`: plan-add session is notified, reads new questions, revises the plan, writes responses into the queue, signals "revision done."
   - `review`: human runs `pm questions triage --plan <id>` first; only accepted questions drive revisions.
4. Adversary re-inspects (plan text + new responses). Loop continues until termination.
5. On exit, the plan has a persistent trail of questions, responses, dismissals, and the termination reason.

### Flow B — Spec generation (during `pm pr impl PR-003`)

1. Step-0 spec generation runs as today, producing a draft spec that now includes the user-action enumeration (new requirement).
2. After the draft lands, spec generation triggers the adversary loop against the spec. The adversary runner launches an `adversary` pane, context bundle includes the spec, the parent plan, and the PR description.
3. Loop by mode (same as Flow A, applied to the spec):
   - `auto`: spec revises silently until the adversary's "enough" signal; impl then proceeds.
   - `prompt`: impl pauses on unresolvable ambiguity (same hook as today's `AMBIGUITY_FLAG`).
   - `review`: human triages between rounds.
4. Adversary terminates → `spec_pending` clears → impl phase proceeds with a stress-tested spec.

### Flow C — Human contributes a review mid-stream

1. `pm questions add` with freeform text / file / stdin; extraction launches `ingest_human.md`, presents the extracted list for confirmation (unless `--yes`), writes attributed questions.
2. These questions appear in the next adversary round, which notices "a human already raised X" and doesn't duplicate.

### Flow D — Revisiting a past response

1. `pm responses list --question q-abc123` shows the response history for that question (standing, superseded, challenged).
2. `pm responses show r-def456` shows a specific response with its question, source, state, and links to changes.
3. `pm responses challenge r-def456 [text|--file|--stdin]` raises a follow-up question specifically targeted at that response — appears in the queue with `challenges_response: r-def456` and shows up in the response's `challenged_by` list. Closes the "did the response actually address the challenge, or dodge it?" loop at the response level.
4. `pm responses supersede r-old --with r-new` marks an old response as superseded; old response remains browsable.

## Constraints

- Must work with messy, incomplete project state — resilient to missing specs, half-written plans, empty PR lists.
- Questions and responses persist across sessions as flat YAML in the repo, version-controlled.
- Adversary loop always runs in a separate pane so the generator and critic are visibly distinct.
- No conflict with existing `plan review` / `pr review`; adversary is a parallel system, not a flag on those.

## Out of scope (deferred to future plans)

- Full question-graph data model (parent/child/cluster/tension edges beyond simple `parent` and `challenges_response`).
- Composite scoring with visible adjustable factors.
- Feed-first / mobile-native interface.
- Autostart driven by question-cluster resolution.
- Multi-user per-feed ranking.
- Cross-project question references.
- **`pm voice` convenience session** — a one-command entry that spins up an uncontainerized pm-aware Claude Code session with `/voice` and `pm tts on` both auto-enabled, for accessibility users who want a single entry point to hands+eyes-free pm. The primitives (`/voice` from Claude Code, `pm tts on/off` from this plan, the pm primer pattern) cover this as a thin wrapper later; deferred until the underlying pieces have been exercised.
- **LLM-post-processed change summaries** for TTS — a second Claude pass that speaks *what* a batch of edits accomplished rather than just announcing the tool call. Flagged in the TTS PR as the natural next step.

## PRs

### PR: Question and response data model + store
- **description**: Define the YAML schemas for question and response records. Implement `pm_core/questions/store.py` with read/write/list/filter helpers for both. Separate files per record. Creates `pm/questions/` and `pm/questions/responses/` on demand. Pure library PR — no CLI/TUI surface. Foundation for everything else. No human testing.
- **tests**: Unit tests for create/load/update/list/filter for questions and responses; id generation; response linkage (`response_ids`, `superseded_by`, `challenged_by`); state transitions.
- **files**: `pm_core/questions/__init__.py`, `pm_core/questions/store.py`, `pm_core/questions/schema.py`, `tests/questions/test_store.py`.
- **depends_on**:

---

### PR: `pm questions` CLI — list / show / respond / dismiss / defer / resolve
- **description**: Subcommand group with `list` (supports `--needs-verify`, `--needs-input`, standard state filters), `show <id>`, `respond <id> <text> [--link-change <ref>]` (writes a new response; `--link-change` adds a change citation to the response's `links`), `dismiss <id> --reason` (required), `defer <id>`, `resolve <id> --response <r-id>` (single path — must point at an existing response; invariant that resolved questions always have a response attached). Default list sorts by the severity/category priority from the plan. Text-only; no human testing.
- **tests**: CLI unit tests per subcommand against a tmp pm project with seeded records; assert state transitions, response creation with/without change-link, dismiss requires reason, resolve refuses without a valid `--response`.
- **files**: `pm_core/cli/questions.py`, registered in `pm_core/cli/__init__.py`, `tests/cli/test_questions_cli.py`.
- **depends_on**: Question and response data model + store

---

### PR: `pm responses` CLI — list / show / challenge / supersede / link
- **description**: Subcommand group with `list [--question <id>] [--state ...]`, `show <id>`, `challenge <id> [text|--file|--stdin]` (spawns a new question with `challenges_response` set; uses the same ingest path as `questions add` for freeform input), `supersede <id> --with <new-id>`, `link <id> --change <ref>` (records a code change a response cites). Makes responses addressable on their own so the user can revisit old answers and challenge specific ones. No human testing.
- **tests**: CLI unit tests for each subcommand; assertion that challenge produces a question with correct `challenges_response` and that the target response's `challenged_by` list is updated.
- **files**: `pm_core/cli/responses.py`, register in CLI, `tests/cli/test_responses_cli.py`.
- **depends_on**: Question and response data model + store

---

### PR: `pm questions add` — ingest freeform human reviews
- **description**: `pm questions add [TEXT] [--file PATH] [--stdin] [--reviewer NAME] [--target ...] [--yes]`. Implements `build_ingest_human_prompt(input_text, target, reviewer)` in `pm_core/adversary/prompts.py` following the same builder pattern as the inspection prompts. Launches Claude with the assembled prompt to extract discrete questions from messy input (chat logs, notes, voice-memo transcripts). Presents extracted list for the reviewer to confirm/edit before writing, unless `--yes`. Attribution preserved.
- **tests**: Unit tests for input routing (text/file/stdin). Integration test with a mocked ingest pass returning a fixed extraction; assert confirmation flow and resulting YAMLs.
- **files**: extend `pm_core/adversary/prompts.py`, extend `pm_core/cli/questions.py`, `pm_core/questions/ingest.py`, `tests/cli/test_questions_add.py`.
- **depends_on**: `pm questions` CLI, Internal inspection prompt — builder + category brief

---

### PR: `pm questions triage` flow
- **description**: Interactive-ish CLI walking open questions one-by-one, recording accept/dismiss/defer with a reason. `--batch` accepts a file mapping ids → decisions for headless use. Accepted questions can spawn a PR via `--spawn-pr` (writes a new `### PR:` into the target plan file and back-links the question). **Human-guided testing** for the interactive walk — call out `INPUT_REQUIRED` in review.
- **tests**: Unit tests for `--batch` path and the spawn-PR plan-file writer; scripted stdin fixture for interactive path.
- **files**: extend `pm_core/cli/questions.py`, `pm_core/questions/triage.py`, `tests/cli/test_questions_triage.py`.
- **depends_on**: `pm questions` CLI

---

### PR: Review-of-review — verify resolutions addressed the challenge
- **description**: `pm questions verify <id> [--ok|--reopen] [--notes]` — confirm or reject that the resolution (regardless of whether it came from `--change`, `--response`, or `--note`) actually addressed the challenge. Reopen writes notes to history and sets state back to `open`; the preserved `resolution` block stays in the record for audit. `pm questions list --needs-verify` filter already exists from the CLI PR. Adversary-loop awareness of unverified resolutions is implemented in the loop PR, not here. CLI-only in this PR; TUI surface covered by the TUI badges / browser PRs.
- **tests**: Unit tests for resolve → verify lifecycle, reopen path, list filter.
- **files**: extend `pm_core/cli/questions.py`, `pm_core/questions/store.py`, `tests/cli/test_questions_verify.py`.
- **depends_on**: `pm questions triage` flow

---

### PR: Adversary pane runner (shared primitive)
- **description**: `pm_core/adversary/runner.py` — launches the `adversary` role pane via existing `launch_pane` / `pane_registry` (deduped by role), assembles the inspection context bundle (target artifact + relevant plans/specs/PRs), invokes the selected inspection prompt(s), writes resulting questions into the queue, emits a "round done" signal (filesystem marker or socket event, whichever matches existing pm session signaling). No loop logic yet — this PR only launches a single round and returns. Used by everything downstream.
- **tests**: Unit tests mocking `launch_pane` — assert role `"adversary"`, correct prompt bundle passed, correct target context, questions written to store.
- **files**: `pm_core/adversary/__init__.py`, `pm_core/adversary/runner.py`, `tests/adversary/test_runner.py`. (`pm_core/adversary/context.py` — the shared project-context bundler reused by all three prompt builders — lands in the Internal inspection prompt PR.)
- **depends_on**: Question and response data model + store

---

### PR: Adversary iteration loop + `adversary-mode` config
- **description**: Wrap the single-round runner in an iteration loop with termination heuristic (zero-new-high-severity; two-rounds-no-accepts; round cap). Add `adversary-mode` (auto/prompt/review) global setting with per-plan/per-PR override, mirroring `spec-mode`'s structure in `pm_core/spec_gen.py` and settings handling. Record termination reason in the target's adversary-history. Mode-aware resolution authority: `auto` instructs the generator prompt to self-resolve every accepted question; `prompt` allows escalation via `state: needs_user_input` and pauses when one is produced; `review` pauses each round for `pm questions triage` to complete. Loop also treats unverified prior-round resolutions as provisional — re-inspects them alongside new content and may re-raise via a fresh challenge if evidence warrants.
- **tests**: Unit tests for each termination condition; mode precedence (global vs. per-plan vs. per-PR); pause-and-resume simulation using a fake runner.
- **files**: `pm_core/adversary/loop.py`, `pm_core/adversary/mode.py`, `tests/adversary/test_loop.py`, `tests/adversary/test_mode.py`.
- **depends_on**: Adversary pane runner (shared primitive)

---

### PR: Internal inspection prompt — builder + category brief
- **description**: Implement `build_internal_prompt(target, project_context, mode)` in `pm_core/adversary/prompts.py`. Assembles the mode-aware preamble, the internal-inspection category brief (unsupported claims, contradictions, ambiguities, missing tests, unhandled edge cases from prose, user-story coverage, scope drift, termination/error semantics, **plan compression / deliverable identification / fastest path to significant value**) as a Python constant, the target plan/spec text, relevant `pm/notes.txt` sections, the parent plan (when target is a spec) or existing specs (when target is a plan), and the response/question schema the output must conform to. The compression/deliverable/fastest-path items instruct Claude to propose concrete cuts, name the minimum shippable subset, and suggest ordering changes — not just ask the user abstractly. Same structural pattern as `_build_spec_prompt()` in `pm_core/spec_gen.py`.
- **tests**: Snapshot tests on fixture targets asserting (a) the category brief is included verbatim, (b) the relevant notes sections are spliced in, (c) parent plan / existing specs are included appropriately, (d) the mode preamble changes with `adversary-mode`.
- **files**: `pm_core/adversary/prompts.py`, `pm_core/adversary/context.py` (shared project-context bundler reused by all three prompt builders), `tests/adversary/test_prompt_internal.py`.
- **depends_on**: Adversary pane runner (shared primitive)

---

### PR: External-adversarial inspection prompt — builder + category brief
- **description**: Implement `build_external_prompt(target, project_context, mode)` in `pm_core/adversary/prompts.py`. Same structural pattern as the internal builder, but the category brief instructs Claude to use the web-search tool and enforces the "concrete contradiction, not citation dump" shape ("X argues Y, which undermines the plan's claim Z because…"). Covers published counterarguments, competing approaches, prior art the plan duplicates, missing user stories from the problem space, domain conventions violated without rationale, and known failure modes in similar systems.
- **tests**: Snapshot test asserting category brief and web-search instruction are included; mode-preamble variation.
- **files**: extend `pm_core/adversary/prompts.py`, `tests/adversary/test_prompt_external.py`.
- **depends_on**: Internal inspection prompt — builder + category brief

---

### PR: Cross-reference inspection prompt — builder + category brief
- **description**: Implement `build_cross_ref_prompt(target, project_context, mode)` in `pm_core/adversary/prompts.py`. Context bundle includes **all** plans and specs in the project (not just the target), plus relevant notes. Category brief covers contradictions across plans, plan↔spec drift, user-story overlap, term drift, and declared-dependency incoherence.
- **tests**: Snapshot test asserting the context bundle loads all plans and specs and that the category brief is included.
- **files**: extend `pm_core/adversary/prompts.py` and `pm_core/adversary/context.py`, `tests/adversary/test_prompt_cross_ref.py`.
- **depends_on**: Internal inspection prompt — builder + category brief

---

### PR: Adversary integration into `pm plan add` + plan-gen prompt updates
- **description**: Update the plan-generation prompt in `pm_core/cli/plan.py` to require a `## User stories` section (actor-first one-liners) before `## PRs`, and require each PR description to list the user story/stories it delivers. When the first `## PRs` block lands, the plan-add session triggers the adversary loop against the plan (Flow A), honouring `adversary-mode`. Plan-add session listens for new queue items and revises/responds between rounds. **Human-guided testing**: run `pm plan add` end-to-end in each mode, confirm user-story section produced, adversary pane spawns, revisions land, loop terminates sensibly. Call out `INPUT_REQUIRED`.
- **tests**: Prompt-content assertions (user-stories requirement present); integration test that the adversary loop is invoked at the right point with correct target.
- **files**: `pm_core/cli/plan.py`, possibly extend `pm_core/adversary/loop.py` to expose a plan-hook entry point, `tests/cli/test_plan_add_adversary.py`.
- **depends_on**: Adversary iteration loop + `adversary-mode` config, Internal inspection prompt — builder + category brief, External-adversarial inspection prompt — builder + category brief, Cross-reference inspection prompt — builder + category brief

---

### PR: Adversary integration into Step-0 spec generation + spec-gen prompt updates
- **description**: Update `_build_spec_prompt()` in `pm_core/spec_gen.py` to require an enumeration of step-by-step user actions that should work after the PR lands, linked to the parent plan's user stories. Hook the adversary loop (Flow B) into spec generation: after the draft spec is produced, launch the adversary against it, honouring `adversary-mode`. Gate `spec_pending` clearance on loop termination. **Human-guided testing**: run `pm pr impl` on a PR in each mode, confirm spec includes user-action enumeration, adversary spawns, `AMBIGUITY_FLAG` still pauses correctly. Call out `INPUT_REQUIRED`.
- **tests**: Prompt-content assertions; integration test that spec generation invokes the adversary loop with correct target and that `spec_pending` state transitions on termination.
- **files**: `pm_core/spec_gen.py`, `tests/spec/test_spec_gen_adversary.py`.
- **depends_on**: Adversary iteration loop + `adversary-mode` config, Internal inspection prompt — builder + category brief, External-adversarial inspection prompt — builder + category brief, Cross-reference inspection prompt — builder + category brief

---

### PR: TUI — open-question counts on plans and PRs
- **description**: Badges on plans pane and PR/tech-tree views showing counts in three buckets: **open** (including accepted/deferred), **needs_user_input** (prompt-mode escalations awaiting a user response), and **needs_verify** (resolved but unverified). Plans show counts for questions targeting the plan directly. PRs show counts for questions targeting the PR's spec (since adversarial questions target plans and specs — the PR-level badge surfaces its spec's queue). Each bucket gets a distinct glyph/color. Counts computed from `pm/questions/` on refresh. **Human-guided testing**: TUI visual — reviewer confirms all three badges render, refresh on state change, don't clutter narrow panes. Call out `INPUT_REQUIRED`.
- **tests**: Unit tests for count-per-target helper. Snapshot render tests.
- **files**: `pm_core/tui/plans_pane.py`, `pm_core/tui/tech_tree.py`, `pm_core/tui/pr_view.py`, `pm_core/questions/counts.py`, `tests/tui/test_question_badges.py`.
- **depends_on**: Question and response data model + store

---

### PR: TUI — questions & responses browser pane
- **description**: New pane / screen (keybinding `?`) listing open questions for the selected plan/PR. Keys: respond (`r`), dismiss (`d`), defer (`f`), resolve (`R`), expand to see the full response history for a question (`enter`), challenge a specific response (`c` on a response row), jump to source artifact (`o`). Makes the revisit-old-responses flow visible in the TUI. **Human-guided testing**: keybinding and navigation. Call out `INPUT_REQUIRED`.
- **tests**: Unit tests for each action handler against a fixture question+response set. Snapshot render tests.
- **files**: `pm_core/tui/questions_pane.py`, `pm_core/tui/app.py` (wire keybinding and pane mounting), `tests/tui/test_questions_pane.py`.
- **depends_on**: TUI — open-question counts, `pm questions` CLI, `pm responses` CLI

---

### PR: `pm tts` — togglable TTS output layer with tmux + TUI binding
- **description**: Implements the TTS feature described in the "Voice input and TTS output" design section. Toggled from inside any pm Claude Code session the same way `/rc` is invoked. No new session type, no new tmux window, no primer. Complements Claude Code's built-in `/voice` so the user can pair them in any session for hands-and-eyes-free operation.
  - **Commands**: `pm tts on` (start on current pane), `pm tts off` (stop), `pm tts toggle` (on→off / off→on / migrate if active elsewhere), `pm tts status` (print active binding).
  - **Tmux keybinding**: register a pm-namespaced key (e.g. `prefix + T`) in pm's existing tmux setup (`pm_core/tmux.py`) that runs `pm tts toggle` against the focused pane. Matching TUI keybinding from inside the pm TUI.
  - **Singleton invariant**: exactly one `pm tts` daemon runs globally at a time, enforced via a lock file at `~/.pm/tts/active.lock` (O_EXCL on create) storing `{pid, pane_id, session_name, started_at}`. Starting in a different pane while one is active transparently migrates: stop old, start new, emit a brief notice ("TTS moved to %pane_id"). Same pane → idempotent. Stale lock (pid not alive) is cleared before retrying.
  - **Detached from user focus**: the daemon is bound to a specific pane at start. Switching tmux panes / windows / sessions has no effect — TTS keeps reading the originating Claude session. Exits cleanly only on `pm tts off`, migration, or bound-pane death (graceful shutdown + lock cleanup).
  - **Signal sources, post-processing pipeline, config, and backend**: as specified in the "Voice input and TTS output" section. Implementation lives across `pm_core/voice/tts.py` (post-processor + TTS driver), `pm_core/voice/lock.py` (singleton), `pm_core/voice/pane_tail.py` (pane capture), `pm_core/voice/jsonl_tail.py` (JSONL fallback), and a hook-config installer for `PreToolUse` / `PostToolUse` / `Notification` / `Stop` / `SubagentStop` / `UserPromptSubmit`.
  - **TUI indicator**: small status-area element showing which pane TTS is bound to (if any), so the user always knows where output is being read from without running `pm tts status`.
  - **Human-guided testing**: run `pm tts on` (or hit the binding) in one session, produce a prompt with prose + code edits, confirm prose is read aloud and code is skipped. Switch tmux panes/windows — TTS should keep reading. Hit the binding in a different pane — TTS should migrate with the notice. Kill the originating pane — TTS should clean up. Call out `INPUT_REQUIRED`.
- **tests**: Post-processor unit tests (fixture pane snapshots + hook events → spoken/skipped assertions). Singleton-lock tests: idempotent same-pane, migration, stale-lock recovery. Bound-pane-death cleanup. Backend selection. Tmux-binding registration smoke test.
- **files**: `pm_core/cli/tts.py`, `pm_core/voice/tts.py`, `pm_core/voice/lock.py`, `pm_core/voice/pane_tail.py`, `pm_core/voice/jsonl_tail.py`, extend `pm_core/tmux.py` for the keybinding, extend `pm_core/tui/app.py` for the TUI binding + indicator, `tests/voice/test_tts_filter.py`, `tests/voice/test_tts_lock.py`, `tests/cli/test_tts_cli.py`.
- **depends_on**:

---
