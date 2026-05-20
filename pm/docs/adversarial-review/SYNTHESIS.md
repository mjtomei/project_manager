# Interleaved Synthesis (methodology)

The literature review's synthesis is built **during** the iterative scan-audit-crawl loop, not after it. Earlier citations' findings produce **synthesis claims** that become part of the in-progress review; later citations' treatment may depend on those claims. The flow handles this by treating synthesis claims as first-class artifacts with explicit auto-accept / block gates.

## Why interleaved synthesis

Deferring synthesis to a final phase would mean later citations' treatment is independent of earlier ones — but in practice it isn't. Whether a later paper "preempts a novelty claim" depends on what the synthesis has already claimed. Whether a later paper "anchors a methodological choice" depends on what methodological framing is already in place. Whether a later paper is *relevant* at all depends on what the synthesis has converged on as the artifact's actual argument.

Interleaving fixes this. Each Phase 2 audit produces both a per-citation entry (for the audit doc) and zero or more synthesis claims (for the in-progress review). Later audits read the synthesis claims, may declare dependencies on them, and may block if their dependencies haven't been resolved.

## Synthesis claims

A synthesis claim is a structured artifact with these fields:

- **id** — short kebab-case slug (e.g., `sycophancy-as-demand-inference`).
- **claim** — one to three sentences asserting something about the literature.
- **supporting citations** — the audit entries whose findings support this claim.
- **status** — `pending` / `auto-accepted` / `human-accepted` / `contested` / `superseded`.
- **dependents** — the audit entries whose treatment depends on this claim (back-edges, populated as later audits declare dependencies).

Claims live in a per-artifact `SYNTHESIS_<artifact>.md` file, one entry per claim, appended in the order they're produced.

## Producing claims

After completing a Phase 2 review on a work, the review agent (or human) may produce one or more synthesis claims by noting:

- A *positioning* the artifact now takes, anchored to this citation ("X et al. 2024 anchors the choice to frame sycophancy as demand-inference rather than as RLHF preference").
- A *gap* the citation does not fill ("X et al. 2024 studies Y on model class Z; transfer to our setting is conditional").
- A *contradiction* between this citation and an earlier one ("X et al. 2024's finding conflicts with Y et al. 2023's; the artifact must take a position").
- A *terminology choice* the artifact will use going forward, anchored to the citation's usage.

Not every audit produces claims; many audits just confirm a citation is faithfully used. Claim production is reserved for findings that shape **later** treatment.

## Auto-accept criteria

A claim is **auto-accepted** when *all* of:

- The supporting citation's audit verdict is `faithful`, or the proposed rewrite is purely additive (no contradiction with existing artifact text).
- The claim does not contradict any prior accepted synthesis claim.
- The claim is structurally simple — a single assertion + a single supporting citation, no novel framing of the artifact's overall argument.

Auto-accept means later dependent audits proceed without waiting. The dashboard still surfaces auto-accepted claims for after-the-fact human review (so a human can disagree and downgrade to `contested`), but they don't block the pipeline.

## Block criteria

A claim **blocks** (status: `pending`) when any of:

- The supporting citation's audit proposed a substantive rewrite that changes framing or a load-bearing claim.
- The claim contradicts a prior accepted synthesis claim — the conflict must be resolved before either branch's dependents can proceed.
- The audit agent explicitly flagged the claim as load-bearing for the artifact's overall argument and not auto-acceptable.
- The claim is the first claim in a new cluster (the first claim in a cluster always blocks for human shape-of-the-argument review).

Blocked claims surface on the dashboard with their dependent-audit count, sorted by dependent count descending — claims that gate the most downstream work are highest-priority for human attention.

## Dependency declarations

When auditing a citation, the agent declares dependencies by referencing claim ids in the audit entry:

```
**Depends on:** [[sycophancy-as-demand-inference]], [[entropy-as-mechanism]]
```

The dependency is recorded in the per-citation audit entry and as a back-edge in the synthesis claim's `dependents` list. If any declared dependency's status is `pending` or `contested`, the audit blocks.

Agents err toward declaring dependencies — over-declaration just costs a few extra dashboard checks, under-declaration produces invalid synthesis.

## Topological ordering

Audits proceed in topological order with respect to synthesis-claim dependencies. The flow scheduler:

1. Pulls the next ready audit (all declared dependencies are `auto-accepted` or `human-accepted`).
2. If none are ready, surfaces the blocking claims for human review and waits.
3. Resumes when a blocking claim resolves; downstream audits unblock atomically.

In practice most audits have no dependencies and proceed in parallel. The dependency structure is a thin graph overlay on a mostly-parallel pipeline — the block-gate triggers only at synthesis-shaping moments.

## Resolution actions

For each blocked claim the human can:

- **Accept as stated.** Status → `human-accepted`; all dependents unblock.
- **Modify.** Edit the claim text. Dependents re-validate: most still satisfied; the occasional dependent that relied on framing the modification changed needs re-audit (the system flags which).
- **Reject.** The claim is withdrawn (status: `superseded` with rationale); dependents lose the dependency. Dependent audits that relied on the claim need re-running.
- **Merge.** Two related claims become one; supporting-citation lists merge; dependents repoint to the merged claim.
- **Split.** The claim's content separates into two distinct claims; dependents declare which side they take.
- **Mark contested.** Two genuinely contradicting claims become a documented disagreement in the artifact's eventual prose; dependents declare which side they take. Status stays `contested` but the pipeline unblocks (the disagreement itself is part of the lit review's contribution).

## Convergence interaction

Phase 4's convergence signal (zero new relevant works in an iteration) is necessary but not sufficient. The flow is complete when **both**:

- The convergence signal has fired (no new relevant works to audit), *and*
- All synthesis claims have terminal status (`auto-accepted`, `human-accepted`, `contested`, or `superseded` — no `pending`).

A converged-but-blocked state means the citation funnel is empty but synthesis decisions still need human resolution. The dashboard surfaces this as "ready for synthesis-only review" — the human can finish out the pipeline without further crawls.

## Output

`SYNTHESIS_<artifact>.md` is the canonical record of synthesis decisions. Phase 5's prose synthesis assembles the lit review from the accepted synthesis claims and their supporting citations' audit entries. **No new synthesis decisions are made in Phase 5** — it's pure assembly of decisions already gated through this protocol.

## Why the gate matters

Without the auto-accept / block gate:

- A wrong synthesis decision on an early citation propagates silently into later citations' treatments — the failure mode the audit was supposed to prevent.
- Synthesis ends up implicit in the audit prose, not first-class, so later authors can't see what shape-of-the-argument decisions were already made.
- Phase 5 ends up making synthesis decisions after the fact, defeating the interleaving entirely.

With the gate, every synthesis decision is an explicit artifact with an explicit status, and the dependency edges make it impossible for a later audit to silently assume a synthesis decision that wasn't actually made.

## Companion files

- `LITERATURE_REVIEW_FLOW.md` — the overall pipeline; this protocol is active throughout Phases 1–3, not just at Phase 5.
- `WORK_REVIEW.md` — Phase 2 per-work review protocol; producing synthesis claims and declaring dependencies are documented outputs of every Tier-1 review.
- `plan-litreview-ui.md` — the HTML interfaces' design; the audit walker and dashboard surface synthesis claims, dependencies, and the block-gate.
