# REVIEW CYCLE 6 — Literature Review (User-Modeling)

Reviewer: fresh Claude session, blind to prior cycles until the final
appendix. Date: 2026-05-15. Artifact: `pm/docs/literature-review-user-model.md`
at ~11,221 words after the +1,664-word two-pass addition (NLA + Patchscopes
+ Activation Oracles, then Deas & McKeown + Persona Vectors + Wang).

Findings count: **9 substantive + 7 phrasing/structure = 16 total.**
Two of the substantive findings are previously-undiscovered prior art the
citation-graph walk turned up. They are why this cycle is *not* nits-only.

---

## BLOCK 1 — Substance

### S1. [MAJOR — missed prior art] Cabello / Neplenbroek / Bisazza / Fernández, "Reading Between the Prompts: How Stereotypes Shape LLM's Implicit Personalization" (EMNLP 2025 Main, arXiv:2505.16467) is closer to Phase 1 than any paper currently cited.

What they do (verified from arxiv abstract + ACL Anthology page):

- Train **linear probes on LLM latent representations** to predict the
  user's demographic group across 4 attributes × 13 demographic groups × 3
  LLMs.
- Probe the user representation **at four conversational checkpoints**
  (round 1, 3, 6, and after a self-introduction).
- Find that latent user representations are **driven by stereotypical
  cues** even when explicit demographic information is absent, and that
  this implicit personalization **lowers response quality for minority-
  group users**.
- Show that **intervening on the model's internal user representation via
  the trained linear probe** mitigates the bias — i.e., they steer the
  probed direction.

This is materially closer to the plan's Phase 1 + Phase 3 than either
Choi/Transluce or Deas & McKeown:

- Same DV shape as the plan: **work quality**, not hedging quality (Deas
  & McKeown) and not just decodability (Choi).
- Same probe-then-steer methodology: linear probe → intervention → effect
  on output quality. This is the Phase 1+Phase 3 pipeline.
- Same variable family: user-representation latents, not Assistant-persona
  latents (Persona Vectors) and not impressions-of-prompts (Deas &
  McKeown).
- **Multi-turn conversational dynamics**, which the plan does not
  currently address but probably should.

Critical implication: the lit review's narrative that "Choi/Transluce is
the closest variable-side peer" and "Deas & McKeown is the closest
SCM-linear-probe peer" leaves a hole exactly where Neplenbroek et al. sit
— linear probes on **user representations**, with **response-quality DV**,
plus **a steering intervention**. The plan's residual contributions list
(SCM structure, contrast-pair extraction, multi-axis fractional factorial,
Phase 3 interchange-intervention bar, Phase 4 closed-model transfer)
narrows further but does not collapse. The honest framing is that the
plan's novelty against Neplenbroek is:

1. The **construct** (peer-ness, SCM-anchored) rather than demographic
   group identity.
2. **Multi-axis fractional-factorial** input design vs Neplenbroek's
   stereotype-cue manipulation.
3. **Interchange-intervention-grade causal evidence** (their intervention
   is linear-probe steering, which is sufficiency-grade per the plan's
   own §4 evidence-bar argument).
4. **Closed-model transfer** (Phase 4) — Neplenbroek is open-only.

But contribution (b) on the existing list — "task performance on standard
gradable benchmarks as the DV rather than hedging quality" — needs to be
rewritten, because Neplenbroek already uses *response quality*. Now the
narrowing is "task performance on gradable benchmarks rather than minority-
group response-quality degradation" — narrower and more honest.

**This is the most substantive finding of the cycle.** The artifact's
post-walk claim of having mapped the SCM-linear-probe-on-users
neighborhood is incomplete.

### S2. [MAJOR — missed prior art] Vennemeyer et al., "Sycophancy Is Not One Thing: Causal Separation of Sycophantic Behaviors in LLMs" (arXiv:2509.21305, Sept 2025) directly bears on Phase 3 and on the §5 framing.

What they do:

- Decompose sycophancy into **sycophantic agreement** vs **sycophantic
  praise** vs **genuine agreement**.
- Show via difference-in-means directions that all three are encoded
  along **distinct linear directions in latent space**.
- Demonstrate **causal separability** — each behavior can be independently
  amplified or suppressed.
- Consistent across model families and scales.

Why this matters:

1. **§5 currently treats sycophancy as a single LLM-behavior direction**
   ("an independently-extracted sycophancy direction (Rimsky 2024 / CAA)")
   that Phase 3 will use as the disambiguator from peer-ness. Vennemeyer
   demonstrates this is wrong: sycophancy is **at least three separable
   directions**. Phase 3's disambiguation against "the" sycophancy
   direction must be against the *family* of sycophancy directions.
2. **The Phase 3 design now needs an explicit choice**: which of
   Vennemeyer's three (agreement / praise / genuine agreement) is the
   relevant disambiguator? Probably sycophantic-agreement-without-truth,
   since the plan's predicted outcome is "peer-ness improves
   benchmark performance" and the alternative explanation is "framing
   makes the model agree more, which inflates the score on benchmarks
   where agreement is rewarded." But this needs to be stated.
3. **Methodologically extremely close to Phase 3.** Difference-in-means
   directions = contrast-pair extraction. Causal separability across
   model families = the Phase 3 + multi-model template. Vennemeyer is
   arguably a closer methodological peer to Phase 3's *execution* than
   Arditi 2024 (which is single-direction).

The prior citation-graph walk (CITATION_GRAPH_WALK_USERMODEL.md line 184)
noted Vennemeyer but characterized it as "Useful for §5's claim that
sycophancy isn't a single thing, but the plan's §5 already treats
sycophancy as a mechanism" and did **not** propose adding it. That
characterization is wrong: the plan's §5 treats sycophancy as a
*mechanism* but as a **single** direction. Vennemeyer falsifies that.

### S3. [MODERATE — missed prior art] Jaipersaud, Krueger, Lubana, "How Do LLMs Persuade? Linear Probes Can Uncover Persuasion Dynamics in Multi-Turn Conversations" (arXiv:2508.05625, Aug 2025).

Trains linear probes on three distinct aspects: **persuasion success,
persuadee personality, persuasion strategy**. Persuadee personality is
the closest published cousin to peer-ness on the *variable* axis — both
are LLM-internal representations of attributes of the human counterpart,
trained as linear probes. The differences from the plan are real (their
DV is persuasion success, the manipulation is conversational persuasion
not framing axes) but smaller than the differences from Deas & McKeown,
which the lit review treats as the closest SCM-linear-probe peer.

Belongs in §4 alongside Choi and Deas & McKeown.

### S4. [SUBSTANTIVE] Deas & McKeown placement framing is *almost* honest but contains one piece of special-pleading.

The lit review's enumeration of the plan's residual contributions against
Deas & McKeown is at §7 line 241:

> "(a) contrast-pair extraction methodology over a multi-axis
> fractional-factorial design, (b) task performance on standard gradable
> benchmarks as the DV rather than hedging quality, (c) Phase 3 causal-
> mediation testing via interchange intervention, and (d) Phase 4
> closed-model transfer."

Three of these are honest, one is special-pleading:

- **(a) contrast-pair extraction**: this is honest *only because* Deas &
  McKeown's abstract does not specify their probe-extraction technique.
  Both papers explicitly describe their work as "fitting linear probes."
  The plan claims novelty on "contrast-pair / RepE-style extraction" but
  contrast-pair-as-vector is *the dominant linear-probe extraction
  recipe in this literature* — claiming it as a residual contribution
  is overclaiming unless the lit review verifies Deas & McKeown used a
  non-contrast-pair technique. Without checking the full Deas & McKeown
  paper text, the lit review should soften (a) to "contrast-pair
  extraction across a multi-axis fractional-factorial design" — the
  fractional-factorial part is the genuine novelty, not the contrast-pair
  shape itself.

- **(b) task performance DV**: honest *but partially redundant with
  Neplenbroek* (S1 above). After incorporating Neplenbroek the
  narrowing becomes "gradable benchmark DV rather than
  minority-group-response-quality" — defensible but smaller.

- **(c) interchange-intervention bar in Phase 3**: honest. Neither Deas
  & McKeown nor Neplenbroek clear that bar (both are at probe + steer,
  which is sufficiency-grade).

- **(d) Phase 4 closed-model transfer**: honest. No published peer
  does this.

The lit review is broadly honest but should pare (a) down.

### S5. [SUBSTANTIVE] NLA framing — "Phase 4 is informal NLA" — is approximately right but overstates the equivalence.

The plan's Phase 4 readout (§6 line 193) is:

> "the plan reads the peer-ness vector by asking the model to verbalize
> its judgment of the user via a meta-prompt, calibrated against the
> Phase 1 open-model probe on matched inputs."

The Anthropic NLA stack (Fraser-Taliente et al. 2026):

- **Activation verbalizer + activation reconstructor**, jointly RL-trained
  on **reconstruction loss under KL penalty**.
- The reconstructor is what enforces faithfulness — descriptions that
  don't reconstruct get bad gradients.
- Operates **on the activations themselves**, not on the model's
  surface-level natural-language self-report.

Phase 4 has **none of these structural features**:

- No reconstructor. Faithfulness is enforced indirectly via calibration
  against the Phase 1 probe — a much weaker constraint.
- No RL training loop.
- Operates on the **closed model's output tokens**, not on its activations
  (which are inaccessible by definition).

Calling Phase 4 "informal NLA" suggests the methodology is a relaxed
version of the same thing. It is closer to **meta-prompted introspection
calibrated post-hoc against an open-model probe**. NLA is a different
operation that happens to share the goal (activations → natural language).
The honest framing is:

- Phase 4 sits in the **Binder 2024 / Lindsey 2025 lineage** of
  introspection-via-self-report.
- NLA is the **mechanically rigorous version**, but its rigor depends on
  having activation access — which Phase 4 by definition does not have.
- The lit review should say: "Phase 4 *shares the goal* of NLA — both
  produce natural-language descriptions of internal states — but
  operates under the closed-model constraint that NLA does not, and
  therefore inherits introspection-grade rather than reconstruction-grade
  faithfulness guarantees."

Currently the framing reads as if Phase 4 could "adopt the Anthropic NLA
stack directly when externally available for the relevant models" (line
193). For closed models — which is *what Phase 4 is for* — the NLA stack
fundamentally cannot apply. NLA requires activation access. The
"externally available" caveat is doing more work than the writing
acknowledges.

### S6. [SUBSTANTIVE] Persona Vectors is asked to do three things and one of the three is shaky.

Persona Vectors appears in:

1. **§4 table + §4 prose**: "methodological cousin; categorically
   different variable (model-own traits, not user-perception)." ✓ Honest.
2. **§5**: cited as confirming sycophancy is a model-side trait, not a
   user-perception trait. ✓ Honest, well-anchored.
3. **§7 "LLM-own-behavior features" bullet**, merged with Templeton
   2024: "Templeton 2024 — sycophantic praise, inner conflict; Chen et
   al. 2025 — Persona Vectors for evil, sycophancy, hallucination
   propensity." ✓ Honest *but* the bullet should add Vennemeyer (per
   S2): Vennemeyer extends Persona Vectors' sycophancy direction into
   three separable directions.

The three placements are individually honest. The risk is **density**:
Persona Vectors now appears in §4 (twice, table + prose), §5, and §7. A
single citation appearing four times in a 11k-word lit review is
acceptable; appearing four times in service of the same load-bearing
point (sycophancy is model-side) starts to feel like the citation is being
asked to carry too much. The §7 mention is the most cuttable — the §5
treatment already establishes the model-side framing; the §7 bullet
could collapse to "(Templeton 2024, Persona Vectors / Chen et al. 2025,
Vennemeyer et al. 2025)" without the descriptive elaboration.

### S7. [SUBSTANTIVE] Wang et al. placement is honest but understates one finding.

The lit review states Wang's finding correctly:

- Simple opinion statements induce sycophancy. ✓
- Expertise framing has negligible effect on sycophancy. ✓
- "User authority not encoded internally." ✓

The "constraining-but-not-refuting" framing is honest: Wang's DV is
sycophancy, the plan's DV is task performance, so a null result on the
sycophancy DV does not bind the plan.

However, Wang's "user authority fails to influence behavior because
models do not encode it internally" finding is in tension with the plan's
working hypothesis more than the lit review acknowledges. Wang
specifically tests whether the model encodes the user-authority
dimension and finds it does not. The plan's Phase 1 will probe for
intellectual competence (an authority-adjacent dimension) and predicts
it *is* encoded. Wang's null on authority is the **closest published
piece of evidence against Phase 1**.

The lit review says (line 175): "Wang's 'user authority not encoded
internally' finding is on the input-framing-to-behavior pathway; the
plan probes for the encoded user-modeling representation directly via
Phase 1's probes, which is a different evidential bar."

This is partly right but elides that Wang **also probes internally** —
the "not encoded internally" claim is itself a probe finding, not an
input-framing finding. The honest statement is: "Wang reports a *null*
on internal encoding of user authority specifically; Phase 1 will test
whether the SCM-anchored intellectual-competence dimension (broader and
more concrete than 'authority') yields a positive result. A Phase 1 null
on intellectual competence would replicate Wang; a positive result would
extend the literature."

This makes Wang a **partial pre-replication target**, not just background.

### S8. [SUBSTANTIVE] Cross-cluster prior-art from the regression literature review.

The instruction was specifically to check whether the AuditBench /
NIST CAISI / Petri 2.0 line cited in the sibling regression-loop lit
review bears on §6 (introspection) and §5 (sycophancy).

Confirmed from search: AuditBench (alignment.anthropic.com, March 2026)
explicitly documents a "tool-to-agent gap" — tools that are effective in
isolation don't reliably translate into investigator-agent effectiveness.

This **does** bear on Phase 4. Phase 4 essentially treats the closed
model as its own auditor — asking it to verbalize its judgment of the
user. The tool-to-agent gap is the warning that **a probe that works in
isolation (Phase 1's open-model probe on a Llama 3.1) does not
necessarily translate when used by a closed model's self-report
machinery**. AuditBench specifically tested whether investigator agents
using auxiliary tools (like Petri) outperform investigator agents with
no tools — and found surprising failures.

§6 should add at least a one-sentence cross-link: "Anthropic's
AuditBench (alignment.anthropic.com, 2026) reports a tool-to-agent gap
in alignment auditing — useful tools in isolation don't automatically
help an investigator-agent form the right hypothesis. Phase 4's design
inherits this risk: the open-model probe (Phase 1) may not translate
cleanly when wrapped in a closed-model self-report meta-prompt."

This is a Block-1-substantive finding because it changes how Phase 4
should be evaluated (calibration is necessary but not sufficient against
the tool-to-agent gap).

### S9. [MINOR — substantive] Patchscopes is introduced (§4 line 159) as the unifying framework, but the relationship of Patchscopes to NLA is mis-stated.

The lit review says NLA *and* Activation Oracles *and* LatentQA *and*
Choi/Transluce all "build on the Patchscopes framework." This is
historically/methodologically loose:

- **LatentQA (Pan 2024, Dec 2024)** — yes, Patchscopes-adjacent.
- **Choi/Transluce (Nov 2025)** — Patchscopes-adjacent (decoders), but
  Transluce's own framing emphasizes narrow-trained decoders, not the
  cross-prompt patching that defines Patchscopes.
- **Activation Oracles (Dec 2025)** — trains a supervised model to
  answer activation-queries; the activations are passed as an input
  modality. This is **not** structurally the same as Patchscopes' patch-
  into-different-prompt operation. It is a fine-tuning approach.
- **NLA (May 2026)** — uses an activation verbalizer + reconstructor
  trained with RL on reconstruction loss. Again, **not** the Patchscopes
  patch-into-prompt operation. Different mechanism.

Calling all four "domain-specific instantiations" of Patchscopes
over-attributes lineage. The honest framing is that all four share the
*goal* of producing natural-language descriptions of activations, but
they use **mechanically distinct approaches**: patching (Patchscopes),
prompted decoders (LatentQA, Transluce), supervised activation-as-input
(Activation Oracles), reconstruction-loop autoencoding (NLA). The lit
review should rephrase: "These applications share Patchscopes' broad
goal — turning activations into natural language — but use
mechanically distinct approaches."

---

## BLOCK 2 — Structure and Readability

### B1. [STRUCTURE] §4 prose ordering after the table doesn't match the table.

The §4 table at lines 114–129 lists papers chronologically:
Subramani 2022 → Turner 2023 → Zou 2023 → Park 2024 → Tigges 2023 →
Rimsky 2024 → Marks 2023 → Hernandez 2024 → Li 2023 → Arditi 2024 → Pan
2024 → Choi 2025 → Chen 2025 (Persona Vectors) → Deas & McKeown 2025.

The prose says "the prose below discusses these in order Zou →
Subramani → Turner → Park → Tigges → Rimsky → Marks → Hernandez → Li →
Arditi → Pan → Choi (Zou first because it is the seed reference)" (line
131). The prose does **not** mention Persona Vectors or Deas & McKeown
in this list — but they're discussed (Deas & McKeown at line 155, Chen
et al. at line 157). The list at line 131 is now stale after the
additions. Update to include the new entries.

### B2. [STRUCTURE] §4 final seminal-anchors paragraph (line 163) has grown into a 6-line dump.

The seminal-anchors paragraph at end of §4 now lists: Subramani, Turner,
Zou, Rimsky, Park, Tigges, Choi, Deas & McKeown, Chen, Li, Marks,
Arditi, Pan, Ghandeharioun, Karvonen, Fraser-Taliente, Hernandez —
seventeen named works, organized under five "closest peer on X" buckets.
This is now functionally the table again, rephrased. Either delete it
(the table covers the same ground) or compress to two sentences.

### B3. [BOLTED-ON] The NLA + Activation Oracles paragraph (line 161) sits as a separate paragraph after the Choi/Transluce paragraph and does not link clearly to the Persona Vectors paragraph above it. The flow goes: Persona Vectors (model-own traits) → Patchscopes/Activation Oracles/NLA (verbalizer methodology). The pivot is uncued. Add a transition: "Beyond the model-own-traits vs user-perception distinction, a parallel methodological line works on the **representation-to-natural-language axis** rather than the variable axis…"

### B4. [STRUCTURE] §7 line 240–242 enumerates the "clean five-axis neighborhood" but adds Deas & McKeown as a sub-bullet making it six axes. Re-label "five-axis" → "neighborhood" (the precise count is no longer load-bearing).

### B5. [REPETITION] Persona Vectors appears in:
- §4 table (line 128)
- §4 prose (line 157)
- §4 seminal-anchors recap (line 163)
- §5 paragraph (line 173)
- §7 bullet (line 242)
- §7 seminal anchors recap (line 265)

Six mentions for one citation is high. Conservative: drop §4 seminal-
anchors recap mention and §7 seminal-anchors recap mention; keep §4
table, §4 prose, §5, §7 bullet.

### B6. [STRUCTURE] The §7 "Predicted-outcome cells" table (line 254) now needs an additional row for the Vennemeyer-extended sycophancy case (per S2): "Steering finds an LLM-behavior direction" should split into "...sycophantic-agreement direction" vs "...sycophantic-praise direction" vs "...genuine-agreement direction."

### B7. [NIT] §1 line 47: "Deas & McKeown is discussed in detail in §4 and §7; the relevance here is that SCM is now an empirically used framework on the LLM-probing side of the literature, not only on the social-psychology side." This sentence is throat-clearing. Cut to: "Deas & McKeown, discussed in §4 and §7, establish SCM as an empirically-used framework on the LLM-probing side."

---

## BLOCK 3 — Non-Expert Accessibility (LOAD-BEARING)

### A1. [LOAD-BEARING] "Reconstructor enforces faithfulness" — the NLA description at line 161 says: "an *activation reconstructor* maps the description back to an activation, and the two are jointly RL-trained on reconstruction loss under a KL penalty. The reconstruction loop is what enforces faithfulness — descriptions that don't enable accurate reconstruction get bad gradients."

For the non-expert reader: "RL-trained," "reconstruction loss," "KL
penalty," "bad gradients" are four unglossed concepts in three lines.
Replace with:

> "an *activation reconstructor* tries to take the natural-language
> description and rebuild the original activation pattern from it. The
> two halves — describer and rebuilder — are trained together: the
> describer is rewarded when its description lets the rebuilder
> reconstruct the original accurately. If the describer makes up a
> plausible-but-untrue description, the rebuilder fails, and the
> describer's reward goes down. This loop is what keeps the description
> honest."

This trades technical accuracy ("RL," "KL penalty") for accessibility
("rewarded," "reward goes down"). The non-expert reader who *needs*
this concept gets it; the expert reader gets a pointer to the paper
where the technical version lives.

### A2. [LOAD-BEARING] "Sufficiency-grade" / "interchange-intervention-grade" / "behavioral-grade" evidence-grade vocabulary at §4 line 110 and re-used in §7. This is now load-bearing across the whole document but is glossed only by example. Add a one-paragraph table or sidebar at §4 making the hierarchy explicit:

> **Evidence grades used throughout this review (from weakest to
> strongest):**
> - **Behavioral**: input changes, output changes. Doesn't tell you what
>   inside the model carried the effect.
> - **Sufficiency / steering**: a direction in the model's scratchpad is
>   *enough* to push behavior toward a target. Doesn't prove the model
>   actually uses that direction; only that it *could*.
> - **Interchange-intervention / causal mediation**: copy that direction
>   from one model run into another at the right place, and the output
>   changes the way you predicted. This is the strongest standard short
>   of opening the model up and inspecting the wires.

### A3. [LOAD-BEARING] §4 line 99 glossary of "residual stream" as "the network's running internal scratchpad" is good. But "scratchpad" then carries §4–§7 *load-bearingly* without being re-anchored. By §7, a reader who skipped §4 will not know what "scratchpad" means. Either move the gloss earlier (into the §1 glossary block on lines 28–35) or re-gloss on first use in §7.

### A4. [LOAD-BEARING] §6 line 193 phrase "this design is informal NLA" — the non-expert reader does not know what NLA is *at first encounter in §6*. NLA was introduced in §4 line 161, but a reader landing on §6 from the table of contents will be lost. Spell out: "Anthropic's published Natural Language Autoencoder (NLA) stack — described in §4 — is the formal version of the same operation."

### A5. [NIT] §5 line 175 — Wang quote "user authority fails to influence behavior because models do not encode it internally" is jargon-dense for a non-expert. Gloss inline: "models do not encode it internally (their hidden representations don't contain a stable signal for 'how authoritative this user is')."

### A6. [STYLE] §1 line 35 "NeurIPS *Spotlight*, where it appears in references, is the top ~5% of accepted papers" — the "where it appears in references" is fillerific. Cut to: "NeurIPS *Spotlight* designates the top ~5% of accepted papers — a signal of high reviewer enthusiasm."

---

## BLOCK 4 — Prose Craft

### P1. [HEDGE] §1 line 51: "The 'humans calibrate effort by perceived peer-ness' claim is treated here as a working hypothesis the plan's result will indirectly test — not as established empirical ground truth about humans." The phrase "indirectly test" is hedge-on-a-hedge. Rewrite: "The 'humans calibrate effort by perceived peer-ness' claim is itself a hypothesis. The plan's result tests it indirectly: if LLMs trained on human text show the effect, the human pattern is more likely real."

### P2. [DEADWOOD] §4 line 107: "the strong test for 'is the network using this internal state to produce this answer?'" — the question-in-quotes is set up by previous prose. Cut to "the strong test for whether the network is using this internal state."

### P3. [WORD-CHOICE] §4 line 110: "behavioral-grade correlation evidence (probe + benchmark, correlated)" — "correlated" already in "correlation evidence." Cut redundancy: "behavioral-grade evidence (probe + benchmark)."

### P4. [REGISTER] §5 line 181: "Canonical real-world demonstration that production frontier models are one bad reward-tuning decision away from collapsing into agreement-with-anything." This is a punchy line in a section that's otherwise formal-academic register. Either embrace the punch elsewhere or pull back here. Suggested pull-back: "A real-world demonstration that production frontier models can shift dramatically toward agreement under reward-tuning."

### P5. [HEDGE] §6 line 197: "Suggestive evidence, not peer-reviewed." The "suggestive evidence" hedge then "not peer-reviewed" hedge is double. Pick one: "Not peer-reviewed; treat as suggestive."

### P6. [BLOAT] §7 line 248: "the plan's target is engineering improvement on standard benchmarks, not statistical confidence in a particular construct — that's what makes exploration appropriate here." The em-dash + "that's what makes" is roundabout. Rewrite: "The plan targets engineering improvement on standard benchmarks, not statistical confidence in a particular construct — which is why exploration is appropriate."

### P7. [REPETITION] "categorically different variable" appears at §4 line 128, line 157, and §7 line 242. This is the same disambiguation repeated three times. Compress: stake the claim once in §4, refer back in §5/§7 by phrase ("see §4 on the model-side-vs-user-side distinction").

---

## Citation-graph walk

**Per the updated step-5 methodology.** Seeds listed before searching:

1. Andreas 2022 (arXiv:2212.01681)
2. Park, Choe, Veitch 2024 (arXiv:2311.03658)
3. Tigges, Hollinsworth, Geiger, Nanda 2023 (arXiv:2310.15154)
4. Templeton 2024 (transformer-circuits.pub)
5. Choi/Transluce 2025 (transluce.org/user-modeling)
6. Fraser-Taliente 2026 (transformer-circuits.pub/2026/nla/)
7. Patchscopes / Ghandeharioun 2024 (arXiv:2401.06102)
8. Fiske/Cuddy SCM 2002
9. Goodwin/Piazza/Rozin 2014
10. Deas & McKeown 2025 (arXiv:2510.08915)
11. Persona Vectors / Chen et al. 2025 (arXiv:2507.21509)
12. Wang et al. 2025 (arXiv:2508.02087)

**Search tactics:**

- Google Scholar with "last 12 months" date filter for forward walks.
- Direct searches on alignment.anthropic.com, transformer-circuits.pub,
  transluce.org, ACL Anthology, OpenReview.
- Plain-topic queries (not arxiv:topic) per methodology 5d.
- Per-seed time budget: 5–10 minutes; total walk: ~45 minutes.

**Coverage by seed:**

| Seed | Forward walk | Backward walk | New finds |
|---|---|---|---|
| Andreas 2022 | sampled, citation network well-established | — | none new in last 6 months |
| Park 2024 | citation network includes Vennemeyer (S2) and Jaipersaud (S3) | — | **2 (see S2, S3)** |
| Tigges 2023 | sampled forward, mostly within-cluster | — | none new |
| Templeton 2024 | catalog work continues but no closer-peer additions | — | none new |
| Choi/Transluce 2025 | too recent for substantial forward walk | found via Transluce direct page (covered in prior walk) | none new beyond prior walk |
| NLA 2026 | only 1 week old; tracking forward is premature | reconstructor lineage well-cited | none new |
| Patchscopes 2024 | Activation Oracles, LatentQA, Transluce all cite | — | none new |
| Fiske/Cuddy 2002 | huge citation network — sampled SCM-on-LLM intersection | — | Cabello/Neplenbroek 2025 (S1) |
| Goodwin 2014 | citation network smaller, sampled person-perception-dimensions debate | — | none new |
| Deas & McKeown 2025 | very recent, citations sparse | references include SCM lineage | none new |
| Persona Vectors 2025 | cited by Vennemeyer (already found via Park walk) | — | none new beyond S2 |
| Wang 2025 | cited by Vennemeyer | — | none new beyond S2 |

**Net new finds from the walk:**

1. **Cabello/Neplenbroek/Bisazza/Fernández 2025** — "Reading Between the
   Prompts" (EMNLP 2025 Main, arXiv:2505.16467). MAJOR. See S1.
2. **Vennemeyer/Duong/Zhan/Jiang 2025** — "Sycophancy Is Not One Thing"
   (arXiv:2509.21305). MAJOR. See S2.
3. **Jaipersaud/Krueger/Lubana 2025** — "How Do LLMs Persuade?" (arXiv:
   2508.05625). MODERATE. See S3.

**Anthropic lab pages spot-check** (per methodology 5d):

- alignment.anthropic.com: AuditBench (March 2026) — useful for §6 cross-
  link, see S8.
- transformer-circuits.pub: NLA (May 2026) already cited; no newer.
- transluce.org: Choi/Transluce already cited; no newer user-modeling
  posts since.

**Beyond-arXiv check**: AuditBench's "tool-to-agent gap" framing
(alignment.anthropic.com/2026/auditbench/) is not yet in either lit
review and bears on Phase 4 of this one. See S8.

**Coverage gap acknowledgment**: I did not walk Subramani 2022, Turner
2023, Marks 2023, Arditi 2024, or Hernandez 2024 forward — these are
older and the within-cluster citation network has been mapped in prior
cycles. Recent additions to those subtrees would mainly be within-cluster
follow-ups (more steering on more variables) and don't open new peer-
ness-adjacent paths.

---

## Convergence assessment

**Prior cycle (5) predicted Cycle 6 would produce only phrasing nits.**

That prediction is **wrong**. Cycle 6 produced:

- **2 MAJOR substantive findings** (S1, S2) — both are previously
  uncited prior art that directly bears on Phase 1, Phase 3, or §5.
- **1 MODERATE substantive finding** (S3) — additional prior art.
- **5 SUBSTANTIVE findings** (S4–S8) — framing honesty and one missing
  cross-cluster link.
- **1 MINOR substantive finding** (S9) — Patchscopes-lineage mis-
  attribution.
- **7 phrasing/structure findings** (B1–B7, A1–A6, P1–P7) — these are
  nits.

**Verdict: convergence does NOT hold.** The +1,664-word two-pass
addition (NLA + Patchscopes + Activation Oracles, then Deas & McKeown +
Persona Vectors + Wang) materially expanded the prior-art surface, and
walking the citations of those new additions surfaced **three new peers
the prior walk missed** — including one (Cabello/Neplenbroek) that is
the closest published peer to Phase 1 + Phase 3 *combined*.

This is a structural feature of citation-graph walks after substantive
additions, not a process failure of Cycle 5. Adding Deas & McKeown
opened the Fiske/Cuddy-citation-network door wider; walking that door
yielded Cabello/Neplenbroek. Adding Persona Vectors opened the
Park-citation-network door; walking that door yielded Vennemeyer.

**Recommendation: one more substantive cycle (7), then close.**
Specifically:

1. Incorporate Cabello/Neplenbroek into §4 and §7 (and re-narrate the
   plan's residual contributions against this fuller peer set).
2. Incorporate Vennemeyer into §5 and §7 (and split the Phase 3
   sycophancy-disambiguation against the three sycophancy directions).
3. Add Jaipersaud as an §4 cousin citation.
4. Soften the Phase-4-is-NLA framing per S5.
5. Pare contribution (a) in §7's Deas & McKeown residual list per S4.
6. Add the AuditBench cross-link in §6 per S8.
7. Re-clean Patchscopes-lineage attribution per S9.
8. Cycle 7's reviewer should re-walk Cabello, Vennemeyer, Jaipersaud
   forward to check for *their* citing papers. If that walk surfaces no
   new prior art, *that* is the convergence signal — not the count of
   nits.

---

## What prior cycles missed (cross-reference appendix)

I read REVIEW_CYCLE_1–5_USERMODEL.md, the REVIEW_RESPONSE files, and
CITATION_GRAPH_WALK_USERMODEL.md *after* drafting the above. Observations:

- **CITATION_GRAPH_WALK_USERMODEL.md line 184 noted Vennemeyer** but
  declined to recommend its inclusion, on the (incorrect) grounds that
  "the plan's §5 already treats sycophancy as a mechanism." This is the
  kind of close-but-wrong characterization the methodology warns about:
  treating "sycophancy is a mechanism alternative" as equivalent to
  "sycophancy is decomposable into separable mechanisms." Vennemeyer's
  contribution is the *decomposition* — and that decomposition propagates
  into Phase 3's design (S2 above). Prior cycles missed this.

- **Cabello/Neplenbroek 2025 is not mentioned anywhere in prior cycles
  or in the citation-graph walk record.** This is a clean miss. The
  paper appeared on arXiv in May 2025 and was published at EMNLP 2025
  Main; either Scholar's date-filter for the prior walk was set too
  narrowly or the walk did not run a Fiske/Cuddy → SCM-on-LLM
  intersection search at all.

- **Jaipersaud 2025 is also not mentioned anywhere.** Same kind of miss
  — within the Park 2024 forward citation network but apparently not
  reached by the prior walk.

- **AuditBench cross-link from the sibling regression lit review** was
  not raised in any prior user-model cycle. Cross-artifact cross-linking
  is a methodological gap; the methodology mentions running the loop
  per-artifact but does not say "check the sibling artifact's
  citations." The instruction in the present cycle's prompt is the
  first time this was tested, and it surfaced a real link (S8).

- **Cycle 5's claim that "the loop has *not quite* converged at Cycle
  5 — one real bite remains — but it is one substantive finding away
  from convergence"** turned out to be optimistic, and not because of
  the prediction itself — Cycle 5 was right that the *Cycle 5 state*
  was nearly converged — but because the response and the two
  subsequent prior-art additions (Deas & McKeown / Persona Vectors /
  Wang) opened a new citation-graph subtree that hadn't been walked.
  Convergence is path-dependent on citation density; adding citations
  creates more directions to walk.

- **No prior cycle distinguished "Patchscopes-as-unifying-framework"
  from "Patchscopes-as-direct-ancestor".** S9 is genuinely new.

- **The "residual contribution" framing against Deas & McKeown (line
  241) was added in response to Cycle 5 or earlier and not
  pressure-tested in any prior cycle.** S4 is new.
