# Citation Graph Walk — `literature-review-user-model.md`

Walk date: 2026-05-15. Methodology: per
`pm/docs/adversarial-review/METHODOLOGY.md` step 5. Time-budgeted at
~5–10 minutes per seed, supplemented by direct lab-page sweeps of
transformer-circuits.pub, alignment.anthropic.com, transluce.org, and
DeepMind / arXiv recent listings.

## Seeds searched

| # | Seed | Cited-by range walked | Direction(s) |
|---|---|---|---|
| 1 | Andreas 2022 (arXiv:2212.01681) | 2024-Q4 → 2026-Q2 | forward |
| 2 | Park, Choe, Veitch 2024 (arXiv:2311.03658) | 2025-Q1 → 2026-Q2 | forward |
| 3 | Tigges 2023 (arXiv:2310.15154) | 2025-Q1 → 2026-Q2 | forward |
| 4 | Templeton 2024 (Scaling Monosemanticity) | 2024-Q3 → 2026-Q2 | forward |
| 5 | Choi 2025 / Transluce (user-modeling) | publication → 2026-Q2 | forward (sparse — too new for heavy citation) |
| 6 | Pan 2024 / LatentQA (arXiv:2412.08686) | 2025-Q1 → 2026-Q2 | forward |
| 7 | Fraser-Taliente 2026 / NLA (transformer-circuits.pub/2026/nla/) | publication → 2026-05-15 | forward (too new — 1 week) |
| 8 | Patchscopes / Ghandeharioun 2024 (arXiv:2401.06102) | 2025-Q1 → 2026-Q2 | forward |
| 9 | Fiske, Cuddy, Glick, Xu 2002 (SCM) | 2025-Q1 → 2026-Q2 (LLM-context only) | forward |
| 10 | Goodwin, Piazza, Rozin 2014 | 2025-Q1 → 2026-Q2 (LLM-context only) | forward |
| 11 | Perez 2022 + Sharma 2023 (sycophancy pair) | 2025-Q1 → 2026-Q2 | forward |

Lab-page sweeps performed: transformer-circuits.pub (full
2025-Q4 + 2026 listing), alignment.anthropic.com (full 2025-Q4 + 2026
listing), transluce.org (full listing).

## Misses worth adding

The walk found three high-confidence additions and one
secondary-but-important one. All four are verifiable on arXiv or the
publisher's own page; none are speculative.

### 1. Chen, Arditi, Sleight, Evans, Lindsey 2025 — **"Persona Vectors: Monitoring and Controlling Character Traits in Language Models"**

- arXiv:2507.21509, July 2025 (revised September 2025). Anthropic +
  collaborators (UT Austin, UC Berkeley, Constellation, Truthful AI).
- https://arxiv.org/abs/2507.21509 ; companion blog at
  https://www.anthropic.com/research/persona-vectors.
- **What it does**: extracts linear directions in activation space
  corresponding to character traits (evil, sycophancy, hallucination,
  politeness, apathy, humor, optimism) using contrast pairs from
  natural-language trait descriptions. Demonstrates monitoring,
  inference-time steering, preventative steering during finetuning,
  and training-data flagging.
- **Relevance to the plan**: this is a *direct* methodological peer
  for Phase 1's contrast-pair-per-sub-dimension recipe and Phase 3's
  steering test. The plan's six sub-dimensions (technical competence,
  effort, reasonableness, honesty/sincerity, good-faith, mutual
  respect) are structurally identical to persona-vector traits. The
  plan's novelty narrows from "persona-vector methodology applied to a
  new variable" to "persona-vector methodology applied to a
  *structured user-modeling* variable grounded in SCM" — which is
  defensible but must be named explicitly.
- **Where it lands**: §4 (activation steering and control vectors) —
  immediately after Zou 2023 / RepE and Rimsky 2024 / CAA in the
  prose; in the §4 table; in the §7 novelty-against-neighbors
  discussion. Should also be named in §5 (sycophancy) because the
  Chen et al. paper explicitly extracts a sycophancy direction. The
  current §5 reference to Rimsky/CAA is still right; this is a 2025
  Anthropic extension.

### 2. Deas & McKeown 2025 — **"Artificial Impressions: Evaluating Large Language Model Behavior Through the Lens of Trait Impressions"**

- EMNLP 2025 main, arXiv:2510.08915, October 2025.
- https://arxiv.org/abs/2510.08915 ;
  https://aclanthology.org/2025.emnlp-main.981/
- **What it does**: applies the Stereotype Content Model (warmth +
  competence) to LLMs as a probing framework. Trains linear probes on
  hidden layers of Llama-3.1-8B, Llama-3.2-1B, and OLMo-2-7B; finds
  that *while explicit responses are inconsistent, internal hidden-
  layer representations consistently encode warmth- and competence-
  style trait impressions*. Crucially, the paper reports that these
  detected impressions **correlate with response quality and hedging
  language** — exactly the DV→IV correlation the plan's Phase 2
  proposes to measure.
- **Relevance to the plan**: this is the closest published peer to
  Phase 1+2 combined. It uses SCM as the framework, uses linear
  probes, finds the representation, and ties it to response behavior.
  The plan's Phase 1+2 contribution narrows from "first to apply SCM
  + linear probing to LLM user-modeling and correlate with output
  quality" to "first to apply SCM + linear probing + multi-axis
  fractional factorial + causal-mediation Phase 3 to *peer-ness as a
  meta-dimensional construct*, with response quality measured on
  gradable benchmarks rather than hedging-rate proxies." This is the
  most load-bearing addition.
- **Where it lands**: §1 (the SCM-anchor section — Deas & McKeown
  belong adjacent to the Fiske/Cuddy citation as the LLM-side
  application); §2 (framing effects on performance — Deas & McKeown
  measure response-quality changes); §4 (linear probing on LLMs); §7
  (variable-space neighborhood — closest peer on the variable). The
  plan's claimed novelty needs to acknowledge this paper directly.

### 3. Wang, Li, Yang, Zhang, Wang 2025 — **"When Truth Is Overridden: Uncovering the Internal Origins of Sycophancy in Large Language Models"**

- arXiv:2508.02087, August 2025 (revised November 2025).
- https://arxiv.org/abs/2508.02087
- **What it does**: traces sycophancy through model layers, finds a
  two-phase mechanism (late-layer output shift + deeper
  representational divergence). **Critical for the plan**: explicitly
  tests whether *user-expertise framing* drives sycophancy. Reports
  that "simple opinion statements reliably induce sycophancy, whereas
  user expertise framing has a negligible impact." Also finds
  first-person ("I believe...") triggers stronger sycophancy than
  third-person.
- **Relevance to the plan**: Wang et al.'s finding cuts both ways for
  the plan's hypothesis. It supports the plan's distinction between
  *user-judgment-as-perception* and *sycophancy-as-behavior* (different
  drivers at different layers). But it also constrains the plan's
  *intellectual peer-ness* construction: if "user expertise framing has
  negligible impact" on at least the sycophancy outcome, the plan needs
  to address whether intellectual peer-ness manipulations will actually
  move the IV. The plan can resolve this by noting that Wang et al.
  measured a different DV (sycophancy on opinion questions) and IV
  (binary expertise prompt) than the plan's gradable-benchmark
  performance under a Resolution-V multi-axis design — but the
  reference must be acknowledged.
- **Where it lands**: §5 (sycophancy) — as a methodological extension
  of Sharma 2023, and as the empirical bound on the
  "expertise-framing-doesn't-help" null. Also §2 in the framing-
  effects discussion.

### 4. Sofroniew et al. 2026 — **"Emotion Concepts and their Function in a Large Language Model"** (currently cited as `transformer-circuits.pub 2026` with no author block)

- transformer-circuits.pub, April 2026, https://transformer-circuits.pub/2026/emotions/
- The artifact already cites this work but with the bare publisher
  attribution. The walk surfaced an author name (Sofroniew et al.) on
  the transformer-circuits index page. **Action**: update the
  reference to name the authors rather than the venue alone; verify
  by re-fetching the post itself before publication.
- This is a citation-formatting fix, not a content miss.

## Adjacent work considered but not added

- **Shekkizhar, Cosentino, Earle 2026, "Beyond the Assistant Turn"
  (arXiv:2604.02315)**: measures *interaction awareness* by having
  models generate user turns. The variable being measured is
  the model's behavioral capacity to role-play the user, not the
  model's internal *judgment* of the user. Not on the plan's
  causal arrow.
- **Choi et al. 2025, "Agent-to-Agent Theory of Mind"
  (arXiv:2506.22957)**: tests whether LLMs can identify peer *models*
  in dialogue. Not user-modeling proper; the dialogue partner here is
  another LLM, not a human user. Adjacent but separate construct.
- **Gilg, Beckmann, Paleka, Butlin 2026, "Probing Persona-Dependent
  Preferences" (arXiv:2605.13339)**: trains probes for the model's
  *own* preferences across personas. Different IV (model self-state)
  and different question (do personas share preferences?). One step
  away.
- **Moskvoretskii et al. 2026, "Tracing Persona Vectors Through LLM
  Pretraining" (arXiv:2605.13329)**: when persona vectors form during
  pretraining. Developmental, not about user-modeling at inference.
- **Chen, Wang, Xie, Feng, Liu 2026, "A Systematic Analysis of the
  Impact of Persona Steering on LLM Capabilities" (arXiv:2604.11048)**:
  measures cognitive-task impact of imposing personas on the *model*,
  not impact of model's perception of *user* personas. The flip side
  of the plan. Worth noting in §2 as a relative if there's room but
  not a load-bearing miss; could be cut.
- **Allbert, Wiles, Grankovsky 2024, "Identifying and Manipulating
  Personality Traits in LLMs Through Activation Engineering"
  (arXiv:2412.10427)**: same flip side — personality of the model.
  Not user-modeling.
- **Yang et al. 2024/2025, "Exploring the Personality Traits of LLMs
  through Latent Features Steering" (arXiv:2410.10863)**: ditto.
- **Tak et al. 2025 character emotions** (already cited in §7).
- **Sun & Wang 2025, "Be Friendly, Not Friends" (arXiv:2502.10844)**:
  HCI study of *user perception of model sycophancy* — different
  direction (user→model). Worth a footnote in §5 if §5 expands but
  not load-bearing.
- **Tak/Banayeeanzade/Bolourani/Kian/Jia/Gratch 2025
  (arXiv:2502.05489)** is the EmotionPrompt-mechanism follow-up the
  search surfaced; the artifact already cites this as "Tak 2025
  character emotions" (§7). Confirmed correctly placed.
- **Anthropic, "The Persona Selection Model" (alignment.anthropic.com,
  February 2026)**: blog post framing Claude as a character; mostly
  conceptual. Adjacent to §1's Shanahan reference but doesn't add new
  empirical content the plan needs. Could be cited in §1 as a
  contemporary practitioner anchor for the role-play framing if the
  reviewer wants more 2026 coverage; not load-bearing.
- **Anthropic, "Stress-testing model specs..."
  (alignment.anthropic.com, October 2025)**: cross-lab character
  comparison via specs. Not user-modeling.
- **Vennemeyer et al. 2025, "Sycophancy Is Not One Thing"
  (arXiv:2509.21305)**: causally separates three sycophancy sub-
  behaviors. Useful for §5's claim that sycophancy isn't a single
  thing, but the plan's §5 already treats sycophancy as a mechanism
  alternative; this paper sharpens that point but isn't load-bearing.
  Optional addition.
- **DeepMind Gemma Scope 2 (December 2025)**: interpretability
  infrastructure release, not a probe-of-user-state paper. Not
  relevant to add.
- **Transluce "Predictive Concept Decoders" (December 2025)**:
  end-to-end interpretability assistants. Methodology adjacent to
  LatentQA but not specifically user-modeling. Could be a §4 footnote
  but isn't required.
- **Karvonen et al. 2025 / Activation Oracles** is already cited; the
  walk confirms placement.

## Negative-result findings (positive convergence signals)

- **Andreas 2022 forward walk**: no 2025–2026 paper extends
  "Language Models as Agent Models" *specifically* to addressee-
  modeling in a way the plan should cite. The theoretical anchor
  stands alone in that role.
- **Patchscopes / Ghandeharioun forward walk**: no missed
  user-modeling-specific instantiation beyond what the plan already
  cites (LatentQA, Choi/Transluce, Activation Oracles, NLA).
- **Fiske/Cuddy SCM (2002) forward walk into LLM context**: Deas &
  McKeown 2025 (added above), Nicolas & Caliskan 2024 (SCM taxonomy
  of stereotype content — bias-side, not user-perception-side; not
  added), and a handful of bias-audit papers. None of the remaining
  hits move the plan.
- **Goodwin 2014 forward walk into LLM context**: no LLM-side
  follow-up. The plan's morality-as-third-dimension framing is
  not contested by recent LLM work.
- **Perez 2022 + Sharma 2023 forward walks**: the only load-bearing
  miss is Wang et al. 2025 (added above). The sycophancy literature
  has expanded (Vennemeyer 2025, multiple HCI papers) but nothing
  else moves the plan's argument.
- **Choi/Transluce forward walk**: too recent (Nov 2025) for a
  meaningful citing-paper count; no follow-ups yet.
- **NLA (May 7 2026) forward walk**: 8 days old at walk time; no
  meaningful citation graph yet.
- **transformer-circuits.pub Q4 2025 + 2026 sweep**: posts inventoried.
  HeadVis (May 2026), Emotion Concepts (April 2026 — already cited),
  Activation Oracles cross-post (December 2025 — already cited),
  Lindsey introspection (October 2025 — already cited), Manifolds
  counting task (October 2025 — not relevant), Circuits Updates Nov
  2025 (not relevant). No misses.
- **alignment.anthropic.com Q4 2025 + 2026 sweep**: the Anthropic
  Alignment Science posts inventoried (October 2025 through May 2026).
  Most are alignment-auditing or safety-training papers without
  direct user-modeling relevance. Persona Selection Model (Feb 2026)
  and Stress-testing Model Specs (Oct 2025) noted as adjacent but
  not added. Introspection Adapters (April 2026) is methodologically
  adjacent to §6 but doesn't change the plan; optional addition.
- **transluce.org full listing**: three posts total
  (Predictive Concept Decoders, Monitoring SWE-bench Agents,
  Surfacing Pathological Behaviors). None new to user-modeling
  beyond Choi 2025 which is already cited.

## Coverage assessment

Confidence that the walk has surfaced the load-bearing misses is
**high for the user-modeling-and-probing core** and **moderate for
the framing-effects-on-task-performance periphery**.

The walk's strongest finding is that the literature review failed to
cite **Deas & McKeown 2025 (Artificial Impressions)** and **Chen et
al. 2025 (Persona Vectors)** — both of which are direct methodological
or variable-side peers that earlier cycles should have caught. Deas
& McKeown in particular is load-bearing because it (a) uses SCM as
the framework, (b) trains linear probes on LLM hidden layers, and
(c) shows that the detected impressions correlate with response
behavior — three of the four moves the plan claims as its
contribution. Chen et al. is load-bearing because the persona-vector
recipe is the published exemplar of the trait-direction methodology
the plan's Phase 1 instantiates.

A Cycle N+1 reviewer could potentially still find:

- Workshop papers from NeurIPS 2025 (December) that index slowly on
  Scholar — particularly any SoLaR / interpretability-workshop work
  on user-state probing.
- Anthropic Alignment Science posts from mid-May 2026 published
  after this walk (the loop's recurring failure mode — NLA was missed
  for 8 days, this walk covers through 2026-05-15).
- Very recent (April-May 2026) ICLR / ICML 2026 main-conference
  acceptances if the camera-ready versions surface findings the
  arXiv preprints don't preview.

The walk did *not* find evidence that the plan's core novelty claim
collapses under prior art. The plan's "first to probe peer-ness as a
two-meta-axis SCM-grounded structure with sub-dimensions, multi-axis
fractional factorial, and Phase-3 causal mediation across gradable
benchmarks" claim survives the additions above — but the claim must
explicitly cite and differentiate from Deas & McKeown 2025 and Chen
et al. 2025 to remain defensible.

## Tan et al. resolution

Earlier cycles flagged "Tan et al. 2024 personality traits" as an
unverified placeholder eventually dropped. The walk's Scholar /
arXiv search returned no paper matching "Tan 2024 personality probing
LLM activations." The closest candidates were:

- **Yang et al. 2024, "Exploring the Personality Traits of LLMs
  through Latent Features Steering" (arXiv:2410.10863)** — first
  author Shu Yang, not Tan.
- **Allbert et al. 2024 (arXiv:2412.10427)** — first author Rumi
  Allbert, not Tan.
- **Tak et al. 2025 (arXiv:2502.05489)** — first author Ala N. Tak.
  Surface-level similar to "Tan" and is about emotion inference, not
  personality traits. Already cited in the artifact as "Tak 2025
  character emotions" in §7.

**Resolution**: "Tan et al. 2024 personality traits" was almost
certainly a phantom — either a misremembering of Tak 2025 (similar
surname, similar domain, off by one letter and one year) or a
hallucinated reference. There is no real Tan 2024 personality-probing
paper that earlier cycles failed to find. Dropping it was the right
call.

The personality-probing literature *does* exist (Yang 2024, Allbert
2024, Chen 2025 Persona Vectors, the AAAI AIES "Localizing Persona
Representations" paper, "Tracing Persona Vectors Through Pretraining"
2026). None of these is a "Tan" paper. The plan's prior decision to
drop the placeholder is vindicated; the gap should be filled instead
by **Chen et al. 2025 Persona Vectors** as the canonical
trait-direction reference (see "Misses worth adding" above).
