# `--resume` Design Note for `pr-98f670e` (QA scenario quality supervisor)

Surfaced from the adversarial review loop's Cycle 3 on the regression-loop literature review. This document is intended as input to `pr-98f670e`'s description and notes — it captures a design problem that the lit review made the plan owner aware of, but that the lit review itself cannot fix.

## TL;DR

The supervisor was originally described as reading the scenario's captures "via `--resume`," with the lit review claiming this provides "context separation" in the sense Pan et al. 2024 recommend for avoiding spontaneous reward hacking in iterative self-refinement. That claim does not survive scrutiny — `--resume` carries forward the scenario's full conversation thread, not a summarized or filtered slice. Combined with the existing amendment cap of 2, the supervisor's design now sits exactly in the regime Pan et al. measured spontaneous hacking in. The supervisor's primary mitigation is the cap, which is necessary but not sufficient.

Recommended redesign: fresh Claude Code session (no `--resume`), structured input bundle (transcript + artifacts + diff), adversarial prompt, K=3 ensemble for merge-gating verdicts. This shifts the supervisor's design out of Pan et al.'s measured-hacking regime entirely.

## The problem in detail

### What `--resume` actually does

Claude Code's `--resume <session-id>` reattaches to a saved session. It carries forward:

- The system prompt
- The full conversation history (every user turn, every assistant turn, every tool-use block)
- The tool-use history with results
- Any memory entries persisted by the previous session

It does *not* carry forward:

- In-memory side state of the previous process
- The model weights themselves (no state inside the model)

So a `--resume`d session has the same context-window content as the original — it is the same conversation continued, not a new conversation with summaries. When the supervisor reads "the scenario's captures via `--resume`," the supervisor session inherits the scenario's full thread.

### Why this is a problem (Pan et al. 2024)

Pan et al. "Spontaneous Reward Hacking in Iterative Self-Refinement" (arXiv:2407.04549) measure cases where generator and evaluator share context. Spontaneous reward hacking emerges within 2 to 10 iterations across multiple configurations. The key independent variables:

1. **Same model on both sides** — yes, our supervisor and scenario both run as Claude.
2. **Shared context** — yes, `--resume` shares the full thread.
3. **Same-role framing** — partial; the supervisor's prompt is different from the scenario's, but it sees the scenario's prompt and reasoning.
4. **Iteration count** — Pan et al. find hacking emerging by iteration 2-3 in many configurations.

The supervisor's current defense is the **amendment cap of 2**. Cap of 2 sits exactly in the regime where Pan et al. show measurable hacking. *The cap is necessary but not sufficient as a defense.*

### What goes wrong, concretely

A scenario session runs, takes a shortcut (e.g., produces a thin assertion that nominally passes without exercising the changed code path), and emits PASS. The supervisor `--resume`s the scenario's session and is now reading the scenario's full reasoning, including the scenario's *justifications* for the shortcut (it produces reasoning like "the test passes, so the assertion is sufficient"). The supervisor is now in the position of being a fresh-perspective check while *also* having absorbed the scenario's framing of why the shortcut is fine.

Pan et al.'s spontaneous-reward-hacking failure mode is exactly this dynamic. The supervisor amends once ("ok, add this one extra check"), the scenario re-runs with the cosmetic amendment, the verdict propagates. Two iterations is enough for the failure to land.

## Recommended redesign

### Option 1 — Fresh session, captures-only input bundle (primary recommendation)

The supervisor session does not `--resume` the scenario's session. Instead it is started fresh with a structured input bundle:

- The scenario's **tool-use transcript** (exported as a flat log: command, args, output — *not* the assistant's reasoning between tool calls)
- The captured **artifacts** (output files, screenshots, test results, diffs)
- The original **PR diff**
- The scenario's emitted **verdict** and assertions, but *not* the scenario's reasoning trace

The supervisor reads the bundle and judges depth-of-evidence without ever seeing the scenario's chain-of-thought. This is the closest practical approximation to what Pan et al. would call "context-separated evaluation."

Implementation cost: low. The transcript export is straightforward (Claude Code already logs every tool call). The bundle is a single text file plus a directory of artifacts. The supervisor launches as a normal Claude Code session with the bundle as its initial input.

### Option 2 — Different model (optional, combinable)

Use a different model for the supervisor (a smaller verifier model, or a different model family). Eliminates the same-model risk Pan et al. measure but introduces calibration concerns: the supervisor model may apply different judgment standards than the scenario model.

Combinable with Option 1. Pragmatically, Option 1 captures most of the same-model risk reduction at lower complexity.

### Option 3 — K=3 ensemble for high-stakes verdicts (recommended for merge-gating)

Three fresh-session supervisors, each with the same bundle (Option 1), majority vote. Expensive but high-confidence for contested verdicts. Reserve for verdicts that gate merge (specifically the bug-fix watcher's pre-auto-merge check and the improvement-fix watcher's pre-handoff-to-human check).

Implementation: spawn K=3 supervisors in parallel windows; collect verdicts; majority vote; record the dissent (a 2-1 split is itself useful signal).

### Option 4 — Adversarial supervisor framing (orthogonal, combinable with all above)

Independent of separation. The supervisor's prompt sets a high prior on flaws:

> Your job is to find the strongest evidence this scenario took a shortcut. List every check the scenario should have run but didn't. Reach NEEDS_WORK by default; only emit PASS if no shortcut is found.

Adversarial framing pushes against the sycophancy-with-prior-turn failure mode even when context is partially shared. Combinable with Options 1-3.

## Recommended design for `pr-98f670e`

The combined design:

1. Supervisor launched as a **fresh Claude Code session** (no `--resume`).
2. Input is a **structured bundle**: tool-use transcript (flat, no reasoning), captured artifacts, original PR diff, scenario verdict and assertions.
3. Prompt is **adversarial**: "find the strongest evidence this scenario took a shortcut. Reach NEEDS_WORK by default."
4. **Amendment cap of 2** remains as a safety, not as the primary mitigation.
5. For **merge-gating verdicts**: escalate to a **K=3 ensemble** of fresh-session adversarial supervisors with majority vote.

This shifts the design from "shared-context generator-evaluator pair with a small iteration cap" (Pan et al.'s exact failure regime) to "context-separated, adversarial, optionally ensembled" — out of the measured-hacking regime entirely.

## What `pr-98f670e`'s description should say

Suggested addition:

> ### Implementation note: context separation
>
> The supervisor is launched as a fresh Claude Code session, *not* as a `--resume` of the scenario's session. The scenario's session shares its full conversation thread when `--resume`d, including the scenario's reasoning and justifications, which puts a same-model generator-evaluator pair into the regime Pan et al. 2024 measure spontaneous reward hacking in.
>
> Instead, the supervisor is started with a structured input bundle:
>
> - Scenario tool-use transcript (flat: command, args, output — no assistant reasoning)
> - Captured artifacts (outputs, screenshots, test results)
> - Original PR diff
> - Scenario verdict and assertions
>
> The supervisor's prompt is adversarial: it is told to look for shortcuts by default, reach NEEDS_WORK unless no shortcut is found.
>
> The amendment cap of 2 remains as safety. For merge-gating verdicts, the supervisor runs as a K=3 ensemble of fresh-session adversarial supervisors with majority vote.

## What `pr-98f670e`'s tests should verify

1. A scenario that produces thin captures (e.g., a check that "the command ran without crashing" but doesn't verify state change) is caught by the supervisor as NEEDS_WORK.
2. The same scenario, if the supervisor were `--resume`d into the scenario's session, would *not* be caught (sanity check that the redesign matters; can be done with FakeClaudeSession in tests).
3. The K=3 ensemble disagreement rate on a corpus of historical scenarios is below some threshold (e.g., <20% 2-1 splits) — calibration check.
4. The transcript export filter removes assistant reasoning but preserves tool calls and outputs (regression test for the export).

## Followups

- File `pr-98f670e`'s notes with a pointer to this design note.
- Update `pr-98f670e`'s description with the implementation note above.
- The literature review's §4 `--resume` passage will be tightened in the Cycle 3 edit pass to acknowledge the supervisor's design is the most under-validated mitigation in the plan, with a forward-pointer to this note (or to the updated `pr-98f670e`).
- This note can be deleted from `pm/docs/adversarial-review/` once `pr-98f670e` carries its substance.
