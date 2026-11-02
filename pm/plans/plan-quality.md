# Quality — Continuous Code-Health
(type hygiene at every step + an automated project-health-check session)

## The thesis

Once the automated test + QA loop (plan-regression) gives us a real safety net, **refactor-only** work — restructuring without changing behavior — becomes safe to do continuously. Today nothing in pm auto-improves code quality without changing features: every code-touching pass (impl, QA fix, review fix) is feature- or bug-driven. This plan adds the missing leg: a behavior-preserving track that finds type-hygiene gaps, promotes conventions to formal types, splits oversized files, reduces line count, and proposes its own refactor PRs through the same loop.

### Motivating example — the missed `signoff` session type

`pr-2d5f712` introduced a new sign-off agent. Every QA scenario that exercised auto-sequence + sign-off ran against a **real Claude session** for the router — expensive, slow, non-deterministic — because the new `signoff` session type **was never registered** in any of the three canonical places it should have been:

- `model_config.SESSION_TYPES` (the canonical session-type tuple),
- `fake_claude.SESSION_TYPE_VERDICTS` (which makes `FakeClaudeSession` able to script verdicts for a type),
- the launch-site `session_type="signoff"` argument to `build_claude_shell_cmd`.

This **was not caught** by the impl agent, the review-loop, three rounds of QA scenarios (which collectively did exercise the sign-off router behaviorally), or any sign-off agent pass on the PR itself. It was caught only when a human asked, on round 3, "are the sign-off scenarios running against a fake or real Claude?". Root cause: each of those three registries was a **convention, not a type**. There was no structural mechanism — no `SessionType` base class with required mock and required registration, no protocol that fails to instantiate unless all three sites are wired — to make the omission impossible. And there was no review or planner prompt asking "this PR adds a new instance of an existing concept (session type) — is it consistent with the siblings?".

A formal `SessionType` (subclass / protocol with required mocks and registration) would have made this omission impossible to commit. **This plan is in large part the response to that miss.**

### A second example — the missed TUI keybinding for sign-off

Same PR, same pattern, different sibling set. `pm_core/tui/app.py` declares `Binding(...)` entries for every other lifecycle action — `s` start, `d` review, `t` QA, `g` merge, `O` auto-sequence — but `pr-2d5f712` never added one for sign-off. The `?` help modal (which lists `show=True` bindings) accordingly never showed sign-off as a TUI action. Caught by the user (`note-738679f`, 2026-05-26) *after* the PR had reached merge-clean QA — the surrounding lifecycle scaffolding (status icon, `valid_statuses`, `pm pr list` glyph, tech-tree rendering, verdict icons, the sign-off window launcher itself) was all in place, but the one tuple of sibling action keys was a convention with no structural check.

Same root cause as the session-type miss: **adding an N-th instance of a concept (lifecycle action key) without any mechanism asking "is the new instance consistent with the existing siblings?"**. A formal lifecycle-action registry (or even a unit test that walks every lifecycle status enum and asserts each has a `Binding` with `show=True`) would have made the omission impossible to commit. The fact that two analogous gaps in the same PR slipped past impl + QA + review + sign-off independently is itself the strongest possible signal that this category of audit is missing.

### The general pattern — strings being used as type names

Both motivating examples (and the verdict-registry prototype below) share a single root cause: **a string is being used where a type would be**. A `session_type: str`, a `status: str`, a tuple of magic strings for keybinding registration — each is a stringly-typed convention with no structural integrity check at the seams. Adding a new instance of the concept requires updating every sibling site, and the typecheck never helps.

The fix family — typed enums, typed value-object hierarchies, typed registries, abstract base classes with `__init_subclass__` enforcement — turns each into a structural family where adding a new instance either fails at import (missing required attribute) or is impossible to reference at all (no string ever names it).

The [[plan-mind]] / [[plan-sensorium]] refactor has applied this pattern to: Stream roles (Stream subclasses with `__init_subclass__` validation), PR-action streams (PRActionStream base with required TUI fields), Channel names (typed `Channel` value-object hierarchy), ResourceKeys (typed `ResourceKey` hierarchy), VisibilityTier (proper enum), PRStatus (StrEnum), Tag (typed registry), PmCommand (typed hierarchy auto-generated from argparse), EditableArtifact registrations (typed subclasses). Track B inherits the discipline: any new `: str` parameter or string-keyed registry is a Track B audit candidate, and the "strings being used as type names" finding type (below) is its own category in the audit prompt.

### A prototype already exists

**`pr-1d8b2b7` (verdict-registry consolidation)** is a perfect prototype of the work this plan generalizes: two places defined the same set (the detector and `fake_claude`), drift was the silent failure mode, and the fix is one canonical typed surface that both import from. We need a process that finds these systematically.

## Goal (one line)

A **behavior-preserving** track in the development loop — both via existing-step prompt addenda AND via a new project-health-check session — that continuously proposes type/structure/file/directory refactors that reduce complexity and line count while making the code more consistent and future-proof.

## Boundary (what this plan is NOT)

- NOT new features.
- NOT bug fixes (those keep going through review/QA as today).
- Every PR from this track is **behavior-preserving**: same public API, same test outputs, all existing QA scenarios pass unchanged. The gate is "diff has no behavior change."

## Two tracks

**Track A — Existing steps become quality-aware.** Small prompt addenda to the review / impl-spec / sign-off / QA-planner prompts that introduce a "type hygiene" lens: when adding an instance of a concept, check sibling consistency; when a concept appears informally in two or more places, propose making it a formal type; when a new entity is introduced, enumerate every registry it should be in.

**Track B — Project Health Checker session.** A new session type (`health_check`) that runs on a cadence, audits the codebase for structural smells, and files behavior-preserving refactor PRs into this plan.

Track A catches type/hygiene gaps **at the moment of edit** — high precision, low coverage of past mistakes. Track B catches them **proactively across the whole codebase** — lower per-audit precision, high coverage. They complement.

## Depends on

- **plan-regression** — the automated test + QA + sign-off loop is what makes behavior-preservation a real, checkable property. Land plan-regression first.
- **pr-1d8b2b7** (verdict registry) — the prototype of "twin-registry consolidation." Track B's first audit category is "find more pr-1d8b2b7-shaped registries."
- The earlier manual **plan-e4fa5cb** (refactor for code quality, done) — manual precedent, lessons learned.

---

## Track A — Quality-aware existing steps

### PR: Type-hygiene addendum to the review prompt

Extend the review prompt with a "type hygiene" lens applied to every PR diff:

- **New instance of an EXISTING concept** (status, session type, verdict, watcher, lifecycle step, …)? Verify consistency with sibling instances — same registries updated, same prompt shape used, same status/icon-map entries added.
- **Concept appearing informally in two or more places in this PR**? Propose extracting a formal type (dataclass, protocol, base class) and a single canonical source of truth.
- **New ENTITY introduced** (status enum value, session type, verdict family)? Enumerate every canonical registry it needs to be in; flag missing entries.
- **Refactor opportunity flagged without acting on it** — surface as a note + recommend a follow-on refactor PR per Track B's PR-generation flow. The review's job is to flag, not to expand scope mid-PR.
- **Prompt hygiene on prompt-builder changes** — when a PR modifies a prompt template, check that removed concepts were CLEANLY DELETED, not turned into `do NOT X` negations (those become vestigial residue once the surrounding context is updated). Also flag the same invariant negated three or more times across one prompt and any negative directive that has an obvious positive rephrasing. The full audit lives in Track B; review just catches the obvious cases at edit time.

Plan: this plan.

### PR: Same addendum applied to the impl-spec generation prompt

Mirror the review-prompt addendum at spec time, so missing registry updates land in the PR's stated scope and naturally cascade into the impl + QA scenarios + review. Catches the gap one stage earlier than review.

Depends on: the review-prompt addendum (shared addendum text).

### PR: Same addendum applied to the sign-off prompt's per-step review

The sign-off agent already walks every step and verdict. Have it raise type-hygiene findings as either (a) an INPUT_REQUIRED with a clear classification, or (b) a recommendation to file a follow-on refactor PR rather than bouncing back to impl. Sign-off's job remains a recommendation — the work itself becomes a separate behavior-preserving refactor PR.

### PR: Type-hygiene / structural-integrity axis in the QA planner

Today the planner covers nominal / error / concurrent. Add a fourth axis: "for any new entity this PR introduces, generate at least one scenario that asserts it's present in every canonical registry it should be in." Catches the signoff-session-type-style omission deterministically per PR.

---

## Track B — Project Health Checker session

### PR: Introduce the `health_check` session type

Register `health_check` in `model_config.SESSION_TYPES`, add `_FALLBACK_TYPES["health_check"] = "review"`, add `(HEALTH_DONE, HEALTH_BLOCKED)` to `fake_claude.SESSION_TYPE_VERDICTS`, pass `session_type="health_check"` at the launch site, expose `pm pr health-check` (or `pm project health`) as the manual entry.

**Meta-circular check:** this PR is the first real test of the Track A type-hygiene checks. The impl-spec and review prompts should catch any missed registry on their own; if either misses, that's a bug in the addendum to fix before continuing.

Depends on: Track A PRs.

### PR: Health-check audit prompt and PR-generation flow

The audit prompt enumerates the categories the session looks for, and the shape of each refactor proposal. Initial categories:

- **Twin-registry / drift candidates** — pairs or triples of constants that must be kept in sync but live in separate modules (the `pr-1d8b2b7` verdict-registry pattern; the `signoff` session-type pattern). Proposal: extract to a single registry with a typed accessor; have both call sites import from it.
- **Conventions worth promoting to formal types** — dicts repeatedly built with the same key set; tuples passed through multiple call sites; magic-string identifiers without a typed wrapper; status-like enums encoded as raw strings. Proposal: introduce a dataclass / `NewType` / protocol; thread it through.
- **Strings being used as type names** — a focused subcategory of the above, called out separately because it is the most common shape of the convention-not-type failure. Specifically scan for: (a) function/method parameters typed `str` whose set of valid values is a closed enumeration (e.g. `role: str`, `kind: str`, `status: str`, `command: str`, `tag: str`); (b) registry lookups keyed by string where the key set is finite and known at design time; (c) dict-of-strings used as a poor-man's discriminated union; (d) string concatenation building structured identifiers (`f"pr:{id}:review-verdicts"` as channel names, resource keys, agent ids). Each is a candidate for promotion to a typed value-object hierarchy, an enum, a typed registry, or a dataclass. The mind/sensorium refactor already converted Channel names, ResourceKeys, PRStatus, VisibilityTier, Tag, Stream roles, PmCommand, and Artifact registrations under this rubric — Track B should keep the discipline applied: every new string-typed parameter or registry key is an audit candidate. Proposal: name the typed family, list the existing call sites, propose the conversion shape.
- **Context-loss resilience in prompts** — every `InputType` subclass (i.e. every prompt and message we send) MUST be written assuming the receiver's prior conversation context could disappear at any point. Specifically scan for: (a) prompts referring to "as we discussed" / "continuing from" / "the previous turn" / similar context-dependent phrasing; (b) prompts that omit task framing because the receiver is presumed to remember it; (c) prompts that reference unspecified state ("the issue we found") instead of citing typed `ArtifactType` refs (a `GitDiffAtSha`, `LogQuery`, `TranscriptSlice`). The structural backing is [[plan-mind]]'s log-replay regen — if a stream's runtime evicts and is rebuilt from inputs, every prompt that's context-loss-resilient still works. Prompts that fail this property silently degrade. Proposal: rewrite the failing prompts to self-contain their task framing and cite typed refs for any state they need.
- **Phase-awareness in multi-phase prompts** — every prompt for a Stream that goes through multiple phases (impl: spec-gen → spec-approval → implementation; qa-planning: plan-gen → plan-approval → scenario fan-out; review-cycle within a PR; etc.) MUST query the EmissionLog for the latest phase emission and render appropriate "you're at phase X; here's what's been done" context at the top. Otherwise a cold restart (log-replay regen with no keep-warm) re-runs completed phases. The structural backing is that phase transitions are durable Emissions (`phase.impl.spec-proposed`, `phase.impl.spec-approved`, `phase.qa-plan.complete`, ...) that survive runtime swaps; the prompt obligation is to consult them. Specifically scan for: (a) prompts that always start "begin drafting the spec" regardless of whether `phase.impl.spec-approved` has already fired; (b) prompts that don't render any progress context, just task framing; (c) prompts that infer progress from chat history rather than the EmissionLog (chat history is gone on restart; the log is not). Proposal: every multi-phase InputType renders a `Stream.render_phase_context()` block at the top of its system prompt that queries `mind.log_of(stream_id).latest('phase.*')` and produces a "Current phase: X. Prior steps: Y, Z." prelude. Audit by mechanically asserting that every InputType for a stream whose `output_emissions` contains any `phase.*` tag also calls the phase-context renderer.
- **Oversized files (line count + theme analysis)** — files past a configurable threshold that mix multiple responsibilities. Proposal: split along the natural seam, with file/import-path moves enumerated.
- **Sprawling or shallow directories** — too-flat module structure or too-deep stacks. Proposal: reorganize.
- **Coupling smells** — circular imports, parameter chains threading state through many functions, repeated `isinstance` ladders that should be polymorphism. Proposal: introduce an interface or move state to a common owner.
- **Future-proofing opportunities** — places where an upcoming change (named in plan files) will require touching many call sites because of rigid coupling. Proposal: decouple now.
- **Prompt hygiene** — scan every prompt-builder (`pm_core/prompt_gen.py`, scenario / spec / review / sign-off / planner prompt builders) for three patterns: (a) **vestigial negations** — `do NOT X` / `never X` / `must not X` lines that refer to a concept no longer mentioned anywhere else in the prompt or codebase (residue from a removed instruction that should have been a clean deletion, not a negation); (b) **repeated negations of the same invariant** — the same "never does X" / "does not Y" stated three or more times across one prompt (consolidation candidate: state once with strong framing, then use the positive verb everywhere else); (c) **negative directives with an obvious positive rephrasing** — e.g. `Do NOT spot-check, walk every scenario` → `Walk every scenario and every step`. Proposal: clean each prompt to the positive form; verify the meaning is preserved by re-running the relevant fake-claude / regression tests. Motivating example: pr-2d5f712's sign-off prompt (audited 2026-05-26) cleanly removed every reference to the removed `autonomy` / `capture gate` concepts (no residue) but still over-emphasised "sign-off never merges" three times — the kind of consolidation Track B should catch routinely. In addition to the intra-codebase categories above, the audit also seeds candidates from outside the repo, to avoid the limit of "we only see patterns we've already met":

- **Similar projects** — search for open-source projects with comparable shape (Python TUI orchestrators, agent-loop frameworks, multi-session test infrastructure) and compare their type structure / module layout / public APIs. Where they have a formal type for a concept we encode as a convention, propose adopting (or adapting) it.
- **Programming guides / language idioms** — pull in current Python language idioms (dataclasses, `typing.Protocol`, `Enum`, `NewType`, `Final`, `Literal`) and best-practice articles for the patterns the audit is touching. Propose idiomatic replacements for stale shapes (e.g. dict-with-known-keys → dataclass; magic strings → `Literal` or `StrEnum`).
- **Architectural best-practice references** — search for canonical write-ups on the smell category being audited (twin registries, oversized modules, polymorphism vs `isinstance` ladders). Cite the source in the proposal so the human reviewer can see the basis.
- **Provenance is mandatory** — every externally-seeded proposal must cite its source (URL or library name + section) in the PR description, so the reviewer can judge whether the comparison is apt and the pattern is current.
- **Adapt, don't copy** — external patterns are seeds, not prescriptions. The proposal must rephrase the pattern in pm's idiom and call out where it diverges and why.

Each finding becomes one refactor PR via `pm pr add`, filed into this plan (or `plan-quality-batch-N` if batching is needed), tagged with the audit category — internal or externally-seeded — and a before/after estimate (lines, files, types touched).

Depends on: the `health_check` session type PR.

### PR: Behavior-preservation gate for refactor PRs

A specific review/QA gate that asserts no behavioral diff:

- All existing tests pass unchanged (no test edits except mechanical follow-throughs from renamed imports).
- All existing QA scenarios pass without scenario edits.
- Public API surface unchanged — or, if narrowed, the narrowing is explicitly approved by sign-off.
- A diff-summary section in the PR description: lines added / removed, files moved, types introduced, types removed.

This is the structural answer to "how do we trust an automated refactor agent" — it cannot pass review/QA unless behavior is preserved. Reuses Track A's review-prompt addendum as the inner lens.

Depends on: Track A.

### PR: Health-check watcher (discovery-supervisor-style)

A watcher that schedules health-check runs on a cadence (every N days, or after every K merges into a target plan/repo), routes generated refactor PRs into auto-sequence per the standard loop, and respects in-flight scope (won't propose refactors of files currently under active impl). Reuses `pr-271cb3a` (discovery supervisor) patterns and the generalized watcher shape from `pr-ff9b728`.

Depends on: the health-check session type PR; `pr-ff9b728`.

### PR: Project-health surface in the sign-off dashboard

A small section in the `#226` dashboard — "code-health trends" — surfacing the running line-count delta from refactor PRs, types introduced / consolidated count, longest files / largest directories with trend lines. Makes the value of the track visible and lets a reader sanity-check that complexity is actually trending down.

Depends on: `pr-8e693f6` (#226); the health-check session type PR.

### PR: Repeat-audit guard

Prevent the health-checker from filing the same proposal twice. Keep a small persistent record (audit fingerprint per proposal — category + target file/symbol + a content hash of the relevant code region) and skip already-filed or already-rejected audits unless the fingerprint changes. Stops noise from a recurring cadence.

Depends on: the audit prompt PR.

---

## Tooling reference: repowise (https://github.com/repowise-dev/repowise)

[repowise](https://github.com/repowise-dev/repowise) is a "codebase intelligence layer for your AI coding agent" that indexes a repo into five intelligence layers and exposes them via MCP tools + CLI. Its feature set maps almost directly onto Track B's audit categories, and several of its metrics give us **quantifiable proxies for code quality** that the plan would otherwise have to define from scratch. Worth referencing both as a source of patterns and as a candidate to integrate (via its MCP tools) once Track B is ready to land.

**Direct feature → audit-category mapping:**

| repowise feature | Plan-quality use |
|---|---|
| **Hotspot detection** — files ranked by *high churn × high complexity* | Direct input to the "oversized files" and "conventions worth promoting to formal types" categories — these are the files most worth a structural pass. |
| **Change-coupling analysis** — *files that change together in the same commit without an import link*, surfacing hidden dependencies | Direct input to the "conventions worth promoting to formal types" category (co-changing files likely share an unnamed concept that should be a typed seam) and to "sprawling or shallow directories" (co-changing files often belong in the same module). |
| **Two-tier call graphs** (file-level + symbol-level), with 3-tier call resolver + confidence scoring + interactive graph visualization + community detection | Direct input to the "coupling smells" category — circular imports, deep parameter chains, isinstance ladders show up as call-graph density / community-boundary violations. |
| **15 per-file health biomarkers** — McCabe complexity, deep nesting, "brain methods", Rabin-Karp duplication detection, untested hotspots | Lets a refactor PR's behavior-preservation gate add a quantitative "the health score moved the right direction" check alongside the existing "all tests pass + no API change" checks. |
| **Dead code detection** with confidence tiers | A new audit category — *unused code is the cleanest possible refactor* — surfaced deterministically rather than by agent inspection. |
| **Ownership / bus factor** | Useful for the discovery supervisor / health-check watcher to weight which audits to surface first (bus-factor-1 files near the top). |
| **Auto-generated `CLAUDE.md`** with architecture summary, hotspot warnings, ownership maps, decision records | Complementary to the radar plan's session-transcript linker and to pm's existing PR-note / plan-note artifacts — both surface project-state-as-prose for agent consumption. Worth aligning shapes if both end up landing. |

**Two adoption paths to consider (decide at audit-prompt-PR landing time):**

1. **Integrate via MCP.** Repowise ships MCP tools; pm sessions can call them directly. Cheapest path; pm doesn't reimplement anything. The price is a dependency + adopting repowise's data shape for the metrics.
2. **Borrow the patterns; implement what fits.** Reimplement the specific metrics we want against pm's existing git history and call-graph tooling. More work; produces metrics on pm's own terms; no external dependency.

Likely a hybrid in practice — integrate the metrics that are *intrinsically external-tool-shaped* (call graphs, change coupling) via MCP, and reimplement the ones that fit pm's existing surfaces (hotspots, ownership) so the audit prompt can read them inline. Both options stay open until we actually land the audit-prompt PR; calling out the reference here keeps us from inventing the metric definitions from scratch.

**Quantifiable success metrics this unlocks** (additive to "lines removed with feature parity" in the philosophy section):

- **Call-graph complexity should trend down.** A refactor PR succeeds when (e.g.) the symbol-level call graph's average node degree, community-boundary violations, or McCabe sum drops — measured pre-PR and post-PR.
- **Change density should trend up.** When a commit touches more than one file, those files should cluster tightly — same module / same directory / co-located in the call graph. Single-file commits don't contribute to the metric either way (no coupling to measure; a "fewer-coupling-pairs" metric would wrongly reward sprawl-by-trickle). Concretely: average a per-commit tightness score over multi-file commits in a rolling window — e.g. (1 − normalized average pairwise path distance between the touched files in the module/directory tree), or (fraction of pairwise touched-file pairs within the same module). A refactor that takes a chronic cross-module co-change pair and brings them into one module raises this metric; a sprawl refactor that lets the same files keep changing together across modules lowers it.
- **Per-file health score should hold or improve.** A refactor PR that lowers the touched files' health scores is suspect — possibly trading complexity for "I made this shorter but harder to follow."

These are the **measurable** version of "better class structures and types make code better" — they operationalize what otherwise has to be argued case-by-case.

---

## Status counts

- pending: 0 (none filed yet; `pm plan load plan-quality` after approval)
- in_progress: 0
- merged: 0

---

## Notes / philosophy

- The success metric for Track B is **lines REMOVED with feature parity** as the headline number, complemented by the quantitative metrics in the repowise reference above — **call-graph complexity trending down**, **change density trending up** (multi-file commits cluster tightly; single-file commits don't count against this either way), **per-file health scores holding or improving**. A refactor PR that reduces line count but worsens any of those should be reconsidered. Together these are the measurable operationalization of "better class structures and types make code better" — what otherwise has to be argued case by case becomes a small dashboard.
- The **behavior-preservation gate** is what makes this safe to automate. Without plan-regression's loop, this track would be a liability.
- Track A's prompt addenda are tiny (paragraph-scale changes) — high leverage per byte changed.
- Track B is the first **automated process whose explicit goal is to make the code smaller**. That's the philosophical step-change once the safety net is in place.
- Recurrence policy: Track B's watcher runs on cadence; it should NEVER propose more than a small N of refactor PRs at once (configurable, default 3) so the loop doesn't drown in parallel refactor work.

---

## Appendix: same-question-across-many-pieces-of-text (Workflow A/B candidates, deferred)

The shape this plan keeps reaching for — "ask the same audit question across every file / every symbol / every sibling instance" — is the cleanest fit for multi-agent fan-out we have. The motivating examples already in this plan (the missed `signoff` session-type registration, the missed TUI keybinding) are both cases where the right audit was "for each new instance of concept C, check it against every sibling instance" — and the failure mode was that no such audit ran. A workflow that fans out per-file or per-symbol is the natural shape.

We are not adopting workflows now (see [[plan-self-improve#appendix-workflow-ab-candidates-deferred]] for the why — portability, visibility, and no quantitative metric yet to prove the win). But this is the plan where the win is most plausible, because behavior-preserving audits are inherently batch and unattended — you read the resulting PR queue, you don't attach to the audit session. Once the regression-loop metric exists, run these as A/B variants:

- **Track A hygiene addenda as per-PR-touched-file fan-out.** Today the addenda are paragraphs in existing prompts that ask the reviewing/QA/sign-off agent to also check sibling consistency. Hypothesis: one agent per touched file (or per affected sibling-set) catches sibling-set inconsistencies a single combined prompt misses, because the single prompt deprioritizes the audit when the primary task is large. Measure: precision/recall on a fixture set of PRs with seeded sibling-set omissions (the `signoff` and TUI-keybinding misses are perfect seed cases).
- **Track B audit prompt as per-symbol or per-file fan-out.** Today the audit is one prompt over a repo. Hypothesis: for codebases past some size (the "repo-size detection" in plan-001 is the right gate), fan-out per file/module produces more concrete refactor candidates than a single prompt that has to compress the whole tree into its context. Measure: number of merged refactor PRs per audit run, and reviewer-rated quality of proposals.
- **Convention-to-type promotion candidate detection.** Asking "is this string-keyed registry a candidate for a formal type?" across every registry-shaped pattern in the repo. Hypothesis: per-candidate independent judgment beats one prompt enumerating candidates, because the latter biases toward whatever it surfaces first. Measure: precision against a human-curated set of "yes this should be a type" / "no this is fine as convention."
- **Sibling-set completeness audits.** For every concept with N instances (session types, lifecycle action keys, status icons, verdict tokens), ask in parallel "list every place an N+1th instance must be registered, and check the latest instance against that list." Hypothesis: this is the structural mechanism the plan's motivating examples needed. Measure: catches on seeded omissions in held-out PRs.
- **Per-file health-score audit.** The repowise-reference integration could be implemented as one prompt per file scoring the health metrics, then aggregating. Hypothesis: per-file judgments are more calibrated than a single prompt scoring a whole tree. Measure: agreement with repowise's own per-file scores once that integration exists.
- **Citation audit loop (plan-litreview augmented cycle).** The `CITATION_AUDIT_CYCLE_N.md` step already iterates per-citation — for each citation in the artifact, judge tier / passage / faithfulness verdict / proposed rewrite against the cited source. This is the canonical "same question, many pieces of text" shape; today it runs as one sequential session walking the citation list. Hypothesis: per-citation fan-out catches faithfulness issues a single sequential pass loses calibration on as the bibliography grows (especially for `over-characterizes` / `under-characterizes` calls that depend on close reading of one source), and gives a natural place to add an independent verifier per citation against the surfaced verbatim quote. Measure: agreement with held-out human-graded citation verdicts on a fixture artifact, and false-faithful rate on seeded mischaracterizations. Visibility cost is genuinely low here — the audit already writes one entry per citation to disk as it runs, so fan-out preserves the streaming/inspection property the walker UI is built around.

The unifying smell: **"same question, many pieces of text"**. When the prompt's logical structure is `for each X in corpus: judge(X)` and the judgments are independent, fan-out is the natural shape and a single prompt that tries to do it sequentially loses calibration as the corpus grows. The A/B framing keeps us honest about *whether* it actually wins on quality, not just *whether* it feels right.
