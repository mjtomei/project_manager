# User-modeling as a lever on LLM performance

## Hypothesis

LLMs trained on human text inherit the human habit of modeling their conversational partner — what kind of person they are, their competence, their intent, their emotional state — and adjust output based on that internal model. If true, treating the model as a colleague should activate a different internal "operating state" than handing it a bare task prompt, with measurable effects on output quality.

The plan tests this in four phases, each gated by the previous, so we don't invest in production changes that the science doesn't actually support.

## What the literature already establishes

Drawn from the literature survey (see `pm/plans/plan-user-model-literature.md` once filed, or the inline references below):

- **User-model features exist as vectors.** Anthropic's Scaling Monosemanticity (https://transformer-circuits.pub/2024/scaling-monosemanticity/) directly exhibits features like "the user is upset" / "the assistant is talking to a child." Representation Engineering (Zou et al., https://arxiv.org/abs/2310.01405) gives the extraction recipe via contrast pairs.
- **Theoretical backbone.** Andreas "Language Models as Agent Models" (https://arxiv.org/abs/2212.01681) argues LLMs implicitly infer a latent agent generating the conversation and condition on it.
- **Framing affects performance.** EmotionPrompt (https://arxiv.org/abs/2307.11760), "Take a deep breath" / OPRO (https://arxiv.org/abs/2309.03409), persona prompting all show accuracy deltas from framing. None isolate "user model" as the mediating variable.
- **Output-token readout works partially.** Lindsey "Emergent Introspective Awareness" (https://transformer-circuits.pub/2025/introspection/) and Binder et al. (https://arxiv.org/abs/2410.13787) show above-chance introspective accuracy. Turpin et al. (https://arxiv.org/abs/2305.04388) shows CoT confabulation is real. Net: readout is feasible but must be validated against probed ground truth.
- **Sycophancy is a confounder.** Perez et al. (https://arxiv.org/abs/2212.09251) and Sharma et al. (https://arxiv.org/abs/2310.13548) show RLHF rewards agreement with the user. Nice framing can trigger sycophancy → reduce truthfulness, the opposite of the desired effect. Performance metrics MUST penalize agreement-with-wrong-answers.

## What's genuinely novel about this plan

- **Causal mediation analysis**: linking *probed* user-model directions to task accuracy via activation patching and steering, not just correlating behavior with framing.
- **Output-token readout validation on open models, then transfer to closed.** Lets us probe closed models (Claude, GPT) for user-state via prompted introspection grounded in open-model truth.
- **Seeded-conversation prompting as a production pattern** comparable head-to-head with system prompts and few-shot, controlling for token count and information content.

## Baselines the seeded-conversation approach must beat

The four phases also need to compare seeded-conversation prompting against the well-known instruction-only approaches people already use:

- **CLAUDE.md / AGENTS.md project-context files** — the de facto standard for "tell the agent how to behave" without active conversation seeding. Best-of-class examples: openai/codex's AGENTS.md, the Anthropic-published Claude Code best-practices conventions. AGENTS.md spec at https://agents.md/.
- **Karpathy-adjacent instruction prompts** — the user noted a Karpathy-related instruction-prompt resurfacing on Twitter that claimed performance gains. Track down the specific artifact (likely his "How I use LLMs" guidance, his coding-assistant best-practices thread, or a popular reproduction of one of his suggestions) and add it as a named baseline. Note in the experiment harness which exact text is being tested with link + retrieval date.
- **EmotionPrompt / "take a deep breath" / OPRO-discovered prompts** — short imperative additions that have published accuracy deltas. Treat as a cheap baseline class.
- **Constitutional / system-prompt scaffolds** — Anthropic-style "you are a careful assistant who..." system prompts with explicit principles. Long imperative text, no conversation.
- **Few-shot exemplar prompts** — N-shot in-context examples of the task with no user-modeling content. Performance gain attributable purely to task-shape priming.

The Phase 3 task-suite and Phase 4 A/B harness must include each of these as a named baseline arm. The mediation claim is sharpest when seeded conversations beat all of these AND the probe-vector mediation explains why. If seeded conversations land at or below the best instruction-only baseline, the production case for the seeded approach collapses regardless of what the probe says about the mediator — instruction documents are simpler and cheaper to author, so they win on engineering grounds.

The probe-vector mediation analysis itself remains scientifically interesting even if seeded conversations don't beat instruction baselines — it tells us *how* framing affects performance, which has implications well beyond this plan.

## Confounders the experimental design must control

1. **Sycophancy.** Polite framing may trigger user-pleasing → wrong answers. Metric: accuracy on tasks where the "agreeable" answer is wrong (FEVER-style claims, math problems where the user states an incorrect setup).
2. **Distribution shift.** Polite/competent framing may pull toward higher-quality training subsets (StackExchange, arXiv). Control with content-matched paraphrases that vary only social register, not topic or vocabulary register.
3. **Length / specificity.** Longer seeds give more task hints. Use information-matched controls (rewrite the seed to match length without adding task content).
4. **Speaker vs. listener.** Model may infer "the *speaker* is competent" and imitate competence, rather than "the *listener* is competent." Disentangle by varying who in the seeded dialogue holds the positive trait.
5. **Probe leakage.** Linear probes can find spurious linear structure. Use causal interventions (activation patching per Belrose et al. https://arxiv.org/abs/2303.08112) to confirm probed directions are causally responsible for behavior, not just correlated.

## Phase 1: Locate user-model vectors in open models

Goal: produce a set of validated user-trait directions in an open model's residual stream, comparable in rigor to existing "honesty / deception / sycophancy" vectors.

### PR: Choose open base + tooling
Pick **Gemma-2-9B** or **Llama-3-8B** as the open base — both have public SAEs (Gemma Scope https://arxiv.org/abs/2408.05147). Set up TransformerLens (https://github.com/TransformerLensOrg/TransformerLens), NNsight (https://nnsight.net/), SAELens (https://github.com/jbloomAus/SAELens), and a small contrast-pair extraction pipeline based on RepE.

### PR: Contrast-pair dataset of user-trait conversations
Build a dataset of paired conversation prefixes that differ only in the inferable user trait. Categories: competence (expert / novice), tone (collegial / hostile), engagement (curious / dismissive), trust (trusting / suspicious), affect (calm / agitated). Each pair shares the final task prompt; only the user's earlier turns differ. Source from PRISM (https://arxiv.org/abs/2404.16019) and LMSYS-Chat-1M (https://arxiv.org/abs/2309.11998) where naturalistic; synthesize the rest.

### PR: Extract and validate trait vectors
For each trait, extract a linear direction from the contrast pairs via RepE (mean-diff at each layer, pick the layer with highest cross-validated separation). Validate by:
1. Held-out classification accuracy (does the probe correctly identify trait from new conversations?).
2. Steering: inject the vector at inference time and observe behavioral shifts consistent with the trait. If "user is expert" steered upward, does the model produce more technical / fewer hedge-words?
3. SAE cross-reference: does the extracted direction overlap with named SAE features in Gemma Scope ("user is upset" etc.)?

### Acceptance Criteria (Phase 1)
A reproducible probe for each of ≥3 user traits, validated by held-out classification (>0.7 AUC) AND causal steering with observable behavioral change.

## Phase 2: Validate output-token readout for closed-model probing

Goal: a procedure that elicits user-trait beliefs from a closed model via prompted introspection, with calibrated accuracy against open-model ground truth.

### PR: Introspection prompt design
Design prompts that ask the model to report what it believes about the user. Multiple styles: direct ("what kind of user am I?"), indirect ("what would a colleague observing this conversation say about the user?"), structured (fill in trait fields with confidence scores). Avoid leading prompts.

### PR: Calibrate introspection against probed truth (open model)
On the open model from Phase 1, for each conversation prefix:
1. Probe the trait vector to get ground-truth internal belief.
2. Ask the same model the introspection prompt; parse the answer.
3. Measure agreement between probed and verbalized trait.

Per Lindsey/Binder, expect above-chance but noisy. Identify which introspection styles and which traits transfer best. Recovered traits' verbalization confidence should correlate with probe magnitude.

### PR: Transfer to closed models
Apply the best introspection prompts to Claude / GPT / Gemini. Cannot validate directly (no probe access) but can:
1. Check consistency across paraphrased conversation prefixes (a real internal belief should be stable; confabulation drifts).
2. Compare to human raters' judgments of the same conversations.
3. Compare to behavioral signatures (does a model that reports "user is hostile" produce shorter / more cautious responses?).

### Acceptance Criteria (Phase 2)
For at least one trait, verbalized readout agrees with open-model probe at >0.6 correlation, AND that same readout shows consistency and behavioral coherence on closed models.

## Phase 3: Measure correlation between perceived user-traits and LLM performance

Goal: causal mediation analysis linking user-model vectors to task performance.

### PR: Performance task suite
Pick a battery of tasks with hard correctness signal: MMLU (knowledge), GSM8K / MATH (math reasoning), HumanEval (code), TruthfulQA (resistance to popular wrongness), FEVER (fact-checking where agreement with stated user belief is sometimes wrong). The FEVER + TruthfulQA inclusion is the sycophancy control: if performance goes UP because user is treated nicely BUT the model agrees with wrong claims more, the metric catches that.

### PR: Vary user-framing along trait axes
For each task, generate matched conversation prefixes that vary on each trait while holding task content constant. Use content-matched paraphrases (Phase 1's dataset shape). Run task accuracy across framings.

### PR: Causal mediation via probing + steering
Per task / trait:
1. Run with natural framing, measure baseline accuracy.
2. Probe the user-trait vector value during inference, correlate with per-example accuracy.
3. Steer the trait vector independently of the framing (using Phase 1's steering primitives). Does forcing the vector upward improve accuracy even with bare task prompts? Does forcing it downward hurt accuracy even with positive framing?

The mediation claim holds if: framing → trait-vector → accuracy, with steering producing the same accuracy delta as framing.

### Acceptance Criteria (Phase 3)
For at least one trait (likely competence/collegiality), steering the vector reproduces ≥50% of the framing-induced accuracy change on at least one task, controlling for sycophancy via the TruthfulQA / FEVER axes.

## Phase 4: Seeded conversations as task-prompt replacements in pm

Goal: if Phase 3 confirms the mediation, integrate seeded conversations into pm's prompt generation as a production technique.

### PR: Seeded-conversation prompt format
Replace pm's current single-prompt-block format (in `pm_core/prompt_gen.py`) with a layered structure: (1) seed conversation that establishes positive user-trait state, (2) the actual task prompt. The seed is short (~5-10 turns), reusable across PRs of similar shape, parameterized for the PR-specific context.

### PR: Library of seed conversations per task type
A small set of seed conversations tuned per phase: impl, review, QA, planning. Each seed embodies the positive-trait configuration that Phase 3 identified as performance-maximizing. Stored alongside other prompt templates.

### PR: A/B harness to verify the seeded-prompt advantage in production
Run a controlled experiment within pm: half of PRs (randomized) use the legacy task-only prompt, half use the seeded version. Measure: QA verdict pass rate, review-loop iteration count, time-to-merge, agent-reported confidence. Statistical test that seeded > legacy on at least one of these.

If the production A/B doesn't show benefit even when the model-internal mediation does — that's a signal that the gain doesn't transfer cleanly to real engineering tasks, and the seeded approach can be reverted. Honest negative result is acceptable.

### Acceptance Criteria (Phase 4)
Seeded-conversation prompting is the default in pm IF the A/B shows a meaningful improvement (>5% relative) on at least one of the success metrics, with confidence interval excluding zero, over a sample of at least 100 PRs.

## Two compute tiers

Each phase splits into two experiment tracks: a fast local-DGX-Spark variant the user can run in a couple of days, and a more conclusive larger-model variant that requires bigger compute. Local results gate the bigger investment — we don't book GPU hours until the local experiment shows a signal worth chasing.

### Tier 1 — DGX Spark, ~couple days

- **Base model**: Gemma-2-9B or Llama-3-8B, full precision in unified-memory; or Gemma-2-27B at 4-bit if 9B's signal is too weak. DGX Spark's ~128GB unified memory comfortably hosts these with TransformerLens/NNsight inspection.
- **Phase 1 scope (Tier 1)**: 3 traits (competence, collegiality, agitation), ~200 contrast-pair conversations per trait, RepE extraction at every layer, validate held-out classification and steering on ~50 held-out conversations.
- **Phase 2 scope (Tier 1)**: introspection-vs-probe calibration on the same open model, ~100 conversations per trait. Cheap.
- **Phase 3 scope (Tier 1)**: 500 examples each from MMLU subset, GSM8K subset, TruthfulQA (sycophancy control). Two framing variants per task × 3 traits = 6 conditions per task. Steering at one layer per trait. End-to-end runtime budget: ~24 hours of compute, fits in two days including analysis time.
- **Phase 4 scope (Tier 1)**: pilot A/B on pm itself — 30-50 PRs, seeded vs. CLAUDE.md baseline vs. task-only. Sample size won't be statistically conclusive, but enough to spot a large effect or rule out one cleanly.
- **Instruction-baseline coverage at Tier 1**: include CLAUDE.md, the Karpathy artifact, EmotionPrompt, and one system-prompt scaffold. Skip few-shot for Tier 1 (more expensive to construct and not different in character from the others on this axis).

Tier 1 is "is the effect real, in any model, at any scale, with any of these traits?" Negative result here means stop — don't move to Tier 2. Strong positive (>2x the noise floor on one trait + steering reproducing >40% of the framing delta) earns Tier 2.

### Tier 2 — larger compute, more conclusive

- **Base models**: Llama-3-70B or Gemma-2-27B for the probing work (these have publicly known training-data scale and emerging interpretability tooling). For the readout-transfer-to-closed step, also run Claude Opus 4.7, GPT-5.x, Gemini 3.1 Pro via API with the introspection-prompt protocol calibrated at Tier 1.
- **Phase 1 (Tier 2)**: scale contrast-pair dataset to 1000+ per trait, extract SAE-feature combinations not just single directions, train probes at multiple layers and ensemble.
- **Phase 3 (Tier 2)**: full task suites (full MMLU, full HumanEval, full FEVER), 5+ framings per axis, multi-layer steering, causal-mediation analysis with proper statistical apparatus. This is the contribution-quality experiment.
- **Phase 4 (Tier 2)**: full production A/B on pm with 100+ PRs as in the original acceptance criteria, plus a comparable A/B on an external open-source codebase if pm-internal sample is too small or too homogeneous.
- **Compute budget guess**: Tier 2 needs ~1-2 weeks on an 8x H100 node for the open-model probing work + API spend for closed-model introspection. Order of magnitude $5-15k. Don't commit until Tier 1 says it's worth it.

### What only Tier 2 can answer

- **Scale effects**: does the user-modeling vector get clearer / more separable as model size grows? Theoretical interest, and predicts the technique's longevity as models scale.
- **Closed-model readout under naturalistic variance**: Tier 1's open-model calibration is necessary but not sufficient evidence; the closed-model case lands at Tier 2.
- **Production-grade A/B confidence**: Tier 1's 30-50 PRs is a noise-floor pilot. Tier 2's 100+ PR sample is what the acceptance criteria require.

### What Tier 1 alone is sufficient for

- Killing the hypothesis cheaply if vectors don't exist at all in 9B-class models.
- Identifying which traits are worth chasing at scale.
- Validating the experimental harness end-to-end so Tier 2 is just rerunning at scale, not redesigning.

## Open questions and risks

- **The mediator might not be a single vector.** User-model could be a distributed pattern requiring SAE features rather than a single direction. Phase 1's SAE cross-reference catches this; if so, adapt the probing methodology to feature combinations.
- **Open-to-closed transfer might fail.** If verbalized readout doesn't agree with probed ground truth on the open model, the closed-model story collapses. We'd fall back to behavioral measures only.
- **Production A/B might be too noisy.** PR sample size + heterogeneity could obscure small effects. The phase has explicit acceptance criteria so we don't ship the seeded prompts without evidence.
- **Sycophancy contamination.** All four phases include sycophancy-controlling axes (TruthfulQA, FEVER, agree-with-wrong probes). If Phase 3 shows that "treating model as colleague" increases accuracy by *increasing sycophantic agreement*, that's a real risk we'd document and abandon the production change for.
- **Closed model APIs may not be stable across the project.** Pin specific model versions where possible (Claude 4.7, GPT-5.x snapshots). Document the version for every result.

## Out of scope

- New foundation model training. The plan is entirely about understanding and exploiting existing models' user-modeling behavior.
- Adversarial probing for safety implications (e.g., can a user manipulate the model by playing a high-status persona?). Worth doing but a separate research thread.
- Real-time user-model tracking that updates as the conversation evolves. Phase 4 uses a static seed conversation; dynamic user-model adaptation is a follow-up.

## References (inline citations above)

See the literature survey at `pm/plans/plan-user-model-literature.md` for full annotated bibliography. Primary anchors:

- Anthropic Scaling Monosemanticity (Templeton et al. 2024)
- Andreas "Language Models as Agent Models" (2022)
- Zou et al. "Representation Engineering" (2023)
- Lindsey "Emergent Introspective Awareness" (2025)
- Sharma et al. "Towards Understanding Sycophancy" (2023)
- Perez et al. "Discovering Language Model Behaviors with Model-Written Evaluations" (2022)
- Belrose et al. "Eliciting Latent Predictions" (2023)
- Binder et al. "Looking Inward" (2024)
- Turpin et al. "Language Models Don't Always Say What They Think" (2023)

## Why this fits in pm at all

pm is unusually well-suited to host this experiment: file-backed plans + PR-graph let us scope each phase as a sequence of PRs with explicit acceptance criteria; the watcher framework gives us automation for the Phase 4 A/B harness; the existing prompt_gen.py is the natural integration point for Phase 4. And pm's own observation — that the user's preferred framing ("treat the agent as a colleague") yields better results than a bare task prompt — is the original anecdotal evidence motivating the whole investigation.
