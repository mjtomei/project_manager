# Review Response — Cycle 1 (user-model literature review)

Date: 2026-05-14
Responding to: `REVIEW_CYCLE_1_USERMODEL.md`

The reviewer's central move is to argue the plan's "no one has done causal mediation on a social variable" novelty claim is overstated, with four lines of work cited as preemption: Park et al. 2024 (linear representation hypothesis as the formal probe-and-steer protocol), Findings of ACL 2025 (mechanistic interpretability of emotion inference), the transformer-circuits 2026 emotion-concepts piece, and Choi et al. 2025 (LatentQA-style decoders for model beliefs about users).

We accept the citations gratefully. They are gifts to the methodology, not refutations of the plan. But we push back on the novelty-narrowing framing, because the reviewer has mis-described what the plan is measuring.

## What the plan actually measures (and what those four works don't)

The plan's central claim, in plain terms: *LLMs perform better when they like and respect you.* Or more carefully: an LLM's internal representation of its *affective stance toward the conversational partner* — whether it has a positive or negative valence toward the user, whether it perceives the user as competent and worth working for — is a causal mediator of the model's task-performance quality. The intervention is framing (treating the model as a colleague rather than as a tool); the mediator is the model's social/relational state toward the user; the outcome is accuracy on standard benchmarks.

None of the four cited works measures that variable.

**Park et al. 2024**: A *methodology* paper. Formalizes the linear representation hypothesis and the probe-then-steer protocol on factual concepts (Spanish-vs-English, gendered nouns, country attributes). It is a boon — it gives us the formal recipe and the experimental discipline — but it does not run the experiment on affective stance toward an interlocutor. **Use**: cite as the methodological backbone in §7. **Effect on novelty**: none.

**Findings ACL 2025 — Mechanistic Interpretability of Emotion Inference**: Studies discrete emotion concepts (anger, fear, joy, sadness) attributed to characters in narratives, and shows those representations causally influence subsequent assistant behavior. Important and structurally adjacent — but emotion concepts attributed to characters in stories are not the same variable as the model's relational stance toward its actual conversational partner. The emotion-of-a-character is a property *of a story being narrated*; the affective stance the plan probes is a property *of the model's current interaction*. **Use**: cite as the closest published example of "social variable as causal mediator," then explicitly contrast with the plan's variable. **Effect on novelty**: shrinks the novelty claim from "any social mediator" to "the specific affective-stance mediator," which is still substantive.

**Anthropic transformer-circuits 2026 — Emotion Concepts**: Functional emotions *of the model itself* as a system. Same caveat as ACL 2025: the model's own emotion-like states are not its disposition toward the addressee. **Use**: cite alongside ACL 2025 as evidence that the methodology works for *some* affective variables, increasing confidence the plan's variable can be similarly probed. **Effect on novelty**: same as ACL 2025.

**Choi et al. 2025 — LatentQA**: Decodes *factual beliefs* about the user (demographics, expertise level, apparent goals). This is the closest peer. But factual beliefs are different from relational valences: "the model believes the user is a beginner" is not the same as "the model has a positive disposition toward the user." A model can correctly identify a user as a beginner and still respect them (or not). The relational state is the variable the plan claims is novel. **Use**: cite as the closest published peer; note that beliefs-about-user is an adjacent but distinct axis. **Effect on novelty**: tightens the plan's claim to specifically *relational/affective stance*, separate from factual user-belief decoding.

## The reviewer's proposed narrower novelty claim undershoots

The reviewer suggests narrowing to "causal mediation specifically targeting a probed user-trait belief (not the model's own state, not the affective state of a character in a story) as the mediator of a productivity / accuracy effect."

That undershoots. "User-trait belief" suggests factual attribution (expertise level, role, demographic), which is exactly what LatentQA covers. The plan's variable is *relational valence* — does the model like and respect the user, not just classify them. Trust, liking, respect are not factual attributions; they are dispositions. A model can know a user is an expert without respecting them, and vice versa.

**Corrected novelty framing**: causal mediation of the model's *relational/affective stance toward the conversational partner* as a determinant of task-performance quality on standard benchmarks. This is a real and previously-unmeasured variable. The methodology (Park's probe-then-steer recipe, the emotion-mediation experimental shape from ACL 2025 and transformer-circuits 2026) carries over directly; the variable does not.

## Other findings (accepted, mostly)

The reviewer's remaining substantive findings are accepted as edits:

- **Andreas 2022 extrapolation**: agree. Andreas covers "LMs model agents whose text they predict" (the author). The plan is about the addressee. The review should flag the extrapolation explicitly rather than treating Andreas as direct support.
- **Belrose conflation**: agree. Belrose's actual contribution is the tuned lens, not the probe-vs-causal distinction. Demote Belrose to its actual role; cite Vig 2020 and Geiger 2021/2022 as the actual sources for causal mediation in transformers.
- **Probe-vs-causal language sloppiness**: agree. Add explicit "what counts as a causal claim here" early in §4 / §7. Don't lump RepE, CAA, ActAdd, ITI together as if all are causally validated — note which are merely steering-validated and which have run formal interchange-intervention tests.
- **Karpathy citation is decorative**: agree. Either pin the exact prompt with a timestamp and link from a specific talk/thread, or drop the baseline. Add a one-line identification of who Karpathy is on first mention.
- **Scaling Monosemanticity feature labels imprecise**: agree. Replace "the user is upset / talking to a child" with the actually-documented features (Templeton et al. 2024): "sycophantic praise," "inner conflict," features for deception, bias features. The illustrative example was the most evocative sentence for the plan's hypothesis and it appears to be misremembered — that is a high-cost imprecision.
- **AGENTS.md attribution**: agree. Sourcegraph is not on the adopter list; correct to Amp/Jules/Codex/Cursor/Factory.
- **OpenAI April 2025 sycophancy rollback**: verified correct, no edit needed (the reviewer flagged this for verification and found it accurate).
- **Block 3 — ~15 undefined interpretability terms with glosses**: accept all proposed glosses. Sparse autoencoder, residual stream, probe, contrast pairs, control vector, steering vector, activation patching, causal mediation analysis, interchange intervention, refusal direction — all need first-use glosses in target-reader vocabulary.

## Edits checklist

1. Rewrite the §7 / Conclusion novelty section to the *affective stance toward user* framing, not "any social variable."
2. Cite Park et al. 2024 (arXiv:2311.03658, ICML 2024) as methodological backbone.
3. Cite Findings ACL 2025 emotion-inference (arXiv:2502.05489) as related-but-different-variable exemplar.
4. Cite transformer-circuits 2026 emotion-concepts as parallel example.
5. Cite Choi et al. 2025 LatentQA (verify title and arXiv ID) as closest peer on the adjacent factual-user-belief axis.
6. Flag the Andreas 2022 extrapolation explicitly.
7. Demote Belrose to tuned-lens, cite Vig 2020 and Geiger 2021/2022 for causal mediation.
8. Tighten probe-vs-causal language throughout §4.
9. Either pin Karpathy's exact prompt or drop the baseline; identify who Karpathy is on first mention.
10. Replace Scaling Monosemanticity feature labels with verifiable ones from Templeton et al. 2024.
11. Fix AGENTS.md adopter list.
12. Apply all Block 3 glosses for the ~15 interpretability terms.

## Notes for the plan owner

The lit review's edits surface one update the *plan* (`pm/plans/plan-66d430f.md`) should incorporate:

- **The plan's hypothesis statement should be the affective-stance version, not "user-model" generally.** "LLMs maintain an implicit model of who they're talking to" is the broad scientific question; the actual experimental claim is narrower and more interesting: "LLMs perform better when they like and respect the user, and we can measure that mediator." The plan would benefit from elevating the affective-stance framing to its Hypothesis section, alongside the looser "user-model" framing as the methodology's substrate.

## Notes for Cycle 2

After applying these edits, Cycle 2 should expect:
- The novelty claim is now specific to *affective stance*. Cycle 2 should pressure-test whether affective stance and factual user-belief are genuinely separable, or whether the experimental setup can't actually distinguish them.
- The methodology section now leans hard on Park et al. 2024. Cycle 2 should check whether the plan's specific contrast-pair design actually implements Park's protocol or just borrows its name.
- The ACL 2025 / transformer-circuits 2026 citations now do real work as exemplars. Cycle 2 should verify our characterization is accurate.
