# Addendum — ground the living-artifacts lit review in the plan's concrete pm instances

Date: 2026-05-15
Supplements: `REVIEW_RESPONSE_LIVING_ARTIFACTS_DRAFT1.md`

## The feedback

> "Increase focus on the examples from the plan file and usage in our tool and what it enables — similar to the earlier criticism about incorporating comparison to Claude Code features."

## Diagnosis

Same shape as the Claude Code grounding gap on the regression-loop review. The first draft surveys abstract prior work (actor model, blackboard, CRDTs, Engelbart, MemGPT, AutoGen) competently — but a reader finishes it knowing the *intellectual lineage* without knowing *what the plan actually proposes to build in pm and what that unlocks*. The plan (`plan-984dfeb.md`) is concrete: it names four sequenced instances (plan files → PRs → pm-itself → the code stretch study) plus four "where this leads" directions. The lit review should be grounded in those instances, not float above them.

The fix: a new section that walks the plan's concrete instances, and for each — (a) what pm does today and where it hurts, (b) what the living-artifact version changes, (c) what new workflow it enables, (d) which prior-work cluster from the survey it draws on. This makes the abstract survey *land*: each prior-work primitive gets tied to the pm instance it bears on.

## Planned change: a new section — "The plan's instances, grounded in pm"

Place it after the prior-work survey sections and before the conclusion (so the survey gives the vocabulary, then this section applies it, then the conclusion states the contribution). For each instance below, the lit review should write a short grounded subsection.

### Instance 1 — plan files become living artifacts (first milestone)

- **pm today**: a plan is static markdown (`plans/*.md`) plus a `project.yaml` entry. Keeping it coherent — the consistency-checking, the dependency-graph audits, the narrative-flow passes — is manual work a human (or a plan-review session) does. This entire adversarial-review effort is an example: a human kept noticing drift and prompting fixes.
- **Living-artifact version**: the plan carries its own task queue and self-maintenance schedule. The coherence-check becomes a self-maintenance task the artifact spawns from its own "wants."
- **What it enables**: the plan notices its own staleness. A PR whose description drifts from the plan's motivation triggers a negotiation, rather than waiting for a human to run a plan-review session and catch it. The plan-review loop we ran by hand becomes a standing property of the artifact.
- **Prior-work cluster**: blackboard systems (the plan as a shared substrate multiple tasks read and post to); Engelbart/Victor (the human-readable rendering requirement — the plan stays markdown-renderable so humans can still audit).

### Instance 2 — PRs become living artifacts (later milestone)

- **pm today**: a PR spec is markdown; the impl/review/QA/merge flow is pm orchestration code — a state machine that watches PR status and advances it. The bug-fix watcher externally detects "this PR is stuck" by pattern-matching repeated NEEDS_WORK.
- **Living-artifact version**: the PR's spec is the document; the phases are tasks in the PR's own queue; pm's orchestration becomes negotiation inside the PR artifact.
- **What it enables**: a PR whose QA keeps failing doesn't need an external watcher to notice it's stuck — the PR's own self-maintenance surfaces the impasse as a want. The watcher's stuck-detection logic (`pr-e3a711c`'s escalation path) becomes the artifact's own concern.
- **Prior-work cluster**: actor model and contract-net (the phases as tasks negotiating); the negotiation-protocol literature.

### Instance 3 — pm's orchestration becomes the artifact protocol (eventual milestone)

- **pm today**: pm is a state machine; `project.yaml` holds workflow state. This conversation repeatedly worked around that central state — `project.yaml` merge conflicts, a concurrent merge-in-progress, stale-state notifications.
- **Living-artifact version**: pm becomes a renderer and host; every flow (start, review, QA, merge, watchers, sync) is a task type over the artifact substrate; `project.yaml` no longer holds workflow state.
- **What it enables**: removes the central state machine that this whole session kept colliding with. The "no central arbiter" claim, grounded: pm's state machine *is* the central arbiter today, and the plan's endpoint is its removal.
- **Prior-work cluster**: Linda tuple spaces and the LLM-OS framing (pm as a host/renderer rather than an orchestrator).

### Instance 4 — code as living artifacts (stretch study)

- **pm today**: nothing — pm doesn't touch program optimization.
- **Living-artifact version**: functions/modules as living artifacts that negotiate optimizations peer-to-peer (the plan's A-talks-to-Y scenario — artifact A notices via its own profiling-driven self-maintenance that it spends most of its time on task X from artifact Y, and opens a negotiation with Y directly).
- **What it enables**: autonomous program optimization without a central profiler-plus-optimizer; the human at the boundary, not on the critical path.
- **Prior-work cluster**: market-based / decentralized coordination; the self-organizing-systems literature.

### The "where this leads" directions

The plan also names four follow-on directions (new evolutionary algorithms, self-organizing knowledge bases, self-tuning infrastructure, living research workflows). The lit review should mention these briefly as substrate-enabled follow-ons — not survey them in depth, but note that each is a domain where the same data structure unlocks something currently bottlenecked by external orchestration. One or two sentences; they are not on the plan's critical path.

## How this differs from the Claude Code grounding section

The §8 Claude Code grounding section answers "how does the living-artifacts model relate to the tool people use today." This new section answers "what does the plan concretely build in pm, and what does each instance unlock." They are complementary: §8 is the *external* grounding (vs. the dominant tool), the new section is the *internal* grounding (vs. pm's current state). Both are antidotes to an abstract-survey-that-floats.

## Edits checklist (additions to the seven in the main response)

8. Add the new section "The plan's instances, grounded in pm" after the prior-work survey, before the conclusion. Four grounded subsections (plan files, PRs, pm-itself, code stretch study), each with: pm-today / living-artifact-version / what-it-enables / prior-work-cluster-it-draws-on. Plus a short paragraph on the four "where this leads" directions.
9. In each prior-work survey section, add a forward-reference to the pm instance that section's primitive bears on (e.g., the blackboard section points forward to Instance 1; the actor-model section to Instance 2). This threads the abstract survey to the concrete instances so the survey doesn't float.
10. In the conclusion, when stating the core contribution (the data structure — non-deterministic, relational, intelligence-resolved), tie it to the instances: the contribution is proven by building Instances 1-3 in pm, with Instance 4 as the stretch demonstration that the substrate generalizes beyond project management to code itself.

## Sequencing note

This addendum's edits (items 8-10) should be applied in the same follow-up pass, after the in-flight edit applying the main response's items 1-7. The two passes don't conflict — items 1-7 restore framing and rebuild the conclusion; items 8-10 add the grounding section and thread the survey to it. The conclusion rebuild (item 7) and the conclusion-ties-to-instances edit (item 10) touch the same section, so apply them together: the rebuilt conclusion should already incorporate the instances tie-in.
