# Principle Coverage Audit — learn-don't-hardcode

(internal design audit, 2026-06-08. Two passes: an adversarial multi-agent workflow over the 6 core minds/cognitive-ops docs — 13/38 candidate findings survived a 3-vote steelman — plus a single-pass read-only sweep over the remaining plans. Findings are classified with the **seed-vs-runtime refinement**. This is engineering hygiene, not literature; it does **not** belong in `literature-review-minimal-sufficient-inference.md` — that review carries only the one-line principle. Confirmed gaps graduate into the relevant plans.)

## Classification (three-way)

- **(A) runtime bake-in of learnable functionality → violation.** A learnable policy/formula/weight/threshold pinned to a constant *in the artifact that is supposed to be trainable*. Fix: learn it, or extend the abstraction.
- **(B) seed generator → fine; judge by variety.** A hand-coded generator that produces *training seeds* (coarse prompt scaffolds, the perplexity-decomposition bootstrap, an operator taxonomy used to generate diverse traces). Not a violation. The only question is **does it maximize variety/coverage?** A narrow seeder biases the learned thing.
- **(C) typed contract / invariant / safety rail → correctly fixed.** Contracts, idempotency keys, ACLs, runaway-loop caps, the held-`y`-fixed firewall. Leave alone.

## Verdict

**The abstraction is expressive enough to reproduce the benchmark battery; the work is wiring, not redesign.** Nearly every confirmed finding is a **(A)** hard-code — a learnable knob frozen to a constant — not a coverage gap. Crucially the de-hardcoding mechanism **already exists in the corpus** (`RecallUsed → relevance-weight` loop; `BudgetPolicy → PoolBudgetGovernor` bandit); it simply isn't wired into every place that froze a knob. Genuine coverage gaps are two and both additive: two missing read-surfaces on the `Artifact` primitive, and the deferred `speculate` op. Zero battery items are unreachable in principle.

The single sharpest pattern is **`plan-radar`**: it collects a dense usefulness signal (in-thread replies, sustained discussion, persistent links — its own stated KPI) and spends it *only* on hand-coded ranking/override rules, never feeding it back to fit the weights, the decay, or the surfacing threshold — while `plan-memory` closes exactly that loop on the *identical* composite. Five of the corpus's violations are here and share one fix.

## Coverage table — can the abstraction ARRIVE AT each battery item today?

| Battery item | Verdict | Why |
|---|---|---|
| **ACT-R activation** (recency+freq + spreading; threshold-gated unrequested retrieval) | **via-composition, 1 gap** | Salience = plan-memory composite + cue-driven injection + dynamic threshold; gap: ACT-R's *frequency-of-retrieval* term needs a per-Artifact access trace (missing), and the weights must actually be learned (not asserted). |
| **CLS** (episodic↔semantic; consolidation/replay; reasoned→rote) | **via-composition, narrow gap** | Episodic replay = `EmissionLog.query/slice` + `StreamTranscript.ref_at`; reasoned→rote = MSI's compile path + "used traces strengthen"; gap: replay over *org-data content* blocked by current-only `Artifact` read surface. |
| **SOAR impasse→subgoal + chunking** | **via-composition** | Impasse→subgoal = a stream spawning a child via `BranchRequest` (`branch.denied`/`deferred` = budget-gated resolution); chunking = MSI reasoned→rote. No first-class impasse-detector/chunk-store, but composable. |
| **GWT broadcast/ignition** (all-or-none threshold) | **via-composition** | Broadcast = `Mailbox` fan-out; ignition = a salience-gated post using plan-memory's dynamic threshold. No dedicated primitive; composable. |
| **Metacognitive monitor→control + confidence/FOK gating** | **reachable, currently HARD-CODED (A)** | Structure exists, but the gates are pinned constants (`consecutive_pass_threshold=2`, `max_consecutive_attention_requests=3`) and MSI's emission gate is a fixed PPL rule. |
| **Predictive-processing precision-weighting** | **reachable, currently HARD-CODED (A)** | Precision = the composite's per-factor weights + the bandit's allocation; mechanism present but weight-learning asserted-not-specced; radar's are hand-set. |
| **The 8 reasoning ops** (branch/emit/compose/join/recall/backtrack/speculate/cut) | **mostly yes; 1 gap** | branch/emit/compose/join = `BranchRequest`/`await_join`; recall = `RecallEmission`; backtrack = the branch/backtrack budget; cut/resolve = control tokens; gap: **`speculate` is not specced** (deferred — needs provisional-emission state + rollback). |

**Net:** zero battery items unreachable; two narrow additive gaps (`Artifact` read surfaces; `speculate`); two reachable-but-hard-coded gates (monitor→control; precision-weighting); the rest compose cleanly.

## Findings by document — core docs (adversarially verified)

- **`plan-radar` — (A) HIGH, the concentration.** Engagement signal collected, never fed back to learn (radar:52/84/214; KPI at 305). Five findings, one fix: relevance weights hand-set (58/63/140), temporal decay a hand-tuned slider (82-84), visibility threshold static (54/238), metric *dimension set* frozen (66-78). **Fix:** add a `RadarUsefulness` signal and feed it to *fit* weights/decay/threshold (reuse plan-memory's loop — dependency already declared at memory:142). Keep the 1-10 per-metric decomposition + the `metrics.yaml` human edit as **(C)** interpretable prior/override; learn only the aggregation. The metric-dimension freeze is a small **extend-the-abstraction** (admit feedback-discovered dimensions, Phase-2 note).
- **`plan-memory` — (A) HIGH.** "RecallUsed trains the relevance weights" is asserted (principle 6 "the spine", 92, PR4 127-128) but no learning mechanism is specced — the composite is "reused wholesale from radar" whose weights are hand-edited; the only real update path is the *budget* bandit. **Fix:** give the composite a learnable weight vector bound to the graded `ignored/referenced/acted-on` label (cold-start = radar seed), distinct from `PoolBudgetGovernor` — or downgrade PR4's prose to match what's built. *(Plus (A/B) LOW: "seed budget ∝ pool" + tier ordering is a cold-start prior — fine as a **(B)** seed that the bandit washes out; just don't present it as permanent, and expose the exploration rate.)*
- **`plan-sensorium` — (coverage gap) MED + LOW.** (1) No per-Artifact **access trace** — `Artifact` records writes only, so a learned salience metric can see change-frequency but not *read*-frequency (exactly ACT-R's base-level term). **Fix:** additive sampled `artifact.<name>.read` Emission + `access_history()` symmetric to `history()`; preserves side-effect-as-truth + redaction. (2) No **content-at-version** read for uncommitted artifacts — blocks CLS replay over org-data; low (session-pool replay is fully representable). **(C)** accept-as-fixed is defensible if documented.
- **`literature-review-minimal-sufficient-inference` (MSI) — (A) MED ×2.** (1) The minimal-context sufficiency gate is a fixed `PPL ≤ base·(1+eps)` formula carried through the whole program — the ACT-R "what's worth retaining" slot, frozen. (2) The **emission admissibility predicate** ("a low-PPL emission *is* certified-safe") is promoted to a standing substrate invariant (also plan-mind:296). **Fix:** separate the fixed fidelity **contract** (distortion ≤ ε — **(C)**, the real safety rail) from the **predicate**; demote perplexity to a bootstrap proxy; add a learned, contract-supervised admissibility judge (C11's speculate accept/reject is a ready ground-truth label). C9 held-`y`-fixed stays **(C)**.
- **`plan-mind` — (A) LOW + (gap) LOW.** Two metacognitive thresholds in `StreamPolicy` (`consecutive_pass_threshold=2`; `max_consecutive_attention_requests=3`) are the monitor→control gates, frozen. **Fix:** sibling outcome-driven governors mirroring `PoolBudgetGovernor`. *`speculate` deferred* (304) is the lone reasoning-op gap — acceptable to defer, but name it a known hole. *Correctly dropped over-reaches **(C)**: `max_iterations=None` (runaway rail), `max_buffered=100` (overflow guard), the ~250ms poll cadence (I/O timing), idle-evict N (open TODO).*
- **`user-model-extension` §4.1 — reclassified by the seed/runtime refinement.** The 8-operator generator×resolver taxonomy: **as a seed generator it is (B) — fine; the right criterion is maximize variety**, and a *typed* taxonomy is good seeding (forces divergence i.i.d. sampling can't). The residual **(A)** is narrower than the raw audit claimed: ensure the *compiled runtime* is **not closed** to the seed set — the learned selector currently only gates *which of 8 fixed moves fire*, never discovers new ones. **Fix:** point the existing exogenous gate at *discovery* (prototype-by-prompting candidate moves beyond the seed, admit iff they beat matched compute); keep the 8 + citations as a documented variety-seed/prior.

## Findings by document — other docs (single-pass, not adversarially verified)

- **`plan-002`** — test-pass-rate as selection signal + fixed 3-level hierarchy. **Needs the seed/runtime check:** if test-pass-rate filters *training examples*, it's **(B)** fine; if it's the *deployed* selection oracle the system can't improve past, it's **(A)**. Likewise the hierarchy: candidate model to test, not a blueprint.
- **`plan-quality`** — 8 fixed structural-smell audit categories. Same check: a **(B)** seed taxonomy for *what to learn to detect* is fine; a frozen *deployed* detector is **(A)**. The plan half-admits this ("seeds candidates from outside the repo").
- **`plan-regression`** — fixed test list; opportunity to **learn** which surfaces are regression-prone and steer coverage. **(A)** low-med (atop a legitimately hand-authored test set).
- **`plan-66d430f`, `plan-simulation`** — flagged HIGH by the sweep, but these are **a different concern**: experimental-design / hypothesis-framed-as-settled (epistemic humility), *not* hard-coding learnable runtime functionality. Fix = label as hypotheses (plan-66d430f already self-corrects toward "the geometry that emerged"). Not this principle.
- **Clean (correctly steelmanned):** `plan-collaboration` (typed protocols/invariants — **(C)**), `plan-984dfeb` living-artifacts (explicitly anti-blueprint), `plan-self-improve` (defers to learned design), `plan-cb4ef69`, the philosophy doc, and the user-model / living-artifacts litreviews.

## Ranked top fixes

1. **`plan-radar`: close the usefulness loop it already has the signal for** (A, high). Add `RadarUsefulness`; fit weights/decay/threshold from it; reuse plan-memory's mechanism. Dissolves 4 of radar's 5 findings at once. *(radar:52/58/84/214)*
2. **`plan-memory`: make "RecallUsed trains the weights" real, or stop claiming it** (A, high). Learnable weight vector on the composite, bound to the graded label; distinct from the budget bandit. *(memory:43/75/92/127)*
3. **`plan-sensorium`: add a per-Artifact access trace** (gap, med). `artifact.<name>.read` Emission + `access_history()`. Unblocks ACT-R frequency-of-retrieval. *(sensorium:71-90)*
4. **MSI + plan-mind: split the emission contract from the predicate** (A, med). Fixed distortion-≤-ε contract; learned, contract-supervised admissibility judge; perplexity demoted to a proxy. *(MSI:58/153; plan-mind:296)*
5. **`plan-mind`: outcome-driven governors for the two metacog thresholds** (A, low). Mirror `PoolBudgetGovernor`. *(plan-mind:1288/1336)*
6. **§4.1: keep the 8 as a variety-seed; add open-set discovery so the runtime isn't closed to them** (B + residual A, med). Point the gate at discovery, not only selection. *(user-model-ext:239-256)*
7. **`plan-002` / `plan-quality` / `plan-regression`: apply the seed/runtime check** (A?, med-low). Decide per case whether the heuristic is seeding training data (fine) or a frozen deployed policy (learn it).
8. **`plan-mind`: spec `speculate` or document the deferral as a known coverage hole** (gap, low). Provisional-emission state + rollback. *(plan-mind:304)*

## Where the fixes land

Each confirmed item is a one-paragraph reframing or a small additive PR in its own plan — none requires an abstraction redesign. The review keeps only the principle; this doc is the audit; the plans get the fixes.

---

## Addendum: what "useful" means, and where small models go

This addendum supersedes the *signal* assumed by fixes #1 and #2 above (which spoke of "feeding the engagement signal back"). The **shape** of those fixes — a learned loop — stands; the **signal** and **where the learned weights live** change.

### 1. Usefulness is a grounded outcome, never attention

Proxying "useful" as "attention was paid to it" (`RecallUsed` = referenced/acted-on; radar's reply/discussion/persistent-link KPI) rewards shallow/flashy over subtle-but-profound — **the exact pathology `plan-radar` exists to fix**, and **sycophancy at the metric level** (serving *performed* demand over *real*; cf. user-model-extension §2.3). So the signal must anchor on a **grounded outcome**; the right metric is an open study. Candidate factors, all outcome-anchored: counterfactual value (trace WITH the injection vs WITHOUT) · attention *gated by* a verified-good outcome (not attention alone) · information-gain toward correctness · adversarial-survival (does the enabled conclusion survive refutation) · diversity/coverage contribution (rewards the subtle/novel) · **signed regret** (usefulness must be allowed to go negative — a distracting injection — which attention structurally cannot represent). These are the **judge's multi-factor rubric (the label)**, not the model's input features.

### 2. Mechanism: judge → reward model → existing RL

- **Bootstrap (Phase 1):** a prompt-aware adversarial **with/without judge** produces counterfactual usefulness labels on *short* traces. Judge-grounding is handled by making the judge aware of the shallow-vs-profound failure mode in its prompt. It does **not** scale to long, multi-recall horizons — N recalls = 2^N ablation combinations; keep it short-horizon, bootstrap-only.
- **Scale (Phase 2):** fold the memory/branch emissions into the trajectory optimized by the **same existing LLM RL flows** (RLVR / verifiable rewards / preference models) over the whole stream collection. Long-horizon credit assignment, no ablation; **signed-regret is automatic** (a hurtful emission gets negative credit). The global reward is **not a new problem** — it is the existing reasoning-model reward; memory emissions just become additional optimized actions. The non-addressable subconscious tier survives — the unconscious is RL-optimized to help the conscious stream's outcome without being addressed by it.
- **Bridge:** the judge's multi-factor labels train a **reward model / PRM** — which is exactly what the existing RL flow consumes. The judge bootstraps the reward model, not the relevance scorer directly.

### 3. Where the learned "weights" live: rung 2 (an external small model)

The "weights" in fixes #1/#2 are the **composite-combiner weights — external to the LLM, not the LLM's weights.** The staging is **three rungs**:

1. **prompt** (no training);
2. **external small model** — a **small LLM reading the raw text context** (the same context the big model sees). No feature-encoding, no activations, no open model required → portable across *any* big model incl. closed APIs; cheap (big model frozen), interpretable, fast to iterate. **Discriminative-not-generative is what keeps it small** (verify ≫ generate). Doubles as the reward model.
3. **compiled into weights** — control tokens / RL; the judgment becomes part of the base model.

So fixes #1/#2 become: **train a small external relevance/usefulness model on grounded judge labels** — not a hand-edited `metrics.yaml`, and not (yet) base-model fine-tuning.

### 4. The fleet lens: small discriminative models as injectors

**Injection test:** *if a change-to-a-stream can be performed as an injection by a separately-trained small model, it's a small-model candidate* — an intermediate rung AND a generator of big-model training data. Dividing line for the whole architecture: **gate / judge / monitor / select / classify → small models that inject; generate → the big model.**

Candidates:
- **plan-memory:** relevance/usefulness scorer · recall selector (sifter) · recall gate · `RecallUsed` labeler (the judge) · cue maintainer.
- **plan-mind:** **monitor / impasse-trigger** (the #1 missing primitive — a small model injecting an interrupt) · confidence / feeling-of-knowing gate (the metacog thresholds, #5) · speculation verifier (C11 accept/reject) · emission admissibility judge (#4) · value-of-computation selector · receptivity detector (preempt-vs-defer) · **Supervisor condition-classifiers** (review passed? stuck? done?) · redaction/secret detector (sensorium) · escalation-necessity (AttentionRequest).

**Why supervision especially benefits.** Base models are **not trained to supervise themselves** today (the MGV "Generate-Verify omits the monitor" finding; #1) — so a small supervisory model is not only cheaper, it supplies a capability the big model currently *lacks*. Gating Supervisor recommendations and self-monitoring are therefore high-value now, and the fleet's grounded-good supervisory injections become the data to teach the big model self-supervision later (rung 3).

The gate also **changes the supervisor's job**: with a learned filter in front, a Supervisor can be **liberal** — optimize for *recall* (surface anything potentially useful) and delegate *precision* to the gate. Because the gate is small, it can be **learned per-project** — affordable where per-project base-model fine-tuning is not — capturing what feedback actually pays off *in this codebase/context*, grounded in this project's outcomes (fits the per-project Mind; relates to `plan-radar`'s project scoping). Cold-start: a new project falls back to a global/default gate (or prompt-only) and specializes as its outcome signal accrues. This is also **seed-variety + grounded-selection**: the liberal supervisor is a high-variety generator, the gate the grounded selector, and together they produce richer (feedback, outcome) training data.

This is **§4.7's specialized-models architecture instantiated on the discriminative roles** (the tight interface = the injection): a fleet of small discriminative models around one big generative model — the intermediate rung at scale (cheap, parallel, commodity-hardware: the C7/C10 dollar-cost win), and a training-data flywheel for the base model. Generation roles (impl, review prose, recall synthesis, branch sub-derivations) stay big.

### 5. Carve-outs (C — correctly fixed)

Human-facing decay (radar's age-penalty) stays hand-tuned for now (hard to learn well, low stakes). Typed contracts, invariants, safety rails, idempotency keys, and the held-`y`-fixed firewall stay fixed.

### Net effect on the ranked fixes

#1 (radar) and #2 (plan-memory) keep their *shape* (a learned loop) but change *signal* (grounded, not attention) and *locus* (a small external text model / reward model, not `metrics.yaml` or base-model fine-tune). The rest of the gates/judges/monitors/selectors join them as small-injector candidates — the implementation path is "a fleet of separately-trained small discriminative models," not "build each into the big model."
